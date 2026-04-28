<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Search,
  Plus,
  FileText,
  Code2,
  ChevronLeft,
  ChevronRight,
  Wrench,
  Trash2,
  Sparkles,
  Plug,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  listSkills,
  deleteSkill,
  listAgents,
  skillDiscoverySearch,
  skillDiscoveryRecommend,
  type SkillRecord,
  type SkillDiscoveryItem,
  type AgentDefinition,
} from '@/services/api'
import { isMcpSkillRecord } from '@/utils/skillMeta'

const { t } = useI18n()

const allSkills = ref<SkillRecord[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)

const agents = ref<AgentDefinition[]>([])
const discoveryAgentId = ref('')
const discoveryQuery = ref('')
const discoveryResults = ref<SkillDiscoveryItem[]>([])
const discoveryError = ref<string | null>(null)
const discoveryLoading = ref(false)
const discoveryHasSearched = ref(false)

onMounted(async () => {
  loading.value = true
  loadError.value = null
  try {
    const [skillsRes, agentsRes] = await Promise.all([listSkills(), listAgents().catch(() => null)])
    allSkills.value = skillsRes.data || []
    if (agentsRes?.data?.length) {
      const first = agentsRes.data[0]
      agents.value = agentsRes.data
      if (first?.agent_id) discoveryAgentId.value = first.agent_id
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : t('skills.err_load_list')
    allSkills.value = []
  } finally {
    loading.value = false
  }
})

const runSkillDiscoverySearch = async () => {
  discoveryError.value = null
  if (!discoveryAgentId.value) {
    discoveryError.value = t('skills.discovery_need_agent')
    return
  }
  const q = discoveryQuery.value.trim()
  if (!q) {
    discoveryError.value = t('skills.discovery_query_empty')
    return
  }
  discoveryLoading.value = true
  discoveryResults.value = []
  try {
    const res = await skillDiscoverySearch({
      q,
      agentId: discoveryAgentId.value,
      topK: 12,
    })
    const raw = res.data as
      | SkillDiscoveryItem[]
      | Array<{ skill: SkillDiscoveryItem; semantic_score: number; tag_match_score: number; hybrid_score: number }>
    if (raw.length > 0 && raw[0] && typeof raw[0] === 'object' && 'skill' in raw[0]) {
      discoveryResults.value = (raw as Array<{ skill: SkillDiscoveryItem }>).map((x) => x.skill)
    } else {
      discoveryResults.value = raw as SkillDiscoveryItem[]
    }
    discoveryFilterSource.value = 'all'
  } catch (e) {
    discoveryError.value = e instanceof Error ? e.message : t('skills.err_load')
  } finally {
    discoveryLoading.value = false
    discoveryHasSearched.value = true
  }
}

const runSkillDiscoveryRecommend = async () => {
  discoveryError.value = null
  if (!discoveryAgentId.value) {
    discoveryError.value = t('skills.discovery_need_agent')
    return
  }
  discoveryLoading.value = true
  discoveryResults.value = []
  try {
    const res = await skillDiscoveryRecommend({
      agentId: discoveryAgentId.value,
      limit: 12,
    })
    discoveryResults.value = (res.data || []) as SkillDiscoveryItem[]
    discoveryFilterSource.value = 'all'
  } catch (e) {
    discoveryError.value = e instanceof Error ? e.message : t('skills.err_load')
  } finally {
    discoveryLoading.value = false
    discoveryHasSearched.value = true
  }
}

const searchQuery = ref('')
const filterType = ref('all')
const filterStatus = ref('all')
/** 来源：全部 / 仅 MCP / 非 MCP */
const filterSource = ref<'all' | 'mcp' | 'other'>('all')
/** 语义发现结果来源筛选（与主列表独立） */
const discoveryFilterSource = ref<'all' | 'mcp' | 'other'>('all')
const currentPage = ref(1)
const pageSize = 10

/** 优先使用后端 is_mcp；否则与本地列表或 definition/category 对齐 */
function isMcpDiscoveryItem(s: SkillDiscoveryItem): boolean {
  if (typeof s.is_mcp === 'boolean') return s.is_mcp
  const full = allSkills.value.find((x) => x.id === s.id)
  if (full) return isMcpSkillRecord(full)
  if (Array.isArray(s.category)) {
    if (s.category.some((c) => String(c).toLowerCase() === 'mcp')) return true
  } else if (typeof s.category === 'string' && s.category.toLowerCase() === 'mcp') {
    return true
  }
  const def = s.definition
  if (def && typeof def === 'object' && (def as Record<string, unknown>).kind === 'mcp_stdio') {
    return true
  }
  return false
}

const filteredDiscoveryResults = computed(() => {
  const raw = discoveryResults.value
  if (discoveryFilterSource.value === 'mcp') {
    return raw.filter(isMcpDiscoveryItem)
  }
  if (discoveryFilterSource.value === 'other') {
    return raw.filter((x) => !isMcpDiscoveryItem(x))
  }
  return raw
})

const filteredSkills = computed(() => {
  let list = allSkills.value
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    list = list.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description && s.description.toLowerCase().includes(q)) ||
        (s.category && s.category.toLowerCase().includes(q)) ||
        (s.type && s.type.toLowerCase().includes(q)) ||
        s.id.toLowerCase().includes(q)
    )
  }
  if (filterSource.value === 'mcp') {
    list = list.filter(isMcpSkillRecord)
  } else if (filterSource.value === 'other') {
    list = list.filter((s) => !isMcpSkillRecord(s))
  }
  return list
})

