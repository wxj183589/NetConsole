<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, nextTick, ref, watch } from 'vue'

import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'
import NcDataTable from '../../table/NcDataTable.vue'
import type { NcTableColumn } from '../../table/NcTableColumn'
import { sortRailStations, sortTracksideApPlanRows, type PlanningStation } from './tracksideApPlanDraft'

interface ValidationIssue {
  rowIndex: number
  field: 'station_id' | 'sequence_no' | 'planned_ap_count' | 'management_vlan'
  message: string
}
type EditableField = 'sequence_no' | 'station_name' | 'planned_ap_count' | 'management_vlan' | 'remark'

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
let editingBaseline: { rowIndex: number; field: EditableField; value: unknown } | null = null
const rows = computed(() => sortTracksideApPlanRows(props.modelValue, props.stations))
const editable = computed(() => props.editing && !props.readonly && !props.saving)
const orderedStations = computed(() => sortRailStations(props.stations))
const linkedRows = computed(() => rows.value.filter((row) => row.relation_status === 'resolved'))
const pendingRows = computed(() => rows.value.filter((row) => row.relation_status !== 'resolved'))

const editableFields: EditableField[] = ['sequence_no', 'station_name', 'planned_ap_count', 'management_vlan', 'remark']
const planColumns = computed<NcTableColumn<TracksideApPlanRow>[]>(() => [
  { key: 'sequence_no', label: '序号', valueType: 'number', width: 72, align: 'center', hideable: false },
  { key: 'station_name', label: '车站名称', valueType: 'name', minWidth: 260, align: 'left', alignmentReason: 'long-text', hideable: false },
  { key: 'planned_ap_count', label: 'AP数量', valueType: 'number', width: 110, align: 'center' },
  { key: 'management_vlan', label: 'AP管理VLAN', valueType: 'number', width: 130, align: 'center' },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 360, align: 'left', alignmentReason: 'long-text' },
  { key: 'relation_status', label: '关联状态', valueType: 'status', width: 120, align: 'center' },
  ...(props.editing ? [{ key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 48, align: 'center', hideable: false } as NcTableColumn<TracksideApPlanRow>] : []),
  ...(props.editing ? [{ key: 'actions', label: '操作', valueType: 'actions', width: 64, align: 'center', fixed: 'right', hideable: false } as NcTableColumn<TracksideApPlanRow>] : []),
])

function copyRows(): TracksideApPlanRow[] {
  // Mutations address the parent model's identity/order; publish() applies
  // the canonical display order after the mutation.
  return JSON.parse(JSON.stringify(props.modelValue)) as TracksideApPlanRow[]
}

function publish(next: TracksideApPlanRow[]): void {
  const ordered = sortTracksideApPlanRows(next, props.stations)
  const issues = validate(ordered)
  emit('update:modelValue', ordered)
  emit('validation-change', issues.length === 0, issues)
}

function updateRow(row: TracksideApPlanRow, patch: Partial<TracksideApPlanRow>): void {
  const index = rowIndex(row)
  if (index < 0) return
  const next = copyRows()
  next[index] = { ...next[index], ...patch }
  publish(next)
}

function updateRequiredNumber(
  row: TracksideApPlanRow,
  field: 'sequence_no' | 'planned_ap_count',
  value: number | undefined,
): void {
  const normalized = Number(value)
  if (!Number.isFinite(normalized)) return
  updateRow(row, {
    [field]: normalized,
    ...(field === 'sequence_no'
      ? { planning_order: normalized, display_order: normalized }
      : {}),
  })
}

function rowIndex(row: TracksideApPlanRow): number {
  return props.modelValue.findIndex((candidate) => candidate === row || candidate.station_id === row.station_id)
}

function beginCellEdit(row: TracksideApPlanRow, field: EditableField): void {
  const index = rowIndex(row)
  if (index >= 0) editingBaseline = { rowIndex: index, field, value: field === 'station_name' ? { ...row } : row[field] }
}

function cancelCellEdit(row: TracksideApPlanRow, field: EditableField): void {
  const index = rowIndex(row)
  if (editingBaseline && editingBaseline.rowIndex === index && editingBaseline.field === field) {
    const next = copyRows()
    if (field === 'station_name') {
      next[index] = editingBaseline.value as TracksideApPlanRow
    } else {
      ;(next[index][field] as unknown) = editingBaseline.value
    }
    publish(next)
  }
  editingBaseline = null
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
}

function cellId(row: TracksideApPlanRow, field: EditableField): string {
  return `${rows.value.indexOf(row)}-${field}`
}

function focusNextRow(row: TracksideApPlanRow, field: EditableField): void {
  const nextIndex = rows.value.indexOf(row) + 1
  if (nextIndex >= rows.value.length) return
  void nextTick(() => document.querySelector<HTMLInputElement>(`[data-plan-cell="${nextIndex}-${field}"] input`)?.focus())
}

