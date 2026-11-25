# HZL9 真实运行数据专项验收

状态：**PARTIAL**

本报告基于本地真实压缩包的解压、结构审计和只读查询证据。Electron GUI、Windows 安装态和设备现场回放未在本轮执行，相关项保持 NOT VERIFIED。

## 来源与规模

- 原始包 SHA-256：`E357A07B28E62463BFDF913C30AE8F3E58B194D5594FCA6326F6DD5D29F90133`
- 隔离 DataRoot：`D:\study\NetConsole-Workspace\test-data\NetConsole\real-data-20261125-hz9\NetConsoleData`
- 文件数量：521
- 解压后总大小：0.57 GiB

## SQLite 结构审计

### devices 数据库
- 相对路径：`sites/hzdt-09/db/devices.db`，大小：64.39 MiB
- 非空表：ac_ap_summary=1、ac_fit_ap_optical=189、ac_fit_ap_resources=189、ac_fit_ap_unauthenticated_summary=1、ac_trackside_ap_plan=7、ap_entities=189、ap_extension_points=509、ap_identity_entities=698、ap_identity_index_state=1、ap_identity_mac_aliases=2,371、ap_identity_radio_evidence=378、ap_identity_source_state=1、ap_optical_treatment=83、ap_optical_treatment_events=88、collect_runs=339、device_credential_states=118、device_fact_recent=11、device_fact_retention_meta=2、device_facts=10、device_groups=5、device_interface_retention_meta=1、device_interfaces=1,076、device_interfaces_history=2,512、device_lldp_neighbors=251、device_lldp_neighbors_history=783、device_lldp_retention_meta=1、device_optical_modules=625、device_optical_modules_history=4,347、device_optical_retention_meta=1、devices=117、fit_ap_lldp_current=189、fit_ap_lldp_history=341、fit_ap_lldp_retention_meta=1、fit_ap_radio_current=378、fit_ap_radio_history=3,639、fit_ap_radio_retention_meta=1、fit_ap_resource_recent=1,890、fit_ap_resource_retention_meta=2、fit_ap_unauthenticated_recent=25、fit_ap_unauthenticated_retention_meta=2、optical_current=378、optical_history=3,091、optical_retention_meta=1、schema_metadata=11、station_online_summary_retention_meta=1
### tasks 数据库
- 相对路径：`sites/hzdt-09/db/tasks.db`，大小：0.88 MiB
- 非空表：online_mr_task_session_schema=1、task_events=918、task_result_blobs=2、task_result_storage_rollout=1、task_results=2、task_retention_tombstones=9、task_schema_meta=1、task_snapshots=2
### ground 数据库
- 相对路径：`sites/hzdt-09/files/rail_transit/ground_unattended/index.sqlite`，大小：125.20 MiB
- 非空表：ground_arp_collections=1、ground_arp_observations=139、ground_mr_identity_relations=6、ground_unattended_ac_basic_controls=3、ground_unattended_ac_deltas=2,535、ground_unattended_ac_snapshots=2,304、ground_unattended_archives=1、ground_unattended_boot_sessions=5、ground_unattended_events=80,489、ground_unattended_health_events=25、ground_unattended_heartbeat_config=1、ground_unattended_heartbeat_inventory_state=1、ground_unattended_heartbeat_states=30、ground_unattended_mr_runtime_states=3、ground_unattended_operations=1、ground_unattended_ping_loss_intervals=9,449、ground_unattended_ping_summaries=15,485、ground_unattended_ping_target_activations=40、ground_unattended_position_reconciliations=83、ground_unattended_profiles=1、ground_unattended_quick_ping_events=22、ground_unattended_quick_ping_runs=2、ground_unattended_quick_ping_stats=10、ground_unattended_quick_ping_target_runtime=8、ground_unattended_raw_files=77、ground_unattended_run_sessions=1、ground_unattended_runs=1、ground_unattended_schema=5、ground_unattended_syslog_config_audits=20、ground_unattended_syslog_position_states=4、ground_unattended_train_endpoints=20、ground_unattended_train_inventory=10、ground_unattended_train_policies=10、ground_unattended_train_runs=10、ground_unattended_wmesh_events=6,818
### mr 数据库
- 相对路径：`sites/hzdt-09/files/rail_transit/online_mr/parsed/vehicle_mr_online.sqlite`，大小：0.61 MiB
- 非空表：vehicle_mr_online_links=2,315、vehicle_mr_online_sessions=74、vehicle_mr_online_snapshots=74、vehicle_mr_train_current_state=10、vehicle_mr_train_pass_events=98

## 业务覆盖判定

- Ground 无人值守：PASS_WITH_EVIDENCE_CAVEATS
- MESH/链路历史：PASS_WITH_EVIDENCE_CAVEATS
- AP/设备管理：PASS_WITH_EVIDENCE_CAVEATS（设备/AP 表存在非空记录，GUI 交互未执行）
- Quick Ping：PASS_WITH_EVIDENCE_CAVEATS（HZL9 有历史记录）
- Syslog/任务中心：PASS_WITH_EVIDENCE_CAVEATS
- 冻结 Worker、真实 Windows 安装、性能冷启动：NOT VERIFIED

## 性能与查询证据

- 已完成解压和 SQLite 只读结构扫描。未启动 Electron/Backend，因此冷启动、页面首开、内存峰值和 CPU 峰值均为 NOT VERIFIED。
- devices SQLite schema 查询：74 个表对象，1.5 ms（只读）
- tasks SQLite schema 查询：11 个表对象，0.7 ms（只读）
- ground SQLite schema 查询：45 个表对象，1.0 ms（只读）
- mr SQLite schema 查询：7 个表对象，0.2 ms（只读）

## 兼容性结论

- 已识别标准 `NetConsoleData` 目录结构及当前项目数据库命名。
- 本轮未对原始数据库执行迁移，未验证写入式迁移和回滚。
- 若用于产品回放，应继续使用该隔离 DataRoot，并在副本上执行迁移演练。

## 数据安全边界

- 原始压缩包仅作校验和解压输入，SHA-256 已记录，未修改或删除。
- 数据解压到 Workspace 下的独立运行目录。
- 未连接 `D:\NetConsoleData` 或 `D:\NetConsoleData-dev`，未修改生产或真实开发数据库。
- SQLite 审计使用只读 URI 和 `PRAGMA query_only=ON`。
- 真实数据文件、数据库和解压目录不纳入 Git。