const totalCount = computed(() => filteredSkills.value.length)
const paginatedSkills = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredSkills.value.slice(start, start + pageSize)
})
const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize)))
const rangeStart = computed(() => (currentPage.value - 1) * pageSize + 1)
const rangeEnd = computed(() =>
  Math.min(currentPage.value * pageSize, totalCount.value)
)

const getSkillIcon = (skill: SkillRecord) => {
  if (isMcpSkillRecord(skill)) return Plug
  if (skill.type === 'tool') return Wrench
  if (skill.type === 'composite') return Code2
  return FileText
}

const router = useRouter()
const handleCreateSkill = () => {
  router.push({ name: 'skills-create' })
}

const goToSkillDetail = (skillId: string) => {
  router.push({ name: 'skill-detail', params: { id: skillId } })
}

const handleDeleteSkill = async (skill: SkillRecord, e: Event) => {
  e.stopPropagation()
  if (!window.confirm(t('skills.delete_confirm', { name: skill.name || skill.id }))) return
  try {
    await deleteSkill(skill.id)
    const res = await listSkills()
    allSkills.value = res.data || []
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : t('skills.err_delete')
  }
}

const isBuiltin = (id: string) => (id || '').startsWith('builtin_')

const goPrev = () => {
  if (currentPage.value > 1) currentPage.value--
}
const goNext = () => {
  if (currentPage.value < totalPages.value) currentPage.value++
}
</script>

