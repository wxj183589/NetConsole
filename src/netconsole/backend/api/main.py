from __future__ import annotations

import asyncio
import html
import json
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from time import perf_counter
from typing import Callable, NoReturn
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
    verified_frontend_commit,
)
from netconsole.core.database import Database
from netconsole.core.build_metadata import current_build_metadata
from netconsole.services.field_diagnostic_bundle import safe_runtime_health
from netconsole.core.paths import PathResolver
from netconsole.core.performance_profiling import (
    begin_request_profile,
    end_request_profile,
)
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.resources import package_resource_path
from netconsole.core.runtime_environment import (
    data_environment,
    is_packaged_runtime,
)
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode, RuntimeMode
from netconsole.core.runtime_profile import (
    RuntimeCapabilityPolicy,
    read_host_environment_profile,
    read_runtime_performance_mode,
)
from netconsole.services.site_manager import SiteManager
from netconsole.core.version import APP_NAME, APP_VERSION
from netconsole.infrastructure.desktop import LocalDesktopAdapter, UnavailableDesktopAdapter
from netconsole.models.api.common import ErrorDetail, ErrorResponse
from netconsole.repositories.device_detail_repository import DeviceDetailRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
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
from netconsole.services.site_ssh_relay import (
    SiteSSHRelayService,
    close_site_jump_sessions,
)
from netconsole.services.site_storage import (
    DataRootApplicationService,
    SiteApplicationService,
    SitePackageService,
    SiteRecord,
    SiteRegistryRepository,
    SiteStorageError,
)
from netconsole.core.sqlite_utils import SqliteIntegrityError, check_sqlite_integrity
from netconsole.services.storage_audit import StorageAuditService


_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)")
_SECRET_RE = re.compile(r"(?i)((?:x-agent-token|token)\s*[:=]\s*)[^\s,;]+")
DESKTOP_SESSION_COOKIE = "netconsole_desktop_session"
DESKTOP_SESSION_HEADER = "x-netconsole-session"
_DESKTOP_DEFERRED_RUNTIME_DELAY_SECONDS = 1.0
_COLLECT_RUN_RECOVERY_GRACE_SECONDS = 5 * 60 + 1
_COLLECT_RUN_RECOVERY_RETRY_SECONDS = 60.0
_SLOW_API_THRESHOLD_MS = 250.0


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


