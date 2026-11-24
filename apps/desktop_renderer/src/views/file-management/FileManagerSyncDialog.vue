<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RefreshRight } from '@element-plus/icons-vue'

import { synchronizeSftpDirectory, type SftpSyncComparison, type SftpSyncDirection, type SftpSyncPreview } from '../../api/terminal'
import { createFileManagerTranslator } from './fileManagementI18n'

const props = defineProps<{
  sessionId: string
  remoteDirectory: string
  localDirectoryId: string
  localDirectoryLabel: string
  allowDownload: boolean
}>()
const emit = defineEmits<{ submitted: [] }>()
const t = createFileManagerTranslator()
const visible = ref(false)
const busy = ref(false)
const direction = ref<SftpSyncDirection>(props.allowDownload ? 'both' : 'upload')
const comparison = ref<SftpSyncComparison>('modified')
const preview = ref<SftpSyncPreview>()
const error = ref('')
const directions = computed<SftpSyncDirection[]>(() => props.allowDownload ? ['both', 'upload', 'download'] : ['upload'])
const directionLabels = { both: 'syncBoth', upload: 'syncUpload', download: 'syncDownload' } as const
const comparisons: SftpSyncComparison[] = ['size', 'modified', 'sha256']
const actionLabels = { upload: 'syncUpload', download: 'syncDownload', conflict: 'syncConflict', same: 'syncSame', excluded: 'syncExcluded', ignored: 'syncIgnored' } as const

function resetPreview(): void {
  preview.value = undefined
  error.value = ''
}

watch([direction, comparison, () => props.localDirectoryId, () => props.remoteDirectory], resetPreview)

async function compare(apply: boolean): Promise<void> {
  const revision = apply ? preview.value?.revision : ''
  if (busy.value || (apply && !revision)) return
  busy.value = true
  error.value = ''
  try {
    const result = await synchronizeSftpDirectory(
      props.sessionId, props.remoteDirectory, props.localDirectoryId, direction.value, comparison.value, revision,
    )
    preview.value = apply ? undefined : result
    if (apply && result.queued.length) emit('submitted')
    if (result.error) error.value = result.error
    else if (apply) visible.value = false
  } catch (cause) {
    if (apply) preview.value = undefined
    error.value = cause instanceof Error ? cause.message : t('syncFailed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-button :icon="RefreshRight" :disabled="!localDirectoryId || !remoteDirectory" @click="visible = true">{{ t('sync') }}</el-button>
  <el-dialog v-model="visible" :title="t('sync')" width="min(780px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @closed="resetPreview">
    <div class="sync-paths"><span>{{ localDirectoryLabel }}</span><span>⇄</span><span>{{ remoteDirectory }}</span></div>
    <div class="sync-options">
      <el-select v-model="direction" :aria-label="t('syncDirection')" :disabled="busy">
        <el-option v-for="choice in directions" :key="choice" :label="t(directionLabels[choice])" :value="choice" />
      </el-select>
      <el-select v-model="comparison" :aria-label="t('syncComparison')" :disabled="busy">
        <el-option v-for="choice in comparisons" :key="choice" :label="choice === 'sha256' ? 'SHA-256' : t(choice)" :value="choice" />
      </el-select>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-table v-if="preview" :data="preview.rows" row-key="name" max-height="380" :empty-text="t('syncEmpty')">
      <el-table-column prop="name" :label="t('name')" min-width="130" show-overflow-tooltip />
      <el-table-column :label="t('syncStatus')" width="130">
        <template #default="{ row }">{{ t(actionLabels[row.action as keyof typeof actionLabels]) }}</template>
      </el-table-column>
      <el-table-column :label="t('syncLocalSize')" width="125">
        <template #default="{ row }">{{ row.local?.size ?? '—' }}</template>
      </el-table-column>
      <el-table-column :label="t('syncRemoteSize')" width="125">
        <template #default="{ row }">{{ row.remote?.size ?? '—' }}</template>
      </el-table-column>
    </el-table>
    <el-alert v-if="preview && preview.transfer_count && !preview.can_apply" :title="t('syncLimit')" type="warning" :closable="false" />
    <template #footer>
      <el-button :disabled="busy" @click="compare(false)">{{ t('syncPreview') }}</el-button>
      <el-button type="primary" :loading="busy" :disabled="!preview?.can_apply" @click="compare(true)">{{ t('syncApply') }}<span v-if="preview">&nbsp;({{ preview.transfer_count }})</span></el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.sync-paths, .sync-options { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-bottom: 12px; }
.sync-paths { overflow-wrap: anywhere; }
.sync-options .el-select { width: min(190px, 100%); }
</style>
