from __future__ import annotations

from pathlib import Path

from netconsole.models.online_mr_agent import (
    OnlineMrAgentDeviceCandidate,
    OnlineMrAgentImportStatus,
    OnlineMrAgentPackageInfo,
    OnlineMrAgentPackageSyncResult,
    OnlineMrAgentPingResponse,
    OnlineMrAgentSyncedPackage,
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
    last_options: dict[str, object] = {}

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

    async def sync_agent_packages(
        self, *, site_id: str, profile_id: str = ""
    ) -> OnlineMrAgentPackageSyncResult:
        del site_id, profile_id
        candidate = OnlineMrAgentDeviceCandidate(
            device_id=7,
            device_name="MR-07",
            mr_id="7",
            mr_name="MR-07",
            host="192.0.2.12",
            device_type="Cloud-AP",
        )
        ready = OnlineMrAgentToolStatus(exists=True, ready=True)
        return OnlineMrAgentPackageSyncResult(
            ping=OnlineMrAgentPingResponse(status="ok"),
            agent_status=OnlineMrAgentSystemStatus(
                agent_id="agent-a",
                agent_name="Agent A",
                version="v1.0.0",
                os="windows",
                arch="amd64",
            ),
            tools=OnlineMrAgentToolsStatus(
                mr_collector=ready,
                fping=ready,
                iperf3=ready,
            ),
            packages=(
                OnlineMrAgentSyncedPackage(
                    package_id="package-1",
                    task_id="task-1",
                    session_id="task-1",
                    task_type="mr_realtime_collect",
                    size=128,
                    source_device_id="temporary-7",
                    source_device_name="Temp MR",
                    source_host="192.0.2.12",
                    candidate_local_device=candidate,
                    candidate_local_devices=(candidate,),
                    candidate_match_method="ip_match",
                    import_status=OnlineMrAgentImportStatus.ALREADY_IMPORTED,
                ),
            ),
        )

    async def download_import_package(
        self, _package_id: str, **options: object
    ) -> OnlineMrAgentDownloadImportResult:
        self.last_options = options
        type(self).last_options = options
        return self.result

    async def download_import_agent_package(
        self, _package_id: str, **options: object
    ) -> OnlineMrAgentDownloadImportResult:
        self.last_options = options
        type(self).last_options = options
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
            "--identity-match-policy",
            "manual_override",
            "--expected-host",
            "192.0.2.12",
            "--allow-identity-override",
            "--data-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "导入结果：IMPORTED" in output
    assert "controller-task-1" in output
    assert "check_online_mr_session_state" in output
    assert _Controller.last_options["identity_match_policy"] == "manual_override"
    assert _Controller.last_options["expected_host"] == "192.0.2.12"
    assert _Controller.last_options["allow_identity_override"] is True


def test_script_lists_packages_with_local_ip_match(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(command, "OnlineMrAgentControllerService", _Controller)

    code = command.main(
        [
            "--agent-url",
            "http://127.0.0.1:18080",
            "--site",
            "site-a",
            "--list-packages-with-match",
            "--data-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "temporary-7 / Temp MR / 192.0.2.12" in output
    assert "7 / MR-07" in output
    assert "导入=already_imported" in output


def test_script_auto_resolves_unique_ip_before_import(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _Controller.result = OnlineMrAgentDownloadImportResult(True, imported=True)
    monkeypatch.setattr(command, "OnlineMrAgentControllerService", _Controller)

    code = command.main(
        [
            "--agent-url",
            "http://127.0.0.1:18080",
            "--package-id",
            "package-1",
            "--site",
            "site-a",
            "--identity-match-policy",
            "ip_match",
            "--auto-resolve-by-ip",
            "--data-root",
            str(tmp_path),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "导入结果：IMPORTED" in output
    assert _Controller.last_options["auto_resolve_by_ip"] is True
