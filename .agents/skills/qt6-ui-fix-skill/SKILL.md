---
name: qt6-ui-fix-skill
description: "Qt6、PySide6、QFluentWidgets 现有页面或弹窗出现遮挡、控件挤压、滚动缺失、Splitter 失衡、表格列不全、深色主题异常、信号失效或 UI 卡顿时使用。全新页面或系统性视觉重构使用 qt6-polished-ui-skill；不用于纯后端或 Excel 格式任务。"
---

# 目标

基于截图、控件树和现有代码定位 Qt6 UI 缺陷根因，以最小改动恢复可达性、响应性和主题可读性。

# 触发与反例

触发示例：

- “1080p 下参数和按钮被右侧窗口遮挡。”
- “弹出详情窗口缩小时底部按钮看不到。”
- “表格列显示不全，点击后页面还会卡住。”

不应触发：

- “新建一个完整的 SNMP 页面。”
- “只修复 Excel 列宽或 H3C 命令解析。”

# 输入与输出

- 输入：截图/复现步骤、目标页面、窗口尺寸、主题和预期行为。
- 输出：根因、最小修复、相关测试和可重复的手工验证步骤。
- 允许修改生产代码：允许，但仅限缺陷涉及的 UI、公共布局/主题 helper 和必要任务提交入口；不得改变数据结构或业务规则，除非用户明确要求。

# 开始前读取

- `docs/ui_table_guidelines.md`、`docs/ui_thread_policy.md`、`docs/ui_governance_guardrails.md`。
- 目标文件及 `src/netconsole/ui/pages/`、`src/netconsole/ui/dialogs/`、`src/netconsole/ui/widgets/`、`src/netconsole/ui/table/`。
- `src/netconsole/ui/table_utils.py`、`src/netconsole/ui/windowing.py`、`src/netconsole/ui/window_manager.py`、`src/netconsole/ui/theme/`。

# 工作流程

1. 复现并判断根因：固定尺寸、错误 stretch、size policy、Splitter 比例、缺少滚动、长文本、同步重任务或失效信号。
2. 先修复现有组件和布局，不重写整个页面，不用无限增大窗口最小尺寸掩盖问题。
3. 为页面、弹窗和弹出子页分别定义纵向与横向溢出策略；表格使用自身滚动条，长表单使用外层滚动区。
4. 若卡顿来自网络、磁盘、大查询、解析、压缩或导出，按 `docs/ARCHITECTURE.md` 转交 Job Center/Export Process，UI 只更新状态。
5. 保持信号连接、页面恢复、后台任务和日志状态；主题切换不得重建页面或中断任务。

# 强制规则

- 参数、按钮、ComboBox、单位标签和操作列不得重叠或截断；1280 宽度允许滚动，不允许挤压。
- 超出当前窗口的内容必须可上下滚动，超宽内容必须可左右滚动或通过 Splitter 调整；弹窗和子页同样适用。
- 弹窗设置合理 `minimumSize`/内容最小宽度，优先非模态；不得用固定尺寸裁剪底部按钮或右侧参数。
- 不需要上下微调按钮的 SpinBox 使用无滚轮/无按钮公共控件或普通输入框加 validator。
- 表格列宽可手动调整，不默认 Stretch 压缩；大数据不得一次性昂贵填表，不在每个单元格创建 QWidget。
- 分组切换后，依赖的设备、IP、地址、OID 下拉框必须清空并按新分组刷新。
- 深色主题下正文、边框、placeholder、禁用、选中和 hover 状态必须可读。

# 验证与失败报告

- 检查窗口缩放、1280 宽度、1920x1080、亮/暗主题、横纵滚动、Splitter、表格拖列宽、分组切换和弹窗关闭。
- 运行受影响页面测试；布局公共能力优先检查 `tests/test_windowing.py`、`tests/test_table_utils.py`。
- 无法完成真实桌面视觉检查时，说明仅做了静态/offscreen 验证及剩余风险。
- 输出根因、影响控件、修改文件、数据/导入导出影响和手工步骤。

# 相关 Skills

- 系统性页面设计：`qt6-polished-ui-skill`。
- QFluentWidgets 主题/Shell：`qfluentwidgets-netconsole-ui-skill`。
- 超过 300ms 的任务：`netconsole-job-center-skill`。
