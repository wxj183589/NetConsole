<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, FolderOpened, Refresh, RefreshLeft, Select, Upload } from '@element-plus/icons-vue'

import {
  deleteDatabaseBackup,
  deleteDatabaseBackups,
  getDatabaseUpgradeSnapshot,
  openDatabaseBackupDirectory,
  organizeLegacyDatabaseArchives,
  restoreDatabaseBackup,
  startDatabaseBatchBackup,
  startDatabaseBatchUpgrade,
  startDatabaseUpgrade,
  validateDatabaseBackup,
  type DatabaseBackup,
  type DatabaseStatus,
  type DatabaseTaskReference,
  type DatabaseUpgradeSnapshot,
} from '../../api/databaseUpgrades'
import { isFeatureEnabled } from '../../features'
import { t } from '../../i18n/runtime'
import { useConfirm } from '../feedback/useConfirm'
import { getPlatformAdapter } from '../../platform/runtime'
import { getTask } from '../../api/tasks'
import type { TaskItem } from '../../types/task'

const snapshot = ref<DatabaseUpgradeSnapshot | null>(null)
const loading = ref(false)
const actionId = ref('')
const lastTask = ref<DatabaseTaskReference | null>(null)
const error = ref('')
const { confirm } = useConfirm()
const databases = computed(() => snapshot.value?.databases || [])
const backups = computed(() => snapshot.value?.backups || [])
const selectedDatabases = ref<DatabaseStatus[]>([])
const databaseTable = ref<{ clearSelection(): void; toggleAllSelection(): void } | null>(null)
const selectedProfileIds = computed(() => selectedDatabases.value.map((item) => item.mr_id).filter(Boolean))
const selectedBackups = ref<DatabaseBackup[]>([])
const backupTable = ref<{
  clearSelection(): void
  toggleAllSelection(): void
  toggleRowSelection(row: DatabaseBackup, selected?: boolean): void
} | null>(null)
const selectedBackupIds = computed(() => selectedBackups.value.map((item) => item.backup_id).filter(Boolean))
const allBackupsSelected = computed(() => backups.value.length > 0 && selectedBackupIds.value.length === backups.value.length)
const backupSelectionIndeterminate = computed(() => selectedBackupIds.value.length > 0 && !allBackupsSelected.value)
const selectedBackupBytes = computed(() => selectedBackups.value.reduce((total, item) => total + backupSize(item), 0))
const backupDeleteConfirming = ref(false)
let syncingBackupSelection = false

onMounted(() => { void reload() })

async function reload(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const nextSnapshot = await getDatabaseUpgradeSnapshot()
    snapshot.value = nextSnapshot
    await pruneBackupSelection(nextSnapshot.backups)
  }
  catch (cause) { showError(cause, t('database_upgrade.load_failed', '数据库升级状态加载失败')) }
  finally { loading.value = false }
}

async function runTask(key: string, operation: () => Promise<DatabaseTaskReference>, message: string): Promise<void> {
  actionId.value = key
  try {
    lastTask.value = await operation()
    ElMessage.success(message)
    await openTask(lastTask.value.task_id)
  } catch (cause) { showError(cause, t('database_upgrade.task_failed', '维护任务失败')) }
  finally { actionId.value = '' }
}

async function upgrade(profileId: string): Promise<void> {
  await runTask(`upgrade:${profileId}`, () => startDatabaseUpgrade(profileId), t('database_upgrade.upgrade_submitted', '数据库升级任务已提交'))
}

async function batchBackup(): Promise<void> {
  if (!selectedProfileIds.value.length) return
  await runTask('batch-backup', () => startDatabaseBatchBackup(selectedProfileIds.value), '批量数据库备份任务已提交')
}

async function batchUpgrade(): Promise<void> {
  if (!selectedProfileIds.value.length) return
  const accepted = await confirm({
    type: 'WARNING',
    title: '批量升级数据库',
    message: `将按顺序处理 ${selectedProfileIds.value.length} 个数据库；版本兼容的数据库会跳过，不兼容数据库会先自动备份再升级。是否继续？`,
    confirmText: '确认批量升级',
    closeOnEscape: false,
  })
  if (!accepted) return
  await runTask('batch-upgrade', () => startDatabaseBatchUpgrade(selectedProfileIds.value), '批量数据库升级任务已提交')
}

