from __future__ import annotations

from collections.abc import Mapping
from threading import Event

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.rail_transit.trackside_optical_collection import (
    classify_trackside_skipped,
    collect_trackside_optical,
)
from netconsole.services.trackside_ap_export_service import (
    load_trackside_ap_business_snapshot,
    require_complete_trackside_snapshot,
)


def run_trackside_ap_optical_update(context: JobContext) -> dict[str, object]:
    """执行 Qt 轨旁 AP“轻量更新”同一套采集与持久化服务。"""

    site_id = str(context.params.get("site_name") or "").strip()
    if not site_id:
        raise ValueError("轨旁 AP 更新缺少局点")
    database = Database(context.params["db_path"])
    repository = DeviceRepository(database)
    snapshot = load_trackside_ap_business_snapshot(repository, site_id, generation=0)
    require_complete_trackside_snapshot(snapshot, "轨旁 AP 光衰更新")
    cancel_event = Event()

    def cancelled_progress(current: int, total: int, details: Mapping[str, object] | None = None) -> None:
        if context.should_cancel is not None and context.should_cancel():
            cancel_event.set()
            context.check_cancelled()
        if isinstance(details, Mapping):
            payload = dict(details)
            stage = str(payload.pop("stage", "") or "trackside_ap_optical_update")
            message = str(payload.pop("message", "") or "正在更新轨旁 AP 光衰")
            context.structured_progress(stage, current, total, message, **payload)
            return
        context.progress("trackside_ap_optical_update", current, total, "正在更新轨旁 AP 光衰")

    def stage_progress(stage: str, message: str | None = None, details: Mapping[str, object] | None = None) -> None:
        payload = dict(details or {})
        payload.pop("message", None)
        context.structured_progress(
            stage,
            0,
            0,
            str(message or "正在更新轨旁 AP 光衰"),
            **payload,
        )

    result = collect_trackside_optical(
        repository,
        site_id,
        context.paths,
        snapshot.rows,
        cancel_event=cancel_event,
        progress_callback=cancelled_progress,
        stage_callback=stage_progress,
        target_station=str(context.params.get("station") or "") or None,
        target_ap_uuid=str(context.params.get("ap_uuid") or "") or None,
        target_ap_mac=str(context.params.get("ap_mac") or "") or None,
        target_ap_name=str(context.params.get("ap_name") or "") or None,
        concurrency=context.params.get("concurrency"),
    )
    if int(result.fit_ap_optical_success_count or 0) > 0:
        ApIdentityQueryService(database).rebuild_index(
            "trackside_ap_optical_refresh_succeeded"
        )
    switch_results = list(getattr(result, "results", []) or [])
    station_switch_total = int(getattr(result, "station_switch_total", len(switch_results)) or 0)
    fit_ap_total = int(getattr(result, "fit_ap_total", getattr(result, "fit_ap_resource_count", 0)) or 0)
    skipped_items = list(getattr(result, "skipped", []) or [])
    fallback_actionable, fallback_ignored, fallback_reason_counts = classify_trackside_skipped(skipped_items)
    actionable_skipped_count = int(getattr(result, "actionable_skipped_count", fallback_actionable) or 0)
    ignored_skipped_count = int(getattr(result, "ignored_skipped_count", fallback_ignored) or 0)
    skipped_reason_counts = dict(getattr(result, "skipped_reason_counts", fallback_reason_counts) or {})
    switch_failed_count = sum(1 for item in switch_results if not item.success)
    switch_success_count = max(station_switch_total - switch_failed_count, 0)
    fit_ap_skipped_count = sum(
        1
        for item in skipped_items
        if str(getattr(item, "target_type", "") or "").upper() in {"AP", "FIT_AP", "AC"}
    )
    failure_reason_counts = dict(
        getattr(result, "failure_reason_counts", {}) or {}
    )
    if not failure_reason_counts:
        failure_reason_counts = {
            key: value
            for key, value in {
                "device_collection_failed": switch_failed_count,
                "fit_ap_collection_failed": max(int(result.failed_count or 0) - switch_failed_count, 0),
            }.items()
            if value > 0
        }
    warning_count = int(getattr(result, "warning_count", 0) or 0)
    warning_reason_counts = dict(
        getattr(result, "warning_reason_counts", {}) or {}
    )
    warnings = [str(value) for value in (getattr(result, "warnings", []) or [])]
    persistence_errors = [dict(value) for value in (getattr(result, "persistence_errors", []) or [])]
    port_errors = [
        dict(value)
        for value in (getattr(result, "port_errors", []) or [])
        if isinstance(value, Mapping)
    ]
    failures = [
        dict(value)
        for value in (getattr(result, "failures", []) or [])
        if isinstance(value, Mapping)
    ]
    return {
        "session_id": result.session_id,
        "status": result.status,
        "terminal_state": _task_terminal_state(result.status),
        "scope": result.scope,
        "target_label": result.target_label,
        "success_count": result.success_count,
        "failed_count": result.failed_count,
        "skipped_count": result.skipped_count,
        "actionable_skipped_count": actionable_skipped_count,
        "ignored_skipped_count": ignored_skipped_count,
        "skipped_reason_counts": skipped_reason_counts,
        "skipped": [_skipped_payload(item) for item in skipped_items],
        "target_count": result.target_count,
        "switch_total": station_switch_total,
        "switch_success_count": switch_success_count,
        "switch_failed_count": switch_failed_count,
        "fit_ap_total": fit_ap_total,
        "fit_ap_success_count": result.fit_ap_optical_success_count,
        "fit_ap_failed_count": result.fit_ap_optical_failed_count,
        "fit_ap_skipped_count": fit_ap_skipped_count,
        "failure_reason_counts": failure_reason_counts,
        "failures": failures,
        "warning_count": warning_count,
        "warning_reason_counts": warning_reason_counts,
        "has_warning": warning_count > 0,
        "error_code": "TRACKSIDE_PERSISTENCE_FAILED" if persistence_errors else "",
        "error_message": (
            "; ".join(
                f"{item.get('stage')}: {item.get('exception_type')} "
                f"{item.get('sqlite_errorname') or item.get('message') or ''} "
                f"rows={item.get('rows_attempted')} db={item.get('db_path')}"
                for item in persistence_errors
            )
            if persistence_errors
            else ""
        ),
        "persistence_errors": persistence_errors,
        "warnings": warnings,
        "port_errors": port_errors,
        "concurrency": result.concurrency,
        "requested_concurrency": result.requested_concurrency,
        "effective_concurrency": result.effective_concurrency,
        "platform_concurrency_limit": result.platform_concurrency_limit,
        "fit_ap_effective_concurrency": result.fit_ap_effective_concurrency,
        "round_summaries": [dict(row) for row in result.fit_ap_round_summaries],
        "fit_ap_resource_count": result.fit_ap_resource_count,
        "fit_ap_optical_success_count": result.fit_ap_optical_success_count,
        "fit_ap_optical_failed_count": result.fit_ap_optical_failed_count,
        "fit_ap_resource_failed_count": int(getattr(result, "fit_ap_resource_failed_count", 0) or 0),
        "candidate_ap_interface_count": result.candidate_ap_interface_count,
        "current_lldp_port_count": result.current_lldp_port_count,
        "preserved_lldp_port_count": result.preserved_lldp_port_count,
    }


def _task_terminal_state(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized == "FAILED":
        return "FAILED"
    if normalized == "CANCELLED":
        return "CANCELLED"
    return "COMPLETED"


def _skipped_payload(item: object) -> dict[str, str]:
    return {
        "name": str(getattr(item, "name", "") or ""),
        "target_type": str(getattr(item, "target_type", "") or ""),
        "reason": str(getattr(item, "reason", "") or ""),
        "host": str(getattr(item, "host", "") or ""),
    }


__all__ = ["run_trackside_ap_optical_update"]
