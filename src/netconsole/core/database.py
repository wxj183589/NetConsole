from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import traceback
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from netconsole.core.device_credential_store import (
    DEVICE_CREDENTIAL_STATE_SCHEMA,
    repair_device_credential_states,
)
from netconsole.core.sqlite_utils import (
    DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
    DEFAULT_SQLITE_TIMEOUT_SECONDS,
    configure_sqlite_connection,
    connect_sqlite,
    initialize_sqlite_wal,
)
from netconsole.models.device_address import InvalidDeviceAddressError, normalize_ip_address


CURRENT_SCHEMA_VERSION = "2026.08.03.fit_ap_association_verbose"

DEVICE_CLASSIFICATION_COLUMNS = (
    "project_phase",
    "work_scope_status",
    "work_scope_reason",
    "work_scope_updated_at",
    "work_scope_updated_by",
)
DEVICE_CLASSIFICATION_INDEXES = (
    "idx_devices_work_scope_status",
    "idx_devices_project_phase",
)
TRACKSIDE_AP_LOCATION_COLUMNS = (
    "location_class",
    "participates_in_mainline",
    "location_class_source",
)
TRACKSIDE_AP_LOCATION_CLASSES = (
    "MAINLINE",
    "DEPOT",
    "PARKING_YARD",
    "STABLING",
    "DEPOT_CONNECTION",
    "TEST_TRACK",
    "NON_MAINLINE",
    "UNKNOWN",
)
LEGACY_OPERATION_STATUS_VALUES = (
    "in_service",
    "not_integrated",
    "commissioning",
    "suspended",
    "retired",
)

_DATABASE_INITIALIZE_LOCKS: dict[str, threading.RLock] = {}
_DATABASE_INITIALIZE_LOCKS_GUARD = threading.Lock()


class DatabaseSchemaMismatchError(RuntimeError):
    """Raised when an existing database is not safe for additive schema updates."""


class DeviceAddressMigrationError(RuntimeError):
    """Raised when historical device addresses prevent a safe additive migration."""


SCHEMA_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Base-data optimistic locking must not hash the complete device database.  The
# counter is changed by SQLite triggers so direct writers and application
# transactions share the same revision boundary.
BASE_DATA_REVISION_SCHEMA = """
INSERT OR IGNORE INTO schema_metadata (key, value, created_at, updated_at)
VALUES (
    'base_data_revision',
    '0',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
);

CREATE TRIGGER IF NOT EXISTS trg_base_revision_ap_extension_points_insert
AFTER INSERT ON ap_extension_points
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_ap_extension_points_update
AFTER UPDATE ON ap_extension_points
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_ap_extension_points_delete
AFTER DELETE ON ap_extension_points
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_devices_insert
AFTER INSERT ON devices
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_devices_update
AFTER UPDATE ON devices
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_devices_delete
AFTER DELETE ON devices
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_device_groups_insert
AFTER INSERT ON device_groups
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_device_groups_update
AFTER UPDATE ON device_groups
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_device_groups_delete
AFTER DELETE ON device_groups
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_ac_trackside_ap_plan_insert
AFTER INSERT ON ac_trackside_ap_plan
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_ac_trackside_ap_plan_update
AFTER UPDATE ON ac_trackside_ap_plan
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_ac_trackside_ap_plan_delete
AFTER DELETE ON ac_trackside_ap_plan
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_ac_trackside_ap_plan_settings_insert
AFTER INSERT ON ac_trackside_ap_plan_settings
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_ac_trackside_ap_plan_settings_update
AFTER UPDATE ON ac_trackside_ap_plan_settings
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_ac_trackside_ap_plan_settings_delete
AFTER DELETE ON ac_trackside_ap_plan_settings
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_plans_insert
AFTER INSERT ON rail_ap_vlan_plans
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_plans_update
AFTER UPDATE ON rail_ap_vlan_plans
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_plans_delete
AFTER DELETE ON rail_ap_vlan_plans
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_groups_insert
AFTER INSERT ON rail_ap_vlan_groups
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_groups_update
AFTER UPDATE ON rail_ap_vlan_groups
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_groups_delete
AFTER DELETE ON rail_ap_vlan_groups
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_group_members_insert
AFTER INSERT ON rail_ap_vlan_group_members
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_group_members_update
AFTER UPDATE ON rail_ap_vlan_group_members
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_group_members_delete
AFTER DELETE ON rail_ap_vlan_group_members
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_group_assignments_insert
AFTER INSERT ON rail_ap_vlan_assignments
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_group_assignments_update
AFTER UPDATE ON rail_ap_vlan_assignments
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_group_assignments_delete
AFTER DELETE ON rail_ap_vlan_assignments
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;

CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_allocations_insert
AFTER INSERT ON rail_ap_vlan_allocations
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_allocations_update
AFTER UPDATE ON rail_ap_vlan_allocations
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_ap_vlan_allocations_delete
AFTER DELETE ON rail_ap_vlan_allocations
BEGIN
    UPDATE schema_metadata
    SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT),
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE key = 'base_data_revision';
END;
"""

DEVICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    system_name TEXT,
    mac_address TEXT,
    station TEXT,
    station_id TEXT NOT NULL DEFAULT '',
    location TEXT,
    group_id INTEGER,
    device_vendor TEXT NOT NULL DEFAULT 'H3C',
    device_type TEXT,
    project_phase TEXT NOT NULL DEFAULT 'unspecified'
        CHECK(project_phase IN ('phase_1', 'phase_2', 'phase_3', 'other', 'unspecified')),
    work_scope_status TEXT NOT NULL DEFAULT 'included'
        CHECK(work_scope_status IN ('included', 'excluded')),
    work_scope_reason TEXT,
    work_scope_updated_at TEXT,
    work_scope_updated_by TEXT,
    primary_address TEXT NOT NULL,
    normalized_primary_address TEXT,
    backup_address TEXT,
    protocol TEXT DEFAULT 'SSH',
    port INTEGER DEFAULT 22,
    username TEXT,
    password TEXT,
    ssh_enabled INTEGER DEFAULT 1,
    ssh_port INTEGER DEFAULT 22,
    telnet_enabled INTEGER DEFAULT 0,
    telnet_port INTEGER DEFAULT 23,
    ssh_username TEXT,
    ssh_password TEXT,
    telnet_username TEXT,
    telnet_password TEXT,
    snmp_enabled INTEGER DEFAULT 1,
    snmp_v1_enabled INTEGER DEFAULT 0,
    snmp_v2c_enabled INTEGER DEFAULT 1,
    snmp_port INTEGER DEFAULT 161,
    snmp_ro_community TEXT,
    snmp_timeout_ms INTEGER DEFAULT 2000,
    snmp_retries INTEGER DEFAULT 1,
    https_port INTEGER,
    tunnel_enabled INTEGER DEFAULT 0,
    tunnel1_enabled INTEGER DEFAULT 0,
    tunnel1_host TEXT,
    tunnel1_port INTEGER DEFAULT 22,
    tunnel1_username TEXT,
    tunnel1_password TEXT,
    tunnel1_local_port_mode TEXT DEFAULT 'auto',
    tunnel1_local_port INTEGER,
    tunnel2_enabled INTEGER DEFAULT 0,
    tunnel2_host TEXT,
    tunnel2_port INTEGER DEFAULT 22,
    tunnel2_username TEXT,
    tunnel2_password TEXT,
    tunnel2_local_port_mode TEXT DEFAULT 'auto',
    tunnel2_local_port INTEGER,
    remark TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

DEVICE_PRIMARY_ADDRESS_INDEX_SCHEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_normalized_primary_address
    ON devices(normalized_primary_address)
    WHERE normalized_primary_address IS NOT NULL
      AND normalized_primary_address <> '';
"""

COLLECT_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS collect_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collect_run_uuid TEXT NOT NULL UNIQUE,
    collect_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    raw_log_dir TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);
"""

DEVICE_FACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL UNIQUE,
    sysname TEXT,
    model TEXT,
    serial_number TEXT,
    mac_address TEXT,
    software_version TEXT,
    bootrom_version TEXT,
    vendor TEXT,
    uptime TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL
);
"""

DEVICE_INTERFACES_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_interfaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    link_status TEXT,
    admin_status TEXT,
    physical_status TEXT,
    protocol_status TEXT,
    media_attribute TEXT,
    media_type TEXT,
    category TEXT,
    speed TEXT,
    duplex TEXT,
    interface_type TEXT,
    port_status TEXT,
    port_mode TEXT,
    pvid TEXT,
    native_vlan TEXT,
    tagged_vlans TEXT,
    untagged_vlans TEXT,
    pvid_source TEXT,
    pvid_verified INTEGER,
    vlan_config_status TEXT,
    vlan_config_collected_at TEXT,
    vlan_warnings TEXT,
    description TEXT,
    ip_address TEXT,
    mac_address TEXT,
    vlan TEXT,
    last_change TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(device_uuid, interface_name)
);
"""

DEVICE_OPTICAL_MODULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_optical_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    rx_power TEXT,
    tx_power TEXT,
    temperature TEXT,
    voltage TEXT,
    bias_current TEXT,
    module_model TEXT,
    module_serial_number TEXT,
    module_vendor TEXT,
    wavelength TEXT,
    transmission_distance TEXT,
    connector_type TEXT,
    device_vendor TEXT,
    device_reported_status TEXT,
    threshold_source TEXT,
    transceiver_mode TEXT,
    vendor_part_number TEXT,
    vendor_revision TEXT,
    vendor_serial_number TEXT,
    rx_low_alarm TEXT,
    rx_high_alarm TEXT,
    tx_low_alarm TEXT,
    tx_high_alarm TEXT,
    rx_low_warning TEXT,
    rx_high_warning TEXT,
    tx_low_warning TEXT,
    tx_high_warning TEXT,
    status TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL
);
"""

DEVICE_LLDP_NEIGHBORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_lldp_neighbors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    local_interface TEXT NOT NULL,
    scope TEXT,
    chassis_type TEXT,
    chassis_id TEXT,
    neighbor_sysname TEXT,
    neighbor_mac TEXT,
    port_id_type TEXT,
    neighbor_interface TEXT,
    neighbor_ip TEXT,
    holdtime INTEGER,
    ttl INTEGER,
    port_description TEXT,
    system_description TEXT,
    system_capabilities TEXT,
    pvid INTEGER,
    operational_mau TEXT,
    max_frame_size INTEGER,
    neighbor_device_uuid TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL
);
"""

DEVICE_FACTS_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_facts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    sysname TEXT,
    model TEXT,
    serial_number TEXT,
    mac_address TEXT,
    software_version TEXT,
    bootrom_version TEXT,
    vendor TEXT,
    uptime TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL
);
"""

DEVICE_INTERFACES_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_interfaces_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    link_status TEXT,
    admin_status TEXT,
    physical_status TEXT,
    protocol_status TEXT,
    media_attribute TEXT,
    media_type TEXT,
    category TEXT,
    speed TEXT,
    duplex TEXT,
    interface_type TEXT,
    port_status TEXT,
    port_mode TEXT,
    pvid TEXT,
    native_vlan TEXT,
    tagged_vlans TEXT,
    untagged_vlans TEXT,
    pvid_source TEXT,
    pvid_verified INTEGER,
    vlan_config_status TEXT,
    vlan_config_collected_at TEXT,
    vlan_warnings TEXT,
    description TEXT,
    ip_address TEXT,
    mac_address TEXT,
    vlan TEXT,
    last_change TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_device_interfaces_history_device_interface_time
    ON device_interfaces_history(device_uuid, interface_name, collected_at DESC, id DESC);
"""

DEVICE_OPTICAL_MODULES_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_optical_modules_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    rx_power TEXT,
    tx_power TEXT,
    temperature TEXT,
    voltage TEXT,
    bias_current TEXT,
    module_model TEXT,
    module_serial_number TEXT,
    module_vendor TEXT,
    wavelength TEXT,
    transmission_distance TEXT,
    connector_type TEXT,
    device_vendor TEXT,
    device_reported_status TEXT,
    threshold_source TEXT,
    transceiver_mode TEXT,
    vendor_part_number TEXT,
    vendor_revision TEXT,
    vendor_serial_number TEXT,
    rx_low_alarm TEXT,
    rx_high_alarm TEXT,
    tx_low_alarm TEXT,
    tx_high_alarm TEXT,
    rx_low_warning TEXT,
    rx_high_warning TEXT,
    tx_low_warning TEXT,
    tx_high_warning TEXT,
    status TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_device_optical_history_device_interface_time
    ON device_optical_modules_history(device_uuid, interface_name, collected_at DESC, id DESC);
