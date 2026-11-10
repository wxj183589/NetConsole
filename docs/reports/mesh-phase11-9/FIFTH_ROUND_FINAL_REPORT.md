# NetConsole MESH Phase 11.9 第五轮最终报告

日期：2026-11-10  
Branch：`codex-A/global-dataroot-disk-policy`  
最终状态：`PHASE_11_9_FIFTH_ROUND=PARTIAL`

## 本轮交付

- 统一 raw `include_zero` 查询契约，保持 `mesh-raw-v1` / `mesh-derived-v1` 版本边界；
- 修复 raw 查询中 query-relative `sample_group_index`，改为稳定持久化样本序号，消除 full/segmented 字段差异；
- 完成 Workbench 的 raw cache gap、history、metric、nearest、build detail、Build Order、AP page 的消费者收敛；
- 新增开发/测试 opt-in 的 Interaction→Cache→HTTP→SQL trace，后端真实 SQL 计数和 operation/query metadata；
- 为 AP page、raw facts、page/metric cache 和 trace ledger 保留明确上限，避免无界缓存；
- 用宁波地铁12号线真实 raw 数据完成 full/segmented 数量、身份、角色、context、include_zero 和实际 TS 派生字段逐字段对照；
- 完成隔离 Electron smoke 与 1920×1080 窗口几何核验。

## 主要证据

- 真实 20 秒窗口：可见 `31+30=61`，完整查询 `61`；可见 ID 串联重复/遗漏均为 0；
- 真实 raw+zero：完整 `total=62`、`zero=1`；
- 真实派生：61 条可见行，所有比较字段（含 counters/delta/gap/role）一致；
- mock Workbench 100 次同窗口交互：warm 后 HTTP=0、SQL=0、cache hit≥100；
- raw gap fill：A+C→仅 B `[BASE+1001, BASE+1999]`；
- 自动化：Renderer 43 passed、Python 134 passed，typecheck 和隔离 Electron startup 通过。

## 必须保留的限制

本轮没有完成真实 Electron 加载真实 MESH 数据后的全工作台交互、真实 Heap/Canvas/长稳、全量回归、Excel/WPS 或现场设备验收。SQLite parsed `-shm` 内容 SHA 未变但 mtime 漂移，数据完整性只能结论为内容级通过、元数据零漂移未通过。

因此本轮不宣称 `PASS`，不宣称生产发布就绪，不宣称真实 GUI/设备验收完成。

## 提交边界

产品只提交本轮 MESH 源码、测试和本目录报告；保留并行 DataRoot/Ground 等 dirty 修改。DevStatus 单独本地提交。产品与 DevStatus 均不 Push、Merge 或 Release。
