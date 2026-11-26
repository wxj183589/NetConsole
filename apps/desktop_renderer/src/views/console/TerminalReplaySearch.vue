<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Close, Search } from '@element-plus/icons-vue'
import { apiRequest } from '../../api/client'

const props = defineProps<{ text: string; sessionId?: string; truncated?: boolean }>()
const query = ref('')
const input = ref<HTMLInputElement>()
const output = ref<HTMLPreElement>()
const total = ref(0)
const current = ref(-1)
const searching = ref(false)
const status = ref('')
const excerpt = ref<{ text: string; start: number; length: number; offset: number }>()
let request: AbortController | undefined
const palette = ['#111827', '#f87171', '#4ade80', '#facc15', '#60a5fa', '#e879f9', '#22d3ee', '#e5e7eb',
  '#6b7280', '#fca5a5', '#86efac', '#fde68a', '#93c5fd', '#f0abfc', '#67e8f9', '#ffffff']
const segments = computed(() => {
  const runs: { text: string; style: Record<string, string> }[] = []
  let start = 0
  let color: string | undefined
  let backgroundColor: string | undefined
  const attributes = new Set<number>()
  function style(): Record<string, string> {
    const reverse = attributes.has(7)
    return {
      color: reverse ? backgroundColor ?? 'var(--nc-bg-code)' : color ?? '',
      backgroundColor: reverse ? color ?? 'var(--nc-text-code)' : backgroundColor ?? '',
      fontWeight: attributes.has(1) ? 'bold' : '',
      opacity: attributes.has(2) ? '0.65' : '',
      fontStyle: attributes.has(3) ? 'italic' : '',
      visibility: attributes.has(8) ? 'hidden' : '',
      textDecoration: [attributes.has(4) ? 'underline' : '', attributes.has(9) ? 'line-through' : ''].filter(Boolean).join(' '),
    }
  }
  for (const match of props.text.matchAll(/\x1b\[([0-9;]*)m/g)) {
    if (match.index > start) runs.push({ text: props.text.slice(start, match.index), style: style() })
    const codes = match[1].split(';').map(Number)
    for (let index = 0; index < codes.length; index += 1) {
      const code = codes[index]
      if (code === 0) {
        attributes.clear()
        color = backgroundColor = undefined
      } else if (code === 38 || code === 48) {
        const mode = codes[++index]
        let extended: string | undefined
        if (mode === 5) {
          const slot = codes[++index]
          if (slot < 16) extended = palette[slot]
          else if (slot < 232) {
            const levels = [0, 95, 135, 175, 215, 255]
            const cube = slot - 16
            extended = `rgb(${levels[Math.floor(cube / 36)]}, ${levels[Math.floor(cube / 6) % 6]}, ${levels[cube % 6]})`
          } else if (slot <= 255) {
            const gray = 8 + (slot - 232) * 10
            extended = `rgb(${gray}, ${gray}, ${gray})`
          }
        } else if (mode === 2) {
          const channels = codes.slice(index + 1, index + 4)
          index += 3
          if (channels.length === 3 && channels.every(channel => channel <= 255)) extended = `rgb(${channels.join(', ')})`
        }
        if (code === 38) color = extended
        else backgroundColor = extended
      } else if (code === 39) color = undefined
      else if (code === 49) backgroundColor = undefined
      else if ((code >= 30 && code <= 37) || (code >= 90 && code <= 97)) color = palette[code < 90 ? code - 30 : code - 82]
      else if ((code >= 40 && code <= 47) || (code >= 100 && code <= 107)) backgroundColor = palette[code < 100 ? code - 40 : code - 92]
      else attributes.add(code)
    }
    start = match.index + match[0].length
  }
  if (start < props.text.length) runs.push({ text: props.text.slice(start), style: style() })
  return runs
})
const allMatches = new Highlight()
const activeMatch = new Highlight()
let matches: Range[] = []
let timer: ReturnType<typeof setTimeout> | undefined

function resetSearchState(): void {
  clearTimeout(timer)
  request?.abort()
  request = undefined
  excerpt.value = undefined
  status.value = ''
  allMatches.clear()
  activeMatch.clear()
  matches = []
  current.value = -1
  total.value = 0
  searching.value = false
}

function move(step: number): void {
  if (props.truncated && total.value) {
    void searchRecording((current.value + step + total.value) % total.value, false)
    return
  }
  if (!matches.length || !output.value) return
  current.value = (current.value + step + matches.length) % matches.length
  const range = matches[current.value]
  activeMatch.clear()
  activeMatch.add(range)
  const viewport = output.value
  const bounds = viewport.getBoundingClientRect()
  const match = range.getBoundingClientRect()
  if (match.top < bounds.top || match.bottom > bounds.bottom) {
    viewport.scrollTop += match.top - bounds.top - viewport.clientHeight / 2
  }
}

async function searchRecording(index: number, countAll: boolean): Promise<void> {
  request?.abort()
  const controller = new AbortController()
  request = controller
  searching.value = true
  status.value = '正在搜索完整记录'
  const queryParams = new URLSearchParams({ keyword: query.value, ordinal: String(index + 1), count_all: String(countAll) })
  try {
    const result = await apiRequest<{ total: number; match: typeof excerpt.value }>(
      `/api/terminal/history/${encodeURIComponent(props.sessionId ?? '')}/search?${queryParams}`,
      { signal: controller.signal, queryTimeoutMs: 300_000 },
    )
    if (controller.signal.aborted) return
    if (countAll) total.value = result.total
    excerpt.value = result.match
    current.value = result.match ? index : -1
    status.value = result.match ? '' : '0 条'
  } catch (error) {
    if (!controller.signal.aborted) status.value = error instanceof Error ? error.message : '搜索失败'
  } finally {
    if (request === controller) searching.value = false
  }
}

function cancelSearch(): void {
  resetSearchState()
  status.value = '搜索已取消'
}

watch([query, () => props.text], async ([keyword], _, onCleanup) => {
  resetSearchState()
  let cancelled = false
  onCleanup(() => { cancelled = true; clearTimeout(timer) })
  if (!keyword || !props.text) return
  searching.value = true
  if (props.truncated && props.sessionId) {
    status.value = '等待搜索'
    timer = setTimeout(() => { void searchRecording(0, true) }, 160)
    return
  }
  await nextTick()
  if (cancelled) return
  if (!output.value) return
  const walker = document.createTreeWalker(output.value, NodeFilter.SHOW_TEXT)
  const nodes: { node: Node; start: number; end: number }[] = []
  let offset = 0
  while (walker.nextNode()) {
    const node = walker.currentNode
    const length = node.textContent?.length ?? 0
    if (length) nodes.push({ node, start: offset, end: offset + length })
    offset += length
  }
  const value = output.value.textContent ?? ''
  const pattern = new RegExp(keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'giu')
  let nodeIndex = 0
  function scan(): void {
    const deadline = performance.now() + 6
    let match: RegExpExecArray | null
    while ((match = pattern.exec(value))) {
      const range = new Range()
      const end = match.index + match[0].length
      while (nodes[nodeIndex].end <= match.index) nodeIndex += 1
      const first = nodes[nodeIndex]
      range.setStart(first.node, match.index - first.start)
      while (nodes[nodeIndex].end < end) nodeIndex += 1
      const last = nodes[nodeIndex]
      range.setEnd(last.node, end - last.start)
      matches.push(range)
      allMatches.add(range)
      if (performance.now() >= deadline) {
        timer = setTimeout(scan, 0)
        return
      }
    }
    searching.value = false
    total.value = matches.length
    move(1)
  }
  CSS.highlights.set('console-replay-match', allMatches)
  activeMatch.priority = 1
  CSS.highlights.set('console-replay-active', activeMatch)
  timer = setTimeout(scan, 160)
})

onBeforeUnmount(() => {
  resetSearchState()
  if (CSS.highlights.get('console-replay-match') === allMatches) CSS.highlights.delete('console-replay-match')
  if (CSS.highlights.get('console-replay-active') === activeMatch) CSS.highlights.delete('console-replay-active')
})

function handleKey(event: KeyboardEvent, close: () => void): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    event.stopPropagation()
    input.value?.select()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    if (query.value) query.value = ''
    else close()
  }
}
defineExpose({ handleKey })
</script>

