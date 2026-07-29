from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentAuthenticationType, AgentConfig, AgentRuntimeSnapshot, AgentStatus
from netconsole.models.agent_traffic import (
    AgentFpingStartRequest,
    AgentIperfClientStartRequest,
    AgentIperfServerStartRequest,
    AgentPingProbeStartRequest,
    AgentTaskDTO,
)
from netconsole.repositories.agent_repository import AgentRepository
from netconsole.services.agent.controller import (
    AgentControllerError,
    AgentControllerService,
    AgentControllerSettings,
)
from netconsole.services.agent.http_client import AgentClientError, AgentHttpClient, AgentProbeResult
from netconsole.services.job_center.task_application_service import TaskApplicationService


def _config(agent_id: str = "agent-1", *, url: str = "http://127.0.0.1:18080", enabled: bool = True) -> AgentConfig:
    return AgentConfig(
        agent_id=agent_id,
        name="测试 Agent",
        base_url=url,
        enabled=enabled,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class FakeAgentClient:
    def __init__(self, result: AgentProbeResult | None = None, error: AgentClientError | None = None) -> None:
        self.result = result or AgentProbeResult("remote-1", "Remote", "v1.0.0-windows", "windows", "amd64", {"ping_probe": True}, 12)
        self.error = error
        self.calls = 0

    async def probe(self, base_url: str, token: str | None = None) -> AgentProbeResult:
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeReadOnlyAgentClient(FakeAgentClient):
    async def get_status(self, base_url: str, token: str | None = None) -> dict:
        return {
            "agent_id": "remote-1",
            "agent_name": "Remote",
            "version": "0.2.0-win-agent",
            "os": "windows",
            "arch": "amd64",
            "current_tasks": 1,
            "task_count": 2,
            "package_count": 1,
        }

    async def get_tools_status(self, base_url: str, token: str | None = None) -> dict:
        return {
            "iperf3": {"exists": True, "ready": True, "version": "iperf 3"},
            "fping": {"exists": True, "ready": True},
            "mr_collector": {"exists": True, "ready": True},
        }

    async def list_tasks(self, base_url: str, token: str | None = None) -> tuple[AgentTaskDTO, ...]:
        return (AgentTaskDTO.from_payload({"task_id": "task-1", "task_type": "fping", "status": "running"}),)

    async def get_task(self, base_url: str, task_id: str, token: str | None = None) -> AgentTaskDTO:
        return AgentTaskDTO.from_payload({"task_id": task_id, "task_type": "fping", "status": "running"})

    async def get_task_logs(
        self,
        base_url: str,
        task_id: str,
        *,
        tail: int = 300,
        token: str | None = None,
    ) -> tuple[str, ...]:
        return ("第一行", "第二行")[-tail:]

    async def list_packages(self, base_url: str, token: str | None = None) -> tuple[dict, ...]:
        return (
            {
                "package_id": "package-1",
                "task_id": "task-1",
                "task_type": "mr_realtime_collect",
                "size": 1024,
                "package_download_url": "/api/v1/packages/package-1/download",
            },
        )


def _service(tmp_path, *, client=None, site="demo") -> AgentControllerService:
    paths = PathResolver(tmp_path)
    Database(paths.site_db_path(site)).initialize()
    return AgentControllerService(
        paths=paths,
        site_name=site,
        client=client or FakeAgentClient(),
        settings=AgentControllerSettings(health_check_enabled=False),
    )


def test_agent_repository_schema_wal_and_config_runtime_boundary(tmp_path) -> None:
    db_path = PathResolver(tmp_path).site_agents_db_path("demo")
    repository = AgentRepository(db_path)
    repository.create(_config())
    repository.save_runtime(
        AgentRuntimeSnapshot(
            agent_id="agent-1",
            status=AgentStatus.ONLINE,
            capabilities={"future_capability": {"mode": "new"}},
            updated_at="2026-01-01T00:01:00+00:00",
        )
    )
    assert repository.get("agent-1").name == "测试 Agent"
    assert repository.get_runtime("agent-1").capabilities["future_capability"] == {"mode": "new"}
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"agent_configs", "agent_runtime_snapshots", "agent_schema_meta"} <= tables


