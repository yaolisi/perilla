/**
 * Agent `model_params` 中与 RAG 检索相关的键（与 `AgentLoop` / `RAGRetrieval` 一致）。
 */
export const RAG_MODEL_PARAM_KEYS = [
  'rag_top_k',
  'rag_score_threshold',
  'rag_retrieval_mode',
  'rag_min_relevance_score',
  'rag_multi_hop_enabled',
  'rag_multi_hop_max_rounds',
  'rag_multi_hop_min_chunks',
  'rag_multi_hop_min_best_relevance',
  'rag_multi_hop_relax_relevance',
  'rag_multi_hop_feedback_chars',
] as const

export interface AgentRagFormState {
  rag_top_k: number
  /** 空字符串表示使用后端默认（max_distance 默认 1.2） */
  rag_score_threshold: string
  rag_retrieval_mode: 'hybrid' | 'vector'
  rag_min_relevance_score: number
  rag_multi_hop_enabled: boolean
  rag_multi_hop_max_rounds: number
  rag_multi_hop_min_chunks: number
  rag_multi_hop_min_best_relevance: number
  rag_multi_hop_relax_relevance: boolean
  rag_multi_hop_feedback_chars: number
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n))
}

/** 与后端 AgentLoop 一致：model_params.rag_multi_hop_enabled 真值解析 */
export function readRagMultiHopEnabledFromModelParams(
  mp: Record<string, unknown> | null | undefined,
): boolean {
  if (!mp || typeof mp !== 'object') return false
  return mpBool((mp as Record<string, unknown>).rag_multi_hop_enabled, false)
}

function mpBool(v: unknown, def: boolean): boolean {
  if (v === null || v === undefined) return def
  if (typeof v === 'boolean') return v
  if (typeof v === 'number') return Boolean(v)
  const s = String(v).trim().toLowerCase()
  return s === '1' || s === 'true' || s === 'yes' || s === 'on'
}

export function defaultAgentRagFormState(): AgentRagFormState {
  return {
    rag_top_k: 5,
    rag_score_threshold: '',
    rag_retrieval_mode: 'hybrid',
    rag_min_relevance_score: 0.5,
    rag_multi_hop_enabled: false,
    rag_multi_hop_max_rounds: 3,
    rag_multi_hop_min_chunks: 2,
    rag_multi_hop_min_best_relevance: 0,
    rag_multi_hop_relax_relevance: true,
    rag_multi_hop_feedback_chars: 320,
  }
}

export function loadAgentRagFormFromModelParams(
  mp: Record<string, unknown> | null | undefined,
): AgentRagFormState {
  const d = defaultAgentRagFormState()
  if (!mp || typeof mp !== 'object') return d
  const m = mp as Record<string, unknown>
  if (m.rag_top_k != null) {
    const n = Number(m.rag_top_k)
    if (!Number.isNaN(n)) d.rag_top_k = clamp(Math.round(n), 1, 50)
  }
  if (m.rag_score_threshold != null && m.rag_score_threshold !== '') {
    d.rag_score_threshold = String(m.rag_score_threshold)
  }
  const rm = String(m.rag_retrieval_mode ?? '').toLowerCase()
  if (rm === 'vector' || rm === 'hybrid') d.rag_retrieval_mode = rm
  if (m.rag_min_relevance_score != null) {
    const n = Number(m.rag_min_relevance_score)
    if (!Number.isNaN(n)) d.rag_min_relevance_score = clamp(n, 0, 1)
  }
  d.rag_multi_hop_enabled = mpBool(m.rag_multi_hop_enabled, false)
  if (m.rag_multi_hop_max_rounds != null) {
    const n = Number(m.rag_multi_hop_max_rounds)
    if (!Number.isNaN(n)) d.rag_multi_hop_max_rounds = clamp(Math.round(n), 2, 5)
  }
  if (m.rag_multi_hop_min_chunks != null) {
    const n = Number(m.rag_multi_hop_min_chunks)
    if (!Number.isNaN(n)) d.rag_multi_hop_min_chunks = clamp(Math.round(n), 0, 50)
  }
  if (m.rag_multi_hop_min_best_relevance != null) {
    const n = Number(m.rag_multi_hop_min_best_relevance)
    if (!Number.isNaN(n)) d.rag_multi_hop_min_best_relevance = clamp(n, 0, 1)
  }
  d.rag_multi_hop_relax_relevance = mpBool(m.rag_multi_hop_relax_relevance, true)
  if (m.rag_multi_hop_feedback_chars != null) {
    const n = Number(m.rag_multi_hop_feedback_chars)
    if (!Number.isNaN(n)) d.rag_multi_hop_feedback_chars = clamp(Math.round(n), 80, 2000)
  }
  return d
}

