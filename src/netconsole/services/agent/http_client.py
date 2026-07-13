from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from netconsole.models.agent_traffic import (
    AgentFpingStartRequest,
    AgentIperfClientStartRequest,
    AgentIperfServerStartRequest,
    AgentTaskDTO,
    AgentTaskEventPageDTO,
    AgentTaskResultDTO,
)


DEFAULT_AGENT_CONNECT_TIMEOUT_SECONDS = 3.0
DEFAULT_AGENT_READ_TIMEOUT_SECONDS = 8.0


class AgentClientError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AgentProbeResult:
    remote_agent_id: str
    remote_name: str
    version: str
    platform: str
    architecture: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


def normalize_agent_base_url(value: str) -> str:
    text = str(value or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Agent 地址必须使用 http 或 https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Agent 地址缺少主机，且不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("Agent 地址不能包含查询参数或片段")
    path = parsed.path.rstrip("/")
    if path and path != "":
        raise ValueError("Agent 地址只允许填写服务根地址")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Agent 端口无效") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Agent 端口必须在 1 到 65535 之间")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


class AgentHttpClient:
    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_AGENT_CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = DEFAULT_AGENT_READ_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        verify_tls: bool = True,
        user_agent: str = "",
    ) -> None:
        self.timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)
        self.transport = transport
        self.verify_tls = verify_tls
        self.user_agent = str(user_agent or "").strip()

    async def probe(self, base_url: str, token: str | None = None) -> AgentProbeResult:
        normalized = normalize_agent_base_url(base_url)
        headers = self._headers(token)
        started = time.perf_counter()
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            headers=headers,
            transport=self.transport,
            verify=self.verify_tls,
        ) as client:
            status = await self._get_data(client, f"{normalized}/api/v1/status")
            capabilities = await self._get_capabilities(client, normalized)
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        version = self._required_text(status, "version", "Agent 状态缺少 version")
        return AgentProbeResult(
            remote_agent_id=self._required_text(status, "agent_id", "Agent 状态缺少 agent_id"),
            remote_name=str(status.get("agent_name") or ""),
            version=version,
            platform=self._required_text(status, "os", "Agent 状态缺少 os"),
            architecture=self._required_text(status, "arch", "Agent 状态缺少 arch"),
            capabilities=capabilities,
            latency_ms=latency_ms,
        )

    async def get_status(self, base_url: str, token: str | None = None) -> dict[str, Any]:
        return await self._call_data("GET", base_url, "/api/v1/status", token)

    async def get_tools_status(self, base_url: str, token: str | None = None) -> dict[str, Any]:
        payload = await self._call_data("GET", base_url, "/api/v1/tools/status", token)
        tools = payload.get("tools")
        if not isinstance(tools, dict):
            raise AgentClientError("AGENT_RESPONSE_INCOMPATIBLE", "Agent 工具状态格式不兼容")
        return tools

    async def list_tasks(self, base_url: str, token: str | None = None) -> tuple[AgentTaskDTO, ...]:
        payload = await self._call_payload("GET", base_url, "/api/v1/tasks", token)
        if not isinstance(payload, list):
            raise AgentClientError("AGENT_RESPONSE_INCOMPATIBLE", "Agent 任务列表格式不兼容")
        return tuple(AgentTaskDTO.from_payload(item) for item in payload if isinstance(item, dict))

    async def get_task_logs(
        self,
        base_url: str,
        task_id: str,
        *,
        tail: int = 300,
        token: str | None = None,
    ) -> tuple[str, ...]:
        payload = await self._call_data(
            "GET",
            base_url,
            f"/api/v1/tasks/{self._task_id(task_id)}/logs",
            token,
            params={"tail": max(1, min(int(tail), 2000))},
        )
        lines = payload.get("lines")
        if not isinstance(lines, list):
            raise AgentClientError("AGENT_RESPONSE_INCOMPATIBLE", "Agent 任务日志格式不兼容")
        return tuple(str(line) for line in lines)

    async def list_packages(self, base_url: str, token: str | None = None) -> tuple[dict[str, Any], ...]:
        payload = await self._call_payload("GET", base_url, "/api/v1/packages", token)
        if not isinstance(payload, list):
            raise AgentClientError("AGENT_RESPONSE_INCOMPATIBLE", "Agent 采集包列表格式不兼容")
        return tuple(dict(item) for item in payload if isinstance(item, dict))

    async def start_fping(self, base_url: str, request: AgentFpingStartRequest, token: str | None = None) -> AgentTaskDTO:
        payload = await self._call_data("POST", base_url, "/api/v1/fping/start", token, json_body=request.as_payload())
        return AgentTaskDTO.from_payload(payload)

    async def start_iperf_server(
        self, base_url: str, request: AgentIperfServerStartRequest, token: str | None = None
    ) -> AgentTaskDTO:
        payload = await self._call_data("POST", base_url, "/api/v1/iperf/server/start", token, json_body=request.as_payload())
        return AgentTaskDTO.from_payload(payload)

    async def start_iperf_client(
        self, base_url: str, request: AgentIperfClientStartRequest, token: str | None = None
    ) -> AgentTaskDTO:
        payload = await self._call_data("POST", base_url, "/api/v1/iperf/client/start", token, json_body=request.as_payload())
        return AgentTaskDTO.from_payload(payload)

    async def get_task(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskDTO:
        payload = await self._call_data("GET", base_url, f"/api/v1/tasks/{self._task_id(task_id)}", token)
        return AgentTaskDTO.from_payload(payload)

    async def stop_task(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskDTO:
        payload = await self._call_data("POST", base_url, f"/api/v1/tasks/{self._task_id(task_id)}/stop", token)
        return AgentTaskDTO.from_payload(payload)

    async def get_task_events(
        self,
        base_url: str,
        task_id: str,
        *,
        after: int = 0,
        limit: int = 200,
        token: str | None = None,
    ) -> AgentTaskEventPageDTO:
        payload = await self._call_data(
            "GET",
            base_url,
            f"/api/v1/tasks/{self._task_id(task_id)}/events",
            token,
            params={"after": after, "limit": limit},
        )
        return AgentTaskEventPageDTO.from_payload(payload)

    async def get_task_result(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskResultDTO:
        payload = await self._call_data("GET", base_url, f"/api/v1/tasks/{self._task_id(task_id)}/result", token)
        return AgentTaskResultDTO.from_payload(payload)

    async def _call_data(
        self,
        method: str,
        base_url: str,
        path: str,
        token: str | None,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = await self._call_payload(
            method,
            base_url,
            path,
            token,
            json_body=json_body,
            params=params,
        )
        if not isinstance(data, dict):
            raise AgentClientError(
                "AGENT_RESPONSE_INCOMPATIBLE", "Agent data 字段格式不兼容"
            )
        return data

    async def _call_payload(
        self,
        method: str,
        base_url: str,
        path: str,
        token: str | None,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        normalized = normalize_agent_base_url(base_url)
        headers = self._headers(token)
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            headers=headers,
            transport=self.transport,
            verify=self.verify_tls,
        ) as client:
            return await self._request_payload(
                client,
                method,
                f"{normalized}{path}",
                json_body=json_body,
                params=params,
                unsupported_on_not_found=True,
            )

    async def _get_capabilities(self, client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
        try:
            value = await self._get_data(client, f"{base_url}/api/v1/capabilities", allow_not_found=True)
        except AgentClientError as exc:
            if exc.code == "AGENT_CAPABILITIES_UNAVAILABLE":
                return {}
            raise
        return value

    async def _get_data(self, client: httpx.AsyncClient, url: str, *, allow_not_found: bool = False) -> dict[str, Any]:
        return await self._request_data(client, "GET", url, allow_not_found=allow_not_found)

    async def _request_data(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        unsupported_on_not_found: bool = False,
    ) -> dict[str, Any]:
        data = await self._request_payload(
            client,
            method,
            url,
            json_body=json_body,
            params=params,
            allow_not_found=allow_not_found,
            unsupported_on_not_found=unsupported_on_not_found,
        )
        if not isinstance(data, dict):
            raise AgentClientError(
                "AGENT_RESPONSE_INCOMPATIBLE", "Agent data 字段格式不兼容"
            )
        return data

    async def _request_payload(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        unsupported_on_not_found: bool = False,
    ) -> Any:
        try:
            response = await client.request(method, url, json=json_body, params=params)
        except httpx.TimeoutException as exc:
            raise AgentClientError("AGENT_TIMEOUT", "连接 Agent 超时") from exc
        except httpx.ConnectError as exc:
            raise AgentClientError("AGENT_CONNECTION_FAILED", "无法连接 Agent") from exc
        except httpx.HTTPError as exc:
            raise AgentClientError("AGENT_HTTP_ERROR", "Agent HTTP 请求失败") from exc
        if 300 <= response.status_code < 400:
            raise AgentClientError("AGENT_REDIRECT_REJECTED", "Agent 返回了不允许的重定向", status_code=response.status_code)
        if response.status_code in {401, 403}:
            raise AgentClientError("AGENT_UNAUTHORIZED", "Agent 认证失败", status_code=response.status_code)
        if allow_not_found and response.status_code == 404:
            raise AgentClientError("AGENT_CAPABILITIES_UNAVAILABLE", "旧 Agent 未提供能力接口", status_code=404)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AgentClientError("AGENT_INVALID_JSON", "Agent 响应不是有效 JSON", status_code=response.status_code) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            raise AgentClientError("AGENT_RESPONSE_INCOMPATIBLE", "Agent 响应格式不兼容", status_code=response.status_code)
        if not response.is_success or payload.get("ok") is not True:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            message = str(error.get("message") or f"Agent 返回 HTTP {response.status_code}")
            code = str(error.get("code") or "")
            if not code and unsupported_on_not_found and response.status_code == 404:
                code = "AGENT_TRAFFIC_UNSUPPORTED"
            raise AgentClientError(code or "AGENT_REQUEST_FAILED", message, status_code=response.status_code)
        data = payload.get("data")
        return data

    def _headers(self, token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        if token:
            headers["X-Agent-Token"] = token
        return headers

    @staticmethod
    def _required_text(value: dict[str, Any], key: str, message: str) -> str:
        result = str(value.get(key) or "").strip()
        if not result:
            raise AgentClientError("AGENT_RESPONSE_INCOMPATIBLE", message)
        return result

    @staticmethod
    def _task_id(value: str) -> str:
        task_id = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", task_id):
            raise ValueError("task_id 格式无效")
        return task_id
