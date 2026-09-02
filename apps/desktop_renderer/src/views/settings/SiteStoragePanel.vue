<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, MoreFilled } from '@element-plus/icons-vue'

import { activateSite, applySiteCleanup, applySiteRetention, auditSite, createSite, exportSite, getDataRoot, getLatestSiteAudit, getLatestSiteRetention, importSite, inspectSitePackage, listSites, migrateDataRoot, migrateSite, preflightSiteActivation, prepareSiteCleanup, rebuildDemoSite, scanSiteRetention, trashSite, updateSite, validateDataRoot, type DataRootSnapshot, type SiteConflictChoice, type SiteConflictResolution, type SitePackageInspection, type SitePackageType, type SiteRecord, type SiteRetentionCandidate, type SiteRetentionReport } from '../../api/siteStorage'
import { ApiRequestError } from '../../api/client'
import { getPlatformAdapter } from '../../platform/runtime'
import { getTask } from '../../api/tasks'
import { useConfirm } from '../../components/feedback/useConfirm'
import { useWorkspaceStore } from '../../stores/workspace'
import { coordinateSiteSwitch, notifySiteContextChanged } from '../../workspace/site-switch'

const props = defineProps<{ focused?: boolean; switchBlocked?: boolean }>()

const sites = ref<SiteRecord[]>([])
const root = ref<DataRootSnapshot | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
interface BlockingTask {
  task_id: string
  task_type: string
  task_name: string
  status: string
  blocking_reason: string
}
const blockingTasks = ref<BlockingTask[]>([])
const importDialogVisible = ref(false)
const importInspection = ref<SitePackageInspection | null>(null)
const importPackagePath = ref('')
const importMode = ref<'new' | 'replace' | 'merge'>('new')
const importSiteId = ref('')
const importDisplayName = ref('')
const importTargetSiteId = ref('')
const importRawOnly = ref(false)
const conflictChoices = ref<Record<string, { choice: SiteConflictChoice; manualValue: string }>>({})
const editDialogVisible = ref(false)
const editMode = ref<'full' | 'rename'>('full')
const editingSite = ref<SiteRecord | null>(null)
const editForm = ref({ display_name: '', line_name: '', project_type: '' })
const retentionDialogVisible = ref(false)
const retentionSite = ref<SiteRecord | null>(null)
const retentionReport = ref<SiteRetentionReport | null>(null)
const retentionSelectedIds = ref<string[]>([])
const retentionBusy = ref(false)
const projectTypeOptions = ['PIS车地无线系统', '信号系统', '通信系统', '综合监控系统', '其他']
const desktopOnly = getPlatformAdapter().hostType === 'electron'
const { confirm: confirmAction } = useConfirm()
const workspace = useWorkspaceStore()
const panelRoot = ref<HTMLElement | null>(null)
let panelMounted = false
let reloadGeneration = 0

const retentionGroups = computed(() => {
  const candidates = retentionReport.value?.candidates || []
  return [
    { key: 'expired-raw', title: '过期原始包/日志', categories: ['expired_raw'] },
    { key: 'history-backup', title: '历史数据库备份', categories: ['history_backup'] },
    { key: 'outdated-database', title: '过时数据库版本', categories: ['outdated_database', 'current_database'] },
    { key: 'task-history', title: '数据库历史记录/空间压缩', categories: ['task_history'] },
  ].map((group) => ({
    ...group,
    candidates: candidates.filter((candidate) => group.categories.includes(candidate.category)),
  }))
})

const selectedRetentionCandidates = computed(() => {
  const selected = new Set(retentionSelectedIds.value)
  return (retentionReport.value?.candidates || []).filter(
    (candidate) => selected.has(candidate.candidate_id) && candidate.safe,
  )
})

const selectedRetentionBytes = computed(() => selectedRetentionCandidates.value.reduce(
  (total, candidate) => total + candidate.estimated_release_bytes,
  0,
))

onMounted(() => {
  panelMounted = true
  if (desktopOnly) void reload().catch(() => undefined)
})
onBeforeUnmount(() => { panelMounted = false })

async function reload(options: { reportError?: boolean } = {}): Promise<void> {
  const generation = ++reloadGeneration
  if (panelMounted) {
    loading.value = true
    error.value = ''
  }
  try {
    const [sitesResult, rootResult] = await Promise.allSettled([listSites(), getDataRoot()])
    if (!panelMounted || generation !== reloadGeneration) return
    const failures: string[] = []
    if (sitesResult.status === 'fulfilled') sites.value = sitesResult.value
    else failures.push(`局点列表（${sitesResult.reason instanceof Error ? sitesResult.reason.message : '未知错误'}）`)
    if (rootResult.status === 'fulfilled') root.value = rootResult.value
    else failures.push(`数据路径（${rootResult.reason instanceof Error ? rootResult.reason.message : '未知错误'}）`)
    if (failures.length) throw new Error(`部分数据刷新失败，已保留最后成功数据。失败项目：${failures.join('、')}`)
  } catch (cause) {
    if (panelMounted && generation === reloadGeneration && options.reportError !== false) {
      showError(cause, '局点与数据路径加载失败')
    }
    throw cause
  } finally {
    if (panelMounted && generation === reloadGeneration) loading.value = false
  }
}

