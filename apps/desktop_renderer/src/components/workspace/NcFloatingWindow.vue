<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Close, FullScreen, ScaleToOriginal } from '@element-plus/icons-vue'

interface WindowRect {
  left: number
  top: number
  width: number
  height: number
}

type ResizeEdge = 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'nw'

const props = withDefaults(defineProps<{
  modelValue: boolean
  title: string
  subtitle?: string
  windowId: string
  routeKey: string
  userKey?: string
  minWidth?: number
  minHeight?: number
  headerOffset?: number
}>(), {
  subtitle: '',
  userKey: 'local-user',
  minWidth: 760,
  minHeight: 480,
  headerOffset: 56,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  close: []
}>()

const windowRef = ref<HTMLElement | null>(null)
const rect = reactive<WindowRect>({ left: 0, top: 0, width: 0, height: 0 })
const restoreRect = reactive<WindowRect>({ left: 0, top: 0, width: 0, height: 0 })
const maximized = ref(false)
let pointerSession: {
  mode: 'drag' | 'resize'
  edge?: ResizeEdge
  startX: number
  startY: number
  startRect: WindowRect
} | null = null

const storageKey = computed(() => [
  'netconsole', 'floating-window', 'v1',
  props.userKey, props.routeKey, props.windowId,
].map(encodeURIComponent).join(':'))

const windowStyle = computed(() => ({
  left: `${rect.left}px`,
  top: `${rect.top}px`,
  width: `${rect.width}px`,
  height: `${rect.height}px`,
}))

function shellHeaderHeight(): number {
  if (typeof getComputedStyle === 'undefined') return props.headerOffset
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue('--nc-shell-header-height')
    .trim()
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : props.headerOffset
}

function viewportBounds() {
  const header = shellHeaderHeight()
  const width = Math.max(320, document.documentElement.clientWidth || window.innerWidth || 0)
  const height = Math.max(header + 240, document.documentElement.clientHeight || window.innerHeight || 0)
  return { header, width, height }
}

function clampRect(value: WindowRect): WindowRect {
  const viewport = viewportBounds()
  const width = Math.min(Math.max(Math.min(props.minWidth, viewport.width - 16), value.width), viewport.width - 16)
  const availableHeight = Math.max(240, viewport.height - viewport.header - 8)
  const height = Math.min(Math.max(Math.min(props.minHeight, availableHeight), value.height), availableHeight)
  return {
    left: Math.min(Math.max(8, value.left), Math.max(8, viewport.width - width - 8)),
    top: Math.min(Math.max(viewport.header, value.top), Math.max(viewport.header, viewport.height - height - 8)),
    width,
    height,
  }
}

function assignRect(target: WindowRect, value: WindowRect): void {
  target.left = value.left
  target.top = value.top
  target.width = value.width
  target.height = value.height
}

function defaultRect(): WindowRect {
  const viewport = viewportBounds()
  const width = Math.min(1180, viewport.width * 0.85)
  const height = Math.min(760, (viewport.height - viewport.header) * 0.82)
  return clampRect({
    left: (viewport.width - width) / 2,
    top: viewport.header + Math.max(8, (viewport.height - viewport.header - height) / 2),
    width,
    height,
  })
}

function restorePersistedRect(): void {
  let saved: WindowRect | null = null
  try {
    const raw = localStorage.getItem(storageKey.value)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<WindowRect>
      if (['left', 'top', 'width', 'height'].every((key) => Number.isFinite(parsed[key as keyof WindowRect]))) {
        saved = parsed as WindowRect
      }
    }
  } catch {
    saved = null
  }
  const next = clampRect(saved ?? defaultRect())
  assignRect(rect, next)
  assignRect(restoreRect, next)
  maximized.value = false
}

function persistRect(): void {
  if (maximized.value) return
  try {
    localStorage.setItem(storageKey.value, JSON.stringify(clampRect(rect)))
  } catch {
    // localStorage 不可用时仅保留当前会话位置。
  }
}

function close(): void {
  endPointerSession()
  persistRect()
  emit('update:modelValue', false)
  emit('close')
}

function toggleMaximize(): void {
  endPointerSession()
  if (maximized.value) {
    assignRect(rect, clampRect(restoreRect))
    maximized.value = false
    return
  }
  assignRect(restoreRect, clampRect(rect))
  const viewport = viewportBounds()
  assignRect(rect, {
    left: 0,
    top: viewport.header,
    width: viewport.width,
    height: viewport.height - viewport.header,
  })
  maximized.value = true
}

function startDrag(event: PointerEvent): void {
  const target = event.target
  if (
    maximized.value
    || event.button !== 0
    || (target instanceof HTMLElement && target.closest('button'))
  ) return
  beginPointer(event, 'drag')
}

function startResize(event: PointerEvent, edge: ResizeEdge): void {
  if (maximized.value || event.button !== 0) return
  beginPointer(event, 'resize', edge)
}

function beginPointer(event: PointerEvent, mode: 'drag' | 'resize', edge?: ResizeEdge): void {
  event.preventDefault()
  pointerSession = {
    mode,
    edge,
    startX: event.clientX,
    startY: event.clientY,
    startRect: { ...rect },
  }
  document.addEventListener('pointermove', handlePointerMove)
  document.addEventListener('pointerup', endPointerSession)
  document.addEventListener('pointercancel', endPointerSession)
}

