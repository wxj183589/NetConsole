from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.main import DESKTOP_SESSION_HEADER, DesktopShutdownAdmissionMiddleware
from netconsole.backend.electron_runtime import (
    ElectronRuntimeOptions,
    build_app,
    emit_shutdown_ack,
    emit_shutdown_complete,
    emit_shutdown_received,
    _start_shutdown_progress_monitor,
    _stop_shutdown_progress_monitor,
    parse_options,
    read_session_token,
    wait_for_exit_command,
    watch_control_stream,
)
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ap_identity import ApIdentityQueryService


TOKEN = "electron-test-token-abcdefghijklmnopqrstuvwxyz"


def test_electron_runtime_accepts_only_loopback_configuration() -> None:
    options = parse_options(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--renderer-origin",
            "http://127.0.0.1:5173",
        ]
    )

    assert options == ElectronRuntimeOptions(
        host="127.0.0.1",
        port=0,
        renderer_origin="http://127.0.0.1:5173",
        development=False,
    )


def test_electron_runtime_accepts_explicit_loopback_development_mode() -> None:
    options = parse_options(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--renderer-origin",
            "http://127.0.0.1:5173",
            "--dev-mode",
        ]
    )

    assert options == ElectronRuntimeOptions(
        host="127.0.0.1",
        port=8000,
        renderer_origin="http://127.0.0.1:5173",
        development=True,
    )


def test_packaged_electron_runtime_rejects_development_mode(monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    monkeypatch.setattr(electron_runtime, "is_packaged_runtime", lambda: True)

    with pytest.raises(SystemExit):
        parse_options(["--host", "127.0.0.1", "--port", "8000", "--dev-mode"])


@pytest.mark.parametrize(
    "arguments",
    [
        ["--host", "0.0.0.0", "--port", "43123"],
        ["--port", "-1"],
        ["--port", "43123", "--renderer-origin", "https://127.0.0.1:5173"],
        ["--port", "43123", "--renderer-origin", "http://localhost:5173"],
        ["--port", "43123", "--renderer-origin", "http://127.0.0.1:5173/path"],
    ],
)
def test_electron_runtime_rejects_unsafe_configuration(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_options(arguments)


def test_session_token_is_read_from_bounded_stdin_json() -> None:
    assert read_session_token(io.StringIO(f'{{"session_token":"{TOKEN}"}}\n')) == TOKEN


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not-json\n",
        '{"session_token":"short"}\n',
        '{"session_token":"contains spaces and is deliberately long enough"}\n',
    ],
)
def test_session_token_rejects_invalid_handshake(payload: str) -> None:
    with pytest.raises(ValueError):
        read_session_token(io.StringIO(payload))


def test_control_stream_requests_shutdown_and_ignores_unknown_messages() -> None:
    server = SimpleNamespace(should_exit=False)
    shutdown_requested = False

    def mark_shutdown() -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    watch_control_stream(
        io.StringIO('not-json\n{"command":"unknown"}\n{"command":"shutdown"}\n'),
        server,
        on_shutdown=mark_shutdown,
    )

    assert server.should_exit is True


def test_shutdown_progress_monitor_emits_only_count_changes() -> None:
    output = io.StringIO()
    values = [{"active_tasks": 6, "active_workers": 2}, {"active_tasks": 3, "active_workers": 1}, {"active_tasks": 0, "active_workers": 0}]
    app = FastAPI()
    app.state.task_service = SimpleNamespace(active_task_snapshot=lambda: values[0])
    _start_shutdown_progress_monitor(app, output)
    import time

    time.sleep(0.25)
    app.state.task_service.active_task_snapshot = lambda: values[1]
    time.sleep(0.25)
    app.state.task_service.active_task_snapshot = lambda: values[2]
    time.sleep(0.25)
    _stop_shutdown_progress_monitor(app)
    progress = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [item["active_tasks"] for item in progress] == [6, 3, 0]
    assert shutdown_requested is True


