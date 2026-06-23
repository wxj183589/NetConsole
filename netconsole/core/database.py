from __future__ import annotations

import sqlite3
from pathlib import Path


CURRENT_SCHEMA_VERSION = "2026.06.23.device_ap_rebuild"


class DatabaseSchemaMismatchError(RuntimeError):
    """Raised when an existing database is not on the current rebuild-only schema."""


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
    snmp_version TEXT,
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_ap_entities_site_ac_apid
    ON ap_entities(site_id, ac_device_uuid, ap_id)
    WHERE ap_id IS NOT NULL AND trim(ap_id) != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_ap_entities_site_ac_name
    ON ap_entities(site_id, ac_device_uuid, ap_name)
    WHERE ap_name IS NOT NULL AND trim(ap_name) != '';
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        existed = self.exists()
        conn = self.connect()
        try:
            if existed:
                self._assert_current_schema(conn)
            conn.executescript(
                "\n".join(
                    (
                        SCHEMA_METADATA_SCHEMA,
                        DEVICES_SCHEMA,
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
                        AC_FIT_AP_RESOURCE_HISTORY_SCHEMA,
                        AC_FIT_AP_OPTICAL_SCHEMA,
                        AP_ENTITIES_SCHEMA,
                        AP_RESOURCE_SNAPSHOTS_SCHEMA,
                        AP_LLDP_HISTORY_SCHEMA,
                        AP_OPTICAL_HISTORY_SCHEMA,
                        TRACKSIDE_AP_VIEW_CACHE_SCHEMA,
                        AC_STATION_AP_CAPACITY_SCHEMA,
                        AC_TRACKSIDE_AP_PLAN_SCHEMA,
                        AC_TRACKSIDE_AP_PLAN_SETTINGS_SCHEMA,
                        AC_STATION_ONLINE_SUMMARY_HISTORY_SCHEMA,
                        AC_FIT_AP_OPTICAL_HISTORY_SCHEMA,
                        AC_FIT_AP_LLDP_HISTORY_SCHEMA,
                        AC_FIT_AP_RADIO_HISTORY_SCHEMA,
                        CONFIG_SNAPSHOTS_SCHEMA,
                    )
                )
            )
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

    def _assert_current_schema(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "schema_metadata"):
            raise DatabaseSchemaMismatchError(self._schema_mismatch_message())
        row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
        if row is None or str(row["value"]) != CURRENT_SCHEMA_VERSION:
            raise DatabaseSchemaMismatchError(self._schema_mismatch_message())

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
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _schema_mismatch_message() -> str:
        return (
            "当前数据库结构与新版本不兼容。本次版本需要重建数据库。"
            "请先备份旧 data 目录，然后使用数据库重建工具或清空旧数据后重新初始化。"
        )

