const statusLabels: Record<string, string> = {
  DISABLED: '未启用',
  WAITING_WINDOW: '等待运行时段',
  STARTING: '启动中',
  RUNNING: '运行中',
  PAUSED: '已暂停',
  STOPPING: '正在停止',
  FINALIZING: '正在收尾',
  ARCHIVING: '正在归档',
  COMPLETED: '已完成',
  ERROR: '运行异常',
  MAINLINE: '正线在线',
  MAINLINE_STATIONARY: '正线长时间停留',
  DEPOT: '车辆段',
  PARKING_LOT: '停车场',
  STORAGE_TRACK: '存车线',
  NON_MAIN_PATH: '非正线路径',
  DEPOT_CONNECTION: '出入段线',
  AC_STALE: 'AC 数据过期',
  AC_UNKNOWN: '暂无 AC 数据',
  AP_UNMATCHED: '位置未匹配',
  OFFLINE: '离线',
  AP_EXACT: 'AP 精确匹配',
  AP_REGISTRY: 'AP 资源匹配',
  AP_ALIAS: 'AP 别名匹配',
  STATION_EXACT: '站点精确匹配',
  STATION_ALIAS: '站点别名匹配',
  UNMATCHED: '未匹配',
  PINGING: '长 Ping 运行中',
  STOPPED: '未启动',
  ONLINE: '在线',
  WAITING: '等待数据',
  ACTIVE: '日志活跃',
  NOT_SEEN: '今日未采集',
  COLLECTING: '采集中',
  PARTIAL: '部分完成',
  COVERED: '已完成',
  EXCLUDED: '已排除',
  FAILED: '失败',
  PENDING: '待处理',
  BUILDING: '正在生成',
  VERIFYING: '正在校验',
  READY: '归档完成',
  FRESH: '数据新鲜',
  STALE: '数据过期',
  NO_DATA: '暂无数据',
  OK: '正常',
  WARNING: '警告',
  CRITICAL: '严重',
  ENABLED: '已启用',
  TARGET_PRESENT: '管理目标已存在',
  TARGET_MISSING: '管理目标缺失',
  TARGET_PORT_CONFLICT: '同 IP 端口冲突',
  OTHER_TARGETS_PRESENT: '存在其他日志目标',
  CONFIG_PRESENT: '配置完整',
  CONFIG_REPAIRED: '配置已修复',
  CONFIG_SENT: '配置已下发',
  CONFIG_VERIFY_FAILED: '配置复核失败',
  CONFIG_FAILED: '配置处理失败',
  NOT_CHECKED: '尚未检查',
  WAITING_FIRST_LOG: '等待首条日志',
  LOG_ACTIVE: '日志接收活跃',
  VERIFIED: '身份已确认',
  UNIDENTIFIED: '来源未识别',
  IDENTITY_CONFLICT: '身份冲突',
  UNCONFIRMED_SOURCE_IP: '来源 IP 待确认',
  UNCONFIRMED_HOSTNAME: '设备名称待确认',
  COMPLETE: '完整',
  PARSED: '已解析',
  IGNORED: '已忽略',
  DUPLICATE: '重复记录',
  OPEN: '正在写入',
  CLOSED: '已关闭',
  RECOVERED: '已恢复关闭',
  ACTIVE_RAW: '活动原始数据',
  ARCHIVED_RAW: '归档原始数据',
  MIXED: '活动与归档混合',
  SUMMARY_ONLY: '仅有汇总',
  MISSING: '原始数据缺失',
  CORRUPT: '原始数据损坏',
  PENDING_RECOVERY: '等待恢复处理',
  MATCHED: '位置已匹配',
  AMBIGUOUS: '存在多个候选',
  UNRESOLVED: '未解析',
  PEER_MAC_EXACT: 'Peer MAC 精确匹配',
  RADIO_BSSID: 'Radio/BSSID 映射',
  H3C_RADIO_DERIVED: 'H3C Radio 规则映射',
  AP_MAC_FALLBACK: 'AP MAC 降级匹配',
  AC_AP_NAME_EXACT: 'AC AP 名称精确匹配',
  NO_ACTIVE_LINK: '无主链路',
  BEFORE_AP_TRANSITION: 'AP 切换前',
  AFTER_AP_TRANSITION: 'AP 切换后',
  CLOCK_OFFSET: '设备时间有偏差',
  CLOCK_JUMP: '设备时钟跳变',
  DEVICE_CLOCK: '设备时钟',
  LOCAL_FALLBACK: '本机时间降级',
  TIME_RANGE_EMPTY: '查询时间范围为空',
  RAW_FILE_MISSING: '原始文件缺失',
  ARCHIVE_NOT_READY: '归档尚未就绪',
  ARCHIVE_ENTRY_MISSING: '归档条目缺失',
  ARCHIVE_MEMBER_MISSING: '归档条目缺失',
  ARCHIVE_INTEGRITY_FAILED: '归档完整性校验失败',
  ARCHIVE_READ_FAILED: '归档读取失败',
  TARGET_NOT_FOUND: '未找到目标',
  FILE_CORRUPT: '原始数据损坏',
  NO_SAMPLES: '本范围没有样本',
  NO_REGISTERED_FILES: '本运行没有登记原始文件',
  FILTER_NO_MATCH: '查询范围内没有匹配记录',
  QUERY_BUDGET_REACHED: '数据量较大，查询已截断',
  SOME_RAW_FILES_MISSING: '部分原始文件缺失',
  MALFORMED_RECORDS_SKIPPED: '已跳过格式异常记录',
  UNKNOWN: '未知',
}

