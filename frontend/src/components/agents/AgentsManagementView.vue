<script setup lang="ts">
import { ref, computed, onMounted, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  Bot, 
  Plus, 
  Search, 
  Code2, 
  FileText, 
  Cpu, 
  HardDrive, 
  Settings2, 
  Activity, 
  History, 
  AlertCircle,
  Terminal,
  FileCode,
  Globe,
  Database,
  SearchCode,
  Binary,
  Wrench,
  Trash2,
  Lightbulb,
  Wand2,
  Plug,
  Layers2,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import {
  listAgents,
  listModels,
  deleteAgent,
  createAgent,
  generateAgentFromNl,
  type AgentModelParamsJsonMap,
  type ModelInfo,
  type GenerateAgentFromNlResponse,
} from '@/services/api'
import { useSystemMetrics } from '@/composables/useSystemMetrics'
import { useSystemConfigWithDebounce } from '@/composables/useSystemConfigWithDebounce'
import { readRagMultiHopEnabledFromModelParams } from '@/utils/agentRagModelParams'
import { formatAgentMutationErrorMessage } from '@/utils/agentMutationMessages'
// Loading State
const loading = ref(true)
/** listAgents + listModels 拉取失败 */
const agentsListError = ref<string | null>(null)
const agents = ref<any[]>([])
const modelsIndex = ref<Record<string, ModelInfo>>({})
const searchQuery = ref('')
const selectedModelFamily = ref<string>('all')
const selectedStatus = ref<string>('all')
const selectedRag = ref<string>('all')
const selectedTool = ref<string>('all')
/** 已启技能中是否含 MCP（与技能中心 / 元信息一致） */
const selectedMcp = ref<'all' | 'with_mcp' | 'without_mcp'>('all')
/** 工具失败反思建议 model_params.tool_failure_reflection */
const selectedReflection = ref<string>('all')


// Extract model family from model name or ID
const extractModelFamily = (modelName: string, modelId: string): string => {
  const combined = `${modelName} ${modelId}`.toLowerCase()
  
  // Common model families
  if (combined.includes('llama') || combined.includes('llama2') || combined.includes('llama3')) {
    return 'llama'
  }
  if (combined.includes('mistral')) {
    return 'mistral'
  }
  if (combined.includes('gpt') || combined.includes('openai')) {
    return 'gpt'
  }
  if (combined.includes('claude') || combined.includes('anthropic')) {
    return 'claude'
  }
  if (combined.includes('gemini') || combined.includes('google')) {
    return 'gemini'
  }
  if (combined.includes('qwen')) {
    return 'qwen'
  }
  if (combined.includes('deepseek')) {
    return 'deepseek'
  }
  if (combined.includes('kimi')) {
    return 'kimi'
  }
  
  return 'other'
}

// Get available model families from agents
const availableModelFamilies = computed(() => {
  const families = new Set<string>()
  agents.value.forEach(agent => {
    if (agent.model_family && agent.model_family !== 'other') {
      families.add(agent.model_family)
    }
  })
  return Array.from(families).sort()
})

// Helper function to get localized family name
const getFamilyLabel = (family: string) => {
  const key = `agents.filters.${family}`
  const translated = t(key)
  // If translation key doesn't exist, t() returns the key itself
  if (translated === key) {
    return family.charAt(0).toUpperCase() + family.slice(1)
  }
  return translated
}

// Helper function to get localized tool name (handles keys with dots like "file.read")
const getToolName = (toolId: string) => {
  if (!toolId) return toolId
  
  // For keys with dots like "file.read", vue-i18n interprets them as nested paths
  // So we need to access the messages object directly using bracket notation
  try {
    const currentLocale = i18n.locale.value
    const messages = (i18n as any).messages.value[currentLocale] || (i18n as any).messages.value.en
    const tools = messages?.agents?.tools
    // Access tool name using bracket notation to handle keys with dots
    if (tools && tools[toolId]) {
      return tools[toolId]
    }
  } catch (e) {
    // Fallback to t() function
  }
  
  // Try using t() function with the key
  const key = `agents.tools.${toolId}`
  const translated = t(key)
  
  // If translation returns the key path itself (meaning not found), use fallback
  if (translated === key || translated.includes('agents.tools')) {
    // Fallback: format tool ID nicely (e.g., "file.read" -> "File Read")
    return toolId.split('.').map(part => 
      part.charAt(0).toUpperCase() + part.slice(1)
    ).join(' ')
  }
  
  return translated
}

const fetchAgents = async (showLoading = true) => {
  try {
    if (showLoading) loading.value = true
    agentsListError.value = null
    const [agentsRes, modelsRes] = await Promise.all([
      listAgents(),
      listModels(),
    ])

    const nextIndex: Record<string, ModelInfo> = {}
    for (const m of (modelsRes.data || [])) nextIndex[m.id] = m
    modelsIndex.value = nextIndex

    const res = agentsRes
    console.log('[AgentsManagementView] Fetched agents:', res)
    // Map backend AgentDefinition to UI-friendly objects
    // Handle case where res.data might be undefined or null
    const agentsList = res?.data || []
    console.log('[AgentsManagementView] Agents list:', agentsList)
    agents.value = agentsList.map((agent: any) => {
      const modelInfo = modelsIndex.value[agent.model_id]
      const runtimeBackend = modelInfo?.backend || null
      const modelName = modelInfo?.name || agent.model_id || ''
      const modelFamily = extractModelFamily(modelName, agent.model_id)
      // v1.5: prefer enabled_skills; fallback to tool_ids as builtin_<id>
      const effectiveSkills: string[] = (agent.enabled_skills && agent.enabled_skills.length > 0)
        ? agent.enabled_skills
        : (agent.tool_ids || []).map((t: string) => `builtin_${t}`)
      const hasWeb = effectiveSkills.some((id: string) => id.includes('web') || id === 'builtin_web.search')
      const hasPython = effectiveSkills.some((id: string) => id.includes('python') || id === 'builtin_python.run')
      // Display list: builtin_* -> tool name, else skill id (for badges & filter)
      const tools = effectiveSkills.map((s: string) => s.startsWith('builtin_') ? s.slice(8) : s)
      const meta = agent.enabled_skills_meta as
        | Array<{ id: string; name: string; is_mcp: boolean }>
        | undefined
      const skillChips = effectiveSkills.map((skillId: string) => {
        const slug = skillId.startsWith('builtin_') ? skillId.slice(8) : skillId
        const m = meta?.find((x) => x.id === skillId)
        const nm = (m?.name || '').trim()
        const label = nm && m ? m.name : getToolName(slug)
        return {
          key: skillId,
          slug,
          label,
          isMcp: m ? !!m.is_mcp : false,
        }
      })
      const has_mcp_skill = skillChips.some((c) => c.isMcp)
      const mp =
        agent.model_params && typeof agent.model_params === 'object'
          ? (agent.model_params as AgentModelParamsJsonMap)
          : null
      const tfr = mp?.tool_failure_reflection
      const toolFailureReflection =
        Boolean(tfr && typeof tfr === 'object' && (tfr as { enabled?: boolean }).enabled === true)
      const ragIdsLen = agent.rag_ids?.length || 0
      const ragMultiHop =
        ragIdsLen > 0 && readRagMultiHopEnabledFromModelParams(mp as Record<string, unknown> | null)
      return ({
      id: agent.agent_id,
      name: agent.name,
      description: agent.description || '',
      status: 'READY', // Default status
      model: agent.model_id,
      model_family: modelFamily,
      runtime_backend: runtimeBackend,
      runtime_label: runtimeLabelForBackend(runtimeBackend),
      rag_count: ragIdsLen,
      rag_multi_hop: ragMultiHop,
      tools,
      skillChips,
      has_mcp_skill,
      tool_failure_reflection: toolFailureReflection,
      icon: hasWeb ? Globe : (hasPython ? Code2 : Bot),
      color: hasWeb ? 'blue' : (hasPython ? 'orange' : 'indigo')
      })
    })
    console.log('[AgentsManagementView] Mapped agents:', agents.value)
  } catch (error) {
    console.error('[AgentsManagementView] Failed to fetch agents:', error)
    agentsListError.value =
      formatAgentMutationErrorMessage(error, t) || t('agents.list_load_failed')
    agents.value = []
  } finally {
    if (showLoading) loading.value = false
    console.log('[AgentsManagementView] Loading state:', loading.value, 'Agents count:', agents.value.length)
  }
}

const { metrics } = useSystemMetrics()
const { systemConfig, refreshSystemConfig } = useSystemConfigWithDebounce({
  logPrefix: 'AgentsManagementView',
})
const wasDeactivated = ref(false)

// Format last heartbeat time
const lastHeartbeat = computed(() => {
  // Use current time as last heartbeat timestamp
  const now = new Date()
  return now.toISOString().replace('T', ' ').substring(0, 19) + ' UTC'
})

onMounted(async () => {
  await fetchAgents()
  await refreshSystemConfig()
})

onDeactivated(() => { wasDeactivated.value = true })

// 从创建/编辑页返回时静默刷新列表，保证新数据可见
onActivated(() => {
  if (wasDeactivated.value) {
    wasDeactivated.value = false
    fetchAgents(false)
  }
})

const getStatusColor = (status: string) => {
  switch (status) {
    case 'RUNNING': return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
    case 'READY': return 'bg-blue-500/10 text-blue-500 border-blue-500/20'
    case 'ERROR': return 'bg-rose-500/10 text-rose-500 border-rose-500/20'
    default: return 'bg-muted text-muted-foreground'
  }
}

const getAgentIconBg = (color: string) => {
  const mapping: Record<string, string> = {
    blue: 'bg-blue-500/10 text-blue-500',
    indigo: 'bg-indigo-500/10 text-indigo-500',
    rose: 'bg-rose-500/10 text-rose-500',
    violet: 'bg-violet-500/10 text-violet-500',
    orange: 'bg-orange-500/10 text-orange-500',
    fuchsia: 'bg-fuchsia-500/10 text-fuchsia-500'
  }
  return mapping[color] || 'bg-muted text-foreground'
}

const router = useRouter()
const i18n = useI18n()
const { t } = i18n

const runtimeLabelForBackend = (backend?: string | null) => {
  const b = (backend || '').toLowerCase()
  const mapping: Record<string, string> = {
    ollama: t('agents.execution.runtime_ollama'),
    lmstudio: t('agents.execution.runtime_lmstudio'),
    local: t('agents.execution.runtime_local'),
    openai: t('agents.execution.runtime_openai'),
    gemini: t('agents.execution.runtime_gemini'),
    deepseek: t('agents.execution.runtime_deepseek'),
    kimi: t('agents.execution.runtime_kimi'),
    mock: t('agents.execution.runtime_mock'),
  }
  return mapping[b] || (backend ? backend : t('agents.unknown'))
}

// Filtered agents based on search query and filters
const filteredAgents = computed(() => {
  let result = agents.value
  
  // Filter by model family
  if (selectedModelFamily.value !== 'all') {
    result = result.filter(agent => agent.model_family === selectedModelFamily.value)
  }
  
  // Filter by status
  if (selectedStatus.value !== 'all') {
    result = result.filter(agent => agent.status?.toLowerCase() === selectedStatus.value.toLowerCase())
  }
  
  // Filter by RAG
  if (selectedRag.value === 'enabled') {
    result = result.filter(agent => agent.rag_count > 0)
  } else if (selectedRag.value === 'disabled') {
    result = result.filter(agent => agent.rag_count === 0)
  } else if (selectedRag.value === 'multi_hop') {
    result = result.filter((agent) => agent.rag_multi_hop === true)
  }
  
  // Filter by tool
  if (selectedTool.value !== 'all') {
    result = result.filter(agent => agent.tools?.includes(selectedTool.value))
  }

  if (selectedMcp.value === 'with_mcp') {
    result = result.filter((agent) => agent.has_mcp_skill === true)
  } else if (selectedMcp.value === 'without_mcp') {
    result = result.filter((agent) => !agent.has_mcp_skill)
  }

  if (selectedReflection.value === 'on') {
    result = result.filter((agent) => agent.tool_failure_reflection === true)
  } else if (selectedReflection.value === 'off') {
    result = result.filter((agent) => !agent.tool_failure_reflection)
  }
  
  // Filter by search query
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim()
    result = result.filter(agent => {
      // Search in name
      if (agent.name?.toLowerCase().includes(query)) return true
      // Search in description
      if (agent.description?.toLowerCase().includes(query)) return true
      // Search in model ID
      if (agent.model?.toLowerCase().includes(query)) return true
      // Search in runtime label
      if (agent.runtime_label?.toLowerCase().includes(query)) return true
      // Search in tool names
      if (agent.tools?.some((tool: string) => tool.toLowerCase().includes(query))) return true
      if (
        agent.skillChips?.some((c: { label: string }) =>
          (c.label || '').toLowerCase().includes(query),
        )
      ) {
        return true
      }
      return false
    })
  }
  
  return result
})