class PerformanceProfilingMiddleware:
    """Attach bounded API/SQL/Repository timings without logging query data."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        request_id = supplied[:64] if supplied else uuid.uuid4().hex
        profile, token = begin_request_profile(
            request_id,
            str(scope.get("method") or ""),
            str(scope.get("path") or ""),
        )
        response_status = 500

        async def send_profiled(message) -> None:
            nonlocal request_id, response_status
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status") or 0)
                existing_request_id = next(
                    (
                        value.decode("ascii", errors="ignore")[:64]
                        for key, value in (message.get("headers") or [])
                        if key.lower() == b"x-request-id"
                    ),
                    "",
                )
                if existing_request_id:
                    request_id = existing_request_id
                    profile.request_id = existing_request_id
                total_ms = (perf_counter() - profile.started_at) * 1000
                timing = (
                    f"app;dur={total_ms:.2f}, "
                    f"sql;dur={profile.sql_ms:.2f};desc=\"{profile.sql_count} queries\", "
                    f"repository;dur={profile.repository_ms:.2f}"
                )
                response_headers = [
                    (key, value)
                    for key, value in (message.get("headers") or [])
                    if key.lower() not in {b"x-request-id", b"server-timing"}
                ]
                response_headers.extend(
                    (
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"server-timing", timing.encode("ascii")),
                    )
                )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_profiled)
        finally:
            total_ms = (perf_counter() - profile.started_at) * 1000
            if total_ms >= _SLOW_API_THRESHOLD_MS:
                repository_stages = ",".join(
                    f"{name}:{duration:.2f}"
                    for name, duration in sorted(profile.repository_calls.items())
                )
                app_logger.log_info(
                    "API_PERFORMANCE_PROFILE",
                    (
                        f"request_id={request_id} method={profile.method} path={profile.path} "
                        f"status={response_status} total_ms={total_ms:.2f} "
                        f"sql_count={profile.sql_count} sql_ms={profile.sql_ms:.2f} "
                        f"repository_ms={profile.repository_ms:.2f} "
                        f"repository_stages={repository_stages or '-'}"
                    ),
                )
            end_request_profile(token)
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
    if hasattr(paths, "app_log_path"):
        app_logger.configure_path_resolver(paths)
    environment = getattr(paths, "data_environment", None)
    if environment is None:
        environment = (
            DataEnvironmentInfo(DataEnvironmentMode.TEST)
            if runtime_mode is RuntimeMode.TEST
            else data_environment(getattr(paths, "data_root"))
        )
    app_logger.log_warning(
        "DATA_ROOT_CONTEXT" if environment.is_production else "DATA_ROOT_CONTEXT",
        f"data_root={getattr(paths, 'data_root', '<test>')} environment={environment.label}",
    )
    if environment.is_production:
        app_logger.log_warning(
            "PRODUCTION_DATA_ROOT_ACTIVE",
            "当前连接真实生产数据；GUI 正常业务操作由各自的确认、依赖、事务和回滚规则控制。",
        )
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
            # AC Web subscribes to terminal Task events below.  Defer the
            # bounded orphan recovery until that subscriber is attached so a
            # recovered AC action can persist its plan audit as well.
            reconcile_on_start=False,
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
    site_application_service = SiteApplicationService(paths, task_service)
    data_root_application_service = DataRootApplicationService(paths, site_application_service)
    site_package_service = SitePackageService(paths, site_application_service)
    site_ssh_relay_service = SiteSSHRelayService(paths)
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

    ground_unattended_repository: GroundUnattendedRepository | None = None
    ground_unattended_supervisor: GroundUnattendedSupervisor | None = None

    def build_ground_runtime(
        target_site_name: str,
    ) -> tuple[
        GroundUnattendedRepository,
        GroundUnattendedSupervisor,
        GroundUnattendedApplicationService,
    ]:
        """为一个明确局点构造完整的 Ground 运行时组合根。"""

        repository = GroundUnattendedRepository(
            paths.ground_unattended_db_path(target_site_name),
            site_id=target_site_name,
        )
        ap_identity_query = ApIdentityQueryService(
            Database(paths.site_db_path(target_site_name))
        )
        supervisor: GroundUnattendedSupervisor | None = None
        try:
            supervisor = GroundUnattendedSupervisor(
                paths,
                site_id=target_site_name,
                repository=repository,
                base_query=app.state.rail_transit_base_data_query_service,
                mesh_query=app.state.ac_mesh_link_query_service,
                vehicle_query=app.state.vehicle_mr_online_query_service,
                ac_refresh_service=ac_mesh_link_refresh_service,
                ac_resident_service=ac_mesh_link_resident_service,
                online_mr_application_service=online_mr_application_service,
                online_mr_query_service=online_mr_query_service,
                network_service=app.state.system_network_application_service,
                ap_identity_query_service=ap_identity_query,
            )
            application_service = GroundUnattendedApplicationService(
                paths,
                site_id=target_site_name,
                repository=repository,
                supervisor=supervisor,
                base_query=app.state.rail_transit_base_data_query_service,
                desktop_action_service=desktop_action_service,
                network_service=app.state.system_network_application_service,
                process_adapter=web_process_adapter,
                ap_identity_query_service=ap_identity_query,
            )
            return repository, supervisor, application_service
        except Exception:
            if supervisor is not None:
                supervisor.close()
            raise

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

        async def start_site_ssh_relay() -> None:
            """Restore the active site's persisted Relay without changing config."""

            try:
                active_site_id = site_application_service.active_site_id()
                status = await asyncio.to_thread(
                    site_ssh_relay_service.auto_start_if_enabled,
                    active_site_id,
                )
                app.state.ssh_relay_status = str(status.get("runtime_status") or "UNKNOWN")
                app.state.ssh_relay_error = str(status.get("runtime_message") or "")
            except Exception as exc:
                app.state.ssh_relay_status = "FAILED"
                app.state.ssh_relay_error = exc.__class__.__name__
                app_logger.log_error(
                    "SSH_RELAY_AUTO_START_FAILED",
                    f"component=site_ssh_relay error={exc.__class__.__name__}: "
                    f"{_safe_error_message(str(exc))}",
                )

        async def run_task_event_retention() -> None:
            retention_runner = getattr(task_service, "run_due_task_event_retention", None)
            if not callable(retention_runner):
                return
            try:
                retention_result = await asyncio.to_thread(retention_runner)
                app_logger.log_info(
                    "TASK_EVENT_RETENTION",
                    f"status={retention_result.get('status', 'unknown')} "
                    f"deleted_event_rows={retention_result.get('deleted_event_rows', 0)}",
                )
            except Exception as exc:
                # Retention is best-effort and must never make the normal
                # runtime services unavailable.
                app_logger.log_warning(
                    "TASK_EVENT_RETENTION_FAILED",
                    f"error={exc.__class__.__name__}: {_safe_error_message(str(exc))}",
                )

        async def start_deferred_runtime_services() -> None:
            try:
                # 先让 health、静态资源与首屏完成；历史任务恢复不参与桌面首屏关键路径。
                await asyncio.sleep(_DESKTOP_DEFERRED_RUNTIME_DELAY_SECONDS)
                if not app.state.accepting_work:
                    return
                await start_site_ssh_relay()
                reconcile_tasks = getattr(task_service, "reconcile_orphaned_local_tasks", None)
                if callable(reconcile_tasks):
                    await asyncio.to_thread(reconcile_tasks)
                await run_task_event_retention()
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

        try:
            staging_recovery = await asyncio.to_thread(
                site_package_service.recover_orphaned_staging
            )
            app.state.site_package_staging_recovery = staging_recovery.to_dict()
            if staging_recovery.failures:
                app_logger.log_warning(
                    "SITE_PACKAGE_STAGING_RECOVERY_PARTIAL",
                    f"failed={len(staging_recovery.failures)}",
                )
        except Exception as exc:
            app.state.site_package_staging_recovery = {
                "status": "FAIL",
                "error": exc.__class__.__name__,
            }
            app_logger.log_warning(
                "SITE_PACKAGE_STAGING_RECOVERY_FAILED",
                f"error={exc.__class__.__name__}",
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

        collect_run_recovery_task = asyncio.create_task(
            _schedule_collect_run_recovery(
                paths,
                site_name,
                should_continue=lambda: bool(app.state.accepting_work),
                is_busy=lambda: _collect_run_recovery_busy(task_service),
            )
        )
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
                await start_site_ssh_relay()
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
            collect_run_recovery_task.cancel()
            await asyncio.gather(collect_run_recovery_task, return_exceptions=True)
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
            try:
                close_site_jump_sessions(paths=paths)
            except Exception as exc:
                app_logger.log_error(
                    "WEB_LIFESPAN_STOP_FAILED",
                    f"component=site_ssh_relay error={exc.__class__.__name__}: {exc}",
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
    app.state.data_environment = environment
    app.state.api_documentation_enabled = bool(api_documentation_enabled)
    app.state.development_api_enabled = bool(development_api_enabled)
    app.state.development_runtime_label = str(development_runtime_label)
    app.state.development_frontend_mode = str(development_frontend_mode)
    app.state.desktop_session_protected = bool(desktop_session_token)
    app.state.accepting_work = True
    app.add_middleware(DesktopShutdownAdmissionMiddleware, state=app.state)
    app.add_middleware(RuntimeServicesAdmissionMiddleware, state=app.state)
    app.add_middleware(PerformanceProfilingMiddleware)
    app.state.online_mr_web_control_enabled = online_mr_web_control_enabled
    app.state.online_mr_agent_executor_enabled = online_mr_agent_executor_enabled
    app.state.runtime_services_ready = False
    app.state.runtime_services_status = "starting"
    app.state.runtime_services_error = ""
    app.state.ssh_relay_status = "starting"
    app.state.ssh_relay_error = ""
    app.state.history_status = "retired"
    app.state.history_pending = 0
    app.state.history_error = ""
    app.state.history_oldest_pending_age_seconds = 0
    app.state.history_pressure = "normal"
    app.state.history_last_drain_elapsed_ms = 0
    app.state.history_last_drain_written = 0
    app.state.history_budget_overrun = False
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
    app.state.storage_audit_service = StorageAuditService(paths.data_root)
    app.state.build_metadata = current_build_metadata(paths.app_root)
    app.state.backend_build_id = backend_build_id(paths.app_root)
    app.state.task_service = task_service
    app.state.site_application_service = site_application_service
    app.state.data_root_application_service = data_root_application_service
    app.state.site_package_service = site_package_service
    app.state.site_ssh_relay_service = site_ssh_relay_service
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
    settings_application_service = SettingsApplicationService(paths, feature_gate, site_name)
    runtime_self_check_service = RuntimeSelfCheckService(
        paths,
        feature_gate,
        site_name,
    )
    app.state.settings_application_service = settings_application_service
    app.state.runtime_self_check_service = runtime_self_check_service
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
    if not defer_runtime_start:
        reconcile_tasks = getattr(task_service, "reconcile_orphaned_local_tasks", None)
        if callable(reconcile_tasks):
            reconcile_tasks()
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
            (
                ground_unattended_repository,
                ground_unattended_supervisor,
                app.state.ground_unattended_application_service,
            ) = build_ground_runtime(site_name)
            app.state.ground_unattended_repository = ground_unattended_repository
            app.state.ground_unattended_supervisor = ground_unattended_supervisor
        except Exception as exc:
            app.state.ground_unattended_startup_error = exc.__class__.__name__
            app.state.unattended_status = "failed"
            app.state.unattended_error = exc.__class__.__name__
            app_logger.log_error(
                "GROUND_UNATTENDED_START_FAILED",
                f"component=ground_unattended error={exc.__class__.__name__}: "
                f"{_safe_error_message(str(exc))}",
            )

    def diagnostic_runtime_snapshot() -> dict[str, object]:
        service = getattr(app.state, "ground_unattended_application_service", None)
        if service is None:
            return {}
        try:
            health = service.health(site_name)
            return safe_runtime_health(health.model_dump(mode="json"))
        except Exception:
            return {}

    system_maintenance_service.runtime_snapshot_provider = diagnostic_runtime_snapshot

    def rebind_runtime_site(target_site_name: str) -> None:
        """在 Backend 进程内切换所有持有 Site-scoped 状态的服务。"""

        nonlocal ground_unattended_repository, ground_unattended_supervisor, site_name

        target = str(target_site_name or "demo")
        old_ground_supervisor = ground_unattended_supervisor
        old_ground_started = bool(
            getattr(app.state, "unattended_ready", False)
            or (old_ground_supervisor is not None and old_ground_supervisor.running)
        )
        old_unattended_status = str(getattr(app.state, "unattended_status", "starting"))
        rebind = getattr(task_service, "rebind_site", None)
        if callable(rebind):
            rebind(target)
        else:
            task_service.site_name = target
        rebind = getattr(agent_service, "rebind_site", None)
        if callable(rebind):
            rebind(target)
        rebind = getattr(device_management_service, "rebind_site", None)
        if callable(rebind):
            rebind(target)
        rebind = getattr(traffic_service, "rebind_site", None)
        if callable(rebind):
            rebind(target)
        rebind = getattr(file_management_service, "rebind_site", None)
        if callable(rebind):
            rebind(target)
        rebind = getattr(online_mr_application_service, "rebind_site", None)
        if callable(rebind):
            rebind(target)
        settings_application_service.site_name = target
        runtime_self_check_service.site_name = target
        desktop_action_service.resolver.replace_directory_group(
            "config_snapshots:",
            {f"config_snapshots:{target}": paths.config_center_snapshots_root(target)},
        )
        desktop_action_service.resolver.replace_directory_group(
            "config_exports:",
            {f"config_exports:{target}": paths.config_center_outputs_dir(target)},
        )
        if ground_unattended_feature_enabled:
            (
                target_ground_repository,
                target_ground_supervisor,
                target_ground_application_service,
            ) = build_ground_runtime(target)
            try:
                if old_ground_started:
                    target_ground_supervisor.start()
                if old_ground_supervisor is not None:
                    old_ground_supervisor.close()
            except Exception:
                target_ground_supervisor.close()
                raise
            ground_unattended_repository = target_ground_repository
            ground_unattended_supervisor = target_ground_supervisor
            app.state.ground_unattended_repository = target_ground_repository
            app.state.ground_unattended_supervisor = target_ground_supervisor
            app.state.ground_unattended_application_service = target_ground_application_service
            app.state.ground_unattended_startup_error = ""
            app.state.unattended_error = ""
            app.state.unattended_ready = old_ground_started
            app.state.unattended_status = "ready" if old_ground_started else old_unattended_status
        site_name = target
        app_logger.log_info("SITE_RUNTIME_REBOUND", f"site_name={target}")
        try:
            close_site_jump_sessions(paths=paths)
            relay_site_id = site_application_service.active_site_id()
            site_ssh_relay_service.auto_start_if_enabled(relay_site_id)
        except Exception as exc:
            app_logger.log_error(
                "SSH_RELAY_AUTO_START_FAILED",
                f"component=site_ssh_relay site_name={target} "
                f"error={exc.__class__.__name__}: {_safe_error_message(str(exc))}",
            )

    site_application_service.set_runtime_rebind_handler(rebind_runtime_site)
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
    app.state.frontend_commit = verified_frontend_commit(app.state.frontend_build_meta)
    app.state.frontend_build_mismatch = (
        app.state.frontend_build_id != app.state.backend_build_id
    )
    _log_build_identity(app)
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


def _log_build_identity(app: FastAPI) -> None:
    metadata = dict(getattr(app.state, "build_metadata", {}) or {})
    feature_gate = getattr(app.state, "feature_gate", None)
    app_logger.log_info(
        "BUILD_IDENTITY",
        " ".join(
            (
                f"product_version={metadata.get('app_version') or 'unknown'}",
                f"commit_sha_full={metadata.get('git_commit_full') or 'unknown'}",
                f"commit_sha_short={metadata.get('git_commit_short') or 'unknown'}",
                f"backend_commit={metadata.get('backend_commit') or 'unknown'}",
                f"frontend_commit={getattr(app.state, 'frontend_commit', 'unknown') or 'unknown'}",
                f"edition={getattr(feature_gate, 'edition', 'unknown') or 'unknown'}",
                f"packaged_dirty={str(bool(metadata.get('build_dirty', True))).lower()}",
                f"build_timestamp={metadata.get('build_time_utc') or ''}",
            )
        ),
    )


@dataclass(frozen=True)
class _ProductionSiteReference:
    source_file: str
    field: str
    value: str
    kind: str

    @property
    def label(self) -> str:
        return f"{self.source_file}:{self.field}"


@dataclass(frozen=True)
class _ProductionSiteReferenceSnapshot:
    references: tuple[_ProductionSiteReference, ...]
    application_present: bool
    read_diagnostics: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class _ProductionStartupContext:
    site_name: str
    site_id: str
    database_path: Path
    selected_source: str
    diagnostics: tuple[dict[str, object], ...] = ()


def _format_active_site_reference_diagnostic(value: dict[str, object]) -> str:
    return " ".join(
        (
            f"来源={value.get('source_file', '')}",
            f"字段={value.get('field', '')}",
            f"引用={value.get('reference', '')}",
            f"canonical_site_id={value.get('canonical_site_id') or 'none'}",
            f"物理目录={value.get('physical_directory') or 'none'}",
            f"存在={str(bool(value.get('exists'))).lower()}",
            f"legacy_hint={str(bool(value.get('legacy_hint'))).lower()}",
            f"与活动局点一致={str(value.get('consistent_with_selected')).lower()}",
            f"原因={value.get('reason', '')}",
        )
    )


class ActiveSiteStartupError(RuntimeError):
    """Raised when the persisted Production active-site contract is unsafe."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        data_root: Path,
        diagnostics: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
    ) -> None:
        self.code = code
        self.data_root = data_root
        self.diagnostics = tuple(diagnostics)
        diagnostic_text = ""
        if self.diagnostics:
            diagnostic_text = "\n局点引用诊断：\n" + "\n".join(
                f"- {_format_active_site_reference_diagnostic(item)}"
                for item in self.diagnostics
            )
        super().__init__(
            "NetConsole 无法读取当前局点配置。\n"
            f"数据目录：{data_root}\n"
            f"错误码：{code}\n"
            f"原因：{message}\n"
            f"{diagnostic_text}\n"
            "现有业务数据未被删除或重建。请检查数据目录配置，或执行受控恢复。"
        )


def _raise_active_site_startup_error(
    paths: PathResolver,
    code: str,
    message: str,
    *,
    cause: BaseException | None = None,
    diagnostics: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
) -> NoReturn:
    app_logger.log_error(
        code,
        f"stage=active_site_startup data_root={paths.data_root} reason={message}",
    )
    error = ActiveSiteStartupError(
        code,
        message,
        data_root=paths.data_root,
        diagnostics=diagnostics,
    )
    if cause is not None:
        raise error from cause
    raise error


def _startup_path_is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & 0x400)


def _read_production_site_reference_snapshot(
    paths: PathResolver,
) -> _ProductionSiteReferenceSnapshot:
    refs: list[_ProductionSiteReference] = []
    read_diagnostics: list[dict[str, object]] = []
    if _startup_path_is_link_or_reparse(paths.config_dir):
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_CONFIG_INVALID",
            "config 目录不得是符号链接或 Reparse Point",
        )
    application_present = paths.app_config_path.exists() or _startup_path_is_link_or_reparse(
        paths.app_config_path
    )
    for config_path in (paths.app_config_path, paths.legacy_app_config_path):
        config_path_is_link = _startup_path_is_link_or_reparse(config_path)
        if not config_path.exists() and not config_path_is_link:
            continue
        is_application = config_path == paths.app_config_path
        strict = is_application or not application_present
        if not config_path.is_file() or config_path_is_link:
            if not strict:
                read_diagnostics.append(
                    {
                        "source_file": config_path.name,
                        "field": "<file>",
                        "reason": "legacy_hint_unreadable_ignored",
                    }
                )
                continue
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_CONFIG_MISSING",
                f"局点配置文件不可读取：{config_path.name}",
            )
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            if not strict:
                read_diagnostics.append(
                    {
                        "source_file": config_path.name,
                        "field": "<json>",
                        "reason": "legacy_hint_invalid_ignored",
                        "error_type": exc.__class__.__name__,
                    }
                )
                continue
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_CONFIG_INVALID",
                f"局点配置文件格式无效：{config_path.name}",
                cause=exc,
            )
        if not isinstance(raw, dict):
            if not strict:
                read_diagnostics.append(
                    {
                        "source_file": config_path.name,
                        "field": "<root>",
                        "reason": "legacy_hint_invalid_ignored",
                    }
                )
                continue
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_CONFIG_INVALID",
                f"局点配置文件结构无效：{config_path.name}",
            )
        for key in ("active_site_id", "current_site"):
            value = raw.get(key)
            if value is None or str(value).strip() == "":
                continue
            if not isinstance(value, str):
                if not strict:
                    read_diagnostics.append(
                        {
                            "source_file": config_path.name,
                            "field": key,
                            "reason": "legacy_hint_field_invalid_ignored",
                        }
                    )
                    continue
                _raise_active_site_startup_error(
                    paths,
                    "ACTIVE_SITE_CONFIG_INVALID",
                    f"{config_path.name} 的 {key} 必须是文本",
                )
            refs.append(
                _ProductionSiteReference(
                    config_path.name,
                    key,
                    value.strip(),
                    "formal_active"
                    if is_application and key == "active_site_id"
                    else "formal_compat"
                    if is_application
                    else "legacy_hint",
                )
            )

    bootstrap_site_id = str(os.environ.get("NETCONSOLE_ACTIVE_SITE_ID") or "").strip()
    if bootstrap_site_id:
        mode = str(os.environ.get("NETCONSOLE_ACTIVE_SITE_MODE") or "").strip().casefold()
        refs.append(
            _ProductionSiteReference(
                "electron-bootstrap" if mode != "authorized_switch" else "site-switch",
                "active_site_id",
                bootstrap_site_id,
                "authorized_switch" if mode == "authorized_switch" else "bootstrap_hint",
            )
        )
    return _ProductionSiteReferenceSnapshot(
        tuple(refs),
        application_present,
        tuple(read_diagnostics),
    )


def _read_production_site_refs(paths: PathResolver) -> list[tuple[str, str]]:
    """Return all startup references for compatibility with existing callers."""

    snapshot = _read_production_site_reference_snapshot(paths)
    return [(reference.label, reference.value) for reference in snapshot.references]


def _production_configured_site_ref(paths: PathResolver) -> str:
    snapshot = _read_production_site_reference_snapshot(paths)
    for kind in ("formal_active", "formal_compat", "legacy_hint"):
        for reference in snapshot.references:
            if reference.kind == kind:
                return reference.value
    _raise_active_site_startup_error(
        paths,
        "ACTIVE_SITE_CONFIG_MISSING",
        "未找到 current_site 或 active_site_id",
    )


def _startup_site_entries(paths: PathResolver) -> list[Path]:
    if _startup_path_is_link_or_reparse(paths.sites_dir):
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_REGISTRY_INVALID",
            "sites 目录不可安全读取",
        )
    if not paths.sites_dir.exists():
        return []
    if not paths.sites_dir.is_dir():
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_REGISTRY_INVALID",
            "sites 目录不可安全读取",
        )
    entries = list(paths.sites_dir.iterdir())
    for entry in entries:
        if _startup_path_is_link_or_reparse(entry):
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_REGISTRY_INVALID",
                f"sites 下存在符号链接或 Reparse Point：{entry.name}",
            )
        if not entry.is_dir():
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_REGISTRY_INVALID",
                f"sites 下存在未登记的非目录项：{entry.name}",
            )
    return entries


def _strict_production_records(
    paths: PathResolver,
) -> tuple[SiteRegistryRepository, list[SiteRecord]]:
    registry = SiteRegistryRepository(paths)
    if _startup_path_is_link_or_reparse(registry.path):
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_REGISTRY_INVALID",
            "site_registry.json 不得是符号链接或 Reparse Point",
        )
    try:
        records = registry.persisted_records()
    except SiteStorageError as exc:
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_REGISTRY_INVALID",
            str(exc),
            cause=exc,
        )
    entries = _startup_site_entries(paths)
    roots = {record.root_path.resolve() for record in records}
    unknown = [entry for entry in entries if entry.resolve() not in roots]
    if unknown:
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_REGISTRY_INVALID",
            f"存在未登记的局点目录：{unknown[0].name}",
        )
    return registry, records


def _recover_legacy_registry(
    paths: PathResolver,
    refs: list[tuple[str, str]],
) -> tuple[SiteRegistryRepository, list[SiteRecord]]:
    registry = SiteRegistryRepository(paths)
    if registry.path.exists():
        return _strict_production_records(paths)
    entries = _startup_site_entries(paths)
    if not entries:
        try:
            SiteApplicationService(paths).initialize_first_run_site()
        except SiteStorageError as exc:
            _raise_active_site_startup_error(
                paths, exc.code, str(exc), cause=exc
            )
        return _strict_production_records(paths)
    if len(entries) > 1 and not refs:
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_AMBIGUOUS",
            "旧数据根包含多个局点，但没有可验证的当前局点引用",
        )
    try:
        # The legacy discovery path is used only when no Registry exists and
        # only after the direct-child inventory above has passed.  It upgrades
        # the unique/explicitly referenced legacy installation to the Registry.
        registry.list()
    except SiteStorageError as exc:
        _raise_active_site_startup_error(
            paths, "ACTIVE_SITE_REGISTRY_INVALID", str(exc), cause=exc
        )
    return _strict_production_records(paths)


def _resolve_startup_reference(
    records: list[SiteRecord], reference: str
) -> SiteRecord | None:
    wanted = reference.casefold()
    matches = [
        record
        for record in records
        if record.site_id.casefold() == wanted
        or record.root_path.name.casefold() == wanted
    ]
    if not matches:
        return None
    unique = {record.site_id: record for record in matches}
    if len(unique) != 1:
        raise ValueError("reference resolves to multiple sites")
    return next(iter(unique.values()))


def _startup_reference_diagnostics(
    references: list[_ProductionSiteReference],
    records: list[SiteRecord],
    *,
    selected_site_id: str | None = None,
    reasons: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    reason_by_label = reasons or {}
    diagnostics: list[dict[str, object]] = []
    for reference in references:
        matches = [
            record
            for record in records
            if record.site_id.casefold() == reference.value.casefold()
            or record.root_path.name.casefold() == reference.value.casefold()
        ]
        unique = {record.site_id: record for record in matches}
        record = next(iter(unique.values())) if len(unique) == 1 else None
        if len(unique) > 1:
            reason = "reference_resolves_to_multiple_sites"
        elif record is None:
            reason = "reference_not_found"
        else:
            reason = reason_by_label.get(reference.label, "reference_resolved")
        diagnostics.append(
            {
                "source_file": reference.source_file,
                "field": reference.field,
                "reference": reference.value,
                "canonical_site_id": record.site_id if record is not None else None,
                "physical_directory": str(record.root_path) if record is not None else "",
                "exists": bool(record is not None and record.root_path.is_dir()),
                "legacy_hint": reference.kind in {"legacy_hint", "bootstrap_hint"},
                "consistent_with_selected": (
                    None
                    if selected_site_id is None or record is None
                    else record.site_id == selected_site_id
                ),
                "reason": reason,
            }
        )
    return diagnostics


def _log_startup_reference_diagnostics(
    diagnostics: list[dict[str, object]],
) -> None:
    for diagnostic in diagnostics:
        app_logger.log_info(
            "ACTIVE_SITE_REFERENCE_DIAGNOSTIC",
            json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")),
        )


def _validate_startup_database(paths: PathResolver, record: SiteRecord) -> Path:
    root = record.root_path
    if not root.is_dir() or _startup_path_is_link_or_reparse(root):
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_CONFIG_MISSING",
            f"当前局点目录不存在或不可安全读取：{record.site_id}",
        )
    database_path = root / "db" / "devices.db"
    if (
        not database_path.is_file()
        or _startup_path_is_link_or_reparse(database_path)
        or database_path.stat().st_size == 0
    ):
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_DATABASE_MISSING",
            f"当前局点设备数据库不存在或为空：{record.site_id}",
        )
    try:
        check = check_sqlite_integrity(database_path)
    except SqliteIntegrityError as exc:
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_DATABASE_CORRUPT",
            f"当前局点设备数据库无法读取：{record.site_id}",
            cause=exc,
        )
    if not check:
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_DATABASE_CORRUPT",
            f"当前局点设备数据库完整性检查失败：{record.site_id}",
        )
    return database_path


def _production_startup_site(
    paths: PathResolver,
    site_ref: str | None = None,
) -> _ProductionStartupContext:
    """Resolve ordinary Production startup from persisted SiteRegistry data."""

    snapshot = _read_production_site_reference_snapshot(paths)
    references = list(snapshot.references)
    if site_ref and not any(
        reference.kind in {"authorized_switch", "bootstrap_hint"}
        and reference.value == site_ref
        for reference in references
    ):
        references.append(
            _ProductionSiteReference(
                "electron-bootstrap",
                "active_site_id",
                site_ref,
                "bootstrap_hint",
            )
        )
    recovery_refs = [
        (reference.label, reference.value)
        for reference in references
        if reference.kind != "bootstrap_hint"
    ]
    registry, records = _recover_legacy_registry(paths, recovery_refs)
    del registry
    if not records:
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_CONFIG_MISSING",
            "数据根中没有已登记的局点",
        )

    reasons: dict[str, str] = {}
    diagnostics = list(snapshot.read_diagnostics)

    def resolve_group(
        group: list[_ProductionSiteReference],
        *,
        group_name: str,
    ) -> SiteRecord | None:
        resolved_refs: dict[str, SiteRecord] = {}
        for reference in group:
            source = reference.label
            value = reference.value
            try:
                match = _resolve_startup_reference(records, value)
            except ValueError as exc:
                reasons[source] = f"{group_name}_reference_ambiguous"
                all_diagnostics = diagnostics + _startup_reference_diagnostics(
                    references,
                    records,
                    reasons=reasons,
                )
                _log_startup_reference_diagnostics(all_diagnostics)
                _raise_active_site_startup_error(
                    paths,
                    "ACTIVE_SITE_AMBIGUOUS",
                    f"{source} 无法唯一对应一个局点：{value}",
                    cause=exc,
                    diagnostics=all_diagnostics,
                )
            if match is None:
                reasons[source] = f"{group_name}_reference_not_found"
                all_diagnostics = diagnostics + _startup_reference_diagnostics(
                    references,
                    records,
                    reasons=reasons,
                )
                _log_startup_reference_diagnostics(all_diagnostics)
                _raise_active_site_startup_error(
                    paths,
                    "ACTIVE_SITE_CONFIG_MISSING",
                    f"{source} 无法在持久化 Registry 中解析：{value}",
                    diagnostics=all_diagnostics,
                )
            resolved_refs[source] = match
        resolved_ids = {record.site_id for record in resolved_refs.values()}
        if len(resolved_ids) > 1:
            for source in resolved_refs:
                reasons[source] = f"{group_name}_fields_conflict"
            all_diagnostics = diagnostics + _startup_reference_diagnostics(
                references,
                records,
                reasons=reasons,
            )
            _log_startup_reference_diagnostics(all_diagnostics)
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_AMBIGUOUS",
                f"{group_name} 的配置字段指向不同局点",
                diagnostics=all_diagnostics,
            )
        return next(iter(resolved_refs.values())) if resolved_refs else None

    authorized_refs = [
        reference for reference in references if reference.kind == "authorized_switch"
    ]
    formal_refs = [
        reference
        for reference in references
        if reference.kind in {"formal_active", "formal_compat"}
    ]
    legacy_refs = [
        reference for reference in references if reference.kind == "legacy_hint"
    ]
    bootstrap_refs = [
        reference for reference in references if reference.kind == "bootstrap_hint"
    ]

    selected: SiteRecord | None = None
    selected_source = "registry_unique_recovery"
    if authorized_refs:
        selected = resolve_group(authorized_refs, group_name="已授权局点切换")
        selected_source = authorized_refs[0].label
        for reference in formal_refs:
            reasons.setdefault(reference.label, "formal_configuration_overridden_by_authorized_switch")
        for reference in legacy_refs:
            reasons.setdefault(reference.label, "legacy_hint_ignored_by_authorized_switch")
        for reference in bootstrap_refs:
            reasons.setdefault(reference.label, "bootstrap_hint_ignored_by_authorized_switch")
    elif snapshot.application_present:
        if formal_refs:
            selected = resolve_group(formal_refs, group_name="application.json")
            selected_source = next(
                (
                    reference.label
                    for reference in formal_refs
                    if reference.kind == "formal_active"
                ),
                formal_refs[0].label,
            )
            for reference in legacy_refs:
                reasons.setdefault(reference.label, "legacy_hint_ignored_by_formal_configuration")
            for reference in bootstrap_refs:
                reasons.setdefault(reference.label, "bootstrap_hint_ignored_by_formal_configuration")
        else:
            diagnostics.extend(
                _startup_reference_diagnostics(references, records, reasons=reasons)
            )
            _log_startup_reference_diagnostics(diagnostics)
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_CONFIG_MISSING",
                "application.json 存在，但没有 active_site_id 或 current_site",
                diagnostics=diagnostics,
            )
    elif legacy_refs:
        selected = resolve_group(legacy_refs, group_name="legacy app.json")
        selected_source = legacy_refs[0].label
        for reference in bootstrap_refs:
            reasons.setdefault(reference.label, "bootstrap_hint_ignored_by_legacy_configuration")
    elif len(records) == 1:
        selected = records[0]
        for reference in bootstrap_refs:
            reasons.setdefault(reference.label, "bootstrap_hint_not_authority_registry_unique")
    else:
        reasons.update(
            {
                reference.label: "bootstrap_hint_not_authority_multiple_candidates"
                for reference in bootstrap_refs
            }
        )
        diagnostics.extend(
            _startup_reference_diagnostics(references, records, reasons=reasons)
        )
        _log_startup_reference_diagnostics(diagnostics)
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_AMBIGUOUS",
            "数据根包含多个局点，但没有可验证的正式活动局点或已授权切换目标",
            diagnostics=diagnostics,
        )

    if selected is None:
        diagnostics.extend(
            _startup_reference_diagnostics(references, records, reasons=reasons)
        )
        _log_startup_reference_diagnostics(diagnostics)
        _raise_active_site_startup_error(
            paths,
            "ACTIVE_SITE_CONFIG_MISSING",
            "无法确定当前局点",
            diagnostics=diagnostics,
        )

    for reference in references:
        if reference.label not in reasons:
            if reference.kind == "formal_active" and reference.value:
                reasons[reference.label] = "formal_active_selected"
            elif reference.kind == "formal_compat":
                reasons[reference.label] = "formal_compat_consistent"
            elif reference.kind == "legacy_hint":
                reasons[reference.label] = "legacy_hint_selected"
            elif reference.kind == "bootstrap_hint":
                reasons[reference.label] = "bootstrap_hint_ignored"
            else:
                reasons[reference.label] = "reference_resolved"
    diagnostics.extend(
        _startup_reference_diagnostics(
            references,
            records,
            selected_site_id=selected.site_id,
            reasons=reasons,
        )
    )
    _log_startup_reference_diagnostics(diagnostics)

    database_path = _validate_startup_database(paths, selected)
    return _ProductionStartupContext(
        site_name=selected.root_path.name,
        site_id=selected.site_id,
        database_path=database_path,
        selected_source=selected_source,
        diagnostics=tuple(diagnostics),
    )


def _paths_are_production(paths: PathResolver) -> bool:
    environment = getattr(paths, "data_environment", None)
    return bool(environment is not None and environment.is_production)


def _current_site_name(
    paths: PathResolver,
    *,
    startup_stage: Callable[[str], None] | None = None,
) -> str:
    production = _paths_are_production(paths)
    preferred = str(os.environ.get("NETCONSOLE_ACTIVE_SITE_ID") or "").strip()
    if production:
        startup_context = _production_startup_site(paths, preferred or None)
        _initialize_active_site_database(
            paths,
            startup_context.site_name,
            production_context=startup_context,
            startup_stage=startup_stage,
        )
        SiteManager(paths).set_current_site_reference(
            startup_context.site_name,
            site_id=startup_context.site_id,
        )
        return startup_context.site_name
    if preferred:
        try:
            selected = SiteRegistryRepository(paths).resolve_directory_name(preferred)
            if paths.site_dir(selected).is_dir():
                # Electron/bootstrap owns the stable identity at startup. Keep
                # the legacy physical pointer in sync for older services while
                # retaining the stable ID as the active-context fact.
                SiteManager(paths).set_current_site_reference(
                    selected, site_id=preferred
                )
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
    production_site_id: str | None = None,
    production_context: _ProductionStartupContext | None = None,
    startup_stage: Callable[[str], None] | None = None,
) -> None:
    production = _paths_are_production(paths)
    database_path = paths.site_db_path(site_name)
    if production:
        if production_context is None:
            production_context = _production_startup_site(
                paths,
                production_site_id or site_name,
            )
        if production_context.site_name != site_name:
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_CONTEXT_CHANGED",
                "启动过程中当前局点目录发生变化，已停止数据库初始化",
                diagnostics=list(production_context.diagnostics),
            )
        site_name = production_context.site_name
        site_id = production_context.site_id
        database_path = production_context.database_path
    database = Database(database_path)
    if not database.exists():
        if production:
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_DATABASE_MISSING",
                f"当前局点设备数据库不存在：{site_id}",
            )
        raise RuntimeError("当前局点设备数据库不存在，Backend 未启动")
    _emit_startup_stage(startup_stage, "active_site_database_initializing")
    if production:
        try:
            database.initialize(startup_policy="production_safe")
        except Exception as exc:
            if isinstance(exc, ActiveSiteStartupError):
                raise
            _raise_active_site_startup_error(
                paths,
                "ACTIVE_SITE_DATABASE_UNAVAILABLE",
                f"当前局点数据库不满足安全启动条件：{site_id}",
                cause=exc,
            )
        if production_context is not None:
            expected_database_path = paths.site_db_path(site_name).resolve()
            if expected_database_path != production_context.database_path.resolve():
                _raise_active_site_startup_error(
                    paths,
                    "ACTIVE_SITE_CONTEXT_CHANGED",
                    "数据库初始化前后目标局点身份或路径发生变化",
                    diagnostics=list(production_context.diagnostics),
                )
    else:
        database.initialize()
    _emit_startup_stage(startup_stage, "active_site_database_ready")
    _recover_orphaned_collect_runs(database, site_name)
    # Database.initialize() may normalize legacy rows and advance the source
    # revision; refresh the read-only identity index before API consumers use it.
    _emit_startup_stage(startup_stage, "ap_identity_index_initializing")
    identity_service = ApIdentityQueryService(database)
    if production:
        identity_service.ensure_index(
            "backend_startup",
            automatic_safe_only=True,
        )
    else:
        identity_service.ensure_index("backend_startup")
    _emit_startup_stage(startup_stage, "ap_identity_index_ready")


def _recover_orphaned_collect_runs(
    database: Database,
    site_name: str,
    *,
    stale_before: str | None = None,
) -> list[dict[str, object | None]]:
    recovery_cutoff = stale_before or (
        datetime.now() - timedelta(minutes=5)
    ).isoformat(timespec="seconds")
    recovered_runs = DeviceFactRepository(database).recover_orphaned_collect_runs(
        stale_before=recovery_cutoff,
    )
    if recovered_runs:
        app_logger.log_warning(
            "COLLECT_RUN_ORPHAN_RECOVERY",
            f"site={site_name} recovered={len(recovered_runs)} "
            f"stale_before={recovery_cutoff}",
        )
    return recovered_runs


def _recover_active_site_collect_runs(
    paths: PathResolver,
    site_name: str,
) -> list[dict[str, object | None]]:
    database = Database(paths.site_db_path(site_name))
    if not database.exists():
        return []
    return _recover_orphaned_collect_runs(database, site_name)


def _collect_run_recovery_busy(task_service: object) -> bool:
    """Keep the delayed recovery behind the current task/worker owner."""

    snapshot_factory = getattr(task_service, "active_task_snapshot", None)
    if not callable(snapshot_factory):
        return True
    try:
        snapshot = snapshot_factory()
        if not isinstance(snapshot, dict):
            return True
        return any(
            int(snapshot.get(field, 0) or 0) > 0
            for field in ("active_tasks", "active_workers")
        )
    except Exception as exc:
        app_logger.log_warning(
            "COLLECT_RUN_ORPHAN_RECOVERY_BUSY_CHECK_FAILED",
            f"error={exc.__class__.__name__}: {_safe_error_message(str(exc))}",
        )
        return True


async def _schedule_collect_run_recovery(
    paths: PathResolver,
    site_name: str,
    *,
    should_continue: Callable[[], bool],
    is_busy: Callable[[], bool],
    grace_seconds: float = _COLLECT_RUN_RECOVERY_GRACE_SECONDS,
    retry_seconds: float = _COLLECT_RUN_RECOVERY_RETRY_SECONDS,
) -> None:
    await asyncio.sleep(max(0.0, float(grace_seconds)))
    while should_continue():
        if not is_busy():
            try:
                await asyncio.to_thread(_recover_active_site_collect_runs, paths, site_name)
            except Exception as exc:
                app_logger.log_warning(
                    "COLLECT_RUN_ORPHAN_RECOVERY_RECHECK_FAILED",
                    f"site={site_name} error={exc.__class__.__name__}: "
                    f"{_safe_error_message(str(exc))}",
                )
            return
        await asyncio.sleep(max(0.0, float(retry_seconds)))


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
