<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'

import { activateSite, applySiteCleanup, auditSite, createSite, exportSite, getDataRoot, getLatestSiteAudit, importSite, inspectSitePackage, listSites, migrateDataRoot, migrateSite, prepareSiteCleanup, rebuildDemoSite, validateDataRoot, type DataRootSnapshot, type SiteConflictChoice, type SiteConflictResolution, type SitePackageInspection, type SitePackageType, type SiteRecord } from '../../api/siteStorage'
import { getPlatformAdapter } from '../../platform/runtime'
import { getTask } from '../../api/tasks'
import { useConfirm } from '../../components/feedback/useConfirm'

defineProps<{ focused?: boolean }>()

const sites = ref<SiteRecord[]>([])
const root = ref<DataRootSnapshot | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const importDialogVisible = ref(false)
const importInspection = ref<SitePackageInspection | null>(null)
const importPackagePath = ref('')
const importMode = ref<'new' | 'replace' | 'merge'>('new')
const importSiteId = ref('')
const importDisplayName = ref('')
const importTargetSiteId = ref('')
const importRawOnly = ref(false)
const conflictChoices = ref<Record<string, { choice: SiteConflictChoice; manualValue: string }>>({})
const desktopOnly = getPlatformAdapter().hostType === 'electron'
const { confirm: confirmAction } = useConfirm()

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
  if (site.active || !(await confirmAction({ type: 'WARNING', title: '切换当前局点', message: `切换到“${site.display_name}”并重启本地 Backend？`, confirmText: '确认切换局点' }))) return
  busy.value = true
  try {
    await activateSite(site.site_id)
    const result = await getPlatformAdapter().restartBackend({ activeSiteId: site.site_id })
    if (!result.success) throw new Error(result.error || 'Backend 重启失败')
    ElMessage.success('局点已切换')
  } catch (cause) { showError(cause, '局点切换失败') }
  finally { busy.value = false }
}

async function auditSelectedSite(site: SiteRecord): Promise<void> {
  busy.value = true
  try {
    const task = await auditSite(site.site_id)
    await openTask(task.task_id)
    const completed = await waitForTask(task.task_id)
    if (completed !== 'COMPLETED') throw new Error(`审计任务状态：${completed}`)
    await reload()
    ElMessage.success('局点审计完成')
  } catch (cause) { showError(cause, '局点审计失败') }
  finally { busy.value = false }
}

async function showAudit(site: SiteRecord): Promise<void> {
  try {
    const audit = await getLatestSiteAudit(site.site_id)
    await ElMessageBox.alert([
      `分类：${classificationLabel(audit.classification)}`,
      `文件：${audit.file_count} 个，目录：${audit.directory_count} 个`,
      `任务：${audit.task_count}，原始日志：${audit.raw_log_count}`,
      `解析库：${audit.parsed_database_count}，报告：${audit.report_count}`,
      `唯一业务数据：${audit.unique_business_data ? '有' : '无'}`,
      `建议：${actionLabel(audit.recommended_action)}`,
    ].join('\n'), `${site.display_name} 审计清单`, { confirmButtonText: '关闭' })
  } catch (cause) { showError(cause, '审计清单读取失败') }
}

async function cleanupSite(site: SiteRecord): Promise<void> {
  busy.value = true
  try {
    const plan = await prepareSiteCleanup(site.site_id)
    if (!plan.can_delete) {
      ElMessage.warning(plan.blocking_reasons.length ? `不能清理：${plan.blocking_reasons.join('、')}` : '当前局点不能安全清理')
      return
    }
    const confirmed = await confirmAction({ type: 'DANGER', title: '安全清理局点', message: `“${site.display_name}”将从 Registry 注销并移入可恢复回收区，不会永久删除。`, confirmText: '移入回收区' })
    if (!confirmed) return
    const task = await applySiteCleanup(site.site_id, plan.cleanup_token)
    await openTask(task.task_id)
    const completed = await waitForTask(task.task_id)
    if (completed !== 'COMPLETED') throw new Error(`清理任务状态：${completed}`)
    await reload()
    ElMessage.success('局点已移入可恢复回收区')
  } catch (cause) { showError(cause, '局点安全清理失败') }
  finally { busy.value = false }
}

