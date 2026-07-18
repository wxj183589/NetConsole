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
</script>

<template>
  <main class="fixture-page">
    <h1>统一表格视觉夹具</h1>
    <p>用于验证表头下限、内容抽样、中文缺失值、状态标签、长文本和横向滚动。</p>
    <NcDataTable :data="rows" :columns="columns" table-id="visual-table-fixture" route-key="/__visual/table" max-height="520" :show-column-settings="false">
      <template #cell-status="{ row }"><el-tag :type="row.status === '在线' ? 'success' : 'danger'">{{ row.status }}</el-tag></template>
      <template #cell-actions="{ row }"><el-button link type="primary">{{ row.actions }}</el-button></template>
    </NcDataTable>
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
</style>
