from netconsole.core.bootstrap import create_demo_context
import pytest

from netconsole.core.database import CURRENT_SCHEMA_VERSION, Database, DatabaseSchemaMismatchError
from netconsole.repositories.ac_repository import AcRepository
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository


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
        interface_history_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_interfaces_history)").fetchall()]
        lldp_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_lldp_neighbors)").fetchall()]
        lldp_history_columns = [row["name"] for row in conn.execute("PRAGMA table_info(device_lldp_neighbors_history)").fetchall()]
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
        history_index_columns = {
            table: {
                row["name"]: [
                    column["name"]
                    for column in conn.execute(f"PRAGMA index_info({row['name']})").fetchall()
                ]
                for row in conn.execute(f"PRAGMA index_list({table})").fetchall()
            }
            for table in (
                "device_interfaces_history",
                "device_optical_modules_history",
                "device_lldp_neighbors_history",
                "ac_fit_ap_resource_history",
                "ac_fit_ap_optical_history",
                "ac_fit_ap_lldp_history",
                "ac_fit_ap_radio_history",
            )
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
    assert "ac_fit_ap_unauthenticated" in table_names
    assert "ac_fit_ap_unauthenticated_history" in table_names
    assert "ac_fit_ap_unauthenticated_summary" in table_names
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
    assert history_index_columns["device_interfaces_history"]["idx_device_interfaces_history_device_interface_time"] == [
        "device_uuid",
        "interface_name",
        "collected_at",
        "id",
    ]
    assert history_index_columns["device_optical_modules_history"]["idx_device_optical_history_device_interface_time"] == [
        "device_uuid",
        "interface_name",
        "collected_at",
        "id",
    ]
    assert history_index_columns["device_lldp_neighbors_history"]["idx_device_lldp_history_device_interface_time"] == [
        "device_uuid",
        "local_interface",
        "collected_at",
        "id",
    ]
    assert history_index_columns["ac_fit_ap_resource_history"]["idx_fit_ap_resource_history_ac_time"] == [
        "ac_device_uuid",
        "collected_at",
        "id",
    ]
    for table, index_name in (
        ("ac_fit_ap_optical_history", "idx_fit_ap_optical_history_ap_time"),
        ("ac_fit_ap_lldp_history", "idx_fit_ap_lldp_history_ap_time"),
        ("ac_fit_ap_radio_history", "idx_fit_ap_radio_history_ap_time"),
    ):
        assert history_index_columns[table][index_name] == ["ap_uuid", "collected_at", "id"]
    assert "base" + "line" not in config_snapshot_columns
    for column in ("interface_type", "port_status", "pvid"):
        assert column in interface_columns
    for column in (
        "admin_status",
        "physical_status",
        "media_attribute",
        "media_type",
        "category",
        "port_mode",
        "native_vlan",
        "tagged_vlans",
        "untagged_vlans",
        "pvid_source",
        "pvid_verified",
        "vlan_config_status",
        "vlan_config_collected_at",
        "vlan_warnings",
    ):
        assert column in interface_columns
        assert column in interface_history_columns
    for column in (
        "scope",
        "chassis_type",
        "chassis_id",
        "port_id_type",
        "holdtime",
        "ttl",
        "port_description",
        "system_description",
        "system_capabilities",
        "pvid",
        "operational_mau",
        "max_frame_size",
    ):
        assert column in lldp_columns
        assert column in lldp_history_columns
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
        "snmp_port",
        "snmp_ro_community",
        "snmp_timeout_ms",
        "snmp_retries",
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
        "snmp_version",
        "snmp_v3_enabled",
        "snmp_rw_community",
        "snmpv3_username",
        "snmpv3_security_level",
        "snmpv3_auth_protocol",
        "snmpv3_auth_password",
        "snmpv3_priv_protocol",
        "snmpv3_priv_password",
        "snmp_context_name",
    ):
        assert removed_column not in columns
    assert schema_version == CURRENT_SCHEMA_VERSION


