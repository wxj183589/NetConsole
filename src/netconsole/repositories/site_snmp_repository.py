from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.models.snmp_models import DictionaryRecommendation, DeviceSnmpProfileResult, SnmpQueryResult, SnmpSetResult


SITE_SNMP_SCHEMA_VERSION = "2026.07.05.snmp_center"


SITE_SNMP_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snmp_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_snmp_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    snmp_enabled INTEGER DEFAULT 1,
    snmp_version TEXT,
    snmp_port INTEGER DEFAULT 161,
    community_ro TEXT,
    community_rw TEXT,
    snmpv3_username TEXT,
    snmpv3_security_level TEXT,
    snmpv3_auth_protocol TEXT,
    snmpv3_auth_key TEXT,
    snmpv3_priv_protocol TEXT,
    snmpv3_priv_key TEXT,
    snmp_context_name TEXT,
    snmp_timeout_ms INTEGER DEFAULT 2000,
    snmp_retries INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_snmp_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    device_name TEXT,
    vendor TEXT,
    device_type TEXT,
    model TEXT,
    system TEXT,
    system_version TEXT,
    sys_name TEXT,
    sys_object_id TEXT,
    sys_descr TEXT,
    sys_up_time TEXT,
    serial_number TEXT,
    interface_count INTEGER DEFAULT 0,
    source TEXT,
    status TEXT,
    latency_ms INTEGER DEFAULT 0,
    error_message TEXT,
    collected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_dictionary_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    dictionary_set_id INTEGER NOT NULL,
    enabled INTEGER DEFAULT 1,
    match_source TEXT,
    match_score INTEGER DEFAULT 0,
    manual_override INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(device_id, dictionary_set_id)
);
CREATE TABLE IF NOT EXISTS device_dictionary_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    dictionary_set_id INTEGER NOT NULL,
    match_score INTEGER DEFAULT 0,
    match_reasons_json TEXT DEFAULT '[]',
    status TEXT DEFAULT 'recommended',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(device_id, dictionary_set_id)
);
CREATE TABLE IF NOT EXISTS device_dictionary_validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    dictionary_set_id INTEGER NOT NULL,
    probe_oid TEXT,
    probe_name TEXT,
    probe_method TEXT,
    status TEXT,
    returned_count INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    error_message TEXT,
    validated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS site_oid_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL,
    scope TEXT DEFAULT 'site',
    vendor TEXT,
    device_type TEXT,
    dictionary_set_id INTEGER,
    module_name TEXT,
    object_name TEXT,
    numeric_oid TEXT NOT NULL,
    query_method TEXT NOT NULL,
    decoder TEXT,
    columns_json TEXT DEFAULT '[]',
    created_from_mib_module TEXT,
    created_from_mib_file TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snmp_query_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_time TEXT NOT NULL,
    device_id TEXT,
    device_name TEXT,
    method TEXT NOT NULL,
    oid TEXT NOT NULL,
    status TEXT NOT NULL,
    elapsed_ms INTEGER DEFAULT 0,
    result_count INTEGER DEFAULT 0,
    error_message TEXT,
    rows_json TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS snmp_set_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_time TEXT NOT NULL,
    device_id TEXT,
    device_name TEXT,
    device_ip TEXT,
    snmp_version TEXT,
    oid TEXT NOT NULL,
    object_name TEXT,
    module_name TEXT,
    data_type TEXT,
    old_value TEXT,
    new_value TEXT,
    result_value TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    operator TEXT
);
CREATE TABLE IF NOT EXISTS snmp_poll_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    device_id TEXT,
    template_id INTEGER,
    interval_seconds INTEGER DEFAULT 60,
    enabled INTEGER DEFAULT 1,
    status TEXT DEFAULT 'created',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snmp_poll_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    oid TEXT NOT NULL,
    query_method TEXT NOT NULL,
    decoder TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snmp_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    device_id TEXT,
    oid TEXT NOT NULL,
    raw_value TEXT,
    decoded_value TEXT,
    sampled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snmp_traps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trap_time TEXT NOT NULL,
    source_ip TEXT,
    source_device TEXT,
    trap_oid TEXT,
    trap_name TEXT,
    severity TEXT,
    content TEXT,
    varbinds_json TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS snmp_alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    condition_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snmp_alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    event_time TEXT NOT NULL,
    device_id TEXT,
    severity TEXT,
    status TEXT DEFAULT 'active',
    content TEXT,
    raw_json TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS topology_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    node_type TEXT,
    device_uuid TEXT,
    address TEXT,
    raw_json TEXT DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topology_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT,
    local_interface TEXT,
    remote_interface TEXT,
    discovery_source TEXT,
    confidence INTEGER DEFAULT 0,
    raw_json TEXT DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topology_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_name TEXT NOT NULL,
    snapshot_path TEXT,
    node_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


class SiteSnmpRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path)

    def initialize(self) -> None:
        with self.connect() as conn:
            initialize_sqlite_wal(conn)
            conn.executescript(SITE_SNMP_SCHEMA)
            self._write_schema_version(conn)
            conn.commit()

    def _write_schema_version(self, conn: sqlite3.Connection) -> None:
        now = _now()
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, created_at, updated_at)
            VALUES ('schema_version', ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (SITE_SNMP_SCHEMA_VERSION, now, now),
        )

    def save_device_profile(self, device_id: str, profile: DeviceSnmpProfileResult) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO device_snmp_profiles
                (device_id, device_name, vendor, device_type, model, system, system_version, sys_name, sys_object_id, sys_descr, sys_up_time, serial_number, interface_count, source, status, latency_ms, error_message, collected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    profile.device_name,
                    profile.vendor,
                    profile.device_type,
                    profile.model,
                    profile.system,
                    profile.system_version,
                    profile.sys_name,
                    profile.sys_object_id,
                    profile.sys_descr,
                    profile.sys_up_time,
                    profile.serial_number,
                    profile.interface_count,
                    profile.source,
                    profile.status,
                    profile.latency_ms,
                    profile.error_message,
                    _now(),
                ),
            )
            conn.commit()

    def latest_device_profile(self, device_id: str) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM device_snmp_profiles WHERE device_id = ? ORDER BY collected_at DESC, id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def save_recommendations(self, device_id: str, recommendations: list[DictionaryRecommendation]) -> None:
        now = _now()
        with self.connect() as conn:
            for item in recommendations:
                conn.execute(
                    """
                    INSERT INTO device_dictionary_recommendations
                    (device_id, dictionary_set_id, match_score, match_reasons_json, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_id, dictionary_set_id) DO UPDATE SET
                        match_score = excluded.match_score,
                        match_reasons_json = excluded.match_reasons_json,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (device_id, item.dictionary_set_id, item.score, json.dumps(item.reasons, ensure_ascii=False), item.status, now, now),
                )
            conn.commit()

    def apply_recommendations(self, device_id: str, recommendations: list[DictionaryRecommendation], *, source: str = "auto_sysdescr") -> None:
        now = _now()
        with self.connect() as conn:
            for item in recommendations:
                conn.execute(
                    """
                    INSERT INTO device_dictionary_bindings
                    (device_id, dictionary_set_id, enabled, match_source, match_score, manual_override, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?, 0, ?, ?)
                    ON CONFLICT(device_id, dictionary_set_id) DO UPDATE SET
                        enabled = 1,
                        match_source = excluded.match_source,
                        match_score = excluded.match_score,
                        updated_at = excluded.updated_at
                    """,
                    (device_id, item.dictionary_set_id, source, item.score, now, now),
                )
                conn.execute(
                    "UPDATE device_dictionary_recommendations SET status = 'applied', updated_at = ? WHERE device_id = ? AND dictionary_set_id = ?",
                    (now, device_id, item.dictionary_set_id),
                )
            conn.commit()

    def list_enabled_dictionary_ids(self, device_id: str) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT dictionary_set_id FROM device_dictionary_bindings WHERE device_id = ? AND enabled = 1 ORDER BY match_score DESC, id",
                (device_id,),
            ).fetchall()
            return [int(row["dictionary_set_id"]) for row in rows]

    def save_query_history(self, result: SnmpQueryResult) -> None:
        request = result.request
        rows = [
            {
                "oid": row.oid,
                "name": row.name,
                "instance": row.instance,
                "type": row.value_type,
                "raw_value": str(row.value),
                "decoded_value": row.decoded_value,
                "latency_ms": row.latency_ms,
                "status": row.status,
                "error_message": row.error_message,
            }
            for row in result.rows
        ]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO snmp_query_history
                (query_time, device_id, device_name, method, oid, status, elapsed_ms, result_count, error_message, rows_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.started_at,
                    request.device_id,
                    request.device_name,
                    request.method,
                    request.oid,
                    result.status,
                    result.elapsed_ms,
                    len(result.rows),
                    result.error_message,
                    json.dumps(rows, ensure_ascii=False),
                ),
            )
            conn.commit()

    def list_query_history(self, limit: int = 100) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM snmp_query_history ORDER BY query_time DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]

    def startup_summary(self) -> dict[str, object]:
        with self.connect() as conn:
            setting = conn.execute("SELECT value FROM snmp_settings WHERE key = 'snmp_set_enabled' LIMIT 1").fetchone()
            return {
                "query_history_count": int(conn.execute("SELECT COUNT(*) FROM snmp_query_history").fetchone()[0] or 0),
                "set_history_count": int(conn.execute("SELECT COUNT(*) FROM snmp_set_history").fetchone()[0] or 0),
                "dictionary_binding_count": int(conn.execute("SELECT COUNT(*) FROM device_dictionary_bindings WHERE enabled = 1").fetchone()[0] or 0),
                "snmp_set_enabled": str(setting["value"]) == "1" if setting is not None else False,
            }

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM snmp_settings WHERE key = ? LIMIT 1", (key,)).fetchone()
            return str(row["value"]) if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO snmp_settings (key, value, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now, now),
            )
            conn.commit()

    def snmp_set_enabled(self) -> bool:
        return self.get_setting("snmp_set_enabled", "0") == "1"

    def set_snmp_set_enabled(self, enabled: bool) -> None:
        self.set_setting("snmp_set_enabled", "1" if enabled else "0")

    def save_set_history(self, result: SnmpSetResult, *, operator: str = "") -> None:
        request = result.request
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO snmp_set_history
                (set_time, device_id, device_name, device_ip, snmp_version, oid, object_name, module_name, data_type, old_value, new_value, result_value, status, error_message, operator)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.started_at,
                    request.device_id,
                    request.device_name,
                    request.profile.host,
                    request.profile.version,
                    request.oid,
                    request.object_name,
                    request.module_name,
                    request.data_type,
                    result.old_value,
                    result.new_value,
                    result.result_value,
                    result.status,
                    result.error_message,
                    operator,
                ),
            )
            conn.commit()

    def list_set_history(self, limit: int = 100) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM snmp_set_history ORDER BY set_time DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_site_template(self, *, name: str, oid: str, method: str, module_name: str = "", object_name: str = "", dictionary_set_id: int | None = None) -> int:
        now = _now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO site_oid_templates
                (template_name, scope, vendor, device_type, dictionary_set_id, module_name, object_name, numeric_oid, query_method, decoder, columns_json, created_from_mib_module, created_from_mib_file, created_at, updated_at)
                VALUES (?, 'site', '', '', ?, ?, ?, ?, ?, '', '[]', ?, '', ?, ?)
                """,
                (name, dictionary_set_id, module_name, object_name, oid, method, module_name, now, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_site_templates(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM site_oid_templates ORDER BY template_name").fetchall()
            return [dict(row) for row in rows]

    def upsert_topology_nodes_edges(self, nodes: list[dict[str, object]], edges: list[dict[str, object]]) -> None:
        now = _now()
        with self.connect() as conn:
            for node in nodes:
                conn.execute(
                    """
                    INSERT INTO topology_nodes (node_id, name, node_type, device_uuid, address, raw_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        name = excluded.name,
                        node_type = excluded.node_type,
                        device_uuid = excluded.device_uuid,
                        address = excluded.address,
                        raw_json = excluded.raw_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(node.get("node_id") or ""),
                        str(node.get("name") or ""),
                        str(node.get("node_type") or "未知设备"),
                        str(node.get("device_uuid") or ""),
                        str(node.get("address") or ""),
                        json.dumps(node, ensure_ascii=False),
                        now,
                    ),
                )
            conn.execute("DELETE FROM topology_edges")
            for edge in edges:
                conn.execute(
                    """
                    INSERT INTO topology_edges
                    (source_id, target_id, edge_type, local_interface, remote_interface, discovery_source, confidence, raw_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(edge.get("source_id") or ""),
                        str(edge.get("target_id") or ""),
                        str(edge.get("edge_type") or "unknown"),
                        str(edge.get("local_interface") or ""),
                        str(edge.get("remote_interface") or ""),
                        str(edge.get("source") or ""),
                        int(edge.get("confidence") or 0),
                        json.dumps(edge, ensure_ascii=False),
                        now,
                    ),
                )
            conn.commit()

    def list_topology_nodes(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM topology_nodes ORDER BY name").fetchall()]

    def list_topology_edges(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM topology_edges ORDER BY source_id, target_id").fetchall()]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
