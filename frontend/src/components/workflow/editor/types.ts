/**
 * Workflow Editor 节点库项与画布节点数据类型
 */

export type EditorNodeType =
  | 'start'
  | 'group'
  | 'llm'
  | 'agent'
  | 'embedding'
  | 'prompt_template'
  | 'system_prompt'
  | 'input'
  | 'output'
  | 'variable'
  | 'condition'
  | 'loop'
  | 'parallel'
  | 'sub_workflow'
  | 'skill'
  | 'http_request'
  | 'python'
  | 'shell'

export type NodeCategory = 'ai' | 'prompt' | 'data' | 'logic' | 'tool'

export interface NodeLibraryItem {
  type: EditorNodeType
  /** i18n key，UI 展示优先使用；缺省时回退到 label */
  labelKey?: string
  /** 兜底文案（当 i18n key 缺失时使用） */
  label: string
  icon: string
  category: NodeCategory
  disabled?: boolean
  /** 禁用原因 i18n key，UI 展示优先使用；缺省时回退到 disabledReason */
  disabledReasonKey?: string
  /** 禁用原因兜底文案 */
  disabledReason?: string
}

export interface WorkflowNodeData {
  type: EditorNodeType
  label: string
  subtitle?: string
  /** 与后端 WorkflowNode.config 对应 */
  config: Record<string, unknown>
}

export const NODE_LIBRARY: NodeLibraryItem[] = [
  // AI
  { type: 'llm', labelKey: 'workflow_editor.node_llm', label: 'LLM', icon: 'brain', category: 'ai' },
  { type: 'agent', labelKey: 'workflow_editor.node_agent', label: 'Agent', icon: 'user', category: 'ai' },
  { type: 'embedding', labelKey: 'workflow_editor.node_embedding', label: 'Embedding', icon: 'layers', category: 'ai', disabled: true, disabledReasonKey: 'workflow_editor.disabled_coming_soon', disabledReason: 'Coming soon' },
  // Prompt
  { type: 'prompt_template', labelKey: 'workflow_editor.node_prompt_template', label: 'Prompt Template', icon: 'file-text', category: 'prompt' },
  { type: 'system_prompt', labelKey: 'workflow_editor.node_system_prompt', label: 'System Prompt', icon: 'message-square', category: 'prompt', disabled: true, disabledReasonKey: 'workflow_editor.disabled_use_prompt_template', disabledReason: 'Use Prompt Template for now' },
  // Data
  { type: 'input', labelKey: 'workflow_editor.node_input', label: 'Input', icon: 'log-in', category: 'data' },
  { type: 'output', labelKey: 'workflow_editor.node_output', label: 'Output', icon: 'log-out', category: 'data' },
  { type: 'variable', labelKey: 'workflow_editor.node_variable', label: 'Variable', icon: 'variable', category: 'data', disabled: true, disabledReasonKey: 'workflow_editor.disabled_coming_soon', disabledReason: 'Coming soon' },
  // Logic
  { type: 'condition', labelKey: 'workflow_editor.node_condition', label: 'Condition', icon: 'git-branch', category: 'logic' },
  { type: 'loop', labelKey: 'workflow_editor.node_loop', label: 'Loop', icon: 'repeat', category: 'logic' },
  { type: 'sub_workflow', labelKey: 'workflow_editor.node_sub_workflow', label: 'Sub-workflow', icon: 'boxes', category: 'logic' },
  { type: 'parallel', labelKey: 'workflow_editor.node_parallel', label: 'Parallel', icon: 'copy', category: 'logic', disabled: true, disabledReasonKey: 'workflow_editor.disabled_coming_soon', disabledReason: 'Coming soon' },
  // Tool
  { type: 'skill', labelKey: 'workflow_editor.node_skill', label: 'Skill', icon: 'sparkles', category: 'tool' },
  { type: 'http_request', labelKey: 'workflow_editor.node_http_request', label: 'HTTP Request', icon: 'globe', category: 'tool', disabled: true, disabledReasonKey: 'workflow_editor.disabled_coming_soon', disabledReason: 'Coming soon' },
  { type: 'python', labelKey: 'workflow_editor.node_python', label: 'Python', icon: 'code', category: 'tool', disabled: true, disabledReasonKey: 'workflow_editor.disabled_coming_soon', disabledReason: 'Coming soon' },
  { type: 'shell', labelKey: 'workflow_editor.node_shell', label: 'Shell', icon: 'terminal', category: 'tool' },
]

// 开发期守卫：防止新增节点时漏配 labelKey，导致 i18n 回退到硬编码文本
if (import.meta.env?.DEV) {
  const missingLabelKey = NODE_LIBRARY.filter((item) => !item.labelKey).map((item) => item.type)
  if (missingLabelKey.length > 0) {
    // eslint-disable-next-line no-console
    console.warn('[workflow-editor] NODE_LIBRARY item missing labelKey:', missingLabelKey.join(', '))
  }
}

export const NODE_CATEGORY_LABELS: Record<NodeCategory, string> = {
  ai: 'AI',
  prompt: 'Prompt',
  data: 'Data',
  logic: 'Logic',
  tool: 'Tool',
}
