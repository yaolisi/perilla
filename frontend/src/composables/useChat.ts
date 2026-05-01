/**
 * useChat Composable
 * 管理聊天状态和逻辑
 */

import { ref, computed, watch, type Ref } from 'vue'
import { 
  chatCompletion, 
  streamChatCompletion, 
  type Message,
  type ChatStreamChunk,
  type ChatStreamResponse,
  type ChatStreamJsonlChunk,
  type ChatStreamMarkdownChunk,
  type ChatRoutingMetadata,
  type ChatRequest,
  type ChatStreamFormat,
  type RAGConfig,
  streamChunkDeltaText,
  setSessionId
} from '@/services/api'
import { useParameters } from './useParameters'
import { useChatStreamPreferences } from './useChatStreamPreferences'
import { getFriendlyErrorMessage } from '@/utils/errorHints'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  loading?: boolean
  modelName?: string
  /** 与后端同步的 message meta（如 RAG） */
  meta?: Record<string, unknown> | null
  /** 智能路由解析元数据（仅 assistant 流式/非流式完成时由 API 返回） */
  routing?: ChatRoutingMetadata | null
  params?: {
    temperature: number
    top_p: number
    max_tokens: number
    system_prompt?: string
  }
  attachments?: Array<{
    type: 'image'
    url: string
    file?: File
  }>
}

/**
 * Convert a File object to a base64 data URL
 * This is needed for sending images through the JSON-based chat API
 */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

interface UseChatOptions {
  model?: string
  temperature?: number
  top_p?: number
  max_tokens?: number
}

const STORAGE_MODEL_KEY = 'ai_platform_selected_model'
const STORAGE_KB_KEY = 'ai_platform_selected_kb'
const STORAGE_RAG_MULTI_HOP_KEY = 'ai_platform_rag_multi_hop'

// module-singleton state
const globalMessages = ref<ChatMessage[]>([])
const globalLoading = ref(false)
const globalError = ref<string | null>(null)
const globalSessionId = ref<string | null>(null)
const globalModel = ref(localStorage.getItem(STORAGE_MODEL_KEY) || 'auto')
const globalKnowledgeBaseId = ref<string | null>(localStorage.getItem(STORAGE_KB_KEY) || null)
const globalRagMultiHop = ref(localStorage.getItem(STORAGE_RAG_MULTI_HOP_KEY) === '1')

// 持久化模型选择
watch(globalModel, (val) => {
  localStorage.setItem(STORAGE_MODEL_KEY, val)
  // 同步对应的聊天参数
  const params = useParameters()
  params.syncFromModel(val)
})

// 持久化知识库选择
watch(globalKnowledgeBaseId, (val) => {
  if (val) {
    localStorage.setItem(STORAGE_KB_KEY, val)
  } else {
    localStorage.removeItem(STORAGE_KB_KEY)
  }
})

watch(globalRagMultiHop, (val) => {
  if (val) {
    localStorage.setItem(STORAGE_RAG_MULTI_HOP_KEY, '1')
  } else {
    localStorage.removeItem(STORAGE_RAG_MULTI_HOP_KEY)
  }
})

export interface SendMessageOptions {
  stream?: boolean
  signal?: AbortSignal
  /** 覆盖「设置 → 运行时」中的流式 GZip 偏好 */
  streamGzip?: boolean
  /** 覆盖「设置 → 运行时」中的流式输出格式 */
  streamFormat?: ChatStreamFormat
}

function applyStreamTransportPrefs(req: ChatRequest, opts: SendMessageOptions, defaults: { gzip: boolean; format: ChatStreamFormat }) {
  const gz = opts.streamGzip !== undefined ? opts.streamGzip : defaults.gzip
  const fmt = opts.streamFormat !== undefined ? opts.streamFormat : defaults.format
  if (gz) {
    req.stream_gzip = true
  }
  if (fmt && fmt !== 'openai') {
    req.stream_format = fmt
  }
}

