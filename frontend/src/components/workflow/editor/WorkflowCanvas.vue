<script setup lang="ts">
import { markRaw, nextTick, onMounted, onUnmounted, ref, provide, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { VueFlow } from '@vue-flow/core'
import { Search, ZoomIn, ZoomOut, ScanSearch, FolderTree } from 'lucide-vue-next'
import { registerWorkflowCanvasSelect, registerWorkflowGroupResizeStart } from './canvasSelection'
import type { Node, Edge, NodeChange, EdgeChange } from '@vue-flow/core'
import WorkflowNode from './nodes/WorkflowNode.vue'
import FlowCoordBridge from './FlowCoordBridge.vue'
import type { WorkflowNodeData } from './types'

const props = withDefaults(
  defineProps<{
    nodes?: Node<WorkflowNodeData>[]
    edges?: Edge[]
    focusNodeId?: string | null
  }>(),
  { nodes: () => [], edges: () => [], focusNodeId: null }
)
const FLOW_ID = 'workflow-editor-canvas'
const SNAP_GRID: [number, number] = [16, 16]
const LARGE_GRAPH_NODE_THRESHOLD = 50
const { t } = useI18n()

const emit = defineEmits<{
  'update:nodes': [Node<WorkflowNodeData>[]]
  'update:edges': [Edge[]]
  'select-node': [Node<WorkflowNodeData> | null]
  'select-node-by-id': [string]
  'select-edge': [Edge | null]
}>()

function normalizeNodes(list: Node<WorkflowNodeData>[]): Node<WorkflowNodeData>[] {
  return (list ?? []).map((n) => ({
    ...n,
    draggable: (n as any).draggable !== false,
  } as Node<WorkflowNodeData>))
}

const nodesRef = ref<Node<WorkflowNodeData>[]>(normalizeNodes(props.nodes ?? []))
const edgesRef = ref<Edge[]>(props.edges ?? [])
const enableLargeGraphOptimization = ref((props.nodes?.length || 0) > LARGE_GRAPH_NODE_THRESHOLD)

// 若在 onNodesChange 里 emit 后立刻用 props 覆盖 nodesRef，会冲掉 Vue Flow 刚写入的拖动位置；用标志位在“刚 emit”的下一拍用 ref 的 position 做 merge
let justEmittedNodes = false
let justEmittedEdges = false

watch(
  () => props.nodes,
  (v) => {
    const next = v ?? []
    if (justEmittedNodes) {
      const currentPositions = new Map(nodesRef.value.map((n) => [n.id, n.position]))
      nodesRef.value = normalizeNodes(next).map((p) => ({
        ...p,
        position: currentPositions.get(p.id) ?? p.position,
      })) as Node<WorkflowNodeData>[]
      nextTick(() => { justEmittedNodes = false })
    } else {
      nodesRef.value = normalizeNodes(next)
    }
    enableLargeGraphOptimization.value = (next?.length || 0) > LARGE_GRAPH_NODE_THRESHOLD
  },
  { immediate: true, deep: true }
)
watch(
  () => props.edges,
  (v) => {
    if (justEmittedEdges) {
      nextTick(() => { justEmittedEdges = false })
    }
    edgesRef.value = v ?? []
  },
  { immediate: true, deep: true }
)
watch(
  () => props.focusNodeId,
  (nodeId) => {
    const id = String(nodeId || '').trim()
    if (!id) return
    if (!nodesRef.value.some((n) => n.id === id)) return
    locateNode(id)
  }
)

const nodeTypes = { workflow: markRaw(WorkflowNode) }

function defaultDataForType(type: WorkflowNodeData['type']): WorkflowNodeData {
  return {
    type,
    label:
      type === 'llm'
        ? t('workflow_editor.node_llm')
        : type === 'agent'
          ? t('workflow_editor.node_agent')
          : type === 'skill'
            ? t('workflow_editor.node_skill')
            : type === 'sub_workflow'
              ? t('workflow_editor.node_sub_workflow')
              : t('workflow_editor.node_default'),
    subtitle:
      type === 'llm'
        ? t('workflow_editor.default_select_model')
        : type === 'skill'
          ? t('workflow_editor.default_select_tool')
          : type === 'agent'
            ? t('workflow_editor.default_select_agent')
            : type === 'sub_workflow'
              ? t('workflow_editor.default_subworkflow_id')
              : undefined,
    config:
      type === 'llm'
        ? { model_id: '' }
        : type === 'skill'
          ? { tool_name: '' }
          : type === 'agent'
            ? { agent_id: '', agent_display_name: '' }
            : type === 'sub_workflow'
              ? {
                  workflow_node_type: 'sub_workflow',
                  target_workflow_id: '',
                  target_version_selector: 'fixed',
                }
              : {},
  }
}

// Flag to prevent conflict between custom click and VueFlow's selection
let isSelectingViaClick = false
let lastSelectedNodeId: string | null = null
// 刚 drop 到画布的新节点 id，在 selectNodeById 执行前若 onNodesChange 发了 deselect，保留对该节点的选中避免配置一闪而过
let recentlyAddedNodeId: string | null = null
// drop 后短时间内不再把 onNodesChange 的 nodes 同步给父组件，避免第二次 onNodesUpdate 与首次竞争导致配置面板不显示（与 edge 点击不同，node 依赖 editorNodes 中的项）
let dropCooldownUntil = 0
const DROP_COOLDOWN_MS = 220

// 坐标转换由 VueFlow 内部的 FlowCoordBridge 设置，避免在 VueFlow 挂载前调用 useVueFlow 导致白屏
const screenToFlowCoordinateRef = ref<(pos: { x: number; y: number }) => { x: number; y: number }>((pos) => pos)
provide('workflowCanvasSetScreenToFlowCoordinate', (fn: (pos: { x: number; y: number }) => { x: number; y: number }) => {
  screenToFlowCoordinateRef.value = fn
})
type CanvasControls = {
  fitView?: (params?: { duration?: number; padding?: number }) => void
  zoomIn?: (options?: { duration?: number }) => void
  zoomOut?: (options?: { duration?: number }) => void
  setCenter?: (x: number, y: number, options?: { zoom?: number; duration?: number }) => void
}
const canvasControlsRef = ref<CanvasControls>({})
provide('workflowCanvasSetControls', (controls: CanvasControls) => {
  canvasControlsRef.value = controls
})

const searchKeyword = ref('')
const selectedSearchNodeId = ref('')
const VIEWPORT_ANIMATION_MS = 220
const searchInFocusedGroupOnly = ref(false)
const searchInputRef = ref<HTMLInputElement | null>(null)

const groupName = ref('')
const focusedGroupId = ref<string | null>(null)
const renamingGroupId = ref<string | null>(null)
const showShortcutHelp = ref(false)
let highlightTimer: number | null = null
const groupResizeState = ref<{
  groupId: string
  startClientX: number
  startClientY: number
  startGroupX: number
  startGroupY: number
  startWidth: number
  startHeight: number
  rawWidth: number
  rawHeight: number
  currentWidth: number
  currentHeight: number
  cursorX: number
  cursorY: number
} | null>(null)

function nodeLabel(node: Node<WorkflowNodeData>): string {
  return String(node.data?.label || node.id)
}

function isGroupNode(node: Node<WorkflowNodeData>): boolean {
  return node.data?.type === 'group'
}

function searchNodeOptions() {
  const keyword = searchKeyword.value.trim().toLowerCase()
  const activeGroupId = focusedGroupId.value
  return nodesRef.value
    .filter((n) => !isGroupNode(n))
    .filter((n) => {
      if (!searchInFocusedGroupOnly.value || !activeGroupId) return true
      return (n as any).parentNode === activeGroupId
    })
    .filter((n) => {
      if (!keyword) return true
      return `${nodeLabel(n)} ${n.id}`.toLowerCase().includes(keyword)
    })
}
function isNodeInsideFocusedScope(node: Node<WorkflowNodeData>): boolean {
  if (!focusedGroupId.value) return true
  return node.id === focusedGroupId.value || (node as any).parentNode === focusedGroupId.value
}
function groupChildren(groupId: string) {
  return nodesRef.value.filter((n) => (n as any).parentNode === groupId && !isGroupNode(n))
}
function syncGroupMeta(groupId: string) {
  const count = groupChildren(groupId).length
  nodesRef.value = nodesRef.value.map((node) => {
    if (node.id !== groupId || !isGroupNode(node)) return node
    const cfg = { ...((node.data?.config as Record<string, unknown>) || {}) } as Record<string, unknown>
    cfg.__nodeCount = count
    const collapsed = cfg.__collapsed === true
    return {
      ...node,
      data: {
        ...node.data,
        config: cfg,
        subtitle: `${count} nodes${collapsed ? ' (collapsed)' : ''}`,
      } as WorkflowNodeData,
    } as Node<WorkflowNodeData>
  })
}
function selectedGroupNode() {
  const selected = nodesRef.value.find((n) => (n as any).selected && isGroupNode(n))
  if (selected) return selected
  if (!lastSelectedNodeId) return null
  return nodesRef.value.find((n) => n.id === lastSelectedNodeId && isGroupNode(n)) ?? null
}
function getNodeSize(node: Node<WorkflowNodeData>) {
  return {
    width: Math.max(80, Number((node as any).width) || 180),
    height: Math.max(40, Number((node as any).height) || 80),
  }
}
function snapSize(value: number, step: number): number {
  return Math.round(value / step) * step
}
function minGroupSizeForChildren(groupId: string): { width: number; height: number } {
  const children = groupChildren(groupId)
  if (!children.length) return { width: 220, height: 140 }
  const padding = 16
  const maxRight = Math.max(...children.map((node) => node.position.x + getNodeSize(node).width))
  const maxBottom = Math.max(...children.map((node) => node.position.y + getNodeSize(node).height))
  return {
    width: Math.max(220, maxRight + padding),
    height: Math.max(140, maxBottom + padding),
  }
}
function clampChildPositionInGroup(node: Node<WorkflowNodeData>): Node<WorkflowNodeData> {
  const parentId = (node as any).parentNode as string | undefined
  if (!parentId) return node
  const parent = nodesRef.value.find((n) => n.id === parentId && isGroupNode(n))
  if (!parent) return node
  const parentSize = {
    width: Math.max(220, Number((parent.style as any)?.width) || Number((parent as any).width) || 220),
    height: Math.max(140, Number((parent.style as any)?.height) || Number((parent as any).height) || 140),
  }
  const childSize = getNodeSize(node)
  const padding = 10
  const maxX = Math.max(padding, parentSize.width - childSize.width - padding)
  const maxY = Math.max(padding, parentSize.height - childSize.height - padding)
  const nextX = Math.min(maxX, Math.max(padding, node.position.x))
  const nextY = Math.min(maxY, Math.max(padding, node.position.y))
  if (nextX === node.position.x && nextY === node.position.y) return node
  return {
    ...node,
    position: { x: nextX, y: nextY },
  } as Node<WorkflowNodeData>
}
function withHighlight(node: Node<WorkflowNodeData>, active: boolean): Node<WorkflowNodeData> {
  const cfg = { ...((node.data?.config as Record<string, unknown>) || {}) }
  if (active) cfg.__highlight = true
  else delete cfg.__highlight
  return {
    ...node,
    data: {
      ...node.data,
      config: cfg,
    } as WorkflowNodeData,
  } as Node<WorkflowNodeData>
}
function isGroupCollapsed(group: Node<WorkflowNodeData>): boolean {
  const cfg = (group.data?.config as Record<string, unknown>) || {}
  return cfg.__collapsed === true
}
function updateGroupCollapsed(groupId: string, collapsed: boolean) {
  const count = groupChildren(groupId).length
  nodesRef.value = nodesRef.value.map((node) => {
    if (node.id === groupId) {
      const nextConfig = { ...((node.data?.config as Record<string, unknown>) || {}), __collapsed: collapsed, __nodeCount: count }
      return {
        ...node,
        data: {
          ...node.data,
          config: nextConfig,
          subtitle: `${groupChildren(groupId).length} nodes${collapsed ? ' (collapsed)' : ''}`,
        } as WorkflowNodeData,
      } as Node<WorkflowNodeData>
    }
    if ((node as any).parentNode === groupId && !isGroupNode(node)) {
      return {
        ...node,
        hidden: collapsed,
      } as Node<WorkflowNodeData>
    }
    return node
  })
  emit('update:nodes', nodesRef.value)
}
function toggleSelectedGroupCollapse() {
  const group = selectedGroupNode()
  if (!group) return
  updateGroupCollapsed(group.id, !isGroupCollapsed(group))
}
function ungroupSelectedGroup() {
  const group = selectedGroupNode()
  if (!group) return
  const groupPos = group.position
  const groupId = group.id
  const nextNodes = nodesRef.value
    .filter((node) => node.id !== groupId)
    .map((node) => {
      if ((node as any).parentNode !== groupId || isGroupNode(node)) return node
      return {
        ...node,
        position: {
          x: groupPos.x + node.position.x,
          y: groupPos.y + node.position.y,
        },
        parentNode: undefined,
        extent: undefined,
        hidden: false,
        selected: true,
      } as Node<WorkflowNodeData>
    })
  nodesRef.value = nextNodes
  if (focusedGroupId.value === groupId) focusedGroupId.value = null
  emit('update:nodes', nodesRef.value)
  const first = nextNodes.find((n) => (n as any).selected)
  if (first) selectNodeById(first.id)
}
function renameSelectedGroup() {
  const group = selectedGroupNode()
  if (!group) return
  const nextName = groupName.value.trim()
  if (!nextName) return
  nodesRef.value = nodesRef.value.map((node) => {
    if (node.id !== group.id) return node
    return {
      ...node,
      data: {
        ...node.data,
        label: nextName,
      } as WorkflowNodeData,
    } as Node<WorkflowNodeData>
  })
  emit('update:nodes', nodesRef.value)
  renamingGroupId.value = null
}
function toggleFocusSelectedGroup() {
  const group = selectedGroupNode()
  if (!group) return
  const shouldFocus = focusedGroupId.value !== group.id
  focusedGroupId.value = shouldFocus ? group.id : null
  const activeGroupId = focusedGroupId.value
  nodesRef.value = nodesRef.value.map((node) => {
    const belongsToGroup = node.id === activeGroupId || (node as any).parentNode === activeGroupId
    const forceHiddenByCollapse = typeof (node as any).parentNode === 'string'
      ? (() => {
          const parent = nodesRef.value.find((n) => n.id === (node as any).parentNode)
          const cfg = (parent?.data?.config as Record<string, unknown>) || {}
          return cfg.__collapsed === true
        })()
      : false
    return {
      ...node,
      hidden: activeGroupId ? (!belongsToGroup || forceHiddenByCollapse) : forceHiddenByCollapse,
    } as Node<WorkflowNodeData>
  })
  emit('update:nodes', nodesRef.value)
  if (focusedGroupId.value) {
    nextTick(() => fitCanvas())
  }
}
function focusedGroupLabel() {
  if (!focusedGroupId.value) return ''
  const node = nodesRef.value.find((n) => n.id === focusedGroupId.value)
  return node ? nodeLabel(node) : ''
}
function clearFocusMode() {
  if (!focusedGroupId.value) return
  focusedGroupId.value = null
  nodesRef.value = nodesRef.value.map((node) => {
    const parentId = (node as any).parentNode as string | undefined
    const forceHiddenByCollapse = parentId
      ? (() => {
          const parent = nodesRef.value.find((n) => n.id === parentId)
          const cfg = (parent?.data?.config as Record<string, unknown>) || {}
          return cfg.__collapsed === true
        })()
      : false
    return { ...node, hidden: forceHiddenByCollapse } as Node<WorkflowNodeData>
  })
  searchInFocusedGroupOnly.value = false
  emit('update:nodes', nodesRef.value)
}
function resizeSelectedGroup(scale: number) {
  const group = selectedGroupNode()
  if (!group) return
  const currentW = Math.max(220, Number((group.style as any)?.width) || Number((group as any).width) || 220)
  const currentH = Math.max(140, Number((group.style as any)?.height) || Number((group as any).height) || 140)
  const nextW = Math.max(220, Math.round(currentW * scale))
  const nextH = Math.max(140, Math.round(currentH * scale))
  nodesRef.value = nodesRef.value.map((node) => {
    if (node.id === group.id) {
      return {
        ...node,
        style: {
          ...((node.style as Record<string, unknown>) || {}),
          width: nextW,
          height: nextH,
        },
      } as Node<WorkflowNodeData>
    }
    if ((node as any).parentNode === group.id) {
      return clampChildPositionInGroup(node)
    }
    return node
  })
  syncGroupMeta(group.id)
  emit('update:nodes', nodesRef.value)
}
function applyGroupSize(
  groupId: string,
  width: number,
  height: number,
  options?: {
    centerScale?: boolean
    startWidth?: number
    startHeight?: number
    startGroupX?: number
    startGroupY?: number
    emitUpdate?: boolean
  }
) {
  const minSize = minGroupSizeForChildren(groupId)
  const nextW = Math.max(minSize.width, snapSize(width, SNAP_GRID[0]))
  const nextH = Math.max(minSize.height, snapSize(height, SNAP_GRID[1]))
  const centerScale = options?.centerScale === true
  const emitUpdate = options?.emitUpdate !== false
  const startWidth = options?.startWidth ?? nextW
  const startHeight = options?.startHeight ?? nextH
  const startGroupX = options?.startGroupX ?? 0
  const startGroupY = options?.startGroupY ?? 0
  const dw = nextW - startWidth
  const dh = nextH - startHeight
  nodesRef.value = nodesRef.value.map((node) => {
    if (node.id === groupId) {
      const nextPosition = centerScale
        ? { x: startGroupX - dw / 2, y: startGroupY - dh / 2 }
        : node.position
      return {
        ...node,
        position: nextPosition,
        style: {
          ...((node.style as Record<string, unknown>) || {}),
          width: nextW,
          height: nextH,
        },
      } as Node<WorkflowNodeData>
    }
    if ((node as any).parentNode === groupId) {
      const shifted = centerScale
        ? ({
            ...node,
            position: {
              x: node.position.x + dw / 2,
              y: node.position.y + dh / 2,
            },
          } as Node<WorkflowNodeData>)
        : node
      return clampChildPositionInGroup(shifted)
    }
    return node
  })
  syncGroupMeta(groupId)
  if (emitUpdate) emit('update:nodes', nodesRef.value)
}
function startGroupResize(nodeId: string, clientX: number, clientY: number) {
  const group = nodesRef.value.find((n) => n.id === nodeId && isGroupNode(n))
  if (!group) return
  if (!isNodeInsideFocusedScope(group)) return
  const startWidth = Math.max(220, Number((group.style as any)?.width) || Number((group as any).width) || 220)
  const startHeight = Math.max(140, Number((group.style as any)?.height) || Number((group as any).height) || 140)
  groupResizeState.value = {
    groupId: nodeId,
    startClientX: clientX,
    startClientY: clientY,
    startGroupX: group.position.x,
    startGroupY: group.position.y,
    startWidth,
    startHeight,
    rawWidth: startWidth,
    rawHeight: startHeight,
    currentWidth: startWidth,
    currentHeight: startHeight,
    cursorX: clientX,
    cursorY: clientY,
  }
}
function onWindowMouseMove(e: MouseEvent) {
  const state = groupResizeState.value
  if (!state) return
  const dx = e.clientX - state.startClientX
  const dy = e.clientY - state.startClientY
  let nextW = state.startWidth + dx
  let nextH = state.startHeight + dy
  if (e.shiftKey) {
    const ratio = state.startWidth / Math.max(1, state.startHeight)
    if (Math.abs(dx) > Math.abs(dy)) nextH = nextW / ratio
    else nextW = nextH * ratio
  }
  applyGroupSize(state.groupId, nextW, nextH, {
    centerScale: e.altKey,
    startWidth: state.startWidth,
    startHeight: state.startHeight,
    startGroupX: state.startGroupX,
    startGroupY: state.startGroupY,
    emitUpdate: false,
  })
  groupResizeState.value = {
    ...state,
    rawWidth: Math.round(nextW),
    rawHeight: Math.round(nextH),
    currentWidth: Math.max(220, Math.round(nextW)),
    currentHeight: Math.max(140, Math.round(nextH)),
    cursorX: e.clientX,
    cursorY: e.clientY,
  }
}
function onWindowMouseUp() {
  if (!groupResizeState.value) return
  emit('update:nodes', nodesRef.value)
  groupResizeState.value = null
}
function onNodeDoubleClick({ node }: { node: Node<WorkflowNodeData> }) {
  if (!isGroupNode(node)) return
  if (!isNodeInsideFocusedScope(node)) return
  selectNodeById(node.id)
  groupName.value = nodeLabel(node)
  renamingGroupId.value = node.id
}
function confirmRenameFromInline() {
  if (!renamingGroupId.value) return
  renameSelectedGroup()
}

watch(searchKeyword, () => {
  const options = searchNodeOptions()
  if (!options.length) {
    selectedSearchNodeId.value = ''
    return
  }
  if (!options.some((n) => n.id === selectedSearchNodeId.value)) {
    selectedSearchNodeId.value = options[0]?.id ?? ''
  }
})
watch(
  () => nodesRef.value.map((n) => n.id).join('|'),
  () => {
    const options = searchNodeOptions()
    if (!options.length) {
      selectedSearchNodeId.value = ''
      return
    }
    if (!options.some((n) => n.id === selectedSearchNodeId.value)) {
      selectedSearchNodeId.value = options[0]?.id ?? ''
    }
  }
)

function moveSearchSelection(step: 1 | -1) {
  const options = searchNodeOptions()
  if (!options.length) return
  const currentIdx = options.findIndex((n) => n.id === selectedSearchNodeId.value)
  const base = currentIdx < 0 ? 0 : currentIdx
  const nextIdx = (base + step + options.length) % options.length
  selectedSearchNodeId.value = options[nextIdx]?.id ?? ''
}
function onSearchInputKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveSearchSelection(1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveSearchSelection(-1)
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    locateNode(selectedSearchNodeId.value)
  }
}

