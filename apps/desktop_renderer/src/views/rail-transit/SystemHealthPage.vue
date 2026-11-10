<script setup lang="ts">
import { t } from '../../i18n/runtime'
import type { GroundHealthStatus } from '../../types/groundUnattended'
import { useGroundContext } from './useGroundUnattended'
const { groundStatusLabel, health, bytes } = useGroundContext()
const healthType = (status?: GroundHealthStatus) => ({ HEALTHY: 'success', DEGRADED: 'warning', CRITICAL: 'danger', UNKNOWN: 'info' } as const)[status || 'UNKNOWN']
const alive = (value?: boolean | null) => value == null ? '—' : value ? t('ground.v2.dynamic_221', '运行') : t('ground.v2.dynamic_222', '停止')
const seconds = (value?: number | null) => value == null ? '—' : `${value.toFixed(1)} ${t('ground.v2.dynamic_223', '秒')}`
const milliseconds = (value?: number | null) => value == null ? '—' : `${value.toFixed(1)} ms`
</script>

<template>
  <section class="ground-subpage">
    <div class="section-heading">
      <div><h2>{{ t('ground.health', '系统健康') }}</h2><p>{{ t('ground.v2.health_note', '监测服务状态独立于设备在线状态。缺测指标显示“—”。') }}</p></div>
      <el-tag :type="healthType(health?.status)">{{ groundStatusLabel(health?.status || 'UNKNOWN') }}</el-tag>
    </div>
    <section class="content-card">
      <h3>{{ t('ground.v2.backend_heartbeat', 'Backend 与心跳检测') }}</h3>
      <div class="health-grid">
        <article><span>Supervisor</span><strong>{{ alive(health?.supervisor_running) }}</strong><small>{{ t('ground.v2.run_state', '运行状态') }} {{ health?.run_state ? groundStatusLabel(health.run_state) : '—' }}</small></article>
        <article><span>{{ t('ground.v2.elapsed_run', '本次运行时长') }}</span><strong>{{ seconds(health?.run_elapsed_seconds) }}</strong><small>{{ t('ground.v2.health_snapshot', '健康快照') }} {{ health?.updated_at || '—' }}</small></article>
        <article><span>{{ t('ground.v2.ping_targets_processes', 'Ping 目标 / fping 进程') }}</span><strong>{{ health?.ping_target_count ?? '—' }} / {{ health?.ping_process_count ?? '—' }}</strong></article>
        <article><span>{{ t('ground.v2.heartbeat_rate', '心跳每秒采样量') }}</span><strong>{{ health?.ping_sample_rate_per_second ?? '—' }} /s</strong><small>{{ t('ground.v2.last_sample', '最近采样') }} {{ health?.ping_last_sample_at || '—' }}</small></article>
        <article><span>{{ t('ground.v2.heartbeat_write_latency', '心跳采样写入延迟') }}</span><strong>{{ milliseconds(health?.ping_sample_write_duration_ms) }}</strong></article>
        <article><span>{{ t('ground.v2.heartbeat_warnings', '心跳 Worker 提示') }}</span><strong>{{ health?.ping_worker_warnings?.join('；') || '—' }}</strong></article>
        <article><span>{{ t('ground.v2.deep_pending', '深度采集待处理') }}</span><strong>{{ health?.deep_queue_length ?? '—' }}</strong></article>
        <article><span>{{ t('ground.v2.latest_system_error', '最近系统错误') }}</span><strong>{{ health?.last_error || '—' }}</strong></article>
      </div>
    </section>
    <section class="content-card">
      <h3>{{ t('ground.v2.syslog_processing', 'Syslog 接收与处理') }}</h3>
      <div class="health-grid">
        <article><span>{{ t('ground.v2.syslog_received_written_parsed', 'Syslog 接收 / 原始写入 / 解析') }}</span><strong>{{ health?.received ?? '—' }} / {{ health?.written ?? '—' }} / {{ health?.parsed ?? '—' }}</strong><small>{{ t('ground.v2.ingested', '入库') }} {{ health?.db_saved ?? '—' }} · {{ t('ground.v2.health_dropped', '丢弃') }} {{ health?.dropped ?? '—' }}</small></article>
        <article><span>UDP Receiver / Writer / Parser</span><strong>{{ alive(health?.receiver_alive) }} / {{ alive(health?.writer_alive) }} / {{ alive(health?.parser_alive) }}</strong><small>{{ health?.udp_listen_address || '—' }}</small></article>
        <article><span>Raw Queue</span><strong>{{ health?.memory_queue_size ?? '—' }} / {{ health?.memory_queue_capacity ?? '—' }}</strong></article>
        <article><span>Parser Queue</span><strong>{{ health?.parser_queue_size ?? '—' }} / {{ health?.parser_queue_capacity ?? '—' }}</strong><small>{{ t('ground.v2.spool_pending', '待回放 Spool') }} {{ t('ground.v2.health_item_count', '{count} 个').replace('{count}', String(health?.disk_queue_count ?? '—')) }}</small></article>
        <article><span>{{ t('ground.v2.spool_disk', 'Spool / 磁盘') }}</span><strong>{{ health ? bytes(health.spool_bytes) : '—' }} / {{ health?.disk_usage_percent ?? '—' }}%</strong><small>{{ t('ground.v2.health_file_count', '{count} 个文件').replace('{count}', String(health?.spool_files ?? '—')) }} · {{ t('ground.v2.health_protection', '保护') }} {{ groundStatusLabel(health?.spool_guard_state) }}</small></article>
        <article><span>{{ t('ground.v2.last_write_segment', '最近写入 / 当前分段') }}</span><strong>{{ health?.last_write_time || '—' }}</strong><small>{{ health?.raw_file || '—' }} · {{ health ? bytes(health.raw_file_size) : '—' }}</small></article>
        <article><span>{{ t('ground.v2.write_fsync_latency', '写入 / fsync 延迟') }}</span><strong>{{ milliseconds(health?.raw_last_write_duration_ms) }} / {{ milliseconds(health?.durable_sync_latency_ms) }}</strong><small>{{ t('ground.v2.batch_average', '批次均值') }} {{ health ? bytes(health.raw_batch_bytes_avg) : '—' }}</small></article>
        <article><span>{{ t('ground.v2.udp_rate', 'UDP 平均接收速率') }}</span><strong>{{ health?.udp_receive_rate_per_second ?? '—' }} /s</strong><small>{{ t('ground.v2.unknown_source', '未知来源') }} {{ health?.udp_unidentified_count ?? '—' }}</small></article>
        <article><span>{{ t('ground.v2.raw_write_failed', '原始写入 / 失败') }}</span><strong>{{ health?.raw_records_written ?? '—' }} / {{ health?.raw_write_failed_count ?? '—' }}</strong><small>{{ health ? bytes(health.raw_bytes_written) : '—' }}</small></article>
        <article><span>{{ t('ground.v2.database_pending_batch_duration', '数据库待写 / 批次耗时') }}</span><strong>{{ health?.database_pending_count ?? '—' }} / {{ milliseconds(health?.database_last_batch_duration_ms) }}</strong></article>
      </div>
    </section>
    <section class="content-card">
      <h3>{{ t('ground.v2.storage_archives', '存储、压缩与归档') }}</h3>
      <div class="health-grid">
        <article><span>{{ t('ground.v2.disk_total_free', '磁盘总空间 / 剩余') }}</span><strong>{{ health ? bytes(health.disk_total_bytes) : '—' }} / {{ health ? bytes(health.disk_free_bytes) : '—' }}</strong></article>
        <article><span>{{ t('ground.v2.raw_files_open', '登记原始文件 / 当前打开') }}</span><strong>{{ health?.raw_file_count ?? '—' }} / {{ health?.open_file_count ?? '—' }}</strong></article>
        <article><span>{{ t('ground.v2.raw_write_rate', '原始文件平均写入速率') }}</span><strong>{{ health ? bytes(health.raw_write_rate_bytes_per_second) : '—' }}/s</strong><small>{{ t('ground.v2.since_syslog_start', '自本次 Syslog 接收启动起计算') }}</small></article>
        <article><span>{{ t('ground.v2.archives_pending_failed', '归档待处理 / 失败') }}</span><strong>{{ health?.archive_pending_count ?? '—' }} / {{ health?.archive_failed_count ?? '—' }}</strong></article>
        <article><span>{{ t('ground.v2.compression_worker_queue', '压缩 Worker / 队列') }}</span><strong>{{ alive(health?.compression_worker_alive) }} · {{ health?.compression_queue_size ?? '—' }} / {{ health?.compression_queue_capacity ?? '—' }}</strong></article>
        <article><span>{{ t('ground.v2.compression_counts', '压缩提交 / 完成 / 失败 / 跳过') }}</span><strong>{{ health?.compression_submitted_count ?? '—' }} / {{ health?.compression_completed_count ?? '—' }} / {{ health?.compression_failed_count ?? '—' }} / {{ health?.compression_skipped_count ?? '—' }}</strong><small>队列满 {{ health?.compression_queue_full_count ?? '—' }} · 恢复 {{ health?.compression_recovery_count ?? '—' }} · 待压缩 {{ health?.compression_pending_count ?? '—' }} · {{ health?.compression_last_error || '—' }}</small></article>
        <article><span>{{ t('ground.v2.storage_profile', '数据盘 / 策略') }}</span><strong>{{ health?.volume || '—' }} · {{ health?.media_type || 'UNKNOWN' }}</strong><small>{{ !health ? '—' : health.storage_profile === 'FAST_STORAGE' ? t('ground.v2.dynamic_224', '高速存储模式') : t('ground.v2.dynamic_225', '机械磁盘/RAID兼容模式') }} · {{ health?.profile_source === 'MANUAL' ? t('ground.v2.dynamic_226', '手动覆盖') : t('ground.v2.dynamic_227', '自动检测') }}</small></article>
        <article><span>{{ t('ground.v2.storage_reason', '存储检测说明') }}</span><strong>{{ health?.storage_detection_reason || '—' }}</strong></article>
      </div>
    </section>
    <section class="content-card ac-poller-health">
      <div class="section-heading"><div><h3>{{ t('ground.v2.ac_resident', 'AC 常驻轮询') }}</h3><p>{{ t('ground.v2.ac_independent', '辅助数据源异常使系统降级；心跳检测独立运行。') }}</p></div></div>
      <el-empty v-if="!health?.ac_pollers?.length" :description="t('ground.v2.no_ac_poller', '当前没有活动 AC 常驻轮询')" />
      <div v-else class="ac-poller-grid">
        <article v-for="poller in health.ac_pollers" :key="poller.task_id || poller.controller_id">
          <header><strong>{{ poller.controller_name || poller.controller_id }}</strong><el-tag :type="healthType(poller.status)" size="small">{{ groundStatusLabel(poller.status) }}</el-tag></header>
          <p>{{ poller.connection_state }} · {{ poller.poll_interval_seconds }} {{ t('ground.v2.dynamic_223', '秒') }}</p>
          <small>{{ t('ground.v2.poll_success_rate', '轮询成功率') }} {{ poller.poll_count ? `${(poller.success_count / poller.poll_count * 100).toFixed(1)}%` : '—' }} · {{ t('ground.v2.health_polls', '轮询') }} {{ poller.poll_count }} · {{ t('ground.v2.health_successes', '成功') }} {{ poller.success_count }} · {{ t('ground.v2.health_failures', '失败') }} {{ poller.failure_count }} · {{ t('ground.v2.health_reconnections', '重连') }} {{ poller.reconnect_count }}</small>
          <small>{{ t('ground.v2.last_poll_success', '最近采集成功') }} {{ poller.last_success_at || '—' }} · {{ t('ground.v2.health_next_poll', '下次') }} {{ poller.next_poll_at || '—' }}</small>
          <small>{{ t('ground.v2.last_success_age', '距最近成功') }} {{ seconds(poller.last_success_age_seconds) }} {{ t('ground.v2.worker_heartbeat_age', '· Worker 心跳年龄') }} {{ seconds(poller.heartbeat_age_seconds) }}</small>
          <small>AC Query {{ poller.last_query_succeeded == null ? '—' : poller.last_query_succeeded ? '成功' : '失败' }} · {{ milliseconds(poller.last_query_duration_ms) }} · 超时 {{ poller.query_timeout_count }} 次</small>
          <small>Query {{ poller.last_query_started_at || '—' }} → {{ poller.last_query_completed_at || '—' }} · Snapshot {{ milliseconds(poller.snapshot_processing_duration_ms) }} · 变化 {{ poller.snapshot_change_count }}</small>
          <small v-if="poller.last_query_failure_at">最近 Query 失败 {{ poller.last_query_failure_at }}</small>
          <small v-if="poller.last_error" class="health-error">{{ poller.last_error }}</small>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped src="./groundUnattended.css"></style>
