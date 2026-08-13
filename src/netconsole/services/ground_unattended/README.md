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
- `identity.py`：将历史列车/MR 别名、端位和管理 IP 解析为稳定 Ping 查询身份；`run_id + target_ip`
  唯一时不再被漂移的 MR UUID 排除，冲突和参数不一致返回稳定错误。
- `raw_query.py`：按运行/列车/MR/端位/时间预筛，流式查询 active 或 READY ZIP 中的 Ping/Syslog
  NDJSON；Syslog 无记录级筛选的首屏按最新文件优先读取，旧 WMESH 只对返回页或确实依赖解析字段的
  有界筛选执行 read-time parse。交互查询限制为 128 个文件、250,000 条、128MB 和 8 秒；单一
  ACTIVE/ARCHIVE 不建立全局去重集合，MIXED 使用 250,000 个稳定键的上限。
- `raw_deletion.py`、`raw_lifecycle.py`：删除预览/确认、Job Center 投递、文件生命周期锁、同目录
  `.part` 原子重写、Registry revision、派生 provenance 和删除审计；只允许已完成 run 的
  `CLOSED/RECOVERED/PENDING` Syslog，READY ZIP 永久不可变。
- `archive_reader.py`：READY ZIP 的受管路径、大小、SHA-256、manifest、成员哈希、CRC、路径和压缩预算
  校验；普通原始列表只做路径、READY、登记大小、ZIP/manifest/成员边界检查，并在读取目标成员时校验
  CRC，完整 ZIP 与成员 SHA-256 保留给详情和显式重新校验。只读流式访问登记成员，不解压或重写归档。
- `ap_resolver.py`：作为 `ApIdentityQueryService` 的薄适配器，按页/批次解析 distinct Peer、
  Radio/BSSID，缓存以 Identity revision 为失效边界；物理 AP MAC 不作为 Peer 证据，歧义保持未绑定，
  不读取或写入 AP Identity 内部表，也不维护第二套 Alias 索引。
- `deep_scheduler.py`：每日覆盖队列、置顶和并发预算；按 CT/CW 管理 IP 构造强制 Online MR
  `FpingConfig`，由共享 `FpingV5ProbeRunner` 进入运行态后才继续 SSH 深采。
- `archive_service.py`：manifest、ZIP 校验、原子发布和保留清理。

Profile 的 `deep_collection_master_enabled=false` 表示轻量监测模式：Supervisor 继续 AC、Fleet Ping、
Syslog 和位置关联，Deep Scheduler 只同步/收尾已有任务，不再填充新槽位。每个 Ping 目标的激活时间
持久化；默认前 10 秒仅写原始样本，不进入有效统计。

普通停止和停止并归档使用 `ground_unattended_operations` 持久化操作状态。Supervisor 停止新的深度
调度后先进入 `STOPPING_AC_POLLER`，请求每台 resident Worker 完成当前命令、关闭 SSH 并正常退出；
之后再核对深采、fping worker、UDP 线程、监听端口可重新绑定、接收队列和 OPEN 文件。AC Poller 超时
记录 controller/task/连接状态并有界强停，不伪装完成；归档通过回调更新准备、写入、校验、登记和清理
阶段。暂停深度调度不会停止 AC Poller、Fleet Ping 或 Syslog。

`/status` 不回退最近一次已完成运行；活动运行、最近运行、活动操作和最近终态操作独立映射。页面统一
使用 `selectedRunId` 查看 Ping、Syslog、时间轴和深度采集。当前运行默认最近 30 分钟，历史运行默认
实际起止时间；active 文件已清理时可从 READY ZIP 读取，混合来源按稳定记录标识去重。Syslog API
只投影公开 DTO 字段，不下发 `raw_bytes_base64`、内部局点或设备数据库标识；每次请求记录
`GROUND_SYSLOG_QUERY_STARTED/COMPLETED/FAILED` 并通过响应头或错误详情返回 `request_id`。

## 数据安全

运行数据位于 `data/sites/<site_id>/ground_unattended/`，路径由 `PathResolver` 解析。归档校验失败时保留 active 原始数据；删除归档必须经过当前局点校验、显式确认和 Repository 状态检查。运行历史删除只移除历史 run 索引及其关联查询数据，不会自动删除历史归档 ZIP；记录级 Syslog 删除只能使用 opaque file/sequence/line 身份，Vue 与 Router 不接触物理路径、文件 API 或 SQL；锁、revision、文件哈希和 SQLite 派生清理由生命周期服务与 Repository 协作完成。自动测试只能使用 `RuntimeMode.TEST` 与 `D:\NetConsoleTestData\<run-id>`。

## 验证

优先运行 `tests/test_ground_unattended_*.py`、API/命令守卫定向测试，以及 Ruff、架构 Guard、Web 类型检查和生产构建。真实设备验证默认只读；任何配置写入都必须通过固定命令白名单和审计记录。

## 相关文档

- [地面无人值守](../../../../docs/rail-transit/ground-unattended/README.md)
- [地面无人值守](../../../../docs/rail-transit/ground-unattended/README.md)
- [数据布局](../../../../docs/storage/DATA_LAYOUT.md)
- [Online MR](../../../../docs/rail-transit/online-mr/README.md)
- [项目架构](../../../../docs/ARCHITECTURE.md)
