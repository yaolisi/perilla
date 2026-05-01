/** RAG 表单校验失败时在页面上的滚动与高亮（Create/Edit Agent）。 */

const PULSE_CLASSES = ['ring-2', 'ring-cyan-500/60', 'shadow-lg', 'shadow-cyan-500/15'] as const

/**
 * 平滑滚动到元素并短暂青色 ring 高亮。
 * @param el 为 null 时不做任何事（例如未选知识库时尚无 RAG 卡片）
 */
export function pulseHighlightElement(el: HTMLElement | null | undefined, durationMs = 2800): void {
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add(...PULSE_CLASSES)
  window.setTimeout(() => {
    el.classList.remove(...PULSE_CLASSES)
  }, durationMs)
}

/** 服务端返回这些 code 时，将焦点拉回知识库 / RAG 配置区 */
export const AGENT_MUTATION_KB_RAG_HIGHLIGHT_CODES: ReadonlySet<string> = new Set([
  'agent_invalid_model_params_rag',
  'agent_kb_store_unavailable',
  'agent_knowledge_base_not_found',
])

/** RAG 参数错误：优先高亮 RAG 参数卡片，否则高亮知识库整块区域 */
export function pulseAgentRagValidationTarget(
  ragSettingsCard: HTMLElement | null | undefined,
  kbSection: HTMLElement | null | undefined,
): void {
  pulseHighlightElement(ragSettingsCard ?? kbSection)
}

/**
 * 知识库不可用 / 未找到：优先高亮知识库区域；RAG 参数字段错误：保持原 RAG 卡片优先逻辑。
 */
export function pulseAgentKnowledgeOrRagOnMutationError(
  code: string | undefined,
  ragSettingsCard: HTMLElement | null | undefined,
  kbSection: HTMLElement | null | undefined,
): void {
  if (!code || !AGENT_MUTATION_KB_RAG_HIGHLIGHT_CODES.has(code)) {
    return
  }
  if (code === 'agent_kb_store_unavailable' || code === 'agent_knowledge_base_not_found') {
    pulseHighlightElement(kbSection ?? ragSettingsCard)
    return
  }
  pulseAgentRagValidationTarget(ragSettingsCard, kbSection)
}
