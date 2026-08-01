<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'
import NcDataTable from '../../table/NcDataTable.vue'
import type { NcTableColumn } from '../../table/NcTableColumn'
import type { PlanningStation } from './tracksideApPlanDraft'

interface ValidationIssue {
  rowIndex: number
  field: 'station_id' | 'sequence_no' | 'planned_ap_count' | 'management_vlan'
  message: string
}

const props = withDefaults(defineProps<{
  modelValue: TracksideApPlanRow[]
  stations: PlanningStation[]
  editing: boolean
  readonly: boolean
  saving: boolean
}>(), {
  modelValue: () => [],
  stations: () => [],
})

const emit = defineEmits<{
  'update:modelValue': [rows: TracksideApPlanRow[]]
  'validation-change': [valid: boolean, issues: ValidationIssue[]]
  'request-generate-stations': []
}>()

const selectedRows = ref<TracksideApPlanRow[]>([])
const rows = computed(() => props.modelValue)
const editable = computed(() => props.editing && !props.readonly && !props.saving)
const orderedStations = computed(() => [...props.stations].sort((left, right) =>
  (left.sort_order ?? Number.MAX_SAFE_INTEGER) - (right.sort_order ?? Number.MAX_SAFE_INTEGER)
  || left.id.localeCompare(right.id)))
const linkedRows = computed(() => rows.value.filter((row) => row.relation_status === 'resolved'))
const pendingRows = computed(() => rows.value.filter((row) => row.relation_status !== 'resolved'))

const baseColumns: NcTableColumn<TracksideApPlanRow>[] = [
  { key: 'sequence_no', label: '序号', valueType: 'number', width: 90 },
  { key: 'station_name', label: '车站名称', valueType: 'name', minWidth: 210 },
  { key: 'planned_ap_count', label: 'AP数量', valueType: 'number', width: 120 },
  { key: 'management_vlan', label: 'AP管理VLAN', valueType: 'number', width: 140 },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 220 },
  { key: 'relation_status', label: '关联状态', valueType: 'status', width: 120 },
]
const columns = computed<NcTableColumn<TracksideApPlanRow>[]>(() => [
  ...(props.editing ? [{ key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 44, hideable: false } as NcTableColumn<TracksideApPlanRow>] : []),
  ...baseColumns,
  ...(props.editing ? [{ key: 'actions', label: '操作', valueType: 'actions', width: 68, hideable: false } as NcTableColumn<TracksideApPlanRow>] : []),
])

function copyRows(): TracksideApPlanRow[] {
  return JSON.parse(JSON.stringify(props.modelValue)) as TracksideApPlanRow[]
}

function publish(next: TracksideApPlanRow[]): void {
  const issues = validate(next)
  emit('update:modelValue', next)
  emit('validation-change', issues.length === 0, issues)
}

function updateRow(index: number, patch: Partial<TracksideApPlanRow>): void {
  const next = copyRows()
  next[index] = { ...next[index], ...patch }
  publish(next)
}

function selectStation(index: number, stationId: string): void {
  const station = props.stations.find((item) => item.id === stationId)
  updateRow(index, {
    station_id: stationId,
    station_name: station?.name ?? '',
    sequence_no: station?.sort_order ?? rows.value[index].sequence_no,
    relation_status: station ? 'resolved' : 'missing',
    candidate_station_ids: [],
  })
}

function addRow(): void {
  const used = new Set(rows.value.map((row) => row.station_id))
  const station = orderedStations.value.find((item) => !used.has(item.id))
  publish([...copyRows(), {
    station_id: station?.id ?? '',
    station_name: station?.name ?? '',
    sequence_no: station?.sort_order ?? rows.value.length + 1,
    planned_ap_count: 0,
    management_vlan: null,
    remark: '',
    relation_status: station ? 'resolved' : 'missing',
    candidate_station_ids: [],
  }])
}

function removeRows(targets: TracksideApPlanRow[]): void {
  const remove = new Set(targets.map((row) => `${row.station_id}\u0000${row.sequence_no}`))
  publish(copyRows().filter((row) => !remove.has(`${row.station_id}\u0000${row.sequence_no}`)))
  selectedRows.value = []
}

function removeRow(index: number): void {
  const next = copyRows()
  next.splice(index, 1)
  publish(next)
}

function selectionChange(selection: TracksideApPlanRow[]): void {
  selectedRows.value = selection
}

