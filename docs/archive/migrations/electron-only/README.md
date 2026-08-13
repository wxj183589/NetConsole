# Electron-only 冻结证据

本目录只保留 Electron-only 收敛中无法由当前代码直接恢复的测量或审计基线，不是当前架构或发布规则。当前规则见 [总体架构](../../../ARCHITECTURE.md)、[Desktop](../../../architecture/DESKTOP.md)、[存储](../../../storage/README.md)和[构建发布](../../../release/BUILD_AND_RELEASE.md)。

- [启动性能基线](./E5-2026-07-18.md)：测量环境、阶段耗时和优化前后证据。
- [真实库索引基线](./E6-2026-07-18.md)：脱敏副本查询计划、索引收益和回滚边界。
- [架构一致性基线](./ARCHITECTURE_COMPLIANCE_REPORT.md)：2026-07 的 Guard、迁移分类与未验收边界。

原 E1-E4、E6A、E10B、E11、交接、依赖和生成物清理过程由 Git 历史保留，其长期规则已并入活动文档。
