from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.terminal_router import router
from test_terminal_workspace import _manager_fixture, _wait_until


def test_console_followup_api_clones_keeps_secrets_backend_and_exports_zip(
    tmp_path, monkeypatch
):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    app = FastAPI()
    app.state.terminal_session_manager = manager
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    try:
        first = client.post(
            "/api/terminal/sessions", json={"device_uuid": device.device_uuid}
        ).json()["session"]
        _wait_until(
            lambda: manager.get_runtime(first["session_id"]).snapshot.state == "RUNNING"
        )
        cloned = client.post(f"/api/terminal/sessions/{first['session_id']}/clone")
        assert cloned.status_code == 200
        assert cloned.json()["session"]["session_id"] != first["session_id"]
        assert "test-secret" not in cloned.text
        cloned_id = cloned.json()["session"]["session_id"]
        assert client.post(f"/api/terminal/sessions/{cloned_id}/window-claim").status_code == 200
        assert client.post(f"/api/terminal/sessions/{cloned_id}/window-claim").status_code == 422
        template = client.post(
            f"/api/terminal/sessions/{first['session_id']}/save-profile"
        )
        assert template.status_code == 200, template.text
        assert (
            "test-secret" not in template.text
            and template.json()["password_configured"] is True
        )
        renamed = client.patch(
            f"/api/terminal/sessions/{first['session_id']}",
            json={"name": "AC-01-renamed"},
        )
        assert renamed.json()["session_name"] == "AC-01-renamed"
        assert (
            client.delete(f"/api/terminal/history/{first['session_id']}").status_code
            == 422
        )
        button_config = client.get("/api/terminal/quick-buttons").json()
        assert (
            client.put("/api/terminal/quick-buttons", json=button_config).status_code
            == 200
        )
        exported = client.get("/api/terminal/quick-buttons/export")
        assert exported.json() == button_config
        sent = client.post(
            "/api/terminal/batch-sends",
            json={"session_ids": [first["session_id"]], "text": "display test\r"},
        )
        assert sent.status_code == 200
        job = sent.json()
        _wait_until(
            lambda: manager.dispatcher.get(job["id"])["rows"][0]["state"] == "SENT"
        )
    finally:
        manager.close()
    preview = client.get(f"/api/terminal/history/{first['session_id']}/transcript")
    assert (
        preview.status_code == 200 and "password=test-secret" in preview.json()["text"]
    )
    exported = client.get(f"/api/terminal/history/{first['session_id']}/export/zip")
    assert exported.status_code == 200 and exported.content.startswith(b"PK")
    assert client.delete(f"/api/terminal/history/{first['session_id']}").json()[
        "deleted"
    ]
    assert client.delete(f"/api/terminal/history/{first['session_id']}").json()[
        "deleted"
    ]
