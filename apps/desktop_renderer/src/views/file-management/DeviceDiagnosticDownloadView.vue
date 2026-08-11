<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'

import { listDevices, startDeviceDiagnosticDownload } from '../../api/deviceManagement'
import { isFeatureEnabled } from '../../features'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import type { DeviceListItem, DevicePage } from '../../types/deviceManagement'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'

const router = useRouter()
const userSelectedExport = useUserSelectedExport()
const emptyPage = (): DevicePage => ({
  items: [],
  groups: [],
  site_name: '',
  total: 0,
  page: 1,
  page_size: 50,
  total_pages: 1,
})

const pageData = ref<DevicePage>(emptyPage())
const loading = ref(false)
const error = ref('')
const search = ref('')
const groupFilter = ref('')
const selectedUuids = ref<string[]>([])
const deviceTable = ref<{ clearSelection(): void } | null>(null)

const deviceGroups = computed(() => [...pageData.value.groups].sort((left, right) => left.name.localeCompare(right.name)))
const selectedCount = computed(() => selectedUuids.value.length)
const deviceColumns: NcTableColumn<DeviceListItem>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', hideable: false },
  { key: 'name', label: '名称', valueType: 'name', measureValue: (row) => `${row.name} ${row.system_name}` },
  { key: 'group_name', label: '分组', valueType: 'text' },
  { key: 'device_type', label: '类型', valueType: 'text' },
  { key: 'station', label: '站点', valueType: 'text' },
  { key: 'primary_address', label: '主地址', valueType: 'ip' },
  { key: 'connection_status', label: '连接状态', valueType: 'status', cellKind: 'tag' },
]

onMounted(() => {
  void loadDevices()
})

async function loadDevices(resetPage = false): Promise<void> {
  loading.value = true
  error.value = ''
  if (resetPage) pageData.value.page = 1
  try {
    pageData.value = await listDevices({
      search: search.value.trim(),
      group_filter: groupFilter.value === '__ungrouped__'
        ? '__ungrouped__'
        : groupFilter.value
          ? Number(groupFilter.value)
          : undefined,
      page: pageData.value.page,
      page_size: pageData.value.page_size,
    })
    selectedUuids.value = selectedUuids.value.filter((deviceUuid) => pageData.value.items.some((item) => item.device_uuid === deviceUuid))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '设备列表加载失败'
  } finally {
    loading.value = false
  }
}

async function refresh(): Promise<void> {
  await loadDevices()
}

function changePage(page: number): void {
  pageData.value.page = page
  void loadDevices()
}

function changePageSize(pageSize: number): void {
  pageData.value.page_size = pageSize
  pageData.value.page = 1
  void loadDevices()
}

function selectionChange(rows: DeviceListItem[]): void {
  selectedUuids.value = rows.map((row) => row.device_uuid)
}

function clearSelection(): void {
  selectedUuids.value = []
  deviceTable.value?.clearSelection()
}

async function downloadDiagnostics(): Promise<void> {
  if (!selectedUuids.value.length) {
    ElMessage.warning('请先选择设备')
    return
  }
  try {
    const submitted = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'devices.diagnostics',
      suggestedName: `${safeFilePart(pageData.value.site_name || '当前局点')}-设备诊断-${localTimestamp()}.zip`,
      context: { scope: 'selected', requestedRowCount: selectedUuids.value.length },
      submit: () => startDeviceDiagnosticDownload(selectedUuids.value),
    })
    if (submitted.status === 'cancelled') return
    ElMessage.success('设备诊断下载任务已提交')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '设备诊断下载失败')
  }
}

async function openTaskCenter(): Promise<void> {
  try {
    if (window.netconsoleDesktop?.openTaskWindow) {
      const result = await window.netconsoleDesktop.openTaskWindow({ module: 'devices' })
      if (!result.success) ElMessage.error(result.error || '任务中心打开失败')
      return
    }
    await router.push({ name: 'tasks', query: { module: 'devices' } })
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '任务中心打开失败')
  }
}

