from __future__ import annotations

from collections.abc import Mapping

from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.handlers.common import legacy_handler
from netconsole.services.rail_transit.car_network_diagnostic_job import run_car_network_diagnostic
from netconsole.services.rail_transit.switch_vendor_sample_job import (
    run_switch_vendor_sample_collect,
)
from netconsole.services.rail_transit.trackside_ap_update_job import run_trackside_ap_optical_update
from netconsole.services.rail_transit.vehicle_mr_online_collection_job import run_vehicle_mr_online_collection
from netconsole.services.wps_trackside_ap_sync import TracksideApWpsSyncService, WPS_SYNC_TASK_TYPE

trackside_interface_history_page = legacy_handler(legacy_tasks._trackside_interface_history_page)
car_network_point_table_import = legacy_handler(legacy_tasks._car_network_point_table_import)
car_network_point_table_load = legacy_handler(legacy_tasks._car_network_point_table_load)
car_network_refresh_all = legacy_handler(legacy_tasks._car_network_refresh_all)
car_network_generate_point_table = legacy_handler(legacy_tasks._car_network_generate_point_table)
car_network_save_point_table = legacy_handler(legacy_tasks._car_network_save_point_table)
trackside_ap_plan_import = legacy_handler(legacy_tasks._trackside_ap_plan_import)
trackside_ap_plan_refresh = legacy_handler(legacy_tasks._trackside_ap_plan_refresh)
trackside_ap_plan_save = legacy_handler(legacy_tasks._trackside_ap_plan_save)
trackside_device_detail_resolve = legacy_handler(legacy_tasks._trackside_device_detail_resolve)
trackside_fit_ap_detail_resolve = legacy_handler(legacy_tasks._trackside_fit_ap_detail_resolve)

HANDLERS = {
    name: globals()[name]
    for name in (
        "trackside_interface_history_page",
        "car_network_point_table_import",
        "car_network_point_table_load",
        "car_network_refresh_all",
        "car_network_generate_point_table",
        "car_network_save_point_table",
        "trackside_ap_plan_import",
        "trackside_ap_plan_refresh",
        "trackside_ap_plan_save",
        "trackside_device_detail_resolve",
        "trackside_fit_ap_detail_resolve",
    )
}
HANDLERS.update(
    {
        "car_network_diagnostic": run_car_network_diagnostic,
        "switch_vendor_sample_collect": run_switch_vendor_sample_collect,
        "trackside_ap_optical_update": run_trackside_ap_optical_update,
        "vehicle_mr_online_collection_start": run_vehicle_mr_online_collection,
    }
)


_WPS_TERMINAL_TEXT_LIMIT = 512
_WPS_TERMINAL_BATCH_FIELDS = (
    "status",
    "batch_id",
    "site_id",
    "business_key",
    "snapshot_revision",
    "snapshot_sha256",
    "content_sha256",
    "snapshot_generated_at",
    "payload_bytes",
    "sheet_count",
    "target_count",
    "success_count",
    "failed_count",
    "unknown_count",
    "warning_count",
    "partial_success",
)
_WPS_TERMINAL_TARGET_FIELDS = (
    "target_code",
    "target_name",
    "target_type",
    "target_batch_id",
    "status",
    "phase",
    "success",
    "error_code",
    "message",
    "site_id",
    "site_name",
    "business_key",
    "snapshot_revision",
    "snapshot_sha256",
    "target_sync_executed_at",
    "artifact_id",
    "artifact_name",
    "artifact_state",
    "artifact_message",
    "artifact_ready",
    "available",
    "sha256",
    "size_bytes",
    "remote_document_id",
    "remote_task_id_masked",
    "remote_task_type",
    "remote_task_status",
    "remote_task_submitted_at",
    "remote_task_last_polled_at",
    "remote_task_finished_at",
    "remote_script_version",
    "runtime_capability",
    "written_object_count",
    "written_row_count",
    "written_sheet_count",
    "format_warning_count",
    "warning_count",
    "http_status",
)


def _wps_terminal_scalar(value: object) -> tuple[bool, object]:
    if isinstance(value, str):
        if len(value) > _WPS_TERMINAL_TEXT_LIMIT:
            return True, value[:_WPS_TERMINAL_TEXT_LIMIT] + "..."
        return True, value
    if isinstance(value, (bool, int, float)) or value is None:
        return True, value
    return False, None


def _wps_terminal_fields(
    source: Mapping[str, object],
    fields: tuple[str, ...],
) -> dict[str, object]:
    values: dict[str, object] = {}
    for key in fields:
        if key not in source:
            continue
        present, value = _wps_terminal_scalar(source[key])
        if present:
            values[key] = value
    return values


def _wps_terminal_summary(result: Mapping[str, object]) -> dict[str, object]:
    """Keep Worker terminal output small while WPS stores the full batch result."""

    summary = {
        "terminal_result_version": 1,
        **_wps_terminal_fields(result, _WPS_TERMINAL_BATCH_FIELDS),
    }
    targets = result.get("targets")
    if isinstance(targets, list):
        compact_targets: list[dict[str, object]] = []
        for target in targets:
            if not isinstance(target, Mapping):
                continue
            compact = _wps_terminal_fields(target, _WPS_TERMINAL_TARGET_FIELDS)
            query_error = target.get("remote_query_error")
            if isinstance(query_error, Mapping):
                compact_query_error = _wps_terminal_fields(
                    query_error,
                    ("code", "message"),
                )
                if compact_query_error:
                    compact["remote_query_error"] = compact_query_error
            compact_targets.append(compact)
        summary["targets"] = compact_targets
    return summary


def trackside_ap_wps_sync(context):
    """在 Job Center Worker 中冻结一次快照并同步 WPS 云文档。"""

    context.check_cancelled()
    target_codes = tuple(
        str(value)
        for value in (context.params.get("target_codes") or ())
        if str(value).strip()
    )
    service = TracksideApWpsSyncService(context.paths)
    result = service.sync(
        str(context.params.get("site_name") or ""),
        target_codes=target_codes,
        expected_revision=str(context.params.get("expected_revision") or ""),
        initialize_binding=bool(context.params.get("initialize_binding")),
        progress=context.progress,
        should_cancel=context.check_cancelled,
    )
    context.check_cancelled()
    business_status = str(result.get("status") or "").upper()
    # The service has already persisted the complete batch/target result in the
    # WPS repository. Only the bounded operational summary crosses Worker IPC.
    terminal_result = _wps_terminal_summary(result)
    if business_status in {"FAILED", "REMOTE_RESULT_UNKNOWN"}:
        # An ambiguous submit has no remote task ID to poll in this process, and
        # a terminal WPS failure must remain a local failure. Keep the WPS batch
        # resumable where supported, but never let JobRunner's normal-return path
        # turn either business state into a completed local task.
        terminal_result["terminal_state"] = "FAILED"
        terminal_result["completion_message"] = (
            "WPS 远端提交结果未确认，任务未完成；已保留恢复信息，请稍后重试查询。"
            if business_status == "REMOTE_RESULT_UNKNOWN"
            else "WPS 云文档同步失败，请查看任务详情中的远端错误和恢复信息。"
        )
    return terminal_result


HANDLERS[WPS_SYNC_TASK_TYPE] = trackside_ap_wps_sync