function validate(source: TracksideApPlanRow[]): ValidationIssue[] {
  const stationIds = new Set(props.stations.map((station) => station.id))
  const seen = new Set<string>()
  const issues: ValidationIssue[] = []
  source.forEach((row, rowIndex) => {
    if (!row.station_id || !stationIds.has(row.station_id) || row.relation_status !== 'resolved') {
      issues.push({ rowIndex, field: 'station_id', message: '必须选择有效的正式站点' })
    } else if (seen.has(row.station_id)) {
      issues.push({ rowIndex, field: 'station_id', message: '同一 station_id 只能有一行规划' })
    }
    seen.add(row.station_id)
    if (!Number.isInteger(row.sequence_no) || row.sequence_no <= 0) {
      issues.push({ rowIndex, field: 'sequence_no', message: '序号必须是正整数' })
    }
    if (!Number.isInteger(row.planned_ap_count) || row.planned_ap_count < 0) {
      issues.push({ rowIndex, field: 'planned_ap_count', message: 'AP数量必须是非负整数' })
    }
    if (row.management_vlan !== null
      && (!Number.isInteger(row.management_vlan) || row.management_vlan < 1 || row.management_vlan > 4094)) {
      issues.push({ rowIndex, field: 'management_vlan', message: 'VLAN 必须在 1～4094 范围内' })
    } else if (row.planned_ap_count > 0 && row.management_vlan === null) {
      issues.push({ rowIndex, field: 'management_vlan', message: 'AP数量大于 0 时必须填写 VLAN' })
    }
  })
  return issues
}

const validationIssues = computed(() => validate(rows.value))
</script>

<template>
  <section class="planning-tab">
    <div class="planning-toolbar">
      <div>
        <h3>{{ editing ? 'AP 规划维护' : 'AP 规划' }}</h3>
        <p>{{ editing ? '规划只写入页面统一草稿，正式关联使用 station_id。' : '当前显示已保存的 AP 规划，正式关联使用 station_id。' }}</p>
      </div>
      <div v-if="editing" class="toolbar-actions">
        <el-button :disabled="!editable" @click="emit('request-generate-stations')">
          从设备管理生成站点
        </el-button>
        <el-button :icon="Plus" :disabled="!editable" @click="addRow">新增规划行</el-button>
        <el-button :icon="Delete" :disabled="!editable || !selectedRows.length" @click="removeRows(selectedRows)">
          删除所选
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="editing && validationIssues.length"
      type="warning"
      :closable="false"
      :title="`有 ${validationIssues.length} 项需要修正，页面统一保存已禁用。`"
    />

    <h4>已关联规划（{{ linkedRows.length }}）</h4>
    <div class="table-scroll">
      <NcDataTable
        table-id="rail-base-trackside-ap-planning"
        :columns="columns"
        :data="rows"
        row-key="station_id"
        route-key="/rail-transit/base-data"
        @selection-change="selectionChange"
      >
        <template #cell-sequence_no="{ row, rowIndex }">
          <el-input-number v-if="editing" :model-value="row.sequence_no" :min="1" :disabled="!editable" @change="updateRow(rowIndex, { sequence_no: Number($event) })" />
          <span v-else>{{ row.sequence_no }}</span>
        </template>
        <template #cell-station_name="{ row, rowIndex }">
          <el-select v-if="editing" :model-value="row.station_id" :disabled="!editable" @change="selectStation(rowIndex, String($event))">
            <el-option v-for="station in orderedStations" :key="station.id" :label="station.name" :value="station.id" />
          </el-select>
          <span v-else>{{ row.station_name || '--' }}</span>
        </template>
        <template #cell-planned_ap_count="{ row, rowIndex }">
          <el-input-number v-if="editing" :model-value="row.planned_ap_count" :min="0" :disabled="!editable" @change="updateRow(rowIndex, { planned_ap_count: Number($event) })" />
          <span v-else>{{ row.planned_ap_count }}</span>
        </template>
        <template #cell-management_vlan="{ row, rowIndex }">
          <el-input-number v-if="editing" :model-value="row.management_vlan" :min="1" :max="4094" :disabled="!editable" @change="updateRow(rowIndex, { management_vlan: $event == null ? null : Number($event) })" />
          <span v-else>{{ row.management_vlan ?? '--' }}</span>
        </template>
        <template #cell-remark="{ row, rowIndex }">
          <el-input v-if="editing" :model-value="row.remark" :disabled="!editable" @update:model-value="updateRow(rowIndex, { remark: String($event) })" />
          <span v-else>{{ row.remark || '--' }}</span>
        </template>
        <template #cell-relation_status="{ row }">
          <el-tag :type="row.relation_status === 'resolved' ? 'success' : 'warning'">{{ row.relation_status || 'missing' }}</el-tag>
        </template>
        <template #cell-actions="{ rowIndex }">
          <el-button text :icon="Delete" :disabled="!editable" title="删除" @click="removeRow(rowIndex)" />
        </template>
      </NcDataTable>
    </div>

    <div v-if="pendingRows.length" class="pending-panel">
      <h4>待关联历史规划（{{ pendingRows.length }}）</h4>
      <p>历史站名仅作展示，请选择正式 station_id 或删除历史行后再保存。</p>
    </div>
  </section>
</template>

<style scoped>
.planning-tab { display: grid; gap: 14px; min-width: 0; }
.planning-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.planning-toolbar h3, .planning-toolbar p, h4 { margin: 0; }
.planning-toolbar p, .pending-panel p { margin-top: 6px; color: var(--el-text-color-secondary); }
.toolbar-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.table-scroll { width: 100%; overflow-x: auto; }
.pending-panel { padding: 12px; border: 1px solid var(--el-color-warning-light-5); border-radius: 8px; }
@media (max-width: 900px) { .planning-toolbar { flex-direction: column; } .toolbar-actions { justify-content: flex-start; } }
</style>
