from __future__ import annotations

import asyncio
import html
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from netconsole.application.ac.web_application_service import AcWebApplicationService
from netconsole.application.desktop import DesktopActionResolver, DesktopActionService
from netconsole.application.device_detail import DeviceDetailApplicationService
from netconsole.application.rail_transit.mesh_bundle_application_service import MeshBundleApplicationService
from netconsole.application.rail_transit.mesh_local_scan_application_service import MeshLocalScanApplicationService
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService
from netconsole.application.system_maintenance import SystemMaintenanceApplicationService
from netconsole.application.web_artifacts import WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.backend.api.router import api_router, ws_router
from netconsole.core import app_logger
from netconsole.core.log_policy import LOG_POLICY
from netconsole.backend.web_build import (
    FRONTEND_MISMATCH_MESSAGE,
    backend_build_id,
    frontend_build_id,
    read_frontend_build_meta,
)
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.resources import package_resource_path
from netconsole.core.runtime_environment import is_packaged_runtime
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.runtime_profile import (
    RuntimeCapabilityPolicy,
    read_host_environment_profile,
    read_runtime_performance_mode,
)
from netconsole.core.sites import SiteManager
from netconsole.core.version import APP_NAME, APP_VERSION
from netconsole.infrastructure.desktop import LocalDesktopAdapter, UnavailableDesktopAdapter
from netconsole.models.api.common import ErrorDetail, ErrorResponse
from netconsole.repositories.device_detail_repository import DeviceDetailRepository
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.mesh_link_refresh_service import AcMeshLinkRefreshApplicationService
from netconsole.services.ac.mesh_link_resident_polling_service import (
    AcMeshLinkResidentPollingApplicationService,
)
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.agent.controller import AgentControllerError, AgentControllerService
from netconsole.services.config_collection_web_service import ConfigCollectionApplicationService
from netconsole.services.command_reference_application_service import CommandReferenceApplicationService
from netconsole.services.device_management_web_service import DeviceManagementWebService
from netconsole.services.device_compatibility.service import DeviceCompatibilityService
from netconsole.services.device_detail_query_service import DeviceDetailQueryService
from netconsole.services.device_operation_service import DeviceOperationService
from netconsole.services.file_management_service import FileManagementApplicationService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.history_store import HistoryStore
from netconsole.services.network_tools.application_service import NetworkToolsApplicationService
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade
from netconsole.services.online_mr.errors import OnlineMrQueryError, OnlineMrQueryErrorCode
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.agent_controller_service import OnlineMrAgentControllerService
from netconsole.services.online_mr.agent_web_control_service import OnlineMrAgentWebControlService
from netconsole.services.online_mr.errors import OnlineMrWebControlError
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.web_control_service import OnlineMrWebControlService
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard, WRITE_FEATURE_ID
from netconsole.application.rail_transit.base_data_application_service import RailTransitBaseDataApplicationService
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService
from netconsole.services.rail_transit.station_source_discovery_service import StationSourceDiscoveryService
from netconsole.services.rail_transit.station_template_service import StationTemplateService
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService
from netconsole.services.rail_transit.trackside_ap_business_query_service import TracksideApBusinessQueryService
from netconsole.services.rail_transit.vehicle_mr_online_query_service import VehicleMrOnlineQueryService
from netconsole.services.rail_transit.wireless_dashboard_query_service import WirelessDashboardQueryService
from netconsole.services.wps_trackside_ap_sync import TracksideApWpsSyncService
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError
from netconsole.services.traffic.web_application_service import TrafficWebApplicationService
from netconsole.services.settings_application_service import SettingsApplicationService
from netconsole.services.database_upgrade.management_service import DatabaseUpgradeManagementService
from netconsole.services.database_upgrade.journal import recover_incomplete_upgrades
from netconsole.services.runtime_self_check_service import RuntimeSelfCheckService
from netconsole.services.system_network_application_service import (
    SystemNetworkApplicationService,
)
from netconsole.services.site_lifecycle import (
    DemoSiteSeedService,
    SiteAuditService,
    SiteCleanupApplicationService,
)
from netconsole.services.site_retention import SiteRetentionService
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
    SiteRegistryRepository,
    SiteStorageError,
)


_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)")
_SECRET_RE = re.compile(r"(?i)((?:x-agent-token|token)\s*[:=]\s*)[^\s,;]+")
DESKTOP_SESSION_COOKIE = "netconsole_desktop_session"
DESKTOP_SESSION_HEADER = "x-netconsole-session"
_DESKTOP_DEFERRED_RUNTIME_DELAY_SECONDS = 1.0
_HISTORY_DRAIN_INITIAL_DELAY_SECONDS = 5.0
_HISTORY_DRAIN_NORMAL_INTERVAL_SECONDS = 10.0
_HISTORY_DRAIN_UNATTENDED_INTERVAL_SECONDS = 60.0


def _unattended_run_active(repository: GroundUnattendedRepository | None) -> bool:
    """Maintenance pauses only for a persisted active unattended run."""

    return bool(repository is not None and repository.get_active_run())


class DesktopSessionMiddleware:
    def __init__(self, app, *, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in {"http", "websocket"} or scope.get("path") == "/__desktop_session":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied_header = headers.get(DESKTOP_SESSION_HEADER.encode("ascii"), b"").decode(
            "ascii", errors="ignore"
        )
        cookie = SimpleCookie()
        cookie.load(headers.get(b"cookie", b"").decode("latin-1"))
        supplied = cookie.get(DESKTOP_SESSION_COOKIE)
        header_authenticated = bool(supplied_header) and secrets.compare_digest(
            supplied_header, self.token
        )
        cookie_authenticated = supplied is not None and secrets.compare_digest(
            supplied.value, self.token
        )
        if header_authenticated or cookie_authenticated:
            scope.setdefault("state", {})["desktop_session_authenticated"] = True
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401, "reason": "desktop session required"})
            return
        content = (
            {
                "ok": False,
                "error": {
                    "code": "ONLINE_MR_WEB_AUTH_REQUIRED",
                    "message": "当前请求缺少主程序短期 WebHost 会话",
                    "details": {},
                },
            }
            if str(scope.get("path") or "").startswith(
                ("/api/rail-transit/online-mr-control", "/api/rail-transit/online-mr-agent")
            )
            else {"detail": "desktop session required"}
        )
        response = JSONResponse(status_code=401, content=content)
        await response(scope, receive, send)


