<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useGroundContext } from './useGroundUnattended'
import { syslogVisibleDetails } from './groundSyslogPresentation'

const {
  t, status, selectedRunId, historySyslogRunId, runs, selectedSyslogRecord, syslogDetailDrawer,
  groundStatusLabel, groundSeverityLabel, groundEventLabel, groundSourceLabel, groundTransitionContextLabel,
  groundControlSourceLabel, groundDisplayNameSourceLabel,
} = useGroundContext()
const runId = computed(() => historySyslogRunId.value || selectedRunId.value)
const runDate = computed(() => runs.value.find((run) => run.run_id === runId.value)?.run_date || status.value?.active_run_date)
async function copySyslogRaw() {
  try {
    await navigator.clipboard.writeText(selectedSyslogRecord.value?.raw_text || '')
    ElMessage.success(t('common.copied', '已复制'))
  } catch {
    ElMessage.error(t('ground.syslog.copy_failed', '复制失败，请选择原始报文手动复制'))
  }
}
</script>

<template>
    <el-drawer v-model="syslogDetailDrawer" title="Syslog 原始记录详情" size="min(720px, 92vw)" destroy-on-close>
      <template v-if="selectedSyslogRecord">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="运行上下文">{{ runDate || '—' }} · {{ runId || '—' }}</el-descriptions-item>
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
</template>

<style scoped src="./groundUnattended.css"></style>
