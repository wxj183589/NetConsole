<script setup lang="ts">
import { computed, watch } from 'vue'
import type { GroundArchive } from '../../types/groundUnattended'
import { useGroundContext } from './useGroundUnattended'

const {
  Delete, Download, FolderOpened, NcDataTable, t, groundStatusLabel,
  archives, selectedArchives, archiveTableHost, archiveTableMaxHeight,
  archiveColumns, showArchive, removeArchive, removeSelectedArchives,
  downloadArchiveSummary, downloadArchiveZip, openArchiveDirectory,
  statusType, activeTab, pageVisible, pageActivated, quickContextRevision,
} = useGroundContext()

const selectedArchiveCount = computed(() => selectedArchives.value.length)
const active = computed(() => activeTab.value === 'archives' && pageVisible.value && pageActivated.value)

function onArchiveSelection(rows: GroundArchive[]): void {
  const byId = new Map<string, GroundArchive>()
  for (const row of rows) {
    if (row.archive_id) byId.set(row.archive_id, row)
  }
  selectedArchives.value = [...byId.values()]
}

function removeSelectedArchiveRows(): void {
  if (selectedArchiveCount.value) void removeSelectedArchives()
}

watch([active, quickContextRevision], ([visible]) => {
  if (!visible) selectedArchives.value = []
}, { immediate: true })
</script>

<template>
  <section class="ground-subpage archive-page">
    <div class="archive-heading">
      <div>
        <h3>{{ t('ground.history.archive_packages', '历史归档') }}</h3>
        <p class="archive-note">{{ t('ground.history.archive_note', '按运行日期保存每日无人值守压缩包；时间轴事件请在“时间轴”页面查询。') }}</p>
      </div>
      <div class="toolbar archive-actions">
        <span class="selection-count">{{ t('ground.history.selected_count', '已选择') }} {{ selectedArchiveCount }} {{ t('ground.history.archive_unit', '个归档包') }}</span>
        <el-button :icon="FolderOpened" @click="openArchiveDirectory">{{ t('ground.open_archive_directory', '打开归档目录') }}</el-button>
        <el-button type="danger" :disabled="selectedArchiveCount === 0" @click="removeSelectedArchiveRows">{{ t('ground.history.batch_delete', '批量删除') }}（{{ selectedArchiveCount }}）</el-button>
      </div>
    </div>
    <div ref="archiveTableHost" class="table-frame">
      <NcDataTable
        :data="archives"
        :columns="archiveColumns"
        table-id="ground-archives"
        route-key="rail-ground-unattended"
        row-key="archive_id"
        :max-height="archiveTableMaxHeight"
        auto-height
        compact
        :empty-text="t('ground.history.archive_empty', '当前没有每日归档包')"
        @selection-change="onArchiveSelection"
      >
        <template #cell-archive_status="{ row }"><el-tag size="small" :type="statusType(row.archive_status)">{{ groundStatusLabel(row.archive_status) }}</el-tag></template>
        <template #cell-integrity_status="{ row }"><el-tag size="small" :type="statusType(row.integrity_status)">{{ groundStatusLabel(row.integrity_status) }}</el-tag></template>
        <template #cell-actions="{ row }">
          <div class="row-actions">
            <el-button size="small" text type="primary" @click="showArchive(row)">{{ t('common.view', '查看') }}</el-button>
            <el-button :icon="Download" size="small" text circle :title="t('ground.history.download_zip', '下载原始 ZIP')" @click="downloadArchiveZip(row)" />
            <el-button size="small" text @click="downloadArchiveSummary(row)">JSON</el-button>
            <el-button :icon="Delete" size="small" text type="danger" circle :title="t('common.delete', '删除')" @click="removeArchive(row)" />
          </div>
        </template>
      </NcDataTable>
    </div>
  </section>
</template>

<style scoped src="./groundUnattended.css"></style>
<style scoped>
.archive-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}.archive-heading h3{margin-bottom:4px}.archive-note{margin:0;color:var(--nc-text-secondary);font-size:12px}.archive-actions{align-items:center;justify-content:flex-end}.selection-count{color:var(--nc-text-secondary);font-size:12px;white-space:nowrap}.row-actions{display:flex;align-items:center;gap:4px;flex-wrap:nowrap}
</style>
