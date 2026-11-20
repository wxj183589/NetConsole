# v1.5.17 功能复审矩阵

| 功能 | Renderer 入口 | API Router | Backend Service / Repository | 数据边界 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 设备管理/凭据 | `views/devices/*` | `device_management_router.py` | `device_management_web_service.py`, `device_repository.py` | devices.db、凭据存储 | PASS（定向契约） |
| Site 创建/切换/回收 | `SiteStoragePanel.vue`, site stores | `site_storage_router.py` | `site_lifecycle.py`, `site_storage.py` | Site Registry、site db | PASS（契约） |
| AC 管理 | `ac-management/*` | `ac_management_router.py` | `application/ac`, `ac_repository.py` | AC/MESH profile | PASS（静态/命令审计） |
| FIT-AP | `AcManagementView.vue`, Device detail | `ac_management_router.py` | `h3c_ac_collect_service.py`, AP identity services | AP inventory | PASS（静态；真实 V5 仍 PARTIAL） |
| Mesh-Link | `AcMeshLinkPage.vue`, `MeshAnalysisView.vue` | `ac_mesh_link_router.py`, `mesh_analysis_router.py` | mesh refresh/analysis services | raw/parsed MESH DB | PASS（契约） |
| Heartbeat | `HeartbeatPage.vue`, `HeartbeatSettings.vue` | `ground_unattended_router.py` | `heartbeat_supervisor.py`, heartbeat repositories | ground config/history | PASS（102 项定向测试） |
| Syslog | `SyslogPage.vue` | `ground_unattended_router.py` | `syslog_runtime.py`, raw lifecycle/position services | UDP raw、projection | PASS（定向；现场长稳仍 PARTIAL） |
| Quick Ping | `QuickPingPage.vue` | `ground_unattended_router.py` | `quick_ping.py`, task repository | tasks.db、历史事件 | PASS（静态/契约） |
| 深度采集 | `DeepCollectionPage.vue`, `DeepTasksPage.vue` | ground/task routers | deep scheduler/handlers | task center | PASS（静态） |
| ARP | Ground views | `ground_unattended_router.py` | `arp_collection.py`, `ground_arp_repository.py` | ARP snapshots | PASS（静态） |
| MR 综合监控 | `OnlineMrRealtimeView.vue`, `OnlineMrAnalysisView.vue` | `online_mr_router.py` | `online_mr_collector.py`, session services | MR raw/parsed DB | PASS（源码；真实 GUI 仍 PARTIAL） |
| 车站视图/基础资料 | `RailTransitBaseDataView.vue` | `rail_transit_base_data_router.py` | base data services/repositories | site base data | PASS（静态；完整站序仍 PARTIAL） |
| 轨旁 AP 业务 | `TracksideApBusinessView.vue` | `trackside_ap_business_router.py` | snapshot/export/identity services | AP snapshot revisions | PASS（契约） |
| WPS/Excel 导出 | `TracksideApWpsConfigDialog.vue` | `wps_sync_router.py` | WPS sync/export services | local xlsx only | PASS（边界审计） |
| 网络工具/Traffic | `NetworkToolsView.vue`, `TrafficTestView.vue` | `network_tools_router.py`, `traffic_router.py` | network tools/traffic services | isolated task output | PASS（静态） |
| 文件管理/诊断 | `FileManagementView.vue` | `file_management_router.py` | file management/diagnostic bundle | approved file roots | PASS（路径审计） |
| Config Collection | `ConfigCollectionView.vue` | `config_collection_router.py` | config collection handlers | task artifacts | PASS（Electron consumer） |
| Job Center/任务 | `JobCenterView.vue` | `job_center_router.py`, `task_router.py` | task application/query/cleanup | tasks.db/artifacts | PASS（静态） |
| 存储管理/审计 | `StorageManagementView.vue`, `SiteStoragePanel.vue` | storage/site/database routers | storage/audit/upgrade services | data-root marker | PASS（只读契约） |
| 报表/归档 | `ArchivePage.vue`, report components | relevant domain routers | export/report services | project report dirs | PASS（静态） |
| 系统设置/网络 | `SystemSettingsView.vue`, `SystemMaintenanceView.vue` | settings/maintenance routers | lifecycle/network/settings services | config files | PASS（契约） |
| Electron 生命周期 | Electron main/preload | IPC whitelist | `backend-manager.ts`, window/runtime services | isolated runtime root | PASS（静态/102 tests） |
| Installer/Portable | package scripts | N/A | PyInstaller + electron-builder | release/<version> | 待构建验证 |

`PASS` 表示源码/契约证据，不等于真实设备、GUI、Win10 或长稳验收通过。
