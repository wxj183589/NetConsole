from netconsole.core.bootstrap import create_demo_context
import pytest

from netconsole.core.database import CURRENT_SCHEMA_VERSION, Database, DatabaseSchemaMismatchError
from netconsole.repositories.ac_repository import AcRepository
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository


def test_database_initializes_devices_table_with_connection_and_snmp_fields(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()

    with db.connect() as conn:
        table_names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()]
        fact_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_facts)").fetchall()]
        fact_history_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_facts_history)").fetchall()]
        config_snapshot_columns = [row["name"] for row in conn.execute("PRAGMA table_info(config_snapshots)").fetchall()]
        interface_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_interfaces)").fetchall()]
        optical_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_optical_modules)").fetchall()]
        optical_history_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_optical_modules_history)").fetchall()]
        schema_version = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()["value"]
        ap_entity_indexes = {row["name"]: dict(row) for row in conn.execute("PRAGMA index_list(ap_entities)").fetchall()}
        fit_ap_resource_indexes = [dict(row) for row in conn.execute("PRAGMA index_list(ac_fit_ap_resources)").fetchall()]
        fit_ap_resource_index_columns = {
            row["name"]: [
                column["name"]
                for column in conn.execute(f"PRAGMA index_info({row['name']})").fetchall()
            ]
            for row in fit_ap_resource_indexes
        }

    assert "collect_runs" in table_names
    assert "device_facts" in table_names
    assert "device_interfaces" in table_names
    assert "device_optical_modules" in table_names
    assert "device_lldp_neighbors" in table_names
    assert "device_facts_history" in table_names
    assert "device_interfaces_history" in table_names
    assert "device_optical_modules_history" in table_names
    assert "device_lldp_neighbors_history" in table_names
    assert "ac_ap_summary" in table_names
    assert "ac_fit_ap_resources" in table_names
    assert "ap_entities" in table_names
    assert "ap_resource_snapshots" in table_names
    assert "ap_lldp_history" in table_names
    assert "ap_optical_history" in table_names
    assert "trackside_ap_view_cache" in table_names
    assert "ac_fit_ap_optical" in table_names
    assert "config_snapshots" in table_names
    assert "device_groups" in table_names
    assert "idx_ap_entities_site_ac_apid" not in ap_entity_indexes
    assert "idx_ap_entities_site_ac_name" not in ap_entity_indexes
    assert ap_entity_indexes["idx_ap_entities_site_ac_apid_lookup"]["unique"] == 0
    assert ap_entity_indexes["idx_ap_entities_site_ac_name_lookup"]["unique"] == 0
    assert ["ac_device_uuid", "serial_number"] not in fit_ap_resource_index_columns.values()
    assert "base" + "line" not in config_snapshot_columns
    for column in ("interface_type", "port_status", "pvid"):
        assert column in interface_columns
    for column in ("rx_low_warning", "rx_high_warning", "tx_low_warning", "tx_high_warning"):
        assert column in optical_columns
        assert column in optical_history_columns
    assert "mac_address" in fact_columns
    assert "mac_address" in fact_history_columns

    for column in (
        "ssh_enabled",
        "ssh_port",
        "telnet_enabled",
        "telnet_port",
        "ssh_username",
        "ssh_password",
        "telnet_username",
        "telnet_password",
        "snmp_v1_enabled",
        "snmp_v2c_enabled",
        "snmp_v3_enabled",
        "snmpv3_auth_password",
        "snmpv3_priv_password",
        "group_id",
        "https_port",
        "system_name",
        "mac_address",
        "primary_address",
        "backup_address",
        "protocol",
        "port",
        "username",
        "password",
        "snmp_version",
        "tunnel_enabled",
        "tunnel1_host",
        "tunnel2_host",
    ):
        assert column in columns
    for removed_column in (
        "credential_shared",
        "auth_mode",
        "ssh_auth_mode",
        "telnet_auth_mode",
        "serial_port",
        "baudrate",
        "data_bits",
        "parity",
        "stop_bits",
        "ip_address",
        "sysname",
        "tags",
    ):
        assert removed_column not in columns
    assert schema_version == CURRENT_SCHEMA_VERSION