function locateNode(nodeId: string) {
  const node = nodesRef.value.find((n) => n.id === nodeId)
  if (!node) return
  selectNodeById(nodeId)
  if (highlightTimer != null) window.clearTimeout(highlightTimer)
  nodesRef.value = nodesRef.value.map((n) => withHighlight(n, n.id === nodeId))
  emit('update:nodes', nodesRef.value)
  highlightTimer = window.setTimeout(() => {
    nodesRef.value = nodesRef.value.map((n) => withHighlight(n, false))
    emit('update:nodes', nodesRef.value)
    highlightTimer = null
  }, 1200)
  const width = Number((node as any).width) || 180
  const height = Number((node as any).height) || 80
  canvasControlsRef.value.setCenter?.(node.position.x + width / 2, node.position.y + height / 2, {
    zoom: 1,
    duration: VIEWPORT_ANIMATION_MS,
  })
}

function fitCanvas() {
  canvasControlsRef.value.fitView?.({ duration: VIEWPORT_ANIMATION_MS, padding: 0.2 })
}

function zoomInCanvas() {
  canvasControlsRef.value.zoomIn?.({ duration: VIEWPORT_ANIMATION_MS })
}

function zoomOutCanvas() {
  canvasControlsRef.value.zoomOut?.({ duration: VIEWPORT_ANIMATION_MS })
}

