<script setup lang="ts">
import { useGroundContext } from './useGroundUnattended'
const { Refresh, t, loading, saving, profile, pingPresets, trains, sourceRecommendation, udpPortCheck, networkLoading, showAllAddresses, profileLoadError, visibleIpv4Addresses, returnAddressIsLocal, listenAddressIsLocal, loadAll, saveProfile, loadLocalAddresses, recommendSourceAddress, applyRecommendedAddress, checkUdpPort, togglePriority, applyDeepPingPreset, markDeepPingCustom, restoreDeepPingDefault } = useGroundContext()
</script>

<template>
<section class="ground-subpage">
        <el-empty v-if="!profile" class="settings-empty" :description="t('ground.v2.settings_empty', '无人值守配置未加载')">
          <p class="muted">{{ profileLoadError || t('ground.v2.settings_init_note', '请确认 Backend 已完成无人值守服务初始化。') }}</p>
          <el-button :icon="Refresh" :loading="loading" type="primary" @click="loadAll()">{{ t('ground.v2.settings_reload', '重新加载配置') }}</el-button>
        </el-empty>
        <el-form v-else :model="profile" label-position="top" class="settings-form">
          <section><h2>{{ t('ground.schedule', '运行时间与 AC') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.start_time', '开始时间')"><el-time-select v-model="profile.schedule_start_time" start="00:00" step="00:05" end="23:55" /></el-form-item>
            <el-form-item :label="t('ground.end_time', '结束时间')"><el-time-select v-model="profile.schedule_end_time" start="00:00" step="00:05" end="23:55" /></el-form-item>
            <el-form-item :label="t('ground.timezone', '时区')">
              <el-select v-model="profile.timezone" filterable allow-create>
                <el-option :label="t('ground.v2.settings_timezone_shanghai', '北京时间（Asia/Shanghai）')" value="Asia/Shanghai" />
                <el-option :label="t('ground.v2.settings_timezone_utc', '协调世界时（UTC）')" value="UTC" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('ground.ac_poll', 'AC 轮询间隔（秒）')"><el-input-number v-model="profile.ac_poll_interval_seconds" :min="3" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.stationary', '同 AP 静止阈值（分钟）')"><el-input-number v-model="profile.stationary_exclusion_minutes" :min="1" :max="180" /></el-form-item>
            <el-form-item :label="t('ground.ac_grace', 'AC 异常 Ping 宽限（秒）')"><el-input-number v-model="profile.ac_stale_grace_seconds" :min="0" :max="3600" /></el-form-item>
            <el-form-item :label="t('ground.correlation_tolerance', 'AC/Ping 关联偏差（秒）')"><el-input-number v-model="profile.ac_ping_correlation_tolerance_seconds" :min="1" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.switch_window', 'AP 切换前 / 后窗口（秒）')"><div class="inline-numbers"><el-input-number v-model="profile.ap_switch_before_seconds" :min="0" :max="60" /><el-input-number v-model="profile.ap_switch_after_seconds" :min="0" :max="60" /></div></el-form-item>
          </div></section>
          <section><h2>{{ t('ground.deep_budget', '深度采集预算') }}</h2>
            <div class="mode-switch">
              <el-switch v-model="profile.deep_collection_master_enabled" :active-text="t('ground.v2.settings_enable_deep', '启用深度采集')" />
              <span>{{ profile.deep_collection_master_enabled ? t('ground.v2.standard_mode_note', '标准模式：运行 AC 轮询、心跳检测、Syslog 和深度 MR 采集。') : t('ground.v2.lightweight_mode_note', '轻量模式：仅运行 AC 轮询、心跳检测、Syslog 和位置关联，不启动 SSH 深度 MR 采集。') }}</span>
            </div>
            <div class="form-grid" :class="{ 'budget-disabled': !profile.deep_collection_master_enabled }">
            <el-form-item :label="t('ground.max_trains', '最大活动列车')"><el-input-number v-model="profile.max_active_trains" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.max_mrs', '最大活动 MR')"><el-input-number v-model="profile.max_active_mrs" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="16" /></el-form-item>
            <el-form-item :label="t('ground.max_starting', '最大启动中 MR')"><el-input-number v-model="profile.max_starting_mrs" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.max_finalizing', '最大最终化 MR')"><el-input-number v-model="profile.max_finalizing_mrs" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="8" /></el-form-item>
            <el-form-item :label="t('ground.minimum_duration', '最低有效时长（分钟）')"><el-input-number v-model="profile.minimum_valid_collection_minutes" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="720" /></el-form-item>
            <el-form-item :label="t('ground.preferred_duration', '建议采集时长（分钟）')"><el-input-number v-model="profile.preferred_collection_minutes" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="720" /></el-form-item>
            <el-form-item :label="t('ground.maximum_duration', '最大采集时长（分钟）')"><el-input-number v-model="profile.maximum_collection_minutes" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="1440" /></el-form-item>
            <el-form-item :label="t('ground.start_jitter', '启动错峰（秒）')"><el-input-number v-model="profile.start_jitter_seconds" :disabled="!profile.deep_collection_master_enabled" :min="0" :max="60" /></el-form-item>
            <el-form-item :label="t('ground.start_batch', '每批启动 MR 数')"><el-input-number v-model="profile.start_batch_size" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="4" /></el-form-item>
          </div>
            <el-divider content-position="left">{{ t('ground.v2.settings_deep_fping', '深度采集 fping（强制依赖）') }}</el-divider>
            <div class="mode-switch"><el-switch :model-value="true" disabled :active-text="t('ground.v2.settings_auto_enabled', '已自动启用')" /><span>{{ t('ground.v2.settings_deep_fping_note', '每个 CT/CW 深度会话自动 Ping 自己的 MR 管理 IP，用户不可关闭。') }}</span></div>
            <div class="form-grid" :class="{ 'budget-disabled': !profile.deep_collection_master_enabled }">
              <el-form-item :label="t('ground.v2.settings_ping_preset', 'Ping 参数方案')"><el-select v-model="profile.deep_fping.preset_key" :disabled="!profile.deep_collection_master_enabled" @change="applyDeepPingPreset"><el-option :label="t('ground.v2.settings_custom', '自定义')" value="" /><el-option v-for="item in pingPresets" :key="item.key" :label="item.name" :value="item.key" /></el-select></el-form-item>
              <el-form-item :label="t('ground.v2.settings_packet_bytes', '包大小（Bytes）')"><el-input-number v-model="profile.deep_fping.packet_size" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="65535" @change="markDeepPingCustom" /></el-form-item>
              <el-form-item :label="t('ground.v2.settings_ping_interval', 'Ping 间隔（ms）')"><el-input-number v-model="profile.deep_fping.interval_ms" :disabled="!profile.deep_collection_master_enabled" :min="10" :max="60000" @change="markDeepPingCustom" /></el-form-item>
              <el-form-item :label="t('ground.v2.settings_ping_timeout', '超时时间（ms）')"><el-input-number v-model="profile.deep_fping.timeout_ms" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="60000" @change="markDeepPingCustom" /></el-form-item>
              <el-form-item :label="t('ground.v2.settings_loss_threshold', '丢包告警阈值（%）')"><el-input-number v-model="profile.deep_fping.loss_warn_percent" :disabled="!profile.deep_collection_master_enabled" :min="0" :max="100" :step="0.1" @change="markDeepPingCustom" /></el-form-item>
              <el-form-item :label="t('ground.v2.settings_latency_threshold', '延迟告警阈值（ms）')"><el-input-number v-model="profile.deep_fping.latency_warn_ms" :disabled="!profile.deep_collection_master_enabled" :min="1" :max="60000" @change="markDeepPingCustom" /></el-form-item>
            </div>
            <div class="form-actions"><el-button :disabled="!pingPresets.length" @click="restoreDeepPingDefault">{{ t('ground.v2.settings_restore_default', '恢复共享默认') }}</el-button></div>
          </section>
          <section><h2>{{ t('ground.ping_and_storage', '心跳检测与存储') }}</h2><div class="form-grid">
            <el-form-item :label="t('ground.ping_interval', 'Ping 间隔（ms）')"><el-input-number v-model="profile.fleet_ping_interval_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item :label="t('ground.ping_timeout', 'Ping 超时（ms）')"><el-input-number v-model="profile.fleet_ping_timeout_ms" :min="100" :max="60000" /></el-form-item>
            <el-form-item :label="t('ground.packet_size', '包大小（字节）')"><el-input-number v-model="profile.fleet_ping_packet_size" :min="1" :max="65507" /></el-form-item>
            <el-form-item :label="t('ground.shard_size', '每个 fping 分片目标数')"><el-input-number v-model="profile.fleet_ping_shard_size" :min="2" :max="32" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_warmup', '启动预热忽略时间（秒）')"><el-input-number v-model="profile.fleet_ping_warmup_seconds" :min="0" :max="300" /></el-form-item>
            <el-form-item :label="t('ground.v2.heartbeat_targets', '心跳检测目标')">
              <span>{{ t('ground.v2.heartbeat_target_scope', '按基础资料中启用的 MR 主备管理 IP 持续采样，不受 AC 位置、正线或车辆段分类影响；深度采集仍独立调度。') }}</span>
            </el-form-item>
            <el-form-item :label="t('ground.detail_retention', '详细数据保留天数')"><el-select v-model="profile.detail_retention_days"><el-option v-for="day in [7,15,30,60,90,180]" :key="day" :label="`${day} ${t('ground.v2.settings_days', '天')}`" :value="day" /></el-select></el-form-item>
            <el-form-item :label="t('ground.summary_retention', '汇总保留天数')"><el-input-number v-model="profile.summary_retention_days" :min="profile.detail_retention_days" :max="3650" /></el-form-item>
            <el-form-item :label="t('ground.warning_space', '空间预警阈值（GB）')"><el-input-number v-model="profile.storage_warning_free_gb" :min="0.1" :max="1024" /></el-form-item>
            <el-form-item :label="t('ground.critical_space', '严重空间阈值（GB）')"><el-input-number v-model="profile.storage_critical_free_gb" :min="0.1" :max="1024" /></el-form-item>
          </div><p class="muted">{{ t('ground.storage_path', '存储路径：当前局点 / files / rail_transit / ground_unattended。深度会话 ZIP 仍保存在既有 Online MR 目录，每日归档只保存引用。') }}</p></section>
          <section><h2>{{ t('ground.v2.settings_udp_boot', 'UDP Syslog 与上电检查') }}</h2>
            <el-alert :title="t('ground.v2.settings_udp_note', '本机监听地址只控制 NetConsole 在哪些网卡接收 UDP；MR 日志回传地址会用于 info-center loghost。监听 0.0.0.0 时仍必须明确选择一个具体回传地址。')" type="info" :closable="false" show-icon />
            <div class="network-actions">
              <el-button :icon="Refresh" :loading="networkLoading" @click="loadLocalAddresses">{{ t('ground.v2.settings_refresh_addresses', '刷新本机地址') }}</el-button>
              <el-button :loading="networkLoading" @click="recommendSourceAddress">{{ t('ground.v2.settings_recommend_address', '检测到 MR 网络的推荐地址') }}</el-button>
              <el-button :loading="networkLoading" @click="checkUdpPort">{{ t('ground.v2.settings_check_udp', '检查 UDP 端口占用') }}</el-button>
              <el-checkbox v-model="showAllAddresses">{{ t('ground.v2.settings_show_virtual', '显示虚拟与其他地址') }}</el-checkbox>
            </div>
            <div class="form-grid">
            <el-form-item :label="t('ground.v2.settings_listen_address', '本机监听地址')">
              <el-select v-model="profile.udp_listen_host" filterable allow-create>
                <el-option :label="t('ground.v2.settings_all_adapters', '0.0.0.0 · 监听全部本机网卡')" value="0.0.0.0" />
                <el-option v-for="row in visibleIpv4Addresses" :key="`listen:${row.adapter_id}:${row.ipv4}`" :value="row.ipv4" :label="`${row.ipv4} · ${row.adapter_name} · /${row.prefix_length}`" />
              </el-select>
              <span :class="listenAddressIsLocal ? 'network-ok' : 'network-error'">{{ listenAddressIsLocal ? t('ground.v2.settings_listen_valid', '监听地址有效') : t('ground.v2.settings_listen_invalid', '监听地址已不属于本机') }}</span>
            </el-form-item>
            <el-form-item :label="t('ground.v2.settings_listen_port', 'UDP 监听端口')"><el-input-number v-model="profile.udp_listen_port" :min="1" :max="65535" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_return_address', 'MR 日志回传地址')">
              <el-select v-model="profile.syslog_server_ip" filterable allow-create clearable :placeholder="t('ground.v2.settings_ipv4_placeholder', '选择或输入具体 IPv4')">
                <el-option v-for="row in visibleIpv4Addresses" :key="`${row.adapter_id}:${row.ipv4}`" :value="row.ipv4" :label="`${row.ipv4} · ${row.adapter_name} · /${row.prefix_length}${row.recommended ? ` · ${t('ground.v2.settings_recommended', '推荐')}` : ''}`" />
              </el-select>
              <span v-if="profile.syslog_server_ip" :class="returnAddressIsLocal ? 'network-ok' : 'network-error'">{{ returnAddressIsLocal ? t('ground.v2.settings_return_local', '当前地址属于本机') : t('ground.v2.settings_return_external', '当前地址不属于本机') }}</span>
            </el-form-item>
            <el-form-item :label="t('ground.v2.settings_server_port', 'Syslog 服务器端口')"><el-input-number v-model="profile.syslog_server_port" :min="1" :max="65535" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_queue_capacity', 'UDP 队列容量')"><el-input-number v-model="profile.udp_queue_capacity" :min="100" :max="500000" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_batch_size', '批量事件数')"><el-input-number v-model="profile.event_batch_size" :min="1" :max="5000" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_check_cooldown', '配置检查冷却（秒）')"><el-input-number v-model="profile.config_check_cooldown_seconds" :min="30" :max="86400" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_boot_tolerance', '上电时间误差（秒）')"><el-input-number v-model="profile.boot_time_tolerance_seconds" :min="10" :max="900" /></el-form-item>
            <el-form-item :label="t('ground.v2.settings_auto_repair', '自动补齐 MR Syslog 临时配置')">
              <el-switch v-model="profile.syslog_auto_repair_enabled" />
              <small>{{ t('ground.v2.settings_repair_note', '无人值守启动或检测到 MR 新上电周期时，自动检查并补齐 Profile v2 临时配置；不会保存设备配置，也不会由 CFGMAN 事件触发。') }}</small>
            </el-form-item>
          </div>
          <div v-if="sourceRecommendation" class="network-status">
            <span>{{ t('ground.v2.settings_route_recommendation', '系统路由推荐：') }}<b>{{ sourceRecommendation.recommended_ip || t('ground.v2.settings_no_recommendation', '无可靠推荐') }}</b></span>
            <span>{{ sourceRecommendation.recommendation_reason }}</span>
            <el-button v-if="sourceRecommendation.recommended_ip" size="small" @click="applyRecommendedAddress">{{ t('ground.v2.settings_apply_recommendation', '采用推荐') }}</el-button>
          </div>
          <div v-if="udpPortCheck" class="network-status"><el-tag :type="udpPortCheck.available ? 'success' : 'danger'">{{ udpPortCheck.message }}</el-tag><span>{{ udpPortCheck.listen_host }}:{{ udpPortCheck.listen_port }}</span></div>
          <el-checkbox v-model="profile.allow_external_syslog_address">{{ t('ground.v2.settings_allow_external', '高级：使用外部 NAT 日志回传地址（保存时需再次确认）') }}</el-checkbox>
          <p class="muted">{{ t('ground.v2.settings_save_note', '保存 Profile 不会在当前请求中直接连接 MR；后台检查只补齐安全缺项。同 IP 端口冲突始终保持只读，必须在单台 MR 详情中再次确认后才允许修改；不会执行 save、undo、reboot、reset 或 delete。') }}</p></section>
          <section><h2>{{ t('ground.priority_trains', '置顶列车') }}</h2><div class="priority-grid"><el-checkbox v-for="row in trains" :key="row.train_id" :model-value="row.priority" @change="togglePriority(row)">{{ row.train_no || row.train_name }}</el-checkbox><span v-if="!trains.length" class="muted">{{ t('ground.no_priority_candidates', '暂无列车基础资料或 AC 在线状态') }}</span></div></section>
          <div class="form-actions"><el-button type="primary" :loading="saving" @click="saveProfile()">{{ t('common.save', '保存设置') }}</el-button><span class="muted">{{ t('ground.profile_effective', '运行中修改默认从下一次调度周期生效') }}</span></div>
        </el-form>

</section>
</template>

<style scoped src="./groundUnattended.css"></style>