async function focus(): Promise<void> {
  await nextTick()
  panelRoot.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  panelRoot.value?.focus({ preventScroll: true })
}

async function newSite(): Promise<void> {
  const displayName = await prompt('请输入局点显示名称', '新建局点')
  if (!displayName) return
  const siteId = await prompt('请输入局点标识（小写字母、数字、-、_）', '新建局点')
  if (!siteId) return
  busy.value = true
  try {
    await createSite({ site_id: siteId, display_name: displayName })
    await reload()
    await getPlatformAdapter().refreshSiteContext()
    ElMessage.success('局点已创建')
  }
  catch (cause) { showError(cause, '局点创建失败') }
  finally { busy.value = false }
}

async function switchSite(site: SiteRecord): Promise<void> {
  if (busy.value || site.active) return
  busy.value = true
  error.value = ''
  blockingTasks.value = []
  try {
    const result = await coordinateSiteSwitch(
      { siteId: site.site_id, displayName: site.display_name },
      {
        isBlocked: () => Boolean(props.switchBlocked),
        confirm: (target) => confirmAction({
          type: 'WARNING',
          title: '切换当前局点',
          message: `切换到“${target.displayName}”？目标局点将在后台就绪后自动接管。`,
          confirmText: '确认切换局点',
        }),
        preflight: async (siteId) => { await preflightSiteActivation(siteId) },
        prepareWorkspace: (siteId, route) => workspace.prepareForSiteSwitch(siteId, route),
        activate: async (siteId) => { await activateSite(siteId) },
        restart: async (siteId) => {
          const restart = await getPlatformAdapter().restartBackend({ activeSiteId: siteId })
          if (!restart.success) throw new Error(restart.error || 'Backend 切换失败')
        },
        restoreWorkspace: async (checkpoint) => {
          await workspace.restoreAfterFailedSiteSwitch(
            checkpoint as ReturnType<typeof workspace.createSnapshot>,
          )
        },
        onSwitchingChanged: (switching) => getPlatformAdapter().reportSiteSwitchState(switching),
      },
    )
    if (result === 'blocked') {
      ElMessage.warning('请先保存或撤销当前系统设置，再切换局点')
    } else if (result === 'completed') {
      ElMessage.success('局点已切换')
    }
  } catch (cause) {
    blockingTasks.value = blockingTasksFrom(cause)
    showError(cause, '局点切换失败')
  }
  finally { busy.value = false }
}

async function requestSwitch(siteId: string): Promise<void> {
  try {
    await reload({ reportError: false })
    const target = sites.value.find((site) => site.site_id === siteId)
    if (!target) {
      ElMessage.error('目标局点已不存在或当前不可用')
      return
    }
    await switchSite(target)
  } finally {
    getPlatformAdapter().reportSiteSwitchState(false)
  }
}

defineExpose({ reload, focus, requestSwitch })

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

async function openRetention(site: SiteRecord): Promise<void> {
  retentionSite.value = site
  retentionReport.value = null
  retentionSelectedIds.value = []
  retentionDialogVisible.value = true
  retentionBusy.value = true
  try {
    retentionReport.value = await getLatestSiteRetention(site.site_id)
  } catch (cause) {
    if (!(cause instanceof ApiRequestError) || cause.code !== 'SITE_RETENTION_SCAN_NOT_FOUND') {
      showError(cause, '数据清理扫描读取失败')
    }
  } finally {
    retentionBusy.value = false
  }
}

async function runRetentionScan(options: { notify?: boolean } = {}): Promise<void> {
  const site = retentionSite.value
  if (!site) return
  retentionBusy.value = true
  try {
    const task = await scanSiteRetention(site.site_id)
    await openTask(task.task_id)
    const completed = await waitForTask(task.task_id)
    if (completed !== 'COMPLETED') throw new Error(`数据清理扫描任务状态：${completed}`)
    retentionReport.value = await getLatestSiteRetention(site.site_id)
    retentionSelectedIds.value = []
    if (options.notify !== false) ElMessage.success('可清理数据扫描完成')
  } catch (cause) {
    showError(cause, '可清理数据扫描失败')
  } finally {
    retentionBusy.value = false
  }
}

function updateRetentionSelection(candidate: SiteRetentionCandidate, selected: boolean): void {
  if (!candidate.safe) return
  const values = new Set(retentionSelectedIds.value)
  if (selected) values.add(candidate.candidate_id)
  else values.delete(candidate.candidate_id)
  retentionSelectedIds.value = [...values]
}

function selectAllSafeRetentionCandidates(): void {
  retentionSelectedIds.value = (retentionReport.value?.candidates || [])
    .filter((candidate) => candidate.safe)
    .map((candidate) => candidate.candidate_id)
}

