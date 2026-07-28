<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  acOmniPeekArtifactDownloadRequest,
  cancelAcWebTask,
  getAcOmniPeekPreferences,
  getAcOmniPeekPreview,
  getAcWebTask,
  saveAcOmniPeekPreferences,
  startAcOmniPeekExport,
  startAcOmniPeekPreview,
} from '../../api/acWebParity'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { downloadBackendResource, getPlatformAdapter, getRuntimeConfig } from '../../platform/runtime'
import type { AcOmniPeekConfig, AcOmniPeekPreview, AcOmniPeekPreviewItem } from '../../types/acWebParity'

const props = defineProps<{
  modelValue: boolean
  acId: string
  apIds: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'task-submitted': [taskId: string]
}>()

const SOURCE_AC = 'AC FIT-AP资源'
const SOURCE_EXTENSION = 'AP扩展信息'
const SOURCE_MR = '设备管理'
const COLOR_LABELS: Record<string, string> = {
  trackside_physical: '轨旁 AP 物理 MAC',
  trackside_r1: '轨旁 AP R1',
  trackside_r2: '轨旁 AP R2',
  onboard_physical: '车载 MR 物理 MAC',
  onboard_r1: '车载 MR R1',
  onboard_r2: '车载 MR R2',
}
const DEFAULT_COLORS: Record<string, string> = {
  trackside_physical: '#00FF00',
  trackside_r1: '#0070C0',
  trackside_r2: '#FFC000',
  onboard_physical: '#7030A0',
  onboard_r1: '#00B0F0',
  onboard_r2: '#FF0000',
}

const config = reactive<AcOmniPeekConfig>({
  line_name: '线路',
  include_ac_fit_ap: true,
  include_ap_extensions: true,
  include_device_mr: false,
  export_trackside_physical: true,
  export_trackside_r1: true,
  export_trackside_r2: true,
  export_onboard_physical: true,
  export_onboard_r1: true,
  export_onboard_r2: true,
  onboard_radio_mode: 'auto',
  enable_h3c_derivation: true,
  colors: { ...DEFAULT_COLORS },
})
const preview = ref<AcOmniPeekPreview | null>(null)
const previewTaskId = ref('')
const previewLoading = ref(false)
const exportLoading = ref(false)
const statusFilter = ref('all')
const search = ref('')
const page = ref(1)
const pageSize = ref(100)
const selectedKeys = ref(new Set<string>())
const forceKeys = ref(new Set<string>())
const outputDirectory = ref('')
const outputDirectoryGranted = ref(false)
const destinationPath = ref('')
const savedCapabilityId = ref('')
let previewGeneration = 0
let previewTimer: number | undefined

const desktopHost = computed(() => getRuntimeConfig().hostType === 'electron')
const fileName = computed(() => `${safeFileName(config.line_name || '线路')}名称表.nam`)
const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const statistics = computed(() => preview.value?.statistics || {})
const sourceCounts = computed(() => preview.value?.source_counts || {})
const selectedCount = computed(() => selectedKeys.value.size)
const forceCount = computed(() => forceKeys.value.size)
const filterOptions = computed(() => [
  ['all', '全部', statistics.value.total || 0],
  ['selected', '已选', selectedCount.value],
  ['abnormal', '异常', statistics.value.abnormal || 0],
  ['mac_conflict', 'MAC 冲突', statistics.value.mac_conflict || 0],
  ['r2_failed', 'R2 推导失败', statistics.value.r2_failed || 0],
  ['missing_mac', '缺少物理 MAC', statistics.value.missing_mac || 0],
] as const)

const columns: NcTableColumn<AcOmniPeekPreviewItem>[] = [
  { key: 'selected', label: '勾选', valueType: 'selection', hideable: false, fixed: 'left' },
  { key: 'type_label', label: '类型', valueType: 'text' },
  { key: 'name', label: '名称', valueType: 'name', fixed: 'left' },
  { key: 'location', label: '归属站点 / 归属区间', valueType: 'text' },
  { key: 'physical_mac', label: '物理 MAC', valueType: 'mac' },
  { key: 'r1_mac', label: 'R1 导出 MAC', valueType: 'mac' },
  { key: 'r2_mac', label: 'R2 导出 MAC', valueType: 'mac' },
  { key: 'r1_source', label: 'R1 来源', valueType: 'text' },
  { key: 'r2_source', label: 'R2 来源', valueType: 'text' },
  { key: 'export_content', label: '导出内容', valueType: 'text' },
  { key: 'group', label: 'Group', valueType: 'text' },
  { key: 'color', label: 'Color', valueType: 'text' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'abnormal_reason', label: '异常说明', valueType: 'error' },
  { key: 'data_source', label: '数据来源', valueType: 'text' },
  { key: 'force_export', label: '强制导出', valueType: 'selection', hideable: false, fixed: 'right' },
]

