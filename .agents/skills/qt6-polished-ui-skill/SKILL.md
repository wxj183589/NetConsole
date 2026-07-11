---
name: qt6-polished-ui-skill
description: "Qt6、PySide6、QFluentWidgets 页面新建或系统性视觉与布局优化时使用；覆盖 QSS、间距、字体、表单、表格、空状态、信息层级和窗口缩放。仅修复单个遮挡、滚动或卡顿缺陷时使用 qt6-ui-fix-skill；不用于纯后端、解析器或数据库任务。"
---

# 目标

让 NetConsole 的 Qt6 界面达到可长期使用的工业网络工具质量：信息清楚、控件不挤压、主题一致、状态完整，并复用现有 PySide6/QFluentWidgets 组件。

# 触发与反例

触发示例：

- “重新设计这个 Qt6 页面并统一 Fluent 风格。”
- “优化表单、工具栏、表格和空状态的整体层级。”
- “增加一个可缩放、亮暗主题可读的新页面。”

不应触发：

- “只修复 1080p 下一个输入框被遮挡。”
- “只调整 SNMP parser 或 SQLite schema。”

# 输入与输出

- 输入：目标页面、截图或交互目标，以及必须保留的业务行为。
- 输出：最小范围的 UI/公共组件修改、对应测试与手工验证步骤。
- 允许修改生产代码：允许，但只限相关 UI、主题、i18n、Feature Registry 和必要公共组件；不得顺手改业务规则或数据结构。

# 开始前读取

- `AGENTS.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_RULES.md`、`docs/ui_table_guidelines.md`。
- `netconsole/ui/app_fluent_window.py`、`netconsole/ui/app_window_factory.py`、`netconsole/ui/navigation.py`。
- `netconsole/ui/theme/`、`netconsole/ui/widgets/`、`netconsole/ui/table/`、`netconsole/ui/table_utils.py`。
- `netconsole/core/i18n.py`、`netconsole/core/feature_registry.py`。

# 工作流程

1. 确认项目实际为 Python 3.13、Qt6、PySide6、QFluentWidgets；禁止混用 PyQt6。
2. 读取现有页面、主题 token、公共组件和相关测试，列出必须保留的信号、状态和数据入口。
3. 先调整布局层级、stretch、size policy、Splitter 和滚动策略，再处理 QSS；不得用 QSS 强行修布局。
4. 复用既有组件；只有重复需求明确时才增加最小公共 helper。
5. 新用户可见页面、Tab、动作或按钮接入 `netconsole/core/feature_registry.py`；用户可见文本进入 `netconsole/core/i18n.py`。
6. 补足 empty、loading、error、success/cancelled 状态；按钮必须连接真实 slot。

# 项目约束

- 页面外边距通常 16～24 px，区块 12～16 px，表单行 8～12 px；不把多个参数横向塞满。
- 所有页面、弹窗、弹出模块和子页都不得被窗口硬挤压。内容超高时用 `QScrollArea` 或区域自身纵向滚动；内容超宽时用水平滚动、`QSplitter` 或分区，禁止压缩到重叠、截字或单位覆盖输入框。
- 复杂页面使用表单/网格、分组、Tab、折叠区或 Splitter；避免绝对定位和大量 `setFixedSize`。
- 1920x1080 和 2560x1440 应保持比例；1280 宽度可出现滚动条，但全部功能必须可达。
- 数字框和下拉框避免滚轮误改；不需要微调按钮时复用 `netconsole/ui/widgets/no_wheel.py` 或带 validator 的输入框。
- 表格支持手动调列宽和横向滚动；大表使用 Model/View、分页、懒加载或分批渲染，不给每个单元格创建 QWidget。
- 深色主题下正文、次要文字、边框、placeholder、禁用、hover、selected 可读；状态不能只靠颜色表达。
- 不删除中文字段，不新增重复页面，不用 Web hero、营销页或装饰性渐变替代工程工具布局。

# 验证与失败报告

- 自动验证相关页面测试，并优先运行 `tests/test_fluent_integration.py`、`tests/test_windowing.py`、`tests/test_table_utils.py` 中受影响用例。
- 手工检查 1280 宽度、1920x1080、2560x1440、窗口缩小、亮/暗主题、弹窗滚动、表格拖列宽和按钮 slot。
- 无法启动 GUI 或缺少目标截图时，不声称已完成分辨率适配；明确列出未验证窗口、主题和交互风险。
- 输出修改文件、主要视觉/交互变化、公共样式变化、业务/数据影响和验证证据。

# 相关 Skills

- 单点 UI 缺陷：`qt6-ui-fix-skill`。
- Fluent Shell/主题组件：`qfluentwidgets-netconsole-ui-skill`。
- UI 质量只读审查：`netconsole-qt6-ui-taste-skill`。
- UI 阻塞迁移：`netconsole-job-center-skill`。
