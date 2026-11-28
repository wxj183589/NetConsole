<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { listDevices } from '../../api/deviceManagement'
import { t } from '../../i18n/runtime'
import type { DevicePage } from '../../types/deviceManagement'
import { SITE_CONTEXT_CHANGED_EVENT } from '../../workspace/site-switch'

const searchInput = ref('')
const result = ref<DevicePage | null>(null)
const loading = ref(false)
const failed = ref(false)
const pageSize = 30
let search = ''
let generation = 0

async function load(page = 1): Promise<void> {
  const request = ++generation
  loading.value = true
  failed.value = false
  try {
    const response = await listDevices({ search, page, page_size: pageSize, work_scope_status: 'all' })
    if (request === generation) result.value = response
  } catch {
    if (request === generation) {
      result.value = null
      failed.value = true
    }
  } finally {
    if (request === generation) loading.value = false
  }
}

function submitSearch(): void {
  search = searchInput.value.trim()
  void load()
}

function reloadSite(): void {
  result.value = null
  void load()
}

onMounted(() => {
  window.addEventListener(SITE_CONTEXT_CHANGED_EVENT, reloadSite)
  void load()
})
onUnmounted(() => {
  generation++
  window.removeEventListener(SITE_CONTEXT_CHANGED_EVENT, reloadSite)
})
</script>

<template>
  <section class="device-archive-list">
    <h1>{{ t('nav.device-archives', '设备档案') }}</h1>
    <form class="archive-search" @submit.prevent="submitSearch">
      <el-input v-model="searchInput" :prefix-icon="Search" clearable :aria-label="t('device_archive.search', '搜索设备')" :placeholder="t('device_archive.search', '搜索设备')" @clear="submitSearch" />
      <el-button native-type="submit">{{ t('device_archive.search_action', '搜索') }}</el-button>
    </form>
    <el-alert v-if="failed" type="error" :closable="false" :title="t('device_archive.load_failed', '设备档案列表加载失败')" />
    <el-table v-else v-loading="loading" :data="result?.items ?? []" row-key="device_uuid" height="100%" :empty-text="t('device_archive.empty', '没有匹配的设备')">
      <el-table-column prop="name" :label="t('device_archive.name', '设备名称')" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <RouterLink :to="{ name: 'device-detail', params: { deviceId: row.device_uuid } }">{{ row.name || row.primary_address || row.device_uuid }}</RouterLink>
        </template>
      </el-table-column>
      <el-table-column prop="primary_address" :label="t('device_archive.address', '管理 IP')" min-width="140" show-overflow-tooltip />
      <el-table-column prop="group_name" :label="t('device_archive.group', '分组')" min-width="120" show-overflow-tooltip />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <RouterLink :to="{ name: 'device-detail', params: { deviceId: row.device_uuid } }">打开档案</RouterLink>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="result" :current-page="result.page" :page-size="pageSize" :total="result.total" layout="prev, pager, next" @current-change="load" />
  </section>
</template>

<style scoped>
.device-archive-list { display: flex; flex-direction: column; gap: 12px; min-width: 0; height: 100%; }
.device-archive-list h1 { margin: 0; }
.archive-search { display: flex; gap: 8px; width: min(380px, 100%); }
.device-archive-list :deep(.el-table) { flex: 1; min-height: 160px; }
</style>