async function executeRetention(): Promise<void> {
  const site = retentionSite.value
  const report = retentionReport.value
  const candidates = selectedRetentionCandidates.value
  if (!site || !report || !candidates.length) {
    ElMessage.warning('请先选择至少一项可安全清理的数据')
    return
  }
  const destructive = candidates.some((candidate) => ['delete', 'purge'].includes(candidate.recommended_action))
  const confirmed = await confirmAction({
    type: destructive ? 'DESTRUCTIVE' : 'WARNING',
    title: destructive ? '确认执行数据清理' : '确认压缩过期数据',
    message: `将处理 ${candidates.length} 项数据，预计释放 ${formatBytes(selectedRetentionBytes.value)}。执行前 Backend 会重新核验扫描令牌、数据库和归档证据。`,
    detail: candidates.map((candidate) => `${retentionActionLabel(candidate.recommended_action)}：${candidate.relative_path}`).join('\n'),
    notice: destructive ? '删除和任务历史清理不可撤销；数据库归档仍保留可校验 ZIP。' : '原始松散文件仅在完整会话包校验通过后移除。',
    ...(destructive ? {
      confirmationText: site.display_name,
      confirmationLabel: `输入“${site.display_name}”以确认`,
    } : {}),
    confirmText: destructive ? '确认执行清理' : '确认压缩',
    closeOnEscape: false,
  })
  if (!confirmed) return

  retentionBusy.value = true
  try {
    const task = await applySiteRetention(
      site.site_id,
      report.scan_token,
      candidates.map((candidate) => candidate.candidate_id),
    )
    await openTask(task.task_id)
    const completed = await waitForTask(task.task_id)
    if (completed !== 'COMPLETED') throw new Error(`数据清理任务状态：${completed}`)
    ElMessage.success('所选数据已处理，正在重新扫描')
    await runRetentionScan({ notify: false })
  } catch (cause) {
    showError(cause, '局点数据清理失败')
  } finally {
    retentionBusy.value = false
  }
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
    await getPlatformAdapter().refreshSiteContext()
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
    await getPlatformAdapter().refreshSiteContext()
    ElMessage.success('演示局点已重建')
  } catch (cause) { showError(cause, '演示局点重建失败') }
  finally { busy.value = false }
}

function openSiteEditor(site: SiteRecord, mode: 'full' | 'rename'): void {
  editingSite.value = site
  editMode.value = mode
  editForm.value = {
    display_name: String(site.display_name || ''),
    line_name: siteInfoText(site.line_name),
    project_type: siteInfoText(site.project_type),
  }
  editDialogVisible.value = true
}

async function saveSiteInfo(): Promise<void> {
  const site = editingSite.value
  if (!site) return
  const displayName = editForm.value.display_name.trim()
  const lineName = editForm.value.line_name.trim()
  const projectType = editForm.value.project_type.trim()
  if (!displayName) {
    ElMessage.warning('局点名称不能为空')
    return
  }
  if (displayName.length > 64) {
    ElMessage.warning('局点名称不能超过 64 个字符')
    return
  }
  if ([displayName, lineName, projectType].some((value) => /[\u0000-\u001f\u007f]/.test(value))) {
    ElMessage.warning('局点信息不能包含控制字符')
    return
  }
  busy.value = true
  try {
    await updateSite(site.site_id, {
      display_name: displayName,
      line_name: lineName || null,
      project_type: projectType || null,
    })
    editDialogVisible.value = false
    await reload()
    await getPlatformAdapter().refreshSiteContext()
    notifySiteContextChanged()
    ElMessage.success(editMode.value === 'rename' ? '局点已重命名' : '局点信息已保存')
  } catch (cause) {
    showError(cause, '局点信息保存失败')
  } finally {
    busy.value = false
  }
}

async function deleteSite(site: SiteRecord): Promise<void> {
  if (site.active) {
    ElMessage.warning('当前局点不可删除，请先切换到其他局点。')
    return
  }
  if (site.classification === 'empty_shell') {
    ElMessage.warning('空壳局点请使用“清理空壳局点”')
    return
  }
  const confirmed = await confirmAction({
    type: 'DESTRUCTIVE',
    title: '删除局点',
    message: `确认将“${site.display_name}”移入数据根 .trash 目录？`,
    detail: [
      `局点 ID：${site.site_id}`,
      `数据目录：${site.path || '不可用'}`,
      `数据大小：${formatBytes(site.size_bytes)}`,
      '删除后原目录会从局点清单移除，但数据仍保留在 .trash 中。',
    ].join('\n'),
    notice: '请输入完整局点名称。当前操作不会递归永久删除原始数据。',
    confirmationText: site.display_name,
    confirmationLabel: `输入“${site.display_name}”以确认`,
    confirmText: '移入 .trash',
    closeOnEscape: false,
  })
  if (!confirmed) return
  busy.value = true
  try {
    await trashSite(site.site_id, site.display_name)
    await reload()
    await getPlatformAdapter().refreshSiteContext()
    notifySiteContextChanged()
    ElMessage.success('局点已移入 .trash')
  } catch (cause) {
    blockingTasks.value = blockingTasksFrom(cause)
    showError(cause, '局点删除失败')
  } finally {
    busy.value = false
  }
}

