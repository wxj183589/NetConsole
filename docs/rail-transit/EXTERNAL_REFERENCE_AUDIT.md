# 外部引用审计矩阵

审计依据为源码、Schema、现有 Repository/Query 和隔离夹具；不扫描真实业务数据。VERIFIED 表示指定的可执行查询范围，NOT_VERIFIED 表示完整领域仍缺证据；不能把列无命中视为没有引用。

| 领域 | 查询入口/结构 | 类型 | 当前/历史 | 状态与删除影响 |
| --- | --- | --- | --- | --- |
| 设备身份/凭据 | devices、device_credential_states；DeviceRepository | UUID/numeric id，MAC；SN 在事实表 | 当前/历史凭据状态 | 精确 UUID 查询 VERIFIED；MAC/SN/密钥/终端连接别名完整性 NOT_VERIFIED，拒绝 |
| 设备采集/接口/光模块/LLDP | device_fact_recent、device_details、接口/光模块/LLDP current/history；device_detail Query | device_uuid/device_id | 两者 | Site 实际存在表精确列 VERIFIED；旧名称/JSON 部分 NOT_VERIFIED |
| 任务/队列/导出 | site_tasks_db_path、TaskRepository、Job Center、artifact paths | UUID/id、JSON parameters、文件引用 | 两者 | 精确列 VERIFIED；JSON/任务引用及 Artifact 文件索引完整性 NOT_VERIFIED |
| AC/FIT-AP | ac_fit_ap_resources/details/optical/resource_history 等、AcRepository | ac_device_uuid/ap_uuid | 两者 | Site 精确列 VERIFIED；AP uuid、MAC、主备别名完整性 NOT_VERIFIED；不合并 Current |
| AP Identity | ap_identity_entities/mac_aliases/conflicts/radio evidence | ac_device_uuid、MAC/entity_id | 两者 | 精确 AC 引用 VERIFIED；MAC 归并链完整性 NOT_VERIFIED |
| 轨旁 AP/规划/光衰 | ap_extension_points、ac_trackside_ap_plan、optical_current/history、Trackside snapshot | point/station/section/AP UUID/端口/MAC | 两者 | 精确设备列 VERIFIED；规划和间接身份链 NOT_VERIFIED |
| 工程/列车 MR | rail_infra_device_link/device_section/device_project/ac_service/train_mr/history/audit/state | UUID/stable node/relation IDs | 两者 | 当前/历史关系查询 VERIFIED；Site 扫描补充旧 MR ended rows；保留 FK/history保护 |
| Ground/PositionEngine | ground index.sqlite、inventory/endpoints、heartbeat/syslog/position/ping、active/archive | UUID/id、AP MAC、JSON及NDJSON | 两者 | 精确列 VERIFIED；压缩归档、轮转段和 MAC 位置映射 NOT_VERIFIED |
| MESH | mesh catalog.sqlite、mr_profiles/sessions、MR parsed/raw/exports | mr_device_id、旧名字、MAC、路径 | 历史为主 | catalog 精确列 VERIFIED；per-MR 解析库/raw/link/report 完整性 NOT_VERIFIED |
| Online MR | online_mr/<MR>/sessions/session_meta.json、parsed/raw/outputs | device_uuid/device_id、MR名称 | 两者 | 有界元数据命中可见；归档包/旧目录/重复命名仍 NOT_VERIFIED |
| 历史报告/Excel/文件索引 | export artifacts、配置/文件下载、MESH/Online outputs、backups | 文件/ZIP/JSON/CSV/XLSX | 历史 | NOT_VERIFIED，不读报告内容、不清理，禁止删除 |
| Host Key/终端/SFTP/Traffic/工具 | host_key records/history、terminal sessions、traffic runs | host/IP/id、路径、JSON | 两者 | 非 UUID identity 链 NOT_VERIFIED，不把IP等同UUID |
| 未登记或将来来源 | 非标准旧表、文件、离线制品、缓存 | 任意 | 未知 | NOT_VERIFIED，默认拒绝 |

## 删除路径与级联

DeviceManagementView 的行/批量删除 → api/deviceManagement.ts → delete-confirmation/batch-delete → DeviceManagementWebService → DeviceRepository。设备详情没有独立删除 SQL。legacy_tasks 的 device_crud(action=delete) 直接调用 Repository，属于已确认的 Service 绕过路径，现由 Repository 固定拒绝。

全源码搜索的 devices 物理 DELETE 原仅两处，均已移除。分组删除仅 UPDATE group_id=NULL；CSV confirm_import 经 Job 使用 create/update，未发现先删资产再覆盖。基础资料站点/区间删除只操作正式点位及关联，并有工程引用检查；工程解除不删资产。

AC 的 /fit-aps/delete → AcWebApplicationService.start_fit_ap_delete → ac_fit_ap_delete_many：独立受控设备配置/运行资源能力，按选定 AC 校验 AP；不是 devices 删除。未执行该操作，也不把其授权继承给资产。

Schema 中 CASCADE 在 AP Identity 子证据、VLAN group、task events、MESH sample/source/profile、Traffic、HostKey 等子域。不存在从 devices 到全部这些历史域的完整 FK 图；因此不能依赖 FK 证明删除安全。SiteStorage 首次 demo 初始化失败回收需要本轮 ownership marker；局点/文件/日志删除属于其他独立授权范围，本次不调用或改写。

## 保留边界

本轮修复所有产品设备物理删除 Repository 入口，但不声称能限制用户直接 SQLite 或外部维护工具。外部历史证据完整删除许可仍 NOT_VERIFIED，can_delete 恒 false。发现当前关系/历史/外部匹配为 BLOCKED；查询异常、超时、缺失库/索引同样拒绝。