class DesktopShutdownAdmissionMiddleware:
    """Reject new mutating desktop requests once controlled shutdown begins."""

    def __init__(self, app, *, state) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}
            and not bool(getattr(self.state, "accepting_work", True))
        ):
            response = JSONResponse(
                status_code=503,
                content={"detail": "NetConsole 正在安全退出，暂不接受新的后台操作"},
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RuntimeServicesAdmissionMiddleware:
    """Reject service-dependent writes while deferred runtime services are unavailable."""

    _PREFIXES = (
        "/api/agents",
        "/api/traffic",
        "/api/file-management",
        "/api/online-mr-control",
        "/api/online-mr-agent",
        "/api/rail-transit/online-mr-control",
        "/api/rail-transit/online-mr-agent",
        "/api/rail-transit/ground-unattended",
    )

    def __init__(self, app, *, state) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}
            and str(scope.get("path") or "").startswith(self._PREFIXES)
            and not bool(getattr(self.state, "runtime_services_ready", False))
            and str(getattr(self.state, "runtime_services_status", "starting")) != "stopping"
        ):
            status = str(getattr(self.state, "runtime_services_status", "starting"))
            degraded = status == "degraded"
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "运行服务初始化失败，当前处于降级状态"
                    if degraded
                    else "运行服务正在初始化",
                    "code": "RUNTIME_SERVICES_DEGRADED"
                    if degraded
                    else "RUNTIME_SERVICES_NOT_READY",
                    "runtime_services_status": status,
                },
                headers={"Retry-After": "2"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(
    runtime_mode: RuntimeMode = RuntimeMode.SERVER,
    *,
    paths: PathResolver | None = None,
    task_service: TaskApplicationService | None = None,
    desktop_action_service: DesktopActionService | None = None,
    agent_service: AgentControllerService | None = None,
    traffic_service: TrafficTestApplicationService | None = None,
    ac_mesh_link_refresh_service: AcMeshLinkRefreshApplicationService | None = None,
    ac_mesh_link_resident_service: AcMeshLinkResidentPollingApplicationService
    | None = None,
    frontend_dist: Path | None = None,
    desktop_session_token: str | None = None,
    rail_base_data_write_feature_enabled: bool | None = None,
    rail_base_data_desktop_write_enabled: bool | None = None,
    online_mr_application_service: OnlineMrApplicationService | None = None,
    online_mr_web_control_service: OnlineMrWebControlService | None = None,
    online_mr_web_control_enabled: bool | None = None,
    online_mr_agent_web_control_service: OnlineMrAgentWebControlService | None = None,
    online_mr_agent_executor_enabled: bool | None = None,
    api_documentation_enabled: bool | None = None,
    development_api_enabled: bool = False,
    development_runtime_label: str = "development",
    development_frontend_mode: str = "dist",
    startup_stage: Callable[[str], None] | None = None,
) -> FastAPI:
    paths = paths or PathResolver()
    host_profile = read_host_environment_profile(paths.host_environment_profile_path)
    performance_mode = read_runtime_performance_mode(paths.settings_path)
    capability_policy = RuntimeCapabilityPolicy.from_profile(host_profile, mode=performance_mode)
    _emit_startup_stage(startup_stage, "upgrade_recovery_started")
    for recovered_upgrade in recover_incomplete_upgrades(paths):
        app_logger.log_warning(
            "DATABASE_UPGRADE_RECOVERED",
            f"operation={recovered_upgrade.get('operation_id')} stage={recovered_upgrade.get('stage')}",
        )
    _emit_startup_stage(startup_stage, "upgrade_recovery_complete")
    _emit_startup_stage(startup_stage, "active_site_resolving")
    site_name = _current_site_name(paths, startup_stage=startup_stage)
    _emit_startup_stage(startup_stage, "active_site_resolved")
    _emit_startup_stage(startup_stage, "application_services_initializing")
    defer_runtime_start = bool(runtime_mode is RuntimeMode.DESKTOP and desktop_session_token)
    if online_mr_web_control_enabled is None:
        online_mr_web_control_enabled = os.environ.get("ONLINE_MR_WEB_CONTROL_ENABLED", "0") == "1"
    online_mr_web_control_enabled = bool(
        online_mr_web_control_enabled
        and runtime_mode is RuntimeMode.DESKTOP
        and desktop_session_token
    )
    if online_mr_agent_executor_enabled is None:
        online_mr_agent_executor_enabled = (
            os.environ.get("ONLINE_MR_AGENT_EXECUTOR_ENABLED", "0") == "1"
        )
    online_mr_agent_executor_enabled = bool(
        online_mr_agent_executor_enabled
        and runtime_mode is RuntimeMode.DESKTOP
        and desktop_session_token
    )
    if task_service is None:
        task_service = TaskApplicationService(
            paths=paths,
            site_name=site_name,
            reconcile_on_start=not defer_runtime_start,
        )
    if agent_service is None:
        agent_service = AgentControllerService(paths=paths, site_name=site_name)
    if traffic_service is None:
        traffic_service = TrafficTestApplicationService(
            paths=paths,
            site_name=site_name,
            task_service=task_service,
            agent_controller=agent_service,
            reconcile_on_start=not defer_runtime_start,
        )
    if ac_mesh_link_refresh_service is None:
        ac_mesh_link_refresh_service = AcMeshLinkRefreshApplicationService(paths, task_service)
    if desktop_action_service is None:
        desktop_action_service = DesktopActionService(
            runtime_mode,
            LocalDesktopAdapter()
            if runtime_mode is RuntimeMode.DESKTOP
            else UnavailableDesktopAdapter(),
            DesktopActionResolver(
                controlled_roots=(paths.app_root, paths.data_root),
                directories={
                    f"config_snapshots:{site_name}": paths.config_center_snapshots_root(site_name),
                    f"config_exports:{site_name}": paths.config_center_outputs_dir(site_name),
                    "system_logs": paths.logs_dir,
                    "system_cache": paths.runtime_cache_dir,
                },
            ),
        )
    feature_gate = FeatureGate(paths.app_root, runtime_path=paths.runtime_dir)
    ground_unattended_feature_enabled = feature_gate.is_enabled("module.ground_unattended")
    if (
        ground_unattended_feature_enabled
        and ac_mesh_link_resident_service is None
    ):
        ac_mesh_link_resident_service = (
            AcMeshLinkResidentPollingApplicationService(paths, task_service)
        )
    resident_binder = getattr(
        ac_mesh_link_refresh_service, "bind_resident_service", None
    )
    if callable(resident_binder):
        resident_binder(ac_mesh_link_resident_service)
    web_process_adapter = LocalProcessAdapter(task_service)
    history_store = HistoryStore(
        paths.site_db_path(site_name),
        site_id=site_name,
        history_root=paths.site_history_dir(site_name),
    )
    site_application_service = SiteApplicationService(paths, task_service)
    data_root_application_service = DataRootApplicationService(paths, site_application_service)
    site_package_service = SitePackageService(paths, site_application_service)
    web_export_adapter = WebExportProcessAdapter(task_service)
    web_artifact_store = WebArtifactStore(paths, task_service)
    system_maintenance_service = SystemMaintenanceApplicationService(
        paths,
        task_service,
        process_adapter=web_process_adapter,
        export_adapter=web_export_adapter,
        artifact_store=web_artifact_store,
        desktop_action_service=desktop_action_service,
    )
    ac_management_query_service = AcManagementQueryService(paths)
    online_mr_query_service = OnlineMrQueryService(paths)
    device_compatibility_service = DeviceCompatibilityService(paths)
    device_detail_gateway = DeviceDetailRepository(paths)
    device_operation_service = DeviceOperationService(
        paths,
        device_detail_gateway,
        task_service,
        web_process_adapter,
    )
    device_management_service = DeviceManagementWebService(
        paths,
        task_service,
        desktop_action_service=desktop_action_service,
        process_adapter=web_process_adapter,
        export_adapter=web_export_adapter,
        artifact_store=web_artifact_store,
        device_operation_service=device_operation_service,
    )
    config_collection_service = ConfigCollectionApplicationService(
        paths,
        task_service,
        process_adapter=web_process_adapter,
        desktop_action_service=desktop_action_service,
    )
    trackside_ap_business_query_service = TracksideApBusinessQueryService(paths)
    trackside_ap_wps_sync_service = TracksideApWpsSyncService(paths)
    device_detail_application_service = DeviceDetailApplicationService(
        DeviceDetailQueryService(
            device_detail_gateway,
            task_service,
            device_operation_service,
            config_reader=config_collection_service,
            business_reader=trackside_ap_business_query_service,
            ac_business_reader=ac_management_query_service,
            online_mr_reader=online_mr_query_service,
        ),
        device_operation_service,
    )
    file_management_service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=web_process_adapter,
        site_name=site_name,
        mesh_auto_import_enabled=feature_gate.is_enabled("file.mesh_auto_import"),
        desktop_action_service=desktop_action_service,
        device_operation_service=device_operation_service,
    )
    owns_online_mr_application_service = online_mr_application_service is None and (
        (ground_unattended_feature_enabled and runtime_mode is RuntimeMode.DESKTOP)
        or (
            online_mr_web_control_service is None
            and online_mr_agent_web_control_service is None
            and (online_mr_web_control_enabled or online_mr_agent_executor_enabled)
        )
    )
    if owns_online_mr_application_service:
        online_mr_application_service = OnlineMrApplicationService(
            paths,
            site_name=site_name,
            task_service=task_service,
            agent_profile_controller=agent_service,
        )

    ground_unattended_supervisor: GroundUnattendedSupervisor | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def start_unattended_services() -> bool:
            if not ground_unattended_feature_enabled:
                return True
            if ground_unattended_supervisor is None:
                app.state.unattended_ready = False
                app.state.unattended_status = "failed"
                app.state.unattended_error = (
                    app.state.ground_unattended_startup_error or "unavailable"
                )
                app_logger.log_error(
                    "UNATTENDED_SERVICE_FAILED",
                    "component=ground_unattended error=unavailable",
                )
                return False
            try:
                await asyncio.to_thread(ground_unattended_supervisor.start)
                app.state.unattended_ready = True
                app.state.unattended_status = "ready"
                app.state.unattended_error = ""
                return True
            except Exception as exc:
                app.state.unattended_ready = False
                app.state.unattended_status = "failed"
                app.state.unattended_error = exc.__class__.__name__
                app_logger.log_error(
                    "UNATTENDED_SERVICE_FAILED",
                    f"component=ground_unattended error={exc.__class__.__name__}: "
                    f"{_safe_error_message(str(exc))}",
                )
                return False

        async def start_deferred_runtime_services() -> None:
            try:
                # 先让 health、静态资源与首屏完成；历史任务恢复不参与桌面首屏关键路径。
                await asyncio.sleep(_DESKTOP_DEFERRED_RUNTIME_DELAY_SECONDS)
                if not app.state.accepting_work:
                    return
                reconcile_tasks = getattr(task_service, "reconcile_orphaned_local_tasks", None)
                if callable(reconcile_tasks):
                    await asyncio.to_thread(reconcile_tasks)
                await agent_service.start()
                reconcile_traffic = getattr(traffic_service, "reconcile_local_runs", None)
                if callable(reconcile_traffic):
                    await asyncio.to_thread(reconcile_traffic)
                await traffic_service.start()
                await asyncio.to_thread(file_management_service.start)
                unattended_started = (
                    app.state.unattended_status != "failed"
                    if capability_policy.unattended_priority
                    else await start_unattended_services()
                )
                app.state.runtime_services_ready = unattended_started
                app.state.runtime_services_status = "ready" if unattended_started else "degraded"
                if not unattended_started:
                    app.state.runtime_services_error = app.state.unattended_error or "unavailable"
            except Exception as exc:
                app.state.runtime_services_ready = False
                app.state.runtime_services_status = "degraded"
                app.state.runtime_services_error = exc.__class__.__name__
                app_logger.log_error(
                    "WEB_LIFESPAN_START_FAILED",
                    f"component=deferred_runtime error={exc.__class__.__name__}: {_safe_error_message(str(exc))}",
                )

        async def schedule_auto_cleanup() -> None:
            await asyncio.sleep(8)
            while True:
                try:
                    await asyncio.to_thread(
                        system_maintenance_service.start_cleanup,
                        site_name,
                        dry_run=False,
                        automatic=True,
                    )
                except Exception as exc:
                    app_logger.log_warning("APP_AUTO_CLEANUP_FAILED", _safe_error_message(str(exc)))
                await asyncio.sleep(LOG_POLICY.housekeeper.interval_seconds)

        async def schedule_history_drain() -> None:
            """Drain history independently from deferred runtime services."""

            await asyncio.sleep(_HISTORY_DRAIN_INITIAL_DELAY_SECONDS)
            while True:
                if not app.state.accepting_work:
                    return
                try:
                    diagnostics = await asyncio.to_thread(history_store.outbox_diagnostics)
                    app.state.history_pending = diagnostics.pending
                    app.state.history_oldest_pending_age_seconds = (
                        diagnostics.oldest_pending_age_seconds
                    )
                    app.state.history_pressure = diagnostics.pressure
                    if diagnostics.pressure == "degraded":
                        app.state.history_status = "degraded"
                    elif app.state.history_status == "idle":
                        app.state.history_status = "ready"
                except (OSError, sqlite3.Error) as exc:
                    app.state.history_status = "degraded"
                    app.state.history_error = exc.__class__.__name__
                try:
                    unattended_active = await asyncio.to_thread(
                        _unattended_run_active,
                        getattr(app.state, "ground_unattended_repository", None),
                    )
                    result = await asyncio.to_thread(
                        history_store.drain,
                        limit=100,
                        unattended_active=unattended_active,
                        max_elapsed_seconds=2.0 if unattended_active else None,
                    )
                    app.state.history_pending = result.pending
                    app.state.history_last_drain_elapsed_ms = result.elapsed_ms
                    app.state.history_last_drain_written = result.written
                    app.state.history_budget_overrun = result.budget_exceeded
                    app.state.history_oldest_pending_age_seconds = result.oldest_pending_age_seconds
                    app.state.history_pressure = result.pressure
                    app.state.history_status = "paused" if result.paused else (
                        "degraded" if result.degraded else "ready"
                    )
                    app.state.history_error = "" if not result.degraded else "shard_write_failed"
                    if result.degraded:
                        app_logger.log_warning(
                            "HISTORY_DRAIN_DEGRADED",
                            f"pending={result.pending} written={result.written}",
                        )
                    elif result.budget_exceeded:
                        app_logger.log_warning(
                            "HISTORY_DRAIN_BUDGET_OVERRUN",
                            f"elapsed_ms={result.elapsed_ms} written={result.written} pending={result.pending}",
                        )
                except (OSError, sqlite3.Error) as exc:
                    app.state.history_status = "degraded"
                    app.state.history_error = exc.__class__.__name__
                    app_logger.log_warning(
                        "HISTORY_DRAIN_DEGRADED",
                        f"error={exc.__class__.__name__}: {_safe_error_message(str(exc))}",
                    )
                await asyncio.sleep(
                    _HISTORY_DRAIN_UNATTENDED_INTERVAL_SECONDS
                    if _unattended_run_active(
                        getattr(app.state, "ground_unattended_repository", None)
                    )
                    else _HISTORY_DRAIN_NORMAL_INTERVAL_SECONDS
                )

        auto_cleanup_task = (
            asyncio.create_task(schedule_auto_cleanup())
            if (
                runtime_mode is RuntimeMode.DESKTOP
                and desktop_session_token
                and capability_policy.low_priority_work_enabled
            )
            else None
        )
        history_drain_task = asyncio.create_task(schedule_history_drain())
        deferred_start_task: asyncio.Task[None] | None = None
        try:
            if defer_runtime_start:
                # Server/unattended mode publishes health only after the
                # realtime receiver/supervisor can run. The remaining desktop
                # services stay deferred and cannot delay that readiness.
                if capability_policy.unattended_priority:
                    unattended_started = await start_unattended_services()
                    if not unattended_started:
                        app.state.runtime_services_ready = False
                        app.state.runtime_services_status = "degraded"
                        app.state.runtime_services_error = app.state.unattended_error or "unavailable"
                deferred_start_task = asyncio.create_task(start_deferred_runtime_services())
            else:
                unattended_started = await start_unattended_services()
                await agent_service.start()
                await traffic_service.start()
                file_management_service.start()
                app.state.runtime_services_ready = unattended_started
                app.state.runtime_services_status = "ready" if unattended_started else "degraded"
                if not unattended_started:
                    app.state.runtime_services_error = app.state.unattended_error or "unavailable"
            yield
        finally:
            app.state.runtime_services_status = "stopping"
            if app.state.unattended_ready:
                app.state.unattended_status = "stopping"
                app.state.unattended_ready = False
            app.state.accepting_work = False
            begin_shutdown = getattr(task_service, "begin_shutdown", None)
            if callable(begin_shutdown):
                begin_shutdown()
            if deferred_start_task is not None:
                deferred_start_task.cancel()
                await asyncio.gather(deferred_start_task, return_exceptions=True)
            if auto_cleanup_task is not None:
                auto_cleanup_task.cancel()
                await asyncio.gather(auto_cleanup_task, return_exceptions=True)
            history_drain_task.cancel()
            await asyncio.gather(history_drain_task, return_exceptions=True)
            if ground_unattended_supervisor is not None:
                try:
                    await asyncio.to_thread(ground_unattended_supervisor.close)
                except BaseException as exc:
                    app_logger.log_error(
                        "WEB_LIFESPAN_STOP_FAILED",
                        f"component=ground_unattended error={exc.__class__.__name__}: {exc}",
                    )
            try:
                # 文件下载队列必须先退出，之后才能关闭它共用的 LocalProcessAdapter。
                await asyncio.to_thread(file_management_service.close)
            except BaseException as exc:
                app_logger.log_error(
                    "WEB_LIFESPAN_STOP_FAILED",
                    f"component=file_management error={exc.__class__.__name__}: {exc}",
                )
            cleanup = await asyncio.gather(
                device_management_service.stop_exports(),
                asyncio.to_thread(web_export_adapter.shutdown),
                asyncio.to_thread(web_process_adapter.shutdown),
                ac_mesh_link_refresh_service.stop(),
                (
                    ac_mesh_link_resident_service.stop()
                    if ac_mesh_link_resident_service is not None
                    else asyncio.sleep(0)
                ),
                traffic_service.stop(),
                return_exceptions=True,
            )
            for component, result in zip(
                (
                    "device_exports",
                    "web_exports",
                    "local_process",
                    "ac_mesh_link",
                    "ac_mesh_link_resident",
                    "traffic",
                ),
                cleanup,
                strict=True,
            ):
                if isinstance(result, BaseException):
                    app_logger.log_error(
                        "WEB_LIFESPAN_STOP_FAILED",
                        f"component={component} error={result.__class__.__name__}: {result}",
                    )
            try:
                await agent_service.stop()
            except Exception as exc:
                app_logger.log_error(
                    "WEB_LIFESPAN_STOP_FAILED",
                    f"component=agent error={exc.__class__.__name__}: {exc}",
                )
            if owns_online_mr_application_service and online_mr_application_service is not None:
                try:
                    online_mr_application_service.close()
                except Exception as exc:
                    app_logger.log_error(
                        "WEB_LIFESPAN_STOP_FAILED",
                        f"component=online_mr error={exc.__class__.__name__}: {exc}",
                    )

    if api_documentation_enabled is None:
        api_documentation_enabled = runtime_mode is RuntimeMode.SERVER
    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION.removeprefix("v"),
        lifespan=lifespan,
        openapi_url="/openapi.json" if api_documentation_enabled else None,
        docs_url="/docs" if api_documentation_enabled else None,
        redoc_url="/redoc" if api_documentation_enabled else None,
    )
    app.state.runtime_mode = runtime_mode
    app.state.api_documentation_enabled = bool(api_documentation_enabled)
    app.state.development_api_enabled = bool(development_api_enabled)
    app.state.development_runtime_label = str(development_runtime_label)
    app.state.development_frontend_mode = str(development_frontend_mode)
    app.state.desktop_session_protected = bool(desktop_session_token)
    app.state.accepting_work = True
    app.add_middleware(DesktopShutdownAdmissionMiddleware, state=app.state)
    app.add_middleware(RuntimeServicesAdmissionMiddleware, state=app.state)
    app.state.online_mr_web_control_enabled = online_mr_web_control_enabled
    app.state.online_mr_agent_executor_enabled = online_mr_agent_executor_enabled
    app.state.runtime_services_ready = False
    app.state.runtime_services_status = "starting"
    app.state.runtime_services_error = ""
    app.state.history_status = "idle"
    app.state.history_pending = 0
    app.state.history_error = ""
    app.state.history_oldest_pending_age_seconds = 0
    app.state.history_pressure = "normal"
    app.state.history_last_drain_elapsed_ms = 0
    app.state.history_last_drain_written = 0
    app.state.history_budget_overrun = False
    app.state.history_store = history_store
    app.state.host_environment_profile = host_profile
    app.state.performance_mode = performance_mode.value
    app.state.capability_policy = capability_policy
    app.state.unattended_status = "starting" if ground_unattended_feature_enabled else "disabled"
    app.state.unattended_ready = False
    app.state.unattended_error = ""
    if host_profile is None:
        app_logger.log_info("HOST_ENVIRONMENT", "profile=unavailable")
    else:
        app_logger.log_info(
            "HOST_ENVIRONMENT",
            "profile=loaded "
            f"cpu_logical={getattr(host_profile.cpu.get('logical_processors'), 'value', 'unknown')} "
            f"hardware_raid={getattr(host_profile.storage.get('hardware_raid'), 'value', 'unknown')}",
        )
    app_logger.log_info(
        "RUNTIME_CAPABILITY_POLICY",
        f"mode={capability_policy.mode} cpu_workers={capability_policy.cpu_worker_limit} "
        f"disk_maintenance={capability_policy.disk_maintenance_concurrency} "
        f"unattended_priority={capability_policy.unattended_priority}",
    )
    app.state.paths = paths
    app.state.backend_build_id = backend_build_id(paths.app_root)
    app.state.task_service = task_service
    app.state.site_application_service = site_application_service
    app.state.data_root_application_service = data_root_application_service
    app.state.site_package_service = site_package_service
    app.state.site_audit_service = SiteAuditService(paths)
    app.state.site_cleanup_application_service = SiteCleanupApplicationService(
        paths, site_application_service
    )
    app.state.site_retention_service = SiteRetentionService(paths)
    app.state.site_process_adapter = web_process_adapter
    app.state.web_artifact_store = web_artifact_store
    app.state.desktop_action_service = desktop_action_service
    app.state.database_upgrade_management_service = DatabaseUpgradeManagementService(paths)
    app.state.feature_gate = feature_gate
    app.state.settings_application_service = SettingsApplicationService(paths, feature_gate, site_name)
    app.state.runtime_self_check_service = RuntimeSelfCheckService(
        paths,
        feature_gate,
        site_name,
    )
    app.state.system_network_application_service = SystemNetworkApplicationService()
    app.state.ac_management_query_service = ac_management_query_service
    app.state.ac_mesh_link_query_service = AcMeshLinkQueryService(paths)
    app.state.ac_mesh_link_refresh_service = ac_mesh_link_refresh_service
    app.state.job_center_query_service = JobCenterQueryService(
        paths,
        config_cancel_capability=config_collection_service.cancel_capability,
    )
    app.state.agent_service = agent_service
    app.state.traffic_service = traffic_service
    app.state.traffic_web_application_service = TrafficWebApplicationService(
        traffic_service,
        agent_service,
    )
    app.state.network_tools_service = NetworkToolsApplicationService(traffic_service)
    app.state.device_compatibility_service = device_compatibility_service
    app.state.device_management_service = device_management_service
    app.state.device_detail_application_service = device_detail_application_service
    app.state.config_collection_service = config_collection_service
    app.state.command_reference_application_service = CommandReferenceApplicationService(
        paths,
        task_service,
        web_export_adapter,
        web_artifact_store,
    )
    app.state.file_management_service = file_management_service
    app.state.system_maintenance_service = system_maintenance_service
    app.state.online_mr_query_service = online_mr_query_service
    app.state.rail_transit_base_data_query_service = RailTransitBaseDataQueryService(paths)
    app.state.online_mr_application_service = online_mr_application_service
    app.state.online_mr_web_control_service = online_mr_web_control_service or OnlineMrWebControlService(
        paths,
        online_mr_application_service,
        app.state.rail_transit_base_data_query_service,
        app.state.online_mr_query_service,
        enabled=online_mr_web_control_enabled,
    )
    app.state.online_mr_agent_web_control_service = (
        online_mr_agent_web_control_service
        or OnlineMrAgentWebControlService(
            paths,
            online_mr_application_service,
            app.state.online_mr_web_control_service,
            app.state.online_mr_query_service,
            OnlineMrAgentControllerService(paths, profile_controller=agent_service),
            enabled=online_mr_agent_executor_enabled,
        )
    )
    app.state.online_mr_api_facade = OnlineMrApiFacade(
        paths,
        app.state.online_mr_query_service,
        app.state.online_mr_web_control_service,
        app.state.online_mr_agent_web_control_service,
    )
    app.state.vehicle_mr_online_query_service = VehicleMrOnlineQueryService(
        paths,
        mesh_query=app.state.ac_mesh_link_query_service,
    )
    app.state.train_communication_query_service = TrainCommunicationQueryService(
        paths,
        base_query=app.state.rail_transit_base_data_query_service,
        mesh_query=app.state.ac_mesh_link_query_service,
        online_mr_query=app.state.online_mr_query_service,
        job_query=app.state.job_center_query_service,
        vehicle_online_query=app.state.vehicle_mr_online_query_service,
    )
    app.state.trackside_ap_business_query_service = trackside_ap_business_query_service
    app.state.trackside_ap_wps_sync_service = trackside_ap_wps_sync_service
    app.state.mesh_analysis_query_service = MeshAnalysisQueryService(
        paths,
        base_query=app.state.rail_transit_base_data_query_service,
    )
    app.state.wireless_dashboard_query_service = WirelessDashboardQueryService(
        paths,
        base_query=app.state.rail_transit_base_data_query_service,
        ac_query=app.state.ac_management_query_service,
        mesh_query=app.state.ac_mesh_link_query_service,
        train_query=app.state.train_communication_query_service,
        online_mr_query=app.state.online_mr_query_service,
        job_query=app.state.job_center_query_service,
        mesh_analysis_query=app.state.mesh_analysis_query_service,
        agent_service=agent_service,
    )
    if rail_base_data_write_feature_enabled is None:
        rail_base_data_write_feature_enabled = feature_gate.is_enabled(WRITE_FEATURE_ID)
    if rail_base_data_desktop_write_enabled is None:
        rail_base_data_desktop_write_enabled = runtime_mode is RuntimeMode.DESKTOP and bool(desktop_session_token)
    rail_base_data_write_guard = BaseDataWriteGuard(
        paths,
        feature_enabled=rail_base_data_write_feature_enabled,
        desktop_session_write_enabled=bool(
            rail_base_data_desktop_write_enabled
            and runtime_mode is RuntimeMode.DESKTOP
            and desktop_session_token
        ),
    )
    app.state.rail_transit_base_data_import_service = RailTransitBaseDataImportService(
        paths,
        guard=rail_base_data_write_guard,
    )
    app.state.rail_transit_base_data_application_service = RailTransitBaseDataApplicationService(
        paths,
        app.state.rail_transit_base_data_query_service,
        rail_base_data_write_guard,
    )
    app.state.rail_transit_station_source_discovery_service = StationSourceDiscoveryService(
        paths,
        app.state.rail_transit_base_data_query_service,
    )
    app.state.rail_transit_station_template_service = StationTemplateService(
        paths,
        app.state.rail_transit_base_data_query_service,
    )
    app.state.rail_transit_import_preview_service = RailTransitImportPreviewService(
        app.state.rail_transit_base_data_query_service,
        import_service=app.state.rail_transit_base_data_import_service,
    )
    app.state.ac_web_application_service = AcWebApplicationService(
        paths,
        task_service,
        process_adapter=web_process_adapter,
        import_preview_service=app.state.rail_transit_import_preview_service,
        base_import_service=app.state.rail_transit_base_data_import_service,
        export_adapter=web_export_adapter,
        artifact_store=web_artifact_store,
        desktop_action_service=desktop_action_service,
    )
    app.state.rail_transit_web_application_service = RailTransitWebApplicationService(
        paths,
        task_service,
        process_adapter=web_process_adapter,
        export_adapter=web_export_adapter,
        query_service=app.state.online_mr_query_service,
        mesh_query_service=app.state.mesh_analysis_query_service,
        vehicle_mr_online_query_service=app.state.vehicle_mr_online_query_service,
        artifact_store=web_artifact_store,
    )
    app.state.mesh_bundle_application_service = MeshBundleApplicationService(
        paths,
        task_service,
        web_process_adapter,
        app.state.rail_transit_base_data_query_service,
    )
    app.state.mesh_local_scan_application_service = MeshLocalScanApplicationService(
        paths,
        task_service,
        web_process_adapter,
        desktop_action_service,
    )
    app.state.ground_unattended_repository = None
    app.state.ground_unattended_supervisor = None
    app.state.ground_unattended_application_service = None
    app.state.ac_mesh_link_resident_service = ac_mesh_link_resident_service
    app.state.ground_unattended_startup_error = ""
    if ground_unattended_feature_enabled:
        try:
            ground_unattended_repository = GroundUnattendedRepository(
                paths.ground_unattended_db_path(site_name),
                site_id=site_name,
            )
            ground_ap_identity_query = ApIdentityQueryService(
                Database(paths.site_db_path(site_name))
            )
            ground_unattended_supervisor = GroundUnattendedSupervisor(
                paths,
                site_id=site_name,
                repository=ground_unattended_repository,
                base_query=app.state.rail_transit_base_data_query_service,
                mesh_query=app.state.ac_mesh_link_query_service,
                vehicle_query=app.state.vehicle_mr_online_query_service,
                ac_refresh_service=ac_mesh_link_refresh_service,
                ac_resident_service=ac_mesh_link_resident_service,
                online_mr_application_service=online_mr_application_service,
                online_mr_query_service=online_mr_query_service,
                network_service=app.state.system_network_application_service,
                ap_identity_query_service=ground_ap_identity_query,
            )
            app.state.ground_unattended_repository = ground_unattended_repository
            app.state.ground_unattended_supervisor = ground_unattended_supervisor
            app.state.ground_unattended_application_service = (
                GroundUnattendedApplicationService(
                    paths,
                    site_id=site_name,
                    repository=ground_unattended_repository,
                    supervisor=ground_unattended_supervisor,
                    base_query=app.state.rail_transit_base_data_query_service,
                    desktop_action_service=desktop_action_service,
                    network_service=app.state.system_network_application_service,
                    process_adapter=web_process_adapter,
                    ap_identity_query_service=ground_ap_identity_query,
                )
            )
        except Exception as exc:
            app.state.ground_unattended_startup_error = exc.__class__.__name__
            app.state.unattended_status = "failed"
            app.state.unattended_error = exc.__class__.__name__
            app_logger.log_error(
                "GROUND_UNATTENDED_START_FAILED",
                f"component=ground_unattended error={exc.__class__.__name__}: "
                f"{_safe_error_message(str(exc))}",
            )
    if desktop_session_token:
        app.add_middleware(DesktopSessionMiddleware, token=desktop_session_token)

        @app.post("/__desktop_session", include_in_schema=False)
        async def create_desktop_session(request: Request):
            form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
            supplied = str((form.get("token") or [""])[0])
            if not secrets.compare_digest(supplied, desktop_session_token):
                return JSONResponse(status_code=401, content={"detail": "invalid desktop session"})
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(
                DESKTOP_SESSION_COOKIE,
                desktop_session_token,
                httponly=True,
                samesite="strict",
            )
            return response

    @app.exception_handler(AgentControllerError)
    async def agent_error_handler(_: Request, exc: AgentControllerError) -> JSONResponse:
        payload = ErrorResponse(error=ErrorDetail(code=exc.code, message=exc.message))
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(TrafficTestError)
    async def traffic_error_handler(_: Request, exc: TrafficTestError) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorDetail(
                code=exc.code,
                message=_safe_error_message(exc.message),
                details={"retryable": exc.retryable},
            )
        )
        return JSONResponse(status_code=_traffic_error_status(exc.code), content=payload.model_dump(mode="json"))

    @app.exception_handler(OnlineMrQueryError)
    async def online_mr_query_error_handler(_: Request, exc: OnlineMrQueryError) -> JSONResponse:
        payload = ErrorResponse(error=ErrorDetail(code=exc.code, message=exc.message))
        return JSONResponse(status_code=_online_mr_query_error_status(exc.code), content=payload.model_dump(mode="json"))

    @app.exception_handler(OnlineMrWebControlError)
    async def online_mr_web_control_error_handler(_: Request, exc: OnlineMrWebControlError) -> JSONResponse:
        payload = ErrorResponse(error=ErrorDetail(code=exc.code, message=_safe_error_message(exc.message)))
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith(
            ("/api/rail-transit/online-mr-control", "/api/rail-transit/online-mr-agent")
        ):
            errors = [
                {key: value for key, value in item.items() if key in {"type", "loc", "msg"}}
                for item in exc.errors()
            ]
            payload = ErrorResponse(
                error=ErrorDetail(
                    code="ONLINE_MR_WEB_INVALID_REQUEST",
                    message="Online MR Web 控制请求字段或参数无效",
                    details={"errors": errors},
                )
            )
            return JSONResponse(status_code=422, content=jsonable_encoder(payload))
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": exc.errors()}))

    app.include_router(api_router)
    app.include_router(ws_router)
    _emit_startup_stage(startup_stage, "routers_registered")
    if development_api_enabled:
        if runtime_mode is not RuntimeMode.DESKTOP or not desktop_session_token:
            raise RuntimeError("development API requires protected desktop runtime")
        from netconsole.backend.api.development_router import router as development_router

        app.include_router(development_router, prefix="/api")

    dist = frontend_dist or _frontend_dist(paths)
    app.state.frontend_root = dist
    app.state.frontend_source_type = "override" if frontend_dist is not None else _frontend_source_type()
    app.state.frontend_build_meta = read_frontend_build_meta(dist)
    app.state.frontend_build_id = frontend_build_id(app.state.frontend_build_meta)
    app.state.frontend_build_mismatch = (
        app.state.frontend_build_id != app.state.backend_build_id
    )
    if (dist / "index.html").is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @app.get("/{frontend_path:path}", include_in_schema=False)
        def frontend(frontend_path: str):
            candidate = (dist / frontend_path).resolve()
            if frontend_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            index = dist / "index.html"
            if app.state.frontend_build_mismatch:
                return HTMLResponse(_inject_frontend_mismatch_warning(index))
            return FileResponse(index)

        return app

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def web_shell_placeholder() -> str:
        return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{APP_NAME}</title></head>
