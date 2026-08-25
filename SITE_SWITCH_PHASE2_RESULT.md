# Site Switch Phase2 结果

日期：2026-08-26

## 结论

Site Switch 的 backend warm handoff 已由主线提交 `4a13213e` 集成，本轮 Phase2 没有重复实现 backend lifecycle，也没有修改 Electron warm handoff 代码。当前结果为 **PASS（代码与启动链路）/ PARTIAL（本轮未重新执行完整 GUI 局点交替）**。

## 基线与当前证据

| 指标 | 优化前证据 | 当前证据 |
| --- | --- | --- |
| 用户可见局点切换 | 8.5–14.4s，原因是 backend restart | warm handoff 路径已在 main；当前 DEV 桌面启动 interactive 6,818ms |
| backend ready | 受冷启动接管影响 | 3,211ms |
| backend restart | 存在 | 本次 DEV 启动日志未发现 restart/exit |
| migration/schema mismatch | 未作为切换优化目标 | 本次 DEV 启动日志未发现 migration 或 schema mismatch |
| metadata warm handoff | 历史 DEV 交替 6 次为 362–453ms，P95 453ms | 该证据对应已合入 main 的 warm handoff 提交；本轮未再次执行 GUI 交替 |

## 重复性检查

- `474c8fe6` 提供性能基础与 warm handoff 所需前置路径。
- `4a13213e` 完成 backend warm handoff；已在 main 中合并。
- 本轮没有新增第二套 backend handoff、缓存或 renderer 生命周期。
- Phase2 代码只触及 Trackside 当前事实批量读取和 MESH 查询源数据预算。

## 风险与后续

完整 backend 接管仍可能在后台持续较长时间；当前设计的目标是先让 metadata/page visible 可交互。下一步应在最终优化提交上补做两局点交替 GUI 验收，确认 warm handoff、返回切换和异常恢复均无回归。