function createGroupFromSelection() {
  const selectedNodes = nodesRef.value.filter((n) => (n as any).selected && !isGroupNode(n))
  if (!selectedNodes.length) return
  const minX = Math.min(...selectedNodes.map((n) => n.position.x))
  const minY = Math.min(...selectedNodes.map((n) => n.position.y))
  const maxX = Math.max(...selectedNodes.map((n) => n.position.x + (Number((n as any).width) || 180)))
  const maxY = Math.max(...selectedNodes.map((n) => n.position.y + (Number((n as any).height) || 80)))
  const padding = 28
  const groupX = minX - padding
  const groupY = minY - padding
  const groupId = `group_${Date.now()}`
  const title = groupName.value.trim() || `Group ${Date.now().toString().slice(-4)}`
  const groupNode = {
    id: groupId,
    type: 'workflow',
    position: { x: groupX, y: groupY },
    selected: true,
    draggable: true,
    data: {
      type: 'group',
      label: title,
      subtitle: `${selectedNodes.length} nodes`,
      config: {
        __canvasGroup: true,
        __nodeCount: selectedNodes.length,
      },
    },
    style: {
      width: Math.max(220, maxX - minX + padding * 2),
      height: Math.max(140, maxY - minY + padding * 2),
      zIndex: 0,
    },
  } as Node<WorkflowNodeData>
  const groupedNodes = nodesRef.value.map((node) => {
    if (!selectedNodes.some((s) => s.id === node.id)) return { ...node, selected: false } as Node<WorkflowNodeData>
    return {
      ...node,
      selected: false,
      parentNode: groupId,
      extent: 'parent',
      position: {
        x: node.position.x - groupX,
        y: node.position.y - groupY,
      },
    } as Node<WorkflowNodeData>
  })
  nodesRef.value = [...groupedNodes, groupNode]
  syncGroupMeta(groupId)
  emit('update:nodes', nodesRef.value)
  selectNodeById(groupId)
  groupName.value = ''
}

