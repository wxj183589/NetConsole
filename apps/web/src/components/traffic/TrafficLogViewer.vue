<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { TrafficEvent } from '../../types/traffic'

const props = defineProps<{ events: TrafficEvent[] }>()
const source = ref('all')
const autoScroll = ref(true)
const hiddenThrough = ref(0)
const container = ref<HTMLDivElement | null>(null)

const visibleEvents = computed(() => props.events.filter((event) => {
  if (event.sequence <= hiddenThrough.value) return false
  if (source.value === 'all') return true
  return event.type === source.value
}))

watch(() => props.events.length, async () => {
  if (!autoScroll.value) return
  await nextTick()
  if (container.value) container.value.scrollTop = container.value.scrollHeight
})

function eventMessage(event: TrafficEvent): string {
  const payload = event.payload || {}
  return String(payload.message || payload.line || payload.error || payload.state || JSON.stringify(payload))
}

function formatTime(value: string): string {
  return value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : '—'
}

function clearDisplay(): void {
  hiddenThrough.value = Math.max(0, ...props.events.map((event) => event.sequence))
}
</script>

<template>
  <div>
    <div class="log-toolbar">
      <el-select v-model="source" size="small" aria-label="日志来源" style="width: 130px">
        <el-option label="全部日志" value="all" />
        <el-option label="stdout" value="stdout" />
        <el-option label="stderr" value="stderr" />
        <el-option label="system" value="system" />
        <el-option label="error" value="error" />
      </el-select>
      <el-checkbox v-model="autoScroll">自动滚动</el-checkbox>
      <el-button link @click="clearDisplay">清空显示</el-button>
    </div>
    <div ref="container" class="log-viewer">
      <div v-for="event in visibleEvents" :key="event.sequence" class="log-row">
        <time>{{ formatTime(event.timestamp) }}</time>
        <span class="source">{{ event.source }}</span>
        <span :class="['event-type', event.type]">{{ event.type }}</span>
        <span class="message">{{ eventMessage(event) }}</span>
      </div>
      <el-empty v-if="!visibleEvents.length" description="暂无日志事件" :image-size="72" />
    </div>
  </div>
</template>

<style scoped>
.log-toolbar {
  align-items: center;
  display: flex;
  gap: 14px;
  justify-content: flex-end;
  margin: 12px 0 8px;
}

.log-viewer {
  background: #0f172a;
  border-radius: 12px;
  color: #dbeafe;
  font-family: Consolas, 'Cascadia Mono', monospace;
  font-size: 12px;
  max-height: 320px;
  min-height: 180px;
  overflow: auto;
  padding: 12px;
}

.log-row {
  display: grid;
  grid-template-columns: 82px 70px 70px minmax(240px, 1fr);
  gap: 10px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.source,
.event-type {
  color: #93c5fd;
}

.event-type.error {
  color: #fca5a5;
}

.message {
  color: #e5e7eb;
}
</style>
