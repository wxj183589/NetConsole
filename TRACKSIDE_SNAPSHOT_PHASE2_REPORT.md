# Trackside Snapshot Phase2 报告

日期：2026-08-26

## 实施范围

本轮仅处理轨旁 AP 业务快照的高频设备事实读取路径：

- `DeviceFactRepository` 新增接口、光模块、LLDP 的按设备 UUID 批量读取；每类事实使用一次 `IN` 查询，再按设备分组。
- `trackside_ap_export_service` 优先使用批量读取；批量读取异常时保留原有逐设备降级路径。
- 同一次快照复用 `list_ap_extension_points()` 结果，避免重复读取站点扩展点。
- 未修改 AP Identity、LLDP 规则、历史模型、Task/Export 生命周期或数据库 schema。

## DEV 实测

数据根仅为 `D:\NetConsoleData-dev`，采用只读数据库连接和已有 profiling harness。

| 局点 | 当前快照读取 | query | build | 行数 | SQL |
| --- | ---: | ---: | ---: | ---: | ---: |
| 杭州 10 号线 | 1,310ms | 1,003ms | 283ms | 868 | 103 次 / 164.1ms |
| 宁波 12 号线 | 8,728ms | 7,576ms | 988ms | 1,247 | 111 次 / 24.91ms |

同一只读 harness 下，逐设备旧路径与批量路径结果行数、行 ID 一致：杭州 10 号线约 1,346.55ms 降至 1,278.51ms；宁波 12 号线约 8,894.41ms 降至 8,768.33ms。该 A/B 结果说明批量读取已生效，但宁波 12 号线的主要耗时不在当前事实 SQL。

## 剩余热点

宁波 12 号线的 cProfile 证据显示，`list_latest_ap_lldp_histories`/HistoryStore 历史解码约 8.2s，包含大量压缩、解码和分片查询。该部分属于独立的 HistoryStore/历史数据专项，未在本轮修改，避免把快照批量读取和历史模型变更混入同一提交。

## 验证

- `tests/test_device_fact_repository.py` 覆盖三类批量读取与逐设备读取结果一致性。
- Trackside 相关测试：109 passed。
- Ruff、compileall、diff check：通过。
- DEV 导出真实结果见 `REAL_TRACKSIDE_EXPORT_TEST.md`；导出端到端仍受 snapshot build 影响。