const eventLabels: Record<string, string> = {
  ap_transition: '当前 AP 变化',
  mesh_linkup: 'WMESH 链路建立',
  mesh_linkdown: 'WMESH 链路断开',
  mesh_activelink_switch: 'WMESH 主链路切换',
  ifnet_phy_updown: '接口物理状态变化',
  ping_loss_pattern: 'Ping 丢包模式',
  run_recovered: '运行恢复',
  operation_recovered: '操作恢复',
  profile_updated: '配置已更新',
  run_started: '运行开始',
  run_completed: '运行结束',
  start_rejected: '启动被拒绝',
  scheduling_paused: '调度已暂停',
  scheduling_resumed: '调度已继续',
  supervisor_error: '调度周期异常',
  stop_failed: '停止失败',
  ping_shard_restarted: 'Ping 分片重建',
  ping_shard_failed: 'Ping 分片失败',
  ping_fallback_enabled: 'Ping 兼容模式启用',
  ac_poll_started: 'AC 轮询已启动',
  ac_poll_failed: 'AC 轮询启动失败',
  mr_loghost_port_change_authorized: 'MR 日志端口修改已授权',
  archive_failed: '归档失败',
}

const severityLabels: Record<string, string> = {
  info: '提示',
  warning: '警告',
  error: '错误',
  critical: '严重',
}

const operationStageLabels: Record<string, string> = {
  STOP_REQUESTED: '已提交停止请求',
  STOPPING_PING: '正在停止长 Ping',
  STOPPING_SYSLOG: '正在停止 Syslog 接收',
  FLUSHING_QUEUE: '正在清空接收队列',
  CLOSING_FILES: '正在关闭原始文件',
  FINALIZING: '正在生成汇总',
  ARCHIVE_PREPARING: '正在准备归档',
  ARCHIVE_WRITING: '正在写入归档',
  ARCHIVE_VERIFYING: '正在校验归档',
  ARCHIVE_REGISTERING: '正在登记归档',
  ARCHIVE_READY: '归档校验完成',
  CLEANING_ARCHIVED_ACTIVE: '正在清理已归档数据',
  COMPLETED: '操作完成',
  FAILED: '操作失败',
}

export function groundStatusLabel(value: unknown): string {
  const key = String(value || '').trim()
  return key ? statusLabels[key] || '未知状态' : '暂无状态'
}

export function groundEventLabel(value: unknown): string {
  const key = String(value || '').trim().toLocaleLowerCase()
  return key ? eventLabels[key] || '其他事件' : '其他事件'
}

export function groundSeverityLabel(value: unknown): string {
  const key = String(value || '').trim().toLocaleLowerCase()
  return key ? severityLabels[key] || '提示' : '提示'
}

export function groundOperationStageLabel(value: unknown): string {
  const key = String(value || '').trim()
  return key ? operationStageLabels[key] || '正在处理' : '等待处理'
}

export function groundRunModeLabel(value: unknown): string {
  return value === 'LIGHTWEIGHT' ? '轻量监测' : '标准采集'
}

export function groundSourceLabel(value: unknown): string {
  const key = String(value || '').trim()
  const labels: Record<string, string> = {
    ACTIVE: '活动原始文件',
    ARCHIVE: 'READY 归档',
    MIXED: '活动与归档混合',
    NONE: '无原始数据',
    NETCONSOLE_MANAGED: 'NetConsole 管理目标',
    DEVICE_EXISTING: '设备已有配置',
  }
  return key ? labels[key] || '其他来源' : '无来源'
}

export function groundTransitionContextLabel(value: unknown): string {
  const key = String(value || '').trim()
  return key ? groundStatusLabel(key) : '否'
}

export function groundDisplayNameSourceLabel(value: unknown): string {
  const key = String(value || '').trim()
  const labels: Record<string, string> = {
    BASE_NAME: '轨旁基础资料名称',
    TRACKSIDE_AP_NAME: '轨旁 AP 工程名称',
    POINT_CODE: '轨旁 AP 点位编号',
    AC_AP_NAME: 'AC 配置名称',
    MAC_FALLBACK: 'MAC 降级显示',
    EVENT_STATE: '事件状态',
    RAW_OBSERVATION: '原始观测',
  }
  return key ? labels[key] || '其他来源' : '暂无来源'
}
