<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { apiRequest } from '../api/client'
import { isFeatureEnabled } from '../features'
import { activeSiteContext, siteContextState } from '../stores/siteContext'
import { formatTaskDateTime } from '../utils/dateTime'
import { taskStatusLabel } from '../utils/taskStatus'
import type { TaskItem, TaskSummary } from '../types/task'
import type { LogPage, LogEntry } from '../api/systemMaintenance'

interface Inventory { site_id: string; total: number; reachable: number; unreachable: number; error: number; unknown: number; testing: number }
interface WirelessCounts { site_id: string; online: number; offline: number; unknown: number; reported_controllers: number; updated_at: string }
const router = useRouter()
const inventory = ref<Inventory>()
const summary = ref<TaskSummary>()
const tasks = ref<TaskItem[]>()
const wireless = ref<WirelessCounts>()
const errors = ref<string[]>([])
const refresh = ref(0)
const loading = ref(false)
const showActivity = ref(false)
const activity = ref<LogEntry[]>()
const activityFailed = ref(false)
watch([showActivity, activeSiteContext, siteContextState, refresh], async ([open, site, state], _, cleanup) => {
  activity.value = undefined
  activityFailed.value = false
  if (!open || !site || state !== 'ready' || !isFeatureEnabled('module.logs')) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  const query = new URLSearchParams({site_id: site.siteId, page: '1', page_size: '50'})
  try {
    const page = await apiRequest<LogPage>('/api/system-maintenance/logs?' + query, {signal: controller.signal})
    if (!controller.signal.aborted) activity.value = page.items.filter(item => item.site_id === site.siteId).slice(0, 5)
  } catch {
    if (!controller.signal.aborted) activityFailed.value = true
  }
})
const counters = [['total','设备总数'], ['reachable','在线'], ['unreachable','离线'], ['error','连接异常'], ['unknown','暂无测试结果'], ['testing','测试中']] as const
watch([activeSiteContext, siteContextState, refresh], async ([site, state], _, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  inventory.value = undefined; tasks.value = undefined; summary.value = undefined; wireless.value = undefined
  errors.value = []
  loading.value = false
  if (!site || state !== 'ready') return
  loading.value = true
  const scope = new URLSearchParams({expected_site: site.siteId, device_only: 'true'})
  async function read<T>(label: string, url: string, accept: (data: T) => void) {
    try {
      const value = await apiRequest<T>(url, {signal: controller.signal})
      if (!controller.signal.aborted) accept(value)
    } catch {
      if (!controller.signal.aborted) errors.value.push(label)
    }
  }
  await Promise.all([
    isFeatureEnabled('module.devices') && read<Inventory>('设备状态', '/api/device-management/connection-overview', value => { if (value.site_id === site.siteId) inventory.value = value }),
    isFeatureEnabled('module.task_center') && read<TaskItem[]>('最近任务', '/api/job-center/tasks?' + scope + '&limit=6', value => { tasks.value = value }),
    isFeatureEnabled('module.task_center') && read<TaskSummary>('待处理任务', '/api/job-center/summary?' + scope, value => { summary.value = value }),
    isFeatureEnabled('module.fit_ap') && read<WirelessCounts>('无线概况', '/api/ac-management/operation-summary?expected_site=' + encodeURIComponent(site.siteId), value => { if (value.site_id === site.siteId) wireless.value = value }),
  ])
  if (!controller.signal.aborted) loading.value = false
}, { immediate: true })
</script>

