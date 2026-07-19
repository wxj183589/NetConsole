# 局点管理

局点 Registry 位于当前数据根的 `data/config/site_registry.json`，是局点列表的唯一事实源。每个记录有稳定 `site_id`、中文 `display_name`、相对路径、创建/更新时间和备注；显示名称不作为数据库主键。

新建流程为：校验 ID/名称、创建 staging、初始化必要数据库和默认设备组、写 `site_meta.json`、执行 SQLite `quick_check`、原子发布、注册 Registry。失败清理 staging，不改变当前局点。

切换前必须确认当前局点没有 `PENDING/STARTING/RUNNING/STOPPING` 任务。切换更新现有应用配置并返回 `restart_required=true`，Electron 随后重启 Backend，使所有 Service 使用同一 SiteContext；不会自动停止任务或连接设备。