watch(() => props.modelValue, (value) => {
  if (value) void initialize()
  else stopPreview()
}, { immediate: true })

watch([statusFilter, search], () => {
  page.value = 1
  void loadPreviewPage()
})

watch(page, () => { void loadPreviewPage() })
watch(pageSize, () => {
  page.value = 1
  void loadPreviewPage()
})

onBeforeUnmount(() => {
  if (previewTimer !== undefined) window.clearTimeout(previewTimer)
  stopPreview()
})

async function initialize(): Promise<void> {
  try {
    const preferences = await getAcOmniPeekPreferences()
    config.line_name = preferences.line_name || '线路'
    config.colors = { ...DEFAULT_COLORS, ...preferences.colors }
  } catch {
    config.colors = { ...DEFAULT_COLORS }
  }
  statusFilter.value = 'all'
  search.value = ''
  page.value = 1
  outputDirectory.value = window.localStorage.getItem('netconsole.ac.omnipeek.last-output-dir') || ''
  outputDirectoryGranted.value = false
  destinationPath.value = ''
  savedCapabilityId.value = ''
  await refreshPreview()
}

function schedulePreview(): void {
  if (previewTimer !== undefined) window.clearTimeout(previewTimer)
  previewTimer = window.setTimeout(() => { void refreshPreview() }, 220)
}

async function refreshPreview(): Promise<void> {
  if (!props.acId) return
  const generation = ++previewGeneration
  const previous = previewTaskId.value
  previewTaskId.value = ''
  preview.value = null
  selectedKeys.value = new Set()
  forceKeys.value = new Set()
  previewLoading.value = true
  if (previous) void cancelAcWebTask(previous).catch(() => undefined)
  try {
    const task = await startAcOmniPeekPreview(props.acId, props.apIds, { ...config, colors: { ...config.colors } })
    previewTaskId.value = task.task_id
    emit('task-submitted', task.task_id)
    const deadline = Date.now() + 120_000
    while (generation === previewGeneration && Date.now() < deadline) {
      const current = await getAcOmniPeekPreview(task.task_id, { page: 1, page_size: pageSize.value })
      if (current.ready) {
        preview.value = current
        selectedKeys.value = new Set(current.selected_item_keys)
        previewTaskId.value = ''
        return
      }
      if (['FAILED', 'CANCELLED'].includes(current.task_status)) throw new Error(current.message || 'OmniPeek 预览失败')
      await new Promise<void>((resolvePromise) => window.setTimeout(resolvePromise, 450))
    }
    if (generation === previewGeneration) throw new Error('OmniPeek 预览超时，请在任务中心查看')
  } catch (cause) {
    if (generation === previewGeneration) ElMessage.error(errorMessage(cause, 'OmniPeek 名称表预览失败'))
  } finally {
    if (generation === previewGeneration) previewLoading.value = false
  }
}

async function loadPreviewPage(): Promise<void> {
  if (!preview.value?.task_id || !preview.value.ready) return
  try {
    preview.value = await getAcOmniPeekPreview(preview.value.task_id, {
      page: page.value,
      page_size: pageSize.value,
      status_filter: statusFilter.value,
      search: search.value,
    })
  } catch (cause) {
    ElMessage.error(errorMessage(cause, '加载 OmniPeek 预览页失败'))
  }
}

function stopPreview(): void {
  previewGeneration += 1
  if (previewTaskId.value) void cancelAcWebTask(previewTaskId.value).catch(() => undefined)
  previewTaskId.value = ''
}

function toggleSelected(item: AcOmniPeekPreviewItem, checked: boolean): void {
  const next = new Set(selectedKeys.value)
  if (checked) next.add(item.item_key)
  else next.delete(item.item_key)
  selectedKeys.value = next
  if (!checked && forceKeys.value.has(item.item_key)) {
    const force = new Set(forceKeys.value)
    force.delete(item.item_key)
    forceKeys.value = force
  }
}

