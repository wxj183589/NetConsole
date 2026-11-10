# Screenshot Inventory

10 张固定名称截图均已生成，均为实际 Electron 原生窗口截图，PNG 尺寸 `1920x1080`；Renderer viewport 为 `1904x1041`、DPR=1。目标会话均为 `80716c07-6bd9-47d8-b76d-ace1e55624d1:1`。

| 文件 | Electron PID | operation | 状态/窗口 | 时间窗口 |
|---|---:|---:|---|---|
| `01-initial-workbench.png` | 46580 | 0 | overview 初始工作台 | 18:37:06.381–18:42:06.381 |
| `02-all-metrics-loaded.png` | 46580 | 1 | main，13/13；14 fields | 18:37:06.381–18:42:06.381 |
| `03-wheel-zoom-in.png` | 46580 | 3 | cached range wheel zoom in | 18:36:31.354–18:41:31.354 |
| `04-wheel-zoom-out.png` | 46580 | 4 | cached range wheel zoom out | 18:35:51.380–18:42:06.380 |
| `05-tooltip-counter.png` | 46580 | 18 | tooltip/counter | 18:39:00.289–18:39:20.905 |
| `06-shift-fixed-detail.png` | 46580 | 19 | Shift fixed selection detail | 18:39:00.289–18:39:20.905 |
| `07-ctrl-browser-detail.png` | 46580 | 20 | Ctrl browser selection detail | 18:39:00.289–18:39:20.905 |
| `08-gap-fill-completed.png` | 52192 | 1（补充运行） | main，13/13 gap completed | 18:35:51.381–18:42:06.381 |
| `09-ap-radio-switch.png` | 52192 | 2（补充运行） | AP 情况，STANDBY，Radio 1，853 rows | 18:35:51.381–18:42:06.381 |
| `10-page-reentry.png` | 46580 | 34 | page re-entry main | 18:38:57.542–18:39:23.312 |

采样源码提交均为 `de7ca957d371cd8bc29b60d05f69f4c85d8b2190` dirty working tree。补充运行仅用于在真实 Electron 中等待完成并补拍 08/09，不改变截图命名约束。
