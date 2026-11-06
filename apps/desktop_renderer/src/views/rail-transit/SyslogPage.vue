<script setup lang="ts">
import { t } from '../../i18n/runtime'
import { computed } from 'vue'
import { useGroundContext } from './useGroundUnattended'
const { Delete, Refresh, NcDataTable, NcMultiValueFilter, NcLogWorkspace, groundEventLabel, groundSourceLabel, groundStatusLabel, health, syslogRecords, syslogTotal, syslogLoading, syslogAutoRefresh, syslogDiagnostics, syslogTotalExact, syslogBackendState, syslogRequestId, syslogLastAttemptAt, syslogFailureCount, syslogErrorCode, selectedSyslogRecords, syslogAdvancedFiltersOpen, syslogDeleteDerived, syslogDeleteLoading, syslogTimeRange, syslogFilter, syslogIssue, historicalRun, syslogDeleteBlocked, syslogAdvancedFilterCount, syslogHasActiveFilters, syslogColumns, loadSyslog, openBackendLogs, showSyslogRecord, syslogRowKey, handleSyslogSelection, deleteSyslog } = useGroundContext()
const { syslogStatistics, syslogSortOrder } = useGroundContext()
const cards = computed(() => [
  ['today_received', '今日接收日志（登记）'], ['active_files', '活动文件'],
  ['parse_failed_files', '解析失败文件'], ['raw_missing_files', '原始数据缺失（登记）'],
  ['wmesh_events', 'WMESH 事件'], ['data_status', '数据状态'],
].map(([key, label]) => ({ key, label: t(`ground.syslog.stat_${key}`, label), value: syslogStatistics?.value?.[key] ?? '—' })))
function sortChanged({ order }: { order: string | null }) {
  syslogSortOrder.value = order === 'ascending' ? 'asc' : 'desc'
  syslogFilter.page = 1
  void loadSyslog()
}
</script>