"""

DEVICE_LLDP_NEIGHBORS_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_lldp_neighbors_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    local_interface TEXT NOT NULL,
    scope TEXT,
    chassis_type TEXT,
    chassis_id TEXT,
    neighbor_sysname TEXT,
    neighbor_mac TEXT,
    port_id_type TEXT,
    neighbor_interface TEXT,
    neighbor_ip TEXT,
    holdtime INTEGER,
    ttl INTEGER,
    port_description TEXT,
    system_description TEXT,
    system_capabilities TEXT,
    pvid INTEGER,
    operational_mau TEXT,
    max_frame_size INTEGER,
    neighbor_device_uuid TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_device_lldp_history_device_interface_time
    ON device_lldp_neighbors_history(device_uuid, local_interface, collected_at DESC, id DESC);
"""

AC_AP_SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_ap_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL UNIQUE,
    total_aps INTEGER,
    online_aps INTEGER,
    offline_aps INTEGER,
    total_ap_licenses INTEGER,
    local_ap_licenses INTEGER,
    remaining_local_ap_licenses INTEGER,
    cpu_usage TEXT,
    cpu_5s INTEGER,
    cpu_1m INTEGER,
    cpu_5m INTEGER,
    memory_usage TEXT,
    memory_total INTEGER,
    memory_used INTEGER,
    memory_free INTEGER,
    memory_free_ratio REAL,
    model TEXT,
    serial_number TEXT,
    software_version TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL
);
"""

AC_FIT_AP_RESOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL UNIQUE,
    ap_name TEXT,
    apid TEXT,
    ap_ip TEXT,
    ap_mac TEXT,
    model TEXT,
    serial_number TEXT,
    state TEXT,
    state_raw TEXT,
    state_display TEXT,
    group_name TEXT,
    online_time TEXT,
    connection_ip TEXT,
    connection_state TEXT,
    connection_time TEXT,
    site TEXT,
    mileage TEXT,
    location_note TEXT,
    direction TEXT,
    rid1_status TEXT,
    rid1_mode TEXT,
    rid1_band TEXT,
    rid1_channel TEXT,
    rid1_bandwidth TEXT,
    rid1_usage TEXT,
    rid1_tx_power TEXT,
    rid1_clients INTEGER,
    rid2_status TEXT,
    rid2_mode TEXT,
    rid2_band TEXT,
    rid2_channel TEXT,
    rid2_bandwidth TEXT,
    rid2_usage TEXT,
    rid2_tx_power TEXT,
    rid2_clients INTEGER,
    rid3_status TEXT,
    rid3_mode TEXT,
    rid3_band TEXT,
    rid3_channel TEXT,
    rid3_bandwidth TEXT,
    rid3_usage TEXT,
    rid3_tx_power TEXT,
    rid3_clients INTEGER,
    rid1_bbssid TEXT,
    rid2_bbssid TEXT,
    rid3_bbssid TEXT,
    lldp_neighbor TEXT,
    lldp_source TEXT,
    lldp_confidence INTEGER,
    lldp_collected_at TEXT,
    lldp_local_interface TEXT,
    lldp_local_interface_normalized TEXT,
    lldp_neighbor_name TEXT,
    lldp_neighbor_mac TEXT,
    lldp_neighbor_mac_normalized TEXT,
    lldp_neighbor_interface TEXT,
    lldp_match_status TEXT,
    optical_interface TEXT,
    optical_interface_normalized TEXT,
    optical_rx_power REAL,
    optical_tx_power REAL,
    optical_collected_at TEXT,
    optical_match_status TEXT,
    ap_optical_power TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL
);
"""

AC_FIT_AP_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ap_uuid TEXT NOT NULL UNIQUE,
    ap_name TEXT,
    site_name TEXT,
    station_id TEXT NOT NULL DEFAULT '',
    station_override_enabled INTEGER NOT NULL DEFAULT 0,
    station_override_source TEXT NOT NULL DEFAULT '',
    belong_type TEXT,
    belong_section TEXT,
    section_start_station TEXT,
    section_end_station TEXT,
    yard_name TEXT,
    area_name TEXT,
    mileage TEXT,
    location_note TEXT,
    direction TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

AC_FIT_AP_DETAILS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_details (
    ap_uuid TEXT PRIMARY KEY,
    ac_device_uuid TEXT NOT NULL,
    ap_name TEXT,
    ap_group_name TEXT,
    backup_type TEXT,
    ready_for_switchover TEXT,
    system_uptime TEXT,
    region_code TEXT,
    region_code_lock TEXT,
    hardware_version TEXT,
    software_version TEXT,
    boot_version TEXT,
    map_file TEXT,
    forwarding_mode TEXT,
    power_level TEXT,
    power_info TEXT,
    capwap_data_tunnel_status TEXT,
    discovery_type TEXT,
    last_reboot_reason TEXT,
    latest_ip_address TEXT,
    current_ac_ip TEXT,
    tunnel_down_reason TEXT,
    connection_count TEXT,
    control_tunnel_encryption_state TEXT,
    data_tunnel_encryption_state TEXT,
    remote_configuration TEXT,
    energy_saving_level TEXT,
    ap_type TEXT,
    extra_fields_json TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_details_ac ON ac_fit_ap_details(ac_device_uuid, updated_at DESC);
"""

AC_FIT_AP_RADIO_DETAILS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_radio_details (
    ap_uuid TEXT NOT NULL,
    radio_id INTEGER NOT NULL,
    base_bssid TEXT,
    state TEXT,
    radio_type TEXT,
    antenna_type TEXT,
    channel_bandwidth TEXT,
    operating_bandwidth TEXT,
    secondary_channel_mode TEXT,
    mimo TEXT,
    channel TEXT,
    channel_mode TEXT,
    channel_usage TEXT,
    max_power TEXT,
    noise_floor TEXT,
    distance TEXT,
    beacon_interval TEXT,
    protection_mode TEXT,
    twt_negotiation TEXT,
    radar_detect TEXT,
    extra_fields_json TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(ap_uuid, radio_id)
);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_radio_details_ap ON ac_fit_ap_radio_details(ap_uuid, radio_id);
"""

AC_FIT_AP_RESOURCE_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_resource_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT,
    ap_mac TEXT,
    ap_ip TEXT,
    serial_number TEXT,
    state_raw TEXT,
    state_display TEXT,
    site_name TEXT,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fit_ap_resource_history_ac_time
    ON ac_fit_ap_resource_history(ac_device_uuid, collected_at DESC, id DESC);
"""

AP_EXTENSION_POINTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_extension_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT,
    line_name TEXT,
    system_type TEXT,
    network_domain TEXT,
    belong_type TEXT,
    station_id TEXT NOT NULL DEFAULT '',
    station_name TEXT,
    section_id TEXT NOT NULL DEFAULT '',
    section_name TEXT,
    section_start_station TEXT,
    section_end_station TEXT,
    yard_name TEXT,
    area_name TEXT,
    line_side TEXT,
    direction TEXT,
    location_class TEXT NOT NULL DEFAULT 'MAINLINE',
    participates_in_mainline INTEGER NOT NULL DEFAULT 1,
    location_class_source TEXT NOT NULL DEFAULT 'DEFAULT_MAINLINE',
    mileage_text TEXT,
    mileage_m REAL,
    distance_to_prev_m REAL,
    ap_point_code TEXT,
    ap_name TEXT,
    ap_vendor TEXT,
    ap_mac_norm TEXT,
    ap_mac_display TEXT,
    curve_radius_m REAL,
    curve_start_text TEXT,
    curve_start_m REAL,
    curve_end_text TEXT,
    curve_end_m REAL,
    curve_flag INTEGER DEFAULT 0,
    curve_impact_level TEXT,
    interval_risk_level TEXT,
    interval_risk_reason TEXT,
    install_scene TEXT,
    power_station TEXT,
    power_distribution TEXT,
    fiber_access_station TEXT,
    fiber_distribution TEXT,
    uplink_switch TEXT,
    uplink_port TEXT,
    optical_port TEXT,
    location_desc TEXT,
    remark TEXT,
    source_file TEXT,
    source_sheet TEXT,
    source_row INTEGER,
    import_batch_id TEXT,
    raw_payload_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ap_extension_points_mac
    ON ap_extension_points(ap_mac_norm);
CREATE INDEX IF NOT EXISTS idx_ap_extension_points_station
    ON ap_extension_points(station_name, line_side, mileage_m);
CREATE INDEX IF NOT EXISTS idx_ap_extension_points_section
    ON ap_extension_points(section_name);
CREATE INDEX IF NOT EXISTS idx_ap_extension_points_name
    ON ap_extension_points(ap_name);
"""

AP_EXTENSION_IMPORT_BATCHES_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_extension_import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT,
    source_file TEXT,
    template_type TEXT,
    system_type TEXT,
    network_domain TEXT,
    import_time TEXT NOT NULL,
    total_rows INTEGER DEFAULT 0,
    success_rows INTEGER DEFAULT 0,
    updated_rows INTEGER DEFAULT 0,
    skipped_rows INTEGER DEFAULT 0,
    error_rows INTEGER DEFAULT 0,
    operator TEXT,
    remark TEXT
);
"""

AC_FIT_AP_UNAUTHENTICATED_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_unauthenticated (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_name TEXT,
    apid TEXT,
    state TEXT,
    state_raw TEXT,
    state_display TEXT,
    model TEXT,
    serial_number TEXT,
    dev_type TEXT,
    work_mode TEXT,
    inferred_ap_mac TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_ac
    ON ac_fit_ap_unauthenticated(ac_device_uuid);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_serial
    ON ac_fit_ap_unauthenticated(serial_number);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_mac
    ON ac_fit_ap_unauthenticated(inferred_ap_mac);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_name
    ON ac_fit_ap_unauthenticated(ap_name);
"""

AC_FIT_AP_UNAUTHENTICATED_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_unauthenticated_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_name TEXT,
    apid TEXT,
    state TEXT,
    state_raw TEXT,
    state_display TEXT,
    model TEXT,
    serial_number TEXT,
    dev_type TEXT,
    work_mode TEXT,
    inferred_ap_mac TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    collected_at TEXT NOT NULL,
    updated_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_history_ac
    ON ac_fit_ap_unauthenticated_history(ac_device_uuid, collected_at);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_history_serial
    ON ac_fit_ap_unauthenticated_history(serial_number);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_unauth_history_mac
    ON ac_fit_ap_unauthenticated_history(inferred_ap_mac);
"""

AC_FIT_AP_UNAUTHENTICATED_SUMMARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_unauthenticated_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL UNIQUE,
    total_aps INTEGER,
    connected_aps INTEGER,
    connected_manual_aps INTEGER,
    connected_auto_aps INTEGER,
    connected_common_aps INTEGER,
    connected_wtus INTEGER,
    inside_aps INTEGER,
    maximum_supported_aps INTEGER,
    remaining_aps INTEGER,
    total_ap_licenses INTEGER,
    local_ap_licenses INTEGER,
    server_ap_licenses INTEGER,
    remaining_local_ap_licenses INTEGER,
    sync_ap_licenses INTEGER,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

AC_FIT_AP_OPTICAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_optical (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT NOT NULL,
    ap_mac TEXT,
    ap_ip TEXT,
    site TEXT,
    lldp_neighbor TEXT,
    lldp_source TEXT,
    lldp_confidence INTEGER,
    lldp_collected_at TEXT,
    lldp_local_interface TEXT,
    lldp_local_interface_normalized TEXT,
    lldp_neighbor_name TEXT,
    lldp_neighbor_mac TEXT,
    lldp_neighbor_mac_normalized TEXT,
    lldp_neighbor_interface TEXT,
    lldp_match_status TEXT,
    neighbor_interface TEXT,
    neighbor_mac TEXT,
    neighbor_device_name TEXT,
    optical_interface TEXT,
    optical_interface_normalized TEXT,
    link_match_status TEXT,
    source TEXT,
    neighbor_name TEXT,
    neighbor_rx_power TEXT,
    interface_name TEXT,
    temperature TEXT,
    voltage TEXT,
    bias_current TEXT,
    tx_power TEXT,
    rx_power TEXT,
    rx_low_alarm TEXT,
    rx_high_alarm TEXT,
    tx_low_alarm TEXT,
    tx_high_alarm TEXT,
    rx_low_warning TEXT,
    rx_high_warning TEXT,
    tx_low_warning TEXT,
    tx_high_warning TEXT,
    optical_alarm_status TEXT,
    status TEXT,
    error_message TEXT,
    module_model TEXT,
    module_serial_number TEXT,
    module_vendor TEXT,
    wavelength TEXT,
    transmission_distance TEXT,
    connector_type TEXT,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_optical_mac_lookup
    ON ac_fit_ap_optical(
        replace(replace(replace(lower(COALESCE(ap_mac, '')), ':', ''), '-', ''), ' ', '')
    );
"""

