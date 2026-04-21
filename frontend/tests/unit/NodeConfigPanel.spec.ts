import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
import NodeConfigPanel from '@/components/workflow/editor/NodeConfigPanel.vue'

vi.mock('@/services/api', () => ({
  listModels: vi.fn(async () => ({
    data: [
      { id: 'qwen-7b', name: 'qwen-7b', display_name: 'Qwen 7B', backend: 'ollama', model_type: 'llm' },
      { id: 'llama-3.1', name: 'llama-3.1', display_name: 'Llama 3.1', backend: 'llama.cpp', model_type: 'llm' },
      { id: 'embed-1', name: 'embed-1', display_name: 'Embed 1', backend: 'ollama', model_type: 'embedding' },
    ],
  })),
  listAgents: vi.fn(async () => ({
    data: [
      { agent_id: 'planner-agent', name: 'Planner Agent' },
      { agent_id: 'reporter-agent', name: 'Reporter Agent' },
    ],
  })),
  listTools: vi.fn(async () => ({
    data: [
      { name: 'web.search', ui: { display_name: 'Web Search' }, input_schema: {} },
      { name: 'python.exec', ui: { display_name: 'Python Exec' }, input_schema: {} },
    ],
  })),
}))

function makeI18n() {
  return createI18n({
    legacy: false,
    locale: 'zh',
    messages: { zh: {} },
    missingWarn: false,
    fallbackWarn: false,
  })
}

describe('NodeConfigPanel searchable selectors', () => {
  it('filters llm model options by keyword', async () => {
    const wrapper = mount(NodeConfigPanel, {
      props: {
        node: {
          id: 'n-1',
          data: { type: 'llm', label: 'LLM', config: {} },
        } as any,
        selectedNodeId: 'n-1',
        nodes: [{ id: 'n-1', data: { type: 'llm', label: 'LLM', config: {} } }] as any,
      },
      global: { plugins: [makeI18n()] },
    })

    await flushPromises()
    const selects = wrapper.findAll('select')
    expect(selects.length).toBeGreaterThan(0)
    expect(selects[0].text()).toContain('Qwen 7B')
    expect(selects[0].text()).toContain('Llama 3.1')

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('qwen')
    await flushPromises()

    expect(selects[0].text()).toContain('Qwen 7B')
    expect(selects[0].text()).not.toContain('Llama 3.1')
  })

  it('filters tool options by keyword', async () => {
    const wrapper = mount(NodeConfigPanel, {
      props: {
        node: {
          id: 'n-2',
          data: { type: 'skill', label: 'Tool', config: {} },
        } as any,
        selectedNodeId: 'n-2',
        nodes: [{ id: 'n-2', data: { type: 'skill', label: 'Tool', config: {} } }] as any,
      },
      global: { plugins: [makeI18n()] },
    })

    await flushPromises()
    const selects = wrapper.findAll('select')
    expect(selects[0].text()).toContain('Web Search')
    expect(selects[0].text()).toContain('Python Exec')

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('python')
    await flushPromises()

    expect(selects[0].text()).not.toContain('Web Search')
    expect(selects[0].text()).toContain('Python Exec')
  })
})
