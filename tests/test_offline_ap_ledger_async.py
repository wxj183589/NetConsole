from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.offline_ap_ledger import (
    OFFLINE_AP_LEDGER_COLUMNS,
    build_device_lookup_by_name,
    build_latest_ap_history_indexes,
    build_offline_ap_ledger,
    fit_ap_online_status,
    is_fit_ap_offline,
)
from netconsole.services.trackside_ap_business import (
    build_trackside_ap_business_rows,
    format_trackside_display_value,
)


def _database(tmp_path):
    database = Database(tmp_path / "data" / "sites" / "demo" / "db" / "devices.db")
    database.initialize()
    return database


def _ac_device():
    return Device(
        name="AC",
        device_type="AC",
        ip_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="password",
    )


def test_fit_ap_state_uses_only_running_master_and_backup_as_online():
    assert fit_ap_online_status({"state": "R/M"}) == "online"
    assert fit_ap_online_status({"state": "R/B"}) == "online"
    assert fit_ap_online_status({"state_display": "运行(主)"}) == "online"
    assert is_fit_ap_offline({"state": "I"}) is True
    assert is_fit_ap_offline({"state": "Idle"}) is True
    assert is_fit_ap_offline({"state": "I = Idle"}) is True
    assert is_fit_ap_offline({"state": "IL"}) is True
    assert is_fit_ap_offline({"state": "JA"}) is True
    assert fit_ap_online_status({}) == "unknown"
    assert is_fit_ap_offline({}) is False


def test_offline_ledger_is_simplified_and_prefers_device_station(tmp_path):
    repository = AcRepository(_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-off",
                "ap_name": "AP-OFF",
                "ap_mac": "0011-2233-4455",
                "state": "I",
                "site": "FIT Site",
            },
            {
                "ap_uuid": "ap-on",
                "ap_name": "AP-ON",
                "ap_mac": "aabb-ccdd-eeff",
                "state": "R/M",
                "site": "FIT Site",
            },
        ],
    )
    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {
                "ap_uuid": "ap-off",
                "ap_name": "AP-OFF",
                "neighbor_device_name": "SW-1",
                "neighbor_interface": "GE1/0/1",
                "rx_power": "-40.00",
                "collected_at": "2026-01-01T00:00:00",
            }
        ],
    )
    resources = repository.list_fit_ap_resources_with_metadata("ac-1")
    latest_lldp, latest_optical = build_latest_ap_history_indexes(repository, resources)
    stats, ledger = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap=latest_lldp,
        latest_optical_by_ap=latest_optical,
        device_lookup_by_name=build_device_lookup_by_name(
            [
                Device(
                    name="SW-1",
                    sysname="SW-1",
                    station="Device DB Site",
                    device_uuid="sw-1",
                )
            ]
        ),
    )

    assert [field for _key, field in OFFLINE_AP_LEDGER_COLUMNS] == [
        "site",
        "ap_name",
        "ap_mac",
        "serial_number",
        "ap_status",
        "last_online_time",
        "offline_time",
        "connection_state",
        "historical_switch_name",
        "historical_switch_interface",
    ]
    assert stats["offline_aps"] == 1
    assert "offline_with_optical" not in stats
    assert ledger[0]["ap_name"] == "AP-OFF"
    assert ledger[0]["ap_mac"] == "0011-2233-4455"
    assert ledger[0]["ap_status"] == "Offline"
    assert ledger[0]["site"] == "Device DB Site"
    assert ledger[0]["historical_switch_name"] == "SW-1"
    assert ledger[0]["historical_switch_interface"] == "GigabitEthernet1/0/1"
    assert "ap_rx_power" not in ledger[0]
    assert "switch_rx_power" not in ledger[0]