AC_STATION_AP_CAPACITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_station_ap_capacity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL UNIQUE,
    ap_total INTEGER NOT NULL,
    remark TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""

AC_TRACKSIDE_AP_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_trackside_ap_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    station_id TEXT NOT NULL DEFAULT '',
    sequence_no INTEGER NOT NULL DEFAULT 0,
    station_name TEXT NOT NULL,
    ap_count INTEGER NOT NULL DEFAULT 0,
    ap_start_address TEXT,
    subnet_mask TEXT NOT NULL DEFAULT '',
    mask_length INTEGER,
    ap_gateway TEXT,
    management_vlan INTEGER,
    ap_management_vlans TEXT NOT NULL,
    remark TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(mode, station_name),
    CHECK (sequence_no >= 0),
    CHECK (management_vlan IS NULL OR management_vlan BETWEEN 1 AND 4094)
);
"""

AC_TRACKSIDE_AP_PLAN_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_trackside_ap_plan_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

AP_MANAGEMENT_VLAN_PLANNING_SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_ap_vlan_plans (
    line_id TEXT PRIMARY KEY,
    planning_mode TEXT NOT NULL,
    auto_group_station_count INTEGER NOT NULL DEFAULT 1,
    address_allocation_strategy TEXT NOT NULL DEFAULT 'station_then_point',
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (planning_mode IN ('line_single', 'station_independent', 'station_grouped')),
    CHECK (auto_group_station_count BETWEEN 1 AND 4),
    CHECK (revision >= 1)
);
"""

AP_MANAGEMENT_VLAN_GROUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_ap_vlan_groups (
    group_id TEXT PRIMARY KEY,
    line_id TEXT NOT NULL,
    group_code TEXT NOT NULL,
    group_name TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    management_vlan INTEGER,
    legacy_management_vlans TEXT NOT NULL DEFAULT '',
    network_address TEXT NOT NULL DEFAULT '',
    prefix_length INTEGER,
    subnet_mask TEXT NOT NULL DEFAULT '',
    default_gateway TEXT NOT NULL DEFAULT '',
    ap_start_ip TEXT NOT NULL DEFAULT '',
    ap_end_ip TEXT NOT NULL DEFAULT '',
    address_allocation_strategy TEXT NOT NULL DEFAULT 'station_then_point',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (line_id) REFERENCES rail_ap_vlan_plans(line_id) ON DELETE CASCADE,
    UNIQUE (line_id, group_code),
    UNIQUE (line_id, sequence),
    CHECK (management_vlan IS NULL OR management_vlan BETWEEN 1 AND 4094),
    CHECK (prefix_length IS NULL OR prefix_length BETWEEN 0 AND 32)
);
CREATE INDEX IF NOT EXISTS idx_rail_ap_vlan_groups_line_sequence
    ON rail_ap_vlan_groups(line_id, sequence);
"""

AP_MANAGEMENT_VLAN_GROUP_MEMBER_SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_ap_vlan_group_members (
    group_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    station_name TEXT NOT NULL,
    station_sequence INTEGER NOT NULL,
    ap_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (group_id, station_id),
    FOREIGN KEY (group_id) REFERENCES rail_ap_vlan_groups(group_id) ON DELETE CASCADE,
    UNIQUE (station_id),
    CHECK (ap_count >= 0)
);
CREATE INDEX IF NOT EXISTS idx_rail_ap_vlan_members_station_name
    ON rail_ap_vlan_group_members(station_name);
"""

AP_MANAGEMENT_VLAN_ASSIGNMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_ap_vlan_assignments (
    assignment_id TEXT PRIMARY KEY,
    assignment_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (group_id) REFERENCES rail_ap_vlan_groups(group_id) ON DELETE CASCADE,
    UNIQUE (assignment_type, target_id),
    CHECK (assignment_type IN ('section_default', 'interval_default', 'ap_override'))
);
CREATE INDEX IF NOT EXISTS idx_rail_ap_vlan_assignments_target
    ON rail_ap_vlan_assignments(target_id);
"""

AP_MANAGEMENT_VLAN_ALLOCATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_ap_vlan_allocations (
    ap_id TEXT PRIMARY KEY,
    ap_name TEXT NOT NULL DEFAULT '',
    point_code TEXT NOT NULL DEFAULT '',
    station_id TEXT NOT NULL DEFAULT '',
    station_name TEXT NOT NULL DEFAULT '',
    section_name TEXT NOT NULL DEFAULT '',
    group_id TEXT NOT NULL,
    planned_ip TEXT NOT NULL,
    allocation_order INTEGER NOT NULL,
    is_manual INTEGER NOT NULL DEFAULT 0,
    is_locked INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    group_source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (group_id) REFERENCES rail_ap_vlan_groups(group_id) ON DELETE CASCADE,
    CHECK (is_manual IN (0, 1)),
    CHECK (is_locked IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_rail_ap_vlan_allocations_group_order
    ON rail_ap_vlan_allocations(group_id, allocation_order);
"""

AC_STATION_ONLINE_SUMMARY_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_station_online_summary_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    ap_total INTEGER NOT NULL,
    online_count INTEGER NOT NULL,
    offline_count INTEGER NOT NULL,
    online_rate TEXT,
    remark TEXT,
    collected_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

AC_FIT_AP_OPTICAL_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_optical_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT,
    ap_mac TEXT,
    ap_ip TEXT,
    site TEXT,
    lldp_neighbor TEXT,
    lldp_local_interface TEXT,
    lldp_local_interface_normalized TEXT,
    lldp_neighbor_name TEXT,
    lldp_neighbor_mac TEXT,
    lldp_neighbor_mac_normalized TEXT,
    lldp_neighbor_interface TEXT,
    link_match_status TEXT,
    source TEXT,
    session_id TEXT,
    neighbor_interface TEXT,
    neighbor_mac TEXT,
    neighbor_device_name TEXT,
    neighbor_rx_power TEXT,
    interface_name TEXT,
    temperature TEXT,
    voltage TEXT,
    bias_current TEXT,
    tx_power TEXT,
    rx_power TEXT,
    rx_low_alarm TEXT,
    rx_high_alarm TEXT,
    tx_low_alarm TEXT,
    tx_high_alarm TEXT,
    rx_low_warning TEXT,
    rx_high_warning TEXT,
    tx_low_warning TEXT,
    tx_high_warning TEXT,
    optical_alarm_status TEXT,
    status TEXT,
    error_message TEXT,
    module_model TEXT,
    module_serial_number TEXT,
    module_vendor TEXT,
    wavelength TEXT,
    transmission_distance TEXT,
    connector_type TEXT,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fit_ap_optical_history_ap_time
    ON ac_fit_ap_optical_history(ap_uuid, collected_at DESC, id DESC);
"""

AC_FIT_AP_LLDP_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_lldp_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT,
    ap_mac TEXT,
    source TEXT,
    local_interface TEXT,
    local_interface_normalized TEXT,
    lldp_neighbor TEXT,
    neighbor_interface TEXT,
    neighbor_mac TEXT,
    neighbor_mac_normalized TEXT,
    neighbor_device_name TEXT,
    neighbor_name TEXT,
    session_id TEXT,
    is_changed INTEGER DEFAULT 1,
    conflict_flag INTEGER DEFAULT 0,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fit_ap_lldp_history_ap_time
    ON ac_fit_ap_lldp_history(ap_uuid, collected_at DESC, id DESC);
"""

AC_FIT_AP_RADIO_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_radio_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT,
    rid INTEGER,
    status TEXT,
    mode TEXT,
    band TEXT,
    channel TEXT,
    bandwidth TEXT,
    usage TEXT,
    tx_power TEXT,
    clients INTEGER,
    bbssid TEXT,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fit_ap_radio_history_ap_time
    ON ac_fit_ap_radio_history(ap_uuid, collected_at DESC, id DESC);
"""

AP_ENTITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ap_uuid TEXT NOT NULL UNIQUE,
    site_id TEXT,
    ac_device_uuid TEXT,
    ap_name TEXT,
    ap_mac TEXT,
    ap_id TEXT,
    ap_ip TEXT,
    serial_number TEXT,
    model TEXT,
    group_name TEXT,
    mode TEXT,
    state TEXT,
    state_raw TEXT,
    state_display TEXT,
    station TEXT,
    milestone TEXT,
    direction TEXT,
    location_note TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    last_online_at TEXT,
    last_resource_update_at TEXT,
    is_offline INTEGER DEFAULT 0,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ap_entities_site_mac
    ON ap_entities(site_id, ap_mac)
    WHERE ap_mac IS NOT NULL AND trim(ap_mac) != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_ap_entities_site_serial
    ON ap_entities(site_id, serial_number)
    WHERE serial_number IS NOT NULL AND trim(serial_number) != '';
DROP INDEX IF EXISTS idx_ap_entities_site_ac_apid;
DROP INDEX IF EXISTS idx_ap_entities_site_ac_name;
CREATE INDEX IF NOT EXISTS idx_ap_entities_site_ac_apid_lookup
    ON ap_entities(site_id, ac_device_uuid, ap_id);
CREATE INDEX IF NOT EXISTS idx_ap_entities_site_ac_name_lookup
    ON ap_entities(site_id, ac_device_uuid, ap_name);
"""

AP_IDENTITY_INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_identity_entities (
    entity_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL DEFAULT 'current',
    effective_ap_name TEXT,
    effective_ap_mac_key TEXT,
    effective_ap_mac_display TEXT,
    effective_station TEXT,
    effective_section TEXT,
    effective_point_code TEXT,
    effective_serial_number TEXT,
    effective_location TEXT,
    effective_mileage TEXT,
    effective_direction TEXT,
    effective_belong_type TEXT,
    ac_ap_uuid TEXT,
    ac_device_uuid TEXT,
    ac_ap_name TEXT,
    ac_ap_mac_key TEXT,
    ac_station TEXT,
    ac_section TEXT,
    ac_updated_at TEXT,
    base_record_id TEXT,
    base_ap_name TEXT,
    base_ap_mac_key TEXT,
    base_station TEXT,
    base_section TEXT,
    base_updated_at TEXT,
    effective_source TEXT NOT NULL,
    identity_status TEXT NOT NULL,
    data_quality_warning TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ap_identity_entities_site_name
    ON ap_identity_entities(site_id, effective_ap_name);
CREATE INDEX IF NOT EXISTS idx_ap_identity_entities_site_mac
    ON ap_identity_entities(site_id, effective_ap_mac_key);
CREATE INDEX IF NOT EXISTS idx_ap_identity_entities_site_station
    ON ap_identity_entities(site_id, effective_station);

CREATE TABLE IF NOT EXISTS ap_identity_mac_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL DEFAULT 'current',
    entity_id TEXT NOT NULL,
    mac_key TEXT NOT NULL,
    mac_display TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    source TEXT NOT NULL,
    match_priority INTEGER NOT NULL,
    confidence INTEGER NOT NULL,
    radio_id INTEGER,
    derivation_rule TEXT,
    is_exact INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES ap_identity_entities(entity_id) ON DELETE CASCADE,
    UNIQUE(site_id, entity_id, mac_key, alias_type, source)
);
CREATE INDEX IF NOT EXISTS idx_ap_identity_mac_alias_lookup
    ON ap_identity_mac_aliases(site_id, mac_key, is_active, match_priority DESC);