def test_database_initialize_auto_updates_additive_schema(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO devices (device_uuid, name, device_vendor, primary_address, created_at, updated_at)
            VALUES ('device-1', 'AC-1', 'H3C', '10.0.0.1', '2026-07-01T00:00:00', '2026-07-01T00:00:00')
            """
        )
        conn.execute("UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'", ("2026.06.23.device_ap_rebuild_mac",))
        conn.execute("DROP TABLE ap_extension_points")
        conn.execute("DROP TABLE ap_extension_import_batches")
        conn.execute("DROP INDEX idx_fit_ap_radio_history_ap_time")
        conn.commit()

    db.initialize()

    with db.connect() as conn:
        version = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()["value"]
        device_count = conn.execute("SELECT COUNT(*) AS count FROM devices WHERE device_uuid = 'device-1'").fetchone()["count"]
        table_names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        radio_history_indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(ac_fit_ap_radio_history)").fetchall()
        }

    assert version == CURRENT_SCHEMA_VERSION
    assert device_count == 1
    assert "ap_extension_points" in table_names
    assert "ap_extension_import_batches" in table_names
    assert "idx_fit_ap_radio_history_ap_time" in radio_history_indexes


def test_trackside_ap_location_migration_defaults_mainline_and_preserves_special_rows(
    tmp_path,
):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    with db.connect() as conn:
        now = "2026-07-31T00:00:00"
        conn.executemany(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_name, section_name, yard_name,
                ap_point_code, ap_name, created_at, updated_at
            ) VALUES ('demo', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("station", "正线站", "", "", "AP-1", "AP-1", now, now),
                ("yard", "", "", "云龙车辆段", "AP-2", "AP-2", now, now),
                ("yard", "", "", "停车场", "AP-3", "AP-3", now, now),
                ("storage_track", "", "", "", "AP-4", "AP-4", now, now),
                ("section", "", "出入段线", "", "AP-5", "AP-5", now, now),
            ],
        )
        conn.execute("ALTER TABLE ap_extension_points DROP COLUMN location_class_source")
        conn.execute("ALTER TABLE ap_extension_points DROP COLUMN participates_in_mainline")
        conn.execute("ALTER TABLE ap_extension_points DROP COLUMN location_class")
        conn.execute(
            "UPDATE schema_metadata SET value='2026.07.30.device_work_scope_status' "
            "WHERE key='schema_version'"
        )
        conn.commit()

    db.initialize()
    db.initialize()

    with db.connect() as conn:
        rows = {
            row["ap_point_code"]: (
                row["location_class"],
                bool(row["participates_in_mainline"]),
                row["location_class_source"],
            )
            for row in conn.execute(
                """
                SELECT ap_point_code, location_class,
                       participates_in_mainline, location_class_source
                FROM ap_extension_points
                WHERE ap_point_code LIKE 'AP-%'
                """
            )
        }
    assert rows == {
        "AP-1": ("MAINLINE", True, "DEFAULT_MAINLINE"),
        "AP-2": ("DEPOT", False, "LEGACY_INFERRED"),
        "AP-3": ("PARKING_YARD", False, "LEGACY_INFERRED"),
        "AP-4": ("STABLING", False, "LEGACY_INFERRED"),
        "AP-5": ("DEPOT_CONNECTION", False, "LEGACY_INFERRED"),
    }
    backups = list(
        (tmp_path / "backups" / "database-migrations").glob(
            "*before-trackside-ap-location-*.sqlite"
        )
    )
    assert backups


def test_zte_interface_lldp_additive_migration_is_repeatable_and_preserves_rows(
    tmp_path,
):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO device_interfaces (
                device_uuid, interface_name, link_status, collected_at, updated_at
            ) VALUES ('device-1', 'gei-0/3/0/2', 'UP', '2026-07-01', '2026-07-01')
            """
        )
        conn.execute(
            """
            INSERT INTO device_interfaces_history (
                device_uuid, interface_name, link_status, collected_at, created_at
            ) VALUES ('device-1', 'gei-0/3/0/2', 'UP', '2026-07-01', '2026-07-01')
            """
        )
        conn.execute(
            """
            INSERT INTO device_lldp_neighbors (
                device_uuid, local_interface, neighbor_sysname, collected_at, updated_at
            ) VALUES ('device-1', 'gei-0/3/0/2', 'OLD-NEIGHBOR', '2026-07-01', '2026-07-01')
            """
        )
        conn.execute(
            """
            INSERT INTO device_optical_modules (
                device_uuid, interface_name, rx_power, module_vendor,
                collected_at, updated_at
            ) VALUES (
                'device-1', 'gei-0/3/0/6', '-15.2', 'ZTRS',
                '2026-07-01', '2026-07-01'
            )
            """
        )
        for table, columns in (
            (
                "device_interfaces",
                (
                    "admin_status",
                    "physical_status",
                    "media_attribute",
                    "media_type",
                    "category",
                    "port_mode",
                    "native_vlan",
                    "tagged_vlans",
                    "untagged_vlans",
                    "pvid_source",
                    "pvid_verified",
                    "vlan_config_status",
                    "vlan_config_collected_at",
                    "vlan_warnings",
                ),
            ),
            (
                "device_interfaces_history",
                (
                    "admin_status",
                    "physical_status",
                    "media_attribute",
                    "media_type",
                    "category",
                    "port_mode",
                    "native_vlan",
                    "tagged_vlans",
                    "untagged_vlans",
                    "pvid_source",
                    "pvid_verified",
                    "vlan_config_status",
                    "vlan_config_collected_at",
                    "vlan_warnings",
                ),
            ),
            (
                "device_lldp_neighbors",
                ("scope", "chassis_type", "chassis_id", "ttl", "pvid"),
            ),
            (
                "device_lldp_neighbors_history",
                ("scope", "chassis_type", "chassis_id", "ttl", "pvid"),
            ),
            (
                "device_optical_modules",
                (
                    "device_vendor",
                    "device_reported_status",
                    "threshold_source",
                    "transceiver_mode",
                    "vendor_part_number",
                    "vendor_revision",
                    "vendor_serial_number",
                ),
            ),
            (
                "device_optical_modules_history",
                (
                    "device_vendor",
                    "device_reported_status",
                    "threshold_source",
                    "transceiver_mode",
                    "vendor_part_number",
                    "vendor_revision",
                    "vendor_serial_number",
                ),
            ),
        ):
            for column in columns:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute(
            "UPDATE schema_metadata SET value = ? WHERE key = 'schema_version'",
            ("2026.07.24.device_credential_state",),
        )
        conn.commit()

    db.initialize()
    db.initialize()

    with db.connect() as conn:
        interface = conn.execute(
            "SELECT interface_name, link_status, admin_status, media_type "
            "FROM device_interfaces WHERE device_uuid = 'device-1'"
        ).fetchone()
        interface_history = conn.execute(
            "SELECT interface_name, link_status, physical_status "
            "FROM device_interfaces_history WHERE device_uuid = 'device-1'"
        ).fetchone()
        neighbor = conn.execute(
            "SELECT neighbor_sysname, chassis_id, ttl, pvid "
            "FROM device_lldp_neighbors WHERE device_uuid = 'device-1'"
        ).fetchone()
        optical = conn.execute(
            "SELECT interface_name, rx_power, module_vendor, device_vendor, "
            "vendor_part_number FROM device_optical_modules "
            "WHERE device_uuid = 'device-1'"
        ).fetchone()
        version = conn.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()["value"]

    assert dict(interface) == {
        "interface_name": "gei-0/3/0/2",
        "link_status": "UP",
        "admin_status": None,
        "media_type": None,
    }
    assert dict(interface_history) == {
        "interface_name": "gei-0/3/0/2",
        "link_status": "UP",
        "physical_status": None,
    }
    assert dict(neighbor) == {
        "neighbor_sysname": "OLD-NEIGHBOR",
        "chassis_id": None,
        "ttl": None,
        "pvid": None,
    }
    assert dict(optical) == {
        "interface_name": "gei-0/3/0/6",
        "rx_power": "-15.2",
        "module_vendor": "ZTRS",
        "device_vendor": None,
        "vendor_part_number": None,
    }
    assert version == CURRENT_SCHEMA_VERSION