def test_offline_ledger_offline_at_uses_current_offline_period_and_sorts():
    resources = [
        {
            "ap_uuid": "ap-b",
            "ap_name": "AP-B",
            "ap_mac": "00aa-bbcc-0002",
            "serial_number": "SN-B",
            "state": "Idle",
            "site": "B",
            "updated_at": "2026-06-30 12:00:00",
        },
        {
            "ap_uuid": "ap-a2",
            "ap_name": "AP-A2",
            "ap_mac": "00aa-bbcc-0003",
            "serial_number": "SN-A2",
            "state": "Idle",
            "site": "A",
            "updated_at": "2026-06-30 12:00:00",
        },
        {
            "ap_uuid": "ap-a1",
            "ap_name": "AP-A1",
            "ap_mac": "00aa-bbcc-0001",
            "serial_number": "SN-A1",
            "state": "Idle",
            "site": "A",
            "updated_at": "2026-06-30 12:00:00",
        },
    ]
    history = [
        {
            "id": 1,
            "ap_name": "AP-A1",
            "ap_mac": "00aa-bbcc-0001",
            "serial_number": "SN-A1",
            "site": "A",
            "state_raw": "R/M",
            "collected_at": "2026-06-30 08:00:00",
        },
        {
            "id": 2,
            "ap_name": "AP-A1",
            "ap_mac": "00aa-bbcc-0001",
            "serial_number": "SN-A1",
            "site": "A",
            "state_raw": "Idle",
            "collected_at": "2026-06-30 09:00:00",
        },
        {
            "id": 3,
            "ap_name": "AP-A2",
            "ap_mac": "00aa-bbcc-0003",
            "serial_number": "SN-A2",
            "site": "A",
            "state_raw": "Idle",
            "collected_at": "2026-06-30 07:00:00",
        },
        {
            "id": 4,
            "ap_name": "AP-B",
            "ap_mac": "00aa-bbcc-0002",
            "serial_number": "SN-B",
            "site": "B",
            "state_raw": "R/M",
            "collected_at": "2026-06-30 06:00:00",
        },
        {
            "id": 5,
            "ap_name": "AP-B",
            "ap_mac": "00aa-bbcc-0002",
            "serial_number": "SN-B",
            "site": "B",
            "state_raw": "Idle",
            "collected_at": "2026-06-30 11:00:00",
        },
    ]

    stats, ledger = build_offline_ap_ledger(
        fit_ap_resources=resources,
        latest_lldp_by_ap={},
        device_lookup_by_name={},
        resource_history_rows=history,
    )

    assert stats["offline_aps"] == 3
    assert [(row["site"], row["ap_name"], row["offline_at"]) for row in ledger] == [
        ("A", "AP-A2", "2026-06-30 07:00:00"),
        ("A", "AP-A1", "2026-06-30 09:00:00"),
        ("B", "AP-B", "2026-06-30 11:00:00"),
    ]


def test_offline_ledger_offline_at_falls_back_to_current_fact_and_allows_blank():
    stats, ledger = build_offline_ap_ledger(
        fit_ap_resources=[
            {
                "ap_name": "AP-TIME",
                "ap_mac": "00aa-bbcc-0001",
                "state": "down",
                "site": "A",
                "updated_at": "2026-06-30 12:00:00",
            },
            {
                "ap_name": "AP-BLANK",
                "ap_mac": "00aa-bbcc-0002",
                "state": "offline",
                "site": "A",
            },
        ],
        latest_lldp_by_ap={},
        device_lookup_by_name={},
        resource_history_rows=[],
    )

    assert stats["offline_aps"] == 2
    assert (
        next(row for row in ledger if row["ap_name"] == "AP-TIME")["offline_at"]
        == "2026-06-30 12:00:00"
    )
    assert (
        next(row for row in ledger if row["ap_name"] == "AP-BLANK")["offline_at"] == ""
    )


def test_offline_ledger_mac_fallback_and_fit_ap_site_fills_empty_device_station(
    tmp_path,
):
    repository = AcRepository(_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-off",
                "ap_name": "30f5-277a-15e0",
                "ap_mac": "",
                "state": "I",
                "site": "FIT Site",
            }
        ],
    )
    resources = repository.list_fit_ap_resources_with_metadata("ac-1")
    stats, ledger = build_offline_ap_ledger(
        fit_ap_resources=resources, latest_lldp_by_ap={}, device_lookup_by_name={}
    )

    assert stats["offline_aps"] == 1
    assert ledger[0]["ap_mac"] == "30f5-277a-15e0"
    assert ledger[0]["site"] == "FIT Site"


