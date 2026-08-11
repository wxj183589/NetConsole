const widthCache = new Map<string, number>()
let canvasContext: CanvasRenderingContext2D | null | undefined

function resolveCanvasContext(): CanvasRenderingContext2D | null {
  if (canvasContext !== undefined) return canvasContext
  if (typeof document === 'undefined') return (canvasContext = null)
  canvasContext = document.createElement('canvas').getContext('2d')
  return canvasContext
}

function measureWithDom(text: string, font: string): number {
  if (typeof document === 'undefined' || !document.body) return 0
  const span = document.createElement('span')
  span.textContent = text
  span.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:${font};inset:auto auto -10000px -10000px;`
  document.body.appendChild(span)
  const width = span.getBoundingClientRect().width
  span.remove()
  return width
}

function estimateGlyphWidth(text: string, fontSize: number): number {
  let width = 0
  for (const char of text) {
    if (/\p{Script=Han}|[\u3000-\u303f\uff00-\uffef]/u.test(char)) width += fontSize
    else if (/[MW@#%&]/.test(char)) width += fontSize * 0.86
    else if (/[ilI1|.,:;'`]/.test(char)) width += fontSize * 0.34
    else if (/\s/.test(char)) width += fontSize * 0.32
    else width += fontSize * 0.62
  }
  return width
}

export function measureTextWidth(text: unknown, font = '14px "Microsoft YaHei UI", sans-serif'): number {
  const normalized = String(text ?? '')
  const key = `${font}\u0000${normalized}`
  const cached = widthCache.get(key)
  if (cached != null) return cached

  let width = 0
  const context = resolveCanvasContext()
  if (context) {
    context.font = font
    width = context.measureText(normalized).width
  }
  if (!(width > 0)) width = measureWithDom(normalized, font)
  if (!(width > 0)) {
    const fontSize = Number.parseFloat(font.match(/(\d+(?:\.\d+)?)px/)?.[1] ?? '14')
    width = estimateGlyphWidth(normalized, fontSize)
  }
  const rounded = Math.ceil(width)
  widthCache.set(key, rounded)
  return rounded
}

export function clearTextMeasurementCache(): void {
  widthCache.clear()
  canvasContext = undefined
}
