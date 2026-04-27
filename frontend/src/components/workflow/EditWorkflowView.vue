<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, Save, Play, Rocket, Undo2, Redo2, Loader2, ChevronDown } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import NodeLibrary from './editor/NodeLibrary.vue'
import WorkflowCanvas from './editor/WorkflowCanvas.vue'
import NodeConfigPanel from './editor/NodeConfigPanel.vue'
import type { Node } from '@vue-flow/core'
import type { Edge } from '@vue-flow/core'
import type { WorkflowNodeData } from './editor/types'
import { toWorkflowDag, fromWorkflowDag } from './editor/serialization'
import { validateWorkflowNodes, validateWorkflowPreflight, type ValidationError } from './editor/validation'
import {
  getWorkflow,
  getWorkflowVersion,
  getSystemConfig,
  updateWorkflow,
  createWorkflowVersion,
  getToolCompositionRecommendations,
  recordToolCompositionUsage,
  type ToolCompositionRecommendationItem,
} from '@/services/api'
import {
  listToolCompositionTemplates,
  recommendTemplates,
  buildTemplateGraph,
  trackTemplateUsage,
  type ToolCompositionTemplateId,
} from './editor/toolCompositionTemplates'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const workflowId = route.params.id as string

const workflowName = ref('')
const workflowVersion = ref('')
const editorNodes = ref<Node<WorkflowNodeData>[]>([
  {
    id: 'start',
    type: 'workflow',
    position: { x: 80, y: 120 },
    data: { type: 'start', label: 'Start', config: {} },
  },
])
const editorEdges = ref<Edge[]>([])
/** 以 ID 为唯一来源，拖动时仅替换 editorNodes，不丢失选中 */
const selectedNodeId = ref<string | null>(null)
const selectedEdge = ref<Edge | null>(null)
const isDirty = ref(false)

const selectedNode = computed(() =>
  selectedNodeId.value
    ? (editorNodes.value.find((n) => n.id === selectedNodeId.value) as Node<WorkflowNodeData> | undefined) ?? null
    : null
)

function isCanvasGroupNode(node: Node<WorkflowNodeData>): boolean {
  return node.data?.type === 'group' || (node.data?.config as Record<string, unknown> | undefined)?.__canvasGroup === true
}

function getPersistableGraph() {
  const nodes = editorNodes.value.filter((node) => !isCanvasGroupNode(node))
  const nodeIdSet = new Set(nodes.map((node) => node.id))
  const edges = editorEdges.value.filter((edge) => nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target))
  return { nodes, edges }
}

type EditorSnapshot = {
  workflowName: string
  nodes: Node<WorkflowNodeData>[]
  edges: Edge[]
}

const HISTORY_LIMIT = 80
const undoStack = ref<EditorSnapshot[]>([])
const redoStack = ref<EditorSnapshot[]>([])
const isApplyingSnapshot = ref(false)
const lastSnapshotSignature = ref('')
const lastSavedSignature = ref('')
const lastBackendDraftSignature = ref('')
let autosaveTimer: number | null = null
const saveInProgress = ref(false)
const EDIT_DRAFT_KEY = `workflow:edit:${workflowId}:draft`
const validationErrors = ref<ValidationError[]>([])
const draftRestorePending = ref<EditorSnapshot | null>(null)
const reflectorMaxRetries = ref<number>(0)
const reflectorRetryIntervalSeconds = ref<number>(1)
const reflectorFallbackAgentId = ref('')

const selectedNodeModelId = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const v = (c as Record<string, unknown>).model_id
  return typeof v === 'string' ? v : ''
})
const selectedNodeModelDisplayName = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const name = (c as Record<string, unknown>).model_display_name
  const id = (c as Record<string, unknown>).model_id
  return (typeof name === 'string' && name) || (typeof id === 'string' ? id : '')
})
const selectedNodeAgentId = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const v = (c as Record<string, unknown>).agent_id
  return typeof v === 'string' ? v : ''
})
const selectedNodeAgentDisplayName = computed(() => {
  const c = selectedNode.value?.data?.config
  if (!c || typeof c !== 'object') return ''
  const name = (c as Record<string, unknown>).agent_display_name
  const id = (c as Record<string, unknown>).agent_id
  return (typeof name === 'string' && name) || (typeof id === 'string' ? id : '')
})

function renderValidationError(e: ValidationError): string {
  if (e.messageKey) return t(e.messageKey, (e.messageParams || {}) as Record<string, unknown>)
  return e.message
}

const effectiveReflectorPolicy = computed(() => {
  const selectedConfig = (selectedNode.value?.data?.config || {}) as Record<string, unknown>
  const hasNodeRetry = selectedConfig.reflector_max_retries !== undefined
  const hasNodeInterval = selectedConfig.reflector_retry_interval_seconds !== undefined
  const hasNodeFallback = selectedConfig.reflector_fallback_agent_id !== undefined
  const nodeRetry = Number(selectedConfig.reflector_max_retries)
  const nodeInterval = Number(selectedConfig.reflector_retry_interval_seconds)
  const nodeFallback = String(selectedConfig.reflector_fallback_agent_id || '').trim()
  return {
    maxRetries: hasNodeRetry && Number.isFinite(nodeRetry) ? Math.max(0, Math.min(20, Math.trunc(nodeRetry))) : reflectorMaxRetries.value,
    retryIntervalSeconds:
      hasNodeInterval && Number.isFinite(nodeInterval)
        ? Math.max(0, Math.min(60, Number(nodeInterval)))
        : reflectorRetryIntervalSeconds.value,
    fallbackAgentId: hasNodeFallback ? nodeFallback : reflectorFallbackAgentId.value,
    maxRetriesSource: hasNodeRetry ? 'node' : 'global',
    retryIntervalSource: hasNodeInterval ? 'node' : 'global',
    fallbackSource: hasNodeFallback ? 'node' : 'global',
    nodeType: selectedNode.value?.data?.type || null,
  }
})

const reflectorOverrideNodes = computed(() => {
  return (editorNodes.value || [])
    .filter((node) => {
      const cfg = (node.data?.config || {}) as Record<string, unknown>
      return (
        cfg.reflector_max_retries !== undefined ||
        cfg.reflector_retry_interval_seconds !== undefined ||
        cfg.reflector_fallback_agent_id !== undefined
      )
    })
    .map((node) => {
      const cfg = (node.data?.config || {}) as Record<string, unknown>
      const overrideKeys: string[] = []
      if (cfg.reflector_max_retries !== undefined) overrideKeys.push('max_retries')
      if (cfg.reflector_retry_interval_seconds !== undefined) overrideKeys.push('retry_interval_seconds')
      if (cfg.reflector_fallback_agent_id !== undefined) overrideKeys.push('fallback_agent_id')
      return {
        nodeId: node.id,
        label: String(node.data?.label || node.id),
        type: String(node.data?.type || ''),
        overrideKeys,
      }
    })
})

