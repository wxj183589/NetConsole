<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRailInfrastructureStore } from '../../../stores/railInfrastructure'
import { t } from '../../../i18n/runtime'
import { useRouter } from 'vue-router'
import { isFeatureEnabled } from '../../../features'
import { ElMessageBox } from 'element-plus'
import DeviceDetailPanel from '../../device-detail/DeviceDetailPanel.vue'
import RelationshipEditor from './RelationshipEditor.vue'
import InfrastructureTreeNode from './InfrastructureTreeNode.vue'
import { hierarchyGroups, nodeFields, nodeLabel, uniqueDevices } from './infrastructurePresentation'
import { getDeviceOverview } from '../../../api/deviceManagement'
import type { DeviceOverviewResponse } from '../../../types/deviceManagement'
import {
  getInfrastructure,
  getInfrastructureSwitchAps,
  initializeInfrastructure,
  type InfrastructureDevice,
  type InfrastructureSwitchAps,
} from '../../../api/railInfrastructure'

const props = defineProps<{ siteId: string; revisionKey?: string; initialNodeUid?: string }>()
const router = useRouter()
const { snapshot, loading, error, search, selectedUid, showUnassociated, selectedDevice, retry } = storeToRefs(useRailInfrastructureStore())
const compactPane = ref<'node' | 'device'>(selectedDevice.value ? 'device' : 'node')
const relationshipDirty = ref(false)
const relationshipSaving = ref(false)
const aps = ref<InfrastructureSwitchAps>()
const apPage = ref(1)
const apLoading = ref(false)
const apUnavailable = ref(false)
const selectedAp = ref<InfrastructureSwitchAps['items'][number]>()
const deviceOverview = ref<DeviceOverviewResponse>()
const deviceQueryFailed = ref(false)
const nodeApCount = ref<number>()
const nodeApFailed = ref(false)
const nodeApLoading = ref(false)
const relationshipNodeUid = ref('')

const node = computed(() => snapshot.value?.nodes.find((item) => item.uid === selectedUid.value && item.kind !== 'section'))
const depotCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'depot' || item.kind === 'parking_yard').length ?? 0)
const stationCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'station').length ?? 0)
const trainCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'train').length ?? 0)
const filteredGroups = computed(() => hierarchyGroups(snapshot.value, search.value))
const fields = computed(() => node.value ? nodeFields(node.value) : [])
const devices = computed(() => uniqueDevices((showUnassociated.value ? snapshot.value?.unassociated_devices : node.value?.devices) ?? []))
const historyNames = computed(() => node.value?.aliases.filter(alias => alias.name.trim() && alias.name !== node.value?.name && (alias.name_type !== 'engineering' || alias.valid_to)) ?? [])
const relationshipNode = computed(() => snapshot.value?.nodes.find(item => item.uid === relationshipNodeUid.value) || node.value)

async function mayLeaveRelationship(): Promise<boolean> {
  if (relationshipSaving.value) return false
  if (!relationshipDirty.value) return true
  try { await ElMessageBox.confirm('放弃未保存的关系草稿？', '确认', { confirmButtonText: '确认', cancelButtonText: '取消' }); relationshipDirty.value = false; return true } catch { return false }
}
async function selectNode(uid = '', unassociated = false): Promise<void> {
  if (!await mayLeaveRelationship()) return
  selectedUid.value = uid
  showUnassociated.value = unassociated
  selectedDevice.value = undefined
  selectedAp.value = undefined
  relationshipNodeUid.value = ''
  compactPane.value = 'node'
}

async function selectDevice(device: InfrastructureDevice): Promise<void> {
  if (!await mayLeaveRelationship()) return
  apPage.value = 1
  selectedDevice.value = device
  selectedAp.value = undefined
  relationshipNodeUid.value = ''
  compactPane.value = 'device'
}

