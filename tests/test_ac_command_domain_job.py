from __future__ import annotations

import json
from pathlib import Path

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
from netconsole.services.job_center.job_runner import run_job


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








def test_ac_command_worker_stdout_is_jsonl_and_cancel_has_one_terminal(
    capfd: pytest.CaptureFixture[str],
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
    assert background_worker.main(["--job", str(job_path)]) == 0
    output = capfd.readouterr().out
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
    assert background_worker.main(["--job", str(job_path)]) == 2
    cancelled_output = capfd.readouterr().out
    cancelled_events = [json.loads(line) for line in cancelled_output.splitlines() if line.strip()]
    assert [event["type"] for event in cancelled_events] == ["cancelled"]
