from __future__ import annotations

import sqlite3
from pathlib import Path


DEVICES_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    sysname TEXT,
    station TEXT,
    device_vendor TEXT NOT NULL DEFAULT 'H3C',
    device_type TEXT,
    ip_address TEXT NOT NULL,
    ssh_enabled INTEGER DEFAULT 1,
    ssh_port INTEGER DEFAULT 22,
    telnet_enabled INTEGER DEFAULT 0,
    telnet_port INTEGER DEFAULT 23,
    ssh_username TEXT,
    ssh_password TEXT,
    telnet_username TEXT,
    telnet_password TEXT,
    snmp_v1_enabled INTEGER DEFAULT 0,
    snmp_v2c_enabled INTEGER DEFAULT 1,
    snmp_v3_enabled INTEGER DEFAULT 0,
    snmp_port INTEGER DEFAULT 161,
    snmp_ro_community TEXT,
    snmp_rw_community TEXT,
    snmpv3_security_level TEXT,
    snmpv3_auth_protocol TEXT,
    snmpv3_auth_password TEXT,
    snmpv3_priv_protocol TEXT,
    snmpv3_priv_password TEXT,
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
    protocol_status TEXT,
    speed TEXT,
    duplex TEXT,
    interface_type TEXT,
    port_status TEXT,
    pvid TEXT,
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
    neighbor_sysname TEXT,
    neighbor_mac TEXT,
    neighbor_interface TEXT,
    neighbor_ip TEXT,
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
    protocol_status TEXT,
    speed TEXT,
    duplex TEXT,
    interface_type TEXT,
    port_status TEXT,
    pvid TEXT,
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
"""

DEVICE_LLDP_NEIGHBORS_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_lldp_neighbors_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_uuid TEXT NOT NULL,
    local_interface TEXT NOT NULL,
    neighbor_sysname TEXT,
    neighbor_mac TEXT,
    neighbor_interface TEXT,
    neighbor_ip TEXT,
    neighbor_device_uuid TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT,
    created_at TEXT NOT NULL
);
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
    site TEXT,
    mileage TEXT,
    location_note TEXT,
    direction TEXT,
    rid1_channel TEXT,
    rid1_bandwidth TEXT,
    rid1_tx_power TEXT,
    rid2_channel TEXT,
    rid2_bandwidth TEXT,
    rid2_tx_power TEXT,
    rid3_channel TEXT,
    rid3_bandwidth TEXT,
    rid3_tx_power TEXT,
    lldp_neighbor TEXT,
    ap_optical_power TEXT,
    collected_at TEXT NOT NULL,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(ac_device_uuid, serial_number)
);
"""

AC_FIT_AP_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ap_uuid TEXT NOT NULL UNIQUE,
    ap_name TEXT,
    site_name TEXT,
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
"""

AC_FIT_AP_LLDP_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_lldp_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT,
    ap_mac TEXT,
    local_interface TEXT,
    lldp_neighbor TEXT,
    neighbor_interface TEXT,
    neighbor_mac TEXT,
    neighbor_device_name TEXT,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT
);
"""

AC_FIT_AP_RADIO_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ac_fit_ap_radio_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ac_device_uuid TEXT NOT NULL,
    ap_uuid TEXT NOT NULL,
    ap_name TEXT,
    rid INTEGER,
    channel TEXT,
    bandwidth TEXT,
    tx_power TEXT,
    collected_at TEXT,
    collect_run_uuid TEXT,
    raw_log_path TEXT,
    created_at TEXT
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                "\n".join(
                    (
                        DEVICES_SCHEMA,
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
                        AC_FIT_AP_RESOURCE_HISTORY_SCHEMA,
                        AC_FIT_AP_OPTICAL_SCHEMA,
                        AC_STATION_AP_CAPACITY_SCHEMA,
                        AC_STATION_ONLINE_SUMMARY_HISTORY_SCHEMA,
                        AC_FIT_AP_OPTICAL_HISTORY_SCHEMA,
                        AC_FIT_AP_LLDP_HISTORY_SCHEMA,
                        AC_FIT_AP_RADIO_HISTORY_SCHEMA,
                        CONFIG_SNAPSHOTS_SCHEMA,
                    )
                )
            )
            conn.commit()

