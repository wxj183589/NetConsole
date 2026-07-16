from __future__ import annotations

from pathlib import Path

from netconsole.backend.api.online_mr_control_router import router


def test_online_mr_control_routes_have_explicit_start_stop_force_stop_recover_and_get() -> None:
    routes = {(route.path, frozenset(route.methods or set())) for route in router.routes}
    assert routes == {
        ("/rail-transit/online-mr-control/status", frozenset({"GET"})),
        ("/rail-transit/online-mr-control/{operation_id}", frozenset({"GET"})),
        ("/rail-transit/online-mr-control/start", frozenset({"POST"})),
        ("/rail-transit/online-mr-control/{operation_id}/stop", frozenset({"POST"})),
        ("/rail-transit/online-mr-control/{operation_id}/force-stop", frozenset({"POST"})),
        ("/rail-transit/online-mr-control/recover", frozenset({"POST"})),
    }
    source = Path("src/netconsole/backend/api/online_mr_control_router.py").read_text(encoding="utf-8")
    for forbidden in ("retry", "agent-start", "agent-stop", "DELETE", "PUT", "command"):
        assert forbidden not in source


def test_control_service_does_not_own_workers_packaging_or_metadata() -> None:
    source = Path("src/netconsole/services/online_mr/web_control_service.py").read_text(encoding="utf-8")
    assert "OnlineMrApplicationService" in source
    assert ".start_local_collection(" in source
    assert ".stop_operation(" in source
    assert ".force_stop_operation(" in source
    assert ".recover_mappings(" in source
    for forbidden in (
        "OnlineMrTrafficCoordinator(",
        "FpingV5ProbeWorker(",
        "Iperf3Worker(",
        "session_meta.json",
        "CollectionPackager(",
        "Netmiko",
    ):
        assert forbidden not in source