<template>
  <div class="flex-1 flex flex-col min-h-0 h-full bg-background text-foreground overflow-hidden">
    <!-- Header -->
    <header class="shrink-0 border-b border-border bg-background/95 px-8 pt-8 pb-6">
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-1">
          <h1 class="text-3xl font-bold tracking-tight text-foreground">
            {{ t('skills.title') }}
          </h1>
          <p class="text-sm text-muted-foreground/90">
            {{ t('skills.subtitle') }}
          </p>
        </div>
        <Button
          class="shrink-0 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 rounded-xl shadow-lg shadow-primary/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
          @click="handleCreateSkill"
        >
          <Plus class="w-4 h-4 mr-2" />
          {{ t('skills.create_skill') }}
        </Button>
      </div>

      <!-- Search & Filters -->
      <div class="mt-6 flex flex-wrap items-center gap-3">
        <div class="relative flex-1 min-w-[220px] max-w-md">
          <Search
            class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none"
          />
          <Input
            v-model="searchQuery"
            :placeholder="t('skills.search_placeholder')"
            class="pl-10 h-10 bg-muted/50 border-border rounded-xl text-sm focus-visible:ring-primary/50 focus-visible:border-primary/50 transition-all"
          />
        </div>
        <Select v-model="filterType">
          <SelectTrigger
            class="w-[130px] h-10 bg-muted/50 border-border rounded-xl text-xs"
          >
            <SelectValue :placeholder="t('skills.filter_type')" />
          </SelectTrigger>
          <SelectContent class="bg-card border-border">
            <SelectItem value="all">{{ t('common.all') }}</SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="filterStatus">
          <SelectTrigger
            class="w-[130px] h-10 bg-muted/50 border-border rounded-xl text-xs"
          >
            <SelectValue :placeholder="t('skills.filter_status')" />
          </SelectTrigger>
          <SelectContent class="bg-card border-border">
            <SelectItem value="all">{{ t('common.all') }}</SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="filterSource">
          <SelectTrigger
            class="w-[140px] h-10 bg-muted/50 border-border rounded-xl text-xs"
          >
            <SelectValue :placeholder="t('skills.filter_source')" />
          </SelectTrigger>
          <SelectContent class="bg-card border-border">
            <SelectItem value="all">{{ t('skills.filter_source_all') }}</SelectItem>
            <SelectItem value="mcp">{{ t('skills.filter_source_mcp') }}</SelectItem>
            <SelectItem value="other">{{ t('skills.filter_source_other') }}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div
        v-if="agents.length > 0"
        class="mt-4 rounded-2xl border border-border/60 bg-muted/20 p-4 space-y-3"
      >
        <div class="flex items-center gap-2">
          <Sparkles class="w-4 h-4 text-primary shrink-0" />
          <h2 class="text-sm font-semibold text-foreground">{{ t('skills.discovery_title') }}</h2>
        </div>
        <p class="text-xs text-muted-foreground leading-relaxed">{{ t('skills.discovery_desc') }}</p>
        <div class="flex flex-wrap items-end gap-3">
          <div class="min-w-[200px]">
            <label class="text-[10px] text-muted-foreground block mb-1">{{ t('skills.discovery_agent') }}</label>
            <select
              v-model="discoveryAgentId"
              class="w-full h-9 rounded-lg border border-border bg-background px-2 text-xs"
            >
              <option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
                {{ a.name || a.agent_id }}
              </option>
            </select>
          </div>
          <div class="flex-1 min-w-[200px] max-w-lg">
            <label class="text-[10px] text-muted-foreground block mb-1">{{ t('skills.discovery_query') }}</label>
            <Input
              v-model="discoveryQuery"
              class="h-9 text-sm"
              :placeholder="t('skills.discovery_query')"
              @keydown.enter.prevent="runSkillDiscoverySearch"
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            class="h-9 shrink-0"
            :disabled="discoveryLoading"
            @click="runSkillDiscoverySearch"
          >
            <Search class="w-3.5 h-3.5 mr-1" />
            {{ t('skills.discovery_search') }}
          </Button>
          <Button
            type="button"
            variant="outline"
            class="h-9 shrink-0"
            :disabled="discoveryLoading"
            @click="runSkillDiscoveryRecommend"
          >
            <Sparkles class="w-3.5 h-3.5 mr-1" />
            {{ t('skills.discovery_recommend') }}
          </Button>
        </div>
        <p v-if="discoveryError" class="text-xs text-destructive break-words">{{ discoveryError }}</p>
        <div v-if="discoveryLoading" class="text-xs text-muted-foreground">{{ t('common.loading') }}</div>
        <div
          v-else-if="discoveryResults.length > 0"
          class="flex flex-wrap items-center gap-2"
        >
          <span class="text-[10px] text-muted-foreground shrink-0">{{ t('skills.filter_source') }}</span>
          <Select v-model="discoveryFilterSource">
            <SelectTrigger
              class="w-[140px] h-8 bg-muted/50 border-border rounded-lg text-xs"
            >
              <SelectValue :placeholder="t('skills.filter_source')" />
            </SelectTrigger>
            <SelectContent class="bg-card border-border">
              <SelectItem value="all">{{ t('skills.filter_source_all') }}</SelectItem>
              <SelectItem value="mcp">{{ t('skills.filter_source_mcp') }}</SelectItem>
              <SelectItem value="other">{{ t('skills.filter_source_other') }}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <ul v-if="!discoveryLoading && filteredDiscoveryResults.length > 0" class="flex flex-wrap gap-2 mt-2">
          <li v-for="s in filteredDiscoveryResults" :key="s.id" class="text-xs">
            <button
              type="button"
              class="rounded-lg border border-border bg-card px-2 py-1.5 hover:bg-muted/50 text-left max-w-[min(100%,320px)] inline-flex items-center gap-1.5"
              :title="(s.description as string) || s.id"
              @click="goToSkillDetail(s.id)"
            >
              <Plug
                v-if="isMcpDiscoveryItem(s)"
                class="w-3.5 h-3.5 text-violet-600 dark:text-violet-400 shrink-0"
              />
              <span class="font-mono text-primary truncate">{{ s.id }}</span>
              <Badge
                v-if="isMcpDiscoveryItem(s)"
                variant="outline"
                class="text-[9px] font-bold border-violet-500/40 text-violet-700 dark:text-violet-300 shrink-0 py-0 px-1"
              >
                MCP
              </Badge>
              <span v-if="s.name" class="text-muted-foreground truncate">· {{ s.name }}</span>
            </button>
          </li>
        </ul>
        <p
          v-else-if="
            discoveryHasSearched &&
              !discoveryLoading &&
              discoveryResults.length > 0 &&
              filteredDiscoveryResults.length === 0
          "
          class="text-xs text-muted-foreground mt-2"
        >
          {{ t('skills.discovery_empty_filtered') }}
        </p>
        <p
          v-else-if="discoveryHasSearched && !discoveryLoading && !discoveryError && discoveryResults.length === 0"
          class="text-xs text-muted-foreground"
        >
          {{ t('skills.discovery_empty') }}
        </p>
      </div>
    </header>

    <!-- Table area: fills remaining height -->
    <div class="flex-1 min-h-0 flex flex-col overflow-hidden">
      <div class="flex-1 min-h-0 overflow-auto px-8 py-6 custom-scrollbar">
        <div v-if="loading" class="flex items-center justify-center py-24 text-muted-foreground">
          {{ t('common.loading') }}
        </div>
        <div v-else-if="loadError" class="rounded-2xl border border-red-500/30 bg-red-500/10 px-6 py-4 text-sm text-red-600 dark:text-red-400">
          {{ loadError }}
        </div>
        <div
          v-else
          class="rounded-2xl border border-border bg-card overflow-hidden shadow-sm min-h-full"
        >
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b border-border bg-muted/40">
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('skills.col_name') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('skills.col_description') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('common.category') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('common.type') }}
                </th>
                <th
                  class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
                >
                  {{ t('common.status_label') }}
                </th>
                <th class="px-5 py-3.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground w-20">
                  {{ t('common.actions') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="skill in paginatedSkills"
                :key="skill.id"
                class="border-b border-border/50 hover:bg-muted/25 transition-colors last:border-b-0 cursor-pointer"
                @click="goToSkillDetail(skill.id)"
              >
                <td class="px-5 py-4">
                  <div class="flex items-center gap-3">
                    <div
                      class="w-10 h-10 rounded-xl bg-muted/80 border border-border flex items-center justify-center shrink-0 text-muted-foreground"
                    >
                      <component
                        :is="getSkillIcon(skill)"
                        class="w-5 h-5"
                      />
                    </div>
                    <span class="font-semibold text-foreground">{{ skill.name }}</span>
                    <Badge
                      v-if="isMcpSkillRecord(skill)"
                      variant="outline"
                      class="text-[10px] font-bold border-violet-500/40 text-violet-700 dark:text-violet-300 shrink-0"
                    >
                      MCP
                    </Badge>
                  </div>
                </td>
                <td class="px-5 py-4 max-w-[300px]">
                  <span class="text-sm text-muted-foreground line-clamp-2 leading-relaxed">
                    {{ skill.description || '—' }}
                  </span>
                </td>
                <td class="px-5 py-4">
                  <span class="text-sm text-muted-foreground">{{ skill.category || '—' }}</span>
                </td>
                <td class="px-5 py-4">
                  <span class="text-xs font-mono px-2 py-1 rounded-lg bg-muted border border-border">{{ skill.type && $te('skills.type_' + skill.type) ? t('skills.type_' + skill.type) : (skill.type || '—') }}</span>
                </td>
                <td class="px-5 py-4">
                  <span
                    :class="[
                      'text-xs font-medium px-2 py-1 rounded-lg',
                      skill.enabled ? 'bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20' : 'bg-muted text-muted-foreground border border-border'
                    ]"
                  >
                    {{ skill.enabled ? t('common.enabled') : t('common.disabled') }}
                  </span>
                </td>
                <td class="px-5 py-4" @click.stop>
                  <Button
                    v-if="!isBuiltin(skill.id)"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-destructive"
                    :title="t('skills.delete_skill')"
                    @click="handleDeleteSkill(skill, $event)"
                  >
                    <Trash2 class="w-4 h-4" />
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Empty (only when not loading and no error) -->
        <div
          v-if="!loading && !loadError && filteredSkills.length === 0"
          class="flex flex-col items-center justify-center py-24 text-center"
        >
          <div
            class="w-20 h-20 rounded-2xl bg-muted border border-border flex items-center justify-center mb-5"
          >
            <Search class="w-10 h-10 text-muted-foreground/50" />
          </div>
          <p class="text-base font-semibold text-foreground">{{ t('common.no_results') }}</p>
          <p class="text-sm text-muted-foreground mt-1">{{ t('common.no_results_hint') }}</p>
        </div>
      </div>

      <!-- Pagination -->
      <footer
        class="shrink-0 border-t border-border bg-muted/30 px-8 py-3.5 flex items-center justify-between"
      >
        <p class="text-xs font-medium text-muted-foreground">
          {{ t('skills.pagination_show', { start: rangeStart, end: rangeEnd, total: totalCount }) }}
        </p>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            class="h-9 rounded-xl border-border text-muted-foreground hover:text-foreground hover:bg-muted/80"
            :disabled="currentPage <= 1"
            @click="goPrev"
          >
            <ChevronLeft class="w-4 h-4 mr-1" />
            {{ t('common.prev') }}
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="h-9 rounded-xl border-border text-muted-foreground hover:text-foreground hover:bg-muted/80"
            :disabled="currentPage >= totalPages"
            @click="goNext"
          >
            {{ t('common.next') }}
            <ChevronRight class="w-4 h-4 ml-1" />
          </Button>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: hsl(var(--muted-foreground) / 0.2);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground) / 0.35);
}
</style>
