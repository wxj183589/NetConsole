<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getMeshBusinessSummary, listMeshApSignalStatistics, listMeshSingleLinks } from '../../api/meshAnalysis'
import type { MeshBusinessSummary, MeshApSignal, MeshSingleLink } from '../../types/meshAnalysis'
import NcDataTable from '../table/NcDataTable.vue'
import type { NcTableColumn } from '../table/NcTableColumn'
import { meshBusinessText as mt } from '../../i18n/meshBusiness'

const props = defineProps<{ sessionId: string; revision?: string }>()
const emit = defineEmits<{ scopeChange: [scope: { exclude_depot: boolean; exclude_parking: boolean }] }>()
const summary = ref<MeshBusinessSummary | null>(null)
const error = ref('')
const detailError = ref('')
const summaryLoading = ref(false)
const loading = ref(false)
const visible = ref(false)
const risk = ref(false)
const grade = ref('')
const station = ref('')
const query = ref('')
const sort = ref('avg_rssi')
const descending = ref(false)
const excludeDepot = ref(true)
const excludeParking = ref(true)
const page = ref(1)
const total = ref(0)
const aps = ref<MeshApSignal[]>([])
const risks = ref<MeshSingleLink[]>([])
let generation = 0
let summaryController: AbortController | null = null
let detailController: AbortController | null = null
const gradeKeys = ['GOOD', 'WARNING', 'BAD', 'INSUFFICIENT', 'UNRECOGNIZED']
const gradeText = (value: string) => mt(value === 'RECOGNIZED' ? 'ap_total' : value)
const apColumns = computed<NcTableColumn<MeshApSignal>[]>(() => [
  { key: 'peer_ap_name', label: mt('ap_name'), valueType: 'name' },
  { key: 'peer_ap_mac', label: mt('ap_mac'), valueType: 'mac' },
  { key: 'station', label: mt('station') }, { key: 'section', label: mt('section') },
  ...['avg_rssi', 'min_rssi', 'max_rssi', 'p10_rssi', 'valid_sample_count', 'weak_sample_count'].map(key => ({ key, label: mt(key), valueType: 'number' as const })),
  { key: 'weak_ratio', label: mt('weak_ratio'), valueType: 'number', displayValue: row => row.weak_ratio == null ? '—' : `${(row.weak_ratio * 100).toFixed(2)}%` },
  { key: 'signal_grade', label: mt('signal_grade'), displayValue: row => gradeText(row.signal_grade) },
  { key: 'first_seen', label: mt('first_seen'), valueType: 'datetime' },
  { key: 'last_seen', label: mt('last_seen'), valueType: 'datetime' },
  { key: 'peer_mac_raw', label: mt('peer_evidence'), valueType: 'mac' },
])
const riskColumns = computed<NcTableColumn<MeshSingleLink>[]>(() => [
  { key: 'radio', label: 'Radio', valueType: 'number' },
  { key: 'peer_ap_name', label: mt('ap_name'), valueType: 'name' },
  { key: 'peer_ap_mac', label: mt('ap_mac'), valueType: 'mac' },
  { key: 'station', label: mt('station') }, { key: 'section', label: mt('section') },
  { key: 'start_time', label: mt('start_time'), valueType: 'datetime' },
  { key: 'end_time', label: mt('end_time'), valueType: 'datetime' },
  { key: 'duration_seconds', label: mt('duration_seconds'), valueType: 'number' },
  { key: 'standby_peer_count', label: mt('standby_count'), valueType: 'number' },
  { key: 'available_backup_count', label: mt('available_count'), valueType: 'number' },
  { key: 'best_backup_rssi', label: mt('best_backup_rssi'), valueType: 'number' },
  { key: 'risk_type', label: mt('risk_type'), displayValue: row => mt(row.risk_type) },
  { key: 'diagnosis', label: mt('diagnosis'), valueType: 'description' },
  { key: 'source_file_id', label: mt('source_file_id'), valueType: 'number' },
  { key: 'source_line_number_start', label: mt('line_start'), valueType: 'number' },
  { key: 'source_line_number_end', label: mt('line_end'), valueType: 'number' },
  { key: 'active_peer_mac', label: mt('peer_evidence'), valueType: 'mac' },
])

