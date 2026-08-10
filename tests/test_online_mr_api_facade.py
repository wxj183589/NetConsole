from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from netconsole.backend.api.online_mr_control_router import router as local_router
from netconsole.backend.api.online_mr_router import router as query_router
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.models.api.online_mr_control import OnlineMrWebStartRequestDTO
from netconsole.services.online_mr.api_facade import OnlineMrApiFacade
from netconsole.services.online_mr.errors import (
    OnlineMrSiteContextError,
    OnlineMrSiteContextErrorCode,
    OnlineMrWebControlError,
    OnlineMrWebControlErrorCode,
)
from netconsole.services.online_mr.web_control_service import OnlineMrWebControlService


class _Query:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def get_current_session(self, site_id: str, *, session_id: str | None = None):
        self.calls.append(("current", site_id, session_id))
        return None


class _Local:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.on_start: Callable[[], None] | None = None

    def status(self, site_id: str):
        self.calls.append(("status", site_id))
        return None

    def start(self, payload, *, current_site_id: str):
        self.calls.append(("start", current_site_id, payload.site_id))
        if self.on_start is not None:
            self.on_start()
        return None

    def get_operation(self, operation_id: str, *, site_id: str | None = None):
        self.calls.append(("detail", operation_id, site_id))
        return None

    def stop(self, operation_id: str, *, site_id: str | None = None):
        self.calls.append(("stop", operation_id, site_id))
        return None


class _Agent:
    pass


def _facade(paths: PathResolver) -> tuple[OnlineMrApiFacade, _Query, _Local]:
    query = _Query()
    local = _Local()
    return OnlineMrApiFacade(paths, query, local, _Agent()), query, local  # type: ignore[arg-type]


def _write_current_site(paths: PathResolver, site_id: object) -> None:
    paths.app_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text(
        json.dumps({"current_site": site_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def _tree(root: Path) -> dict[str, tuple[bool, bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.is_dir(),
            b"" if path.is_dir() else path.read_bytes(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
    }


def _api(facade: OnlineMrApiFacade) -> FastAPI:
    app = FastAPI()
    app.state.online_mr_api_facade = facade
    app.state.runtime_mode = RuntimeMode.DESKTOP

    @app.middleware("http")
    async def desktop_session(request: Request, call_next):
        request.state.desktop_session_authenticated = True
        return await call_next(request)

    @app.exception_handler(OnlineMrSiteContextError)
    async def site_error(_: Request, exc: OnlineMrSiteContextError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(query_router, prefix="/api")
    app.include_router(local_router, prefix="/api")
    return app


def test_current_site_is_read_only_and_distinguishes_context_failures(tmp_path: Path) -> None:
    cases = (
        ("not-selected", None, OnlineMrSiteContextErrorCode.NOT_SELECTED),
        ("empty-selection", "", OnlineMrSiteContextErrorCode.NOT_SELECTED),
        ("not-found", "missing", OnlineMrSiteContextErrorCode.NOT_FOUND),
        ("invalid", "../site-a", OnlineMrSiteContextErrorCode.INVALID),
    )
    for name, value, code in cases:
        paths = PathResolver(app_root=tmp_path / name, data_root=tmp_path / name)
        if value is not None:
            _write_current_site(paths, value)
        before = _tree(tmp_path / name)
        facade, _, _ = _facade(paths)
        with pytest.raises(OnlineMrSiteContextError) as error:
            facade.current_site_id()
        assert error.value.code == code
        assert _tree(tmp_path / name) == before


def test_current_site_accepts_only_an_existing_selected_site(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("site-a").mkdir(parents=True)
    _write_current_site(paths, "site-a")
    before = _tree(tmp_path)

    facade, _, _ = _facade(paths)

    assert facade.current_site_id() == "site-a"
    assert _tree(tmp_path) == before


def test_current_site_reports_unavailable_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.app_config_path.parent.mkdir(parents=True)
    before = _tree(tmp_path)
    original = Path.read_text

    def unavailable(path: Path, *args, **kwargs):
        if path == paths.app_config_path:
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unavailable)
    facade, _, _ = _facade(paths)
    with pytest.raises(OnlineMrSiteContextError) as error:
        facade.current_site_id()

    assert error.value.code == OnlineMrSiteContextErrorCode.UNAVAILABLE
    assert _tree(tmp_path) == before


def test_get_and_start_site_preflight_failures_have_zero_side_effects(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    facade, query, local = _facade(paths)
    app = _api(facade)
    before = _tree(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        get_response = client.get("/api/online-mr/sessions/current")
        start_response = client.post(
            "/api/rail-transit/online-mr-control/start",
            json={"site_id": "site-a", "device_id": 7, "mr_id": "mr-7", "executor": "LOCAL"},
        )

    assert get_response.status_code == start_response.status_code == 422
    assert get_response.json()["error"]["code"] == OnlineMrSiteContextErrorCode.NOT_SELECTED
    assert start_response.json()["error"]["code"] == OnlineMrSiteContextErrorCode.NOT_SELECTED
    assert query.calls == local.calls == []
    assert _tree(tmp_path) == before


def test_start_site_mismatch_fails_before_database_or_config_writes(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("site-a").mkdir(parents=True)
    _write_current_site(paths, "site-a")
    local = OnlineMrWebControlService(
        paths,
        None,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        enabled=True,
    )
    facade = OnlineMrApiFacade(paths, _Query(), local, _Agent())  # type: ignore[arg-type]
    before = _tree(tmp_path)

    with pytest.raises(OnlineMrWebControlError) as error:
        facade.start_local(
            OnlineMrWebStartRequestDTO(site_id="site-b", device_id=7, mr_id="mr-7")
        )

    assert error.value.code == OnlineMrWebControlErrorCode.INVALID_REQUEST
    assert _tree(tmp_path) == before


def test_start_captures_one_site_snapshot_and_operation_calls_do_not_rebind(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.site_dir("site-a").mkdir(parents=True)
    paths.site_dir("site-b").mkdir(parents=True)
    _write_current_site(paths, "site-a")
    facade, _, local = _facade(paths)
    local.on_start = lambda: _write_current_site(paths, "site-b")
    payload = type("Payload", (), {"site_id": "site-a"})()

    facade.start_local(payload)  # type: ignore[arg-type]
    facade.local_operation("operation-a")
    facade.stop_local("operation-a")

    assert local.calls == [
        ("start", "site-a", "site-a"),
        ("detail", "operation-a", None),
        ("stop", "operation-a", None),
    ]


def test_online_mr_routers_only_depend_on_the_injected_facade() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in (
        "online_mr_router.py",
        "online_mr_control_router.py",
        "online_mr_agent_control_router.py",
    ):
        source = (root / "src" / "netconsole" / "backend" / "api" / name).read_text(encoding="utf-8")
        assert "online_mr_api_facade" in source
        for forbidden in (
            "SiteManager",
            "PathResolver",
                "from netconsole.core.database import Database",
            "Repository",
            "OnlineMrQueryService",
            "OnlineMrWebControlService",
            "OnlineMrAgentWebControlService",
        ):
            assert forbidden not in source