def test_shutdown_lifecycle_events_are_emitted_as_bounded_json_events() -> None:
    output = io.StringIO()

    emit_shutdown_received(output)
    output.seek(0)
    assert json.loads(output.readline()) == {
        "event": "netconsole.electron_backend.shutdown_received"
    }
    output = io.StringIO()
    emit_shutdown_complete(output)
    assert json.loads(output.getvalue()) == {
        "event": "netconsole.electron_backend.shutdown_complete"
    }
    output = io.StringIO()
    emit_shutdown_ack(output)

    assert json.loads(output.getvalue()) == {
        "event": "netconsole.electron_backend.shutdown_ack"
    }


def test_build_app_forwards_startup_stage_callback(monkeypatch) -> None:
    stages: list[str] = []
    captured: dict[str, object] = {}

    def fake_create_app(*args, **kwargs):
        captured.update(kwargs)
        return FastAPI()

    monkeypatch.setattr("netconsole.backend.electron_runtime.create_app", fake_create_app)

    build_app(
        ElectronRuntimeOptions(host="127.0.0.1", port=0),
        "a" * 32,
        startup_stage=stages.append,
    )

    assert captured["startup_stage"] == stages.append


def test_desktop_shutdown_admission_rejects_new_mutating_requests() -> None:
    app = FastAPI()
    app.state.accepting_work = False
    app.add_middleware(DesktopShutdownAdmissionMiddleware, state=app.state)

    @app.get("/read")
    def read() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/write")
    def write() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/read").status_code == 200
        response = client.post("/write")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"


def test_startup_failure_protocol_is_ascii_and_preserves_chinese(monkeypatch, capsys) -> None:
    from netconsole.backend import electron_runtime
    from netconsole.core.storage_manifest import StorageCompatibilityError

    class InstanceLock:
        def __init__(self, _paths) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

    monkeypatch.setattr(electron_runtime, "PathResolver", lambda: object())
    monkeypatch.setattr(electron_runtime, "BackendInstanceLock", InstanceLock)
    monkeypatch.setattr(
        electron_runtime,
        "prepare_storage_manifest",
        lambda _paths: (_ for _ in ()).throw(StorageCompatibilityError("数据目录初始化失败")),
    )

    result = electron_runtime.main(
        ["--host", "127.0.0.1", "--port", "0"],
        stdin=io.StringIO(f'{{"session_token":"{TOKEN}"}}\n'),
    )
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]

    assert result == 3
    assert output.isascii()
    assert [event["stage"] for event in events[:-1]] == [
        "paths_resolving",
        "paths_resolved",
        "instance_lock_acquiring",
        "instance_lock_acquired",
        "storage_manifest_preparing",
    ]
    assert events[-1]["message"] == "数据目录初始化失败"


def test_slow_storage_manifest_is_announced_before_work_starts(monkeypatch, capsys) -> None:
    from netconsole.backend import electron_runtime
    from netconsole.core.storage_manifest import StorageCompatibilityError

    class InstanceLock:
        def __init__(self, _paths) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

    def slow_manifest(_paths) -> None:
        output = capsys.readouterr().out
        stages = [json.loads(line)["stage"] for line in output.splitlines()]
        assert stages[-1] == "storage_manifest_preparing"
        raise StorageCompatibilityError("simulated slow storage stop")

    monkeypatch.setattr(electron_runtime, "PathResolver", lambda: object())
    monkeypatch.setattr(electron_runtime, "BackendInstanceLock", InstanceLock)
    monkeypatch.setattr(electron_runtime, "prepare_storage_manifest", slow_manifest)

    result = electron_runtime.main(
        ["--host", "127.0.0.1", "--port", "0"],
        stdin=io.StringIO(f'{{"session_token":"{TOKEN}"}}\n'),
    )

    assert result == 3


