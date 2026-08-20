from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    ProductionWriteBlockedError,
    data_environment,
    require_production_write_allowed,
    write_data_environment,
)
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.backend.api.main import ProductionMaintenanceAdmissionMiddleware


def test_persistent_root_requires_an_explicit_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    with pytest.raises(RuntimeError, match="runtime_mode.json"):
        data_environment(tmp_path)


def test_environment_marker_round_trip_and_path_resolver_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(
            DataEnvironmentMode.DEVELOPMENT,
            created_from=r"D:\NetConsoleData",
            created_time="2026-08-21T00:00:00+00:00",
        ),
    )

    info = PathResolver(app_root=tmp_path / "app", data_root=tmp_path).data_environment
    assert info.mode is DataEnvironmentMode.DEVELOPMENT
    assert info.label == "DEV COPY"
    assert json.loads((tmp_path / "runtime_mode.json").read_text(encoding="utf-8"))["created_from"] == r"D:\NetConsoleData"


def test_production_write_requires_explicit_process_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    with pytest.raises(ProductionWriteBlockedError, match="allow-production-write"):
        require_production_write_allowed(tmp_path, "test-maintenance")

    monkeypatch.setenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", "1")
    require_production_write_allowed(tmp_path, "test-maintenance")


def test_development_copy_allows_maintenance_without_production_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop-development")
    write_data_environment(
        tmp_path,
        DataEnvironmentInfo(DataEnvironmentMode.DEVELOPMENT, created_from=r"D:\NetConsoleData"),
    )
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    require_production_write_allowed(tmp_path, "test-maintenance")


def test_test_environment_is_process_bound_and_does_not_require_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")
    assert data_environment(tmp_path).mode is DataEnvironmentMode.TEST


def test_production_middleware_blocks_rebuild_but_allows_mesh_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    calls: list[str] = []

    async def downstream(scope, receive, send) -> None:
        calls.append(str(scope["path"]))

    middleware = ProductionMaintenanceAdmissionMiddleware(
        downstream,
        state=SimpleNamespace(
            data_environment=DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True)
        ),
    )

    async def invoke(path: str) -> list[dict]:
        messages: list[dict] = []

        async def send(message: dict) -> None:
            messages.append(message)

        await middleware({"type": "http", "method": "POST", "path": path}, None, send)
        return messages

    blocked = asyncio.run(invoke("/api/rail-transit/mesh-analysis/sessions/s1/rebuild"))
    allowed = asyncio.run(invoke("/api/rail-transit/mesh-analysis/ap-coverage/export"))

    assert blocked[0]["status"] == 409
    assert allowed == []
    assert calls == ["/api/rail-transit/mesh-analysis/ap-coverage/export"]
