# Infrastructure 适配层

本目录提供 Core 与外部宿主/进程之间的基础设施适配，当前重点是 Desktop 本地进程适配器。它不承载业务规则、Router 或 Vue 页面。

主要子目录为 `desktop/`；修改可用性、进程边界或异常映射时运行依赖层、LocalProcessAdapter 和 Electron/Job 相关测试。
