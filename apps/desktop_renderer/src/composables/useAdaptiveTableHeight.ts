import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

export interface AdaptiveTableHeightOptions {
  rowHeight?: number
  headerHeight?: number
  emptyHeight?: number
  minVisibleRows?: number
  maxVisibleRows?: number
  bottomGap?: number
}

export interface AdaptiveTableHeightMeasurement {
  maxHeight: number
  contentHeight: number
  needsInternalScroll: boolean
}

export function measureAdaptiveTableHeight(
  viewportHeight: number,
  top: number,
  rowCount: number,
  options: AdaptiveTableHeightOptions = {},
): AdaptiveTableHeightMeasurement {
  const rowHeight = Math.max(1, options.rowHeight ?? 34)
  const headerHeight = Math.max(1, options.headerHeight ?? rowHeight)
  const emptyHeight = Math.max(headerHeight, options.emptyHeight ?? 200)
  const minVisibleRows = Math.max(1, options.minVisibleRows ?? 4)
  const maxVisibleRows = Math.max(minVisibleRows, options.maxVisibleRows ?? 18)
  const bottomGap = Math.max(0, options.bottomGap ?? 24)
  const rows = Math.max(0, Math.floor(rowCount))
  const naturalHeight = rows ? headerHeight + rows * rowHeight + 2 : emptyHeight
  const minimum = headerHeight + Math.min(Math.max(rows, 1), minVisibleRows) * rowHeight
  const rowCap = headerHeight + maxVisibleRows * rowHeight + 2
  const viewportCap = Math.max(minimum, Math.floor(viewportHeight - top - bottomGap))
  const maxHeight = Math.max(headerHeight, Math.min(rowCap, viewportCap))
  return {
    maxHeight,
    contentHeight: Math.min(naturalHeight, maxHeight),
    needsInternalScroll: naturalHeight > maxHeight,
  }
}

export function useAdaptiveTableHeight(
  container: Ref<HTMLElement | null>,
  rowCount: Ref<number>,
  options: AdaptiveTableHeightOptions = {},
) {
  const initial = measureAdaptiveTableHeight(900, 0, rowCount.value, options)
  const maxHeight = ref(initial.maxHeight)
  const contentHeight = ref(initial.contentHeight)
  const needsInternalScroll = ref(initial.needsInternalScroll)
  let resizeObserver: ResizeObserver | null = null
  let frame: number | null = null

  function update(): void {
    frame = null
    const element = container.value
    if (!element || !element.isConnected) return
    const bounds = element.getBoundingClientRect()
    if (bounds.width <= 0) return
    const measured = measureAdaptiveTableHeight(
      window.innerHeight,
      bounds.top,
      rowCount.value,
      options,
    )
    maxHeight.value = measured.maxHeight
    contentHeight.value = measured.contentHeight
    needsInternalScroll.value = measured.needsInternalScroll
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
  watch(rowCount, refresh)

  onMounted(() => {
    observe(container.value)
    window.addEventListener('resize', refresh)
    refresh()
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', refresh)
    resizeObserver?.disconnect()
    if (frame !== null) cancelAnimationFrame(frame)
  })

  return { maxHeight, contentHeight, needsInternalScroll, refresh }
}
