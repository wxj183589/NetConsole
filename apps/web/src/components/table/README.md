# 统一数据表格组件

本目录是 Electron/Vue 标准业务表格的唯一公共实现。页面只声明字段、插槽和轻量交互，不在页面中自行测量文本、计算列宽或覆盖表格对齐。

## 组件职责

- `NcDataTable.vue`：统一表格容器、列渲染、横向滚动、列偏好和 Element Plus 事件转发。
- `NcTableColumn.ts`：强类型列定义、缺失值和字段读取规则。
- `useAutoColumnWidth.ts`：表头/内容基础宽度、可视区剩余空间分配、稳定抽样、防抖、跨页历史宽度和手工宽度优先级。
- `textMeasurement.ts`：Canvas 优先、DOM 次选的真实文本测量；无渲染环境时按字符类别估算，不使用 `text.length * px`。
- `columnPresets.ts`：字段类型的统一最小/最大宽度。
- `tablePreferences.ts`：按用户、路由、表格 ID 和语言保存列宽、顺序、显隐及固定位置；只写视图偏好，不写业务数据库。
- `NcColumnSettings.vue`：恢复默认、自动适应、列显隐、顺序和固定位置。
- `NcTableCell.vue`、`NcOverflowTooltip.vue`：缺失值、省略和 Tooltip 展示。

## 强制契约

最终列宽必须满足：

```text
finalWidth >= headerRequiredWidth
```

表头宽度包含文字、内边距、排序/筛选图标和安全余量。空间不足时保持列宽并由表格内部横向滚动，不能压缩表头。普通列默认表头/内容居中；日志、配置、路径、错误和描述等长文本左对齐时必须声明 `alignmentReason`。

空间充足时按 `priority=3`、`normal=1` 分配剩余宽度，`fill` 最后承接，`none` 不参与。状态、时间、操作、固定列和手工宽度默认不拉伸；所有列达到最大宽度后列组居中。公共组件只把当前容器拉伸应用到最终宽度，跨页历史只记录内容基础宽度，因此窗口缩小时不会保留上一轮大窗口的额外拉伸。

页面必须提供稳定的字面量 `table-id` 和 `route-key`。页面不得直接写 `el-table-column`、`header-align`、`measureText()` 或表格列宽；确需固定的复选框、序号、展开或图标列登记到 `config/architecture/table-layout-exceptions.yaml`。
页面也不得直接调用公共列宽算法、使用 `containerWidth / columns.length` 平均分配，或用小于 100% 的百分比宽度限制标准表格。

## 使用示例

```vue
<NcDataTable
  table-id="device-list"
  route-key="/devices"
  :data="rows"
  :columns="columns"
>
  <template #cell-status="{ row }"><NcStatusTag :status="row.status" /></template>
</NcDataTable>
```

## 验证

```powershell
pnpm --dir apps/web exec vitest run src/components/table
pnpm --dir apps/web exec vue-tsc -b --pretty false
pnpm --dir apps/web test:visual
\.venv\Scripts\python.exe scripts\ui\check_table_contracts.py
\.venv\Scripts\python.exe -m pytest tests\test_ui_table_guards.py -q
```
