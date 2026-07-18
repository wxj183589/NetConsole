# 网络工具组件

本目录提供网络工具箱、无线扫描、TCP 端口测试和下载交互组件。组件只绑定 API/Store 状态和用户输入，不自行启动进程或写运行数据。

主要入口为 `NetworkToolboxPanel.vue`、`TcpPortTestPanel.vue` 与 `WirelessScanPanel.vue`；流量能力另由 `traffic/` 组件承载。修改后运行相关 Web 测试。
