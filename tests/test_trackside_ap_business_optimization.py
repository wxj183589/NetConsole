from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import h3c_ac_collect_service
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources
from netconsole.parsers.h3c.interface_parser import parse_interfaces
from netconsole.services import command_guard
from netconsole.services.trackside_ap_business import (
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    build_trackside_ap_business_rows,
    enrich_trackside_export_rows,
    filter_station_switch_devices,
    format_trackside_display_value,
    is_trackside_ap_interface,
    merge_fit_ap_rows_by_identity,
    optical_change_text,
    trackside_row_status,
)
from netconsole.core.paths import PathResolver


def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def test_station_switch_filter_excludes_non_station_groups(tmp_path):
    database = make_database(tmp_path)
    group_repo = DeviceGroupRepository(database, "demo")
    station = group_repo.create("车站")
    other = group_repo.create("控制中心")
    device_repo = DeviceRepository(database)
    station_switch = device_repo.create(Device(name="ST-SW", device_uuid=Device.new_uuid(), group_id=station.id, device_type="SW"))
    device_repo.create(Device(name="COCC-SW", device_uuid=Device.new_uuid(), group_id=other.id, device_type="SW"))
    device_repo.create(Device(name="ST-AC", device_uuid=Device.new_uuid(), group_id=station.id, device_type="AC"))

    filtered = filter_station_switch_devices(device_repo.list(), database, "demo")

    assert [device.name for device in filtered] == [station_switch.name]


def test_trackside_interface_requires_layer2_port_before_description_or_pvid_match():
    device = Device(name="SW1", station="Station A")
    plan = {"all_vlans": {921}, "station_vlans": {}}

    assert not is_trackside_ap_interface(device, {"interface_name": "Vlan-interface921", "description": "To AP", "pvid": "921"})[0]
    assert not is_trackside_ap_interface(device, {"interface_name": "GigabitEthernet1/0/1", "interface_type": "三层", "description": "To AP", "pvid": "921"})[0]
    assert is_trackside_ap_interface(device, {"interface_name": "GigabitEthernet1/0/2", "port_status": "access", "description": "To AP"}) == (True, "description")
    assert is_trackside_ap_interface(device, {"interface_name": "Bridge-Aggregation1", "port_status": "trunk", "pvid": "921"}, plan) == (True, "pvid")


def test_export_columns_exclude_ui_only_fields_and_port_change_fields():
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS]

    assert "port_type" not in fields
    assert "description" not in fields
    assert "pvid" not in fields
    assert "vlan" not in fields
    assert "switch_optical_change" in fields
    assert "ap_optical_change" in fields
    for field in (
        "ap_port_change",
        "ap_port_change_reason",
        "previous_switch",
        "previous_interface",
        "current_switch",
        "current_interface",
        "history_compared_at",
    ):
        assert field not in fields


def test_display_interface_brief_parses_bridge_and_route_modes():
    rows = parse_interfaces(
        """
Brief information on interfaces in route mode:
Interface            Link Protocol Primary IP      Description
Vlan101              UP   UP       10.0.0.1/24     station gateway

Brief information on interfaces in bridge mode:
Interface            Link Speed   Duplex Type PVID Description
GE1/0/1              UP   1G(a)   F(a)   A    921  To AP-01
BAGG1                DOWN auto    A      T    1    Uplink
"""
    )

    by_name = {row["interface_name"]: row for row in rows}
    assert by_name["Vlan-interface101"]["interface_type"] == "三层"
    assert by_name["Vlan-interface101"]["port_status"] == "route"
    assert by_name["GigabitEthernet1/0/1"]["interface_type"] == "二层"
    assert by_name["GigabitEthernet1/0/1"]["port_status"] == "access"
    assert by_name["GigabitEthernet1/0/1"]["pvid"] == "921"
    assert by_name["Bridge-Aggregation1"]["port_status"] == "trunk"


def test_new_trackside_commands_are_whitelisted():
    assert command_guard.is_command_allowed("display interface brief", "optical_refresh")
    assert command_guard.is_command_allowed("display interface brief", "fit_ap_collect")


