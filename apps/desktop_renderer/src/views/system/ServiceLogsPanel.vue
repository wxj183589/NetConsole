<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'

import { listLocalServices, readLocalServiceLogs, type ServiceLogEntry } from '../../api/localNetworkServices'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { serviceLogLabel as label } from '../../i18n/serviceLogs'

const services = ref<string[]>([])
const service = ref('')
const level = ref('')
const keyword = ref('')
const range = ref<[Date, Date] | null>(null)
const live = ref(true)
const history = ref(false)
const includeHistory = computed(() => history.value || Boolean(range.value))
const loading = ref(false)
const error = ref('')
const entries = ref<ServiceLogEntry[]>([])
const selected = ref<ServiceLogEntry>()
const columns = computed<NcTableColumn<ServiceLogEntry>[]>(() => [
  { key: 'time', label: label('time'), valueType: 'datetime' },
  { key: 'level', label: label('level'), valueType: 'status' },
  { key: 'message', label: label('message'), valueType: 'description', alignmentReason: 'long-text' },
])
let active = false
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined

function clearTimer(): void {
  if (timer) clearTimeout(timer)
  timer = undefined
}

async function load(): Promise<void> {
  clearTimer()
  if (!active || !service.value) return
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const result = await readLocalServiceLogs(service.value, {
      keyword: keyword.value.trim(), level: level.value,
      since: range.value?.[0].toISOString(), until: range.value?.[1].toISOString(),
      history: includeHistory.value,
    })
    if (!active || current !== generation) return
    entries.value = result.entries
    if (selected.value) selected.value = result.entries.find((entry) => entry.raw === selected.value?.raw)
  } catch (cause) {
    if (active && current === generation) error.value = cause instanceof Error ? cause.message : label('failed')
  } finally {
    if (active && current === generation) {
      loading.value = false
      if (live.value) timer = setTimeout(() => { void load() }, 2000)
    }
  }
}

async function activate(): Promise<void> {
  if (active) return
  active = true
  const current = ++generation
  try {
    const result = await listLocalServices()
    if (!active || current !== generation) return
    services.value = result.services.filter((item) => item.enabled).map((item) => item.id)
    if (!services.value.includes(service.value)) service.value = services.value[0] ?? ''
    else await load()
  } catch (cause) {
    if (active && current === generation) error.value = cause instanceof Error ? cause.message : label('failed')
  }
}

function deactivate(): void {
  active = false
  generation += 1
  loading.value = false
  clearTimer()
}

function refresh(): void {
  if (services.value.length) {
    void load()
    return
  }
  active = false
  void activate()
}

watch(service, () => {
  entries.value = []
  selected.value = undefined
  void load()
})
watch([level, keyword, range, history], () => { void load() })
watch(live, () => {
  clearTimer()
  if (live.value) void load()
})
onMounted(activate)
onActivated(activate)
onDeactivated(deactivate)
onUnmounted(deactivate)
</script>

<template>
  <section class="service-logs">
    <div class="filters">
      <el-select v-model="service" :aria-label="label('service')" :placeholder="label('select')">
        <el-option v-for="id in services" :key="id" :label="id.toUpperCase()" :value="id" />
      </el-select>
      <el-select v-model="level" :aria-label="label('level')" :placeholder="label('allLevels')" clearable>
        <el-option v-for="value in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']" :key="value" :label="value" :value="value" />
      </el-select>
      <el-input v-model="keyword" :aria-label="label('keyword')" :placeholder="label('keyword')" clearable maxlength="500" />
      <el-date-picker v-model="range" type="datetimerange" :start-placeholder="label('start')" :end-placeholder="label('end')" />
      <el-switch v-model="live" :active-text="label('live')" />
      <el-checkbox v-model="history">{{ label('history') }}</el-checkbox>
      <el-button :loading="loading" @click="refresh">{{ label('refresh') }}</el-button>
      <el-tooltip :content="label(includeHistory ? 'historyHelp' : 'tailHelp')"><span class="tail">{{ label(includeHistory ? 'history' : 'tail') }}</span></el-tooltip>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="table-host">
      <NcDataTable
        :data="entries" :columns="columns" table-id="system-service-log-entries" route-key="/logs"
        height="100%" :empty-text="label(service ? 'empty' : 'select')" highlight-current-row
        @row-click="selected = $event"
      />
    </div>
    <pre v-if="selected" class="details">{{ selected.raw }}</pre>
  </section>
</template>

<style scoped>
.service-logs { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: 12px; }
.filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.filters .el-select { width: 160px; }
.filters .el-input { width: min(260px, 100%); }
.filters :deep(.el-date-editor) { max-width: 100%; }
.tail { color: var(--el-text-color-secondary); }
.table-host { flex: 1; min-height: 150px; }
.details { margin: 0; max-height: 30%; padding: 10px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: var(--el-fill-color-light); }
</style>
