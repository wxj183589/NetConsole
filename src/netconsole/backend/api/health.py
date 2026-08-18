from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.core.storage_manifest import CURRENT_STORAGE_SCHEMA_VERSION
from netconsole.core.version import APP_VERSION
from netconsole.models.api import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    sites = request.app.state.site_application_service
    metadata = dict(getattr(request.app.state, "build_metadata", {}) or {})
    feature_gate = getattr(request.app.state, "feature_gate", None)
    return health_response(
        str(request.app.state.backend_build_id),
        data_root=str(request.app.state.paths.data_root),
        active_site_id=sites.active_site_id(),
        storage_schema_version=CURRENT_STORAGE_SCHEMA_VERSION,
        backend_commit=str(metadata.get("backend_commit") or "unknown"),
        frontend_commit=str(getattr(request.app.state, "frontend_commit", "unknown") or "unknown"),
        commit_sha_short=str(metadata.get("git_commit_short") or "unknown"),
        edition=str(getattr(feature_gate, "edition", "dev") or "dev"),
        packaged_dirty=bool(metadata.get("build_dirty", True)),
        build_timestamp=str(metadata.get("build_time_utc") or ""),
        runtime_services_status=str(getattr(request.app.state, "runtime_services_status", "ready")),
        runtime_services_ready=bool(getattr(request.app.state, "runtime_services_ready", True)),
        runtime_services_error=str(getattr(request.app.state, "runtime_services_error", "")),
        performance_mode=str(getattr(request.app.state, "performance_mode", "standard")),
        unattended_status=str(getattr(request.app.state, "unattended_status", "disabled")),
        unattended_ready=bool(getattr(request.app.state, "unattended_ready", False)),
        unattended_error=str(getattr(request.app.state, "unattended_error", "")),
        history_status=str(getattr(request.app.state, "history_status", "idle")),
        history_pending=int(getattr(request.app.state, "history_pending", 0)),
        history_error=str(getattr(request.app.state, "history_error", "")),
        history_oldest_pending_age_seconds=int(
            getattr(request.app.state, "history_oldest_pending_age_seconds", 0)
        ),
        history_pressure=str(getattr(request.app.state, "history_pressure", "normal")),
        history_last_drain_elapsed_ms=int(getattr(request.app.state, "history_last_drain_elapsed_ms", 0)),
        history_last_drain_written=int(getattr(request.app.state, "history_last_drain_written", 0)),
        history_budget_overrun=bool(getattr(request.app.state, "history_budget_overrun", False)),
    )


def health_response(
    build_id: str,
    *,
    data_root: str = "",
    active_site_id: str = "",
    storage_schema_version: int = CURRENT_STORAGE_SCHEMA_VERSION,
    backend_commit: str = "unknown",
    frontend_commit: str = "unknown",
    commit_sha_short: str = "unknown",
    edition: str = "dev",
    packaged_dirty: bool = True,
    build_timestamp: str = "",
    runtime_services_status: str = "ready",
    runtime_services_ready: bool = True,
    runtime_services_error: str = "",
    performance_mode: str = "standard",
    unattended_status: str = "disabled",
    unattended_ready: bool = False,
    unattended_error: str = "",
    history_status: str = "idle",
    history_pending: int = 0,
    history_error: str = "",
    history_oldest_pending_age_seconds: int = 0,
    history_pressure: str = "normal",
    history_last_drain_elapsed_ms: int = 0,
    history_last_drain_written: int = 0,
    history_budget_overrun: bool = False,
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=APP_VERSION.removeprefix("v"),
        build_id=build_id,
        backend_commit=backend_commit,
        frontend_commit=frontend_commit,
        commit_sha_short=commit_sha_short,
        edition=edition,
        packaged_dirty=packaged_dirty,
        build_timestamp=build_timestamp,
        data_root=data_root,
        active_site_id=active_site_id,
        storage_schema_version=storage_schema_version,
        runtime_services_status=runtime_services_status,
        runtime_services_ready=runtime_services_ready,
        runtime_services_error=runtime_services_error,
        performance_mode=performance_mode,
        unattended_status=unattended_status,
        unattended_ready=unattended_ready,
        unattended_error=unattended_error,
        history_status=history_status,
        history_pending=max(0, int(history_pending)),
        history_error=history_error,
        history_oldest_pending_age_seconds=max(0, int(history_oldest_pending_age_seconds)),
        history_pressure=history_pressure,
        history_last_drain_elapsed_ms=max(0, int(history_last_drain_elapsed_ms)),
        history_last_drain_written=max(0, int(history_last_drain_written)),
        history_budget_overrun=bool(history_budget_overrun),
    )
