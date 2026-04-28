<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ChevronLeft,
  ChevronRight,
  Sliders,
  Cpu,
  ScanSearch,
  Mic,
  Database,
  FileJson,
  Zap,
  Plug,
  Trash2,
  RefreshCw,
  Boxes,
  Plus,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import {
  createMcpServer,
  deleteMcpServer,
  getMcpServerTools,
  importMcpTools,
  listMcpServers,
  mcpProbe,
  getSystemConfig,
  updateSystemConfig,
  type McpServerRecord,
} from '@/services/api'
import { useDebouncedOnSystemConfigChange } from '@/composables/useDebouncedOnSystemConfigChange'
import { Switch } from '@/components/ui/switch'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const settingsSection = computed(() => route.name as string)
const navCollapsed = ref(false)

const servers = ref<McpServerRecord[]>([])
const loading = ref(false)
const errorMsg = ref('')

const probeTransport = ref<'stdio' | 'http'>('stdio')
const probeCommandText = ref('npx\n-y\n@modelcontextprotocol/server-filesystem\n/tmp')
const probeUrl = ref('')
const probeEnvText = ref('')
const probeCwd = ref('')
const probing = ref(false)
const probeResult = ref<string | null>(null)

const formName = ref('Local MCP')
const formDesc = ref('')
const formTransport = ref<'stdio' | 'http'>('stdio')
const formCommandText = ref('npx\n-y\n@modelcontextprotocol/server-filesystem\n/tmp')
const formBaseUrl = ref('')
const formCwd = ref('')
const formEnvText = ref('')
const creating = ref(false)

const expandedId = ref<string | null>(null)
const toolsJson = ref<Record<string, string>>({})
const loadingTools = ref<string | null>(null)
const importing = ref<string | null>(null)

/** Streamable HTTP：服务端 SSE 推送是否写入事件总线（与后端 mcpHttpEmitServerPushEvents / MCP_HTTP_EMIT_SERVER_PUSH_EVENTS 对齐） */
const mcpHttpEmitServerPushEvents = ref(true)
/** 是否在平台库中存在 `mcpHttpEmitServerPushEvents`（否则生效值来自环境/默认） */
const mcpEmitFromPlatform = ref(false)
const behaviorSaving = ref(false)
const behaviorFeedback = ref('')
const behaviorFeedbackIsError = ref(false)

const mcpEmitSourceLabel = computed(() =>
  mcpEmitFromPlatform.value ? t('settings.mcp.emit_source_platform') : t('settings.mcp.emit_source_env'),
)

/** 应用事件总线 DLQ：按 MCP 服务端推送事件类型筛选（管理员 API） */
const mcpDlqInspectUrl = computed(() => {
  const raw = import.meta.env.VITE_API_URL as string | undefined
  const base = (raw || 'http://localhost:8000').replace(/\/$/, '')
  return `${base}/api/system/event-bus/dlq?event_type=${encodeURIComponent('mcp.streamable.server_rpc')}`
})

function parseLines(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
}

function parseEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const s = line.trim()
    if (!s || s.startsWith('#')) continue
    const i = s.indexOf('=')
    if (i <= 0) continue
    const k = s.slice(0, i).trim()
    const v = s.slice(i + 1).trim()
    if (k) out[k] = v
  }
  return out
}

async function loadMcpBehaviorSettings() {
  try {
    const c = await getSystemConfig()
    const st = c.settings
    mcpEmitFromPlatform.value =
      st != null && typeof st === 'object' && 'mcpHttpEmitServerPushEvents' in st

    const eff = c.mcp_http_emit_server_push_events_effective
    if (typeof eff === 'boolean') {
      mcpHttpEmitServerPushEvents.value = eff
      return
    }
    const v = st?.mcpHttpEmitServerPushEvents
    mcpHttpEmitServerPushEvents.value = v !== undefined ? Boolean(v) : true
  } catch (_) {
    mcpHttpEmitServerPushEvents.value = true
    mcpEmitFromPlatform.value = false
  }
}

useDebouncedOnSystemConfigChange(() => {
  void loadMcpBehaviorSettings()
})

