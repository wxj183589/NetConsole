from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sqlite3
from pathlib import Path

from netconsole.core.device_credential_store import (
    DEVICE_CREDENTIAL_STATE_SCHEMA,
    repair_device_credential_states,
)
from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal


CURRENT_SCHEMA_VERSION = "2026.07.28.ap_management_vlan_groups"


class DatabaseSchemaMismatchError(RuntimeError):
    """Raised when an existing database is not safe for additive schema updates."""


SCHEMA_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

DEVICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    system_name TEXT,
    mac_address TEXT,
    station TEXT,
    location TEXT,
    group_id INTEGER,
    device_vendor TEXT NOT NULL DEFAULT 'H3C',
    device_type TEXT,
    primary_address TEXT NOT NULL,
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
    station_name TEXT,
    section_name TEXT,
    section_start_station TEXT,
    section_end_station TEXT,
    yard_name TEXT,
    area_name TEXT,
    line_side TEXT,
    direction TEXT,
    mileage_text TEXT,
    mileage_m REAL,
    distance_to_prev_m REAL,
    ap_point_code TEXT,
    ap_name TEXT,
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
    station_name TEXT NOT NULL,
    ap_count INTEGER NOT NULL DEFAULT 0,
    ap_start_address TEXT,
    mask_length INTEGER,
    ap_gateway TEXT,
    ap_management_vlans TEXT NOT NULL,
    remark TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(mode, station_name)
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
    UNIQUE (planned_ip),
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