async function handleSiteAction(site: SiteRecord, command: unknown): Promise<void> {
  switch (String(command)) {
    case 'edit': openSiteEditor(site, 'full'); break
    case 'rename': openSiteEditor(site, 'rename'); break
    case 'open': await openSiteDirectory(site); break
    case 'migrate': await moveSite(site); break
    case 'cleanup': await cleanupSite(site); break
    case 'rebuild-demo': await rebuildDemo(site); break
    case 'delete': await deleteSite(site); break
  }
}

async function exportCurrent(packageType: SitePackageType): Promise<void> {
  const current = sites.value.find((site) => site.active)
  if (!current) return
  if (packageType === 'full_migration') {
    ElMessage.warning('完整迁移包包含设备用户名和密码，且未加密，请仅保存到可信位置并妥善保管。')
  }
  if (packageType === 'lightweight') {
    try {
      await ElMessageBox.confirm(
        '轻量包会包含设备连接密码，并汇总设备、AC、轨旁 AP 和轨道交通基础资料。请仅保存到可信位置；manifest 不包含密码值，脱敏包仍会继续脱敏。',
        '导出轻量包确认',
        { type: 'warning', confirmButtonText: '确认导出', cancelButtonText: '取消', closeOnClickModal: false, closeOnPressEscape: false },
      )
    } catch { return }
  }
  const date = new Date().toISOString().slice(0, 10).replaceAll('-', '')
  const names: Record<SitePackageType, string> = {
    full_migration: `${current.display_name}_完整迁移包_${date}.ncsite`,
    sanitized_share: `${current.display_name}_脱敏分享包_${date}.ncsite`,
    field_collection: `${current.display_name}_现场采集包_${date}.ncsite`,
    collection_return: `${current.display_name}_采集回传包_${date}.ncresult`,
    lightweight: `${current.display_name}_轻量包_${date}.zip`,
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
    const inspected: SitePackageInspection = await inspectSitePackage(selected.path)
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
    const completed = await waitForTask(task.task_id)
    if (completed !== 'COMPLETED') throw new Error(`局点导入任务状态：${completed}`)
    try {
      await reload({ reportError: false })
    } catch {
      ElMessage.warning('导入已完成，但局点列表刷新失败')
      return
    } finally {
      await getPlatformAdapter().refreshSiteContext().catch(() => undefined)
    }
    ElMessage.success('局点数据包导入完成')
  } catch (cause) { showError(cause, '数据包导入失败') }
  finally { if (panelMounted) busy.value = false }
}

async function chooseRoot(): Promise<void> {
  const selected = await getPlatformAdapter().selectDataRootDirectory()
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try { await validateDataRoot(selected.path); const task = await migrateDataRoot(selected.path); await openTask(task.task_id); const completed = await waitForTask(task.task_id); if (completed === 'COMPLETED') { const result = await getPlatformAdapter().restartBackend({ dataRoot: selected.path }); if (!result.success) throw new Error(result.error || 'Backend 重启失败'); ElMessage.success('数据根迁移并重启完成') } else if (completed) throw new Error(`迁移任务状态：${completed}`) }
  catch (cause) { showError(cause, '数据根迁移失败') }
  finally { busy.value = false }
}