def test_trackside_offline_row_uses_port_type_and_realtime_switch_optical():
    switch = Device(
        name="SW-1", sysname="SW-1", station="Device DB Site", device_uuid="sw-1"
    )
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/1",
                    "link_status": "DOWN",
                    "protocol_status": "DOWN",
                    "port_status": "access",
                    "pvid": "201",
                    "vlan": "201",
                    "description": "Trackside AP",
                }
            ]
        },
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/1",
                    "rx_power": "-6.10 dBm",
                    "tx_power": "-2.20 dBm",
                    "port_status": "up",
                }
            ]
        },
        [],
        {},
        [],
        {},
        None,
        [
            {
                "site": "Device DB Site",
                "device_uuid": "sw-1",
                "historical_switch_name": "SW-1",
                "historical_switch_interface": "GigabitEthernet1/0/1",
                "ap_name": "AP-OFF",
                "ap_mac": "0011-2233-4455",
                "ap_status": "Idle",
                "is_ap_offline": True,
            }
        ],
    )

    offline = next(row for row in rows if row.get("is_ap_offline"))
    assert offline["site"] == "Device DB Site"
    assert offline["port_type"] == "access"
    assert offline["pvid"] == "201"
    assert offline["vlan"] == "201"
    assert offline["switch_rx_power"] == "-6.10 dBm"
    assert offline["switch_tx_power"] == "-2.20 dBm"
    assert format_trackside_display_value("port_type", offline) == "access"
    assert format_trackside_display_value("link_status", offline) == "DOWN"
    assert format_trackside_display_value("port_type", offline) not in {"UP", "DOWN"}


def test_trackside_switch_offline_forces_downstream_ap_offline_even_when_ac_run():
    switch = Device(
        name="SW-1", sysname="SW-1", station="Station A", device_uuid="sw-1"
    )
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/1",
                    "link_status": "UP",
                    "port_status": "access",
                    "pvid": "201",
                    "vlan": "201",
                    "description": "Trackside AP",
                    "switch_collection_status": "offline",
                }
            ]
        },
        {},
        [],
        {},
        [{"ap_name": "AP-RUN", "ap_mac": "0011-2233-4455", "state": "R/M"}],
        {},
        None,
        [
            {
                "site": "Station A",
                "device_uuid": "sw-1",
                "historical_switch_name": "SW-1",
                "historical_switch_interface": "GigabitEthernet1/0/1",
                "ap_name": "AP-RUN",
                "ap_mac": "0011-2233-4455",
                "ap_status": "Run",
            }
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["offline_reason"] == "switch_offline"
    assert row["status_reason"] == "室内交换机离线，轨旁AP跟随离线"
    assert row["switch_collection_status"] == "offline"
    assert format_trackside_display_value("switch_optical_status", row) == "交换机离线"
    assert format_trackside_display_value("ap_optical_status", row) == "未知"
    assert format_trackside_display_value("link_status", row) == "DOWN"
    assert format_trackside_display_value("port_type", row) == "access"
    assert format_trackside_display_value("port_type", row) != "DOWN"


def test_trackside_ac_idle_marks_ap_offline_when_switch_online():
    switch = Device(
        name="SW-1", sysname="SW-1", station="Station A", device_uuid="sw-1"
    )
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/2",
                    "link_status": "UP",
                    "port_status": "trunk",
                    "description": "Trackside AP",
                }
            ]
        },
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/2",
                    "rx_power": "-6.1",
                    "port_status": "up",
                }
            ]
        },
        [
            {
                "neighbor_device_name": "SW-1",
                "neighbor_interface": "GigabitEthernet1/0/2",
                "ap_name": "AP-IDLE",
                "ap_mac": "0011-2233-5566",
                "state": "Idle",
            }
        ],
    )

    row = rows[0]
    assert row["offline_reason"] == "ac_idle"
    assert format_trackside_display_value("ap_optical_status", row) == "未知"
    assert format_trackside_display_value("link_status", row) == "UP"
    assert format_trackside_display_value("port_type", row) == "trunk"


def test_trackside_same_interface_merges_current_and_historical_rows():
    switch = Device(
        name="SW-1", sysname="SW-1", station="Station A", device_uuid="sw-1"
    )
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/3",
                    "link_status": "DOWN",
                    "port_status": "hybrid",
                    "pvid": "203",
                    "vlan": "203",
                    "description": "Trackside AP",
                }
            ]
        },
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet1/0/3",
                    "rx_power": "-7.1",
                    "port_status": "down",
                }
            ]
        },
        [],
        {},
        [],
        {},
        None,
        [
            {
                "site": "Station A",
                "device_uuid": "sw-1",
                "historical_switch_name": "SW-1",
                "historical_switch_interface": "GigabitEthernet1/0/3",
                "ap_name": "AP-HIST",
                "ap_mac": "0011-2233-6677",
                "ap_status": "Idle",
            }
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["ap_name"] == "AP-HIST"
    assert row["ap_mac"] == "0011-2233-6677"
    assert row["port_type"] == "hybrid"
    assert row["pvid"] == "203"
    assert format_trackside_display_value("port_type", row) not in {"UP", "DOWN"}
