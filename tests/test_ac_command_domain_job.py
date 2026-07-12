from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from netconsole import background_worker
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.ac.ac_command_service import AcCommandCancelled, AcCommandService
from netconsole.services.ac.ac_models import AcCommandExecutionResult, AcCommandRequest
from netconsole.services.background_job import BackgroundJob
from netconsole.services.h3c_ac_collect_service import AcCommandActionResult
from netconsole.services.h3c_collect_service import CommandResult
from netconsole.services.job_center.handlers import ac_jobs
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.job_runner import run_job
from netconsole.ui.pages.ac_management_page import AcManagementPage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _device() -> Device:
    return Device.from_mapping(
        {
            "id": 1,
            "device_uuid": "ac-001",
            "name": "测试 AC",
            "primary_address": "192.0.2.10",
            "device_vendor": "H3C",
            "device_type": "AC",
        }
    )


class _DeviceRepository:
    def list(self, **_kwargs):
        return [_device()]


class _AcRepository:
    pass


def _action_result(action: str, commands: tuple[str, ...], *, success: bool = True, error: str = "") -> AcCommandActionResult:
    return AcCommandActionResult(
        success,
        "ac-001",
        "run-001",
        "raw/ac.log",
        action,
        commands,
        error or None,
        [CommandResult(command, success, output=f"{command} output", error_message=error or None) for command in commands],
    )


def _service(tmp_path: Path, runner) -> AcCommandService:
    return AcCommandService(
        _DeviceRepository(),  # type: ignore[arg-type]
        _AcRepository(),  # type: ignore[arg-type]
        PathResolver(tmp_path),
        action_runner=runner,
    )


