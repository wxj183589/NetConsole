<script setup lang="ts">
import type { MeshAnalysisParams } from '../../types/meshAnalysis'
import { meshBusinessText as mt } from '../../i18n/meshBusiness'
defineProps<{ params: MeshAnalysisParams }>()
</script>

<template>
  <div class="mesh-business-params">
    <el-form-item :label="mt('good_threshold')"><el-input-number v-model="params.rssi_good_threshold" :min="1" :max="200" clearable /></el-form-item>
    <el-form-item :label="mt('warning_threshold')"><el-input-number v-model="params.rssi_warning_threshold" :min="1" :max="200" clearable /></el-form-item>
    <el-form-item :label="mt('backup_threshold')"><el-input-number v-model="params.backup_available_threshold" :min="1" :max="200" clearable /></el-form-item>
    <el-form-item :label="mt('minimum')"><el-input-number v-model="params.ap_minimum_samples" :min="2" :max="10000" /></el-form-item>
  </div>
  <p class="hint">{{ mt('inherit') }}</p>
</template>

<style scoped>
.mesh-business-params { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
