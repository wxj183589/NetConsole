# 表格与字段展示标准

## 默认规则

标准业务表格使用 `NcDataTable`，表头和内容水平/垂直居中，单元格单行显示，缺失值统一为 `—`。事实为零时保留 `0`，不能把缺失值伪造成 `0 Mbps`、`0 dBm`、`null` 或空字符串。

只允许配置正文、日志正文、命令输出、错误详情、备注、描述、JSON、路径和多行文本左对齐。列定义必须同时给出 `alignmentReason`，不能在页面 CSS 中覆盖。

## 两阶段自动列宽

```text
headerRequiredWidth
= 表头文本 + 左右内边距 + 排序/筛选/状态图标 + 安全余量

contentRequiredWidth
= 抽样内容最大宽度 + 左右内边距 + 图标/Tag/按钮边框与间距 + 安全余量

baseWidth
= clamp(max(headerRequiredWidth, contentRequiredWidth,
            typeDefaultMinWidth, configuredMinWidth),
        effectiveMinWidth, effectiveMaxWidth)
```

绝对条件是：

```text
baseWidth >= headerRequiredWidth
```

配置的最大宽度若小于完整表头宽度，以完整表头为准。内容超过有效最大宽度后才省略并显示 Tooltip；容器不足时由表格区域横向滚动，不能压缩表头。

基础宽度计算后，公共组件按表格滚动区域的实际 `clientWidth` 执行第二阶段布局：

```text
baseTotalWidth >= availableWidth
→ 保留基础宽度，表格内部横向滚动

baseTotalWidth < availableWidth
→ 按 priority=3、normal=1 的权重分配剩余空间
→ 达到 maxWidth 的列退出分配，空间继续交给其他列
→ fill 列最后承接仍可用的空间
→ 全部列达到最大宽度后，列组整体居中
```

`selection/index/status/port/number/rate/percentage/datetime/duration/actions` 默认 `stretch=none`；`text/ip` 默认 `normal`；`name/description/error` 默认 `priority`。页面只在业务含义需要覆盖默认值时声明 `stretch` 和 `stretchWeight`。用户手工宽度、固定列和 `widthMode=fixed` 不参与自动拉伸。

文本测量使用当前字体的 Canvas `measureText()`；Canvas 不可用时使用隐藏 DOM，测试/无渲染环境才按字符类别估算。不得使用字符串长度乘固定像素。

## 性能与刷新

- 默认最多稳定抽样 200 行，保留首尾代表记录。
- 分页后宽度只增不减，避免列跳动；“自动适应”可以显式重置历史最大值。
- `ResizeObserver` 监听表格滚动区域；数据、容器、语言、主题、字体或缩放变化后防抖 350ms 重算。
- 历史内容宽度和当前容器拉伸宽度分开保存；窗口缩小时可以回到内容基础宽度，但不能因分页内容变短自动缩窄。
- 用户手工列宽优先于自动结果，但不能小于完整表头。
- WebSocket 单条更新不能立即触发整表重复测量。

## 偏好与优先级

```text
用户手工设置 > 页面显式配置 > 自动计算 > 字段类型默认值
```

视图偏好按用户、route、table ID 和语言写入专用 localStorage 键，保存宽度、顺序、显隐和固定列。它不是业务数据，不写 SQLite、系统设置 API 或 Electron 配置。载入时必须以当前完整列定义为基准归一化：补齐新增列、删除旧列、去重并补齐顺序、强制不可隐藏列可见、清理非法宽度和固定状态；异步 Electron 偏好返回不得覆盖用户已经做出的修改。损坏偏好失败关闭为默认布局，不能阻止表格加载。结构变化后必须等待 DOM 更新并调用 Element Plus `doLayout()` 与宽度重算。

## 字段和操作列

字段类型宽度基线只在 `columnPresets.ts` 维护。状态 Tag、图标和操作按钮的实际 chrome 均计入宽度。操作列默认固定右侧，保留一到两个高频动作，其余进入“更多”；不能无限撑宽。

## 详情与表单

详情页同组标签使用一致且能完整显示的宽度，建议标签和值均左对齐；长值使用 Tooltip 或复制动作，路径不得撑破页面。表单标签必须计入必填标记和帮助图标，语言变化后重新布局。

## 增量迁移

阶段 1 的旧表进入 `table-layout-baseline.json` 并在清单标记 `BLOCKED`。新表不得使用直接 `el-table`；逐域迁移后删除对应基线记录。固定列例外必须精确到表格和列，包含原因、测试与到期日期，禁止页面级通配。

当前清单中的 77 张标准表格均已迁移为 `NcDataTable + NcTableColumn`，并自动继承可视区填充策略，旧表基线为空。后续新增表格必须在同一提交中接入公共组件、补充定向测试并更新 `TABLE_INVENTORY.md`；截图、DPI/缩放和人工验收仍是独立门禁。

`NcDataTable` 外层只负责 flex 尺寸约束并保持 `overflow: hidden`，不得与固定高度的 Element Plus 表格形成第二层 `overflow: auto/scroll`。根 `el-table` 宽度固定为 `100%`，列宽总和只通过 `el-table-column width` 进入 Element Plus 自身布局；纵向和横向滚动、固定表头及底部横向滚动条均由 Element Plus 的单一滚动平面管理。分页必须位于表格宿主之外。
