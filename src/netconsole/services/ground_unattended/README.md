# 地面无人值守服务

## 用途

本目录实现轨道交通地面无人值守的应用编排与后台生命周期，包括运行时间窗、列车库存、正线资格、AC/Syslog 状态、Fleet Ping、深度采集调度、时间轴和每日归档。

## 边界

- FastAPI Router 只调用 `GroundUnattendedApplicationService`，不直接读取局点配置、SQLite 或运行目录。
- Supervisor 独立于 Vue 页面生命周期，由 FastAPI lifespan 启停；页面隐藏或关闭不停止后台任务。
- AC、Online MR、fping 和轨道交通基础资料复用现有 Service/Repository，不在本目录复制第二套设备采集实现。
- 所有局点数据通过 `PathResolver` 和 `GroundUnattendedRepository` 隔离；原始 Syslog/Ping 文件不写入长期主 SQLite。

## 主要入口

- `application_service.py`：API 用例边界、DTO 映射和当前局点约束。
- `supervisor.py`：时间窗状态机、恢复、调度和停止归档。
- `boot_config.py`、`syslog_runtime.py`：Information Center 只读核验、受控修复与 WMESH UDP 接收。
- `fleet_ping.py`、`timeline.py`：分片 Ping 生命周期、汇总和 AC/Ping 时间关联。
- `deep_scheduler.py`：每日覆盖队列、置顶和并发预算。
- `archive_service.py`：manifest、ZIP 校验、原子发布和保留清理。

## 数据安全

运行数据位于 `data/sites/<site_id>/ground_unattended/`，路径由 `PathResolver` 解析。归档校验失败时保留 active 原始数据；删除归档必须经过当前局点校验、显式确认和 Repository 状态检查。自动测试只能使用 `RuntimeMode.TEST` 与 `D:\NetConsoleTestData\<run-id>`。

## 验证

优先运行 `tests/test_ground_unattended_*.py`、API/命令守卫定向测试，以及 Ruff、架构 Guard、Web 类型检查和生产构建。真实设备验证默认只读；任何配置写入都必须通过固定命令白名单和审计记录。

## 相关文档

- [地面无人值守](../../../../docs/GROUND_UNATTENDED.md)
- [数据布局](../../../../docs/DATA_LAYOUT.md)
- [Online MR](../../../../docs/ONLINE_MR_COLLECTION.md)
- [项目架构](../../../../docs/ARCHITECTURE.md)
