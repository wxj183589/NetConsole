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
import {
  getInfrastructure,
  getInfrastructureSwitchAps,
  type InfrastructureDevice,
  type InfrastructureNode,
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

const groups: { name: string; kinds: InfrastructureNode['kind'][] }[] = [
  { name: '控制中心', kinds: ['cocc', 'bocc'] },
  { name: '正线车站', kinds: ['station'] },
  { name: '区间', kinds: ['section'] },
  { name: '车辆段与停车场', kinds: ['depot', 'parking_yard'] },
  { name: '车载设备', kinds: ['train'] },
]
const node = computed(() => snapshot.value?.nodes.find((item) => item.uid === selectedUid.value))
const depotCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'depot' || item.kind === 'parking_yard').length ?? 0)
const stationCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'station').length ?? 0)
const sectionCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'section').length ?? 0)
const trainCount = computed(() => snapshot.value?.nodes.filter((item) => item.kind === 'train').length ?? 0)
const filteredGroups = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  const matches = (item: InfrastructureNode) => [
    item.code, item.name, ...item.aliases.map((alias) => alias.name), ...item.devices.map((device) => device.name),
  ].some((value) => value.toLocaleLowerCase().includes(query))
  return groups.map((group) => ({
    ...group,
    items: (snapshot.value?.nodes ?? []).filter((item) => group.kinds.includes(item.kind) && matches(item)),
  }))
})

function nodeLabel(item: InfrastructureNode): string {
  return [item.code, item.name].filter(Boolean).join(' ')
}

function deviceLabel(device: InfrastructureDevice): string {
  return device.role && device.role !== device.name ? `${device.role} · ${device.name}` : device.name
}

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
  compactPane.value = 'node'
}