async function loadSummary() {
  summaryController?.abort()
  const controller = new AbortController()
  summaryController = controller
  const current = ++generation
  summaryLoading.value = true
  error.value = ''
  try {
    const result = await getMeshBusinessSummary(props.sessionId, scope.value, controller.signal)
    if (current === generation && !controller.signal.aborted) summary.value = result
  } catch (reason) {
    if (!controller.signal.aborted && current === generation) error.value = reason instanceof Error ? reason.message : mt('failed')
  } finally {
    if (current === generation) summaryLoading.value = false
  }
}
const scope = computed(() => ({ exclude_depot: excludeDepot.value, exclude_parking: excludeParking.value }))
function changeScope() {
  emit('scopeChange', scope.value)
  detailController?.abort()
  void loadSummary()
  if (visible.value) void loadDetails(true)
}
async function loadDetails(reset = false) {
  if (reset) page.value = 1
  detailController?.abort()
  const controller = new AbortController()
  detailController = controller
  loading.value = true
  detailError.value = ''
  try {
    if (risk.value) {
      const result = await listMeshSingleLinks(props.sessionId, { page: page.value, page_size: 50, ...scope.value }, controller.signal)
      if (controller !== detailController || controller.signal.aborted) return
      risks.value = result.items; total.value = result.total
    } else {
      const result = await listMeshApSignalStatistics(props.sessionId, {
        page: page.value, page_size: 50, query: query.value, station: station.value,
        signal_grade: grade.value, sort_by: sort.value, descending: descending.value,
        ...scope.value,
      }, controller.signal)
      if (controller !== detailController || controller.signal.aborted) return
      aps.value = result.items; total.value = result.total
    }
  } catch (reason) {
    if (!controller.signal.aborted && controller === detailController) detailError.value = reason instanceof Error ? reason.message : mt('failed')
  } finally {
    if (controller === detailController) loading.value = false
  }
}
function open(value: string, single = false) {
  grade.value = value; risk.value = single; query.value = ''; station.value = ''
  aps.value = []; risks.value = []; total.value = 0; visible.value = true
  void loadDetails(true)
}
function closeDetails() { detailController?.abort() }
watch(() => [props.sessionId, props.revision], () => {
  detailController?.abort(); visible.value = false; summary.value = null
  void loadSummary()
}, { immediate: true })
onBeforeUnmount(() => { generation++; summaryController?.abort(); detailController?.abort() })
</script>