def test_database_initialize_rejects_old_schema_without_auto_migration(tmp_path):
    db = Database(tmp_path / "legacy.db")
    with db.connect() as conn:
        conn.execute(
            """
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                device_vendor TEXT NOT NULL DEFAULT 'H3C',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO devices (device_uuid, name, ip_address, created_at, updated_at)
            VALUES ('legacy-uuid', 'AC-OLD', '10.122.100.10', '2026-06-19T10:00:00', '2026-06-19T10:00:00')
            """
        )
        conn.commit()

    with pytest.raises(DatabaseSchemaMismatchError, match="数据库结构已变更|当前数据库结构"):
        db.initialize()

    with db.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
        row = conn.execute("SELECT device_uuid, name, ip_address FROM devices WHERE device_uuid = 'legacy-uuid'").fetchone()

    assert "https_port" not in columns
    assert "group_id" not in columns
    assert dict(row) == {"device_uuid": "legacy-uuid", "name": "AC-OLD", "ip_address": "10.122.100.10"}


def test_fit_ap_resource_update_writes_ap_entity_and_snapshot(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    repository = AcRepository(db)

    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-idle",
                "ap_name": "30f5-277a-15e0",
                "serial_number": "SN-IDLE",
                "state": "I",
                "site": "Station A",
            }
        ],
    )

    entities = repository.list_ap_entities("ac-1")
    with db.connect() as conn:
        snapshots = conn.execute("SELECT * FROM ap_resource_snapshots WHERE ap_uuid = 'ap-idle'").fetchall()

    assert len(entities) == 1
    assert entities[0]["ap_uuid"] == "ap-idle"
    assert entities[0]["ap_mac"] == "30f5-277a-15e0"
    assert entities[0]["station"] == "Station A"
    assert entities[0]["state_display"] == "Idle"
    assert entities[0]["is_offline"] == 1
    assert len(snapshots) == 1