export function buildRagModelParamsPayload(
  hasRagIds: boolean,
  s: AgentRagFormState,
): Record<string, unknown> | undefined {
  if (!hasRagIds) return undefined
  const topK = clamp(Math.round(Number(s.rag_top_k) || 5), 1, 50)
  const mrs = clamp(Number(s.rag_min_relevance_score) || 0.5, 0, 1)
  const out: Record<string, unknown> = {
    rag_top_k: topK,
    rag_retrieval_mode: s.rag_retrieval_mode === 'vector' ? 'vector' : 'hybrid',
    rag_min_relevance_score: mrs,
    rag_multi_hop_enabled: Boolean(s.rag_multi_hop_enabled),
    rag_multi_hop_max_rounds: clamp(Math.round(Number(s.rag_multi_hop_max_rounds) || 3), 2, 5),
    rag_multi_hop_min_chunks: clamp(Math.round(Number(s.rag_multi_hop_min_chunks) || 2), 0, 50),
    rag_multi_hop_min_best_relevance: clamp(Number(s.rag_multi_hop_min_best_relevance) || 0, 0, 1),
    rag_multi_hop_relax_relevance: Boolean(s.rag_multi_hop_relax_relevance),
    rag_multi_hop_feedback_chars: clamp(Math.round(Number(s.rag_multi_hop_feedback_chars) || 320), 80, 2000),
  }
  const thr = String(s.rag_score_threshold ?? '').trim()
  if (thr !== '') {
    const n = Number(thr)
    if (!Number.isNaN(n)) out.rag_score_threshold = n
  }
  return out
}

export function stripRagModelParamsFromAgent(next: Record<string, unknown>): void {
  for (const k of RAG_MODEL_PARAM_KEYS) {
    delete next[k]
  }
}

/**
 * 提交前校验（与 `api/agents._validate_model_params_rag` 范围一致）。
 * 返回 i18n 键后缀：`agents.create.${key}`。
 */
export type AgentRagClientIssueKey =
  | 'err_rag_top_k'
  | 'err_rag_threshold'
  | 'err_rag_mode'
  | 'err_rag_min_rel'
  | 'err_rag_mh_rounds'
  | 'err_rag_mh_chunks'
  | 'err_rag_mh_best'
  | 'err_rag_mh_feedback'

export function validateAgentRagFormClient(s: AgentRagFormState): AgentRagClientIssueKey | null {
  const tkN = Math.round(Number(s.rag_top_k))
  if (!Number.isFinite(tkN) || tkN < 1 || tkN > 50) {
    return 'err_rag_top_k'
  }

  const thr = String(s.rag_score_threshold ?? '').trim()
  if (thr !== '') {
    const x = Number(thr)
    if (!Number.isFinite(x) || x <= 0 || x > 100) {
      return 'err_rag_threshold'
    }
  }

  const rm = s.rag_retrieval_mode
  if (rm !== 'hybrid' && rm !== 'vector') {
    return 'err_rag_mode'
  }

  const mrs = Number(s.rag_min_relevance_score)
  if (!Number.isFinite(mrs) || mrs < 0 || mrs > 1) {
    return 'err_rag_min_rel'
  }

  const mhR = Math.round(Number(s.rag_multi_hop_max_rounds))
  if (!Number.isFinite(mhR) || mhR < 2 || mhR > 5) {
    return 'err_rag_mh_rounds'
  }

  const mhC = Math.round(Number(s.rag_multi_hop_min_chunks))
  if (!Number.isFinite(mhC) || mhC < 0 || mhC > 50) {
    return 'err_rag_mh_chunks'
  }

  const mhB = Number(s.rag_multi_hop_min_best_relevance)
  if (!Number.isFinite(mhB) || mhB < 0 || mhB > 1) {
    return 'err_rag_mh_best'
  }

  const mhF = Math.round(Number(s.rag_multi_hop_feedback_chars))
  if (!Number.isFinite(mhF) || mhF < 80 || mhF > 2000) {
    return 'err_rag_mh_feedback'
  }

  return null
}
