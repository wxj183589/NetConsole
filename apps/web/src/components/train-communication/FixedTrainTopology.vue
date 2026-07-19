<script setup lang="ts">
import type { TrainCommunicationTopology, TrainCommunicationTopologyNode, TopologyStatus } from '../../types/trainCommunication'

const props = defineProps<{ topology: TrainCommunicationTopology | null; checking?: boolean }>()
const emit = defineEmits<{ selectNode: [node: TrainCommunicationTopologyNode] }>()

const statusLabels: Record<TopologyStatus, string> = {
  normal: '正常', abnormal: '异常', checking: '检测中', stale: '数据过期', not_detected: '未检测', not_configured: '未配置',
}
const statusClasses: Record<TopologyStatus, string> = {
  normal: 'is-normal', abnormal: 'is-abnormal', checking: 'is-checking', stale: 'is-stale', not_detected: 'is-not-detected', not_configured: 'is-not-configured',
}

function nodes(side: 'TC1' | 'TC2'): TrainCommunicationTopologyNode[] {
  const source = side === 'TC1' ? props.topology?.tc1_nodes : props.topology?.tc2_nodes
  return source || [
    { node_id: `${side}-MR`, side, role: 'MR', name: '', device_id: null, ip_address: null, status: 'not_detected', message: '', updated_at: null },
    { node_id: `${side}-SW`, side, role: 'SWITCH', name: '', device_id: null, ip_address: null, status: 'not_detected', message: '', updated_at: null },
    { node_id: `${side}-SRV`, side, role: 'SERVER', name: '', device_id: null, ip_address: null, status: 'not_detected', message: '', updated_at: null },
  ]
}
function node(side: 'TC1' | 'TC2', role: TrainCommunicationTopologyNode['role']): TrainCommunicationTopologyNode {
  return nodes(side).find((item) => item.role === role) || nodes(side)[role === 'MR' ? 0 : role === 'SWITCH' ? 1 : 2]
}
function roleLabel(role: TrainCommunicationTopologyNode['role']): string {
  return role === 'MR' ? 'MR' : role === 'SWITCH' ? '交换机' : '服务器'
}
function statusLabel(status: TopologyStatus): string { return statusLabels[status] || '未检测' }
function statusClass(status: TopologyStatus): string { return statusClasses[status] || 'is-not-detected' }
function currentStatus(status: TopologyStatus): TopologyStatus { return props.checking && status !== 'not_configured' ? 'checking' : status }
function nodeTitle(item: TrainCommunicationTopologyNode): string { return item.name || item.node_id }
function linkStatus(id: string): TopologyStatus {
  const status = props.topology?.links.find((item) => item.link_id === id)?.status || 'not_detected'
  return currentStatus(status)
}
function linkClass(id: string): string { return statusClass(linkStatus(id)) }
function linkLabel(id: string): string { return props.topology?.links.find((item) => item.link_id === id)?.label || '通信链路' }
</script>

<template>
  <section class="train-topology" aria-label="固定车载网络拓扑">
    <div class="topology-heading"><div><h2>车载通信拓扑</h2><p>固定 TC1 / TC2 两端节点与跨端链路</p></div><span class="topology-checked">{{ topology?.checked_at ? topology.checked_at.replace('T', ' ') : '未检测' }}</span></div>
    <div class="topology-canvas">
      <svg class="topology-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <line x1="20" y1="24" x2="20" y2="50" :class="linkClass('tc1-mr-sw')" />
        <line x1="20" y1="50" x2="20" y2="76" :class="linkClass('tc1-sw-srv')" />
        <line x1="80" y1="24" x2="80" y2="50" :class="linkClass('tc2-mr-sw')" />
        <line x1="80" y1="50" x2="80" y2="76" :class="linkClass('tc2-sw-srv')" />
        <line x1="28" y1="50" x2="72" y2="50" :class="linkClass('tc1-sw-tc2-sw')" />
      </svg>
      <div class="topology-grid">
        <div class="topology-end tc1-end"><h3>TC1 端 / 车头</h3><button v-for="item in [node('TC1', 'MR'), node('TC1', 'SWITCH'), node('TC1', 'SERVER')]" :key="item.node_id" class="topology-node" :class="statusClass(currentStatus(item.status))" @click="emit('selectNode', item)"><span class="node-status" :aria-label="statusLabel(currentStatus(item.status))"></span><strong :title="nodeTitle(item)">{{ nodeTitle(item) }}</strong><small>{{ roleLabel(item.role) }} · {{ item.ip_address || statusLabel(item.status) }}</small><em>{{ statusLabel(currentStatus(item.status)) }}</em></button></div>
        <div class="vrrp-panel"><strong>VRRP</strong><span :class="statusClass(currentStatus(topology?.vrrp.status || 'not_detected'))">{{ statusLabel(currentStatus(topology?.vrrp.status || 'not_detected')) }}</span><small>主端：{{ topology?.vrrp.master_side || '未知' }}</small><small v-if="topology?.vrrp.virtual_ip">虚拟 IP：{{ topology.vrrp.virtual_ip }}</small><small>{{ topology?.vrrp.message || '未检测' }}</small></div>
        <div class="topology-end tc2-end"><h3>TC2 端 / 车尾</h3><button v-for="item in [node('TC2', 'MR'), node('TC2', 'SWITCH'), node('TC2', 'SERVER')]" :key="item.node_id" class="topology-node" :class="statusClass(currentStatus(item.status))" @click="emit('selectNode', item)"><span class="node-status" :aria-label="statusLabel(currentStatus(item.status))"></span><strong :title="nodeTitle(item)">{{ nodeTitle(item) }}</strong><small>{{ roleLabel(item.role) }} · {{ item.ip_address || statusLabel(item.status) }}</small><em>{{ statusLabel(currentStatus(item.status)) }}</em></button></div>
      </div>
    </div>
    <div class="cross-end" :class="statusClass(checking ? 'checking' : topology?.cross_end.status || 'not_detected')"><strong>跨 TC 通信：{{ statusLabel(checking ? 'checking' : topology?.cross_end.status || 'not_detected') }}</strong><span>{{ topology?.cross_end.message || '未检测' }}</span></div>
    <div class="topology-links-legend"><span v-for="id in ['tc1-mr-sw', 'tc1-sw-srv', 'tc2-mr-sw', 'tc2-sw-srv', 'tc1-sw-tc2-sw']" :key="id"><i :class="['legend-line', linkClass(id)]"></i>{{ linkLabel(id) }}：{{ statusLabel(linkStatus(id)) }}</span></div>
  </section>
