from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit import car_network_diagnostic as car_diag
from netconsole.services.rail_transit.car_network_diagnostic import (
    AcApStatus,
    CarNetworkDiagnosticService,
    CarNetworkGlobalConfigStore,
    CarNetworkNode,
    CarNetworkPointTableStore,
    PingResult,
    SshResult,
    apply_address_mapping,
    apply_global_rules_to_nodes,
    build_car_network_trains,
    build_ping_targets,
    default_point_table,
    discover_core_switches,
    evaluate_diagnostic,
    generate_point_table_from_devices,
    match_train_mr_in_mesh_links,
    merge_train_nodes,
    normalize_train_network_defaults,
    parse_ping_output,
    probe_ac_mesh_links,
    run_ac_commands,
)
from netconsole.services.vehicle_mr_online import (
    H3CComwareV9VehicleMrMeshLinkParser,
    VehicleMrOnlineStore,
    VehicleMrTrainState,
    build_train_states,
    parse_train_identity,
)
from netconsole.ui.pages.rail_transit_page import RailTransitPage
from netconsole.ui.pages.car_network_diagnostic_page import PointTableDialog
from netconsole.ui.pages import car_network_diagnostic_page as car_page


REAL_MESH_OUTPUT = """AP name: 30f5-2787-8080
Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
NBL12-LC06-MR-CW       74ad-cb9d-317f 30f5-2787-808f Forwarding 47   17/18
NBL12-LC06-MR-CW       74ad-cb9d-317f 30f5-2787-809f Forwarding 39   0/36

AP name: bc5a-3457-8cc0
Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
NBL12-LC06-MR-CT       74ad-cb9d-3321 bc5a-3457-8cdf Forwarding 35   49/104
NBL12-LC06-MR-CT       74ad-cb9d-3321 bc5a-3457-8ccf Forwarding 40   0/25
"""


def _ok_ping(nodes: list[CarNetworkNode]) -> dict[str, PingResult]:
    return {ip: PingResult(ip, True, 0, 1.0) for ip in build_ping_targets(nodes)}


def _cross_ok() -> dict[str, SshResult]:
    return {
        "TC1-MR": SshResult(
            "10.122.6.249",
            True,
            "TC1-MR",
            {
                "10.122.6.252": PingResult("10.122.6.252", True, 0),
                "10.122.6.2": PingResult("10.122.6.2", True, 0),
            },
        ),
        "TC2-MR": SshResult(
            "10.122.6.250",
            True,
            "TC2-MR",
            {
                "10.122.6.251": PingResult("10.122.6.251", True, 0),
                "10.122.6.1": PingResult("10.122.6.1", True, 0),
            },
        ),
    }


def _point_table_with_prefix(train_id: str = "LC06", train_no: str = "06", prefix: str = "10.122.6") -> list[CarNetworkNode]:
    return default_point_table(
        train_id,
        train_no,
        {
            "TC1-MR": Device(name=f"LC{train_no}-MR-CT", primary_address=f"{prefix}.249"),
            "TC2-MR": Device(name=f"LC{train_no}-MR-CW", primary_address=f"{prefix}.250"),
        },
    )


def test_default_nodes_use_mr_names_and_dynamic_targets() -> None:
    nodes = _point_table_with_prefix("LC17", "17", "10.66.17")

    assert [node.node_name for node in nodes] == ["TC1-MR", "TC1-SW", "TC1-SRV", "TC2-MR", "TC2-SW", "TC2-SRV"]
    assert "10.66.17.251" in build_ping_targets(nodes)
    assert "10.122.17.251" not in build_ping_targets(nodes)


def test_full_ok_outputs_mr_json_names() -> None:
    nodes = _point_table_with_prefix()
    result = evaluate_diagnostic(nodes, _ok_ping(nodes), _cross_ok(), AcApStatus(True, True, True, True))

    payload = result.to_json_dict()
    assert result.status == "ok"
    assert payload["nodes"]["TC1-MR"] == "ok"
    assert "TC1-AP" not in payload["nodes"]
    assert payload["vrrp"]["ip"] == "10.122.6.254"


def test_train_offline_requires_no_ac_no_ssh_and_all_configured_ping_failed() -> None:
    nodes = _point_table_with_prefix()
    ping = {ip: PingResult(ip, False, 100) for ip in build_ping_targets(nodes)}

    result = evaluate_diagnostic(nodes, ping, {}, AcApStatus(selected=True))

    assert result.status == "partial_fail"
    assert "不能直接判定车内网络故障" in result.conclusion


def test_vehicle_ping_loss_is_abnormal() -> None:
    nodes = _point_table_with_prefix()
    ping = _ok_ping(nodes)
    ping["10.122.6.1"] = PingResult("10.122.6.1", True, 25.0, 4.0)

    result = evaluate_diagnostic(nodes, ping, _cross_ok(), AcApStatus(True, True, True, True))

    assert result.status == "partial_fail"
    assert result.conclusion == "车内通信存在丢包"
    assert result.nodes["TC1-SRV"] == "unstable"


def test_mr_without_vehicle_ip_is_not_failed_when_management_ping_ok() -> None:
    nodes = [
        CarNetworkNode("LC06", "TC1-MR", "MR", ssh_host="10.122.89.106", train_no="06", tc="TC1", end="CT"),
        CarNetworkNode("LC06", "TC1-SW", "SW", ip_vehicle="10.122.6.251", train_no="06", tc="TC1", end="CT"),
    ]
    ping = _ok_ping(nodes)

    result = evaluate_diagnostic(nodes, ping, {}, AcApStatus(selected=False))

    assert result.nodes["TC1-MR"] == "ok"


