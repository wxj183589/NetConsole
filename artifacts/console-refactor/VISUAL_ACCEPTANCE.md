# Console R2 Visual Acceptance

## 当前状态

- 真实 Electron 外壳：VISUALLY_VERIFIED（隔离 fixture）。
- 1920×1080、2560×1440、1024×680：PASS。
- SmartHub 原版同状态逐像素对比：EVIDENCE_GAP。
- 真实设备终端内容：NOT_VERIFIED。

## 本轮证据

目录：`D:\study\NetConsole-Workspace\reports\tests\console-r2`

- `console-electron-1920x1080.png`：设备树、两个标签、左右分屏、独立 xterm、自动化写任务提示。
- `console-electron-2560x1440-history.png`：会话历史 Drawer、搜索和状态表格。
- `console-electron-1024x680.png`：小窗口双终端布局。
- `console-electron-1024x680-toolbar-end.png`：横向滚动后的日志、SFTP、会话记录和设置入口。
- `console-electron-1920x1080-sftp.png`：独立 SFTP 文件列表、操作工具栏和传输队列。
- `console-electron-1920x1080-settings.png`：样式/编码、附件规则计数 22/226、日志设置入口。

捕获入口为 `apps/desktop_renderer/tests/visual/capture-console-electron.mjs`。它通过 CDP 连接本轮真实 `pnpm dev:codex` Electron 窗口；REST/WS/SFTP 数据由隔离 fixture 截获，没有连接设备。截图均通过尺寸和非空像素检查，并经人工复核，无明显重叠、裁切或不可达工具。

运行结束后 5179、18019、9333 均无监听，隔离根 `electron-VWW0FQ` 已自动删除。
