from __future__ import annotations

import re
import secrets
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from netconsole.backend.api.router import api_router, ws_router
from netconsole.core.paths import PathResolver
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.resources import package_resource_path
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.core.version import APP_NAME, APP_VERSION
from netconsole.models.api.common import ErrorDetail, ErrorResponse
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.mesh_link_refresh_service import AcMeshLinkRefreshApplicationService
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.agent.controller import AgentControllerError, AgentControllerService
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.online_mr.errors import OnlineMrQueryError, OnlineMrQueryErrorCode
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard, WRITE_FEATURE_ID
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService
from netconsole.services.rail_transit.wireless_dashboard_query_service import WirelessDashboardQueryService
from netconsole.services.traffic.application_service import TrafficTestApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)")
_SECRET_RE = re.compile(r"(?i)((?:x-agent-token|token)\s*[:=]\s*)[^\s,;]+")
DESKTOP_SESSION_COOKIE = "netconsole_desktop_session"


class DesktopSessionMiddleware:
    def __init__(self, app, *, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in {"http", "websocket"} or scope.get("path") == "/__desktop_session":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        cookie = SimpleCookie()
        cookie.load(headers.get(b"cookie", b"").decode("latin-1"))
        supplied = cookie.get(DESKTOP_SESSION_COOKIE)
        if supplied is not None and secrets.compare_digest(supplied.value, self.token):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401, "reason": "desktop session required"})
            return
        response = JSONResponse(status_code=401, content={"detail": "desktop session required"})
        await response(scope, receive, send)


def create_app(
    runtime_mode: RuntimeMode = RuntimeMode.SERVER,
    *,
    paths: PathResolver | None = None,
    task_service: TaskApplicationService | None = None,
    agent_service: AgentControllerService | None = None,
    traffic_service: TrafficTestApplicationService | None = None,
    ac_mesh_link_refresh_service: AcMeshLinkRefreshApplicationService | None = None,
    frontend_dist: Path | None = None,
    desktop_session_token: str | None = None,
    rail_base_data_write_feature_enabled: bool | None = None,
) -> FastAPI:
    paths = paths or PathResolver()
    site_name = _current_site_name(paths)
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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await agent_service.start()
        await traffic_service.start()
        try:
            yield
        finally:
            await ac_mesh_link_refresh_service.stop()
            await traffic_service.stop()
            await agent_service.stop()

    app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION.removeprefix("v"), lifespan=lifespan)
    app.state.runtime_mode = runtime_mode
    app.state.paths = paths
    app.state.task_service = task_service
    app.state.ac_management_query_service = AcManagementQueryService(paths)
    app.state.ac_mesh_link_query_service = AcMeshLinkQueryService(paths)
    app.state.ac_mesh_link_refresh_service = ac_mesh_link_refresh_service
    app.state.job_center_query_service = JobCenterQueryService(paths)
    app.state.agent_service = agent_service
    app.state.traffic_service = traffic_service
    app.state.online_mr_query_service = OnlineMrQueryService(paths)
    app.state.rail_transit_base_data_query_service = RailTransitBaseDataQueryService(paths)
    app.state.train_communication_query_service = TrainCommunicationQueryService(
        paths,
        base_query=app.state.rail_transit_base_data_query_service,
        mesh_query=app.state.ac_mesh_link_query_service,
        online_mr_query=app.state.online_mr_query_service,
        job_query=app.state.job_center_query_service,
    )
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
        rail_base_data_write_feature_enabled = FeatureGate(paths.app_root).is_enabled(WRITE_FEATURE_ID)
    app.state.rail_transit_base_data_import_service = RailTransitBaseDataImportService(
        paths,
        guard=BaseDataWriteGuard(paths, feature_enabled=rail_base_data_write_feature_enabled),
    )
    app.state.rail_transit_import_preview_service = RailTransitImportPreviewService(
        app.state.rail_transit_base_data_query_service,
        import_service=app.state.rail_transit_base_data_import_service,
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

    app.include_router(api_router)
    app.include_router(ws_router)

    dist = frontend_dist or _frontend_dist(paths)
    if (dist / "index.html").is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @app.get("/{frontend_path:path}", include_in_schema=False, response_class=FileResponse)
        def frontend(frontend_path: str) -> Path:
            candidate = (dist / frontend_path).resolve()
            if frontend_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return candidate
            return dist / "index.html"

        return app

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def web_shell_placeholder() -> str:
        return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{APP_NAME}</title></head>
<body style="font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:48px;color:#202124">
<h1>{APP_NAME} Web Shell</h1>
<p>阶段 1 实验入口已运行，当前模式：{runtime_mode.value}。</p>
<p>业务页面尚未迁移。可打开 <a href="/docs">OpenAPI 文档</a> 或访问 <a href="/api/health">健康检查</a>。</p>
</body>
</html>"""

    return app


def _current_site_name(paths: PathResolver) -> str:
    try:
        return str(SiteManager(paths).get_current_site() or "demo")
    except (OSError, ValueError, KeyError):
        return "demo"


def _frontend_dist(paths: PathResolver) -> Path:
    packaged = package_resource_path("assets", "web")
    source = paths.app_root / "apps" / "web" / "dist"
    return packaged if (packaged / "index.html").is_file() else source


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


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("netconsole.backend.api.main:app", host="127.0.0.1", port=8000, reload=False)
