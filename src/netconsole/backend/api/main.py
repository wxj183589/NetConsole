from __future__ import annotations

import asyncio
import html
import os
import re
import secrets
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from netconsole.application.ac.web_application_service import AcWebApplicationService
from netconsole.application.desktop import DesktopActionResolver, DesktopActionService
from netconsole.application.rail_transit.web_application_service import RailTransitWebApplicationService
from netconsole.application.web_artifacts import WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.backend.api.router import api_router, ws_router
from netconsole.core import app_logger
from netconsole.backend.web_build import (
    FRONTEND_MISMATCH_MESSAGE,
    backend_build_id,
    frontend_build_id,
    read_frontend_build_meta,
)
from netconsole.core.paths import PathResolver
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.resources import package_resource_path
from netconsole.core.runtime_environment import is_packaged_runtime
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.core.version import APP_NAME, APP_VERSION
from netconsole.infrastructure.desktop import LocalDesktopAdapter, UnavailableDesktopAdapter
from netconsole.models.api.common import ErrorDetail, ErrorResponse
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.mesh_link_refresh_service import AcMeshLinkRefreshApplicationService
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.agent.controller import AgentControllerError, AgentControllerService
from netconsole.services.config_collection_web_service import ConfigCollectionApplicationService
from netconsole.services.device_management_web_service import DeviceManagementWebService
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
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard, WRITE_FEATURE_ID
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService
from netconsole.services.rail_transit.trackside_ap_business_query_service import TracksideApBusinessQueryService
from netconsole.services.rail_transit.vehicle_mr_online_query_service import VehicleMrOnlineQueryService
from netconsole.services.rail_transit.wireless_dashboard_query_service import WirelessDashboardQueryService
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError
from netconsole.services.traffic.web_application_service import TrafficWebApplicationService


_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)")
_SECRET_RE = re.compile(r"(?i)((?:x-agent-token|token)\s*[:=]\s*)[^\s,;]+")
DESKTOP_SESSION_COOKIE = "netconsole_desktop_session"
DESKTOP_SESSION_HEADER = "x-netconsole-session"


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


