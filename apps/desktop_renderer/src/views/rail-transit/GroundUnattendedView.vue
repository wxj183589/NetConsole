<script setup lang="ts">
import { ref, watch, watchEffect } from 'vue'
import { ElMessage } from 'element-plus'
import { syslogVisibleDetails } from './groundSyslogPresentation'
import { isFeatureVisible, isFeatureEnabled } from '../../features'
import { GROUND_TAB_FEATURES } from './groundFeatures'
import HeartbeatPage from './HeartbeatPage.vue'
import AcMeshLinkPage from './AcMeshLinkPage.vue'
import QuickPingPage from './QuickPingPage.vue'
import OverviewPage from './OverviewPage.vue'
import DeepCollectionPage from './DeepTasksPage.vue'
import TimelinePage from './TimelinePage.vue'
import SyslogPage from './SyslogPage.vue'
import SystemHealthPage from './SystemHealthPage.vue'
import ArchivePage from './ArchivePage.vue'
import SettingsPage from './SettingsPage.vue'
import { provideGroundContext } from './useGroundUnattended'
const groundContext = provideGroundContext()
defineExpose(groundContext)
const { Box, CopyDocument, Delete, Refresh, SwitchButton, VideoPause, VideoPlay, pauseGroundRun, resumeGroundRun, startGroundRun, GroundPingChart, NcFloatingWindow, t, groundDisplayNameSourceLabel, groundEventLabel, groundOperationStageLabel, groundRunModeLabel, groundSeverityLabel, groundStopTriggerLabel, groundSourceLabel, groundStatusLabel, groundTransitionContextLabel, activeTab, pageVisible, pageActivated, quickContextRevision, loading, action, status, profile, trains, pingTargets, selectedDeepCollector, deepRecords, deepWindowOpen, deepRecordsLoading, deepCategory, deepKeyword, deepPaused, deepAutoRefresh, acMeshSummary, acMeshLinks, acMeshMrs, acMeshSnapshots, acMeshRawTail, acMeshLoading, acControllers, selectedAcControllerId, acControllersLoading, acControllersError, runs, selectedRunId, runHistoryDeleteLoading, pingSeries, selectedPingTarget, pingWindowOpen, pingSeriesLoading, pingIncrementalLoading, includeWarmup, pingRange, pingCustomRange, pingAutoRefresh, pingPaused, pingFollowLatest, pingInitialLoadSucceeded, pingBackendState, pingRequestId, pingErrorCode, selectedSyslogRecord, syslogDetailDrawer, selectedArchive, archiveDetailTab, selectedTrain, archiveDialog, trainDialog, openingSessionId, trainFilter, pingFilter, generalLoadIssues, pingIssue, loadIssueDescription, running, operationActive, visibleOperation, selectedRun, historicalRun, runHistoryDeleteBlocked, selectedPingHistorical, runScopedTab, archiveRecordCount, selectedTrainCollection, trainTableMaxHeight, pingTableMaxHeight, startBlockedReason, pingAvailability, pingEmptyDescription, pingLiveStats, locationStats, trainColumns, pingColumns, refreshAcMesh, dismissOperation, loadAll, runAction, submitStop, showPingSeries, openPingBackendLogs, togglePriority, syncInventory, updatePolicy, checkConfigs, confirmTargetPortChange, showTrain, showTrainPing, showTrainTimeline, openDeepSession, deleteSelectedRunHistory, downloadArchiveSummary, downloadArchiveZip, verifyArchive, endpoint, groundControlSourceLabel, endpointRadioTooltip, duration, metric, bytes, statusType, useFullPingRange, togglePingPaused, returnPingToLive, copyPingDiagnostics, handlePingDialogClosed, loadDeepRecords, toggleDeepPaused, handleDeepWindowClosed, copyDeepRecords } = groundContext
const quickPingMrId = ref('')
async function copySyslogRaw() {
  try {
    await navigator.clipboard.writeText(selectedSyslogRecord.value?.raw_text || '')
    ElMessage.success(t('common.copied', '已复制'))
  } catch {
    ElMessage.error(t('ground.syslog.copy_failed', '复制失败，请选择原始报文手动复制'))
  }
}
watch(quickContextRevision, () => { quickPingMrId.value = '' })
const tabVisible = (name: string) => isFeatureVisible(GROUND_TAB_FEATURES[name] || '')
const tabEnabled = (name: string) => isFeatureEnabled(GROUND_TAB_FEATURES[name] || '')
watchEffect(() => {
  if (tabVisible(activeTab.value) && tabEnabled(activeTab.value)) return
  activeTab.value = Object.keys(GROUND_TAB_FEATURES).find((name) => tabVisible(name) && tabEnabled(name)) || ''
})
function openQuickPing(mrId: string) {
  if (!tabVisible('quick-ping') || !tabEnabled('quick-ping') || !isFeatureEnabled('capability.ground_unattended.quick_ping')) return
  quickPingMrId.value = mrId; activeTab.value = 'quick-ping'
}
</script>

