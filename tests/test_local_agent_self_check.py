from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from netconsole.models.agent_traffic import (
    AgentTaskArtifactDTO,
    AgentTaskDTO,
    AgentTaskResultDTO,
)
from netconsole.services.agent.http_client import AgentClientError, AgentProbeResult
from netconsole.services.agent.local_self_check import LocalAgentSelfCheck


class FakeLocalAgentClient:
    def __init__(self) -> None:
        self.started_payloads: list[dict] = []
        self.stopped: list[str] = []

    async def probe(self, base_url: str, token: str | None = None) -> AgentProbeResult:
        assert base_url == "http://127.0.0.1:18080"
        assert token == "secret"
        return AgentProbeResult("agent-local", "本机 Agent", "0.2.0-win-agent", "windows", "amd64")

    async def get_tools_status(self, base_url: str, token: str | None = None) -> dict:
        return {
            "mr_collector": {"ready": True},
            "fping": {"ready": True},
            "iperf3": {"ready": True},
        }

    async def start_fping(self, base_url, request, token=None) -> AgentTaskDTO:
        self.started_payloads.append(request.as_payload())
        return _task("fping-1", "fping", "running")

    async def start_iperf_server(self, base_url, request, token=None) -> AgentTaskDTO:
        self.started_payloads.append(request.as_payload())
        return _task("server-1", "iperf_server", "running")

    async def start_iperf_client(self, base_url, request, token=None) -> AgentTaskDTO:
        self.started_payloads.append(request.as_payload())
        return _task("client-1", "iperf_client", "running")

    async def get_task(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskDTO:
        status = "cancelled" if task_id == "server-1" and task_id in self.stopped else "completed"
        task_type = "fping" if task_id.startswith("fping") else "iperf_server" if task_id.startswith("server") else "iperf_client"
        return _task(task_id, task_type, status)

    async def stop_task(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskDTO:
        self.stopped.append(task_id)
        return await self.get_task(base_url, task_id, token)

    async def get_task_result(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskResultDTO:
        now = datetime.now(timezone.utc)
        is_fping = task_id.startswith("fping")
        return AgentTaskResultDTO(
            task_id=task_id,
            task_type="fping" if is_fping else "iperf_client",
            status="completed",
            started_at=now,
            finished_at=now,
            summary={"samples": 10} if is_fping else {"mode": "client"},
            artifacts=(AgentTaskArtifactDTO("fping_samples.jsonl" if is_fping else "iperf_raw.log", "samples" if is_fping else "raw", True),),
            last_sequence=1,
            error_code="",
            error="",
        )

    async def get_task_logs(self, base_url: str, task_id: str, *, tail: int = 300, token: str | None = None) -> tuple[str, ...]:
        return (f"task={task_id}", "done")


def _task(task_id: str, task_type: str, status: str) -> AgentTaskDTO:
    return AgentTaskDTO(task_id=task_id, task_type=task_type, status=status)


def test_local_agent_self_check_runs_fixed_loopback_traffic_and_cleans_tasks() -> None:
    client = FakeLocalAgentClient()
    report = asyncio.run(
        LocalAgentSelfCheck(client).run(
            agent_url="http://127.0.0.1:18080",
            token="secret",
            iperf_port=5202,
            duration_sec=1,
            tcp_requested_mbps=2,
        )
    )

    assert report.passed is True
    assert report.fping_samples == 10
    assert report.iperf_client_status == "completed"
    assert {"fping-1", "server-1", "client-1"} <= set(client.stopped)
    assert client.started_payloads[0] == {
        "targets": ["127.0.0.1"],
        "interval_ms": 1000,
        "timeout_ms": 4000,
        "packet_size": 64,
        "count": 10,
        "continuous": False,
        "source_address": "",
    }
    assert client.started_payloads[1]["bind_address"] == "127.0.0.1"
    assert client.started_payloads[2]["server_host"] == "127.0.0.1"
    assert client.started_payloads[2]["bandwidth_mbps"] == 2
    assert "不对 TCP 强制限速" in report.warnings[0]


@pytest.mark.parametrize(
    "url",
    ["http://192.0.2.10:18080", "https://agent.example.com", "http://127.0.0.2:18080"],
)
def test_local_agent_self_check_rejects_non_loopback_agent(url: str) -> None:
    with pytest.raises(ValueError, match="只允许"):
        asyncio.run(LocalAgentSelfCheck(FakeLocalAgentClient()).run(agent_url=url))


def test_local_agent_self_check_stops_server_when_client_start_fails() -> None:
    class FailingClient(FakeLocalAgentClient):
        async def start_iperf_client(self, base_url, request, token=None) -> AgentTaskDTO:
            raise AgentClientError("AGENT_TRAFFIC_PROCESS_START_FAILED", "iPerf client 启动失败")

    client = FailingClient()
    report = asyncio.run(
        LocalAgentSelfCheck(client).run(
            agent_url="http://127.0.0.1:18080",
            token="secret",
            duration_sec=1,
        )
    )

    assert report.passed is False
    assert "iPerf client 启动失败" in report.errors
    assert "server-1" in client.stopped