def test_primary_address_role_all_maps_vehicle_uplink_and_ssh() -> None:
    node = CarNetworkNode(
        "LC06",
        "TC1-MR",
        "MR",
        train_no="06",
        tc="TC1",
        end="CT",
        primary_address="10.122.6.249",
        primary_address_role="all",
        backup_address_role="ignore",
        address_mapping_mode="custom",
    )

    mapped = apply_address_mapping(node)

    assert mapped.primary_address_role == "all"
    assert mapped.ip_vehicle == "10.122.6.249"
    assert mapped.ip_uplink == "10.122.6.249"
    assert mapped.ssh_host == "10.122.6.249"
    assert mapped.ping_ips == ("10.122.6.249",)


def test_global_primary_address_role_all_maps_device_addresses() -> None:
    node = CarNetworkNode(
        "LC06",
        "TC1-SW",
        "SW",
        train_no="06",
        tc="TC1",
        end="CT",
        primary_address="10.122.6.251",
        address_mapping_mode="global",
    )
    config = {"address_mapping": {"3SW": {"primary_address_role": "all", "backup_address_role": "ignore", "ssh_source": "primary_address"}}}

    mapped = apply_address_mapping(node, config, overwrite=True)

    assert mapped.primary_address_role == "all"
    assert mapped.ip_vehicle == "10.122.6.251"
    assert mapped.ip_uplink == "10.122.6.251"
    assert mapped.ssh_host == "10.122.6.251"


def test_primary_all_allows_backup_role_to_override_target_field() -> None:
    node = CarNetworkNode(
        "LC06",
        "TC1-MR",
        "MR",
        train_no="06",
        tc="TC1",
        end="CT",
        primary_address="10.122.6.249",
        backup_address="10.122.89.106",
        primary_address_role="all",
        backup_address_role="uplink_ip",
        address_mapping_mode="custom",
    )

    mapped = apply_address_mapping(node)

    assert mapped.ip_vehicle == "10.122.6.249"
    assert mapped.ip_uplink == "10.122.89.106"
    assert mapped.ssh_host == "10.122.6.249"


def test_address_role_all_import_aliases_normalize_to_internal_value() -> None:
    rows = [
        {"train_id": "LC06", "node_name": "TC1-MR", "node_type": "MR", "primary_address_role": "全部", "address_mapping_mode": "custom"},
        {"train_id": "LC06", "node_name": "TC1-SW", "node_type": "SW", "primary_address_role": "ALL", "address_mapping_mode": "custom"},
        {"train_id": "LC06", "node_name": "TC1-SRV", "node_type": "Server", "primary_address_role": "all_addresses", "address_mapping_mode": "custom"},
    ]

    nodes = [car_diag.node_from_mapping(row) for row in rows]

    assert [node.primary_address_role for node in nodes] == ["all", "all", "all"]


def test_ssh_connected_even_when_remote_ping_fails() -> None:
    nodes = _point_table_with_prefix()
    mr_device = Device(name="列车06-MR-CT", primary_address="10.122.6.249", ssh_username="admin", ssh_password="pwd")
    service = CarNetworkDiagnosticService(
        nodes,
        mr_devices={"TC1-MR": mr_device},
        ssh_command_func=lambda _host, _command: "Request timed out.\n100% loss",
    )

    result = service._check_ssh_from_mr(next(node for node in nodes if node.node_name == "TC1-MR"))

    assert result.ok is True
    assert result.command_results
    assert all(not ping.ok for ping in result.command_results.values())


def test_cross_ping_failure_after_ssh_success_reports_cross_link_abnormal() -> None:
    nodes = _point_table_with_prefix()
    ping = _ok_ping(nodes)
    ssh = {
        "TC1-MR": SshResult(
            "10.122.6.249",
            True,
            "TC1-MR",
            {
                "10.122.6.251": PingResult("10.122.6.251", True, 0),
                "10.122.6.1": PingResult("10.122.6.1", True, 0),
                "10.122.6.252": PingResult("10.122.6.252", False, 100),
                "10.122.6.2": PingResult("10.122.6.2", False, 100),
            },
        ),
        "TC2-MR": SshResult(
            "10.122.6.250",
            True,
            "TC2-MR",
            {
                "10.122.6.252": PingResult("10.122.6.252", True, 0),
                "10.122.6.2": PingResult("10.122.6.2", True, 0),
                "10.122.6.251": PingResult("10.122.6.251", False, 100),
                "10.122.6.1": PingResult("10.122.6.1", False, 100),
            },
        ),
    }

    result = evaluate_diagnostic(nodes, ping, ssh, AcApStatus(True, True, True, True))
    payload = result.to_json_dict()

    assert result.conclusion == "跨TC链路 / VRRP / 中间骨干链路异常"
    assert result.cross_train == {"TC1->TC2": "fail", "TC2->TC1": "fail"}
    assert payload["ssh_status"]["TC1-MR"]["connected"] is True
    assert payload["ssh_status"]["TC1-MR"]["remote_ping_ok_count"] == 2
    assert any(row["layer"] == "MR远程跨TC快速检测" and row["status"] == "不通" for row in result.tables["TC1"])


def test_single_entry_tc2_ping_tc1_mr_marks_tc1_ok() -> None:
    nodes = _point_table_with_prefix()
    ssh = {
        "TC1-MR": SshResult("10.122.6.249", False, "TC1-MR", error="ssh failed"),
        "TC2-MR": SshResult(
            "10.122.6.250",
            True,
            "TC2-MR",
            {"10.122.6.249": PingResult("10.122.6.249", True, 0, 1.0)},
        ),
    }

    result = evaluate_diagnostic(nodes, {}, ssh, AcApStatus(selected=False))
    payload = result.to_json_dict()

    assert result.nodes["TC1-MR"] == "ok"
    assert result.status == "ok"
    assert result.conclusion == "车内通信正常（单端激活）"
    assert payload["vehicle_internal_status"]["validation_mode"] == "single_entry"
    assert payload["vehicle_internal_status"]["single_entry_verified"] is True


