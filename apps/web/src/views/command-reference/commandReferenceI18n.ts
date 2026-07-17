import { currentAppLocale } from '../../i18n/runtime'

const zh = {
  referenceOnly: '仅供参考 · 不执行设备命令', title: '命令说明', subtitle: '查询版本化命令资源，复制模板或导出当前筛选结果。',
  refresh: '刷新', copy: '复制命令模板', exportMarkdown: '导出 Markdown', searchPlaceholder: '搜索命令、用途、模块、源码位置',
  search: '搜索', module: '模块', deviceScope: '设备类型', vendor: '厂商', protocol: '协议', category: '类别', riskLevel: '风险级别',
  archived: '已归档', shown: '当前显示', switch: '交换机', nonCli: '非 CLI / 本地工具', itemUnit: '条', retry: '重试',
  empty: '当前筛选没有命令说明', command: '命令', purpose: '当前用途', prerequisites: '前置条件', notes: '备注',
  details: '命令详情', commandTemplate: '命令模板', moduleCategory: '模块 / 类别', deviceVendorProtocol: '设备 / 厂商 / 协议',
  readOnly: '是否只读', modifiesConfig: '是否修改设备配置', interactive: '是否存在交互确认', riskCli: '风险 / CLI',
  parameters: '参数', preCommands: '前置命令', outputLog: '输出 / 日志', parserConsumer: '解析器 / 消费模块', sourceLocations: '源码位置',
  comwareZte: 'Comware / ZTE', adaptationStatus: '适配状态', parser: '解析器', cautions: '注意事项', selectDetails: '选择左侧命令后查看详情',
  yes: '是', no: '否', conditional: '需按风险级别判断', none: '—',
  selectFirst: '请先选择一条命令说明', copied: '命令模板已复制', copyFailed: '复制失败，请检查剪贴板权限',
  loadFailed: '命令说明加载失败', exportFailed: '导出启动失败', restoreFailed: '导出状态恢复失败', cancelFailed: '取消导出失败',
  taskRefreshFailed: '任务状态刷新暂时失败，正在重试',
  downloadSaved: 'Markdown 已保存', downloadFailed: 'Artifact 下载失败', taskSubmitted: 'Markdown 导出任务已提交',
  task: '任务', status: '状态', artifact: 'Artifact', openTaskWindow: '打开统一任务窗口', cancel: '取消', download: '下载 Artifact',
  taskWindowFailed: '统一任务窗口打开失败', zte: 'ZTE',
  riskReadOnly: '只读', riskConfigWrite: '修改配置', riskInteractive: '交互操作', riskExternalTool: '外部工具', riskUnknown: '未知',
  zteNotApplicable: '不适用', ztePhase1: '第一阶段参考', ztePhase2: '第二阶段参考',
} as const

type CommandReferenceTextKey = keyof typeof zh

const en: Record<CommandReferenceTextKey, string> = {
  referenceOnly: 'REFERENCE ONLY · Does not execute device commands', title: 'Command Reference', subtitle: 'Search versioned command resources, copy templates, or export the filtered results.',
  refresh: 'Refresh', copy: 'Copy command', exportMarkdown: 'Export Markdown', searchPlaceholder: 'Search command, purpose, module, or source location',
  search: 'Search', module: 'Module', deviceScope: 'Device type', vendor: 'Vendor', protocol: 'Protocol', category: 'Category', riskLevel: 'Risk',
  archived: 'Archived', shown: 'Shown', switch: 'Switch', nonCli: 'Non-CLI / local tool', itemUnit: '', retry: 'Retry',
  empty: 'No command references match the current filters', command: 'Command', purpose: 'Purpose', prerequisites: 'Prerequisites', notes: 'Notes',
  details: 'Command details', commandTemplate: 'Command template', moduleCategory: 'Module / category', deviceVendorProtocol: 'Device / vendor / protocol',
  readOnly: 'Read only', modifiesConfig: 'Modifies device configuration', interactive: 'Interactive confirmation', riskCli: 'Risk / CLI',
  parameters: 'Parameters', preCommands: 'Prerequisite commands', outputLog: 'Output / log', parserConsumer: 'Parser / consumer', sourceLocations: 'Source locations',
  comwareZte: 'Comware / ZTE', adaptationStatus: 'Adaptation status', parser: 'Parser', cautions: 'Cautions', selectDetails: 'Select a command to view details',
  yes: 'Yes', no: 'No', conditional: 'Depends on risk level', none: '—',
  selectFirst: 'Select a command reference first', copied: 'Command template copied', copyFailed: 'Copy failed; check clipboard permission',
  loadFailed: 'Failed to load command references', exportFailed: 'Failed to start export', restoreFailed: 'Failed to restore export status', cancelFailed: 'Failed to cancel export',
  taskRefreshFailed: 'Task status refresh failed temporarily; retrying',
  downloadSaved: 'Markdown saved', downloadFailed: 'Artifact download failed', taskSubmitted: 'Markdown export task submitted',
  task: 'Task', status: 'Status', artifact: 'Artifact', openTaskWindow: 'Open task window', cancel: 'Cancel', download: 'Download Artifact',
  taskWindowFailed: 'Failed to open task window', zte: 'ZTE',
  riskReadOnly: 'Read only', riskConfigWrite: 'Configuration write', riskInteractive: 'Interactive', riskExternalTool: 'External tool', riskUnknown: 'Unknown',
  zteNotApplicable: 'Not applicable', ztePhase1: 'Phase 1 reference', ztePhase2: 'Phase 2 reference',
}

export function createCommandReferenceTranslator(language?: string) {
  return (key: CommandReferenceTextKey): string => {
    const selected = language ?? currentAppLocale()
    return selected.toLocaleLowerCase().startsWith('zh') ? zh[key] : en[key]
  }
}
