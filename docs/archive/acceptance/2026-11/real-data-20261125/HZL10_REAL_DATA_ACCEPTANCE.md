# HZL10 真实运行数据专项验收

状态：**PARTIAL**

本报告基于本地真实压缩包的解压、结构审计和只读查询证据。Electron GUI、Windows 安装态和设备现场回放未在本轮执行，相关项保持 NOT VERIFIED。

## 来源与规模

- 原始包 SHA-256：`D0EDA9908782FB96690802763E9B09C334D2889BDEC902B3790AC2C6A31A8A86`
- 隔离 DataRoot：`D:\study\NetConsole-Workspace\test-data\NetConsole\real-data-20261125-hzl10`
- 文件数量：24,249
- 解压后总大小：22.92 GiB

## SQLite 结构审计

### devices 数据库
- 相对路径：`sites/hzl10/db/devices.db`，大小：811.57 MiB
- 非空表：ac_ap_summary=1、ac_fit_ap_details=939、ac_fit_ap_lldp_history=62,792、ac_fit_ap_metadata=4、ac_fit_ap_optical=948、ac_fit_ap_optical_history=35,507、ac_fit_ap_radio_details=1,878、ac_fit_ap_radio_history=56,280、ac_fit_ap_resource_history=28,141、ac_fit_ap_resources=948、ac_fit_ap_unauthenticated_history=2,763、ac_fit_ap_unauthenticated_summary=1、ac_trackside_ap_plan=16、ac_trackside_ap_plan_settings=1、ap_entities=950、ap_extension_points=29、ap_identity_entities=979、ap_identity_index_state=1、ap_identity_mac_aliases=4,742、ap_identity_radio_evidence=1,896、ap_identity_source_state=1、ap_lldp_history=35,496、ap_optical_history=35,496、ap_optical_treatment=139、ap_optical_treatment_events=161、ap_resource_snapshots=28,141、collect_runs=5,818、device_credential_states=79、device_fact_recent=179、device_fact_retention_meta=2、device_facts=69、device_facts_history=935、device_groups=5、device_interface_retention_meta=1、device_interfaces=3,513、device_interfaces_history=105,958、device_lldp_neighbors=1,035、device_lldp_neighbors_history=9,725、device_lldp_retention_meta=1、device_optical_modules=2,506、device_optical_modules_history=104,858、device_optical_retention_meta=1、devices=76、fit_ap_lldp_current=948、fit_ap_lldp_history=1,585、fit_ap_lldp_retention_meta=1、fit_ap_radio_current=1,896、fit_ap_radio_history=18,199、fit_ap_radio_retention_meta=1、fit_ap_resource_recent=9,480、fit_ap_resource_retention_meta=2、fit_ap_unauthenticated_recent=112、fit_ap_unauthenticated_retention_meta=2、history_state=880、optical_current=1,896、optical_history=17,868、optical_retention_meta=1、rail_ap_vlan_group_members=15、rail_ap_vlan_groups=15、rail_ap_vlan_plans=1、schema_metadata=12、station_online_summary_retention_meta=1
### tasks 数据库
- 相对路径：`sites/hzl10/db/tasks.db`，大小：43.44 MiB
- 非空表：online_mr_task_session_schema=1、task_events=53,278、task_result_blobs=65、task_result_storage_rollout=1、task_results=65、task_schema_meta=1、task_snapshots=65
### ground 数据库
- 相对路径：`sites/hzl10/files/rail_transit/ground_unattended/index.sqlite`，大小：6029.30 MiB
- 非空表：ground_unattended_ac_basic_controls=3、ground_unattended_ac_deltas=366,572、ground_unattended_ac_snapshots=358,870、ground_unattended_archives=1、ground_unattended_boot_sessions=198、ground_unattended_events=616,103、ground_unattended_health_events=3,343、ground_unattended_heartbeat_config=1、ground_unattended_heartbeat_states=63、ground_unattended_mr_runtime_states=37、ground_unattended_operations=6、ground_unattended_ping_loss_intervals=372、ground_unattended_ping_summaries=562,861、ground_unattended_ping_target_activations=42、ground_unattended_position_reconciliations=694、ground_unattended_profiles=1、ground_unattended_raw_files=4,600、ground_unattended_run_sessions=6、ground_unattended_runs=6、ground_unattended_schema=5、ground_unattended_syslog_config_audits=2,873、ground_unattended_syslog_position_states=37、ground_unattended_train_endpoints=42、ground_unattended_train_inventory=21、ground_unattended_train_policies=21、ground_unattended_train_runs=126、ground_unattended_wmesh_events=297,397
### mr 数据库
- 相对路径：`sites/hzl10/files/rail_transit/online_mr/parsed/vehicle_mr_online.sqlite`，大小：487.02 MiB
- 非空表：vehicle_mr_online_links=1,999,008、vehicle_mr_online_sessions=4,393、vehicle_mr_online_snapshots=4,393、vehicle_mr_train_current_state=21、vehicle_mr_train_pass_events=47,913

## 业务覆盖判定

- Ground 无人值守：PASS_WITH_EVIDENCE_CAVEATS
- MESH/链路历史：PASS_WITH_EVIDENCE_CAVEATS
- AP/设备管理：PASS_WITH_EVIDENCE_CAVEATS（设备/AP 表存在非空记录，GUI 交互未执行）
- Quick Ping：NOT AVAILABLE（当前 Ground 表无 Quick Ping 记录）
- Syslog/任务中心：PASS_WITH_EVIDENCE_CAVEATS
- 冻结 Worker、真实 Windows 安装、性能冷启动：NOT VERIFIED

## 性能与查询证据

- 已完成解压和 SQLite 只读结构扫描。未启动 Electron/Backend，因此冷启动、页面首开、内存峰值和 CPU 峰值均为 NOT VERIFIED。
- devices SQLite schema 查询：76 个表对象，1.4 ms（只读）
- tasks SQLite schema 查询：11 个表对象，0.5 ms（只读）
- ground SQLite schema 查询：45 个表对象，0.8 ms（只读）
- mr SQLite schema 查询：7 个表对象，0.1 ms（只读）

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
