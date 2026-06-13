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
            conn.execute(DEVICES_SCHEMA)
            conn.commit()