const handleCreateAgent = () => {
  router.push('/agents/create')
}

const nlOpen = ref(false)
const nlDescription = ref('')
/** 选中的模型 id；__default__ 表示交给后端选默认模型 */
const nlModelId = ref<string>('__default__')
const nlBusy = ref(false)
const nlCreating = ref(false)
const nlResult = ref<GenerateAgentFromNlResponse | null>(null)

const modelOptions = computed(() => Object.values(modelsIndex.value))

const openNlDialog = () => {
  nlDescription.value = ''
  nlModelId.value = '__default__'
  nlResult.value = null
  nlOpen.value = true
}

const closeNlDialog = () => {
  nlOpen.value = false
}

const runNlGenerate = async () => {
  const q = nlDescription.value.trim()
  if (q.length < 4) {
    alert(t('agents.nl.err_short'))
    return
  }
  nlBusy.value = true
  nlResult.value = null
  try {
    nlResult.value = await generateAgentFromNl({
      description: q,
      model_id: nlModelId.value === '__default__' ? undefined : nlModelId.value,
      top_skills: 12,
    })
  } catch (e) {
    alert(e instanceof Error ? e.message : t('agents.nl.loading'))
  } finally {
    nlBusy.value = false
  }
}

const confirmNlCreate = async () => {
  const d = nlResult.value?.draft
  if (!d?.name?.trim() || !d.model_id) return
  nlCreating.value = true
  try {
    const agent = await createAgent({
      name: d.name.trim(),
      description: (d.description || '').trim(),
      model_id: d.model_id,
      system_prompt: (d.system_prompt || '').trim(),
      enabled_skills: d.enabled_skills || [],
      execution_mode: d.execution_mode || 'legacy',
      max_steps: d.max_steps ?? 20,
      temperature: d.temperature ?? 0.7,
    })
    nlOpen.value = false
    await fetchAgents(false)
    router.push(`/agents/${agent.agent_id}/edit`)
  } catch (e) {
    alert(formatAgentMutationErrorMessage(e, t) || 'Create failed')
  } finally {
    nlCreating.value = false
  }
}

