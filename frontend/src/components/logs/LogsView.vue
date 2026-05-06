<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Pause, Play, Trash2, Download } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useLogs } from '@/composables/useLogs'
import type { LogEntry } from '@/services/api'

defineOptions({ name: 'LogsViewPanel' })

const { t } = useI18n()
const { logs, isStreaming, error, startStreaming, stopStreaming, clearLogs } = useLogs()

type LevelFilter = 'ALL' | LogEntry['level']

const levelFilter = ref<LevelFilter>('ALL')
const searchText = ref('')
const autoScroll = ref(true)
const logContainer = ref<HTMLElement | null>(null)

const filteredLogs = computed(() => {
  let rows = logs.value
  if (levelFilter.value !== 'ALL') {
    rows = rows.filter((l) => l.level === levelFilter.value)
  }
  const q = searchText.value.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(
    (l) =>
      l.message.toLowerCase().includes(q) ||
      (l.tag || '').toLowerCase().includes(q) ||
      (l.timestamp || '').toLowerCase().includes(q),
  )
})

function levelClass(level: string): string {
  switch (level) {
    case 'ERRR':
      return 'text-red-400'
    case 'WARN':
      return 'text-amber-400'
    case 'DEBUG':
      return 'text-slate-500'
    default:
      return 'text-slate-200'
  }
}

function toggleStream() {
  if (isStreaming.value) stopStreaming()
  else startStreaming()
}

function triggerDownload(filename: string, mime: string, body: string) {
  const blob = new Blob([body], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function downloadJson() {
  triggerDownload(
    `perilla-logs-${Date.now()}.json`,
    'application/json',
    JSON.stringify(filteredLogs.value, null, 2),
  )
}

function downloadCsv() {
  const header = 'timestamp,level,tag,message'
  const escape = (s: string) => `"${String(s).replace(/"/g, '""')}"`
  const lines = filteredLogs.value.map((l) =>
    [escape(l.timestamp), escape(l.level), escape(l.tag || ''), escape(l.message || '')].join(','),
  )
  triggerDownload(`perilla-logs-${Date.now()}.csv`, 'text/csv', [header, ...lines].join('\n'))
}

async function scrollToBottom() {
  await nextTick()
  const el = logContainer.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(
  () => filteredLogs.value.length,
  async () => {
    if (autoScroll.value) await scrollToBottom()
  },
)

onMounted(() => {
  startStreaming()
})

onUnmounted(() => {
  stopStreaming()
})
</script>

<template>
  <div class="flex flex-col h-full min-h-0 bg-background">
    <div class="flex flex-col gap-3 border-b border-border px-4 py-3 shrink-0 md:flex-row md:items-center md:justify-between">
      <div>
        <h1 class="text-lg font-semibold tracking-tight">{{ t('logs.title') }}</h1>
        <p class="text-xs text-muted-foreground mt-0.5">
          <span
            :class="isStreaming ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'"
          >
            {{ isStreaming ? t('logs.stream.live') : t('logs.stream.pause') }}
          </span>
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <select
          v-model="levelFilter"
          class="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="ALL">{{ t('logs.levels.all') }}</option>
          <option value="DEBUG">{{ t('logs.levels.debug') }}</option>
          <option value="INFO">{{ t('logs.levels.info') }}</option>
          <option value="WARN">{{ t('logs.levels.warn') }}</option>
          <option value="ERRR">{{ t('logs.levels.err') }}</option>
        </select>

        <Input
          v-model="searchText"
          class="w-full md:w-56 h-9"
          :placeholder="t('logs.search_placeholder')"
        />

        <label class="flex items-center gap-1.5 text-xs text-muted-foreground whitespace-nowrap">
          <input v-model="autoScroll" type="checkbox" class="rounded border-input" />
          {{ t('logs.stream.auto_scroll') }}
        </label>

        <Button variant="outline" size="sm" @click="toggleStream">
          <Pause v-if="isStreaming" class="w-4 h-4 mr-1" />
          <Play v-else class="w-4 h-4 mr-1" />
          {{ isStreaming ? t('logs.stream.pause') : t('logs.stream.resume') }}
        </Button>

        <Button variant="outline" size="sm" @click="clearLogs">
          <Trash2 class="w-4 h-4 mr-1" />
          {{ t('logs.clear') }}
        </Button>

        <Button variant="outline" size="sm" @click="downloadJson">
          <Download class="w-4 h-4 mr-1" />
          {{ t('logs.export.json') }}
        </Button>

        <Button variant="outline" size="sm" @click="downloadCsv">
          <Download class="w-4 h-4 mr-1" />
          {{ t('logs.export.csv') }}
        </Button>
      </div>
    </div>

    <div
      v-if="error"
      class="mx-4 mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive flex flex-wrap items-center gap-2"
    >
      <span>{{ error }}</span>
      <Button size="sm" variant="secondary" @click="startStreaming">
        {{ t('logs.error_state.retry') }}
      </Button>
    </div>

    <div
      ref="logContainer"
      class="flex-1 min-h-0 overflow-auto px-4 py-3 font-mono text-xs leading-relaxed"
    >
      <div v-if="!filteredLogs.length" class="text-muted-foreground py-12 text-center text-sm">
        {{
          searchText.trim() || levelFilter !== 'ALL'
            ? t('logs.empty_state.no_match')
            : t('logs.empty_state.waiting')
        }}
      </div>
      <div v-for="line in filteredLogs" :key="line.id" class="flex gap-2 py-0.5 border-b border-border/40">
        <span class="text-muted-foreground shrink-0 whitespace-nowrap">{{ line.timestamp }}</span>
        <span class="shrink-0 w-12" :class="levelClass(line.level)">{{ line.level }}</span>
        <span class="text-sky-400/90 shrink-0 max-w-[140px] truncate" :title="line.tag">{{ line.tag }}</span>
        <span class="text-foreground break-all whitespace-pre-wrap">{{ line.message }}</span>
      </div>
    </div>
  </div>
</template>
