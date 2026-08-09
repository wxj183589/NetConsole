<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  DEFAULT_MESH_RSSI_SPLIT_RATIO,
  MIN_MESH_RSSI_PANE_HEIGHT,
  MESH_RSSI_SPLITTER_SIZE,
  normalizeMeshRssiSplitRatio,
  resolveMeshRssiCompareLayout,
  type MeshRssiLayoutMode,
} from '../mesh-analysis/meshRssiLayout'

const props = withDefaults(defineProps<{
  mode: MeshRssiLayoutMode
  splitRatio: number
  workspaceHeight: number
}>(), {
  mode: 'compare',
  splitRatio: DEFAULT_MESH_RSSI_SPLIT_RATIO,
  workspaceHeight: 0,
})

const emit = defineEmits<{
  'update:splitRatio': [ratio: number]
  resize: []
}>()

const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLElement | null>(null)
const dragging = ref(false)
const compareLayout = computed(() => resolveMeshRssiCompareLayout(props.workspaceHeight, props.splitRatio))
const canvasStyle = computed(() => {
  if (props.mode !== 'compare') {
    return {
      height: `${Math.max(MIN_MESH_RSSI_PANE_HEIGHT, Math.floor(props.workspaceHeight))}px`,
      gridTemplateRows: 'minmax(0, 1fr)',
    }
  }
  const layout = compareLayout.value
  return {
    height: `${layout.innerHeight}px`,
    gridTemplateRows: `${layout.activePaneHeight}px ${MESH_RSSI_SPLITTER_SIZE}px ${layout.tracksidePaneHeight}px`,
  }
})

let resizeObserver: ResizeObserver | null = null
let resizeFrame: number | null = null
let dragFrame: number | null = null
let dragPointerId: number | null = null
let dragTarget: HTMLElement | null = null
let pendingPointerY: number | null = null
let disposed = false

function scheduleResize(): void {
  if (resizeFrame !== null) return
  resizeFrame = requestAnimationFrame(() => {
    resizeFrame = null
    if (!disposed) void nextTick(() => { if (!disposed) emit('resize') })
  })
}

function applyPendingPointer(): void {
  dragFrame = null
  const clientY = pendingPointerY
  pendingPointerY = null
  if (clientY === null || props.mode !== 'compare') return
  const bounds = canvas.value?.getBoundingClientRect()
  const height = bounds?.height && bounds.height > 0 ? bounds.height : compareLayout.value.innerHeight
  const paneSpace = Math.max(1, height - MESH_RSSI_SPLITTER_SIZE)
  const pointerOffset = clientY - (bounds?.top ?? 0) - MESH_RSSI_SPLITTER_SIZE / 2
  const layout = compareLayout.value
  emit('update:splitRatio', normalizeMeshRssiSplitRatio(Math.min(
    layout.maximumRatio,
    Math.max(layout.minimumRatio, pointerOffset / paneSpace),
  )))
}

function handlePointerMove(event: PointerEvent): void {
  if (event.pointerId !== dragPointerId) return
  pendingPointerY = event.clientY
  if (dragFrame === null) dragFrame = requestAnimationFrame(applyPendingPointer)
}

function removeDragListeners(): void {
  dragTarget?.removeEventListener('pointermove', handlePointerMove)
  dragTarget?.removeEventListener('pointerup', finishResize)
  dragTarget?.removeEventListener('pointercancel', finishResize)
}

function finishResize(event?: PointerEvent): void {
  if (event && event.pointerId !== dragPointerId) return
  if (dragFrame !== null) {
    cancelAnimationFrame(dragFrame)
    applyPendingPointer()
  }
  const pointerId = dragPointerId
  const target = dragTarget
  removeDragListeners()
  if (target && pointerId !== null && target.hasPointerCapture?.(pointerId)) target.releasePointerCapture(pointerId)
  dragPointerId = null
  dragTarget = null
  pendingPointerY = null
  dragging.value = false
  scheduleResize()
}

