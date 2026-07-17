# Qt 迁移期界面

## 用途

本目录仅保存 Electron-only 重构期间尚未删除的 Qt 页面、控件和薄 Adapter，作为历史功能事实源与迁移兼容层；不再新增 Qt 业务页面或只供 Qt 使用的业务实现。

## 边界

允许布局、Signal/Slot、轻量输入校验、显示格式化和对永久 Application Service 的调用。禁止新增设备命令、Parser、数据库事务、报告规则、任务状态机或领域计算；发现既有逻辑时迁入 `src/netconsole/services`、Repository、Parser 或其他实际永久层。

## 迁移规则

每个删除文件都要按 `PURE_UI`、`BUSINESS_MOVED`、`ADAPTER_REPLACED`、`DEAD_CODE` 或 `FEATURE_REMOVED` 记录去向。无法证明无调用的代码不得标记为 `DEAD_CODE`；Qt 文件删除后以 Git 历史保留，不创建 `legacy/old/backup` 副本。

## 测试

迁移期间只运行受影响的 Qt 兼容测试，保证业务抽离不改变历史行为。Electron-only 最终门使用无 Qt 环境和非 Qt 全量测试；Qt 测试不得进入最终发布依赖。

## 相关文档

- [下一代架构](../../../docs/ARCHITECTURE_NEXT.md)
- [架构一致性审计](../../../docs/ARCHITECTURE_COMPLIANCE.md)
- [Qt/Electron 对等矩阵](../../../docs/development/qt-electron-parity-matrix.md)
