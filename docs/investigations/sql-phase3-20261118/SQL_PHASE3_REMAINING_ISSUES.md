# SQL Phase 3 剩余事项

- Mesh-Link `vehicle_mr_online_links` 的 snapshot 条件在当前合成库上仍显示表扫描；本轮瓶颈证据是 identity 单条回退而不是该扫描，未修改
  Schema。后续只有在真实规模只读画像证明扫描占主导时，才单独评估兼容索引。
- 画像 baseline 与优化路径使用同一请求入口；仅 identity fallback 被关闭 batch，以量化修复前的 N+1。
- 未运行全量 Python、Renderer、Electron 或 Release Gate，按本阶段范围保留为集成门禁。
- 未进行真实设备、GUI、安装包或生产数据验收。

当前未发现会阻断 Phase 3 合并的业务回归。