async function rebuildDemo(site: SiteRecord): Promise<void> {
  if (site.active) { ElMessage.warning('请先切换到正式局点，再重建演示局点'); return }
  const confirmed = await confirmAction({ type: 'WARNING', title: '重建演示局点', message: '旧 Demo 将先完整移入回收区，再生成当前 Schema 的小型演示数据。', confirmText: '确认重建' })
  if (!confirmed) return
  busy.value = true
  try {
    const task = await rebuildDemoSite(false)
    await openTask(task.task_id)
    const completed = await waitForTask(task.task_id)
    if (completed !== 'COMPLETED') throw new Error(`Demo 重建任务状态：${completed}`)
    await reload()
    ElMessage.success('演示局点已重建')
  } catch (cause) { showError(cause, '演示局点重建失败') }
  finally { busy.value = false }
}

async function exportCurrent(packageType: SitePackageType): Promise<void> {
  const current = sites.value.find((site) => site.active)
  if (!current) return
  const date = new Date().toISOString().slice(0, 10).replaceAll('-', '')
  const names: Record<SitePackageType, string> = {
    full_migration: `${current.display_name}_完整迁移包_${date}.ncsite`,
    field_collection: `${current.display_name}_现场采集包_${date}.ncsite`,
    collection_return: `${current.display_name}_采集回传包_${date}.ncresult`,
  }
  const selected = await getPlatformAdapter().selectSiteExportDestination(names[packageType])
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try { const task = await exportSite(current.site_id, selected.path, packageType); await openTask(task.task_id); ElMessage.success(`${packageTypeLabel(packageType)}导出任务已提交`) }
  catch (cause) { showError(cause, '数据包导出失败') }
  finally { busy.value = false }
}

async function importPackage(): Promise<void> {
  const selected = await getPlatformAdapter().selectSitePackage()
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try {
    const inspected = await inspectSitePackage(selected.path)
    importInspection.value = inspected
    importPackagePath.value = selected.path
    importMode.value = inspected.package_type === 'collection_return' ? 'merge' : 'new'
    importSiteId.value = inspected.site_id
    importDisplayName.value = inspected.site_name
    importTargetSiteId.value = inspected.target_site_id || sites.value.find((site) => site.active)?.site_id || ''
    importRawOnly.value = false
    conflictChoices.value = Object.fromEntries(inspected.conflicts.map((item) => [item.conflict_id, { choice: 'local' as const, manualValue: '' }]))
    importDialogVisible.value = true
  } catch (cause) { showError(cause, '数据包预检失败') }
  finally { busy.value = false }
}