def test_agent_repository_repeated_initialization_preserves_unknown_table(tmp_path) -> None:
    db_path = PathResolver(tmp_path).site_agents_db_path("demo")
    repository = AgentRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE legacy_keep(value TEXT)")
        conn.execute("INSERT INTO legacy_keep VALUES ('保留')")
        conn.commit()
    AgentRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM legacy_keep").fetchone()[0] == "保留"
    assert repository.list() == []


def test_agent_repository_crud_archive_and_site_isolation(tmp_path) -> None:
    paths = PathResolver(tmp_path)
    first = AgentRepository(paths.site_agents_db_path("site-a"))
    second = AgentRepository(paths.site_agents_db_path("site-b"))
    first.create(_config())
    assert second.list() == []
    updated = replace(_config(), name="新名称", updated_at="2026-01-02T00:00:00+00:00")
    first.update(updated)
    assert first.get("agent-1").name == "新名称"
    assert first.archive("agent-1", "2026-01-03T00:00:00+00:00")
    assert first.get("agent-1") is None
    assert first.get("agent-1", include_archived=True).archived_at


def test_session_credential_never_enters_database_or_record(tmp_path) -> None:
    service = _service(tmp_path)
    record = service.create_agent(
        name="安全 Agent",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.TOKEN,
        token="top-secret-token",
    )
    assert record["has_credential"] is True
    assert "token" not in record
    assert b"top-secret-token" not in service.repository.db_path.read_bytes()


def test_failed_agent_update_keeps_previous_session_credential(tmp_path) -> None:
    service = _service(tmp_path)
    first = service.create_agent(
        name="Agent A",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.TOKEN,
        token="old-secret",
    )
    service.create_agent(
        name="Agent B",
        base_url="http://127.0.0.1:18081",
        enabled=True,
        authentication_type=AgentAuthenticationType.NONE,
    )
    reference = service.repository.get(first["agent_id"]).credential_reference
    with pytest.raises(AgentControllerError) as exc_info:
        service.update_agent(first["agent_id"], {"base_url": "http://127.0.0.1:18081", "token": "new-secret"})
    assert exc_info.value.code == "AGENT_ALREADY_EXISTS"
    assert service.credentials.get(reference) == "old-secret"


def test_controller_status_change_persists_and_unchanged_scheduler_probe_does_not_broadcast(tmp_path) -> None:
    service = _service(tmp_path)
    created = service.create_agent(
        name="Agent",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.NONE,
    )
    subscription = service.events.subscribe_stream()
    while not subscription.queue.empty():
        subscription.queue.get_nowait()
    asyncio.run(service.probe_agent(created["agent_id"], publish_probe=False, persist_unchanged=False))
    first = subscription.queue.get_nowait()
    assert first["type"] == "agent.status_changed"
    asyncio.run(service.probe_agent(created["agent_id"], publish_probe=False, persist_unchanged=False))
    assert subscription.queue.empty()
    assert service.get_agent(created["agent_id"])["status"] == "ONLINE"
    subscription.close()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (AgentClientError("AGENT_CONNECTION_FAILED", "无法连接 Agent"), AgentStatus.OFFLINE),
        (AgentClientError("AGENT_TIMEOUT", "连接 Agent 超时"), AgentStatus.OFFLINE),
        (AgentClientError("AGENT_UNAUTHORIZED", "Agent 认证失败", status_code=401), AgentStatus.UNAUTHORIZED),
    ],
)
def test_controller_normalizes_probe_failures(tmp_path, error, status) -> None:
    service = _service(tmp_path, client=FakeAgentClient(error=error))
    created = service.create_agent(
        name="Agent",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.NONE,
    )
    record = asyncio.run(service.probe_agent(created["agent_id"]))
    assert record["status"] == status.value
    assert record["last_error_code"] == error.code
    assert "traceback" not in record["last_error_message"].lower()


