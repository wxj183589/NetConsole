<script setup lang="ts">
import { computed, ref } from 'vue'

import NcStatusTag from '../NcStatusTag.vue'
import type { TrafficRun } from '../../types/traffic'

const props = defineProps<{ runs: TrafficRun[]; loading: boolean }>()
defineEmits<{ select: [run: TrafficRun]; cancel: [run: TrafficRun]; retry: [run: TrafficRun]; task: [run: TrafficRun] }>()
const testType = ref('')
const status = ref('')
const visibleRuns = computed(() => props.runs.filter((run) => (
  (!testType.value || run.test_type === testType.value) && (!status.value || run.status === status.value)
)))

function typeLabel(value: string): string {
  return {
    IPERF_SERVER: 'iPerf 服务端',
    IPERF_CLIENT: 'iPerf 客户端',
    HIGH_FREQUENCY_PING: '高频 Ping',
  }[value] || value
}

function executorLabel(run: TrafficRun): string {
  return run.executor_kind === 'LOCAL' ? '本机' : run.agent_id || 'Agent'
}

function formatTime(value: string): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}
</script>

<template>
  <div class="history-filters">
    <el-select v-model="testType" clearable placeholder="测试类型" style="width: 170px">
      <el-option label="iPerf 服务端" value="IPERF_SERVER" />
      <el-option label="iPerf 客户端" value="IPERF_CLIENT" />
      <el-option label="高频 Ping" value="HIGH_FREQUENCY_PING" />
    </el-select>
    <el-select v-model="status" clearable placeholder="任务状态" style="width: 150px">
      <el-option v-for="value in ['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED']" :key="value" :label="value" :value="value" />
    </el-select>
  </div>
  <el-table v-loading="loading" :data="visibleRuns" empty-text="暂无流量测试记录" stripe>
    <el-table-column label="任务" min-width="180">
      <template #default="{ row }">
        <strong>{{ typeLabel(row.test_type) }}</strong>
        <small class="secondary-text">{{ row.traffic_run_id }}</small>
      </template>
    </el-table-column>
    <el-table-column label="执行端" min-width="120">
      <template #default="{ row }">{{ executorLabel(row) }}</template>
    </el-table-column>
    <el-table-column label="状态" width="104"><template #default="{ row }"><NcStatusTag :status="row.status" /></template></el-table-column>
    <el-table-column label="更新时间" width="176"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
    <el-table-column label="操作" width="250" fixed="right">
      <template #default="{ row }">
        <el-button link type="primary" @click="$emit('select', row)">详情</el-button>
        <el-button link @click="$emit('task', row)">任务中心</el-button>
        <el-button v-if="row.cancellable" link type="danger" @click="$emit('cancel', row)">停止</el-button>
        <el-button v-else link @click="$emit('retry', row)">重试</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.history-filters {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.secondary-text {
  color: var(--el-text-color-secondary);
  display: block;
  font-size: 12px;
  margin-top: 2px;
}
</style>
