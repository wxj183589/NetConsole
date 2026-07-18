# Vue 表格与高密度数据规范

本文定义 Electron 唯一 Vue Renderer 的表格规则。旧 QTableWidget、Delegate 和 QCheckBox 规范已经归档；新代码使用 Element Plus、`NcTable` 与 [NetConsole UI Design System](UI_DESIGN_SYSTEM.md)。

## 选择与批量操作

- 多选使用 `el-table-column type="selection"`，选择状态以稳定业务 ID 关联，不使用行号。
- 全选只覆盖当前明确数据范围；跨页全选必须显示范围并要求确认。
- 无选择时禁用批量动作；选择变化后按钮状态必须立即一致。
- 删除、写配置、批量刷新等危险动作显示数量、对象摘要和二次确认。

## 列宽与滚动

- 核心标识列给出稳定 `min-width`，短状态/时间列使用明确宽度。
- 总宽超过视口时允许横向滚动，不能为塞进窗口而把字段压缩到不可读。
- 页面、弹窗和子窗口内容超出时提供纵向和必要的横向滚动；操作区始终可达。
- 允许用户手工调整列宽；固定列只用于确有操作必要的首尾列。

## 密度与状态

- 默认使用 `NcTable` 的 40px 行高和 14px 字体；仅在信息密集页面显式启用 `compact`。
- loading、empty、success、warning、failed、cancelled 均有可见反馈。
- 状态使用 `NcStatusTag` 和统一语义 Token，不在页面重复维护颜色/标签映射。
- 路径、命令、错误和长文本使用省略、Tooltip 或详情区，不直接撑破表格。

## 性能与数据边界

- 大列表使用分页、服务端筛选或懒加载，不在 Renderer 一次构造无上限数据。
- 单元格只做轻量展示；解析、聚合、设备访问和导出进入 Application Service/Job/Export。
- 行 key 必须稳定；更新数据时避免整表深拷贝和重复注册监听。
- ECharts 与表格联动必须节流，并在组件卸载时释放图表和订阅。

## 验证

至少验证 1920×1080、最小支持窗口和窄窗口：列宽、滚动、选择、分页、空态、加载态、深浅主题、弹窗确认与键盘焦点均可用。