<body style="font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:48px;color:#202124">
<h1>{APP_NAME} Web 前端资源不可用</h1>
<p>当前 {app.state.frontend_source_type} 模式未找到完整 Web 构建资源，请重新构建或重新安装应用。</p>
<p>可打开 <a href="/docs">OpenAPI 文档</a> 或访问 <a href="/api/health">健康检查</a>。</p>
</body>
</html>"""

    return app


def _current_site_name(
    paths: PathResolver,
    *,
    startup_stage: Callable[[str], None] | None = None,
) -> str:
    preferred = str(os.environ.get("NETCONSOLE_ACTIVE_SITE_ID") or "").strip()
    if preferred:
        try:
            selected = SiteRegistryRepository(paths).resolve_directory_name(preferred)
            if paths.site_dir(selected).is_dir():
                _initialize_active_site_database(paths, selected, startup_stage=startup_stage)
                return selected
        except (SiteStorageError, ValueError):
            pass
    if not any(path.is_dir() and not path.is_symlink() for path in paths.sites_dir.glob("*")):
        DemoSiteSeedService(paths).seed()
    selected = SiteManager(paths).get_current_site()
    _initialize_active_site_database(paths, selected, startup_stage=startup_stage)
    return selected


def _initialize_active_site_database(
    paths: PathResolver,
    site_name: str,
    *,
    startup_stage: Callable[[str], None] | None = None,
) -> None:
    database = Database(paths.site_db_path(site_name))
    if not database.exists():
        raise RuntimeError("当前局点设备数据库不存在，Backend 未启动")
    _emit_startup_stage(startup_stage, "active_site_database_initializing")
    database.initialize()
    _emit_startup_stage(startup_stage, "active_site_database_ready")
    # Database.initialize() may normalize legacy rows and advance the source
    # revision; refresh the read-only identity index before API consumers use it.
    _emit_startup_stage(startup_stage, "ap_identity_index_initializing")
    ApIdentityQueryService(database).ensure_index("backend_startup")
    _emit_startup_stage(startup_stage, "ap_identity_index_ready")


def _emit_startup_stage(
    callback: Callable[[str], None] | None,
    stage: str,
) -> None:
    if callback is not None:
        callback(stage)


def _frontend_dist(paths: PathResolver) -> Path:
    if is_packaged_runtime():
        return package_resource_path("assets", "desktop_renderer")
    return paths.app_root / "apps" / "desktop_renderer" / "dist"


def _frontend_source_type() -> str:
    return "packaged" if is_packaged_runtime() else "source"


def _inject_frontend_mismatch_warning(index: Path) -> str:
    try:
        content = index.read_text(encoding="utf-8")
    except OSError:
        return FRONTEND_MISMATCH_MESSAGE
    warning = (
        '<div role="alert" data-netconsole-build-warning="1" '
        'style="padding:12px 18px;color:#7a2e00;background:#fff3cd;'
        'border-bottom:1px solid #f0cf7b;font:14px Segoe UI,Microsoft YaHei,sans-serif">'
        f"{html.escape(FRONTEND_MISMATCH_MESSAGE)}</div>"
    )
    if re.search(r"<body(?:\s[^>]*)?>", content, flags=re.IGNORECASE):
        return re.sub(
            r"<body(?:\s[^>]*)?>",
            lambda match: f"{match.group(0)}{warning}",
            content,
            count=1,
            flags=re.IGNORECASE,
        )
    return warning + content


def _traffic_error_status(code: str) -> int:
    try:
        normalized = TrafficErrorCode(code)
    except ValueError:
        return 400
    if normalized in {TrafficErrorCode.RESULT_NOT_FOUND, TrafficErrorCode.AGENT_NOT_FOUND, TrafficErrorCode.REMOTE_TASK_NOT_FOUND}:
        return 404
    if normalized in {TrafficErrorCode.INVALID_CONFIG, TrafficErrorCode.EXECUTION_TARGET_INVALID, TrafficErrorCode.EVENT_CURSOR_INVALID}:
        return 422
    if normalized in {
        TrafficErrorCode.AGENT_DISABLED,
        TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED,
        TrafficErrorCode.CAPABILITY_UNSUPPORTED,
        TrafficErrorCode.SERVER_PORT_IN_USE,
    }:
        return 409
    if normalized is TrafficErrorCode.AGENT_UNAUTHORIZED:
        return 401
    if normalized in {TrafficErrorCode.CONNECTION_TIMEOUT, TrafficErrorCode.CANCEL_TIMEOUT}:
        return 504
    if normalized in {
        TrafficErrorCode.AGENT_OFFLINE,
        TrafficErrorCode.REMOTE_SYNC_FAILED,
        TrafficErrorCode.SERVER_NOT_READY,
        TrafficErrorCode.CONNECTION_REFUSED,
        TrafficErrorCode.PROCESS_START_FAILED,
        TrafficErrorCode.PROCESS_EXITED,
        TrafficErrorCode.TOOL_NOT_FOUND,
    }:
        return 502
    return 400


def _safe_error_message(message: str) -> str:
    redacted = _ABSOLUTE_PATH_RE.sub("<redacted-path>", str(message or "流量测试失败"))
    return _SECRET_RE.sub(r"\1<redacted>", redacted)


def _online_mr_query_error_status(code: str) -> int:
    if code in {
        OnlineMrQueryErrorCode.SESSION_NOT_FOUND,
        OnlineMrQueryErrorCode.ARTIFACT_NOT_FOUND,
        OnlineMrQueryErrorCode.DATABASE_NOT_FOUND,
    }:
        return 404
    if code == OnlineMrQueryErrorCode.DATABASE_BUSY:
        return 503
    if code in {
        OnlineMrQueryErrorCode.DATABASE_UNREADABLE,
        OnlineMrQueryErrorCode.DATABASE_CORRUPT,
    }:
        return 409
    if code in {
        OnlineMrQueryErrorCode.LOG_SOURCE_INVALID,
        OnlineMrQueryErrorCode.LOG_CURSOR_INVALID,
        OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED,
        OnlineMrQueryErrorCode.METRIC_UNSUPPORTED,
        OnlineMrQueryErrorCode.SCHEMA_LEGACY,
        OnlineMrQueryErrorCode.SCHEMA_INCOMPLETE,
        OnlineMrQueryErrorCode.PARSE_REQUIRED,
        OnlineMrQueryErrorCode.RAW_SOURCE_MISSING,
        OnlineMrQueryErrorCode.QUERY_UNSUPPORTED,
    }:
        return 422
    return 409


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("netconsole.backend.api.main:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)