<template>
  <div class="operations">
    <el-alert v-if="errors.length" type="warning" :closable="false" :title="errors.join('、') + '暂时无法读取，请刷新重试。'" />
    <section v-if="isFeatureEnabled('module.devices')" class="band">
      <header><h2>设备状态</h2><div><small>最近 1,000 次连接测试</small> <el-button text :icon="Refresh" :loading="loading" aria-label="刷新工作台" title="刷新工作台" @click="refresh++" /></div></header>
      <dl class="counts"><div v-for="[key, label] in counters" :key="key"><dt>{{ label }}</dt><dd :class="{ issue: inventory && inventory[key] > 0 && ['unreachable','error'].includes(key) }">{{ inventory?.[key] ?? '—' }}</dd></div></dl>
    </section>
    <el-button v-else :icon="Refresh" :loading="loading" @click="refresh++">刷新</el-button>
    <div class="columns">
      <section v-if="isFeatureEnabled('module.task_center')" class="band">
        <header><h2>最近设备任务</h2><el-button link type="primary" @click="router.push({name:'tasks'})">全部任务</el-button></header>
        <button v-if="summary" type="button" class="attention" @click="router.push({name:'tasks',query:{status:'attention'}})">查看待处理任务 <span>失败 {{ summary.unacknowledged_failed }} · 告警 {{ summary.unacknowledged_warning }}</span></button>
        <ul v-if="tasks?.length"><li v-for="task in tasks" :key="task.id"><button class="task" @click="router.push({name:'tasks',query:{task_id:task.id}})"><strong>{{ task.name }}</strong><span>{{ taskStatusLabel(task.status) }}</span><time>{{ formatTaskDateTime(task.updated_time) }}</time></button></li></ul>
        <p v-else>{{ tasks ? '当前局点暂无设备任务' : loading ? '正在读取任务…' : '暂无可显示的任务记录' }}</p>
      </section>
      <div class="side">
        <section class="band"><h2>常用操作</h2><div class="actions">
          <el-button v-if="isFeatureEnabled('module.devices')" @click="router.push({ name:'device-management' })">管理设备</el-button>
          <el-button v-if="isFeatureEnabled('module.task_center') && isFeatureEnabled('capability.config_collection.fetch')" @click="router.push({name:'tasks-backup'})">配置备份</el-button>
          <el-button v-if="isFeatureEnabled('module.console')" @click="router.push({name:'device-console'})">打开控制台</el-button>
          <el-button v-if="isFeatureEnabled('module.logs')" @click="router.push({name:'logs'})">查看操作日志</el-button>
        </div></section>
        <section v-if="isFeatureEnabled('module.fit_ap')" class="band"><header><h2>无线概况</h2><el-button link type="primary" @click="router.push({name:'ac-fit-aps'})">查看 AP</el-button></header>
          <dl class="counts wireless"><div><dt>在线 AP</dt><dd>{{ wireless?.reported_controllers ? wireless.online : '—' }}</dd></div><div><dt>离线 AP</dt><dd>{{ wireless?.reported_controllers ? wireless.offline : '—' }}</dd></div><div><dt>状态未知</dt><dd>{{ wireless?.reported_controllers ? wireless.unknown : '—' }}</dd></div></dl>
          <small v-if="wireless">{{ wireless.reported_controllers ? '已汇报控制器：' + wireless.reported_controllers : '当前局点暂无控制器汇总' }}</small>
        </section>
      </div>
    </div>
    <details v-if="isFeatureEnabled('module.logs')" class="activity" @toggle="showActivity = ($event.currentTarget as HTMLDetailsElement).open">
      <summary>最近局点活动</summary>
      <p v-if="activityFailed">活动记录暂时无法读取，请刷新重试。</p>
      <p v-else-if="!activity">正在读取…</p>
      <ul v-else-if="activity.length"><li v-for="(entry,index) in activity" :key="index"><time>{{ entry.time }}</time> {{ entry.display_event }}</li></ul>
      <p v-else>当前局点暂无活动记录</p>
    </details>
  </div>
</template>

<style scoped>
.operations,.side{display:grid;gap:var(--nc-space-4);min-width:0}
header,.task,.attention{display:flex;align-items:center;justify-content:space-between;gap:16px}
h1,h2,p,dl,dd,ul{margin:0} h1{font-size:24px} h2{font-size:18px}
.band{padding:var(--nc-space-5);background:var(--nc-bg-card);border:1px solid var(--nc-border-light);border-radius:var(--nc-radius-base);min-width:0}
.columns{display:grid;grid-template-columns:minmax(0,3fr) minmax(290px,2fr);gap:16px}
.counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:12px;margin-top:18px}
small,dt,time,.task span,p{color:var(--nc-text-secondary)}dd{font-size:26px;font-variant-numeric:tabular-nums;font-weight:650}.issue{color:var(--nc-danger)}
.wireless{grid-template-columns:repeat(3,minmax(0,1fr))}
ul{list-style:none;padding:0}.attention,.task{width:100%;color:inherit;font:inherit;text-align:left;border:0;cursor:pointer}.attention{padding:12px;margin:14px 0;background:var(--nc-bg-page);flex-wrap:wrap}.task{background:transparent;padding:11px 0;border-bottom:1px solid var(--nc-border-light);flex-wrap:wrap}.task strong{flex:1;overflow-wrap:anywhere}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.actions :deep(.el-button){margin:0}
.activity summary{cursor:pointer;font-weight:600}.activity li,.activity p{padding:8px 0}
@media(max-width:920px){.columns{grid-template-columns:1fr}}
</style>