async function executeImport(): Promise<void> {
  const inspected = importInspection.value
  if (!inspected || !importPackagePath.value) return
  if (importMode.value === 'new' && (!importSiteId.value.trim() || !importDisplayName.value.trim())) {
    ElMessage.warning('请填写局点标识和显示名称')
    return
  }
  if (importMode.value === 'replace' && !importTargetSiteId.value) {
    ElMessage.warning('请选择要替换的局点')
    return
  }
  if (importMode.value === 'replace') {
    const target = sites.value.find((site) => site.site_id === importTargetSiteId.value)
    const confirmed = await confirmAction({ type: 'DANGER', title: '替换现有局点', message: `“${target?.display_name || importTargetSiteId.value}”将先创建完整备份，再由迁移包替换。`, confirmText: '确认替换局点' })
    if (!confirmed) return
  }
  const resolutions: SiteConflictResolution[] = inspected.conflicts.map((item) => {
    const selection = conflictChoices.value[item.conflict_id] || { choice: 'local' as const, manualValue: '' }
    return {
      conflict_id: item.conflict_id,
      choice: selection.choice,
      ...(selection.choice === 'manual' ? { manual_value: selection.manualValue } : {}),
    }
  })
  busy.value = true
  try {
    const task = await importSite({
      package_path: importPackagePath.value,
      ...(importMode.value === 'new' ? { site_id: importSiteId.value.trim(), display_name: importDisplayName.value.trim() } : {}),
      ...(importMode.value === 'replace' ? { replace_site_id: importTargetSiteId.value, display_name: importDisplayName.value.trim() } : {}),
      ...(importMode.value === 'merge' ? { site_id: inspected.target_site_id || importTargetSiteId.value, raw_only: importRawOnly.value, conflict_resolutions: resolutions } : {}),
    })
    importDialogVisible.value = false
    await openTask(task.task_id)
    ElMessage.success('数据包导入任务已提交')
  } catch (cause) { showError(cause, '数据包导入失败') }
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
  if (!root.value || root.value.data_root === root.value.default_data_root || !(await confirmAction({ type: 'DANGER', title: '恢复默认数据根', message: '迁移全部数据并恢复默认数据根？', confirmText: '确认迁移并恢复' }))) return
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
function showError(cause: unknown, fallback: string): void { error.value = cause instanceof Error && cause.message ? cause.message : fallback; ElMessage.error(error.value) }
function formatBytes(value: number): string { if (!Number.isFinite(value) || value <= 0) return '0 B'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1); return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}` }
function classificationLabel(value: string): string { return ({ active_site: '当前正式局点', normal_site: '正式局点', managed_demo: '演示局点 · 可重建', legacy_demo: '旧版 Demo 待审计', legacy_valid: 'Legacy 待审计', legacy_alias: 'Legacy 别名', legacy_duplicate: 'Legacy 重复', orphan: '孤立目录', empty_shell: '疑似迁移残留', unknown: '未审计' } as Record<string, string>)[value] || value }
function actionLabel(value: string): string { return ({ audit_required: '需要审计', safe_delete_to_recycle: '可安全移入回收区', backup_then_rebuild: '备份后重建 Demo', keep_and_review: '保留并复核' } as Record<string, string>)[value] || value }
function integrityLabel(value: SiteRecord['data_integrity']): string { return ({ ok: '正常', failed: '异常', unknown: '待审计' } as const)[value] || '待审计' }
function classificationTag(site: SiteRecord): 'success' | 'warning' | 'danger' | 'info' { const value = site.classification || 'unknown'; if (value === 'managed_demo') return 'success'; if (value === 'empty_shell') return 'danger'; if (value.startsWith('legacy')) return 'warning'; return 'info' }
function packageTypeLabel(value: SitePackageType): string { return ({ full_migration: '完整迁移包', field_collection: '现场采集包', collection_return: '采集回传包' } as const)[value] }
function displayValue(value: unknown): string { if (value === null || value === undefined || value === '') return '空'; if (typeof value === 'object') return JSON.stringify(value); return String(value) }
</script>

<template>
  <section
    v-if="desktopOnly"
    id="site-storage-management"
    class="storage-panel"
    :class="{ 'storage-panel--focused': focused }"
    v-loading="loading"
  >
    <div class="panel-heading">
      <div><h2>局点与数据管理</h2><p>局点切换、迁移和数据包合并都经过 Backend 校验与 Task Center。</p></div>
      <div v-if="root?.persistent !== false" class="actions">
        <el-button data-testid="create-site" :loading="busy" @click="newSite">新建局点</el-button>
        <el-button data-testid="import-site" :loading="busy" @click="importPackage">导入数据包</el-button>
        <el-dropdown :disabled="busy" trigger="click" @command="exportCurrent">
          <el-button data-testid="export-site" type="primary" :loading="busy">
            导出当前局点
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="full_migration">导出完整迁移包</el-dropdown-item>
              <el-dropdown-item command="field_collection">导出现场采集包</el-dropdown-item>
              <el-dropdown-item command="collection_return">导出采集回传包</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <el-alert v-if="root?.persistent === false" data-testid="isolated-storage-alert" title="隔离测试模式：当前数据将在退出后删除，不会写入正式 NetConsole 数据。" type="warning" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="root" class="root-summary"><span>{{ root.persistent ? '全局数据根' : '临时测试数据根' }}</span><code :title="root.persistent ? root.data_root : undefined">{{ root.data_root }}</code><span>{{ root.site_count }} 个局点</span><template v-if="root.persistent"><el-button data-testid="migrate-data-root" size="small" @click="chooseRoot">选择并迁移</el-button><el-button data-testid="restore-data-root" size="small" :disabled="root.data_root === root.default_data_root" @click="restoreDefaultRoot">恢复默认路径</el-button></template></div>
    <div class="site-list">
      <article v-for="site in sites" :key="site.site_id" class="site-item" :class="{ active: site.active }">
        <div class="site-main"><strong>{{ site.display_name }}</strong><el-tag v-if="site.active" type="success">当前</el-tag><el-tag size="small" :type="classificationTag(site)">{{ classificationLabel(site.classification || 'unknown') }}</el-tag><code>{{ site.site_id }}</code><span>{{ formatBytes(site.size_bytes) }}</span><span>完整性：{{ integrityLabel(site.data_integrity) }}</span></div>
        <div v-if="root?.persistent" class="site-actions"><el-button :data-testid="`audit-site-${site.site_id}`" size="small" :disabled="busy" @click="auditSelectedSite(site)">审计</el-button><el-button v-if="site.audited_at" :data-testid="`show-audit-${site.site_id}`" size="small" :disabled="busy" @click="showAudit(site)">查看清单</el-button><el-button v-if="site.classification === 'empty_shell'" :data-testid="`cleanup-site-${site.site_id}`" size="small" type="danger" plain :disabled="site.active || busy" @click="cleanupSite(site)">安全清理</el-button><el-button v-if="site.site_kind === 'demo'" :data-testid="`rebuild-demo-${site.site_id}`" size="small" :disabled="site.active || busy" @click="rebuildDemo(site)">重建 Demo</el-button><el-button size="small" :disabled="site.active || busy" @click="switchSite(site)">{{ site.active ? '当前局点' : '切换' }}</el-button><el-button v-if="site.active" size="small" @click="openCurrentSite">打开目录</el-button><el-button v-if="site.active" size="small" :disabled="busy" @click="moveCurrentSite">迁移局点</el-button></div>
      </article>
    </div>
    <el-dialog v-model="importDialogVisible" class="site-import-dialog" width="min(920px, 94vw)" :close-on-click-modal="false" title="数据包导入预检">
      <template v-if="importInspection">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="目标局点">{{ importInspection.site_name }}</el-descriptions-item>
          <el-descriptions-item label="包类型">{{ packageTypeLabel(importInspection.package_type) }}</el-descriptions-item>
          <el-descriptions-item label="局点 UUID"><code>{{ importInspection.site_uuid || '旧版包未提供' }}</code></el-descriptions-item>
          <el-descriptions-item label="版本">基准 {{ importInspection.base_revision }}<template v-if="importInspection.local_revision !== undefined"> / 本地 {{ importInspection.local_revision }}</template></el-descriptions-item>
        </el-descriptions>

        <div v-if="importInspection.package_type === 'collection_return'" class="preflight-grid">
          <span><strong>{{ importInspection.new_files || 0 }}</strong> 新增文件</span>
          <span><strong>{{ importInspection.new_tasks || 0 }}</strong> 新增任务</span>
          <span><strong>{{ importInspection.updated_records || 0 }}</strong> 自动更新</span>
          <span><strong>{{ importInspection.duplicate_files || 0 }}</strong> 重复文件</span>
          <span :class="{ danger: importInspection.conflict_count > 0 }"><strong>{{ importInspection.conflict_count }}</strong> 冲突</span>
          <span :class="{ danger: importInspection.invalid_count > 0 }"><strong>{{ importInspection.invalid_count }}</strong> 无效数据</span>
          <span><strong>{{ importInspection.deletion_requests || 0 }}</strong> 删除请求</span>
          <span><strong>{{ formatBytes(importInspection.estimated_additional_bytes) }}</strong> 预计空间</span>
        </div>

        <div v-if="importInspection.package_type !== 'collection_return'" class="import-options">
          <el-radio-group v-model="importMode">
            <el-radio-button value="new">恢复为新局点</el-radio-button>
            <el-radio-button value="replace">替换现有局点</el-radio-button>
          </el-radio-group>
          <el-form label-position="top">
            <template v-if="importMode === 'new'">
              <el-form-item label="局点标识"><el-input v-model="importSiteId" /></el-form-item>
              <el-form-item label="显示名称"><el-input v-model="importDisplayName" /></el-form-item>
            </template>
            <template v-else>
              <el-form-item label="替换目标">
                <el-select v-model="importTargetSiteId" class="full-width">
                  <el-option v-for="site in sites" :key="site.site_id" :label="site.display_name" :value="site.site_id" />
                </el-select>
              </el-form-item>
              <el-form-item label="导入后显示名称"><el-input v-model="importDisplayName" /></el-form-item>
            </template>
          </el-form>
        </div>

        <template v-else>
          <el-alert title="导入前自动创建恢复快照；原始文件按 SHA-256 追加；删除请求不会自动执行。" type="info" :closable="false" show-icon />
          <el-checkbox v-model="importRawOnly" class="raw-only-option">仅导入原始采集数据</el-checkbox>
          <div v-if="importInspection.conflicts.length" class="conflict-section">
            <div class="section-heading"><strong>冲突处理</strong><span>默认保留本地值，可逐项选择回传值或手工填写。</span></div>
            <div class="conflict-table-wrap">
              <el-table :data="importInspection.conflicts" size="small" max-height="320">
                <el-table-column label="对象" min-width="150"><template #default="{ row }">{{ row.entity_type }} / {{ row.entity_id }}</template></el-table-column>
                <el-table-column prop="field" label="字段" min-width="120" />
                <el-table-column label="基准值" min-width="150"><template #default="{ row }">{{ displayValue(row.base_value) }}</template></el-table-column>
                <el-table-column label="本地值" min-width="150"><template #default="{ row }">{{ displayValue(row.local_value) }}</template></el-table-column>
                <el-table-column label="回传值" min-width="150"><template #default="{ row }">{{ displayValue(row.returned_value) }}</template></el-table-column>
                <el-table-column label="处理" width="180" fixed="right">
                  <template #default="{ row }">
                    <el-select v-model="conflictChoices[row.conflict_id].choice" size="small">
                      <el-option label="使用本地值" value="local" />
                      <el-option label="使用回传值" value="returned" />
                      <el-option label="手工填写" value="manual" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="手工值" min-width="160" fixed="right">
                  <template #default="{ row }">
                    <el-input v-if="conflictChoices[row.conflict_id].choice === 'manual'" v-model="conflictChoices[row.conflict_id].manualValue" size="small" />
                    <span v-else>不适用</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </template>
      </template>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="!importInspection?.can_import" @click="executeImport">导入并合并</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.el-alert{margin-top:14px}
.storage-panel{padding:18px 20px;scroll-margin-top:16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px;transition:outline-color .18s ease,box-shadow .18s ease}.storage-panel--focused{outline:1px solid var(--nc-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--nc-primary),transparent 82%)}.panel-heading,.actions,.root-summary,.site-item,.site-main,.site-actions{display:flex;align-items:center;gap:10px}.panel-heading{justify-content:space-between;gap:18px}.panel-heading h2{margin:0 0 5px;font-size:17px}.panel-heading p{margin:0;color:var(--nc-text-secondary);font-size:13px}.actions,.site-actions{flex-wrap:wrap;justify-content:flex-end}.root-summary{margin:16px 0;padding:10px 12px;background:var(--nc-surface-muted);border-radius:6px;flex-wrap:wrap}.root-summary code{flex:1;min-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.site-list{display:grid;gap:8px}.site-item{justify-content:space-between;padding:11px 12px;border:1px solid var(--el-border-color-lighter);border-radius:6px}.site-item.active{border-color:var(--el-color-success-light-5);background:var(--el-color-success-light-9)}.site-main{min-width:0;flex-wrap:wrap}.site-main strong{font-size:14px}.site-main code{color:var(--nc-text-secondary)}.site-main span{color:var(--nc-text-secondary);font-size:12px}.preflight-grid{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;margin:14px 0}.preflight-grid span{padding:9px 10px;background:var(--nc-surface-muted);border-radius:6px;color:var(--nc-text-secondary);font-size:12px}.preflight-grid strong{display:block;margin-bottom:2px;color:var(--nc-text-primary);font-size:16px}.preflight-grid .danger strong{color:var(--el-color-danger)}.import-options{display:grid;gap:14px;margin-top:16px}.import-options :deep(.el-form){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.import-options :deep(.el-form-item){margin-bottom:0}.full-width{width:100%}.raw-only-option{margin:14px 0}.conflict-section{margin-top:4px}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:8px}.section-heading span{color:var(--nc-text-secondary);font-size:12px}.conflict-table-wrap{width:100%;overflow-x:auto}.conflict-table-wrap :deep(.el-table){min-width:980px}.site-import-dialog code{overflow-wrap:anywhere}@media(max-width:900px){.panel-heading{align-items:flex-start;flex-direction:column}.actions{justify-content:flex-start}.site-item{align-items:flex-start;flex-direction:column}.site-actions{justify-content:flex-start}.preflight-grid{grid-template-columns:repeat(2,minmax(110px,1fr))}.import-options :deep(.el-form){grid-template-columns:1fr}.section-heading{align-items:flex-start;flex-direction:column}}
</style>