function handlePointerMove(event: PointerEvent): void {
  const session = pointerSession
  if (!session) return
  const dx = event.clientX - session.startX
  const dy = event.clientY - session.startY
  if (session.mode === 'drag') {
    assignRect(rect, clampRect({
      ...session.startRect,
      left: session.startRect.left + dx,
      top: session.startRect.top + dy,
    }))
    return
  }
  const edge = session.edge ?? 'se'
  const next = { ...session.startRect }
  if (edge.includes('e')) next.width += dx
  if (edge.includes('s')) next.height += dy
  if (edge.includes('w')) {
    next.left += dx
    next.width -= dx
  }
  if (edge.includes('n')) {
    next.top += dy
    next.height -= dy
  }
  assignRect(rect, clampRect(next))
}

function endPointerSession(): void {
  if (!pointerSession) return
  pointerSession = null
  document.removeEventListener('pointermove', handlePointerMove)
  document.removeEventListener('pointerup', endPointerSession)
  document.removeEventListener('pointercancel', endPointerSession)
  persistRect()
}

function handleViewportResize(): void {
  if (maximized.value) {
    const viewport = viewportBounds()
    assignRect(rect, {
      left: 0,
      top: viewport.header,
      width: viewport.width,
      height: viewport.height - viewport.header,
    })
  } else {
    assignRect(rect, clampRect(rect))
  }
}

watch(() => props.modelValue, (visible) => {
  if (!visible) {
    endPointerSession()
    return
  }
  restorePersistedRect()
  void nextTick(() => windowRef.value?.focus())
})
watch(storageKey, () => {
  if (props.modelValue) restorePersistedRect()
})

onMounted(() => {
  window.addEventListener('resize', handleViewportResize)
  if (props.modelValue) restorePersistedRect()
})

onBeforeUnmount(() => {
  endPointerSession()
  persistRect()
  window.removeEventListener('resize', handleViewportResize)
})

defineExpose({ rect, maximized, startDrag, startResize, toggleMaximize })
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="nc-floating-layer">
      <section
        ref="windowRef"
        class="nc-floating-window"
        :class="{ 'is-maximized': maximized }"
        :style="windowStyle"
        role="region"
        :aria-label="title"
        tabindex="-1"
      >
        <header class="nc-floating-window__header" @pointerdown="startDrag">
          <div class="nc-floating-window__heading">
            <strong>{{ title }}</strong>
            <small v-if="subtitle">{{ subtitle }}</small>
          </div>
          <div class="nc-floating-window__controls">
            <el-button
              :icon="maximized ? ScaleToOriginal : FullScreen"
              text
              circle
              :title="maximized ? '还原' : '最大化'"
              @click="toggleMaximize"
            />
            <el-button :icon="Close" text circle title="关闭" @click="close" />
          </div>
        </header>
        <div class="nc-floating-window__body">
          <slot />
        </div>
        <span
          v-for="edge in (['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw'] as ResizeEdge[])"
          :key="edge"
          :class="['nc-floating-window__resize', `is-${edge}`]"
          :data-resize-edge="edge"
          @pointerdown="startResize($event, edge)"
        />
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.nc-floating-layer { position: fixed; z-index: 1980; inset: 0; pointer-events: none; }
.nc-floating-window { position: fixed; display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; pointer-events: auto; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 8px; box-shadow: var(--nc-shadow-floating); }
.nc-floating-window.is-maximized { border-right: 0; border-bottom: 0; border-left: 0; border-radius: 0; }
.nc-floating-window__header { display: flex; min-height: 52px; flex: none; align-items: center; justify-content: space-between; gap: 12px; padding: 7px 8px 7px 14px; background: var(--nc-bg-elevated); border-bottom: 1px solid var(--nc-divider); cursor: move; user-select: none; }
.nc-floating-window__heading { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.nc-floating-window__heading strong,.nc-floating-window__heading small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-floating-window__heading strong { font-size: 15px; letter-spacing: 0; }
.nc-floating-window__heading small { color: var(--nc-text-secondary); font-size: 12px; }
.nc-floating-window__controls { display: flex; flex: none; align-items: center; }
.nc-floating-window__body { display:flex; min-width: 0; min-height: 0; flex: 1; overflow: hidden; overscroll-behavior: contain; padding: 12px 14px 16px; }
.nc-floating-window__resize { position: absolute; z-index: 2; }
.nc-floating-window__resize.is-n,.nc-floating-window__resize.is-s { right: 10px; left: 10px; height: 8px; cursor: ns-resize; }
.nc-floating-window__resize.is-n { top: -4px; }
.nc-floating-window__resize.is-s { bottom: -4px; }
.nc-floating-window__resize.is-e,.nc-floating-window__resize.is-w { top: 10px; bottom: 10px; width: 8px; cursor: ew-resize; }
.nc-floating-window__resize.is-e { right: -4px; }
.nc-floating-window__resize.is-w { left: -4px; }
.nc-floating-window__resize.is-ne,.nc-floating-window__resize.is-nw,.nc-floating-window__resize.is-se,.nc-floating-window__resize.is-sw { width: 14px; height: 14px; }
.nc-floating-window__resize.is-ne { top: -4px; right: -4px; cursor: nesw-resize; }
.nc-floating-window__resize.is-nw { top: -4px; left: -4px; cursor: nwse-resize; }
.nc-floating-window__resize.is-se { right: -4px; bottom: -4px; cursor: nwse-resize; }
.nc-floating-window__resize.is-sw { bottom: -4px; left: -4px; cursor: nesw-resize; }
</style>