def test_upgrade_recovery_is_announced_before_storage_scan(monkeypatch) -> None:
    from netconsole.backend.api import main as api_main
    from netconsole.core.runtime_mode import RuntimeMode

    stages: list[str] = []

    def slow_recovery(_paths):
        assert stages[-1] == "upgrade_recovery_started"
        raise RuntimeError("simulated slow recovery stop")

    monkeypatch.setattr(api_main, "recover_incomplete_upgrades", slow_recovery)

    with pytest.raises(RuntimeError, match="simulated slow recovery stop"):
        api_main.create_app(
            RuntimeMode.TEST,
            paths=object(),
            startup_stage=stages.append,
        )


def test_active_site_storage_stages_are_emitted_before_slow_operations(monkeypatch) -> None:
    from netconsole.backend.api import main as api_main

    stages: list[str] = []

    class SlowDatabase:
        def __init__(self, _path) -> None:
            pass

        def exists(self) -> bool:
            return True

        def initialize(self) -> None:
            assert stages[-1] == "active_site_database_initializing"

    class SlowIdentityService:
        def __init__(self, _database) -> None:
            pass

        def ensure_index(self, reason: str) -> None:
            assert reason == "backend_startup"
            assert stages[-1] == "ap_identity_index_initializing"

    paths = SimpleNamespace(site_db_path=lambda _site_name: Path("slow-storage.sqlite"))
    monkeypatch.setattr(api_main, "Database", SlowDatabase)
    monkeypatch.setattr(api_main, "ApIdentityQueryService", SlowIdentityService)

    api_main._initialize_active_site_database(
        paths,
        "demo",
        startup_stage=stages.append,
    )

    assert stages == [
        "active_site_database_initializing",
        "active_site_database_ready",
        "ap_identity_index_initializing",
        "ap_identity_index_ready",
    ]


def test_exit_command_wait_ignores_unknown_messages_and_eof() -> None:
    wait_for_exit_command(io.StringIO('not-json\n{"command":"unknown"}\n{"command":"exit"}\n'))
    wait_for_exit_command(io.StringIO(""))


def test_control_stream_eof_also_requests_shutdown() -> None:
    server = SimpleNamespace(should_exit=False)
    watch_control_stream(io.StringIO(""), server)

    assert server.should_exit is True


