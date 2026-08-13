# 历史归档

本目录只保存当前代码无法恢复、未来维护仍需要的冻结证据。归档不是当前规范、待办清单、功能授权或恢复旧架构的入口；当前事实以生产代码、测试和 [活动文档](../README.md) 为准。

## 保留资料

- [Electron-only 迁移证据](./migrations/electron-only/README.md)：启动性能、真实库索引和当时架构 Guard 基线。
- [Qt 到 Electron 冻结迁移映射](./migrations/qt-to-electron/README.md)：已删除路径去向、迁移决策与独立验收维度。

真实局点问题调查保存在 `docs/investigations/`，用于复现证据与回归口径，不替代领域文档。

新增归档必须同时满足：知识无法从当前代码或 Git 提交说明直接恢复、对未来维护有明确价值、背景和日期清楚、不含凭据或真实敏感数据、不会被误认为当前规则。普通 Audit、Assessment、Plan、Handoff 和阶段流水账不进入归档。