CREATE TABLE IF NOT EXISTS ap_identity_h3c_prefixes (
    prefix_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL DEFAULT 'current',
    entity_id TEXT NOT NULL,
    base_mac_key TEXT NOT NULL,
    prefix_key TEXT NOT NULL,
    prefix_bits INTEGER NOT NULL DEFAULT 36,
    derivation_rule TEXT NOT NULL,
    source TEXT NOT NULL,
    match_priority INTEGER NOT NULL,
    confidence INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES ap_identity_entities(entity_id) ON DELETE CASCADE,
    UNIQUE(site_id, entity_id, base_mac_key, prefix_bits, source)
);
CREATE INDEX IF NOT EXISTS idx_ap_identity_h3c_prefix_lookup
    ON ap_identity_h3c_prefixes(
        site_id,
        prefix_bits,
        prefix_key,
        is_active,
        match_priority DESC
    );

CREATE TABLE IF NOT EXISTS ap_identity_conflicts (
    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL DEFAULT 'current',
    entity_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    ac_value TEXT,
    base_value TEXT,
    effective_source TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    details_json TEXT,
    FOREIGN KEY(entity_id) REFERENCES ap_identity_entities(entity_id) ON DELETE CASCADE,
    UNIQUE(site_id, entity_id, conflict_type)
);
CREATE INDEX IF NOT EXISTS idx_ap_identity_conflicts_site_active
    ON ap_identity_conflicts(site_id, resolved_at, conflict_type);

CREATE TABLE IF NOT EXISTS ap_identity_index_state (
    site_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    source_revision INTEGER NOT NULL DEFAULT -1,
    base_record_count INTEGER NOT NULL DEFAULT 0,
    ac_record_count INTEGER NOT NULL DEFAULT 0,
    entity_count INTEGER NOT NULL DEFAULT 0,
    alias_count INTEGER NOT NULL DEFAULT 0,
    prefix_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    actual_radio_alias_count INTEGER NOT NULL DEFAULT 0,
    actual_bssid_alias_count INTEGER NOT NULL DEFAULT 0,
    actual_bbssid_alias_count INTEGER NOT NULL DEFAULT 0,
    derived_alias_count INTEGER NOT NULL DEFAULT 0,
    ambiguous_alias_count INTEGER NOT NULL DEFAULT 0,
    build_duration_ms REAL NOT NULL DEFAULT 0,
    diagnostics_json TEXT,
    build_reason TEXT,
    built_at TEXT NOT NULL
);
INSERT OR IGNORE INTO ap_identity_index_state (
    site_id, revision, base_record_count, ac_record_count,
    entity_count, alias_count, prefix_count, conflict_count,
    build_reason, built_at
)
VALUES ('current', 0, 0, 0, 0, 0, 0, 0, 'schema_initialized', '');
"""

AP_RESOURCE_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_resource_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_uuid TEXT NOT NULL UNIQUE,
    ap_uuid TEXT NOT NULL,
    ac_device_uuid TEXT,
    collected_at TEXT,
    ap_name TEXT,
    ap_mac TEXT,
    ap_id TEXT,
    ap_ip TEXT,
    serial_number TEXT,
    model TEXT,
    group_name TEXT,
    state TEXT,
    state_raw TEXT,
    online_time TEXT,
    clients TEXT,
    mode TEXT,
    station TEXT,
    raw_source_type TEXT,
    created_at TEXT NOT NULL
);
"""


def _ap_identity_source_revision_schema() -> str:
    tables = (
        "ap_extension_points",
        "ac_fit_ap_resources",
        "ac_fit_ap_radio_history",
        "ac_fit_ap_lldp_history",
        "ac_fit_ap_metadata",
        "ap_entities",
        "ac_fit_ap_optical",
        "trackside_ap_view_cache",
    )
    statements = [
        """
CREATE TABLE IF NOT EXISTS ap_identity_source_state (
    site_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
INSERT OR IGNORE INTO ap_identity_source_state(site_id, revision, updated_at)
VALUES ('current', 0, '');
"""
    ]
    for table in tables:
        safe_name = table.replace("_", "")
        for action in ("INSERT", "UPDATE", "DELETE"):
            statements.append(
                f"""
CREATE TRIGGER IF NOT EXISTS trg_ap_identity_source_{safe_name}_{action.lower()}
AFTER {action} ON {table}
BEGIN
    UPDATE ap_identity_source_state
    SET revision = revision + 1,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE site_id = 'current';
END;
"""
            )
    statements.append(
        """
DROP TRIGGER IF EXISTS trg_ap_identity_source_devices_insert;
DROP TRIGGER IF EXISTS trg_ap_identity_source_devices_update;
DROP TRIGGER IF EXISTS trg_ap_identity_source_devices_delete;
DROP TRIGGER IF EXISTS trg_ap_identity_source_devicefacts_insert;
DROP TRIGGER IF EXISTS trg_ap_identity_source_devicefacts_update;
DROP TRIGGER IF EXISTS trg_ap_identity_source_devicefacts_delete;

CREATE TRIGGER trg_ap_identity_source_devices_insert
AFTER INSERT ON devices
WHEN EXISTS (
    SELECT 1
    FROM ac_fit_ap_resources
    WHERE ac_device_uuid = NEW.device_uuid
)
BEGIN
    UPDATE ap_identity_source_state
    SET revision = revision + 1,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE site_id = 'current';
END;

CREATE TRIGGER trg_ap_identity_source_devices_update
AFTER UPDATE OF device_uuid, device_vendor ON devices
WHEN EXISTS (
    SELECT 1
    FROM ac_fit_ap_resources
    WHERE ac_device_uuid IN (OLD.device_uuid, NEW.device_uuid)
)
BEGIN
    UPDATE ap_identity_source_state
    SET revision = revision + 1,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE site_id = 'current';
END;

CREATE TRIGGER trg_ap_identity_source_devices_delete
AFTER DELETE ON devices
WHEN EXISTS (
    SELECT 1
    FROM ac_fit_ap_resources
    WHERE ac_device_uuid = OLD.device_uuid
)
BEGIN
    UPDATE ap_identity_source_state
    SET revision = revision + 1,
        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE site_id = 'current';
END;
"""
    )
    return "\n".join(statements)

AP_LLDP_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_lldp_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_uuid TEXT NOT NULL UNIQUE,
    ap_uuid TEXT NOT NULL,
    ap_mac TEXT,
    ap_name TEXT,
    serial_number TEXT,
    neighbor_switch_uuid TEXT,
    neighbor_switch_name TEXT,
    neighbor_switch_sysname TEXT,
    neighbor_switch_ip TEXT,
    neighbor_interface TEXT,
    collected_at TEXT,
    source_device_uuid TEXT,
    is_latest INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ap_lldp_history_latest
    ON ap_lldp_history(ap_uuid, is_latest, collected_at);
"""

AP_OPTICAL_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_optical_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_uuid TEXT NOT NULL UNIQUE,
    ap_uuid TEXT NOT NULL,
    side TEXT,
    device_uuid TEXT,
    interface_name TEXT,
    rx_power TEXT,
    tx_power TEXT,
    alarm_status TEXT,
    collected_at TEXT,
    data_source TEXT,
    is_latest INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ap_optical_history_latest
    ON ap_optical_history(ap_uuid, side, is_latest, collected_at);
"""

TRACKSIDE_AP_VIEW_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trackside_ap_view_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_uuid TEXT NOT NULL UNIQUE,
    site_id TEXT,
    station TEXT,
    switch_uuid TEXT,
    switch_name TEXT,
    switch_sysname TEXT,
    interface_name TEXT,
    port_type TEXT,
    port_description TEXT,
    pvid TEXT,
    vlan_list TEXT,
    switch_rx_power TEXT,
    switch_alarm_status TEXT,
    ap_uuid TEXT,
    ap_name TEXT,
    ap_mac TEXT,
    ap_rx_power TEXT,
    ap_alarm_status TEXT,
    ap_state TEXT,
    last_collected_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trackside_ap_view_cache_interface
    ON trackside_ap_view_cache(site_id, switch_uuid, interface_name);
"""

DEVICE_GROUPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_id, name)
);
"""

CONFIG_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS config_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER,
    device_uuid TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    hash TEXT NOT NULL,
    raw_log_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);
