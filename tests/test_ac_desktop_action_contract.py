from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest

from fastapi.testclient import TestClient

from tests.support.ac_management_web_fixture import build_ac_management_fixture

from tests.support.rail_transit_base_data_fixture import mark_base_data_copy

from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter

from netconsole.application.ac.web_application_service import AcWebActionError, AcWebApplicationService

from netconsole.backend.api.main import create_app

from netconsole.core.database import Database

from netconsole.core.runtime_mode import RuntimeMode

from netconsole.core.settings import SettingsStore

from netconsole.services.job_center.task_application_service import TaskApplicationService

from netconsole.services.rail_transit.base_data_import_service import RailTransitBaseDataImportService

from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService

from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard

from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService

AC_FEATURE_IDS = (
    "capability.ac.extensions",
    "capability.ac.extensions.preview",
    "capability.ac.extensions.apply",
    "capability.ac.extensions.rollback",
    "capability.ac.extensions.export",
    "capability.ac.refresh",
    "capability.ac.fit_ap.delete",
    "capability.ac.fit_ap.metadata_import",
    "capability.ac.fit_ap.metadata_write",
    "capability.ac.fit_ap.history",
    "capability.ac.fit_ap.resource_export",
    "capability.ac.dangerous_actions",
    "ac.omnipeek_name_table_export",
    "capability.ac.external_terminal",
    "capability.desktop_native_integration",
)

class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

def _service(paths, tasks=None, *, desktop_action_service=None):
    mark_base_data_copy(paths)
    tasks = tasks or TaskApplicationService(paths=paths, site_name="demo")
    normal = FakeLocalProcessAdapter(tasks)
    export = FakeExportProcessAdapter(tasks)
    guard = BaseDataWriteGuard(
        paths,
        feature_enabled=True,
        write_enabled=True,
        copy_write_enabled=True,
        rollback_enabled=True,
    )
    imports = RailTransitBaseDataImportService(paths, guard=guard)
    previews = RailTransitImportPreviewService(
        RailTransitBaseDataQueryService(paths), import_service=imports
    )
    service = AcWebApplicationService(
        paths,
        tasks,
        process_adapter=normal,  # type: ignore[arg-type]
        import_preview_service=previews,
        base_import_service=imports,
        export_adapter=export,  # type: ignore[arg-type]
        desktop_action_service=desktop_action_service,
    )
    return service, normal, export, tasks

def _enable_features(app, feature_ids=AC_FEATURE_IDS) -> None:
    for feature_id in feature_ids:
        app.state.feature_gate.features[feature_id] = {
            "visible": True,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        }

def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AcWebApplicationService]:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.app_config_path.write_text('{"current_site":"demo"}', encoding="utf-8")
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    service, _normal, _export, _tasks = _service(paths, app.state.task_service)
    app.state.ac_web_application_service = service
    _enable_features(app)
    return TestClient(app), service

class _FakeDesktopActionService:
    runtime_mode = RuntimeMode.DESKTOP

    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.launches: list[tuple[str, str, object]] = []

    def launch_terminal(self, action_id: str, object_id: str, launch):
        self.launches.append((action_id, object_id, launch))
        return SimpleNamespace(success=self.success, message="fixture launch failed" if not self.success else "")