def test_single_entry_tc1_ping_tc2_mr_marks_tc2_ok() -> None:
    nodes = _point_table_with_prefix()
    ssh = {
        "TC1-MR": SshResult(
            "10.122.6.249",
            True,
            "TC1-MR",
            {"10.122.6.250": PingResult("10.122.6.250", True, 0, 1.0)},
        ),
        "TC2-MR": SshResult("10.122.6.250", False, "TC2-MR", error="ssh failed"),
    }

    result = evaluate_diagnostic(nodes, {}, ssh, AcApStatus(selected=False))

    assert result.nodes["TC2-MR"] == "ok"
    assert result.status == "ok"
    assert result.conclusion == "车内通信正常（单端激活）"


def test_single_entry_peer_mr_ping_loss_warns() -> None:
    nodes = _point_table_with_prefix()
    ssh = {
        "TC1-MR": SshResult(
            "10.122.6.249",
            True,
            "TC1-MR",
            {"10.122.6.250": PingResult("10.122.6.250", True, 2.0, 1.0)},
        ),
        "TC2-MR": SshResult("10.122.6.250", False, "TC2-MR", error="ssh failed"),
    }

    result = evaluate_diagnostic(nodes, {}, ssh, AcApStatus(selected=True))

    assert result.nodes["TC2-MR"] == "unstable"
    assert result.status == "partial_fail"
    assert result.conclusion == "车内通信存在丢包"


def test_mr_remote_ping_uses_quick_detect_commands() -> None:
    nodes = _point_table_with_prefix()
    mr_device = Device(name="列车06-MR-CT", primary_address="10.122.6.249", ssh_username="admin", ssh_password="pwd")
    commands: list[str] = []
    service = CarNetworkDiagnosticService(
        nodes,
        mr_devices={"TC1-MR": mr_device},
        ssh_command_func=lambda _host, command: commands.append(command) or "5 packet(s) transmitted, 5 packet(s) received, 0.0% packet loss\nround-trip min/avg/max/std-dev = 0.413/0.714/0.975/0.180 ms",
    )

    result = service._check_ssh_from_mr(next(node for node in nodes if node.node_name == "TC1-MR"))

    assert result.ok is True
    assert "ping -c 4 10.122.6.251" in commands
    assert "ping -c 4 10.122.6.1" in commands
    assert "ping -c 4 10.122.6.252" in commands
    assert "ping -c 4 10.122.6.2" in commands
    assert "ping -c 50 10.122.6.252" not in commands
    assert car_diag.CAR_NETWORK_QUICK_DETECT_SECONDS == 4
    assert car_diag.CAR_NETWORK_QUICK_PING_COUNT == 4
    assert car_diag.CAR_NETWORK_QUICK_PING_TIMEOUT == 4
    assert car_diag._h3c_ping_read_timeout("ping -c 4 10.122.7.250", 4) >= 8
    assert car_diag._h3c_ping_read_timeout("ping -c 50 10.122.7.250", 8) >= 60


def test_cross_tc_ping_skipped_when_no_mr_login() -> None:
    nodes = _point_table_with_prefix()
    result = evaluate_diagnostic(
        nodes,
        {},
        {
            "TC1-MR": SshResult("10.122.6.249", False, "TC1-MR", error="ssh failed"),
            "TC2-MR": SshResult("10.122.6.250", False, "TC2-MR", error="ssh failed"),
        },
        AcApStatus(selected=True),
    )

    assert result.cross_tc_ping["status"] == "skipped"
    assert result.to_json_dict()["cross_tc_ping"]["status"] == "skipped"


def test_cross_tc_ping_ui_status_color_mapping() -> None:
    assert "#22C55E" in car_page._cross_tc_ping_style("ok")
    assert "#FACC15" in car_page._cross_tc_ping_style("loss")
    assert "#EF4444" in car_page._cross_tc_ping_style("fail")
    assert "#64748B" in car_page._cross_tc_ping_style("skipped")
    assert car_page._cross_tc_ping_label({"status": "loss", "loss_percent": 2.0}) == "跨TC通信：丢包 2.0%"


def test_cross_tc_ping_prefers_direction_with_peer_mr_reachable() -> None:
    nodes = _point_table_with_prefix("LC07", "07", "10.122.7")
    ssh = {
        "TC1-MR": SshResult(
            "10.122.7.249",
            True,
            "TC1-MR",
            {
                "10.122.7.250": PingResult("10.122.7.250", False, 100.0),
                "10.122.7.252": PingResult("10.122.7.252", True, 0.0, 1.2),
                "10.122.7.2": PingResult("10.122.7.2", True, 0.0, 0.8),
            },
        ),
        "TC2-MR": SshResult(
            "10.122.7.250",
            True,
            "TC2-MR",
            {
                "10.122.7.249": PingResult("10.122.7.249", True, 0.0, 0.9),
                "10.122.7.251": PingResult("10.122.7.251", True, 0.0, 1.2),
                "10.122.7.1": PingResult("10.122.7.1", True, 0.0, 0.7),
            },
        ),
    }

    result = evaluate_diagnostic(nodes, {}, ssh, AcApStatus(selected=False))

    assert result.cross_train == {"TC1->TC2": "ok", "TC2->TC1": "ok"}
    assert result.cross_tc_ping["status"] == "ok"
    assert result.cross_tc_ping["source"] == "TC2-MR"
    assert result.cross_tc_ping["target"] == "TC1-MR"
    assert result.conclusion == "车内通信正常（双端验证）"


