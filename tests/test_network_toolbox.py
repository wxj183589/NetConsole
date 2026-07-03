from __future__ import annotations

import ipaddress
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from netconsole.core.feature_registry import FEATURE_BY_ID
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.network_tools.toolbox.fping_runner import discover_fping, parse_fping_json_line
from netconsole.services.network_tools.toolbox.ip_calc import (
    ipv4_calculate,
    plan_vlsm,
    split_subnets,
    summarize_routes,
    wildcard_calculate,
)
from netconsole.services.network_tools.toolbox.ping_tools import PingResult, _decode_output, _ping_args, parse_ping_output, run_single_ping, run_tcp_ping
from netconsole.services.network_tools.toolbox.route_tools import normalize_routes, parse_powershell_routes_json
from netconsole.services.windows_network_manager import NetworkAdapterInfo, RouteInfo
from netconsole.ui.pages.network_adapter_route_page import NetworkAdapterRoutePage
from netconsole.ui.pages.network_toolbox_page import IpStatusGridWidget, NetworkPingHostResult, NetworkToolboxPage, ToolResultPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_feature_registry_includes_network_toolbox() -> None:
    assert FEATURE_BY_ID["network_tools.toolbox"].parent_id == "module.network_tools"


def test_ipv4_calculate_normalizes_host_address_and_special_prefixes() -> None:
    result = ipv4_calculate("192.168.1.1/24")
    assert result["network"] == "192.168.1.0"
    assert result["broadcast"] == "192.168.1.255"
    assert result["wildcard"] == "0.0.0.255"

    assert "/31" in ipv4_calculate("192.0.2.0/31")["note"]
    assert "/32" in ipv4_calculate("192.0.2.1/32")["note"]


def test_wildcard_calculate_supports_default_values() -> None:
    result = wildcard_calculate("/24\n255.255.0.0\n192.168.0.0 255.255.0.0")

    assert result.errors == []
    assert result.rows[0]["wildcard"] == "0.0.0.255"
    assert result.rows[1]["wildcard"] == "0.0.255.255"
    assert result.rows[2]["wildcard"] == "0.0.255.255"


def test_vlsm_allocates_by_host_requirement_and_reports_capacity_error() -> None:
    result = plan_vlsm("192.168.1.0/24", "部门A,50\n部门B,30\n部门C,20\n部门D,10")

    assert result.errors == []
    assert [row["name"] for row in result.rows] == ["部门A", "部门B", "部门C", "部门D"]
    assert result.rows[0]["cidr"] == "192.168.1.0/26"
    assert result.rows[1]["cidr"] == "192.168.1.64/27"

    failed = plan_vlsm("192.168.1.0/30", "部门A,50")
    assert failed.errors
    assert failed.rows == []


def test_vlsm_accepts_chinese_comma_and_one_line_paste() -> None:
    chinese_comma = plan_vlsm("192.168.1.0/24", "部门A，50\n部门B，30")
    one_line = plan_vlsm("192.168.1.0/24", "部门A,50 部门B,30 部门C 20 部门D 10")

    assert chinese_comma.errors == []
    assert [row["name"] for row in chinese_comma.rows] == ["部门A", "部门B"]
    assert one_line.errors == []
    assert len(one_line.rows) == 4


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


def test_route_summary_collapses_default_networks() -> None:
    result = summarize_routes("192.168.0.0/24\n192.168.1.0/24\n192.168.2.0/24\n192.168.3.0/24")

    assert result.errors == []
    assert result.rows[0]["summary"] == "192.168.0.0/22"


def test_ping_args_support_source_ip(monkeypatch) -> None:
    monkeypatch.setattr("netconsole.services.network_tools.toolbox.ping_tools.sys.platform", "win32")
    assert _ping_args("192.0.2.1", count=1, size=32, timeout_ms=1000) == ["ping", "-n", "1", "-l", "32", "-w", "1000", "192.0.2.1"]
    assert _ping_args("192.0.2.1", count=1, size=32, timeout_ms=1000, source_ip="10.0.0.10")[:3] == ["ping", "-S", "10.0.0.10"]

    monkeypatch.setattr("netconsole.services.network_tools.toolbox.ping_tools.sys.platform", "linux")
    assert _ping_args("192.0.2.1", count=1, size=32, timeout_ms=1000, source_ip="10.0.0.10")[:3] == ["ping", "-I", "10.0.0.10"]


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
    assert rows[0].on_link is True
    assert rows[0].interface_alias == "Ethernet"
    assert rows[0].interface_ip == "10.0.0.5"
    assert rows[0].metric == 5


