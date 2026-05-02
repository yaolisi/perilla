import { ref } from 'vue'
import { getSystemConfig, updateSystemConfig, type SystemConfig } from '@/services/api'

function parseBool(value: unknown, defaultVal: boolean): boolean {
  if (value === undefined || value === null) return defaultVal
  if (value === true || value === 1 || value === 'true') return true
  if (value === false || value === 0 || value === 'false') return false
  return defaultVal
}

function parseFloat01(value: unknown, defaultVal: number): number {
  if (value === undefined || value === null || value === '') return defaultVal
  const n = Number(value)
  if (Number.isNaN(n)) return defaultVal
  return Math.min(1, Math.max(0, n))
}

type SmartRoutingPreviewItem = {
  alias: string
  strategy: string
  summary: string
}

type SmartRoutingSnapshotItem = {
  id: string
  createdAt: number
  text: string
}

type SmartRoutingSnapshotDiff = {
  addedAliases: string[]
  removedAliases: string[]
  changedAliases: string[]
  changedDetails: Array<{
    alias: string
    lines: Array<{
      current: string
      snapshot: string
      currentChanged: boolean
      snapshotChanged: boolean
    }>
  }>
}

type SmartRoutingSnapshotDiffView = {
  addedAliases: string[]
  removedAliases: string[]
  changedAliases: string[]
  changedDetails: Array<{
    alias: string
    lines: Array<{
      current: string
      snapshot: string
      currentChanged: boolean
      snapshotChanged: boolean
    }>
  }>
}

const SMART_ROUTING_SNAPSHOT_STORAGE_KEY = 'runtime.smartRouting.snapshots.v1'
const MAX_SMART_ROUTING_SNAPSHOTS = 8

