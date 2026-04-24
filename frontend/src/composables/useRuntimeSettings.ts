import { ref } from 'vue'
import { getSystemConfig, updateSystemConfig, type SystemConfig } from '@/services/api'

function parseBool(value: unknown, defaultVal: boolean): boolean {
  if (value === undefined || value === null) return defaultVal
  if (value === true || value === 1 || value === 'true') return true
  if (value === false || value === 0 || value === 'false') return false
  return defaultVal
}

type SmartRoutingPreviewItem = {
  alias: string
  strategy: string
  summary: string
}

type SmartRoutingSnapshotItem = {
  id: string
  createdAt: number
  text: string
}

type SmartRoutingSnapshotDiff = {
  addedAliases: string[]
  removedAliases: string[]
  changedAliases: string[]
  changedDetails: Array<{
    alias: string
    lines: Array<{
      current: string
      snapshot: string
      currentChanged: boolean
      snapshotChanged: boolean
    }>
  }>
}

type SmartRoutingSnapshotDiffView = {
  addedAliases: string[]
  removedAliases: string[]
  changedAliases: string[]
  changedDetails: Array<{
    alias: string
    lines: Array<{
      current: string
      snapshot: string
      currentChanged: boolean
      snapshotChanged: boolean
    }>
  }>
}

const SMART_ROUTING_SNAPSHOT_STORAGE_KEY = 'runtime.smartRouting.snapshots.v1'
const MAX_SMART_ROUTING_SNAPSHOTS = 8