<template>
  <div class="replay-search">
    <Search aria-hidden="true" />
    <input ref="input" v-model="query" aria-label="搜索关键字" placeholder="搜索关键字" maxlength="512" @keydown.enter.prevent="move($event.shiftKey ? -1 : 1)" />
    <el-button :icon="ArrowUp" aria-label="上一个匹配项" title="上一个匹配项" :disabled="!total" @click="move(-1)" />
    <el-button :icon="ArrowDown" aria-label="下一个匹配项" title="下一个匹配项" :disabled="!total" @click="move(1)" />
    <output aria-live="polite">{{ status || (searching ? '搜索中' : total ? `${current + 1}/${total}` : '0 条') }}</output>
    <el-button v-if="searching && truncated" @click="cancelSearch">取消搜索</el-button>
    <el-button :icon="Close" aria-label="清除搜索" title="清除搜索" :disabled="!query" @click="query = ''; input?.focus()" />
  </div>
  <pre v-if="excerpt" class="replay-output" tabindex="0">{{ excerpt.text.slice(0, excerpt.start) }}<mark>{{ excerpt.text.slice(excerpt.start, excerpt.start + excerpt.length) }}</mark>{{ excerpt.text.slice(excerpt.start + excerpt.length) }}</pre>
  <pre v-else ref="output" class="replay-output" tabindex="0"><template v-if="segments.length"><span v-for="(segment, index) in segments" :key="index" :style="segment.style">{{ segment.text }}</span></template><template v-else>暂无可回放输出</template></pre>
</template>

<style scoped>
.replay-search { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.replay-search > svg { width: 16px; }
.replay-search input { flex: 1; min-width: 72px; padding: 6px; color: inherit; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 4px; }
.replay-search output { min-width: 7ch; text-align: center; font-variant-numeric: tabular-nums; }
.replay-search .el-button + .el-button { margin-left: 0; }
.replay-output { min-height: min(420px, 45vh); max-height: 60vh; margin: 0; padding: 14px; overflow: auto; border-radius: 8px; color: var(--nc-text-code); background: var(--nc-bg-code); font: 13px/1.45 var(--nc-font-family-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
:global(::highlight(console-replay-match)) { background-color: var(--nc-status-warning-bg); color: var(--nc-text-primary); }
:global(::highlight(console-replay-active)) { background-color: var(--nc-warning); color: var(--nc-bg-app); }
</style>