async function moveSite(site: SiteRecord): Promise<void> {
  const selected = await getPlatformAdapter().selectDataRootDirectory()
  if (selected.cancelled || !selected.path) return
  busy.value = true
  try { const task = await migrateSite(site.site_id, selected.path); await openTask(task.task_id); ElMessage.success('局点迁移任务已提交') }
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

async function openSiteDirectory(site: SiteRecord): Promise<void> {
  if (!site.active) {
    ElMessage.warning('为避免开放任意路径，仅当前局点可直接打开目录')
    return
  }
  const result = await getPlatformAdapter().executeSettingsAction('open_current_site')
  if (!result.success) showError(new Error(result.error || '打开目录失败'), '打开目录失败')
}

async function openTask(taskId: string): Promise<void> {
  const result = await getPlatformAdapter().openTaskWindow({ taskId, module: 'logs' })
  if (!result.success && result.error) ElMessage.warning(result.error)
}

function blockingTasksFrom(cause: unknown): BlockingTask[] {
  if (!(cause instanceof ApiRequestError) || cause.code !== 'SITE_HAS_ACTIVE_TASKS') return []
  const tasks = cause.details.blocking_tasks
  if (!Array.isArray(tasks)) return []
  return tasks.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const value = item as Record<string, unknown>
    const taskId = typeof value.task_id === 'string' ? value.task_id : ''
    if (!taskId) return []
    return [{
      task_id: taskId,
      task_type: typeof value.task_type === 'string' ? value.task_type : '',
      task_name: typeof value.task_name === 'string' ? value.task_name : taskId,
      status: typeof value.status === 'string' ? value.status : 'UNKNOWN',
      blocking_reason: typeof value.blocking_reason === 'string' ? value.blocking_reason : '任务仍在运行',
    }]
  })
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
function retentionActionLabel(value: string): string { return ({ keep: '保留', archive: '压缩归档', delete: '删除', purge: '清理并压缩数据库' } as Record<string, string>)[value] || value }
function retentionStatusLabel(value: string): string { return ({ current_use: '当前使用', recent_rollback: '最近回滚', recent_stable: '最近稳定', historical_migration_version: '历史迁移版本', duplicate_backup: '重复备份', unknown_database: '未知数据库', recent_raw: '近期原始数据', archived_raw_copy: '归档副本已校验', protected_raw: '受保护原始数据', manual_retain: '人工保留', expired_task_events: '过期任务事件', within_retention: '保留期内' } as Record<string, string>)[value] || value }
function integrityLabel(value: SiteRecord['data_integrity']): string { return ({ ok: '正常', failed: '异常', unknown: '待审计' } as const)[value] || '待审计' }
function classificationTag(site: SiteRecord): 'success' | 'warning' | 'danger' | 'info' { const value = site.classification || 'unknown'; if (value === 'managed_demo') return 'success'; if (value === 'empty_shell') return 'danger'; if (value.startsWith('legacy')) return 'warning'; return 'info' }
function siteInfoText(value: string | null | undefined): string { return String(value || '').trim() }
function deleteDisabled(site: SiteRecord): boolean { return site.active || site.classification === 'empty_shell' || busy.value }
function deleteDisabledReason(site: SiteRecord): string {
  if (site.active) return '当前局点不可删除，请先切换到其他局点。'
  if (site.classification === 'empty_shell') return '空壳局点请使用“清理空壳局点”'
  return ''
}
function packageTypeLabel(value: SitePackageType): string { return ({ full_migration: '完整迁移包', sanitized_share: '脱敏分享包', field_collection: '现场采集包', collection_return: '采集回传包', lightweight: '轻量包' } as const)[value] }
function displayValue(value: unknown): string { if (value === null || value === undefined || value === '') return '空'; if (typeof value === 'object') return JSON.stringify(value); return String(value) }
</script>