const reflectorCoverageSummary = computed(() => {
  const total = editorNodes.value.length
  const overridden = reflectorOverrideNodes.value.length
  return {
    total,
    overridden,
    ratioText: `${overridden}/${total}`,
    ratio: total > 0 ? overridden / total : 0,
  }
})

const reflectorOverrideFieldStats = computed(() => {
  let retriesCount = 0
  let intervalCount = 0
  let fallbackCount = 0
  for (const node of editorNodes.value) {
    const cfg = (node.data?.config || {}) as Record<string, unknown>
    if (cfg.reflector_max_retries !== undefined) retriesCount += 1
    if (cfg.reflector_retry_interval_seconds !== undefined) intervalCount += 1
    if (cfg.reflector_fallback_agent_id !== undefined) fallbackCount += 1
  }
  return {
    retriesCount,
    intervalCount,
    fallbackCount,
  }
})
const importedGovernanceSnapshot = ref<{
  workflow_id?: string
  workflow_name?: string
  exported_at?: string
  coverage?: { overridden?: number; total?: number; ratioText?: string }
  field_distribution?: { retriesCount?: number; intervalCount?: number; fallbackCount?: number }
  overridden_nodes?: Array<{ nodeId?: string; label?: string; type?: string; overrideKeys?: string[] }>
} | null>(null)
const importedGovernanceError = ref('')
const governanceUiMessage = ref('')
const governanceHealthyThreshold = ref(0.1)
const governanceWarningThreshold = ref(0.3)
const selectedTemplateId = ref<ToolCompositionTemplateId>('travel_planning')
const templates = listToolCompositionTemplates()
const backendRecommendedTemplates = ref<ToolCompositionRecommendationItem[]>([])
const recommendedTemplates = computed(() => {
  if (backendRecommendedTemplates.value.length > 0) {
    const known = new Map(templates.map((t) => [t.id, t]))
    return backendRecommendedTemplates.value.map((item) => ({
      id: item.id as ToolCompositionTemplateId,
      name: item.name || known.get(item.id as ToolCompositionTemplateId)?.name || item.id,
      description: item.description || known.get(item.id as ToolCompositionTemplateId)?.description || '',
      tools: item.tools || known.get(item.id as ToolCompositionTemplateId)?.tools || [],
      score: item.score || 0,
      signals: item.signals || {},
    }))
  }
  return recommendTemplates(editorNodes.value)
})
const selectedRecommendationReason = computed(() => {
  const picked = recommendedTemplates.value.find((x) => x.id === selectedTemplateId.value) as
    | ({ signals?: Record<string, any> } & Record<string, any>)
    | undefined
  const s = (picked?.signals || {}) as Record<string, any>
  if (!s || Object.keys(s).length === 0) return ''
  return `重叠工具 ${s.overlap ?? 0}，转移信号 ${s.transition_score ?? 0}（置信度 ${(Number(s.transition_confidence || 0) * 100).toFixed(0)}%），用户历史 ${s.user_uses ?? 0} 次`
})
const selectedRecommendationChips = computed(() => {
  const picked = recommendedTemplates.value.find((x) => x.id === selectedTemplateId.value) as
    | ({ signals?: Record<string, any> } & Record<string, any>)
    | undefined
  const s = (picked?.signals || {}) as Record<string, any>
  const pairs = Array.isArray(s.transition_pairs) ? s.transition_pairs : []
  return pairs
    .filter((p) => p && typeof p === 'object')
    .map((p) => {
      const from = String((p as Record<string, unknown>).from || '')
      const to = String((p as Record<string, unknown>).to || '')
      const w = Number((p as Record<string, unknown>).weight || 0)
      return {
        key: `${from}->${to}`,
        label: `${from} -> ${to}`,
        detail: `转移权重 ${w.toFixed(2)}`,
        from,
        to,
      }
    })
})
const activeRecommendationPairKey = ref('')
const canvasFocusNodeId = ref<string | null>(null)
const previewTemplateSkillNodes = computed(() => {
  const graph = buildTemplateGraph(selectedTemplateId.value)
  return graph.nodes
    .filter((n) => n.data?.type === 'skill')
    .map((n) => ({
      nodeId: n.id,
      label: String(n.data?.label || n.id),
      toolName: String((n.data?.config as Record<string, unknown>)?.tool_name || ''),
    }))
})
const governanceMaturity = computed(() => {
  const ratio = reflectorCoverageSummary.value.ratio
  const healthyThreshold = Math.max(0, Math.min(1, Number(governanceHealthyThreshold.value || 0.1)))
  const warningThreshold = Math.max(healthyThreshold, Math.min(1, Number(governanceWarningThreshold.value || 0.3)))
  if (ratio <= healthyThreshold) {
    return {
      level: 'Healthy',
      toneClass: 'text-emerald-700 dark:text-emerald-300 border-emerald-500/40 bg-emerald-500/10',
      hint: `节点覆盖较少（<= ${(healthyThreshold * 100).toFixed(0)}%），策略收敛良好。`,
    }
  }
  if (ratio <= warningThreshold) {
    return {
      level: 'Warning',
      toneClass: 'text-amber-700 dark:text-amber-300 border-amber-500/40 bg-amber-500/10',
      hint: `存在一定节点覆盖（<= ${(warningThreshold * 100).toFixed(0)}%），建议定期巡检。`,
    }
  }
  return {
    level: 'Risky',
    toneClass: 'text-destructive border-destructive/40 bg-destructive/10',
    hint: '节点覆盖占比较高，建议收敛至全局策略。',
  }
})
const importedGovernanceDiff = computed(() => {
  if (!importedGovernanceSnapshot.value) return null
  const importedCoverage = importedGovernanceSnapshot.value.coverage || {}
  const importedFields = importedGovernanceSnapshot.value.field_distribution || {}
  const importedNodes = importedGovernanceSnapshot.value.overridden_nodes || []
  const importedNodeIds = new Set(
    importedNodes.map((n) => String(n.nodeId || '').trim()).filter((id) => id.length > 0),
  )
  const currentNodeIds = new Set(
    reflectorOverrideNodes.value.map((n) => String(n.nodeId || '').trim()).filter((id) => id.length > 0),
  )
  const addedNodeIds = [...currentNodeIds].filter((id) => !importedNodeIds.has(id))
  const removedNodeIds = [...importedNodeIds].filter((id) => !currentNodeIds.has(id))
  const currentCoverage = reflectorCoverageSummary.value.overridden
  const importedCoverageValue = Number(importedCoverage.overridden ?? 0)
  return {
    coverageDelta: currentCoverage - importedCoverageValue,
    retriesDelta: reflectorOverrideFieldStats.value.retriesCount - Number(importedFields.retriesCount ?? 0),
    intervalDelta: reflectorOverrideFieldStats.value.intervalCount - Number(importedFields.intervalCount ?? 0),
    fallbackDelta: reflectorOverrideFieldStats.value.fallbackCount - Number(importedFields.fallbackCount ?? 0),
    addedNodeIds,
    removedNodeIds,
  }
})

