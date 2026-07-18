# Renderer 事件循环与响应性规范

本文是 Electron + Vue Renderer 的响应性规范。Qt UI 线程、QThread 和 QWidget 规则已经归档，不适用于活动代码。

## 允许在 Renderer 同步执行

- 布局、状态绑定、轻量格式化与输入校验；
- 小型集合的筛选、排序和展示映射；
- 发起受控 API/Bridge 请求；
- 更新 loading、progress、success、error、cancelled 等可见状态。

## 必须移出 Renderer

- SSH/Telnet/SNMP/SFTP、设备命令和外部工具；
- SQLite、批量 Repository、大查询和 schema 操作；
- 大日志解析、压缩/解压、报告、Excel/PDF/图片导出；
- 文件扫描、网络等待、CPU 密集计算和可能阻塞超过 300 ms 的操作。

这些任务必须进入 Application Service、Job Center 或 Export Process。Electron Main/Preload 只承载窗口、生命周期和白名单本机能力，不承担业务计算。

## 生命周期

- 组件卸载时清理 timer、事件监听、WebSocket 和 AbortController。
- 页面切换或关闭子窗口不得停止后台任务；重新打开后从服务器事实源恢复。
- Electron 退出通过统一 shutdown barrier 清理下载、任务窗口和受管 Backend。
- 禁止用 `setTimeout`、吞异常或重复轮询掩盖递归、竞态和状态错乱。

后台任务、取消、恢复和 Artifact 规则见[后台任务规范](background_task_policy.md)与 [Job Center](JOB_CENTER.md)。
