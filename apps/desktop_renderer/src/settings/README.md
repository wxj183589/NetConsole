# Web 外观设置

本目录管理 Web 端主题/外观偏好与运行时绑定，负责把用户选择映射到统一 Token 和 Element Plus/ECharts 主题，不保存业务数据。

主要入口为 `appearance.ts`；测试覆盖持久化、默认值和主题同步。修改设置键或视觉语义时同步 `styles/`、`theme/` 和对应测试。