function diffToneClass(delta: number): string {
  if (delta > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (delta < 0) return 'text-destructive'
  return 'text-muted-foreground'
}


function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

function captureSnapshot(): EditorSnapshot {
  return {
    workflowName: workflowName.value,
    nodes: clone(editorNodes.value),
    edges: clone(editorEdges.value),
  }
}

function snapshotSignature(snapshot: EditorSnapshot): string {
  return JSON.stringify(snapshot)
}

function recalcDirty() {
  isDirty.value = snapshotSignature(captureSnapshot()) !== lastSavedSignature.value
}

function applySnapshot(snapshot: EditorSnapshot) {
  isApplyingSnapshot.value = true
  workflowName.value = snapshot.workflowName
  editorNodes.value = clone(snapshot.nodes)
  editorEdges.value = clone(snapshot.edges)
  selectedNodeId.value = null
  selectedEdge.value = null
  isApplyingSnapshot.value = false
}

function saveDraftToLocal() {
  const payload = {
    updated_at: new Date().toISOString(),
    snapshot: captureSnapshot(),
  }
  localStorage.setItem(EDIT_DRAFT_KEY, JSON.stringify(payload))
}

/** 仅本地草稿，不创建 version，避免版本膨胀；仅手动 Save/Publish 创建新 version */
function scheduleAutosave() {
  if (autosaveTimer != null) window.clearTimeout(autosaveTimer)
  autosaveTimer = window.setTimeout(() => {
    saveDraftToLocal()
    autosaveTimer = null
  }, 5000)
}

function markStateChange() {
  if (isApplyingSnapshot.value) return
  validationErrors.value = []
  const current = captureSnapshot()
  const currentSig = snapshotSignature(current)
  if (!lastSnapshotSignature.value) {
    lastSnapshotSignature.value = currentSig
    recalcDirty()
    return
  }
  if (currentSig === lastSnapshotSignature.value) return
  undoStack.value.push(JSON.parse(lastSnapshotSignature.value) as EditorSnapshot)
  if (undoStack.value.length > HISTORY_LIMIT) undoStack.value.shift()
  redoStack.value = []
  lastSnapshotSignature.value = currentSig
  recalcDirty()
  scheduleAutosave()
}

function undo() {
  if (!undoStack.value.length) return
  const prev = undoStack.value.pop()!
  redoStack.value.push(captureSnapshot())
  applySnapshot(prev)
  lastSnapshotSignature.value = snapshotSignature(prev)
  recalcDirty()
}

function redo() {
  if (!redoStack.value.length) return
  const next = redoStack.value.pop()!
  undoStack.value.push(captureSnapshot())
  applySnapshot(next)
  lastSnapshotSignature.value = snapshotSignature(next)
  recalcDirty()
}

function tryRestoreDraft() {
  const raw = localStorage.getItem(EDIT_DRAFT_KEY)
  if (!raw) return
  try {
    const parsed = JSON.parse(raw) as { snapshot?: EditorSnapshot }
    if (!parsed?.snapshot) return
    draftRestorePending.value = parsed.snapshot
  } catch {
    // ignore broken local draft
  }
}
function acceptDraftRestore() {
  if (draftRestorePending.value) {
    applySnapshot(draftRestorePending.value)
    localStorage.removeItem(EDIT_DRAFT_KEY)
    draftRestorePending.value = null
  }
}
function dismissDraftRestore() {
  localStorage.removeItem(EDIT_DRAFT_KEY)
  draftRestorePending.value = null
}

function goBack() {
  router.push({ name: 'workflow-detail', params: { id: workflowId } })
}

function confirmGovernanceRiskBeforeSave(): boolean {
  if (governanceMaturity.value.level !== 'Risky') return true
  return window.confirm(
    '当前治理状态为 Risky（节点覆盖比例较高）。建议先收敛策略后再发布。\n是否仍继续保存为新版本？',
  )
}

function normalizeReflectorConfig() {
  const retries = Number.isFinite(reflectorMaxRetries.value)
    ? Math.max(0, Math.min(20, Math.trunc(reflectorMaxRetries.value)))
    : 0
  const retryInterval = Number.isFinite(reflectorRetryIntervalSeconds.value)
    ? Math.max(0, Math.min(60, Number(reflectorRetryIntervalSeconds.value)))
    : 1
  const fallback = String(reflectorFallbackAgentId.value || '').trim()
  reflectorMaxRetries.value = retries
  reflectorRetryIntervalSeconds.value = retryInterval
  reflectorFallbackAgentId.value = fallback
  return {
    reflector: {
      max_retries: retries,
      retry_interval_seconds: retryInterval,
      fallback_agent_id: fallback,
    },
  } as Record<string, unknown>
}

async function saveWorkflow() {
  if (saveInProgress.value) return
  if (!confirmGovernanceRiskBeforeSave()) return
  const { nodes, edges } = getPersistableGraph()
  const { valid, errors } = validateWorkflowNodes(nodes)
  if (!valid) {
    validationErrors.value = errors
    return
  }
  validationErrors.value = []
  const snapshot = captureSnapshot()
  saveInProgress.value = true
  try {
    await updateWorkflow(workflowId, { name: (snapshot.workflowName || 'Untitled Workflow').trim() })
    const dag = toWorkflowDag(nodes, edges, normalizeReflectorConfig())
    await createWorkflowVersion(workflowId, {
      description: `Saved at ${new Date().toISOString().slice(0, 19)}`,
      dag,
    })
    lastSavedSignature.value = snapshotSignature(snapshot)
    recalcDirty()
    localStorage.removeItem(EDIT_DRAFT_KEY)
    router.push({ name: 'workflow-detail', params: { id: workflowId } })
  } catch (e) {
    console.error('Save failed:', e)
  } finally {
    saveInProgress.value = false
  }
}

async function runWorkflowSaveAndRun() {
  if (!confirmGovernanceRiskBeforeSave()) return
  const { nodes, edges } = getPersistableGraph()
  const { valid, errors } = validateWorkflowNodes(nodes)
  if (!valid) {
    validationErrors.value = errors
    return
  }
  validationErrors.value = []
  const snapshot = captureSnapshot()
  saveInProgress.value = true
  try {
    await updateWorkflow(workflowId, { name: (snapshot.workflowName || 'Untitled Workflow').trim() })
    const dag = toWorkflowDag(nodes, edges, normalizeReflectorConfig())
    await createWorkflowVersion(workflowId, {
      description: `Saved at ${new Date().toISOString().slice(0, 19)}`,
      dag,
    })
    lastSavedSignature.value = snapshotSignature(snapshot)
    recalcDirty()
    localStorage.removeItem(EDIT_DRAFT_KEY)
    router.push({ name: 'workflow-run', params: { id: workflowId } })
  } catch (e) {
    console.error('Save failed:', e)
  } finally {
    saveInProgress.value = false
  }
}
function runWorkflowPublishedOnly() {
  router.push({ name: 'workflow-run', params: { id: workflowId } })
}

function onUpdateConfig(nodeId: string, config: Record<string, unknown>) {
  const list = [...editorNodes.value]
  const idx = list.findIndex((n) => n.id === nodeId)
  if (idx === -1) return
  const node = list[idx]
  if (!node?.data) return
  const mergedConfigRaw = { ...(node.data.config as Record<string, unknown> || {}), ...config }
  const mergedConfig = Object.fromEntries(
    Object.entries(mergedConfigRaw).filter(([, v]) => v !== undefined)
  ) as Record<string, unknown>
  const nextData = { ...node.data, config: mergedConfig } as WorkflowNodeData
  list[idx] = { ...node, data: nextData }
  editorNodes.value = list
}

function onNodesUpdate(incoming: Node<WorkflowNodeData>[]) {
  const current = editorNodes.value
  const merged = current.map((cur) => {
    const inc = incoming.find((i) => i.id === cur.id)
    if (!inc) return cur
    const nextData = inc.data
      ? ({
          ...cur.data,
          ...inc.data,
          config: {
            ...((cur.data?.config as Record<string, unknown>) || {}),
            ...((inc.data?.config as Record<string, unknown>) || {}),
          },
        } as WorkflowNodeData)
      : cur.data
    return {
      ...cur,
      ...inc,
      position: inc.position ?? cur.position,
      data: nextData,
    } as Node<WorkflowNodeData>
  })
  const added = (incoming || []).filter((n) => !current.some((c) => c.id === n.id))
  if (added.length) {
    editorNodes.value = [...merged, ...added]
    selectedEdge.value = null
    const lastAdded = added[added.length - 1]
    if (lastAdded) {
      // 同步设选中，避免与画布 onNodesChange 竞争导致配置面板一闪而过
      selectedNodeId.value = lastAdded.id
    }
  } else {
    editorNodes.value = merged
  }
}

function onEdgesUpdate(nextEdges: Edge[]) {
  const prevEdges = editorEdges.value
  editorEdges.value = nextEdges

  // 自动模板：Input -> Condition 连线时，若 Condition 为空则填入可运行默认表达式
  const prevIds = new Set(prevEdges.map((e) => e.id))
  const added = nextEdges.filter((e) => !prevIds.has(e.id))
  for (const edge of added) {
    const src = editorNodes.value.find((n) => n.id === edge.source)
    const tgt = editorNodes.value.find((n) => n.id === edge.target)
    if (src?.data?.type === 'input' && tgt?.data?.type === 'condition') {
      const cfg = (tgt.data?.config || {}) as Record<string, unknown>
      const currentExpr = String(cfg.condition_expression || '').trim()
      if (!currentExpr) {
        onUpdateConfig(tgt.id, {
          ...cfg,
          condition_expression: '${input.query} is not None',
        })
      }
    }
  }
}

function runPreflightCheck() {
  const { nodes, edges } = getPersistableGraph()
  const baseCheck = validateWorkflowNodes(nodes)
  const preflight = validateWorkflowPreflight(nodes, edges)
  const errors = [...baseCheck.errors, ...preflight.errors]
  validationErrors.value = errors
}

function applyTemplate() {
  const graph = buildTemplateGraph(selectedTemplateId.value)
  editorNodes.value = graph.nodes
  editorEdges.value = graph.edges
  selectedNodeId.value = null
  selectedEdge.value = null
  trackTemplateUsage(selectedTemplateId.value)
  const toolSequence = graph.nodes
    .filter((n) => n.data?.type === 'skill')
    .map((n) => String((n.data?.config as Record<string, unknown>)?.tool_name || ''))
    .filter(Boolean)
  recordToolCompositionUsage(workflowId, {
    template_id: selectedTemplateId.value,
    tool_sequence: toolSequence,
  }).catch(() => undefined)
  void refreshBackendRecommendations()
}

async function refreshBackendRecommendations() {
  try {
    const currentTools = editorNodes.value
      .filter((n) => n.data?.type === 'skill')
      .map((n) => String((n.data?.config as Record<string, unknown>)?.tool_name || ''))
      .filter(Boolean)
    const res = await getToolCompositionRecommendations(workflowId, {
      current_tools: currentTools,
      limit: 5,
    })
    backendRecommendedTemplates.value = res.items || []
  } catch {
    backendRecommendedTemplates.value = []
  }
}

function onSelectNode(node: Node<WorkflowNodeData> | null) {
  selectedNodeId.value = node?.id ?? null
  if (node) selectedEdge.value = null
}

function onSelectNodeById(nodeId: string) {
  if (!editorNodes.value.some((n) => n.id === nodeId)) return
  selectedNodeId.value = nodeId
  selectedEdge.value = null
}

function clearNodeReflectorOverrides(nodeId: string) {
  const list = [...editorNodes.value]
  const idx = list.findIndex((n) => n.id === nodeId)
  if (idx === -1) return
  const node = list[idx]
  if (!node?.data) return
  const cfg = { ...((node.data.config as Record<string, unknown>) || {}) }
  delete cfg.reflector_max_retries
  delete cfg.reflector_retry_interval_seconds
  delete cfg.reflector_fallback_agent_id
  list[idx] = {
    ...node,
    data: {
      ...node.data,
      config: cfg,
    } as WorkflowNodeData,
  }
  editorNodes.value = list
}

function clearAllReflectorOverrides() {
  if (!reflectorOverrideNodes.value.length) return
  const confirmed = window.confirm(`确认清除 ${reflectorOverrideNodes.value.length} 个节点的 Reflector 覆盖配置吗？`)
  if (!confirmed) return
  editorNodes.value = editorNodes.value.map((node) => {
    const cfg = { ...((node.data?.config as Record<string, unknown>) || {}) }
    if (
      cfg.reflector_max_retries === undefined &&
      cfg.reflector_retry_interval_seconds === undefined &&
      cfg.reflector_fallback_agent_id === undefined
    ) {
      return node
    }
    delete cfg.reflector_max_retries
    delete cfg.reflector_retry_interval_seconds
    delete cfg.reflector_fallback_agent_id
    return {
      ...node,
      data: {
        ...(node.data as WorkflowNodeData),
        config: cfg,
      },
    }
  })
}

function exportReflectorGovernanceSnapshot() {
  const payload = {
    exported_at: new Date().toISOString(),
    workflow_id: workflowId,
    workflow_name: workflowName.value,
    coverage: reflectorCoverageSummary.value,
    risk_assessment: {
      level: governanceMaturity.value.level,
      hint: governanceMaturity.value.hint,
      ratio: reflectorCoverageSummary.value.ratio,
    },
    field_distribution: reflectorOverrideFieldStats.value,
    overridden_nodes: reflectorOverrideNodes.value,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  const ts = new Date().toISOString().replace(/[:.]/g, '-')
  link.href = url
  link.download = `workflow-reflector-governance-${workflowId}-${ts}.json`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function openGovernanceSnapshotImport() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'application/json,.json'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    try {
      const raw = await file.text()
      const parsed = JSON.parse(raw) as {
        workflow_id?: string
        workflow_name?: string
        exported_at?: string
        coverage?: { overridden?: number; total?: number; ratioText?: string }
        field_distribution?: { retriesCount?: number; intervalCount?: number; fallbackCount?: number }
        overridden_nodes?: Array<{ nodeId?: string; label?: string; type?: string; overrideKeys?: string[] }>
      }
      importedGovernanceSnapshot.value = parsed
      importedGovernanceError.value = ''
    } catch (error) {
      importedGovernanceSnapshot.value = null
      importedGovernanceError.value = `快照导入失败：${String(error)}`
    }
  }
  input.click()
}

function clearImportedGovernanceSnapshot() {
  importedGovernanceSnapshot.value = null
  importedGovernanceError.value = ''
}

function focusNodeFromGovernanceDiff(nodeId: string) {
  const exists = editorNodes.value.some((node) => node.id === nodeId)
  if (exists) {
    onSelectNodeById(nodeId)
    governanceUiMessage.value = ''
    return
  }
  governanceUiMessage.value = `节点 ${nodeId} 不在当前画布中，无法定位。`
}

function onRecommendationChipClick(chip: { key: string; label: string; detail: string; from: string; to: string }) {
  governanceUiMessage.value = `推荐链路：${chip.label}（${chip.detail}）`
  activeRecommendationPairKey.value = chip.key
  const fromNode = editorNodes.value.find((n) => {
    const cfg = (n.data?.config || {}) as Record<string, unknown>
    return n.data?.type === 'skill' && String(cfg.tool_name || cfg.tool_id || '') === chip.from
  })
  const toNode = editorNodes.value.find((n) => {
    const cfg = (n.data?.config || {}) as Record<string, unknown>
    return n.data?.type === 'skill' && String(cfg.tool_name || cfg.tool_id || '') === chip.to
  })
  const target = toNode || fromNode
  if (target) {
    onSelectNodeById(target.id)
    canvasFocusNodeId.value = target.id
    window.setTimeout(() => {
      if (canvasFocusNodeId.value === target.id) canvasFocusNodeId.value = null
    }, 300)
  }
  void nextTick(() => {
    const fromEl = document.querySelector(`[data-tool-name="${chip.from}"]`) as HTMLElement | null
    const toEl = document.querySelector(`[data-tool-name="${chip.to}"]`) as HTMLElement | null
    ;(fromEl || toEl)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function onSelectEdge(edge: Edge | null) {
  // 仅在选择某条 edge 时清空节点选中；select-edge(null) 只清边，避免 drop 节点后配置被清空（onDrop 里会先 emit select-edge null 再 emit select-node-by-id）
  if (edge != null) selectedNodeId.value = null
  selectedEdge.value = edge
}

function onCloseConfigPanel() {
  selectedNodeId.value = null
  selectedEdge.value = null
}

function onUpdateEdge(edgeId: string, patch: Record<string, unknown>) {
  editorEdges.value = editorEdges.value.map((edge) => {
    if (edge.id !== edgeId) return edge
    return { ...edge, ...patch } as Edge
  })
  selectedEdge.value = editorEdges.value.find((edge) => edge.id === edgeId) || null
}

function removeEdge(edgeId: string) {
  editorEdges.value = editorEdges.value.filter((edge) => edge.id !== edgeId)
  if (selectedEdge.value?.id === edgeId) selectedEdge.value = null
}

function removeNode(nodeId: string) {
  if (nodeId === 'start') return
  editorNodes.value = editorNodes.value.filter((n) => n.id !== nodeId)
  editorEdges.value = editorEdges.value.filter((e) => e.source !== nodeId && e.target !== nodeId)
  if (selectedNodeId.value === nodeId) selectedNodeId.value = null
  if (selectedEdge.value?.source === nodeId || selectedEdge.value?.target === nodeId) selectedEdge.value = null
}

function onKeydown(e: KeyboardEvent) {
  const meta = e.metaKey || e.ctrlKey
  if (meta && e.key.toLowerCase() === 's') {
    e.preventDefault()
    void saveWorkflow()
    return
  }
  if (meta && e.key.toLowerCase() === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
    return
  }
  if (meta && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) {
    e.preventDefault()
    redo()
    return
  }
  if ((e.key !== 'Delete' && e.key !== 'Backspace') || !selectedNode.value) return
  // 焦点在输入框/文本框时不要触发删除节点，避免编辑 Default input 等时误删
  const target = e.target as HTMLElement | null
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
  if (selectedNode.value.data?.type === 'start') return
  e.preventDefault()
  removeNode(selectedNode.value.id)
}

watch([workflowName, editorNodes, editorEdges], () => {
  markStateChange()
}, { deep: true })

onBeforeRouteLeave((_to, _from, next) => {
  if (!isDirty.value) {
    next()
    return
  }
  const ok = window.confirm('You have unsaved changes. Leave without saving?')
  next(ok)
})

function onBeforeUnload(e: BeforeUnloadEvent) {
  if (!isDirty.value) return
  e.preventDefault()
  e.returnValue = ''
}

onMounted(async () => {
  try {
    const systemConfig = await getSystemConfig()
    const rawHealthy = Number(systemConfig?.settings?.workflowGovernanceHealthyThreshold)
    const rawWarning = Number(systemConfig?.settings?.workflowGovernanceWarningThreshold)
    const healthy = Number.isFinite(rawHealthy) ? Math.max(0, Math.min(1, rawHealthy)) : 0.1
    const warning = Number.isFinite(rawWarning) ? Math.max(healthy, Math.min(1, rawWarning)) : 0.3
    governanceHealthyThreshold.value = healthy
    governanceWarningThreshold.value = warning
  } catch {
    governanceHealthyThreshold.value = 0.1
    governanceWarningThreshold.value = 0.3
  }
  await refreshBackendRecommendations()
  try {
    const wf = await getWorkflow(workflowId)
    workflowName.value = wf.name || 'Untitled Workflow'
    workflowVersion.value = wf.latest_version_id ? `v: ${String(wf.latest_version_id).slice(0, 8)}` : ''

    // 优先使用已发布版本，其次 latest 版本；如果都没有，则保持默认起始节点
    const baseVersionId = (wf.published_version_id as string | null) || (wf.latest_version_id as string | null) || null
    if (baseVersionId) {
      try {
        const version = await getWorkflowVersion(workflowId, baseVersionId)
        if (version.dag) {
          const { nodes, edges } = fromWorkflowDag(version.dag)
          editorNodes.value = nodes
          editorEdges.value = edges
          const gc = (version.dag.global_config || {}) as Record<string, unknown>
          const reflector = (gc.reflector || {}) as Record<string, unknown>
          const mr = Number(reflector.max_retries)
          const ri = Number(reflector.retry_interval_seconds)
          reflectorMaxRetries.value = Number.isFinite(mr) ? mr : 0
          reflectorRetryIntervalSeconds.value = Number.isFinite(ri) ? ri : 1
          reflectorFallbackAgentId.value = String(reflector.fallback_agent_id || '')
        }
      } catch (e) {
        console.error('Failed to load workflow version DAG:', e)
        // 保持默认 start 节点，允许用户继续编辑
      }
    }
  } catch {
    workflowName.value = 'Untitled Workflow'
  }

  // 如果存在本地编辑草稿，让用户选择是否覆盖为草稿快照
  tryRestoreDraft()

  const initialSig = snapshotSignature(captureSnapshot())
  lastSnapshotSignature.value = initialSig
  lastSavedSignature.value = initialSig
  lastBackendDraftSignature.value = initialSig
  recalcDirty()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
})
onUnmounted(() => {
  if (autosaveTimer != null) window.clearTimeout(autosaveTimer)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<template>
  <div class="flex flex-col h-full bg-background">
    <!-- Top bar -->
    <div class="flex items-center gap-4 px-6 py-4 border-b border-border/50 shrink-0">
      <Button variant="ghost" size="icon" @click="goBack">
        <ArrowLeft class="w-5 h-5" />
      </Button>
      <div class="flex items-center gap-3 min-w-0 flex-1">
        <input
          v-model="workflowName"
          type="text"
          class="font-semibold text-lg bg-transparent border-b border-transparent hover:border-border focus:border-primary focus:outline-none px-1 py-0.5 min-w-0 max-w-md"
          placeholder="Workflow name"
        />
        <div class="text-sm text-muted-foreground shrink-0">{{ workflowVersion }}</div>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" class="gap-2" :disabled="undoStack.length === 0" @click="undo">
          <Undo2 class="w-4 h-4" />
          撤销
        </Button>
        <Button variant="outline" size="sm" class="gap-2" :disabled="redoStack.length === 0" @click="redo">
          <Redo2 class="w-4 h-4" />
          重做
        </Button>
        <Button variant="outline" size="sm" class="gap-2" @click="runPreflightCheck">
          运行前检查
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="sm" class="gap-2">
              <Play class="w-4 h-4" />
              {{ t('workflow_editor.run') }}
              <ChevronDown class="w-3.5 h-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem @click="runWorkflowSaveAndRun">先保存当前草稿并运行</DropdownMenuItem>
            <DropdownMenuItem @click="runWorkflowPublishedOnly">直接运行已发布版本</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="outline" size="sm" class="gap-2" :disabled="saveInProgress" @click="saveWorkflow">
          <Loader2 v-if="saveInProgress" class="w-4 h-4 animate-spin" />
          <Save v-else class="w-4 h-4" />
          {{ saveInProgress ? '保存中...' : '保存为新版本' }}<span v-if="isDirty && !saveInProgress" class="ml-1 text-amber-500">*</span>
        </Button>
        <Button
          size="sm"
          class="gap-2"
          variant="outline"
          disabled
          title="功能开发中，敬请期待"
        >
          <Rocket class="w-4 h-4 opacity-50" />
          <span class="opacity-70">{{ t('workflow_editor.deploy') }}</span>
        </Button>
      </div>
    </div>
    <div class="px-6 py-3 border-b border-border/40 bg-muted/20 flex items-center gap-3">
      <span class="text-sm font-medium">智能推荐模板</span>
      <select
        v-model="selectedTemplateId"
        class="h-8 min-w-[220px] rounded-md border border-input bg-background px-2 text-sm"
      >
        <option
          v-for="tpl in recommendedTemplates"
          :key="tpl.id"
          :value="tpl.id"
        >
          {{ tpl.name }}（推荐分: {{ tpl.score }}）
        </option>
      </select>
      <Button variant="outline" size="sm" @click="applyTemplate">一键导入模板</Button>
      <span class="text-xs text-muted-foreground">
        {{ templates.find((t) => t.id === selectedTemplateId)?.description }}
      </span>
      <span v-if="selectedRecommendationReason" class="text-xs text-muted-foreground">
        推荐原因：{{ selectedRecommendationReason }}
      </span>
      <div v-if="selectedRecommendationChips.length" class="flex items-center gap-2 flex-wrap">
        <button
          v-for="chip in selectedRecommendationChips"
          :key="chip.key"
          type="button"
          class="rounded-full border border-border/70 bg-background px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted"
          :class="activeRecommendationPairKey === chip.key ? 'border-primary text-primary' : ''"
          :title="chip.detail"
          @click="onRecommendationChipClick(chip)"
        >
          {{ chip.label }}
        </button>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <span class="text-xs text-muted-foreground">模板节点预览：</span>
        <button
          v-for="node in previewTemplateSkillNodes"
          :key="node.nodeId"
          type="button"
          class="rounded border px-2 py-0.5 text-[11px]"
          :data-tool-name="node.toolName"
          :class="activeRecommendationPairKey.includes(node.toolName) ? 'border-primary text-primary bg-primary/10' : 'border-border/70 text-muted-foreground bg-background'"
          :title="node.nodeId"
        >
          {{ node.label }} · {{ node.toolName }}
        </button>
      </div>
    </div>
    <div class="px-6 py-3 border-b border-border/40 bg-muted/20">
      <div class="text-sm font-medium mb-2">Reflector 默认策略（全局）</div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <label class="flex flex-col gap-1 text-xs text-muted-foreground">
          最大重试次数 (0-20)
          <input
            v-model.number="reflectorMaxRetries"
            type="number"
            min="0"
            max="20"
            class="h-8 rounded border border-input bg-background px-2 text-sm text-foreground"
          />
        </label>
        <label class="flex flex-col gap-1 text-xs text-muted-foreground">
          重试间隔秒数 (0-60)
          <input
            v-model.number="reflectorRetryIntervalSeconds"
            type="number"
            min="0"
            max="60"
            step="0.1"
            class="h-8 rounded border border-input bg-background px-2 text-sm text-foreground"
          />
        </label>
        <label class="flex flex-col gap-1 text-xs text-muted-foreground">
          备用 Agent ID
          <input
            v-model="reflectorFallbackAgentId"
            type="text"
            maxlength="512"
            placeholder="agent.worker.backup"
            class="h-8 rounded border border-input bg-background px-2 text-sm text-foreground"
          />
        </label>
      </div>
      <div class="mt-3 rounded border border-border/60 bg-background/80 px-3 py-2 text-xs">
        <div class="font-medium mb-1">最终生效策略预览（当前选中节点）</div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
          <div>
            <span class="text-muted-foreground">重试次数：</span>
            <span class="font-medium">{{ effectiveReflectorPolicy.maxRetries }}</span>
            <span class="ml-1 text-muted-foreground">
              (来源：{{ effectiveReflectorPolicy.maxRetriesSource === 'node' ? '节点覆盖' : '工作流全局' }})
            </span>
          </div>
          <div>
            <span class="text-muted-foreground">重试间隔：</span>
            <span class="font-medium">{{ effectiveReflectorPolicy.retryIntervalSeconds }}s</span>
            <span class="ml-1 text-muted-foreground">
              (来源：{{ effectiveReflectorPolicy.retryIntervalSource === 'node' ? '节点覆盖' : '工作流全局' }})
            </span>
          </div>
          <div>
            <span class="text-muted-foreground">备用 Agent：</span>
            <span class="font-medium">{{ effectiveReflectorPolicy.fallbackAgentId || '未配置' }}</span>
            <span class="ml-1 text-muted-foreground">
              (来源：{{ effectiveReflectorPolicy.fallbackSource === 'node' ? '节点覆盖' : '工作流全局' }})
            </span>
          </div>
        </div>
        <div class="mt-1 text-muted-foreground">
          当前节点类型：{{ effectiveReflectorPolicy.nodeType || '未选中' }}（仅当节点配置包含 reflector_* 字段时会覆盖全局）
        </div>
      </div>
      <div class="mt-3 rounded border border-border/60 bg-background/80 px-3 py-2 text-xs">
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-2">
            <div class="font-medium">节点级覆盖巡检</div>
            <span
              class="inline-flex items-center rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
              :title="`覆盖节点 ${reflectorCoverageSummary.ratioText}`"
            >
              覆盖节点 {{ reflectorCoverageSummary.ratioText }}
            </span>
            <span
              :class="[
                'inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]',
                governanceMaturity.toneClass,
              ]"
            >
              {{ governanceMaturity.level }}
            </span>
          </div>
          <div class="flex items-center gap-3">
            <button
              class="text-xs text-primary hover:underline"
              type="button"
              @click="openGovernanceSnapshotImport"
            >
              导入治理快照
            </button>
            <button
              class="text-xs text-primary hover:underline"
              type="button"
              @click="exportReflectorGovernanceSnapshot"
            >
              导出治理快照
            </button>
            <button
              v-if="reflectorOverrideNodes.length > 0"
              class="text-xs text-destructive hover:underline"
              type="button"
              @click="clearAllReflectorOverrides"
            >
              清除全部覆盖
            </button>
          </div>
        </div>
        <div class="mb-2 text-muted-foreground">
          治理建议：{{ governanceMaturity.hint }}
        </div>
        <div v-if="reflectorOverrideNodes.length === 0" class="text-muted-foreground">
          当前流程没有节点覆盖 reflector 全局策略。
        </div>
        <div class="mb-2 text-muted-foreground">
          字段分布：
          max_retries={{ reflectorOverrideFieldStats.retriesCount }}，
          retry_interval_seconds={{ reflectorOverrideFieldStats.intervalCount }}，
          fallback_agent_id={{ reflectorOverrideFieldStats.fallbackCount }}
        </div>
        <div v-if="importedGovernanceError" class="mb-2 text-destructive">
          {{ importedGovernanceError }}
        </div>
        <div v-else-if="governanceUiMessage" class="mb-2 text-amber-600 dark:text-amber-400">
          {{ governanceUiMessage }}
        </div>
        <div v-if="importedGovernanceSnapshot" class="mb-2 rounded border border-dashed border-border px-2 py-2">
          <div class="flex items-center justify-between mb-1">
            <div class="font-medium">导入快照预览（只读，不影响当前配置）</div>
            <button
              class="text-xs text-muted-foreground hover:underline"
              type="button"
              @click="clearImportedGovernanceSnapshot"
            >
              关闭预览
            </button>
          </div>
          <div class="text-muted-foreground">
            workflow={{ importedGovernanceSnapshot.workflow_name || '-' }}
            ({{ importedGovernanceSnapshot.workflow_id || '-' }})，
            exported_at={{ importedGovernanceSnapshot.exported_at || '-' }}
          </div>
          <div class="text-muted-foreground">
            覆盖节点={{ importedGovernanceSnapshot.coverage?.ratioText || '-' }}；
            字段分布：
            max_retries={{ importedGovernanceSnapshot.field_distribution?.retriesCount ?? '-' }}，
            retry_interval_seconds={{ importedGovernanceSnapshot.field_distribution?.intervalCount ?? '-' }}，
            fallback_agent_id={{ importedGovernanceSnapshot.field_distribution?.fallbackCount ?? '-' }}
          </div>
          <div v-if="importedGovernanceDiff" class="mt-1">
            <div class="text-muted-foreground mb-1">与当前差异：</div>
            <div class="flex flex-wrap gap-2">
              <span :class="['inline-flex items-center rounded border border-border px-1.5 py-0.5', diffToneClass(importedGovernanceDiff.coverageDelta)]">
                覆盖节点Δ={{ importedGovernanceDiff.coverageDelta >= 0 ? '+' : '' }}{{ importedGovernanceDiff.coverageDelta }}
              </span>
              <span :class="['inline-flex items-center rounded border border-border px-1.5 py-0.5', diffToneClass(importedGovernanceDiff.retriesDelta)]">
                max_retriesΔ={{ importedGovernanceDiff.retriesDelta >= 0 ? '+' : '' }}{{ importedGovernanceDiff.retriesDelta }}
              </span>
              <span :class="['inline-flex items-center rounded border border-border px-1.5 py-0.5', diffToneClass(importedGovernanceDiff.intervalDelta)]">
                retry_interval_secondsΔ={{ importedGovernanceDiff.intervalDelta >= 0 ? '+' : '' }}{{ importedGovernanceDiff.intervalDelta }}
              </span>
              <span :class="['inline-flex items-center rounded border border-border px-1.5 py-0.5', diffToneClass(importedGovernanceDiff.fallbackDelta)]">
                fallback_agent_idΔ={{ importedGovernanceDiff.fallbackDelta >= 0 ? '+' : '' }}{{ importedGovernanceDiff.fallbackDelta }}
              </span>
            </div>
          </div>
          <div
            v-if="importedGovernanceDiff && (importedGovernanceDiff.addedNodeIds.length || importedGovernanceDiff.removedNodeIds.length)"
            class="mt-1"
          >
            <div class="text-muted-foreground mb-1">节点清单差异：</div>
            <div class="flex flex-wrap gap-2">
              <span
                v-for="nodeId in importedGovernanceDiff.addedNodeIds"
                :key="`added-${nodeId}`"
                class="inline-flex cursor-pointer items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-700 hover:opacity-80 dark:text-emerald-300"
                @click="focusNodeFromGovernanceDiff(nodeId)"
              >
                + {{ nodeId }}
              </span>
              <span
                v-for="nodeId in importedGovernanceDiff.removedNodeIds"
                :key="`removed-${nodeId}`"
                class="inline-flex cursor-pointer items-center rounded border border-destructive/40 bg-destructive/10 px-1.5 py-0.5 text-destructive hover:opacity-80"
                @click="focusNodeFromGovernanceDiff(nodeId)"
              >
                - {{ nodeId }}
              </span>
            </div>
          </div>
        </div>
        <div v-else class="space-y-1">
          <div
            v-for="item in reflectorOverrideNodes"
            :key="item.nodeId"
            class="flex flex-wrap items-center gap-2"
          >
            <button
              class="text-primary hover:underline"
              type="button"
              @click="onSelectNodeById(item.nodeId)"
            >
              {{ item.label }} ({{ item.nodeId }})
            </button>
            <span class="text-muted-foreground">类型: {{ item.type }}</span>
            <span class="text-muted-foreground">覆盖字段: {{ item.overrideKeys.join(', ') }}</span>
            <button
              class="text-xs text-destructive hover:underline"
              type="button"
              @click="clearNodeReflectorOverrides(item.nodeId)"
            >
              清除覆盖
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 校验错误面板：点击定位节点 -->
    <div v-if="validationErrors.length" class="mx-6 mb-2 rounded-lg border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm">
      <p class="font-medium text-amber-800 dark:text-amber-400 mb-2">保存前校验未通过</p>
      <ul class="space-y-1">
        <li
          v-for="(e, i) in validationErrors"
          :key="i"
          class="cursor-pointer hover:underline text-amber-700 dark:text-amber-300"
          @click="onSelectNodeById(e.nodeId)"
        >
          [{{ e.nodeLabel || e.nodeId }}] {{ renderValidationError(e) }}
        </li>
      </ul>
    </div>

    <!-- 草稿恢复提示条（非阻断） -->
    <div v-if="draftRestorePending" class="mx-6 mb-2 rounded-lg border border-blue-500/50 bg-blue-500/10 px-4 py-2 flex items-center justify-between text-sm">
      <span class="text-blue-800 dark:text-blue-200">检测到未保存草稿</span>
      <div class="flex gap-2">
        <Button variant="outline" size="sm" @click="acceptDraftRestore">恢复草稿</Button>
        <Button variant="ghost" size="sm" @click="dismissDraftRestore">丢弃草稿</Button>
      </div>
    </div>

    <!-- Three columns -->
    <div class="flex flex-1 min-h-0">
      <!-- Left: Node Library -->
      <aside class="w-56 shrink-0 flex flex-col border-r border-border/50" aria-label="节点库面板">
        <NodeLibrary />
      </aside>

      <!-- Center: Canvas -->
      <main class="flex-1 min-w-0 flex flex-col p-4">
        <WorkflowCanvas
          :nodes="editorNodes"
          :edges="editorEdges"
          :focus-node-id="canvasFocusNodeId"
          @update:nodes="onNodesUpdate"
          @update:edges="onEdgesUpdate"
          @select-node="onSelectNode"
          @select-node-by-id="onSelectNodeById"
          @select-edge="onSelectEdge"
        />
      </main>

      <!-- Right: Node Config -->
      <aside class="w-80 shrink-0 flex flex-col border-l border-border/50" aria-label="节点配置面板">
        <NodeConfigPanel
          :node="selectedNode"
          :selected-node-id="selectedNodeId"
          :edge="selectedEdge"
          :nodes="editorNodes"
          :editor-workflow-id="workflowId"
          :selected-model-id="selectedNodeModelId"
          :selected-model-display-name="selectedNodeModelDisplayName"
          :selected-agent-id="selectedNodeAgentId"
          :selected-agent-display-name="selectedNodeAgentDisplayName"
          @close="onCloseConfigPanel"
          @update:config="onUpdateConfig"
          @delete-node="removeNode"
          @update:edge="onUpdateEdge"
          @delete-edge="removeEdge"
        />
      </aside>
    </div>
  </div>
</template>
