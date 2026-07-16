from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.launcher import launcher
from netconsole.launcher.runtime_supervisor import RuntimeSupervisor


class _FakeRuntime:
    instances: list[_FakeRuntime] = []

    def __init__(self, host_mode, *, paths, host, port):
        self.host_mode = host_mode
        self.paths = paths
        self.host = host
        self.port = port
        self.web_server = object()
        self.started = False
        self.stopped = False
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                frontend_root=Path("missing"),
                frontend_build_mismatch=False,
                frontend_build_id="",
                backend_build_id="test",
            )
        )
        _FakeRuntime.instances.append(self)

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1:12345"

    def start(self) -> bool:
        self.started = True
        return True

    def wait(self) -> int:
        return 0

    def stop(self) -> None:
        self.stopped = True


@pytest.fixture(autouse=True)
def _reset_fake_runtime() -> None:
    _FakeRuntime.instances.clear()


def test_parse_launch_options_preserves_qt_arguments() -> None:
    options = launcher.parse_launch_options(["--mode", "qt", "--admin-network-manager", "-style", "fusion"])

    assert options.mode == "qt"
    assert options.shell_args == ("--admin-network-manager", "-style", "fusion")


def test_parse_launch_options_rejects_invalid_port() -> None:
    with pytest.raises(SystemExit):
        launcher.parse_launch_options(["--port", "70000"])


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "example.com"])
def test_parse_launch_options_rejects_non_loopback_host(host: str) -> None:
    with pytest.raises(SystemExit):
        launcher.parse_launch_options(["--mode", "server", "--host", host])


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1"])
def test_parse_launch_options_accepts_loopback_host(host: str) -> None:
    assert launcher.parse_launch_options(["--mode", "server", "--host", host]).host == host


def test_help_exit_is_not_recorded_as_startup_failure(tmp_path: Path, monkeypatch) -> None:
    from netconsole import entrypoint

    monkeypatch.setattr(sys, "argv", ["NetConsole", "--help"])
    monkeypatch.setattr(entrypoint, "_runtime_log_dir", lambda: str(tmp_path))

    with pytest.raises(SystemExit) as raised:
        entrypoint.main()

    assert raised.value.code == 0
    assert not (tmp_path / "startup_error.log").exists()


def test_admin_network_manager_keeps_legacy_qt_child_path(monkeypatch) -> None:
    from netconsole import app, entrypoint

    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["NetConsole", "--admin-network-manager"])
    monkeypatch.setattr(app, "run", lambda: calls.append("qt") or 0)

    assert entrypoint.main() == 0
    assert calls == ["qt"]


@pytest.mark.parametrize(
    ("mode", "report", "expected"),
    [
        ("qt", launcher.CapabilityReport(qt_widgets_available=True), launcher.ShellMode.QT),
        ("qt", launcher.CapabilityReport(), None),
        ("web", launcher.CapabilityReport(), launcher.ShellMode.BROWSER),
        ("server", launcher.CapabilityReport(), launcher.ShellMode.NONE),
        ("auto", launcher.CapabilityReport(qt_widgets_available=True), launcher.ShellMode.QT),
        ("auto", launcher.CapabilityReport(external_browser_available=True), None),
        ("auto", launcher.CapabilityReport(), None),
    ],
)
def test_shell_mode_resolution(mode, report, expected) -> None:
    assert launcher._resolve_shell_mode(mode, report) is expected


def test_web_mode_opens_browser_without_qt_probe(tmp_path: Path, monkeypatch) -> None:
    import netconsole.launcher.runtime_supervisor as supervisor_module

    opened: list[str] = []
    monkeypatch.setattr(supervisor_module, "RuntimeSupervisor", _FakeRuntime)
    monkeypatch.setattr(launcher, "_capabilities_for", lambda mode: launcher.CapabilityReport())
    monkeypatch.setattr(launcher, "_open_browser_shell", lambda runtime, paths: opened.append(runtime.base_url) or True)
    monkeypatch.setattr(launcher, "_log_frontend_status", lambda runtime: None)

    result = launcher._launch_once(launcher.LaunchOptions("web", "0.0.0.0", 9000, ()), PathResolver(tmp_path))

    runtime = _FakeRuntime.instances[0]
    assert result == 0
    assert runtime.host_mode is RuntimeMode.DESKTOP
    assert runtime.host == "127.0.0.1"
    assert runtime.port is None
    assert opened == [runtime.base_url]
    assert runtime.stopped is True


def test_server_mode_uses_requested_bind_and_never_opens_browser(tmp_path: Path, monkeypatch) -> None:
    import netconsole.launcher.runtime_supervisor as supervisor_module

    monkeypatch.setattr(supervisor_module, "RuntimeSupervisor", _FakeRuntime)
    monkeypatch.setattr(launcher, "_capabilities_for", lambda mode: launcher.CapabilityReport())
    monkeypatch.setattr(launcher, "_open_browser_shell", lambda *args: pytest.fail("server mode opened browser"))
    monkeypatch.setattr(launcher, "_log_frontend_status", lambda runtime: None)

    result = launcher._launch_once(launcher.LaunchOptions("server", "127.0.0.2", 9000, ()), PathResolver(tmp_path))

    runtime = _FakeRuntime.instances[0]
    assert result == 0
    assert runtime.host_mode is RuntimeMode.SERVER
    assert runtime.host == "127.0.0.2"
    assert runtime.port == 9000
    assert runtime.stopped is True


