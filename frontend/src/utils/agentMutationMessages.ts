import { AgentApiError, formatAgentApiError } from '@/services/api'

/**
 * 智能体相关 API（创建 / 更新 / 删除等）失败时的展示文案：
 * 知识库、`request_unknown_fields` 等走 i18n，其余走 formatAgentApiError。
 */
export function formatAgentMutationErrorMessage(
  error: unknown,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  if (error instanceof AgentApiError) {
    if (error.code === 'agent_kb_store_unavailable') {
      return t('agents.create.err_kb_store_unavailable')
    }
    if (error.code === 'request_unknown_fields') {
      const uf = error.details?.unknown_fields
      if (
        Array.isArray(uf) &&
        uf.length > 0 &&
        uf.every((x): x is string => typeof x === 'string')
      ) {
        return t('agents.create.err_request_unknown_fields', { fields: uf.join(', ') })
      }
    }
    if (error.code === 'agent_knowledge_base_not_found') {
      const id = error.details?.knowledge_base_id
      if (typeof id === 'string' && id.length > 0) {
        return t('agents.create.err_knowledge_base_not_found', { id })
      }
      return t('agents.create.err_knowledge_base_not_found_generic')
    }
  }
  return formatAgentApiError(error)
}
