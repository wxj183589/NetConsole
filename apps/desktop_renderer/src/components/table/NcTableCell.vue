<script setup lang="ts">
import { computed } from 'vue'

import { displayTableValue, type NcTableAlignment } from './NcTableColumn'
import NcOverflowTooltip from './NcOverflowTooltip.vue'

const props = withDefaults(defineProps<{
  value: unknown
  align?: NcTableAlignment
  tooltip?: boolean
}>(), {
  align: 'center',
  tooltip: true,
})

const text = computed(() => displayTableValue(props.value))
</script>

<template>
  <NcOverflowTooltip :text="text" :enabled="tooltip">
    <span :class="`nc-table-cell nc-table-cell--${align}`">{{ text }}</span>
  </NcOverflowTooltip>
</template>

<style scoped>
.nc-table-cell { display: block; min-width: 0; }
.nc-table-cell--left { text-align: left; }
.nc-table-cell--center { text-align: center; }
.nc-table-cell--right { text-align: right; }
</style>
