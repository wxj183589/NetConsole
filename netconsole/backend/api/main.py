from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from netconsole.backend.api.router import api_router, ws_router
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.core.sites import SiteManager
from netconsole.core.version import APP_NAME, APP_VERSION
from netconsole.models.api.common import ErrorDetail, ErrorResponse
from netconsole.services.agent.controller import AgentControllerError, AgentControllerService
from netconsole.services.job_center.task_application_service import TaskApplicationService


def create_app(
    runtime_mode: RuntimeMode = RuntimeMode.SERVER,
    *,
    paths: PathResolver | None = None,
    task_service: TaskApplicationService | None = None,
    agent_service: AgentControllerService | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    paths = paths or PathResolver()
    site_name = _current_site_name(paths)
    if task_service is None:
        task_service = TaskApplicationService(paths=paths, site_name=site_name)
    if agent_service is None:
        agent_service = AgentControllerService(paths=paths, site_name=site_name)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await agent_service.start()
        try:
            yield
        finally:
            await agent_service.stop()

    app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION.removeprefix("v"), lifespan=lifespan)
    app.state.runtime_mode = runtime_mode
    app.state.paths = paths
    app.state.task_service = task_service
    app.state.agent_service = agent_service

    @app.exception_handler(AgentControllerError)
    async def agent_error_handler(_: Request, exc: AgentControllerError) -> JSONResponse:
        payload = ErrorResponse(error=ErrorDetail(code=exc.code, message=exc.message))
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump(mode="json"))

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
    packaged = paths.app_root / "frontend" / "dist"
    source = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return packaged if (packaged / "index.html").is_file() else source


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("netconsole.backend.api.main:app", host="127.0.0.1", port=8000, reload=False)