function onCanvasKeydown(e: KeyboardEvent) {
  const meta = e.metaKey || e.ctrlKey
  const target = e.target as HTMLElement | null
  if (e.key === 'F1' || (e.shiftKey && e.key === '/')) {
    e.preventDefault()
    showShortcutHelp.value = !showShortcutHelp.value
    return
  }
  if (e.key === '/') {
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
    e.preventDefault()
    searchInputRef.value?.focus()
    searchInputRef.value?.select()
    return
  }
  if (e.key === '?') {
    e.preventDefault()
    showShortcutHelp.value = !showShortcutHelp.value
    return
  }
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
  if (meta && e.key.toLowerCase() === 'f') {
    e.preventDefault()
    fitCanvas()
    return
  }
  if (meta && e.key.toLowerCase() === 'g') {
    e.preventDefault()
    if (e.shiftKey) ungroupSelectedGroup()
    else createGroupFromSelection()
    return
  }
  if (meta && e.key.toLowerCase() === 'e') {
    e.preventDefault()
    toggleSelectedGroupCollapse()
    return
  }
  if (meta && e.key === '=') {
    e.preventDefault()
    zoomInCanvas()
    return
  }
  if (meta && e.key === '-') {
    e.preventDefault()
    zoomOutCanvas()
    return
  }
  if (meta && e.key.toLowerCase() === 'r') {
    e.preventDefault()
    renameSelectedGroup()
    return
  }
  if (meta && e.key === ']') {
    e.preventDefault()
    resizeSelectedGroup(1.12)
    return
  }
  if (meta && e.key === '[') {
    e.preventDefault()
    resizeSelectedGroup(0.9)
    return
  }
  if (e.key === 'Escape') {
    if (renamingGroupId.value) {
      renamingGroupId.value = null
      return
    }
    if (showShortcutHelp.value) {
      showShortcutHelp.value = false
      return
    }
    clearFocusMode()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onCanvasKeydown)
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onCanvasKeydown)
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
  if (highlightTimer != null) window.clearTimeout(highlightTimer)
})

