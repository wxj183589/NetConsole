<script setup lang="ts">
import { t } from '../../i18n/runtime'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { startGroundHistoryExport } from '../../api/groundUnattended'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import type { GroundTimelineEvent } from '../../types/groundUnattended'
import { useGroundContext } from './useGroundUnattended'
const { Refresh, NcDataTable, NcLogWorkspace, trains, groundEventLabel, timelineFilter, timelinePage, timelinePageSize, timelineTotal, filteredTimeline, timelineColumns, loadTimelineData } = useGroundContext()
const { submitExportAfterDestinationSelected, hasActiveExportAction } = useUserSelectedExport()
const selectedEvent = ref<GroundTimelineEvent | null>(null)
const detailOpen = ref(false)
const exporting = ref(false)
const mrOptions = computed(() => trains.value.filter(row => !timelineFilter.trainId || row.train_id === timelineFilter.trainId).flatMap(row => row.endpoints))
const eventTypes = ['mr_loss_pending', 'mr_offline', 'mr_recovered', 'train_connectivity_changed', 'train_offline', 'train_recovered', 'heartbeat_sampling_interrupted', 'ap_transition', 'mesh_linkup', 'mesh_linkdown', 'mesh_activelink_switch', 'rssi_changed', 'ifnet_phy_updown', 'radio_interface_down', 'radio_interface_up', 'radio_interface_recovered', 'radio_interface_bounce', 'radio_interface_flapping', 'cfgman_snmp_change', 'radio_snmp_down', 'radio_snmp_up', 'radio_snmp_bounce', 'radio_snmp_flapping', 'ping_loss_pattern', 'deep_collection_started', 'deep_collection_completed', 'deep_collection_failed', 'run_recovered', 'run_started', 'run_completed', 'stop_failed']
async function exportTimeline(): Promise<void> {
  if (!isFeatureEnabled('capability.ground_unattended.history_export')) return
  exporting.value = true
  try {
    await submitExportAfterDestinationSelected({
      action: 'rail.ground_history',
      suggestedName: `ground_timeline_${new Date().toISOString().slice(0, 10)}.csv`,
      context: { data_type: 'timeline', train_id: timelineFilter.trainId, mr_id: timelineFilter.mrId, mr_role: timelineFilter.mrRole, event_type: timelineFilter.eventType, start_at: timelineFilter.range[0] || '', end_at: timelineFilter.range[1] || '', sort_order: 'desc' },
      submit: () => startGroundHistoryExport({ data_type: 'timeline', train_id: timelineFilter.trainId, mr_id: timelineFilter.mrId, mr_role: timelineFilter.mrRole, event_type: timelineFilter.eventType, start_at: timelineFilter.range[0] || '', end_at: timelineFilter.range[1] || '', sort_order: 'desc' }),
      taskId: (task) => task.task_id,
    })
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : String(reason))
  } finally {
    exporting.value = false
  }
}
</script>

<template>
<section class="ground-subpage">
        <NcLogWorkspace>
          <template #header>
            <div class="toolbar log-filter-grid timeline-filter-grid">
              <el-input v-model="timelineFilter.query" clearable :placeholder="t('ground.v2.filter_device', '设备名称、列车号或 CT/CW')" />
              <el-select v-model="timelineFilter.trainId" clearable filterable :placeholder="t('ground.train', '列车')" @change="timelineFilter.mrId = ''">
                <el-option v-for="row in trains" :key="row.train_id" :label="row.train_name || row.train_no" :value="row.train_id" />
              </el-select>
              <el-select v-model="timelineFilter.mrRole" clearable placeholder="CT / CW"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select>
              <el-select v-model="timelineFilter.mrId" clearable filterable :placeholder="t('ground.mr', 'MR 设备')"><el-option v-for="mr in mrOptions" :key="mr.mr_id" :label="`${mr.mr_name || mr.mr_id} · ${mr.endpoint}`" :value="mr.mr_id" /></el-select>
              <el-date-picker v-model="timelineFilter.range" type="datetimerange" value-format="YYYY-MM-DDTHH:mm:ssZ" :start-placeholder="t('ground.start_time', '开始时间')" :end-placeholder="t('ground.end_time', '结束时间')" />
              <el-select v-model="timelineFilter.eventType" clearable :placeholder="t('ground.v2.event_type', '事件类型')">
                <el-option v-for="value in eventTypes" :key="value" :label="groundEventLabel(value)" :value="value" />
              </el-select>
              <el-button :icon="Refresh" @click="timelinePage = 1; loadTimelineData(false)">{{ t('common.query', '查询') }}</el-button>
              <el-button v-if="isFeatureVisible('capability.ground_unattended.history_export')" :loading="exporting" :disabled="!isFeatureEnabled('capability.ground_unattended.history_export') || hasActiveExportAction('rail.ground_history')" @click="exportTimeline">{{ t('ground.history_export', '导出时间轴') }}</el-button>
            </div>
          </template>
          <NcDataTable
            :data="filteredTimeline"
            :columns="timelineColumns"
            table-id="ground-timeline"
            route-key="rail-ground-unattended"
            row-key="event_id"
            fill-remaining-height
            compact
          >
            <template #cell-actions="{ row }"><el-button text type="primary" @click="selectedEvent = row; detailOpen = true">{{ t('ground.details', '详情') }}</el-button></template>
          </NcDataTable>
          <template #pagination>
            <el-pagination
              v-model:current-page="timelinePage"
              v-model:page-size="timelinePageSize"
              :total="timelineTotal"
              :page-sizes="[50, 100, 200, 500]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadTimelineData(false)"
              @size-change="timelinePage = 1; loadTimelineData(false)"
            />
          </template>
        </NcLogWorkspace>
        <el-drawer v-model="detailOpen" :title="selectedEvent?.title || t('ground.details', '详情')" size="min(680px, 92vw)" append-to-body>
          <template v-if="selectedEvent"><p>{{ selectedEvent.message }}</p><el-descriptions :column="1" border><el-descriptions-item :label="t('ground.event_time', '事件时间')">{{ selectedEvent.event_at || selectedEvent.ts || '—' }}</el-descriptions-item><el-descriptions-item :label="t('ground.run_date', '运行日期')">{{ selectedEvent.run_date || '—' }}</el-descriptions-item><el-descriptions-item :label="t('ground.event_source', '事件来源')">{{ selectedEvent.source || '—' }}</el-descriptions-item><el-descriptions-item :label="t('ground.device_time', '设备时间')">{{ selectedEvent.device_time || '—' }}</el-descriptions-item><el-descriptions-item :label="t('ground.received_at', '接收时间')">{{ selectedEvent.received_at || '—' }}</el-descriptions-item></el-descriptions><pre class="event-detail">{{ JSON.stringify(selectedEvent, null, 2) }}</pre></template>
        </el-drawer>

</section>
</template>

<style scoped src="./groundUnattended.css"></style>
<style scoped>.event-detail{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}</style>
