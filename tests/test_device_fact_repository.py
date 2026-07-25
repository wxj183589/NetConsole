from netconsole.core.database import Database
from netconsole.repositories.device_fact_repository import DeviceFactRepository


def make_repository(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return DeviceFactRepository(database)


def test_upsert_device_fact_creates_and_replaces_old_data(tmp_path):
    repository = make_repository(tmp_path)

    repository.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "OLD",
            "model": "Old Model",
            "collected_at": "2026-06-13T10:00:00",
            "updated_at": "2026-06-13T10:00:00",
        }
    )
    repository.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "NEW",
            "model": "New Model",
            "collected_at": "2026-06-13T10:01:00",
            "updated_at": "2026-06-13T10:01:00",
        }
    )

    fact = repository.get_device_fact("device-1")
    assert fact["sysname"] == "NEW"
    assert fact["model"] == "New Model"
    assert len(repository.list_device_facts()) == 1
    assert [item["sysname"] for item in repository.list_fact_history("device-1")] == ["NEW", "OLD"]


def test_get_latest_raw_log_path_reads_device_fact_path(tmp_path):
    repository = make_repository(tmp_path)
    repository.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "SW1",
            "raw_log_path": str(tmp_path / "raw.log"),
            "collected_at": "2026-06-13T10:00:00",
            "updated_at": "2026-06-13T10:00:00",
        }
    )

    assert repository.get_latest_raw_log_path("device-1") == str(tmp_path / "raw.log")
    assert repository.get_latest_raw_log_path("missing") is None


def test_replace_device_interfaces_replaces_only_target_device(tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_device_interfaces("device-1", [{"interface_name": "GE1/0/1"}, {"interface_name": "GE1/0/2"}])
    repository.replace_device_interfaces("device-2", [{"interface_name": "GE1/0/9"}])

    repository.replace_device_interfaces(
        "device-1",
        [{"interface_name": "GE1/0/3", "link_status": "up", "interface_type": "L3", "port_status": "route", "pvid": "1"}],
    )

    device_1_interfaces = repository.list_device_interfaces("device-1")
    assert [item["interface_name"] for item in device_1_interfaces] == ["GE1/0/3"]
    assert device_1_interfaces[0]["link_status"] == "up"
    assert device_1_interfaces[0]["interface_type"] == "L3"
    assert device_1_interfaces[0]["port_status"] == "route"
    assert device_1_interfaces[0]["pvid"] == "1"
    assert [item["interface_name"] for item in repository.list_device_interfaces("device-2")] == ["GE1/0/9"]


def test_device_interfaces_use_logical_interface_sort(tmp_path):
    repository = make_repository(tmp_path)

    repository.replace_device_interfaces(
        "device-1",
        [
            {"interface_name": "GigabitEthernet1/0/10"},
            {"interface_name": "GigabitEthernet1/0/2"},
            {"interface_name": "GigabitEthernet1/0/1"},
        ],
    )

    assert [item["interface_name"] for item in repository.list_device_interfaces("device-1")] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/10",
    ]


def test_list_interface_history_orders_by_collected_at_desc(tmp_path):
    repository = make_repository(tmp_path)
    repository.append_interface_history({"device_uuid": "device-1", "interface_name": "GE1/0/1", "collected_at": "2026-06-13T09:00:00", "link_status": "OLD"})
    repository.append_interface_history({"device_uuid": "device-1", "interface_name": "GE1/0/1", "collected_at": "2026-06-13T11:00:00", "link_status": "NEW"})

    assert [item["link_status"] for item in repository.list_interface_history("device-1", "GE1/0/1")] == ["NEW", "OLD"]


