<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { activateSite, createSite, exportSite, getDataRoot, importSite, inspectSitePackage, listSites, migrateDataRoot, migrateSite, validateDataRoot, type DataRootSnapshot, type SiteRecord } from '../../api/siteStorage'
import { getPlatformAdapter } from '../../platform/runtime'
import { getTask } from '../../api/tasks'

const sites = ref<SiteRecord[]>([])
const root = ref<DataRootSnapshot | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const desktopOnly = getPlatformAdapter().hostType === 'electron'

onMounted(() => { if (desktopOnly) void reload() })

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    ;[sites.value, root.value] = await Promise.all([listSites(), getDataRoot()])
  } catch (cause) { showError(cause, '局点与数据路径加载失败') }
  finally { loading.value = false }
}

async function newSite(): Promise<void> {
  const displayName = await prompt('请输入局点显示名称', '新建局点')
  if (!displayName) return
  const siteId = await prompt('请输入局点标识（小写字母、数字、-、_）', '新建局点')
  if (!siteId) return
  busy.value = true
  try { await createSite({ site_id: siteId, display_name: displayName }); ElMessage.success('局点已创建'); await reload() }
  catch (cause) { showError(cause, '局点创建失败') }
  finally { busy.value = false }
}

async function switchSite(site: SiteRecord): Promise<void> {
  if (site.active || !(await confirm(`切换到“${site.display_name}”并重启本地 Backend？`))) return
  busy.value = true
  try {
    await activateSite(site.site_id)
    const result = await getPlatformAdapter().restartBackend({ activeSiteId: site.site_id })
    if (!result.success) throw new Error(result.error || 'Backend 重启失败')
    ElMessage.success('局点已切换')
  } catch (cause) { showError(cause, '局点切换失败') }
  finally { busy.value = false }
}

async function exportCurrent(): Promise<void> {
  const current = sites.value.find((site) => site.active)
  if (!current) return
  const selected = await getPlatformAdapter().selectSiteExportDestination(`${current.site_id}.ncsite`)
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try { const task = await exportSite(current.site_id, selected.path); await openTask(task.task_id); ElMessage.success('导出任务已提交') }
  catch (cause) { showError(cause, '局点导出失败') }
  finally { busy.value = false }
}

async function importPackage(): Promise<void> {
  const selected = await getPlatformAdapter().selectSitePackage()
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try {
    const inspected = await inspectSitePackage(selected.path)
    const displayName = await prompt(`导入局点显示名称（默认：${inspected.site_name}）`, '导入局点', inspected.site_name)
    if (!displayName) return
    const siteId = await prompt(`导入局点标识（默认：${inspected.site_id}）`, '导入局点', inspected.site_id)
    if (!siteId) return
    const task = await importSite({ package_path: selected.path, site_id: siteId, display_name: displayName })
    await openTask(task.task_id); ElMessage.success('导入任务已提交')
  } catch (cause) { showError(cause, '局点导入失败') }
  finally { busy.value = false }
}

async function chooseRoot(): Promise<void> {
  const selected = await getPlatformAdapter().selectDataRootDirectory()
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try { await validateDataRoot(selected.path); const task = await migrateDataRoot(selected.path); await openTask(task.task_id); const completed = await waitForTask(task.task_id); if (completed === 'COMPLETED') { const result = await getPlatformAdapter().restartBackend({ dataRoot: selected.path }); if (!result.success) throw new Error(result.error || 'Backend 重启失败'); ElMessage.success('数据根迁移并重启完成') } else if (completed) throw new Error(`迁移任务状态：${completed}`) }
  catch (cause) { showError(cause, '数据根迁移失败') }
  finally { busy.value = false }
}

async function moveCurrentSite(): Promise<void> {
  const current = sites.value.find((site) => site.active)
  if (!current) return
  const selected = await getPlatformAdapter().selectDataRootDirectory()
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try { const task = await migrateSite(current.site_id, selected.path); await openTask(task.task_id); ElMessage.success('局点迁移任务已提交') }
  catch (cause) { showError(cause, '局点迁移失败') }
  finally { busy.value = false }
}

async function restoreDefaultRoot(): Promise<void> {
  if (!root.value || root.value.data_root === root.value.default_data_root || !(await confirm('迁移全部数据并恢复默认数据根？'))) return
  busy.value = true
  try { const task = await migrateDataRoot(root.value.default_data_root); await openTask(task.task_id); const completed = await waitForTask(task.task_id); if (completed === 'COMPLETED') { const result = await getPlatformAdapter().restartBackend({ dataRoot: root.value.default_data_root }); if (!result.success) throw new Error(result.error || 'Backend 重启失败'); ElMessage.success('默认数据根已恢复') } else if (completed) throw new Error(`迁移任务状态：${completed}`) }
  catch (cause) { showError(cause, '恢复默认数据根失败') }
  finally { busy.value = false }
}

