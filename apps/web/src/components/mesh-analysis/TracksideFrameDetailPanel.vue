<script setup lang="ts">
import { computed } from 'vue'
import { Close } from '@element-plus/icons-vue'

import {
  displayTracksideTooltipMetric,
  sortTracksideTooltipEntries,
  tracksideTooltipApLabel,
  type PinnedTracksideFrame,
  type TracksideTooltipEntry,
} from './tracksideTooltip'

const props = defineProps<{
  frame: PinnedTracksideFrame
  outsideRange?: boolean
}>()

const emit = defineEmits<{
  close: []
  select: [entry: TracksideTooltipEntry]
}>()

const sortedEntries = computed(() => sortTracksideTooltipEntries(props.frame.entries))
const activeCount = computed(() => props.frame.entries.filter((entry) => entry.role === 'ACTIVE').length)
const standbyCount = computed(() => props.frame.entries.length - activeCount.value)
const countSummary = computed(() => [
  activeCount.value ? `ACTIVE ${activeCount.value} 条` : '',
  standbyCount.value ? `STANDBY ${standbyCount.value} 条` : '',
  `共 ${props.frame.entries.length} 条`,
].filter(Boolean).join(' · '))

function hasActiveDuration(entry: TracksideTooltipEntry): boolean {
  return entry.role === 'ACTIVE'
    && entry.activeDurationSeconds != null
    && Number.isFinite(entry.activeDurationSeconds)
    && entry.activeDurationSeconds >= 0
}
</script>

<template>
  <aside
    class="trackside-frame-detail-panel"
    data-trackside-frame-detail-panel
    @click.stop
    @pointerdown.stop
    @wheel.stop
  >
    <header class="trackside-frame-detail-panel__header">
      <div class="trackside-frame-detail-panel__heading">
        <strong>轨旁链路详情</strong>
        <span>采样时间：{{ frame.timestamp }}</span>
        <span>{{ countSummary }}</span>
        <span v-if="outsideRange" class="trackside-frame-detail-panel__status">
          当前固定采样位于可见范围外
        </span>
      </div>
      <button
        type="button"
        class="trackside-frame-detail-panel__close"
        title="关闭"
        aria-label="关闭"
        @click="emit('close')"
      >
        <Close />
      </button>
    </header>
    <div class="trackside-frame-detail-panel__body">
      <section
        v-for="entry in sortedEntries"
        :key="`${entry.seriesId}:${entry.metaId}`"
        class="trackside-frame-detail-entry"
      >
        <div
          class="trackside-frame-detail-entry__role"
          :class="entry.role === 'ACTIVE' ? 'is-active' : 'is-standby'"
        >
          <span :style="{ color: entry.color }">{{ entry.role === 'ACTIVE' ? '●' : '○' }}</span>
          {{ entry.role }}
        </div>
        <button
          type="button"
          class="trackside-frame-detail-entry__ap"
          @click="emit('select', entry)"
        >
          AP：{{ tracksideTooltipApLabel(entry) }} · Radio {{ displayTracksideTooltipMetric(entry.radio) }}
        </button>
        <div>
          轨旁 / MR RSSI：{{ displayTracksideTooltipMetric(entry.tracksideRssi) }} / {{ displayTracksideTooltipMetric(entry.mrRssi) }}
        </div>
        <div>
          站点 / 区间：{{ entry.station || '—' }} / {{ entry.section || '—' }}
        </div>
        <div v-if="hasActiveDuration(entry)">
          主链持续：{{ displayTracksideTooltipMetric(entry.activeDurationSeconds) }} s
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.trackside-frame-detail-panel {
  position: absolute;
  top: 8px;
  right: 8px;
  bottom: 8px;
  z-index: 30;
  display: flex;
  width: clamp(380px, 32vw, 520px);
  max-width: calc(100% - 16px);
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--nc-border-strong);
  border-radius: 6px;
  background: var(--nc-bg-elevated);
  box-shadow: var(--nc-shadow-floating);
  color: var(--nc-text-primary);
  font-size: 12px;
  line-height: 1.5;
}
.trackside-frame-detail-panel__header {
  display: flex;
  flex: none;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--nc-border);
}
.trackside-frame-detail-panel__heading { display: grid; min-width: 0; gap: 2px; }
.trackside-frame-detail-panel__heading strong { font-size: 14px; }
.trackside-frame-detail-panel__heading span { color: var(--nc-text-secondary); }
.trackside-frame-detail-panel__heading .trackside-frame-detail-panel__status { color: var(--nc-warning); }
.trackside-frame-detail-panel__close {
  display: inline-flex;
  width: 28px;
  height: 28px;
  flex: none;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--nc-text-secondary);
  cursor: pointer;
}
.trackside-frame-detail-panel__close:hover { background: var(--nc-bg-muted); color: var(--nc-text-primary); }
.trackside-frame-detail-panel__close svg { width: 16px; height: 16px; }
.trackside-frame-detail-panel__body {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 4px 14px 14px;
}
.trackside-frame-detail-entry {
  padding: 10px 0;
  break-inside: avoid;
}
.trackside-frame-detail-entry + .trackside-frame-detail-entry { border-top: 1px solid var(--nc-border-light); }
.trackside-frame-detail-entry__role { font-weight: 700; }
.trackside-frame-detail-entry__role.is-active { color: var(--nc-success); }
.trackside-frame-detail-entry__role.is-standby { color: var(--nc-text-secondary); }
.trackside-frame-detail-entry__role span { display: inline-block; width: 1em; }
.trackside-frame-detail-entry__ap {
  display: block;
  max-width: 100%;
  margin: 2px 0 0;
  padding: 0;
  overflow-wrap: anywhere;
  border: 0;
  background: transparent;
  color: var(--nc-text-primary);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  text-align: left;
}
.trackside-frame-detail-entry__ap:hover { color: var(--nc-primary); }
</style>
