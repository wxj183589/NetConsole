from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from netconsole.models.agent_traffic import (
    AgentFpingStartRequest,
    AgentIperfClientStartRequest,
    AgentIperfServerStartRequest,
    AgentTaskDTO,
)
from netconsole.services.agent.http_client import AgentClientError, AgentHttpClient, normalize_agent_base_url


_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "completed_with_warnings",
        "stopped",
        "stopped_with_warnings",
        "failed",
        "cancelled",
    }
)
_SUCCESS_STATUSES = frozenset({"completed", "completed_with_warnings", "stopped", "stopped_with_warnings"})


@dataclass
class LocalAgentSelfCheckReport:
    agent_url: str
    agent_name: str = ""
    agent_version: str = ""
    tool_ready: dict[str, bool] = field(default_factory=dict)
    fping_task_id: str = ""
    fping_status: str = ""
    fping_samples: int = 0
    fping_log_lines: int = 0
    iperf_server_task_id: str = ""
    iperf_server_status: str = ""
    iperf_client_task_id: str = ""
    iperf_client_status: str = ""
    iperf_client_log_lines: int = 0
    tcp_requested_mbps: float = 2.0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


class LocalAgentSelfCheck:
    """仅通过回环地址验证 Agent 的结构化 fping/iPerf 生命周期。"""

    def __init__(self, client: AgentHttpClient | None = None) -> None:
        self.client = client or AgentHttpClient(read_timeout=15.0)

    async def run(
        self,
        *,
        agent_url: str = "http://127.0.0.1:18080",
        token: str | None = None,
        iperf_port: int = 5201,
        duration_sec: int = 10,
        tcp_requested_mbps: float = 2.0,
    ) -> LocalAgentSelfCheckReport:
        normalized = _local_agent_url(agent_url)
        if not 1 <= iperf_port <= 65535:
            raise ValueError("iperf_port 必须在 1-65535 之间")
        if not 1 <= duration_sec <= 60:
            raise ValueError("duration_sec 必须在 1-60 秒之间")
        if tcp_requested_mbps <= 0:
            raise ValueError("tcp_requested_mbps 必须大于 0")

        report = LocalAgentSelfCheckReport(agent_url=normalized, tcp_requested_mbps=tcp_requested_mbps)
        active_task_ids: list[str] = []
        try:
            probe = await self.client.probe(normalized, token)
            report.agent_name = probe.remote_name or probe.remote_agent_id
            report.agent_version = probe.version
            tools = await self.client.get_tools_status(normalized, token)
            report.tool_ready = {
                name: bool(details.get("ready")) if isinstance(details, dict) else False
                for name, details in tools.items()
            }
            missing = [name for name in ("mr_collector", "fping", "iperf3") if not report.tool_ready.get(name)]
            if missing:
                raise RuntimeError(f"Agent 工具未就绪：{', '.join(missing)}")

            fping = await self.client.start_fping(
                normalized,
                AgentFpingStartRequest(
                    targets=("127.0.0.1",),
                    interval_ms=1000,
                    timeout_ms=4000,
                    packet_size=64,
                    count=10,
                ),
                token,
            )
            report.fping_task_id = fping.task_id
            fping = await self._wait_terminal(normalized, fping.task_id, token, timeout_sec=25)
            await self.client.stop_task(normalized, fping.task_id, token)
            fping_result = await self.client.get_task_result(normalized, fping.task_id, token)
            report.fping_status = fping.status
            report.fping_samples = int(fping_result.summary.get("samples") or 0)
            report.fping_log_lines = len(await self.client.get_task_logs(normalized, fping.task_id, token=token))
            if fping.status.lower() not in _SUCCESS_STATUSES:
                report.errors.append(f"fping 任务异常终结：{fping.status}")
            if report.fping_samples < 1:
                report.errors.append("fping 未生成样本")

            server = await self.client.start_iperf_server(
                normalized,
                AgentIperfServerStartRequest(bind_address="127.0.0.1", port=iperf_port, one_off=True),
                token,
            )
            report.iperf_server_task_id = server.task_id
            active_task_ids.append(server.task_id)
            await asyncio.sleep(0.5)

            client_task = await self.client.start_iperf_client(
                normalized,
                AgentIperfClientStartRequest(
                    server_host="127.0.0.1",
                    server_port=iperf_port,
                    protocol="tcp",
                    duration_sec=duration_sec,
                    parallel=1,
                    bandwidth_mbps=tcp_requested_mbps,
                    reverse=False,
                ),
                token,
            )
            report.iperf_client_task_id = client_task.task_id
            active_task_ids.append(client_task.task_id)
            client_task = await self._wait_terminal(
                normalized,
                client_task.task_id,
                token,
                timeout_sec=duration_sec + 20,
            )
            await self.client.stop_task(normalized, client_task.task_id, token)
            client_result = await self.client.get_task_result(normalized, client_task.task_id, token)
            report.iperf_client_status = client_task.status
            report.iperf_client_log_lines = len(
                await self.client.get_task_logs(normalized, client_task.task_id, token=token)
            )
            if client_task.status.lower() not in _SUCCESS_STATUSES:
                report.errors.append(f"iPerf client 异常终结：{client_task.status}")
            if not any(artifact.available and artifact.kind == "raw" for artifact in client_result.artifacts):
                report.errors.append("iPerf client 未生成 raw 日志")

            await self.client.stop_task(normalized, server.task_id, token)
            server = await self._wait_terminal(normalized, server.task_id, token, timeout_sec=10)
            report.iperf_server_status = server.status
            if server.status.lower() not in _TERMINAL_STATUSES:
                report.errors.append(f"iPerf server 未进入终态：{server.status}")
            report.warnings.append(
                "当前 Agent 的 TCP bandwidth_mbps 只记录期望值，runner 不对 TCP 强制限速；本机测试不作为链路带宽验收。"
            )
        except (AgentClientError, RuntimeError, TimeoutError, ValueError) as exc:
            report.errors.append(str(exc))
        finally:
            for task_id in reversed(active_task_ids):
                try:
                    await self.client.stop_task(normalized, task_id, token)
                except (AgentClientError, ValueError):
                    pass
        return report

    async def _wait_terminal(
        self,
        agent_url: str,
        task_id: str,
        token: str | None,
        *,
        timeout_sec: float,
    ) -> AgentTaskDTO:
        deadline = time.monotonic() + timeout_sec
        while True:
            task = await self.client.get_task(agent_url, task_id, token)
            if task.status.lower() in _TERMINAL_STATUSES:
                return task
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Agent 任务等待终态超时：{task_id}")
            await asyncio.sleep(0.25)


def _local_agent_url(value: str) -> str:
    normalized = normalize_agent_base_url(value)
    host = (urlsplit(normalized).hostname or "").lower()
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("本地 Agent 自检只允许 127.0.0.1 或 localhost")
    return normalized