def test_local_route_rows_reuse_service_sorting_and_display_fields() -> None:
    routes = [
        RouteInfo("192.168.1.99/32", order_index=0, next_hop="192.168.1.1", interface_index=1, route_metric=20, source="NetMgmt"),
        RouteInfo("10.0.0.0/24", order_index=1, next_hop="192.168.1.1", interface_index=1, route_metric=10, policy_store="PersistentStore", persistent=True),
        RouteInfo("172.16.0.0/16", order_index=2, next_hop="0.0.0.0", interface_index=1, route_metric=5, source="Local"),
        RouteInfo("0.0.0.0/0", order_index=3, next_hop="192.168.1.254", interface_index=1, route_metric=1, source="Dhcp"),
    ]
    adapters = [NetworkAdapterInfo(name="Ethernet", interface_index=1, ipv4_addresses=["192.168.1.10/24"])]

    rows = normalize_routes(routes, adapters)

    assert [row.destination_prefix for row in rows] == ["0.0.0.0/0", "10.0.0.0/24", "192.168.1.99/32", "172.16.0.0/16"]
    assert rows[3].next_hop == "\u5728\u94fe\u8def\u4e0a"
    assert rows[1].policy_store == "PersistentStore"


def test_network_ping_adapter_mock_autofills_cidr(tmp_path) -> None:
    _app()

    class FakeManager:
        def list_adapters(self):
            return [NetworkAdapterInfo(name="Ethernet", interface_index=7, status="Up", ipv4_addresses=["10.10.20.5/24"])]

        def list_routes(self):
            return []

    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=FakeManager())
    page.network_adapter_combo.setCurrentIndex(1)

    assert page.network_ping_cidr.text() == "10.10.20.0/24"
    assert page._selected_source_ip() == "10.10.20.5"


def test_network_ping_tab_uses_page_scroll_area(tmp_path) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())

    scroll_areas = page.ping_tabs.widget(3).findChildren(QScrollArea)

    assert scroll_areas
    assert scroll_areas[0].widgetResizable() is True
    margins = scroll_areas[0].widget().layout().contentsMargins()
    assert margins.right() >= 24
    assert page.network_ping_grid.minimumHeight() >= 300
    assert page.network_ping_panel.result_table.minimumHeight() >= 320
    assert page.network_ping_detail_text.minimumHeight() >= 120
    assert page.network_adapter_combo.minimumHeight() >= 34
    assert page.network_ping_cidr.minimumHeight() >= 34
    for spin in (page.network_ping_timeout, page.network_ping_size, page.network_ping_threads):
        assert spin.minimumHeight() >= 34
        assert spin.minimumWidth() >= 136
    action_buttons = [button for button in page.ping_tabs.widget(3).findChildren(type(page.network_ping_panel.clear_button)) if button.objectName() == "networkPingActionButton"]
    assert action_buttons
    assert all(button.minimumHeight() >= 32 for button in action_buttons)


def test_toolbox_route_page_is_scrollable_and_uses_route_columns(tmp_path) -> None:
    _app()

    class FakeManager:
        def list_adapters(self):
            return [NetworkAdapterInfo(name="Ethernet", interface_index=1, ipv4_addresses=["192.168.1.10/24"])]

        def list_routes(self):
            return [RouteInfo("0.0.0.0/0", next_hop="192.168.1.1", interface_index=1, route_metric=1, policy_store="ActiveStore")]

    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=FakeManager())
    rows = page._route_rows_for_display()

    assert isinstance(page.tabs.widget(2), QScrollArea)
    assert list(rows[0]) == ["order_index", "destination_prefix", "next_hop", "interface_alias", "metric", "policy_store", "persistent", "source", "interface_index"]
    assert rows[0]["metric"] == 1


