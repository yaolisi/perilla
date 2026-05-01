import { describe, expect, it } from 'vitest'
import { AgentApiError, formatAgentApiError } from '@/services/api'

describe('AgentApiError / formatAgentApiError', () => {
  it('formatAgentApiError appends details.field when present', () => {
    const err = new AgentApiError('参数不合法', {
      status: 400,
      code: 'agent_invalid_model_params_rag',
      details: { field: 'model_params.rag_top_k', value: 0 },
    })
    expect(formatAgentApiError(err)).toContain('参数不合法')
    expect(formatAgentApiError(err)).toContain('model_params.rag_top_k')
  })

  it('formatAgentApiError falls back to Error.message', () => {
    expect(formatAgentApiError(new Error('plain'))).toBe('plain')
  })

  it('formatAgentApiError appends details.unknown_fields when present', () => {
    const err = new AgentApiError('Request contains unknown fields', {
      status: 422,
      code: 'request_unknown_fields',
      details: { unknown_fields: ['extra_field'], allowed_fields: ['a'] },
    })
    const out = formatAgentApiError(err)
    expect(out).toContain('Request contains unknown fields')
    expect(out).toContain('extra_field')
  })
})