function onDatabaseSelectionChange(rows: DatabaseStatus[]): void { selectedDatabases.value = rows }

async function organizeLegacy(): Promise<void> {
  await runTask('organize', organizeLegacyDatabaseArchives, t('database_upgrade.organize_submitted', '历史数据库归档整理任务已提交'))
}

async function validateBackup(item: DatabaseBackup): Promise<void> {
  await runTask(`validate:${item.backup_id}`, () => validateDatabaseBackup(item.backup_id), t('database_upgrade.validate_submitted', '数据库备份验证任务已提交'))
}

async function restoreBackup(item: DatabaseBackup): Promise<void> {
  const accepted = await confirm({
    type: 'DANGER',
    title: t('database_upgrade.confirm_restore_title', '恢复数据库备份'),
    message: interpolate('database_upgrade.confirm_restore_message', '确认将“{profile}”恢复到备份 {backupId}？当前活动数据库会先创建新的安全备份。', { profile: profileLabel(item), backupId: item.backup_id }),
    detail: interpolate('database_upgrade.confirm_restore_detail', '旧版本：{version}\n备份时间：{time}\nSHA-256：{sha256}', { version: item.old_schema_version || unknownLabel(), time: formatTime(item.created_at), sha256: item.database_sha256 || notRecordedLabel() }),
    confirmText: t('database_upgrade.confirm_restore', '确认恢复'),
    closeOnEscape: false,
  })
  if (!accepted) return
  await runTask(`restore:${item.backup_id}`, () => restoreDatabaseBackup(item.backup_id), t('database_upgrade.restore_submitted', '数据库恢复任务已提交'))
}

async function deleteBackup(item: DatabaseBackup): Promise<void> {
  const accepted = await confirm({
    type: 'DESTRUCTIVE',
    title: t('database_upgrade.confirm_delete_title', '删除数据库备份'),
    message: interpolate('database_upgrade.confirm_delete_message', '确认永久删除“{profile}”的数据库备份？此操作不会删除当前活动数据库。', { profile: profileLabel(item) }),
    detail: interpolate('database_upgrade.confirm_delete_detail', '备份 ID：{backupId}\n大小：{size}\n完整性：{integrity}', { backupId: item.backup_id, size: formatBytes(item.database_size), integrity: integrityLabel(item) }),
    confirmationText: item.backup_id,
    confirmationLabel: interpolate('database_upgrade.confirm_delete_label', '输入“{backupId}”以确认', { backupId: item.backup_id }),
    confirmText: t('database_upgrade.confirm_delete', '永久删除备份'),
    closeOnEscape: false,
  })
  if (!accepted) return
  await runTask(`delete:${item.backup_id}`, () => deleteDatabaseBackup(item.backup_id), t('database_upgrade.delete_submitted', '数据库备份删除任务已提交'))
}

async function deleteSelectedBackups(): Promise<void> {
  const backupIds = [...selectedBackupIds.value]
  if (!backupIds.length || actionId.value || backupDeleteConfirming.value) return
  const selectedCount = backupIds.length
  const estimatedBytes = selectedBackupBytes.value
  backupDeleteConfirming.value = true
  try {
    const accepted = await confirm({
      type: 'DESTRUCTIVE',
      title: '批量删除数据库备份',
      message: `确认永久删除已选择的 ${selectedCount} 个数据库备份？删除后无法通过 NetConsole 恢复。`,
      detail: `已选择：${selectedCount} 个备份\n预计释放空间：${formatBytes(estimatedBytes)}\n删除后无法通过 NetConsole 恢复；当前活动数据库、正在创建或使用中的备份会被保护。`,
      confirmText: '永久删除所选备份',
      closeOnEscape: false,
    })
    if (!accepted || actionId.value) return
    actionId.value = 'delete-backups-batch'
    const task = await deleteDatabaseBackups(backupIds)
    lastTask.value = task
    await openTask(task.task_id)
    const completed = await waitForTask(task.task_id)
    const failed = taskMetric(completed, 'failed_count', 'failed')
    const skipped = taskMetric(completed, 'skipped_count', 'skipped')
    const deleted = taskMetric(completed, 'success_count', 'deleted')
    const partial = Boolean(completed.partial_success) || failed > 0 || skipped > 0
    if (completed.status === 'COMPLETED') {
      if (!partial) clearSelectedBackups()
      await reload()
      if (partial) {
        ElMessage.warning(`批量删除完成：成功 ${deleted} 个，失败 ${failed} 个，跳过 ${skipped} 个`)
      } else {
        ElMessage.success(`批量删除完成：已删除 ${deleted} 个备份，释放 ${formatBytes(taskMetric(completed, 'released_bytes'))}`)
      }
    } else {
      await reload()
      throw new Error(`批量删除任务状态：${completed.status}`)
    }
  } catch (cause) {
    showError(cause, '批量删除数据库备份失败')
  } finally {
    backupDeleteConfirming.value = false
    actionId.value = ''
  }
}

