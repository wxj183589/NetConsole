# 真实数据验证

日期：2026-11-09；数据 Authority：`D:\NetConsoleData-dev`；实际 Electron，1920×1080。

## 样本与保护

宁波地铁12号线，列车01-MR-CW，会话 `80716c07-6bd9-47d8-b76d-ace1e55624d1:1`，有效记录 108700；ACTIVE 44470、STANDBY 64230。直接只读查询，未复制完整数据库/数据根。

`real-data-crosscheck.json` 中 SQLite 大小 156786688 字节，SHA-256 `2b8bf5b5c7fdf350f2cb105eb1512d6f93b292354b5739942d2c49e6f78da61d`；raw gzip 大小 2892510 字节，SHA-256 `f53990d5448f297ea8cbc6901d87132fcf3f616c61149feaa4e875829a3b0fc7`。前后相同。

## L/P、增量与历史角色

对照归档原始行、只读 SQLite 和真实 API 响应，样本 107873→107875，AP `bc:5a:34:57:62:c0`、Radio1、ACTIVE，采样 18:38:42.656 起。RSSI、CPU、内存、Busy、Rate、Noise、TxDesFreeCnt 及计数器原值逐项对照，`all_comparisons_passed=true`。

| 增量 | L | P |
| --- | ---: | ---: |
| Tx | 277 | 15 |
| Rx | 20 | 261 |
| Retry | 79 | 5 |
| Err | 4 | 0 |
| GARP | 0 | 0 |
| MulJoin | 0 | 0 |

图表使用真实时间戳，无值保留空缺；计数器趋势是差分，右侧详情为当时原始累计值。历史 STANDBY 与 Radio2 的操作结果保留在 `rapid-cache-lifecycle.json`，不以当前角色覆盖历史角色。样本正确不代表所有站点和所有日志均已现场验证。

## LinkCnt=0

同一真实窗口：默认关闭 history135/build28/zero0；开启 history142/build35/zero7；关闭恢复135/28/0。选中零槽位样本时间 18:38:59.468，角色 UNCONNECTED，LinkCnt=0，未计入 ACTIVE/STANDBY。证据 `filters-interactions.json` 和截图10/11。默认已有质量统计语义不变。

## 交互与业务一致性

- 单 AP 历史：`single-ap-interaction.json`；表格分页与图表使用同一 AP/Radio/角色/时间窗。
- 统一记录：`13-unified-build-records.png`；移除重复旧表，保留建链时间、持续时长和 RSSI 统计。
- 八图拖动、缩放、导航器、悬停和点击：`timeline-interactions.json`；各图真实 time axis 与相同窗口，右侧选择同一采样点。
- RSSI 跳转：窗口14:07:01.605–14:07:31.605，定位14:07:16.605；AP `bc:5a:34:57:8b:20`、Radio1、ACTIVE，八图完成且详情时间相同。证据 `rssi-jump.json`。
- 快速切换、12次重复AP操作、缓存16项、工作区销毁和重入：`rapid-cache-lifecycle.json`；实际应用导航补验见 `actual-navigation-lifecycle.json`。

以上使用已有真实会话，未模拟填充缺失指标。没有真实故障注入、设备命令或数据库写入。
