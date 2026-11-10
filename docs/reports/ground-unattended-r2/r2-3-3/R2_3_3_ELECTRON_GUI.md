# R2.3.3 Electron GUI 回归

## 运行

使用真实可见 Windows Electron、候选 Vite Renderer、隔离 Backend/DataRoot 和 loopback UDP。`r2_3_3-electron-gui-20261110-1825` 运行持续 150 秒，50 列车、100 MR、200 Heartbeat targets，Harness 正常完成。

GUI capture 证据：

```text
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825\gui-latency\evidence.json
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825\gui-latency\syslog-mr001-ap-a-before.png
D:\study\NetConsole-Workspace\test-data\NetConsole\r2_3_3-electron-gui-20261110-1825\gui-latency\syslog-mr001-ap-b-after.png
```

筛选 `列车001-MR-CT` 的交互成功，前后截图中的 Syslog/WMESH 计数发生变化，Electron 和 Renderer 实际运行。截图没有把当前 AP 详情行纳入视口，因此 AP-A→AP-B 的“可见值”未被截图直接证明；不得将其升级为 UI Visible PASS。真实 AC/SSH 未配置，AC 页面无数据不作现场 AC 成功证据。

结论：`ELECTRON_GUI=PASS_WITH_EVIDENCE_CAVEATS`，`UI_VISIBLE_LATENCY=PARTIAL`。截图和证据保留在 Workspace test-data，不进入 Git。
