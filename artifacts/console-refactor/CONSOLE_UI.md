# Console UI

## 模块

- `ConsoleWorkspaceView.vue`：页面结构与 SmartHub 风格布局。
- `useConsoleWorkspace.ts`：设备、会话、标签、分屏、历史和导出状态。
- `TerminalPane.vue`：每会话独立 xterm、WebSocket、fit/resize 与重连。
- `TerminalQuickConnectDialog.vue`：快速连接、保存会话和凭据记忆选择。
- `TerminalSftpPanel.vue`：独立 SFTP 浏览、批量选择和传输队列。
- `TerminalSettingsDialog.vue`：字体、编码、双日志、关键词高亮和高危提示规则。
- `api/terminal.ts`：终端 REST/WS 契约。

## 完成状态

| 能力 | 状态 |
| --- | --- |
| 设备/会话视图、搜索、设备分组、活动与最近/断开会话 | IMPLEMENTED / BUILD_VERIFIED |
| 双击与右键打开、批量打开 | IMPLEMENTED / BUILD_VERIFIED |
| 多标签、关闭当前/其他/全部 | IMPLEMENTED / BUILD_VERIFIED |
| 标签关闭与后端终止分离；活动会话重新附着并恢复有界显示缓冲 | IMPLEMENTED / MOCK_VERIFIED |
| 左右/上下分屏、拖动比例 | IMPLEMENTED / BUILD_VERIFIED |
| xterm 输入、复制、粘贴、滚动、清屏、resize | IMPLEMENTED / BUILD_VERIFIED |
| Backspace、左右光标、上下历史、Tab 补全 | IMPLEMENTED / MOCK_VERIFIED |
| 会话历史、查看、TXT/JSONL 导出 | IMPLEMENTED / BUILD_VERIFIED |
| 设备详情跳转、会话右键结束/重连/查看记录 | IMPLEMENTED / BUILD_VERIFIED |
| 快速连接、保存会话、文件夹、收藏 | IMPLEMENTED / TESTED |
| 字体、编码、关键词高亮、高危命令提醒 | IMPLEMENTED / TESTED |
| 独立 SFTP 浏览、上传、下载、目录、删除、重命名、复制、移动、进度、取消和重试 | IMPLEMENTED / TESTED |
| 自动操作日志与手动会话日志独立启停/导出 | IMPLEMENTED / TESTED |
| 批量命令 | 由 Netmiko 自动化任务负责，不接管控制台 Shell |

页面和 REST/WS 使用独立 `module.console` 门禁；设备树继续复用 Device Service，没有建立重复设备数据源。
设备管理的单设备操作可直接进入内置控制台；控制台消费一次性 `device_uuid` 路由参数并自动建立会话，随后清除参数以避免恢复页面时重复连接。
