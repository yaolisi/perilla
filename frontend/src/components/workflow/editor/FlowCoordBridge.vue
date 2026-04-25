<script setup lang="ts">
import { onMounted, inject } from 'vue'
import { useVueFlow } from '@vue-flow/core'

const setScreenToFlowCoordinate = inject<(fn: (pos: { x: number; y: number }) => { x: number; y: number }) => void>(
  'workflowCanvasSetScreenToFlowCoordinate',
  () => {}
)
const setControls = inject<(controls: {
  fitView?: (params?: { duration?: number; padding?: number }) => void
  zoomIn?: (options?: { duration?: number }) => void
  zoomOut?: (options?: { duration?: number }) => void
  setCenter?: (x: number, y: number, options?: { zoom?: number; duration?: number }) => void
}) => void>('workflowCanvasSetControls', () => {})

const { screenToFlowCoordinate, fitView, zoomIn, zoomOut, setCenter } = useVueFlow()

onMounted(() => {
  setScreenToFlowCoordinate(screenToFlowCoordinate)
  setControls({ fitView, zoomIn, zoomOut, setCenter })
})
</script>

<template>
  <div style="position: absolute; pointer-events: none; width: 0; height: 0; overflow: hidden" aria-hidden="true" />
</template>