def test_http_adapter_contract_unknown_capability_and_auth_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Agent-Token") == "secret"
        if request.url.path.endswith("/status"):
            return httpx.Response(
                200,
                json={"ok": True, "data": {"agent_id": "remote", "agent_name": "Agent", "version": "0.2.0-win-agent", "os": "windows", "arch": "amd64"}},
            )
        return httpx.Response(404, json={"ok": False, "error": {"message": "接口不存在"}})

    client = AgentHttpClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(client.probe("http://127.0.0.1:18080", "secret"))
    assert result.capabilities == {}
    assert result.platform == "windows"
    assert result.version == "0.2.0-win-agent"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(200, text="not-json"), "AGENT_INVALID_JSON"),
        (httpx.Response(200, json={"unexpected": True}), "AGENT_RESPONSE_INCOMPATIBLE"),
    ],
)
def test_http_adapter_rejects_invalid_responses(response, code) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            return response
        return httpx.Response(200, json={"ok": True, "data": {}})

    with pytest.raises(AgentClientError) as exc_info:
        asyncio.run(AgentHttpClient(transport=httpx.MockTransport(handler)).probe("http://127.0.0.1:18080"))
    assert exc_info.value.code == code


def test_agent_http_client_typed_traffic_contract_and_cursor() -> None:
    requests: list[tuple[str, str, dict | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Agent-Token") == "secret"
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path.endswith("/events"):
            assert dict(request.url.params) == {"after": "7", "limit": "50"}
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "task_id": "task-1",
                        "events": [
                            {
                                "sequence": 8,
                                "timestamp": "2026-07-12T12:30:01.123Z",
                                "type": "future-event",
                                "source": "future-source",
                                "payload": {"future": {"value": 1}},
                                "unknown": True,
                            }
                        ],
                        "next_after": 8,
                        "has_more": False,
                    },
                },
            )
        if request.url.path.endswith("/result"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "task_id": "task-1",
                        "task_type": "fping",
                        "status": "completed",
                        "started_at": "2026-07-12T12:30:00Z",
                        "finished_at": "2026-07-12T12:31:00Z",
                        "summary": {"samples": 10},
                        "artifacts": [{"name": "fping_samples.jsonl", "kind": "samples", "available": True}],
                        "last_sequence": 8,
                        "error": "",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "task_id": "task-1",
                    "task_type": "fping",
                    "status": "running",
                    "created_at": "2026-07-12T12:30:00Z",
                    "start_time": "2026-07-12T12:30:00Z",
                    "end_time": "",
                    "params": body or {},
                },
            },
        )

    client = AgentHttpClient(transport=httpx.MockTransport(handler))
    base_url = "http://127.0.0.1:18080"
    fping_task = asyncio.run(
        client.start_fping(
            base_url,
            AgentFpingStartRequest(("127.0.0.1",), packet_size=1256, count=3),
            "secret",
        )
    )
    asyncio.run(client.start_iperf_server(base_url, AgentIperfServerStartRequest(one_off=True), "secret"))
    asyncio.run(
        client.start_iperf_client(
            base_url,
            AgentIperfClientStartRequest("192.0.2.1", protocol="udp", bandwidth_mbps=100, udp_packet_length=1400),
            "secret",
        )
    )
    asyncio.run(client.get_task(base_url, "task-1", "secret"))
    asyncio.run(client.stop_task(base_url, "task-1", "secret"))
    events = asyncio.run(client.get_task_events(base_url, "task-1", after=7, limit=50, token="secret"))
    result = asyncio.run(client.get_task_result(base_url, "task-1", "secret"))

    assert fping_task.task_id == "task-1"
    assert requests[0][2]["packet_size"] == 1256
    assert "extra_args" not in requests[0][2]
    assert requests[1][2]["one_off"] is True
    assert "extra_args" not in requests[2][2]
    assert events.events[0].type == "future-event"
    assert events.events[0].payload == {"future": {"value": 1}}
    assert result.summary == {"samples": 10}
    assert result.artifacts[0].name == "fping_samples.jsonl"


