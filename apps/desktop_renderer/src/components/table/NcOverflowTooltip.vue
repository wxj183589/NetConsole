<script setup lang="ts">
import { nextTick, ref } from 'vue'

withDefaults(defineProps<{
  text: string
  enabled?: boolean
}>(), {
  enabled: true,
})

const contentRef = ref<HTMLElement>()
const overflowing = ref(false)

async function checkOverflow(): Promise<void> {
  await nextTick()
  const element = contentRef.value
  overflowing.value = Boolean(element && element.scrollWidth > element.clientWidth + 1)
}
</script>

<template>
  <el-tooltip :content="text" :disabled="!enabled || !overflowing" placement="top" :show-after="300">
    <span ref="contentRef" class="nc-overflow-tooltip" @mouseenter="checkOverflow">
      <slot>{{ text }}</slot>
    </span>
  </el-tooltip>
</template>

<style scoped>
.nc-overflow-tooltip {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