def test_local_adapter_config_page_does_not_expose_route_tab(tmp_path) -> None:
    _app()

    class FakeManager:
        pass

    page = NetworkAdapterRoutePage(I18n(), PathResolver(app_root=tmp_path, data_root=tmp_path), manager=FakeManager())

    assert page.tabs.count() == 1
    assert all(page.tabs.tabText(index) != "\u8def\u7531\u914d\u7f6e" for index in range(page.tabs.count()))


def test_tool_result_panel_state_is_not_shared(tmp_path) -> None:
    _app()
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    left = ToolResultPanel(paths, "demo", "left")
    right = ToolResultPanel(paths, "demo", "right")

    left.show_rows([{"target": "192.0.2.1", "status": "online"}], "left")
    right.show_rows([{"target": "192.0.2.2", "status": "offline"}], "right")

    assert left.current_rows != right.current_rows
    assert left.result_table.item(0, 0).text() == "192.0.2.1"
    assert right.result_table.item(0, 0).text() == "192.0.2.2"


def test_network_ping_grid_initializes_24_hosts(tmp_path) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())
    network = ipaddress.ip_network("192.168.10.0/24")
    targets = [str(host) for host in network.hosts()]

    page._init_network_ping_grid(network, targets)

    assert len(page.network_ping_grid.hosts) == 255
    assert sum(1 for item in page.network_ping_grid.hosts.values() if item.in_range) == 254
    assert page.network_ping_grid.hosts[1].status == "idle"
    assert page.network_ping_grid.hosts[255].status == "disabled"


def test_network_ping_grid_marks_out_of_range_hosts_disabled(tmp_path) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())
    network = ipaddress.ip_network("192.168.10.64/26")
    targets = [str(host) for host in network.hosts()]

    page._init_network_ping_grid(network, targets)

    assert page.network_ping_grid.hosts[63].status == "disabled"
    assert page.network_ping_grid.hosts[65].status == "idle"
    assert page.network_ping_grid.hosts[126].status == "idle"
    assert page.network_ping_grid.hosts[127].status == "disabled"


def test_network_ping_grid_updates_host_status(tmp_path) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())
    network = ipaddress.ip_network("192.168.10.0/24")
    page._init_network_ping_grid(network, ["192.168.10.10"])

    page._network_ping_progress({"target": "192.168.10.10", "status": "online", "latency_ms": 3, "timestamp": "2026-07-03 12:34:56"})

    assert page.current_network_ping_results["192.168.10.10"].status == "online"
    assert page.network_ping_grid.hosts[10].status == "online"


def test_ip_status_grid_click_emits_ip() -> None:
    app = _app()
    widget = IpStatusGridWidget()
    widget.resize(900, 260)
    widget.set_hosts([NetworkPingHostResult(ip=f"192.168.10.{host}", host_number=host, in_range=True, status="idle") for host in range(1, 256)])
    widget.show()
    app.processEvents()
    widget.repaint()
    app.processEvents()
    clicked: list[str] = []
    widget.hostClicked.connect(clicked.append)

    QTest.mouseClick(widget, Qt.LeftButton, pos=widget.rects[10].center())

    assert clicked == ["192.168.10.10"]


def test_network_ping_table_and_grid_share_result_state(tmp_path) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())
    network = ipaddress.ip_network("192.168.10.0/24")
    page._init_network_ping_grid(network, ["192.168.10.20"])
    row = {"target": "192.168.10.20", "status": "online", "latency_ms": 4}
    page._network_ping_progress(row)
    page.network_ping_panel.show_rows([row], "network_ping")

    page._network_grid_host_clicked("192.168.10.20")

    assert page.network_ping_grid.selected_ip == "192.168.10.20"
    assert page.network_ping_panel.result_table.currentRow() == 0


def test_ping_output_decode_uses_local_codepage_without_replacement() -> None:
    text = "请求超时。"
    decoded = _decode_output(text.encode("gbk"))

    assert decoded == text
    assert "\ufffd" not in decoded


