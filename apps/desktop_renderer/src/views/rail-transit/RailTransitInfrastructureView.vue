<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import InfrastructureWorkbench from '../../components/rail-transit/base-data/InfrastructureWorkbench.vue'
import { activeSiteContext, refreshSiteContext } from '../../stores/siteContext'
import { BEFORE_SITE_SWITCH_EVENT } from '../../workspace/site-switch'
import type { BeforeSiteSwitchDetail } from '../../workspace/site-switch'
import { t } from '../../i18n/runtime'

const route = useRoute()
const workbench = ref<InstanceType<typeof InfrastructureWorkbench>>()
const siteId = computed(() => activeSiteContext.value?.siteId || '')
const siteError = ref('')
async function loadSite(): Promise<void> {
  siteError.value = ''
  try { await refreshSiteContext() } catch { siteError.value = t('infrastructure.site_error', '当前局点查询失败') }
}
function beforeSiteSwitch(event: Event): void {
  const detail = (event as CustomEvent<BeforeSiteSwitchDetail>).detail
  detail.waitUntil(workbench.value?.confirmRelationshipNavigation() ?? Promise.resolve(true))
}
onMounted(() => { if (!siteId.value) void loadSite(); window.addEventListener(BEFORE_SITE_SWITCH_EVENT, beforeSiteSwitch) })
onBeforeUnmount(() => window.removeEventListener(BEFORE_SITE_SWITCH_EVENT, beforeSiteSwitch))
onBeforeRouteLeave(() => workbench.value?.confirmRelationshipNavigation() ?? true)
</script>

<template>
  <section class="rail-infrastructure" data-testid="infrastructure-page">
    <header v-if="!siteId"><h2>{{ t('infrastructure.title', '基础设施') }}</h2><el-button @click="loadSite()">{{ t('common.refresh', '刷新') }}</el-button></header>
    <el-alert v-if="siteError" :title="siteError" type="error" :closable="false" />
    <InfrastructureWorkbench v-if="siteId" ref="workbench" :site-id="siteId" :initial-node-uid="String(route.query.node_uid || '')" />
    <el-empty v-else :description="siteError || t('infrastructure.no_site', '请选择局点')" />
  </section>
</template>

<style scoped>
.rail-infrastructure { display: flex; flex-direction: column; height: 100%; min-width: 0; min-height: 0; gap: 8px; overflow: hidden; }
header { display: flex; justify-content: space-between; align-items: center; }
h2 { margin: 0; }
</style>
