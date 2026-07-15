from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.models.agent import AgentStatus
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    TrafficEvent,
    TrafficEventType,
    TrafficPingSample,
    TrafficRun,
    TrafficRunPage,
    TrafficTestType,
)
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError
from netconsole.services.traffic.event_hub import TrafficEventHub
from netconsole.services.traffic.web_application_service import TrafficWebApplicationService


class FakeAgentService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def list_agents(self) -> list[dict[str, object]]:
        return [
            {
                "agent_id": "agent-1",
                "name": "车站 Agent",
                "enabled": True,
                "status": AgentStatus.ONLINE.value,
                "platform": "windows",
                "architecture": "amd64",
                "version": "1.0.0",
                "capabilities": {"iperf_server": True, "iperf_client": True, "fping": True},
            },
            {
                "agent_id": "agent-2",
                "name": "离线 Agent",
                "enabled": True,
                "status": AgentStatus.OFFLINE.value,
                "capabilities": {"fping": True},
            },
        ]


class FakeTrafficService:
    def __init__(self) -> None:
        self.events = TrafficEventHub()
        self.started = False
        self.stopped = False
        self.runs: dict[str, TrafficRun] = {}
        self.run_events: dict[str, list[dict[str, object]]] = {}
        self.samples: dict[str, list[TrafficPingSample]] = {}

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def start_iperf_server(self, config, execution_target, **kwargs) -> TrafficRun:
        return self._create(TrafficTestType.IPERF_SERVER, "server", execution_target, {"port": config.port}, **kwargs)

    async def start_iperf_client(self, config, execution_target, **kwargs) -> TrafficRun:
        return self._create(TrafficTestType.IPERF_CLIENT, "client", execution_target, config.as_dict(), **kwargs)

    async def start_high_frequency_ping(self, config, execution_target, **kwargs) -> TrafficRun:
        return self._create(TrafficTestType.HIGH_FREQUENCY_PING, "ping", execution_target, config.to_dict(), **kwargs)

    async def cancel(self, controller_task_id: str) -> TrafficRun:
        run = self.get_run_by_task(controller_task_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        stopped = replace(run, status=TaskState.STOPPING, updated_at=utc_now_iso())
        self.runs[run.traffic_run_id] = stopped
        return stopped

    async def retry(self, controller_task_id: str) -> TrafficRun:
        run = self.get_run_by_task(controller_task_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return self._create(
            run.test_type,
            run.role,
            type("Target", (), {"kind": run.executor_kind, "agent_id": run.agent_id})(),
            run.normalized_config,
            retry_of_traffic_run_id=run.traffic_run_id,
        )

    def list_runs_page(self, *, offset: int = 0, limit: int = 100, **_kwargs) -> TrafficRunPage:
        runs = list(self.runs.values())
        selected_offset = max(0, int(offset))
        selected_limit = max(1, min(int(limit), 500))
        items = runs[selected_offset : selected_offset + selected_limit]
        return TrafficRunPage(
            items=items,
            total=len(runs),
            offset=selected_offset,
            limit=selected_limit,
            has_more=selected_offset + len(items) < len(runs),
        )

    def get_run(self, traffic_run_id: str) -> TrafficRun | None:
        return self.runs.get(traffic_run_id)

    def get_run_by_task(self, controller_task_id: str) -> TrafficRun | None:
        return next((run for run in self.runs.values() if run.controller_task_id == controller_task_id), None)

    def get_events(self, traffic_run_id: str, *, after: int = 0, limit: int = 500) -> list[dict[str, object]]:
        if traffic_run_id not in self.runs:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return [event for event in self.run_events.get(traffic_run_id, []) if int(event["sequence"]) > after][:limit]

    def get_ping_samples(self, traffic_run_id: str, *, after: int = 0, **_kwargs) -> list[TrafficPingSample]:
        if traffic_run_id not in self.runs:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return [sample for sample in self.samples.get(traffic_run_id, []) if sample.sequence > after]

    def get_summary(self, traffic_run_id: str) -> dict[str, object]:
        run = self.get_run(traffic_run_id)
        if run is None:
            raise TrafficTestError(TrafficErrorCode.RESULT_NOT_FOUND, "流量任务不存在")
        return dict(run.summary)

    def publish_event(self, traffic_run_id: str) -> None:
        run = self.runs[traffic_run_id]
        event = TrafficEvent(
            traffic_run_id=traffic_run_id,
            controller_task_id=run.controller_task_id,
            source="test",
            type=TrafficEventType.SAMPLE,
            payload={"rtt_ms": 1.2},
            sequence=1,
        )
        self.run_events.setdefault(traffic_run_id, []).append(event.to_dict())
        self.events.publish(event)

    def _create(self, test_type, role, execution_target, normalized_config, **kwargs) -> TrafficRun:
        index = len(self.runs) + 1
        now = utc_now_iso()
        run = TrafficRun(
            traffic_run_id=f"run-{index}",
            controller_task_id=f"task-{index}",
            test_type=test_type,
            role=role,
            executor_kind=execution_target.kind,
            agent_id=getattr(execution_target, "agent_id", ""),
            normalized_config=dict(normalized_config),
            status=TaskState.RUNNING,
            created_at=now,
            updated_at=now,
            started_at=now,
            summary={"sent": 3, "loss_percent": 0},
            raw_reference=r"C:\\private\\traffic.log",
            result_reference="summary.json",
            retry_of_traffic_run_id=str(kwargs.get("retry_of_traffic_run_id") or ""),
        )
        self.runs[run.traffic_run_id] = run
        if test_type is TrafficTestType.HIGH_FREQUENCY_PING:
            self.samples[run.traffic_run_id] = [
                TrafficPingSample(run.traffic_run_id, 1, now, "192.0.2.1", 1, True, 1.2, packet_size=64)
            ]
        return run


def _app(tmp_path):
    paths = PathResolver(tmp_path)
    traffic = FakeTrafficService()
    agent = FakeAgentService()
    app = create_app(
        paths=paths,
        task_service=TaskApplicationService(paths=paths),
        agent_service=agent,
        traffic_service=traffic,
        frontend_dist=tmp_path / "missing",
    )
    app.state.traffic_web_application_service = TrafficWebApplicationService(traffic, agent)
    return app, traffic, agent


def test_traffic_rest_targets_start_list_detail_cancel_and_retry(tmp_path) -> None:
    app, traffic, _agent = _app(tmp_path)
    with TestClient(app) as client:
        targets = client.get("/api/traffic/execution-targets").json()
        assert [target["id"] for target in targets] == ["LOCAL", "agent-1", "agent-2"]
        assert targets[1]["available"] is True
        assert targets[2]["available"] is False

        response = client.post(
            "/api/traffic/fping",
            json={"targets": ["192.0.2.1"], "packet_size": 64, "execution_target": {"kind": "LOCAL"}},
        )
        assert response.status_code == 202
        run_id = response.json()["run"]["traffic_run_id"]
        assert client.get("/api/traffic/runs").json()[0]["traffic_run_id"] == run_id
        assert client.get(f"/api/traffic/runs/{run_id}").json()["status"] == "RUNNING"
        assert client.get(f"/api/traffic/runs/{run_id}").json()["raw_reference"] == ""
        assert client.get(f"/api/traffic/runs/{run_id}").json()["result_reference"] == "summary.json"
        assert client.get(f"/api/traffic/runs/{run_id}/summary").json()["summary"]["sent"] == 3
        assert client.get(f"/api/traffic/runs/{run_id}/ping-samples").json()[0]["packet_size"] == 64
        assert client.post(f"/api/traffic/runs/{run_id}/cancel").json()["status"] == "STOPPING"
        traffic.runs[run_id] = replace(traffic.runs[run_id], status=TaskState.FAILED)
        retry = client.post(f"/api/traffic/runs/{run_id}/retry")
        assert retry.status_code == 202
        assert retry.json()["retry_of_traffic_run_id"] == run_id


def test_traffic_rest_error_is_standardized_and_path_redacted(tmp_path) -> None:
    app, _traffic, _agent = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/traffic/runs/missing")
    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": {"code": "TRAFFIC_RESULT_NOT_FOUND", "message": "流量任务不存在", "details": {"retryable": False}},
    }

    _traffic.get_run = lambda _run_id: (_ for _ in ()).throw(
        TrafficTestError(
            TrafficErrorCode.PROCESS_START_FAILED,
            r"C:\\private\\iperf3.exe 启动失败 token=top-secret",
        )
    )
    with TestClient(app) as client:
        protected = client.get("/api/traffic/runs/secret").json()
    assert "C:\\private" not in protected["error"]["message"]
    assert "top-secret" not in protected["error"]["message"]


def test_traffic_websocket_uses_dedicated_incremental_channel(tmp_path) -> None:
    app, traffic, _agent = _app(tmp_path)
    with TestClient(app) as client:
        run_id = client.post("/api/traffic/fping", json={"targets": ["192.0.2.1"]}).json()["run"]["traffic_run_id"]
        with client.websocket_connect(f"/ws/traffic/{run_id}?after_event=0&after_sample=1") as websocket:
            ready = websocket.receive_json()
            assert ready == {"type": "ready", "traffic_run_id": run_id}
            traffic.publish_event(run_id)
            message = websocket.receive_json()
            assert message["type"] in {"event", "events"}


def test_fastapi_lifespan_starts_and_stops_traffic_service(tmp_path) -> None:
    app, traffic, agent = _app(tmp_path)
    with TestClient(app):
        assert agent.started is True
        assert traffic.started is True
    assert traffic.stopped is True
    assert agent.stopped is True
