<script setup lang="ts">
defineProps<{
  modelValue: string
  disabled?: boolean
  testable?: boolean
  loading?: boolean
  error?: string
  success?: string
  placeholder?: string
  selectTestId?: string
  clearTestId?: string
  testTestId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: []
  clear: []
  test: []
}>()

function clear(): void {
  emit('update:modelValue', '')
  emit('clear')
}
</script>

<template>
  <div class="nc-executable-path-field">
    <el-input
      class="nc-executable-path-field__input"
      :model-value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :aria-invalid="Boolean(error)"
      readonly
      @update:model-value="emit('update:modelValue', $event)"
    />
    <div class="nc-executable-path-field__actions">
      <el-button :data-testid="selectTestId" :disabled="disabled" @click="emit('select')">选择</el-button>
      <el-button :data-testid="clearTestId" :disabled="disabled || !modelValue" @click="clear">清空</el-button>
      <el-button v-if="testable" :data-testid="testTestId" :disabled="disabled || !modelValue" :loading="loading" @click="emit('test')">试启动</el-button>
    </div>
    <div class="nc-executable-path-field__feedback" aria-live="polite">
      <span v-if="error" class="nc-executable-path-field__error">{{ error }}</span>
      <span v-else-if="success" class="nc-executable-path-field__success">{{ success }}</span>
    </div>
  </div>
</template>

<style scoped>
.nc-executable-path-field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  width: 100%;
  gap: 6px 8px;
}
.nc-executable-path-field__input { min-width: 0; }
.nc-executable-path-field__actions {
  display: inline-flex;
  align-items: stretch;
  flex: none;
  gap: 6px;
  white-space: nowrap;
}
.nc-executable-path-field__actions :deep(.el-button) {
  min-width: 64px;
  margin-left: 0;
}
.nc-executable-path-field__feedback {
  grid-column: 1 / -1;
  min-height: 20px;
  font-size: 12px;
  line-height: 20px;
}
.nc-executable-path-field__error { color: var(--el-color-danger); }
.nc-executable-path-field__success { color: var(--el-color-success); }
@media (max-width: 900px) {
  .nc-executable-path-field { grid-template-columns: 1fr; }
  .nc-executable-path-field__actions { justify-content: flex-end; }
  .nc-executable-path-field__feedback { grid-column: 1; }
}
</style>
