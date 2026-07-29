export interface UserSelectedExportDefinition {
  module: 'devices' | 'ac' | 'rail' | 'config' | 'command-reference' | 'logs' | 'network'
  label: string
  filters: Array<{ name: string; extensions: string[] }>
  artifactExtensions: string[]
  artifactMediaTypes: string[]
}

const CSV_MEDIA_TYPES = ['text/csv', 'application/csv']
const XLSX_MEDIA_TYPES = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
const ZIP_MEDIA_TYPES = ['application/zip', 'application/x-zip-compressed']
const TEXT_MEDIA_TYPES = ['text/plain', 'text/markdown']

export const userSelectedExportDefinitions = {
  'devices.csv': csvDefinition('devices', '设备清单'),
  'devices.template': csvDefinition('devices', '设备导入模板'),
  'devices.securecrt': zipDefinition('devices', 'SecureCRT 会话'),
  'devices.diagnostics': zipDefinition('devices', '设备诊断信息'),
  'ac.fit_ap_resources': xlsxDefinition('ac', 'FIT-AP 资源'),
  'ac.extensions': xlsxDefinition('ac', 'AP 扩展信息'),
  'rail.mesh_report': xlsxDefinition('rail', 'MESH 分析报告'),
  'rail.mesh_link_details': xlsxDefinition('rail', 'MESH 链路明细'),
  'rail.trackside_business': xlsxDefinition('rail', '轨旁 AP 业务表'),
  'rail.trackside_plan_template': xlsxDefinition('rail', '轨旁 AP 规划模板'),
  'rail.trackside_plan_current': xlsxDefinition('rail', '轨旁 AP 规划资料'),
  'rail.trackside_base_template': xlsxDefinition('rail', '轨旁 AP 基础资料模板'),
  'rail.trackside_base_current': xlsxDefinition('rail', '轨旁 AP 基础资料'),
  'rail.trackside_rename_commands': textDefinition('rail', '轨旁 AP 重命名命令', 'txt'),
  'rail.online_mr_report': xlsxDefinition('rail', 'Online MR 分析报告'),
  'rail.vehicle_history': xlsxDefinition('rail', '列车经过历史'),
  'rail.vehicle_mapping_template': xlsxDefinition('rail', '列车 MR 映射模板'),
  'rail.car_network_points_csv': csvDefinition('rail', '车内通信点表'),
  'rail.car_network_points_xlsx': xlsxDefinition('rail', '车内通信点表'),
  'config.diff': textDefinition('config', '配置差异', 'diff'),
  'config.snapshots': zipDefinition('config', '配置快照'),
  'command-reference.markdown': textDefinition('command-reference', '命令说明', 'md'),
  'system.logs': csvDefinition('logs', '应用日志'),
  'system.open_source_txt': textDefinition('logs', '开源清单', 'txt'),
  'system.open_source_xlsx': xlsxDefinition('logs', '开源清单'),
  'network.toolbox_csv': csvDefinition('network', '网络工具结果'),
  'network.toolbox_xlsx': xlsxDefinition('network', '网络工具结果'),
  'network.wireless_scan_csv': csvDefinition('network', '无线扫描结果'),
  'network.wireless_scan_xlsx': xlsxDefinition('network', '无线扫描结果'),
} as const satisfies Record<string, UserSelectedExportDefinition>

export type UserSelectedExportAction = keyof typeof userSelectedExportDefinitions

export function exportDefinition(action: UserSelectedExportAction): UserSelectedExportDefinition {
  return userSelectedExportDefinitions[action]
}

export function isUserSelectedExportAction(value: unknown): value is UserSelectedExportAction {
  return typeof value === 'string' && value in userSelectedExportDefinitions
}

function csvDefinition(
  module: UserSelectedExportDefinition['module'],
  label: string,
): UserSelectedExportDefinition {
  return {
    module,
    label,
    filters: [{ name: 'CSV 文件', extensions: ['csv'] }],
    artifactExtensions: ['csv'],
    artifactMediaTypes: CSV_MEDIA_TYPES,
  }
}

function xlsxDefinition(
  module: UserSelectedExportDefinition['module'],
  label: string,
): UserSelectedExportDefinition {
  return {
    module,
    label,
    filters: [{ name: 'Excel 工作簿', extensions: ['xlsx'] }],
    artifactExtensions: ['xlsx'],
    artifactMediaTypes: XLSX_MEDIA_TYPES,
  }
}

function zipDefinition(
  module: UserSelectedExportDefinition['module'],
  label: string,
): UserSelectedExportDefinition {
  return {
    module,
    label,
    filters: [{ name: 'ZIP 压缩包', extensions: ['zip'] }],
    artifactExtensions: ['zip'],
    artifactMediaTypes: ZIP_MEDIA_TYPES,
  }
}

function textDefinition(
  module: UserSelectedExportDefinition['module'],
  label: string,
  extension: 'diff' | 'md' | 'txt',
): UserSelectedExportDefinition {
  return {
    module,
    label,
    filters: [{
      name: extension === 'md' ? 'Markdown 文件' : extension === 'diff' ? 'Diff 文件' : '文本文件',
      extensions: [extension],
    }],
    artifactExtensions: [extension],
    artifactMediaTypes: TEXT_MEDIA_TYPES,
  }
}
