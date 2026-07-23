<script setup lang="ts">
import { computed } from 'vue'

import {
  displayTracksideTooltipMetric,
  sortTracksideTooltipEntries,
  tracksideTooltipApLabel,
  type TracksideTooltipEntry,
} from './tracksideTooltip'

const props = withDefaults(defineProps<{
  visible?: boolean
  timestamp?: string | null
  entries?: TracksideTooltipEntry[]
  side?: 'left' | 'right'
}>(), {
  visible: false,
  timestamp: null,
  entries: () => [],
  side: 'right',
})

const emit = defineEmits<{
  pointerenter: []
  pointerleave: []
}>()

const sortedEntries = computed(() => sortTracksideTooltipEntries(props.entries))

function hasActiveDuration(entry: TracksideTooltipEntry): boolean {
  return entry.role === 'ACTIVE'
    && entry.activeDurationSeconds != null
    && Number.isFinite(entry.activeDurationSeconds)
    && entry.activeDurationSeconds >= 0
}
</script>

<template>
  <div
    v-if="visible"
    class="trackside-external-tooltip"
    :class="`is-${side}`"
    data-trackside-external-tooltip
    @pointerenter="emit('pointerenter')"
    @pointerleave="emit('pointerleave')"
    @pointerdown.stop
    @click.stop
    @wheel.stop
  >
    <div class="trackside-external-tooltip__time">
      采样时间：{{ timestamp || '—' }}
    </div>
    <div v-if="!sortedEntries.length" class="trackside-external-tooltip__empty">
      当前时刻无有效采样
    </div>
    <section
      v-for="(entry, index) in sortedEntries"
      :key="`${entry.role}:${tracksideTooltipApLabel(entry)}:${entry.radio ?? 'unknown'}:${index}`"
      class="trackside-tooltip-entry"
    >
      <div
        class="trackside-tooltip-entry__role"
        :class="entry.role === 'ACTIVE' ? 'is-active' : 'is-standby'"
      >
        <span
          class="trackside-tooltip-entry__marker"
          :style="{ color: entry.color }"
        >{{ entry.role === 'ACTIVE' ? '●' : '○' }}</span>
        {{ entry.role }}
      </div>
      <div class="trackside-tooltip-entry__ap">
        AP：{{ tracksideTooltipApLabel(entry) }} · Radio {{ displayTracksideTooltipMetric(entry.radio) }}
      </div>
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
</template>

<style scoped>
.trackside-external-tooltip {
  position: absolute;
  top: 12px;
  z-index: 20;
  width: min(340px, calc(100% - 24px));
  min-width: min(260px, calc(100% - 24px));
  max-height: min(420px, 60%);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 10px 12px;
  border: 1px solid var(--nc-border);
  border-radius: 6px;
  background: var(--nc-bg-elevated);
  box-shadow: var(--nc-shadow-floating);
  color: var(--nc-text-primary);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.trackside-external-tooltip.is-left { left: 12px; }
.trackside-external-tooltip.is-right { right: 12px; }
.trackside-external-tooltip__time { margin-bottom: 8px; color: var(--nc-text-secondary); }
.trackside-external-tooltip__empty { color: var(--nc-text-secondary); }
.trackside-tooltip-entry + .trackside-tooltip-entry { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--nc-border-light); }
.trackside-tooltip-entry__role { font-weight: 700; }
.trackside-tooltip-entry__role.is-active { color: var(--nc-success); }
.trackside-tooltip-entry__role.is-standby { color: var(--nc-text-secondary); }
.trackside-tooltip-entry__marker { display: inline-block; width: 1em; }
.trackside-tooltip-entry__ap { margin-top: 2px; font-weight: 600; }
</style>
