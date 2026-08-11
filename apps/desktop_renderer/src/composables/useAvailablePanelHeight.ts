import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

export interface AvailablePanelHeightOptions {
  minHeight: number
  bottomGap: number
}

export function measureAvailablePanelHeight(
  viewportHeight: number,
  top: number,
  options: AvailablePanelHeightOptions,
): number {
  return Math.max(options.minHeight, Math.floor(viewportHeight - top - options.bottomGap))
}

export function useAvailablePanelHeight(
  container: Ref<HTMLElement | null>,
  options: AvailablePanelHeightOptions,
) {
  const height = ref(options.minHeight)
  let resizeObserver: ResizeObserver | null = null
  let frame: number | null = null

  function update(): void {
    frame = null
    const element = container.value
    if (!element || !element.isConnected) return
    const bounds = element.getBoundingClientRect()
    if (bounds.width <= 0) return
    const next = measureAvailablePanelHeight(window.innerHeight, bounds.top, options)
    if (height.value !== next) height.value = next
  }

  function refresh(): void {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = requestAnimationFrame(update)
  }

  function observe(element: HTMLElement | null): void {
    resizeObserver?.disconnect()
    resizeObserver = null
    if (!element || typeof ResizeObserver === 'undefined') return
    resizeObserver = new ResizeObserver(refresh)
    resizeObserver.observe(element)
    if (element.parentElement) resizeObserver.observe(element.parentElement)
    resizeObserver.observe(document.documentElement)
  }

  watch(container, (element) => {
    observe(element)
    refresh()
  })

  onMounted(() => {
    observe(container.value)
    window.addEventListener('resize', refresh)
    refresh()
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', refresh)
    resizeObserver?.disconnect()
    resizeObserver = null
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
  })

  return { height, refresh }
}