def test_service_does_not_use_local_ping_for_main_diagnosis() -> None:
    nodes = _point_table_with_prefix()
    uplinks = {"TC1-MR": "10.122.89.106", "TC1-SW": "10.122.89.6", "TC2-MR": "10.122.90.106", "TC2-SW": "10.122.90.6"}
    nodes = [CarNetworkNode(**{**node.__dict__, "ip_uplink": uplinks.get(node.node_name, node.ip_uplink)}) for node in nodes]
    mr_devices = {
        "TC1-MR": Device(name="列车06-MR-CT", primary_address="10.122.6.249", ssh_username="admin", ssh_password="pwd"),
        "TC2-MR": Device(name="列车06-MR-CW", primary_address="10.122.6.250", ssh_username="admin", ssh_password="pwd"),
    }
    commands: list[str] = []
    service = CarNetworkDiagnosticService(
        nodes,
        mr_devices=mr_devices,
        core_devices=[Device(name="COCC核心交换机", primary_address="10.1.1.1", device_type="Switch")],
        ac_command_func=lambda command: "列车06-MR-CT\n列车06-MR-CW",
        ping_func=lambda ip: (_ for _ in ()).throw(AssertionError(f"local ping must not run: {ip}")),
        ssh_command_func=lambda _host, command: commands.append(command) or "5 packet(s) transmitted, 5 packet(s) received, 0.0% packet loss\nround-trip min/avg/max/std-dev = 0.413/0.714/0.975/0.180 ms",
        core_command_func=lambda _device, _ip: "5 packet(s) transmitted, 0 packet(s) received, 100.0% packet loss",
    )

    result = service.run()

    assert result.status == "ok"
    assert "车内通信正常" in result.conclusion
    assert all(" -n " not in command and " -w " not in command for command in commands)
    assert "ping -c 4 10.122.6.252" in commands
    assert any(command.startswith("ping -c 50 ") for command in commands)
    assert result.to_json_dict()["ground_access_status"]["uplink_ip_reachable_from_core"] == "fail"


def test_parse_ping_output_supports_h3c_packet_loss_and_min_avg_max() -> None:
    output = """PING 10.122.6.251: 56  data bytes, press CTRL_C to break
Reply from 10.122.6.251: bytes=56 Sequence=1 ttl=255 time=2 ms

--- 10.122.6.251 ping statistics ---
4 packet(s) transmitted
4 packet(s) received
0.00% packet loss
round-trip min/avg/max = 1/2/5 ms
"""

    result = parse_ping_output("10.122.6.251", output)

    assert result.ok is True
    assert result.loss_percent == 0.0
    assert result.avg_rtt_ms == 2.0


def test_h3c_ping_channel_reader_collects_until_packet_loss() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.command = ""
            self.outputs = [
                "PING 10.122.7.250: 56 data bytes, press CTRL_C to break\n",
                "56 bytes from 10.122.7.250: icmp_seq=0 ttl=255 time=1.094 ms\n",
                "--- Ping statistics for 10.122.7.250 ---\n4 packet(s) transmitted, 4 packet(s) received, 0.0% packet loss\nround-trip min/avg/max/std-dev = 0.508/0.856/1.249/0.273 ms\n",
            ]

        def clear_buffer(self) -> None:
            pass

        def write_channel(self, command: str) -> None:
            self.command = command

        def read_channel(self) -> str:
            return self.outputs.pop(0) if self.outputs else ""

    conn = FakeConnection()

    output = car_diag._send_h3c_ping_command(conn, "ping -c 4 10.122.7.250", "gb2312", 8)
    result = parse_ping_output("10.122.7.250", output)

    assert conn.command == "ping -c 4 10.122.7.250\n"
    assert result.ok is True
    assert result.loss_percent == 0.0


def test_old_point_table_ap_names_are_imported_as_mr(tmp_path: Path) -> None:
    store = CarNetworkPointTableStore(PathResolver(tmp_path), "demo")
    path = tmp_path / "points.xlsx"

    store.export_file(path, [CarNetworkNode("LC06", "TC1-AP", "AP", ip_vehicle="", ip_uplink="10.122.6.249")])
    store.import_file(path)

    loaded = store.load()
    assert loaded[0].node_name == "TC1-MR"
    assert loaded[0].node_type == "MR"


def test_ac_online_matches_mr_device_name() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    nodes = [
        node if node.node_name != "TC1-MR" else CarNetworkNode(**{**node.__dict__, "device_name": "列车06-MR-CT"})
        for node in nodes
    ]
    service = CarNetworkDiagnosticService(
        nodes,
        ac_command_func=lambda command: REAL_MESH_OUTPUT if command != "display wlan ap all radio" else "radio normal",
        ping_func=lambda ip: PingResult(ip, False, 100),
    )

    status = service._check_ac()

    assert status.mesh_link is True
    assert status.ap_all is True
    assert status.online is True


def test_run_ac_commands_ignores_screen_length_failure_and_collects_mesh(monkeypatch) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def send_command_timing(self, command: str, **_kwargs) -> str:
            self.commands.append(command)
            if command == "screen-length disable":
                raise RuntimeError("Pattern not detected: 'screen\\\\-length\\\\ dis'")
            if command == "display wlan mesh-link ap":
                return REAL_MESH_OUTPUT
            return ""

        def disconnect(self) -> None:
            pass

    fake = FakeConnection()
    monkeypatch.setattr(car_diag, "ConnectHandler", lambda **_target: fake)

    output = run_ac_commands(
        Device(name="AC", primary_address="10.122.100.10", ssh_username="admin", ssh_password="pwd"),
        ("display wlan mesh-link ap",),
    )

    assert "NBL12-LC06-MR-CT" in output["display wlan mesh-link ap"]
    assert fake.commands[:2] == ["screen-length disable", "display wlan mesh-link ap"]


def test_ac_query_failure_is_unknown_not_both_offline() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    probe = probe_ac_mesh_links([], command_func=lambda _command: (_ for _ in ()).throw(RuntimeError("display failed")))

    status = match_train_mr_in_mesh_links(None, nodes, probe)

    assert status.any_query_success is False
    assert status.both_mr_offline is False
    assert status.parse_warning is True
    assert status.online_source == "ac_query_failed"


