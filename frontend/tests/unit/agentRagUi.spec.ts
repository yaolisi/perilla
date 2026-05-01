import { describe, expect, it, vi } from 'vitest'
import {
  AGENT_MUTATION_KB_RAG_HIGHLIGHT_CODES,
  pulseAgentKnowledgeOrRagOnMutationError,
} from '@/utils/agentRagUi'

describe('pulseAgentKnowledgeOrRagOnMutationError', () => {
  it('no-ops when code is missing or unknown', () => {
    const kb = document.createElement('div')
    const rag = document.createElement('div')
    const scroll = vi.spyOn(kb, 'scrollIntoView').mockImplementation(() => {})
    pulseAgentKnowledgeOrRagOnMutationError(undefined, rag, kb)
    pulseAgentKnowledgeOrRagOnMutationError('other', rag, kb)
    expect(scroll).not.toHaveBeenCalled()
  })

  it('includes expected server codes', () => {
    expect(AGENT_MUTATION_KB_RAG_HIGHLIGHT_CODES.has('agent_kb_store_unavailable')).toBe(true)
    expect(AGENT_MUTATION_KB_RAG_HIGHLIGHT_CODES.has('agent_knowledge_base_not_found')).toBe(true)
  })
})
