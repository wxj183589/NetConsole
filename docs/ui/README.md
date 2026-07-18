# Electron/Vue UI 规范

本目录记录唯一 Vue Renderer 的全局展示契约。主题事实源仍在 `apps/web/src/theme/`，表格运行时事实源在 `apps/web/src/components/table/`。

- [表格与字段标准](TABLE_AND_FIELD_STANDARDS.md)
- [表格迁移清单](TABLE_INVENTORY.md)
- [Design Token](DESIGN_TOKENS.md)
- [响应式布局](RESPONSIVE_LAYOUT.md)
- [视觉测试](VISUAL_TESTING.md)

当前登记的 87 张标准表格均已使用统一组件并通过 Guard，`table-layout-baseline.json` 不再保留旧表债务。后续新增表格仍必须直接使用 `NcDataTable` 并登记清单；截图、DPI/缩放和人工验收未执行前，不得把自动测试写成全局视觉验收完成。