function selectNodeById(nodeId: string) {
  if (!nodeId) return
  isSelectingViaClick = true
  const list = nodesRef.value.map((n) => ({ ...n, selected: n.id === nodeId } as Node<WorkflowNodeData>))
  nodesRef.value = list
  emit('update:nodes', list)
  emit('select-node-by-id', nodeId)
  lastSelectedNodeId = nodeId
  const selected = list.find((n) => n.id === nodeId)
  if (selected && isGroupNode(selected)) {
    groupName.value = nodeLabel(selected)
  } else {
    renamingGroupId.value = null
  }
  emit('select-edge', null)
  setTimeout(() => { isSelectingViaClick = false }, 60)
}

// 必须在 setup 同步注册：子节点可能在 onMounted 之前就可交互；onMounted 过晚会导致 inject/回调未就绪
registerWorkflowCanvasSelect(selectNodeById)
onUnmounted(() => registerWorkflowCanvasSelect(null))
registerWorkflowGroupResizeStart(startGroupResize)
onUnmounted(() => registerWorkflowGroupResizeStart(null))

function onNodesChange(changes: NodeChange[]) {
  const inDropCooldown = Date.now() < dropCooldownUntil
  let shouldSnapPositions = false
  if (!inDropCooldown) {
    justEmittedNodes = true
    emit('update:nodes', nodesRef.value)
  }
  let hasSelectChange = false
  let draggingNodeId: string | null = null
  for (const change of changes) {
    if (change.type === 'position') {
      const changedId = (change as any).id as string | undefined
      if (changedId) {
        nodesRef.value = nodesRef.value.map((node) => (node.id === changedId ? clampChildPositionInGroup(node) : node))
      }
      const dragging = (change as any).dragging
      if (dragging) draggingNodeId = (change as any).id ?? null
      if (dragging === false) shouldSnapPositions = true
      continue
    }
    if (change.type === 'select') {
      hasSelectChange = true
      continue
    }
  }
  if (hasSelectChange) {
    if (isSelectingViaClick) return
    const current = nodesRef.value
    const selected = current.find((n) => (n as any).selected) as Node<WorkflowNodeData> | undefined
    if (selected) {
      emit('select-node-by-id', selected.id)
      lastSelectedNodeId = selected.id
    } else if (draggingNodeId) {
      emit('select-node-by-id', draggingNodeId)
      lastSelectedNodeId = draggingNodeId
    } else if (lastSelectedNodeId && current.some((n) => n.id === lastSelectedNodeId)) {
      emit('select-node-by-id', lastSelectedNodeId)
    } else if (recentlyAddedNodeId && current.some((n) => n.id === recentlyAddedNodeId)) {
      // 刚 drop 的新节点尚未被 selectNodeById 标记 selected，避免被清空导致配置面板一闪而过
      emit('select-node-by-id', recentlyAddedNodeId)
      lastSelectedNodeId = recentlyAddedNodeId
    } else {
      emit('select-node', null)
      lastSelectedNodeId = null
    }
    emit('select-edge', null)
  }
  if (shouldSnapPositions) {
    // Drag end alignment: keep nodes visually aligned for dense workflow layouts.
    nodesRef.value = nodesRef.value.map((node) => {
      const snapped = { ...node } as Node<WorkflowNodeData>
      snapped.position = {
        x: Math.round(node.position.x / SNAP_GRID[0]) * SNAP_GRID[0],
        y: Math.round(node.position.y / SNAP_GRID[1]) * SNAP_GRID[1],
      }
      return clampChildPositionInGroup(snapped)
    })
    emit('update:nodes', nodesRef.value)
  }
}