<template>
  <section
    v-if="desktopOnly"
    ref="panelRoot"
    id="site-storage-management"
    tabindex="-1"
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
              <el-dropdown-item command="sanitized_share">导出脱敏分享包</el-dropdown-item>
              <el-dropdown-item command="field_collection">导出现场采集包</el-dropdown-item>
              <el-dropdown-item command="collection_return">导出采集回传包</el-dropdown-item>
              <el-dropdown-item command="lightweight" divided>导出轻量包（含设备密码）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <el-alert v-if="root?.persistent === false" data-testid="isolated-storage-alert" title="隔离测试模式：当前数据将在退出后删除，不会写入正式 NetConsole 数据。" type="warning" :closable="false" show-icon />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="blockingTasks.length" data-testid="site-blocking-tasks" class="blocking-tasks">
      <div v-for="task in blockingTasks" :key="task.task_id" class="blocking-task">
        <div>
          <strong>{{ task.task_name || task.task_type }}</strong>
          <el-tag size="small" type="warning">{{ task.status }}</el-tag>
          <code>{{ task.task_id }}</code>
          <p>{{ task.blocking_reason }}</p>
        </div>
        <el-button size="small" @click="openTask(task.task_id)">打开任务中心</el-button>
      </div>
    </div>
    <div v-if="root" class="root-summary"><span>{{ root.persistent ? '全局数据根' : '临时测试数据根' }}</span><code :title="root.persistent ? root.data_root : undefined">{{ root.data_root }}</code><span>{{ root.site_count }} 个局点</span><template v-if="root.persistent"><el-button data-testid="migrate-data-root" size="small" @click="chooseRoot">选择并迁移</el-button><el-button data-testid="restore-data-root" size="small" :disabled="root.data_root === root.default_data_root" @click="restoreDefaultRoot">恢复默认路径</el-button></template></div>
    <div class="site-list">
      <article v-for="site in sites" :key="site.site_id" class="site-item" :class="{ active: site.active }">
        <div class="site-content">
          <div class="site-main">
            <strong>{{ site.display_name }}</strong>
            <el-tag v-if="site.active" type="success">当前</el-tag>
            <el-tag size="small" :type="classificationTag(site)">{{ classificationLabel(site.classification || 'unknown') }}</el-tag>
          </div>
          <div class="site-info-tags">
            <el-tag v-if="siteInfoText(site.line_name)" size="small" effect="plain">线路：{{ siteInfoText(site.line_name) }}</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">线路未填写</el-tag>
            <el-tag v-if="siteInfoText(site.project_type)" size="small" effect="plain">项目类型：{{ siteInfoText(site.project_type) }}</el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">项目类型未填写</el-tag>
          </div>
          <div class="site-facts"><code>{{ site.site_id }}</code><span>{{ formatBytes(site.size_bytes) }}</span><span>完整性：{{ integrityLabel(site.data_integrity) }}</span></div>
        </div>
        <div v-if="root?.persistent" class="site-actions">
          <el-button :data-testid="`audit-site-${site.site_id}`" size="small" :disabled="busy" @click="auditSelectedSite(site)">审计</el-button>
          <el-button v-if="site.audited_at" :data-testid="`show-audit-${site.site_id}`" size="small" :disabled="busy" @click="showAudit(site)">查看清单</el-button>
          <el-button :data-testid="`retention-site-${site.site_id}`" size="small" :disabled="busy" @click="openRetention(site)">数据清理</el-button>
          <el-button :data-testid="`switch-site-${site.site_id}`" size="small" :disabled="site.active || busy" @click="switchSite(site)">{{ site.active ? '当前局点' : '切换' }}</el-button>
          <el-dropdown :disabled="busy" trigger="click" @command="handleSiteAction(site, $event)">
            <el-button :data-testid="`more-site-${site.site_id}`" size="small" :disabled="busy">
              更多<el-icon class="el-icon--right"><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit">编辑局点信息</el-dropdown-item>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="open" :disabled="!site.active">打开目录</el-dropdown-item>
                <el-dropdown-item command="migrate">迁移局点</el-dropdown-item>
                <el-dropdown-item v-if="site.classification === 'empty_shell'" command="cleanup" divided :disabled="site.active" :data-testid="`cleanup-site-${site.site_id}`">清理空壳局点</el-dropdown-item>
                <el-dropdown-item v-if="site.site_kind === 'demo'" command="rebuild-demo" divided :disabled="site.active" :data-testid="`rebuild-demo-${site.site_id}`">重建 Demo</el-dropdown-item>
                <el-dropdown-item command="delete" divided class="danger-menu-item" style="color:var(--el-color-danger)" :disabled="deleteDisabled(site)" :title="deleteDisabledReason(site)" :data-testid="`delete-site-${site.site_id}`">删除局点</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </article>
    </div>
    <el-dialog v-if="retentionDialogVisible" v-model="retentionDialogVisible" class="site-retention-dialog" width="min(1120px, 96vw)" :close-on-click-modal="false" :close-on-press-escape="!retentionBusy" :show-close="!retentionBusy" title="数据清理">
      <div v-loading="retentionBusy" class="retention-content" data-testid="retention-dialog">
        <div class="retention-heading">
          <div>
            <strong>{{ retentionSite?.display_name }}</strong>
            <code>{{ retentionSite?.site_id }}</code>
          </div>
          <div class="retention-actions">
            <el-button size="small" :disabled="retentionBusy" data-testid="retention-scan" @click="runRetentionScan()">扫描可清理数据</el-button>
            <el-button v-if="retentionReport" size="small" :disabled="retentionBusy || !retentionReport.summary.actionable_count" @click="selectAllSafeRetentionCandidates">全选可安全处理项</el-button>
          </div>
        </div>

        <template v-if="retentionReport">
          <div class="retention-summary" data-testid="retention-summary">
            <span><small>当前总占用</small><strong>{{ formatBytes(retentionReport.summary.total_bytes) }}</strong></span>
            <span><small>当前数据库</small><strong>{{ formatBytes(retentionReport.summary.current_database_bytes) }}</strong></span>
            <span><small>原始抓包/日志</small><strong>{{ formatBytes(retentionReport.summary.raw_bytes) }}</strong></span>
            <span><small>解析数据</small><strong>{{ formatBytes(retentionReport.summary.parsed_bytes) }}</strong></span>
            <span><small>历史备份</small><strong>{{ formatBytes(retentionReport.summary.backup_bytes) }}</strong></span>
            <span><small>可安全清理</small><strong>{{ formatBytes(retentionReport.summary.safe_cleanup_bytes) }}</strong></span>
            <span><small>可压缩空间</small><strong>{{ formatBytes(retentionReport.summary.compressible_bytes) }}</strong></span>
          </div>
          <div class="retention-meta">
            <span>扫描时间：{{ retentionReport.generated_at }}</span>
            <span>可处理 {{ retentionReport.summary.actionable_count }} 项</span>
            <span>已选 {{ selectedRetentionCandidates.length }} 项 / 预计释放 {{ formatBytes(selectedRetentionBytes) }}</span>
          </div>

          <section v-for="group in retentionGroups" :key="group.key" class="retention-group" :data-testid="`retention-group-${group.key}`">
            <div class="retention-group-heading">
              <h3>{{ group.title }}</h3>
              <span>{{ group.candidates.length }} 项</span>
            </div>
            <div v-if="group.candidates.length" class="retention-list">
              <label v-for="candidate in group.candidates" :key="candidate.candidate_id" class="retention-row" :class="{ blocked: !candidate.safe }">
                <el-checkbox
                  :model-value="retentionSelectedIds.includes(candidate.candidate_id)"
                  :disabled="!candidate.safe || retentionBusy"
                  :aria-label="candidate.display_name"
                  :data-testid="`retention-candidate-${candidate.candidate_id}`"
                  @change="updateRetentionSelection(candidate, Boolean($event))"
                />
                <span class="retention-item-main">
                  <span class="retention-item-title">
                    <strong>{{ candidate.display_name }}</strong>
                    <el-tag size="small" :type="candidate.safe ? 'success' : 'info'">{{ retentionStatusLabel(candidate.status) }}</el-tag>
                    <el-tag v-if="candidate.recommended_action !== 'keep'" size="small" effect="plain">{{ retentionActionLabel(candidate.recommended_action) }}</el-tag>
                  </span>
                  <code>{{ candidate.relative_path }}</code>
                  <small>{{ candidate.reason }}</small>
                </span>
                <span class="retention-item-size">
                  <strong>{{ formatBytes(candidate.size_bytes) }}</strong>
                  <small v-if="candidate.safe">预计释放 {{ formatBytes(candidate.estimated_release_bytes) }}</small>
                  <small>{{ candidate.age_days }} 天</small>
                </span>
              </label>
            </div>
            <el-empty v-else :image-size="48" description="暂无数据" />
          </section>
        </template>
        <el-empty v-else :image-size="72" description="尚未生成数据清理扫描">
          <el-button type="primary" :disabled="retentionBusy" @click="runRetentionScan()">开始扫描</el-button>
        </el-empty>
      </div>
      <template #footer>
        <el-button :disabled="retentionBusy" @click="retentionDialogVisible = false">关闭</el-button>
        <el-button type="danger" :loading="retentionBusy" :disabled="!selectedRetentionCandidates.length" data-testid="retention-execute" @click="executeRetention">执行所选项</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="editDialogVisible" class="site-edit-dialog" width="min(620px, calc(100vw - 32px))" :close-on-click-modal="false" :title="editMode === 'rename' ? '重命名局点' : '编辑局点信息'">
      <el-form label-position="top">
        <el-form-item label="局点名称" required>
          <el-input v-model="editForm.display_name" maxlength="64" show-word-limit data-testid="site-display-name-input" />
        </el-form-item>
        <template v-if="editMode === 'full'">
          <el-form-item label="线路名称">
            <el-input v-model="editForm.line_name" maxlength="128" placeholder="可选" data-testid="site-line-name-input" />
          </el-form-item>
          <el-form-item label="项目类型">
            <el-select v-model="editForm.project_type" filterable allow-create default-first-option clearable class="full-width" placeholder="选择或输入项目类型" data-testid="site-project-type-input">
              <el-option v-for="option in projectTypeOptions" :key="option" :label="option" :value="option" />
            </el-select>
          </el-form-item>
        </template>
        <el-form-item label="局点 ID"><el-input :model-value="editingSite?.site_id" readonly /></el-form-item>
        <el-form-item label="数据目录"><el-input :model-value="editingSite?.path || '不可用'" readonly /></el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="busy" @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="busy" data-testid="save-site-info" @click="saveSiteInfo">保存</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="importDialogVisible" class="site-import-dialog" width="min(920px, 94vw)" :close-on-click-modal="false" title="数据包导入预检">
      <template v-if="importInspection">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="目标局点">{{ importInspection.site_name }}</el-descriptions-item>
          <el-descriptions-item label="包类型">{{ packageTypeLabel(importInspection.package_type) }}</el-descriptions-item>
          <el-descriptions-item label="局点 UUID"><code>{{ importInspection.site_uuid || '旧版包未提供' }}</code></el-descriptions-item>
          <el-descriptions-item label="版本">基准 {{ importInspection.base_revision }}<template v-if="importInspection.local_revision !== undefined"> / 本地 {{ importInspection.local_revision }}</template></el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="importInspection.package_type === 'full_migration' && importInspection.contains_credentials" title="完整迁移包包含设备用户名和密码，请妥善保管。" type="warning" :closable="false" show-icon />
        <el-alert v-else-if="importInspection.credential_reentry_count > 0" title="该数据包不包含设备凭据，导入后需要重新录入。" type="warning" :closable="false" show-icon />

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
.storage-panel{padding:18px 20px;scroll-margin-top:16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-light);border-radius:8px;transition:outline-color .18s ease,box-shadow .18s ease}.storage-panel--focused{outline:1px solid var(--nc-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--nc-primary),transparent 82%)}.panel-heading,.actions,.root-summary,.site-item,.site-main,.site-actions,.site-info-tags,.site-facts{display:flex;align-items:center;gap:10px}.panel-heading{justify-content:space-between;gap:18px}.panel-heading h2{margin:0 0 5px;font-size:17px}.panel-heading p{margin:0;color:var(--nc-text-secondary);font-size:13px}.actions,.site-actions{flex-wrap:wrap;justify-content:flex-end}.blocking-tasks{display:grid;gap:8px;margin-top:10px}.blocking-task{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border:1px solid var(--el-color-warning-light-5);border-radius:6px;background:var(--el-color-warning-light-9)}.blocking-task>div{display:flex;align-items:center;gap:8px;min-width:0;flex-wrap:wrap}.blocking-task code{overflow-wrap:anywhere}.blocking-task p{width:100%;margin:0;color:var(--nc-text-secondary);font-size:12px}.root-summary{margin:16px 0;padding:10px 12px;background:var(--nc-surface-muted);border-radius:6px;flex-wrap:wrap}.root-summary code{flex:1;min-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.site-list{display:grid;gap:8px}.site-item{justify-content:space-between;padding:11px 12px;border:1px solid var(--el-border-color-lighter);border-radius:6px}.site-item.active{border-color:var(--el-color-success-light-5);background:var(--el-color-success-light-9)}.site-content{display:grid;min-width:0;gap:7px}.site-main,.site-info-tags,.site-facts{min-width:0;flex-wrap:wrap}.site-main strong{font-size:14px}.site-facts code{color:var(--nc-text-secondary)}.site-facts span{color:var(--nc-text-secondary);font-size:12px}.retention-content{min-height:280px;max-height:68vh;overflow:auto;padding-right:4px}.retention-heading,.retention-heading>div,.retention-actions,.retention-meta,.retention-item-title{display:flex;align-items:center;gap:10px}.retention-heading{position:sticky;top:0;z-index:2;justify-content:space-between;padding:2px 0 12px;background:var(--el-bg-color)}.retention-heading>div:first-child{min-width:0;flex-wrap:wrap}.retention-heading code{color:var(--nc-text-secondary)}.retention-actions{flex-wrap:wrap;justify-content:flex-end}.retention-summary{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));border-block:1px solid var(--el-border-color-lighter)}.retention-summary span{min-width:0;padding:12px;border-right:1px solid var(--el-border-color-lighter)}.retention-summary span:nth-child(4n){border-right:0}.retention-summary small,.retention-summary strong{display:block}.retention-summary small{margin-bottom:4px;color:var(--nc-text-secondary)}.retention-summary strong{font-size:16px}.retention-meta{padding:10px 0;color:var(--nc-text-secondary);font-size:12px;flex-wrap:wrap}.retention-group{margin-top:14px}.retention-group-heading{display:flex;align-items:center;justify-content:space-between;padding-bottom:7px;border-bottom:1px solid var(--el-border-color)}.retention-group-heading h3{margin:0;font-size:14px}.retention-group-heading span{color:var(--nc-text-secondary);font-size:12px}.retention-list{display:grid}.retention-row{display:grid;grid-template-columns:28px minmax(0,1fr) minmax(100px,auto);align-items:center;gap:10px;padding:10px 8px;border-bottom:1px solid var(--el-border-color-lighter);cursor:pointer}.retention-row.blocked{cursor:default;background:var(--nc-surface-muted)}.retention-item-main{display:grid;min-width:0;gap:4px}.retention-item-title{min-width:0;flex-wrap:wrap}.retention-item-title strong{font-size:13px}.retention-item-main code{overflow-wrap:anywhere;color:var(--nc-text-secondary);font-size:12px}.retention-item-main small{color:var(--nc-text-secondary)}.retention-item-size{display:grid;justify-items:end;gap:3px;text-align:right}.retention-item-size small{color:var(--nc-text-secondary);font-size:11px}.site-edit-dialog :deep(.el-form){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 14px}.site-edit-dialog :deep(.el-form-item){min-width:0}.site-edit-dialog :deep(.el-form-item:first-child),.site-edit-dialog :deep(.el-form-item:nth-child(2)),.site-edit-dialog :deep(.el-form-item:nth-child(3)){grid-column:1/-1}.preflight-grid{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;margin:14px 0}.preflight-grid span{padding:9px 10px;background:var(--nc-surface-muted);border-radius:6px;color:var(--nc-text-secondary);font-size:12px}.preflight-grid strong{display:block;margin-bottom:2px;color:var(--nc-text-primary);font-size:16px}.preflight-grid .danger strong{color:var(--el-color-danger)}.import-options{display:grid;gap:14px;margin-top:16px}.import-options :deep(.el-form){display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.import-options :deep(.el-form-item){margin-bottom:0}.full-width{width:100%}.raw-only-option{margin:14px 0}.conflict-section{margin-top:4px}.section-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:8px}.section-heading span{color:var(--nc-text-secondary);font-size:12px}.conflict-table-wrap{width:100%;overflow-x:auto}.conflict-table-wrap :deep(.el-table){min-width:980px}.site-import-dialog code{overflow-wrap:anywhere}@media(max-width:900px){.panel-heading{align-items:flex-start;flex-direction:column}.actions{justify-content:flex-start}.blocking-task{align-items:flex-start;flex-direction:column}.site-item{align-items:flex-start;flex-direction:column}.site-actions{justify-content:flex-start}.retention-heading{align-items:flex-start;flex-direction:column}.retention-actions{justify-content:flex-start}.retention-summary{grid-template-columns:repeat(2,minmax(120px,1fr))}.retention-summary span:nth-child(2n){border-right:0}.retention-row{grid-template-columns:28px minmax(0,1fr)}.retention-item-size{grid-column:2;justify-items:start;text-align:left}.site-edit-dialog :deep(.el-form){grid-template-columns:1fr}.preflight-grid{grid-template-columns:repeat(2,minmax(110px,1fr))}.import-options :deep(.el-form){grid-template-columns:1fr}.section-heading{align-items:flex-start;flex-direction:column}}
</style>
