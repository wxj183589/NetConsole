<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isFeatureEnabled } from '../../features'
import DeviceSftpTransferView from './DeviceSftpTransferView.vue'
import FileManagementView from './FileManagementView.vue'
import { createFileManagerTranslator } from './fileManagementI18n'

const route = useRoute()
const router = useRouter()
const t = createFileManagerTranslator()
const canTransfer = computed(() => isFeatureEnabled('capability.file_management.remote'))
const view = computed(() => canTransfer.value && route.query.view === 'sftp' ? 'sftp' : 'downloads')

function changeView(value: string | number | boolean | undefined): void {
  void router.replace({ query: { ...route.query, view: value === 'sftp' ? 'sftp' : undefined } })
}
</script>

<template>
  <section class="device-file-transfer">
    <el-radio-group v-if="canTransfer" :model-value="view" @change="changeView">
      <el-radio-button value="downloads">{{ t('managedDownloads') }}</el-radio-button>
      <el-radio-button value="sftp">{{ t('sftpTransfer') }}</el-radio-button>
    </el-radio-group>
    <DeviceSftpTransferView v-if="view === 'sftp'" class="transfer-content" />
    <FileManagementView v-else class="transfer-content" />
  </section>
</template>

<style scoped>
.device-file-transfer { display: flex; flex-direction: column; gap: 8px; min-height: 0; height: 100%; }
.transfer-content { flex: 1; min-height: 0; }
</style>
