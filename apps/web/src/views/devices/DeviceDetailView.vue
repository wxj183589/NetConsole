<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import DeviceDetailPanel from '../../components/device-detail/DeviceDetailPanel.vue'

const route = useRoute()
const router = useRouter()
const deviceUuid = computed(() => String(route.params.deviceId || ''))

function backToDevices(): void {
  void router.push({ name: 'device-management' })
}
</script>

<template>
  <section class="device-detail-page">
    <div class="page-heading">
      <div>
        <el-button link :icon="ArrowLeft" @click="backToDevices">返回设备列表</el-button>
        <h1>设备完整详情</h1>
        <p>设备 {{ deviceUuid }} · 数据按后端能力分区加载</p>
      </div>
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
.page-heading { margin-bottom: 16px; }
.page-heading h1 { margin: 5px 0 0; }
.page-heading p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
</style>