function assignPastedValue(row: TracksideApPlanRow, field: EditableField, value: string): void {
  const text = value.trim()
  if (field === 'sequence_no' || field === 'planned_ap_count') row[field] = Number(text)
  else if (field === 'management_vlan') row.management_vlan = text ? Number(text) : null
  else if (field === 'station_name') {
    const station = props.stations.find((item) => item.name.trim() === text)
    row.station_name = station?.name ?? text
    row.station_id = station?.id ?? ''
    row.sequence_no = station?.sort_order ?? row.sequence_no
    row.planning_order = null
    row.display_order = station?.sort_order ?? null
    row.relation_status = station ? 'resolved' : 'missing'
    row.candidate_station_ids = []
  } else row.remark = value
}

function blankRow(source: TracksideApPlanRow[] = rows.value): TracksideApPlanRow {
  return {
    station_id: '', station_name: '', sequence_no: Math.max(0, ...source.map((row) => Number(row.sequence_no) || 0)) + 1,
    planning_order: null,
    display_order: null,
    planned_ap_count: 0, management_vlan: null, remark: '', relation_status: 'missing', candidate_station_ids: [],
  }
}

function pasteGrid(event: ClipboardEvent, startRow: TracksideApPlanRow, startField: EditableField): void {
  if (!editable.value) return
  const text = event.clipboardData?.getData('text/plain') ?? ''
  if (!text) return
  event.preventDefault()
  const grid = text.replace(/\r/g, '').split('\n')
    .filter((line, index, all) => line.length > 0 || index < all.length - 1)
    .map((line) => line.split('\t'))
  const next = copyRows()
  const startRowIndex = Math.max(rowIndex(startRow), 0)
  const startColumnIndex = editableFields.indexOf(startField)
  for (let y = 0; y < grid.length; y += 1) {
    if (!next[startRowIndex + y]) next.push(blankRow(next))
    for (let x = 0; x < grid[y].length; x += 1) {
      const field = editableFields[startColumnIndex + x]
      if (!field) break
      assignPastedValue(next[startRowIndex + y], field, grid[y][x])
    }
  }
  publish(next)
}

