<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { DeviceEngineeringContext } from '../../types/deviceManagement'
import { t } from '../../i18n/runtime'
import { isFeatureEnabled } from '../../features'

const props = defineProps<{ context?: DeviceEngineeringContext; historical?: boolean }>()
const router = useRouter()
const state = computed(() => props.context?.affiliation_status || 'unavailable')
const labels: Record<string, string> = { associated: '已关联', unassociated: '未关联', unavailable: '上下文不可用', conflict: '身份或关系冲突', stale: '上下文已过期', historical: '历史关系', not_found: '对象不存在', unconfirmed: '身份未确认' }
const title = computed(() => props.historical || props.context?.temporal_scope === 'historical' ? t('engineering.historical', '事件时工程上下文') : t('engineering.current', '当前工程上下文'))
const usable = computed(() => props.context?.available && ['associated', 'historical'].includes(state.value))
const current = computed(() => usable.value && !props.historical && props.context?.temporal_scope !== 'historical')
function node(uid: string): void {
  void router.push({ name: 'rail-transit-infrastructure', query: { node_uid: uid } })
}
</script>

<template>
  <section class="engineering-context" data-testid="engineering-context">
    <header>
      <strong>{{ title }}</strong>
      <span v-if="context?.device_name">{{ context.device_name }}</span>
      <el-tooltip :content="[context?.source, context?.context_updated_at, context?.relationship_revision, context?.reason_code].filter(Boolean).join(' · ')">
        <el-tag :type="['conflict', 'unavailable'].includes(state) ? 'danger' : ['stale', 'unconfirmed'].includes(state) ? 'warning' : 'info'">{{ t(`engineering.${state}`, labels[state] || state) }}</el-tag>
      </el-tooltip>
      <span v-if="historical || context?.temporal_scope === 'historical'">{{ context?.effective_at || '—' }}</span>
    </header>
    <dl v-if="usable">
      <dt v-if="context?.point_id">{{ t('engineering.identity', 'AP 身份状态') }}</dt><dd v-if="context?.point_id">{{ context.identity_status || t('engineering.unconfirmed', '身份未确认') }}</dd>
      <dt>{{ t('engineering.line', '线路') }}</dt><dd>{{ context?.line_name || '—' }}</dd>
      <dt>{{ t('engineering.node', '工程节点') }}</dt><dd><el-button v-if="current && context?.node_uid && isFeatureEnabled('module.rail_infrastructure')" link type="primary" @click="node(context.node_uid)">{{ context.node_name || context.node_uid }}</el-button><span v-else>{{ context?.node_name || '—' }}</span> {{ context?.role }}</dd>
      <dt>{{ t('engineering.section', '区间') }}</dt><dd>{{ context?.service_sections?.join(' / ') || '—' }}</dd>
      <dt>{{ t('engineering.project', '建设项目') }}</dt><dd>{{ context?.project_names.join(' / ') || '—' }}</dd>
      <dt>{{ t('engineering.location', '安装位置') }}</dt><dd>{{ context?.physical_location || '—' }}</dd>
      <dt>{{ t('engineering.service', '工程服务站点') }}</dt><dd>{{ context?.service_stations.join(' / ') || '—' }}</dd>
    </dl>
    <nav v-if="current">
      <el-button v-if="context?.device_uuid && isFeatureEnabled('module.devices')" link type="primary" @click="router.push({ name: 'device-detail', params: { deviceId: context.device_uuid } })">{{ t('engineering.asset', '设备资产') }}</el-button>
      <el-button v-if="context?.station_id && isFeatureEnabled('capability.rail_transit.wireless_dashboard')" link type="primary" @click="router.push({ name: 'rail-transit-wireless-dashboard', query: { station_id: context.station_id } })">{{ t('engineering.wireless', '无线看板') }}</el-button>
      <el-button v-if="context?.device_uuid && ['CT', 'CW', 'MR-CT', 'MR-CW'].includes(context.role) && isFeatureEnabled('module.online_mr')" link type="primary" @click="router.push({ name: 'online-mr-realtime', query: { mr_id: context.device_uuid } })">Online MR</el-button>
      <el-button v-for="scope in (context?.service_scope || []).filter(s => s.relationship_type === 'ac_service')" v-show="isFeatureEnabled('module.rail_infrastructure')" :key="scope.relationship_id" link type="primary" @click="node(scope.target_uid || '')">{{ scope.target_name || scope.target_uid }}</el-button>
    </nav>
  </section>
</template>

<style scoped>
.engineering-context{border-block-end:1px solid var(--el-border-color-light);padding:10px 0;min-width:0}
header,nav{display:flex;align-items:center;gap:12px;flex-wrap:wrap}header span{font-size:12px}dl{display:grid;grid-template-columns:90px minmax(0,1fr) 90px minmax(0,1fr);gap:6px 12px;font-size:13px;margin:10px 0}dt{color:var(--el-text-color-secondary)}dd{margin:0;overflow-wrap:anywhere}nav:empty{display:none}@media(max-width:900px){dl{grid-template-columns:90px minmax(0,1fr)}}
</style>
