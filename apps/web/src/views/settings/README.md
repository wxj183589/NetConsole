# 系统设置页面

本目录展示系统设置、工具路径、局点和外观等用户配置。配置校验、文件写入和清理边界由 Python Service/PathResolver 管理，页面不直接操作磁盘。

`SiteStoragePanel.vue` 提供局点 Registry、数据根、迁移和 `.ncsite` 导入导出入口。Renderer 只调用 `/api/v1` 和专用 Platform Adapter；不能直接访问文件系统、修改 Electron bootstrap 或在页面执行复制/压缩。

主要入口为 `SystemSettingsView.vue`；修改设置项时更新 Feature/i18n、API DTO 与测试，确认敏感配置不回显。

主题和强调色只写入现有系统设置 API。页面预览通过 `settings/appearance.ts` 使用共享主题运行时，不得新增 Pinia/localStorage 主题副本；页面文字和边框消费语义 Token。
