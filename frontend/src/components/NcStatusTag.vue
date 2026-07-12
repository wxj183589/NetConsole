<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const labels: Record<string, string> = {
  ONLINE: '在线', OFFLINE: '离线', UNAUTHORIZED: '认证失败', UNKNOWN: '未检查', DISABLED: '已禁用',
  PENDING: '等待中', STARTING: '启动中', RUNNING: '运行中', STOPPING: '停止中', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消',
}
const types: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = {
  ONLINE: 'success', COMPLETED: 'success', RUNNING: 'primary', STARTING: 'primary',
  OFFLINE: 'danger', FAILED: 'danger', UNAUTHORIZED: 'warning', STOPPING: 'warning',
  UNKNOWN: 'info', DISABLED: 'info', PENDING: 'info', CANCELLED: 'info',
}
const label = computed(() => labels[props.status] || props.status)
const type = computed(() => types[props.status] || 'info')
</script>

<template>
  <el-tag :type="type" effect="light" round>{{ label }}</el-tag>
</template>
