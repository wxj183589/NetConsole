from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from netconsole.backend.api.error_mapping import (
    classify_sqlite_error,
    map_api_errors,
)
from scripts.architecture.checks import (
    ROUTER_ROOT,
    SQLITE_DEPENDENCY,
    router_boundary_messages,
)


TEMPORARY_WAVE_DEBT: dict[str, set[str]] = {}


def test_routers_keep_static_application_boundary() -> None:
    actual = {
        path.name: findings
        for path in sorted(ROUTER_ROOT.glob("*_router.py"))
        if (findings := router_boundary_messages(path))
    }
    assert actual == TEMPORARY_WAVE_DEBT


def test_router_boundary_allows_controlled_transport_responses(tmp_path: Path) -> None:
    router = tmp_path / "transport_router.py"
    router.write_text(
        "from fastapi import WebSocket\n"
        "from fastapi.responses import FileResponse, StreamingResponse\n"
        "def download(path): return FileResponse(path)\n"
        "def stream(rows): return StreamingResponse(rows)\n"
        "async def socket(websocket: WebSocket): await websocket.accept()\n",
        encoding="utf-8",
    )
    assert router_boundary_messages(router) == set()


def test_router_boundary_rejects_runtime_dependencies_and_construction(
    tmp_path: Path,
) -> None:
    router = tmp_path / "invalid_router.py"
    router.write_text(
        "import sqlite3, zipfile, paramiko\n"
        "from netconsole.core.database import Database\n"
        "from netconsole.core.paths import PathResolver\n"
        "from netconsole.core.sites import SiteManager\n"
        "from netconsole.repositories.device_repository import DeviceRepository\n"
        "from netconsole.parsers.cli import CommandParser\n"
        "from netconsole.services.demo import DemoApplicationService\n"
        "def route():\n"
        " sqlite3.connect('runtime.db')\n"
        " Database(); PathResolver(); DeviceRepository(); CommandParser(); DemoApplicationService()\n"
        " SiteManager().get_current_site(); zipfile.ZipFile('runtime.zip'); __import__('module')\n",
        encoding="utf-8",
    )

    findings = router_boundary_messages(router)
    assert SQLITE_DEPENDENCY in findings
    assert "sqlite3 runtime call connect" in findings
    assert "stateful SiteManager.get_current_site" in findings
    assert "infrastructure construction DemoApplicationService" in findings
    assert "dynamic import or constructor lookup" in findings
    assert {"forbidden import zipfile", "forbidden import paramiko"} <= findings
    assert any(
        item.startswith("forbidden import netconsole.repositories")
        for item in findings
    )


def test_router_boundary_rejects_sqlite_direct_symbol_import(tmp_path: Path) -> None:
    router = tmp_path / "sqlite_symbol_router.py"
    router.write_text("from sqlite3 import OperationalError\n", encoding="utf-8")
    assert router_boundary_messages(router) == {SQLITE_DEPENDENCY}


def test_shared_api_error_mapping_keeps_database_and_io_contracts() -> None:
    with pytest.raises(HTTPException) as database_error:
        with map_api_errors("数据库暂时不可读"):
            raise sqlite3.OperationalError("locked")
    assert (database_error.value.status_code, database_error.value.detail) == (
        503,
        "数据库暂时不可读",
    )

    with pytest.raises(HTTPException) as io_error:
        with map_api_errors(
            "数据库暂时不可读", io_detail="文件暂时不可读", io_status_code=404
        ):
            raise OSError("denied")
    assert (io_error.value.status_code, io_error.value.detail) == (
        404,
        "文件暂时不可读",
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("no such column: d.operation_status", "DEVICE_DATABASE_SCHEMA_NOT_READY"),
        ("database is locked", "DEVICE_DATABASE_BUSY"),
        ("attempt to write a readonly database", "DEVICE_DATABASE_ACCESS_DENIED"),
        ("database disk image is malformed", "DEVICE_DATABASE_INTEGRITY_ERROR"),
        ("disk I/O error", "DEVICE_DATABASE_IO_ERROR"),
        ("unknown sqlite failure", "DEVICE_DATABASE_UNAVAILABLE"),
    ),
)
def test_sqlite_error_classification_is_specific(
    message: str, expected: str
) -> None:
    assert classify_sqlite_error(sqlite3.OperationalError(message)) == expected


def test_structured_database_error_hides_private_diagnostics() -> None:
    with pytest.raises(HTTPException) as captured:
        with map_api_errors(
            "设备数据库暂时不可读",
            structured_database_errors=True,
            database_context={
                "operation": "list_devices",
                "site": "line-one",
                "database_path": r"D:\private\devices.db",
                "schema_version": "old",
                "missing_columns": ["operation_status"],
            },
        ):
            raise sqlite3.OperationalError(
                "no such column: d.operation_status"
            )

    assert captured.value.status_code == 503
    detail = captured.value.detail
    assert detail["code"] == "DEVICE_DATABASE_SCHEMA_NOT_READY"
    assert detail["details"]["operation"] == "list_devices"
    assert detail["details"]["site"] == "line-one"
    assert "database_path" not in detail["details"]
    assert "missing_columns" not in detail["details"]