watch(() => [props.siteId, props.revisionKey, props.initialNodeUid, retry.value], async (_, __, cleanup) => {
  if (!props.siteId) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  if (snapshot.value?.site_id !== props.siteId) {
    snapshot.value = undefined
    selectNode()
  }
  error.value = ''
  loading.value = true
  try {
    const siteId = props.siteId
    let result = await getInfrastructure(siteId, controller.signal)
    if (!controller.signal.aborted && result.schema_available && result.organization_initialized === false && isFeatureEnabled('capability.rail_infrastructure.write')) {
      result = await initializeInfrastructure(siteId, controller.signal)
    }
    if (controller.signal.aborted) return
    snapshot.value = result
    if (props.initialNodeUid && props.initialNodeUid !== selectedUid.value) {
      if (result.nodes.some(item => item.uid === props.initialNodeUid && item.kind !== 'section')) await selectNode(props.initialNodeUid)
      else {
        await selectNode()
        error.value = t('engineering.missing_node', '工程节点不可用或已不存在')
      }
    }
    if (selectedUid.value && !node.value) selectNode()
    const candidates = showUnassociated.value ? result.unassociated_devices : node.value?.devices
    if (selectedDevice.value && !candidates?.some((item) => item.device_uuid === selectedDevice.value?.device_uuid)) {
      selectedDevice.value = undefined
    }
  } catch {
    if (!controller.signal.aborted) error.value = '组织结构查询失败'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

watch(() => [props.siteId, selectedDevice.value?.device_uuid, apPage.value], async (_, __, cleanup) => {
  aps.value = undefined
  apUnavailable.value = false
  apLoading.value = false
  const device = selectedDevice.value
  if (!device || device.device_role !== 'switch' || !isFeatureEnabled('module.trackside_ap')) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  apLoading.value = true
  try {
    const result = await getInfrastructureSwitchAps(props.siteId, device.device_uuid, apPage.value, controller.signal)
    if (!controller.signal.aborted) aps.value = result
  } catch {
    if (!controller.signal.aborted) apUnavailable.value = true
  } finally {
    if (!controller.signal.aborted) apLoading.value = false
  }
})
watch(() => [props.siteId, node.value?.uid, snapshot.value], async (_, __, cleanup) => {
  nodeApCount.value = undefined
  nodeApFailed.value = false
  nodeApLoading.value = false
  const selected = node.value
  if (!selected || !['station','depot','parking_yard'].includes(selected.kind) || !isFeatureEnabled('module.trackside_ap')) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  nodeApLoading.value = true
  try {
    const identities = new Set<string>()
    let complete = true
    for (const device of uniqueDevices(selected.devices).filter(device => device.device_role === 'switch')) {
      let currentPage = 1
      let page: InfrastructureSwitchAps
      do {
        page = await getInfrastructureSwitchAps(props.siteId, device.device_uuid, currentPage, controller.signal)
        if (controller.signal.aborted) return
        complete &&= !page.partial_data && !page.unavailable_sources?.length
        for (const ap of page.items) {
          if (!ap.ap_uuid || ap.identity_match_status === 'conflict') complete = false
          else identities.add(ap.ap_uuid)
        }
        currentPage++
      } while ((currentPage - 1) * page.page_size < page.total && page.items.length)
    }
    if (complete) nodeApCount.value = identities.size
  } catch {
    if (!controller.signal.aborted) nodeApFailed.value = true
  } finally {
    if (!controller.signal.aborted) nodeApLoading.value = false
  }
})
watch(() => [props.siteId, selectedDevice.value?.device_uuid], async (_, __, cleanup) => {
  deviceOverview.value = undefined
  deviceQueryFailed.value = false
  const device = selectedDevice.value
  if (!device || !isFeatureEnabled('module.devices')) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  try {
    const result = await getDeviceOverview(device.device_uuid, controller.signal)
    if (!controller.signal.aborted) deviceOverview.value = result
  } catch {
    if (!controller.signal.aborted) deviceQueryFailed.value = true
  }
})
async function selectAp(ap: InfrastructureSwitchAps['items'][number]) {
  if (!await mayLeaveRelationship()) return
  selectedAp.value = ap
  compactPane.value = 'device'
}
async function selectRelationshipNode(uid: string) {
  if (await mayLeaveRelationship()) relationshipNodeUid.value = uid
}
defineExpose({ confirmRelationshipNavigation: mayLeaveRelationship })
</script>

<template>
  <section class="infrastructure-workbench" aria-label="组织结构工作台">
    <header class="workbench-header" :aria-busy="loading">
      <div class="site-title">
        <strong>{{ snapshot?.line_name || '线路待配置' }}</strong>
      </div>
      <dl v-if="snapshot" class="site-counts">
        <div><dt>线路设备</dt><dd>{{ snapshot.device_count }}</dd></div>
        <div><dt>车站</dt><dd>{{ stationCount }}</dd></div>
        <div><dt>车辆段与停车场</dt><dd>{{ depotCount }}</dd></div>
        <div><dt>列车</dt><dd>{{ trainCount }}</dd></div>
        <div><dt>关联异常</dt><dd>{{ snapshot.unresolved_binding_count }}</dd></div>
      </dl>
      <label class="workbench-search">
        <span class="visually-hidden">搜索组织树</span>
        <input v-model="search" type="search" placeholder="搜索编号、名称、历史名称或设备">
      </label>
      <el-button :loading="loading" @click="retry++">{{ t('common.refresh', '刷新') }}</el-button>
      <div class="compact-switch" :aria-label="t('infrastructure.panes', '工作区视图')">
        <button type="button" :aria-pressed="compactPane === 'node'" @click="compactPane = 'node'">{{ t('infrastructure.node_details', '工程资料') }}</button>
        <button type="button" :aria-pressed="compactPane === 'device'" :disabled="!selectedDevice" @click="compactPane = 'device'">{{ t('infrastructure.device_details', '设备详情') }}</button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-loading="loading" class="workbench-columns" :data-compact-pane="compactPane">
      <nav class="workbench-column organization" aria-label="组织结构树">
        <button class="tree-root" type="button" :aria-pressed="!node && !showUnassociated" @click="selectNode()">{{ t('infrastructure.line_overview', '线路概览') }}</button>
        <details v-for="group in filteredGroups" :key="group.name" open>
          <summary>{{ group.name }} <span>{{ group.items.length }}</span></summary>
          <InfrastructureTreeNode v-for="item in group.items" :key="item.uid" :node="item" :label="nodeLabel(item)" :selected-uid="selectedUid" :selected-device-id="selectedDevice?.device_uuid" :aps="aps" @node="selectNode" @device="selectDevice" @ap="selectAp" />
          <div v-if="!group.items.length" class="tree-empty">{{ search ? '无匹配节点' : '待配置' }}</div>
        </details>
        <button v-if="snapshot" class="tree-node unassociated" type="button" :aria-pressed="showUnassociated"
          @click="selectNode('', true)">未关联设备 <span v-if="snapshot.unassociated_device_count">{{ snapshot.unassociated_device_count }}</span></button>
      </nav>

      <div class="workbench-column node-content">
        <header class="section-heading">
          <h3 class="selected-node">{{ selectedDevice ? t('infrastructure.device_context', '设备工程上下文') : showUnassociated ? '未关联设备' : node?.name ?? t('infrastructure.line_overview', '线路概览') }}</h3>
          <el-button v-if="node?.station && isFeatureEnabled('capability.rail_transit.wireless_dashboard')" link type="primary" @click="router.push({ name: 'rail-transit-wireless-dashboard', query: { station_id: node.station.id } })">{{ t('engineering.wireless', '无线看板') }}</el-button>
        </header>
        <template v-if="node && !selectedDevice">
          <dl class="node-facts">
            <div v-for="field in fields" :key="field.label"><dt>{{ t(`infrastructure.field.${field.label}`, field.label) }}</dt><dd><template v-if="node.kind === 'train' && field.label.startsWith('MR-') && devices.some(device => device.role === field.label)"><button v-for="device in devices.filter(device => device.role === field.label)" :key="device.device_uuid" class="device-link" type="button" @click="selectDevice(device)">{{ device.name }}</button></template><template v-else>{{ t(`infrastructure.value.${field.value}`, field.value) }}</template></dd></div>
          </dl>
          <p v-if="['station','depot','parking_yard'].includes(node.kind)" class="empty-state">{{ t('infrastructure.switch_ap', '交换机关联 AP') }} · {{ nodeApLoading ? t('infrastructure.querying', '查询中') : nodeApFailed ? t('infrastructure.query_failed', '查询失败') : nodeApCount ?? t('infrastructure.count_unconfirmed', '数量未确认') }}</p>
          <details v-if="historyNames.length" class="node-section name-history">
            <summary>{{ t('infrastructure.name_history', '名称历史') }}</summary>
            <ul><li v-for="(alias, index) in historyNames" :key="index">{{ alias.name }}<span v-if="alias.valid_from || alias.valid_to"> · {{ alias.valid_from || '起始未知' }} 至 {{ alias.valid_to || '当前' }}</span></li></ul>
          </details>
          <details class="node-section engineering-relations">
            <summary>{{ t('infrastructure.relationships', '工程关系') }}</summary>
            <RelationshipEditor :key="node.uid" :site-id="siteId" :entity-uid="node.uid" :entity-kind="node.kind" :entity-name="node.name" @busy-change="relationshipSaving=$event" @dirty-change="relationshipDirty=$event" @saved="retry++" />
          </details>
        </template>
        <template v-if="selectedDevice">
          <p v-if="deviceQueryFailed" class="empty-state">{{ t('infrastructure.device_query_failed', '设备工程信息查询失败') }}</p>
          <dl class="node-facts">
            <div v-if="deviceOverview?.model"><dt>{{ t('infrastructure.model', '设备型号') }}</dt><dd>{{ deviceOverview.model }}</dd></div>
            <div v-if="node"><dt>{{ t('infrastructure.owner', '工程节点') }}</dt><dd>{{ node.name }}</dd></div>
            <div v-if="deviceOverview?.engineering_context?.physical_location"><dt>{{ t('infrastructure.location', '安装位置') }}</dt><dd>{{ deviceOverview.engineering_context.physical_location }}</dd></div>
          </dl>
          <details class="node-section engineering-relations">
            <summary>{{ t('infrastructure.relationships', '工程关系') }}</summary>
            <el-select v-if="showUnassociated && selectedDevice.device_role !== 'wireless_controller'" :model-value="relationshipNodeUid" :placeholder="t('infrastructure.select_engineering_node', '选择工程节点')" @update:model-value="selectRelationshipNode">
              <el-option v-for="item in snapshot?.nodes.filter(candidate => candidate.kind !== 'section')" :key="item.uid" :value="item.uid" :label="nodeLabel(item)" />
            </el-select>
            <RelationshipEditor v-if="relationshipNode || selectedDevice.device_role === 'wireless_controller'" :key="`${selectedDevice.device_uuid}:${relationshipNode?.uid || ''}`" :site-id="siteId" :entity-uid="selectedDevice.device_role === 'wireless_controller' ? selectedDevice.device_uuid : relationshipNode!.uid" :entity-kind="selectedDevice.device_role === 'wireless_controller' ? 'ac' : relationshipNode!.kind" :entity-name="selectedDevice.device_role === 'wireless_controller' ? selectedDevice.name : relationshipNode!.name" @busy-change="relationshipSaving=$event" @dirty-change="relationshipDirty=$event" @saved="retry++" />
          </details>
        </template>
        <section v-if="(node || showUnassociated) && !selectedDevice && node?.kind !== 'train'" class="node-section">
          <h4>{{ showUnassociated ? '设备' : '关联设备' }}</h4>
          <ul v-if="devices.length" class="device-links">
            <li v-for="device in devices" :key="device.device_uuid">
              <button type="button" class="device-link" @click="selectDevice(device)">
                <strong>{{ device.name }}</strong><span v-if="device.role !== device.name">{{ device.role || device.device_type }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="empty-state">{{ showUnassociated ? '没有未关联设备' : '工程关联待配置' }}</p>
        </section>
        <p v-if="!node && !showUnassociated && !selectedDevice" class="empty-state">选择组织树节点查看工程资料与设备。</p>
        <section v-if="selectedDevice?.device_role === 'switch' && isFeatureEnabled('module.trackside_ap')" class="node-section" aria-label="交换机下挂 AP">
          <h4>{{ t('infrastructure.switch_ap', '交换机关联 AP') }} <span v-if="aps && !aps.partial_data && !aps.unavailable_sources?.length">{{ aps.total }}</span></h4>
          <p v-if="apLoading" class="empty-state">正在读取 LLDP 与 AP Identity</p>
          <p v-else-if="apUnavailable" class="empty-state">当前关联数据不可用</p>
          <p v-else-if="aps?.partial_data || aps?.unavailable_sources?.length" class="empty-state">{{ t('infrastructure.ap_partial', '关联查询不完整，数量未确认') }}</p>
          <p v-if="!apLoading && !apUnavailable && !aps?.partial_data && !aps?.unavailable_sources?.length && !aps?.items.length" class="empty-state">暂无经 LLDP 与 AP Identity 确认的接入</p>
          <ul v-if="aps?.items.length" class="ap-links">
            <li v-for="ap in aps?.items" :key="ap.row_id">
              <button type="button" class="device-link" @click="selectAp(ap)">{{ ap.ap_name || t('infrastructure.identity_unconfirmed', '身份未确认') }}</button><span>{{ ap.interface_name || '端口未知' }}</span>
              <span>{{ ap.link_status || '状态未知' }}</span>
            </li>
          </ul>
          <el-pagination v-if="aps && aps.total > aps.page_size" v-model:current-page="apPage" small
            layout="prev, pager, next" :page-size="aps.page_size" :total="aps.total" />
        </section>
      </div>
      <aside class="workbench-column device-content" aria-label="设备详情">
        <h3 v-if="!selectedDevice">设备详情</h3>
        <DeviceDetailPanel v-if="selectedDevice" v-show="!selectedAp" :key="selectedDevice.device_uuid" :device-uuid="selectedDevice.device_uuid" mode="page" />
        <section v-if="selectedAp" class="ap-engineering-detail">
          <h3>{{ selectedAp.ap_name || t('infrastructure.identity_unconfirmed', '身份未确认') }}</h3>
          <dl class="node-facts">
            <div v-if="selectedAp.interface_name"><dt>{{ t('infrastructure.port', '交换机端口') }}</dt><dd>{{ selectedAp.interface_name }}</dd></div>
            <div><dt>{{ t('infrastructure.identity', 'AP 身份') }}</dt><dd>{{ selectedAp.identity_match_status || t('infrastructure.identity_unconfirmed', '身份未确认') }}</dd></div>
            <div v-if="selectedAp.primary_reason_label"><dt>{{ t('infrastructure.reason', '原因') }}</dt><dd>{{ selectedAp.primary_reason_label }}</dd></div>
            <div v-if="selectedAp.link_status"><dt>{{ t('infrastructure.link', '链路状态') }}</dt><dd>{{ selectedAp.link_status }}</dd></div>
          </dl>
          <el-button @click="selectedAp = undefined">{{ t('infrastructure.back_device', '返回设备详情') }}</el-button>
        </section>
        <p v-if="!selectedDevice" class="empty-state">选择设备查看接口、光模块和采集记录。</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.infrastructure-workbench { container-type: inline-size; display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; gap: 8px; }
.workbench-header { display: flex; flex: none; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.site-title { display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1 1 180px; }
.site-title strong { flex: none; }
.selected-node { overflow-wrap: anywhere; }

.site-title span, .site-counts dt, .empty-state, .tree-empty { color: var(--nc-text-secondary); font-size: 12px; }
.site-title strong { font-size: 16px; }
.site-counts { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 0; }
.site-counts > div { display: flex; align-items: baseline; gap: 5px; white-space: nowrap; }
.site-counts dd { margin: 0; font-weight: 650; }
.workbench-search { flex: 0 1 240px; min-width: 160px; }
.workbench-search input { width: 100%; min-height: 32px; padding: 0 10px; color: var(--nc-text-primary); background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 6px; }
.compact-switch { display: none; }
.compact-switch button { padding: 5px 10px; color: inherit; background: transparent; border: 1px solid var(--nc-border); border-radius: 5px; cursor: pointer; }
.compact-switch button:disabled { color: var(--nc-text-secondary); cursor: default; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.workbench-columns { display: grid; flex: 1; grid-template-columns: clamp(240px, 18cqw, 280px) clamp(340px, 28cqw, 420px) minmax(500px, 1fr); grid-template-rows: minmax(0, 1fr); min-width: 0; min-height: 0; border: 1px solid var(--nc-border); border-radius: 8px; overflow: hidden; }
.workbench-column { min-width: 0; min-height: 0; padding: 12px; overflow: auto; overscroll-behavior: contain; }
.workbench-column + .workbench-column { border-left: 1px solid var(--nc-border); }
.organization details { margin: 6px 0 10px; }
.node-section > summary { cursor: pointer; font-weight: 600; margin-bottom: 8px; }
.organization summary { padding: 6px; cursor: pointer; font-weight: 600; }
.organization summary span, .unassociated span { color: var(--nc-text-secondary); font-weight: 400; }
.tree-root, .tree-node, .device-link { display: block; width: 100%; padding: 7px 9px; color: inherit; text-align: left; background: transparent; border: 0; border-radius: 5px; cursor: pointer; }
.tree-root { font-weight: 650; }
.tree-node { padding-left: 16px; }
.tree-label { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.tree-devices, .tree-aps { list-style: none; padding-left: 17px; margin: 0; }
.tree-aps { font-size: 12px; color: var(--nc-text-secondary); }
.tree-empty { padding: 3px 16px; }
.tree-root:hover, .tree-node:hover, .device-link:hover, button[aria-pressed="true"] { background: var(--el-color-primary-light-9); }
button[aria-pressed="true"] { color: var(--el-color-primary); }
.section-heading, .device-link, .ap-links li { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; }
.section-heading h3, .device-content h3 { margin: 0 0 8px; font-size: 16px; overflow-wrap: anywhere; }
.node-facts { display: grid; gap: 6px; margin: 8px 0 12px; }
.node-facts div { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 8px; }
.node-facts dt, .device-link span, .ap-links span { color: var(--nc-text-secondary); }
.node-facts dd { margin: 0; overflow-wrap: anywhere; }
.node-section { border-top: 1px solid var(--nc-border); padding-top: 10px; margin-top: 12px; }
.node-section h4 { font-size: 14px; margin: 0 0 8px; }
.device-links, .ap-links { list-style: none; padding: 0; margin: 0; }
.ap-links li { padding: 6px 0; }
.device-content { display: flex; flex-direction: column; overflow: hidden; }
.device-content :deep(.device-detail-panel) { min-height: 0; flex: 1; height: auto; }
.device-content :deep(.detail-heading > div > p) { display: none; }
.device-content > .relationship-editor { flex: 0 1 auto; overflow: auto; }
@container (max-width: 1100px) {
  .workbench-columns { grid-template-columns: 240px minmax(0, 1fr); }
  .compact-switch { display: flex; gap: 6px; }
  .node-content, .device-content { grid-column: 2; grid-row: 1; }
  [data-compact-pane="node"] > .device-content, [data-compact-pane="device"] > .node-content { display: none; }
}
@container (max-width: 740px) {
  .workbench-columns { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(140px, .3fr) minmax(0, 1fr); }
  .organization { grid-column: 1; grid-row: 1; }
  .node-content, .device-content { grid-column: 1; grid-row: 2; border-left: 0; border-top: 1px solid var(--nc-border); }
  .site-counts { order: 1; flex-basis: 100%; }
}
</style>
