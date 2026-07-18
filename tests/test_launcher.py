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


def test_parse_launch_options_defaults_to_server_diagnostics() -> None:
    options = launcher.parse_launch_options([])

    assert options.mode == "server"
    assert options.host == "127.0.0.1"
    assert options.port == 8000


@pytest.mark.parametrize("removed_mode", ["auto", "qt"])
def test_parse_launch_options_rejects_removed_qt_modes(removed_mode: str) -> None:
    with pytest.raises(SystemExit):
        launcher.parse_launch_options(["--mode", removed_mode])


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


def test_empty_python_entrypoint_dispatches_electron_desktop(capsys, monkeypatch) -> None:
    from netconsole import entrypoint
    from netconsole.launcher import electron_desktop

    monkeypatch.setattr(sys, "argv", ["NetConsole"])
    calls: list[bool] = []
    monkeypatch.setattr(electron_desktop, "launch_electron_desktop", lambda: calls.append(True) or 0)

    assert entrypoint.main() == 0
    assert calls == [True]
    assert capsys.readouterr().err == ""


def test_electron_desktop_plan_uses_project_runtime_without_global_pnpm(tmp_path: Path) -> None:
    from netconsole.launcher.electron_desktop import build_electron_desktop_launch_plan

    desktop = tmp_path / "apps" / "desktop_electron"
    web = tmp_path / "apps" / "web"
    electron = desktop / "node_modules" / "electron" / "dist" / "electron.exe"
    for path in (
        desktop / "scripts" / "dev.mjs",
        electron,
        desktop / "node_modules" / "typescript" / "bin" / "tsc",
        web / "node_modules" / "vite" / "bin" / "vite.js",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    plan = build_electron_desktop_launch_plan(
        project_root=tmp_path,
        python_executable=python,
        environment={},
    )

    assert plan.executable == electron.resolve()
    assert plan.arguments == (str((desktop / "scripts" / "dev.mjs").resolve()),)
    assert plan.environment["ELECTRON_RUN_AS_NODE"] == "1"
    assert plan.environment["NETCONSOLE_PROJECT_ROOT"] == str(tmp_path.resolve())
    assert plan.environment["NETCONSOLE_PYTHON"] == str(python.resolve())


def test_electron_desktop_plan_accepts_explicit_node_override(tmp_path: Path) -> None:
    from netconsole.launcher.electron_desktop import build_electron_desktop_launch_plan

    desktop = tmp_path / "apps" / "desktop_electron"
    web = tmp_path / "apps" / "web"
    for path in (
        desktop / "scripts" / "dev.mjs",
        desktop / "node_modules" / "electron" / "dist" / "electron.exe",
        desktop / "node_modules" / "typescript" / "bin" / "tsc",
        web / "node_modules" / "vite" / "bin" / "vite.js",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")

    plan = build_electron_desktop_launch_plan(
        project_root=tmp_path,
        python_executable=python,
        environment={"NETCONSOLE_NODE": str(node), "ELECTRON_RUN_AS_NODE": "1"},
    )

    assert plan.executable == node.resolve()
    assert "ELECTRON_RUN_AS_NODE" not in plan.environment


def test_electron_desktop_plan_reports_missing_locked_dependencies(tmp_path: Path) -> None:
    from netconsole.launcher.electron_desktop import (
        ElectronDesktopLaunchError,
        build_electron_desktop_launch_plan,
    )

    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")

    with pytest.raises(ElectronDesktopLaunchError, match="pnpm install --frozen-lockfile"):
        build_electron_desktop_launch_plan(
            project_root=tmp_path,
            python_executable=python,
            environment={},
        )


def test_electron_desktop_launch_returns_process_exit_code(tmp_path: Path, monkeypatch) -> None:
    from netconsole.launcher import electron_desktop

    executable = tmp_path / "electron.exe"
    executable.write_text("", encoding="utf-8")
    plan = electron_desktop.ElectronDesktopLaunchPlan(
        executable=executable,
        arguments=("dev.mjs",),
        working_directory=tmp_path,
        environment={},
    )

    class FakeProcess:
        def wait(self, timeout=None):
            assert timeout is None
            return 17

    monkeypatch.setattr(electron_desktop, "build_electron_desktop_launch_plan", lambda: plan)
    monkeypatch.setattr(electron_desktop.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    assert electron_desktop.launch_electron_desktop() == 17


def test_electron_desktop_launch_reports_process_creation_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    from netconsole.launcher import electron_desktop

    executable = tmp_path / "electron.exe"
    executable.write_text("", encoding="utf-8")
    plan = electron_desktop.ElectronDesktopLaunchPlan(
        executable=executable,
        arguments=("dev.mjs",),
        working_directory=tmp_path,
        environment={},
    )
    monkeypatch.setattr(electron_desktop, "build_electron_desktop_launch_plan", lambda: plan)

    def fail_to_start(*_args, **_kwargs):
        raise OSError("process unavailable")

    monkeypatch.setattr(electron_desktop.subprocess, "Popen", fail_to_start)

    assert electron_desktop.launch_electron_desktop() == 2
    assert "Electron 启动失败" in capsys.readouterr().err


def test_entrypoint_dispatches_packaged_electron_backend(monkeypatch) -> None:
    from netconsole import entrypoint
    from netconsole.backend import electron_runtime

    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["NetConsoleBackend.exe", "--electron-backend", "--host", "127.0.0.1", "--port", "0"])
    monkeypatch.setattr(electron_runtime, "main", lambda argv: calls.append(argv) or 7)

    assert entrypoint.main() == 7
    assert calls == [["--host", "127.0.0.1", "--port", "0"]]


def test_web_mode_opens_browser_without_qt(tmp_path: Path, monkeypatch) -> None:
    import netconsole.launcher.runtime_supervisor as supervisor_module

    opened: list[str] = []
    monkeypatch.setattr(supervisor_module, "RuntimeSupervisor", _FakeRuntime)
    monkeypatch.setattr(launcher, "_open_browser_shell", lambda runtime, paths: opened.append(runtime.base_url) or True)
    monkeypatch.setattr(launcher, "_log_frontend_status", lambda runtime: None)

    result = launcher._launch_once(launcher.LaunchOptions("web", "127.0.0.1", 9000), PathResolver(tmp_path))

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
    monkeypatch.setattr(launcher, "_open_browser_shell", lambda *args: pytest.fail("server mode opened browser"))
    monkeypatch.setattr(launcher, "_log_frontend_status", lambda runtime: None)

    result = launcher._launch_once(launcher.LaunchOptions("server", "127.0.0.2", 9000), PathResolver(tmp_path))

    runtime = _FakeRuntime.instances[0]
    assert result == 0
    assert runtime.host_mode is RuntimeMode.SERVER
    assert runtime.host == "127.0.0.2"
    assert runtime.port == 9000
    assert runtime.stopped is True


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
