<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getStorageAudit, type StorageAuditSnapshot } from '../api/storageAudit'

const snapshot = ref<StorageAuditSnapshot | null>(null)
const loading = ref(false)
const error = ref('')
const formatBytes = (bytes = 0) => {
  let value = Number(bytes) || 0
  for (const unit of ['B', 'KiB', 'MiB', 'GiB', 'TiB']) {
    if (value < 1024 || unit === 'TiB') return `${value.toFixed(unit === 'B' ? 0 : 2)} ${unit}`
    value /= 1024
  }
  return '0 B'
}
const topSites = computed(() => snapshot.value?.sites.slice(0, 10) || [])
const topDirectories = computed(() => snapshot.value?.directories.slice(0, 12) || [])
const topFiles = computed(() => snapshot.value?.largest_files.slice(0, 20) || [])
const databases = computed(() => snapshot.value?.databases.slice(0, 20) || [])

async function load(): Promise<void> {
  loading.value = true; error.value = ''
  try { snapshot.value = await getStorageAudit() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '存储审计报告加载失败'; ElMessage.error(error.value) }
  finally { loading.value = false }
}
onMounted(() => { void load() })
</script>

<template>
  <main class="storage-management" v-loading="loading">
    <header class="page-heading"><div><h1>存储管理</h1><p>只读查看已生成的 NetConsoleData 存储审计报告。</p></div><el-button data-testid="storage-refresh" :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template v-if="snapshot">
      <section class="overview-grid"><div><small>NetConsoleData 总容量</small><strong>{{ formatBytes(snapshot.total_size_bytes) }}</strong></div><div><small>文件数量</small><strong>{{ snapshot.total_files.toLocaleString() }}</strong></div><div><small>报告生成时间</small><strong>{{ snapshot.generated_at || '未记录' }}</strong></div></section>
      <section class="report-section"><h2>Site 占用排名</h2><el-table :data="topSites" stripe><el-table-column prop="site_name" label="Site" min-width="220"/><el-table-column label="容量" width="170"><template #default="scope">{{ formatBytes(scope.row.total_size_bytes) }}</template></el-table-column><el-table-column prop="total_files" label="文件数" width="130"/><el-table-column prop="percentage" label="占比" width="110"><template #default="scope">{{ scope.row.percentage == null ? '-' : `${Number(scope.row.percentage).toFixed(2)}%` }}</template></el-table-column></el-table><el-empty v-if="!topSites.length" description="暂无 Site 报告" /></section>
      <section class="report-section"><h2>目录占用排行</h2><el-table :data="topDirectories" stripe><el-table-column prop="path" label="目录" min-width="260"/><el-table-column label="容量" width="180"><template #default="scope">{{ formatBytes(scope.row.size_bytes) }}</template></el-table-column><el-table-column prop="file_count" label="文件数" width="130"/><el-table-column prop="percentage" label="占比" width="110"><template #default="scope">{{ scope.row.percentage == null ? '-' : `${Number(scope.row.percentage).toFixed(2)}%` }}</template></el-table-column></el-table><el-empty v-if="!topDirectories.length" description="暂无目录报告" /></section>
      <section class="report-section"><h2>TOP 大文件</h2><el-table :data="topFiles" stripe><el-table-column prop="path" label="文件" min-width="360" show-overflow-tooltip/><el-table-column label="大小" width="170"><template #default="scope">{{ formatBytes(scope.row.size_bytes) }}</template></el-table-column><el-table-column prop="modified_time" label="修改时间" width="220"/></el-table><el-empty v-if="!topFiles.length" description="暂无大文件报告" /></section>
      <section class="report-section"><h2>SQLite 数据库大小</h2><el-table :data="databases" stripe><el-table-column prop="database" label="数据库" min-width="340" show-overflow-tooltip/><el-table-column prop="site" label="Site" min-width="170"/><el-table-column label="大小" width="170"><template #default="scope">{{ formatBytes(scope.row.size_bytes) }}</template></el-table-column></el-table><el-empty v-if="!databases.length" description="暂无 SQLite 报告" /></section>
      <el-alert v-if="snapshot.errors.length" title="报告包含扫描异常，请查看原始报告详情。" type="warning" :description="snapshot.errors.join('\n')" show-icon />
    </template>
  </main>
</template>

<style scoped>
.storage-management{height:100%;overflow:auto;padding:24px;box-sizing:border-box;background:var(--nc-surface)}.page-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}.page-heading h1{margin:0 0 6px;font-size:22px}.page-heading p{margin:0;color:var(--nc-text-secondary)}.overview-grid{display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:10px;margin-bottom:18px}.overview-grid>div{padding:15px 16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:6px}.overview-grid small,.overview-grid strong{display:block}.overview-grid small{color:var(--nc-text-secondary);margin-bottom:6px}.overview-grid strong{font-size:20px}.report-section{margin:18px 0;padding:16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:6px}.report-section h2{margin:0 0 12px;font-size:16px}@media(max-width:800px){.storage-management{padding:16px}.overview-grid{grid-template-columns:1fr}.page-heading{align-items:stretch;flex-direction:column}}
</style>
