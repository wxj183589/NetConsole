# R2.3.1 AC 全快照差异同步

AC 当前按完整 Mesh-Link 快照处理，差异在本地计算并写入 `ground_unattended_ac_deltas`。变更是 additive、可回放、按 `(site, snapshot, entity, change_type)` 幂等插入；失败、过期、旧版本或不完整快照不会产生安全删除。

## 本地模拟结果

三次合成快照统计：

| 快照 | ADDED | UPDATED | REMOVED | UNCHANGED | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| 1 | 100 | 0 | 0 | 0 | 0 |
| 2 | 0 | 99 | 1 | 0 | 1 |
| 3 | 1 | 0 | 0 | 99 | 0 |

共持久化 301 条 delta 证据。未知 MR 行被保留为 UNKNOWN，不参与已识别 MR 的删除决策。过期/旧/不完整快照的单元测试确认不会生成 REMOVED。

## 轮询边界

AC 默认轮询周期仍为 60 秒，AC-Mesh-Link 保持独立开关和退避边界；本次验证覆盖代码默认值、全快照差异和 Repository 持久化，但没有等待 60 秒现场轮询周期或连接真实 AC。该项在验收矩阵中以本地证据 caveat 标记。
