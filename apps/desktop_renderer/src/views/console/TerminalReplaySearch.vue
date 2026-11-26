<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Close, Search } from '@element-plus/icons-vue'

const props = defineProps<{ text: string }>()
const query = ref('')
const input = ref<HTMLInputElement>()
const output = ref<HTMLPreElement>()
const total = ref(0)
const current = ref(-1)
const searching = ref(false)
const palette = ['#111827', '#f87171', '#4ade80', '#facc15', '#60a5fa', '#e879f9', '#22d3ee', '#e5e7eb',
  '#6b7280', '#fca5a5', '#86efac', '#fde68a', '#93c5fd', '#f0abfc', '#67e8f9', '#ffffff']
const segments = computed(() => {
  const runs: { text: string; color?: string; backgroundColor?: string }[] = []
  let start = 0
  let color: string | undefined
  let backgroundColor: string | undefined
  for (const match of props.text.matchAll(/\x1b\[(?:(\d{2});(\d{2,3})|0)m/g)) {
    if (match.index > start) runs.push({ text: props.text.slice(start, match.index), color, backgroundColor })
    const foreground = Number(match[1])
    const background = Number(match[2])
    color = foreground === 39 ? undefined : palette[foreground < 90 ? foreground - 30 : foreground - 82]
    backgroundColor = background === 49 ? undefined : palette[background < 100 ? background - 40 : background - 92]
    start = match.index + match[0].length
  }
  if (start < props.text.length) runs.push({ text: props.text.slice(start), color, backgroundColor })
  return runs
})
const allMatches = new Highlight()
const activeMatch = new Highlight()
let matches: Range[] = []
let timer: ReturnType<typeof setTimeout> | undefined

function clearMatches(): void {
  clearTimeout(timer)
  allMatches.clear()
  activeMatch.clear()
  matches = []
  current.value = -1
  total.value = 0
  searching.value = false
}

function move(step: number): void {
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

watch([query, () => props.text], async ([keyword], _, onCleanup) => {
  clearMatches()
  let cancelled = false
  onCleanup(() => { cancelled = true; clearTimeout(timer) })
  if (!keyword || !props.text) return
  searching.value = true
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
  clearMatches()
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
    <output aria-live="polite">{{ searching ? '搜索中' : total ? `${current + 1}/${total}` : '0 条' }}</output>
    <el-button :icon="Close" aria-label="清除搜索" title="清除搜索" :disabled="!query" @click="query = ''; input?.focus()" />
  </div>
  <pre ref="output" class="replay-output" tabindex="0"><template v-if="segments.length"><span v-for="(segment, index) in segments" :key="index" :style="{ color: segment.color, backgroundColor: segment.backgroundColor }">{{ segment.text }}</span></template><template v-else>暂无可回放输出</template></pre>
</template>

<style scoped>
.replay-search { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.replay-search > svg { width: 16px; }
.replay-search input { flex: 1; min-width: 72px; padding: 6px; color: inherit; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 4px; }
.replay-search output { min-width: 7ch; text-align: center; font-variant-numeric: tabular-nums; }
.replay-search .el-button + .el-button { margin-left: 0; }
.replay-output { min-height: min(420px, 45vh); max-height: 60vh; margin: 0; padding: 14px; overflow: auto; border-radius: 8px; color: var(--nc-text-code); background: var(--nc-bg-code); font: 13px/1.45 var(--nc-font-family-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
:global(::highlight(console-replay-match)) { background-color: #f4da81; color: #231c07; }
:global(::highlight(console-replay-active)) { background-color: #ff9e52; color: #231c07; }
</style>
