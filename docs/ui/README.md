# Electron/Vue UI 规范

本目录记录唯一 Vue Renderer 的全局展示契约。主题事实源仍在 `apps/web/src/theme/`，表格运行时事实源在 `apps/web/src/components/table/`。

- [表格与字段标准](TABLE_AND_FIELD_STANDARDS.md)
- [表格迁移清单](TABLE_INVENTORY.md)
- [Design Token](DESIGN_TOKENS.md)
- [响应式布局](RESPONSIVE_LAYOUT.md)
- [视觉测试](VISUAL_TESTING.md)

当前处于分阶段迁移期。`TABLE_INVENTORY.md` 中 `BLOCKED` 是明确的旧表债务；只有使用统一组件并通过 Guard 的表格才标记 `MIGRATED`。截图和人工 DPI 验收未执行前，不得把公共组件自动测试写成全局视觉完成。
