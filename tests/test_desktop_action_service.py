from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from netconsole.application.desktop import (
    DesktopActionResolver,
    DesktopActionResult,
    DesktopActionService,
    DesktopSelectionPurpose,
    RegisteredLaunch,
    RegisteredNotification,
)
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.infrastructure.desktop import BrowserDesktopAdapter, UnavailableDesktopAdapter


class FakeDesktopAdapter:
    def __init__(self, selected_root: Path) -> None:
        self.selected_root = selected_root
        self.calls: list[tuple[str, object]] = []

    def select_file(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        self.calls.append(("select_file", purpose))
        return DesktopActionResult(True, "completed", paths=(self.selected_root / "selected.txt",))

    def select_files(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        self.calls.append(("select_files", purpose))
        return DesktopActionResult(
            True,
            "completed",
            paths=(self.selected_root / "first.txt", self.selected_root / "second.txt"),
        )

    def select_directory(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        self.calls.append(("select_directory", purpose))
        return DesktopActionResult(True, "completed", paths=(self.selected_root,))

    def open_controlled_directory(self, path: Path) -> DesktopActionResult:
        self.calls.append(("open_controlled_directory", path))
        return DesktopActionResult(True, "completed")

    def open_controlled_artifact(self, path: Path) -> DesktopActionResult:
        self.calls.append(("open_controlled_artifact", path))
        return DesktopActionResult(True, "completed")

    def launch_registered_terminal(self, launch: RegisteredLaunch) -> DesktopActionResult:
        self.calls.append(("launch_registered_terminal", launch))
        return DesktopActionResult(True, "completed")

    def launch_registered_tool(self, launch: RegisteredLaunch) -> DesktopActionResult:
        self.calls.append(("launch_registered_tool", launch))
        return DesktopActionResult(True, "completed")

    def show_native_notification(self, notification: RegisteredNotification) -> DesktopActionResult:
        self.calls.append(("show_native_notification", notification))
        return DesktopActionResult(True, "completed")


def _fixture(tmp_path: Path, *, adapter=None, runtime_mode: RuntimeMode = RuntimeMode.DESKTOP, audit=lambda *_args: None):
    controlled = tmp_path / "controlled"
    reports = controlled / "reports"
    binaries = controlled / "bin"
    reports.mkdir(parents=True)
    binaries.mkdir()
    artifact = reports / "report.txt"
    artifact.write_text("result", encoding="utf-8")
    terminal = binaries / "SecureCRT.exe"
    tool = binaries / "iperf3.exe"
    terminal.write_bytes(b"terminal")
    tool.write_bytes(b"tool")
    resolver = DesktopActionResolver(
        controlled_roots=(controlled,),
        directories={"reports": reports},
        artifacts={"report-1": artifact},
        terminals={
            ("terminal.device", "device-1"): RegisteredLaunch(
                terminal,
                ("/SSH2", "10.0.0.1"),
            )
        },
        tools={
            ("tool.traffic", "run-1"): RegisteredLaunch(
                tool,
                ("-c", "10.0.0.2"),
            )
        },
        notifications={"task.completed": RegisteredNotification("NetConsole", "任务已完成")},
    )
    selected_adapter = adapter or FakeDesktopAdapter(controlled)
    return DesktopActionService(runtime_mode, selected_adapter, resolver, audit), selected_adapter, controlled, artifact


def _all_actions(service: DesktopActionService):
    return (
        service.select_file(DesktopSelectionPurpose.IMPORT_FILE),
        service.select_files(DesktopSelectionPurpose.IMPORT_FILES),
        service.select_directory(DesktopSelectionPurpose.IMPORT_DIRECTORY),
        service.open_controlled_directory("reports"),
        service.open_controlled_artifact("report-1"),
        service.launch_registered_terminal("terminal.device", "device-1"),
        service.launch_registered_tool("tool.traffic", "run-1"),
        service.show_native_notification("task.completed"),
    )


def test_fake_adapter_covers_every_allowed_action_with_registered_targets(tmp_path: Path) -> None:
    service, adapter, controlled, artifact = _fixture(tmp_path)

    results = _all_actions(service)

    assert all(result.success for result in results)
    assert [name for name, _payload in adapter.calls] == [
        "select_file",
        "select_files",
        "select_directory",
        "open_controlled_directory",
        "open_controlled_artifact",
        "launch_registered_terminal",
        "launch_registered_tool",
        "show_native_notification",
    ]
    assert adapter.calls[3][1] == (controlled / "reports").resolve()
    assert adapter.calls[4][1] == artifact.resolve()
    assert adapter.calls[5][1] == RegisteredLaunch(
        (controlled / "bin" / "SecureCRT.exe").resolve(),
        ("/SSH2", "10.0.0.1"),
        (controlled / "bin").resolve(),
    )


@pytest.mark.parametrize(
    "forged_id",
    [
        "",
        "../secret",
        "..\\secret",
        "C:\\Windows\\System32\\cmd.exe",
        "\\\\server\\share\\report.txt",
        "report-1 & calc",
        "report-1; powershell",
    ],
)
def test_rejects_path_and_shell_shaped_ids(tmp_path: Path, forged_id: str) -> None:
    service, adapter, _controlled, _artifact = _fixture(tmp_path)

    assert service.open_controlled_artifact(forged_id).code == "invalid_identifier"
    assert service.launch_registered_terminal("terminal.device", forged_id).code == "invalid_identifier"
    assert adapter.calls == []


def test_rejects_unknown_cross_kind_and_escaped_registered_targets(tmp_path: Path) -> None:
    service, adapter, controlled, _artifact = _fixture(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    escaped = DesktopActionService(
        RuntimeMode.DESKTOP,
        adapter,
        DesktopActionResolver(controlled_roots=(controlled,), artifacts={"report-2": outside}),
        lambda *_args: None,
    )

    assert service.open_controlled_artifact("missing").code == "unknown_artifact"
    assert service.open_controlled_artifact("reports").code == "unknown_artifact"
    assert service.open_controlled_directory("report-1").code == "unknown_directory"
    assert service.launch_registered_tool("tool.traffic", "device-1").code == "unknown_tool_action"
    assert service.launch_registered_tool("powershell.exe", "device-1").code == "unknown_tool_action"
    assert escaped.open_controlled_artifact("report-2").code == "path_outside_controlled_roots"
    assert adapter.calls == []


def test_rejects_registered_command_interpreters(tmp_path: Path) -> None:
    controlled = tmp_path / "controlled"
    controlled.mkdir()
    command = controlled / "cmd.exe"
    command.write_bytes(b"cmd")
    adapter = FakeDesktopAdapter(controlled)
    service = DesktopActionService(
        RuntimeMode.DESKTOP,
        adapter,
        DesktopActionResolver(
            controlled_roots=(controlled,),
            tools={("tool.shell", "device-1"): RegisteredLaunch(command, ("/c", "calc"))},
        ),
        lambda *_args: None,
    )

    assert service.launch_registered_tool("tool.shell", "device-1").code == "forbidden_executable"
    assert adapter.calls == []


def test_server_mode_rejects_every_desktop_action_before_adapter(tmp_path: Path) -> None:
    service, adapter, _controlled, _artifact = _fixture(tmp_path, runtime_mode=RuntimeMode.SERVER)

    results = _all_actions(service)

    assert {result.code for result in results} == {"server_mode_forbidden"}
    assert adapter.calls == []


def test_browser_and_unavailable_adapters_return_controlled_results(tmp_path: Path) -> None:
    browser_service, _adapter, _controlled, _artifact = _fixture(tmp_path, adapter=BrowserDesktopAdapter())
    unavailable_service, _adapter, _controlled, _artifact = _fixture(
        tmp_path / "unavailable",
        adapter=UnavailableDesktopAdapter(),
    )

    assert {result.code for result in _all_actions(browser_service)} == {"desktop_host_required"}
    assert {result.code for result in _all_actions(unavailable_service)} == {"desktop_unavailable"}


def test_audit_records_only_fixed_actions_safe_ids_and_result_codes(tmp_path: Path) -> None:
    audit: list[tuple[str, str]] = []
    service, _adapter, controlled, _artifact = _fixture(tmp_path, audit=lambda event, detail: audit.append((event, detail)))

    assert service.open_controlled_artifact("report-1").success is True
    assert service.open_controlled_artifact("C:\\secret.txt").code == "invalid_identifier"

    assert audit == [
        ("DESKTOP_ACTION_ATTEMPT", "action=open_controlled_artifact target=report-1"),
        ("DESKTOP_ACTION_RESULT", "action=open_controlled_artifact target=report-1 code=completed"),
        ("DESKTOP_ACTION_ATTEMPT", "action=open_controlled_artifact target=invalid"),
        ("DESKTOP_ACTION_RESULT", "action=open_controlled_artifact target=invalid code=invalid_identifier"),
    ]
    assert all(str(controlled) not in detail for _event, detail in audit)


def test_non_qt_desktop_contract_imports_without_pyside6(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    code = """
import sys
import netconsole.application.desktop
import netconsole.infrastructure.desktop
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


def test_qt_adapter_maps_resolved_paths_and_argv_without_shell(tmp_path: Path, monkeypatch) -> None:
    from netconsole.infrastructure.desktop import qt_adapter

    selected = tmp_path / "selected.txt"
    executable = tmp_path / "tool.exe"
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(qt_adapter.QFileDialog, "getOpenFileName", lambda *_args: (str(selected), ""))
    monkeypatch.setattr(
        qt_adapter.QDesktopServices,
        "openUrl",
        lambda url: calls.append(("open", url.toLocalFile())) or True,
    )
    monkeypatch.setattr(
        qt_adapter.QProcess,
        "startDetached",
        lambda program, arguments, directory: calls.append(("launch", program, arguments, directory)) or (True, 123),
    )
    adapter = qt_adapter.QtDesktopAdapter()
    launch = RegisteredLaunch(executable, ("-c", "10.0.0.2"), tmp_path)

    assert adapter.select_file(DesktopSelectionPurpose.IMPORT_FILE).paths == (selected.resolve(),)
    assert adapter.open_controlled_artifact(selected).success is True
    assert adapter.launch_registered_tool(launch).success is True
    assert Path(str(calls[0][1])) == selected
    assert calls[1] == ("launch", str(executable), ["-c", "10.0.0.2"], str(tmp_path))
