<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { getTaskLogs } from '../../api/tasks'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import type { TaskLogLine } from '../../types/task'

const props = defineProps<{ initialTaskId: string }>()
const taskId = ref(props.initialTaskId)
const loadedId = ref('')
const level = ref('')
const keyword = ref('')
const error = ref('')
const loading = ref(false)
const logs = ref<TaskLogLine[]>([])
const selected = ref<TaskLogLine>()
let request = 0

const columns: NcTableColumn<TaskLogLine>[] = [
  { key: 'time', label: '时间', valueType: 'datetime' },
  { key: 'level', label: '级别', valueType: 'status' },
  { key: 'source', label: '来源', valueType: 'text' },
  { key: 'message', label: '消息', valueType: 'description', alignmentReason: 'long-text' },
]
const visible = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return logs.value.filter((line) =>
    (!level.value || line.level.toUpperCase() === level.value) &&
    (!query || [line.source, line.type, line.message].some((value) => value.toLowerCase().includes(query))),
  )
})

async function load(): Promise<void> {
  const id = taskId.value.trim()
  const current = ++request
  logs.value = []
  selected.value = undefined
  loadedId.value = ''
  error.value = ''
  loading.value = Boolean(id)
  if (!id) return
  try {
    const result = await getTaskLogs(id)
    if (current !== request) return
    logs.value = result.lines
    loadedId.value = id
  } catch (cause) {
    if (current === request) error.value = cause instanceof Error ? cause.message : '读取任务日志失败'
  } finally {
    if (current === request) loading.value = false
  }
}

watch(() => props.initialTaskId, (id) => {
  taskId.value = id
  void load()
})
onMounted(load)
</script>

<template>
  <section class="task-logs">
    <div class="filters">
      <el-input v-model="taskId" aria-label="任务 ID" placeholder="任务 ID" clearable maxlength="200" @keyup.enter="load" />
      <el-button type="primary" :loading="loading" :disabled="!taskId.trim()" @click="load">查询</el-button>
      <el-select v-model="level" aria-label="日志级别" placeholder="全部级别" clearable>
        <el-option label="信息" value="INFO" />
        <el-option label="警告" value="WARNING" />
        <el-option label="错误" value="ERROR" />
        <el-option label="调试" value="DEBUG" />
      </el-select>
      <el-input v-model="keyword" aria-label="筛选任务日志" placeholder="筛选消息或来源" clearable />
      <RouterLink v-if="loadedId" :to="{ name: 'tasks', query: { task_id: loadedId } }">查看任务</RouterLink>
    </div>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <div class="table-host">
      <NcDataTable
        v-loading="loading" :data="visible" :columns="columns" table-id="system-task-log-entries"
        route-key="/logs" height="100%" :empty-text="loadedId ? '暂无匹配记录' : '请输入任务 ID'"
        highlight-current-row @row-click="selected = $event"
      />
    </div>
    <pre v-if="selected" class="details">{{ selected.message }}<template v-if="selected.details && Object.keys(selected.details).length">{{ '\n\n' + JSON.stringify(selected.details, null, 2) }}</template></pre>
  </section>
</template>

<style scoped>
.task-logs { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: 12px; }
.filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.filters .el-input { width: min(280px, 100%); }
.filters .el-select { width: 125px; }
.table-host { flex: 1; min-height: 0; }
.details { max-height: 30%; margin: 0; padding: 10px; overflow: auto; background: var(--el-fill-color-light); white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
