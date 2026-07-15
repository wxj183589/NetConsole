from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ac_management_web_fixture import build_ac_management_fixture
from netconsole.application.ac.web_application_service import AcWebApplicationService
from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _client(tmp_path: Path) -> TestClient:
    paths, _db_path, _files = build_ac_management_fixture(tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    app.state.ac_web_application_service = AcWebApplicationService(paths, app.state.task_service)
    return TestClient(app)


def test_ac_action_plan_rejects_tamper_repeat_and_records_fake_audit(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        unknown = client.post("/api/ac-management/actions/plans", json={"target_id": "ac-1", "action_id": "raw_command"})
        expired_plan = client.post("/api/ac-management/actions/plans", json={"target_id": "ac-1", "action_id": "save_config"}).json()
        client.app.state.ac_web_application_service._plans[expired_plan["plan_id"]]["expires_at"] = 0
        expired = client.post(
            f"/api/ac-management/actions/plans/{expired_plan['plan_id']}/confirm",
            json={"plan_digest": expired_plan["plan_digest"], "confirm_token": expired_plan["confirm_token"]},
        )
        plan = client.post("/api/ac-management/actions/plans", json={"target_id": "ac-1", "action_id": "save_config"})
        payload = plan.json()
        tampered = client.post(
            f"/api/ac-management/actions/plans/{payload['plan_id']}/confirm",
            json={"plan_digest": "tampered", "confirm_token": payload["confirm_token"]},
        )
        confirmed = client.post(
            f"/api/ac-management/actions/plans/{payload['plan_id']}/confirm",
            json={"plan_digest": payload["plan_digest"], "confirm_token": payload["confirm_token"]},
        )
        repeated = client.post(
            f"/api/ac-management/actions/plans/{payload['plan_id']}/confirm",
            json={"plan_digest": payload["plan_digest"], "confirm_token": payload["confirm_token"]},
        )
        executed = client.post(f"/api/ac-management/actions/plans/{payload['plan_id']}/execute")
        audit = client.get(f"/api/ac-management/actions/plans/{payload['plan_id']}/audit")

    assert unknown.status_code == 422
    assert expired.status_code == 409
    assert plan.status_code == 200
    assert tampered.status_code == 409
    assert confirmed.status_code == 200
    assert repeated.status_code == 409
    assert executed.status_code == 202
    assert executed.json()["status"] == "COMPLETED"
    assert audit.json()["executor"] == "FAKE"
    assert audit.json()["audit"] is True


def test_ac_extension_preview_apply_and_rollback_are_explicitly_confirmed(tmp_path: Path) -> None:
    csv_content = (
        "AP名称,AP_MAC,归属类型,归属站点,归属区间,区间起点站,区间终点站,场段,区域,网络,线别,里程,点位说明,方向,备注\n"
        "AP-Online,0000-0000-0001,section,车站A,A-B 区间,A,B,,,,上行,K1+100,站台,上行,web\n"
    ).encode("utf-8-sig")
    with _client(tmp_path) as client:
        preview = client.post(
            "/api/ac-management/extensions/import-preview",
            files={"file": ("extensions.csv", csv_content, "text/csv")},
        )
        preview_payload = preview.json()
        rejected = client.post(
            "/api/ac-management/extensions/import-apply",
            json={"preview_id": preview_payload["preview_id"], "preview_digest": preview_payload["preview_digest"]},
        )
        applied = client.post(
            "/api/ac-management/extensions/import-apply",
            json={
                "preview_id": preview_payload["preview_id"],
                "preview_digest": preview_payload["preview_digest"],
                "explicit_confirmation": True,
            },
        )
        rollback = client.post(
            f"/api/ac-management/extensions/audits/{applied.json()['audit_id']}/rollback",
            json={"explicit_confirmation": True},
        )

    assert preview.status_code == 200
    assert preview_payload["row_count"] == 1
    assert rejected.status_code == 409
    assert applied.status_code == 202
    assert applied.json()["status"] == "APPLIED"
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "ROLLED_BACK"