function onBackupSelectionChange(rows: DatabaseBackup[]): void {
  if (syncingBackupSelection) return
  selectedBackups.value = rows.filter((item) => Boolean(item?.backup_id))
}

function toggleAllBackups(checked: boolean): void {
  if (!backupTable.value) return
  if (!checked) {
    syncingBackupSelection = true
    backupTable.value.clearSelection()
    syncingBackupSelection = false
    selectedBackups.value = []
    return
  }
  if (!allBackupsSelected.value) backupTable.value.toggleAllSelection()
}

function clearSelectedBackups(): void {
  selectedBackups.value = []
  backupTable.value?.clearSelection()
}

async function pruneBackupSelection(rows: DatabaseBackup[]): Promise<void> {
  const available = new Map(rows.map((item) => [item.backup_id, item]))
  const retained = selectedBackupIds.value.map((id) => available.get(id)).filter((item): item is DatabaseBackup => Boolean(item))
  selectedBackups.value = retained
  await nextTick()
  if (!backupTable.value) return
  syncingBackupSelection = true
  backupTable.value.clearSelection()
  retained.forEach((item) => backupTable.value?.toggleRowSelection(item, true))
  syncingBackupSelection = false
}

async function openDirectory(item: DatabaseBackup): Promise<void> {
  actionId.value = `open:${item.backup_id}`
  try {
    const result = await openDatabaseBackupDirectory(item.backup_id)
    if (!result.success) throw new Error(result.message || t('common.unavailable', '当前运行模式无法打开目录'))
  } catch (cause) { showError(cause, t('database_upgrade.open_directory_failed', '打开数据库备份目录失败')) }
  finally { actionId.value = '' }
}

async function openTask(taskId: string): Promise<void> {
  const result = await getPlatformAdapter().openTaskWindow({ taskId, module: 'logs' })
  if (!result.success && result.error) ElMessage.warning(result.error)
}

async function waitForTask(taskId: string): Promise<TaskItem> {
  const deadline = Date.now() + 10 * 60_000
  while (Date.now() < deadline) {
    const task = await getTask(taskId)
    if (['COMPLETED', 'FAILED', 'CANCELLED'].includes(task.status)) return task
    await new Promise((resolve) => setTimeout(resolve, 750))
  }
  throw new Error('批量删除任务等待超时，请在任务中心确认状态')
}

function taskMetric(task: TaskItem, directKey: string, detailKey = directKey): number {
  const direct = task[directKey as keyof TaskItem]
  if (typeof direct === 'number') return direct
  const detail = task.details?.[detailKey]
  return typeof detail === 'number' ? detail : Number(detail || 0)
}