def test_history_change_helpers_only_report_normal_abnormal_transitions():
    assert optical_change_text("normal", "warning") == "正常 → 不正常"
    assert optical_change_text("alarm", "normal") == "不正常 → 正常"
    assert optical_change_text("warning", "alarm") == "-"
    assert optical_change_text("normal", "normal") == "-"
    assert optical_change_text("failed", "alarm") == "-"


def test_multi_ac_same_ap_merge_prefers_online_over_idle():
    rows = merge_fit_ap_rows_by_identity(
        [
            {"ac_device_uuid": "standby", "serial_number": "SN-1", "ap_name": "AP1", "state": "Idle", "updated_at": "2026-06-29T10:00:00"},
            {"ac_device_uuid": "active", "serial_number": "SN-1", "ap_name": "AP1", "state": "Run", "ap_ip": "10.0.0.10", "updated_at": "2026-06-29T09:00:00"},
        ]
    )

    assert len(rows) == 1
    assert rows[0]["ac_device_uuid"] == "active"


def test_trackside_business_merges_same_ap_by_identity():
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "description": "To AP", "port_status": "access"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "rx_power": "-8", "rx_low_warning": "-20"}]},
        [
            {"ac_device_uuid": "standby", "serial_number": "SN-1", "ap_name": "AP1", "ap_mac": "0011-2233-4455", "state": "Idle", "neighbor_device_name": "SW1", "neighbor_interface": "GigabitEthernet1/0/1"},
            {"ac_device_uuid": "active", "serial_number": "SN-1", "ap_name": "AP1", "ap_mac": "0011-2233-4455", "state": "Run", "ap_ip": "10.0.0.10", "neighbor_device_name": "SW1", "neighbor_interface": "GigabitEthernet1/0/1"},
        ],
        fit_ap_resource_rows=[
            {"ac_device_uuid": "standby", "serial_number": "SN-1", "ap_name": "AP1", "ap_mac": "0011-2233-4455", "state": "Idle"},
            {"ac_device_uuid": "active", "serial_number": "SN-1", "ap_name": "AP1", "ap_mac": "0011-2233-4455", "state": "Run", "ap_ip": "10.0.0.10"},
        ],
    )

    assert len(rows) == 1
    assert rows[0]["ac_device_uuid"] == "active"
    assert rows[0]["ap_ip"] == "10.0.0.10"


def test_trackside_business_uses_latest_current_fact_for_same_interface():
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "id": 1,
                    "interface_name": "GigabitEthernet1/0/1",
                    "description": "To AP",
                    "port_status": "access",
                    "updated_at": "2026-06-29T10:00:00",
                }
            ]
        },
        {
            "sw-1": [
                {
                    "id": 1,
                    "interface_name": "GigabitEthernet1/0/1",
                    "rx_power": "-28",
                    "rx_low_warning": "-20",
                    "status": "warning",
                    "updated_at": "2026-06-29T09:00:00",
                },
                {
                    "id": 2,
                    "interface_name": "GE1/0/1",
                    "rx_power": "-8",
                    "rx_low_warning": "-20",
                    "status": "normal",
                    "updated_at": "2026-06-29T10:00:00",
                },
            ]
        },
        [
            {
                "id": 1,
                "ap_name": "AP1",
                "ap_mac": "0011-2233-4455",
                "state": "Run",
                "rx_power": "-30",
                "rx_low_warning": "-20",
                "updated_at": "2026-06-29T09:00:00",
                "neighbor_device_name": "SW1",
                "neighbor_interface": "GigabitEthernet1/0/1",
            },
            {
                "id": 2,
                "ap_name": "AP1",
                "ap_mac": "0011-2233-4455",
                "state": "Run",
                "rx_power": "-7",
                "rx_low_warning": "-20",
                "updated_at": "2026-06-29T10:00:00",
                "neighbor_device_name": "SW1",
                "neighbor_interface": "GE1/0/1",
            },
        ],
    )

    assert rows[0]["switch_rx_power"] == "-8"
    assert rows[0]["switch_optical_status"] == "normal"
    assert rows[0]["ap_rx_power"] == "-7"
    assert rows[0]["ap_optical_status"] == "normal"


