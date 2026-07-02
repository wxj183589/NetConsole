from __future__ import annotations

from types import SimpleNamespace

from netconsole.core.feature_registry import FEATURE_BY_ID
from netconsole.services.network_tools.toolbox.ip_calc import (
    ipv4_calculate,
    plan_vlsm,
    split_subnets,
    summarize_routes,
    wildcard_calculate,
)
from netconsole.services.network_tools.toolbox.ping_tools import parse_ping_output, run_tcp_ping
from netconsole.services.network_tools.toolbox.route_tools import parse_powershell_routes_json


def test_feature_registry_includes_network_toolbox() -> None:
    assert FEATURE_BY_ID["network_tools.toolbox"].parent_id == "module.network_tools"


def test_ipv4_calculate_normalizes_host_address_and_special_prefixes() -> None:
    result = ipv4_calculate("192.168.1.1/24")
    assert result["network"] == "192.168.1.0"
    assert result["broadcast"] == "192.168.1.255"
    assert result["wildcard"] == "0.0.0.255"

    assert "/31" in ipv4_calculate("192.0.2.0/31")["note"]
    assert "/32" in ipv4_calculate("192.0.2.1/32")["note"]


def test_wildcard_calculate_supports_prefix_and_netmask() -> None:
    result = wildcard_calculate("/24\n255.255.0.0")

    assert result.errors == []
    assert result.rows[0]["wildcard"] == "0.0.0.255"
    assert result.rows[1]["wildcard"] == "0.0.255.255"


def test_vlsm_allocates_by_host_requirement_and_reports_capacity_error() -> None:
    result = plan_vlsm("192.168.1.0/24", "部门A,50\n部门B,30\n部门C,20\n部门D,10")

    assert result.errors == []
    assert [row["name"] for row in result.rows] == ["部门A", "部门B", "部门C", "部门D"]
    assert result.rows[0]["cidr"] == "192.168.1.0/26"
    assert result.rows[1]["cidr"] == "192.168.1.64/27"

    failed = plan_vlsm("192.168.1.0/30", "部门A,50")
    assert failed.errors
    assert failed.rows == []


def test_subnet_split_returns_expected_page() -> None:
    result = split_subnets("192.168.0.0/22", 24, page_size=50)

    assert result.errors == []
    assert result.summary["total"] == 4
    assert [row["cidr"] for row in result.rows] == [
        "192.168.0.0/24",
        "192.168.1.0/24",
        "192.168.2.0/24",
        "192.168.3.0/24",
    ]


def test_route_summary_collapses_adjacent_networks() -> None:
    result = summarize_routes("192.168.0.0/24\n192.168.1.0/24\n192.168.2.0/24\n192.168.3.0/24")

    assert result.errors == []
    assert result.rows[0]["summary"] == "192.168.0.0/22"


def test_parse_ping_output_extracts_latency_and_loss() -> None:
    output = """
Pinging 192.0.2.1 with 32 bytes of data:
Reply from 192.0.2.1: bytes=32 time=3ms TTL=64

Ping statistics for 192.0.2.1:
    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 3ms, Maximum = 3ms, Average = 3ms
"""
    result = parse_ping_output(output, target="192.0.2.1")

    assert result.received == 1
    assert result.avg_ms == 3
    assert result.packet_loss_percent == 0


def test_tcp_ping_uses_mock_socket() -> None:
    class FakeSocket:
        def close(self) -> None:
            pass

    result = run_tcp_ping("localhost", 443, socket_factory=lambda _target, timeout: FakeSocket())

    assert result.status == "open"
    assert result.port == 443


def test_parse_powershell_route_json_maps_interface_fields() -> None:
    routes = '[{"DestinationPrefix":"10.0.0.0/24","NextHop":"0.0.0.0","InterfaceIndex":12,"RouteMetric":5,"PolicyStore":"ActiveStore","Protocol":"Local"}]'
    interfaces = '[{"InterfaceIndex":12,"InterfaceAlias":"Ethernet","IPAddress":"10.0.0.5"}]'
    rows = parse_powershell_routes_json(routes, interfaces)

    assert rows[0].destination == "10.0.0.0"
    assert rows[0].prefix_length == 24
    assert rows[0].netmask == "255.255.255.0"
    assert rows[0].next_hop == "在链路上"
    assert rows[0].interface_alias == "Ethernet"
    assert rows[0].interface_ip == "10.0.0.5"
    assert rows[0].metric == 5
