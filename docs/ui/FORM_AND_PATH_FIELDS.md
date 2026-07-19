# 表单与路径字段

系统设置中的可执行文件路径统一使用 `apps/web/src/components/settings/NcExecutablePathField.vue`。组件负责只读路径、选择、清空、可选试启动及字段级错误/成功反馈；页面只绑定值和语义动作。

布局必须使用“可收缩输入框 + 独立按钮组”：按钮组为 `inline-flex`，间距至少 6px，每个文字按钮最小宽度 64px，不使用绝对定位，也不把多个按钮堆入 input suffix/append。窄于 900px 时按钮组换到下一行并保持完整文字，错误反馈预留稳定高度。

路径选择和执行安全不属于 Vue。Renderer 不得传入 executable allowlist、任意扩展名、路径执行参数或命令；Electron Main 根据语义 `toolId` 选择固定过滤器，Python Service 保存和执行前再次验证真实文件。字段即时提示只能改善交互，不能替代后端校验。

新增“路径 + 选择/清空/试启动”字段时优先复用该组件，并补充组件、页面、Electron IPC 和 Python 校验的定向测试。DPI、缩放和真实窗口视觉项在人工验收前保持待验证，不能用源码断言代替人工结论。
