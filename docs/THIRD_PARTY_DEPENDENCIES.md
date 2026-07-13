# 第三方依赖说明

本文记录 NetConsole 当前需要重点关注的第三方依赖、授权和打包边界。

## QFluentWidgets

- 依赖包：`PySide6-Fluent-Widgets==1.11.2`
- 导入包名：`qfluentwidgets`
- 授权：GPLv3
- 项目用途：非商业项目按 GPLv3 使用免费版，不使用 Pro 组件。
- 商业风险：商业用途需要购买 QFluentWidgets 商业授权。

当前项目是 PySide6 / Qt Widgets 应用，因此只允许安装 `PySide6-Fluent-Widgets`。禁止同时安装以下包，因为它们的导入包名都为 `qfluentwidgets`，混装会导致运行期导入不确定：

- `PyQt-Fluent-Widgets`
- `PyQt6-Fluent-Widgets`
- `PySide2-Fluent-Widgets`
- `PySide6-Fluent-Widgets`

## QFluentWidgets 传递依赖

`PySide6-Fluent-Widgets==1.11.2` 当前会引入：

- `PySideSix-Frameless-Window>=0.8.0`：LGPLv3，用于无边框窗口底层能力。
- `darkdetect`：BSD-3-Clause，用于系统主题检测。
- `pywin32`：PSF，Windows 平台能力。

项目默认不启用 Mica / Acrylic / 毛玻璃效果。窗口特效必须是可选开关；低版本 Windows、Windows Server、Linux 或特效初始化失败时必须自动降级为普通背景，不能影响软件启动。

## 打包注意事项

- 发布包必须包含 `qfluentwidgets` 包资源、图标、QSS 和 PySide6 插件。
- 不使用 QFluentWidgets Pro 组件。
- 若 `qfluentwidgets` 导入失败，主窗口必须 fallback 到普通 Qt 窗口壳，不能阻断启动。
- 运行依赖检查应避免把 PyQt/PyQt6/PySide2 版本的 Fluent Widgets 与 PySide6 版本一同打入发布包。

## Excel 导出

- `openpyxl`：继续用于既有 Excel 导入、普通报表和测试读取。
- `xlsxwriter`：用于 10 万行级别大表高速 `.xlsx` 导出，启用 `constant_memory` 以降低内存占用，并配合独立导出进程避免抢占 Qt 主 UI 进程。

本地 `.xlsx` 导出只面向 WPS Office / Microsoft Office 可打开的文件格式，不引入 WPS 云、KDocs 或在线文档同步能力。

## Agent 运行工具

- `fping` 和 `iperf3` 的版本化源码唯一位于 `resources/tools/`，Agent 交付包内才复制到 `tools/windows-x64/`。
- fping 目录保留来源和许可证说明；当前 iPerf3 Windows x64 Cygwin 目录仍缺少可核验的上游许可证/NOTICE 材料。
- 正式对外分发前必须人工确认来源、版本、许可证、NOTICE 和同目录 DLL；构建脚本的文件存在性检查和 IPOP 排除不等同于法律授权确认。
- 未补齐材料前不得新增或替换来源不明的 iPerf3/Cygwin 二进制。IPOP 仍是用户自备的桌面端可选外部工具，不属于 Agent 依赖。

## IPOP v4.1

- 分类：用户自行提供的可选外部工具，不属于 NetConsole 内置工具或开源依赖。
- 配置：在“系统设置 → 外部工具”选择本机 `IPOP.EXE`；未配置时可检查用户手动放置的 `tools/windows-x64/ipop/IPOP.EXE`。
- 授权状态：仓库没有可核验的许可证或再分发授权，不声明 IPOP 属于 MIT、GPL 或 NetConsole 的授权范围。
- 发布策略：PyInstaller、Nuitka、内部版、客户版和工程师版均不携带 `IPOP.EXE` 或 `tools/windows-x64/ipop` 目录。
- 完整说明：[IPOP_v4.1_notice.md](IPOP_v4.1_notice.md)。