async function openCurrentSite(): Promise<void> {
  const result = await getPlatformAdapter().executeSettingsAction('open_current_site')
  if (!result.success) showError(new Error(result.error || '打开目录失败'), '打开目录失败')
}

async function openTask(taskId: string): Promise<void> {
  const result = await getPlatformAdapter().openTaskWindow({ taskId, module: 'logs' })
  if (!result.success && result.error) ElMessage.warning(result.error)
}

async function waitForTask(taskId: string): Promise<string> {
  const deadline = Date.now() + 10 * 60_000
  while (Date.now() < deadline) {
    const task = await getTask(taskId)
    if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)) return task.status
    await new Promise((resolve) => setTimeout(resolve, 750))
  }
  throw new Error('迁移任务等待超时，请在任务中心确认状态')
}

async function prompt(message: string, title: string, inputValue = ''): Promise<string> {
  try { const result = await ElMessageBox.prompt(message, title, { inputValue, inputPattern: /.+/, inputErrorMessage: '不能为空', confirmButtonText: '确定', cancelButtonText: '取消' }); return result.value.trim() }
  catch { return '' }
}
async function confirm(message: string): Promise<boolean> { try { await ElMessageBox.confirm(message, '确认操作', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }); return true } catch { return false } }
function showError(cause: unknown, fallback: string): void { error.value = cause instanceof Error && cause.message ? cause.message : fallback; ElMessage.error(error.value) }
function formatBytes(value: number): string { if (!Number.isFinite(value) || value <= 0) return '0 B'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1); return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}` }
</script>

<template>
  <section v-if="desktopOnly" class="storage-panel" v-loading="loading">
    <div class="panel-heading"><div><h2>局点与数据管理</h2><p>局点切换、迁移和导入导出都经过 Backend 校验与 Task Center。</p></div><div class="actions"><el-button data-testid="create-site" :loading="busy" @click="newSite">新建局点</el-button><el-button data-testid="import-site" :loading="busy" @click="importPackage">导入局点</el-button><el-button data-testid="export-site" :loading="busy" type="primary" @click="exportCurrent">导出当前局点</el-button></div></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="root" class="root-summary"><span>全局数据根</span><code :title="root.data_root">{{ root.data_root }}</code><span>{{ root.site_count }} 个局点</span><el-button data-testid="migrate-data-root" size="small" @click="chooseRoot">选择并迁移</el-button><el-button data-testid="restore-data-root" size="small" :disabled="root.data_root === root.default_data_root" @click="restoreDefaultRoot">恢复默认路径</el-button></div>
    <div class="site-list">
      <article v-for="site in sites" :key="site.site_id" class="site-item" :class="{ active: site.active }">
        <div class="site-main"><strong>{{ site.display_name }}</strong><el-tag v-if="site.active" type="success">当前</el-tag><code>{{ site.site_id }}</code><span>{{ formatBytes(site.size_bytes) }}</span></div>
        <div class="site-actions"><el-button size="small" :disabled="site.active || busy" @click="switchSite(site)">{{ site.active ? '当前局点' : '切换' }}</el-button><el-button v-if="site.active" size="small" @click="openCurrentSite">打开目录</el-button><el-button v-if="site.active" size="small" :disabled="busy" @click="moveCurrentSite">迁移局点</el-button></div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.storage-panel{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.panel-heading,.actions,.root-summary,.site-item,.site-main,.site-actions{display:flex;align-items:center;gap:10px}.panel-heading{justify-content:space-between;gap:18px}.panel-heading h2{margin:0 0 5px;font-size:17px}.panel-heading p{margin:0;color:var(--nc-text-secondary);font-size:13px}.actions,.site-actions{flex-wrap:wrap;justify-content:flex-end}.root-summary{margin:16px 0;padding:10px 12px;background:var(--nc-surface-muted);border-radius:6px;flex-wrap:wrap}.root-summary code{flex:1;min-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.site-list{display:grid;gap:8px}.site-item{justify-content:space-between;padding:11px 12px;border:1px solid var(--el-border-color-lighter);border-radius:6px}.site-item.active{border-color:var(--el-color-success-light-5);background:var(--el-color-success-light-9)}.site-main{min-width:0;flex-wrap:wrap}.site-main strong{font-size:14px}.site-main code{color:var(--nc-text-secondary)}.site-main span{color:var(--nc-text-secondary);font-size:12px}@media(max-width:900px){.panel-heading{align-items:flex-start;flex-direction:column}.actions{justify-content:flex-start}.site-item{align-items:flex-start;flex-direction:column}.site-actions{justify-content:flex-start}}
</style>
