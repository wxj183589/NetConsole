# R5.0.5.2 RSSI 语义修复报告

日期：2026-11-22
产品 HEAD：`425d5b42`
数据 Authority：`D:\NetConsoleData-dev`（本轮未写入）

## 解析结论

`MESH_ACTIVELINK_SWITCH` 现在分别保存 `old_rssi`（from/切出）和 `new_rssi`（to/切入），不会复制或交换两个值。真实样本回归覆盖 15:28:43、15:28:51、15:28:56、16:01:20、16:01:22、16:01:25 六条记录，逐条核对为：

| 时间 | 切出 RSSI | 切入 RSSI |
| --- | ---: | ---: |
| 15:28:43 | 37 | 42 |
| 15:28:51 | 40 | 45 |
| 15:28:56 | 38 | 47 |
| 16:01:20 | 37 | 46 |
| 16:01:22 | 43 | 53 |
| 16:01:25 | 54 | 62 |

相邻且 MAC 连续的事件生成 Peer AP 主用区间；区间柱高使用切入 RSSI，Tooltip 同时展示切入/切出 RSSI。缺少后续切出证据、无主链路或缺失 RSSI 时保持未记录，不补造时间或数值。

## 代码证据

- `src/netconsole/services/ground_unattended/syslog_runtime.py`：解析并持久化 `old_rssi` / `new_rssi`。
- `src/netconsole/services/ground_unattended/monitoring.py`：按相邻事件和 canonical AP MAC 构建区间。
- `apps/desktop_renderer/src/components/ground-unattended/mrMonitoringChartOptions.ts`：Tooltip 分列显示切入/切出 RSSI。

结论：`FROM_AP_MAPPING=PASS`、`FROM_RSSI_MAPPING=PASS`、`TO_AP_MAPPING=PASS`、`TO_RSSI_MAPPING=PASS`、`PEER_AP_INTERVAL=PASS`、`ENTRY_RSSI=PASS`、`EXIT_RSSI=PASS`、`AP_MAC_CONTINUITY=PASS`、`NO_ACTIVE_LINK_HANDLING=PASS`。
