<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAcApDetail } from '../../api/acManagement'
import { getAcWebTask, saveAcFitApMetadata } from '../../api/acWebParity'
import { isFeatureEnabled } from '../../features'
import type { AcAp } from '../../types/acManagement'
import type { Station } from '../../types/railTransitBaseData'
import { listAllStations } from '../ac-management/stationPagination'

const props = defineProps<{ apId: string }>()
const emit = defineEmits<{ saved: [] }>()
const route = useRoute()
const router = useRouter()
const ap = ref<AcAp>()
const stations = ref<Station[]>([])
const error = ref('')
const busy = ref(true)
const canWrite = () => isFeatureEnabled('capability.ac.fit_ap.metadata_write')
const form = reactive({ station_id: '', station_override_enabled: false, mileage: '', location_note: '', direction: '' })
let disposed = false

onMounted(async () => {
  try {
    const [detail, items] = await Promise.all([getAcApDetail(props.apId), listAllStations()])
    ap.value = detail.ap
    stations.value = items.filter(item => item.enabled !== false)
    Object.assign(form, {
      station_id: detail.ap.manual_station_id || '',
      station_override_enabled: detail.ap.manual_override_enabled,
      mileage: detail.ap.mileage || '',
      location_note: detail.ap.location_note || '',
      direction: detail.ap.direction || '',
    })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '工程关联加载失败'
  } finally {
    busy.value = false
  }
})
onUnmounted(() => { disposed = true })

function setStation(id: string): void {
  form.station_id = id
  form.station_override_enabled = Boolean(id)
}

function close(): void {
  if (!busy.value) void router.replace({ query: { ...route.query, engineering_ap: undefined } })
}

async function save(): Promise<void> {
  if (!ap.value || busy.value || !canWrite()) return
  busy.value = true
  error.value = ''
  try {
    let task = await saveAcFitApMetadata(ap.value.ac_id, ap.value.id, { ...form })
    for (let attempt = 0; !disposed && attempt < 120; attempt++) {
      if (task.status === 'COMPLETED') {
        emit('saved')
        busy.value = false
        close()
        return
      }
      if (task.status === 'FAILED' || task.status === 'CANCELLED') throw new Error(task.error_message || task.message || '工程关联保存失败')
      await new Promise(resolve => window.setTimeout(resolve, 500))
      if (!disposed) task = await getAcWebTask(task.task_id)
    }
    if (!disposed) error.value = '保存任务仍在运行，请在任务记录查看'
  } catch (cause) {
    if (!disposed) error.value = cause instanceof Error ? cause.message : '工程关联保存失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="true" title="AP 工程关联" width="min(640px, 94vw)" :show-close="!busy" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @close="close">
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <el-form v-if="ap" v-loading="busy" :model="form" label-width="88px" :disabled="!canWrite() || busy">
      <el-form-item label="归属站点">
        <el-select :model-value="form.station_id" clearable filterable @change="setStation($event || '')">
          <el-option v-for="station in stations" :key="station.id" :label="`${station.code || '--'}-${station.name}`" :value="station.id" />
        </el-select>
        <el-button text :disabled="!ap.auto_station_id" @click="setStation(ap.auto_station_id)">采用自动关联</el-button>
        <el-button text :disabled="!form.station_override_enabled" @click="setStation('')">清除覆盖</el-button>
      </el-form-item>
      <el-form-item label="里程"><el-input v-model="form.mileage" maxlength="100" /></el-form-item>
      <el-form-item label="线路方向"><el-select v-model="form.direction" clearable><el-option label="上行" value="上行" /><el-option label="下行" value="下行" /><el-option v-if="form.direction && !['上行', '下行'].includes(form.direction)" :label="form.direction" :value="form.direction" /></el-select></el-form-item>
      <el-form-item label="点位说明"><el-input v-model="form.location_note" maxlength="500" /></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="busy" @click="close">关闭</el-button><el-button v-if="ap && canWrite()" type="primary" :loading="busy" @click="save">保存</el-button></template>
  </el-dialog>
</template>