def test_agent_http_client_uses_exact_ping_probe_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/ping-probe/start"
        assert request.headers.get("X-Agent-Token") == "secret"
        assert json.loads(request.content) == {
            "targets": ["127.0.0.1"],
            "tcp_port": 443,
            "interval_ms": 250,
            "timeout_ms": 500,
            "packet_size": 64,
            "count": 2,
        }
        return httpx.Response(
            200,
            json={"ok": True, "data": {"task_id": "tcp-1", "task_type": "ping_probe", "status": "running"}},
        )

    task = asyncio.run(
        AgentHttpClient(transport=httpx.MockTransport(handler)).start_ping_probe(
            "http://127.0.0.1:18080",
            AgentPingProbeStartRequest("127.0.0.1", 443, interval_ms=250, timeout_ms=500, count=2),
            "secret",
        )
    )

    assert task.task_id == "tcp-1"
    assert task.task_type == "ping_probe"


def test_agent_http_client_reports_old_agent_traffic_endpoint_as_unsupported() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"ok": False, "error": {"message": "接口不存在"}})

    client = AgentHttpClient(transport=httpx.MockTransport(handler))
    with pytest.raises(AgentClientError) as exc_info:
        asyncio.run(client.get_task_events("http://127.0.0.1:18080", "task-1"))
    assert exc_info.value.code == "AGENT_TRAFFIC_UNSUPPORTED"


