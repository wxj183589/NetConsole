# Vue 表格与高密度数据规范

本文是 Electron 唯一 Vue Renderer 的表格入口说明。完整列模型、自动列宽、字段对齐、偏好和 Guard 以 [表格与字段展示标准](./TABLE_AND_FIELD_STANDARDS.md) 为准，迁移状态以 [表格清单](./TABLE_INVENTORY.md) 为准。旧 QTableWidget、Delegate 和 QCheckBox 规范已经归档；新增标准表格使用 `NcDataTable`，`NcTable` 只保留给尚未迁移的旧页面。

## 选择与批量操作

- 多选使用 `el-table-column type="selection"`，选择状态以稳定业务 ID 关联，不使用行号。
- 全选只覆盖当前明确数据范围；跨页全选必须显示范围并要求确认。
- 无选择时禁用批量动作；选择变化后按钮状态必须立即一致。
- 删除、写配置、批量刷新等危险动作显示数量、对象摘要和二次确认。

## WPS 风格筛选下拉框

离散值、可组合的**列表筛选**使用 `components/table/NcMultiValueFilter.vue`：支持搜索（包括显示标签）、全选、反选和确定/取消；模型为字符串数组，`[]` 代表不限制范围。需要显示名称与实际筛选键不一致时传入 `labels`，不要将多选用于编辑单值、选择设备目标、排序方向或互斥业务动作。当前已用于轨旁 AP 车站、任务中心状态与模块、Agent 状态与启用状态、车内通信点表列车及节点类型。

筛选结果在前端已有完整数据时可使用本地 OR 匹配；服务端分页、XLSX/WPS 任务或跨页筛选必须在 API、Application Service 与 Worker 中一致接收多值过滤。轨旁 AP 的选站状态按局点保存在本地 UI 配置，默认 `[]`（全部站点），导出和在线同步使用同一组所选车站，不因为 UI 单页分页而缩小导出范围。

## 列宽与滚动

- 页面不再散写 `min-width`；字段类型基线由 `columnPresets.ts` 维护，最终宽度由统一测量算法确定。
- 自动列宽的绝对下限是完整表头宽度，排序、筛选和状态图标必须计入。
- 总宽超过视口时允许横向滚动，不能为塞进窗口而把字段压缩到不可读。
- 页面、弹窗和子窗口内容超出时提供纵向和必要的横向滚动；操作区始终可达。
- 允许用户手工调整列宽；固定列只用于确有操作必要的首尾列。

日志控制台型页面使用 `NcLogWorkspace + NcDataTable.fillRemainingHeight`：筛选、摘要、动作和分页
`flex: none`，表格区 `flex: 1; min-height: 0`，纵向只滚动 table body。普通资料表使用
`autoHeight`；`fillRemainingHeight` 启用时不得再叠加 `autoHeight`、`maxHeight` 或页面级主滚动。

## 密度与状态

- 默认使用 `NcDataTable` 的 40px 行高和 14px 字体；仅在信息密集页面显式启用 `compact`。
- loading、empty、success、warning、failed、cancelled 均有可见反馈。
- 状态使用 `NcStatusTag` 和统一语义 Token，不在页面重复维护颜色/标签映射。
- 路径、命令、错误和长文本使用省略、Tooltip 或详情区，不直接撑破表格。

## 性能与数据边界

- 大列表使用分页、服务端筛选或懒加载，不在 Renderer 一次构造无上限数据。
- 单元格只做轻量展示；解析、聚合、设备访问和导出进入 Application Service/Job/Export。
- 行 key 必须稳定；更新数据时避免整表深拷贝和重复注册监听。
- 隐藏列不挂载到 Element Plus；列显隐、顺序和固定状态变化可以受控重挂载，普通数据刷新和空态切换必须保持既有列结构。
- ECharts 与表格联动必须节流，并在组件卸载时释放图表和订阅。

## 验证

至少验证 1920×1080、最小支持窗口和窄窗口：列宽、滚动、选择、分页、空态、加载态、深浅主题、弹窗确认与键盘焦点均可用。