export function useChat(options: UseChatOptions = {}) {
  const messages = globalMessages
  const loading = globalLoading
  const error = globalError
  const sessionId = globalSessionId
  const model = globalModel
  const knowledgeBaseId = globalKnowledgeBaseId
  const ragMultiHop = globalRagMultiHop

  function buildRagOptions(): RAGConfig | undefined {
    if (!knowledgeBaseId.value) return undefined
    const rag: RAGConfig = {
      knowledge_base_id: knowledgeBaseId.value,
      top_k: 5,
      score_threshold: 1.2,
      retrieval_mode: 'hybrid',
    }
    if (ragMultiHop.value) {
      rag.multi_hop_enabled = true
    }
    return rag
  }

  const params = useParameters()
  const { streamGzip, streamFormat } = useChatStreamPreferences()

  // 初始化模型 (仅在全局模型为默认 'auto' 且 options 提供了具体模型时)
  if (options.model && model.value === 'auto') {
    model.value = options.model
  } else if (model.value !== 'auto') {
    // 如果已有活动模型，初始化时加载一次参数
    params.syncFromModel(model.value)
  }
  const temperature = params.temperature
  const top_p = params.top_p
  const max_tokens = params.maxTokens

  const messageCount = computed(() => messages.value.length)
  const isLoading = computed(() => loading.value)

  /**
   * 生成唯一 ID
   */
  function generateId(): string {
    return `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
  }

  /**
   * 添加消息到历史
   */
  function addMessage(
    role: 'user' | 'assistant', 
    content: string, 
    modelName?: string, 
    msgParams?: ChatMessage['params'],
    attachments?: ChatMessage['attachments'],
    routing?: ChatMessage['routing'],
    meta?: Record<string, unknown> | null,
  ): ChatMessage {
    const message: ChatMessage = {
      id: generateId(),
      role,
      content,
      timestamp: Date.now(),
      modelName,
      loading: false,
      params: msgParams,
      attachments,
      routing: routing ?? undefined,
      meta: meta ?? undefined,
    }
    messages.value.push(message)
    return message
  }

  /**
   * 更新消息状态
   */
  function updateMessageLoading(id: string, loadingStatus: boolean): void {
    const message = messages.value.find((m) => m.id === id)
    if (message) {
      message.loading = loadingStatus
    }
  }

  /**
   * 更新消息内容
   */
  function updateMessageContent(id: string, content: string): void {
    const message = messages.value.find((m) => m.id === id)
    if (message) {
      message.content = content
    }
  }

  /**
   * 更新消息命中的实际模型
   */
  function updateMessageModelName(id: string, modelName: string): void {
    const message = messages.value.find((m) => m.id === id)
    if (message) {
      message.modelName = modelName
    }
  }

  function updateMessageRouting(id: string, routing: ChatRoutingMetadata): void {
    const message = messages.value.find((m) => m.id === id)
    if (message) {
      message.routing = routing
    }
  }

  /** 流式最后一帧携带与非流式相同的 metadata（含 rag / multi_hop），写入 assistant 消息以便无需刷新即可溯源 */
  function applyStreamCompletionMetadata(id: string, chunk: ChatStreamChunk): void {
    let raw: Record<string, unknown> | undefined
    if (chunk.object === 'chat.completion.chunk') {
      const c = chunk as ChatStreamResponse
      if (c.choices?.[0]?.finish_reason === 'stop' && c.metadata && typeof c.metadata === 'object') {
        raw = c.metadata as Record<string, unknown>
      }
    } else if (chunk.object === 'perilla.stream.jsonl') {
      const j = chunk as ChatStreamJsonlChunk
      if (j.d === true && j.metadata && typeof j.metadata === 'object') {
        raw = j.metadata as Record<string, unknown>
      }
    } else if (chunk.object === 'perilla.stream.md') {
      const m = chunk as ChatStreamMarkdownChunk
      if (m.d === true && m.metadata && typeof m.metadata === 'object') {
        raw = m.metadata as Record<string, unknown>
      }
    }
    if (!raw) return
    const message = messages.value.find((m) => m.id === id)
    if (!message) return
    message.meta = { ...(message.meta || {}), ...raw }
    const rm = raw.resolved_model
    const rv = raw.resolved_via
    if (typeof rm === 'string' && typeof rv === 'string') {
      message.routing = { resolved_model: rm, resolved_via: rv }
    }
  }

  /**
   * 清除消息历史
   */
  function clearMessages(): void {
    messages.value = []
    sessionId.value = null
    setSessionId(null) // 清除全局缓存
  }

  function setMessages(next: ChatMessage[]): void {
    messages.value = Array.isArray(next) ? next : []
  }

  /**
   * 获取 API 消息格式
   * 过滤掉：
   * 1. 正在加载的消息（避免发送中间状态）
   * 2. 内容为空的消息
   * 3. 错误或占位符消息（根据业务逻辑判断）
   */
  function getApiMessages(): Message[] {
    return messages.value
      .filter((m) => !m.loading && (m.content.trim() !== '' || (m.attachments && m.attachments.length > 0)))
      .map((m) => {
        const baseMessage: Message = {
          role: m.role as 'user' | 'assistant',
          content: m.content,
        }
        
        // 如果是用户消息且有附件，转换为多模态格式
        if (m.role === 'user' && m.attachments && m.attachments.length > 0) {
          const imageAttachments = m.attachments.filter(att => att.type === 'image')
          if (imageAttachments.length > 0) {
            // 构建多模态内容数组
            // Note: even if text content is empty, we still include it
            const contentArray = [
              { type: 'text' as const, text: m.content || '' },
              ...imageAttachments.map(att => ({
                type: 'image_url' as const,
                image_url: { url: att.url }
              }))
            ]
            
            return {
              ...baseMessage,
              content: contentArray
            }
          }
        }
        
        return baseMessage
      })
  }

  /**
   * 发送消息（自动选择流式或非流式）
   * 流式时默认使用「设置 → 运行时」中的 GZip/格式；可用 `options.streamGzip` / `options.streamFormat` 单次覆盖。
   */
  async function sendMessage(
    userContent: string, 
    options: SendMessageOptions = {},
    attachments?: ChatMessage['attachments']
  ): Promise<void> {
    const { stream: useStream = false, signal } = options
    const streamTransportDefaults = { gzip: streamGzip.value, format: streamFormat.value }
    error.value = null

    // Convert file attachments to base64 data URLs for API transmission
    let processedAttachments: ChatMessage['attachments'] | undefined
    if (attachments && attachments.length > 0) {
      processedAttachments = await Promise.all(
        attachments.map(async (att) => {
          if (att.file) {
            // Convert File to base64 data URL
            const base64Url = await fileToBase64(att.file)
            return { ...att, url: base64Url }
          }
          return att
        })
      )
    }

    // 添加用户消息
    addMessage('user', userContent, undefined, undefined, processedAttachments)

    loading.value = true

    try {
      const apiMessages = getApiMessages()
      const currentParams = {
        temperature: temperature.value,
        top_p: top_p.value,
        max_tokens: Number(max_tokens.value),
        system_prompt: params.useSystemPrompt.value ? params.systemPrompt.value : undefined,
      }

      if (useStream) {
        // 流式模式
        const assistantMsg = addMessage('assistant', '', model.value, currentParams)
        assistantMsg.loading = true

        try {
          const streamBody: ChatRequest = {
            model: model.value,
            messages: apiMessages,
            temperature: temperature.value,
            top_p: top_p.value,
            max_tokens: Number(max_tokens.value),
            system_prompt: params.useSystemPrompt.value ? params.systemPrompt.value : undefined,
            max_history_messages: params.maxHistoryMessages.value,
            rag: buildRagOptions(),
            signal,
          }
          applyStreamTransportPrefs(streamBody, options, streamTransportDefaults)
          await streamChatCompletion(
            streamBody,
            (chunk: ChatStreamChunk) => {
              if (chunk.object === 'perilla.stream.meta') return
              applyStreamCompletionMetadata(assistantMsg.id, chunk)
              const c = chunk as ChatStreamResponse
              if (c.model) {
                updateMessageModelName(assistantMsg.id, c.model)
              }
              const delta = streamChunkDeltaText(chunk)
              if (delta) {
                updateMessageContent(assistantMsg.id, assistantMsg.content + delta)
              }
            },
            () => {
              // 流完成
              updateMessageLoading(assistantMsg.id, false)
            },
            (err) => {
              error.value = err.message
              updateMessageLoading(assistantMsg.id, false)
            }
          )
        } finally {
          // 最终保险：确保 loading 状态被关闭
          updateMessageLoading(assistantMsg.id, false)
        }
      } else {
        // 非流式模式
        const response = await chatCompletion({
          model: model.value,
          messages: apiMessages,
          temperature: currentParams.temperature,
          top_p: currentParams.top_p,
          max_tokens: currentParams.max_tokens,
          system_prompt: currentParams.system_prompt,
          max_history_messages: params.maxHistoryMessages.value,
          rag: buildRagOptions(),
          signal,
        })

        if (response.choices?.[0]?.message) {
          // 处理可能的多模态响应内容
          const content = typeof response.choices[0].message.content === 'string' 
            ? response.choices[0].message.content 
            : ''
          const apiMeta = response.metadata as ChatRoutingMetadata | undefined
          const routingOnly =
            apiMeta?.resolved_model && apiMeta?.resolved_via
              ? {
                  resolved_model: apiMeta.resolved_model,
                  resolved_via: apiMeta.resolved_via,
                }
              : undefined
          const metaFull =
            response.metadata && typeof response.metadata === 'object'
              ? { ...(response.metadata as Record<string, unknown>) }
              : undefined
          addMessage(
            'assistant',
            content,
            response.model || model.value,
            currentParams,
            undefined,
            routingOnly,
            metaFull,
          )
        }
      }
    } catch (err) {
      error.value = getFriendlyErrorMessage(err instanceof Error ? err.message : String(err))
    } finally {
      loading.value = false
    }
  }

  /**
   * 重新生成最后一条 AI 回复
   */
  async function regenerate(options: SendMessageOptions = {}): Promise<void> {
    if (loading.value || messages.value.length === 0) return

    // 找到最后一条用户消息
    let lastUserMsgIdx = -1
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const msg = messages.value[i]
      if (msg && msg.role === 'user') {
        lastUserMsgIdx = i
        break
      }
    }

    if (lastUserMsgIdx === -1) return

    const lastMsg = messages.value[lastUserMsgIdx]
    if (!lastMsg) return
    const userContent = lastMsg.content
    
    // 移除最后一条用户消息之后的所有消息
    messages.value = messages.value.slice(0, lastUserMsgIdx)
    
    // 重新发送
    await sendMessage(userContent, options)
  }

  /**
   * 编辑并重新发送
   */
  async function editAndResubmit(messageId: string, newContent: string, options: SendMessageOptions = {}): Promise<void> {
    if (loading.value) return

    const idx = messages.value.findIndex(m => m.id === messageId)
    if (idx === -1) return

    // 移除该消息及其之后的所有消息
    messages.value = messages.value.slice(0, idx)
    
    // 重新发送新内容
    await sendMessage(newContent, options)
  }

  return {
    messages: messages as Ref<ChatMessage[]>,
    loading,
    error,
    model,
    knowledgeBaseId,
    ragMultiHop,
    temperature,
    top_p,
    max_tokens,
    messageCount,
    isLoading,
    addMessage,
    updateMessageContent,
    updateMessageModelName,
    clearMessages,
    setMessages,
    sendMessage,
    regenerate,
    editAndResubmit,
    /** 与「设置 → 运行时」流式选项同步，可在聊天区做快捷绑定 */
    streamGzip,
    streamFormat,
  }
}
