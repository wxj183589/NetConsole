# R2.3.2 Electron GUI 实际验收

## 实际窗口与切换证据

运行根：`D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_2-electron-gui-switch-023-20261110`

该运行启动真实可见 Windows Electron、候选 Vite Renderer、隔离 Backend/DataRoot 和合成 inventory（50 trains / 100 MR / 200 Heartbeat targets）。`evidence.json` 记录了运行概览、Heartbeat、Syslog、AC-Mesh-Link、筛选目标 MR、正常停止和 Renderer reload 的成功交互。

同一次 GUI 运行中的 AP 切换截图（证据文件保留在 Workspace `test-data`，不随源码提交）：

- `test-data/NetConsole/r2_3_2-electron-gui-switch-023-20261110/gui/03-syslog-mr001-before.png`：筛选 `列车001-MR-CT`，当前 AP 为 `R232-AP-A-001`。
- `test-data/NetConsole/r2_3_2-electron-gui-switch-023-20261110/gui/05-syslog-mr001-after.png`：同一筛选，当前 AP 为 `R232-AP-B-001`。
- `test-data/NetConsole/r2_3_2-electron-gui-switch-023-20261110/gui/06-ground-stopped-heartbeat-resident.png`。
- `test-data/NetConsole/r2_3_2-electron-gui-switch-023-20261110/gui/evidence.json`。

## API / SQLite 交叉核验

`ground_unattended_syslog_position_states` 对 `test-mr-001/CT` 的最终值为：

- `current_ap_name=R232-AP-B-001`，`current_ap_mac=02:00:00:00:00:02`。
- `previous_ap_name=R232-AP-A-001`，`previous_ap_mac=02:00:00:00:00:01`。
- `position_status=VALID`，`position_source=SYSLOG`，`position_event_count=40`，`duplicate_event_count=147`，`out_of_order_event_count=0`。
- 最后事件 `16:15:22.000+08:00`，接收 `16:15:22.120+08:00`，位置提交 `16:15:22.499+08:00`，该样本位置延迟 499 ms。

Ground 正常停止后 Syslog pipeline、Receiver、Writer、Parser 均停止；Heartbeat 保留 200 targets/17 processes。Renderer reload 成功。SQLite `integrity_check=ok`。

## AC 与限制

本次 GUI 隔离运行没有配置真实 AC/SSH，因此 AC-Mesh-Link 页面显示未配置/无数据。旧 AC 快照不得覆盖 Syslog 新位置的断言由 AC/Heartbeat/recovery 专项 `119 passed` 和 AC reconciliation 证据覆盖：本地测试中保留 Syslog 新位置并记录 `SYSLOG_NEWER`/`STALE`，不把 GUI no-data 页面写成现场 AC 成功。

结论：`ELECTRON_GUI=PASS_WITH_EVIDENCE_CAVEATS`。这是实际 Electron + 隔离合成数据证据，不是现场设备验收。