def test_ac_command_service_preserves_verified_command_sequences(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def runner(_device, _site_name, action, **kwargs):
        calls.append({"action": action, **kwargs})
        kwargs["progress"]("正在执行命令...")
        return _action_result(action, kwargs["commands"])

    service = _service(tmp_path, runner)
    progress: list[str] = []
    persist = service.persist_auto_ap(
        AcCommandRequest("ac-001", "demo", "persist_auto_ap"),
        progress_callback=lambda _stage, _current, _total, message: progress.append(message),
    )
    remote = service.enable_ap_remote_login(AcCommandRequest("ac-001", "demo", "enable_ap_remote_login"))
    saved = service.save_config(AcCommandRequest("ac-001", "demo", "save_config"))

    assert persist.commands == ["system-view", "wlan auto-ap persistent all", "save force", "return", "quit"]
    assert remote.commands == [
        "screen-length disable",
        "system-view",
        "probe",
        "wlan ap-execute all exec-console enable",
        "return",
        "quit",
    ]
    assert saved.commands == ["save force"]
    assert [call["context"] for call in calls] == ["ac_persist_auto_ap", "ac_enable_ap_remote_login", "config_lifecycle"]
    assert any("正在执行命令" in message for message in progress)


def test_ac_command_service_custom_sequence_is_limited_to_verified_actions(tmp_path: Path) -> None:
    def runner(_device, _site_name, action, **kwargs):
        return _action_result(action, kwargs["commands"])

    service = _service(tmp_path, runner)
    verified = ["save force"]
    result = service.execute_action(AcCommandRequest("ac-001", "demo", "custom_sequence", command_sequence=verified))

    assert result.success is True
    assert result.commands == verified
    with pytest.raises(ValueError, match="安全白名单"):
        service.execute_action(
            AcCommandRequest("ac-001", "demo", "custom_sequence", command_sequence=["reboot force"])
        )
    with pytest.raises(ValueError, match="命令序列与已验证动作不一致"):
        service.execute_action(
            AcCommandRequest("ac-001", "demo", "persist_auto_ap", command_sequence=["wlan auto-ap persistent all"])
        )


@pytest.mark.parametrize(
    ("message", "error_code"),
    [
        ("Connection refused", "connection_failed"),
        ("Authentication failed", "authentication_failed"),
        ("Read timeout", "timeout"),
        ("% Unrecognized command", "device_command_error"),
        ("save force 保存失败", "save_failed"),
    ],
)
def test_ac_command_service_returns_structured_errors(tmp_path: Path, message: str, error_code: str) -> None:
    def runner(_device, _site_name, action, **kwargs):
        return _action_result(action, kwargs["commands"], success=False, error=message)

    result = _service(tmp_path, runner).execute_action(AcCommandRequest("ac-001", "demo", "persist_auto_ap"))

    assert result.success is False
    assert result.error_code == error_code
    assert result.error_message == message
    assert result.to_payload()["command_results"][0]["error_message"] == message


def test_ac_command_service_checks_cancel_before_and_after_runner(tmp_path: Path) -> None:
    calls = 0

    def runner(_device, _site_name, action, **kwargs):
        nonlocal calls
        calls += 1
        return _action_result(action, kwargs["commands"], success=False, error="用户已取消更新")

    service = _service(tmp_path, runner)
    with pytest.raises(AcCommandCancelled):
        service.execute_action(AcCommandRequest("ac-001", "demo", "persist_auto_ap"), should_cancel=lambda: True)
    assert calls == 0
    with pytest.raises(AcCommandCancelled):
        service.execute_action(AcCommandRequest("ac-001", "demo", "persist_auto_ap"))
    assert calls == 1


def test_ac_command_job_success_custom_failed_and_cancelled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = {"mode": "success", "actions": []}

    class FakeCommandService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def execute_action(self, request, *, progress_callback=None, should_cancel=None):
            del should_cancel
            state["actions"].append(request.action)
            if progress_callback is not None:
                progress_callback("ac_command_action", 1, 1, "命令完成")
            if state["mode"] == "cancel":
                raise AcCommandCancelled("用户已取消更新")
            success = state["mode"] != "failed"
            return AcCommandExecutionResult(
                success,
                request.device_uuid,
                request.action,
                commands=list(request.command_sequence),
                error_code="connection_failed" if not success else "",
                error_message="连接失败" if not success else "",
            )

    monkeypatch.setattr(ac_jobs, "AcCommandService", FakeCommandService)
    base = {
        "device_uuid": "ac-001",
        "site_name": "demo",
        "db_path": str(tmp_path / "devices.db"),
        "data_root": str(tmp_path),
        "command_sequence": ["save force"],
    }
    progress: list[str] = []
    for action in ("persist_auto_ap", "enable_ap_remote_login", "custom_sequence"):
        result = run_job(
            BackgroundJob(job_id=action, task_type="ac_command_action_execute", params={**base, "action": action}),
            progress_callback=lambda stage, *_args: progress.append(stage),
        )
        assert result.ok is True
        assert result.result["action"] == action
    assert state["actions"] == ["persist_auto_ap", "enable_ap_remote_login", "custom_sequence"]
    assert progress == ["ac_command_action"] * 3

    state["mode"] = "failed"
    failed = run_job(BackgroundJob(job_id="failed", task_type="ac_command_action_execute", params={**base, "action": "persist_auto_ap"}))
    assert failed.ok is False
    assert failed.error == "连接失败"

    state["mode"] = "cancel"
    cancelled = run_job(BackgroundJob(job_id="cancel", task_type="ac_command_action_execute", params={**base, "action": "persist_auto_ap"}))
    assert cancelled.cancelled is True
    assert cancelled.error == "用户已取消更新"


def test_ac_page_command_actions_keep_confirmation_and_submit_job(monkeypatch: pytest.MonkeyPatch) -> None:
    submitted: list[tuple[str, dict[str, object], str]] = []
    confirmations: list[str] = []
    device = _device()
    page = SimpleNamespace(
        feature_gate=SimpleNamespace(assert_enabled=lambda _feature: None),
        current_device=lambda: device,
        _ensure_h3c_ac_selected=lambda _device: True,
        site_name="demo",
        repository=SimpleNamespace(database=SimpleNamespace(path=Path("devices.db"))),
        _set_update_running=lambda *_args: None,
        _start_background_job=lambda task_type, params, title: submitted.append((task_type, params, title)) or "action-job",
        action_job_id=None,
    )
    monkeypatch.setattr(
        "netconsole.ui.pages.ac_management_page.MessageBox.question",
        lambda _parent, _title, message: confirmations.append(message) or 16384,
    )

    AcManagementPage.run_ac_action(page, "persist_auto_ap", "固化新上线AP")  # type: ignore[arg-type]
    AcManagementPage.run_ac_action(page, "enable_ap_remote_login", "开启AP远程登入")  # type: ignore[arg-type]

    assert submitted[0][0] == "ac_command_action_execute"
    assert submitted[0][1]["command_sequence"] == ["system-view", "wlan auto-ap persistent all", "save force", "return", "quit"]
    assert submitted[1][1]["command_sequence"][2:4] == ["probe", "wlan ap-execute all exec-console enable"]
    assert "save force" in confirmations[0]
    assert "probe" in confirmations[1]

    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.MessageBox.question", lambda *_args: 65536)
    AcManagementPage.run_ac_action(page, "persist_auto_ap", "固化新上线AP")  # type: ignore[arg-type]
    assert len(submitted) == 2


def test_ac_page_command_terminal_events_restore_state(monkeypatch: pytest.MonkeyPatch) -> None:
    running: list[bool] = []
    warnings: list[str] = []
    status = SimpleNamespace(value="", setText=lambda value: setattr(status, "value", value))
    page = SimpleNamespace(
        _background_jobs={
            "finished": {"task_type": "ac_command_action_execute", "title": "固化新上线AP"},
        },
        action_job_id="finished",
        _set_update_running=lambda value, *_args: running.append(value),
        _finish_ac_action=lambda result, title: AcManagementPage._finish_ac_action(page, result, title),
        status_label=status,
        i18n=SimpleNamespace(t=lambda key, **_kwargs: key),
    )

    AcManagementPage._background_finished(  # type: ignore[arg-type]
        page,
        {"job_id": "finished", "result": {"action": "persist_auto_ap", "command_results": []}},
    )
    assert page.action_job_id is None
    assert running[-1] is False
    assert "save force" in status.value

    monkeypatch.setattr(
        "netconsole.ui.pages.ac_management_page.MessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    page._background_jobs = {"failed": {"task_type": "ac_command_action_execute", "title": "命令动作"}}
    page.action_job_id = "failed"
    AcManagementPage._background_failed(page, {"job_id": "failed", "error": "认证失败"})  # type: ignore[arg-type]
    assert page.action_job_id is None
    assert warnings == ["认证失败"]

    page._background_jobs = {"cancelled": {"task_type": "ac_command_action_execute", "title": "命令动作"}}
    page.action_job_id = "cancelled"
    AcManagementPage._background_cancelled(page, {"job_id": "cancelled"})  # type: ignore[arg-type]
    assert page.action_job_id is None
    assert status.value == "ac.update_cancelled"


def test_ac_page_tab_switch_cancels_command_job() -> None:
    cancelled: list[str] = []
    page = SimpleNamespace(
        action_job_id="action-job",
        background_manager=SimpleNamespace(cancel_job=lambda job_id: cancelled.append(job_id)),
        cancel_update_button=SimpleNamespace(setEnabled=lambda _enabled: None),
        _current_feature_id=lambda: "ac.fit_ap_resources",
        tabs=SimpleNamespace(tabText=lambda _index: "FIT-AP资源"),
        current_tab_action_labels=lambda: [],
        refresh_current_async_or_lazy=lambda: None,
    )

    AcManagementPage._on_current_tab_changed(page, 1)  # type: ignore[arg-type]

    assert cancelled == ["action-job"]


def test_ac_command_worker_stdout_is_jsonl_and_cancel_has_one_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeCommandService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def execute_action(self, request, *, progress_callback=None, should_cancel=None):
            del should_cancel
            print("raw device echo")
            if progress_callback is not None:
                progress_callback("ac_command_action", 1, 1, "命令完成")
            return AcCommandExecutionResult(True, request.device_uuid, request.action, commands=["save force"])

    monkeypatch.setattr(ac_jobs, "AcCommandService", FakeCommandService)
    job_path = tmp_path / "action.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="action-worker",
                task_type="ac_command_action_execute",
                params={
                    "device_uuid": "ac-001",
                    "site_name": "demo",
                    "action": "save_config",
                    "command_sequence": ["save force"],
                    "db_path": str(tmp_path / "devices.db"),
                    "data_root": str(tmp_path),
                    "_emit_log_events": True,
                },
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", stdout)

    assert background_worker.main(["--job", str(job_path)]) == 0
    output = stdout.getvalue()
    events = [json.loads(line) for line in output.splitlines() if line.strip()]
    assert [event["type"] for event in events] == ["progress", "log", "finished"]
    assert "raw device echo" not in output

    cancel_path = tmp_path / "cancel.flag"
    cancel_path.write_text("cancelled", encoding="utf-8")
    cancelled_job = BackgroundJob(
        job_id="action-cancelled",
        task_type="ac_command_action_execute",
        params={"action": "save_config", "db_path": str(tmp_path / "devices.db"), "data_root": str(tmp_path)},
        cancel_path=str(cancel_path),
    )
    job_path.write_text(json.dumps(cancelled_job.to_dict(), ensure_ascii=False), encoding="utf-8")
    stdout.seek(0)
    stdout.truncate(0)
    assert background_worker.main(["--job", str(job_path)]) == 2
    cancelled_events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert [event["type"] for event in cancelled_events] == ["cancelled"]


def test_ac_command_registration_and_static_ui_boundaries() -> None:
    assert "ac_command_action_execute" in registered_task_types()
    page_source = (PROJECT_ROOT / "src" / "netconsole" / "ui" / "pages" / "ac_management_page.py").read_text(encoding="utf-8")
    domain_source = (PROJECT_ROOT / "src" / "netconsole" / "services" / "ac" / "ac_command_service.py").read_text(encoding="utf-8")
    worker_source = (PROJECT_ROOT / "src" / "netconsole" / "background_worker.py").read_text(encoding="utf-8")

    assert "AcCommandActionThread" not in page_source
    assert "run_h3c_ac_action" not in page_source
    assert "ConnectHandler" not in page_source
    assert "netconsole.ui.pages" not in domain_source
    assert "netconsole.ui.pages" not in worker_source
