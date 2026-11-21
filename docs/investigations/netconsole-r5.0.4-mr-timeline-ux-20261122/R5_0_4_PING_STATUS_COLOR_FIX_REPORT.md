# R5.0.4 Ping 状态颜色修复报告

## 修复内容

Heartbeat 和 Quick Ping 不再把成功的 `0%` 与失败的 `100%` 绘制到同一条阶梯线。每个目标现在分为 RTT、连通、丢包/超时和未知状态系列：

- RTT：`#3B82F6`，只保留有效 RTT；超时不生成 `RTT=0`。
- 正常连通：`#22C55E`，状态值为 `0%`。
- 丢包/超时：`#EF4444`，状态值为实际丢包率，缺少比例时失败采样为 `100%`。
- UNKNOWN：`#909399`，使用隐藏状态轴的灰色标记，不伪装成成功或丢包率。

Tooltip 由同一份状态映射生成，统一显示时间、RTT、状态和丢包率。主用/备用目标分别建系列，不串扰。Peer AP 的红橙黄绿青蓝紫时序颜色未修改。

## DEV Electron 证据

本次 GUI 使用既有独立 DEV Electron：

```text
DATA_ROOT=D:\NetConsoleData-dev
SITE=hzdt-09
RUNTIME_MODE=DEVELOPMENT
COLLECTION_MODE=playback_only
WINDOW=1920x956 client area on 1920x1080 display
```

Runtime bootstrap 和日志证据位于 `D:\NetConsoleRuntime-dev\R5.0.1\electron\user-data\bootstrap.json` 与 `D:\NetConsoleRuntime-dev\R5.0.1\logs\`。窗口标题也显示当前数据根和 DEVELOPMENT 模式。

实际画面已观察到：

- 主用 Heartbeat：蓝色 RTT、红色失败采样和失败 Tooltip（`丢包：100%`）。
- 备用 Heartbeat：同样的蓝/红图例和失败采样。
- 主地址 Quick Ping：蓝色 RTT、绿色 `0%` 连通线、红色失败点。
- 备用地址 Quick Ping：同样的颜色和成功 Tooltip（`RTT：28 ms`、`状态：正常连通`）。

证据截图：

- `gui-ping-color-1920x1080-full.png`
- `gui-ping-color-1920x1080-backup.png`

## 验收矩阵

```text
PING_SUCCESS_GREEN=PASS
PING_TIMEOUT_RED=PASS
PING_PACKET_LOSS_RED=PASS
PING_UNKNOWN_GRAY=PASS (状态轴灰色标记)
RTT_BLUE=PASS
LOSS_ZERO_MAPPING=PASS
LOSS_PERCENT_MAPPING=PASS
TOOLTIP_DATA_CONSISTENCY=PASS
LEGEND_CONSISTENCY=PASS
PRIMARY_HEARTBEAT=PASS (1920x1080 DEV GUI)
BACKUP_HEARTBEAT=PASS (1920x1080 DEV GUI)
PRIMARY_QUICKPING=PASS (1920x1080 DEV GUI)
BACKUP_QUICKPING=PASS (1920x1080 DEV GUI)
PRIMARY_BACKUP_ISOLATION=PASS
FIVE_CHARTS_TIMELINE_SYNC=PASS (automated contract; native wheel/drag not re-certified here)
COLLAPSE_EXPAND=PASS (existing regression contract)
PEER_AP_RAINBOW_PRESERVED=PASS
QUICK_PING_SIMULATION_PRESERVED=PASS
SYSLOG_PRIORITY_PRESERVED=PASS
GUI_1920X1080=PASS
GUI_2560X1440=NOT_VERIFIED
PRODUCTION_DATA_MODIFIED=0
REAL_DEVICES_ACCESSED=0
DEVICE_CONFIG_WRITES=0
```