def create_app(
    runtime_mode: RuntimeMode = RuntimeMode.SERVER,
    *,
    paths: PathResolver | None = None,
    task_service: TaskApplicationService | None = None,
    desktop_action_service: DesktopActionService | None = None,
    agent_service: AgentControllerService | None = None,
    traffic_service: TrafficTestApplicationService | None = None,
    ac_mesh_link_refresh_service: AcMeshLinkRefreshApplicationService | None = None,
    frontend_dist: Path | None = None,
    desktop_session_token: str | None = None,
    rail_base_data_write_feature_enabled: bool | None = None,
    online_mr_application_service: OnlineMrApplicationService | None = None,
    online_mr_web_control_service: OnlineMrWebControlService | None = None,
    online_mr_web_control_enabled: bool | None = None,
    online_mr_agent_web_control_service: OnlineMrAgentWebControlService | None = None,
    online_mr_agent_executor_enabled: bool | None = None,
) -> FastAPI:
    paths = paths or PathResolver()
    site_name = _current_site_name(paths)
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
        task_service = TaskApplicationService(paths=paths, site_name=site_name)
    if agent_service is None:
        agent_service = AgentControllerService(paths=paths, site_name=site_name)
    if traffic_service is None:
        traffic_service = TrafficTestApplicationService(
            paths=paths,
            site_name=site_name,
            task_service=task_service,
            agent_controller=agent_service,
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
                },
            ),
        )
    feature_gate = FeatureGate(paths.app_root)
    web_process_adapter = LocalProcessAdapter(task_service)
    web_export_adapter = WebExportProcessAdapter(task_service)
    web_artifact_store = WebArtifactStore(paths, task_service)
    device_management_service = DeviceManagementWebService(
        paths,
        task_service,
        desktop_action_service=desktop_action_service,
        process_adapter=web_process_adapter,
    )
    config_collection_service = ConfigCollectionApplicationService(
        paths,
        task_service,
        process_adapter=web_process_adapter,
        desktop_action_service=desktop_action_service,
    )
    file_management_service = FileManagementApplicationService(
        paths,
        task_service=task_service,
        process_adapter=web_process_adapter,
        site_name=site_name,
        mesh_auto_import_enabled=feature_gate.is_enabled("file.mesh_auto_import"),
        desktop_action_service=desktop_action_service,
    )
    owns_online_mr_application_service = (
        online_mr_application_service is None
        and online_mr_web_control_service is None
        and online_mr_agent_web_control_service is None
        and (online_mr_web_control_enabled or online_mr_agent_executor_enabled)
    )
    if owns_online_mr_application_service:
        online_mr_application_service = OnlineMrApplicationService(
            paths,
            site_name=site_name,
            task_service=task_service,
            agent_profile_controller=agent_service,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            await agent_service.start()
            await traffic_service.start()
            file_management_service.start()
            yield
        finally:
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
                traffic_service.stop(),
                return_exceptions=True,
            )
            for component, result in zip(
                ("device_exports", "web_exports", "local_process", "ac_mesh_link", "traffic"),
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

    app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION.removeprefix("v"), lifespan=lifespan)
    app.state.runtime_mode = runtime_mode
    app.state.desktop_session_protected = bool(desktop_session_token)
    app.state.online_mr_web_control_enabled = online_mr_web_control_enabled
    app.state.online_mr_agent_executor_enabled = online_mr_agent_executor_enabled
    app.state.paths = paths
    app.state.backend_build_id = backend_build_id(paths.app_root)
    app.state.task_service = task_service
    app.state.web_artifact_store = web_artifact_store
    app.state.desktop_action_service = desktop_action_service
    app.state.feature_gate = feature_gate
    app.state.ac_management_query_service = AcManagementQueryService(paths)
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
    app.state.device_management_service = device_management_service
    app.state.config_collection_service = config_collection_service
    app.state.file_management_service = file_management_service
    app.state.online_mr_query_service = OnlineMrQueryService(paths)
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
    app.state.train_communication_query_service = TrainCommunicationQueryService(
        paths,
        base_query=app.state.rail_transit_base_data_query_service,
        mesh_query=app.state.ac_mesh_link_query_service,
        online_mr_query=app.state.online_mr_query_service,
        job_query=app.state.job_center_query_service,
    )
    app.state.trackside_ap_business_query_service = TracksideApBusinessQueryService(paths)
    app.state.vehicle_mr_online_query_service = VehicleMrOnlineQueryService(paths)
    app.state.mesh_analysis_query_service = MeshAnalysisQueryService(
        paths,
        base_query=app.state.rail_transit_base_data_query_service,
        online_mr_query=app.state.online_mr_query_service,
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
    app.state.rail_transit_base_data_import_service = RailTransitBaseDataImportService(
        paths,
        guard=BaseDataWriteGuard(paths, feature_enabled=rail_base_data_write_feature_enabled),
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
    )
    app.state.rail_transit_web_application_service = RailTransitWebApplicationService(
        paths,
        task_service,
        process_adapter=web_process_adapter,
        export_adapter=web_export_adapter,
        query_service=app.state.online_mr_query_service,
        mesh_query_service=app.state.mesh_analysis_query_service,
        artifact_store=web_artifact_store,
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


def _current_site_name(paths: PathResolver) -> str:
    try:
        return str(SiteManager(paths).get_current_site() or "demo")
    except (OSError, ValueError, KeyError):
        return "demo"


def _frontend_dist(paths: PathResolver) -> Path:
    if is_packaged_runtime():
        return package_resource_path("assets", "web")
    return paths.app_root / "apps" / "web" / "dist"


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
        OnlineMrQueryErrorCode.LOG_SOURCE_INVALID,
        OnlineMrQueryErrorCode.LOG_CURSOR_INVALID,
        OnlineMrQueryErrorCode.QUERY_LIMIT_EXCEEDED,
        OnlineMrQueryErrorCode.METRIC_UNSUPPORTED,
    }:
        return 422
    return 409


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("netconsole.backend.api.main:create_app", factory=True, host="127.0.0.1", port=8000, reload=False)