const handleRunAgent = (agentId: string) => {
  router.push(`/agents/${agentId}/run`)
}

const handleEditAgent = (agentId: string) => {
  router.push(`/agents/${agentId}/edit`)
}

const deletingId = ref<string | null>(null)
const handleDeleteAgent = async (agentId: string, agentName: string) => {
  if (!window.confirm(t('agents.delete_confirm', { name: agentName }))) {
    return
  }
  deletingId.value = agentId
  try {
    await deleteAgent(agentId)
    agents.value = agents.value.filter((a) => a.id !== agentId)
  } catch (error) {
    console.error('Failed to delete agent:', error)
    alert(formatAgentMutationErrorMessage(error, t) || t('agents.delete_failed'))
  } finally {
    deletingId.value = null
  }
}
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="pt-8 pb-6 px-8 flex items-start justify-between shrink-0 border-b border-border">
      <div class="space-y-1">
        <h1 class="text-3xl font-bold tracking-tight text-foreground">{{ t('agents.title') }}</h1>
        <p class="text-muted-foreground/80">{{ t('agents.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-4">
        <div class="relative w-80">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input 
            v-model="searchQuery"
            :placeholder="t('agents.search_placeholder')" 
            class="pl-10 h-10 bg-muted border-border focus:border-blue-500/50 transition-all rounded-lg text-sm"
          />
        </div>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            class="h-10 px-4 gap-2 rounded-lg border-border"
            @click="openNlDialog"
          >
            <Wand2 class="w-4 h-4" />
            {{ t('agents.nl.open') }}
          </Button>
          <Button @click="handleCreateAgent" class="bg-blue-600 hover:bg-blue-700 text-white font-bold h-10 px-4 gap-2 rounded-lg shadow-lg shadow-blue-500/20">
            <Plus class="w-4 h-4" />
            {{ t('agents.create_button') }}
          </Button>
        </div>
      </div>
    </header>

    <div v-if="agentsListError && !loading" class="px-8 pb-4 shrink-0">
      <div
        class="text-sm text-destructive rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3"
      >
        {{ agentsListError }}
      </div>
    </div>

    <!-- Filters -->
    <div v-if="!loading && agents.length > 0" class="px-8 pb-6 flex items-center gap-3 shrink-0 border-b border-border">
      <Select v-model="selectedModelFamily">
        <SelectTrigger class="w-[160px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.model_family') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem 
            v-for="family in availableModelFamilies" 
            :key="family" 
            :value="family"
          >
            {{ getFamilyLabel(family) }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedStatus">
        <SelectTrigger class="w-[130px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.status') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="running">{{ t('agents.filters.running') }}</SelectItem>
          <SelectItem value="ready">{{ t('agents.filters.ready') }}</SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedRag">
        <SelectTrigger class="w-[140px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.rag') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="enabled">{{ t('agents.filters.enabled') }}</SelectItem>
          <SelectItem value="disabled">{{ t('agents.filters.disabled') }}</SelectItem>
          <SelectItem value="multi_hop">{{ t('agents.filters.rag_multi_hop') }}</SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedTool">
        <SelectTrigger class="w-[120px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.tools') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="terminal">{{ t('agents.filters.terminal') }}</SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedMcp">
        <SelectTrigger class="w-[150px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.mcp_skills') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="with_mcp">{{ t('agents.filters.mcp_with') }}</SelectItem>
          <SelectItem value="without_mcp">{{ t('agents.filters.mcp_without') }}</SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="selectedReflection">
        <SelectTrigger class="w-[150px] h-9 bg-muted border-border rounded-md text-xs">
          <span class="text-muted-foreground mr-1">{{ t('agents.filters.reflection') }}:</span>
          <SelectValue :placeholder="t('agents.filters.all')" />
        </SelectTrigger>
        <SelectContent class="bg-card border-border">
          <SelectItem value="all">{{ t('agents.filters.all') }}</SelectItem>
          <SelectItem value="on">{{ t('agents.filters.reflection_on') }}</SelectItem>
          <SelectItem value="off">{{ t('agents.filters.reflection_off') }}</SelectItem>
        </SelectContent>
      </Select>

      <button 
        @click="selectedModelFamily = 'all'; selectedStatus = 'all'; selectedRag = 'all'; selectedTool = 'all'; selectedMcp = 'all'; selectedReflection = 'all'; searchQuery = ''"
        class="text-xs font-medium text-muted-foreground/60 hover:text-foreground transition-colors ml-2"
      >
        {{ t('agents.filters.clear_all') }}
      </button>
    </div>

    <!-- Agent Grid -->
    <div v-if="!loading && filteredAgents.length > 0" class="flex-1 min-h-0 overflow-y-auto px-8 pb-8 custom-scrollbar">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div 
          v-for="agent in filteredAgents" 
          :key="agent.id"
          class="bg-card border border-border rounded-2xl p-6 flex flex-col gap-5 hover:border-border transition-all group"
        >
          <!-- Card Header -->
          <div class="flex items-start justify-between">
            <div class="flex items-center gap-4">
              <div :class="['w-12 h-12 rounded-xl flex items-center justify-center shrink-0 shadow-inner cursor-pointer hover:scale-105 transition-transform', getAgentIconBg(agent.color)]" @click="handleRunAgent(agent.id)">
                <component :is="agent.icon" class="w-6 h-6" />
              </div>
              <div>
                <h3 class="text-xl font-bold text-foreground group-hover:text-blue-500 transition-colors cursor-pointer" @click="handleRunAgent(agent.id)">{{ agent.name }}</h3>
              </div>
            </div>
            <div class="flex flex-col items-end gap-1.5">
              <Badge :class="['px-2.5 py-0.5 rounded-full text-[10px] font-black tracking-widest border', getStatusColor(agent.status)]">
                {{ agent.status === 'RUNNING' ? t('agents.status.running') : (agent.status === 'READY' ? t('agents.status.ready') : t('agents.status.error')) }}
              </Badge>
              <Badge
                v-if="agent.has_mcp_skill"
                variant="outline"
                class="px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide border-violet-500/40 bg-violet-500/10 text-violet-800 dark:text-violet-200 gap-1"
              >
                <Plug class="w-3 h-3" />
                MCP
              </Badge>
              <Badge
                v-if="agent.tool_failure_reflection"
                variant="outline"
                class="px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200 gap-1"
              >
                <Lightbulb class="w-3 h-3" />
                {{ t('agents.card.reflection_badge') }}
              </Badge>
              <Badge
                v-if="agent.rag_multi_hop"
                variant="outline"
                class="px-2 py-0.5 rounded-full text-[9px] font-bold tracking-wide border-cyan-500/40 bg-cyan-500/10 text-cyan-800 dark:text-cyan-200 gap-1"
              >
                <Layers2 class="w-3 h-3" />
                {{ t('agents.card.rag_mh_badge') }}
              </Badge>
            </div>
          </div>

          <!-- Description -->
          <p class="text-muted-foreground/90 text-[13px] leading-relaxed line-clamp-2">
            {{ agent.description }}
          </p>

          <!-- Error Message (if any) -->
          <div v-if="agent.error" class="bg-rose-500/10 border border-rose-500/20 rounded-lg p-3 flex items-start gap-3">
            <AlertCircle class="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
            <p class="text-[11px] font-bold text-rose-500/90 leading-tight">{{ agent.error }}</p>
          </div>

          <!-- Meta Info -->
          <div class="space-y-3">
            <div class="flex items-center gap-3 text-[11px] text-muted-foreground/70 font-medium">
              <Binary class="w-3.5 h-3.5" />
              <span>{{ agent.model }} <span class="mx-1.5 opacity-30">•</span> {{ agent.runtime_label }}</span>
            </div>
            <div class="flex items-center gap-3 text-[11px] text-muted-foreground/70 font-medium">
              <Database class="w-3.5 h-3.5" />
              <span>{{ t('agents.card.rag') }}: <span class="text-muted-foreground">{{ agent.rag_count > 0 ? `${agent.rag_count} ${t('agents.card.sources')}` : t('agents.card.disabled') }}</span></span>
            </div>
          </div>

          <!-- Skills / tools -->
          <div class="flex flex-wrap gap-2">
            <div 
              v-for="chip in agent.skillChips" 
              :key="chip.key"
              :class="[
                'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[10px] font-bold transition-all cursor-default max-w-full',
                chip.isMcp
                  ? 'bg-violet-500/10 border-violet-500/25 text-violet-900 dark:text-violet-100'
                  : 'bg-muted border-border text-muted-foreground hover:bg-muted/80 hover:text-foreground',
              ]"
            >
              <Plug v-if="chip.isMcp" class="w-3 h-3 shrink-0 text-violet-600 dark:text-violet-400" />
              <Globe v-else-if="chip.slug === 'web-search' || chip.slug === 'web.search'" class="w-3 h-3 shrink-0" />
              <Code2 v-else-if="chip.slug === 'python-interpreter' || chip.slug === 'python.run'" class="w-3 h-3 shrink-0" />
              <Database v-else-if="chip.slug === 'sql-engine' || chip.slug === 'sql.query'" class="w-3 h-3 shrink-0" />
              <FileText v-else-if="chip.slug === 'file.read' || chip.slug === 'file.list' || chip.slug === 'content-gen'" class="w-3 h-3 shrink-0" />
              <Terminal v-else-if="chip.slug === 'terminal'" class="w-3 h-3 shrink-0" />
              <FileCode v-else-if="chip.slug === 'fs-access'" class="w-3 h-3 shrink-0" />
              <SearchCode v-else-if="chip.slug === 'audit' || chip.slug === 'scanner'" class="w-3 h-3 shrink-0" />
              <Activity v-else-if="chip.slug === 'metrics'" class="w-3 h-3 shrink-0" />
              <Wrench v-else class="w-3 h-3 shrink-0 opacity-70" />
              <span class="truncate min-w-0">{{ chip.label }}</span>
            </div>
          </div>

          <!-- Card Footer -->
          <div class="mt-auto pt-4 border-t border-border flex items-center justify-between">
            <div class="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                class="h-8 rounded-lg bg-muted border-border text-muted-foreground hover:text-foreground hover:bg-muted/80"
                @click="handleRunAgent(agent.id)"
              >
                {{ t('agents.card.run') }}
              </Button>
            </div>
            <div class="flex items-center gap-1">
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted" @click="handleRunAgent(agent.id)">
                <History v-if="agent.status === 'ERROR'" class="w-4 h-4" />
                <Activity v-else class="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground hover:bg-muted" @click="handleEditAgent(agent.id)" :title="t('agents.card.edit')">
                <Settings2 class="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-red-500 hover:bg-red-500/10" :title="t('agents.card.delete')" :disabled="deletingId === agent.id" @click.stop="handleDeleteAgent(agent.id, agent.name)">
                <Trash2 class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- No Search Results -->
    <div v-if="!loading && agents.length > 0 && filteredAgents.length === 0" class="flex-1 min-h-0 flex flex-col items-center justify-center p-8 text-center">
      <div class="w-24 h-24 rounded-full bg-muted border border-border flex items-center justify-center mb-6 shadow-2xl">
        <Search class="w-12 h-12 text-blue-500/50" />
      </div>
      <h2 class="text-2xl font-bold text-foreground mb-2">{{ t('agents.search_no_results') }}</h2>
      <p class="text-muted-foreground/80 max-w-md mb-8 leading-relaxed">
        {{ t('agents.search_no_results_desc', { query: searchQuery }) }}
      </p>
      <Button @click="searchQuery = ''" variant="outline" class="border-border text-muted-foreground hover:text-foreground hover:bg-muted">
        {{ t('agents.search_clear') }}
      </Button>
    </div>

    <!-- Empty State -->
    <div v-if="!loading && agents.length === 0" class="flex-1 min-h-0 flex flex-col items-center justify-center p-8 text-center">
      <div class="w-24 h-24 rounded-full bg-muted border border-border flex items-center justify-center mb-6 shadow-2xl">
        <Bot class="w-12 h-12 text-blue-500/50" />
      </div>
      <h2 class="text-2xl font-bold text-foreground mb-2">{{ t('agents.empty_state.title') }}</h2>
      <p class="text-muted-foreground/80 max-w-md mb-8 leading-relaxed">
        {{ t('agents.empty_state.subtitle') }}
      </p>
      <div class="flex flex-col sm:flex-row gap-3 justify-center">
        <Button variant="outline" class="h-12 px-8 gap-2 rounded-xl border-border" @click="openNlDialog">
          <Wand2 class="w-5 h-5" />
          {{ t('agents.nl.open') }}
        </Button>
        <Button @click="handleCreateAgent" class="bg-blue-600 hover:bg-blue-700 text-white font-bold h-12 px-8 gap-2 rounded-xl shadow-lg shadow-blue-500/20 transition-all hover:scale-105 active:scale-95">
          <Plus class="w-5 h-5" />
          {{ t('agents.empty_state.create_first') }}
        </Button>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex-1 min-h-0 flex items-center justify-center">
      <div class="flex flex-col items-center gap-4">
        <div class="w-10 h-10 border-2 border-blue-600/20 border-t-blue-600 rounded-full animate-spin"></div>
        <p class="text-xs font-black tracking-widest uppercase text-muted-foreground/60 animate-pulse">{{ t('agents.loading') }}</p>
      </div>
    </div>

    <!-- Page Footer (System Info) -->
    <Teleport to="body">
      <div
        v-if="nlOpen"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        @click.self="closeNlDialog"
      >
        <div
          class="bg-card border border-border rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden"
          @click.stop
        >
          <div class="px-6 pt-6 pb-4 border-b border-border shrink-0">
            <h2 class="text-xl font-bold text-foreground">{{ t('agents.nl.title') }}</h2>
            <p class="text-sm text-muted-foreground mt-1">{{ t('agents.nl.subtitle') }}</p>
          </div>
          <div class="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-4">
            <div class="space-y-2">
              <label class="text-xs font-semibold text-muted-foreground" for="agent-nl-desc">{{ t('agents.create.desc_label') }}</label>
              <Textarea
                id="agent-nl-desc"
                v-model="nlDescription"
                class="min-h-[100px] bg-muted border-border text-sm"
                :placeholder="t('agents.nl.placeholder')"
              />
            </div>
            <div class="space-y-2">
              <label class="text-xs font-semibold text-muted-foreground" for="agent-nl-model">{{ t('agents.nl.model_label') }}</label>
              <Select v-model="nlModelId">
                <SelectTrigger id="agent-nl-model" class="w-full h-10 bg-muted border-border rounded-lg text-sm">
                  <SelectValue :placeholder="t('agents.nl.model_default')" />
                </SelectTrigger>
                <SelectContent class="bg-card border-border max-h-[240px]">
                  <SelectItem value="__default__">{{ t('agents.nl.model_default') }}</SelectItem>
                  <SelectItem v-for="m in modelOptions" :key="m.id" :value="m.id">
                    {{ m.name || m.id }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="flex gap-2">
              <Button
                class="bg-blue-600 hover:bg-blue-700 text-white"
                :disabled="nlBusy"
                @click="runNlGenerate"
              >
                {{ nlBusy ? t('agents.nl.loading') : t('agents.nl.generate') }}
              </Button>
              <Button variant="outline" :disabled="nlBusy || nlCreating" @click="closeNlDialog">
                {{ t('agents.nl.close') }}
              </Button>
            </div>
            <div v-if="nlResult" class="space-y-3 pt-2 border-t border-border">
              <p v-if="!nlResult.llm_used" class="text-xs text-amber-600 dark:text-amber-400">
                {{ t('agents.nl.llm_off') }}
              </p>
              <p v-if="nlResult.warnings?.length" class="text-xs text-muted-foreground">
                {{ t('agents.nl.warnings') }}: {{ nlResult.warnings.join(', ') }}
              </p>
              <div class="space-y-1">
                <p class="text-xs font-semibold text-muted-foreground">{{ t('agents.nl.matched') }}</p>
                <div class="flex flex-wrap gap-1.5">
                  <Badge
                    v-for="s in nlResult.matched_skills"
                    :key="s.skill_id"
                    variant="outline"
                    class="text-[10px]"
                  >
                    {{ s.name }}
                  </Badge>
                  <span v-if="!nlResult.matched_skills?.length" class="text-xs text-muted-foreground">—</span>
                </div>
              </div>
              <div class="rounded-lg border border-border bg-muted/40 p-3 space-y-2 text-sm">
                <div><span class="text-muted-foreground">{{ t('agents.nl.draft_name') }}:</span> {{ nlResult.draft.name }}</div>
                <div><span class="text-muted-foreground">{{ t('agents.nl.draft_desc') }}:</span> {{ nlResult.draft.description }}</div>
                <div><span class="text-muted-foreground">{{ t('agents.nl.draft_mode') }}:</span> {{ nlResult.draft.execution_mode }}</div>
                <div>
                  <span class="text-muted-foreground">{{ t('agents.nl.draft_skills') }}:</span>
                  {{ (nlResult.draft.enabled_skills || []).join(', ') || '—' }}
                </div>
                <div class="text-xs whitespace-pre-wrap max-h-40 overflow-y-auto">
                  <span class="text-muted-foreground block mb-1">{{ t('agents.nl.draft_prompt') }}</span>
                  {{ nlResult.draft.system_prompt }}
                </div>
              </div>
              <Button
                class="w-full bg-emerald-600 hover:bg-emerald-700 text-white"
                :disabled="nlCreating"
                @click="confirmNlCreate"
              >
                {{ nlCreating ? '…' : t('agents.nl.create') }}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <footer class="h-12 border-t border-border bg-muted px-8 flex items-center justify-between shrink-0 text-[10px] font-bold tracking-tight uppercase">
      <div class="flex items-center gap-6">
        <div class="flex items-center gap-2">
          <div class="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"></div>
          <span class="text-muted-foreground/60">{{ t('agents.footer.local_engine') }}: <span class="text-foreground ml-1">{{ systemConfig?.version || t('agents.not_available') }}</span></span>
        </div>
        <div class="flex items-center gap-2">
          <HardDrive class="w-3.5 h-3.5 text-muted-foreground/40" />
          <span class="text-muted-foreground/60">{{ t('agents.footer.vram_usage') }}: <span class="text-foreground ml-1">{{ t('agents.footer.gb_format', { n: metrics?.vram_used?.toFixed(1) || '0' }) }} / {{ t('agents.footer.gb_format', { n: metrics?.vram_total?.toFixed(1) || '0' }) }}</span></span>
        </div>
        <div class="flex items-center gap-2">
          <Cpu class="w-3.5 h-3.5 text-muted-foreground/40" />
          <span class="text-muted-foreground/60">{{ t('agents.footer.cpu_load') }}: <span class="text-foreground ml-1">{{ Math.round(metrics?.cpu_load || 0) }}%</span></span>
        </div>
      </div>
      <div class="text-muted-foreground/40">
        {{ t('agents.footer.last_heartbeat') }}: {{ lastHeartbeat }}
      </div>
    </footer>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 5px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.25);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.1);
}
</style>
