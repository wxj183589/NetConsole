from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.handlers import online_mr_jobs
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.task_manager import BackgroundProcessManager
from netconsole.services.online_mr.agent_download_service import OnlineMrAgentDownloadImportResult
from netconsole.ui.dialogs.online_mr_agent_packages_dialog import (
    AGENT_TOKEN_ENV,
    OnlineMrAgentPackagesDialog,
)

pytestmark = pytest.mark.usefixtures("qt_page_lifecycle")


class _Profiles:
    def list_agents(self) -> list[dict[str, object]]:
        return [
            {
                "agent_id": "agent-profile-1",
                "name": "车载采集 Agent",
                "base_url": "http://127.0.0.1:18080",
                "enabled": True,
                "authentication_type": "token",
            }
        ]


def _sync_result(*, import_status: str = "not_imported", matched: bool = True) -> dict[str, object]:
    candidate = {
        "device_id": 12,
        "device_name": "列车12-MR-CT",
        "mr_id": "12",
        "mr_name": "列车12-MR-CT",
        "host": "192.0.2.12",
        "device_type": "SW",
    }
    return {
        "ping": {"status": "ok", "time": "now"},
        "agent_status": {
            "agent_id": "agent-1",
            "agent_name": "Agent 1",
            "version": "0.2.0-win-agent",
            "os": "windows",
            "arch": "amd64",
            "package_count": 1,
        },
        "tools": {
            "mr_collector": {"ready": True, "version": "1"},
            "fping": {"ready": True, "version": "5"},
            "iperf3": {"ready": True, "version": "3"},
        },
        "packages": [
            {
                "package_id": "package-1",
                "file_name": "package-1.zip",
                "task_id": "agent-task-1",
                "session_id": "agent-session-1",
                "task_type": "mr_realtime_collect",
                "status": "completed",
                "size": 1024,
                "end_time": "2026-07-14T12:00:00Z",
                "source_device_id": "temporary-id",
                "source_device_name": "临时名称",
                "source_host": "192.0.2.12",
                "candidate_local_device": candidate if matched else None,
                "candidate_local_devices": [candidate] if matched else [],
                "candidate_match_method": "ip_match" if matched else "not_found",
                "import_status": import_status,
                "resolution_code": "",
                "resolution_message": "",
            }
        ],
    }


def _dialog(tmp_path: Path, submissions: list[dict[str, Any]]) -> OnlineMrAgentPackagesDialog:
    def submitter(_parent, job, **kwargs):
        submissions.append({"job": job, **kwargs})
        return job.job_id

    return OnlineMrAgentPackagesDialog(
        paths=PathResolver(tmp_path),
        site_name="宁波地铁12号线",
        i18n=I18n("zh_CN"),
        devices=[Device(id=12, name="列车12-MR-CT", primary_address="192.0.2.12")],
        profile_controller=_Profiles(),  # type: ignore[arg-type]
        job_submitter=submitter,
    )


def test_dialog_passes_token_only_in_worker_environment(tmp_path: Path) -> None:
    submissions: list[dict[str, Any]] = []
    dialog = _dialog(tmp_path, submissions)
    dialog.profile_combo.setCurrentIndex(1)
    dialog.token_edit.setText("secret-token")

    dialog.refresh_packages()

    submission = submissions[0]
    assert submission["job"].task_type == "online_mr_agent_packages_sync"
    assert "secret-token" not in str(submission["job"].to_dict())
    assert submission["environment"] == {AGENT_TOKEN_ENV: "secret-token"}


def test_dialog_enforces_import_status_and_manual_confirmation(tmp_path: Path, monkeypatch) -> None:
    submissions: list[dict[str, Any]] = []
    dialog = _dialog(tmp_path, submissions)
    dialog._apply_sync_result(_sync_result(matched=False))
    assert not dialog.import_button.isEnabled()
    assert dialog.manual_import_button.isEnabled()

    monkeypatch.setattr("netconsole.ui.dialogs.online_mr_agent_packages_dialog.confirm", lambda *_args, **_kwargs: True)
    dialog.import_manual_package()

    params = submissions[-1]["job"].params
    assert submissions[-1]["job"].task_type == "online_mr_agent_package_import"
    assert params["manual_override"] is True
    assert params["device_id"] == 12
    assert params["device_name"] == "列车12-MR-CT"

    dialog._set_job_running(False)
    dialog._apply_sync_result(_sync_result(import_status="conflict"))
    assert not dialog.import_button.isEnabled()
    assert not dialog.manual_import_button.isEnabled()