function startResize(event: PointerEvent): void {
  if (props.mode !== 'compare' || event.button !== 0) return
  finishResize()
  dragPointerId = event.pointerId
  dragTarget = event.currentTarget as HTMLElement
  dragging.value = true
  dragTarget.addEventListener('pointermove', handlePointerMove)
  dragTarget.addEventListener('pointerup', finishResize)
  dragTarget.addEventListener('pointercancel', finishResize)
  dragTarget.setPointerCapture(event.pointerId)
  event.preventDefault()
}

function handleSplitterKeydown(event: KeyboardEvent): void {
  if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return
  event.preventDefault()
  const layout = compareLayout.value
  const next = props.splitRatio + (event.key === 'ArrowUp' ? -0.02 : 0.02)
  emit('update:splitRatio', Math.min(layout.maximumRatio, Math.max(layout.minimumRatio, next)))
  scheduleResize()
}

watch(() => [props.mode, props.workspaceHeight] as const, ([mode]) => {
  if (mode !== 'compare' && dragging.value) finishResize()
  scheduleResize()
})

onMounted(() => {
  disposed = false
  resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(scheduleResize)
  if (root.value) resizeObserver?.observe(root.value)
  scheduleResize()
})

onBeforeUnmount(() => {
  disposed = true
  finishResize()
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
})
</script>

<template>
  <div
    ref="root"
    class="rail-rssi-comparison"
    :class="[`is-${mode}`, { 'is-dragging': dragging }]"
    :data-layout-mode="mode"
    :data-scrollable="compareLayout.scrollable"
  >
    <div ref="canvas" class="rail-rssi-comparison__canvas" :style="canvasStyle">
      <section v-show="mode !== 'trackside-focus'" class="rail-rssi-comparison__pane" data-rssi-pane="active"><slot name="active" /></section>
      <div
        v-if="mode === 'compare'"
        class="rail-rssi-comparison__splitter"
        role="separator"
        aria-label="调整主链图与轨旁图高度"
        aria-orientation="horizontal"
        :aria-valuemin="Math.round(compareLayout.minimumRatio * 100)"
        :aria-valuemax="Math.round(compareLayout.maximumRatio * 100)"
        :aria-valuenow="Math.round(compareLayout.splitRatio * 100)"
        tabindex="0"
        @pointerdown="startResize"
        @dblclick="emit('update:splitRatio', DEFAULT_MESH_RSSI_SPLIT_RATIO)"
        @keydown="handleSplitterKeydown"
      ><span aria-hidden="true"></span></div>
      <section v-show="mode !== 'active-focus'" class="rail-rssi-comparison__pane" data-rssi-pane="trackside"><slot name="trackside" /></section>
    </div>
  </div>
</template>

<style scoped>
.rail-rssi-comparison{width:100%;height:100%;min-width:0;overflow:hidden}
.rail-rssi-comparison[data-scrollable=true].is-compare{overflow-y:auto}
.rail-rssi-comparison__canvas{display:grid;width:100%;min-width:0}
.rail-rssi-comparison__pane{display:flex;min-width:0;min-height:0;flex-direction:column;overflow:hidden}
.rail-rssi-comparison__splitter{position:relative;z-index:2;min-width:0;background:var(--nc-bg-page);border-top:1px solid var(--nc-border-light);border-bottom:1px solid var(--nc-border-light);cursor:row-resize;touch-action:none}
.rail-rssi-comparison__splitter span{position:absolute;top:50%;left:50%;width:42px;height:2px;background:var(--nc-text-secondary);border-radius:999px;opacity:.55;transform:translate(-50%,-50%)}
.rail-rssi-comparison__splitter:focus-visible{outline:2px solid var(--nc-primary);outline-offset:-2px}
.rail-rssi-comparison.is-dragging{cursor:row-resize;user-select:none}
.rail-rssi-comparison.is-active-focus .rail-rssi-comparison__pane,.rail-rssi-comparison.is-trackside-focus .rail-rssi-comparison__pane{height:100%}
</style>
