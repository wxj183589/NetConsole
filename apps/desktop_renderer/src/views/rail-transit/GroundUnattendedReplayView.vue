<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import { provideGroundContext } from './useGroundUnattended'
import GroundSyslogDetail from './GroundSyslogDetail.vue'
import { GROUND_TAB_FEATURES } from './groundFeatures'

const Playback = defineAsyncComponent(() => import('../../components/ground-unattended/GroundHistoryPlayback.vue'))
const ArchivePage = defineAsyncComponent(() => import('./ArchivePage.vue'))
const SyslogPage = defineAsyncComponent(() => import('./SyslogPage.vue'))
const {
  t, Refresh, activeTab, pageVisible, pageActivated, profile, runs, runHistoryDeleteLoading, loading,
  historySyslogRunId, generalLoadIssues, loadIssueDescription, loadAll, deleteSelectedRunHistory,
  archiveDialog, archiveDetailTab, selectedArchive, archiveRecordCount, groundStatusLabel,
  groundRunModeLabel, bytes, verifyArchive, downloadArchiveSummary, downloadArchiveZip,
} = provideGroundContext('replay')
const active = computed(() => activeTab.value === 'playback' && pageVisible.value && pageActivated.value)
const historicalRuns = computed(() => runs.value.filter((run) => run.actual_started_at && run.actual_ended_at
  && ['COMPLETED', 'FAILED', 'CANCELLED', 'ERROR'].includes(run.state)))
const { archives: archiveFeature, syslog: syslogFeature } = GROUND_TAB_FEATURES
</script>

<template>
  <main v-loading="loading" class="ground-page">
    <header class="page-heading">
      <h1>{{ t('ground.replay_title', '地面无人值守 · 归档回放') }}</h1>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll()">{{ t('common.refresh', '刷新') }}</el-button>
    </header>
    <details v-if="generalLoadIssues.length" class="load-warning">
      <summary>{{ t('ground.replay_load_failed', '归档数据读取失败') }}</summary>
      <p>{{ loadIssueDescription }}</p>
    </details>
    <el-tabs v-model="activeTab">
      <el-tab-pane :label="t('ground.replay_tab', '运行回放')" name="playback">
        <Playback
          v-if="profile?.site_id"
          :key="profile.site_id"
          :site-id="profile.site_id"
          :runs="historicalRuns"
          :trains="[]"
          :active="active"
          :deleting="runHistoryDeleteLoading"
          @delete-run="deleteSelectedRunHistory"
          @view-syslog="historySyslogRunId = $event"
        />
        <SyslogPage v-if="active && historySyslogRunId && isFeatureEnabled(syslogFeature)" />
      </el-tab-pane>
      <el-tab-pane v-if="isFeatureVisible(archiveFeature)" :disabled="!isFeatureEnabled(archiveFeature)" :label="t('ground.archives', '历史归档')" name="archives" lazy>
        <ArchivePage />
      </el-tab-pane>
    </el-tabs>
    <GroundSyslogDetail />
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
  </main>
</template>

<style scoped src="./groundUnattended.css"></style>
