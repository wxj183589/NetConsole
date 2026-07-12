<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, View } from '@element-plus/icons-vue'

import NcStatusTag from '../components/NcStatusTag.vue'
import { useTaskStore } from '../stores/tasks'
import type { TaskItem, TaskStatus } from '../types/task'
import { taskStatusLabel } from '../utils/taskStatus'

const store = useTaskStore()
const filter = ref<TaskStatus | ''>('')
const drawerVisible = ref(false)
const visibleTasks = computed(() => (filter.value ? store.tasks.filter((task) => task.status === filter.value) : store.tasks))

const statusOptions: TaskStatus[] = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED']

onMounted(async () => {
  await store.refresh()
  store.connectSocket()
})

onBeforeUnmount(() => store.disconnectSocket())

async function openDetail(task: TaskItem): Promise<void> {
  try {
    await store.selectTask(task.id)
    drawerVisible.value = true
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '任务详情加载失败')
  }
}

async function cancel(task: TaskItem): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认停止任务“${task.name}”吗？`, '停止任务', { type: 'warning' })
    await store.requestCancel(task.id)
    ElMessage.success('已提交停止请求')
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '停止任务失败')
  }
}

function eventMessage(payload: Record<string, unknown>): string {
  return String(payload.message || payload.error || payload.state || JSON.stringify(payload))
}

function formatTime(value: string): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}
</script>

<template>
  <section class="task-center">
    <div class="metric-grid">
      <div class="metric-card"><span>任务总数</span><strong>{{ store.tasks.length }}</strong></div>
      <div class="metric-card active"><span>运行任务</span><strong>{{ store.runningCount }}</strong></div>
      <div class="metric-card success"><span>已完成</span><strong>{{ store.completedCount }}</strong></div>
      <div class="metric-card danger"><span>失败任务</span><strong>{{ store.failedCount }}</strong></div>
    </div>

    <div class="content-card">
      <div class="table-toolbar">
        <div>
          <h2>任务列表</h2>
          <p><span :class="['status-dot', store.socketConnected ? 'online' : 'offline']"></span>{{ store.socketConnected ? '实时事件已连接' : '实时事件重连中' }}</p>
        </div>
        <div class="toolbar-actions">
          <el-select v-model="filter" placeholder="全部状态" clearable style="width: 160px">
            <el-option v-for="status in statusOptions" :key="status" :label="taskStatusLabel(status)" :value="status" />
          </el-select>
          <el-button :icon="Refresh" :loading="store.loading" @click="store.refresh">刷新</el-button>
        </div>
      </div>

      <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" />
      <el-table v-loading="store.loading" :data="visibleTasks" empty-text="暂无任务记录" stripe>
        <el-table-column prop="name" label="任务" min-width="190">
          <template #default="{ row }"><strong>{{ row.name }}</strong><small class="secondary-text">{{ row.type }}</small></template>
        </el-table-column>
        <el-table-column label="状态" width="104"><template #default="{ row }"><NcStatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }"><el-progress :percentage="row.progress" :stroke-width="8" :show-text="true" /></template>
        </el-table-column>
        <el-table-column prop="device" label="设备" min-width="130" show-overflow-tooltip />
        <el-table-column prop="owner" label="所有者" width="100" />
        <el-table-column label="更新时间" width="176"><template #default="{ row }">{{ formatTime(row.updated_time) }}</template></el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button>
            <el-button v-if="row.cancellable" link type="danger" @click="cancel(row)">停止</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" title="任务详情" size="min(720px, 92vw)">
      <template v-if="store.selected">
        <div class="detail-heading">
          <div><h2>{{ store.selected.name }}</h2><p>{{ store.selected.id }}</p></div>
          <NcStatusTag :status="store.selected.status" />
        </div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务类型">{{ store.selected.type }}</el-descriptions-item>
          <el-descriptions-item label="进度">{{ store.selected.progress }}%</el-descriptions-item>
          <el-descriptions-item label="设备">{{ store.selected.device || '--' }}</el-descriptions-item>
          <el-descriptions-item label="Agent">{{ store.selected.agent || '--' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(store.selected.created_time) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(store.selected.finished_time) }}</el-descriptions-item>
          <el-descriptions-item label="结果路径" :span="2">{{ store.selected.result_path || '--' }}</el-descriptions-item>
          <el-descriptions-item label="错误信息" :span="2">{{ store.selected.error_message || '--' }}</el-descriptions-item>
        </el-descriptions>
        <div class="event-header"><h3>任务事件与日志</h3><span>{{ store.events.length }} 条</span></div>
        <div class="event-log">
          <div v-for="event in store.events" :key="event.id" class="event-row">
            <time>{{ formatTime(event.time) }}</time><span class="event-type">{{ event.type }}</span><span>{{ eventMessage(event.payload) }}</span>
          </div>
          <el-empty v-if="!store.events.length" description="暂无事件" :image-size="72" />
        </div>
      </template>
    </el-drawer>
  </section>
</template>
