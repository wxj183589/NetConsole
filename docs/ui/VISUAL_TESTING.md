# UI 视觉测试

公共表格单元测试必须覆盖表头长于内容、内容长于表头、空数据、中英文、排序/筛选图标、状态 Tag、操作按钮、最大宽度、横向滚动、手工列宽和恢复自动宽度，并断言 `computedWidth >= headerRequiredWidth`。

阶段 7 使用固定 fixture、字体、窗口、语言和主题建立 Playwright 截图及 DOM 断言。当前 `apps/desktop_renderer/tests/visual` 已使用真实 `NcDataTable` 建立公共组件夹具，覆盖 1280×720、1920×1080、2560×1440 与 100%/125%/150% device scale factor；测试断言表头完整、默认内容居中、横向滚动可用，并把每次截图写入 `.local/tests/renderer-visual`。像素截图不能替代以下 DOM 事实：

- 表头未被裁剪或异常换行；
- 内容和表头按列定义对齐；
- 长内容具有 Tooltip；
- 横向滚动区域可用；
- 操作按钮完整且可聚焦；
- 页面卸载后无监听器或测量任务残留。

当前公共表格自动视觉矩阵已完成。P5 工程化矩阵使用固定 `VisualMatrixFixture` 和 7 个推荐组合：1280×720@100% zh-CN light、1280×720@150% zh-CN dark、1920×1080@100% zh-CN light、1920×1080@125% en dark、1920×1080@150% zh-CN light、2560×1440@100% en light、2560×1440@150% en dark；覆盖 Dashboard、Device Management、Device Detail、FIT-AP、Trackside AP Business、Online MR、Job Center、Traffic、Agent、Settings。每个组合执行核心页面/无溢出、`NcDataTable`/操作/上下文菜单/Drawer/Dialog、语言主题切换与重排、稳定截图 4 类场景，共 28 项；矩阵重复 3 轮且 `FLAKE_COUNT=0`。

P5 的断言优先于截图：验证页面和导航可见、表头/行/操作按钮、表格滚动区域、菜单边界、弹层 footer 可达、ECharts 有效尺寸、语言/主题属性及窗口重排。DSF 由 Playwright Chromium `deviceScaleFactor=1/1.25/1.5` 实现，固定 CSS viewport；这不是 Windows 系统显示缩放或真实 Electron 人工验收的替代。既有 54 项公共视觉回归与新增 28 项矩阵均通过，截图写入 `.local/tests/renderer-visual`，不提交黄金截图。

`MANUAL_GUI_ACCEPTANCE=PASS` 与自动化 P5 矩阵是不同门禁；真实 Electron 人工页面截图基线仍按独立验收维度维护，不把自动化 fixture 结果升级为真实设备、Production 或安装器验收。