def test_fit_ap_external_terminal_launches_fixed_telnet_without_credentials_or_device_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    terminals = {
        "securecrt": tmp_path / "SecureCRT.exe",
        "xshell": tmp_path / "Xshell.exe",
        "putty": tmp_path / "putty.exe",
    }
    for terminal in terminals.values():
        terminal.write_bytes(b"fixture")
    settings = SettingsStore(paths)
    settings.set_value("external_terminal/securecrt_path", str(terminals["securecrt"]))
    settings.set_value("external_terminal/xshell_path", str(terminals["xshell"]))
    settings.set_value("external_terminal/putty_path", str(terminals["putty"]))
    settings.set_value("external_terminal/type", "securecrt")
    settings.set_value("external_terminal/pass_password", True)
    desktop = _FakeDesktopActionService()
    service, _normal, _export, _tasks = _service(paths, desktop_action_service=desktop)

    expected_args = {
        "securecrt": ("/TELNET", "10.0.1.1", "23"),
        "xshell": ("-url", "telnet://10.0.1.1:23"),
        "putty": ("-telnet", "10.0.1.1", "-P", "23"),
    }
    for terminal_type, arguments in expected_args.items():
        launched = service.launch_fit_ap_external_terminal(
            "demo", ac_id="ac-1", ap_id="ap-online", terminal_type=terminal_type
        )
        assert launched.ap_id == "ap-online"
        assert launched.terminal_type == terminal_type
        assert launched.protocol == "telnet"
        assert launched.port == 23
        assert launched.message == "已打开 AP-Online 的 Telnet 终端"
        action_id, object_id, launch = desktop.launches[-1]
        assert (action_id, object_id) == (f"terminal.{terminal_type}", "ap-online")
        assert launch.executable == terminals[terminal_type].resolve()
        assert launch.arguments == arguments
        serialized = " ".join(launch.arguments).casefold()
        assert "/password" not in serialized
        assert "-pw" not in serialized
        assert "ssh://" not in serialized
        assert "@" not in serialized
    legacy_profile_file = "fit_ap_" + "remote_" + "terminal_" + "profiles.json"
    assert not (paths.config_dir / legacy_profile_file).exists()

    failed_desktop = _FakeDesktopActionService(success=False)
    failed_service, _normal2, _export2, _tasks2 = _service(
        paths, desktop_action_service=failed_desktop
    )
    with pytest.raises(AcWebActionError) as launch_failed:
        failed_service.launch_fit_ap_external_terminal(
            "demo", ac_id="ac-1", ap_id="ap-online", terminal_type="securecrt"
        )
    assert launch_failed.value.code == "TERMINAL_LAUNCH_FAILED"

    server_service, _normal3, _export3, _tasks3 = _service(paths)
    with pytest.raises(AcWebActionError) as server_rejected:
        server_service.launch_fit_ap_external_terminal(
            "demo", ac_id="ac-1", ap_id="ap-online", terminal_type="securecrt"
        )
    assert server_rejected.value.code == "DESKTOP_REQUIRED"

    client, _client_service = _client(tmp_path / "api", monkeypatch)
    with client:
        rejected = client.post(
            "/api/ac-management/fit-aps/ap-online/external-terminal",
            json={
                "ac_id": "ac-1",
                "terminal_type": "securecrt",
                "executable": "cmd.exe",
                "arguments": ["/c", "whoami"],
                "protocol": "ssh",
                "port": 22,
                "username": "must-not-enter-api",
                "password": "must-not-enter-api",
            },
        )
    assert rejected.status_code == 422


def test_fit_ap_external_terminal_rejects_invalid_ap_scope_state_and_runtime(tmp_path: Path) -> None:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    terminal = tmp_path / "PuTTY.exe"
    terminal.write_bytes(b"fixture")
    settings = SettingsStore(paths)
    settings.set_value("external_terminal/putty_path", str(terminal))
    desktop = _FakeDesktopActionService()
    service, _normal, _export, _tasks = _service(paths, desktop_action_service=desktop)

    with pytest.raises(AcWebActionError) as offline:
        service.launch_fit_ap_external_terminal(
            "demo", ac_id="ac-1", ap_id="ap-offline", terminal_type="putty"
        )
    assert offline.value.code == "AP_NOT_ONLINE"

    with pytest.raises(AcWebActionError) as foreign:
        service.launch_fit_ap_external_terminal(
            "demo", ac_id="ac-1", ap_id="not-current-ac", terminal_type="putty"
        )
    assert foreign.value.code == "AP_TARGET_NOT_AUTHORIZED"

    with Database(paths.site_db_path("demo")).connect() as conn:
        conn.execute("UPDATE ac_fit_ap_resources SET ap_ip = '' WHERE ap_uuid = 'ap-online'")
        conn.commit()
    with pytest.raises(AcWebActionError) as no_ip:
        service.launch_fit_ap_external_terminal(
            "demo", ac_id="ac-1", ap_id="ap-online", terminal_type="putty"
        )
    assert no_ip.value.code == "AP_ADDRESS_MISSING"
