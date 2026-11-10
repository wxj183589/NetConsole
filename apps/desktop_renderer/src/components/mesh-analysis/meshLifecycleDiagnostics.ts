export interface MeshLifecycleSnapshot {
  enabled: boolean
  component_count: number
  active_echarts_instances: number
  init_count: number
  dispose_count: number
  active_canvas_count: number
  wheel_listeners: number
  datazoom_listeners: number
  tooltip_listeners: number
  resize_observers: number
  native_listener_count: number
  mount_count: number
  unmount_count: number
}

const LIFECYCLE_GLOBAL = '__NETCONSOLE_MESH_ECHARTS_LIFECYCLE__'
const ENABLED = import.meta.env.DEV || import.meta.env.MODE === 'test'

type LifecycleEntry = {
  mounted: boolean
  initialized: boolean
  canvasCount: number
  resizeObserver: boolean
  listeners: Set<string>
}

const entries = new Set<LifecycleEntry>()
let initCount = 0
let disposeCount = 0
let mountCount = 0
let unmountCount = 0
let activeEchartsInstances = 0
let activeCanvasCount = 0
let resizeObservers = 0
let wheelListeners = 0
let datazoomListeners = 0
let tooltipListeners = 0
let nativeListenerCount = 0

function snapshot(): MeshLifecycleSnapshot {
  return {
    enabled: ENABLED,
    component_count: entries.size,
    active_echarts_instances: activeEchartsInstances,
    init_count: initCount,
    dispose_count: disposeCount,
    active_canvas_count: activeCanvasCount,
    wheel_listeners: wheelListeners,
    datazoom_listeners: datazoomListeners,
    tooltip_listeners: tooltipListeners,
    resize_observers: resizeObservers,
    native_listener_count: nativeListenerCount,
    mount_count: mountCount,
    unmount_count: unmountCount,
  }
}

function publish(): void {
  if (!ENABLED || typeof globalThis === 'undefined') return
  const target = globalThis as typeof globalThis & {
    [LIFECYCLE_GLOBAL]?: { snapshot: () => MeshLifecycleSnapshot }
  }
  target[LIFECYCLE_GLOBAL] = { snapshot }
}

function setCanvasCount(entry: LifecycleEntry, host: HTMLElement | null): void {
  const next = host ? host.querySelectorAll('canvas').length : 0
  activeCanvasCount += next - entry.canvasCount
  entry.canvasCount = next
}

function removeListener(entry: LifecycleEntry, name: string): void {
  if (!entry.listeners.delete(name)) return
  nativeListenerCount = Math.max(0, nativeListenerCount - 1)
  if (name === 'wheel') wheelListeners = Math.max(0, wheelListeners - 1)
}

function removeAllListeners(entry: LifecycleEntry): void {
  for (const name of [...entry.listeners]) removeListener(entry, name)
}

export interface MeshChartLifecycleHandle {
  mount(): void
  addNativeListener(name: string): void
  removeNativeListener(name: string): void
  addResizeObserver(): void
  removeResizeObserver(): void
  initialize(host: HTMLElement): void
  syncCanvas(host: HTMLElement | null): void
  dispose(host?: HTMLElement | null): void
  unmount(): void
}

export function createMeshChartLifecycleHandle(): MeshChartLifecycleHandle {
  const entry: LifecycleEntry = {
    mounted: false,
    initialized: false,
    canvasCount: 0,
    resizeObserver: false,
    listeners: new Set(),
  }

  return {
    mount() {
      if (!ENABLED || entry.mounted) return
      entry.mounted = true
      entries.add(entry)
      mountCount += 1
      publish()
    },
    addNativeListener(name) {
      if (!ENABLED || !entry.mounted || entry.listeners.has(name)) return
      entry.listeners.add(name)
      nativeListenerCount += 1
      if (name === 'wheel') wheelListeners += 1
      publish()
    },
    removeNativeListener(name) {
      if (!ENABLED) return
      removeListener(entry, name)
      publish()
    },
    addResizeObserver() {
      if (!ENABLED || !entry.mounted || entry.resizeObserver) return
      entry.resizeObserver = true
      resizeObservers += 1
      publish()
    },
    removeResizeObserver() {
      if (!ENABLED || !entry.resizeObserver) return
      entry.resizeObserver = false
      resizeObservers = Math.max(0, resizeObservers - 1)
      publish()
    },
    initialize(host) {
      if (!ENABLED || !entry.mounted || entry.initialized) return
      entry.initialized = true
      initCount += 1
      activeEchartsInstances += 1
      datazoomListeners += 1
      tooltipListeners += 1
      setCanvasCount(entry, host)
      publish()
    },
    syncCanvas(host) {
      if (!ENABLED || !entry.mounted) return
      setCanvasCount(entry, host)
      publish()
    },
    dispose(host = null) {
      if (!ENABLED || !entry.initialized) return
      entry.initialized = false
      disposeCount += 1
      activeEchartsInstances = Math.max(0, activeEchartsInstances - 1)
      datazoomListeners = Math.max(0, datazoomListeners - 1)
      tooltipListeners = Math.max(0, tooltipListeners - 1)
      setCanvasCount(entry, host)
      publish()
    },
    unmount() {
      if (!ENABLED || !entry.mounted) return
      if (entry.initialized) this.dispose()
      this.removeResizeObserver()
      removeAllListeners(entry)
      activeCanvasCount = Math.max(0, activeCanvasCount - entry.canvasCount)
      entry.canvasCount = 0
      entries.delete(entry)
      entry.mounted = false
      unmountCount += 1
      publish()
    },
  }
}

export function getMeshLifecycleSnapshot(): MeshLifecycleSnapshot {
  return snapshot()
}