function toggleForce(item: AcOmniPeekPreviewItem, checked: boolean): void {
  const next = new Set(forceKeys.value)
  if (checked) next.add(item.item_key)
  else next.delete(item.item_key)
  forceKeys.value = next
}

function selectCurrentFilter(selected: boolean): void {
  const next = new Set(selectedKeys.value)
  for (const key of preview.value?.matching_item_keys || []) {
    if (selected) next.add(key)
    else next.delete(key)
  }
  selectedKeys.value = next
  if (!selected) {
    const force = new Set(forceKeys.value)
    for (const key of preview.value?.matching_item_keys || []) force.delete(key)
    forceKeys.value = force
  }
}

async function chooseOutputDirectory(): Promise<void> {
  if (!desktopHost.value) return
  const result = await getPlatformAdapter().selectDirectory()
  if (result.cancelled || !result.path) return
  outputDirectory.value = result.path
  outputDirectoryGranted.value = true
  destinationPath.value = ''
  window.localStorage.setItem('netconsole.ac.omnipeek.last-output-dir', result.path)
}

async function chooseOutputFile(): Promise<boolean> {
  if (!desktopHost.value) return true
  const result = await getPlatformAdapter().chooseSavePath({
    suggestedName: fileName.value,
    filters: [{ name: 'OmniPeek 名称表', extensions: ['nam'] }],
    ...(outputDirectoryGranted.value && outputDirectory.value ? { directoryPath: outputDirectory.value } : {}),
  })
  if (result.cancelled || !result.path) return false
  destinationPath.value = result.path
  outputDirectory.value = parentDirectory(result.path)
  window.localStorage.setItem('netconsole.ac.omnipeek.last-output-dir', outputDirectory.value)
  return true
}

async function exportNameTable(): Promise<void> {
  if (!preview.value || !selectedKeys.value.size) return
  if (forceKeys.value.size) {
    try {
      await ElMessageBox.confirm(
        `已选择强制导出 ${forceKeys.value.size} 条异常记录。请确认 MAC、Group 与颜色配置后继续。`,
        '确认强制导出异常项',
        { type: 'warning', confirmButtonText: '确认导出', cancelButtonText: '返回检查' },
      )
    } catch {
      return
    }
  }
  if (!await chooseOutputFile()) return
  exportLoading.value = true
  try {
    await saveAcOmniPeekPreferences(config.colors)
    const allKeys = new Set(preview.value.statistics.total ? preview.value.selected_item_keys : [])
    for (const key of preview.value.matching_item_keys) allKeys.add(key)
    const excluded = [...allKeys].filter((key) => !selectedKeys.value.has(key))
    const task = await startAcOmniPeekExport(props.acId, props.apIds, {
      ...config,
      colors: { ...config.colors },
      selected_item_keys: [...selectedKeys.value],
      excluded_item_keys: excluded,
      force_export_keys: [...forceKeys.value],
    })
    emit('task-submitted', task.task_id)
    const completed = await waitForExport(task.task_id)
    const result = await downloadBackendResource(acOmniPeekArtifactDownloadRequest(
      completed.artifact_id || task.artifact_id,
      fileName.value,
      destinationPath.value,
    ))
    if (result.status === 'saved' || result.status === 'started') {
      savedCapabilityId.value = result.capabilityId || ''
      ElMessage.success('OmniPeek 名称表已保存')
    } else if (result.status === 'failed') {
      throw new Error(result.error || '保存 OmniPeek 名称表失败')
    }
  } catch (cause) {
    ElMessage.error(errorMessage(cause, 'OmniPeek 名称表导出失败'))
  } finally {
    exportLoading.value = false
  }
}

async function waitForExport(taskId: string) {
  const deadline = Date.now() + 180_000
  while (Date.now() < deadline) {
    const task = await getAcWebTask(taskId)
    if (task.status === 'COMPLETED' && task.available && task.artifact_id) return task
    if (['FAILED', 'CANCELLED'].includes(task.status)) throw new Error(task.error_message || task.message || 'OmniPeek 导出任务失败')
    await new Promise<void>((resolvePromise) => window.setTimeout(resolvePromise, 500))
  }
  throw new Error('OmniPeek 导出超过 180 秒，请在任务中心查看')
}