<template>
  <main v-loading="loading" :class="['ground-page', { 'ground-page--log-view': ['timeline', 'syslog'].includes(activeTab) }]">
    <header class="page-heading">
      <div>
        <p class="eyebrow">{{ t('ground.section', '轨道交通') }}</p>
        <h1>{{ t('ground.title', '地面无人值守') }}</h1>
      </div>
      <div class="heading-actions">
        <el-button :icon="Refresh" circle :title="t('common.refresh', '刷新')" @click="loadAll()" />
        <el-button :icon="Refresh" :loading="action === 'sync'" @click="runAction('sync', syncInventory)">同步设备</el-button>
        <el-button :loading="action === 'config'" :disabled="!running || !profile?.syslog_server_ip" @click="runAction('config', () => checkConfigs())">检查 MR 配置</el-button>
        <span :title="startBlockedReason">
          <el-button
            :icon="VideoPlay"
            type="primary"
            :loading="action === 'start'"
            :disabled="running || !profile?.enabled || Boolean(startBlockedReason)"
            @click="runAction('start', startGroundRun)"
          >{{ t('ground.start_now', '立即开始') }}</el-button>
        </span>
        <el-button :icon="VideoPause" :loading="action === 'pause'" :disabled="status?.state !== 'RUNNING'" @click="runAction('pause', pauseGroundRun)">{{ t('ground.pause', '暂停调度') }}</el-button>
        <el-button :icon="VideoPlay" :loading="action === 'resume'" :disabled="status?.state !== 'PAUSED'" @click="runAction('resume', resumeGroundRun)">{{ t('ground.resume', '继续调度') }}</el-button>
        <el-button :icon="SwitchButton" :loading="action === 'stop'" :disabled="!running || operationActive" @click="submitStop(false)">{{ t('ground.stop', '正常停止') }}</el-button>
        <el-button :icon="Box" type="danger" plain :loading="action === 'archive'" :disabled="!running || operationActive" @click="submitStop(true)">{{ t('ground.stop_archive', '停止并归档') }}</el-button>
      </div>
    </header>

    <section v-if="visibleOperation" class="operation-band" :class="`operation-${visibleOperation.operation_state.toLocaleLowerCase()}`">
      <div class="operation-heading">
        <div>
          <b>{{ visibleOperation.operation_type === 'STOP_AND_ARCHIVE' ? '停止并归档' : '运行停止' }}</b>
          <span>{{ groundOperationStageLabel(visibleOperation.operation_stage) }}</span>
        </div>
        <div class="row-actions">
          <el-tag :type="visibleOperation.operation_state === 'FAILED' ? 'danger' : visibleOperation.operation_state === 'COMPLETED' ? 'success' : 'warning'">
            {{ groundStatusLabel(visibleOperation.operation_state) }}
          </el-tag>
          <el-button v-if="!operationActive" text @click="dismissOperation">关闭</el-button>
        </div>
      </div>
      <el-progress :percentage="visibleOperation.progress_percent" :status="visibleOperation.operation_state === 'FAILED' ? 'exception' : visibleOperation.operation_state === 'COMPLETED' ? 'success' : undefined" />
      <p>{{ visibleOperation.message }}<span v-if="visibleOperation.failure_reason">：{{ visibleOperation.failure_reason }}</span></p>
      <small>触发原因 {{ visibleOperation.stop_reason || groundStopTriggerLabel(visibleOperation.stop_trigger) }} · 触发时间 {{ visibleOperation.triggered_at || visibleOperation.started_at }}</small>
      <small>操作编号 {{ visibleOperation.operation_id }}<template v-if="visibleOperation.request_id"> · 请求编号 {{ visibleOperation.request_id }}</template> · 最后更新 {{ visibleOperation.updated_at }}</small>
    </section>

    <section v-if="generalLoadIssues.length" class="load-warning">
      <el-alert
        title="地面无人值守部分数据未加载"
        :description="loadIssueDescription"
        type="error"
        :closable="false"
        show-icon
      />
      <el-button :icon="Refresh" :loading="loading" @click="loadAll()">重新加载</el-button>
    </section>

    <section v-if="runScopedTab" class="run-context-bar">
      <div>
        <b>数据运行上下文</b>
        <span>深度采集、时间轴与 Syslog 使用所选运行；心跳检测始终展示常驻监测状态。</span>
      </div>
      <el-select v-model="selectedRunId" filterable placeholder="选择运行日期">
        <el-option
          v-for="row in runs"
          :key="row.run_id"
          :value="row.run_id"
          :label="`${row.run_date} · ${groundStatusLabel(row.state)} · ${groundStatusLabel(row.data_availability)}`"
        />
      </el-select>
      <el-tag :type="historicalRun ? 'info' : 'success'">{{ historicalRun ? '历史运行' : '当前活动运行' }}</el-tag>
      <el-button
        :icon="Delete"
        type="danger"
        plain
        :loading="runHistoryDeleteLoading"
        :disabled="runHistoryDeleteBlocked"
        @click="deleteSelectedRunHistory"
      >删除历史记录</el-button>
      <span class="muted">{{ selectedRun?.actual_started_at || selectedRun?.scheduled_start_at || '—' }} 至 {{ selectedRun?.actual_ended_at || '进行中' }}</span>
    </section>

    <el-tabs v-model="activeTab" class="ground-tabs">
      <el-tab-pane v-if="tabVisible('overview')" :disabled="!tabEnabled('overview')" :label="t('ground.overview', '运行概览')" name="overview">
        <OverviewPage />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('heartbeat')" :disabled="!tabEnabled('heartbeat')" :label="t('ground.heartbeat', '心跳检测')" name="heartbeat">
        <HeartbeatPage
          :trains="trains"
          :ping-targets="pingTargets"
          :train-columns="trainColumns"
          :ping-columns="pingColumns"
          :train-table-max-height="trainTableMaxHeight"
          :ping-table-max-height="pingTableMaxHeight"
          :train-filter="trainFilter"
          :ping-filter="pingFilter"
          :location-stats="locationStats"
          :status-label="groundStatusLabel"
          :status-type="statusType"
          :endpoint="endpoint"
          :endpoint-radio-tooltip="endpointRadioTooltip"
          :control-source-label="groundControlSourceLabel"
          @update:train-filter="trainFilter = $event"
          @update:ping-filter="Object.assign(pingFilter, $event)"
          @refresh="loadAll()"
          @show-train="showTrain"
          @toggle-priority="togglePriority"
          @toggle-enabled="(row) => updatePolicy(row, { enabled: !row.enabled })"
          @show-ping-series="showPingSeries"
          @quick-ping="openQuickPing"
        />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('ac-mesh-link')" :disabled="!tabEnabled('ac-mesh-link')" :label="t('ground.ac_mesh_link', 'AC-Mesh-Link')" name="ac-mesh-link">
        <AcMeshLinkPage
          :summary="acMeshSummary"
          :links="acMeshLinks"
          :mrs="acMeshMrs"
          :snapshots="acMeshSnapshots"
          :raw-tail="acMeshRawTail"
          :controllers="acControllers"
          :selected-controller-id="selectedAcControllerId"
          :controllers-loading="acControllersLoading"
          :controllers-error="acControllersError"
          :loading="acMeshLoading"
          @update:selected-controller-id="selectedAcControllerId = $event"
          @refresh="refreshAcMesh"
        />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('quick-ping')" :disabled="!tabEnabled('quick-ping')" :label="t('ground.quick_ping', '快速 Ping')" name="quick-ping">
        <QuickPingPage :mr-id="quickPingMrId" :key="quickContextRevision" :trains="trains" :active="pageVisible && pageActivated && activeTab === 'quick-ping'" />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('syslog')" :disabled="!tabEnabled('syslog')" :label="t('ground.syslog', 'Syslog 日志')" name="syslog" class="log-console-pane">
        <SyslogPage />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('deep')" :disabled="!tabEnabled('deep')" :label="t('ground.deep_collection', '深度采集')" name="deep">
        <DeepCollectionPage />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('timeline')" :disabled="!tabEnabled('timeline')" :label="t('ground.timeline', '时间轴')" name="timeline" class="log-console-pane">
        <TimelinePage />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('health')" :disabled="!tabEnabled('health')" :label="t('ground.health', '系统健康')" name="health">
        <SystemHealthPage />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('archives')" :disabled="!tabEnabled('archives')" :label="t('ground.archives', '历史归档')" name="archives">
        <ArchivePage />
      </el-tab-pane>

      <el-tab-pane v-if="tabVisible('settings')" :disabled="!tabEnabled('settings')" :label="t('ground.settings', '设置')" name="settings">
        <SettingsPage />
      </el-tab-pane>
    </el-tabs>

    <NcFloatingWindow
      v-model="pingWindowOpen"
      :title="selectedPingTarget ? `${selectedPingTarget.train_no || selectedPingTarget.train_id} · ${selectedPingTarget.mr_name || selectedPingTarget.mr_position_code} · ${selectedPingTarget.target_ip}` : t('ground.v2.heartbeat_packet_chart', '心跳检测逐包曲线')"
      :subtitle="selectedPingTarget ? `运行日期 ${selectedPingTarget.run_date || selectedRun?.run_date || '—'} · ${selectedPingHistorical ? '历史静态数据' : !pingInitialLoadSucceeded ? '首次查询未完成' : pingPaused ? '实时刷新已暂停' : '实时增量'} · ${groundStatusLabel(pingAvailability)}` : ''"
      window-id="ground-ping-series"
      route-key="rail-ground-unattended"
      @close="handlePingDialogClosed"
    >
      <section v-if="selectedPingTarget" class="ping-floating-content">
        <div class="toolbar">
          <el-select v-model="pingRange" :aria-label="t('ground.v2.heartbeat_range', '心跳检测时间范围')" @change="showPingSeries(selectedPingTarget)">
            <el-option label="完整运行时段" value="run" />
            <el-option label="最近 5 分钟" value="5m" />
            <el-option label="最近 30 分钟" value="30m" />
            <el-option label="最近 1 小时" value="1h" />
            <el-option label="自定义时间" value="custom" />
          </el-select>
          <el-date-picker
            v-if="pingRange === 'custom'"
            v-model="pingCustomRange"
            type="datetimerange"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            @change="showPingSeries(selectedPingTarget)"
          />
          <el-checkbox v-model="includeWarmup" @change="showPingSeries(selectedPingTarget)">显示预热样本</el-checkbox>
          <el-checkbox v-model="pingAutoRefresh" :disabled="selectedPingHistorical || !pingInitialLoadSucceeded">实时增量</el-checkbox>
          <el-checkbox v-model="pingFollowLatest">跟随最新</el-checkbox>
          <el-button v-if="!selectedPingHistorical" :icon="pingPaused ? VideoPlay : VideoPause" @click="togglePingPaused">{{ pingPaused ? '继续' : '暂停' }}</el-button>
          <el-button v-if="!pingFollowLatest" type="primary" plain @click="returnPingToLive">回到实时</el-button>
          <el-button @click="useFullPingRange">完整运行</el-button>
          <el-button :icon="Refresh" :loading="pingSeriesLoading || pingIncrementalLoading" @click="showPingSeries(selectedPingTarget, true)">刷新</el-button>
        </div>
        <div class="coverage-strip ping-query-identity">
          <span>运行 <b>{{ selectedPingTarget.run_id || selectedRunId }}</b></span>
          <span>目标 IP <b>{{ selectedPingTarget.target_ip }}</b></span>
          <span>MR <b>{{ selectedPingTarget.mr_name || selectedPingTarget.mr_id || '未知' }}</b></span>
          <span>端位 <b>{{ selectedPingTarget.mr_position_code || '未知' }}</b></span>
        </div>
        <div class="coverage-strip">
          <span>原始样本 <b>{{ pingSeries?.raw_sample_count ?? 0 }}</b></span>
          <span>有效样本 <b>{{ pingSeries?.effective_sample_count ?? 0 }}</b></span>
          <span>预热忽略 <b>{{ pingSeries?.ignored_sample_count ?? 0 }}</b></span>
          <span>成功 / 丢包 <b>{{ pingLiveStats.success }} / {{ pingLiveStats.loss }}</b></span>
          <span>丢包率 <b>{{ pingLiveStats.lossRate.toFixed(2) }}%</b></span>
          <span>当前 / 平均 / 最大 RTT <b>{{ metric(pingLiveStats.currentRtt, 'ms') }} / {{ metric(pingLiveStats.averageRtt, 'ms') }} / {{ metric(pingLiveStats.maxRtt, 'ms') }}</b></span>
          <span>最长连续丢包 <b>{{ selectedPingTarget.continuous_loss_max_count ?? 0 }} / {{ (selectedPingTarget.continuous_loss_max_seconds ?? 0).toFixed(1) }}s</b></span>
          <span v-if="pingSeries">来源 <b>{{ groundSourceLabel(pingSeries.diagnostics.source_kind) }}</b></span>
          <span v-if="pingSeries">可用性 <b>{{ groundStatusLabel(pingSeries.diagnostics.data_availability) }}</b></span>
        </div>
        <div class="coverage-strip">
          <span>Registry 文件 <b>{{ pingSeries?.diagnostics.raw_file_registry_hit_count ?? selectedPingTarget.raw_file_count ?? 0 }}</b></span>
          <span>扫描文件 <b>{{ pingSeries?.diagnostics.files_scanned ?? 0 }}</b></span>
          <span>扫描记录 <b>{{ pingSeries?.diagnostics.records_scanned ?? 0 }}</b></span>
          <span>匹配记录 <b>{{ pingSeries?.diagnostics.matched_count ?? 0 }}</b></span>
          <span>当前状态 <b>{{ groundStatusLabel(pingSeries?.target_state || selectedPingTarget.data_availability) }}</b></span>
          <span>当前 AP <b>{{ pingLiveStats.currentAp || '未知' }}</b></span>
          <span>站点 / 区间 <b>{{ pingLiveStats.station || '未知' }} / {{ pingLiveStats.section || '未知' }}</b></span>
          <span>最近样本 <b>{{ pingLiveStats.latestAt || '尚无样本' }}</b></span>
          <span v-if="pingSeries?.diagnostics.truncated">查询预算已截断</span>
          <span v-if="pingIncrementalLoading">正在补拉增量</span>
        </div>
        <el-alert
          v-if="pingIssue"
          class="ping-query-error"
          type="error"
          :closable="false"
          show-icon
          :title="pingIssue.message"
        >
          <template #default>
            <div class="coverage-strip">
              <span>错误码 <b>{{ pingErrorCode || 'UNKNOWN_ERROR' }}</b></span>
              <span>Backend <b>{{ pingBackendState }}</b></span>
              <span v-if="pingRequestId">request_id <b>{{ pingRequestId }}</b></span>
              <span v-if="pingSeries?.diagnostics.no_data_reason">原因 <b>{{ pingSeries.diagnostics.no_data_reason }}</b></span>
            </div>
            <div class="row-actions">
              <el-button type="primary" plain @click="showPingSeries(selectedPingTarget, true)">重试</el-button>
              <el-button :icon="CopyDocument" @click="copyPingDiagnostics">复制诊断信息</el-button>
              <el-button @click="openPingBackendLogs">查看 Backend 日志</el-button>
            </div>
          </template>
        </el-alert>
        <el-skeleton v-if="pingSeriesLoading && !pingSeries" :rows="8" animated />
        <el-empty
          v-else-if="!pingSeries?.points.length"
          class="ping-empty-state"
          :description="pingEmptyDescription"
        >
          <div class="row-actions">
            <el-button v-if="pingRange !== 'run'" @click="useFullPingRange">切换到完整运行时段</el-button>
            <el-button :icon="CopyDocument" @click="copyPingDiagnostics">复制文件诊断</el-button>
            <el-button @click="openPingBackendLogs">查看 Backend 日志</el-button>
          </div>
        </el-empty>
        <div v-else class="ping-chart-workspace">
          <GroundPingChart
            :series="pingSeries"
            :follow-latest="pingFollowLatest"
            @user-zoom="pingFollowLatest = false"
          />
        </div>
        <section v-if="pingSeries?.points.length" class="ping-loss-panel">
          <h3>丢包区段</h3>
          <el-table :data="pingSeries?.loss_windows || []" size="small" max-height="220" empty-text="暂无丢包区段">
            <el-table-column prop="started_at" label="开始时间" min-width="180" />
            <el-table-column prop="ended_at" label="结束时间" min-width="180" />
            <el-table-column prop="duration_seconds" label="持续时间（秒）" width="130" />
            <el-table-column prop="loss_count" label="丢包数" width="90" />
            <el-table-column prop="mr_name" label="MR" min-width="150" />
            <el-table-column prop="current_ap_name" label="AP" min-width="150" />
            <el-table-column prop="station" label="站点" min-width="130" />
            <el-table-column prop="section" label="区间" min-width="130" />
            <el-table-column prop="ap_transition_context" label="AP 切换前后" min-width="140"><template #default="{ row }">{{ groundTransitionContextLabel(row.ap_transition_context) }}</template></el-table-column>
            <el-table-column prop="position_quality" label="位置质量" min-width="110"><template #default="{ row }">{{ groundStatusLabel(row.position_quality) }}</template></el-table-column>
          </el-table>
        </section>
      </section>
    </NcFloatingWindow>

    <NcFloatingWindow
      v-model="deepWindowOpen"
      :title="selectedDeepCollector ? `${selectedDeepCollector.train_id} · ${selectedDeepCollector.mr_role || selectedDeepCollector.mr_id} · 深度采集实时数据` : '深度采集实时数据'"
      :subtitle="selectedDeepCollector ? `${groundStatusLabel(selectedDeepCollector.state)} · ${selectedDeepCollector.collector_session_id || '尚未创建会话'}` : ''"
      window-id="ground-deep-collection"
      route-key="rail-ground-unattended"
      @close="handleDeepWindowClosed"
    >
      <section v-if="selectedDeepCollector" class="deep-floating-content">
        <div class="coverage-strip">
          <span>运行 <b>{{ selectedDeepCollector.run_id || selectedRunId }}</b></span>
          <span>MR <b>{{ selectedDeepCollector.mr_role || '未知' }} / {{ selectedDeepCollector.management_ip || '未配置' }}</b></span>
          <span>状态 <b>{{ groundStatusLabel(selectedDeepCollector.state) }}</b></span>
          <span>开始 <b>{{ selectedDeepCollector.started_at || '尚未开始' }}</b></span>
          <span>最后记录 <b>{{ selectedDeepCollector.last_record_at || '尚未收到数据' }}</b></span>
          <span>原始数据 <b>{{ bytes(selectedDeepCollector.bytes_written) }}</b></span>
          <span>AP / 站点 <b>{{ selectedDeepCollector.current_ap || '未知' }} / {{ selectedDeepCollector.station || '未知' }}</b></span>
          <span>fping <b>{{ selectedDeepCollector.fping_status }} / {{ selectedDeepCollector.fping_target_ip || '等待目标' }}</b></span>
          <span>fping 样本 <b>{{ selectedDeepCollector.fping_sample_count }}</b></span>
          <span>fping 参数 <b>{{ selectedDeepCollector.fping_interval_ms || '—' }} / {{ selectedDeepCollector.fping_timeout_ms || '—' }} ms · {{ selectedDeepCollector.fping_packet_size || '—' }} Bytes</b></span>
          <span>fping RTT <b>{{ metric(selectedDeepCollector.fping_latest_latency_ms, 'ms') }} / 平均 {{ metric(selectedDeepCollector.fping_avg_latency_ms, 'ms') }}</b></span>
          <span>fping 丢包 <b>{{ selectedDeepCollector.fping_loss_percent == null ? '—' : `${selectedDeepCollector.fping_loss_percent.toFixed(2)}%` }}</b></span>
          <span>Ping 完整性 <b>{{ selectedDeepCollector.data_integrity_status }}</b></span>
        </div>
        <el-alert v-if="selectedDeepCollector.fping_error || selectedDeepCollector.data_integrity_status === 'INCOMPLETE'" type="error" :closable="false" show-icon :title="selectedDeepCollector.fping_error || '本次深度采集缺少完整 fping 时序数据'" />
        <div class="toolbar">
          <el-select v-model="deepCategory" @change="loadDeepRecords(true)">
            <el-option label="全部" value="ALL" /><el-option label="WMESH" value="WMESH" />
            <el-option label="RSSI" value="RSSI" /><el-option label="Radio" value="RADIO" />
            <el-option label="状态" value="STATUS" /><el-option label="原始输出" value="RAW_OUTPUT" />
          </el-select>
          <el-input v-model="deepKeyword" clearable placeholder="搜索实时记录" @change="loadDeepRecords(true)" />
          <el-checkbox v-model="deepAutoRefresh">自动刷新</el-checkbox>
          <el-button :icon="deepPaused ? VideoPlay : VideoPause" @click="toggleDeepPaused">{{ deepPaused ? '继续显示' : '暂停显示' }}</el-button>
          <el-button :icon="Refresh" :loading="deepRecordsLoading" @click="loadDeepRecords(true)">跳到最新</el-button>
          <el-button :icon="CopyDocument" @click="copyDeepRecords">复制</el-button>
        </div>
        <el-alert v-if="!selectedDeepCollector.collector_session_id" type="info" :closable="false" show-icon :title="selectedDeepCollector.state_reason" />
        <div v-else class="deep-records-container">
          <el-table :data="deepRecords" size="small" height="100%" :empty-text="selectedDeepCollector.state === 'RUNNING' ? 'Collector 已运行，等待原始记录写入' : '暂无可读取的采集记录'">
            <el-table-column prop="timestamp" label="时间" min-width="180" />
            <el-table-column prop="category" label="分类" width="110" />
            <el-table-column prop="source" label="来源" min-width="150" />
            <el-table-column prop="text" label="记录" min-width="540" show-overflow-tooltip />
          </el-table>
        </div>
      </section>
    </NcFloatingWindow>

    <el-dialog v-model="archiveDialog" :title="t('ground.archive_summary', '无人值守归档汇总')" width="min(1100px, 96vw)" top="4vh">
      <el-tabs v-if="selectedArchive" v-model="archiveDetailTab">
        <el-tab-pane label="归档概览" name="overview">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('ground.run_date', '运行日期')">{{ selectedArchive.archive.run_date }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.archive_status', '归档状态')">{{ groundStatusLabel(selectedArchive.archive.archive_status) }}</el-descriptions-item>
            <el-descriptions-item label="实际开始">{{ selectedArchive.archive.actual_started_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="实际结束">{{ selectedArchive.archive.actual_ended_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="运行模式">{{ groundRunModeLabel(selectedArchive.archive.summary.running_mode) }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.mainline_trains', '正线车辆')">{{ selectedArchive.archive.mainline_train_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.ping_targets', 'Ping 目标')">{{ selectedArchive.archive.ping_target_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.ping_samples', 'Ping 样本')">{{ selectedArchive.archive.ping_sample_count }}</el-descriptions-item>
            <el-descriptions-item label="Syslog 记录">{{ selectedArchive.archive.summary.syslog_record_count || 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.covered_trains', '覆盖列车')">{{ selectedArchive.archive.covered_train_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.run_sessions', '运行会话')">{{ selectedArchive.archive.session_count || selectedArchive.archive.summary.session_count || 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.complete_sessions', '完整会话')">{{ selectedArchive.archive.complete_session_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.partial_sessions', '部分会话')">{{ selectedArchive.archive.partial_session_count }}</el-descriptions-item>
            <el-descriptions-item :label="t('ground.archive_size', '归档大小')">{{ bytes(selectedArchive.archive.archive_size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="归档 SHA-256" :span="2"><code>{{ selectedArchive.archive.sha256 }}</code></el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="运行会话" name="sessions">
          <el-table :data="selectedArchive.archive.summary.sessions || []" size="small" empty-text="当天没有独立会话记录">
            <el-table-column prop="session_id" label="会话 ID" min-width="220" />
            <el-table-column prop="started_at" label="启动时间" min-width="190" />
            <el-table-column prop="ended_at" label="停止时间" min-width="190" />
            <el-table-column prop="state" label="状态" width="120" />
            <el-table-column prop="stop_reason" label="停止原因" min-width="220" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="文件清单" name="files">
          <el-table :data="selectedArchive.files" size="small" max-height="480" empty-text="归档没有可展示的文件成员">
            <el-table-column prop="path" label="ZIP Entry" min-width="300" fixed />
            <el-table-column prop="data_type" label="数据类型" width="110" />
            <el-table-column prop="train_id" label="列车" width="120" />
            <el-table-column prop="mr_id" label="MR" min-width="150" />
            <el-table-column prop="mr_role" label="CT/CW" width="80" />
            <el-table-column prop="hour" label="小时" width="90" />
            <el-table-column prop="record_count" label="记录数" width="100" />
            <el-table-column label="原始大小" width="120"><template #default="{ row }">{{ bytes(row.size_bytes) }}</template></el-table-column>
            <el-table-column label="压缩大小" width="120"><template #default="{ row }">{{ bytes(row.compressed_size_bytes) }}</template></el-table-column>
            <el-table-column prop="parse_status" label="解析状态" width="110" />
            <el-table-column prop="sha256" label="SHA-256" min-width="260" show-overflow-tooltip />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="Ping 汇总" name="ping">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Ping 目标">{{ selectedArchive.archive.ping_target_count }}</el-descriptions-item>
            <el-descriptions-item label="Ping 样本">{{ selectedArchive.archive.ping_sample_count }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="Syslog 汇总" name="syslog">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Syslog 记录">{{ selectedArchive.archive.summary.syslog_record_count || 0 }}</el-descriptions-item>
            <el-descriptions-item label="Syslog 文件">{{ selectedArchive.files.filter((row) => row.data_type === 'syslog').length }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="深度会话" name="deep">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="完整会话">{{ selectedArchive.archive.complete_session_count }}</el-descriptions-item>
            <el-descriptions-item label="部分会话">{{ selectedArchive.archive.partial_session_count }}</el-descriptions-item>
            <el-descriptions-item label="覆盖列车">{{ selectedArchive.archive.covered_train_count }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="完整性校验" name="integrity">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="校验状态">{{ groundStatusLabel(selectedArchive.validation.status) }}</el-descriptions-item>
            <el-descriptions-item label="最后校验">{{ selectedArchive.validation.checked_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="清单文件数">{{ selectedArchive.validation.file_count }}</el-descriptions-item>
            <el-descriptions-item label="总记录数">{{ archiveRecordCount }}</el-descriptions-item>
            <el-descriptions-item label="ZIP 大小">{{ bytes(selectedArchive.validation.archive_size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="旧版 Manifest">{{ selectedArchive.validation.legacy_manifest ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="ZIP SHA-256" :span="2"><code>{{ selectedArchive.validation.archive_sha256 }}</code></el-descriptions-item>
            <el-descriptions-item label="Manifest SHA-256" :span="2"><code>{{ selectedArchive.validation.manifest_sha256 }}</code></el-descriptions-item>
            <el-descriptions-item label="校验说明" :span="2">{{ selectedArchive.validation.message }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="保留策略" name="retention">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="保留截止">{{ selectedArchive.archive.retention_until || '未设置' }}</el-descriptions-item>
            <el-descriptions-item label="归档创建">{{ selectedArchive.archive.created_at || '—' }}</el-descriptions-item>
            <el-descriptions-item label="最近更新">{{ selectedArchive.archive.updated_at || '—' }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button v-if="selectedArchive" @click="verifyArchive">重新校验</el-button>
        <el-button v-if="selectedArchive" @click="downloadArchiveSummary(selectedArchive.archive)">下载 JSON</el-button>
        <el-button v-if="selectedArchive" type="primary" @click="downloadArchiveZip(selectedArchive.archive)">下载原始 ZIP</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="syslogDetailDrawer" title="Syslog 原始记录详情" size="min(720px, 92vw)" destroy-on-close>
      <template v-if="selectedSyslogRecord">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="运行上下文">{{ selectedRun?.run_date || '—' }} · {{ selectedRunId || '—' }}</el-descriptions-item>
          <el-descriptions-item label="接收 / 设备时间">{{ selectedSyslogRecord.receive_time }} / {{ selectedSyslogRecord.device_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="时间差">{{ selectedSyslogRecord.clock_offset_ms == null ? '—' : `${selectedSyslogRecord.clock_offset_ms} ms` }}</el-descriptions-item>
          <el-descriptions-item label="列车 / MR">{{ selectedSyslogRecord.train_no || '未识别' }}（{{ selectedSyslogRecord.train_id || '—' }}）/ {{ selectedSyslogRecord.mr_name || selectedSyslogRecord.source_ip }}（{{ selectedSyslogRecord.device_uuid || '—' }}）</el-descriptions-item>
          <el-descriptions-item label="来源 / system_name">{{ selectedSyslogRecord.source_ip }}:{{ selectedSyslogRecord.source_port || '—' }} / {{ selectedSyslogRecord.system_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="Facility / 级别">{{ selectedSyslogRecord.facility || '—' }} / {{ groundSeverityLabel(selectedSyslogRecord.severity) }}</el-descriptions-item>
          <el-descriptions-item label="事件族 / 事件">{{ selectedSyslogRecord.event_family || '—' }} / {{ groundEventLabel(selectedSyslogRecord.event_type) }}</el-descriptions-item>
          <el-descriptions-item label="射频接口 / 状态">{{ selectedSyslogRecord.interface_name || '—' }} / {{ groundStatusLabel(selectedSyslogRecord.physical_state) }}</el-descriptions-item>
          <el-descriptions-item label="CFG EventIndex / 来源">{{ selectedSyslogRecord.cfg_event_index || '—' }} / {{ groundControlSourceLabel(selectedSyslogRecord.cfg_command_source) }}</el-descriptions-item>
          <el-descriptions-item label="配置来源 / 目标">{{ selectedSyslogRecord.cfg_source || '—' }} / {{ selectedSyslogRecord.cfg_destination || '—' }}</el-descriptions-item>
          <el-descriptions-item label="预期内部变更">{{ selectedSyslogRecord.expected_internal_change ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="关联状态">{{ groundStatusLabel(selectedSyslogRecord.correlation_status) }} / {{ groundStatusLabel(selectedSyslogRecord.correlation_confidence) }} / {{ selectedSyslogRecord.correlation_delta_ms == null ? '—' : `${selectedSyslogRecord.correlation_delta_ms} ms` }}</el-descriptions-item>
          <el-descriptions-item label="综合事件">{{ selectedSyslogRecord.composite_event_type ? groundEventLabel(selectedSyslogRecord.composite_event_type) : '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联结构化事件 ID">{{ selectedSyslogRecord.correlated_event_ids.length ? selectedSyslogRecord.correlated_event_ids.join(', ') : '—' }}</el-descriptions-item>
          <el-descriptions-item label="AP 切换">{{ selectedSyslogRecord.previous_peer_name || selectedSyslogRecord.previous_peer_mac || '—' }} → {{ selectedSyslogRecord.peer_name || selectedSyslogRecord.peer_mac || '—' }}</el-descriptions-item>
          <el-descriptions-item label="站点 / 区间">{{ selectedSyslogRecord.station || '—' }} / {{ selectedSyslogRecord.section || '—' }}</el-descriptions-item>
          <el-descriptions-item label="AP 解析 / 名称来源">{{ groundStatusLabel(selectedSyslogRecord.resolution_status) }} / {{ groundDisplayNameSourceLabel(selectedSyslogRecord.parsed_details.display_name_source) }}</el-descriptions-item>
          <el-descriptions-item label="身份 / 解析 / 质量">{{ groundStatusLabel(selectedSyslogRecord.identity_status) }} / {{ groundStatusLabel(selectedSyslogRecord.parse_status) }} / {{ groundStatusLabel(selectedSyslogRecord.data_quality) }}</el-descriptions-item>
          <el-descriptions-item label="接收序号">{{ selectedSyslogRecord.global_receive_sequence ?? '—' }} / {{ selectedSyslogRecord.source_receive_sequence ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="数据来源">{{ groundSourceLabel(selectedSyslogRecord.data_source) }}<span v-if="selectedSyslogRecord.archive_entry"> · {{ selectedSyslogRecord.archive_entry }}</span></el-descriptions-item>
          <el-descriptions-item label="原始文件">{{ selectedSyslogRecord.raw_file_id }} · 行 {{ selectedSyslogRecord.raw_line_number ?? '—' }} · {{ groundStatusLabel(selectedSyslogRecord.raw_file_status) }}</el-descriptions-item>
        </el-descriptions>
        <h3>解析字段</h3>
        <pre class="raw-record">{{ JSON.stringify(syslogVisibleDetails(selectedSyslogRecord.parsed_details), null, 2) }}</pre>
        <h3>原始报文</h3>
        <el-button @click="copySyslogRaw">{{ t('ground.syslog.copy_raw', '复制原始内容') }}</el-button>
        <pre class="raw-record">{{ selectedSyslogRecord.raw_text }}</pre>
      </template>
    </el-drawer>

    <el-dialog v-model="trainDialog" :title="t('ground.train_detail', '列车无人值守详情')" width="min(820px, 94vw)">
      <template v-if="selectedTrain">
        <el-alert
          :title="`AP Identity: ${selectedTrain.ap_identity_diagnostics?.ap_identity_match_status || 'NOT_CHECKED'} / ${selectedTrain.ap_identity_diagnostics?.canonical_current_ap || '—'}`"
          :description="`站点匹配 ${selectedTrain.ap_identity_diagnostics?.station_match_status || 'UNMATCHED'}，依据 ${selectedTrain.ap_identity_diagnostics?.matched_by || 'none'}，主线/Ping 原因码 ${selectedTrain.mainline_reason_code} / ${selectedTrain.ping_reason_code}，决策 r${selectedTrain.decision_revision} ${selectedTrain.decision_source}`"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
        />
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('ground.train', '列车')">{{ selectedTrain.train_no || selectedTrain.train_name }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.eligibility', '正线判断')"><el-tag :type="statusType(selectedTrain.eligibility_status)">{{ groundStatusLabel(selectedTrain.eligibility_status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="位置类型">{{ groundStatusLabel(selectedTrain.location_class) }}</el-descriptions-item>
          <el-descriptions-item label="是否正线">{{ selectedTrain.participates_in_mainline ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="位置判定来源">{{ selectedTrain.location_class_source }}</el-descriptions-item>
          <el-descriptions-item label="Ping 纳入原因" :title="selectedTrain.ping_reason_code">{{ selectedTrain.ping_reason_text || '未评估' }}</el-descriptions-item>
          <el-descriptions-item label="深采资格" :title="selectedTrain.deep_collection_reason_code">{{ selectedTrain.deep_collection_reason_text || '未评估' }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.current_ap', '当前 AP')">{{ selectedTrain.current_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="位置匹配等级">{{ groundStatusLabel(selectedTrain.location_match_level) }}</el-descriptions-item>
          <el-descriptions-item label="原始 AP 名称">{{ selectedTrain.raw_peer_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原始 AP MAC">{{ selectedTrain.raw_peer_ap_mac || '—' }}</el-descriptions-item>
          <el-descriptions-item label="解析后 AP">{{ selectedTrain.resolved_ap_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="规范站点">{{ selectedTrain.canonical_station_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="匹配依据" :span="2">{{ selectedTrain.location_match_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.same_ap_duration', '同 AP 停留')">{{ duration(selectedTrain.same_ap_duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item :label="t('ground.exclusion_reason', '排除原因')" :span="2">{{ selectedTrain.exclusion_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT 会话">{{ selectedTrainCollection?.ct_session_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CW 会话">{{ selectedTrainCollection?.cw_session_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT Syslog">{{ groundStatusLabel(endpoint(selectedTrain, 'CT')?.syslog_status) }}</el-descriptions-item>
          <el-descriptions-item label="CW Syslog">{{ groundStatusLabel(endpoint(selectedTrain, 'CW')?.syslog_status) }}</el-descriptions-item>
          <el-descriptions-item label="CT Syslog 当前 AP">
            {{ endpoint(selectedTrain, 'CT')?.position_current_ap_name || '—' }}
            <span v-if="endpoint(selectedTrain, 'CT')?.position_current_ap_mac"> / {{ endpoint(selectedTrain, 'CT')?.position_current_ap_mac }}</span>
            <small> · {{ endpoint(selectedTrain, 'CT')?.position_freshness || 'NO_DATA' }} · {{ endpoint(selectedTrain, 'CT')?.position_source || '—' }}</small>
          </el-descriptions-item>
          <el-descriptions-item label="CW Syslog 当前 AP">
            {{ endpoint(selectedTrain, 'CW')?.position_current_ap_name || '—' }}
            <span v-if="endpoint(selectedTrain, 'CW')?.position_current_ap_mac"> / {{ endpoint(selectedTrain, 'CW')?.position_current_ap_mac }}</span>
            <small> · {{ endpoint(selectedTrain, 'CW')?.position_freshness || 'NO_DATA' }} · {{ endpoint(selectedTrain, 'CW')?.position_source || '—' }}</small>
          </el-descriptions-item>
          <el-descriptions-item label="CT 上一个 AP">{{ endpoint(selectedTrain, 'CT')?.position_previous_ap_name || '—' }}<span v-if="endpoint(selectedTrain, 'CT')?.position_previous_ap_mac"> / {{ endpoint(selectedTrain, 'CT')?.position_previous_ap_mac }}</span></el-descriptions-item>
          <el-descriptions-item label="CW 上一个 AP">{{ endpoint(selectedTrain, 'CW')?.position_previous_ap_name || '—' }}<span v-if="endpoint(selectedTrain, 'CW')?.position_previous_ap_mac"> / {{ endpoint(selectedTrain, 'CW')?.position_previous_ap_mac }}</span></el-descriptions-item>
          <el-descriptions-item label="CT 位置时间">事件 {{ endpoint(selectedTrain, 'CT')?.position_last_event_time || '—' }} · 接收 {{ endpoint(selectedTrain, 'CT')?.position_last_receive_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CW 位置时间">事件 {{ endpoint(selectedTrain, 'CW')?.position_last_event_time || '—' }} · 接收 {{ endpoint(selectedTrain, 'CW')?.position_last_receive_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT 位置更新延迟">{{ endpoint(selectedTrain, 'CT')?.position_latency_ms == null ? '—' : `${endpoint(selectedTrain, 'CT')?.position_latency_ms} ms` }} · {{ endpoint(selectedTrain, 'CT')?.position_commit_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CW 位置更新延迟">{{ endpoint(selectedTrain, 'CW')?.position_latency_ms == null ? '—' : `${endpoint(selectedTrain, 'CW')?.position_latency_ms} ms` }} · {{ endpoint(selectedTrain, 'CW')?.position_commit_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="CT 射频 / 控制来源">{{ groundStatusLabel(endpoint(selectedTrain, 'CT')?.radio_overall_state || 'UNKNOWN') }} / {{ groundControlSourceLabel(endpoint(selectedTrain, 'CT')?.cfg_command_source) }}</el-descriptions-item>
          <el-descriptions-item label="CW 射频 / 控制来源">{{ groundStatusLabel(endpoint(selectedTrain, 'CW')?.radio_overall_state || 'UNKNOWN') }} / {{ groundControlSourceLabel(endpoint(selectedTrain, 'CW')?.cfg_command_source) }}</el-descriptions-item>
        </el-descriptions>
        <section v-for="mrEndpoint in selectedTrain.endpoints" :key="`loghost:${mrEndpoint.mr_id || mrEndpoint.endpoint}`" class="loghost-section">
          <div class="network-status">
            <b>{{ mrEndpoint.endpoint }} · 设备现有日志主机</b>
            <span>NetConsole 管理目标：{{ mrEndpoint.managed_target_ip || profile?.syslog_server_ip || '—' }}:{{ mrEndpoint.managed_target_port || profile?.syslog_server_port || '—' }}</span>
            <el-tag v-for="item in mrEndpoint.managed_target_statuses" :key="item" :type="item === 'TARGET_PRESENT' ? 'success' : item === 'TARGET_PORT_CONFLICT' ? 'danger' : 'info'">{{ groundStatusLabel(item) }}</el-tag>
          </div>
          <el-table :data="mrEndpoint.configured_log_hosts" size="small" empty-text="尚未执行配置检查">
            <el-table-column prop="ip" label="IP" min-width="130" />
            <el-table-column prop="port" label="端口" width="90" />
            <el-table-column prop="facility" label="Facility" width="100" />
            <el-table-column label="归属" min-width="160"><template #default="{ row }">{{ groundSourceLabel(row.source) }}</template></el-table-column>
            <el-table-column label="判断" min-width="170"><template #default="{ row }">{{ row.same_ip_different_port ? '同 IP 端口冲突' : row.is_managed_target ? '目标一致' : '保留，不处理' }}</template></el-table-column>
          </el-table>
          <el-alert
            v-if="mrEndpoint.managed_target_statuses.includes('TARGET_PORT_CONFLICT')"
            :title="`设备已存在 ${mrEndpoint.managed_target_ip} 的其他端口；默认配置检查保持只读，不会进入 system-view。`"
            type="error"
            :closable="false"
            show-icon
          />
          <div class="boot-evidence">
            <span>估算上电时间：{{ mrEndpoint.estimated_boot_time || '—' }}</span>
            <span>误差：±{{ mrEndpoint.boot_time_uncertainty_seconds || 0 }} 秒</span>
            <span>原因：{{ mrEndpoint.reboot_reason || '—' }}</span>
            <span>设备时区：{{ mrEndpoint.timezone_name || '—' }}</span>
            <span>时间质量：{{ mrEndpoint.device_time_quality || '—' }}</span>
          </div>
          <el-button
            v-if="mrEndpoint.managed_target_statuses.includes('TARGET_PORT_CONFLICT')"
            type="danger"
            plain
            @click="confirmTargetPortChange(mrEndpoint.mr_id)"
          >确认修改此 MR 的目标端口</el-button>
        </section>
        <div class="dialog-actions">
          <el-button @click="showTrainPing(selectedTrain)">{{ t('ground.view_ping', '查看心跳检测') }}</el-button>
          <el-button @click="showTrainTimeline(selectedTrain)">{{ t('ground.view_timeline', '查看事件时间轴') }}</el-button>
          <el-button :disabled="!running" @click="checkConfigs(endpoint(selectedTrain, 'CT')?.mr_id || '')">检查 CT 配置</el-button>
          <el-button :loading="openingSessionId === selectedTrainCollection?.ct_session_id" :disabled="!selectedTrainCollection?.ct_session_id || Boolean(openingSessionId)" @click="openDeepSession(selectedTrainCollection?.ct_session_id || '')">{{ t('ground.open_ct_session', '打开 CT 会话') }}</el-button>
          <el-button :loading="openingSessionId === selectedTrainCollection?.cw_session_id" :disabled="!selectedTrainCollection?.cw_session_id || Boolean(openingSessionId)" @click="openDeepSession(selectedTrainCollection?.cw_session_id || '')">{{ t('ground.open_cw_session', '打开 CW 会话') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </main>
</template>

<style scoped src="./groundUnattended.css"></style>