export function useRuntimeSettings() {
  const autoUnloadLocalModelOnSwitch = ref(false)
  const runtimeAutoReleaseEnabled = ref(true)
  const runtimeMaxCachedLocalRuntimes = ref(1)
  const runtimeMaxCachedLocalLlmRuntimes = ref(1)
  const runtimeMaxCachedLocalVlmRuntimes = ref(1)
  const runtimeMaxCachedLocalImageGenerationRuntimes = ref(1)
  const runtimeReleaseIdleTtlSeconds = ref(300)
  const runtimeReleaseMinIntervalSeconds = ref(5)
  const inferenceSmartRoutingEnabled = ref(true)
  const inferenceSmartRoutingPoliciesJson = ref('')
  const DEFAULT_SMART_ROUTING_POLICIES_TEMPLATE = `{
  "reasoning-model": {
    "strategy": "blue_green",
    "stable": "reasoning-v1",
    "candidate": "reasoning-v2",
    "candidate_percent": 10
  },
  "chat-fast": {
    "strategy": "least_loaded",
    "candidates": ["chat-fast-a", "chat-fast-b"]
  },
  "chat-balanced": {
    "strategy": "weighted",
    "candidates": [
      { "target": "chat-a", "weight": 70 },
      { "target": "chat-b", "weight": 30 }
    ]
  }
}`

  const config = ref<SystemConfig | null>(null)
  const isSaving = ref(false)
  const saveSuccess = ref(false)
  const saveError = ref('')
  const smartRoutingJsonError = ref('')
  const smartRoutingBuilderError = ref('')
  const smartRoutingBuilderInfo = ref('')
  const smartRoutingPreview = ref<SmartRoutingPreviewItem[]>([])
  const smartRoutingPreviewError = ref('')
  const smartRoutingSnapshots = ref<SmartRoutingSnapshotItem[]>([])
  const smartRoutingSnapshotDiff = ref<SmartRoutingSnapshotDiff | null>(null)
  const smartRoutingSnapshotDiffError = ref('')
  const smartRoutingSnapshotDiffAliasFilter = ref('')
  const isEditing = ref(false)

  const loadConfig = async () => {
    try {
      const c = await getSystemConfig()
      config.value = c
      const s = c.settings ?? {}
      autoUnloadLocalModelOnSwitch.value = parseBool(s.autoUnloadLocalModelOnSwitch, false)
      runtimeAutoReleaseEnabled.value = parseBool(s.runtimeAutoReleaseEnabled, true)
      runtimeMaxCachedLocalRuntimes.value = Math.min(16, Math.max(1, Number(s.runtimeMaxCachedLocalRuntimes) || 1))
      runtimeMaxCachedLocalLlmRuntimes.value = Math.min(
        16,
        Math.max(1, Number(s.runtimeMaxCachedLocalLlmRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1),
      )
      runtimeMaxCachedLocalVlmRuntimes.value = Math.min(
        16,
        Math.max(1, Number(s.runtimeMaxCachedLocalVlmRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1),
      )
      runtimeMaxCachedLocalImageGenerationRuntimes.value = Math.min(
        16,
        Math.max(1, Number(s.runtimeMaxCachedLocalImageGenerationRuntimes) || runtimeMaxCachedLocalRuntimes.value || 1),
      )
      runtimeReleaseIdleTtlSeconds.value = Math.min(86400, Math.max(30, Number(s.runtimeReleaseIdleTtlSeconds) || 300))
      runtimeReleaseMinIntervalSeconds.value = Math.min(3600, Math.max(1, Number(s.runtimeReleaseMinIntervalSeconds) || 5))
      inferenceSmartRoutingEnabled.value = parseBool(s.inferenceSmartRoutingEnabled, true)
      inferenceSmartRoutingPoliciesJson.value = String(s.inferenceSmartRoutingPoliciesJson || '')
      smartRoutingJsonError.value = ''
      refreshSmartRoutingPreview()
      isEditing.value = false
    } catch (e) {
      console.error('Failed to load system config:', e)
    }
  }

  const handleSave = async (onAfterSave?: () => Promise<void>) => {
    isSaving.value = true
    saveError.value = ''
    smartRoutingJsonError.value = ''
    try {
      const policyText = String(inferenceSmartRoutingPoliciesJson.value || '').trim()
      if (policyText) {
        try {
          JSON.parse(policyText)
        } catch {
          smartRoutingJsonError.value = '智能路由策略 JSON 格式无效，请检查后重试。'
          throw new Error(smartRoutingJsonError.value)
        }
      }
      await updateSystemConfig({
        autoUnloadLocalModelOnSwitch: Boolean(autoUnloadLocalModelOnSwitch.value),
        runtimeAutoReleaseEnabled: Boolean(runtimeAutoReleaseEnabled.value),
        runtimeMaxCachedLocalRuntimes: runtimeMaxCachedLocalRuntimes.value,
        runtimeMaxCachedLocalLlmRuntimes: runtimeMaxCachedLocalLlmRuntimes.value,
        runtimeMaxCachedLocalVlmRuntimes: runtimeMaxCachedLocalVlmRuntimes.value,
        runtimeMaxCachedLocalImageGenerationRuntimes: runtimeMaxCachedLocalImageGenerationRuntimes.value,
        runtimeReleaseIdleTtlSeconds: runtimeReleaseIdleTtlSeconds.value,
        runtimeReleaseMinIntervalSeconds: runtimeReleaseMinIntervalSeconds.value,
        inferenceSmartRoutingEnabled: Boolean(inferenceSmartRoutingEnabled.value),
        inferenceSmartRoutingPoliciesJson: policyText,
      })
      await loadConfig()
      if (policyText) {
        pushSmartRoutingSnapshot(policyText)
      }
      if (onAfterSave) await onAfterSave()
      saveSuccess.value = true
      setTimeout(() => {
        saveSuccess.value = false
      }, 3000)
    } catch (e) {
      console.error('Failed to save runtime settings:', e)
      saveError.value = e instanceof Error ? e.message : String(e)
    } finally {
      isSaving.value = false
    }
  }

  const _parsePolicyObject = (): Record<string, any> => {
    const text = String(inferenceSmartRoutingPoliciesJson.value || '').trim()
    if (!text) return {}
    const parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('智能路由策略 JSON 必须是对象（key 为 model alias）。')
    }
    return parsed as Record<string, any>
  }

  const _setPolicyObject = (obj: Record<string, any>) => {
    inferenceSmartRoutingPoliciesJson.value = JSON.stringify(obj, null, 2)
    isEditing.value = true
  }

  const refreshSmartRoutingPreview = () => {
    smartRoutingPreviewError.value = ''
    smartRoutingPreview.value = []
    try {
      const root = _parsePolicyObject()
      const entries: SmartRoutingPreviewItem[] = []
      for (const [alias, rawPolicy] of Object.entries(root)) {
        if (!rawPolicy || typeof rawPolicy !== 'object' || Array.isArray(rawPolicy)) {
          entries.push({ alias, strategy: 'invalid', summary: '策略不是对象' })
          continue
        }
        const policy = rawPolicy as Record<string, any>
        const strategy = String(policy.strategy || 'unknown')
        let summary = ''
        if (strategy === 'canary') {
          summary = `stable=${policy.stable || '-'} canary=${policy.canary || '-'} canary_percent=${policy.canary_percent ?? 10}%`
        } else if (strategy === 'blue_green') {
          summary = `stable=${policy.stable || '-'} candidate=${policy.candidate || '-'} candidate_percent=${policy.candidate_percent ?? 0}%`
        } else if (strategy === 'least_loaded') {
          const candidates = Array.isArray(policy.candidates) ? policy.candidates.join(', ') : '-'
          summary = `candidates=[${candidates}]`
        } else if (strategy === 'weighted') {
          const candidates = Array.isArray(policy.candidates)
            ? policy.candidates
                .map((x: any) => `${String(x?.target || x?.model_id || '-')}:${String(x?.weight ?? '-')}`)
                .join(', ')
            : '-'
          summary = `candidates=[${candidates}]`
        } else if (strategy === 'least_loaded_prefer_candidate') {
          summary = `stable=${policy.stable || '-'} candidate=${policy.candidate || '-'} threshold=${policy.candidate_max_extra_queue ?? 1}`
        } else {
          summary = '未知策略'
        }
        entries.push({ alias, strategy, summary })
      }
      smartRoutingPreview.value = entries
    } catch (e) {
      smartRoutingPreviewError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const loadSmartRoutingSnapshots = () => {
    try {
      const raw = localStorage.getItem(SMART_ROUTING_SNAPSHOT_STORAGE_KEY)
      if (!raw) {
        smartRoutingSnapshots.value = []
        return
      }
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) {
        smartRoutingSnapshots.value = []
        return
      }
      smartRoutingSnapshots.value = parsed
        .filter((x) => x && typeof x.text === "string" && typeof x.createdAt === "number" && typeof x.id === "string")
        .slice(0, MAX_SMART_ROUTING_SNAPSHOTS)
    } catch {
      smartRoutingSnapshots.value = []
    }
  }

  const persistSmartRoutingSnapshots = () => {
    localStorage.setItem(
      SMART_ROUTING_SNAPSHOT_STORAGE_KEY,
      JSON.stringify(smartRoutingSnapshots.value.slice(0, MAX_SMART_ROUTING_SNAPSHOTS)),
    )
  }

  const pushSmartRoutingSnapshot = (text: string) => {
    const trimmed = String(text || '').trim()
    if (!trimmed) return
    const next: SmartRoutingSnapshotItem = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
      createdAt: Date.now(),
      text: trimmed,
    }
    const deduped = smartRoutingSnapshots.value.filter((x) => x.text !== trimmed)
    smartRoutingSnapshots.value = [next, ...deduped].slice(0, MAX_SMART_ROUTING_SNAPSHOTS)
    persistSmartRoutingSnapshots()
  }

  const restoreSnapshotById = (snapshotId: string) => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    const target = smartRoutingSnapshots.value.find((x) => x.id === snapshotId)
    if (!target) {
      smartRoutingBuilderError.value = '未找到可回滚的策略快照。'
      return
    }
    try {
      const parsed = JSON.parse(target.text)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('快照内容不是合法策略对象。')
      }
      _setPolicyObject(parsed as Record<string, any>)
      refreshSmartRoutingPreview()
      smartRoutingBuilderInfo.value = '已回滚到所选策略快照。'
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const compareSnapshotById = (snapshotId: string) => {
    smartRoutingSnapshotDiffError.value = ''
    smartRoutingSnapshotDiff.value = null
    try {
      const target = smartRoutingSnapshots.value.find((x) => x.id === snapshotId)
      if (!target) {
        throw new Error('未找到要对比的快照。')
      }
      const currentRaw = _parsePolicyObject()
      const snapshotRaw = JSON.parse(target.text)
      if (!snapshotRaw || typeof snapshotRaw !== 'object' || Array.isArray(snapshotRaw)) {
        throw new Error('快照内容不是合法策略对象。')
      }
      const current = currentRaw as Record<string, any>
      const snap = snapshotRaw as Record<string, any>
      const currentKeys = new Set(Object.keys(current))
      const snapKeys = new Set(Object.keys(snap))
      const addedAliases = Array.from(snapKeys).filter((k) => !currentKeys.has(k)).sort()
      const removedAliases = Array.from(currentKeys).filter((k) => !snapKeys.has(k)).sort()
      const changedAliases = Array.from(currentKeys)
        .filter((k) => snapKeys.has(k))
        .filter((k) => JSON.stringify(current[k]) !== JSON.stringify(snap[k]))
        .sort()
      const changedDetails = changedAliases.map((alias) => ({
        alias,
        lines: buildJsonLineDiff(
          JSON.stringify(current[alias], null, 2),
          JSON.stringify(snap[alias], null, 2),
        ),
      }))
      smartRoutingSnapshotDiff.value = {
        addedAliases,
        removedAliases,
        changedAliases,
        changedDetails,
      }
    } catch (e) {
      smartRoutingSnapshotDiffError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const buildJsonLineDiff = (currentText: string, snapshotText: string) => {
    const currentLines = String(currentText || '').split('\n')
    const snapshotLines = String(snapshotText || '').split('\n')
    const maxLen = Math.max(currentLines.length, snapshotLines.length)
    const rows: Array<{
      current: string
      snapshot: string
      currentChanged: boolean
      snapshotChanged: boolean
    }> = []
    for (let i = 0; i < maxLen; i += 1) {
      const current = currentLines[i] ?? ''
      const snapshot = snapshotLines[i] ?? ''
      const changed = current !== snapshot
      rows.push({
        current,
        snapshot,
        currentChanged: changed,
        snapshotChanged: changed,
      })
    }
    return rows
  }

  const getFilteredSnapshotDiff = (): SmartRoutingSnapshotDiffView | null => {
    if (!smartRoutingSnapshotDiff.value) return null
    const keyword = smartRoutingSnapshotDiffAliasFilter.value.trim().toLowerCase()
    if (!keyword) {
      return {
        addedAliases: smartRoutingSnapshotDiff.value.addedAliases,
        removedAliases: smartRoutingSnapshotDiff.value.removedAliases,
        changedAliases: smartRoutingSnapshotDiff.value.changedAliases,
        changedDetails: smartRoutingSnapshotDiff.value.changedDetails,
      }
    }
    const match = (alias: string) => alias.toLowerCase().includes(keyword)
    return {
      addedAliases: smartRoutingSnapshotDiff.value.addedAliases.filter(match),
      removedAliases: smartRoutingSnapshotDiff.value.removedAliases.filter(match),
      changedAliases: smartRoutingSnapshotDiff.value.changedAliases.filter(match),
      changedDetails: smartRoutingSnapshotDiff.value.changedDetails.filter((x) => match(x.alias)),
    }
  }

  const copyFilteredSnapshotDiffReport = async () => {
    smartRoutingSnapshotDiffError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const diff = getFilteredSnapshotDiff()
      if (!diff) {
        throw new Error('当前没有可复制的差异报告。')
      }
      const lines: string[] = []
      lines.push('Smart Routing Snapshot Diff Report')
      lines.push(`Generated At: ${new Date().toISOString()}`)
      lines.push('')
      lines.push(`Added Aliases: ${diff.addedAliases.length ? diff.addedAliases.join(', ') : '-'}`)
      lines.push(`Removed Aliases: ${diff.removedAliases.length ? diff.removedAliases.join(', ') : '-'}`)
      lines.push(`Changed Aliases: ${diff.changedAliases.length ? diff.changedAliases.join(', ') : '-'}`)
      for (const detail of diff.changedDetails) {
        lines.push('')
        lines.push(`## ${detail.alias}`)
        lines.push('--- Current ---')
        for (const row of detail.lines) {
          lines.push(row.current || ' ')
        }
        lines.push('--- Snapshot ---')
        for (const row of detail.lines) {
          lines.push(row.snapshot || ' ')
        }
      }
      await navigator.clipboard.writeText(lines.join('\n'))
      smartRoutingBuilderInfo.value = '差异报告已复制到剪贴板。'
    } catch (e) {
      smartRoutingSnapshotDiffError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const exportFilteredSnapshotDiffAsMarkdown = () => {
    smartRoutingSnapshotDiffError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const diff = getFilteredSnapshotDiff()
      if (!diff) {
        throw new Error('当前没有可导出的差异报告。')
      }
      const lines: string[] = []
      lines.push('# Smart Routing Snapshot Diff Report')
      lines.push('')
      lines.push(`- Generated At: ${new Date().toISOString()}`)
      lines.push(`- Added Aliases: ${diff.addedAliases.length ? diff.addedAliases.join(', ') : '-'}`)
      lines.push(`- Removed Aliases: ${diff.removedAliases.length ? diff.removedAliases.join(', ') : '-'}`)
      lines.push(`- Changed Aliases: ${diff.changedAliases.length ? diff.changedAliases.join(', ') : '-'}`)

      for (const detail of diff.changedDetails) {
        lines.push('')
        lines.push(`## ${detail.alias}`)
        lines.push('')
        lines.push('### Current')
        lines.push('```json')
        for (const row of detail.lines) {
          lines.push(row.current || ' ')
        }
        lines.push('```')
        lines.push('')
        lines.push('### Snapshot')
        lines.push('```json')
        for (const row of detail.lines) {
          lines.push(row.snapshot || ' ')
        }
        lines.push('```')
      }

      const content = lines.join('\n')
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const stamp = new Date().toISOString().replace(/[:.]/g, '-')
      a.href = url
      a.download = `smart-routing-diff-${stamp}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      smartRoutingBuilderInfo.value = '差异报告 Markdown 已导出。'
    } catch (e) {
      smartRoutingSnapshotDiffError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const upsertCanaryPolicy = (params: {
    alias: string
    stable: string
    canary: string
    percent: number
  }) => {
    smartRoutingBuilderError.value = ''
    try {
      const alias = params.alias.trim()
      const stable = params.stable.trim()
      const canary = params.canary.trim()
      const percent = Math.max(0, Math.min(100, Number(params.percent) || 0))
      if (!alias || !stable || !canary) {
        throw new Error('请填写 alias / stable / canary 后再生成策略。')
      }
      const root = _parsePolicyObject()
      root[alias] = {
        strategy: 'canary',
        stable,
        canary,
        canary_percent: percent,
      }
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
  loadSmartRoutingSnapshots()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const upsertLeastLoadedPolicy = (params: {
    alias: string
    candidatesText: string
  }) => {
    smartRoutingBuilderError.value = ''
    try {
      const alias = params.alias.trim()
      const candidates = params.candidatesText
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
      if (!alias || candidates.length === 0) {
        throw new Error('请填写 alias，并提供至少一个候选模型。')
      }
      const root = _parsePolicyObject()
      root[alias] = {
        strategy: 'least_loaded',
        candidates,
      }
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const upsertWeightedPolicy = (params: {
    alias: string
    pairsText: string
  }) => {
    smartRoutingBuilderError.value = ''
    try {
      const alias = params.alias.trim()
      if (!alias) {
        throw new Error('请填写 alias。')
      }
      const candidates = params.pairsText
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
        .map((item) => {
          const [targetRaw, weightRaw] = item.split(':')
          const target = String(targetRaw || '').trim()
          const weight = Number(weightRaw)
          if (!target || !Number.isFinite(weight) || weight <= 0) {
            throw new Error('weighted 格式应为 model-a:70, model-b:30，且权重大于 0。')
          }
          return { target, weight }
        })

      if (candidates.length === 0) {
        throw new Error('请至少填写一个 weighted 候选模型。')
      }

      const root = _parsePolicyObject()
      root[alias] = {
        strategy: 'weighted',
        candidates,
      }
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const formatSmartRoutingPoliciesJson = () => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const root = _parsePolicyObject()
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const removePolicyByAlias = (alias: string) => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const key = String(alias || '').trim()
      if (!key) {
        throw new Error('alias 不能为空。')
      }
      const root = _parsePolicyObject()
      if (!(key in root)) {
        throw new Error(`未找到 alias=${key} 对应策略。`)
      }
      delete root[key]
      _setPolicyObject(root)
      refreshSmartRoutingPreview()
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const exportPoliciesToClipboard = async () => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const root = _parsePolicyObject()
      const text = JSON.stringify(root, null, 2)
      await navigator.clipboard.writeText(text)
      smartRoutingBuilderInfo.value = '策略已复制到剪贴板。'
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const importPoliciesFromClipboard = async () => {
    smartRoutingBuilderError.value = ''
    smartRoutingBuilderInfo.value = ''
    try {
      const text = await navigator.clipboard.readText()
      const parsed = JSON.parse(String(text || '').trim() || '{}')
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('剪贴板内容不是合法策略对象 JSON。')
      }
      _setPolicyObject(parsed as Record<string, any>)
      refreshSmartRoutingPreview()
      smartRoutingBuilderInfo.value = '已从剪贴板导入策略。'
    } catch (e) {
      smartRoutingBuilderError.value = e instanceof Error ? e.message : String(e)
    }
  }

  const fillSmartRoutingTemplate = () => {
    inferenceSmartRoutingPoliciesJson.value = DEFAULT_SMART_ROUTING_POLICIES_TEMPLATE
    isEditing.value = true
    refreshSmartRoutingPreview()
  }

  const clearSmartRoutingPolicies = () => {
    inferenceSmartRoutingPoliciesJson.value = ''
    isEditing.value = true
    refreshSmartRoutingPreview()
  }

  return {
    autoUnloadLocalModelOnSwitch,
    runtimeAutoReleaseEnabled,
    runtimeMaxCachedLocalRuntimes,
    runtimeMaxCachedLocalLlmRuntimes,
    runtimeMaxCachedLocalVlmRuntimes,
    runtimeMaxCachedLocalImageGenerationRuntimes,
    runtimeReleaseIdleTtlSeconds,
    runtimeReleaseMinIntervalSeconds,
    inferenceSmartRoutingEnabled,
    inferenceSmartRoutingPoliciesJson,
    fillSmartRoutingTemplate,
    clearSmartRoutingPolicies,
    config,
    isSaving,
    saveSuccess,
    saveError,
    smartRoutingJsonError,
    smartRoutingBuilderError,
    smartRoutingBuilderInfo,
    smartRoutingPreview,
    smartRoutingPreviewError,
    smartRoutingSnapshots,
    smartRoutingSnapshotDiff,
    smartRoutingSnapshotDiffError,
    smartRoutingSnapshotDiffAliasFilter,
    isEditing,
    loadConfig,
    handleSave,
    refreshSmartRoutingPreview,
    upsertCanaryPolicy,
    upsertLeastLoadedPolicy,
    upsertWeightedPolicy,
    formatSmartRoutingPoliciesJson,
    removePolicyByAlias,
    exportPoliciesToClipboard,
    importPoliciesFromClipboard,
    restoreSnapshotById,
    compareSnapshotById,
    getFilteredSnapshotDiff,
    copyFilteredSnapshotDiffReport,
    exportFilteredSnapshotDiffAsMarkdown,
  }
}
