# 系统设置页面

本目录展示系统设置、工具路径、局点和外观等用户配置。配置校验、文件写入和清理边界由 Python Service/PathResolver 管理，页面不直接操作磁盘。

主要入口为 `SystemSettingsView.vue`；修改设置项时更新 Feature/i18n、API DTO 与测试，确认敏感配置不回显。