"""


def _normalized_trackside_ap_location_class(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    aliases = {
        "MAINLINE": "MAINLINE",
        "正线": "MAINLINE",
        "DEPOT": "DEPOT",
        "车辆段": "DEPOT",
        "场段": "DEPOT",
        "PARKING_YARD": "PARKING_YARD",
        "PARKING_LOT": "PARKING_YARD",
        "停车场": "PARKING_YARD",
        "STABLING": "STABLING",
        "STORAGE_TRACK": "STABLING",
        "存车线": "STABLING",
        "DEPOT_CONNECTION": "DEPOT_CONNECTION",
        "出入段线": "DEPOT_CONNECTION",
        "出段线": "DEPOT_CONNECTION",
        "入段线": "DEPOT_CONNECTION",
        "TEST_TRACK": "TEST_TRACK",
        "试车线": "TEST_TRACK",
        "NON_MAINLINE": "NON_MAINLINE",
        "非正线": "NON_MAINLINE",
        "UNKNOWN": "UNKNOWN",
        "未知": "UNKNOWN",
    }
    return aliases.get(text.upper(), aliases.get(text, "UNKNOWN"))


def _legacy_trackside_ap_location_class(row: dict[str, object]) -> str:
    belong_type = str(row.get("belong_type") or "").strip()
    explicit = _normalized_trackside_ap_location_class(belong_type)
    if belong_type.casefold() in {
        "depot",
        "parking_yard",
        "parking_lot",
        "stabling",
        "storage_track",
        "depot_connection",
        "test_track",
        "non_mainline",
    }:
        return explicit
    text = " ".join(
        str(row.get(field) or "").strip()
        for field in (
            "yard_name",
            "area_name",
            "station_name",
            "section_name",
            "install_scene",
            "location_desc",
        )
    )
    if any(token in text for token in ("出入段线", "出段线", "入段线", "出场线", "入场线")):
        return "DEPOT_CONNECTION"
    if "试车线" in text:
        return "TEST_TRACK"
    if "存车线" in text or "存车场" in text:
        return "STABLING"
    if "停车场" in text:
        return "PARKING_YARD"
    if "车辆段" in text:
        return "DEPOT"
    if "非正线" in text:
        return "NON_MAINLINE"
    return "MAINLINE"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, foreign_keys=True)

    def connect_readonly(self) -> sqlite3.Connection:
        """Open an existing database through SQLite's read-only URI mode.

        Read endpoints must not create a missing database or accidentally
        acquire a write transaction while projecting legacy data.
        """
        if not self.path.is_file():
            raise sqlite3.OperationalError(f"unable to open database file: {self.path}")
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=DEFAULT_SQLITE_TIMEOUT_SECONDS,
        )
        connection.row_factory = sqlite3.Row
        configure_sqlite_connection(
            connection,
            busy_timeout_ms=DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
            foreign_keys=True,
        )
        connection.execute("PRAGMA query_only = ON")
        return connection

    def initialize(self) -> None:
        with _database_initialize_lock(self.path):
            existed = self.exists()
            conn: sqlite3.Connection | None = None
            stage = "connect"
            backup_path: Path | None = None
            schema_version_before = ""
            address_migration = False
            classification_migration = False
            identity_schema_migration = False
            trackside_ap_location_migration = False
            rail_base_identity_migration = False
            try:
                conn = self.connect()
                stage = "configure"
                initialize_sqlite_wal(conn)
                if existed:
                    stage = "inspect"
                    schema_version_before = self._safe_schema_version(conn)
                    address_migration = self._requires_device_address_migration(conn)
                    classification_migration = self._requires_device_classification_migration(
                        conn
                    )
                    identity_schema_migration = self._requires_ap_identity_schema_migration(
                        conn
                    )
                    trackside_ap_location_migration = (
                        self._requires_trackside_ap_location_migration(conn)
                    )
                    rail_base_identity_migration = (
                        self._requires_rail_base_identity_migration(conn)
                    )
                    if (
                        address_migration
                        or classification_migration
                        or trackside_ap_location_migration
                        or rail_base_identity_migration
                    ):
                        stage = "backup"
                        backup_path = self._backup_before_device_migration(
                            conn,
                            "primary-address"
                            if address_migration
                            else "work-scope-status"
                            if classification_migration
                            else "trackside-ap-location"
                            if trackside_ap_location_migration
                            else "rail-base-identity-relations",
                        )
                stage = "schema"
                schema_scripts = (
                    self._schema_scripts_for_existing_database(conn)
                    if existed
                    else self._all_schema_scripts()
                )
                conn.executescript(
                    "BEGIN IMMEDIATE;\n" + "\n".join(schema_scripts)
                )
                stage = "additive_updates"
                self._apply_additive_schema_updates(conn)
                stage = "rail_base_master_identity_backfill"
                self._backfill_rail_base_master_ids(conn)
                stage = "classification_validation"
                self._validate_device_classification_migration(conn)
                stage = "trackside_ap_location_validation"
                self._validate_trackside_ap_location_migration(conn)
                stage = "rail_base_identity_validation"
                self._validate_rail_base_identity_migration(conn)
                stage = "ap_vlan_reference_migration"
                self._migrate_trackside_ap_vlan_allocation_references(conn)
                stage = "credential_state_repair"
                repair_device_credential_states(conn)
                stage = "integrity_check"
                requires_integrity_check = (
                    not existed
                    or address_migration
                    or classification_migration
                    or identity_schema_migration
                    or trackside_ap_location_migration
                    or rail_base_identity_migration
                    or schema_version_before != CURRENT_SCHEMA_VERSION
                )
                if requires_integrity_check:
                    self._assert_integrity(conn, "设备数据库迁移后完整性校验失败")
                stage = "schema_version"
                self._write_schema_version(conn)
                stage = "commit"
                conn.commit()
                # 初始化阶段产生的 WAL 必须在 Backend 对外提供只读 API 前落盘；
                # 否则首个 GET 关闭连接时可能触发延迟 checkpoint，表现为只读请求改写数据库文件。
                stage = "checkpoint"
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if existed and (
                    address_migration
                    or classification_migration
                    or trackside_ap_location_migration
                    or rail_base_identity_migration
                ):
                    self._log_migration_completed(
                        schema_version_before=schema_version_before,
                        backup_path=backup_path,
                        address_migration=address_migration,
                        classification_migration=classification_migration,
                        trackside_ap_location_migration=(
                            trackside_ap_location_migration
                        ),
                        rail_base_identity_migration=rail_base_identity_migration,
                        legacy_operation_status_counts=(
                            self._legacy_operation_status_counts(conn)
                            if classification_migration
                            else {}
                        ),
                    )
            except Exception as exc:
                if conn is not None:
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                self._log_initialize_failure(
                    exc,
                    conn=conn,
                    stage=stage,
                    backup_path=backup_path,
                    schema_version_before=schema_version_before,
                )
                raise
            finally:
                if conn is not None:
                    conn.close()

    def _schema_scripts_for_existing_database(self, conn: sqlite3.Connection) -> tuple[str, ...]:
        if not self._table_exists(conn, "schema_metadata"):
            raise DatabaseSchemaMismatchError(self._schema_mismatch_message())
        if (
            self._schema_version(conn) == CURRENT_SCHEMA_VERSION
            and not self._requires_device_address_migration(conn)
        ):
            return self._all_schema_scripts()
        self._assert_additive_update_safe(conn)
        return self._all_schema_scripts(
            include_device_address_index=not self._requires_device_address_migration(
                conn
            )
        )

    def _assert_additive_update_safe(self, conn: sqlite3.Connection) -> None:
        required_tables = {
            "devices",
            "device_groups",
            "ac_fit_ap_resources",
            "ap_entities",
            "schema_metadata",
        }
        missing = sorted(table for table in required_tables if not self._table_exists(conn, table))
        if missing:
            raise DatabaseSchemaMismatchError(self._schema_mismatch_message())

    def _apply_additive_schema_updates(self, conn: sqlite3.Connection) -> None:
        if self._requires_device_address_migration(conn):
            self._apply_device_address_migration(conn)

        if self._table_exists(conn, "ac_fit_ap_metadata"):
            metadata_columns = {
                "station_id": "TEXT NOT NULL DEFAULT ''",
                "station_override_enabled": "INTEGER NOT NULL DEFAULT 0",
                "station_override_source": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in metadata_columns.items():
                if not self._column_exists(conn, "ac_fit_ap_metadata", column):
                    conn.execute(
                        f"ALTER TABLE ac_fit_ap_metadata ADD COLUMN {column} {definition}"
                    )
            # Historical values came through the old free-text editor. Keep them
            # as explicit legacy manual data; never reinterpret them as auto links.
            conn.execute(
                """
                UPDATE ac_fit_ap_metadata
                SET station_override_enabled = 1,
                    station_override_source = 'legacy_manual'
                WHERE COALESCE(TRIM(site_name), '') != ''
                  AND COALESCE(TRIM(station_override_source), '') = ''
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_metadata_station_id "
                "ON ac_fit_ap_metadata(station_id)"
            )

        if self._table_exists(conn, "devices") and not self._column_exists(
            conn, "devices", "station_id"
        ):
            conn.execute(
                "ALTER TABLE devices ADD COLUMN station_id TEXT NOT NULL DEFAULT ''"
            )
        if self._table_exists(conn, "devices"):
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_devices_station_id ON devices(station_id)"
            )

        if self._table_exists(conn, "ap_extension_points"):
            for column in ("station_id", "section_id"):
                if not self._column_exists(conn, "ap_extension_points", column):
                    conn.execute(
                        f"ALTER TABLE ap_extension_points ADD COLUMN {column} "
                        "TEXT NOT NULL DEFAULT ''"
                    )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ap_extension_points_station_id "
                "ON ap_extension_points(station_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ap_extension_points_section_id "
                "ON ap_extension_points(section_id)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_base_station_id_unique "
                "ON ap_extension_points(station_id) "
                "WHERE belong_type = '__base_station__' AND station_id != ''"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_base_section_id_unique "
                "ON ap_extension_points(section_id) "
                "WHERE belong_type = '__base_section__' AND section_id != ''"
            )

        optical_columns = {
            "device_vendor": "TEXT",
            "device_reported_status": "TEXT",
            "threshold_source": "TEXT",
            "transceiver_mode": "TEXT",
            "vendor_part_number": "TEXT",
            "vendor_revision": "TEXT",
            "vendor_serial_number": "TEXT",
        }
        for table in ("device_optical_modules", "device_optical_modules_history"):
            for column, column_type in optical_columns.items():
                if self._table_exists(conn, table) and not self._column_exists(
                    conn, table, column
                ):
                    conn.execute(
                        f"ALTER {'TABLE'} {table} ADD COLUMN {column} {column_type}"
                    )

        work_scope_status_existed = self._column_exists(
            conn, "devices", "work_scope_status"
        )
        device_classification_columns = {
            "project_phase": (
                "TEXT NOT NULL DEFAULT 'unspecified' "
                "CHECK(project_phase IN ('phase_1', 'phase_2', 'phase_3', 'other', 'unspecified'))"
            ),
            "work_scope_status": (
                "TEXT NOT NULL DEFAULT 'included' "
                "CHECK(work_scope_status IN ('included', 'excluded'))"
            ),
            "work_scope_reason": "TEXT",
            "work_scope_updated_at": "TEXT",
            "work_scope_updated_by": "TEXT",
        }
        for column, definition in device_classification_columns.items():
            if not self._column_exists(conn, "devices", column):
                conn.execute(f"ALTER TABLE devices ADD COLUMN {column} {definition}")
        conn.execute(
            "UPDATE devices SET project_phase = 'unspecified' "
            "WHERE project_phase IS NULL OR TRIM(project_phase) = ''"
        )
        if (
            not work_scope_status_existed
            and self._column_exists(conn, "devices", "operation_status")
        ):
            self._validate_legacy_operation_status_values(conn)
            conn.execute(
                """
                UPDATE devices
                SET work_scope_status =
                    CASE LOWER(TRIM(COALESCE(operation_status, '')))
                        WHEN 'in_service' THEN 'included'
                        WHEN 'not_integrated' THEN 'excluded'
                        WHEN 'commissioning' THEN 'excluded'
                        WHEN 'suspended' THEN 'excluded'
                        WHEN 'retired' THEN 'excluded'
                        ELSE 'included'
                    END
                """
            )
            for current, legacy in (
                ("work_scope_reason", "operation_status_reason"),
                ("work_scope_updated_at", "operation_status_updated_at"),
                ("work_scope_updated_by", "operation_status_updated_by"),
            ):
                if self._column_exists(conn, "devices", legacy):
                    conn.execute(
                        f"UPDATE devices SET {current} = {legacy} "
                        f"WHERE {current} IS NULL"
                    )
        conn.execute(
            "UPDATE devices SET work_scope_status = 'included' "
            "WHERE work_scope_status IS NULL OR TRIM(work_scope_status) = ''"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_devices_work_scope_status "
            "ON devices(work_scope_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_devices_project_phase "
            "ON devices(project_phase)"
        )
        interface_columns = {
            "admin_status": "TEXT",
            "physical_status": "TEXT",
            "media_attribute": "TEXT",
            "media_type": "TEXT",
            "category": "TEXT",
            "port_mode": "TEXT",
            "native_vlan": "TEXT",
            "tagged_vlans": "TEXT",
            "untagged_vlans": "TEXT",
            "pvid_source": "TEXT",
            "pvid_verified": "INTEGER",
            "vlan_config_status": "TEXT",
            "vlan_config_collected_at": "TEXT",
            "vlan_warnings": "TEXT",
        }
        for table in ("device_interfaces", "device_interfaces_history"):
            for column, column_type in interface_columns.items():
                if self._table_exists(conn, table) and not self._column_exists(
                    conn, table, column
                ):
                    conn.execute(
                        f"ALTER {'TABLE'} {table} ADD COLUMN {column} {column_type}"
                    )
        lldp_columns = {
            "scope": "TEXT",
            "chassis_type": "TEXT",
            "chassis_id": "TEXT",
            "port_id_type": "TEXT",
            "holdtime": "INTEGER",
            "ttl": "INTEGER",
            "port_description": "TEXT",
            "system_description": "TEXT",
            "system_capabilities": "TEXT",
            "pvid": "INTEGER",
            "operational_mau": "TEXT",
            "max_frame_size": "INTEGER",
        }
        for table in ("device_lldp_neighbors", "device_lldp_neighbors_history"):
            for column, column_type in lldp_columns.items():
                if self._table_exists(conn, table) and not self._column_exists(
                    conn, table, column
                ):
                    conn.execute(
                        f"ALTER {'TABLE'} {table} ADD COLUMN {column} {column_type}"
                    )
        if self._table_exists(conn, "ac_trackside_ap_plan") and not self._column_exists(conn, "ac_trackside_ap_plan", "remark"):
            conn.execute("ALTER TABLE ac_trackside_ap_plan ADD COLUMN remark TEXT")
        trackside_plan_columns = {
            "station_id": "TEXT NOT NULL DEFAULT ''",
            "sequence_no": "INTEGER NOT NULL DEFAULT 0",
            "subnet_mask": "TEXT NOT NULL DEFAULT ''",
            "management_vlan": "INTEGER",
        }
        if self._table_exists(conn, "ac_trackside_ap_plan"):
            for column, definition in trackside_plan_columns.items():
                if not self._column_exists(conn, "ac_trackside_ap_plan", column):
                    conn.execute(
                        f"ALTER TABLE ac_trackside_ap_plan ADD COLUMN {column} {definition}"
                    )
            sequence_rows = conn.execute(
                """
                SELECT id, sequence_no, sort_order, station_name
                FROM ac_trackside_ap_plan
                WHERE mode = 'unified'
                ORDER BY
                    CASE WHEN sequence_no > 0 THEN sequence_no ELSE sort_order + 1 END,
                    sort_order,
                    station_name,
                    id
                """
            ).fetchall()
            sequence_numbers = [int(row["sequence_no"] or 0) for row in sequence_rows]
            if any(value <= 0 for value in sequence_numbers) or len(
                sequence_numbers
            ) != len(set(sequence_numbers)):
                conn.execute(
                    """
                    UPDATE ac_trackside_ap_plan
                    SET sequence_no = 0
                    WHERE mode = 'unified'
                    """
                )
                for sequence_no, row in enumerate(sequence_rows, start=1):
                    conn.execute(
                        """
                        UPDATE ac_trackside_ap_plan
                        SET sequence_no = ?, sort_order = ?
                        WHERE id = ?
                        """,
                        (sequence_no, sequence_no - 1, int(row["id"])),
                    )
            conn.execute(
                """
                UPDATE ac_trackside_ap_plan
                SET subnet_mask = CASE
                    WHEN mask_length IS NULL THEN ''
                    ELSE CAST(mask_length AS TEXT)
                END
                WHERE mode = 'unified' AND TRIM(COALESCE(subnet_mask, '')) = ''
                """
            )
            conn.execute(
                """
                UPDATE ac_trackside_ap_plan
                SET management_vlan = CAST(ap_management_vlans AS INTEGER)
                WHERE mode = 'unified'
                  AND management_vlan IS NULL
                  AND TRIM(ap_management_vlans) GLOB '[0-9]*'
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trackside_plan_sequence
                ON ac_trackside_ap_plan(mode, sequence_no)
                WHERE mode = 'unified' AND sequence_no > 0
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_trackside_plan_station_id
                ON ac_trackside_ap_plan(mode, station_id)
                WHERE mode = 'unified' AND station_id != ''
                """
            )
        fit_ap_resource_columns = {
            "connection_ip": "TEXT",
            "connection_state": "TEXT",
            "connection_time": "TEXT",
            "rid1_status": "TEXT",
            "rid1_mode": "TEXT",
            "rid1_band": "TEXT",
            "rid1_usage": "TEXT",
            "rid1_clients": "INTEGER",
            "rid2_status": "TEXT",
            "rid2_mode": "TEXT",
            "rid2_band": "TEXT",
            "rid2_usage": "TEXT",
            "rid2_clients": "INTEGER",
            "rid3_status": "TEXT",
            "rid3_mode": "TEXT",
            "rid3_band": "TEXT",
            "rid3_usage": "TEXT",
            "rid3_clients": "INTEGER",
            "rid1_bbssid": "TEXT",
            "rid2_bbssid": "TEXT",
            "rid3_bbssid": "TEXT",
            "lldp_source": "TEXT",
            "lldp_confidence": "INTEGER",
            "lldp_collected_at": "TEXT",
            "lldp_local_interface": "TEXT",
            "lldp_local_interface_normalized": "TEXT",
            "lldp_neighbor_name": "TEXT",
            "lldp_neighbor_mac": "TEXT",
            "lldp_neighbor_mac_normalized": "TEXT",
            "lldp_neighbor_interface": "TEXT",
            "lldp_match_status": "TEXT",
            "optical_interface": "TEXT",
            "optical_interface_normalized": "TEXT",
            "optical_rx_power": "REAL",
            "optical_tx_power": "REAL",
            "optical_collected_at": "TEXT",
            "optical_match_status": "TEXT",
        }
        for column, column_type in fit_ap_resource_columns.items():
            if self._table_exists(conn, "ac_fit_ap_resources") and not self._column_exists(conn, "ac_fit_ap_resources", column):
                conn.execute(f"ALTER {'TABLE'} ac_fit_ap_resources ADD COLUMN {column} {column_type}")
        if self._table_exists(conn, "ac_fit_ap_resources") and self._column_exists(conn, "ac_fit_ap_resources", "ap_mac"):
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ac_fit_ap_resources_mac_lookup
                    ON ac_fit_ap_resources(
                        replace(replace(replace(lower(COALESCE(ap_mac, '')), ':', ''), '-', ''), ' ', '')
                    )
                """
            )
        fit_ap_metadata_columns = {
            "belong_type": "TEXT",
            "belong_section": "TEXT",
            "section_start_station": "TEXT",
            "section_end_station": "TEXT",
            "yard_name": "TEXT",
            "area_name": "TEXT",
        }
        for column, column_type in fit_ap_metadata_columns.items():
            if self._table_exists(conn, "ac_fit_ap_metadata") and not self._column_exists(conn, "ac_fit_ap_metadata", column):
                conn.execute(f"ALTER {'TABLE'} ac_fit_ap_metadata ADD COLUMN {column} {column_type}")
        ap_extension_point_columns = {
            "ap_vendor": "TEXT",
            "belong_type": "TEXT",
            "section_start_station": "TEXT",
            "section_end_station": "TEXT",
            "yard_name": "TEXT",
            "area_name": "TEXT",
            "location_class": "TEXT NOT NULL DEFAULT 'MAINLINE'",
            "participates_in_mainline": "INTEGER NOT NULL DEFAULT 1",
            "location_class_source": (
                "TEXT NOT NULL DEFAULT 'DEFAULT_MAINLINE'"
            ),
        }
        trackside_location_columns_before = {
            column: self._column_exists(conn, "ap_extension_points", column)
            for column in TRACKSIDE_AP_LOCATION_COLUMNS
        }
        for column, column_type in ap_extension_point_columns.items():
            if self._table_exists(conn, "ap_extension_points") and not self._column_exists(conn, "ap_extension_points", column):
                conn.execute(f"ALTER {'TABLE'} ap_extension_points ADD COLUMN {column} {column_type}")
        ap_identity_state_columns = {
            "source_revision": "INTEGER NOT NULL DEFAULT -1",
            "actual_radio_alias_count": "INTEGER NOT NULL DEFAULT 0",
            "actual_bssid_alias_count": "INTEGER NOT NULL DEFAULT 0",
            "actual_bbssid_alias_count": "INTEGER NOT NULL DEFAULT 0",
            "derived_alias_count": "INTEGER NOT NULL DEFAULT 0",
            "ambiguous_alias_count": "INTEGER NOT NULL DEFAULT 0",
            "build_duration_ms": "REAL NOT NULL DEFAULT 0",
            "diagnostics_json": "TEXT",
        }
        for column, column_type in ap_identity_state_columns.items():
            if self._table_exists(conn, "ap_identity_index_state") and not self._column_exists(conn, "ap_identity_index_state", column):
                conn.execute(
                    f"ALTER {'TABLE'} ap_identity_index_state ADD COLUMN {column} {column_type}"
                )
        if self._table_exists(conn, "ap_extension_points"):
            self._migrate_trackside_ap_locations(
                conn,
                location_column_existed=trackside_location_columns_before[
                    "location_class"
                ],
                participation_column_existed=trackside_location_columns_before[
                    "participates_in_mainline"
                ],
                source_column_existed=trackside_location_columns_before[
                    "location_class_source"
                ],
            )
        fit_ap_optical_columns = {
            "lldp_source": "TEXT",
            "lldp_confidence": "INTEGER",
            "lldp_collected_at": "TEXT",
            "lldp_local_interface": "TEXT",
            "lldp_local_interface_normalized": "TEXT",
            "lldp_neighbor_name": "TEXT",
            "lldp_neighbor_mac": "TEXT",
            "lldp_neighbor_mac_normalized": "TEXT",
            "lldp_neighbor_interface": "TEXT",
            "lldp_match_status": "TEXT",
            "optical_interface": "TEXT",
            "optical_interface_normalized": "TEXT",
            "link_match_status": "TEXT",
            "source": "TEXT",
        }
        for column, column_type in fit_ap_optical_columns.items():
            if self._table_exists(conn, "ac_fit_ap_optical") and not self._column_exists(conn, "ac_fit_ap_optical", column):
                conn.execute(f"ALTER {'TABLE'} ac_fit_ap_optical ADD COLUMN {column} {column_type}")
        fit_ap_optical_history_columns = {
            "lldp_local_interface": "TEXT",
            "lldp_local_interface_normalized": "TEXT",
            "lldp_neighbor_name": "TEXT",
            "lldp_neighbor_mac": "TEXT",
            "lldp_neighbor_mac_normalized": "TEXT",
            "lldp_neighbor_interface": "TEXT",
            "link_match_status": "TEXT",
            "source": "TEXT",
            "session_id": "TEXT",
        }
        for column, column_type in fit_ap_optical_history_columns.items():
            if self._table_exists(conn, "ac_fit_ap_optical_history") and not self._column_exists(conn, "ac_fit_ap_optical_history", column):
                conn.execute(f"ALTER {'TABLE'} ac_fit_ap_optical_history ADD COLUMN {column} {column_type}")
        fit_ap_radio_history_columns = {
            "status": "TEXT",
            "mode": "TEXT",
            "band": "TEXT",
            "usage": "TEXT",
            "clients": "INTEGER",
            "bbssid": "TEXT",
        }
        for column, column_type in fit_ap_radio_history_columns.items():
            if self._table_exists(conn, "ac_fit_ap_radio_history") and not self._column_exists(conn, "ac_fit_ap_radio_history", column):
                conn.execute(f"ALTER {'TABLE'} ac_fit_ap_radio_history ADD COLUMN {column} {column_type}")
        fit_ap_lldp_history_columns = {
            "source": "TEXT",
            "local_interface_normalized": "TEXT",
            "neighbor_mac_normalized": "TEXT",
            "neighbor_name": "TEXT",
            "session_id": "TEXT",
            "is_changed": "INTEGER",
            "conflict_flag": "INTEGER",
        }
        for column, column_type in fit_ap_lldp_history_columns.items():
            if self._table_exists(conn, "ac_fit_ap_lldp_history") and not self._column_exists(conn, "ac_fit_ap_lldp_history", column):
                conn.execute(f"ALTER {'TABLE'} ac_fit_ap_lldp_history ADD COLUMN {column} {column_type}")
        device_snmp_columns = {
            "snmp_enabled": "INTEGER DEFAULT 1",
            "snmp_v1_enabled": "INTEGER DEFAULT 0",
            "snmp_v2c_enabled": "INTEGER DEFAULT 1",
            "snmp_port": "INTEGER DEFAULT 161",
            "snmp_ro_community": "TEXT",
            "snmp_timeout_ms": "INTEGER DEFAULT 2000",
            "snmp_retries": "INTEGER DEFAULT 1",
        }
        for column, column_type in device_snmp_columns.items():
            if self._table_exists(conn, "devices") and not self._column_exists(conn, "devices", column):
                conn.execute(f"ALTER {'TABLE'} devices ADD COLUMN {column} {column_type}")

    def _apply_device_address_migration(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "devices"):
            return
        if not self._column_exists(conn, "devices", "normalized_primary_address"):
            conn.execute(
                "ALTER TABLE devices ADD COLUMN normalized_primary_address TEXT"
            )
        rows = conn.execute(
            """
            SELECT id, name, primary_address
            FROM devices
            ORDER BY id
            """
        ).fetchall()
        normalized_rows: list[tuple[str | None, str, int]] = []
        by_address: dict[str, list[sqlite3.Row]] = {}
        invalid: list[sqlite3.Row] = []
        for row in rows:
            raw_address = str(row["primary_address"] or "")
            try:
                normalized = normalize_ip_address(raw_address)
            except InvalidDeviceAddressError:
                invalid.append(row)
                continue
            if normalized:
                by_address.setdefault(normalized, []).append(row)
            normalized_rows.append((normalized, normalized or "", int(row["id"])))
        conflicts = {
            address: values
            for address, values in by_address.items()
            if len(values) > 1
        }
        if invalid or conflicts:
            parts: list[str] = []
            site_name = self._site_name()
            for row in invalid:
                parts.append(
                    f"局点={site_name} 主地址={row['primary_address']} "
                    f"设备ID={row['id']} 设备名称={row['name']}（非法地址）"
                )
            for address, values in conflicts.items():
                devices = "；".join(
                    f"设备ID={row['id']} 设备名称={row['name']}" for row in values
                )
                parts.append(f"局点={site_name} 主地址={address} {devices}")
            raise DeviceAddressMigrationError(
                "设备主地址迁移被历史数据阻止，原数据库未修改："
                + " | ".join(parts)
            )
        conn.executemany(
            """
            UPDATE devices
            SET normalized_primary_address = ?,
                primary_address = ?
            WHERE id = ?
            """,
            normalized_rows,
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_normalized_primary_address
            ON devices(normalized_primary_address)
            WHERE normalized_primary_address IS NOT NULL
              AND normalized_primary_address <> ''
            """
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).casefold() != "ok":
            raise sqlite3.DatabaseError("设备数据库迁移后完整性校验失败")

    def _requires_device_address_migration(self, conn: sqlite3.Connection) -> bool:
        if not self._table_exists(conn, "devices"):
            return False
        if not self._column_exists(conn, "devices", "normalized_primary_address"):
            return True
        index = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'uq_devices_normalized_primary_address'
            LIMIT 1
            """
        ).fetchone()
        if index is None:
            return True
        return conn.execute(
            """
            SELECT 1
            FROM devices
            WHERE COALESCE(normalized_primary_address, '') <>
                  CASE
                      WHEN TRIM(COALESCE(primary_address, '')) = '' THEN ''
                      ELSE TRIM(primary_address)
                  END
            LIMIT 1
            """
        ).fetchone() is not None

    def _requires_device_classification_migration(
        self, conn: sqlite3.Connection
    ) -> bool:
        if not self._table_exists(conn, "devices"):
            return False
        missing_columns = self._missing_device_classification_columns(conn)
        if missing_columns:
            return True
        indexes = {
            str(row["name"])
            for row in conn.execute("PRAGMA index_list(devices)").fetchall()
        }
        if any(index not in indexes for index in DEVICE_CLASSIFICATION_INDEXES):
            return True
        return (
            conn.execute(
                """
                SELECT 1
                FROM devices
                WHERE project_phase IS NULL
                   OR TRIM(project_phase) = ''
                   OR work_scope_status IS NULL
                   OR TRIM(work_scope_status) = ''
                LIMIT 1
                """
            ).fetchone()
            is not None
        )

    def _requires_ap_identity_schema_migration(self, conn: sqlite3.Connection) -> bool:
        if not self._table_exists(conn, "ap_identity_index_state"):
            return True
        required_columns = {
            "source_revision",
            "actual_radio_alias_count",
            "actual_bssid_alias_count",
            "actual_bbssid_alias_count",
            "derived_alias_count",
            "ambiguous_alias_count",
            "build_duration_ms",
            "diagnostics_json",
        }
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(ap_identity_index_state)"
            ).fetchall()
        }
        return not required_columns <= columns

    def _requires_trackside_ap_location_migration(
        self, conn: sqlite3.Connection
    ) -> bool:
        if not self._table_exists(conn, "ap_extension_points"):
            return False
        if any(
            not self._column_exists(conn, "ap_extension_points", column)
            for column in TRACKSIDE_AP_LOCATION_COLUMNS
        ):
            return True
        placeholders = ", ".join("?" for _ in TRACKSIDE_AP_LOCATION_CLASSES)
        return (
            conn.execute(
                f"""
                SELECT 1
                FROM ap_extension_points
                WHERE location_class IS NULL
                   OR TRIM(location_class) = ''
                   OR UPPER(TRIM(location_class)) NOT IN ({placeholders})
                   OR participates_in_mainline IS NULL
                   OR location_class_source IS NULL
                   OR TRIM(location_class_source) = ''
                LIMIT 1
                """,
                TRACKSIDE_AP_LOCATION_CLASSES,
            ).fetchone()
            is not None
        )

    def _requires_rail_base_identity_migration(
        self, conn: sqlite3.Connection
    ) -> bool:
        required = (
            ("devices", "station_id"),
            ("ap_extension_points", "station_id"),
            ("ap_extension_points", "section_id"),
        )
        if any(
            self._table_exists(conn, table)
            and not self._column_exists(conn, table, column)
            for table, column in required
        ):
            return True
        if not self._table_exists(conn, "ap_extension_points"):
            return False
        return conn.execute(
            """
            SELECT 1 FROM ap_extension_points
            WHERE belong_type IN ('__base_station__', '__base_section__')
              AND (
                (belong_type = '__base_station__' AND TRIM(COALESCE(station_id, '')) = '')
                OR
                (belong_type = '__base_section__' AND TRIM(COALESCE(section_id, '')) = '')
              )
            LIMIT 1
            """
        ).fetchone() is not None

    @staticmethod
    def _backfill_rail_base_master_ids(conn: sqlite3.Connection) -> None:
        if not Database._table_exists(conn, "ap_extension_points"):
            return
        rows = conn.execute(
            """
            SELECT id, site_id, belong_type, station_id, section_id, raw_payload_json
            FROM ap_extension_points
            WHERE belong_type IN ('__base_station__', '__base_section__')
            """
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(str(row["raw_payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            if row["belong_type"] == "__base_station__" and not str(
                row["station_id"] or ""
            ).strip():
                node_uid = str(metadata.get("node_uid") or "").strip() or str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"netconsole:{row['site_id']}:station:ap:{row['id']}",
                    )
                )
                station_id = (
                    "station:"
                    + hashlib.sha1(node_uid.encode("utf-8")).hexdigest()[:12]
                )
                conn.execute(
                    "UPDATE ap_extension_points SET station_id = ? WHERE id = ?",
                    (station_id, int(row["id"])),
                )
            elif row["belong_type"] == "__base_section__" and not str(
                row["section_id"] or ""
            ).strip():
                identity = str(metadata.get("generation_key") or f"ap:{row['id']}")
                section_id = (
                    "section:"
                    + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
                )
                conn.execute(
                    "UPDATE ap_extension_points SET section_id = ? WHERE id = ?",
                    (section_id, int(row["id"])),
                )

    def _validate_rail_base_identity_migration(
        self, conn: sqlite3.Connection
    ) -> None:
        required = (
            ("devices", "station_id"),
            ("ap_extension_points", "station_id"),
            ("ap_extension_points", "section_id"),
        )
        missing = [
            f"{table}.{column}"
            for table, column in required
            if not self._table_exists(conn, table)
            or not self._column_exists(conn, table, column)
        ]
        if missing:
            raise sqlite3.DatabaseError(
                "轨道基础资料稳定关联字段迁移不完整: " + ",".join(missing)
            )
        blank_master = conn.execute(
            """
            SELECT belong_type FROM ap_extension_points
            WHERE (belong_type = '__base_station__' AND TRIM(station_id) = '')
               OR (belong_type = '__base_section__' AND TRIM(section_id) = '')
            LIMIT 1
            """
        ).fetchone()
        if blank_master is not None:
            raise sqlite3.DatabaseError("轨道基础资料主记录稳定 ID 迁移不完整")
        expected_indexes = {
            "devices": {"idx_devices_station_id"},
            "ap_extension_points": {
                "idx_ap_extension_points_station_id",
                "idx_ap_extension_points_section_id",
                "idx_base_station_id_unique",
                "idx_base_section_id_unique",
            },
        }
        for table, names in expected_indexes.items():
            actual = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA index_list({table})").fetchall()
            }
            if not names <= actual:
                raise sqlite3.DatabaseError(
                    "轨道基础资料稳定关联索引迁移不完整: "
                    + ",".join(sorted(names - actual))
                )

    def _migrate_trackside_ap_locations(
        self,
        conn: sqlite3.Connection,
        *,
        location_column_existed: bool,
        participation_column_existed: bool,
        source_column_existed: bool,
    ) -> None:
        rows = conn.execute(
            """
            SELECT id, belong_type, station_name, section_name, yard_name,
                   area_name, install_scene, location_desc, location_class,
                   participates_in_mainline, location_class_source
            FROM ap_extension_points
            """
        ).fetchall()
        for row in rows:
            raw_class = (
                str(row["location_class"] or "").strip()
                if location_column_existed
                else ""
            )
            normalized = _normalized_trackside_ap_location_class(raw_class)
            inferred = False
            if not normalized:
                normalized = _legacy_trackside_ap_location_class(dict(row))
                inferred = True

            raw_source = (
                str(row["location_class_source"] or "").strip()
                if source_column_existed
                else ""
            )
            if raw_source:
                source = raw_source
            elif inferred:
                source = (
                    "DEFAULT_MAINLINE"
                    if normalized == "MAINLINE"
                    else "LEGACY_INFERRED"
                )
            else:
                source = (
                    "DEFAULT_MAINLINE"
                    if normalized == "MAINLINE"
                    else "EXPLICIT"
                )

            participates = (
                bool(row["participates_in_mainline"])
                if participation_column_existed
                and row["participates_in_mainline"] is not None
                else normalized == "MAINLINE"
            )
            if (
                raw_class == normalized
                and raw_source == source
                and participation_column_existed
                and row["participates_in_mainline"] is not None
                and bool(row["participates_in_mainline"]) == participates
            ):
                continue
            conn.execute(
                """
                UPDATE ap_extension_points
                SET location_class = ?,
                    participates_in_mainline = ?,
                    location_class_source = ?
                WHERE id = ?
                """,
                (normalized, int(participates), source, int(row["id"])),
            )

    def _validate_trackside_ap_location_migration(
        self, conn: sqlite3.Connection
    ) -> None:
        if not self._table_exists(conn, "ap_extension_points"):
            raise sqlite3.DatabaseError("轨旁 AP 表缺失")
        missing = [
            column
            for column in TRACKSIDE_AP_LOCATION_COLUMNS
            if not self._column_exists(conn, "ap_extension_points", column)
        ]
        if missing:
            raise sqlite3.DatabaseError(
                "轨旁 AP 位置字段迁移不完整: " + ",".join(missing)
            )
        placeholders = ", ".join("?" for _ in TRACKSIDE_AP_LOCATION_CLASSES)
        invalid = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM ap_extension_points
            WHERE location_class IS NULL
               OR UPPER(TRIM(location_class)) NOT IN ({placeholders})
               OR participates_in_mainline IS NULL
               OR location_class_source IS NULL
               OR TRIM(location_class_source) = ''
            """,
            TRACKSIDE_AP_LOCATION_CLASSES,
        ).fetchone()
        if invalid and int(invalid[0]) > 0:
            raise sqlite3.DatabaseError("轨旁 AP 位置分类迁移不完整")

    def _validate_device_classification_migration(
        self, conn: sqlite3.Connection
    ) -> None:
        missing_columns = self._missing_device_classification_columns(conn)
        if missing_columns:
            raise sqlite3.DatabaseError(
                "设备分类字段迁移不完整: " + ",".join(missing_columns)
            )
        indexes = {
            str(row["name"])
            for row in conn.execute("PRAGMA index_list(devices)").fetchall()
        }
        missing_indexes = [
            index for index in DEVICE_CLASSIFICATION_INDEXES if index not in indexes
        ]
        if missing_indexes:
            raise sqlite3.DatabaseError(
                "设备分类索引迁移不完整: " + ",".join(missing_indexes)
            )
        invalid_defaults = conn.execute(
            """
            SELECT COUNT(*)
            FROM devices
            WHERE project_phase IS NULL
               OR TRIM(project_phase) = ''
               OR project_phase NOT IN ('phase_1', 'phase_2', 'phase_3', 'other', 'unspecified')
               OR work_scope_status IS NULL
               OR TRIM(work_scope_status) = ''
               OR work_scope_status NOT IN ('included', 'excluded')
            """
        ).fetchone()
        if invalid_defaults and int(invalid_defaults[0]) > 0:
            raise sqlite3.DatabaseError("设备分类默认值迁移不完整")

    def _missing_device_classification_columns(
        self, conn: sqlite3.Connection
    ) -> list[str]:
        return [
            column
            for column in DEVICE_CLASSIFICATION_COLUMNS
            if not self._column_exists(conn, "devices", column)
        ]

    def _validate_legacy_operation_status_values(
        self, conn: sqlite3.Connection
    ) -> None:
        placeholders = ", ".join("?" for _ in LEGACY_OPERATION_STATUS_VALUES)
        rows = conn.execute(
            f"""
            SELECT operation_status, COUNT(*) AS count
            FROM devices
            WHERE TRIM(COALESCE(operation_status, '')) <> ''
              AND LOWER(TRIM(operation_status)) NOT IN ({placeholders})
            GROUP BY operation_status
            ORDER BY operation_status
            """,
            LEGACY_OPERATION_STATUS_VALUES,
        ).fetchall()
        if rows:
            values = ", ".join(
                f"{row['operation_status']}={int(row['count'])}" for row in rows
            )
            raise DatabaseSchemaMismatchError(
                "旧投运状态存在无法安全映射的值，原数据库未修改：" + values
            )

    def _legacy_operation_status_counts(
        self, conn: sqlite3.Connection
    ) -> dict[str, int]:
        if not self._column_exists(conn, "devices", "operation_status"):
            return {}
        return {
            str(row["operation_status"] or "<empty>"): int(row["count"])
            for row in conn.execute(
                """
                SELECT operation_status, COUNT(*) AS count
                FROM devices
                GROUP BY operation_status
                ORDER BY operation_status
                """
            ).fetchall()
        }

    def _backup_before_device_migration(
        self, source: sqlite3.Connection, migration_name: str
    ) -> Path:
        if self.path.parent.name.casefold() == "db":
            backup_dir = (
                self.path.parent.parent
                / "files"
                / "backups"
                / "database-migrations"
            )
        else:
            backup_dir = self.path.parent / "backups" / "database-migrations"
        backup_dir.mkdir(parents=True, exist_ok=True)
        site_key = hashlib.sha256(
            self._site_name().encode("utf-8")
        ).hexdigest()[:10]
        fingerprint = self._device_migration_fingerprint(source)
        reusable = sorted(
            backup_dir.glob(
                f"devices-site-{site_key}-before-{migration_name}-*-{fingerprint}.sqlite"
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in reusable:
            if self._backup_integrity_ok(candidate):
                self._log_backup_event(
                    "DATABASE_MIGRATION_BACKUP_REUSED",
                    candidate,
                    migration_name,
                    fingerprint,
                )
                return candidate
        target = backup_dir / (
            f"devices-site-{site_key}-before-{migration_name}-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}-{fingerprint}.sqlite"
        )
        try:
            with closing(connect_sqlite(target, foreign_keys=True)) as destination:
                source.backup(destination)
                self._assert_integrity(
                    destination, "设备数据库迁移备份完整性校验失败"
                )
                destination.commit()
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self._log_backup_event(
            "DATABASE_MIGRATION_BACKUP_CREATED",
            target,
            migration_name,
            fingerprint,
        )
        return target

    def _device_migration_fingerprint(
        self, source: sqlite3.Connection
    ) -> str:
        columns = [
            str(row["name"])
            for row in source.execute("PRAGMA table_info(devices)").fetchall()
        ]
        indexes = sorted(
            str(row["name"])
            for row in source.execute("PRAGMA index_list(devices)").fetchall()
        )
        summary = source.execute(
            """
            SELECT COUNT(*) AS device_count,
                   COALESCE(MAX(updated_at), '') AS latest_update
            FROM devices
            """
        ).fetchone()
        payload = {
            "schema_version": self._safe_schema_version(source),
            "columns": columns,
            "indexes": indexes,
            "device_count": int(summary["device_count"]) if summary else 0,
            "latest_update": str(summary["latest_update"]) if summary else "",
        }
        serialized = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(serialized.encode("ascii")).hexdigest()[:16]

    @staticmethod
    def _backup_integrity_ok(path: Path) -> bool:
        try:
            uri = f"{path.resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(
                integrity and str(integrity[0]).casefold() == "ok"
            )
        except sqlite3.Error:
            return False

    def _log_backup_event(
        self,
        event: str,
        path: Path,
        migration_name: str,
        fingerprint: str,
    ) -> None:
        try:
            from netconsole.core import app_logger

            app_logger.log_info(
                event,
                (
                    f"site={self._site_name()} database_path={self.path} "
                    f"migration={migration_name} backup_path={path} "
                    f"fingerprint={fingerprint}"
                ),
            )
        except Exception:
            pass

    def _site_name(self) -> str:
        try:
            return self.path.parent.parent.name or "unknown"
        except IndexError:
            return "unknown"

    @staticmethod
    def _all_schema_scripts(
        *, include_device_address_index: bool = True
    ) -> tuple[str, ...]:
        scripts = [
            SCHEMA_METADATA_SCHEMA,
            DEVICES_SCHEMA,
            DEVICE_CREDENTIAL_STATE_SCHEMA,
            DEVICE_GROUPS_SCHEMA,
            COLLECT_RUNS_SCHEMA,
            DEVICE_FACTS_SCHEMA,
            DEVICE_INTERFACES_SCHEMA,
            DEVICE_OPTICAL_MODULES_SCHEMA,
            DEVICE_LLDP_NEIGHBORS_SCHEMA,
            DEVICE_FACTS_HISTORY_SCHEMA,
            DEVICE_INTERFACES_HISTORY_SCHEMA,
            DEVICE_OPTICAL_MODULES_HISTORY_SCHEMA,
            DEVICE_LLDP_NEIGHBORS_HISTORY_SCHEMA,
            AC_AP_SUMMARY_SCHEMA,
            AC_FIT_AP_RESOURCES_SCHEMA,
            AC_FIT_AP_METADATA_SCHEMA,
            AC_FIT_AP_DETAILS_SCHEMA,
            AC_FIT_AP_RADIO_DETAILS_SCHEMA,
            AP_EXTENSION_POINTS_SCHEMA,
            AP_EXTENSION_IMPORT_BATCHES_SCHEMA,
            AC_FIT_AP_RESOURCE_HISTORY_SCHEMA,
            AC_FIT_AP_UNAUTHENTICATED_SCHEMA,
            AC_FIT_AP_UNAUTHENTICATED_HISTORY_SCHEMA,
            AC_FIT_AP_UNAUTHENTICATED_SUMMARY_SCHEMA,
            AC_FIT_AP_OPTICAL_SCHEMA,
            AP_ENTITIES_SCHEMA,
            AP_IDENTITY_INDEX_SCHEMA,
            AP_RESOURCE_SNAPSHOTS_SCHEMA,
            AP_LLDP_HISTORY_SCHEMA,
            AP_OPTICAL_HISTORY_SCHEMA,
            TRACKSIDE_AP_VIEW_CACHE_SCHEMA,
            AC_STATION_AP_CAPACITY_SCHEMA,
            AC_TRACKSIDE_AP_PLAN_SCHEMA,
            AC_TRACKSIDE_AP_PLAN_SETTINGS_SCHEMA,
            AP_MANAGEMENT_VLAN_PLANNING_SCHEMA,
            AP_MANAGEMENT_VLAN_GROUP_SCHEMA,
            AP_MANAGEMENT_VLAN_GROUP_MEMBER_SCHEMA,
            AP_MANAGEMENT_VLAN_ASSIGNMENT_SCHEMA,
            AP_MANAGEMENT_VLAN_ALLOCATION_SCHEMA,
            AC_STATION_ONLINE_SUMMARY_HISTORY_SCHEMA,
            AC_FIT_AP_OPTICAL_HISTORY_SCHEMA,
            AC_FIT_AP_LLDP_HISTORY_SCHEMA,
            AC_FIT_AP_RADIO_HISTORY_SCHEMA,
            CONFIG_SNAPSHOTS_SCHEMA,
            _ap_identity_source_revision_schema(),
            BASE_DATA_REVISION_SCHEMA,
        ]
        if include_device_address_index:
            scripts.insert(2, DEVICE_PRIMARY_ADDRESS_INDEX_SCHEMA)
        return tuple(scripts)

    def _migrate_trackside_ap_vlan_allocation_references(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        """移除参考 IP 唯一约束；事务由 initialize 统一提交或回滚。"""
        if not self._table_exists(conn, "rail_ap_vlan_allocations"):
            return
        row = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'rail_ap_vlan_allocations'
            """
        ).fetchone()
        if row is None:
            return
        definition = "".join(str(row["sql"] or "").upper().split())
        if "UNIQUE(PLANNED_IP)" not in definition:
            return
        conn.execute(
            """
            CREATE TABLE rail_ap_vlan_allocations_reference_migration (
                ap_id TEXT PRIMARY KEY,
                ap_name TEXT NOT NULL DEFAULT '',
                point_code TEXT NOT NULL DEFAULT '',
                station_id TEXT NOT NULL DEFAULT '',
                station_name TEXT NOT NULL DEFAULT '',
                section_name TEXT NOT NULL DEFAULT '',
                group_id TEXT NOT NULL,
                planned_ip TEXT NOT NULL,
                allocation_order INTEGER NOT NULL,
                is_manual INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                group_source TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (group_id) REFERENCES rail_ap_vlan_groups(group_id) ON DELETE CASCADE,
                CHECK (is_manual IN (0, 1)),
                CHECK (is_locked IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            INSERT INTO rail_ap_vlan_allocations_reference_migration (
                ap_id, ap_name, point_code, station_id, station_name,
                section_name, group_id, planned_ip, allocation_order,
                is_manual, is_locked, source, group_source, created_at, updated_at
            )
            SELECT
                ap_id, ap_name, point_code, station_id, station_name,
                section_name, group_id, planned_ip, allocation_order,
                is_manual, is_locked, source, group_source, created_at, updated_at
            FROM rail_ap_vlan_allocations
            """
        )
        conn.execute("DROP TABLE rail_ap_vlan_allocations")
        conn.execute(
            """
            ALTER TABLE rail_ap_vlan_allocations_reference_migration
            RENAME TO rail_ap_vlan_allocations
            """
        )
        conn.execute(
            """
            CREATE INDEX idx_rail_ap_vlan_allocations_group_order
            ON rail_ap_vlan_allocations(group_id, allocation_order)
            """
        )

    def _write_schema_version(self, conn: sqlite3.Connection) -> None:
        now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, created_at, updated_at)
            VALUES ('schema_version', ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            WHERE schema_metadata.value != excluded.value
            """,
            (CURRENT_SCHEMA_VERSION, now, now),
        )

    @staticmethod
    def _schema_version(conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
        return str(row["value"]) if row is not None else ""

    def _safe_schema_version(self, conn: sqlite3.Connection) -> str:
        try:
            if not self._table_exists(conn, "schema_metadata"):
                return ""
            return self._schema_version(conn)
        except sqlite3.Error:
            return ""

    @staticmethod
    def _assert_integrity(conn: sqlite3.Connection, message: str) -> None:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).casefold() != "ok":
            raise sqlite3.DatabaseError(message)

    def _log_migration_completed(
        self,
        *,
        schema_version_before: str,
        backup_path: Path | None,
        address_migration: bool,
        classification_migration: bool,
        trackside_ap_location_migration: bool,
        rail_base_identity_migration: bool,
        legacy_operation_status_counts: dict[str, int],
    ) -> None:
        try:
            from netconsole.core import app_logger

            app_logger.log_info(
                "DATABASE_MIGRATION_COMPLETED",
                (
                    f"site={self._site_name()} database_path={self.path} "
                    f"schema_version_before={schema_version_before or '<missing>'} "
                    f"schema_version_after={CURRENT_SCHEMA_VERSION} "
                    f"address_migration={address_migration} "
                    f"classification_migration={classification_migration} "
                    "trackside_ap_location_migration="
                    f"{trackside_ap_location_migration} "
                    "rail_base_identity_migration="
                    f"{rail_base_identity_migration} "
                    "legacy_operation_status_counts="
                    f"{json.dumps(legacy_operation_status_counts, ensure_ascii=True, sort_keys=True)} "
                    f"backup_path={backup_path or '<none>'}"
                ),
            )
        except Exception:
            pass

    def _log_initialize_failure(
        self,
        exc: Exception,
        *,
        conn: sqlite3.Connection | None,
        stage: str,
        backup_path: Path | None,
        schema_version_before: str,
    ) -> None:
        missing_columns: list[str] = []
        missing_indexes: list[str] = []
        schema_version = schema_version_before
        diagnostic_error = ""
        try:
            if conn is not None:
                schema_version = self._safe_schema_version(conn) or schema_version
                if self._table_exists(conn, "devices"):
                    missing_columns = self._missing_device_classification_columns(conn)
                    indexes = {
                        str(row["name"])
                        for row in conn.execute(
                            "PRAGMA index_list(devices)"
                        ).fetchall()
                    }
                    missing_indexes = [
                        index
                        for index in DEVICE_CLASSIFICATION_INDEXES
                        if index not in indexes
                    ]
        except Exception as diagnostic_exc:
            diagnostic_error = (
                f"{diagnostic_exc.__class__.__name__}: {diagnostic_exc}"
            )
        try:
            from netconsole.core import app_logger

            app_logger.log_error(
                "DATABASE_INITIALIZE_FAILED",
                (
                    f"site={self._site_name()} database_path={self.path} "
                    f"stage={stage} backup_path={backup_path or '<none>'} "
                    f"exception_class={exc.__class__.__name__} "
                    f"sqlite_errorcode={getattr(exc, 'sqlite_errorcode', '')} "
                    f"sqlite_errorname={getattr(exc, 'sqlite_errorname', '')} "
                    f"error={exc} schema_version={schema_version or '<missing>'} "
                    f"missing_columns={','.join(missing_columns) or '<none>'} "
                    f"missing_indexes={','.join(missing_indexes) or '<none>'} "
                    f"diagnostic_error={diagnostic_error} "
                    f"traceback={''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
                ),
            )
        except Exception:
            pass

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
        return any(row["name"] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall())

    @staticmethod
    def _schema_mismatch_message() -> str:
        return (
            "当前数据库结构缺少基础元数据，无法自动升级。"
            "原数据库未被自动修改，请使用已验证备份或受控迁移工具恢复。"
        )


def _database_initialize_lock(path: Path) -> threading.RLock:
    key = str(Path(path).resolve()).casefold()
    with _DATABASE_INITIALIZE_LOCKS_GUARD:
        return _DATABASE_INITIALIZE_LOCKS.setdefault(key, threading.RLock())

