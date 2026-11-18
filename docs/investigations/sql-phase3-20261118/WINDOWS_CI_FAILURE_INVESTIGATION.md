# PR #121 Windows CI Failure Investigation

## Scope

- CI Run: `44142115842`
- Python Job: `134247385669`
- Business HEAD investigated: `d37f98609b61763b49504610343562e1d50d6c14`
- Original result: `11 failed, 5584 passed, 4 skipped, 34 warnings`
- No SQL business code was changed by this stability repair.

## Failure Matrix

| Test | Failure stage | Evidence and classification |
| --- | --- | --- |
| `tests/test_ac_mesh_link_resident_polling.py::test_interval_update_and_immediate_refresh_do_not_reconnect` | test | `PermissionError` while reading `status.json` during atomic replacement; transient Windows file-handle race. |
| `tests/test_command_reference_web_api.py::test_command_reference_export_uses_public_store_and_safe_download_name` | setup | `WinError 5` moving staged Demo; `devices.db` was still in the staged tree. Demo seed move lifecycle. |
| `tests/test_desktop_runtime_contract.py::test_disabled_web_page_cannot_bypass_backend_feature_gate[...]` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_ground_unattended_api.py::test_ground_raw_file_and_operation_ignore_future_additive_columns` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_ground_unattended_api.py::test_syslog_delete_api_previews_blocks_and_queues_one_scoped_job` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_ground_unattended_api.py::test_syslog_records_http_api_accepts_multi_value_mr_role_filter` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_ground_unattended_api.py::test_ground_unattended_repository_failure_is_feature_scoped` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_ground_unattended_history_archive_query.py::test_status_separates_service_active_and_latest_run_and_downloads_artifact` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_ground_unattended_ui_read_models.py::test_syslog_sort_paginates_actual_receive_time_without_altering_raw` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |
| `tests/test_iperf_network_tools.py::test_snapshot_replace_retries_permission_error` | test | CI observed `replace_calls == 6` vs expected `2`; local reproduction passed 20 consecutive runs, so no stable business defect is established. |
| `tests/test_system_settings_web_api.py::test_runtime_self_check_returns_safe_unicode_and_release_contract` | setup | Same Demo seed `WinError 5/32`; not a SQL regression. |

The CI log showed no runner timeout. The Python step completed normally after 30:54, with `BASELINE_EXCLUSIONS=0` and `PYTHON_REGRESSION_NEW_FAILURES=UNKNOWN exit=1`.

## Resource-Lifecycle Findings

1. Resident status readers could collide with the worker's Windows `os.replace()` window. The worker now uses unique temporary names, bounded retries for lock errors (`WinError 5/32`), and cleanup of the temporary file. The regression helper reads status with the same bounded retry contract.
2. Test-root cleanup previously attempted one recursive delete after `gc.collect()`. It now retries only the owned test roots with bounded delays and raises a diagnostic error after the final attempt. Cleanup remains idempotent and does not delete unrelated paths.
3. Demo seed publication and rollback moved an SQLite-backed directory with no retry around short Windows handle windows. Owned Demo moves now use the same bounded lock retry helper. SQLite finalization still closes connections before publication.
4. Resident polling already closes the AC connection in `finally`; the local resident suite passed without an orphan-task or connection leak. No production or development database was touched.

## iPerf Investigation

The failing iPerf assertion is independent of the Phase 3 SQL diff. The same node passed 20 consecutive local runs on the current branch. The implementation and assertion were not weakened or skipped; the CI observation remains recorded as not reproduced.

## Repair Diff

- `tests/conftest.py`: bounded owned-root cleanup retry and idempotent teardown.
- `src/netconsole/services/ac/mesh_link_resident_polling_service.py`: bounded status read/atomic-write retries and unique temporary files.
- `tests/test_ac_mesh_link_resident_polling.py`: status-read regression helper tolerant of the documented replace window.
- `src/netconsole/services/site_lifecycle.py`: bounded `os.rename()` retry for owned Demo publication and rollback moves; avoids `shutil.move()` copy fallback and partial trees.
- `tests/test_site_lifecycle.py`: transient Windows move-lock regression test.
- `docs/investigations/sql-phase3-20261118/SQL_PHASE3_VALIDATION_REPORT.md`: CI failure and current stability status.

## Validation Before New CI

- Original 11 failure nodes: `11 passed` in one focused run.
- Resident polling suite: `8 passed`.
- iPerf failure node: `20` consecutive focused runs passed.
- Lifecycle/API related suite: `136 passed, 2 warnings`.
- Combined resident/iPerf/lifecycle regression after repair: `59 passed`.
- Ruff: PASS.
- SQL Phase 3 business code: unchanged.
- `PRODUCTION_DATA_MODIFIED=0`.
- `DATABASES_REMOVED=0`.

## Current Gate

The repair is local-only until a new GitHub CI run validates the pushed commit. Current acceptance remains `BLOCKED_SQL_PHASE3_CI_STABILITY`; PR #121 is not mergeable until all Required Checks pass on the new HEAD and Codex Review covers that HEAD.
