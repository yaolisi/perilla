import { describe, expect, it } from 'vitest'
import {
  buildRagModelParamsPayload,
  defaultAgentRagFormState,
  loadAgentRagFormFromModelParams,
  readRagMultiHopEnabledFromModelParams,
  RAG_MODEL_PARAM_KEYS,
  stripRagModelParamsFromAgent,
  validateAgentRagFormClient,
} from '@/utils/agentRagModelParams'

describe('agentRagModelParams', () => {
  it('defaultAgentRagFormState matches backend-oriented defaults', () => {
    const s = defaultAgentRagFormState()
    expect(s.rag_top_k).toBe(5)
    expect(s.rag_retrieval_mode).toBe('hybrid')
    expect(s.rag_min_relevance_score).toBe(0.5)
    expect(s.rag_multi_hop_enabled).toBe(false)
    expect(s.rag_multi_hop_max_rounds).toBe(3)
    expect(s.rag_score_threshold).toBe('')
  })

  it('readRagMultiHopEnabledFromModelParams parses truthy variants', () => {
    expect(readRagMultiHopEnabledFromModelParams(null)).toBe(false)
    expect(readRagMultiHopEnabledFromModelParams({})).toBe(false)
    expect(readRagMultiHopEnabledFromModelParams({ rag_multi_hop_enabled: true })).toBe(true)
    expect(readRagMultiHopEnabledFromModelParams({ rag_multi_hop_enabled: 1 })).toBe(true)
    expect(readRagMultiHopEnabledFromModelParams({ rag_multi_hop_enabled: 'on' })).toBe(true)
    expect(readRagMultiHopEnabledFromModelParams({ rag_multi_hop_enabled: false })).toBe(false)
  })

  it('loadAgentRagFormFromModelParams merges and clamps', () => {
    const s = loadAgentRagFormFromModelParams({
      rag_top_k: 99,
      rag_retrieval_mode: 'vector',
      rag_min_relevance_score: 1.5,
      rag_multi_hop_enabled: 'true',
      rag_multi_hop_max_rounds: 10,
      rag_score_threshold: '1.1',
    })
    expect(s.rag_top_k).toBe(50)
    expect(s.rag_retrieval_mode).toBe('vector')
    expect(s.rag_min_relevance_score).toBe(1)
    expect(s.rag_multi_hop_enabled).toBe(true)
    expect(s.rag_multi_hop_max_rounds).toBe(5)
    expect(s.rag_score_threshold).toBe('1.1')
  })

  it('buildRagModelParamsPayload returns undefined without knowledge bases', () => {
    const f = defaultAgentRagFormState()
    f.rag_multi_hop_enabled = true
    expect(buildRagModelParamsPayload(false, f)).toBeUndefined()
  })

  it('buildRagModelParamsPayload omits rag_score_threshold when empty', () => {
    const f = defaultAgentRagFormState()
    f.rag_score_threshold = '  '
    const p = buildRagModelParamsPayload(true, f)
    expect(p).toBeDefined()
    expect(p!.rag_score_threshold).toBeUndefined()
    expect(p!.rag_top_k).toBe(5)
    expect(p!.rag_multi_hop_enabled).toBe(false)
  })

  it('buildRagModelParamsPayload includes numeric threshold when valid', () => {
    const f = defaultAgentRagFormState()
    f.rag_score_threshold = '0.9'
    const p = buildRagModelParamsPayload(true, f)
    expect(p!.rag_score_threshold).toBe(0.9)
  })

  it('stripRagModelParamsFromAgent removes all RAG keys', () => {
    const next: Record<string, unknown> = {
      intent_rules: [],
      rag_top_k: 3,
      rag_multi_hop_enabled: true,
      other: 1,
    }
    stripRagModelParamsFromAgent(next)
    expect(next.rag_top_k).toBeUndefined()
    expect(next.rag_multi_hop_enabled).toBeUndefined()
    expect(next.intent_rules).toEqual([])
    expect(next.other).toBe(1)
    expect(RAG_MODEL_PARAM_KEYS.length).toBeGreaterThan(5)
  })

  it('validateAgentRagFormClient accepts defaults', () => {
    expect(validateAgentRagFormClient(defaultAgentRagFormState())).toBeNull()
  })

  it('validateAgentRagFormClient rejects out-of-range top_k', () => {
    const f = defaultAgentRagFormState()
    f.rag_top_k = 0
    expect(validateAgentRagFormClient(f)).toBe('err_rag_top_k')
  })

  it('validateAgentRagFormClient rejects bad threshold', () => {
    const f = defaultAgentRagFormState()
    f.rag_score_threshold = '0'
    expect(validateAgentRagFormClient(f)).toBe('err_rag_threshold')
  })

  it('roundtrip: build payload then load yields stable display state', () => {
    const f = defaultAgentRagFormState()
    f.rag_top_k = 12
    f.rag_retrieval_mode = 'vector'
    f.rag_min_relevance_score = 0.35
    f.rag_multi_hop_enabled = true
    f.rag_multi_hop_max_rounds = 4
    f.rag_multi_hop_min_chunks = 3
    f.rag_multi_hop_min_best_relevance = 0.55
    f.rag_multi_hop_relax_relevance = false
    f.rag_multi_hop_feedback_chars = 400
    const p = buildRagModelParamsPayload(true, f)!
    const back = loadAgentRagFormFromModelParams(p)
    expect(back.rag_top_k).toBe(12)
    expect(back.rag_retrieval_mode).toBe('vector')
    expect(back.rag_min_relevance_score).toBeCloseTo(0.35, 5)
    expect(back.rag_multi_hop_enabled).toBe(true)
    expect(back.rag_multi_hop_max_rounds).toBe(4)
    expect(back.rag_multi_hop_min_chunks).toBe(3)
    expect(back.rag_multi_hop_min_best_relevance).toBeCloseTo(0.55, 5)
    expect(back.rag_multi_hop_relax_relevance).toBe(false)
    expect(back.rag_multi_hop_feedback_chars).toBe(400)
  })
})
