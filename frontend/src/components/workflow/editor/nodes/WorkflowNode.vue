<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import type { NodeProps } from '@vue-flow/core'
import { computed } from 'vue'
import {
  Play,
  FileText,
  Brain,
  User,
  Layers,
  GitBranch,
  Repeat,
  Code,
  Globe,
} from 'lucide-vue-next'
import type { WorkflowNodeData } from '../types'
import { requestWorkflowGroupResizeStart, requestWorkflowNodeSelect } from '../canvasSelection'

const props = defineProps<NodeProps<WorkflowNodeData>>()

const iconMap: Record<string, typeof Play> = {
  start: Play,
  prompt_template: FileText,
  llm: Brain,
  agent: User,
  embedding: Layers,
  condition: GitBranch,
  loop: Repeat,
  script: Code,
  tool: Globe,
}

const colorMap: Record<string, string> = {
  start: 'from-blue-500 to-blue-600 border-blue-500/30 bg-blue-500/10',
  prompt_template: 'from-amber-500 to-amber-600 border-amber-500/30 bg-amber-500/10',
  llm: 'from-indigo-500 to-indigo-600 border-indigo-500/30 bg-indigo-500/10',
  agent: 'from-violet-500 to-violet-600 border-violet-500/30 bg-violet-500/10',
  embedding: 'from-cyan-500 to-cyan-600 border-cyan-500/30 bg-cyan-500/10',
  condition: 'from-emerald-500 to-emerald-600 border-emerald-500/30 bg-emerald-500/10',
  loop: 'from-teal-500 to-teal-600 border-teal-500/30 bg-teal-500/10',
  script: 'from-slate-500 to-slate-600 border-slate-500/30 bg-slate-500/10',
  tool: 'from-orange-500 to-orange-600 border-orange-500/30 bg-orange-500/10',
}

const Icon = computed(() => iconMap[props.data?.type] ?? Brain)
const colorClass = computed(() => colorMap[props.data?.type] ?? 'from-gray-500 to-gray-600 border-gray-500/30 bg-gray-500/10')

const nodeSubtitle = computed(() => {
  const d = props.data
  const cfg = d?.config ?? {}
  if (d?.type === 'llm') {
    const name = (cfg.model_display_name as string) || (cfg.model_id as string)
    return name || ''
  }
  if (d?.type === 'agent') {
    const name = (cfg.agent_display_name as string) || (cfg.agent_id as string)
    return name || ''
  }
  return (d?.subtitle as string) || ''
})
const isGroupNode = computed(() => props.data?.type === 'group')
const isHighlighted = computed(() => {
  const cfg = (props.data?.config as Record<string, unknown>) || {}
  return cfg.__highlight === true
})
const groupNodeCount = computed(() => {
  if (!isGroupNode.value) return 0
  const cfg = (props.data?.config as Record<string, unknown>) || {}
  const count = Number(cfg.__nodeCount)
  if (Number.isFinite(count) && count >= 0) return count
  const matched = String(props.data?.subtitle || '').match(/(\d+)/)
  return matched ? Number(matched[1]) : 0
})

function onNodeContentClick() {
  requestWorkflowNodeSelect(String(props.id || ''))
}
function onGroupResizeHandleMouseDown(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  requestWorkflowNodeSelect(String(props.id || ''))
  requestWorkflowGroupResizeStart(String(props.id || ''), e.clientX, e.clientY)
}
</script>

<template>
  <div
    :data-id="props.id"
    class="group relative px-4 py-3 rounded-xl border-2 min-w-[160px] shadow-lg bg-card transition-shadow hover:shadow-xl cursor-grab active:cursor-grabbing"
    :class="[colorClass, isHighlighted ? 'ring-2 ring-amber-400/90 ring-offset-2 ring-offset-background' : '']"
    @click.stop="onNodeContentClick"
  >
    <template v-if="!isGroupNode">
      <Handle v-if="props.data?.type !== 'start'" type="target" :position="Position.Left" class="!w-3 !h-3 !border-2 !bg-background !-left-1.5" />
      <div class="flex items-center gap-2">
        <div class="w-8 h-8 rounded-lg flex items-center justify-center bg-white/10">
          <component :is="Icon" class="w-4 h-4 text-white" />
        </div>
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-sm text-foreground truncate">
            {{ props.data?.label ?? 'Node' }}
          </div>
          <div v-if="nodeSubtitle" class="text-xs text-muted-foreground truncate">
            {{ nodeSubtitle }}
          </div>
        </div>
      </div>
      <Handle type="source" :position="Position.Right" class="!w-3 !h-3 !border-2 !bg-background !-right-1.5 z-10" />
    </template>
    <template v-else>
      <div class="h-full w-full rounded-xl border-2 border-dashed border-slate-500/40 bg-slate-500/5 p-2">
        <div class="flex items-center justify-between gap-2">
          <div class="font-semibold text-sm text-foreground truncate">
          {{ props.data?.label ?? 'Group' }}
          </div>
          <span class="rounded-full border border-slate-400/40 bg-slate-500/10 px-2 py-0.5 text-[10px] text-muted-foreground">
            {{ groupNodeCount }}
          </span>
        </div>
        <div v-if="nodeSubtitle" class="text-xs text-muted-foreground truncate">
          {{ nodeSubtitle }}
        </div>
      </div>
      <button
        class="absolute bottom-1 right-1 h-3.5 w-3.5 rounded-sm border border-slate-400/70 bg-slate-500/30 cursor-se-resize hover:bg-slate-500/50"
        title="拖拽调整分组尺寸"
        @mousedown="onGroupResizeHandleMouseDown"
      />
      <div class="pointer-events-none absolute bottom-2 right-6 h-px w-10 bg-slate-400/60 opacity-0 transition-opacity group-hover:opacity-100" />
      <div class="pointer-events-none absolute bottom-6 right-2 h-10 w-px bg-slate-400/60 opacity-0 transition-opacity group-hover:opacity-100" />
    </template>
  </div>
</template>