<template>
  <section class="mesh-business-summary" :aria-busy="summaryLoading">
    <p v-if="summaryLoading" class="hint">{{ mt('loading') }}</p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"><el-button link @click="loadSummary">{{ mt('retry') }}</el-button></el-alert>
    <template v-if="summary">
      <div class="business-scope">
        <el-checkbox v-model="excludeDepot" @change="changeScope">排除车辆段 <span>{{ excludeDepot ? '已排除' : '已纳入' }}</span></el-checkbox>
        <el-checkbox v-model="excludeParking" @change="changeScope">排除停车场 <span>{{ excludeParking ? '已排除' : '已纳入' }}</span></el-checkbox>
      </div>
      <div class="business-cards">
        <button class="business-card" @click="open('RECOGNIZED')"><span>{{ mt('ap_total') }}</span><strong>{{ summary.ap_total }}</strong></button>
        <button v-for="key in gradeKeys" :key="key" class="business-card" @click="open(key)"><span>{{ gradeText(key) }}</span><strong>{{ summary.grades[key] || 0 }}</strong></button>
        <button class="business-card risk-card" @click="open('', true)"><span>{{ mt('single_link') }}</span><strong>{{ summary.single_link_count }}</strong><small>{{ summary.single_link_seconds }} s · {{ summary.single_link_ap_count }} AP · Radio {{ summary.single_link_radios.join(', ') || '—' }}</small></button>
      </div>
      <p class="hint">{{ mt('rule_note') }} {{ summary.good_threshold }} / {{ summary.warning_threshold }} · {{ mt('minimum') }} {{ summary.minimum_samples }} · {{ mt('backup_threshold') }} {{ summary.backup_available_threshold }}</p>
    </template>
    <el-dialog v-model="visible" :title="risk ? mt('single_link') : mt('ap_quality')" width="min(1500px, 96vw)" top="6vh" @closed="closeDetails">
      <div v-if="!risk" class="business-filters">
        <el-input v-model="query" :placeholder="mt('search')" clearable @keyup.enter="loadDetails(true)" />
        <el-input v-model="station" :placeholder="mt('station_filter')" clearable @keyup.enter="loadDetails(true)" />
        <el-select v-model="grade" :placeholder="mt('signal_grade')" clearable @change="loadDetails(true)"><el-option v-for="key in ['RECOGNIZED', ...gradeKeys]" :key="key" :label="gradeText(key)" :value="key" /></el-select>
        <el-select v-model="sort" @change="loadDetails(true)"><el-option v-for="key in ['avg_rssi', 'min_rssi', 'p10_rssi', 'max_rssi', 'peer_ap_name']" :key="key" :label="mt(key === 'peer_ap_name' ? 'ap_name' : key)" :value="key" /></el-select>
        <el-checkbox v-model="descending" @change="loadDetails(true)">{{ mt('descending') }}</el-checkbox>
        <el-button @click="loadDetails(true)">{{ mt('filter') }}</el-button>
      </div>
      <el-alert v-if="detailError" :title="detailError" type="warning" :closable="false"><el-button link @click="loadDetails()">{{ mt('retry') }}</el-button></el-alert>
      <NcDataTable v-if="risk" table-id="mesh-single-link:v1" route-key="/rail-transit/mesh-analysis" :data="risks" :columns="riskColumns" :loading="loading" height="min(540px, 56vh)" />
      <NcDataTable v-else table-id="mesh-ap-signal:v1" route-key="/rail-transit/mesh-analysis" :data="aps" :columns="apColumns" :loading="loading" height="min(540px, 56vh)" />
      <el-pagination v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="loadDetails()" />
    </el-dialog>
  </section>
</template>

<style scoped>
.business-cards { display: grid; grid-template-columns: repeat(6, minmax(90px, 1fr)) minmax(190px, 1.8fr); gap: 6px; }
.business-scope { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 6px; padding: 4px 8px; background: var(--el-fill-color-lighter); border: 1px solid var(--el-border-color-lighter); border-radius: 4px; }
.business-card { display: flex; min-height: 58px; flex-direction: column; align-items: flex-start; justify-content: center; gap: 2px; padding: 6px 10px; color: var(--el-text-color-primary); background: var(--el-fill-color-light); border: 1px solid var(--el-border-color); border-radius: 4px; cursor: pointer; }
.business-card:hover { border-color: var(--el-color-primary); }
.business-card span, .business-card small, .hint { color: var(--el-text-color-secondary); font-size: 12px; }
.business-card strong { font-size: 20px; line-height: 1.05; }
.business-filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.business-filters .el-input, .business-filters .el-select { width: 180px; }
@media (max-width: 1300px) { .business-cards { grid-template-columns: repeat(4, minmax(100px, 1fr)); } .risk-card { grid-column: span 2; } }
@media (max-width: 900px) { .business-cards { grid-template-columns: repeat(2, minmax(120px, 1fr)); } .risk-card { grid-column: span 2; } }
</style>
