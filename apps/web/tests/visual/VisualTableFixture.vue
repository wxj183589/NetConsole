<script setup lang="ts">
import NcDataTable from '../../src/components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../src/components/table/NcTableColumn'

interface FixtureRow {
  name: string
  address: string
  status: '在线' | '连接失败'
  description: string
  updatedAt: string
  actions: string
}

const rows: FixtureRow[] = [
  { name: '轨旁 AP 一号', address: '192.168.10.11', status: '在线', description: '短文本', updatedAt: '2026-07-19 08:30:00', actions: '查看' },
  { name: '设备名称包含较长中文字段用于表头和内容测量', address: '2001:db8::20', status: '连接失败', description: '这是一个超过普通列宽的长说明，用于确认表格区域保持横向滚动、单元格不挤压表头并提供省略显示。', updatedAt: '2026-07-19 08:31:00', actions: '查看 / 重试' },
  { name: 'Switch-GE-2/0/1', address: '10.0.0.1', status: '在线', description: '—', updatedAt: '—', actions: '更多' },
]

const columns: NcTableColumn<FixtureRow>[] = [
  { key: 'name', label: '完整设备名称', valueType: 'name' },
  { key: 'address', label: '主地址', valueType: 'ip' },
  { key: 'status', label: '连接状态', valueType: 'status', cellKind: 'tag' },
  { key: 'description', label: '错误与说明摘要', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
  { key: 'updatedAt', label: '最近更新时间', valueType: 'datetime' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['查看', '重试', '更多'] },
]

interface MeshLinkFixture {
  recordId: number
  timestamp: string
  timestampTag: string
  radio: number
  status: string
  peerMac: string
  peerName: string
  mrRssi: number
  peerRssi: number
  apMac: string
  station: string
  section: string
  peerRadio: string
  peerRadioMac: string
  establishTime: string
  duration: string
  linkCount: number
  mrNoise: number
  peerNoise: number
  mrRate: string
  peerRate: string
}

const meshRows: MeshLinkFixture[] = [
  {
    recordId: 634,
    timestamp: '2026-07-20 10:00:00.123',
    timestampTag: 'sample-634',
    radio: 1,
    status: 'ACTIVE',
    peerMac: '4073-4d65-064f',
    peerName: '宁波地铁1号线轨旁AP-中河路上行-01',
    mrRssi: 41,
    peerRssi: 39,
    apMac: '4073-4d65-0640',
    station: '宝幢站长站点名称',
    section: '宝幢站至邱隘东站上行区间',
    peerRadio: 'radio1',
    peerRadioMac: '4073-4d65-064f',
    establishTime: '2026-07-20 09:59:45.000',
    duration: '0d 00h 00m 15s',
    linkCount: 1,
    mrNoise: -92,
    peerNoise: -94,
    mrRate: '1201 Mbps / HE-MCS11',
    peerRate: '1201 Mbps / HE-MCS11',
  },
  {
    recordId: 633,
    timestamp: '2026-07-20 10:00:01.123',
    timestampTag: 'sample-633',
    radio: 1,
    status: 'STANDBY',
    peerMac: '1c94-6876-818f',
    peerName: '宁波地铁1号线轨旁AP-中河路下行-02',
    mrRssi: 30,
    peerRssi: 26,
    apMac: '1c94-6876-8180',
    station: '邱隘站长站点名称',
    section: '宝幢站至邱隘东站下行区间',
    peerRadio: 'radio1',
    peerRadioMac: '1c94-6876-818f',
    establishTime: '2026-07-20 09:59:41.000',
    duration: '0d 00h 00m 20s',
    linkCount: 2,
    mrNoise: -91,
    peerNoise: -93,
    mrRate: '600 Mbps / HE-MCS9',
    peerRate: '600 Mbps / HE-MCS9',
  },
]

const meshColumns: NcTableColumn<MeshLinkFixture>[] = [
  { key: 'recordId', label: '序号', valueType: 'number', width: 75, fixed: 'left', hideable: false },
  { key: 'timestamp', label: '采样时间', valueType: 'datetime', width: 215, hideable: false },
  { key: 'timestampTag', label: '采样标识', width: 120 },
  { key: 'radio', label: 'Radio', valueType: 'number', width: 80, hideable: false },
  { key: 'status', label: '状态', width: 90, hideable: false },
  { key: 'peerMac', label: 'PeerMac', valueType: 'mac', width: 145, hideable: false },
  { key: 'peerName', label: '当前 PEER AP 名称', valueType: 'name', width: 175 },
  { key: 'mrRssi', label: 'MR 侧 RSSI 差值', valueType: 'number', width: 130 },
  { key: 'peerRssi', label: 'Peer 侧 RSSI 差值', valueType: 'number', width: 140 },
  { key: 'apMac', label: 'AP MAC', valueType: 'mac', width: 145 },
  { key: 'station', label: '归属站点', width: 130 },
  { key: 'section', label: '归属区间', width: 190 },
  { key: 'peerRadio', label: 'PEER Radio', width: 105 },
  { key: 'peerRadioMac', label: 'Peer Radio MAC', valueType: 'mac', width: 145 },
  { key: 'establishTime', label: '建链时间', valueType: 'datetime', width: 210 },
  { key: 'duration', label: '链路时长', width: 140 },
  { key: 'linkCount', label: 'LinkCnt', valueType: 'number', width: 90 },
  { key: 'mrNoise', label: 'MR 侧底噪', valueType: 'number', width: 120 },
  { key: 'peerNoise', label: 'Peer 侧底噪', valueType: 'number', width: 120 },
  { key: 'mrRate', label: 'MR 侧协商速率', width: 170 },
  { key: 'peerRate', label: 'Peer 侧协商速率', width: 180 },
]
</script>

<template>
  <main class="fixture-page">
    <h1>统一表格视觉夹具</h1>
    <p>用于验证表头下限、内容抽样、中文缺失值、状态标签、长文本和横向滚动。</p>
    <NcDataTable :data="rows" :columns="columns" table-id="visual-table-fixture" route-key="/__visual/table" max-height="520" :show-column-settings="false">
      <template #cell-status="{ row }"><el-tag :type="row.status === '在线' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
      <template #cell-actions="{ row }"><el-button link type="primary">{{ row.actions }}</el-button></template>
    </NcDataTable>
    <section class="mesh-link-fixture" data-mesh-link-table>
      <h2>MESH 链路明细</h2>
      <NcDataTable :data="meshRows" :columns="meshColumns" table-id="visual-mesh-link-fixture" route-key="/__visual/mesh-link" height="340" border :show-column-settings="false" />
    </section>
  </main>
</template>

<style>
:root { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; color: #1f2937; background: #f4f7fb; }
* { box-sizing: border-box; }
body { margin: 0; min-width: 0; }
.fixture-page { min-height: 100vh; padding: 24px; }
.fixture-page h1 { margin: 0 0 8px; font-size: 24px; }
.fixture-page p { margin: 0 0 16px; color: #526174; }
.fixture-page .nc-data-table { background: #fff; padding: 12px; border: 1px solid #d9e2ef; border-radius: 8px; }
.mesh-link-fixture { margin-top: 24px; min-width: 0; }
.mesh-link-fixture h2 { margin: 0 0 12px; font-size: 18px; }
.mesh-link-fixture .nc-data-table { height: 340px; }
</style>
