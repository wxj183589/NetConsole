# 局点管理

局点 Registry 位于当前数据根的 `data/config/site_registry.json`，是局点列表的唯一事实源。每个记录有稳定 `site_id`、中文 `display_name`、相对路径、创建/更新时间和备注；显示名称不作为数据库主键。

首次启动或 Registry 缺少历史记录时，系统只扫描受控的 `data/sites/<目录>/db/devices.db`，以无覆盖、幂等方式补登记既有局点。符合稳定 ID 规则的目录沿用目录名；中文或其他历史目录生成 `legacy-<稳定哈希>` 作为内部 `site_id`，原目录名保留为相对路径和 Backend 的实际存储名称，`site_meta.json` 中的 `display_name` 优先用于显示。没有主数据库、路径越界、符号链接或损坏 Registry 的目录不会被自动登记，也不会被删除、重命名或初始化。

Electron 重启传递稳定 `site_id`，Backend 启动时先通过 Registry 解析到实际目录名；所有 Repository、任务和历史数据继续使用原局点目录。这样局点 ID 与 Windows/中文目录名可以安全分离。

新建流程为：校验 ID/名称、创建 staging、初始化必要数据库和默认设备组、写 `site_meta.json`、执行 SQLite `quick_check`、原子发布、注册 Registry。失败清理 staging，不改变当前局点。

切换前必须确认当前局点没有 `PENDING/STARTING/RUNNING/STOPPING` 任务。切换更新现有应用配置并返回 `restart_required=true`，Electron 随后重启 Backend，使所有 Service 使用同一 SiteContext；不会自动停止任务或连接设备。
