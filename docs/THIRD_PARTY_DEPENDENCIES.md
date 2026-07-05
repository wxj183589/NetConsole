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