def test_trackside_business_marks_link_down_with_light_as_link_abnormal():
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "description": "To AP", "link_status": "DOWN", "port_status": "access"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "rx_power": "-7.77", "rx_low_warning": "-20", "rx_low_alarm": "-25"}]},
        [],
    )

    assert rows[0]["switch_optical_status"] == "link_abnormal"
    assert format_trackside_display_value("switch_optical_status", rows[0]) == "链路异常"
    assert trackside_row_status(rows[0]) == "link_abnormal"


def test_trackside_business_keeps_link_up_with_light_normal():
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "description": "To AP", "link_status": "UP", "port_status": "access"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "rx_power": "-7.77", "rx_low_warning": "-20", "rx_low_alarm": "-25"}]},
        [],
    )

    assert rows[0]["switch_optical_status"] == "normal"


@pytest.mark.parametrize(
    ("optical", "expected"),
    [
        ({"rx_power": None, "rx_low_warning": "-20", "rx_low_alarm": "-25"}, "no_light"),
        ({"rx_power": "-36.00", "rx_low_warning": "-20", "rx_low_alarm": "-25"}, "no_light"),
        ({"rx_power": "-7.77", "status": "no_module"}, "no_module"),
    ],
)
def test_trackside_business_does_not_mark_link_down_without_valid_light(optical, expected):
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "description": "To AP", "link_status": "DOWN", "port_status": "access"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", **optical}]},
        [],
    )

    assert rows[0]["switch_optical_status"] == expected


def test_trackside_business_keeps_switch_offline_over_link_abnormal():
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/1",
                    "description": "To AP",
                    "link_status": "DOWN",
                    "port_status": "access",
                    "switch_collection_status": "switch_offline",
                }
            ]
        },
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "rx_power": "-7.77", "rx_low_warning": "-20", "rx_low_alarm": "-25"}]},
        [],
    )

    assert rows[0]["switch_optical_status"] == "offline"


def test_trackside_business_keeps_ap_identity_when_ap_optical_missing():
    switch = Device(device_uuid="sw-1", name="SW1", station="Station A", device_type="SW")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "description": "To AP", "port_status": "access"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet1/0/1", "rx_power": "-8", "rx_low_warning": "-20"}]},
        [
            {
                "ap_name": "AP-MISSING-OPTICAL",
                "ap_mac": "083b.e9ec.da40",
                "serial_number": "SN-MISSING-OPTICAL",
                "state": "Run",
                "neighbor_device_name": "SW1",
                "neighbor_interface": "GigabitEthernet1/0/1",
            }
        ],
    )

    assert rows[0]["ap_name"] == "AP-MISSING-OPTICAL"
    assert rows[0]["ap_mac"] == "083b-e9ec-da40"
    assert rows[0]["serial_number"] == "SN-MISSING-OPTICAL"
    assert rows[0]["ap_rx_power"] is None


def test_ac_resource_collect_failure_keeps_existing_resources(monkeypatch, tmp_path):
    database = make_database(tmp_path)
    repository = AcRepository(database)
    ac = Device(device_uuid="22222222-2222-4222-8222-222222222222", name="AC1", device_type="AC", device_vendor="H3C", primary_address="10.0.0.1", ssh_enabled=1, ssh_username="u", ssh_password="p")
    repository.replace_fit_ap_resources(str(ac.device_uuid), [{"ap_name": "old-ap", "ap_mac": "0011-2233-4455", "serial_number": "SN-OLD"}])

    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("connection failed")))

    result = collect_h3c_ac_resources(ac, "demo", repository=repository, paths=PathResolver(tmp_path), refresh_ac_overview=False)

    assert result.success is False
    assert [row["ap_name"] for row in repository.list_fit_ap_resources(str(ac.device_uuid))] == ["old-ap"]


