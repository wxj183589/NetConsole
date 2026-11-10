# Remaining Issues

1. 真实运行更新了隔离快照的 `mr_raw_mesh/catalog.sqlite`；当前没有恢复，避免破坏验收证据。需要后续用可写 candidate 或重新生成 snapshot 做无副作用复验。
2. 当前 probe 未记录 `mtime_ns`，无法完成用户要求的完整 mtime 前后证明；不能以 SHA/size 相同替代 mtime 结论。
3. 全运行 request ledger 有 94 条 MESH HTTP、9 SQL，其中 13 条 FAILED/transition cancellation；缓存 chart 动作本身为 HTTP=0/SQL=0，但不能把全运行说成 0/0。
4. gap trace 证明缺口检测、补取、合并和最终 13/13，但未证明只查询 B 而绝不重新读 A/C。
5. 13 个 ECharts panel 对应 14 个业务字段，因为 Tx/Rx 是双序列；若验收必须要求 14 个独立 DOM chart，需要另行明确产品要求。
6. ECharts instance count 与 event listener count 当前无法从 Electron probe 直接观测；30 分钟 Heap 结果因此保持 PARTIAL。
7. Workspace layout checker 仍报告既有 `D:\study\NetConsole-Workspace\docs` 顶层目录；本轮 harness 已退役，没有删除该既有目录。
8. Excel/WPS、真实设备/现场数据、生产根和跨机器验收不在本轮结论内。

