import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import zhLocale from '@/i18n/locales/zh.json'
import CreateWorkflowView from '@/components/workflow/CreateWorkflowView.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  onBeforeRouteLeave: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  createWorkflow: vi.fn(),
  createWorkflowVersion: vi.fn(),
  runWorkflow: vi.fn(),
  getToolCompositionRecommendations: vi.fn(async () => ({ items: [], total: 0 })),
  recordToolCompositionUsage: vi.fn(async () => ({ ok: true })),
}))

vi.mock('@/components/workflow/editor/toolCompositionTemplates', () => ({
  listToolCompositionTemplates: () => [
    { id: 'travel_planning', name: '差旅规划模板', description: 'desc', tools: ['weather.query', 'flight.booking'] },
  ],
  recommendTemplates: () => [
    {
      id: 'travel_planning',
      name: '差旅规划模板',
      description: 'desc',
      tools: ['weather.query', 'flight.booking'],
      score: 10,
      signals: {
        transition_pairs: [
          { from: 'weather.query', to: 'flight.booking', weight: 2.3 },
        ],
      },
    },
  ],
  buildTemplateGraph: () => ({
    nodes: [
      {
        id: 'start',
        type: 'workflow',
        position: { x: 80, y: 120 },
        data: { type: 'start', label: 'Start', config: {} },
      },
      {
        id: 'tool_1',
        type: 'workflow',
        position: { x: 260, y: 120 },
        data: { type: 'skill', label: 'Weather', config: { tool_name: 'weather.query' } },
      },
      {
        id: 'tool_2',
        type: 'workflow',
        position: { x: 460, y: 120 },
        data: { type: 'skill', label: 'Flight', config: { tool_name: 'flight.booking' } },
      },
    ],
    edges: [],
  }),
  trackTemplateUsage: vi.fn(),
}))

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh',
    messages: {
      zh: {
        workflow_page: zhLocale.workflow_page,
      },
    },
    missingWarn: false,
    fallbackWarn: false,
  })
}

const WorkflowCanvasStub = defineComponent({
  name: 'WorkflowCanvas',
  props: {
    nodes: { type: Array, default: () => [] },
    edges: { type: Array, default: () => [] },
    focusNodeId: { type: String, default: null },
  },
  template: '<div data-testid="workflow-canvas-stub"></div>',
})

describe('CreateWorkflowView recommendation focus integration', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    const mockLocalStorage = {
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      setItem: (key: string, value: string) => { store.set(key, value) },
      removeItem: (key: string) => { store.delete(key) },
      clear: () => { store.clear() },
    }
    Object.defineProperty(globalThis, 'localStorage', {
      value: mockLocalStorage,
      configurable: true,
    })
  })

  it('sets canvas focus-node-id when clicking recommendation chip', async () => {
    vi.useFakeTimers()
    const wrapper = mount(CreateWorkflowView, {
      global: {
        plugins: [makeI18n()],
        stubs: {
          NodeLibrary: true,
          NodeConfigPanel: true,
          WorkflowCanvas: WorkflowCanvasStub,
        },
      },
    })

    await flushPromises()

    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('一键导入模板'))
    expect(applyBtn).toBeTruthy()
    await applyBtn!.trigger('click')
    await flushPromises()

    const chip = wrapper.findAll('button').find((b) => b.text().includes('weather.query -> flight.booking'))
    expect(chip).toBeTruthy()
    await chip!.trigger('click')
    await flushPromises()

    const canvas = wrapper.findComponent(WorkflowCanvasStub)
    expect(canvas.exists()).toBe(true)
    expect((canvas.props('focusNodeId') as string | null) || '').toBe('tool_2')

    vi.runAllTimers()
    vi.useRealTimers()
  })
})

