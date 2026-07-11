---
name: qfluentwidgets-netconsole-ui-skill
description: "QFluentWidgets、PySide6-Fluent-Widgets、Fluent Shell、AppFluentWindow、CommandBar、FluentIcon、InfoBar、Mica、Acrylic、主题切换或 qfluentwidgets fallback 任务时使用。普通 Qt 布局设计使用 qt6-polished-ui-skill，单点遮挡修复使用 qt6-ui-fix-skill；不用于业务采集、解析或数据库逻辑。"
---

# 目标

维护 NetConsole 的 QFluentWidgets 集成、主窗口 Shell、主题协调和 Fluent 公共组件，不扩展为通用页面布局 Skill。

# 触发与反例

触发示例：

- “修复 AppFluentWindow 的导航和标题区。”
- “统一 CommandBar、FluentIcon 和 InfoBar 的用法。”
- “主题切换后 QFluentWidgets 与项目 QSS 不一致。”

不应触发：

- “修复一个普通 QFormLayout 的字段遮挡。”
- “调整 H3C parser、SNMP 采集或 Excel 报告。”

# 输入与输出

- 输入：Shell/主题/Fluent 组件目标、受影响页面和必须保留的 fallback 行为。
- 输出：最小 Fluent 集成修改、主题/启动/降级验证与风险说明。
- 允许修改生产代码：允许，仅限 `netconsole/ui/` 的 Shell、主题、组件、设置入口和必要 i18n/Feature Registry；不修改业务服务或数据库。

# 开始前读取

- `README.md`、`docs/THIRD_PARTY_DEPENDENCIES.md`、`docs/DEVELOPMENT_RULES.md`。
- `netconsole/ui/app_fluent_window.py`、`netconsole/ui/app_window_factory.py`、`netconsole/ui/shell/fluent_bridge.py`。
- `netconsole/ui/components/`、`netconsole/ui/theme/`、`netconsole/ui/pages/settings_page.py`。

# 工作流程与约束

1. 确认当前依赖为 PySide6 与 `PySide6-Fluent-Widgets==1.11.2`，导入名为 `qfluentwidgets`。
2. 复用 `fluent_bridge.py`、现有 CommandBar/图标 helper 和统一主题入口；不在页面散落直接集成。
3. 保持 QFluentWidgets 导入失败时普通 Qt fallback 可启动；禁止使用 Pro 组件或混装 PyQt/PySide2 Fluent 包。
4. 默认不启用 Mica/Acrylic；特效失败或不支持时降级普通背景，不阻断启动。
5. 主题切换只刷新视觉，不重建主窗口、不清空日志、不停止任务；异常写日志并保持应用可用。
6. 按钮优先“图标 + 中文文字”，不创建无 parent 的顶级按钮；图标缺失必须 fallback。
7. 页面级操作留在对应页面/Tab/表格工具栏，Shell 只承载全局导航、局点和全局状态。

# 验证与失败报告

- 运行 `tests/test_fluent_integration.py` 和受影响窗口测试。
- 手工验证普通/Fluent fallback、浅色/深色、重复切换、启动、关闭和 1280/1920/2560 尺寸。
- 无法验证特定 Windows 特效时明确说明操作系统和视觉验证缺口。
- 输出修改文件、使用的免费版组件、fallback 状态、主题风险和业务影响。

# 相关 Skills

- 页面整体设计：`qt6-polished-ui-skill`。
- 具体遮挡/滚动缺陷：`qt6-ui-fix-skill`。
- UI 交互审查：`netconsole-qt6-ui-taste-skill`。
