# 系统设置页面

本目录展示系统设置、工具路径、局点和外观等用户配置。配置校验、文件写入和清理边界由 Python Service/PathResolver 管理，页面不直接操作磁盘。

`SiteStoragePanel.vue` 提供局点 Registry、数据根、迁移及完整迁移包/现场采集包/采集回传包入口。回传包先调用 Backend 预检，再显示增量、重复、冲突、删除请求与空间预估；Renderer 只提交用户选择的冲突策略，不能访问文件系统、修改 Electron bootstrap 或在页面执行复制、压缩、数据库写入。导入任务仅在 `COMPLETED` 后刷新局点列表、数量和 Electron 托盘事实源；提交、失败和刷新失败分别提示。托盘快速切换请求会回到此面板，和普通切换共用确认、预检、工作区快照、激活、受管 Backend 重启与失败恢复链路。

主要入口为 `SystemSettingsView.vue`；修改设置项时更新 Feature/i18n、API DTO 与测试，确认敏感配置不回显。

源码开发态的功能开关区域只管理当前实例的全局 `visible/enabled` 运行时覆盖。普通模式使用“显示并启用 / 隐藏入口 / 完全禁用”三状态，按 Registry 分组并在抽屉中预览直接修改、依赖联动、导航和任务入口影响。`client_package/internal_only` 是只读发布元数据，页面和更新 DTO 均不得修改；保存由 Python Application Service 原子写入应用数据根下的 `runtime/feature_flags.local.json`。正式包不显示该区域且拒绝相关 API。

工具程序路径统一使用 `components/settings/NcExecutablePathField.vue`。输入框与“选择 / 清空 / 试启动”位于独立网格列，窄窗口时按钮组换行；页面不得再把多个动作塞入 `el-input` append。终端文件名只用于即时交互提示，安全校验仍由 Electron Main 与 Python Service 的固定白名单执行。PuTTY 接受大小写不敏感的 `putty.exe` 和 `putty64.exe`。

主题和强调色只写入现有系统设置 API。页面预览通过 `settings/appearance.ts` 使用共享主题运行时，不得新增 Pinia/localStorage 主题副本；页面文字和边框消费语义 Token。
