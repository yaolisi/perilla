import type { Edge, Node } from '@vue-flow/core'
import type { WorkflowNodeData } from './types'

export type ToolCompositionTemplateId = 'travel_planning' | 'market_research'

export interface ToolCompositionTemplate {
  id: ToolCompositionTemplateId
  name: string
  description: string
  tools: string[]
}

export interface RecommendedTemplate extends ToolCompositionTemplate {
  score: number
}

const USAGE_KEY = 'workflow:tool-composition:template-usage'

const TEMPLATE_DEFS: ToolCompositionTemplate[] = [
  {
    id: 'travel_planning',
    name: '差旅规划模板',
    description: '天气查询 -> 机票预订 -> 酒店推荐（含恶劣天气分支）',
    tools: ['weather.query', 'flight.booking', 'hotel.recommendation'],
  },
  {
    id: 'market_research',
    name: '市场调研模板',
    description: '搜索采集 -> 摘要分析 -> 报告输出',
    tools: ['web.search', 'llm.analyze', 'report.export'],
  },
]

function newId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function startNode(): Node<WorkflowNodeData> {
  return {
    id: 'start',
    type: 'workflow',
    position: { x: 80, y: 120 },
    data: { type: 'start', label: 'Start', config: {} },
  }
}

export function listToolCompositionTemplates(): ToolCompositionTemplate[] {
  return TEMPLATE_DEFS
}

export function buildTemplateGraph(templateId: ToolCompositionTemplateId): {
  nodes: Node<WorkflowNodeData>[]
  edges: Edge[]
} {
  if (templateId === 'market_research') {
    const inputId = newId('input')
    const searchId = newId('tool')
    const analyzeId = newId('llm')
    const outputId = newId('output')
    const nodes: Node<WorkflowNodeData>[] = [
      startNode(),
      {
        id: inputId,
        type: 'workflow',
        position: { x: 280, y: 120 },
        data: { type: 'input', label: 'Research Input', config: { input_key: 'query' } },
      },
      {
        id: searchId,
        type: 'workflow',
        position: { x: 520, y: 120 },
        data: {
          type: 'skill',
          label: 'Web Search',
          subtitle: 'web.search',
          config: {
            tool_name: 'web.search',
            inputs: {
              query: '{{input.query}}',
            },
          },
        },
      },
      {
        id: analyzeId,
        type: 'workflow',
        position: { x: 760, y: 120 },
        data: {
          type: 'llm',
          label: 'Analyze',
          config: {
            prompt: '请基于以下搜索结果输出要点总结：{{prev.output}}',
          },
        },
      },
      {
        id: outputId,
        type: 'workflow',
        position: { x: 980, y: 120 },
        data: {
          type: 'output',
          label: 'Report Output',
          config: { output_key: 'report' },
        },
      },
    ]
    const edges: Edge[] = [
      { id: newId('e'), source: 'start', target: inputId },
      { id: newId('e'), source: inputId, target: searchId },
      { id: newId('e'), source: searchId, target: analyzeId },
      { id: newId('e'), source: analyzeId, target: outputId },
    ]
    return { nodes, edges }
  }

  const inputId = newId('input')
  const weatherId = newId('tool')
  const conditionId = newId('cond')
  const flightId = newId('tool')
  const hotelIndoorId = newId('tool')
  const hotelOutdoorId = newId('tool')
  const outputId = newId('output')
  const nodes: Node<WorkflowNodeData>[] = [
    startNode(),
    {
      id: inputId,
      type: 'workflow',
      position: { x: 260, y: 220 },
      data: { type: 'input', label: 'Travel Input', config: { input_key: 'city' } },
    },
    {
      id: weatherId,
      type: 'workflow',
      position: { x: 480, y: 220 },
      data: {
        type: 'skill',
        label: 'Weather Query',
        subtitle: 'weather.query',
        config: {
          tool_name: 'weather.query',
          inputs: {
            city: '{{input.city}}',
          },
        },
      },
    },
    {
      id: conditionId,
      type: 'workflow',
      position: { x: 700, y: 220 },
      data: {
        type: 'condition',
        label: 'Weather Branch',
        config: {
          condition_expression: '${prev.weather} in ["暴雨", "雷暴", "台风"]',
        },
      },
    },
    {
      id: flightId,
      type: 'workflow',
      position: { x: 920, y: 140 },
      data: {
        type: 'skill',
        label: 'Flight Booking',
        subtitle: 'flight.booking',
        config: {
          tool_name: 'flight.booking',
          inputs: {
            city: '{{nodes.' + weatherId + '.city}}',
          },
        },
      },
    },
    {
      id: hotelIndoorId,
      type: 'workflow',
      position: { x: 1160, y: 90 },
      data: {
        type: 'skill',
        label: 'Indoor Hotel',
        subtitle: 'hotel.recommendation',
        config: {
          tool_name: 'hotel.recommendation',
          inputs: {
            city: '{{nodes.' + weatherId + '.city}}',
            theme: 'indoor_activity',
          },
        },
      },
    },
    {
      id: hotelOutdoorId,
      type: 'workflow',
      position: { x: 1160, y: 260 },
      data: {
        type: 'skill',
        label: 'Outdoor Hotel',
        subtitle: 'hotel.recommendation',
        config: {
          tool_name: 'hotel.recommendation',
          inputs: {
            city: '{{nodes.' + weatherId + '.city}}',
            theme: 'outdoor_activity',
          },
        },
      },
    },
    {
      id: outputId,
      type: 'workflow',
      position: { x: 1360, y: 190 },
      data: {
        type: 'output',
        label: 'Travel Plan',
        config: { output_key: 'travel_plan' },
      },
    },
  ]
  const edges: Edge[] = [
    { id: newId('e'), source: 'start', target: inputId },
    { id: newId('e'), source: inputId, target: weatherId },
    { id: newId('e'), source: weatherId, target: conditionId },
    { id: newId('e'), source: conditionId, target: flightId, label: 'always' },
    { id: newId('e'), source: conditionId, target: hotelIndoorId, sourceHandle: 'true', label: 'true' },
    { id: newId('e'), source: conditionId, target: hotelOutdoorId, sourceHandle: 'false', label: 'false' },
    { id: newId('e'), source: flightId, target: outputId },
    { id: newId('e'), source: hotelIndoorId, target: outputId },
    { id: newId('e'), source: hotelOutdoorId, target: outputId },
  ]
  return { nodes, edges }
}

export function trackTemplateUsage(templateId: ToolCompositionTemplateId): void {
  const raw = localStorage.getItem(USAGE_KEY)
  const parsed = raw ? (JSON.parse(raw) as Record<string, number>) : {}
  parsed[templateId] = (parsed[templateId] || 0) + 1
  localStorage.setItem(USAGE_KEY, JSON.stringify(parsed))
}

export function recommendTemplates(currentNodes: Node<WorkflowNodeData>[]): RecommendedTemplate[] {
  const usageRaw = localStorage.getItem(USAGE_KEY)
  const usage = usageRaw ? (JSON.parse(usageRaw) as Record<string, number>) : {}
  const nodeTypes = new Set((currentNodes || []).map((n) => n.data?.type))
  return TEMPLATE_DEFS.map((tpl) => {
    let score = (usage[tpl.id] || 0) * 2
    if (nodeTypes.has('condition') && tpl.id === 'travel_planning') score += 3
    if (nodeTypes.has('llm') && tpl.id === 'market_research') score += 2
    if (nodeTypes.has('skill')) score += 1
    return { ...tpl, score }
  }).sort((a, b) => b.score - a.score)
}