def test_replace_and_list_optical_modules(tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_optical_modules("device-1", [{"interface_name": "GE1/0/2", "rx_power": "-3.2 dBm"}])
    repository.replace_optical_modules("device-2", [{"interface_name": "GE1/0/9", "rx_power": "-9.9 dBm"}])

    repository.replace_optical_modules(
        "device-1",
        [
            {
                "interface_name": "GE1/0/1",
                "rx_power": "-3.1 dBm",
                "tx_power": "-2.8 dBm",
                "temperature": "38 C",
                "voltage": "3.3 V",
                "bias_current": "6.1 mA",
                "module_model": "SFP-GE-LX-SM1310",
                "module_serial_number": "OPT-1",
                "module_vendor": "H3C",
                "wavelength": "1310 nm",
                "transmission_distance": "10 km",
                "connector_type": "LC",
                "status": "normal",
            }
        ],
    )

    modules = repository.list_optical_modules("device-1")
    assert len(modules) == 1
    assert modules[0]["interface_name"] == "GE1/0/1"
    assert modules[0]["rx_power"] == "-3.1 dBm"
    assert modules[0]["module_serial_number"] == "OPT-1"
    assert repository.list_optical_modules("device-2")[0]["interface_name"] == "GE1/0/9"


def test_optical_modules_use_logical_interface_sort(tmp_path):
    repository = make_repository(tmp_path)

    repository.replace_optical_modules(
        "device-1",
        [{"interface_name": "GigabitEthernet1/0/10"}, {"interface_name": "GigabitEthernet1/0/2"}],
    )

    assert [item["interface_name"] for item in repository.list_optical_modules("device-1")] == [
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/10",
    ]


def test_list_optical_history_orders_by_collected_at_desc(tmp_path):
    repository = make_repository(tmp_path)
    repository.append_optical_history({"device_uuid": "device-1", "interface_name": "GE1/0/1", "collected_at": "2026-06-13T09:00:00", "rx_power": "-3.45 dBm"})
    repository.append_optical_history({"device_uuid": "device-1", "interface_name": "GE1/0/1", "collected_at": "2026-06-13T11:00:00", "rx_power": "-3.21 dBm"})

    assert [item["rx_power"] for item in repository.list_optical_history("device-1", "GE1/0/1")] == ["-3.21 dBm", "-3.45 dBm"]


def test_replace_lldp_neighbors_replaces_only_target_device(tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_lldp_neighbors("device-1", [{"local_interface": "GE1/0/1", "neighbor_sysname": "OLD"}])
    repository.replace_lldp_neighbors("device-2", [{"local_interface": "GE1/0/9", "neighbor_sysname": "OTHER"}])

    repository.replace_lldp_neighbors("device-1", [{"local_interface": "GE1/0/2", "neighbor_sysname": "NEW"}])

    neighbors = repository.list_lldp_neighbors("device-1")
    assert [(item["local_interface"], item["neighbor_sysname"]) for item in neighbors] == [("GE1/0/1", "OLD"), ("GE1/0/2", "NEW")]
    assert repository.list_lldp_neighbors("device-2")[0]["neighbor_sysname"] == "OTHER"


def test_replace_lldp_neighbors_preserves_ports_missing_from_partial_collect(tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_lldp_neighbors(
        "device-1",
        [
            {"local_interface": "GigabitEthernet1/0/1", "neighbor_mac": "0000-0000-0001"},
            {"local_interface": "GigabitEthernet1/0/2", "neighbor_mac": "0000-0000-0002"},
            {"local_interface": "GigabitEthernet1/0/3", "neighbor_mac": "0000-0000-0003"},
        ],
    )

    repository.replace_lldp_neighbors(
        "device-1",
        [
            {"local_interface": "GE1/0/1", "neighbor_mac": "0000-0000-0011"},
            {"local_interface": "GE1/0/2", "neighbor_mac": "0000-0000-0022"},
        ],
    )

    neighbors = repository.list_lldp_neighbors("device-1")
    assert [item["neighbor_mac"] for item in neighbors] == ["0000-0000-0011", "0000-0000-0022", "0000-0000-0003"]
    assert len(repository.list_lldp_history("device-1", "GE1/0/1")) == 1


def test_replace_lldp_neighbors_matches_spaced_interface_name(tmp_path):
    repository = make_repository(tmp_path)
    repository.replace_lldp_neighbors(
        "device-1",
        [
            {
                "local_interface": "GigabitEthernet2/0/16",
                "neighbor_mac": "0000-0000-0001",
            }
        ],
    )

    repository.replace_lldp_neighbors(
        "device-1",
        [
            {
                "local_interface": "GigabitEthernet 2/0/16",
                "neighbor_mac": "0000-0000-0016",
            }
        ],
    )

    neighbors = repository.list_lldp_neighbors("device-1")
    assert len(neighbors) == 1
    assert neighbors[0]["neighbor_mac"] == "0000-0000-0016"


def test_lldp_neighbors_use_logical_local_interface_sort(tmp_path):
    repository = make_repository(tmp_path)

    repository.replace_lldp_neighbors(
        "device-1",
        [{"local_interface": "GE1/0/10", "neighbor_sysname": "B"}, {"local_interface": "GE1/0/2", "neighbor_sysname": "A"}],
    )

    assert [item["local_interface"] for item in repository.list_lldp_neighbors("device-1")] == ["GE1/0/2", "GE1/0/10"]


def test_list_lldp_history_orders_by_collected_at_desc(tmp_path):
    repository = make_repository(tmp_path)
    repository.append_lldp_history({"device_uuid": "device-1", "local_interface": "GE1/0/1", "collected_at": "2026-06-13T09:00:00", "neighbor_sysname": "OLD"})
    repository.append_lldp_history({"device_uuid": "device-1", "local_interface": "GE1/0/1", "collected_at": "2026-06-13T11:00:00", "neighbor_sysname": "NEW"})

    assert [item["neighbor_sysname"] for item in repository.list_lldp_history("device-1", "GE1/0/1")] == ["NEW", "OLD"]


def test_create_collect_run_can_be_read(tmp_path):
    repository = make_repository(tmp_path)

    created = repository.create_collect_run({"collect_type": "device_facts", "status": "success"})

    fetched = repository.get_collect_run(created["collect_run_uuid"])
    assert fetched["collect_type"] == "device_facts"
    assert fetched["status"] == "success"
