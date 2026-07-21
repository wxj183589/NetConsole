const zh = {
  refreshAll: '全部刷新', connect: '连接 SFTP', disconnect: '断开', winscp: 'WinSCP', back: '返回', root: '根目录',
  refresh: '刷新', newDirectory: '新建目录', openCurrent: '打开当前目录', up: '上级', selectAll: '全选文件',
  clearSelection: '清除选择', meshLogs: 'Mesh 日志', downloadAndImportMesh: '下载并传入 MESH 分析', downloadSelected: '下载选中', queue: '下载队列',
  clearCompleted: '清理完成', clearFailed: '清理失败', cancel: '取消', retry: '重试', save: '保存', open: '打开',
  containingFolder: '所在目录',
} as const

type FileTextKey = keyof typeof zh

const en: Record<FileTextKey, string> = {
  refreshAll: 'Refresh all', connect: 'Connect SFTP', disconnect: 'Disconnect', winscp: 'WinSCP', back: 'Back', root: 'Root',
  refresh: 'Refresh', newDirectory: 'New folder', openCurrent: 'Open current folder', up: 'Up', selectAll: 'Select files',
  clearSelection: 'Clear selection', meshLogs: 'Mesh logs', downloadAndImportMesh: 'Download and import MESH', downloadSelected: 'Download selected', queue: 'Download queue',
  clearCompleted: 'Clear completed', clearFailed: 'Clear failed', cancel: 'Cancel', retry: 'Retry', save: 'Save', open: 'Open',
  containingFolder: 'Show in folder',
}

export function createFileManagementTranslator(language = typeof navigator === 'undefined' ? 'zh-CN' : navigator.language) {
  const messages = language.toLocaleLowerCase().startsWith('zh') ? zh : en
  return (key: FileTextKey): string => messages[key]
}
