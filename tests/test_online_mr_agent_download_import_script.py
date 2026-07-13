from __future__ import annotations

from pathlib import Path

from netconsole.models.online_mr_agent import (
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSystemStatus,
    OnlineMrAgentToolsStatus,
    OnlineMrAgentToolStatus,
)
from netconsole.services.online_mr.agent_download_service import (
    OnlineMrAgentDownloadImportResult,
)
from scripts.maintenance import download_import_agent_online_mr_package as command


class _Controller:
    result = OnlineMrAgentDownloadImportResult(True, imported=True)

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def ping_agent(self) -> OnlineMrAgentPingResponse:
        return OnlineMrAgentPingResponse(status="ok")

    async def get_agent_status(self) -> OnlineMrAgentSystemStatus:
        return OnlineMrAgentSystemStatus(
            agent_id="agent-a",
            agent_name="Agent A",
            version="v1.0.0",
            os="windows",
            arch="amd64",
        )

    async def get_agent_tools(self) -> OnlineMrAgentToolsStatus:
        ready = OnlineMrAgentToolStatus(exists=True, ready=True)
        return OnlineMrAgentToolsStatus(
            mr_collector=ready,
            fping=ready,
            iperf3=ready,
        )

    async def list_agent_packages(self) -> tuple[OnlineMrAgentPackageInfo, ...]:
        return (
            OnlineMrAgentPackageInfo(
                package_id="package-1",
                task_id="task-1",
                task_type="mr_realtime_collect",
                size=128,
            ),
        )

    async def download_import_package(
        self, _package_id: str, **_options: object
    ) -> OnlineMrAgentDownloadImportResult:
        return self.result


def test_script_lists_packages_without_import(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(command, "OnlineMrAgentControllerService", _Controller)

    code = command.main(
        [
            "--agent-url",
            "http://127.0.0.1:18080",
            "--token",
            "secret-token",
            "--data-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "package-1" in output
    assert "secret-token" not in output


def test_script_downloads_imports_and_prints_acceptance_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _Controller.result = OnlineMrAgentDownloadImportResult(
        True,
        downloaded=True,
        imported=True,
        task_id="controller-task-1",
        session_id="session-1",
        session_dir=tmp_path / "session-1",
        sha256="abc123",
    )
    monkeypatch.setattr(command, "OnlineMrAgentControllerService", _Controller)

    code = command.main(
        [
            "--agent-url",
            "http://127.0.0.1:18080",
            "--package-id",
            "package-1",
            "--site",
            "site-a",
            "--device-id",
            "7",
            "--device-name",
            "MR-07",
            "--mr-name",
            "MR-07",
            "--data-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "导入结果：IMPORTED" in output
    assert "controller-task-1" in output
    assert "check_online_mr_session_state" in output