function safeFilePart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || '导出'
}

function localTimestamp(now = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}
</script>

<template>
  <section class="device-diagnostic-downloads-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">LOCAL / DEVICE FILES</p>
        <h1>设备诊断下载</h1>
        <p>从设备管理中抽出的批量诊断包下载入口，结果仍通过统一 Task Center 与 Artifact 保存协调器处理。</p>
      </div>
      <div class="heading-actions">
        <el-button @click="openTaskCenter">任务中心</el-button>
        <el-button :loading="loading" :icon="Refresh" @click="refresh">刷新</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert
      v-else
      title="诊断下载沿用现有设备诊断任务与导出保存流程；取消另存不会创建额外任务。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="toolbar content-card">
      <el-input v-model="search" clearable :prefix-icon="Search" placeholder="搜索名称、地址、站点、类型或分组" @keyup.enter="loadDevices(true)" />
        <el-select v-model="groupFilter" clearable placeholder="全部分组" @change="loadDevices(true)">
          <el-option label="未分组" value="__ungrouped__" />
        <el-option v-for="group in deviceGroups" :key="group.id" :label="group.name" :value="String(group.id)" />
        </el-select>
      <div class="toolbar-actions">
        <el-button type="primary" :icon="Download" :disabled="!selectedCount || !isFeatureEnabled('capability.devices.collect')" @click="downloadDiagnostics">下载诊断</el-button>
        <el-button :disabled="!selectedCount" @click="clearSelection">清空选择</el-button>
        <el-button type="primary" plain :disabled="!search && !groupFilter" @click="loadDevices(true)">应用筛选</el-button>
      </div>
    </div>

    <div class="summary-row">
      <span>当前局点 <strong>{{ pageData.site_name || '当前局点' }}</strong></span>
      <span>设备 <strong>{{ pageData.total }}</strong></span>
      <span>已选 <strong>{{ selectedCount }}</strong></span>
    </div>

    <div v-loading="loading" class="content-card table-card">
      <NcDataTable
        ref="deviceTable"
        :data="pageData.items"
        :columns="deviceColumns"
        table-id="device-diagnostic-downloads"
        route-key="/device-files/diagnostics"
        row-key="device_uuid"
        height="100%"
        empty-text="暂无设备"
        @selection-change="selectionChange"
      />
      <el-pagination
        v-if="pageData.total"
        v-model:current-page="pageData.page"
        v-model:page-size="pageData.page_size"
        :total="pageData.total"
        :page-sizes="[20, 50, 100, 200]"
        layout="total, sizes, prev, pager, next"
        @current-change="changePage"
        @size-change="changePageSize"
      />
    </div>
  </section>
</template>

<style scoped>
.device-diagnostic-downloads-page{display:flex;flex-direction:column;gap:16px;min-width:0}
.page-heading,.toolbar,.heading-actions,.summary-row{display:flex;align-items:center;gap:10px}
.page-heading,.toolbar{justify-content:space-between}
.page-heading h1{margin:2px 0 6px}
.page-heading p,.summary-row{margin:0;color:var(--el-text-color-secondary)}
.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:0}
.content-card{padding:14px 16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px;overflow:hidden}
.toolbar{flex-wrap:wrap}
.toolbar .el-input{width:260px}
.toolbar .el-select{width:220px}
.toolbar-actions{display:flex;flex-wrap:wrap;gap:8px}
.summary-row{flex-wrap:wrap;gap:14px}
.table-card{display:flex;min-height:0;flex-direction:column;gap:10px}
.table-card :deep(.nc-data-table){min-height:420px}
.table-card :deep(.el-pagination){justify-content:flex-end;padding-top:10px}
strong{color:var(--el-text-color-primary)}
@media (max-width: 900px){
  .page-heading,.toolbar{align-items:flex-start;flex-direction:column}
  .toolbar .el-input,.toolbar .el-select{width:100%}
}
</style>