function onPaneClick(evt: MouseEvent) {
  const el = evt.target as HTMLElement
  if (el.closest('.vue-flow__node')) return
  if (nodesRef.value.some((n) => Boolean((n as any).dragging))) return
  nodesRef.value = nodesRef.value.map((n) => ({ ...n, selected: false } as Node<WorkflowNodeData>))
  emit('update:nodes', nodesRef.value)
  emit('select-node', null)
  lastSelectedNodeId = null
  emit('select-edge', null)
}

function onEdgesChange(_changes: EdgeChange[]) {
  justEmittedEdges = true
  emit('update:edges', edgesRef.value)
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  if (focusedGroupId.value) return
  const raw = e.dataTransfer?.getData('application/vnd.workflow-node')
  if (!raw) return
  try {
    const { type, label } = JSON.parse(raw) as { type: string; label: string }
    const pos = screenToFlowCoordinateRef.value({ x: e.clientX, y: e.clientY })
    const id = `node_${type}_${Date.now()}`
    const newNode = {
      id,
      type: 'workflow',
      position: pos,
      selected: true,
      data: { ...defaultDataForType(type as WorkflowNodeData['type']), label },
    } as Node<WorkflowNodeData>
    recentlyAddedNodeId = id
    lastSelectedNodeId = id
    dropCooldownUntil = Date.now() + DROP_COOLDOWN_MS
    const othersDeselected = nodesRef.value.map((n) => ({ ...n, selected: false } as Node<WorkflowNodeData>))
    nodesRef.value = [...othersDeselected, newNode]
    emit('update:nodes', nodesRef.value)
    emit('select-edge', null)
    emit('select-node-by-id', id)
    // 延迟再同步画布 selected 态并清除“刚添加”标记；cooldown 内 onNodesChange 不再 emit update:nodes，避免父组件二次 onNodesUpdate 冲掉配置
    setTimeout(() => {
      selectNodeById(id)
      recentlyAddedNodeId = null
    }, 50)
  } catch (_) {
    // ignore
  }
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

function onNodeClick({ node }: { node: Node<WorkflowNodeData> }) {
  if (!isNodeInsideFocusedScope(node)) return
  selectNodeById(node.id)
}

function onEdgeClick({ edge }: { edge: Edge }) {
  if (focusedGroupId.value) {
    const sourceNode = nodesRef.value.find((n) => n.id === edge.source)
    const targetNode = nodesRef.value.find((n) => n.id === edge.target)
    if (!sourceNode || !targetNode) return
    if (!isNodeInsideFocusedScope(sourceNode) || !isNodeInsideFocusedScope(targetNode)) return
  }
  const selected = (props.edges ?? []).find((e) => e.id === edge.id) ?? edge
  emit('select-edge', selected as Edge)
  emit('select-node', null)
}

function onConnect(connection: { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) {
  if (focusedGroupId.value) {
    const sourceNode = nodesRef.value.find((n) => n.id === connection.source)
    const targetNode = nodesRef.value.find((n) => n.id === connection.target)
    if (!sourceNode || !targetNode) return
    if (!isNodeInsideFocusedScope(sourceNode) || !isNodeInsideFocusedScope(targetNode)) return
  }
  const id = `e-${connection.source}-${connection.target}-${Date.now()}`
  const label = connection.sourceHandle && ['true', 'false', 'continue', 'exit'].includes(connection.sourceHandle)
    ? connection.sourceHandle
    : undefined
  const newEdge: Edge = {
    id,
    source: connection.source,
    target: connection.target,
    ...(label && { label }),
    ...(connection.sourceHandle != null && { sourceHandle: connection.sourceHandle }),
    ...(connection.targetHandle != null && { targetHandle: connection.targetHandle }),
  }
  edgesRef.value = [...edgesRef.value, newEdge]
  emit('update:edges', edgesRef.value)
}
</script>

<template>
  <div class="workflow-canvas-wrap h-full w-full relative">
    <div class="absolute left-3 top-3 z-20 flex items-center gap-2 rounded-lg border border-border/60 bg-background/95 px-2 py-2 shadow-sm backdrop-blur">
      <div class="flex items-center gap-1 rounded-md border border-border/60 px-2">
        <Search class="h-3.5 w-3.5 text-muted-foreground" />
        <input
          ref="searchInputRef"
          v-model="searchKeyword"
          type="text"
          placeholder="搜索节点"
          class="h-7 w-40 bg-transparent text-xs outline-none"
          @keydown="onSearchInputKeydown"
        />
      </div>
      <select
        v-model="selectedSearchNodeId"
        class="h-7 min-w-[170px] rounded-md border border-border/60 bg-background px-2 text-xs"
        @change="locateNode(selectedSearchNodeId)"
      >
        <option v-if="!searchNodeOptions().length" value="">无匹配节点</option>
        <option v-for="node in searchNodeOptions()" :key="node.id" :value="node.id">
          {{ nodeLabel(node) }}
        </option>
      </select>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="定位到当前搜索节点" aria-label="定位到当前搜索节点" @click="locateNode(selectedSearchNodeId)">
        定位
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="快捷键帮助（? / F1）" aria-label="打开快捷键帮助" @click="showShortcutHelp = !showShortcutHelp">
        ?
      </button>
      <label class="ml-1 flex items-center gap-1 text-[11px] text-muted-foreground">
        <input v-model="searchInFocusedGroupOnly" type="checkbox" :disabled="!focusedGroupId" />
        仅当前分组
      </label>
    </div>
    <div class="absolute right-3 top-3 z-20 flex items-center gap-1 rounded-lg border border-border/60 bg-background/95 px-2 py-2 shadow-sm backdrop-blur">
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted flex items-center gap-1" title="适配画布（Ctrl/Cmd+F）" aria-label="适配画布" @click="fitCanvas">
        <ScanSearch class="h-3.5 w-3.5" />
        适配
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="缩小画布（Ctrl/Cmd+-）" aria-label="缩小画布" @click="zoomOutCanvas">
        <ZoomOut class="h-3.5 w-3.5" />
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="放大画布（Ctrl/Cmd+=）" aria-label="放大画布" @click="zoomInCanvas">
        <ZoomIn class="h-3.5 w-3.5" />
      </button>
      <input
        v-model="groupName"
        type="text"
        placeholder="分组名"
        class="h-7 w-20 rounded-md border border-border/60 bg-transparent px-2 text-xs outline-none"
      />
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted flex items-center gap-1" title="创建分组（Ctrl/Cmd+G）" aria-label="创建分组" @click="createGroupFromSelection">
        <FolderTree class="h-3.5 w-3.5" />
        分组
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="重命名分组（Ctrl/Cmd+R）" aria-label="重命名分组" @click="renameSelectedGroup">
        重命名
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="折叠/展开分组（Ctrl/Cmd+E）" aria-label="折叠或展开分组" @click="toggleSelectedGroupCollapse">
        折叠/展开
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="聚焦当前分组" aria-label="聚焦当前分组" @click="toggleFocusSelectedGroup">
        聚焦分组
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="分组放大（Ctrl/Cmd+]）" aria-label="分组放大" @click="resizeSelectedGroup(1.12)">
        组放大
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="分组缩小（Ctrl/Cmd+[）" aria-label="分组缩小" @click="resizeSelectedGroup(0.9)">
        组缩小
      </button>
      <button class="h-7 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" title="解组（Ctrl/Cmd+Shift+G）" aria-label="解组" @click="ungroupSelectedGroup">
        解组
      </button>
    </div>
    <div class="absolute right-3 bottom-3 z-20 rounded-md border border-border/50 bg-background/85 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur">
      按 <span class="font-mono text-foreground">?</span> 或 <span class="font-mono text-foreground">F1</span> 查看快捷键
    </div>
    <div
      v-if="focusedGroupId"
      class="absolute bottom-3 left-1/2 z-30 -translate-x-1/2 rounded-full border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-700 dark:text-blue-300"
    >
      当前聚焦：{{ focusedGroupLabel() }}
      <button class="ml-2 rounded border border-blue-500/40 px-2 py-0.5 hover:bg-blue-500/20" @click="clearFocusMode">
        退出
      </button>
    </div>
    <div
      v-if="renamingGroupId"
      class="absolute left-1/2 top-16 z-30 -translate-x-1/2 rounded-lg border border-border/60 bg-background/95 px-2 py-2 shadow-sm backdrop-blur"
    >
      <div class="flex items-center gap-2">
        <input
          v-model="groupName"
          type="text"
          placeholder="输入分组名并回车"
          class="h-8 w-52 rounded-md border border-border/60 bg-transparent px-2 text-xs outline-none"
          @keydown.enter.prevent="confirmRenameFromInline"
          @keydown.esc.prevent="renamingGroupId = null"
        />
        <button class="h-8 rounded-md border border-border/60 px-2 text-xs hover:bg-muted" @click="confirmRenameFromInline">
          确认
        </button>
      </div>
    </div>
    <div
      v-if="showShortcutHelp"
      class="absolute right-3 bottom-12 z-40 w-80 rounded-lg border border-border/60 bg-background/95 p-3 text-xs shadow-sm backdrop-blur"
    >
      <div class="mb-2 flex items-center justify-between">
        <p class="font-semibold">快捷键帮助</p>
        <button class="rounded border border-border/60 px-2 py-0.5 hover:bg-muted" @click="showShortcutHelp = false">关闭</button>
      </div>
      <div class="grid grid-cols-[110px_1fr] gap-x-2 gap-y-1 text-muted-foreground">
        <span class="font-mono text-foreground">?</span><span>显示/隐藏帮助</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+S</span><span>保存工作流</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+Z</span><span>撤销</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+Y</span><span>重做</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+F</span><span>画布适配视图</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+=</span><span>放大画布</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+-</span><span>缩小画布</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+G</span><span>创建分组</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+Shift+G</span><span>解组</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+E</span><span>折叠/展开分组</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+R</span><span>重命名已选分组</span>
        <span class="font-mono text-foreground">Ctrl/Cmd+[ / ]</span><span>组缩小 / 组放大</span>
        <span class="font-mono text-foreground">Shift 拖拽</span><span>等比缩放分组</span>
        <span class="font-mono text-foreground">Alt 拖拽</span><span>中心点缩放分组</span>
      </div>
    </div>
    <div
      v-if="groupResizeState"
      class="fixed z-[60] rounded border border-slate-500/40 bg-slate-900/85 px-2 py-1 text-[11px] text-slate-100 pointer-events-none"
      :style="{ left: `${groupResizeState.cursorX + 12}px`, top: `${groupResizeState.cursorY + 12}px` }"
    >
      {{ groupResizeState.rawWidth }} x {{ groupResizeState.rawHeight }}
      <span class="mx-1 text-slate-400">-></span>
      {{ groupResizeState.currentWidth }} x {{ groupResizeState.currentHeight }}
      <span class="ml-1 text-slate-300">Shift 等比 / Alt 中心</span>
    </div>
    <!-- v-model 与 Vue Flow 双向绑定，拖动由库内部更新 nodesRef，onNodesChange 只做同步与选中逻辑 -->
    <VueFlow
      :id="FLOW_ID"
      v-model:nodes="nodesRef"
      v-model:edges="edgesRef"
      :node-types="nodeTypes"
      :nodes-draggable="true"
      :snap-to-grid="true"
      :snap-grid="SNAP_GRID"
      :connectable="true"
      :zoom-on-scroll="true"
      :pan-on-drag="true"
      :pan-on-scroll="false"
      :default-viewport="{ zoom: 1 }"
      :min-zoom="0.3"
      :max-zoom="2.2"
      :only-render-visible-elements="enableLargeGraphOptimization"
      :class="['rounded-lg bg-muted/20', groupResizeState ? 'canvas-resizing' : '']"
      @drop="onDrop"
      @dragover="onDragOver"
      @connect="onConnect"
      @node-click="onNodeClick"
      @node-double-click="onNodeDoubleClick"
      @pane-click="onPaneClick"
      @edge-click="onEdgeClick"
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
    >
      <FlowCoordBridge />
    </VueFlow>
  </div>
</template>

<style scoped>
.canvas-resizing :deep(.vue-flow__edge-path),
.canvas-resizing :deep(.vue-flow__connection-path) {
  transition: none !important;
  animation: none !important;
}
</style>
