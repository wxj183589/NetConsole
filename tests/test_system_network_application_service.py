from __future__ import annotations

import socket
import sys

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.models.api.system_network import (
    LocalIpv4AddressDTO,
    SourceIpRecommendationRequestDTO,
    UdpPortCheckRequestDTO,
)
from netconsole.services.system_network_application_service import (
    SystemNetworkAddressProvider,
    SystemNetworkApplicationService,
    SystemNetworkError,
)


class _Provider:
    def __init__(self) -> None:
        self.rows = [
            _row("ethernet", "以太网 2", "10.8.0.4", metric=25),
            _row("ethernet", "以太网 2", "10.8.1.4", metric=25),
            _row("wifi", "WLAN", "192.168.1.20", metric=35),
            _row("wsl", "vEthernet (WSL)", "172.20.0.1", virtual=True),
            _row("loop", "Loopback", "127.0.0.1", loopback=True),
            _row("apipa", "断开网卡", "169.254.1.2", up=False, apipa=True),
        ]
        self.routes = {
            "10.122.6.249": "10.8.0.4",
            "10.122.6.250": "10.8.0.4",
            "192.168.1.1": "192.168.1.20",
        }

    def list_ipv4_addresses(self) -> list[LocalIpv4AddressDTO]:
        return self.rows

    def route_source_ip(self, target_ip: str) -> str:
        if target_ip not in self.routes:
            raise SystemNetworkError(
                "NETWORK_ROUTE_UNAVAILABLE",
                "无系统路由",
                status_code=409,
            )
        return self.routes[target_ip]


def _row(
    adapter_id: str,
    name: str,
    ipv4: str,
    *,
    metric: int = 100,
    virtual: bool = False,
    loopback: bool = False,
    up: bool = True,
    apipa: bool = False,
) -> LocalIpv4AddressDTO:
    return LocalIpv4AddressDTO(
        adapter_id=adapter_id,
        adapter_name=name,
        description=name,
        interface_index=1,
        ipv4=ipv4,
        prefix_length=24,
        netmask="255.255.255.0",
        gateway="10.8.0.1" if adapter_id == "ethernet" else "",
        is_up=up,
        is_loopback=loopback,
        is_virtual=virtual,
        is_apipa=apipa,
        has_default_route=adapter_id == "ethernet",
        route_metric=metric,
        source="test",
    )


def test_lists_every_ipv4_per_adapter_and_filters_unsafe_defaults() -> None:
    service = SystemNetworkApplicationService(_Provider())

    page = service.list_ipv4_addresses()

    assert [row.ipv4 for row in page.items] == [
        "10.8.0.4",
        "10.8.1.4",
        "192.168.1.20",
        "172.20.0.1",
    ]
    assert sum(row.adapter_id == "ethernet" for row in page.items) == 2
    assert next(row for row in page.items if row.ipv4 == "172.20.0.1").is_virtual
    expanded = service.list_ipv4_addresses(
        include_loopback=True,
        include_apipa=True,
        include_down=True,
    )
    assert {row.ipv4 for row in expanded.items} == {
        "10.8.0.4",
        "10.8.1.4",
        "192.168.1.20",
        "172.20.0.1",
        "127.0.0.1",
        "169.254.1.2",
    }


def test_route_recommendation_uses_system_selected_source_and_keeps_preferred() -> None:
    service = SystemNetworkApplicationService(_Provider())

    recommendation = service.recommend_source_ip(
        SourceIpRecommendationRequestDTO(
            target_ips=["10.122.6.249", "10.122.6.250", "192.168.1.1"],
            preferred_ip="10.8.0.4",
        )
    )

    assert recommendation.recommended_ip == "10.8.0.4"
    assert "2 个目标" in recommendation.recommendation_reason
    assert [row.source_ip for row in recommendation.routes] == [
        "10.8.0.4",
        "10.8.0.4",
        "192.168.1.20",
    ]
    assert next(
        row for row in recommendation.candidates if row.ipv4 == "10.8.0.4"
    ).recommended


def test_profile_address_validation_blocks_stale_unspecified_and_broadcast() -> None:
    service = SystemNetworkApplicationService(_Provider())
    service.validate_profile_addresses(
        udp_listen_host="0.0.0.0",
        syslog_server_ip="10.8.0.4",
        require_syslog=True,
        allow_external=False,
    )

    with pytest.raises(SystemNetworkError) as stale:
        service.validate_listen_host("10.8.0.99")
    assert stale.value.code == "UDP_LISTEN_HOST_NOT_LOCAL"

    with pytest.raises(SystemNetworkError) as unspecified:
        service.validate_syslog_server_ip(
            "0.0.0.0", required=True, allow_external=False
        )
    assert unspecified.value.code == "SYSLOG_TARGET_INVALID"

    with pytest.raises(SystemNetworkError) as broadcast:
        service.validate_syslog_server_ip(
            "10.8.0.255", required=True, allow_external=True
        )
    assert broadcast.value.code == "SYSLOG_TARGET_BROADCAST"

    with pytest.raises(SystemNetworkError) as external:
        service.validate_syslog_server_ip(
            "198.51.100.10", required=True, allow_external=False
        )
    assert external.value.code == "SYSLOG_TARGET_NOT_LOCAL"
    service.validate_syslog_server_ip(
        "198.51.100.10", required=True, allow_external=True
    )


def test_udp_port_check_reports_exclusive_occupancy() -> None:
    service = SystemNetworkApplicationService(_Provider())
    occupied = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    occupied.bind(("0.0.0.0", 0))
    port = int(occupied.getsockname()[1])
    try:
        result = service.check_udp_port(
            UdpPortCheckRequestDTO(listen_host="0.0.0.0", listen_port=port)
        )
    finally:
        occupied.close()
    assert result.available is False
    assert result.status == "IN_USE"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows IP Helper smoke")
def test_udp_port_inspection_is_read_only_and_reports_owner_table() -> None:
    service = SystemNetworkApplicationService(_Provider())
    occupied = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    occupied.bind(("0.0.0.0", 0))
    port = int(occupied.getsockname()[1])
    try:
        result = service.inspect_udp_port("0.0.0.0", port)
    finally:
        occupied.close()

    assert result.available is False
    assert result.status == "IN_USE"


def test_network_api_delegates_to_read_only_application_service(tmp_path) -> None:
    app = create_app(paths=PathResolver(tmp_path / "app", tmp_path / "data"))
    app.state.system_network_application_service = (
        SystemNetworkApplicationService(_Provider())
    )
    with TestClient(app) as client:
        listed = client.get("/api/system/network/ipv4-addresses")
        recommended = client.post(
            "/api/system/network/recommend-source-ip",
            json={"target_ips": ["10.122.6.249"], "preferred_ip": ""},
        )
    assert listed.status_code == 200
    assert listed.json()["total"] == 4
    assert recommended.status_code == 200
    assert recommended.json()["recommended_ip"] == "10.8.0.4"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows IP Helper smoke")
def test_windows_packaged_runtime_can_enumerate_with_ip_helper() -> None:
    rows = SystemNetworkAddressProvider().list_ipv4_addresses()

    assert rows
    assert all(row.source == "windows_ip_helper_api" for row in rows)
    assert all(row.adapter_id and row.adapter_name for row in rows)