def test_legacy_snmpv3_columns_are_ignored_and_preserved(tmp_path):
    db = Database(tmp_path / "devices.db")
    db.initialize()
    with db.connect() as conn:
        for column, column_type in (
            ("snmp_v3_enabled", "INTEGER DEFAULT 0"),
            ("snmp_rw_community", "TEXT"),
            ("snmpv3_auth_password", "TEXT"),
            ("snmpv3_priv_password", "TEXT"),
        ):
            conn.execute(f"ALTER TABLE devices ADD COLUMN {column} {column_type}")
        conn.execute(
            """
            INSERT INTO devices (
                device_uuid, name, primary_address, snmp_v2c_enabled,
                snmp_ro_community, snmp_v3_enabled, snmp_rw_community,
                snmpv3_auth_password, snmpv3_priv_password, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-snmp-device",
                "旧 SNMP 设备",
                "192.0.2.20",
                1,
                "readonly",
                1,
                "legacy-write",
                "legacy-auth",
                "legacy-priv",
                "2026-07-18T00:00:00",
                "2026-07-18T00:00:00",
            ),
        )
        conn.commit()

    repository = DeviceRepository(db)
    device = repository.get_by_uuid("legacy-snmp-device")
    assert device is not None
    assert device.snmp_v2c_enabled == 1
    assert device.snmp_ro_community == "readonly"
    assert not hasattr(device, "snmp_v3_enabled")

    device.name = "旧 SNMP 设备（已更新）"
    repository.update(device)
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT snmp_v3_enabled, snmp_rw_community,
                   snmpv3_auth_password, snmpv3_priv_password
            FROM devices WHERE device_uuid = ?
            """,
            ("legacy-snmp-device",),
        ).fetchone()

    assert dict(row) == {
        "snmp_v3_enabled": 1,
        "snmp_rw_community": "legacy-write",
        "snmpv3_auth_password": "legacy-auth",
        "snmpv3_priv_password": "legacy-priv",
    }


def test_database_initialize_rejects_schema_without_metadata(tmp_path):
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

    with pytest.raises(DatabaseSchemaMismatchError, match="基础元数据|当前数据库结构"):
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
    assert any(device.snmp_v2c_enabled and device.snmp_ro_community for device in devices)
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