function databaseLabel(kind: string): string { return kind === 'mesh_derived' ? t('database_upgrade.database_mesh_derived', 'MESH 派生数据库') : kind }
function healthLabel(status: string): string { return status === 'healthy' ? t('database_upgrade.health_healthy', '正常') : status === 'upgrade_required' ? t('database_upgrade.health_upgrade_required', '需要升级') : t('database_upgrade.health_not_created', '尚未创建') }
function healthType(status: string): 'success' | 'warning' | 'info' { return status === 'healthy' ? 'success' : status === 'upgrade_required' ? 'warning' : 'info' }
function profileLabel(item: DatabaseBackup): string { return item.profile_name || item.scope_id.split(':').slice(1).join(':') || item.scope_id }
function integrityLabel(item: DatabaseBackup): string {
  if (item.result_status === 'ZERO_BYTE_ARCHIVE') return t('database_upgrade.zero_byte', '0 KB 无效归档')
  if (item.result_status === 'DUPLICATE_BACKUP') return t('database_upgrade.duplicate', '重复内容')
  if (item.result_status !== 'VALID_BACKUP') return t('database_upgrade.invalid', '无效')
  return item.integrity_check_result?.restorable ? t('database_upgrade.complete', '完整') : t('database_upgrade.pending_validation', '待验证')
}
function integrityType(item: DatabaseBackup): 'success' | 'danger' | 'warning' {
  const label = integrityLabel(item)
  return label === t('database_upgrade.complete', '完整')
    ? 'success'
    : label === t('database_upgrade.pending_validation', '待验证') || label === t('database_upgrade.duplicate', '重复内容')
      ? 'warning'
      : 'danger'
}
function formatBytes(value: number): string {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}
function backupSize(item: DatabaseBackup): number { return Number(item.database_size ?? item.size_bytes ?? 0) }
function formatTime(value: string): string { return value ? new Date(value).toLocaleString() : notRecordedLabel() }
function shortVersion(value?: string): string { return value && value.length > 24 ? `${value.slice(0, 21)}...` : value || unknownLabel() }
function unknownLabel(): string { return t('database_upgrade.unknown', '未知') }
function notRecordedLabel(): string { return t('database_upgrade.not_recorded', '未记录') }
function interpolate(key: string, fallback: string, values: Record<string, string>): string {
  return Object.entries(values).reduce((value, [name, replacement]) => value.replaceAll(`{${name}}`, replacement), t(key, fallback))
}
function showError(cause: unknown, fallback: string): void {
  error.value = cause instanceof Error && cause.message ? cause.message : fallback
  ElMessage.error(error.value)
}
</script>

