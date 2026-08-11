# UI 视觉测试

公共表格单元测试必须覆盖表头长于内容、内容长于表头、空数据、中英文、排序/筛选图标、状态 Tag、操作按钮、最大宽度、横向滚动、手工列宽和恢复自动宽度，并断言 `computedWidth >= headerRequiredWidth`。

阶段 7 使用固定 fixture、字体、窗口、语言和主题建立 Playwright 截图及 DOM 断言。当前 `apps/desktop_renderer/tests/visual` 已使用真实 `NcDataTable` 建立公共组件夹具，覆盖 1280×720、1920×1080、2560×1440 与 100%/125%/150% device scale factor；测试断言表头完整、默认内容居中、横向滚动可用，并把每次截图写入 `.local/tests/renderer-visual`。像素截图不能替代以下 DOM 事实：

- 表头未被裁剪或异常换行；
- 内容和表头按列定义对齐；
- 长内容具有 Tooltip；
- 横向滚动区域可用；
- 操作按钮完整且可聚焦；
- 页面卸载后无监听器或测量任务残留。

当前公共表格自动视觉矩阵已完成；设备管理、设备详情、FIT-AP、Online MR、任务中心、Traffic、Agent 和系统设置的真实页面截图基线，以及中/英文、浅/深主题组合仍为 `PENDING`。真实 Electron 人工验收继续作为独立门禁。
