from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.network_tools_router import router
from netconsole.core.feature_flags import FeatureGate
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import ExecutionTargetKind, TrafficRun, TrafficTestType


class FakeTrafficService:
    def __init__(self) -> None:
        self.config = None
        self.target = None

    async def start_tcp_port_test(self, config, target):
        self.config, self.target = config, target
        now = utc_now_iso()
        return TrafficRun(
            traffic_run_id="tcp-run-1",
            controller_task_id="tcp-task-1",
            test_type=TrafficTestType.TCP_PORT_TEST,
            role="tcp_probe",
            executor_kind=target.kind,
            normalized_config=config.to_dict(),
            status=TaskState.STARTING,
            created_at=now,
            updated_at=now,
        )


def test_network_tools_router_submits_whitelisted_tcp_probe(tmp_path) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.traffic_service = FakeTrafficService()
    app.state.feature_gate = FeatureGate(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/network-tools/tcp-port-test",
            json={
                "execution_target": {"kind": "LOCAL"},
                "target": "127.0.0.1",
                "port": 443,
                "interval_ms": 250,
                "timeout_ms": 500,
                "count": 2,
            },
        )

    assert response.status_code == 202
    assert response.json()["run"]["test_type"] == "TCP_PORT_TEST"
    assert app.state.traffic_service.config.to_dict()["target"] == "127.0.0.1"
    assert app.state.traffic_service.target.kind is ExecutionTargetKind.LOCAL
