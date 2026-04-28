import type { SkillRecord } from '@/services/api'

/** 与 `AgentDefinition.enabled_skills_meta` 单条一致 */
export type EnabledSkillMetaItem = { id: string; name: string; is_mcp: boolean }

/** 与后端 `is_mcp` / definition.kind / category 对齐 */
export function isMcpSkillRecord(s: SkillRecord): boolean {
  if (typeof s.is_mcp === 'boolean') return s.is_mcp
  const k = (s.definition && (s.definition as Record<string, unknown>).kind) as string | undefined
  return k === 'mcp_stdio' || (s.category || '').toLowerCase() === 'mcp'
}

/** 由 `enabled_skills_meta` 单项构造最小 `SkillRecord`（与 merge 追加桩一致） */
export function skillRecordStubFromEnabledMeta(m: EnabledSkillMetaItem): SkillRecord {
  return {
    id: m.id,
    name: (m.name || '').trim() ? m.name : m.id,
    description: '',
    category: m.is_mcp ? 'mcp' : 'writing',
    type: 'tool',
    definition: m.is_mcp ? { kind: 'mcp_stdio' } : {},
    input_schema: {},
    enabled: true,
    is_mcp: m.is_mcp,
    created_at: null,
    updated_at: null,
  } as SkillRecord
}

/** 无 meta 时的占位记录（侧栏 / 目录兜底） */
export function skillRecordStubFromId(id: string): SkillRecord {
  return {
    id,
    name: id,
    description: '',
    category: 'writing',
    type: 'tool',
    definition: {},
    input_schema: {},
    enabled: true,
    created_at: null,
    updated_at: null,
  } as SkillRecord
}

/**
 * 将 GET/POST/PUT agent 返回的 enabled_skills_meta 并入本地技能列表，避免仅依赖 listSkills 时名称或 MCP 标记不一致。
 * 就地更新 `list` 中的项或追加桩记录。
 */
export function mergeEnabledSkillsMetaIntoSkillList(
  list: SkillRecord[],
  meta: EnabledSkillMetaItem[] | undefined,
): void {
  if (!meta?.length) return
  for (const m of meta) {
    const idx = list.findIndex((s) => s.id === m.id)
    if (idx >= 0) {
      const s = list[idx]
      if (!s) continue
      list[idx] = {
        ...s,
        name: (m.name || '').trim() ? m.name : s.name,
        is_mcp: typeof m.is_mcp === 'boolean' ? m.is_mcp : s.is_mcp,
      } as SkillRecord
    } else {
      list.push(skillRecordStubFromEnabledMeta(m))
    }
  }
}
