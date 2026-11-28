# 旧版桌面产品实现清单

基线 `7d423a73`。以下索引取自受 Git 管理的实现。API 列出 Router 内声明的相对端点，完整 URL 还需拼接 Router 与挂载前缀。表声明是源码静态清单，包含迁移和派生库。实际安装、Feature 可见性和运行状态需独立验证。

## 后端 API

### ac_management_router

[实现](../../src/netconsole/backend/api/ac_management_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/summary` | `summary` |
| `GET` | `/aps` | `list_aps` |
| `GET` | `/optical-anomalies` | `optical_anomalies` |
| `GET` | `/aps/{ap_id}` | `ap_detail` |
| `GET` | `/aps/{ap_id}/history/{history_kind}` | `ap_history` |
| `GET` | `/aps/{ap_id}/radios` | `ap_radios` |
| `GET` | `/aps/{ap_id}/lldp` | `ap_lldp` |
| `GET` | `/aps/{ap_id}/lldp/current` | `ap_current_lldp` |
| `GET` | `/aps/{ap_id}/optical` | `ap_optical` |
| `GET` | `/config-snapshots` | `config_snapshots` |
| `GET` | `/config-snapshots/{snapshot_id}` | `config_snapshot` |
| `GET` | `/config-snapshots/{snapshot_id}/diff` | `config_diff` |
| `GET` | `/online-overview` | `online_overview` |
| `GET` | `/optical` | `optical` |
| `GET` | `/extensions` | `extensions` |
| `POST` | `/extensions/import-preview` | `extension_import_preview` |
| `POST` | `/extensions/import-apply` | `extension_import_apply` |
| `POST` | `/extensions/audits/{audit_id}/rollback` | `extension_rollback` |
| `POST` | `/local-rebuild/{rebuild_kind}` | `local_rebuild` |
| `POST` | `/refresh/{refresh_kind}` | `refresh_resources` |
| `POST` | `/fit-aps/verbose` | `refresh_fit_ap_verbose` |
| `POST` | `/fit-aps/delete` | `delete_fit_aps` |
| `POST` | `/fit-aps/metadata/import` | `import_fit_ap_metadata` |
| `POST` | `/aps/{ap_id}/metadata` | `save_fit_ap_metadata` |
| `POST` | `/fit-aps/omnipeek/preview` | `preview_fit_ap_omnipeek` |
| `GET` | `/fit-aps/omnipeek/preview/{task_id}` | `fit_ap_omnipeek_preview` |
| `POST` | `/fit-aps/omnipeek/export` | `export_fit_ap_omnipeek` |
| `POST` | `/fit-aps/export` | `export_fit_ap_resources` |
| `GET` | `/fit-aps/omnipeek/preferences` | `fit_ap_omnipeek_preferences` |
| `PUT` | `/fit-aps/omnipeek/preferences` | `save_fit_ap_omnipeek_preferences` |
| `GET` | `/fit-aps/external-terminal/options` | `fit_ap_external_terminal_options` |
| `POST` | `/fit-aps/{ap_id}/external-terminal` | `fit_ap_external_terminal` |
| `POST` | `/trackside-business/local-rebuild` | `trackside_business_local_rebuild` |
| `GET` | `/web-tasks/{task_id}` | `web_task` |
| `POST` | `/web-tasks/{task_id}/cancel` | `cancel_web_task` |
| `POST` | `/web-tasks/recover` | `recover_web_tasks` |
| `POST` | `/actions/plans` | `create_action_plan` |
| `GET` | `/actions/plans/{plan_id}` | `action_plan` |
| `POST` | `/actions/plans/{plan_id}/confirm` | `confirm_action_plan` |
| `POST` | `/actions/plans/{plan_id}/execute` | `execute_action_plan` |
| `POST` | `/actions/plans/{plan_id}/reconcile` | `reconcile_action_plan` |
| `GET` | `/actions/plans/{plan_id}/audit` | `action_audit` |
| `POST` | `/extensions/export` | `extension_export` |
| `GET` | `/extensions/artifacts/{artifact_id}/download` | `extension_export_download` |
| `GET` | `/fit-aps/omnipeek/artifacts/{artifact_id}/download` | `fit_ap_omnipeek_download` |
| `GET` | `/fit-aps/artifacts/{artifact_id}/download` | `fit_ap_resource_download` |

### ac_mesh_link_router

[实现](../../src/netconsole/backend/api/ac_mesh_link_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/summary` | `summary` |
| `POST` | `/refresh` | `refresh_mesh_links` |
| `GET` | `/current` | `current_links` |
| `GET` | `/mrs` | `mrs` |
| `GET` | `/offline-mrs` | `offline_mrs` |
| `GET` | `/unmatched` | `unmatched_links` |
| `GET` | `/peer-aps` | `peer_aps` |
| `GET` | `/mrs/{mr_id}` | `mr_detail` |
| `GET` | `/snapshots` | `snapshots` |
| `GET` | `/raw-tail` | `raw_tail` |
| `GET` | `/snapshots/{snapshot_id}` | `snapshot_detail` |

### command_reference_router

[实现](../../src/netconsole/backend/api/command_reference_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `list_references` |
| `POST` | `/exports` | `start_export` |
| `GET` | `/exports/{task_id}` | `export_task` |
| `POST` | `/exports/{task_id}/cancel` | `cancel_export` |
| `GET` | `/artifacts/{artifact_id}/download` | `download_artifact` |

### config_collection_router

[实现](../../src/netconsole/backend/api/config_collection_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/devices` | `list_devices` |
| `GET` | `/devices/{device_id}/snapshots` | `list_snapshots` |
| `POST` | `/actions` | `submit_collection` |
| `POST` | `/snapshots/{snapshot_id}/content` | `load_snapshot_content` |
| `POST` | `/devices/{device_id}/diff/latest` | `compare_latest_snapshots` |
| `POST` | `/diff/snapshots` | `compare_snapshot_pair` |
| `POST` | `/diff/devices` | `compare_device_pair` |
| `GET` | `/tasks` | `list_tasks` |
| `GET` | `/tasks/{task_id}` | `get_task` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel_task` |
| `POST` | `/snapshots/delete/issue` | `issue_snapshot_delete` |
| `POST` | `/snapshots/delete/confirm` | `confirm_snapshot_delete` |
| `POST` | `/actions/save-force/preview` | `preview_save_force` |
| `POST` | `/actions/save-force/confirm` | `confirm_save_force` |
| `POST` | `/exports/diff` | `export_diff` |
| `POST` | `/exports/snapshots` | `export_snapshots` |
| `POST` | `/desktop-actions/open-directory` | `directory_info` |
| `GET` | `/artifacts/{artifact_id}` | `download_artifact` |

### database_upgrade_router

[实现](../../src/netconsole/backend/api/database_upgrade_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `list_database_upgrades` |
| `POST` | `/upgrade` | `start_database_upgrade` |
| `POST` | `/upgrade/batch` | `start_database_batch_upgrade` |
| `POST` | `/backups/batch` | `start_database_batch_backup` |
| `POST` | `/legacy-archives/organize` | `organize_legacy_archives` |
| `POST` | `/backups/{backup_id}/validate` | `validate_backup` |
| `POST` | `/backups/{backup_id}/restore` | `restore_backup` |
| `POST` | `/backups/{backup_id}/delete` | `delete_backup` |
| `POST` | `/backups/batch-delete` | `delete_backups` |
| `POST` | `/backups/{backup_id}/open-directory` | `open_backup_directory` |

### development_router

[实现](../../src/netconsole/backend/api/development_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/runtime-status` | `runtime_status` |
| `POST` | `/session` | `create_development_browser_session` |

### device_compatibility_router

[实现](../../src/netconsole/backend/api/device_compatibility_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/summary` | `compatibility_summary` |

### device_management_router

[实现](../../src/netconsole/backend/api/device_management_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/devices` | `list_devices` |
| `GET` | `/groups/totals` | `group_totals` |
| `GET` | `/groups` | `list_groups` |
| `POST` | `/groups` | `create_group` |
| `PATCH` | `/groups/{group_id}` | `rename_group` |
| `DELETE` | `/groups/{group_id}` | `delete_group` |
| `POST` | `/groups/assign` | `assign_group` |
| `PATCH` | `/devices/classification` | `update_classification` |
| `POST` | `/devices` | `create_device` |
| `PUT` | `/devices/{device_uuid}` | `update_device` |
| `POST` | `/devices/{device_uuid}/duplicate` | `duplicate_device` |
| `POST` | `/devices/deletion-preflight` | `deletion_preflight` |
| `POST` | `/devices/delete-confirmation` | `issue_delete_token` |
| `POST` | `/devices/batch-delete` | `delete_devices` |
| `POST` | `/devices/batch-refresh-details` | `batch_refresh_details` |
| `GET` | `/batch-refreshes/{batch_id}` | `get_batch_refresh` |
| `POST` | `/devices/batch-connection-tests` | `batch_connection_tests` |
| `POST` | `/devices/connection-health-checks` | `start_connection_health_check` |
| `GET` | `/devices/connection-health-checks/{task_id}` | `get_connection_health_check` |
| `POST` | `/devices/connection-health-checks/{task_id}/cancel` | `cancel_connection_health_check` |
| `POST` | `/health-checks` | `start_health_check` |
| `GET` | `/health-checks/{task_id}` | `get_health_check` |
| `POST` | `/health-checks/{task_id}/cancel` | `cancel_health_check` |
| `POST` | `/devices/{device_uuid}/refresh-optical` | `refresh_optical` |
| `GET` | `/devices/{device_uuid}/overview` | `device_overview` |
| `GET` | `/devices/{device_uuid}/recent-change-counts` | `device_recent_change_counts` |
| `GET` | `/devices/{device_uuid}/interfaces` | `device_interfaces` |
| `GET` | `/devices/{device_uuid}/interfaces/{interface_name:path}` | `device_interface_detail` |
| `GET` | `/devices/{device_uuid}/transceivers` | `device_transceivers` |
| `GET` | `/devices/{device_uuid}/lldp` | `device_lldp` |
| `GET` | `/devices/{device_uuid}/config-snapshots` | `device_config_snapshots` |
| `GET` | `/devices/{device_uuid}/tasks` | `device_detail_tasks` |
| `GET` | `/devices/{device_uuid}/business-associations` | `device_business_associations` |
| `POST` | `/devices/{device_uuid}/refresh` | `refresh_device_detail` |
| `POST` | `/imports/preview` | `preview_import` |
| `POST` | `/imports/confirm` | `confirm_import` |
| `POST` | `/exports/csv` | `export_csv` |
| `POST` | `/exports/template` | `export_template` |
| `POST` | `/exports/securecrt` | `export_securecrt` |
| `POST` | `/exports/securecrt-with-template` | `export_securecrt_with_template` |
| `GET` | `/exports/{task_id}` | `export_status` |
| `GET` | `/exports/{task_id}/download` | `download_export` |
| `POST` | `/devices/{device_uuid}/diagnostic-download` | `diagnostic_download` |
| `POST` | `/diagnostic-download` | `batch_diagnostic_download` |
| `GET` | `/diagnostics/{task_id}/download` | `download_diagnostics` |
| `GET` | `/external-terminal/settings` | `external_terminal_settings` |
| `PUT` | `/external-terminal/settings` | `update_external_terminal_settings` |
| `POST` | `/external-terminal/launch` | `batch_external_terminal` |
| `POST` | `/external-terminal/preflight` | `external_terminal_preflight` |
| `POST` | `/external-terminal/confirmation` | `external_terminal_confirmation` |
| `POST` | `/devices/{device_uuid}/external-terminal` | `external_terminal` |
| `GET` | `/devices/{device_uuid}/edit-profile` | `device_edit_profile` |
| `GET` | `/devices/{device_uuid}/credentials/{credential_field}/reveal` | `reveal_device_credentials` |
| `GET` | `/devices/{device_uuid}` | `device_detail` |
| `GET` | `/devices/{device_uuid}/history` | `device_history` |
| `POST` | `/connection-tests/form` | `start_form_connection_test` |
| `POST` | `/devices/{device_uuid}/connection-tests` | `start_connection_test` |
| `GET` | `/connection-tests/{task_id}` | `connection_test` |
| `GET` | `/tasks/{task_id}` | `task_status` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel_task` |

### device_operations_router

[实现](../../src/netconsole/backend/api/device_operations_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/organizations` | `target_organizations` |
| `POST` | `/templates/preview` | `preview_template` |
| `GET` | `/templates` | `list_templates` |
| `POST` | `/templates` | `create_template` |
| `POST` | `/templates/saved-preview` | `preview_saved_template` |
| `GET` | `/templates/{template_id}/versions` | `template_versions` |
| `PUT` | `/templates/{template_id}` | `update_template` |
| `POST` | `/tasks` | `start_device_task` |
| `GET` | `/tasks/{task_id}/result` | `device_task_result` |
| `POST` | `/tasks/{task_id}/exports` | `export_device_task` |
| `POST` | `/tasks/{task_id}/retry` | `retry_device_task` |

### feature_router

[实现](../../src/netconsole/backend/api/feature_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `renderer_feature_states` |

### file_management_router

[实现](../../src/netconsole/backend/api/file_management_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/workspace/entries` | `workspace_entries` |
| `GET` | `/workspace/files/{entry_id}` | `workspace_download` |
| `POST` | `/workspace/operations` | `workspace_operation` |
| `GET` | `/workspace/operations` | `workspace_operations` |
| `POST` | `/workspace/upload` | `workspace_upload` |
| `POST` | `/workspace/operations/{task_id}/cancel` | `cancel_workspace_operation` |
| `GET` | `/status` | `management_status` |
| `GET` | `/local/entries` | `list_local_entries` |
| `POST` | `/local/directories` | `create_local_directory` |
| `GET` | `/local/entries/{entry_id}/file` | `open_local_file` |
| `GET` | `/devices` | `list_remote_devices` |
| `POST` | `/connections` | `connect_device` |
| `DELETE` | `/connections/{connection_id}` | `disconnect_device` |
| `GET` | `/connections/{connection_id}/entries` | `list_remote_entries` |
| `GET` | `/files` | `list_files` |
| `POST` | `/downloads` | `start_download` |
| `POST` | `/downloads/batch` | `start_download_batch` |
| `GET` | `/downloads/{task_id}` | `download_task` |
| `GET` | `/downloads` | `list_downloads` |
| `POST` | `/downloads/{task_id}/cancel` | `cancel_download` |
| `POST` | `/downloads/{task_id}/retry` | `retry_download` |
| `POST` | `/downloads/{task_id}/mesh-import` | `retry_mesh_import` |
| `POST` | `/downloads/clear` | `clear_downloads` |
| `GET` | `/downloads/{task_id}/file` | `download_file` |
| `POST` | `/desktop-actions/{action}` | `prepare_desktop_action` |
| `POST` | `/desktop-actions/{action_ref}/execute` | `execute_desktop_action` |

### ground_unattended_router

[实现](../../src/netconsole/backend/api/ground_unattended_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/heartbeat/config` | `get_heartbeat_config` |
| `PUT` | `/heartbeat/config` | `update_heartbeat_config` |
| `GET` | `/heartbeat/runtime` | `get_heartbeat_runtime` |
| `POST` | `/history/export` | `export_history` |
| `GET` | `/status` | `get_status` |
| `GET` | `/profile` | `get_profile` |
| `GET` | `/ac/basic-collection` | `get_ac_basic_collection` |
| `GET` | `/arp/status` | `get_arp_status` |
| `POST` | `/arp/refresh` | `refresh_arp` |
| `PUT` | `/ac/basic-collection/{device_uuid}` | `set_ac_basic_collection` |
| `GET` | `/heartbeat` | `get_heartbeat` |
| `POST` | `/heartbeat/inventory/preview` | `heartbeat_inventory_preview` |
| `POST` | `/heartbeat/inventory/apply` | `heartbeat_inventory_apply` |
| `GET` | `/mr/{mr_uuid}/monitoring` | `get_mr_monitoring` |
| `PUT` | `/profile` | `update_profile` |
| `POST` | `/start` | `start` |
| `POST` | `/pause` | `pause` |
| `POST` | `/resume` | `resume` |
| `POST` | `/stop` | `stop` |
| `POST` | `/stop-and-archive` | `stop_and_archive` |
| `POST` | `/quick-ping` | `start_quick_ping` |
| `GET` | `/quick-ping` | `list_quick_ping` |
| `GET` | `/quick-ping/{run_id}/samples` | `quick_ping_samples` |
| `GET` | `/quick-ping/{run_id}` | `get_quick_ping` |
| `GET` | `/history` | `history` |
| `POST` | `/quick-ping/{run_id}/stop` | `stop_quick_ping` |
| `POST` | `/quick-ping/{run_id}/targets/{target_ip}/stop` | `stop_quick_ping_target` |
| `GET` | `/trains` | `trains` |
| `GET` | `/mr-runtime-status` | `mr_runtime_status` |
| `POST` | `/inventory/sync` | `sync_inventory` |
| `GET` | `/trains/{train_id}` | `train` |
| `PUT` | `/trains/{train_id}/priority` | `update_priority` |
| `PUT` | `/trains/{train_id}/policy` | `update_policy` |
| `POST` | `/config-check` | `config_check` |
| `POST` | `/syslog-control` | `syslog_control` |
| `GET` | `/health` | `health` |
| `GET` | `/syslog-transport-status` | `syslog_transport_status` |
| `GET` | `/raw-files` | `raw_files` |
| `GET` | `/runs` | `runs` |
| `DELETE` | `/runs/{run_id}` | `delete_run_history` |
| `POST` | `/archives/batch-delete` | `batch_delete_archives` |
| `GET` | `/ping-targets` | `ping_targets` |
| `GET` | `/ping-summary` | `ping_summary` |
| `GET` | `/ping-series` | `ping_series` |
| `GET` | `/ping-series/incremental` | `ping_series_incremental` |
| `GET` | `/ping-samples` | `ping_samples` |
| `GET` | `/syslog-records` | `syslog_records` |
| `POST` | `/syslog-delete-preview` | `preview_syslog_delete` |
| `POST` | `/syslog-delete` | `submit_syslog_delete` |
| `GET` | `/timeline` | `timeline` |
| `GET` | `/deep-collections/tasks` | `deep_tasks` |
| `GET` | `/deep-collections` | `deep_collections` |
| `GET` | `/deep-collections/records` | `deep_collection_records` |
| `GET` | `/coverage` | `coverage` |
| `GET` | `/operations/latest` | `latest_operation` |
| `GET` | `/operations/active` | `active_operation` |
| `GET` | `/operations/{operation_id}` | `operation` |
| `GET` | `/archives` | `archives` |
| `GET` | `/archives/{archive_id}` | `archive` |
| `GET` | `/archives/{archive_id}/detail` | `archive_detail` |
| `POST` | `/archives/{archive_id}/verify` | `verify_archive` |
| `GET` | `/archives/{archive_id}/summary-download` | `download_archive_summary` |
| `GET` | `/artifacts/{archive_id}/download` | `download_archive_artifact` |
| `GET` | `/artifacts/{archive_id}/summary-download` | `download_archive_summary_artifact` |
| `POST` | `/archives/open-directory` | `open_archive_directory` |
| `DELETE` | `/archives/{archive_id}` | `delete_archive` |

### health

[实现](../../src/netconsole/backend/api/health.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/health` | `health` |

### job_center_router

[实现](../../src/netconsole/backend/api/job_center_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/tasks` | `list_tasks` |
| `GET` | `/summary` | `summary` |
| `POST` | `/cleanup` | `cleanup_tasks` |
| `POST` | `/acknowledge` | `acknowledge_tasks` |
| `GET` | `/tasks/{task_id}` | `detail` |
| `POST` | `/tasks/{task_id}/acknowledge` | `acknowledge_task` |
| `POST` | `/tasks/{task_id}/dismiss` | `dismiss_task` |
| `GET` | `/tasks/{task_id}/logs` | `logs` |
| `GET` | `/artifacts/{artifact_id}` | `download_artifact` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel` |

### local_network_services_router

[实现](../../src/netconsole/backend/api/local_network_services_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `list_services` |
| `PUT` | `/{kind}/config` | `configure_service` |
| `POST` | `/{kind}/actions/{action}` | `service_action` |
| `GET` | `/{kind}/logs` | `service_logs` |

### main

[实现](../../src/netconsole/backend/api/main.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/` | `web_shell_placeholder` |
| `POST` | `/__desktop_session` | `create_desktop_session` |
| `GET` | `/{frontend_path:path}` | `frontend` |

### mesh_analysis_router

[实现](../../src/netconsole/backend/api/mesh_analysis_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `POST` | `/ap-coverage/audit` | `audit_ap_coverage` |
| `POST` | `/ap-coverage/export` | `export_ap_coverage` |
| `GET` | `/ap-coverage/artifacts/{artifact_id}/download` | `download_ap_coverage_export` |
| `GET` | `/summary` | `summary` |
| `GET` | `/profiles` | `profiles` |
| `POST` | `/import-context/prepare` | `prepare_import_context` |
| `GET` | `/import-context` | `import_context` |
| `POST` | `/profiles` | `create_profile` |
| `POST` | `/import-preview` | `preview_import` |
| `POST` | `/bundles/preview` | `preview_bundle` |
| `POST` | `/bundles/import` | `import_bundle` |
| `POST` | `/local-scans` | `start_local_scan` |
| `GET` | `/local-scans/{scan_id}` | `local_scan_result` |
| `POST` | `/local-scans/{scan_id}/import` | `import_local_scan` |
| `POST` | `/local-scans/{scan_id}/ignore` | `ignore_local_scan` |
| `POST` | `/local-scans/{scan_id}/candidates/{candidate_id}/open-directory` | `open_local_scan_candidate_directory` |
| `GET` | `/sessions` | `sessions` |
| `GET` | `/overview` | `overview` |
| `GET` | `/sessions/{session_id}` | `session_detail` |
| `GET` | `/sessions/{session_id}/parse-issues` | `parse_issues` |
| `GET` | `/sessions/{session_id}/links` | `links` |
| `GET` | `/sessions/{session_id}/timeline` | `timeline` |
| `GET` | `/sessions/{session_id}/switch-events` | `switch_events` |
| `GET` | `/sessions/{session_id}/rssi` | `rssi` |
| `GET` | `/sessions/{session_id}/channel-busy` | `channel_busy` |
| `GET` | `/sessions/{session_id}/rate-series` | `rate_series` |
| `GET` | `/sessions/{session_id}/active-build-order` | `active_build_order` |
| `GET` | `/sessions/{session_id}/charts/active-path` | `active_path_chart` |
| `GET` | `/sessions/{session_id}/charts/trackside-signal` | `trackside_signal_chart` |
| `GET` | `/sessions/{session_id}/charts/peer-segment` | `peer_segment_chart` |
| `GET` | `/sessions/{session_id}/counter-deltas` | `counter_deltas` |
| `GET` | `/sessions/{session_id}/anomalies` | `anomalies` |
| `GET` | `/sessions/{session_id}/ap-statistics` | `ap_statistics` |
| `GET` | `/sessions/{session_id}/ap-signal-statistics` | `ap_signal_statistics` |
| `GET` | `/sessions/{session_id}/business-summary` | `business_summary` |
| `GET` | `/sessions/{session_id}/single-links` | `single_links` |
| `GET` | `/sessions/{session_id}/artifacts` | `artifacts` |
| `DELETE` | `/sessions/{session_id}/artifacts/{artifact_id}` | `delete_artifact` |
| `GET` | `/sessions/{session_id}/artifacts/{artifact_id}/download` | `download_artifact` |
| `GET` | `/sessions/{session_id}/raw-sources` | `raw_sources` |
| `POST` | `/sessions/{session_id}/desktop-location` | `desktop_location` |
| `GET` | `/sessions/{session_id}/raw-sources/{source_action_id}/tail` | `raw_tail` |
| `DELETE` | `/sources/{source_id}` | `delete_source` |
| `POST` | `/sources/batch-delete` | `delete_sources` |
| `POST` | `/sessions/{session_id}/maintenance` | `maintain_session` |
| `POST` | `/sessions/{session_id}/rebuild` | `rebuild_session` |
| `POST` | `/sessions/{session_id}/report` | `start_report` |
| `POST` | `/sessions/{session_id}/link-details/export` | `start_link_detail_export` |
| `POST` | `/sessions/{session_id}/raw-links/export` | `start_raw_link_export` |
| `GET` | `/report-artifacts/{artifact_id}/download` | `download_generated_report` |
| `GET` | `/analysis-params` | `get_analysis_params` |
| `GET` | `/analysis-params/templates/{service_type}` | `get_analysis_params_template` |
| `PUT` | `/analysis-params` | `save_analysis_params` |

### network_tools_router

[实现](../../src/netconsole/backend/api/network_tools_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `POST` | `/tcp-port-test` | `start_tcp_port_test` |
| `POST` | `/toolbox/ipv4` | `calculate_ipv4` |
| `POST` | `/toolbox/ipv6` | `calculate_ipv6` |
| `POST` | `/toolbox/vlsm` | `calculate_vlsm` |
| `POST` | `/toolbox/subnets` | `calculate_subnets` |
| `POST` | `/toolbox/summarize` | `summarize_routes` |
| `POST` | `/toolbox/wildcard` | `calculate_wildcard` |
| `GET` | `/toolbox/probe-environment` | `get_network_probe_environment` |
| `POST` | `/tasks` | `start_network_task` |
| `GET` | `/runs` | `list_network_tasks` |
| `GET` | `/runs/{task_id}` | `get_network_task` |
| `GET` | `/runs/{task_id}/events` | `get_network_task_events` |
| `POST` | `/runs/{task_id}/cancel` | `cancel_network_task` |
| `GET` | `/runs/{task_id}/results` | `list_network_task_results` |
| `POST` | `/runs/{task_id}/export` | `export_network_task` |
| `GET` | `/runs/{task_id}/artifact` | `get_network_export_artifact` |
| `GET` | `/artifacts/{artifact_id}` | `download_network_artifact` |
| `GET` | `/wireless-scan/adapters` | `list_wireless_adapters` |
| `GET` | `/wireless-scan/projects` | `list_wireless_projects` |
| `POST` | `/wireless-scan/projects` | `create_wireless_project` |
| `DELETE` | `/wireless-scan/projects/{project_id}` | `delete_wireless_project` |
| `POST` | `/wireless-scan/tasks` | `start_wireless_scan` |
| `GET` | `/wireless-scan/tasks` | `list_wireless_tasks` |
| `GET` | `/wireless-scan/tasks/{task_id}` | `get_wireless_task` |
| `GET` | `/wireless-scan/tasks/{task_id}/events` | `get_wireless_task_events` |
| `POST` | `/wireless-scan/tasks/{task_id}/cancel` | `cancel_wireless_task` |
| `GET` | `/wireless-scan/runs` | `list_wireless_runs` |
| `GET` | `/wireless-scan/runs/{scan_id}/results` | `list_wireless_results` |
| `GET` | `/wireless-scan/runs/{scan_id}` | `get_wireless_run_detail` |
| `POST` | `/wireless-scan/export` | `export_wireless_scan` |
| `GET` | `/wireless-scan/tasks/{task_id}/artifact` | `get_wireless_export_artifact` |
| `GET` | `/wireless-scan/artifacts/{artifact_id}` | `download_wireless_artifact` |

### online_mr_control_router

[实现](../../src/netconsole/backend/api/online_mr_control_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/status` | `status` |
| `GET` | `/presets` | `presets` |
| `GET` | `/{operation_id}` | `operation_detail` |
| `POST` | `/start` | `start` |
| `POST` | `/{operation_id}/stop` | `stop` |
| `POST` | `/{operation_id}/force-stop` | `force_stop` |
| `POST` | `/recover` | `recover` |

### online_mr_inventory_router

[实现](../../src/netconsole/backend/api/online_mr_inventory_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/summary` | `summary` |
| `GET` | `/trains` | `trains` |

### online_mr_router

[实现](../../src/netconsole/backend/api/online_mr_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/sessions/current` | `current_session` |
| `GET` | `/sessions/recent` | `recent_sessions` |
| `GET` | `/sessions/{session_id}` | `session_detail` |
| `GET` | `/sessions/{session_id}/collectors` | `collectors` |
| `GET` | `/sessions/{session_id}/preview` | `preview` |
| `GET` | `/sessions/{session_id}/raw-tail` | `raw_tail` |
| `GET` | `/sessions/{session_id}/raw-summary` | `raw_summary` |
| `GET` | `/sessions/{session_id}/business-summary` | `business_summary` |
| `GET` | `/sessions/{session_id}/traffic-overview` | `traffic_overview` |
| `GET` | `/sessions/{session_id}/business-table` | `business_table` |
| `GET` | `/sessions/{session_id}/logs` | `collector_logs` |
| `GET` | `/sessions/{session_id}/metrics` | `metrics` |
| `GET` | `/sessions/{session_id}/metric-page` | `metric_page` |
| `GET` | `/sessions/{session_id}/switch-rssi-windows` | `switch_rssi_windows` |
| `GET` | `/sessions/{session_id}/timeline` | `timeline` |
| `GET` | `/sessions/{session_id}/notes` | `notes` |
| `POST` | `/sessions/{session_id}/notes` | `add_note` |
| `POST` | `/sessions/{session_id}/parse` | `parse_session` |
| `POST` | `/sessions/{session_id}/ensure-current` | `ensure_current` |
| `GET` | `/sessions/{session_id}/database-summary` | `database_summary` |
| `GET` | `/sessions/{session_id}/artifacts` | `artifacts` |
| `POST` | `/sessions/{session_id}/report` | `report` |
| `POST` | `/sessions/{session_id}/desktop-location` | `desktop_location` |
| `DELETE` | `/sessions/{session_id}` | `delete_session` |
| `POST` | `/mesh-analysis/import` | `mesh_analysis_import` |
| `GET` | `/report-artifacts/{artifact_id}/download` | `report_download` |
| `GET` | `/tasks/{task_id}` | `task_detail` |
| `POST` | `/tasks/{task_id}/cancel` | `task_cancel` |
| `POST` | `/tasks/recover` | `task_recover` |

### rail_infrastructure_router

[实现](../../src/netconsole/backend/api/rail_infrastructure_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `infrastructure` |
| `POST` | `/initialize` | `initialize` |
| `GET` | `/organization-catalog` | `organization_catalog` |
| `POST` | `/organization-assets/preview` | `preview_organization_assets` |
| `POST` | `/organization-assets/apply` | `apply_organization_assets` |
| `POST` | `/organization-nodes` | `save_organization_node` |
| `GET` | `/switch-aps` | `switch_aps` |

### rail_relationship_router

[实现](../../src/netconsole/backend/api/rail_relationship_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `list_relationships` |
| `GET` | `/history` | `history` |
| `GET` | `/engineering-context` | `engineering_context` |
| `GET` | `/catalog` | `catalog` |
| `GET` | `/delete-preflight` | `delete_preflight` |
| `GET` | `/ac-resources` | `ac_resources` |
| `POST` | `/projects` | `save_project` |
| `POST` | `/preview` | `preview` |
| `POST` | `` | `mutate` |

### rail_transit_base_data_router

[实现](../../src/netconsole/backend/api/rail_transit_base_data_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/summary` | `summary` |
| `GET` | `/infrastructure` | `infrastructure` |
| `GET` | `/infrastructure/switch-aps` | `infrastructure_switch_aps` |
| `GET` | `/revision` | `revision` |
| `GET` | `/edit-snapshot` | `edit_snapshot` |
| `GET` | `/clear-preview` | `clear_preview` |
| `POST` | `/clear-all` | `clear_all` |
| `POST` | `/validate` | `validate_changes` |
| `POST` | `/changes` | `save_changes` |
| `GET` | `/stations` | `stations` |
| `GET` | `/station-source-preview` | `station_source_preview` |
| `POST` | `/stations/delete-preflight` | `station_delete_preflight` |
| `GET` | `/stations/conflicts` | `station_conflicts` |
| `GET` | `/station-template` | `station_template` |
| `POST` | `/station-template-preview` | `station_template_preview` |
| `GET` | `/station-template-export` | `station_template_export` |
| `GET` | `/sections` | `sections` |
| `POST` | `/section-generation-preview` | `section_generation_preview` |
| `GET` | `/aps` | `aps` |
| `GET` | `/aps/{ap_id}` | `ap_detail` |
| `GET` | `/trains` | `trains` |
| `GET` | `/trains/{train_id}` | `train_detail` |
| `GET` | `/mrs` | `mrs` |
| `GET` | `/mrs/{mr_id}` | `mr_detail` |
| `GET` | `/issues` | `issues` |
| `GET` | `/issues/groups` | `issue_groups` |
| `GET` | `/import-policies` | `import_policies` |
| `POST` | `/import-apply` | `import_apply` |
| `GET` | `/import-operations` | `import_operations` |
| `GET` | `/import-operations/{operation_id}` | `import_operation` |
| `GET` | `/import-operations/{operation_id}/changes` | `import_operation_changes` |
| `POST` | `/import-operations/{operation_id}/rollback` | `import_operation_rollback` |
| `GET` | `/relations` | `relations` |
| `POST` | `/import-preview` | `import_preview` |

### site_storage_router

[实现](../../src/netconsole/backend/api/site_storage_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/sites` | `list_sites` |
| `GET` | `/sites/runtime-context` | `site_runtime_context` |
| `POST` | `/sites` | `create_site` |
| `GET` | `/sites/active` | `active_site` |
| `GET` | `/sites/{site_id}` | `get_site` |
| `GET` | `/sites/{site_id}/ssh-relay` | `get_ssh_relay` |
| `PUT` | `/sites/{site_id}/ssh-relay` | `update_ssh_relay` |
| `POST` | `/sites/{site_id}/ssh-relay/test` | `test_ssh_relay` |
| `POST` | `/sites/{site_id}/ssh-relay/host-key/refresh` | `refresh_ssh_relay_host_key` |
| `DELETE` | `/sites/{site_id}/ssh-relay/host-key` | `delete_ssh_relay_host_key` |
| `GET` | `/sites/{site_id}/task-result-storage` | `task_result_storage_status` |
| `PATCH` | `/sites/{site_id}` | `update_site` |
| `POST` | `/sites/{site_id}/trash` | `trash_site` |
| `POST` | `/sites/{site_id}/audit` | `audit_site` |
| `GET` | `/sites/{site_id}/audit/latest` | `latest_site_audit` |
| `POST` | `/sites/{site_id}/retention/scan` | `scan_site_retention` |
| `GET` | `/sites/{site_id}/retention/latest` | `latest_site_retention` |
| `POST` | `/sites/{site_id}/retention/apply` | `apply_site_retention` |
| `POST` | `/sites/{site_id}/cleanup/prepare` | `prepare_site_cleanup` |
| `POST` | `/sites/{site_id}/cleanup/apply` | `apply_site_cleanup` |
| `POST` | `/sites/recycle/{cleanup_token}/restore` | `restore_site_cleanup` |
| `POST` | `/sites/demo/rebuild` | `rebuild_demo` |
| `POST` | `/sites/{site_id}/activate/preflight` | `preflight_site_activation` |
| `POST` | `/sites/{site_id}/activate` | `activate_site` |
| `POST` | `/sites/{site_id}/migrate` | `migrate_site` |
| `POST` | `/sites/{site_id}/export` | `export_site` |
| `POST` | `/sites/export-lightweight-bundle` | `export_lightweight_bundle` |
| `POST` | `/sites/import/inspect` | `inspect_site_package` |
| `POST` | `/sites/import` | `import_site` |
| `GET` | `/storage/data-root` | `get_data_root` |
| `POST` | `/storage/data-root/validate` | `validate_data_root` |
| `POST` | `/storage/data-root/migration-plan` | `plan_data_root_migration` |
| `POST` | `/storage/data-root/migrate` | `migrate_data_root` |

### storage_audit_router

[实现](../../src/netconsole/backend/api/storage_audit_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `get_storage_audit` |

### system_maintenance_router

[实现](../../src/netconsole/backend/api/system_maintenance_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/logs` | `list_logs` |
| `GET` | `/logs/summary` | `runtime_log_summary` |
| `DELETE` | `/logs` | `clear_logs` |
| `POST` | `/cleanup/tasks` | `start_cleanup` |
| `POST` | `/open-source/tasks` | `start_open_source_scan` |
| `POST` | `/exports/logs` | `start_log_export` |
| `POST` | `/exports/open-source` | `start_open_source_export` |
| `POST` | `/exports/field-diagnostic` | `start_field_diagnostic` |
| `GET` | `/tasks` | `recover_tasks` |
| `GET` | `/tasks/{task_id}` | `get_task` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel_task` |
| `GET` | `/changelog` | `changelog` |
| `GET` | `/about` | `about` |
| `POST` | `/links/about/{link_id}` | `about_link` |
| `POST` | `/links/open-source/{task_id}/{component_index}` | `open_source_link` |
| `POST` | `/desktop-actions/open-directory/{kind}` | `open_directory` |
| `GET` | `/artifacts/{kind}/{artifact_id}` | `download_artifact` |

### system_network_router

[实现](../../src/netconsole/backend/api/system_network_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/ipv4-addresses` | `ipv4_addresses` |
| `POST` | `/recommend-source-ip` | `recommend_source_ip` |
| `POST` | `/check-udp-port` | `check_udp_port` |

### system_settings_router

[实现](../../src/netconsole/backend/api/system_settings_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `get_settings` |
| `PUT` | `` | `save_settings` |
| `POST` | `/reload` | `reload_settings` |
| `GET` | `/network-components` | `get_network_components` |
| `PUT` | `/network-components/{component_name}` | `save_network_component` |
| `GET` | `/self-check` | `runtime_self_check` |
| `POST` | `/native-action` | `execute_native_settings_action` |

### task_router

[实现](../../src/netconsole/backend/api/task_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/tasks` | `list_tasks` |
| `GET` | `/tasks/{task_id}` | `get_task` |
| `GET` | `/tasks/{task_id}/events` | `get_task_events` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel_task` |
| `WEBSOCKET` | `/ws/tasks` | `task_events_socket` |

### terminal_router

[实现](../../src/netconsole/backend/api/terminal_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/quick-buttons` | `quick_buttons` |
| `PUT` | `/quick-buttons` | `save_quick_buttons` |
| `GET` | `/quick-buttons/export` | `export_quick_buttons` |
| `POST` | `/quick-buttons/reset` | `reset_quick_buttons` |
| `POST` | `/batch-sends` | `batch_send` |
| `GET` | `/batch-sends/{job_id}` | `batch_status` |
| `POST` | `/batch-sends/{job_id}/cancel` | `batch_cancel` |
| `POST` | `/batch-sends/{job_id}/pause` | `batch_pause` |
| `POST` | `/batch-sends/{job_id}/resume` | `batch_resume` |
| `GET` | `/batch-sends/{job_id}/export` | `batch_export` |
| `POST` | `/batch-sends/{job_id}/retry/{session_id}` | `batch_retry` |
| `GET` | `/rules/{kind}/export` | `export_terminal_rules` |
| `POST` | `/rules/import` | `import_terminal_rules` |
| `POST` | `/sessions` | `create_session` |
| `POST` | `/sessions/quick-connect` | `quick_connect_session` |
| `GET` | `/profiles` | `list_terminal_profiles` |
| `GET` | `/profiles/export` | `export_terminal_profiles` |
| `POST` | `/profiles/import` | `import_terminal_profiles` |
| `POST` | `/profiles` | `create_terminal_profile` |
| `PUT` | `/profiles/{profile_id}` | `update_terminal_profile` |
| `DELETE` | `/profiles/{profile_id}` | `delete_terminal_profile` |
| `POST` | `/profiles/{profile_id}/connect` | `connect_terminal_profile` |
| `GET` | `/serial/ports` | `enumerate_serial_ports` |
| `GET` | `/serial/profiles` | `list_serial_profiles` |
| `PUT` | `/serial/profiles` | `save_serial_profiles` |
| `POST` | `/serial/profiles/import` | `import_serial_profiles` |
| `GET` | `/serial/profiles/export` | `export_serial_profiles` |
| `POST` | `/serial/sessions` | `create_serial_session` |
| `POST` | `/serial/sessions/{session_id}/send-bytes` | `send_serial_bytes` |
| `GET` | `/serial/sessions/{session_id}/receive` | `receive_serial_bytes` |
| `POST` | `/serial/sessions/{session_id}/wait-for-pattern` | `wait_for_serial_pattern` |
| `POST` | `/serial/sessions/{session_id}/flush` | `flush_serial_session` |
| `POST` | `/serial/sessions/{session_id}/cancel` | `cancel_serial_session` |
| `POST` | `/profile-folders` | `create_terminal_profile_folder` |
| `PUT` | `/profile-folders/{folder_id}` | `rename_terminal_profile_folder` |
| `DELETE` | `/profile-folders/{folder_id}` | `delete_terminal_profile_folder` |
| `GET` | `/sessions` | `list_sessions` |
| `GET` | `/history` | `list_history` |
| `GET` | `/history/{session_id}` | `get_history` |
| `GET` | `/history/{session_id}/events` | `get_history_events` |
| `GET` | `/history/{session_id}/export/{export_format}` | `export_history` |
| `GET` | `/settings` | `get_terminal_settings` |
| `PUT` | `/settings` | `update_terminal_settings` |
| `GET` | `/rules/{kind}` | `get_terminal_rules` |
| `PUT` | `/rules/{kind}` | `replace_terminal_rules` |
| `POST` | `/sessions/{session_id}/ticket` | `issue_ticket` |
| `POST` | `/sessions/{session_id}/reconnect` | `reconnect_session` |
| `POST` | `/sessions/{session_id}/clone` | `clone_session` |
| `POST` | `/sessions/{session_id}/window-claim` | `claim_detached_window` |
| `PATCH` | `/sessions/{session_id}` | `rename_session` |
| `DELETE` | `/history/{session_id}` | `delete_recording` |
| `GET` | `/history/{session_id}/transcript` | `recording_transcript` |
| `GET` | `/history/{session_id}/search` | `search_recording` |
| `POST` | `/sessions/{session_id}/save-profile` | `save_session_profile` |
| `DELETE` | `/sessions/{session_id}` | `close_session` |
| `POST` | `/sessions/{session_id}/manual-log/start` | `start_manual_log` |
| `POST` | `/sessions/{session_id}/manual-log/pause` | `pause_manual_log` |
| `POST` | `/sessions/{session_id}/manual-log/resume` | `resume_manual_log` |
| `POST` | `/sessions/{session_id}/manual-log/stop` | `stop_manual_log` |
| `GET` | `/sessions/{session_id}/manual-log/{log_id}/export` | `export_manual_log` |
| `POST` | `/sftp/sessions` | `create_sftp_session` |
| `GET` | `/sftp/sessions` | `list_sftp_sessions` |
| `DELETE` | `/sftp/sessions/{session_id}` | `close_sftp_session` |
| `GET` | `/sftp/sessions/{session_id}/entries` | `list_sftp_entries` |
| `POST` | `/sftp/sessions/{session_id}/directories` | `create_sftp_directory` |
| `POST` | `/sftp/sessions/{session_id}/rename` | `rename_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/move` | `move_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/delete` | `delete_sftp_entries` |
| `POST` | `/sftp/sessions/{session_id}/copy` | `copy_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/download` | `download_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/upload` | `upload_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/upload-managed` | `upload_managed_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/download-managed` | `download_managed_sftp_entry` |
| `POST` | `/sftp/sessions/{session_id}/sync` | `synchronize_sftp_directory` |
| `GET` | `/sftp/sessions/{session_id}/text` | `read_sftp_text_file` |
| `PUT` | `/sftp/sessions/{session_id}/text` | `write_sftp_text_file` |
| `GET` | `/sftp/transfers` | `list_sftp_transfers` |
| `GET` | `/sftp/transfers/{task_id}` | `get_sftp_transfer` |
| `DELETE` | `/sftp/transfers` | `clear_sftp_transfers` |
| `GET` | `/sftp/transfer-log` | `sftp_transfer_log` |
| `POST` | `/sftp/transfers/{task_id}/save-result` | `record_sftp_save` |
| `POST` | `/sftp/transfers/{task_id}/cancel` | `cancel_sftp_transfer` |
| `POST` | `/sftp/transfers/{task_id}/pause` | `pause_sftp_transfer` |
| `POST` | `/sftp/transfers/{task_id}/retry` | `retry_sftp_transfer` |
| `GET` | `/sftp/transfers/{task_id}/file` | `export_sftp_download` |
| `WEBSOCKET` | `/ws/terminal/{session_id}` | `terminal_websocket` |

### trackside_ap_business_router

[实现](../../src/netconsole/backend/api/trackside_ap_business_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/rows` | `rows` |
| `GET` | `/switch-adapters` | `switch_adapters` |
| `POST` | `/switch-adapters/sample` | `start_switch_adapter_sample` |
| `GET` | `/switch-adapters/artifacts/{artifact_id}/download` | `download_switch_adapter_sample` |
| `POST` | `/export` | `export_business` |
| `GET` | `/export/proposal` | `export_business_proposal` |
| `GET` | `/artifacts/{artifact_id}/download` | `download_business_artifact` |
| `POST` | `/base/export` | `export_base` |
| `GET` | `/base/artifacts/{artifact_id}/download` | `download_base_artifact` |
| `POST` | `/base/rename-commands/export` | `export_rename_commands` |
| `GET` | `/base/rename-commands/artifacts/{artifact_id}/download` | `download_rename_command_artifact` |
| `GET` | `/plan` | `plan` |
| `GET` | `/plan/online-status` | `plan_online_status` |
| `GET` | `/plan/online-status/excluded` | `plan_online_status_excluded` |
| `GET` | `/plan/online-status/unmatched` | `plan_online_status_unmatched` |
| `POST` | `/plan/auto-group-preview` | `preview_auto_group` |
| `POST` | `/plan/adjustment-preview` | `preview_adjustment` |
| `POST` | `/plan/mode-impact-preview` | `preview_mode_impact` |
| `POST` | `/plan/validate` | `validate_plan` |
| `POST` | `/plan/address-preview` | `preview_addresses` |
| `GET` | `/plan/effective-network` | `effective_network` |
| `POST` | `/plan/point-table-preview` | `preview_point_table` |
| `POST` | `/plan/import/preview` | `preview_plan_import` |
| `POST` | `/plan/save` | `save_plan` |
| `POST` | `/plan/export` | `export_plan` |
| `GET` | `/plan/artifacts/{artifact_id}/download` | `download_plan_artifact` |
| `POST` | `/update` | `update` |
| `GET` | `/tasks/{task_id}` | `task` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel_task` |
| `POST` | `/tasks/recover` | `recover_tasks` |

### traffic_router

[实现](../../src/netconsole/backend/api/traffic_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/execution-targets` | `list_execution_targets` |
| `POST` | `/iperf/server` | `start_iperf_server` |
| `POST` | `/iperf/client` | `start_iperf_client` |
| `POST` | `/fping` | `start_fping` |
| `GET` | `/runs` | `list_runs` |
| `GET` | `/runs/{traffic_run_id}` | `get_run` |
| `GET` | `/runs/{traffic_run_id}/summary` | `get_summary` |
| `GET` | `/runs/{traffic_run_id}/events` | `get_events` |
| `GET` | `/runs/{traffic_run_id}/ping-samples` | `get_ping_samples` |
| `POST` | `/runs/{traffic_run_id}/cancel` | `cancel_run` |
| `POST` | `/runs/{traffic_run_id}/retry` | `retry_run` |
| `WEBSOCKET` | `/ws/traffic/{traffic_run_id}` | `traffic_events_socket` |

### vehicle_mr_online_router

[实现](../../src/netconsole/backend/api/vehicle_mr_online_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/trains` | `trains` |
| `GET` | `/trains/{train_id}` | `train_detail` |
| `GET` | `/mappings` | `mappings` |
| `POST` | `/mappings/import/preview` | `preview_mapping_import` |
| `GET` | `/controllers` | `controllers` |
| `GET` | `/trains/{train_id}/events` | `events` |
| `POST` | `/collection/start` | `start_collection` |
| `POST` | `/collection/{task_id}/stop` | `stop_collection` |
| `POST` | `/refresh` | `refresh` |
| `POST` | `/ap-mapping/refresh` | `refresh_ap_mapping` |
| `PUT` | `/mappings` | `save_mappings` |
| `POST` | `/mappings/template/export` | `export_mapping_template` |
| `GET` | `/mappings/template/artifacts/{artifact_id}/download` | `download_mapping_template` |
| `POST` | `/history/export` | `export_history` |
| `GET` | `/history/artifacts/{artifact_id}/download` | `download_history` |
| `GET` | `/tasks/{task_id}` | `task` |
| `POST` | `/tasks/{task_id}/cancel` | `cancel_task` |
| `POST` | `/tasks/recover` | `recover_tasks` |

### wireless_dashboard_router

[实现](../../src/netconsole/backend/api/wireless_dashboard_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `` | `dashboard` |
| `GET` | `/summary` | `summary` |
| `GET` | `/infrastructure` | `infrastructure` |
| `GET` | `/trains` | `trains` |
| `GET` | `/alerts` | `alerts` |
| `GET` | `/freshness` | `freshness` |
| `GET` | `/recent-operations` | `recent_operations` |
| `GET` | `/analysis` | `analysis` |

### wps_sync_router

[实现](../../src/netconsole/backend/api/wps_sync_router.py)

| 方法 | Router 路径 | 处理函数 |
| --- | --- | --- |
| `GET` | `/targets` | `list_targets` |
| `PUT` | `/targets/{target_code}` | `update_target` |
| `POST` | `/targets/{target_code}/connection-test` | `connection_test` |
| `POST` | `/targets/{target_code}/runtime-write-probe` | `runtime_write_probe` |
| `POST` | `/targets/{target_code}/migrate-legacy-binding` | `migrate_legacy_binding` |
| `POST` | `/targets/{target_code}/sync-test-sheet` | `sync_test_sheet` |
| `POST` | `/targets/{target_code}/sheet-tab-color-probe` | `sheet_tab_color_probe` |
| `POST` | `/targets/{target_code}/column-width-probe` | `column_width_probe` |
| `POST` | `/targets/{target_code}/revalidate-deployment` | `revalidate_deployment` |
| `POST` | `/sync` | `sync` |
| `GET` | `/batches/recent` | `recent_batches` |

## 前端入口与状态

### 页面与业务组件

- [views/DashboardView.vue](../../apps/desktop_renderer/src/views/DashboardView.vue)
- [views/StorageManagementView.vue](../../apps/desktop_renderer/src/views/StorageManagementView.vue)
- [views/ac-management/AcManagementView.vue](../../apps/desktop_renderer/src/views/ac-management/AcManagementView.vue)
- [views/ac-management/AcOmniPeekExportDialog.vue](../../apps/desktop_renderer/src/views/ac-management/AcOmniPeekExportDialog.vue)
- [views/ac-management/AcWebParityView.vue](../../apps/desktop_renderer/src/views/ac-management/AcWebParityView.vue)
- [views/command-reference/CommandReferenceView.vue](../../apps/desktop_renderer/src/views/command-reference/CommandReferenceView.vue)
- [views/config-collection/ConfigCollectionView.vue](../../apps/desktop_renderer/src/views/config-collection/ConfigCollectionView.vue)
- [views/console/ConsoleCommandBar.vue](../../apps/desktop_renderer/src/views/console/ConsoleCommandBar.vue)
- [views/console/ConsoleWorkspaceView.vue](../../apps/desktop_renderer/src/views/console/ConsoleWorkspaceView.vue)
- [views/console/TerminalPane.vue](../../apps/desktop_renderer/src/views/console/TerminalPane.vue)
- [views/console/TerminalQuickConnectDialog.vue](../../apps/desktop_renderer/src/views/console/TerminalQuickConnectDialog.vue)
- [views/console/TerminalReplaySearch.vue](../../apps/desktop_renderer/src/views/console/TerminalReplaySearch.vue)
- [views/console/TerminalSerialConnectDialog.vue](../../apps/desktop_renderer/src/views/console/TerminalSerialConnectDialog.vue)
- [views/console/TerminalSettingsDialog.vue](../../apps/desktop_renderer/src/views/console/TerminalSettingsDialog.vue)
- [views/console/TerminalSftpPanel.vue](../../apps/desktop_renderer/src/views/console/TerminalSftpPanel.vue)
- [views/devices/DeviceDetailView.vue](../../apps/desktop_renderer/src/views/devices/DeviceDetailView.vue)
- [views/devices/DeviceManagementView.vue](../../apps/desktop_renderer/src/views/devices/DeviceManagementView.vue)
- [views/file-management/DeviceDiagnosticDownloadView.vue](../../apps/desktop_renderer/src/views/file-management/DeviceDiagnosticDownloadView.vue)
- [views/file-management/FileManagementView.vue](../../apps/desktop_renderer/src/views/file-management/FileManagementView.vue)
- [views/file-management/FileManagerSyncDialog.vue](../../apps/desktop_renderer/src/views/file-management/FileManagerSyncDialog.vue)
- [views/file-management/FileManagerWorkspaceView.vue](../../apps/desktop_renderer/src/views/file-management/FileManagerWorkspaceView.vue)
- [views/file-management/FileWorkspacePanel.vue](../../apps/desktop_renderer/src/views/file-management/FileWorkspacePanel.vue)
- [views/job-center/DeviceTaskCreateDialog.vue](../../apps/desktop_renderer/src/views/job-center/DeviceTaskCreateDialog.vue)
- [views/job-center/DeviceTaskResultDialog.vue](../../apps/desktop_renderer/src/views/job-center/DeviceTaskResultDialog.vue)
- [views/job-center/JobCenterView.vue](../../apps/desktop_renderer/src/views/job-center/JobCenterView.vue)
- [views/network-tools/LocalNetworkServicesView.vue](../../apps/desktop_renderer/src/views/network-tools/LocalNetworkServicesView.vue)
- [views/network-tools/NetworkToolsView.vue](../../apps/desktop_renderer/src/views/network-tools/NetworkToolsView.vue)
- [views/network-tools/TrafficTestView.vue](../../apps/desktop_renderer/src/views/network-tools/TrafficTestView.vue)
- [views/network-tools/WirelessScanView.vue](../../apps/desktop_renderer/src/views/network-tools/WirelessScanView.vue)
- [views/rail-transit/AcMeshLinkPage.vue](../../apps/desktop_renderer/src/views/rail-transit/AcMeshLinkPage.vue)
- [views/rail-transit/ArchivePage.vue](../../apps/desktop_renderer/src/views/rail-transit/ArchivePage.vue)
- [views/rail-transit/DeepCollectionPage.vue](../../apps/desktop_renderer/src/views/rail-transit/DeepCollectionPage.vue)
- [views/rail-transit/DeepTasksPage.vue](../../apps/desktop_renderer/src/views/rail-transit/DeepTasksPage.vue)
- [views/rail-transit/GroundUnattendedView.vue](../../apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.vue)
- [views/rail-transit/HeartbeatPage.vue](../../apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.vue)
- [views/rail-transit/HeartbeatSettings.vue](../../apps/desktop_renderer/src/views/rail-transit/HeartbeatSettings.vue)
- [views/rail-transit/MeshAnalysisView.vue](../../apps/desktop_renderer/src/views/rail-transit/MeshAnalysisView.vue)
- [views/rail-transit/OnlineMrAnalysisView.vue](../../apps/desktop_renderer/src/views/rail-transit/OnlineMrAnalysisView.vue)
- [views/rail-transit/OnlineMrRealtimeView.vue](../../apps/desktop_renderer/src/views/rail-transit/OnlineMrRealtimeView.vue)
- [views/rail-transit/OverviewPage.vue](../../apps/desktop_renderer/src/views/rail-transit/OverviewPage.vue)
- [views/rail-transit/QuickPingPage.vue](../../apps/desktop_renderer/src/views/rail-transit/QuickPingPage.vue)
- [views/rail-transit/RailTransitBaseDataView.vue](../../apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.vue)
- [views/rail-transit/RailTransitInfrastructureView.vue](../../apps/desktop_renderer/src/views/rail-transit/RailTransitInfrastructureView.vue)
- [views/rail-transit/RailTransitWirelessDashboardView.vue](../../apps/desktop_renderer/src/views/rail-transit/RailTransitWirelessDashboardView.vue)
- [views/rail-transit/SettingsPage.vue](../../apps/desktop_renderer/src/views/rail-transit/SettingsPage.vue)
- [views/rail-transit/SyslogPage.vue](../../apps/desktop_renderer/src/views/rail-transit/SyslogPage.vue)
- [views/rail-transit/SystemHealthPage.vue](../../apps/desktop_renderer/src/views/rail-transit/SystemHealthPage.vue)
- [views/rail-transit/TimelinePage.vue](../../apps/desktop_renderer/src/views/rail-transit/TimelinePage.vue)
- [views/rail-transit/TracksideApBusinessView.vue](../../apps/desktop_renderer/src/views/rail-transit/TracksideApBusinessView.vue)
- [views/rail-transit/TracksideApWpsConfigDialog.vue](../../apps/desktop_renderer/src/views/rail-transit/TracksideApWpsConfigDialog.vue)
- [views/rail-transit/VehicleMrOnlineView.vue](../../apps/desktop_renderer/src/views/rail-transit/VehicleMrOnlineView.vue)
- [views/settings/RetiredFeatureDeliveryView.vue](../../apps/desktop_renderer/src/views/settings/RetiredFeatureDeliveryView.vue)
- [views/settings/SiteSSHRelayPanel.vue](../../apps/desktop_renderer/src/views/settings/SiteSSHRelayPanel.vue)
- [views/settings/SiteStoragePanel.vue](../../apps/desktop_renderer/src/views/settings/SiteStoragePanel.vue)
- [views/settings/SystemSettingsView.vue](../../apps/desktop_renderer/src/views/settings/SystemSettingsView.vue)
- [views/system/ServiceLogsPanel.vue](../../apps/desktop_renderer/src/views/system/ServiceLogsPanel.vue)
- [views/system/SystemMaintenanceView.vue](../../apps/desktop_renderer/src/views/system/SystemMaintenanceView.vue)
- [views/system/TaskLogsPanel.vue](../../apps/desktop_renderer/src/views/system/TaskLogsPanel.vue)
- [views/tools/NetworkComponentsView.vue](../../apps/desktop_renderer/src/views/tools/NetworkComponentsView.vue)
- [views/tools/ToolCollectionView.vue](../../apps/desktop_renderer/src/views/tools/ToolCollectionView.vue)
- [views/tools/components/ExternalToolCard.vue](../../apps/desktop_renderer/src/views/tools/components/ExternalToolCard.vue)
- [views/tools/components/ExternalToolCategoryDialog.vue](../../apps/desktop_renderer/src/views/tools/components/ExternalToolCategoryDialog.vue)
- [views/tools/components/ExternalToolEditorDialog.vue](../../apps/desktop_renderer/src/views/tools/components/ExternalToolEditorDialog.vue)

### 状态容器

- [stores/acManagement.ts](../../apps/desktop_renderer/src/stores/acManagement.ts)
- [stores/deviceManagement.ts](../../apps/desktop_renderer/src/stores/deviceManagement.ts)
- [stores/externalTools.ts](../../apps/desktop_renderer/src/stores/externalTools.ts)
- [stores/onlineMr.ts](../../apps/desktop_renderer/src/stores/onlineMr.ts)
- [stores/onlineMrAnalysis.ts](../../apps/desktop_renderer/src/stores/onlineMrAnalysis.ts)
- [stores/openPageTabs.ts](../../apps/desktop_renderer/src/stores/openPageTabs.ts)
- [stores/railInfrastructure.ts](../../apps/desktop_renderer/src/stores/railInfrastructure.ts)
- [stores/railTransitBaseData.ts](../../apps/desktop_renderer/src/stores/railTransitBaseData.ts)
- [stores/siteContext.ts](../../apps/desktop_renderer/src/stores/siteContext.ts)
- [stores/tasks.ts](../../apps/desktop_renderer/src/stores/tasks.ts)
- [stores/traffic.ts](../../apps/desktop_renderer/src/stores/traffic.ts)
- [stores/workspace.ts](../../apps/desktop_renderer/src/stores/workspace.ts)

### API 客户端

- [api/acManagement.ts](../../apps/desktop_renderer/src/api/acManagement.ts)
- [api/acMeshLink.ts](../../apps/desktop_renderer/src/api/acMeshLink.ts)
- [api/acWebParity.ts](../../apps/desktop_renderer/src/api/acWebParity.ts)
- [api/client.ts](../../apps/desktop_renderer/src/api/client.ts)
- [api/commandReference.ts](../../apps/desktop_renderer/src/api/commandReference.ts)
- [api/configCollection.ts](../../apps/desktop_renderer/src/api/configCollection.ts)
- [api/databaseUpgrades.ts](../../apps/desktop_renderer/src/api/databaseUpgrades.ts)
- [api/deviceCompatibility.ts](../../apps/desktop_renderer/src/api/deviceCompatibility.ts)
- [api/deviceManagement.ts](../../apps/desktop_renderer/src/api/deviceManagement.ts)
- [api/deviceOperations.ts](../../apps/desktop_renderer/src/api/deviceOperations.ts)
- [api/externalTools.ts](../../apps/desktop_renderer/src/api/externalTools.ts)
- [api/features.ts](../../apps/desktop_renderer/src/api/features.ts)
- [api/fileManagement.ts](../../apps/desktop_renderer/src/api/fileManagement.ts)
- [api/fileWorkspace.ts](../../apps/desktop_renderer/src/api/fileWorkspace.ts)
- [api/groundUnattended.ts](../../apps/desktop_renderer/src/api/groundUnattended.ts)
- [api/localNetworkServices.ts](../../apps/desktop_renderer/src/api/localNetworkServices.ts)
- [api/meshAnalysis.ts](../../apps/desktop_renderer/src/api/meshAnalysis.ts)
- [api/meshHttpTrace.ts](../../apps/desktop_renderer/src/api/meshHttpTrace.ts)
- [api/networkTools.ts](../../apps/desktop_renderer/src/api/networkTools.ts)
- [api/onlineMr.ts](../../apps/desktop_renderer/src/api/onlineMr.ts)
- [api/onlineMrControl.ts](../../apps/desktop_renderer/src/api/onlineMrControl.ts)
- [api/railInfrastructure.ts](../../apps/desktop_renderer/src/api/railInfrastructure.ts)
- [api/railRelationships.ts](../../apps/desktop_renderer/src/api/railRelationships.ts)
- [api/railTransitBaseData.ts](../../apps/desktop_renderer/src/api/railTransitBaseData.ts)
- [api/railTransitWeb.ts](../../apps/desktop_renderer/src/api/railTransitWeb.ts)
- [api/siteStorage.ts](../../apps/desktop_renderer/src/api/siteStorage.ts)
- [api/storageAudit.ts](../../apps/desktop_renderer/src/api/storageAudit.ts)
- [api/systemMaintenance.ts](../../apps/desktop_renderer/src/api/systemMaintenance.ts)
- [api/systemSettings.ts](../../apps/desktop_renderer/src/api/systemSettings.ts)
- [api/tasks.ts](../../apps/desktop_renderer/src/api/tasks.ts)
- [api/terminal.ts](../../apps/desktop_renderer/src/api/terminal.ts)
- [api/tracksideApBusiness.ts](../../apps/desktop_renderer/src/api/tracksideApBusiness.ts)
- [api/traffic.ts](../../apps/desktop_renderer/src/api/traffic.ts)
- [api/trainCommunication.ts](../../apps/desktop_renderer/src/api/trainCommunication.ts)
- [api/vehicleMrOnline.ts](../../apps/desktop_renderer/src/api/vehicleMrOnline.ts)
- [api/wirelessDashboard.ts](../../apps/desktop_renderer/src/api/wirelessDashboard.ts)

## SQLite 声明

| 所有者 | 源码中声明的表 |
| --- | --- |
| [data_root_configuration.py](../../src/netconsole/core/data_root_configuration.py) | `validation` |
| [database.py](../../src/netconsole/core/database.py) | `ac_ap_summary`, `ac_fit_ap_details`, `ac_fit_ap_lldp_history`, `ac_fit_ap_metadata`, `ac_fit_ap_optical`, `ac_fit_ap_optical_history`, `ac_fit_ap_radio_details`, `ac_fit_ap_radio_history`, `ac_fit_ap_resource_history`, `ac_fit_ap_resources`, `ac_fit_ap_unauthenticated`, `ac_fit_ap_unauthenticated_history`, `ac_fit_ap_unauthenticated_summary`, `ac_station_ap_capacity`, `ac_station_online_summary_history`, `ac_trackside_ap_plan`, `ac_trackside_ap_plan_settings`, `ap_entities`, `ap_extension_import_batches`, `ap_extension_points`, `ap_identity_conflicts`, `ap_identity_entities`, `ap_identity_h3c_prefixes`, `ap_identity_index_state`, `ap_identity_mac_aliases`, `ap_identity_radio_evidence`, `ap_identity_source_state`, `ap_lldp_history`, `ap_optical_history`, `ap_optical_treatment`, `ap_optical_treatment_events`, `ap_resource_snapshots`, `collect_runs`, `config_snapshots`, `device_fact_recent`, `device_fact_retention_meta`, `device_facts`, `device_facts_history`, `device_groups`, `device_interface_retention_meta`, `device_interfaces`, `device_interfaces_history`, `device_lldp_neighbors`, `device_lldp_neighbors_history`, `device_lldp_retention_meta`, `device_optical_modules`, `device_optical_modules_history`, `device_optical_retention_meta`, `devices`, `fit_ap_lldp_current`, `fit_ap_lldp_history`, `fit_ap_lldp_retention_meta`, `fit_ap_radio_current`, `fit_ap_radio_history`, `fit_ap_radio_retention_meta`, `fit_ap_resource_recent`, `fit_ap_resource_retention_meta`, `fit_ap_unauthenticated_recent`, `fit_ap_unauthenticated_retention_meta`, `optical_current`, `optical_history`, `optical_retention_meta`, `rail_ap_vlan_allocations`, `rail_ap_vlan_allocations_reference_migration`, `rail_ap_vlan_assignments`, `rail_ap_vlan_group_members`, `rail_ap_vlan_groups`, `rail_ap_vlan_plans`, `schema_metadata`, `station_online_summary_current`, `station_online_summary_recent`, `station_online_summary_retention_meta`, `trackside_ap_view_cache` |
| [device_credential_store.py](../../src/netconsole/core/device_credential_store.py) | `device_credential_states` |
| [rail_infrastructure_schema.py](../../src/netconsole/core/rail_infrastructure_schema.py) | `rail_infra_ac_service`, `rail_infra_device_link`, `rail_infra_device_project`, `rail_infra_device_section`, `rail_infra_node`, `rail_infra_node_layout`, `rail_infra_node_name`, `rail_infra_node_project`, `rail_infra_project`, `rail_infra_relation_audit`, `rail_infra_relation_history`, `rail_infra_relation_state`, `rail_infra_train`, `rail_infra_train_mr` |
| [ground_arp_repository.py](../../src/netconsole/repositories/ground_arp_repository.py) | `ground_arp_collections`, `ground_arp_observations`, `ground_mr_identity_conflicts`, `ground_mr_identity_relations` |
| [ground_unattended_repository.py](../../src/netconsole/repositories/ground_unattended_repository.py) | `ground_unattended_ac_basic_controls`, `ground_unattended_ac_deltas`, `ground_unattended_ac_snapshots`, `ground_unattended_archives`, `ground_unattended_boot_sessions`, `ground_unattended_daily_queues`, `ground_unattended_deep_operations`, `ground_unattended_delete_operations`, `ground_unattended_events`, `ground_unattended_health_events`, `ground_unattended_heartbeat_config`, `ground_unattended_heartbeat_inventory_state`, `ground_unattended_heartbeat_states`, `ground_unattended_mr_runtime_states`, `ground_unattended_operations`, `ground_unattended_ping_loss_intervals`, `ground_unattended_ping_segments`, `ground_unattended_ping_summaries`, `ground_unattended_ping_target_activations`, `ground_unattended_position_reconciliations`, `ground_unattended_priority_trains`, `ground_unattended_profiles`, `ground_unattended_quick_ping_events`, `ground_unattended_quick_ping_ip_reservations`, `ground_unattended_quick_ping_runs`, `ground_unattended_quick_ping_stats`, `ground_unattended_quick_ping_target_runtime`, `ground_unattended_radio_correlations`, `ground_unattended_radio_interface_states`, `ground_unattended_raw_files`, `ground_unattended_run_sessions`, `ground_unattended_runs`, `ground_unattended_runs_v17`, `ground_unattended_schema`, `ground_unattended_syslog_config_audits`, `ground_unattended_syslog_position_states`, `ground_unattended_train_endpoints`, `ground_unattended_train_inventory`, `ground_unattended_train_policies`, `ground_unattended_train_runs`, `ground_unattended_wmesh_events` |
| [history_store.py](../../src/netconsole/repositories/history_store.py) | `history_catalog`, `history_entities_v2`, `history_event_provenance_v2`, `history_event_provenance_v2_compact`, `history_event_types_v2`, `history_events`, `history_events_v2`, `history_kinds_v2`, `history_migration_journal`, `history_migration_skips`, `history_outbox`, `history_payload_schemas_v2`, `history_state`, `history_storage_metadata`, `schema_metadata` |
| [host_key_repository.py](../../src/netconsole/repositories/host_key_repository.py) | `host_key_events`, `host_key_history`, `host_key_records`, `host_key_schema_meta` |
| [mesh_catalog_schema.py](../../src/netconsole/repositories/mesh_catalog_schema.py) | `mesh_catalog_index_state`, `mesh_session_index`, `mesh_source_fingerprints`, `mesh_source_lifecycle`, `mesh_source_lifecycle_events`, `mr_profiles`, `schema_meta` |
| [mesh_mr_repository.py](../../src/netconsole/repositories/mesh_mr_repository.py) | `active_points`, `active_segments`, `diagnosis_events`, `mesh_links`, `mesh_peer_mapping`, `mesh_peer_resolve_cache`, `mesh_sessions`, `meta`, `parse_issues`, `rssi_stats`, `samples`, `schema_meta`, `source_files`, `switch_events` |
| [online_mr_diagnosis_repository.py](../../src/netconsole/repositories/online_mr_diagnosis_repository.py) | `active_segment_metrics`, `active_segments`, `analysis_events`, `channel_busy_records`, `fping_1s_summary`, `fping_samples`, `interface_rate_samples`, `iperf_intervals`, `iperf_runs`, `main_link_samples`, `online_identity_metadata`, `online_parse_issues`, `online_parse_metadata`, `online_schema_meta`, `radio_statistics_samples`, `switch_history_events`, `switch_realtime_events`, `time_sync_samples` |
| [online_mr_task_session_repository.py](../../src/netconsole/repositories/online_mr_task_session_repository.py) | `online_mr_task_session_schema`, `online_mr_task_sessions` |
| [task_cleanup_schema.py](../../src/netconsole/repositories/task_cleanup_schema.py) | `task_retention_tombstones` |
| [task_repository.py](../../src/netconsole/repositories/task_repository.py) | `task_events`, `task_result_blobs`, `task_result_storage_rollout`, `task_result_storage_rollout_audit`, `task_results`, `task_retention_tombstones`, `task_schema_meta`, `task_snapshots` |
| [traffic_run_repository.py](../../src/netconsole/repositories/traffic_run_repository.py) | `traffic_agent_tasks`, `traffic_ping_samples`, `traffic_runs`, `traffic_schema_meta` |
| [wireless_scan_repository.py](../../src/netconsole/repositories/wireless_scan_repository.py) | `wireless_scan_results`, `wireless_scan_runs` |
| [wps_sync_repository.py](../../src/netconsole/repositories/wps_sync_repository.py) | `wps_credentials`, `wps_sync_batches`, `wps_sync_target_runs`, `wps_sync_targets` |
| [mesh_log_analysis_service.py](../../src/netconsole/services/mesh_log_analysis_service.py) | `imported_files`, `parse_issues`, `records`, `switch_events` |
| [iperf_runner.py](../../src/netconsole/services/network_tools/iperf_runner.py) | `iperf_intervals`, `iperf_runs` |
| [event_db_writer.py](../../src/netconsole/services/online_mr/db/event_db_writer.py) | `event_stream` |
| [online_mr_session_store.py](../../src/netconsole/services/online_mr_session_store.py) | `collector_logs`, `iperf_intervals`, `iperf_runs`, `live_channel_busy`, `live_events`, `live_interface_rates`, `live_mesh_links`, `live_radio_statistics_raw_index`, `live_samples`, `live_switch_history_latest`, `live_terminal_events`, `ping_samples`, `ping_summary` |
| [runtime_self_check_service.py](../../src/netconsole/services/runtime_self_check_service.py) | `probe` |
| [site_ssh_relay.py](../../src/netconsole/services/site_ssh_relay.py) | `site_credentials` |
| [vehicle_mr_online.py](../../src/netconsole/services/vehicle_mr_online.py) | `vehicle_mr_online_links`, `vehicle_mr_online_sessions`, `vehicle_mr_online_snapshots`, `vehicle_mr_train_current_state`, `vehicle_mr_train_mapping`, `vehicle_mr_train_pass_events` |
| [mr_db.py](../../src/netconsole/storage/mr_db.py) | `mr_samples` |

## 启动与交付

- [API 挂载及功能门](../../src/netconsole/backend/api/router.py)
- [业务服务组装](../../src/netconsole/backend/api/main.py)
- [Vue 路由](../../apps/desktop_renderer/src/router/routes.ts)
- [导航及兼容元数据](../../apps/desktop_renderer/src/navigation/registry.ts)
- [受管 Backend 进程](../../apps/desktop_electron/src/main/backend-manager.ts)
- [安装事务与日志](../../apps/desktop_electron/build/installer-data-root.nsh)
- [测试分层和隔离](../testing/BASELINE.md)
- [发布功能矩阵](../release/PACKAGED_FEATURE_MATRIX.md)