def test_fping_discovery_prefers_environment_path(tmp_path, monkeypatch) -> None:
    exe = tmp_path / "fping.exe"
    exe.write_text("", encoding="utf-8")

    def fake_run(args, **_kwargs):
        if args[1] == "-v":
            return subprocess.CompletedProcess(args, 0, b"fping: Version 5.5", b"")
        return subprocess.CompletedProcess(args, 0, b"-J --json -S --src", b"")

    monkeypatch.setenv("NETCONSOLE_FPING_EXE", str(exe))
    monkeypatch.setattr("netconsole.services.network_tools.toolbox.fping_runner.subprocess.run", fake_run)

    result = discover_fping(tmp_path)

    assert result.available is True
    assert result.path == exe.resolve()
    assert result.supports_json is True


def test_fping_discovery_reports_unavailable(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NETCONSOLE_FPING_EXE", raising=False)
    result = discover_fping(tmp_path, env={})

    assert result.available is False
    assert "fping.exe" in result.error


def test_parse_fping_json_line_maps_statuses() -> None:
    online = parse_fping_json_line('{"summary":{"host":"10.0.0.1","xmt":1,"rcv":1,"loss":0,"rttMin":1.2,"rttAvg":1.2,"rttMax":1.2}}')
    timeout = parse_fping_json_line('{"timeout":{"host":"10.0.0.2","seq":0}}')
    unreachable = parse_fping_json_line('{"unreachable":{"host":"10.0.0.3","seq":0}}')

    assert online is not None and online.status == "online" and online.received == 1
    assert timeout is not None and timeout.status == "timeout"
    assert unreachable is not None and unreachable.status == "unreachable"
    assert parse_fping_json_line("not json") is None


def test_system_ping_unreachable_reply_from_other_ip_is_not_online() -> None:
    output = """
正在 Ping 10.0.0.146 具有 32 字节的数据:
来自 10.0.0.14 的回复: 无法访问目标主机。
"""
    parsed = parse_ping_output(output, target="10.0.0.146")
    result = run_single_ping("10.0.0.146", runner=lambda _args, _timeout: subprocess.CompletedProcess(_args, 0, output, ""))

    assert parsed.received == 0
    assert parsed.latency_ms is None
    assert result.status != "online"


def test_system_ping_english_unreachable_reply_from_other_ip_is_not_online() -> None:
    output = """
Pinging 10.0.0.146 with 32 bytes of data:
Reply from 10.0.0.14: Destination host unreachable.
"""
    result = run_single_ping("10.0.0.146", runner=lambda _args, _timeout: subprocess.CompletedProcess(_args, 0, output, ""))

    assert result.status != "online"
    assert result.received == 0


def test_network_ping_stats_counts_only_online_as_online(tmp_path) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())
    network = ipaddress.ip_network("192.168.10.0/24")
    page._init_network_ping_grid(network, ["192.168.10.1", "192.168.10.2", "192.168.10.3"])

    page._network_ping_progress({"target": "192.168.10.1", "status": "online", "latency_ms": 1})
    page._network_ping_progress({"target": "192.168.10.2", "status": "timeout"})
    page._network_ping_progress({"target": "192.168.10.3", "status": "unreachable"})

    text = page.network_ping_stats_label.text()
    assert "在线: 1" in text
    assert "离线: 2" in text


def test_fping_unavailable_falls_back_to_system_ping(tmp_path, monkeypatch) -> None:
    _app()
    page = NetworkToolboxPage(I18n(), "demo", PathResolver(app_root=tmp_path, data_root=tmp_path), network_manager=type("M", (), {"list_adapters": lambda self: [], "list_routes": lambda self: []})())
    monkeypatch.setattr("netconsole.ui.pages.network_toolbox_page.discover_fping", lambda _root: type("A", (), {"available": False, "error": "missing"})())
    monkeypatch.setattr("netconsole.ui.pages.network_toolbox_page.run_single_ping", lambda target, **_kwargs: PingResult(target=target, status="offline"))
    rows, engine = page._run_fping_or_system_batch(["192.0.2.1"], count=1, size=32, timeout_ms=100, concurrency=1, source_ip="")

    assert rows
    assert "系统 ping" in engine