<template>
<section class="ground-subpage">
        <div class="syslog-statistics" aria-label="Syslog 统计">
          <article v-for="card in cards" :key="card.key" :class="{ abnormal: ['parse_failed_files', 'raw_missing_files'].includes(card.key) && Number(card.value) > 0 }">
            <span>{{ card.label }}</span><strong>{{ card.key === 'data_status' ? groundStatusLabel(String(card.value)) : card.value }}</strong>
          </article>
        </div>
        <p class="statistics-note">{{ t('ground.syslog.index_scope', '统计范围：所选运行的登记索引，不受列表筛选影响；跨日文件的今日条数显示为空。文件缺失统计不代替磁盘完整性校验。') }}</p>
        <NcLogWorkspace :loading="syslogLoading">
          <template #header>
            <div class="toolbar log-filter-grid syslog-common-filters">
              <el-input v-model="syslogFilter.trainId" clearable :placeholder="t('ground.train_id', '列车 ID')" />
              <el-input v-model="syslogFilter.mrName" clearable :placeholder="t('ground.v2.mr_name', 'MR 设备名称')" />
              <NcMultiValueFilter v-model="syslogFilter.mrRole" :options="['CT', 'CW']" placeholder="CT/CW" />
              <el-input v-model="syslogFilter.sourceIp" clearable :placeholder="t('ground.v2.source_ip', '来源 IP')" />
              <NcMultiValueFilter v-model="syslogFilter.eventType" :options="['MESH_LINKUP', 'MESH_LINKDOWN', 'MESH_ACTIVELINK_SWITCH', 'IFNET_PHY_UPDOWN', 'CFGMAN_CFGCHANGED']" :labels="Object.fromEntries(['MESH_LINKUP', 'MESH_LINKDOWN', 'MESH_ACTIVELINK_SWITCH', 'IFNET_PHY_UPDOWN', 'CFGMAN_CFGCHANGED'].map((value) => [value, groundEventLabel(value)]))" :placeholder="t('ground.v2.raw_event', '原始事件')" />
              <el-input v-model="syslogFilter.peerName" clearable :placeholder="t('ground.v2.ap_name_mac', 'AP 名称或 MAC')" />
              <el-date-picker v-model="syslogTimeRange" type="datetimerange" :start-placeholder="t('ground.v2.syslog_start_time', '开始时间')" :end-placeholder="t('ground.v2.syslog_end_time', '结束时间')" />
              <el-button @click="syslogAdvancedFiltersOpen = !syslogAdvancedFiltersOpen">
                {{ t('ground.v2.syslog_advanced_count', '高级筛选（{count} 个条件）').replace('{count}', String(syslogAdvancedFilterCount)) }}
              </el-button>
              <el-checkbox v-model="syslogAutoRefresh">{{ t('ground.v2.auto_refresh', '自动刷新') }}{{ historicalRun ? t('ground.syslog.auto_refresh_30', '（30 秒）') : '' }}</el-checkbox>
              <el-button type="primary" :icon="Refresh" :loading="syslogLoading" @click="syslogFilter.page = 1; loadSyslog()">{{ t('ground.v2.query', '查询') }}</el-button>
            </div>
            <el-collapse-transition>
              <div v-show="syslogAdvancedFiltersOpen" class="toolbar log-filter-grid syslog-advanced-filters">
                <el-input v-model="syslogFilter.systemName" clearable placeholder="system_name" />
                <el-input v-model="syslogFilter.facility" clearable placeholder="Facility" />
                <NcMultiValueFilter v-model="syslogFilter.severity" :options="['info', 'warning', 'error']" :labels="{ info: t('ground.v2.syslog_info', '提示'), warning: t('ground.v2.syslog_warning', '警告'), error: t('ground.v2.syslog_error', '错误') }" :placeholder="t('ground.v2.severity', '严重级别')" />
                <NcMultiValueFilter v-model="syslogFilter.identityStatus" :options="['VERIFIED', 'UNIDENTIFIED', 'IDENTITY_CONFLICT']" :labels="{ VERIFIED: t('ground.v2.syslog_verified', '身份已确认'), UNIDENTIFIED: t('ground.v2.syslog_unidentified', '来源未识别'), IDENTITY_CONFLICT: t('ground.v2.syslog_identity_conflict', '身份冲突') }" :placeholder="t('ground.v2.identity_state', '身份状态')" />
                <NcMultiValueFilter v-model="syslogFilter.eventFamily" :options="['WMESH', 'IFNET', 'CFGMAN']" :placeholder="t('ground.v2.event_family', '事件族')" />
                <NcMultiValueFilter v-model="syslogFilter.commandSource" :options="['snmp', 'cli', 'netconf']" :labels="{ snmp: 'SNMP', cli: 'CLI', netconf: 'NETCONF' }" :placeholder="t('ground.v2.control_source', '控制来源')" />
                <NcMultiValueFilter v-model="syslogFilter.physicalState" :options="['UP', 'DOWN']" :labels="{ UP: t('ground.v2.syslog_up', '开启'), DOWN: t('ground.v2.syslog_down', '关闭') }" :placeholder="t('ground.v2.radio_state', '射频状态')" />
                <NcMultiValueFilter v-model="syslogFilter.correlationStatus" :options="['CORRELATED', 'UNCORRELATED']" :labels="{ CORRELATED: t('ground.v2.syslog_correlated', '已关联'), UNCORRELATED: t('ground.v2.syslog_uncorrelated', '未关联') }" :placeholder="t('ground.v2.association_state', '关联状态')" />
                <NcMultiValueFilter v-model="syslogFilter.correlationConfidence" :options="['HIGH', 'MEDIUM']" :labels="{ HIGH: t('ground.v2.syslog_confidence_high', '高置信度'), MEDIUM: t('ground.v2.syslog_confidence_medium', '中置信度') }" :placeholder="t('ground.v2.association_confidence', '关联置信度')" />
                <NcMultiValueFilter v-model="syslogFilter.dataSource" :options="['ACTIVE', 'ARCHIVE']" :labels="{ ACTIVE: t('ground.v2.syslog_active_raw', '活动原始文件'), ARCHIVE: t('ground.v2.syslog_ready_archive', 'READY 归档') }" :placeholder="t('ground.v2.source', '数据来源')" />
                <el-input v-model="syslogFilter.keyword" clearable :placeholder="t('ground.v2.raw_keyword', '原始内容关键字')" />
              </div>
            </el-collapse-transition>
          </template>
          <template #summary>
            <section v-if="syslogIssue" class="syslog-failure">
          <el-alert
            :title="t('ground.syslog.failure_title', 'Syslog 日志暂时无法加载')"
            :description="syslogIssue.message"
            type="error"
            :closable="false"
            show-icon
          />
          <div class="coverage-strip">
            <span>{{ t('ground.syslog.backend_status', 'Backend 状态') }} <b>{{ groundStatusLabel(syslogBackendState) }}</b></span>
            <span>{{ t('ground.syslog.error_type', '错误类型') }} <b>{{ syslogErrorCode || 'UNKNOWN_ERROR' }}</b></span>
            <span>{{ t('ground.syslog.failure_count', '失败次数') }} <b>{{ syslogFailureCount }}</b></span>
            <span>{{ t('ground.syslog.last_attempt', '最近尝试') }} <b>{{ syslogLastAttemptAt || '—' }}</b></span>
            <span v-if="syslogRequestId">{{ t('ground.syslog.request_id', '请求编号') }} <b>{{ syslogRequestId }}</b></span>
          </div>
          <div class="row-actions">
            <el-button :icon="Refresh" :loading="syslogLoading" type="primary" @click="loadSyslog()">{{ t('ground.syslog.retry', '重新查询') }}</el-button>
            <el-button @click="openBackendLogs">{{ t('ground.syslog.open_backend_logs', '查看 Backend 日志') }}</el-button>
          </div>
            </section>
            <el-alert
              v-else-if="syslogDiagnostics?.truncated"
              :title="t('ground.syslog.truncated', '日志量较大，本次已返回最近的数据。请设置时间范围或增加筛选条件。')"
              type="warning"
              :closable="false"
              show-icon
            />
            <div v-if="syslogDiagnostics" class="coverage-strip">
              <span>{{ t('ground.v2.source', '数据来源') }} <b>{{ groundSourceLabel(syslogDiagnostics.source_kind) }}</b></span>
              <span>{{ t('ground.v2.availability', '可用性') }} <b>{{ groundStatusLabel(syslogDiagnostics.data_availability) }}</b></span>
              <span>{{ t('ground.v2.scanned_files', '扫描文件') }} <b>{{ syslogDiagnostics.files_scanned }}</b></span>
              <span>{{ t('ground.v2.scanned_records', '扫描记录') }} <b>{{ syslogDiagnostics.records_scanned }}</b></span>
              <span>{{ t('ground.v2.matching_records', '匹配记录') }} <b>{{ syslogTotal }}{{ syslogTotalExact ? '' : '+' }}</b></span>
              <span>{{ t('ground.v2.receiver', '接收器') }} <b>{{ health?.udp_running ? t('ground.v2.syslog_listening', '正在监听') : t('ground.v2.syslog_not_listening', '未监听') }}</b></span>
              <span v-if="syslogDiagnostics.no_data_reason">{{ groundStatusLabel(syslogDiagnostics.no_data_reason) }}</span>
            </div>
          </template>
          <template #actions>
            <div class="syslog-bulk-actions">
              <span>{{ t('ground.v2.syslog_selected_count', '已选择 {count} 条（表头复选框可全选当前页）').replace('{count}', String(selectedSyslogRecords.length)) }}</span>
              <el-checkbox v-model="syslogDeleteDerived">{{ t('ground.v2.also_delete_derived', '同时删除派生 WMESH/时间轴事件') }}</el-checkbox>
              <el-button :icon="Delete" :loading="syslogDeleteLoading" :disabled="syslogDeleteBlocked || !selectedSyslogRecords.length" @click="deleteSyslog('SELECTED')">{{ t('ground.v2.delete_selected', '删除选中日志') }}</el-button>
              <el-button :icon="Delete" :loading="syslogDeleteLoading" :disabled="syslogDeleteBlocked || !syslogHasActiveFilters" @click="deleteSyslog('FILTERED')">{{ t('ground.v2.delete_filtered', '删除当前筛选范围') }}</el-button>
              <el-button type="danger" plain :icon="Delete" :loading="syslogDeleteLoading" :disabled="syslogDeleteBlocked" @click="deleteSyslog('RUN_ALL')">{{ t('ground.v2.delete_run_syslog', '删除当前运行全部 Syslog') }}</el-button>
              <span v-if="syslogDeleteBlocked" class="muted">{{ t('ground.v2.delete_prohibited', '活动运行、ERROR 状态、OPEN 文件与最终化阶段禁止删除') }}</span>
            </div>
          </template>
          <NcDataTable
            :data="syslogRecords"
            :columns="syslogColumns"
            table-id="ground-syslog:v2"
            route-key="rail-ground-unattended"
            :row-key="syslogRowKey"
            fill-remaining-height
            compact
            @selection-change="handleSyslogSelection"
            @row-click="showSyslogRecord"
            @sort-change="sortChanged"
          >
          <template #cell-actions="{ row }"><el-button size="small" text type="primary" @click="showSyslogRecord(row)">{{ t('ground.details', '详情') }}</el-button></template>
          </NcDataTable>
          <template #pagination>
            <el-pagination
              v-model:current-page="syslogFilter.page"
              v-model:page-size="syslogFilter.pageSize"
              :total="syslogTotal"
              :page-sizes="[50, 100, 200, 500]"
              layout="total, sizes, prev, pager, next"
              @current-change="loadSyslog"
              @size-change="syslogFilter.page = 1; loadSyslog()"
            />
          </template>
        </NcLogWorkspace>
      
</section>
</template>

<style scoped src="./groundUnattended.css"></style>
<style scoped>
.syslog-statistics { display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 12px; }
.syslog-statistics article { padding: 14px 16px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 8px; display: grid; gap: 10px; }
.syslog-statistics span, .statistics-note { color: var(--el-text-color-secondary); font-size: 12px; }
.syslog-statistics strong { font-size: 22px; color: var(--el-color-primary); }
.syslog-statistics .abnormal strong { color: var(--el-color-danger); }
.statistics-note { margin: 0; }
@media (max-width: 1100px) { .syslog-statistics { grid-template-columns: repeat(3, 1fr); } }
</style>