export function useRuntimeSettings() {
  const autoUnloadLocalModelOnSwitch = ref(false)
  const runtimeAutoReleaseEnabled = ref(true)
  const runtimeMaxCachedLocalRuntimes = ref(1)
  const runtimeMaxCachedLocalLlmRuntimes = ref(1)
  const runtimeMaxCachedLocalVlmRuntimes = ref(1)
  const runtimeMaxCachedLocalImageGenerationRuntimes = ref(1)
  const runtimeReleaseIdleTtlSeconds = ref(300)
  const runtimeReleaseMinIntervalSeconds = ref(5)
  /** Torch VLM HF 流式：generate 线程 join 超时（秒），与后端 torchStreamThreadJoinTimeoutSec 对齐 */
  const torchStreamThreadJoinTimeoutSec = ref(600)
  /** 异步 chunk 队列深度；0 为不限制 */
  const torchStreamChunkQueueMax = ref(0)
  /** Chat SSE 墙钟上限（秒）；0 为不限制，与后端 chatStreamWallClockMaxSeconds 对齐 */
  const chatStreamWallClockMaxSeconds = ref(0)
  /** 断点续传开启时：断连即取消上游；与 chatStreamResumeCancelUpstreamOnDisconnect 对齐 */
  const chatStreamResumeCancelUpstreamOnDisconnect = ref(false)
  /** /api/events 是否要求 graph_instance 已登记 workflow_executions；与 eventsStrictWorkflowBinding 对齐 */
  const eventsStrictWorkflowBinding = ref(false)
  /** /api/events 是否要求 API Key + 平台 admin；与 eventsApiRequireAuthenticated 对齐 */
  const eventsApiRequireAuthenticated = ref(false)
  const inferenceSmartRoutingEnabled = ref(true)
  const inferenceSmartRoutingPoliciesJson = ref('')
  /** 技能语义发现：混合分中标签匹配权重（0–1），语义为 1 - 该值 */
  const skillDiscoveryTagMatchWeight = ref(0.3)
  /** 余弦相似度下限，0 表示不筛 */
  const skillDiscoveryMinSemanticSimilarity = ref(0)
  /** 混合分下限，0 表示不筛 */
  const skillDiscoveryMinHybridScore = ref(0)
  /** PlanBasedExecutor / parallel_group 批内与 parallel_calls 的全局并发上限 */
  const agentPlanMaxParallelSteps = ref(4)
  /** 0 或空：未在控制台覆盖，用后端 .env；>0 为单步默认超时（秒） */
  const agentStepDefaultTimeoutSeconds = ref(0)
  const agentStepDefaultMaxRetries = ref(0)
  const agentStepDefaultRetryIntervalSeconds = ref(1)
  const workflowSchedulerMaxConcurrency = ref(10)
  const workflowGovernanceHealthyThreshold = ref(0.1)
  const workflowGovernanceWarningThreshold = ref(0.3)
  const inferencePriorityPanelHighSloCriticalRate = ref(0.95)
  const inferencePriorityPanelHighSloWarningRate = ref(0.99)
  const inferencePriorityPanelPreemptionCooldownBusyThreshold = ref(10)
  const DEFAULT_SMART_ROUTING_POLICIES_TEMPLATE = `{
  "reasoning-model": {
    "strategy": "blue_green",
    "stable": "reasoning-v1",
    "candidate": "reasoning-v2",
    "candidate_percent": 10
  },
  "chat-fast": {
    "strategy": "least_loaded",
    "candidates": ["chat-fast-a", "chat-fast-b"]
  },
  "chat-balanced": {
    "strategy": "weighted",
    "candidates": [
      { "target": "chat-a", "weight": 70 },
      { "target": "chat-b", "weight": 30 }
    ]
  }
}`

  const config = ref<SystemConfig | null>(null)
  /** GET /api/system/config 返回的 MCP 服务端推送→事件总线生效值；旧后端则为 null（不展示只读条） */
  const mcpHttpEmitEffective = ref<boolean | null>(null)
  const apiRateLimitEnabledEffective = ref<boolean>(true)
  const apiRateLimitRequestsEffective = ref<number>(0)
  const apiRateLimitWindowSecondsEffective = ref<number>(60)
  const apiRateLimitMiddlewareActiveEffective = ref<boolean>(false)
  const apiRateLimitRedisBackendConfiguredEffective = ref<boolean>(false)
  const apiRateLimitUserMaxConcurrentEffective = ref<number>(5)
  const apiRateLimitTrustXForwardedForEffective = ref<boolean>(true)
  /** 进程环境（Helm/.env）：/api/events* 专用限流；0 表示与全局限流共用计数键 */
  const apiRateLimitEventsRequestsEffective = ref<number>(0)
  const apiRateLimitEventsPathPrefixEffective = ref<string>('/api/events')
  const apiRateLimitEventsDedicatedBucketActiveEffective = ref<boolean>(false)
  const isSaving = ref(false)
  const saveSuccess = ref(false)
  const saveError = ref('')
  const smartRoutingJsonError = ref('')
  const smartRoutingBuilderError = ref('')
  const smartRoutingBuilderInfo = ref('')
  const smartRoutingPreview = ref<SmartRoutingPreviewItem[]>([])
  const smartRoutingPreviewError = ref('')
  const smartRoutingSnapshots = ref<SmartRoutingSnapshotItem[]>([])
  const smartRoutingSnapshotDiff = ref<SmartRoutingSnapshotDiff | null>(null)
  const smartRoutingSnapshotDiffError = ref('')
  const smartRoutingSnapshotDiffAliasFilter = ref('')
  const isEditing = ref(false)

  const loadConfig = async () => {
    try {
      const c = await getSystemConfig()
      config.value = c
      {
        const eff = c.mcp_http_emit_server_push_events_effective
        mcpHttpEmitEffective.value = typeof eff === 'boolean' ? eff : null
      }
      {
        const on = c.api_rate_limit_enabled_effective
        apiRateLimitEnabledEffective.value = typeof on === 'boolean' ? on : true
      }
      {
        const r = c.api_rate_limit_requests_effective
        apiRateLimitRequestsEffective.value =
          typeof r === 'number' && !Number.isNaN(r) ? Math.max(0, Math.floor(Number(r))) : 0
      }
      {
        const w = c.api_rate_limit_window_seconds_effective
        apiRateLimitWindowSecondsEffective.value =
          typeof w === 'number' && !Number.isNaN(w) ? Math.max(1, Math.floor(Number(w))) : 60
      }
      {
        const m = c.api_rate_limit_middleware_active_effective
        apiRateLimitMiddlewareActiveEffective.value = typeof m === 'boolean' ? m : false
      }
      {
        const r = c.api_rate_limit_redis_backend_configured_effective
        apiRateLimitRedisBackendConfiguredEffective.value = typeof r === 'boolean' ? r : false
      }
      {
        const u = c.api_rate_limit_user_max_concurrent_effective
        apiRateLimitUserMaxConcurrentEffective.value =
          typeof u === 'number' && !Number.isNaN(u) ? Math.max(1, Math.floor(Number(u))) : 5
      }
      {
        const x = c.api_rate_limit_trust_x_forwarded_for_effective
        apiRateLimitTrustXForwardedForEffective.value = typeof x === 'boolean' ? x : true
      }
      {
        const q = c.api_rate_limit_events_requests_effective
        apiRateLimitEventsRequestsEffective.value =
          typeof q === 'number' && !Number.isNaN(q) ? Math.floor(Number(q)) : 0
      }
      {
        const p = c.api_rate_limit_events_path_prefix_effective
        apiRateLimitEventsPathPrefixEffective.value =
          typeof p === 'string' && p.trim() ? p.trim() : '/api/events'
      }
      {
        const d = c.api_rate_limit_events_dedicated_bucket_active_effective
        apiRateLimitEventsDedicatedBucketActiveEffective.value = typeof d === 'boolean' ? d : false
      }
      const s = c.settings ?? {}
      autoUnloadLocalModelOnSwitch.value = parseBool(s.autoUnloadLocalModelOnSwitch, false)
      runtimeAutoReleaseEnabled.value = parseBool(s.runtimeAutoReleaseEnabled, true)
      runtimeMaxCachedLocalRuntimes.value = Math.min(16, Math.max(1, Number(s.runtimeMaxCachedLocalRuntimes) || 1))
      runtimeMaxCachedLocalLlmRuntimes.value = Math.min(
        16,
        Math.max(1, Number(s.runtimeMaxCachedLocalLlmRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1),
      )
      runtimeMaxCachedLocalVlmRuntimes.value = Math.min(
        16,
        Math.max(1, Number(s.runtimeMaxCachedLocalVlmRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1),
      )
      runtimeMaxCachedLocalImageGenerationRuntimes.value = Math.min(
        16,
        Math.max(1, Number(s.runtimeMaxCachedLocalImageGenerationRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1),
      )
      runtimeReleaseIdleTtlSeconds.value = Math.min(86400, Math.max(30, Number(s.runtimeReleaseIdleTtlSeconds) || 300))
      runtimeReleaseMinIntervalSeconds.value = Math.min(3600, Math.max(1, Number(s.runtimeReleaseMinIntervalSeconds) || 5))
      {
        const tj = s.torchStreamThreadJoinTimeoutSec
        if (tj !== undefined && tj !== null && String(tj) !== '') {
          const n = Math.floor(Number(tj))
          torchStreamThreadJoinTimeoutSec.value = Number.isNaN(n)
            ? 600
            : Math.min(86400, Math.max(30, n))
        } else {
          torchStreamThreadJoinTimeoutSec.value = 600
        }
      }
      {
        const qc = s.torchStreamChunkQueueMax
        if (qc !== undefined && qc !== null && String(qc) !== '') {
          const n = Math.floor(Number(qc))
          torchStreamChunkQueueMax.value = Number.isNaN(n) ? 0 : Math.min(4096, Math.max(0, n))
        } else {
          torchStreamChunkQueueMax.value = 0
        }
      }
      {
        const cw = s.chatStreamWallClockMaxSeconds
        if (cw !== undefined && cw !== null && String(cw) !== '') {
          const n = Math.floor(Number(cw))
          chatStreamWallClockMaxSeconds.value = Number.isNaN(n) ? 0 : Math.min(86400, Math.max(0, n))
        } else {
          chatStreamWallClockMaxSeconds.value = 0
        }
      }
      chatStreamResumeCancelUpstreamOnDisconnect.value = parseBool(
        s.chatStreamResumeCancelUpstreamOnDisconnect,
        false,
      )
      eventsStrictWorkflowBinding.value = parseBool(s.eventsStrictWorkflowBinding, false)
      eventsApiRequireAuthenticated.value = parseBool(s.eventsApiRequireAuthenticated, false)
      inferenceSmartRoutingEnabled.value = parseBool(s.inferenceSmartRoutingEnabled, true)
      inferenceSmartRoutingPoliciesJson.value = String(s.inferenceSmartRoutingPoliciesJson || '')
      skillDiscoveryTagMatchWeight.value = parseFloat01(s.skillDiscoveryTagMatchWeight, 0.3)
      skillDiscoveryMinSemanticSimilarity.value = parseFloat01(
        s.skillDiscoveryMinSemanticSimilarity,
        0,
      )
      skillDiscoveryMinHybridScore.value = parseFloat01(s.skillDiscoveryMinHybridScore, 0)
      {
        const fbP = 4
        const pp = s.agentPlanMaxParallelSteps
        if (pp !== undefined && pp !== null && String(pp) !== '') {
          const n = Math.min(32, Math.max(1, Math.floor(Number(pp))))
          agentPlanMaxParallelSteps.value = Number.isNaN(n) ? fbP : n
        } else {
          agentPlanMaxParallelSteps.value = fbP
        }
      }
      {
        const ts = s.agentStepDefaultTimeoutSeconds
        if (ts !== undefined && ts !== null && String(ts) !== '') {
          const f = parseFloat(String(ts))
          agentStepDefaultTimeoutSeconds.value = Number.isNaN(f) ? 0 : Math.min(3600, Math.max(0, f))
        } else {
          agentStepDefaultTimeoutSeconds.value = 0
        }
      }
      {
        const mr = s.agentStepDefaultMaxRetries
        if (mr !== undefined && mr !== null && String(mr) !== '') {
          const n = Math.min(20, Math.max(0, Math.floor(Number(mr))))
          agentStepDefaultMaxRetries.value = Number.isNaN(n) ? 0 : n
        } else {
          agentStepDefaultMaxRetries.value = 0
        }
      }
      {
        const ri = s.agentStepDefaultRetryIntervalSeconds
        if (ri !== undefined && ri !== null && String(ri) !== '') {
          const f = parseFloat(String(ri))
          agentStepDefaultRetryIntervalSeconds.value = Number.isNaN(f) ? 1 : Math.min(60, Math.max(0, f))
        } else {
          agentStepDefaultRetryIntervalSeconds.value = 1
        }
      }
      {
        const fbW = 10
        const wc = s.workflowSchedulerMaxConcurrency
        if (wc !== undefined && wc !== null && String(wc) !== '') {
          const n = Math.min(256, Math.max(1, Math.floor(Number(wc))))
          workflowSchedulerMaxConcurrency.value = Number.isNaN(n) ? fbW : n
        } else {
          workflowSchedulerMaxConcurrency.value = fbW
        }
      }
      workflowGovernanceHealthyThreshold.value = parseFloat01(
        s.workflowGovernanceHealthyThreshold,
        0.1,
      )
      workflowGovernanceWarningThreshold.value = Math.max(
        workflowGovernanceHealthyThreshold.value,
        parseFloat01(s.workflowGovernanceWarningThreshold, 0.3),
      )
      inferencePriorityPanelHighSloCriticalRate.value = parseFloat01(
        s.inferencePriorityPanelHighSloCriticalRate,
        0.95,
      )
      inferencePriorityPanelHighSloWarningRate.value = Math.max(
        inferencePriorityPanelHighSloCriticalRate.value,
        parseFloat01(s.inferencePriorityPanelHighSloWarningRate, 0.99),
      )
      inferencePriorityPanelPreemptionCooldownBusyThreshold.value = Math.max(
        0,
        Math.floor(Number(s.inferencePriorityPanelPreemptionCooldownBusyThreshold) || 10),
      )
      smartRoutingJsonError.value = ''
      refreshSmartRoutingPreview()
      isEditing.value = false
    } catch (e) {
      console.error('Failed to load system config:', e)
      mcpHttpEmitEffective.value = null
    }
  }

  const handleSave = async (onAfterSave?: () => Promise<void>) => {
    isSaving.value = true
    saveError.value = ''
    smartRoutingJsonError.value = ''
    try {
      const policyText = String(inferenceSmartRoutingPoliciesJson.value || '').trim()
      if (policyText) {
        try {
          JSON.parse(policyText)
        } catch {
          smartRoutingJsonError.value = '智能路由策略 JSON 格式无效，请检查后重试。'
          throw new Error(smartRoutingJsonError.value)
        }
      }
      await updateSystemConfig({
        autoUnloadLocalModelOnSwitch: Boolean(autoUnloadLocalModelOnSwitch.value),
        runtimeAutoReleaseEnabled: Boolean(runtimeAutoReleaseEnabled.value),
        runtimeMaxCachedLocalRuntimes: runtimeMaxCachedLocalRuntimes.value,
        runtimeMaxCachedLocalLlmRuntimes: runtimeMaxCachedLocalLlmRuntimes.value,
        runtimeMaxCachedLocalVlmRuntimes: runtimeMaxCachedLocalVlmRuntimes.value,
        runtimeMaxCachedLocalImageGenerationRuntimes: runtimeMaxCachedLocalImageGenerationRuntimes.value,
        runtimeReleaseIdleTtlSeconds: runtimeReleaseIdleTtlSeconds.value,
        runtimeReleaseMinIntervalSeconds: runtimeReleaseMinIntervalSeconds.value,
        inferenceSmartRoutingEnabled: Boolean(inferenceSmartRoutingEnabled.value),
        inferenceSmartRoutingPoliciesJson: policyText,
        skillDiscoveryTagMatchWeight: parseFloat01(skillDiscoveryTagMatchWeight.value, 0.3),
        skillDiscoveryMinSemanticSimilarity: parseFloat01(
          skillDiscoveryMinSemanticSimilarity.value,
          0,
        ),
        skillDiscoveryMinHybridScore: parseFloat01(skillDiscoveryMinHybridScore.value, 0),
        agentPlanMaxParallelSteps: Math.min(32, Math.max(1, Math.floor(Number(agentPlanMaxParallelSteps.value) || 4))),
        workflowSchedulerMaxConcurrency: Math.min(
          256,
          Math.max(1, Math.floor(Number(workflowSchedulerMaxConcurrency.value) || 10)),
        ),
        agentStepDefaultTimeoutSeconds: Math.min(3600, Math.max(0, Number(agentStepDefaultTimeoutSeconds.value) || 0)),
        agentStepDefaultMaxRetries: Math.min(20, Math.max(0, Math.floor(Number(agentStepDefaultMaxRetries.value) || 0))),
        agentStepDefaultRetryIntervalSeconds: Math.min(
          60,
          Math.max(0, parseFloat(String(agentStepDefaultRetryIntervalSeconds.value)) || 1),
        ),
        workflowGovernanceHealthyThreshold: parseFloat01(
          workflowGovernanceHealthyThreshold.value,
          0.1,
        ),
        workflowGovernanceWarningThreshold: Math.max(
          parseFloat01(workflowGovernanceHealthyThreshold.value, 0.1),
          parseFloat01(workflowGovernanceWarningThreshold.value, 0.3),
        ),
        inferencePriorityPanelHighSloCriticalRate: parseFloat01(
          inferencePriorityPanelHighSloCriticalRate.value,
          0.95,
        ),
        inferencePriorityPanelHighSloWarningRate: Math.max(
          parseFloat01(inferencePriorityPanelHighSloCriticalRate.value, 0.95),
          parseFloat01(inferencePriorityPanelHighSloWarningRate.value, 0.99),
        ),
        inferencePriorityPanelPreemptionCooldownBusyThreshold: Math.max(
          0,
          Math.floor(Number(inferencePriorityPanelPreemptionCooldownBusyThreshold.value) || 10),
        ),
        torchStreamThreadJoinTimeoutSec: Math.min(
          86400,
          Math.max(30, Math.floor(Number(torchStreamThreadJoinTimeoutSec.value) || 600)),
        ),
        torchStreamChunkQueueMax: Math.min(
          4096,
          Math.max(0, Math.floor(Number(torchStreamChunkQueueMax.value) || 0)),
        ),
        chatStreamWallClockMaxSeconds: Math.min(
          86400,
          Math.max(0, Math.floor(Number(chatStreamWallClockMaxSeconds.value) || 0)),
        ),
        chatStreamResumeCancelUpstreamOnDisconnect: Boolean(chatStreamResumeCancelUpstreamOnDisconnect.value),
        eventsStrictWorkflowBinding: Boolean(eventsStrictWorkflowBinding.value),
        eventsApiRequireAuthenticated: Boolean(eventsApiRequireAuthenticated.value),
      })
      await loadConfig()
      if (policyText) {
        pushSmartRoutingSnapshot(policyText)
      }
      if (onAfterSave) await onAfterSave()
      saveSuccess.value = true
      setTimeout(() => {
        saveSuccess.value = false
      }, 3000)
    } catch (e) {
      console.error('Failed to save runtime settings:', e)
      saveError.value = e instanceof Error ? e.message : String(e)
    } finally {
      isSaving.value = false
    }
  }

  const _parsePolicyObject = (): Record<string, any> => {
    const text = String(inferenceSmartRoutingPoliciesJson.value || '').trim()
    if (!text) return {}
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('智能路由策略 JSON 必须是对象（key 为 model alias）。')
    }
    return parsed as Record<string, any>
  }

  const _setPolicyObject = (obj: Record<string, any>) => {
    inferenceSmartRoutingPoliciesJson.value = JSON.stringify(obj, null, 2)
    isEditing.value = true
  }

  const refreshSmartRoutingPreview = () => {
    smartRoutingPreviewError.value = ''
    smartRoutingPreview.value = []
    try {
      const root = _parsePolicyObject()
      const entries: SmartRoutingPreviewItem[] = []
      for (const [alias, rawPolicy] of Object.entries(root)) {
        if (!rawPolicy || typeof rawPolicy !== 'object' || Array.isArray(rawPolicy)) {
          entries.push({ alias, strategy: 'invalid', summary: '策略不是对象' })
          continue
        }
        const policy = rawPolicy as Record<string, any>
        const strategy = String(policy.strategy || 'unknown')
        let summary = ''
        if (strategy === 'canary') {
          summary = `stable=${policy.stable || '-'} canary=${policy.canary || '-'} canary_percent=${policy.canary_percent ?? 10}%`
        } else if (strategy === 'blue_green') {
          summary = `stable=${policy.stable || '-'} candidate=${policy.candidate || '-'} candidate_percent=${policy.candidate_percent ?? 0}%`
        } else if (strategy === 'least_loaded') {
          const candidates = Array.isArray(policy.candidates) ? policy.candidates.join(', ') : '-'
          summary = `candidates=[${candidates}]`
        } else if (strategy === 'weighted') {
          const candidates = Array.isArray(policy.candidates)
            ? policy.candidates
                .map((x: any) => `${String(x?.target || x?.model_id || '-')}:${String(x?.weight ?? '-')}`)
                .join(', ')
            : '-'
          summary = `candidates=[${candidates}]`
        } else if (strategy === 'least_loaded_prefer_candidate') {
          summary = `stable=${policy.stable || '-'} candidate=${policy.candidate || '-'} threshold=${policy.candidate_max_extra_queue ?? 1}`
        } else {
          summary = '未知策略'
        }
        entries.push({ alias, strategy, summary })
      }
      smartRoutingPreview.value = entries
    } catch (e) {
      smartRoutingPreviewError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const loadSmartRoutingSnapshots = () => {
    try {
      const raw = localStorage.getItem(SMART_ROUTING_SNAPSHOT_STORAGE_KEY)
      if (!raw) {
        smartRoutingSnapshots.value = []
        return
      }
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) {
        smartRoutingSnapshots.value = []
        return
      }
      smartRoutingSnapshots.value = parsed
        .filter((x) => x && typeof x.text === "string" && typeof x.createdAt === "number" && typeof x.id === "string")
        .slice(0, MAX_SMART_ROUTING_SNAPSHOTS)
    } catch {
      smartRoutingSnapshots.value = []
    }
  }

  const persistSmartRoutingSnapshots = () => {
    localStorage.setItem(
      SMART_ROUTING_SNAPSHOT_STORAGE_KEY,
      JSON.stringify(smartRoutingSnapshots.value.slice(0, MAX_SMART_ROUTING_SNAPSHOTS)),
    )
  }

  const pushSmartRoutingSnapshot = (text: string) => {
    const trimmed = String(text || '').trim()
    if (!trimmed) return
    const next: SmartRoutingSnapshotItem = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      createdAt: Date.now(),
      text: trimmed,
    }
    const deduped = smartRoutingSnapshots.value.filter((x) => x.text !== trimmed)
    smartRoutingSnapshots.value = [next, ...deduped].slice(0, MAX_SMART_ROUTING_SNAPSHOTS)
    persistSmartRoutingSnapshots()
  }

  const restoreSnapshotById = (snapshotId: string) => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    const target = smartRoutingSnapshots.value.find((x) => x.id === snapshotId)
    if (!target) {
      smartRoutingBuilderError.value = '未找到可回滚的策略快照。'
      return
    }
    try {
      const parsed = JSON.parse(target.text)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('快照内容不是合法策略对象。')
      }
      _setPolicyObject(parsed as Record<string, any>)
      refreshSmartRoutingPreview()
      smartRoutingBuilderInfo.value = '已回滚到所选策略快照。'
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const compareSnapshotById = (snapshotId: string) => {
    smartRoutingSnapshotDiffError.value = ''
    smartRoutingSnapshotDiff.value = null
    try {
      const target = smartRoutingSnapshots.value.find((x) => x.id === snapshotId)
      if (!target) {
        throw new Error('未找到要对比的快照。')
      }
      const currentRaw = _parsePolicyObject()
      const snapshotRaw = JSON.parse(target.text)
      if (!snapshotRaw || typeof snapshotRaw !== 'object' || Array.isArray(snapshotRaw)) {
        throw new Error('快照内容不是合法策略对象。')
      }
      const current = currentRaw as Record<string, any>
      const snap = snapshotRaw as Record<string, any>
      const currentKeys = new Set(Object.keys(current))
      const snapKeys = new Set(Object.keys(snap))
      const addedAliases = Array.from(snapKeys).filter((k) => !currentKeys.has(k)).sort()
      const removedAliases = Array.from(currentKeys).filter((k) => !snapKeys.has(k)).sort()
      const changedAliases = Array.from(currentKeys)
        .filter((k) => snapKeys.has(k))
        .filter((k) => JSON.stringify(current[k]) !== JSON.stringify(snap[k]))
        .sort()
      const changedDetails = changedAliases.map((alias) => ({
        alias,
        lines: buildJsonLineDiff(
          JSON.stringify(current[alias], null, 2),
          JSON.stringify(snap[alias], null, 2),
        ),
      }))
      smartRoutingSnapshotDiff.value = {
        addedAliases,
        removedAliases,
        changedAliases,
        changedDetails,
      }
    } catch (e) {
      smartRoutingSnapshotDiffError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const buildJsonLineDiff = (currentText: string, snapshotText: string) => {
    const currentLines = String(currentText || '').split('\n')
    const snapshotLines = String(snapshotText || '').split('\n')
    const maxLen = Math.max(currentLines.length, snapshotLines.length)
    const rows: Array<{
      current: string
      snapshot: string
      currentChanged: boolean
      snapshotChanged: boolean
    }> = []
    for (let i = 0; i < maxLen; i += 1) {
      const current = currentLines[i] ?? ''
      const snapshot = snapshotLines[i] ?? ''
      const changed = current !== snapshot
      rows.push({
        current,
        snapshot,
        currentChanged: changed,
        snapshotChanged: changed,
      })
    }
    return rows
  }

  const getFilteredSnapshotDiff = (): SmartRoutingSnapshotDiffView | null => {
    if (!smartRoutingSnapshotDiff.value) return null
    const keyword = smartRoutingSnapshotDiffAliasFilter.value.trim().toLowerCase()
    if (!keyword) {
      return {
        addedAliases: smartRoutingSnapshotDiff.value.addedAliases,
        removedAliases: smartRoutingSnapshotDiff.value.removedAliases,
        changedAliases: smartRoutingSnapshotDiff.value.changedAliases,
        changedDetails: smartRoutingSnapshotDiff.value.changedDetails,
      }
    }
    const match = (alias: string) => alias.toLowerCase().includes(keyword)
    return {
      addedAliases: smartRoutingSnapshotDiff.value.addedAliases.filter(match),
      removedAliases: smartRoutingSnapshotDiff.value.removedAliases.filter(match),
      changedAliases: smartRoutingSnapshotDiff.value.changedAliases.filter(match),
      changedDetails: smartRoutingSnapshotDiff.value.changedDetails.filter((x) => match(x.alias)),
    }
  }

  const copyFilteredSnapshotDiffReport = async () => {
    smartRoutingSnapshotDiffError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const diff = getFilteredSnapshotDiff()
      if (!diff) {
        throw new Error('当前没有可复制的差异报告。')
      }
      const lines: string[] = []
      lines.push('Smart Routing Snapshot Diff Report')
      lines.push(`Generated At: ${new Date().toISOString()}`)
      lines.push('')
      lines.push(`Added Aliases: ${diff.addedAliases.length ? diff.addedAliases.join(', ') : '-'}`)
      lines.push(`Removed Aliases: ${diff.removedAliases.length ? diff.removedAliases.join(', ') : '-'}`)
      lines.push(`Changed Aliases: ${diff.changedAliases.length ? diff.changedAliases.join(', ') : '-'}`)
      for (const detail of diff.changedDetails) {
        lines.push('')
        lines.push(`## ${detail.alias}`)
        lines.push('--- Current ---')
        for (const row of detail.lines) {
          lines.push(row.current || ' ')
        }
        lines.push('--- Snapshot ---')
        for (const row of detail.lines) {
          lines.push(row.snapshot || ' ')
        }
      }
      await navigator.clipboard.writeText(lines.join('\n'))
      smartRoutingBuilderInfo.value = '差异报告已复制到剪贴板。'
    } catch (e) {
      smartRoutingSnapshotDiffError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const exportFilteredSnapshotDiffAsMarkdown = () => {
    smartRoutingSnapshotDiffError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const diff = getFilteredSnapshotDiff()
      if (!diff) {
        throw new Error('当前没有可导出的差异报告。')
      }
      const lines: string[] = []
      lines.push('# Smart Routing Snapshot Diff Report')
      lines.push('')
      lines.push(`- Generated At: ${new Date().toISOString()}`)
      lines.push(`- Added Aliases: ${diff.addedAliases.length ? diff.addedAliases.join(', ') : '-'}`)
      lines.push(`- Removed Aliases: ${diff.removedAliases.length ? diff.removedAliases.join(', ') : '-'}`)
      lines.push(`- Changed Aliases: ${diff.changedAliases.length ? diff.changedAliases.join(', ') : '-'}`)

      for (const detail of diff.changedDetails) {
        lines.push('')
        lines.push(`## ${detail.alias}`)
        lines.push('')
        lines.push('### Current')
        lines.push('```json')
        for (const row of detail.lines) {
          lines.push(row.current || ' ')
        }
        lines.push('```')
        lines.push('')
        lines.push('### Snapshot')
        lines.push('```json')
        for (const row of detail.lines) {
          lines.push(row.snapshot || ' ')
        }
        lines.push('```')
      }

      const content = lines.join('\n')
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const stamp = new Date().toISOString().replace(/[:.]/g, '-')
      a.href = url
      a.download = `smart-routing-diff-${stamp}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      smartRoutingBuilderInfo.value = '差异报告 Markdown 已导出。'
    } catch (e) {
      smartRoutingSnapshotDiffError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const upsertCanaryPolicy = (params: {
    alias: string
    stable: string
    canary: string
    percent: number
  }) => {
    smartRoutingBuilderError.value = ''
    try {
      const alias = params.alias.trim()
      const stable = params.stable.trim()
      const canary = params.canary.trim()
      const percent = Math.max(0, Math.min(100, Number(params.percent) || 0))
      if (!alias || !stable || !canary) {
        throw new Error('请填写 alias / stable / canary 后再生成策略。')
      }
      const root = _parsePolicyObject()
      root[alias] = {
        strategy: 'canary',
        stable,
        canary,
        canary_percent: percent,
      }
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
  loadSmartRoutingSnapshots()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const upsertLeastLoadedPolicy = (params: {
    alias: string
    candidatesText: string
  }) => {
    smartRoutingBuilderError.value = ''
    try {
      const alias = params.alias.trim()
      const candidates = params.candidatesText
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
      if (!alias || candidates.length === 0) {
        throw new Error('请填写 alias，并提供至少一个候选模型。')
      }
      const root = _parsePolicyObject()
      root[alias] = {
        strategy: 'least_loaded',
        candidates,
      }
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const upsertWeightedPolicy = (params: {
    alias: string
    pairsText: string
  }) => {
    smartRoutingBuilderError.value = ''
    try {
      const alias = params.alias.trim()
      if (!alias) {
        throw new Error('请填写 alias。')
      }
      const candidates = params.pairsText
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
        .map((item) => {
          const [targetRaw, weightRaw] = item.split(':')
          const target = String(targetRaw || '').trim()
          const weight = Number(weightRaw)
          if (!target || !Number.isFinite(weight) || weight <= 0) {
            throw new Error('weighted 格式应为 model-a:70, model-b:30，且权重大于 0。')
          }
          return { target, weight }
        })

      if (candidates.length === 0) {
        throw new Error('请至少填写一个 weighted 候选模型。')
      }

      const root = _parsePolicyObject()
      root[alias] = {
        strategy: 'weighted',
        candidates,
      }
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const formatSmartRoutingPoliciesJson = () => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const root = _parsePolicyObject()
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const removePolicyByAlias = (alias: string) => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const key = String(alias || '').trim()
      if (!key) {
        throw new Error('alias 不能为空。')
      }
      const root = _parsePolicyObject()
      if (!(key in root)) {
        throw new Error(`未找到 alias=${key} 对应策略。`)
      }
      delete root[key]
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const exportPoliciesToClipboard = async () => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const root = _parsePolicyObject()
      const text = JSON.stringify(root, null, 2)
      await navigator.clipboard.writeText(text)
      smartRoutingBuilderInfo.value = '策略已复制到剪贴板。'
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const importPoliciesFromClipboard = async () => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const text = await navigator.clipboard.readText()
      const parsed = JSON.parse(String(text || '').trim() || '{}')
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('剪贴板内容不是合法策略对象 JSON。')
      }
      _setPolicyObject(parsed as Record<string, any>)
      refreshSmartRoutingPreview()
      smartRoutingBuilderInfo.value = '已从剪贴板导入策略。'
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const fillSmartRoutingTemplate = () => {
    inferenceSmartRoutingPoliciesJson.value = DEFAULT_SMART_ROUTING_POLICIES_TEMPLATE
    isEditing.value = true
    refreshSmartRoutingPreview()
  }

  const clearSmartRoutingPolicies = () => {
    inferenceSmartRoutingPoliciesJson.value = ''
    isEditing.value = true
    refreshSmartRoutingPreview()
  }

  return {
    autoUnloadLocalModelOnSwitch,
    runtimeAutoReleaseEnabled,
    runtimeMaxCachedLocalRuntimes,
    runtimeMaxCachedLocalLlmRuntimes,
    runtimeMaxCachedLocalVlmRuntimes,
    runtimeMaxCachedLocalImageGenerationRuntimes,
    runtimeReleaseIdleTtlSeconds,
    runtimeReleaseMinIntervalSeconds,
    torchStreamThreadJoinTimeoutSec,
    torchStreamChunkQueueMax,
    chatStreamWallClockMaxSeconds,
    chatStreamResumeCancelUpstreamOnDisconnect,
    eventsStrictWorkflowBinding,
    eventsApiRequireAuthenticated,
    inferenceSmartRoutingEnabled,
    inferenceSmartRoutingPoliciesJson,
    skillDiscoveryTagMatchWeight,
    skillDiscoveryMinSemanticSimilarity,
    skillDiscoveryMinHybridScore,
    agentPlanMaxParallelSteps,
    agentStepDefaultTimeoutSeconds,
    agentStepDefaultMaxRetries,
    agentStepDefaultRetryIntervalSeconds,
    workflowSchedulerMaxConcurrency,
    workflowGovernanceHealthyThreshold,
    workflowGovernanceWarningThreshold,
    inferencePriorityPanelHighSloCriticalRate,
    inferencePriorityPanelHighSloWarningRate,
    inferencePriorityPanelPreemptionCooldownBusyThreshold,
    fillSmartRoutingTemplate,
    clearSmartRoutingPolicies,
    mcpHttpEmitEffective,
    apiRateLimitEnabledEffective,
    apiRateLimitRequestsEffective,
    apiRateLimitWindowSecondsEffective,
    apiRateLimitMiddlewareActiveEffective,
    apiRateLimitRedisBackendConfiguredEffective,
    apiRateLimitUserMaxConcurrentEffective,
    apiRateLimitTrustXForwardedForEffective,
    apiRateLimitEventsRequestsEffective,
    apiRateLimitEventsPathPrefixEffective,
    apiRateLimitEventsDedicatedBucketActiveEffective,
    config,
    isSaving,
    saveSuccess,
    saveError,
    smartRoutingJsonError,
    smartRoutingBuilderError,
    smartRoutingBuilderInfo,
    smartRoutingPreview,
    smartRoutingPreviewError,
    smartRoutingSnapshots,
    smartRoutingSnapshotDiff,
    smartRoutingSnapshotDiffError,
    smartRoutingSnapshotDiffAliasFilter,
    isEditing,
    loadConfig,
    handleSave,
    refreshSmartRoutingPreview,
    upsertCanaryPolicy,
    upsertLeastLoadedPolicy,
    upsertWeightedPolicy,
    formatSmartRoutingPoliciesJson,
    removePolicyByAlias,
    exportPoliciesToClipboard,
    importPoliciesFromClipboard,
    restoreSnapshotById,
    compareSnapshotById,
    getFilteredSnapshotDiff,
    copyFilteredSnapshotDiffReport,
    exportFilteredSnapshotDiffAsMarkdown,
  }
}
