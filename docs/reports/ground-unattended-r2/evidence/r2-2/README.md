# R2.2 验证证据

- `gui-summary.json`：隔离 Electron 的无 Run、离页、刷新、Ground stop、Backend 正常重启观测；合成 60 车辆/120 MR/200 loopback IP。
- `load-summary.json`：实际 fping 的 400 MR/800 loopback IP 短时测量，含采样时点、进程资源、SQLite/gzip 完整性与退出结果。
- 四张 PNG：实际 Electron 页面截图，解读及限制见 [GUI 验收](../../R2_2_GUI_ACCEPTANCE.md)。

隔离根绝对路径已在 JSON 中脱敏；原始证据保留在 Workspace task-owned 测试根。短测不能替代 8 小时长稳，合成库存不能替代真实设备验收。