class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, foreign_keys=True)

    def initialize(self) -> None:
        existed = self.exists()
        conn = self.connect()
        try:
            initialize_sqlite_wal(conn)
            conn.executescript(
                "\n".join(
                    self._schema_scripts_for_existing_database(conn) if existed else self._all_schema_scripts()
                )
            )
            self._apply_additive_schema_updates(conn)
            self._migrate_trackside_ap_vlan_groups(conn)
            repair_device_credential_states(conn)
            self._write_schema_version(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            try:
                from netconsole.core import app_logger

                app_logger.log_error("DATABASE_INITIALIZE_FAILED", f"path={self.path}")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _schema_scripts_for_existing_database(self, conn: sqlite3.Connection) -> tuple[str, ...]:
        if not self._table_exists(conn, "schema_metadata"):
            raise DatabaseSchemaMismatchError(self._schema_mismatch_message())
        if self._schema_version(conn) == CURRENT_SCHEMA_VERSION:
            return self._all_schema_scripts()
        self._assert_additive_update_safe(conn)
        return self._all_schema_scripts()

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
            "belong_type": "TEXT",
            "section_start_station": "TEXT",
            "section_end_station": "TEXT",
            "yard_name": "TEXT",
            "area_name": "TEXT",
        }
        for column, column_type in ap_extension_point_columns.items():
            if self._table_exists(conn, "ap_extension_points") and not self._column_exists(conn, "ap_extension_points", column):
                conn.execute(f"ALTER {'TABLE'} ap_extension_points ADD COLUMN {column} {column_type}")
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

    @staticmethod
    def _all_schema_scripts() -> tuple[str, ...]:
        return (
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
            AP_EXTENSION_POINTS_SCHEMA,
            AP_EXTENSION_IMPORT_BATCHES_SCHEMA,
            AC_FIT_AP_RESOURCE_HISTORY_SCHEMA,
            AC_FIT_AP_UNAUTHENTICATED_SCHEMA,
            AC_FIT_AP_UNAUTHENTICATED_HISTORY_SCHEMA,
            AC_FIT_AP_UNAUTHENTICATED_SUMMARY_SCHEMA,
            AC_FIT_AP_OPTICAL_SCHEMA,
            AP_ENTITIES_SCHEMA,
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
        )

    def _migrate_trackside_ap_vlan_groups(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "ac_trackside_ap_plan"):
            return
        existing_plan = conn.execute(
            "SELECT 1 FROM rail_ap_vlan_plans LIMIT 1"
        ).fetchone()
        if existing_plan is not None:
            return
        legacy_rows = conn.execute(
            """
            SELECT id, station_name, ap_count, ap_start_address, mask_length,
                   ap_gateway, ap_management_vlans, remark, sort_order,
                   created_at, updated_at
            FROM ac_trackside_ap_plan
            WHERE mode = 'unified'
            ORDER BY sort_order, station_name, id
            """
        ).fetchall()
        if not legacy_rows:
            return
        now = (
            __import__("datetime")
            .datetime.now(__import__("datetime").timezone.utc)
            .isoformat()
        )
        conn.execute(
            """
            INSERT INTO rail_ap_vlan_plans (
                line_id, planning_mode, auto_group_station_count,
                address_allocation_strategy, revision, created_at, updated_at
            )
            VALUES ('current', 'station_independent', 1, 'station_then_point', 1, ?, ?)
            """,
            (now, now),
        )
        for sequence, row in enumerate(legacy_rows):
            station_name = str(row["station_name"] or "").strip()
            vlan_text = self._normalized_vlan_text(row["ap_management_vlans"])
            vlan_values = [
                int(token) for token in vlan_text.split(",") if token.isdigit()
            ]
            primary_vlan = vlan_values[0] if vlan_values else None
            start_ip = str(row["ap_start_address"] or "").strip()
            prefix_length = (
                int(row["mask_length"])
                if row["mask_length"] not in (None, "")
                else None
            )
            network_address = ""
            subnet_mask = ""
            if start_ip and "X" not in start_ip.upper() and prefix_length is not None:
                try:
                    network = ipaddress.ip_network(
                        f"{start_ip}/{prefix_length}",
                        strict=False,
                    )
                except ValueError:
                    network = None
                if isinstance(network, ipaddress.IPv4Network):
                    network_address = str(network.network_address)
                    subnet_mask = str(network.netmask)
            group_id = f"legacy-plan-{int(row['id'])}"
            created_at = str(row["created_at"] or now)
            updated_at = str(row["updated_at"] or now)
            conn.execute(
                """
                INSERT INTO rail_ap_vlan_groups (
                    group_id, line_id, group_code, group_name, sequence,
                    management_vlan, legacy_management_vlans, network_address,
                    prefix_length, subnet_mask, default_gateway, ap_start_ip,
                    ap_end_ip, address_allocation_strategy, notes,
                    created_at, updated_at
                )
                VALUES (?, 'current', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '',
                        'station_then_point', ?, ?, ?)
                """,
                (
                    group_id,
                    f"G{sequence + 1:03d}",
                    station_name or f"VLAN 组 {sequence + 1}",
                    sequence,
                    primary_vlan,
                    vlan_text if len(vlan_values) > 1 else "",
                    network_address,
                    prefix_length,
                    subnet_mask,
                    str(row["ap_gateway"] or "").strip(),
                    start_ip,
                    str(row["remark"] or "").strip(),
                    created_at,
                    updated_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO rail_ap_vlan_group_members (
                    group_id, station_id, station_name, station_sequence,
                    ap_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    self._migration_station_id(conn, station_name),
                    station_name,
                    sequence,
                    max(0, int(row["ap_count"] or 0)),
                    created_at,
                    updated_at,
                ),
            )

    @staticmethod
    def _migration_station_id(
        conn: sqlite3.Connection,
        station_name: str,
    ) -> str:
        row = conn.execute(
            """
            SELECT raw_payload_json
            FROM ap_extension_points
            WHERE belong_type = '__base_station__' AND station_name = ?
            ORDER BY id
            LIMIT 1
            """,
            (station_name,),
        ).fetchone()
        if row is not None:
            try:
                metadata = json.loads(str(row[0] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            node_uid = str(metadata.get("node_uid") or "").strip()
            if node_uid:
                digest = hashlib.sha1(node_uid.encode("utf-8")).hexdigest()[:12]
                return f"station:{digest}"
        digest = hashlib.sha1(station_name.casefold().encode("utf-8")).hexdigest()[:12]
        return f"legacy-station:{digest}"

    @staticmethod
    def _normalized_vlan_text(value: object) -> str:
        vlans: set[int] = set()
        for token in re.split(r"[,，;；\s]+", str(value or "").strip()):
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
                if left.isdigit() and right.isdigit():
                    vlans.update(range(int(left), int(right) + 1))
            elif token.isdigit():
                vlans.add(int(token))
        return ",".join(str(vlan) for vlan in sorted(vlans) if 1 <= vlan <= 4094)

    def _write_schema_version(self, conn: sqlite3.Connection) -> None:
        now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, created_at, updated_at)
            VALUES ('schema_version', ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (CURRENT_SCHEMA_VERSION, now, now),
        )

    @staticmethod
    def _schema_version(conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
        return str(row["value"]) if row is not None else ""

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
            "请先备份旧 data 目录，然后使用数据库重建工具或清空旧数据后重新初始化。"
        )