</template>

<style scoped>
.train-topology{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:10px;padding:18px}.topology-heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.topology-heading h2{margin:0 0 4px}.topology-heading p,.topology-checked{margin:0;color:var(--el-text-color-secondary);font-size:13px}.topology-canvas{position:relative;min-height:520px;margin-top:12px}.topology-links{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.topology-links line{stroke-width:1.2;vector-effect:non-scaling-stroke}.topology-links .is-normal{stroke:var(--el-color-success)}.topology-links .is-abnormal{stroke:var(--el-color-danger)}.topology-links .is-checking{stroke:var(--el-color-primary);stroke-dasharray:6 4}.topology-links .is-stale{stroke:var(--el-color-warning)}.topology-links .is-not-detected{stroke:var(--el-text-color-placeholder);stroke-dasharray:4 4}.topology-links .is-not-configured{stroke:var(--el-border-color)}.topology-grid{position:relative;display:grid;grid-template-columns:minmax(240px,1fr) 180px minmax(240px,1fr);gap:24px;align-items:stretch;height:100%;z-index:1}.topology-end{display:flex;flex-direction:column;gap:18px}.topology-end h3{text-align:center;margin:0;font-size:15px}.topology-node{width:220px;min-height:108px;margin:0 auto;border:1px solid var(--el-border-color);border-radius:8px;background:var(--el-bg-color-overlay);padding:12px;text-align:left;display:grid;grid-template-columns:16px 1fr;grid-template-rows:auto auto auto;column-gap:8px;cursor:pointer;color:var(--el-text-color-primary)}.topology-node:hover{border-color:var(--el-color-primary)}.topology-node strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.topology-node small{grid-column:2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--el-text-color-secondary)}.topology-node em{grid-column:2;font-style:normal;font-size:12px;margin-top:5px}.node-status{width:10px;height:10px;border-radius:50%;margin-top:4px;background:var(--el-text-color-placeholder)}.is-normal .node-status{background:var(--el-color-success)}.is-abnormal .node-status{background:var(--el-color-danger)}.is-checking .node-status{background:var(--el-color-primary)}.is-stale .node-status{background:var(--el-color-warning)}.vrrp-panel{align-self:center;justify-self:center;display:flex;flex-direction:column;align-items:center;gap:8px;min-width:140px;padding:16px;border:1px dashed var(--el-border-color);border-radius:8px;background:var(--el-fill-color-light)}.vrrp-panel strong{font-size:16px}.vrrp-panel span{font-weight:600}.vrrp-panel small{color:var(--el-text-color-secondary);text-align:center}.cross-end{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;padding:12px;margin-top:4px;border-radius:8px;background:var(--el-fill-color-light)}.cross-end span{color:var(--el-text-color-secondary)}.topology-links-legend{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:14px;color:var(--el-text-color-secondary);font-size:12px}.legend-line{display:inline-block;width:22px;border-top:2px solid var(--el-border-color);margin-right:5px;vertical-align:middle}.legend-line.is-normal{border-color:var(--el-color-success)}.legend-line.is-abnormal{border-color:var(--el-color-danger)}.legend-line.is-checking{border-color:var(--el-color-primary);border-top-style:dashed}.legend-line.is-stale{border-color:var(--el-color-warning)}.legend-line.is-not-detected{border-color:var(--el-text-color-placeholder);border-top-style:dashed}.legend-line.is-not-configured{border-color:var(--el-border-color)}
@media (max-width:900px){.topology-canvas{min-height:650px}.topology-grid{grid-template-columns:1fr 120px 1fr;gap:8px}.topology-node{width:100%;padding:10px}.vrrp-panel{min-width:100px}.topology-links-legend{display:grid;grid-template-columns:1fr 1fr}}
@media (max-width:680px){.topology-canvas{min-height:780px}.topology-grid{grid-template-columns:1fr;gap:12px}.vrrp-panel{order:2;justify-self:stretch}.tc2-end{order:3}.topology-links{display:none}.topology-node{max-width:360px}.topology-heading{flex-direction:column}}
</style>