def test_qt_shell_receives_core_owned_web_server(monkeypatch) -> None:
    import netconsole.app as qt_app

    received: list[tuple[object, str]] = []
    runtime = SimpleNamespace(web_server=object())
    options = launcher.LaunchOptions("qt", "127.0.0.1", 8000, ("-style", "fusion"))
    monkeypatch.setattr(
        qt_app,
        "run",
        lambda *, web_server: received.append(
            (web_server, os.environ["NETCONSOLE_QT_WEBENGINE_AVAILABLE"])
        )
        or 7,
    )

    assert launcher._run_qt_shell(runtime, options, launcher.CapabilityReport()) == 7
    assert received == [(runtime.web_server, "0")]
    assert "NETCONSOLE_QT_WEBENGINE_AVAILABLE" not in os.environ


def test_auto_does_not_hide_qt_business_failure(monkeypatch) -> None:
    import netconsole.app as qt_app

    runtime = SimpleNamespace(web_server=object())
    options = launcher.LaunchOptions("auto", "127.0.0.1", 8000, ())
    monkeypatch.setattr(qt_app, "run", lambda *, web_server: (_ for _ in ()).throw(RuntimeError("db failed")))

    with pytest.raises(RuntimeError, match="db failed"):
        launcher._run_qt_shell(
            runtime,
            options,
            launcher.CapabilityReport(external_browser_available=True),
        )


def test_single_instance_guard_rejects_second_owner(tmp_path: Path) -> None:
    first = launcher.SingleInstanceGuard(tmp_path / "launcher.lock")
    second = launcher.SingleInstanceGuard(tmp_path / "launcher.lock")
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
        second.release()


def test_launcher_and_api_factory_import_without_pyside6(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    code = """
import builtins
import sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'PySide6' or name.startswith('PySide6.'):
        raise AssertionError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import netconsole.backend.api.main as api_main
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.launcher.launcher import parse_launch_options
from netconsole.launcher.runtime_supervisor import RuntimeSupervisor
assert parse_launch_options(['--mode', 'server']).mode == 'server'
assert parse_launch_options(['--mode', 'web']).mode == 'web'
RuntimeSupervisor(RuntimeMode.SERVER, paths=PathResolver(), port=None)
RuntimeSupervisor(RuntimeMode.DESKTOP, paths=PathResolver(), port=None)
assert not hasattr(api_main, 'app')
assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)
print('qt_imported=false')
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    env["NETCONSOLE_DATA_ROOT"] = str(tmp_path / "data")

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "qt_imported=false" in result.stdout


def test_auto_qt_initialization_failure_does_not_open_browser(tmp_path: Path, monkeypatch) -> None:
    import netconsole.launcher.runtime_supervisor as supervisor_module

    opened: list[str] = []
    monkeypatch.setattr(supervisor_module, "RuntimeSupervisor", _FakeRuntime)
    monkeypatch.setattr(
        launcher,
        "_capabilities_for",
        lambda _mode: launcher.CapabilityReport(
            qt_widgets_available=False,
            external_browser_available=True,
            qt_detail="widgets=initialization-failed",
        ),
    )
    monkeypatch.setattr(launcher, "_open_browser_shell", lambda runtime, _paths: opened.append(runtime.base_url) or True)
    monkeypatch.setattr(launcher, "_log_frontend_status", lambda _runtime: None)

    result = launcher._launch_once(launcher.LaunchOptions("auto", "127.0.0.1", 8000, ()), PathResolver(tmp_path))

    assert result == 2
    assert _FakeRuntime.instances == []
    assert opened == []


def test_qt_probe_import_does_not_load_core_runtime(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    code = """
import sys
import netconsole.launcher.qt_probe
assert 'netconsole.launcher.launcher' not in sys.modules
assert 'netconsole.launcher.runtime_supervisor' not in sys.modules
assert 'netconsole.backend.api.main' not in sys.modules
print('probe_import_isolated=true')
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    env["NETCONSOLE_DATA_ROOT"] = str(tmp_path / "data")

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "probe_import_isolated=true" in result.stdout


def test_runtime_supervisor_starts_health_endpoint_and_stops(tmp_path: Path) -> None:
    runtime = RuntimeSupervisor(RuntimeMode.SERVER, paths=PathResolver(tmp_path), port=None)
    try:
        assert runtime.start() is True
        with urllib.request.urlopen(f"{runtime.base_url}/api/health", timeout=5) as response:
            assert response.status == 200
        assert runtime.web_server.thread_alive is True
    finally:
        runtime.stop()

    assert runtime.web_server.thread_alive is False


def test_browser_open_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    runtime = RuntimeSupervisor(RuntimeMode.DESKTOP, paths=PathResolver(tmp_path), port=None)
    cleanup_paths: list[Path] = []
    monkeypatch.setattr(launcher.webbrowser, "open_new_tab", lambda _url: False)
    monkeypatch.setattr(launcher.atexit, "register", lambda _callback, path: cleanup_paths.append(path))

    assert launcher._open_browser_shell(runtime, PathResolver(tmp_path)) is False
    assert cleanup_paths == [PathResolver(tmp_path).runtime_cache_dir / f"web-console-{runtime.web_server.port}.html"]