<template>
  <section class="database-upgrade-panel" v-loading="loading">
    <div class="panel-heading">
      <div><h2>{{ t('database_upgrade.title', '数据库升级与备份') }}</h2></div>
      <div class="panel-actions">
        <span class="selection-summary">已选 {{ selectedDatabases.length }} / {{ databases.length }} 个数据库</span>
        <el-button v-if="isFeatureEnabled('capability.database_upgrade.start')" size="small" :disabled="!selectedProfileIds.length || !!actionId" :loading="actionId === 'batch-backup'" @click="batchBackup">批量备份</el-button>
        <el-button v-if="isFeatureEnabled('capability.database_upgrade.start')" type="primary" size="small" :disabled="!selectedProfileIds.length || !!actionId" :loading="actionId === 'batch-upgrade'" @click="batchUpgrade">批量升级</el-button>
        <el-button size="small" :disabled="!databases.length" @click="databaseTable?.toggleAllSelection()">全选 / 取消全选</el-button>
        <el-button v-if="isFeatureEnabled('capability.database_upgrade.legacy_archive_organize')" :icon="Upload" :loading="actionId === 'organize'" @click="organizeLegacy">{{ t('database_upgrade.organize_legacy', '整理历史归档') }}</el-button>
        <el-button :icon="Refresh" :loading="loading" circle :title="t('common.refresh', '刷新')" :aria-label="t('common.refresh', '刷新')" @click="reload" />
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="lastTask" type="success" :closable="false">
      <template #title>{{ t('database_upgrade.task_submitted', '维护任务已提交') }}：{{ lastTask.task_id }}</template>
      <el-button size="small" @click="openTask(lastTask.task_id)">{{ t('job_center.action.details', '查看任务') }}</el-button>
    </el-alert>

    <el-tabs>
      <el-tab-pane :label="t('database_upgrade.status_tab', '数据库状态')">
        <div class="table-wrap">
          <el-table ref="databaseTable" :data="databases" min-width="900" :empty-text="t('database_upgrade.no_databases', '当前局点没有已登记的数据库')" @selection-change="onDatabaseSelectionChange">
            <el-table-column type="selection" width="52" />
            <el-table-column :label="t('database_upgrade.database', '数据库')" min-width="150"><template #default="{ row }"><strong>{{ databaseLabel(row.database_kind) }}</strong></template></el-table-column>
            <el-table-column prop="display_name" :label="t('database_upgrade.profile', 'Profile')" min-width="170" />
            <el-table-column :label="t('database_upgrade.current_version', '当前版本')" min-width="170"><template #default="{ row }"><code :title="row.current_version">{{ shortVersion(row.current_version) }}</code></template></el-table-column>
            <el-table-column :label="t('database_upgrade.target_version', '目标版本')" min-width="170"><template #default="{ row }"><code :title="row.required_version">{{ shortVersion(row.required_version) }}</code></template></el-table-column>
            <el-table-column :label="t('database_upgrade.health', '健康状态')" width="120"><template #default="{ row }"><el-tag :type="healthType(row.health_status)">{{ healthLabel(row.health_status) }}</el-tag></template></el-table-column>
            <el-table-column :label="t('database_upgrade.sources_backups', '来源 / 备份')" width="130"><template #default="{ row }">{{ row.registered_source_count }} / {{ row.backup_count }}</template></el-table-column>
            <el-table-column :label="t('database_upgrade.actions', '操作')" width="130" fixed="right"><template #default="{ row }"><el-button v-if="isFeatureEnabled('capability.database_upgrade.start')" type="primary" size="small" :icon="Select" :disabled="!row.needs_upgrade" :loading="actionId === `upgrade:${row.mr_id}`" @click="upgrade(row.mr_id)">{{ t('database_upgrade.start', '立即升级') }}</el-button></template></el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
      <el-tab-pane :label="`${t('database_upgrade.history_tab', '历史数据库备份')} (${snapshot?.backup_count || 0})`">
        <div class="backup-summary">{{ t('database_upgrade.backup_usage', '备份占用') }} <strong>{{ formatBytes(snapshot?.backup_size_bytes || 0) }}</strong></div>
        <div class="backup-selection-toolbar">
          <el-checkbox
            data-testid="history-backup-select-all"
            :model-value="allBackupsSelected"
            :indeterminate="backupSelectionIndeterminate"
            :disabled="!backups.length || !!actionId || backupDeleteConfirming"
            @change="toggleAllBackups"
          >
            全选当前结果
          </el-checkbox>
          <span data-testid="history-backup-selection-summary">已选 {{ selectedBackups.length }} / {{ backups.length }} 个备份</span>
          <span data-testid="history-backup-selection-bytes">预计释放 {{ formatBytes(selectedBackupBytes) }}</span>
          <el-button
            v-if="isFeatureEnabled('capability.database_upgrade.backup_delete')"
            data-testid="history-backup-batch-delete"
            type="danger"
            size="small"
            :disabled="!selectedBackupIds.length || !!actionId || backupDeleteConfirming"
            :loading="actionId === 'delete-backups-batch'"
            @click="deleteSelectedBackups"
          >
            批量删除
          </el-button>
        </div>
        <div class="table-wrap">
          <el-table ref="backupTable" :data="backups" row-key="backup_id" :empty-text="t('database_upgrade.no_backups', '尚无数据库升级备份')" @selection-change="onBackupSelectionChange">
            <el-table-column type="selection" width="52" :selectable="(row: DatabaseBackup) => Boolean(row.backup_id)" />
            <el-table-column type="expand">
              <template #default="{ row }"><dl class="backup-detail"><div><dt>{{ t('database_upgrade.backup_id', '备份 ID') }}</dt><dd><code>{{ row.backup_id }}</code></dd></div><div><dt>{{ t('database_upgrade.sha256', 'SHA-256') }}</dt><dd><code>{{ row.database_sha256 || notRecordedLabel() }}</code></dd></div><div><dt>{{ t('database_upgrade.task', '任务') }}</dt><dd><code>{{ row.task_id || notRecordedLabel() }}</code></dd></div><div><dt>{{ t('database_upgrade.scope', '范围') }}</dt><dd><code>{{ row.scope_id }}</code></dd></div></dl></template>
            </el-table-column>
            <el-table-column :label="t('database_upgrade.backup_time', '备份时间')" min-width="170"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
            <el-table-column :label="t('database_upgrade.database_profile', '数据库 / Profile')" min-width="210"><template #default="{ row }"><strong>{{ databaseLabel(row.database_kind) }}</strong><small>{{ profileLabel(row) }}</small></template></el-table-column>
            <el-table-column :label="t('database_upgrade.version', '版本')" min-width="170"><template #default="{ row }"><code>{{ shortVersion(row.old_schema_version) }}</code><span> → </span><code>{{ shortVersion(row.target_schema_version) }}</code></template></el-table-column>
            <el-table-column :label="t('database_upgrade.size', '大小')" width="110"><template #default="{ row }">{{ formatBytes(row.database_size) }}</template></el-table-column>
            <el-table-column :label="t('database_upgrade.integrity', '完整性')" width="120"><template #default="{ row }"><el-tag :type="integrityType(row)">{{ integrityLabel(row) }}</el-tag></template></el-table-column>
            <el-table-column :label="t('database_upgrade.operation', '操作')" width="190" fixed="right">
              <template #default="{ row }">
                <div class="icon-actions">
                  <el-tooltip v-if="isFeatureEnabled('capability.database_upgrade.backup_validate')" :content="t('database_upgrade.validate', '验证备份')"><el-button :icon="Select" circle :loading="actionId === `validate:${row.backup_id}`" @click="validateBackup(row)" /></el-tooltip>
                  <el-tooltip v-if="isFeatureEnabled('capability.database_upgrade.backup_restore')" :content="t('database_upgrade.restore', '恢复此版本')"><el-button :icon="RefreshLeft" circle :disabled="row.integrity_check_result?.restorable !== true" :loading="actionId === `restore:${row.backup_id}`" @click="restoreBackup(row)" /></el-tooltip>
                  <el-tooltip v-if="isFeatureEnabled('capability.database_upgrade.backup_open_directory')" :content="t('database_upgrade.open_directory', '打开所在目录')"><el-button :icon="FolderOpened" circle :loading="actionId === `open:${row.backup_id}`" @click="openDirectory(row)" /></el-tooltip>
                  <el-tooltip v-if="isFeatureEnabled('capability.database_upgrade.backup_delete')" :content="t('database_upgrade.delete', '删除备份')"><el-button type="danger" plain :icon="Delete" circle :loading="actionId === `delete:${row.backup_id}`" @click="deleteBackup(row)" /></el-tooltip>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.database-upgrade-panel{padding:18px 20px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px}.panel-heading,.panel-actions,.icon-actions{display:flex;align-items:center;gap:10px}.panel-heading{justify-content:space-between;margin-bottom:12px}.panel-heading h2{margin:0 0 5px;font-size:17px}.panel-heading p{margin:0;color:var(--nc-text-secondary);font-size:13px}.panel-actions,.icon-actions{flex-wrap:wrap;justify-content:flex-end}.el-alert{margin:10px 0}.table-wrap{width:100%;overflow-x:auto}.table-wrap :deep(.el-table){min-width:900px}.backup-summary{margin-bottom:10px;color:var(--nc-text-secondary)}.backup-selection-toolbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:10px;color:var(--nc-text-secondary);font-size:13px}.backup-detail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 18px;margin:0;padding:8px 28px}.backup-detail div{min-width:0}.backup-detail dt{color:var(--nc-text-secondary);font-size:12px}.backup-detail dd{margin:4px 0 0;overflow-wrap:anywhere}.el-table small{display:block;margin-top:4px;color:var(--nc-text-secondary)}code{overflow-wrap:anywhere}@media(max-width:900px){.panel-heading{align-items:flex-start;flex-direction:column}.panel-actions{justify-content:flex-start}.backup-detail{grid-template-columns:1fr}}
</style>