def test_demo_context_creates_demo_data_once_with_connection_and_snmp_examples(tmp_path):
    context = create_demo_context(PathResolver(tmp_path))
    devices = context.repository.list()
    pairs = {(device.device_vendor, device.device_type) for device in devices}
    uuids = {device.device_uuid for device in devices}

    assert context.demo_inserted is True
    assert context.site.name == "demo"
    assert len(devices) == 8
    assert len(uuids) == len(devices)
    assert all(Device.is_valid_uuid(device.device_uuid) for device in devices)
    assert ("H3C", "SW") in pairs
    assert ("H3C", "AC") in pairs
    assert ("Huawei", "SW") in pairs
    assert ("Ruijie", "SW") in pairs
    assert ("H3C", "FW") in pairs
    assert all(not hasattr(device, "credential_shared") for device in devices)
    assert any(device.ssh_enabled and not device.telnet_enabled and device.ssh_username and device.ssh_password for device in devices)
    assert any(device.telnet_enabled and not device.ssh_enabled and not device.telnet_username and device.telnet_password for device in devices)
    assert any(device.ssh_enabled and device.telnet_enabled and device.ssh_username == device.telnet_username and device.ssh_password == device.telnet_password for device in devices)
    assert any(device.ssh_enabled and device.telnet_enabled and device.ssh_username != device.telnet_username for device in devices)
    assert any(
        device.snmp_v3_enabled
        and device.snmpv3_security_level == "AuthPriv"
        and device.snmpv3_auth_protocol == "SHA"
        and device.snmpv3_auth_password == "auth123456"
        and device.snmpv3_priv_protocol == "AES128"
        and device.snmpv3_priv_password == "priv123456"
        for device in devices
    )
    simulators = {device.name: device for device in devices if device.name in {"AC", "SW01", "SW02"}}
    assert set(simulators) == {"AC", "SW01", "SW02"}
    assert simulators["AC"].ip_address == "10.0.0.51"
    assert simulators["SW01"].ip_address == "10.0.0.52"
    assert simulators["SW02"].ip_address == "10.0.0.53"
    assert all(Device.is_valid_uuid(device.device_uuid) for device in simulators.values())
    assert all(device.ssh_username == "admin" for device in simulators.values())
    assert all(device.ssh_password == "Admin@123" for device in simulators.values())
    assert all(getattr(device, "device_type") != "Serial" for device in devices)

    fact_repository = DeviceFactRepository(context.database)
    simulator_facts = {name: fact_repository.get_device_fact(device.device_uuid) for name, device in simulators.items()}
    assert simulator_facts["AC"]["model"] == "H3C WX3540H"
    assert simulator_facts["AC"]["sysname"] == "AC-DEMO"
    assert simulator_facts["SW01"]["model"] == "H3C S5560X"
    assert simulator_facts["SW01"]["serial_number"] == "DEMO-SW01-0001"
    assert simulator_facts["SW02"]["model"] == "H3C S5130S"
    assert simulator_facts["SW02"]["serial_number"] == "DEMO-SW02-0001"

    sw01_interfaces = fact_repository.list_device_interfaces(simulators["SW01"].device_uuid)
    sw02_interfaces = fact_repository.list_device_interfaces(simulators["SW02"].device_uuid)
    assert [item["interface_name"] for item in sw01_interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/3",
    ]
    assert [item["interface_name"] for item in sw02_interfaces] == [
        "GigabitEthernet1/0/1",
        "GigabitEthernet1/0/2",
        "GigabitEthernet1/0/3",
    ]
    assert sw01_interfaces[1]["description"] == "Link to SW02"
    assert sw01_interfaces[0]["interface_type"] == "L3"
    assert sw01_interfaces[0]["port_status"] == "route"
    assert sw01_interfaces[0]["ip_address"] == "10.0.0.52/24"
    assert sw01_interfaces[1]["interface_type"] == "L2"
    assert sw01_interfaces[1]["port_status"] == "trunk"
    assert sw01_interfaces[1]["pvid"] == "1"
    assert sw02_interfaces[0]["description"] == "Uplink to SW01"
    assert sw02_interfaces[0]["port_status"] == "trunk"

    sw01_neighbors = fact_repository.list_lldp_neighbors(simulators["SW01"].device_uuid)
    sw02_neighbors = fact_repository.list_lldp_neighbors(simulators["SW02"].device_uuid)
    ac_neighbors = fact_repository.list_lldp_neighbors(simulators["AC"].device_uuid)
    assert sw01_neighbors[0]["neighbor_sysname"] == "SW02-DEMO"
    assert sw01_neighbors[0]["neighbor_interface"] == "GigabitEthernet1/0/1"
    assert sw02_neighbors[0]["neighbor_sysname"] == "SW01-DEMO"
    assert ac_neighbors[0]["neighbor_sysname"] == "SW01-DEMO"
    sw01_optical_modules = fact_repository.list_optical_modules(simulators["SW01"].device_uuid)
    sw02_optical_modules = fact_repository.list_optical_modules(simulators["SW02"].device_uuid)
    assert sw01_optical_modules[0]["interface_name"] == "GigabitEthernet1/0/2"
    assert sw01_optical_modules[0]["module_serial_number"] == "DEMO-OPT-SW01-0001"
    assert sw01_optical_modules[0]["rx_power"] == "-3.21 dBm"
    assert sw02_optical_modules[0]["interface_name"] == "GigabitEthernet1/0/1"
    assert sw02_optical_modules[0]["module_serial_number"] == "DEMO-OPT-SW02-0001"
    assert len(fact_repository.list_interface_history(simulators["SW01"].device_uuid, "GigabitEthernet1/0/2")) >= 3
    assert len(fact_repository.list_optical_history(simulators["SW01"].device_uuid, "GigabitEthernet1/0/2")) >= 3
    assert len(fact_repository.list_lldp_history(simulators["SW01"].device_uuid, "GigabitEthernet1/0/2")) >= 3

    second_context = create_demo_context(PathResolver(tmp_path))
    assert second_context.demo_inserted is False
    assert len(second_context.repository.list()) == len(devices)