def test_agent_http_client_read_only_control_center_contract() -> None:
    requested: list[tuple[str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Agent-Token") == "secret"
        requested.append((request.url.path, dict(request.url.params)))
        payloads = {
            "/api/v1/status": {"agent_id": "remote", "version": "0.2.0", "os": "windows", "arch": "amd64"},
            "/api/v1/tools/status": {
                "tools": {"iperf3": {"ready": True}, "fping": {"ready": True}, "mr_collector": {"ready": True}}
            },
            "/api/v1/tasks": [{"task_id": "task-1", "task_type": "fping", "status": "running"}],
            "/api/v1/tasks/task-1/logs": {"task_id": "task-1", "lines": ["line-1"]},
            "/api/v1/packages": [{"package_id": "package-1", "size": 10}],
        }
        return httpx.Response(200, json={"ok": True, "data": payloads[request.url.path]})

    client = AgentHttpClient(transport=httpx.MockTransport(handler))
    base_url = "http://127.0.0.1:18080"
    assert asyncio.run(client.get_status(base_url, "secret"))["agent_id"] == "remote"
    assert asyncio.run(client.get_tools_status(base_url, "secret"))["iperf3"]["ready"] is True
    assert asyncio.run(client.list_tasks(base_url, "secret"))[0].task_id == "task-1"
    assert asyncio.run(client.get_task_logs(base_url, "task-1", tail=25, token="secret")) == ("line-1",)
    assert asyncio.run(client.list_packages(base_url, "secret"))[0]["package_id"] == "package-1"
    assert requested[3] == ("/api/v1/tasks/task-1/logs", {"tail": "25"})


def test_agent_rest_crud_probe_disable_archive_and_no_secret(tmp_path) -> None:
    service = _service(tmp_path)
    app = create_app(
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=service,
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app) as client:
        created_response = client.post(
            "/api/agents",
            json={
                "name": "车载 Agent 01",
                "base_url": "http://127.0.0.1:18080",
                "authentication_type": "token",
                "token": "api-secret",
                "tags": ["车载"],
                "note": "测试",
            },
        )
        assert created_response.status_code == 201
        assert "api-secret" not in created_response.text
        agent_id = created_response.json()["data"]["agent_id"]
        assert client.get("/api/agents").json()["data"][0]["has_credential"] is True
        assert client.post(f"/api/agents/{agent_id}/probe").json()["data"]["status"] == "ONLINE"
        assert client.patch(f"/api/agents/{agent_id}", json={"note": "已更新"}).json()["data"]["note"] == "已更新"
        assert client.post(f"/api/agents/{agent_id}/disable").json()["data"]["status"] == "DISABLED"
        assert client.post(f"/api/agents/{agent_id}/enable").json()["data"]["status"] == "UNKNOWN"
        assert client.delete(f"/api/agents/{agent_id}").json()["data"] == {"agent_id": agent_id, "archived": True}
        assert client.delete(f"/api/agents/{agent_id}").json()["data"] == {"agent_id": agent_id, "archived": True}
        assert client.get("/api/agents").json()["data"] == []


def test_agent_rest_unsaved_probe_error_is_standardized(tmp_path) -> None:
    service = _service(tmp_path, client=FakeAgentClient(error=AgentClientError("AGENT_TIMEOUT", "连接 Agent 超时")))
    app = create_app(
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=service,
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app) as client:
        response = client.post("/api/agents/probe", json={"base_url": "http://127.0.0.1:18080"})
    assert response.status_code == 502
    assert response.json() == {"ok": False, "error": {"code": "AGENT_TIMEOUT", "message": "连接 Agent 超时", "details": {}}}


def test_agent_rest_read_only_control_center_endpoints(tmp_path) -> None:
    service = _service(tmp_path, client=FakeReadOnlyAgentClient())
    created = service.create_agent(
        name="Agent",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.NONE,
    )
    app = create_app(
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=service,
        frontend_dist=tmp_path / "missing",
    )
    prefix = f"/api/agents/{created['agent_id']}/remote"
    with TestClient(app) as client:
        assert client.get(f"{prefix}/status").json()["data"]["current_tasks"] == 1
        assert client.get(f"{prefix}/tools").json()["data"]["iperf3"]["ready"] is True
        assert client.get(f"{prefix}/tasks").json()["data"][0]["task_id"] == "task-1"
        assert client.get(f"{prefix}/tasks/task-1").json()["data"]["status"] == "running"
        assert client.get(f"{prefix}/tasks/task-1/logs?tail=1").json()["data"]["lines"] == ["第二行"]
        assert client.get(f"{prefix}/packages").json()["data"][0]["package_id"] == "package-1"

        for method, path in (
            ("post", f"{prefix}/tasks/task-1/stop"),
            ("delete", f"{prefix}/packages/package-1"),
        ):
            assert getattr(client, method)(path).status_code == 404


def test_saved_agent_probe_persists_failure_and_returns_domain_error(tmp_path) -> None:
    service = _service(tmp_path, client=FakeAgentClient(error=AgentClientError("AGENT_CONNECTION_FAILED", "无法连接 Agent")))
    created = service.create_agent(
        name="Agent",
        base_url="http://127.0.0.1:18080",
        enabled=True,
        authentication_type=AgentAuthenticationType.NONE,
    )
    app = create_app(
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=service,
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app) as client:
        response = client.post(f"/api/agents/{created['agent_id']}/probe")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AGENT_CONNECTION_FAILED"
    assert service.get_agent(created["agent_id"])["status"] == "OFFLINE"


def test_agent_websocket_snapshot_and_incremental_event(tmp_path) -> None:
    service = _service(tmp_path)
    app = create_app(
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=service,
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app) as client, client.websocket_connect("/ws/agents") as websocket:
        assert websocket.receive_json() == {"type": "snapshot", "agents": []}
        service.events.publish("agent.updated", "agent-1", {"name": "测试"})
        event = websocket.receive_json()
        assert event["type"] == "agent.updated"
        assert event["agent_id"] == "agent-1"


def test_fastapi_lifespan_starts_and_stops_agent_controller(tmp_path) -> None:
    class TrackingService(AgentControllerService):
        started = False
        stopped = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    service = TrackingService(paths=PathResolver(tmp_path), settings=AgentControllerSettings(health_check_enabled=False))
    Database(service.paths.site_db_path("demo")).initialize()
    app = create_app(
        paths=PathResolver(tmp_path),
        task_service=TaskApplicationService(paths=PathResolver(tmp_path)),
        agent_service=service,
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app):
        assert service.started is True
        assert service.stopped is False
    assert service.stopped is True
