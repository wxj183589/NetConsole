---
name: netconsole-qt6-ui-taste-skill
description: "NetConsole Qt6/PySide6/QFluentWidgets 界面审查、Taste、Impeccable、anti-slop、按钮归属、重复/无效按钮、empty/loading/error/success 状态、信息密度和工业工具可用性评估时使用。默认用于 UI 质量审查，不替代页面实现或单点布局修复，也不用于纯后端评审。"
---

# 目标

把前端审美审查思路转换为 NetConsole 工业网络工具的可执行 UI 审核，优先发现“看起来存在但不可用”、操作归属错误、状态缺失和信息层级混乱。

# 触发与反例

触发示例：

- “按 Taste/Impeccable 思路审查这个 Qt 页面。”
- “检查重复按钮、无效 slot 和状态缺失。”
- “评估这个网络工具页面是否像可长期使用的桌面软件。”

不应触发：

- “直接新建一个完整 Qt 页面。”
- “评审数据库迁移或 H3C parser。”

# 输入与输出

- 输入：截图、目标页面/弹窗、关键工作流和用户角色。
- 输出：按严重程度排列的 UI 发现、证据位置、影响和建议方向；默认不自动修复。
- 允许修改生产代码：默认不允许；用户明确要求同时修复时，按 `qt6-polished-ui-skill` 或 `qt6-ui-fix-skill` 的边界实施。

# 开始前读取

- 目标页面、相关弹窗和控件 helper。
- `docs/ui_table_guidelines.md`、`docs/ui_thread_policy.md`、`docs/DEVELOPMENT_RULES.md`。
- 涉及 Fluent 时读取 `netconsole/ui/shell/fluent_bridge.py`、`netconsole/ui/theme/`、`netconsole/ui/components/`。

# 审查流程

1. 确认操作归属：全局、页面、Tab、表格或行级；识别重复、错位和无效按钮。
2. 检查 empty、loading、error、success、cancelled 状态及重复提交保护。
3. 检查内容溢出、弹窗/子页滚动、表格可读性、最小窗口和亮暗主题。
4. 检查大日志、大表、解析和导出是否阻塞 UI；按钮是否连接真实 slot 并反馈错误。
5. 检查危险操作确认、日志/目录入口、Feature Registry 和 i18n。

# 审美边界

- NetConsole 是工业网络设备采集工具，不做 Web hero、SaaS 营销页、无意义卡片、装饰性渐变或大面积留白。
- 功能可用性、信息密度、状态解释、采集稳定性和日志可追溯性优先。
- 页面/弹窗内容超出窗口必须可纵向和必要的横向滚动；不得用缩字、裁剪中文或隐藏字段换取整齐。
- 本地 XLSX 只审查列宽、冻结、筛选和文本格式体验，不引入 WPS 云服务/API/KDocs。

# 验证与失败报告

- 有截图时注明分辨率和可见证据；有代码时给出文件位置和可复现条件。
- 没有真实运行或点击验证时，不断言按钮有效、主题完整或所有分辨率已适配。
- 输出 Findings、Questions/Assumptions、Verification Gaps 和简短 Summary。

# 相关 Skills

- 实施系统性优化：`qt6-polished-ui-skill`。
- 实施单点修复：`qt6-ui-fix-skill`。
- 项目级跨领域评审：`netconsole-change-review-skill`。