async function selectDevice(device: InfrastructureDevice): Promise<void> {
  if (!await mayLeaveRelationship()) return
  apPage.value = 1
  selectedDevice.value = device
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
    const result = await getInfrastructure(props.siteId, controller.signal)
    if (controller.signal.aborted) return
    snapshot.value = result
    if (props.initialNodeUid && props.initialNodeUid !== selectedUid.value) {
      if (result.nodes.some(item => item.uid === props.initialNodeUid)) await selectNode(props.initialNodeUid)
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
    if (!controller.signal.aborted) error.value = '基础设施查询失败'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

watch(() => [props.siteId, selectedDevice.value?.device_uuid, apPage.value], async (_, __, cleanup) => {
  aps.value = undefined
  apUnavailable.value = false
  apLoading.value = false
  const device = selectedDevice.value
  if (!device || device.device_role !== 'switch') return
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
defineExpose({ confirmRelationshipNavigation: mayLeaveRelationship })
</script>

<template>
  <section class="infrastructure-workbench" aria-label="基础设施工作台">
    <header class="workbench-header" :aria-busy="loading">
      <div class="site-title">
        <strong>{{ snapshot?.line_name || '线路待配置' }}</strong>
        <el-tooltip v-if="node || showUnassociated" :content="node ? nodeLabel(node) : '未关联设备'" placement="bottom" :show-after="350">
          <span class="selected-node">{{ node ? nodeLabel(node) : '未关联设备' }}</span>
        </el-tooltip>
      </div>
      <dl v-if="snapshot" class="site-counts">
        <div><dt>线路设备</dt><dd>{{ snapshot.device_count }}</dd></div>
        <div><dt>车站</dt><dd>{{ stationCount }}</dd></div>
        <div><dt>区间</dt><dd>{{ sectionCount }}</dd></div>
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
      <nav class="workbench-column organization" aria-label="基础设施组织树">
        <button class="tree-root" type="button" :aria-pressed="!node && !showUnassociated" @click="selectNode()">{{ t('infrastructure.line_overview', '线路概览') }}</button>
        <details v-for="group in filteredGroups" :key="group.name" open>
          <summary>{{ group.name }} <span>{{ group.items.length }}</span></summary>
          <div v-for="item in group.items" :key="item.uid">
            <el-tooltip :content="nodeLabel(item)" placement="right" :show-after="350">
              <button class="tree-node" type="button" :aria-pressed="item.uid === selectedUid"
                @click="selectNode(item.uid)"><span class="tree-label">{{ nodeLabel(item) }}</span></button>
            </el-tooltip>
            <ul v-if="item.uid === selectedUid && item.devices.length" class="tree-devices">
              <li v-for="device in item.devices" :key="device.device_uuid">
                <el-tooltip :content="deviceLabel(device)" placement="right" :show-after="350">
                  <button class="tree-node" type="button" :aria-pressed="device.device_uuid === selectedDevice?.device_uuid"
                    @click="selectDevice(device)"><span class="tree-label">{{ deviceLabel(device) }}</span></button>
                </el-tooltip>
                <ul v-if="device.device_uuid === selectedDevice?.device_uuid && aps?.items.length" class="tree-aps">
                  <li v-for="ap in aps.items" :key="ap.row_id" :title="ap.ap_name || ap.ap_uuid" class="tree-label">{{ ap.ap_name || ap.ap_uuid }}</li>
                </ul>
              </li>
            </ul>
          </div>
          <div v-if="!group.items.length" class="tree-empty">{{ search ? '无匹配节点' : '待配置' }}</div>
        </details>
        <button v-if="snapshot" class="tree-node unassociated" type="button" :aria-pressed="showUnassociated"
          @click="selectNode('', true)">未关联设备 <span>{{ snapshot.unassociated_device_count }}</span></button>
      </nav>

      <div class="workbench-column node-content">
        <header class="section-heading">
          <h3>{{ showUnassociated ? '未关联设备' : node ? t('infrastructure.node_details', '工程资料') : t('infrastructure.line_overview', '线路概览') }}</h3>
          <el-button v-if="node?.station && isFeatureEnabled('capability.rail_transit.wireless_dashboard')" link type="primary" @click="router.push({ name: 'rail-transit-wireless-dashboard', query: { station_id: node.station.id } })">{{ t('engineering.wireless', '无线看板') }}</el-button>
        </header>
        <template v-if="node">
          <dl class="node-facts">
            <div v-if="node.code"><dt>{{ node.kind === 'train' ? '列车编号' : '编号' }}</dt><dd>{{ node.code }}</dd></div>
            <div><dt>正式名称</dt><dd>{{ node.name }}</dd></div>
            <div v-if="node.kind !== 'train' && node.projects.length"><dt>建设项目</dt><dd>{{ node.projects.map((item) => [item.stage, item.name].filter(Boolean).join(' ')).join('、') }}</dd></div>
            <div v-if="(node.kind === 'cocc' || node.kind === 'bocc') && node.ac_service_stations.length"><dt>AC 服务站点</dt><dd>{{ node.ac_service_stations.join('、') }}</dd></div>
            <div v-if="node.kind === 'train'"><dt>资料来源</dt><dd>{{ node.source === 'legacy_train' ? '既有列车资料' : '正式工程资料' }}</dd></div>
          </dl>
          <section v-if="node.aliases.length" class="node-section">
            <h4>名称记录</h4>
            <ul>
              <li v-for="(alias, index) in node.aliases" :key="index">
                {{ alias.name }} · {{ alias.name_type === 'engineering' ? '工程名称' : '历史名称' }}
                <span v-if="alias.source"> · {{ alias.source }}</span>
                <span v-if="alias.valid_from || alias.valid_to"> · {{ alias.valid_from || '起始未知' }} 至 {{ alias.valid_to || '当前' }}</span>
              </li>
            </ul>
          </section>
          <section v-if="node.sections.length && node.kind !== 'section'" class="node-section">
            <h4>相邻区间</h4>
            <details v-for="item in node.sections" :key="item.id"><summary>{{ item.name }}</summary><RelationshipEditor :site-id="siteId" :entity-uid="item.id" entity-kind="section" :entity-name="item.name" @busy-change="relationshipSaving=$event" @dirty-change="relationshipDirty=$event" @saved="retry++" /></details>
          </section>
          <RelationshipEditor :key="node.uid" :site-id="siteId" :entity-uid="node.uid" :entity-kind="node.kind" :entity-name="node.name" @busy-change="relationshipSaving=$event" @dirty-change="relationshipDirty=$event" @saved="retry++" />
        </template>
        <section v-if="node || showUnassociated" class="node-section">
          <h4>{{ showUnassociated ? '设备' : node?.kind === 'train' ? '车载 MR' : '关联设备' }}</h4>
          <ul v-if="(showUnassociated ? snapshot?.unassociated_devices : node?.devices)?.length" class="device-links">
            <li v-for="device in showUnassociated ? snapshot?.unassociated_devices : node?.devices" :key="device.device_uuid">
              <button type="button" class="device-link" :aria-pressed="selectedDevice?.device_uuid === device.device_uuid" @click="selectDevice(device)">
                <strong>{{ device.name }}</strong><span>{{ device.role || device.device_type }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="empty-state">{{ showUnassociated ? '没有未关联设备' : '工程关联待配置' }}</p>
        </section>
        <p v-else class="empty-state">选择组织树节点查看工程资料与设备。</p>
        <section v-if="selectedDevice?.device_role === 'switch'" class="node-section" aria-label="交换机下挂 AP">
          <h4>下挂 AP <span v-if="aps">{{ aps.total }}</span></h4>
          <p v-if="apLoading" class="empty-state">正在读取 LLDP 与 AP Identity</p>
          <p v-else-if="apUnavailable" class="empty-state">当前关联数据不可用</p>
          <p v-else-if="!aps?.items.length" class="empty-state">暂无经 LLDP 与 AP Identity 确认的接入</p>
          <ul v-else class="ap-links">
            <li v-for="ap in aps.items" :key="ap.row_id">
              <strong>{{ ap.ap_name || ap.ap_uuid }}</strong><span>{{ ap.interface_name || '端口未知' }}</span>
              <span>{{ ap.link_status || '状态未知' }}</span>
            </li>
          </ul>
          <el-pagination v-if="aps && aps.total > aps.page_size" v-model:current-page="apPage" small
            layout="prev, pager, next" :page-size="aps.page_size" :total="aps.total" />
        </section>
      </div>
      <aside class="workbench-column device-content" aria-label="设备详情">
        <h3 v-if="!selectedDevice">设备详情</h3>
        <DeviceDetailPanel v-if="selectedDevice" :key="selectedDevice.device_uuid" :device-uuid="selectedDevice.device_uuid" mode="page" />
        <RelationshipEditor v-if="selectedDevice?.device_role === 'wireless_controller'" :site-id="siteId" :entity-uid="selectedDevice.device_uuid" entity-kind="ac" :entity-name="selectedDevice.name" @busy-change="relationshipSaving=$event" @dirty-change="relationshipDirty=$event" @saved="retry++" />
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
.selected-node { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-node::before { content: '/'; margin-right: 12px; color: var(--nc-text-secondary); }
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