def test_electron_runtime_authenticates_http_with_ephemeral_header(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(ElectronRuntimeOptions("127.0.0.1", 43123), TOKEN)

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        response = client.get(
            "/api/health",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["data_root"]
    assert response.json()["active_site_id"]
    assert response.json()["storage_schema_version"] == 1
    assert response.json()["status"] == "ok"


def test_electron_backend_initializes_legacy_active_site_before_device_query(
    tmp_path: Path,
) -> None:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
    )
    site = "legacy-site"
    paths.ensure_site_dirs(site)
    database = Database(paths.site_db_path(site))
    database.initialize()
    created = DeviceRepository(database).create(
        Device(
            name="冻结旧库设备",
            primary_address="198.51.100.81",
            ssh_username="admin",
            ssh_password="secret",
        )
    )
    with database.connect() as connection:
        connection.execute("DROP INDEX idx_devices_work_scope_status")
        connection.execute("DROP INDEX idx_devices_project_phase")
        for column in (
            "work_scope_updated_by",
            "work_scope_updated_at",
            "work_scope_reason",
            "work_scope_status",
            "project_phase",
        ):
            connection.execute(f"ALTER TABLE devices DROP COLUMN {column}")
        connection.execute(
            "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
            ("2026.07.29.device_primary_address_identity",),
        )
        connection.commit()

    app = build_app(
        ElectronRuntimeOptions("127.0.0.1", 43123),
        TOKEN,
        paths=paths,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/device-management/devices",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["device_uuid"] == created.device_uuid
    assert response.json()["items"][0]["project_phase"] == "unspecified"
    assert response.json()["items"][0]["work_scope_status"] == "included"

    backups = sorted(
        (
            paths.site_files_dir(site)
            / "backups"
            / "database-migrations"
        ).glob("devices-site-*-before-work-scope-status-*.sqlite")
    )
    assert len(backups) == 1

    restarted = build_app(
        ElectronRuntimeOptions("127.0.0.1", 43123),
        TOKEN,
        paths=paths,
    )
    with TestClient(restarted) as client:
        response = client.get(
            "/api/device-management/devices",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert len(
        list(
            (
                paths.site_files_dir(site)
                / "backups"
                / "database-migrations"
            ).glob("devices-site-*-before-work-scope-status-*.sqlite")
        )
    ) == 1


def test_electron_backend_startup_refreshes_stale_identity_index(
    tmp_path: Path,
) -> None:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
    )
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    AcRepository(database).upsert_ap_extension_point(
        {
            "ap_name": "AP-STARTUP-STALE",
            "ap_point_code": "AP-STARTUP-STALE",
            "ap_vendor": "H3C",
            "ap_mac_display": "74ad-cb9d-3320",
            "station_name": "测试站",
            "belong_type": "station",
        }
    )
    before = ApIdentityQueryService(database).index_state()

    build_app(
        ElectronRuntimeOptions("127.0.0.1", 43123),
        TOKEN,
        paths=paths,
    )

    after = ApIdentityQueryService(database).index_state()
    assert before is not None
    assert after is not None
    assert before["revision"] == 0
    assert after["revision"] == 1
    assert after["source_revision"] >= 0


def test_electron_runtime_does_not_publish_api_documentation(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(ElectronRuntimeOptions("127.0.0.1", 43123), TOKEN)

    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = client.get(path, headers={DESKTOP_SESSION_HEADER: TOKEN})
            assert response.status_code == 404
        assert client.get(
            "/api/dev/runtime-status",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        ).status_code == 404

    assert app.state.api_documentation_enabled is False


def test_electron_development_runtime_is_authenticated_and_redacted(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(
        ElectronRuntimeOptions(
            "127.0.0.1",
            8000,
            "http://127.0.0.1:5173",
            development=True,
        ),
        TOKEN,
    )

    with TestClient(app, client=("127.0.0.1", 50123)) as client:
        assert client.get("/api/dev/runtime-status").status_code == 401
        response = client.get(
            "/api/dev/runtime-status",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )
        session = client.post(
            "/api/dev/session",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )
        cookie_status = client.get("/api/dev/runtime-status")
        docs = client.get("/openapi.json")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_mode"] == "electron-development"
    assert body["frontend_mode"] == "vite"
    assert body["data_root"] == "<redacted>"
    assert body["storage_mode"] == "persistent"
    assert body["data_root_kind"] == "persistent"
    assert body["persistent"] is True
    assert str(tmp_path) not in response.text
    assert TOKEN not in response.text
    assert session.status_code == 204
    set_cookie = session.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/" in set_cookie
    assert cookie_status.status_code == 200
    assert docs.status_code == 200
    assert app.state.api_documentation_enabled is True


def test_electron_development_api_rejects_non_loopback_client(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(
        ElectronRuntimeOptions("127.0.0.1", 8000, development=True),
        TOKEN,
    )

    with TestClient(app, client=("192.0.2.10", 50123)) as client:
        response = client.get(
            "/api/dev/runtime-status",
            headers={DESKTOP_SESSION_HEADER: TOKEN},
        )

    assert response.status_code == 403


def test_electron_runtime_cors_is_limited_to_declared_vite_origin(tmp_path, monkeypatch) -> None:
    from netconsole.backend import electron_runtime

    original_create_app = electron_runtime.create_app

    def isolated_create_app(*args, **kwargs):
        from netconsole.core.paths import PathResolver

        kwargs["paths"] = PathResolver(tmp_path)
        kwargs["frontend_dist"] = tmp_path / "missing-web-dist"
        return original_create_app(*args, **kwargs)

    monkeypatch.setattr(electron_runtime, "create_app", isolated_create_app)
    app = build_app(
        ElectronRuntimeOptions("127.0.0.1", 43123, "http://127.0.0.1:5173"),
        TOKEN,
    )

    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": DESKTOP_SESSION_HEADER,
            },
        )
        denied = client.options(
            "/api/health",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": DESKTOP_SESSION_HEADER,
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in denied.headers
