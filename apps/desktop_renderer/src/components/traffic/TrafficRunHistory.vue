<script setup lang="ts">
import { computed, ref } from 'vue'

import NcStatusTag from '../NcStatusTag.vue'
import NcDataTable from '../table/NcDataTable.vue'
import NcMultiValueFilter from '../table/NcMultiValueFilter.vue'
import type { NcTableColumn } from '../table/NcTableColumn'
import type { TrafficRun } from '../../types/traffic'

const props = defineProps<{ runs: TrafficRun[]; loading: boolean }>()
defineEmits<{ select: [run: TrafficRun]; cancel: [run: TrafficRun]; retry: [run: TrafficRun]; task: [run: TrafficRun] }>()
const testTypes = ref<string[]>([])
const statuses = ref<string[]>([])
const testTypeOptions = ['IPERF_SERVER', 'IPERF_CLIENT', 'HIGH_FREQUENCY_PING', 'TCP_PORT_TEST']
const statusOptions = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED']
const testTypeLabels: Record<string, string> = {
  IPERF_SERVER: 'iPerf 服务端',
  IPERF_CLIENT: 'iPerf 客户端',
  HIGH_FREQUENCY_PING: '高频 Ping',
  TCP_PORT_TEST: 'TCP 端口测试',
}
const visibleRuns = computed(() => props.runs.filter((run) => (
  (!testTypes.value.length || testTypes.value.includes(run.test_type))
  && (!statuses.value.length || statuses.value.includes(run.status))
)))
const columns: NcTableColumn<TrafficRun>[] = [
  { key: 'task', label: '任务', valueType: 'name', fixed: 'left' },
  { key: 'executor', label: '执行端', valueType: 'name', displayValue: executorLabel },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'updated_at', label: '更新时间', valueType: 'datetime', displayValue: (row) => formatTime(row.updated_at) },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['详情', '任务中心', '停止', '重试'] },
]

function typeLabel(value: string): string {
  return testTypeLabels[value] || value
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
    <NcMultiValueFilter v-model="testTypes" :options="testTypeOptions" :labels="testTypeLabels" placeholder="全部测试类型" style="width: 170px" />
    <NcMultiValueFilter v-model="statuses" :options="statusOptions" placeholder="全部任务状态" style="width: 150px" />
  </div>
  <NcDataTable v-loading="loading" table-id="traffic-run-history" route-key="/network-tools/traffic" :data="visibleRuns" :columns="columns" empty-text="暂无流量测试记录">
    <template #cell-task="{ row }">
        <strong>{{ typeLabel(row.test_type) }}</strong>
        <small class="secondary-text">{{ row.traffic_run_id }}</small>
    </template>
    <template #cell-status="{ row }"><NcStatusTag :status="row.status" /></template>
    <template #cell-actions="{ row }">
        <el-button link type="primary" @click="$emit('select', row)">详情</el-button>
        <el-button link @click="$emit('task', row)">任务中心</el-button>
        <el-button v-if="row.cancellable" link type="danger" @click="$emit('cancel', row)">停止</el-button>
        <el-button v-else link @click="$emit('retry', row)">重试</el-button>
    </template>
  </NcDataTable>
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