def test_dialog_exposes_import_result_and_acceptance_actions(tmp_path: Path, monkeypatch) -> None:
    submissions: list[dict[str, Any]] = []
    dialog = _dialog(tmp_path, submissions)
    session_dir = tmp_path / "session-1"
    session_dir.mkdir()
    dialog._apply_sync_result(_sync_result())

    clipboard: list[str] = []
    opened: list[str] = []
    monkeypatch.setattr(
        "netconsole.ui.dialogs.online_mr_agent_packages_dialog.QGuiApplication.clipboard",
        lambda: type("Clipboard", (), {"setText": lambda _self, value: clipboard.append(value)})(),
    )
    monkeypatch.setattr(
        "netconsole.ui.dialogs.online_mr_agent_packages_dialog.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    dialog._import_finished(
        {
            "result": {
                "task_id": "controller-task-1",
                "session_id": "agent-session-1",
                "session_dir": str(session_dir),
                "warnings": [],
            }
        }
    )

    assert "controller-task-1" in dialog.result_label.text()
    assert dialog.open_import_dir_button.isEnabled()
    assert dialog.copy_acceptance_command_button.isEnabled()
    dialog.copy_selected_package_id()
    dialog.copy_acceptance_command()
    dialog.open_import_dir()

    assert clipboard[0] == "package-1"
    assert "--task-id \"controller-task-1\"" in clipboard[1]
    assert len(opened) == 1
    assert Path(opened[0]) == session_dir


def test_agent_import_handler_forwards_cancellation_without_token_in_params(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class Service:
        async def download_import_agent_package(self, package_id: str, **kwargs):
            calls.append({"package_id": package_id, **kwargs})
            return OnlineMrAgentDownloadImportResult(True, imported=True, task_id="task-1", session_id="session-1")

    monkeypatch.setattr(online_mr_jobs, "_online_mr_agent_service", lambda _context: Service())
    context = JobContext(
        job_id="job-1",
        task_type="online_mr_agent_package_import",
        params={
            "site_id": "宁波地铁12号线",
            "site_name": "宁波地铁12号线",
            "package_id": "package-1",
            "manual_override": False,
        },
        progress_callback=None,
        should_cancel=lambda: False,
        paths=PathResolver(tmp_path),
    )

    result = online_mr_jobs.online_mr_agent_package_import(context)

    assert result["imported"] is True
    assert calls[0]["auto_resolve_by_ip"] is True
    assert calls[0]["cancel_check"] is context.should_cancel
    assert "token" not in context.params


def test_worker_environment_keeps_agent_token_out_of_job_file(tmp_path: Path) -> None:
    assert AGENT_TOKEN_ENV == online_mr_jobs.ONLINE_MR_AGENT_TOKEN_ENV
    paths = PathResolver(tmp_path)
    manager = BackgroundProcessManager(paths=paths)
    launch = manager.task_service.prepare(
        BackgroundJob(
            job_id="agent-secret-job",
            task_type="online_mr_agent_packages_sync",
            params={"site_id": "site-a", "base_url": "http://127.0.0.1:18080"},
        )
    )

    environment = manager._worker_environment(paths.app_root, {AGENT_TOKEN_ENV: "secret-token"})
    job_text = launch.job_path.read_text(encoding="utf-8")

    assert environment.value(AGENT_TOKEN_ENV) == "secret-token"
    assert "secret-token" not in job_text
    with pytest.raises(ValueError, match="受控密钥前缀"):
        manager._worker_environment(paths.app_root, {"PYTHONPATH": "unsafe"})
    manager.task_service.abandon(launch.job.job_id)