def test_trackside_optical_change_uses_latest_status_boundary():
    rows = [{"device_uuid": "sw-1", "interface_name": "GE1/0/1", "switch_optical_status": "alarm", "updated_at": "2026-01-04"}]
    history = [
        {"device_uuid": "sw-1", "interface_name": "GE1/0/1", "alarm_status": "normal", "collected_at": "2026-01-01", "id": 1},
        {"device_uuid": "sw-1", "interface_name": "GE1/0/1", "alarm_status": "warning", "collected_at": "2026-01-02", "id": 2},
        {"device_uuid": "sw-1", "interface_name": "GE1/0/1", "alarm_status": "alarm", "collected_at": "2026-01-03", "id": 3},
    ]

    enriched = enrich_trackside_export_rows(rows, switch_optical_history_rows=history)

    assert enriched[0]["switch_optical_change"] == optical_change_text("normal", "alarm")
    assert enriched[0]["history_compared_at"] == "2026-01-01"


def test_trackside_optical_change_ignores_same_abnormal_boundary_without_normal():
    rows = [{"device_uuid": "sw-1", "interface_name": "GE1/0/1", "switch_optical_status": "warning", "updated_at": "2026-01-03"}]
    history = [
        {"device_uuid": "sw-1", "interface_name": "GE1/0/1", "alarm_status": "alarm", "collected_at": "2026-01-01", "id": 1},
        {"device_uuid": "sw-1", "interface_name": "GE1/0/1", "alarm_status": "warning", "collected_at": "2026-01-02", "id": 2},
    ]

    enriched = enrich_trackside_export_rows(rows, switch_optical_history_rows=history)

    assert enriched[0]["switch_optical_change"] == "-"


def test_trackside_optical_change_reports_recovery_from_earlier_abnormal():
    rows = [{"ap_uuid": "ap-1", "ap_name": "AP1", "ap_optical_status": "normal", "updated_at": "2026-01-04"}]
    history = [
        {"ap_uuid": "ap-1", "ap_name": "AP1", "optical_alarm_status": "alarm", "collected_at": "2026-01-01", "id": 1},
        {"ap_uuid": "ap-1", "ap_name": "AP1", "optical_alarm_status": "normal", "collected_at": "2026-01-02", "id": 2},
        {"ap_uuid": "ap-1", "ap_name": "AP1", "optical_alarm_status": "normal", "collected_at": "2026-01-03", "id": 3},
    ]

    enriched = enrich_trackside_export_rows(rows, ap_optical_history_rows=history)

    assert enriched[0]["ap_optical_change"] == optical_change_text("alarm", "normal")
    assert enriched[0]["history_compared_at"] == "2026-01-01"


def test_trackside_export_no_longer_calculates_ap_port_change_from_lldp_history():
    rows = [
        {
            "ap_uuid": "ap-1",
            "ap_name": "AP1",
            "device_name": "SW-B",
            "interface_name": "GigabitEthernet1/0/2",
            "updated_at": "2026-01-05",
        }
    ]
    history = [
        {"ap_uuid": "ap-1", "ap_name": "AP1", "neighbor_device_name": "SW-A", "neighbor_interface": "GigabitEthernet1/0/1", "collected_at": "2026-01-01", "id": 1},
        {"ap_uuid": "ap-1", "ap_name": "AP1", "neighbor_device_name": "SW-A", "neighbor_interface": "GE1/0/1", "collected_at": "2026-01-02", "id": 2},
        {"ap_uuid": "ap-1", "ap_name": "AP1", "neighbor_device_name": "SW-B", "neighbor_interface": "GE1/0/2", "collected_at": "2026-01-03", "id": 3},
        {"ap_uuid": "ap-1", "ap_name": "AP1", "neighbor_device_name": "SW-B", "neighbor_interface": "GigabitEthernet1/0/2", "collected_at": "2026-01-04", "id": 4},
    ]

    enriched = enrich_trackside_export_rows(rows, ap_lldp_history_rows=history)

    assert "ap_port_change" not in enriched[0]
    assert "ap_port_change_reason" not in enriched[0]
    assert "previous_switch" not in enriched[0]
    assert "previous_interface" not in enriched[0]
    assert "current_switch" not in enriched[0]
    assert "current_interface" not in enriched[0]
