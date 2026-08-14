from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.wps_sync_router import router as wps_sync_router
from netconsole.core.feature_flags import (
    FeatureGate,
    install_embedded_feature_files,
    validate_feature_profile_payload,
)
from netconsole.core.feature_registry import FEATURE_BY_ID, FeatureStatus
from netconsole.core.paths import PathResolver
from netconsole.services.runtime_self_check_service import RuntimeSelfCheckService


ROOT = Path(__file__).resolve().parents[1]
WPS_FEATURE_ID = "capability.trackside_ap.wps_sync"
WPS_TARGET_CODE = "wps_standard_spreadsheet"


def _profile(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / "config" / "profiles" / "features" / f"{name}.json").read_text(
            encoding="utf-8"
        )
    )


def _packaged_gate(root: Path, edition: str) -> FeatureGate:
    install_embedded_feature_files(
        root,
        build_info={
            "edition": edition,
            "feature_profile": edition,
            "admin_unlock_enabled": False,
        },
        feature_flags=_profile(edition),
        session_full_flags=_profile("full"),
    )
    return FeatureGate(
        root=root,
        allow_local_override=False,
        packaged_runtime=True,
        runtime_path=root / "runtime",
    )


def _target() -> dict[str, object]:
    return {
        "target_id": "wps-target",
        "site_id": "demo",
        "business_key": "rail_transit.trackside_ap_business",
        "target_code": WPS_TARGET_CODE,
        "target_type": "WPS_STANDARD_SPREADSHEET",
        "target_name": "WPS 云文档",
        "document_open_url": "https://www.kdocs.cn/l/test-document",
        "webhook_url": "https://www.kdocs.cn/api/v3/ide/file/test/script/test/sync_task",
        "expected_document_id": "test",
        "enabled": True,
        "protocol_version": 1,
        "timeout_seconds": 30,
        "token_configured": True,
    }


class _WpsService:
    def list_targets(self, _site_id: str) -> list[dict[str, object]]:
        return []

    def configure_target(self, *_args, **_kwargs) -> dict[str, object]:
        return _target()

    def connection_test(self, _site_id: str, _target_code: str) -> dict[str, object]:
        return {"status": "CONNECTED"}


class _RailService:
    def start_trackside_ap_wps_sync(self, *_args, **_kwargs) -> dict[str, object]:
        return {
            "task_id": "wps-task",
            "status": "PENDING",
            "action": "trackside_ap_wps_sync",
        }


def _app(tmp_path: Path, edition: str) -> FastAPI:
    app_root = tmp_path / f"{edition}-backend"
    app_root.mkdir()
    app = FastAPI()
    app.include_router(wps_sync_router, prefix="/api")
    app.state.feature_gate = _packaged_gate(app_root, edition)
    app.state.paths = PathResolver(app_root, tmp_path / f"{edition}-data")
    app.state.trackside_ap_business_query_service = SimpleNamespace(
        current_site_id=lambda: "demo"
    )
    app.state.trackside_ap_wps_sync_service = _WpsService()
    app.state.rail_transit_web_application_service = _RailService()
    return app


def test_wps_is_a_formal_full_feature_and_customer_remains_closed() -> None:
    item = FEATURE_BY_ID[WPS_FEATURE_ID]
    full = _profile("full")
    customer = _profile("customer")

    assert item.parent_id == "module.trackside_ap"
    assert item.status is FeatureStatus.ENABLED
    assert item.default_client_package is True
    assert full["features"][WPS_FEATURE_ID] == {
        "visible": True,
        "enabled": True,
        "client_package": True,
        "internal_only": False,
    }
    assert customer["features"][WPS_FEATURE_ID] == {
        "visible": False,
        "enabled": False,
        "client_package": False,
        "internal_only": False,
    }
    assert validate_feature_profile_payload(full, profile="full") == []
    assert validate_feature_profile_payload(customer, profile="customer") == []


def test_runtime_self_check_enforces_the_full_only_wps_delivery_contract(
    tmp_path: Path,
) -> None:
    full_root = tmp_path / "full-backend"
    full_root.mkdir()
    full_gate = _packaged_gate(full_root, "full")
    full_service = RuntimeSelfCheckService(
        PathResolver(full_root, tmp_path / "full-data"),
        full_gate,
        "demo",
    )
    assert full_gate.edition == full_gate.profile == "full"
    assert full_gate.is_visible(WPS_FEATURE_ID)
    assert full_gate.is_enabled(WPS_FEATURE_ID)
    normal = full_service._feature_policy(True)
    assert normal.check_id == "production_feature_policy"
    assert normal.status == "normal"
    assert full_service._feature_policy(False).status == "warning"

    full_gate.features[WPS_FEATURE_ID] = {
        "visible": False,
        "enabled": False,
        "client_package": False,
        "internal_only": False,
    }
    assert full_service._feature_policy(True).status == "error"

    customer_root = tmp_path / "customer-backend"
    customer_root.mkdir()
    customer_gate = _packaged_gate(customer_root, "customer")
    customer_service = RuntimeSelfCheckService(
        PathResolver(customer_root, tmp_path / "customer-data"),
        customer_gate,
        "demo",
    )
    assert customer_gate.edition == customer_gate.profile == "customer"
    assert not customer_gate.is_visible(WPS_FEATURE_ID)
    assert not customer_gate.is_enabled(WPS_FEATURE_ID)
    assert customer_service._feature_policy(True).status == "normal"


def test_full_packaged_feature_gate_admits_wps_routes(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, "full")) as client:
        responses = (
            client.get("/api/rail-transit/trackside-ap-business/wps/targets"),
            client.put(
                f"/api/rail-transit/trackside-ap-business/wps/targets/{WPS_TARGET_CODE}",
                json={"enabled": True},
            ),
            client.post(
                f"/api/rail-transit/trackside-ap-business/wps/targets/{WPS_TARGET_CODE}/connection-test"
            ),
            client.post(
                "/api/rail-transit/trackside-ap-business/wps/sync",
                json={
                    "target_codes": [WPS_TARGET_CODE],
                    "expected_revision": "revision-1",
                },
            ),
        )

    assert [response.status_code for response in responses] == [200, 200, 200, 202]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    (
        ("GET", "/api/rail-transit/trackside-ap-business/wps/targets", None),
        (
            "PUT",
            f"/api/rail-transit/trackside-ap-business/wps/targets/{WPS_TARGET_CODE}",
            {"enabled": True},
        ),
        (
            "POST",
            f"/api/rail-transit/trackside-ap-business/wps/targets/{WPS_TARGET_CODE}/connection-test",
            None,
        ),
        (
            "POST",
            "/api/rail-transit/trackside-ap-business/wps/sync",
            {"target_codes": [WPS_TARGET_CODE], "expected_revision": "revision-1"},
        ),
    ),
)
def test_customer_packaged_feature_gate_rejects_wps_routes(
    tmp_path: Path,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    with TestClient(_app(tmp_path, "customer")) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "功能未启用"}
