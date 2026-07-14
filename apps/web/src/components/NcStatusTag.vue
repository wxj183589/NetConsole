<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const labels: Record<string, string> = {
  ONLINE: '在线', OFFLINE: '离线', UNAUTHORIZED: '认证失败', UNKNOWN: '未检查', DISABLED: '已禁用',
  PENDING: '等待中', STARTING: '启动中', RUNNING: '运行中', STOPPING: '停止中', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消',
  QUEUED: '排队中', WARNING: '有告警',
  CREATED: '已创建', CONNECTING: '连接中', INITIALIZING: '初始化', COLLECTING: '采集中', RECONNECTING: '重连中',
  STOPPED: '已停止', FORCED_STOPPED: '已强停', ABORTED: '已中止',
  STOPPED_WITH_WARNINGS: '已停止，有告警',
}
const types: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = {
  ONLINE: 'success', COMPLETED: 'success', RUNNING: 'success', STARTING: 'primary',
  OFFLINE: 'danger', FAILED: 'danger', UNAUTHORIZED: 'warning', STOPPING: 'warning',
  UNKNOWN: 'info', DISABLED: 'info', PENDING: 'info', CANCELLED: 'info', QUEUED: 'primary', WARNING: 'warning',
  CREATED: 'info', CONNECTING: 'primary', INITIALIZING: 'primary', COLLECTING: 'success', RECONNECTING: 'warning',
  STOPPED: 'success', FORCED_STOPPED: 'warning', ABORTED: 'info',
  STOPPED_WITH_WARNINGS: 'warning',
}
const label = computed(() => labels[props.status] || '未知')
const type = computed(() => types[props.status] || 'info')
</script>

<template>
  <el-tag :type="type" effect="light" round>{{ label }}</el-tag>
</template>
