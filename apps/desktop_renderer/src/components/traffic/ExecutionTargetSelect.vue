<script setup lang="ts">
import { computed } from 'vue'

import type { TrafficExecutionTarget, TrafficTestType } from '../../types/traffic'

const props = defineProps<{
  modelValue: string
  targets: TrafficExecutionTarget[]
  testType: TrafficTestType
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const selected = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

function valueOf(target: TrafficExecutionTarget): string {
  return target.kind === 'LOCAL' ? 'LOCAL' : target.id
}

function disabledReason(target: TrafficExecutionTarget): string {
  if (!target.available) return target.unavailable_reason || '执行端不可用'
  return ''
}
</script>

<template>
  <el-select v-model="selected" filterable placeholder="选择执行端" style="width: 100%">
    <el-option
      v-for="target in targets"
      :key="valueOf(target)"
      :label="target.display_name"
      :value="valueOf(target)"
      :disabled="Boolean(disabledReason(target))"
    >
      <div class="target-option">
        <span>{{ target.display_name }}</span>
        <small v-if="disabledReason(target)">{{ disabledReason(target) }}</small>
        <small v-else>本地执行</small>
      </div>
    </el-option>
  </el-select>
</template>

<style scoped>
.target-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.target-option small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