def test_ac_success_both_mr_offline_skips_ping_and_ssh() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    called: list[str] = []
    output = """AP name: ap1
Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
NBL12-LC16-MR-CT       74ad-cb9d-3321 bc5a-3457-689f Forwarding 35   1/2
"""
    service = CarNetworkDiagnosticService(
        nodes,
        ac_command_func=lambda command: output,
        ping_func=lambda ip: called.append(ip) or PingResult(ip, True, 0),
    )

    result = service.run()

    assert result.status == "offline"
    assert result.conclusion.startswith("AC mesh-link")
    assert called == []
    assert result.nodes["TC1-SW"] == "skipped"
    assert result.to_json_dict()["ac_probe"]["both_mr_offline"] is True


def test_h3c_mesh_peer_name_matches_single_end_without_offline() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    output = """AP name: bc5a-3457-6880
Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
NBL12-LC06-MR-CT       74ad-cb9d-3321 bc5a-3457-689f Forwarding 35   1/2
"""
    called: list[str] = []
    service = CarNetworkDiagnosticService(
        nodes,
        ac_command_func=lambda command: output,
        ping_func=lambda ip: called.append(ip) or PingResult(ip, True, 0, 1.0),
    )

    result = service.run()

    assert result.status != "offline"
    assert result.train_ac_status is not None
    assert result.train_ac_status.tc1_mr_online is True
    assert result.train_ac_status.tc2_mr_online is False
    assert result.train_ac_status.both_mr_offline is False
    assert called == []
    matched = result.to_json_dict()["ac_probe"]["matched_mrs"]
    assert matched[0]["peer_name"] == "NBL12-LC06-MR-CT"
    assert matched[0]["node"] == "TC1-MR"
    assert matched[0]["match_mode"] == "train_no_end"
    assert matched[0]["source"] == "ac_realtime_parser"


def test_ac_mesh_link_matches_ap_cw_peer_for_current_train() -> None:
    nodes = [
        CarNetworkNode("LC14", "TC1-MR", "MR", train_no="14", tc="TC1", end="CT"),
        CarNetworkNode("LC14", "TC2-MR", "MR", train_no="14", tc="TC2", end="CW"),
    ]
    output = """AP name: AP-TCC-15
 Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
 Nbl06-LC14-AP-CW       eccd-4c04-b30f 30f5-277a-4e1f Forwarding 43   448470/1852345
"""

    status = match_train_mr_in_mesh_links(None, nodes, car_diag.AcProbeResult(True, True, [car_diag.AcControllerProbe("", "AC", "", True, output)]))

    assert status.tc1_mr_online is False
    assert status.tc2_mr_online is True
    assert status.both_mr_offline is False
    assert status.matched_details["TC2-MR"][0]["peer_name"] == "Nbl06-LC14-AP-CW"


