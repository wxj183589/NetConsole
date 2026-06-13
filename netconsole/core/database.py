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
                    )
                )
            )
            conn.commit()
