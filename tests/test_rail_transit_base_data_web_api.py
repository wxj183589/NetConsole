from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture
from netconsole.backend.api.main import create_app
from netconsole.core.runtime_mode import RuntimeMode


class _NoopAsyncService:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_base_data_api_is_read_only_except_preview_and_redacts_credentials(tmp_path: Path) -> None:
    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    app = create_app(
        RuntimeMode.SERVER,
        paths=paths,
        task_service=object(),  # type: ignore[arg-type]
        agent_service=_NoopAsyncService(),  # type: ignore[arg-type]
        traffic_service=_NoopAsyncService(),  # type: ignore[arg-type]
        frontend_dist=tmp_path / "missing",
    )
    with TestClient(app) as client:
        assert client.get("/api/rail-transit/base-data/summary").status_code == 200
        before = _fingerprint(db_path)
        responses = [
            client.get("/api/rail-transit/base-data/summary"),
            client.get("/api/rail-transit/base-data/stations"),
            client.get("/api/rail-transit/base-data/sections"),
            client.get("/api/rail-transit/base-data/aps?page=1&page_size=2"),
            client.get("/api/rail-transit/base-data/trains"),
            client.get("/api/rail-transit/base-data/mrs"),
            client.get("/api/rail-transit/base-data/issues"),
            client.get("/api/rail-transit/base-data/issues/groups"),
            client.get("/api/rail-transit/base-data/import-policies"),
            client.get("/api/rail-transit/base-data/relations"),
        ]
        ap_id = responses[3].json()["items"][0]["id"]
        train_id = responses[4].json()["items"][0]["id"]
        mr_id = responses[5].json()["items"][0]["id"]
        responses.extend(
            [
                client.get(f"/api/rail-transit/base-data/aps/{ap_id}"),
                client.get(f"/api/rail-transit/base-data/trains/{train_id}"),
                client.get(f"/api/rail-transit/base-data/mrs/{mr_id}"),
            ]
        )
        preview = client.post(
            "/api/rail-transit/base-data/import-preview",
            files={
                "file": (
                    "preview.json",
                    json.dumps(
                        [{"ap_name": "AP-Preview", "ap_mac_display": "0011-2233-4455"}],
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "application/json",
                )
            },
        )
        responses.append(preview)
    assert all(response.status_code == 200 for response in responses)
    text = "".join(response.text for response in responses).casefold()
    assert "private-user" not in text
    assert "private-pass" not in text
    assert "password" not in text
    assert _fingerprint(db_path) == before

    routes = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/rail-transit/base-data")
        for method in operations
    }
    assert {path for path, method in routes if method == "POST"} == {
        "/api/rail-transit/base-data/import-preview",
        "/api/rail-transit/base-data/import-apply",
        "/api/rail-transit/base-data/import-operations/{operation_id}/rollback",
    }
    assert not any(method in {"PUT", "PATCH", "DELETE"} for _path, method in routes)
    assert responses[8].json()["write_enabled"] is False
