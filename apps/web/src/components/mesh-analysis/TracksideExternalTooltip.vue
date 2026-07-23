<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

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
  availableHeight?: number
}>(), {
  visible: false,
  timestamp: null,
  entries: () => [],
  side: 'right',
  availableHeight: 640,
})

const emit = defineEmits<{
  pin: []
  pointerenter: []
  pointerleave: []
}>()

const sortedEntries = computed(() => sortTracksideTooltipEntries(props.entries))
const body = ref<HTMLDivElement | null>(null)
const overflowing = ref(false)
const tooltipStyle = computed(() => ({
  maxHeight: `${Math.max(0, Math.min(props.availableHeight, 640))}px`,
}))

watch(
  () => [props.visible, props.entries, props.availableHeight] as const,
  () => {
    void nextTick(() => {
      overflowing.value = Boolean(
        body.value
        && body.value.scrollHeight > body.value.clientHeight + 1,
      )
    })
  },
  { immediate: true },
)

function hasActiveDuration(entry: TracksideTooltipEntry): boolean {
  return entry.role === 'ACTIVE'
    && entry.activeDurationSeconds != null
    && Number.isFinite(entry.activeDurationSeconds)
    && entry.activeDurationSeconds >= 0
}
</script>

<template>
  <div
    v-if="visible && sortedEntries.length"
    class="trackside-external-tooltip"
    :class="`is-${side}`"
    :style="tooltipStyle"
    data-trackside-external-tooltip
    @pointerenter="emit('pointerenter')"
    @pointerleave="emit('pointerleave')"
    @pointerdown.stop
    @click.stop
    @wheel.stop
  >
    <div class="trackside-external-tooltip__header">
      <span>采样时间：{{ timestamp || '—' }}</span>
      <button
        type="button"
        class="trackside-external-tooltip__pin"
        @click="emit('pin')"
      >
        固定查看
      </button>
    </div>
    <div ref="body" class="trackside-external-tooltip__body">
      <section
        v-for="entry in sortedEntries"
        :key="`${entry.seriesId}:${entry.metaId}`"
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
    <div v-if="overflowing" class="trackside-external-tooltip__overflow-hint">
      内容较多，可固定查看完整内容
    </div>
  </div>
</template>

<style scoped>
.trackside-external-tooltip {
  position: absolute;
  top: 12px;
  z-index: 20;
  display: flex;
  width: clamp(320px, 26vw, 440px);
  min-width: min(300px, calc(100% - 24px));
  max-width: calc(100% - 24px);
  flex-direction: column;
  overflow: hidden;
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
.trackside-external-tooltip__header {
  display: flex;
  min-height: 36px;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--nc-border-light);
  color: var(--nc-text-secondary);
}
.trackside-external-tooltip__pin {
  flex: none;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: var(--nc-primary);
  cursor: pointer;
  font: inherit;
}
.trackside-external-tooltip__body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 10px 12px;
}
.trackside-external-tooltip__overflow-hint {
  flex: none;
  padding: 6px 12px;
  border-top: 1px solid var(--nc-border-light);
  background: linear-gradient(to bottom, color-mix(in srgb, var(--nc-bg-elevated) 72%, transparent), var(--nc-bg-elevated));
  color: var(--nc-text-secondary);
}
.trackside-tooltip-entry { break-inside: avoid; }
.trackside-tooltip-entry + .trackside-tooltip-entry { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--nc-border-light); }
.trackside-tooltip-entry__role { font-weight: 700; }
.trackside-tooltip-entry__role.is-active { color: var(--nc-success); }
.trackside-tooltip-entry__role.is-standby { color: var(--nc-text-secondary); }
.trackside-tooltip-entry__marker { display: inline-block; width: 1em; }
.trackside-tooltip-entry__ap { margin-top: 2px; font-weight: 600; }
</style>
