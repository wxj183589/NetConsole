<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import DeviceDetailPanel from '../../components/device-detail/DeviceDetailPanel.vue'
import { t } from '../../i18n/runtime'

const route = useRoute()
const router = useRouter()
const deviceUuid = computed(() => String(route.params.deviceId || ''))

function backToDevices(): void {
  void router.push({ name: 'device-archives' })
}
</script>

<template>
  <section class="device-detail-page">
    <div class="page-heading">
      <div>
        <el-button link :icon="ArrowLeft" @click="backToDevices">{{ t('device_archive.back', '返回档案列表') }}</el-button>
        <h1>{{ t('nav.device-archives', '设备档案') }}</h1>
      </div>
      <RouterLink :to="{ name: 'device-management' }">{{ t('device_archive.manage', '设备管理') }}</RouterLink>
    </div>
    <DeviceDetailPanel :device-uuid="deviceUuid" mode="page" />
  </section>
</template>

<style scoped>
.device-detail-page {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: calc(100dvh - var(--nc-shell-header-height) - var(--nc-content-padding) - var(--nc-content-padding));
  margin: 0;
}
.device-detail-page :deep(.device-detail-panel) { flex: 1; min-height: 0; }
.page-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.page-heading h1 { margin: 5px 0 0; }
</style>