async function openSavedDirectory(): Promise<void> {
  if (!savedCapabilityId.value) return
  const result = await getPlatformAdapter().showItemInFolder(savedCapabilityId.value)
  if (!result.success) ElMessage.error(result.error || '无法打开导出目录')
}

function sourceCount(key: string): number {
  return Number(sourceCounts.value[key] || 0)
}

function statusTagType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === '正常') return 'success'
  if (status === 'R2推导失败') return 'warning'
  return status ? 'danger' : 'info'
}

function safeFileName(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').replace(/[. ]+$/g, '').trim() || '线路'
}

function parentDirectory(value: string): string {
  const index = Math.max(value.lastIndexOf('\\'), value.lastIndexOf('/'))
  return index > 0 ? value.slice(0, index) : ''
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
</script>

<template>
  <el-dialog v-model="visible" title="导出 OmniPeek 名称表" width="min(1500px, 98vw)" top="2vh" class="omnipeek-dialog" :close-on-click-modal="false">
    <div class="omnipeek-body" v-loading="previewLoading || exportLoading">
      <el-card shadow="never" class="config-card">
        <template #header><strong>基础信息</strong></template>
        <el-form label-width="92px">
          <el-form-item label="线路名称"><el-input v-model="config.line_name" maxlength="200" @change="schedulePreview" /></el-form-item>
          <el-form-item label="输出文件名"><el-input :model-value="fileName" readonly /></el-form-item>
          <el-form-item label="输出目录">
            <div class="output-row"><el-input :model-value="outputDirectory || (desktopHost ? '请选择输出目录' : '浏览器受控下载')" readonly /><el-button :disabled="!desktopHost" @click="chooseOutputDirectory">浏览</el-button></div>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card shadow="never" class="config-card">
        <template #header><strong>数据源选择</strong></template>
        <div class="option-grid sources">
          <el-checkbox v-model="config.include_ac_fit_ap" @change="schedulePreview">AC FIT-AP资源：{{ sourceCount(SOURCE_AC) }} 条</el-checkbox>
          <el-checkbox v-model="config.include_ap_extensions" @change="schedulePreview">AP扩展信息：{{ sourceCount(SOURCE_EXTENSION) }} 条</el-checkbox>
          <el-checkbox v-model="config.include_device_mr" @change="schedulePreview">设备管理车载MR：{{ sourceCount(SOURCE_MR) }} 条</el-checkbox>
        </div>
      </el-card>

      <el-card shadow="never" class="config-card">
        <template #header><strong>导出内容</strong></template>
        <div class="content-layout">
          <div><span class="group-label">轨旁 AP</span><div class="option-grid"><el-checkbox v-model="config.export_trackside_physical" @change="schedulePreview">物理 MAC</el-checkbox><el-checkbox v-model="config.export_trackside_r1" @change="schedulePreview">R1 MAC</el-checkbox><el-checkbox v-model="config.export_trackside_r2" @change="schedulePreview">R2 MAC</el-checkbox></div></div>
          <div><span class="group-label">车载 MR</span><div class="option-grid"><el-checkbox v-model="config.export_onboard_physical" @change="schedulePreview">物理 MAC</el-checkbox><el-checkbox v-model="config.export_onboard_r1" @change="schedulePreview">R1 MAC</el-checkbox><el-checkbox v-model="config.export_onboard_r2" @change="schedulePreview">R2 MAC</el-checkbox></div></div>
          <div><span class="group-label">Radio 模式</span><el-select v-model="config.onboard_radio_mode" @change="schedulePreview"><el-option label="自动" value="auto" /><el-option label="仅 R1" value="r1_only" /><el-option label="仅 R2" value="r2_only" /><el-option label="R1 + R2" value="r1_r2" /><el-option label="不导出 Radio" value="none" /></el-select></div>
          <el-checkbox v-model="config.enable_h3c_derivation" @change="schedulePreview">启用 H3C 物理 MAC 推导 R1 / R2</el-checkbox>
        </div>
      </el-card>

      <el-card shadow="never" class="config-card">
        <template #header><strong>颜色配置</strong></template>
        <div class="color-grid"><label v-for="(label, key) in COLOR_LABELS" :key="key"><span>{{ label }}</span><el-color-picker v-model="config.colors[key]" @change="schedulePreview" /><code>{{ config.colors[key] }}</code></label></div>
      </el-card>

      <section class="preview-section">
        <div class="preview-toolbar">
          <div class="filter-buttons"><el-button v-for="item in filterOptions" :key="item[0]" :type="statusFilter === item[0] ? 'primary' : 'default'" :plain="statusFilter !== item[0]" @click="statusFilter = item[0]">{{ item[1] }} {{ item[2] }}</el-button></div>
          <el-input v-model="search" clearable placeholder="搜索名称、MAC、归属站点" class="preview-search" />
        </div>
        <div class="selection-toolbar"><span>共 {{ preview?.statistics.total || 0 }} 条 · 已选 {{ selectedCount }} 条 · 强制 {{ forceCount }} 条 · 当前筛选 {{ preview?.total || 0 }} 条</span><div><el-button @click="selectCurrentFilter(true)">全选当前筛选</el-button><el-button @click="selectCurrentFilter(false)">清空当前筛选</el-button></div></div>
        <NcDataTable table-id="ac-omnipeek-preview" route-key="/ac-management" :data="preview?.items || []" :columns="columns" :show-column-settings="false" height="420px" empty-text="暂无符合条件的预览行">
          <template #cell-selected="{ row }"><el-checkbox :model-value="selectedKeys.has(row.item_key)" @change="toggleSelected(row, Boolean($event))" /></template>
          <template #cell-status="{ row }"><el-tag :type="statusTagType(row.status)">{{ row.status }}</el-tag></template>
          <template #cell-color="{ row }"><span class="color-cell"><i :style="{ background: row.color.split(' / ')[0] }" />{{ row.color }}</span></template>
          <template #cell-force_export="{ row }"><el-checkbox :model-value="forceKeys.has(row.item_key)" :disabled="!row.force_export_allowed || !selectedKeys.has(row.item_key)" @change="toggleForce(row, Boolean($event))" /></template>
        </NcDataTable>
        <div class="pagination-row"><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[50, 100, 200, 500]" layout="total, sizes, prev, pager, next" :total="preview?.total || 0" /></div>
      </section>
    </div>
    <template #footer><div class="dialog-footer"><el-button :disabled="!savedCapabilityId" @click="openSavedDirectory">打开目录</el-button><span class="spacer" /><el-button @click="visible = false">关闭</el-button><el-button type="primary" :loading="exportLoading" :disabled="!preview?.ready || !selectedCount" @click="exportNameTable">导出</el-button></div></template>
  </el-dialog>
</template>

<style scoped>
.omnipeek-body { display: grid; gap: 10px; max-height: calc(96vh - 128px); overflow: auto; padding-right: 2px; }
.config-card :deep(.el-card__header) { padding: 10px 14px; }
.config-card :deep(.el-card__body) { padding: 12px 14px; }
.config-card :deep(.el-form-item:last-child) { margin-bottom: 0; }
.output-row { display: flex; width: 100%; gap: 8px; }
.option-grid { display: flex; flex-wrap: wrap; gap: 8px 24px; }
.option-grid.sources { justify-content: flex-start; }
.content-layout { display: grid; grid-template-columns: repeat(2, minmax(300px, 1fr)); gap: 12px 24px; }
.group-label { display: block; margin-bottom: 8px; color: var(--nc-text-secondary); font-size: 12px; }
.color-grid { display: grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: 10px 18px; }
.color-grid label { display: grid; grid-template-columns: minmax(120px, 1fr) auto 74px; align-items: center; gap: 8px; }
.color-grid code { color: var(--nc-text-secondary); font-size: 12px; }
.preview-section { min-height: 500px; padding: 12px; border: 1px solid var(--nc-border); border-radius: 8px; }
.preview-toolbar, .selection-toolbar, .pagination-row, .dialog-footer { display: flex; align-items: center; gap: 10px; }
.preview-toolbar, .selection-toolbar { justify-content: space-between; margin-bottom: 10px; }
.filter-buttons { display: flex; flex-wrap: wrap; gap: 6px; }
.preview-search { width: min(340px, 36vw); }
.selection-toolbar { color: var(--nc-text-secondary); font-size: 12px; }
.pagination-row { justify-content: flex-end; padding-top: 10px; }
.dialog-footer .spacer { flex: 1; }
.color-cell { display: inline-flex; align-items: center; gap: 6px; }
.color-cell i { width: 12px; height: 12px; border: 1px solid var(--nc-border); border-radius: 2px; }
@media (max-width: 1100px) { .content-layout, .color-grid { grid-template-columns: 1fr; } }
</style>
