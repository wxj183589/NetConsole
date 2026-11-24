const zh = {
  refreshAll: '全部刷新', connect: '连接 SFTP', disconnect: '断开', winscp: 'WinSCP', back: '返回', root: '根目录',
  refresh: '刷新', newDirectory: '新建目录', openCurrent: '打开当前目录', up: '上级', selectAll: '全选文件',
  clearSelection: '清除选择', meshLogs: 'MESH 日志', downloadSelected: '下载选中', queue: '下载队列',
  clearCompleted: '清理完成', clearFailed: '清理失败', cancel: '取消', retry: '重试', save: '保存', open: '打开',
  containingFolder: '所在目录',
} as const

type FileTextKey = keyof typeof zh

const en: Record<FileTextKey, string> = {
  refreshAll: 'Refresh all', connect: 'Connect SFTP', disconnect: 'Disconnect', winscp: 'WinSCP', back: 'Back', root: 'Root',
  refresh: 'Refresh', newDirectory: 'New folder', openCurrent: 'Open current folder', up: 'Up', selectAll: 'Select files',
  clearSelection: 'Clear selection', meshLogs: 'MESH logs', downloadSelected: 'Download selected', queue: 'Download queue',
  clearCompleted: 'Clear completed', clearFailed: 'Clear failed', cancel: 'Cancel', retry: 'Retry', save: 'Save', open: 'Open',
  containingFolder: 'Show in folder',
}

export function createFileManagementTranslator(language = typeof navigator === 'undefined' ? 'zh-CN' : navigator.language) {
  const messages = language.toLocaleLowerCase().startsWith('zh') ? zh : en
  return (key: FileTextKey): string => messages[key]
}

const managerZh = {
  selectDevice: '选择设备',
  managedDownloads: '设备文件下载',
  localFiles: '本地受管目录',
  remoteFiles: '远程文件',
  up: '上级目录',
  refresh: '刷新',
  newDirectory: '新建目录',
  folderName: '目录名称',
  filter: '筛选名称',
  name: '名称',
  size: '大小（字节）',
  modified: '修改时间',
  conflict: '同名文件处理',
  error: '停止',
  skip: '跳过',
  rename: '保留副本',
  overwrite: '覆盖',
  overwriteConfirm: '上传将覆盖目标目录下的同名文件，是否继续？',
  loadDevicesFailed: '设备列表读取失败',
  loadLocalFailed: '本地目录读取失败',
  folderFailed: '目录创建失败',
  uploadSelectedLocal: '上传本地选中',
  uploadFailed: '上传提交失败',
  downloadToLocal: '下载到左侧目录',
  downloadFailed: '下载提交失败',
} as const

const managerEn: Record<keyof typeof managerZh, string> = {
  selectDevice: 'Select device',
  managedDownloads: 'Device downloads',
  localFiles: 'Managed local folder',
  remoteFiles: 'Remote files',
  up: 'Parent directory',
  refresh: 'Refresh',
  newDirectory: 'New directory',
  folderName: 'Directory name',
  filter: 'Filter by name',
  name: 'Name',
  size: 'Size (bytes)',
  modified: 'Modified',
  conflict: 'File conflict policy',
  error: 'Stop',
  skip: 'Skip',
  rename: 'Keep both',
  overwrite: 'Overwrite',
  overwriteConfirm: 'Overwrite matching files in the remote directory?',
  loadDevicesFailed: 'Could not load devices',
  loadLocalFailed: 'Could not open the local directory',
  folderFailed: 'Could not create the directory',
  uploadSelectedLocal: 'Upload selected files',
  uploadFailed: 'Could not queue the upload',
  downloadToLocal: 'Download to left folder',
  downloadFailed: 'Could not queue the download',
}

export function createFileManagerTranslator(language = typeof navigator === 'undefined' ? 'zh-CN' : navigator.language) {
  const messages = language.toLocaleLowerCase().startsWith('zh') ? managerZh : managerEn
  return (key: keyof typeof managerZh): string => messages[key]
}
