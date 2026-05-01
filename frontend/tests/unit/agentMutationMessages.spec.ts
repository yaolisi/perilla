import { describe, expect, it, vi } from 'vitest'
import { AgentApiError } from '@/services/api'
import { formatAgentMutationErrorMessage } from '@/utils/agentMutationMessages'

describe('formatAgentMutationErrorMessage', () => {
  const t = vi.fn((key: string, values?: Record<string, string>) => {
    if (key === 'agents.create.err_kb_store_unavailable') return 'KB down'
    if (key === 'agents.create.err_knowledge_base_not_found') return `missing ${values?.id}`
    if (key === 'agents.create.err_knowledge_base_not_found_generic') return 'missing generic'
    return key
  })

  it('maps agent_kb_store_unavailable to i18n', () => {
    const err = new AgentApiError('x', { status: 503, code: 'agent_kb_store_unavailable' })
    expect(formatAgentMutationErrorMessage(err, t)).toBe('KB down')
  })

  it('maps agent_knowledge_base_not_found with id', () => {
    const err = new AgentApiError('x', {
      status: 400,
      code: 'agent_knowledge_base_not_found',
      details: { knowledge_base_id: 'kb1' },
    })
    expect(formatAgentMutationErrorMessage(err, t)).toBe('missing kb1')
  })

  it('maps agent_knowledge_base_not_found without id', () => {
    const err = new AgentApiError('x', {
      status: 400,
      code: 'agent_knowledge_base_not_found',
      details: {},
    })
    expect(formatAgentMutationErrorMessage(err, t)).toBe('missing generic')
  })

  it('maps request_unknown_fields to i18n with fields', () => {
    const mockT = vi.fn((key: string, values?: Record<string, string>) => {
      if (key === 'agents.create.err_request_unknown_fields') return `bad fields ${values?.fields}`
      return key
    })
    const err = new AgentApiError('Request contains unknown fields', {
      status: 422,
      code: 'request_unknown_fields',
      details: { unknown_fields: ['foo', 'bar'] },
    })
    expect(formatAgentMutationErrorMessage(err, mockT)).toBe('bad fields foo, bar')
  })

  it('falls back to formatAgentApiError for other AgentApiError', () => {
    const err = new AgentApiError('bad field', {
      status: 400,
      code: 'agent_invalid_model_params_rag',
      details: { field: 'model_params.rag_top_k' },
    })
    expect(formatAgentMutationErrorMessage(err, t)).toContain('bad field')
    expect(formatAgentMutationErrorMessage(err, t)).toContain('model_params.rag_top_k')
  })
})
