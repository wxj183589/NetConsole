from __future__ import annotations

from threading import Event

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.rail_transit.trackside_optical_collection import collect_trackside_optical
from netconsole.services.trackside_ap_export_service import load_trackside_ap_business_snapshot


def run_trackside_ap_optical_update(context: JobContext) -> dict[str, object]:
    """执行 Qt 轨旁 AP“轻量更新”同一套采集与持久化服务。"""

    site_id = str(context.params.get("site_name") or "").strip()
    if not site_id:
        raise ValueError("轨旁 AP 更新缺少局点")
    repository = DeviceRepository(Database(context.params["db_path"]))
    snapshot = load_trackside_ap_business_snapshot(repository, site_id, generation=0)
    cancel_event = Event()

    def cancelled_progress(current: int, total: int) -> None:
        if context.should_cancel is not None and context.should_cancel():
            cancel_event.set()
            context.check_cancelled()
        context.progress("trackside_ap_optical_update", current, total, "正在更新轨旁 AP 光衰")

    result = collect_trackside_optical(
        repository,
        site_id,
        context.paths,
        snapshot.rows,
        cancel_event=cancel_event,
        progress_callback=cancelled_progress,
        stage_callback=lambda stage: context.progress(stage, 0, 0, stage),
        target_station=str(context.params.get("station") or "") or None,
        target_ap_uuid=str(context.params.get("ap_uuid") or "") or None,
        target_ap_mac=str(context.params.get("ap_mac") or "") or None,
        target_ap_name=str(context.params.get("ap_name") or "") or None,
    )
    return {
        "session_id": result.session_id,
        "status": result.status,
        "terminal_state": _task_terminal_state(result.status),
        "scope": result.scope,
        "target_label": result.target_label,
        "success_count": result.success_count,
        "failed_count": result.failed_count,
        "skipped_count": result.skipped_count,
        "target_count": result.target_count,
        "concurrency": result.concurrency,
        "requested_concurrency": result.requested_concurrency,
        "effective_concurrency": result.effective_concurrency,
        "platform_concurrency_limit": result.platform_concurrency_limit,
        "fit_ap_effective_concurrency": result.fit_ap_effective_concurrency,
        "round_summaries": [dict(row) for row in result.fit_ap_round_summaries],
        "fit_ap_resource_count": result.fit_ap_resource_count,
        "fit_ap_optical_success_count": result.fit_ap_optical_success_count,
        "fit_ap_optical_failed_count": result.fit_ap_optical_failed_count,
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


__all__ = ["run_trackside_ap_optical_update"]