async function onMcpEmitToggle(val: boolean) {
  const prev = mcpHttpEmitServerPushEvents.value
  mcpHttpEmitServerPushEvents.value = val
  behaviorSaving.value = true
  behaviorFeedback.value = ''
  behaviorFeedbackIsError.value = false
  try {
    await updateSystemConfig({ mcpHttpEmitServerPushEvents: val })
    mcpEmitFromPlatform.value = true
    behaviorFeedback.value = t('settings.saved')
    setTimeout(() => {
      behaviorFeedback.value = ''
    }, 2500)
  } catch (e) {
    mcpHttpEmitServerPushEvents.value = prev
    behaviorFeedbackIsError.value = true
    behaviorFeedback.value = e instanceof Error ? e.message : String(e)
  } finally {
    behaviorSaving.value = false
  }
}

async function refreshServers() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await listMcpServers(false)
    servers.value = res.data || []
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
    servers.value = []
  } finally {
    loading.value = false
  }
}

async function runProbe() {
  probing.value = true
  probeResult.value = null
  try {
    if (probeTransport.value === 'http') {
      const u = probeUrl.value.trim()
      if (!u.length) {
        probeResult.value = t('settings.mcp.err_url')
        return
      }
      const env = parseEnv(probeEnvText.value)
      const r = await mcpProbe({
        url: u,
        env: Object.keys(env).length ? env : undefined,
        request_timeout: 45,
      })
      probeResult.value = t('settings.mcp.probe_ok', { n: (r.tools as unknown[])?.length ?? 0 })
      return
    }
    const cmd = parseLines(probeCommandText.value)
    if (!cmd.length) {
      probeResult.value = t('settings.mcp.err_command')
      return
    }
    const env = parseEnv(probeEnvText.value)
    const r = await mcpProbe({
      command: cmd,
      cwd: probeCwd.value.trim() || undefined,
      env: Object.keys(env).length ? env : undefined,
      request_timeout: 45,
    })
    probeResult.value = t('settings.mcp.probe_ok', { n: (r.tools as unknown[])?.length ?? 0 })
  } catch (e) {
    probeResult.value = e instanceof Error ? e.message : String(e)
  } finally {
    probing.value = false
  }
}

async function submitCreate() {
  if (!formName.value.trim()) {
    errorMsg.value = t('settings.mcp.err_form_name')
    return
  }
  if (formTransport.value === 'http') {
    const u = formBaseUrl.value.trim()
    if (!u.length) {
      errorMsg.value = t('settings.mcp.err_url')
      return
    }
  } else {
    const cmd = parseLines(formCommandText.value)
    if (!cmd.length) {
      errorMsg.value = t('settings.mcp.err_form')
      return
    }
  }
  creating.value = true
  errorMsg.value = ''
  try {
    if (formTransport.value === 'http') {
      await createMcpServer({
        name: formName.value.trim(),
        description: formDesc.value.trim(),
        transport: 'http',
        base_url: formBaseUrl.value.trim(),
        command: [],
        env: Object.keys(parseEnv(formEnvText.value)).length ? parseEnv(formEnvText.value) : undefined,
        enabled: true,
      })
    } else {
      const cmd = parseLines(formCommandText.value)
      await createMcpServer({
        name: formName.value.trim(),
        description: formDesc.value.trim(),
        transport: 'stdio',
        command: cmd,
        cwd: formCwd.value.trim() || undefined,
        env: Object.keys(parseEnv(formEnvText.value)).length ? parseEnv(formEnvText.value) : undefined,
        enabled: true,
      })
    }
    await refreshServers()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    creating.value = false
  }
}