function selectStation(row: TracksideApPlanRow, stationId: string): void {
  const station = props.stations.find((item) => item.id === stationId)
  updateRow(row, {
    station_id: stationId,
    station_name: station?.name ?? '',
    sequence_no: station?.sort_order ?? row.sequence_no,
    planning_order: null,
    display_order: station?.sort_order ?? null,
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
    sequence_no: station?.sort_order ?? Math.max(0, ...rows.value.map((row) => Number(row.sequence_no) || 0)) + 1,
    planning_order: null,
    display_order: station?.sort_order ?? null,
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

function removeRow(row: TracksideApPlanRow): void {
  const index = rowIndex(row)
  if (index < 0) return
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
watch(validationIssues, (issues) => emit('validation-change', issues.length === 0, issues), { immediate: true })

function cellError(row: TracksideApPlanRow, field: ValidationIssue['field']): string {
  const index = rowIndex(row)
  return validationIssues.value.find((issue) => issue.rowIndex === index && issue.field === field)?.message ?? ''
}
</script>

<template>
  <section class="planning-tab">
    <div class="planning-toolbar">
      <div>
        <h3>{{ editing ? 'AP 规划维护' : 'AP 规划' }}</h3>
        <p>{{ editing ? '规划只写入当前子页草稿，正式关联使用 station_id。' : '当前显示已保存的 AP 规划，正式关联使用 station_id。' }}</p>
      </div>
      <div v-if="editing" class="toolbar-actions">
        <el-button :disabled="!editable" @click="emit('request-generate-stations')">
          从设备管理匹配正式站点
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
      :title="`有 ${validationIssues.length} 项需要修正，当前子页保存已禁用。`"
    />

    <h4>已关联规划（{{ linkedRows.length }}）</h4>
    <div class="table-scroll">
      <NcDataTable
        table-id="rail-base-trackside-ap-planning"
        :columns="planColumns"
        :data="rows"
        row-key="station_id"
        route-key="/rail-transit/base-data"
        @selection-change="selectionChange"
      >
        <template #cell-sequence_no="{ row }">
          <div class="plan-cell numeric-plan-cell" :data-plan-cell="cellId(row, 'sequence_no')" :title="cellError(row, 'sequence_no')">
            <el-input-number v-if="editing" :model-value="row.sequence_no" :min="1" :controls="false" :disabled="!editable" :class="{ 'field-error': cellError(row, 'sequence_no') }" @focus="beginCellEdit(row, 'sequence_no')" @update:model-value="updateRequiredNumber(row, 'sequence_no', $event)" @paste="pasteGrid($event, row, 'sequence_no')" @keydown.enter.prevent="focusNextRow(row, 'sequence_no')" @keydown.esc.prevent="cancelCellEdit(row, 'sequence_no')" @wheel.prevent.stop />
            <span v-else>{{ row.sequence_no }}</span>
          </div>
        </template>
        <template #cell-station_name="{ row }">
          <div class="plan-cell" :data-plan-cell="cellId(row, 'station_name')" :title="cellError(row, 'station_id')">
            <el-select v-if="editing" :model-value="row.station_id" filterable :disabled="!editable" :class="{ 'field-error': cellError(row, 'station_id') }" @focus="beginCellEdit(row, 'station_name')" @change="selectStation(row, String($event))" @paste="pasteGrid($event, row, 'station_name')" @keydown.enter.prevent="focusNextRow(row, 'station_name')" @keydown.esc.prevent="cancelCellEdit(row, 'station_name')">
              <el-option v-for="station in orderedStations" :key="station.id" :label="station.name" :value="station.id" />
            </el-select>
            <span v-else>{{ row.station_name || '--' }}</span>
          </div>
        </template>
        <template #cell-planned_ap_count="{ row }">
          <div class="plan-cell numeric-plan-cell" :data-plan-cell="cellId(row, 'planned_ap_count')" :title="cellError(row, 'planned_ap_count')">
            <el-input-number v-if="editing" :model-value="row.planned_ap_count" :min="0" :controls="false" :disabled="!editable" :class="{ 'field-error': cellError(row, 'planned_ap_count') }" @focus="beginCellEdit(row, 'planned_ap_count')" @update:model-value="updateRequiredNumber(row, 'planned_ap_count', $event)" @paste="pasteGrid($event, row, 'planned_ap_count')" @keydown.enter.prevent="focusNextRow(row, 'planned_ap_count')" @keydown.esc.prevent="cancelCellEdit(row, 'planned_ap_count')" @wheel.prevent.stop />
            <span v-else>{{ row.planned_ap_count }}</span>
          </div>
        </template>
        <template #cell-management_vlan="{ row }">
          <div class="plan-cell numeric-plan-cell" :data-plan-cell="cellId(row, 'management_vlan')" :title="cellError(row, 'management_vlan')">
            <el-input-number v-if="editing" :model-value="row.management_vlan" :min="1" :max="4094" :controls="false" :disabled="!editable" :class="{ 'field-error': cellError(row, 'management_vlan') }" @focus="beginCellEdit(row, 'management_vlan')" @update:model-value="updateRow(row, { management_vlan: $event == null ? null : Number($event) })" @paste="pasteGrid($event, row, 'management_vlan')" @keydown.enter.prevent="focusNextRow(row, 'management_vlan')" @keydown.esc.prevent="cancelCellEdit(row, 'management_vlan')" @wheel.prevent.stop />
            <span v-else>{{ row.management_vlan ?? '--' }}</span>
          </div>
        </template>
        <template #cell-remark="{ row }">
          <div class="plan-cell" :data-plan-cell="cellId(row, 'remark')">
            <el-input v-if="editing" :model-value="row.remark" :disabled="!editable" @focus="beginCellEdit(row, 'remark')" @update:model-value="updateRow(row, { remark: String($event) })" @paste="pasteGrid($event, row, 'remark')" @keydown.enter.prevent="focusNextRow(row, 'remark')" @keydown.esc.prevent="cancelCellEdit(row, 'remark')" />
            <span v-else>{{ row.remark || '--' }}</span>
          </div>
        </template>
        <template #cell-relation_status="{ row }">
          <el-tag :type="row.relation_status === 'resolved' ? 'success' : 'warning'">{{ row.relation_status || 'missing' }}</el-tag>
        </template>
        <template #cell-actions="{ row }">
          <el-button text :icon="Delete" :disabled="!editable" title="删除" @click="removeRow(row)" />
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
.plan-cell { width: 100%; min-width: 0; box-sizing: border-box; }
.plan-cell :deep(.el-input-number),
.plan-cell :deep(.el-select),
.plan-cell :deep(.el-input) { width: 100%; min-width: 0; box-sizing: border-box; }
.numeric-plan-cell :deep(.el-input__inner) { text-align: center; }
.plan-cell :deep(.el-input-number .el-input__wrapper) { padding-inline: 8px; }
.plan-cell :deep(.field-error .el-input__wrapper) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; }
.pending-panel { padding: 12px; border: 1px solid var(--el-color-warning-light-5); border-radius: 8px; }
@media (max-width: 900px) { .planning-toolbar { flex-direction: column; } .toolbar-actions { justify-content: flex-start; } }
</style>
