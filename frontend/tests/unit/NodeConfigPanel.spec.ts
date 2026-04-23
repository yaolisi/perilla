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

  it('filters agent options by keyword', async () => {
    const wrapper = mount(NodeConfigPanel, {
      props: {
        node: {
          id: 'n-3',
          data: { type: 'agent', label: 'Agent', config: {} },
        } as any,
        selectedNodeId: 'n-3',
        nodes: [{ id: 'n-3', data: { type: 'agent', label: 'Agent', config: {} } }] as any,
      },
      global: { plugins: [makeI18n()] },
    })

    await flushPromises()
    const selects = wrapper.findAll('select')
    expect(selects[0].text()).toContain('Planner Agent')
    expect(selects[0].text()).toContain('Reporter Agent')

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('planner')
    await flushPromises()

    expect(selects[0].text()).toContain('Planner Agent')
    expect(selects[0].text()).not.toContain('Reporter Agent')
  })

  it('emits normalized model config when selecting model', async () => {
    const wrapper = mount(NodeConfigPanel, {
      props: {
        node: {
          id: 'n-4',
          data: { type: 'llm', label: 'LLM', config: {} },
        } as any,
        selectedNodeId: 'n-4',
        nodes: [{ id: 'n-4', data: { type: 'llm', label: 'LLM', config: {} } }] as any,
      },
      global: { plugins: [makeI18n()] },
    })

    await flushPromises()
    const modelSelect = wrapper.find('select')
    await modelSelect.setValue('qwen-7b')
    await flushPromises()

    const events = wrapper.emitted('update:config')
    expect(events).toBeTruthy()
    const payload = events?.at(-1)
    expect(payload?.[0]).toBe('n-4')
    expect(payload?.[1]).toMatchObject({
      model_id: 'qwen-7b',
      model_display_name: 'Qwen 7B',
    })
  })

  it('emits agent config when selecting agent', async () => {
    const wrapper = mount(NodeConfigPanel, {
      props: {
        node: {
          id: 'n-5',
          data: { type: 'agent', label: 'Agent', config: {} },
        } as any,
        selectedNodeId: 'n-5',
        nodes: [{ id: 'n-5', data: { type: 'agent', label: 'Agent', config: {} } }] as any,
      },
      global: { plugins: [makeI18n()] },
    })

    await flushPromises()
    const agentSelect = wrapper.find('select')
    await agentSelect.setValue('planner-agent')
    await flushPromises()

    const events = wrapper.emitted('update:config')
    expect(events).toBeTruthy()
    const payload = events?.at(-1)
    expect(payload?.[0]).toBe('n-5')
    expect(payload?.[1]).toMatchObject({
      agent_id: 'planner-agent',
      agent_display_name: 'Planner Agent',
    })
  })

  it('emits tool config when selecting tool', async () => {
    const wrapper = mount(NodeConfigPanel, {
      props: {
        node: {
          id: 'n-6',
          data: { type: 'skill', label: 'Tool', config: {} },
        } as any,
        selectedNodeId: 'n-6',
        nodes: [{ id: 'n-6', data: { type: 'skill', label: 'Tool', config: {} } }] as any,
      },
      global: { plugins: [makeI18n()] },
    })

    await flushPromises()
    const toolSelect = wrapper.find('select')
    await toolSelect.setValue('web.search')
    await flushPromises()

    const events = wrapper.emitted('update:config')
    expect(events).toBeTruthy()
    const payload = events?.at(-1)
    expect(payload?.[0]).toBe('n-6')
    expect(payload?.[1]).toMatchObject({
      tool_name: 'web.search',
      tool_id: 'web.search',
      tool_display_name: 'Web Search',
    })
  })
})