async function handleDelete(id: string) {
  if (!window.confirm(t('settings.mcp.confirm_delete'))) return
  try {
    await deleteMcpServer(id)
    if (expandedId.value === id) expandedId.value = null
    await refreshServers()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleTools(id: string) {
  if (expandedId.value === id) {
    expandedId.value = null
    return
  }
  expandedId.value = id
  loadingTools.value = id
  try {
    const r = await getMcpServerTools(id)
    toolsJson.value[id] = JSON.stringify(r.tools ?? [], null, 2)
  } catch (e) {
    toolsJson.value[id] = e instanceof Error ? e.message : String(e)
  } finally {
    loadingTools.value = null
  }
}

async function handleImportAll(id: string) {
  importing.value = id
  errorMsg.value = ''
  try {
    const r = await importMcpTools(id, null)
    errorMsg.value = t('settings.mcp.import_done', {
      n: r.imported?.length ?? 0,
      s: r.skipped_existing?.length ?? 0,
    })
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    importing.value = null
  }
}

onMounted(() => {
  loadMcpBehaviorSettings()
  refreshServers()
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full bg-background text-foreground overflow-hidden">
    <header class="pt-10 pb-6 px-10 flex items-start justify-between shrink-0">
      <div class="space-y-2">
        <h1 class="text-4xl font-bold tracking-tight">{{ t('settings.mcp.title') }}</h1>
        <p class="text-muted-foreground text-lg">{{ t('settings.mcp.subtitle') }}</p>
      </div>
      <Button variant="outline" class="gap-2" :disabled="loading" @click="refreshServers">
        <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': loading }" />
        {{ t('settings.mcp.refresh') }}
      </Button>
    </header>

    <div class="flex-1 flex overflow-hidden px-10 pb-10 gap-8">
      <aside
        class="shrink-0 hidden lg:flex flex-col transition-all duration-200"
        :class="navCollapsed ? 'w-16' : 'w-56'"
      >
        <div class="flex items-center justify-between mb-4">
          <div v-if="!navCollapsed" class="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            Settings
          </div>
          <button
            class="h-7 w-7 rounded-lg border border-border/50 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
            @click="navCollapsed = !navCollapsed"
          >
            <ChevronLeft v-if="!navCollapsed" class="w-4 h-4" />
            <ChevronRight v-else class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-2 flex-1 overflow-y-auto pr-1">
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-general' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/general')"
          >
            <span v-if="!navCollapsed">{{ t('settings.general_nav') }}</span>
            <span v-else class="flex items-center justify-center"><Sliders class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/backup')"
          >
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_database_backup') }}</span>
            <span v-else class="flex items-center justify-center"><Database class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-model-backup' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/model-backup')"
          >
            <span v-if="!navCollapsed">{{ t('settings.model_backup.nav_model_backup') }}</span>
            <span v-else class="flex items-center justify-center"><FileJson class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-backend' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/backend')"
          >
            <span v-if="!navCollapsed">{{ t('settings.backend_nav') }}</span>
            <span v-else class="flex items-center justify-center"><Cpu class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-runtime' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/runtime')"
          >
            <span v-if="!navCollapsed">{{ t('settings.runtime.nav') }}</span>
            <span v-else class="flex items-center justify-center"><Zap class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-object-detection' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/object-detection')"
          >
            <span v-if="!navCollapsed">{{ t('settings.object_detection_nav') }}</span>
            <span v-else class="flex items-center justify-center"><ScanSearch class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-image-generation' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/image-generation')"
          >
            <span v-if="!navCollapsed">{{ t('settings.image_generation.nav') }}</span>
            <span v-else class="flex items-center justify-center"><FileJson class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-asr' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/asr')"
          >
            <span v-if="!navCollapsed">{{ t('settings.asr_nav') }}</span>
            <span v-else class="flex items-center justify-center"><Mic class="w-4 h-4" /></span>
          </button>
          <button
            class="w-full text-left text-sm font-semibold px-3 py-2 rounded-lg transition-colors"
            :class="settingsSection === 'settings-mcp' ? 'bg-muted/40 text-foreground' : 'hover:bg-muted/40'"
            @click="router.push('/settings/mcp')"
          >
            <span v-if="!navCollapsed">{{ t('settings.mcp.nav') }}</span>
            <span v-else class="flex items-center justify-center"><Plug class="w-4 h-4" /></span>
          </button>
        </div>
      </aside>

      <div class="flex-1 overflow-y-auto custom-scrollbar pr-4">
        <div class="space-y-8">
          <p v-if="errorMsg" class="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            {{ errorMsg }}
          </p>

          <section class="rounded-2xl border border-border bg-card p-6 space-y-4">
            <h2 class="text-lg font-bold">{{ t('settings.mcp.http_behavior_section') }}</h2>
            <p class="text-sm text-muted-foreground">{{ t('settings.mcp.emit_server_push_events_hint') }}</p>
            <p class="text-xs text-muted-foreground">{{ mcpEmitSourceLabel }}</p>
            <div class="text-[11px] text-muted-foreground space-y-1">
              <div>{{ t('settings.mcp.dlq_inspect_hint') }}</div>
              <code class="block rounded-md bg-muted/70 px-2 py-1.5 font-mono break-all">{{ mcpDlqInspectUrl }}</code>
            </div>
            <div class="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border/60 bg-muted/30 px-4 py-3">
              <div class="space-y-1 min-w-[200px]">
                <div class="text-sm font-semibold">{{ t('settings.mcp.emit_server_push_events') }}</div>
                <div
                  v-if="behaviorFeedback"
                  class="text-xs"
                  :class="
                    behaviorFeedbackIsError
                      ? 'text-destructive'
                      : behaviorSaving
                        ? 'text-muted-foreground'
                        : 'text-emerald-600 dark:text-emerald-400'
                  "
                >
                  {{ behaviorFeedback }}
                </div>
              </div>
              <Switch
                :checked="mcpHttpEmitServerPushEvents"
                :disabled="behaviorSaving"
                @update:checked="onMcpEmitToggle"
              />
            </div>
          </section>

          <section class="rounded-2xl border border-border bg-card p-6 space-y-4">
            <h2 class="text-lg font-bold flex items-center gap-2">
              <Boxes class="w-5 h-5" />
              {{ t('settings.mcp.probe_section') }}
            </h2>
            <p class="text-sm text-muted-foreground">{{ t('settings.mcp.probe_hint') }}</p>
            <div class="grid gap-3 md:grid-cols-2">
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.transport') }}</label>
                <select
                  v-model="probeTransport"
                  class="mt-1 flex h-10 w-full rounded-md border border-input bg-muted px-3 py-2 text-sm"
                >
                  <option value="stdio">{{ t('settings.mcp.transport_stdio') }}</option>
                  <option value="http">{{ t('settings.mcp.transport_http') }}</option>
                </select>
              </div>
            </div>
            <template v-if="probeTransport === 'http'">
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.base_url') }}</label>
                <Input v-model="probeUrl" class="mt-1 bg-muted font-mono text-xs" :placeholder="t('settings.mcp.base_url_ph')" />
              </div>
            </template>
            <template v-else>
              <Textarea v-model="probeCommandText" class="min-h-[100px] bg-muted font-mono text-xs" />
              <div class="grid gap-3 md:grid-cols-2">
                <div>
                  <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.cwd') }}</label>
                  <Input v-model="probeCwd" class="mt-1 bg-muted" :placeholder="t('settings.mcp.cwd_ph')" />
                </div>
              </div>
            </template>
            <div>
              <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.probe_env') }}</label>
              <Textarea
                v-model="probeEnvText"
                class="mt-1 min-h-[72px] bg-muted font-mono text-xs"
                :placeholder="t('settings.mcp.probe_env_ph')"
              />
            </div>
            <Button :disabled="probing" class="gap-2" @click="runProbe">
              {{ probing ? '…' : t('settings.mcp.probe_run') }}
            </Button>
            <pre v-if="probeResult" class="text-xs bg-muted rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">{{ probeResult }}</pre>
          </section>

          <section class="rounded-2xl border border-border bg-card p-6 space-y-4">
            <h2 class="text-lg font-bold flex items-center gap-2">
              <Plus class="w-5 h-5" />
              {{ t('settings.mcp.add_server') }}
            </h2>
            <div class="grid gap-3 md:grid-cols-2">
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.name') }}</label>
                <Input v-model="formName" class="mt-1 bg-muted" />
              </div>
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.desc') }}</label>
                <Input v-model="formDesc" class="mt-1 bg-muted" />
              </div>
            </div>
            <div class="grid gap-3 md:grid-cols-2">
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.transport') }}</label>
                <select
                  v-model="formTransport"
                  class="mt-1 flex h-10 w-full rounded-md border border-input bg-muted px-3 py-2 text-sm"
                >
                  <option value="stdio">{{ t('settings.mcp.transport_stdio') }}</option>
                  <option value="http">{{ t('settings.mcp.transport_http') }}</option>
                </select>
              </div>
            </div>
            <template v-if="formTransport === 'http'">
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.base_url') }}</label>
                <Input v-model="formBaseUrl" class="mt-1 bg-muted font-mono text-xs" :placeholder="t('settings.mcp.base_url_ph')" />
              </div>
            </template>
            <template v-else>
              <div>
                <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.command') }}</label>
                <Textarea v-model="formCommandText" class="mt-1 min-h-[100px] bg-muted font-mono text-xs" />
              </div>
              <div class="grid gap-3 md:grid-cols-2">
                <div>
                  <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.cwd') }}</label>
                  <Input v-model="formCwd" class="mt-1 bg-muted" />
                </div>
              </div>
            </template>
            <div>
              <label class="text-xs font-semibold text-muted-foreground">{{ t('settings.mcp.env') }}</label>
              <Textarea
                v-model="formEnvText"
                class="mt-1 min-h-[72px] bg-muted font-mono text-xs"
                :placeholder="formTransport === 'http' ? t('settings.mcp.env_ph_http') : t('settings.mcp.env_ph')"
              />
            </div>
            <Button :disabled="creating" class="gap-2 bg-primary" @click="submitCreate">
              {{ creating ? '…' : t('settings.mcp.save_server') }}
            </Button>
          </section>

          <section class="space-y-3">
            <h2 class="text-lg font-bold">{{ t('settings.mcp.servers') }}</h2>
            <div v-if="loading" class="text-sm text-muted-foreground">{{ t('settings.mcp.loading') }}</div>
            <div v-else-if="!servers.length" class="text-sm text-muted-foreground">{{ t('settings.mcp.empty') }}</div>
            <div v-else class="space-y-3">
              <div
                v-for="s in servers"
                :key="s.id"
                class="rounded-2xl border border-border bg-card p-4 space-y-3"
              >
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div class="font-bold">{{ s.name }}</div>
                    <div class="text-xs text-muted-foreground font-mono">{{ s.id }}</div>
                    <div v-if="(s.transport || 'stdio') === 'http' && s.base_url" class="text-[11px] text-muted-foreground font-mono break-all mt-1">
                      {{ s.base_url }}
                    </div>
                  </div>
                  <div class="flex flex-wrap gap-2">
                    <Badge variant="outline">{{ (s.transport || 'stdio') === 'http' ? 'HTTP' : 'stdio' }}</Badge>
                    <Badge :variant="s.enabled ? 'default' : 'secondary'">{{ s.enabled ? 'ON' : 'OFF' }}</Badge>
                    <Button size="sm" variant="outline" class="gap-1" @click="toggleTools(s.id)">
                      {{ t('settings.mcp.tools') }}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      class="gap-1"
                      :disabled="importing === s.id"
                      @click="handleImportAll(s.id)"
                    >
                      {{ t('settings.mcp.import_skills') }}
                    </Button>
                    <Button size="sm" variant="ghost" class="text-destructive gap-1" @click="handleDelete(s.id)">
                      <Trash2 class="w-4 h-4" />
                    </Button>
                  </div>
                </div>
                <div v-if="expandedId === s.id" class="border-t border-border pt-3">
                  <div v-if="loadingTools === s.id" class="text-sm text-muted-foreground">Loading…</div>
                  <pre v-else class="text-[11px] bg-muted rounded-lg p-3 overflow-x-auto max-h-64">{{ toolsJson[s.id] }}</pre>
                </div>
              </div>
            </div>
          </section>

          <div class="h-16" />
        </div>
      </div>
    </div>
  </div>
</template>