def test_generate_point_table_infers_non_default_vehicle_subnet_without_line_hardcode(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    mr_group = groups.create("车载-MR")
    sw_group = groups.create("车载-3SW")
    repository.create(Device(name="Nbl06-LC14-AP-CT", group_id=mr_group.id, device_type="Cloud-AP", primary_address="172.20.14.249"))
    repository.create(Device(name="Nbl06-LC14-TC1-SW", group_id=sw_group.id, device_type="Switch", primary_address="172.20.14.251"))

    nodes = generate_point_table_from_devices(repository, "demo", [])

    by_name = {node.node_name: node for node in nodes}
    assert {node.train_id for node in nodes} == {"Nbl06-LC14"}
    assert by_name["TC1-SRV"].ip_vehicle == "172.20.14.1"
    assert by_name["TC2-SRV"].ip_vehicle == "172.20.14.2"
    assert all("10.122" not in node.ip_vehicle for node in nodes)


def test_default_point_table_leaves_server_ips_blank_when_prefix_unknown() -> None:
    nodes = default_point_table("LC14", "14")

    assert next(node for node in nodes if node.node_name == "TC1-SRV").ip_vehicle == ""
    assert next(node for node in nodes if node.node_name == "TC2-SRV").ip_vehicle == ""
    assert all("10.122" not in node.ip_vehicle for node in nodes)


def test_real_h3c_mesh_output_matches_both_mr_ends() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    service = CarNetworkDiagnosticService(nodes, ac_command_func=lambda command: REAL_MESH_OUTPUT, ping_func=lambda ip: PingResult(ip, True, 0, 1.0))

    result = service.run()
    payload = result.to_json_dict()

    assert result.status != "offline"
    assert result.train_ac_status is not None
    assert result.train_ac_status.tc1_mr_online is True
    assert result.train_ac_status.tc2_mr_online is True
    assert result.train_ac_status.both_mr_offline is False
    matched_names = {item["peer_name"] for item in payload["ac_probe"]["matched_mrs"]}
    assert "NBL12-LC06-MR-CT" in matched_names
    assert "NBL12-LC06-MR-CW" in matched_names
    assert payload["ac_probe"]["controllers"][0]["output_length"] > 0
    assert payload["ac_probe"]["controllers"][0]["parsed_peer_count"] >= 4
    assert payload["ac_probe"]["online_source"] == "ac_realtime_parser"
    assert payload["ac_probe"]["parser"] == "H3CComwareV9VehicleMrMeshLinkParser"


def test_suspected_current_train_raw_line_does_not_skip_deep_probe() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    output = "NBL12-LC06-MR-CT malformed-mac still-has Forwarding signal\nNBL12-LC06-MR-CW malformed Forwarding\n"
    service = CarNetworkDiagnosticService(nodes, ac_command_func=lambda command: output, ping_func=lambda ip: PingResult(ip, True, 0, 1.0))

    result = service.run()

    assert result.status != "offline"
    assert result.train_ac_status is not None
    assert result.train_ac_status.tc1_mr_online is False
    assert result.train_ac_status.tc2_mr_online is False
    assert result.train_ac_status.parse_warning is True
    assert result.train_ac_status.suspected_current_train_lines


def test_h3c_mesh_peer_name_does_not_match_other_train() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    output = """AP name: ap1
Peer Name              Peer Mac       Local Mac      Status     RSSI Packets(Rx/Tx)
NBL12-LC16-MR-CT       74ad-cb9d-3321 bc5a-3457-689f Forwarding 35   1/2
"""
    service = CarNetworkDiagnosticService(nodes, ac_command_func=lambda command: output, ping_func=lambda ip: PingResult(ip, True, 0, 1.0))

    result = service.run()

    assert result.status == "offline"
    assert result.train_ac_status is not None
    assert result.train_ac_status.tc1_mr_online is False


def test_vehicle_mr_parser_and_identity_extraction() -> None:
    parse_result = H3CComwareV9VehicleMrMeshLinkParser().parse(REAL_MESH_OUTPUT)
    ct = parse_train_identity("NBL12-LC06-MR-CT")
    cw = parse_train_identity("NBL12-LC06-MR-CW")

    assert len(parse_result.links) >= 4
    assert ct is not None
    assert cw is not None
    assert ct.train_no == "06"
    assert ct.car_end == "CT"
    assert cw.car_end == "CW"


def test_car_network_uses_vehicle_mr_online_current_state(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    store = VehicleMrOnlineStore(paths, "demo")
    parse_result = H3CComwareV9VehicleMrMeshLinkParser().parse(REAL_MESH_OUTPUT)
    trains = build_train_states(
        {"NBL12-LC06": VehicleMrTrainState("NBL12-LC06", "06", True)},
        parse_result,
    )
    session_id = store.create_session(Device(name="AC"), 10)
    store.persist_snapshot(session_id, 1, parse_result, trains, {}, 1)
    nodes = default_point_table("NBL12-LC06", "06")
    service = CarNetworkDiagnosticService(
        nodes,
        paths=paths,
        site_name="demo",
        ac_command_func=lambda command: (_ for _ in ()).throw(RuntimeError("should not query AC")),
        ping_func=lambda ip: PingResult(ip, True, 0, 1.0),
    )

    result = service.run()
    payload = result.to_json_dict()

    assert result.status != "offline"
    assert result.train_ac_status is not None
    assert result.train_ac_status.tc1_mr_online is True
    assert result.train_ac_status.tc2_mr_online is True
    assert payload["ac_probe"]["online_source"] == "vehicle_mr_online_current_state"
    assert payload["ac_probe"]["tc1_mr_online"] is True
    assert payload["ac_probe"]["tc2_mr_online"] is True


def test_ac_query_failure_does_not_skip_ping() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    called: list[str] = []
    service = CarNetworkDiagnosticService(
        nodes,
        ac_command_func=lambda command: (_ for _ in ()).throw(RuntimeError("AC failed")),
        ping_func=lambda ip: called.append(ip) or PingResult(ip, True, 0, 1.0),
    )

    result = service.run()

    assert result.status != "offline"
    assert called == []


def test_build_trains_from_vehicle_group_mr_devices(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载-MR")
    repository.create(Device(name="列车06-MR-CT", group_id=group.id, device_type="FAT-AP", primary_address="10.122.89.106"))
    repository.create(Device(name="列车06-MR-CW", group_id=group.id, device_type="FAT-AP", primary_address="10.122.90.106"))

    trains = build_car_network_trains(repository, "demo")
    nodes = merge_train_nodes([], trains[0])

    assert trains[0].display_name == "06车"
    assert trains[0].tc1_device is not None
    assert trains[0].tc2_device is not None
    mr = next(node for node in nodes if node.node_name == "TC1-MR")
    assert mr.ip_vehicle == "10.122.89.106"
    assert mr.ssh_host == "10.122.89.106"


def test_generate_point_table_reads_vehicle_groups_and_preserves_manual_mapping(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    mr_group = groups.create("车载-MR")
    sw_group = groups.create("车载-3SW")
    srv_group = groups.create("车载-服务器")
    mr = repository.create(Device(name="列车06-MR-CT", group_id=mr_group.id, device_type="Cloud-AP", primary_address="10.122.6.249", backup_address="10.122.89.106"))
    sw = repository.create(Device(name="LC06-TC1-SW", group_id=sw_group.id, device_type="Switch", primary_address="10.122.6.251", backup_address="10.122.89.6"))
    repository.create(Device(name="LC06-TC1-Server", group_id=srv_group.id, device_type="Other", primary_address="10.122.6.1"))
    old = CarNetworkNode(
        train_id="NBL12-LC06",
        train_no="06",
        node_name="TC1-MR",
        node_type="MR",
        device_id=str(mr.id),
        ip_vehicle="10.122.6.249",
        ip_uplink="10.122.89.200",
        ssh_host="10.122.6.249",
        primary_address_role="vehicle_ip",
        backup_address_role="uplink_ip",
        address_mapping_mode="manual",
    )

    nodes = generate_point_table_from_devices(repository, "demo", [old])

    mr_node = next(node for node in nodes if node.node_name == "TC1-MR")
    sw_node = next(node for node in nodes if node.node_name == "TC1-SW")
    srv_node = next(node for node in nodes if node.node_name == "TC1-SRV")
    assert mr_node.ip_uplink == "10.122.89.200"
    assert sw_node.device_id == str(sw.id)
    assert sw_node.ip_vehicle == "10.122.6.251"
    assert sw_node.ip_uplink == "10.122.89.6"
    assert srv_node.ip_vehicle == "10.122.6.1"


def test_core_switch_auxiliary_result_is_reported() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    nodes = [node if node.node_name != "TC1-MR" else CarNetworkNode(**{**node.__dict__, "ip_uplink": "10.122.89.106"}) for node in nodes]
    core = Device(name="COCC核心交换机", primary_address="10.1.1.1", device_type="Switch")
    service = CarNetworkDiagnosticService(
        nodes,
        core_devices=[core],
        ac_command_func=lambda command: "列车06-MR-CT\n列车06-MR-CW",
        ping_func=lambda ip: PingResult(ip, False, 100) if ip == "10.122.89.106" else PingResult(ip, True, 0, 1.0),
        core_command_func=lambda _device, ip: f"Reply from {ip}: bytes=32 time=1ms TTL=255\n0% loss",
    )

    result = service.run()

    assert any(row["layer"] == "核心侧落地IP检测" and row["status"] == "OK" for row in result.tables["TC1"])


def test_core_auxiliary_is_silent_when_no_core_device_selected() -> None:
    nodes = default_point_table("NBL12-LC06", "06")
    nodes = [
        node if node.node_name != "TC1-MR" else CarNetworkNode(**{**node.__dict__, "ip_uplink": "10.122.89.106"})
        for node in nodes
    ]

    result = evaluate_diagnostic(nodes, _ok_ping(nodes), {}, AcApStatus())

    rows = [row for rows in result.tables.values() for row in rows]
    core_rows = [row for row in rows if row["layer"] == "核心侧落地IP检测"]
    assert not any(row["status"] == "跳过" for row in core_rows)
    assert all("未配置" not in str(row["note"]) for row in core_rows)


def test_cocc_core_switch_discovery_selects_core_and_excludes_ac(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    cocc = groups.create("COCC")
    repository.create(Device(name="无线控制器", system_name="WX-AC", group_id=cocc.id, device_type="AC", primary_address="10.122.100.253"))
    repository.create(Device(name="核心交换机", system_name="COCC-12-CORE", group_id=cocc.id, device_type="Switch", primary_address="10.122.100.254"))

    cores = discover_core_switches(repository, "demo")

    assert [device.primary_address for device in cores] == ["10.122.100.254"]


def test_core_switch_discovery_can_use_device_identity_when_group_name_missing(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    repository.create(Device(name="核心交换机", system_name="COCC-12-CORE", device_type="Switch", primary_address="10.122.100.254"))
    repository.create(Device(name="无线控制器", system_name="NBDT12HX-WX3540X-AC1", device_type="AC", primary_address="10.122.100.10"))

    cores = discover_core_switches(repository, "demo")

    assert [device.primary_address for device in cores] == ["10.122.100.254"]


def test_mr_remote_ping_includes_peer_mr_long_ping() -> None:
    nodes = _point_table_with_prefix()
    mr_devices = {
        "TC1-MR": Device(name="列车06-MR-CT", primary_address="10.122.6.249", ssh_username="admin", ssh_password="pwd"),
        "TC2-MR": Device(name="列车06-MR-CW", primary_address="10.122.6.250", ssh_username="admin", ssh_password="pwd"),
    }
    commands: list[str] = []
    service = CarNetworkDiagnosticService(
        nodes,
        mr_devices=mr_devices,
        ac_command_func=lambda command: "列车06-MR-CT\n列车06-MR-CW",
        ssh_command_func=lambda _host, command: commands.append(command) or "50 packet(s) transmitted, 50 packet(s) received, 0.0% packet loss\nround-trip min/avg/max/std-dev = 0.413/0.714/0.975/0.180 ms",
    )

    result = service.run()
    payload = result.to_json_dict()

    assert "ping -c 50 10.122.6.250" in commands
    assert "ping -c 50 10.122.6.249" not in commands
    assert any(row["node"].startswith("TC1-MR -> TC2-MR") for row in result.tables["TC1"])
    assert any(row["node"].startswith("TC2-MR -> TC1-MR") for row in result.tables["TC2"])
    assert payload["vehicle_internal_status"]["mr_peer_reachability"] == {
        "TC1-MR->TC2-MR": "ok",
        "TC2-MR->TC1-MR": "ok",
    }
    assert payload["cross_tc_ping"]["status"] == "ok"
    assert payload["cross_tc_ping"]["command"] == "ping -c 50 10.122.6.250"


def test_global_srv_generation_uses_train_subnet_and_configured_hosts(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载-MR")
    repository.create(Device(name="LC14-MR-CT", group_id=group.id, device_type="Cloud-AP", primary_address="10.122.14.249", backup_address="10.122.89.106"))
    config = {
        "srv_generation": {"enabled": True, "tc1_host": 3, "tc2_host": 4, "vrrp_host": 254, "mode": "same_vehicle_subnet"}
    }

    nodes = generate_point_table_from_devices(repository, "demo", [], config)

    assert next(node for node in nodes if node.node_name == "TC1-SRV").ip_vehicle == "10.122.14.3"
    assert next(node for node in nodes if node.node_name == "TC2-SRV").ip_vehicle == "10.122.14.4"
    assert next(node for node in nodes if node.node_name == "TC1-SW").vrrp_ip == "10.122.14.254"


def test_apply_global_rules_keeps_vrrp_per_train_subnet() -> None:
    nodes = [
        CarNetworkNode("NBL12-LC01", "TC1-SW", "SW", train_no="01", tc="TC1", end="CT", ip_vehicle="10.122.1.251"),
        CarNetworkNode("NBL12-LC01", "TC2-SW", "SW", train_no="01", tc="TC2", end="CW", ip_vehicle="10.122.1.252"),
        CarNetworkNode("NBL12-LC06", "TC1-SW", "SW", train_no="06", tc="TC1", end="CT", ip_vehicle="10.122.6.251"),
        CarNetworkNode("NBL12-LC06", "TC2-SW", "SW", train_no="06", tc="TC2", end="CW", ip_vehicle="10.122.6.252"),
        CarNetworkNode("NBL12-LC14", "TC1-SW", "SW", train_no="14", tc="TC1", end="CT", ip_vehicle="192.168.14.251"),
    ]

    result = apply_global_rules_to_nodes(nodes)

    by_train = {(node.train_no, node.node_name): node for node in result}
    assert by_train[("01", "TC1-SW")].vrrp_ip == "10.122.1.254"
    assert by_train[("06", "TC1-SW")].vrrp_ip == "10.122.6.254"
    assert by_train[("14", "TC1-SW")].vrrp_ip == "192.168.14.254"


def test_normalize_train_network_defaults_repairs_stale_vrrp_values() -> None:
    nodes = [
        CarNetworkNode("NBL12-LC01", "TC1-SW", "SW", train_no="01", tc="TC1", end="CT", ip_vehicle="10.122.1.251", vrrp_ip="10.122.1.254"),
        CarNetworkNode("NBL12-LC02", "TC1-SW", "SW", train_no="02", tc="TC1", end="CT", ip_vehicle="10.122.2.251", vrrp_ip="10.122.1.254"),
        CarNetworkNode("NBL12-LC06", "TC1-SW", "SW", train_no="06", tc="TC1", end="CT", ip_vehicle="10.122.6.251", vrrp_ip="10.122.1.254"),
        CarNetworkNode("NBL12-LC14", "TC1-SW", "SW", train_no="14", tc="TC1", end="CT", ip_vehicle="10.122.14.251", vrrp_ip="10.122.1.254"),
    ]

    result = normalize_train_network_defaults(nodes)

    by_train = {node.train_no: node for node in result}
    assert by_train["01"].vrrp_ip == "10.122.1.254"
    assert by_train["02"].vrrp_ip == "10.122.2.254"
    assert by_train["06"].vrrp_ip == "10.122.6.254"
    assert by_train["14"].vrrp_ip == "10.122.14.254"


def test_generate_from_devices_does_not_preserve_global_stale_vrrp(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载-3SW")
    device = repository.create(Device(name="LC06-TC1-SW", group_id=group.id, device_type="Switch", primary_address="10.122.6.251", backup_address="10.122.89.6"))
    old = CarNetworkNode("NBL12-LC06", "TC1-SW", "SW", train_no="06", tc="TC1", end="CT", device_id=str(device.id), ip_vehicle="10.122.6.251", vrrp_ip="10.122.1.254", address_mapping_mode="global")

    nodes = generate_point_table_from_devices(repository, "demo", [old])

    assert next(node for node in nodes if node.node_name == "TC1-SW").vrrp_ip == "10.122.6.254"


def test_generation_normalizes_legacy_remarks(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载-MR")
    mr = repository.create(Device(name="列车06-MR-CT", group_id=group.id, device_type="Cloud-AP", primary_address="10.122.6.249", remark="车载AP（主）"))
    old = CarNetworkNode("NBL12-LC06", "TC1-MR", "MR", train_no="06", tc="TC1", end="CT", device_id=str(mr.id), remark="车载AP（主）")

    nodes = generate_point_table_from_devices(repository, "demo", [old])

    assert next(node for node in nodes if node.node_name == "TC1-MR").remark == "CT MR"


def test_point_table_dialog_uses_chinese_headers_and_keeps_internal_mapping_values(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    store = CarNetworkPointTableStore(paths, "demo")
    store.save([CarNetworkNode("LC06", "TC1-MR", "MR", train_no="06", tc="TC1", end="CT", primary_address_role="vehicle_ip")])

    dialog = PointTableDialog(repository, "demo", store, CarNetworkGlobalConfigStore(paths, "demo"))
    header_labels = [dialog.table.horizontalHeaderItem(column).text() for column in range(dialog.table.columnCount())]
    role_column = header_labels.index("主用地址映射")
    combo = dialog.table.cellWidget(0, role_column)

    assert "station" not in header_labels
    assert "primary_address" not in header_labels
    assert "归属站点" in header_labels
    assert combo.currentText() == "车内IP"
    assert dialog._rows_to_nodes()[0].primary_address_role == "vehicle_ip"


def test_point_table_role_combo_supports_all_internal_value(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    store = CarNetworkPointTableStore(paths, "demo")
    store.save([
        CarNetworkNode(
            "LC06",
            "TC1-MR",
            "MR",
            train_no="06",
            tc="TC1",
            end="CT",
            primary_address="10.122.6.249",
            primary_address_role="all",
            address_mapping_mode="custom",
        )
    ])

    dialog = PointTableDialog(repository, "demo", store, CarNetworkGlobalConfigStore(paths, "demo"))
    role_column = car_diag.POINT_TABLE_FIELDS.index("primary_address_role")
    combo = dialog.table.cellWidget(0, role_column)
    assert combo is not None

    labels = [combo.itemText(index) for index in range(combo.count())]
    assert "全部" in labels
    assert combo.currentText() == "全部"
    assert dialog._rows_to_nodes()[0].primary_address_role == "all"


def test_point_table_lock_persists_and_blocks_edit_actions(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    store = CarNetworkPointTableStore(paths, "demo")
    config_store = CarNetworkGlobalConfigStore(paths, "demo")
    config_store.save({"point_table_locked": True})

    dialog = PointTableDialog(repository, "demo", store, config_store)

    assert dialog.locked is True
    assert dialog.add_button.isEnabled() is False
    assert dialog.save_button.isEnabled() is False
    assert dialog.export_button.isEnabled() is True
    assert config_store.load()["point_table_locked"] is True


def test_rail_transit_contains_car_network_tab_and_train_from_devices(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    paths = PathResolver(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车载-MR")
    repository.create(Device(name="列车06-MR-CT", group_id=group.id, device_type="FAT-AP", primary_address="10.122.89.106"))

    page = RailTransitPage(repository, I18n("zh_CN"), "demo", paths)
    assert page.car_network_page is None
    page._ensure_feature_page("rail.car_network_diagnostic")

    assert page.tabs.tabText(1) == "车内通信检测"
    assert page.car_network_page.train_table.item(0, 0).text() == "06车"
    assert page.car_network_page.train_table.item(0, 1).text() == "未检测"
    assert not hasattr(page.car_network_page, "generate_button")
