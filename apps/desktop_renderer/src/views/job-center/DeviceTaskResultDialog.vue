<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { getDeviceTaskResult, retryDeviceTask, type DeviceExecution } from '../../api/deviceOperations'
import { isFeatureEnabled } from '../../features'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{ taskId: string }>()
const emit = defineEmits<{ submitted: [id: string] }>()
const labels = { success: '成功', failed: '失败', partial: '部分成功', skipped: '已跳过' }
const commandLabels: Record<string, string> = { success: '成功', unavailable: '未取得回显' }
const items = ref<DeviceExecution[]>([])
const error = ref('')
const busy = ref(false)
const usesSavedTemplate = ref(false)
const hasRetry = computed(() => !usesSavedTemplate.value && items.value.some((item) => ['partial', 'failed'].includes(item.status)))
let loadGeneration = 0

async function load(): Promise<void> {
  const generation = ++loadGeneration
  busy.value = true
  error.value = ''
  try {
    const result = await getDeviceTaskResult(props.taskId)
    if (generation === loadGeneration) {
      items.value = result.items ?? []
      usesSavedTemplate.value = Boolean(result.template?.template_id)
    }
  } catch (cause) {
    if (generation === loadGeneration) error.value = cause instanceof Error ? cause.message : '读取执行结果失败'
  } finally {
    if (generation === loadGeneration) busy.value = false
  }
}

async function retry(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const result = await retryDeviceTask(props.taskId)
    open.value = false
    emit('submitted', result.task_id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务重试失败'
  } finally {
    busy.value = false
  }
}

watch([open, () => props.taskId], ([visible, id]) => {
  loadGeneration += 1
  busy.value = false
  error.value = ''
  items.value = []
  usesSavedTemplate.value = false
  if (visible && id) void load()
}, { immediate: true })
</script>

<template>
  <el-dialog v-model="open" title="逐设备结果" width="min(880px, 94vw)">
    <div v-loading="busy" class="results">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-empty v-else-if="!items.length && !busy" description="暂无设备执行结果" />
      <el-collapse v-else>
        <el-collapse-item
          v-for="item in items" :key="item.device_uuid" :name="item.device_uuid"
          :title="`${item.device_name || item.device_uuid} · ${labels[item.status]}`"
        >
          <p v-if="item.message || item.warning_message">{{ item.message || item.warning_message }}</p>
          <dl>
            <dt>设备 UUID</dt><dd>{{ item.device_uuid }}</dd>
            <dt>开始时间</dt><dd>{{ item.started_at }}</dd>
            <dt>完成时间</dt><dd>{{ item.finished_at }}</dd>
            <template v-if="item.software_version"><dt>软件版本</dt><dd>{{ item.software_version }}</dd></template>
            <template v-if="item.device_model"><dt>设备型号</dt><dd>{{ item.device_model }}</dd></template>
            <template v-if="item.collect_run_uuid"><dt>采集 ID</dt><dd>{{ item.collect_run_uuid }}</dd></template>
            <template v-if="item.snapshot_ids?.length"><dt>配置快照</dt><dd>{{ item.snapshot_ids.join('、') }}</dd></template>
            <template v-if="item.record_count !== undefined"><dt>采集记录</dt><dd>{{ item.record_count }}</dd></template>
          </dl>
          <template v-for="line in item.command_results" :key="line.command">
            <h4>{{ line.command }} · {{ commandLabels[line.status] || line.status }}</h4>
            <pre v-if="line.output">{{ line.output }}</pre>
          </template>
          <pre v-if="item.records?.length">{{ JSON.stringify(item.records, null, 2) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </div>
    <template #footer>
      <div class="actions">
        <RouterLink v-if="isFeatureEnabled('module.logs')" :to="{ name: 'logs', query: { tab: 'task-logs', task_id: taskId } }" @click="open = false">任务日志</RouterLink>
        <el-button @click="load">刷新结果</el-button>
        <el-button v-if="hasRetry && isFeatureEnabled('module.devices')" type="primary" :loading="busy" @click="retry">重试失败设备</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.results { max-height: 58vh; overflow: auto; }
dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; }
dd { margin: 0; overflow-wrap: anywhere; }
h4 { margin-bottom: 4px; }
pre { max-height: 240px; padding: 8px; overflow: auto; background: var(--el-fill-color-light); white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; }
</style>
