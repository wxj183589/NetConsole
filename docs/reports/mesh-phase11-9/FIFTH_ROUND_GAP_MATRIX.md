# NetConsole MESH Phase 11.9 第五轮差距矩阵

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
结论：`PHASE_11_9_FIFTH_ROUND=PARTIAL`

本轮按“证据已完成”与“仍未证明”分开记录，不把 mock、代码检查或隔离 Electron 启动升级为真实业务 GUI 验收。

| 范围 | 结果 | 证据 | 边界 |
|---|---|---|---|
| `mesh-raw-v1` 统一原始采样 | PASS | Workbench、raw cache、gap planner 与后端 raw DTO 已统一；定向 Renderer 43 项通过 | 未执行完整全量 Renderer |
| `include_zero` 进入 raw 主链路 | PASS | LinkCnt=0 Renderer 契约、后端 raw+zero 测试；宁波12号线真实查询返回 zero=1 | 仍保留旧 API 兼容 fallback |
| 真实 full/segmented raw 连续性 | PASS | 20 秒窗口可见 `31+30=61`，重复/遗漏均为 0 | 仅宁波12号线一个窗口 |
| 真实派生字段逐字段对照 | PASS（Service raw + 实际 TS 派生） | 61 条可见真实 raw 行，`deriveMeshRawSamples()` 全字段对照通过 | 未在完整 Electron 页面中执行 |
| A+C 缺口只补 B | PASS | `meshRawSampleCache.test.ts` 精确断言 `[BASE+1001, BASE+1999]` | 仅最小 fixture |
| 300 秒缩放至 240 秒 | PASS（代码/测试） | complete raw cache、complete index 和 gap planner 优先本地派生 | 未做长时滚轮实机统计 |
| build/detail 避免重复 nearest | PASS（代码/测试） | `selectBuild()` 先查 raw cache，命中时本地派生；未命中才走单次 fallback | 真实 GUI 点击未执行 |
| AP 统计缓存与 scope 隔离 | PASS（代码/测试） | role/radio scope 测试通过；AP LRU 上限为 32 | 未完成真实 AP 页面长稳 |
| Interaction→Cache→HTTP→SQL trace | PARTIAL | 后端 DTO/Service SQL 计数、开发/测试 trace ledger、mock 100 次验收通过 | 未完成真实 Electron 全工作台 trace |
| 100 次交互 HTTP=0/SQL=0 | PASS（mock workbench） | 100 次同窗口 `openContext` 后 HTTP=0、SQL=0、cache hit≥100 | 非真实 Electron、非真实数据请求 |
| LRU/内存 | PARTIAL | raw 8 scopes/100000 samples、AP 32、page cache 32、metric cache 16、trace 2048、selection 128 | 未完成 JS Heap/Canvas/ECharts profile、1/4/8 小时 soak |
| Electron 1920×1080 启动 | PASS（runtime geometry） | 隔离 `dev:codex` ready；真实 Electron window rect=1920×1080 | 空隔离根；未宣称 MESH 业务 GUI 验收 |
| 数据完整性与 SHM | PARTIAL | 主要文件内容 SHA/大小未变，SHM SHA 未变 | SHM mtime 漂移，不能宣称零文件系统副作用 |
| 广泛 MESH 回归 | PARTIAL | 本轮相关 Python 134、Renderer 43、typecheck 通过 | 全量 Python/Renderer/Electron、Excel/WPS、现场设备未执行 |

未关闭的 P0/P1 证据缺口：真实 Electron 加载宁波12号线后的完整工作台请求闭环、真实 Heap 长稳、逆序/多段/重叠现场交互、全量回归及设备/Excel/WPS 验收。
