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
- `supervisor.py`：时间窗状态机、恢复、常驻 AC Poller 编排、调度和停止归档。
- `../ac/mesh_link_resident_polling_service.py`：每个 run/controller 唯一的 resident Task、受控控制/状态
  文件、单 Worker SSH 复用、间隔热更新、立即轮询、同 Task 重连和正常停止。
- `boot_config.py`、`syslog_runtime.py`：Information Center 只读核验、受控修复与 WMESH UDP 接收。
- `fleet_ping.py`、`timeline.py`：分片 Ping 生命周期、汇总和 AC/Ping 时间关联。
- `raw_query.py`：只读扫描与查询时间范围相交的已登记 Ping/Syslog NDJSON，执行有界内存分页、降采样和路径/链接安全校验。
- `deep_scheduler.py`：每日覆盖队列、置顶和并发预算。
- `archive_service.py`：manifest、ZIP 校验、原子发布和保留清理。

Profile 的 `deep_collection_master_enabled=false` 表示轻量监测模式：Supervisor 继续 AC、Fleet Ping、
Syslog 和位置关联，Deep Scheduler 只同步/收尾已有任务，不再填充新槽位。每个 Ping 目标的激活时间
持久化；默认前 10 秒仅写原始样本，不进入有效统计。

普通停止和停止并归档使用 `ground_unattended_operations` 持久化操作状态。Supervisor 停止新的深度
调度后先进入 `STOPPING_AC_POLLER`，请求每台 resident Worker 完成当前命令、关闭 SSH 并正常退出；
之后再核对深采、fping worker、UDP 线程、监听端口可重新绑定、接收队列和 OPEN 文件。AC Poller 超时
记录 controller/task/连接状态并有界强停，不伪装完成；归档通过回调更新准备、写入、校验、登记和清理
阶段。暂停深度调度不会停止 AC Poller、Fleet Ping 或 Syslog。

## 数据安全

运行数据位于 `data/sites/<site_id>/ground_unattended/`，路径由 `PathResolver` 解析。归档校验失败时保留 active 原始数据；删除归档必须经过当前局点校验、显式确认和 Repository 状态检查。自动测试只能使用 `RuntimeMode.TEST` 与 `D:\NetConsoleTestData\<run-id>`。

## 验证

优先运行 `tests/test_ground_unattended_*.py`、API/命令守卫定向测试，以及 Ruff、架构 Guard、Web 类型检查和生产构建。真实设备验证默认只读；任何配置写入都必须通过固定命令白名单和审计记录。

## 相关文档

- [地面无人值守](../../../../docs/GROUND_UNATTENDED.md)
- [数据布局](../../../../docs/DATA_LAYOUT.md)
- [Online MR](../../../../docs/ONLINE_MR_COLLECTION.md)
- [项目架构](../../../../docs/ARCHITECTURE.md)
