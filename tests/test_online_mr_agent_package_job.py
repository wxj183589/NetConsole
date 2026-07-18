from __future__ import annotations

from pathlib import Path
from typing import Any



from netconsole.core.paths import PathResolver
from netconsole.services.job_center.handlers import online_mr_jobs
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.online_mr.agent_download_service import OnlineMrAgentDownloadImportResult


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
