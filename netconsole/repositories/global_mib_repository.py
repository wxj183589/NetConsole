from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.models.mib_models import DictionarySetRecord, MibObjectRecord


GLOBAL_MIB_SCHEMA_VERSION = "2026.07.05.snmp_center"


def _oid_sort_key(value: object) -> tuple[int, tuple[int, ...], str]:
    text = str(value or "").strip().strip(".")
    parts = text.split(".") if text else []
    if not parts or any(not part.isdigit() for part in parts):
        return (1, (), text)
    return (0, tuple(int(part) for part in parts), text)


def _is_numeric_oid(value: object) -> bool:
    return _oid_sort_key(value)[0] == 0


def _product_tree_sort_key(row: dict[str, object]) -> tuple[object, ...]:
    node_type = str(row.get("node_type") or "")
    if node_type == "category":
        return (
            int(row.get("sort_order") or 0),
            str(row.get("display_name") or row.get("node_name") or ""),
            int(row.get("id") or 0),
        )
    sort_oid = row.get("sort_oid") or row.get("numeric_oid")
    if sort_oid:
        return (
            0,
            _oid_sort_key(sort_oid),
            str(row.get("display_name") or row.get("node_name") or ""),
            int(row.get("id") or 0),
        )
    return (
        1,
        int(row.get("sort_order") or 0),
        str(row.get("display_name") or row.get("node_name") or ""),
        int(row.get("id") or 0),
    )


GLOBAL_MIB_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mib_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor TEXT,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    product_line TEXT,
    product_name TEXT,
    software_version TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mib_source_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    vendor TEXT NOT NULL,
    product_line TEXT,
    version_line TEXT,
    package_version TEXT,
    package_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_file TEXT,
    file_hash TEXT,
    extract_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(file_hash)
);
CREATE TABLE IF NOT EXISTS mib_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    source_package_id INTEGER,
    file_name TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    compiled_path TEXT,
    module_name TEXT,
    file_hash TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    compile_status TEXT NOT NULL,
    missing_dependencies_json TEXT DEFAULT '[]',
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mib_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER,
    source_package_id INTEGER,
    module_name TEXT NOT NULL,
    module_version TEXT,
    vendor TEXT,
    status TEXT NOT NULL,
    compiled_path TEXT,
    object_count INTEGER DEFAULT 0,
    table_count INTEGER DEFAULT 0,
    trap_count INTEGER DEFAULT 0,
    notification_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mib_modules_name ON mib_modules(module_name);
CREATE TABLE IF NOT EXISTS mib_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER,
    name TEXT NOT NULL,
    oid TEXT NOT NULL,
    parent_oid TEXT,
    syntax TEXT,
    access TEXT,
    status TEXT,
    description TEXT,
    is_scalar INTEGER DEFAULT 0,
    is_table INTEGER DEFAULT 0,
    is_table_entry INTEGER DEFAULT 0,
    is_column INTEGER DEFAULT 0,
    is_trap INTEGER DEFAULT 0,
    is_notification INTEGER DEFAULT 0,
    table_name TEXT,
    entry_name TEXT,
    index_def TEXT,
    enum_map_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mib_objects_oid ON mib_objects(oid);
CREATE INDEX IF NOT EXISTS idx_mib_objects_name ON mib_objects(name);
CREATE TABLE IF NOT EXISTS mib_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER,
    dependency_module TEXT NOT NULL,
    resolved INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mib_compile_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER,
    module_name TEXT,
    status TEXT NOT NULL,
    report_path TEXT,
    missing_dependencies_json TEXT DEFAULT '[]',
    error_message TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dictionary_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_package_id INTEGER,
    name TEXT NOT NULL UNIQUE,
    vendor TEXT,
    device_type TEXT,
    model_pattern TEXT,
    os_pattern TEXT,
    sysobjectid_prefix TEXT,
    description TEXT,
    is_builtin INTEGER DEFAULT 0,
    enabled_by_default INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dictionary_set_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dictionary_set_id INTEGER NOT NULL,
    mib_module_id INTEGER NOT NULL,
    priority INTEGER DEFAULT 100,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(dictionary_set_id, mib_module_id)
);
CREATE TABLE IF NOT EXISTS dictionary_match_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dictionary_set_id INTEGER NOT NULL,
    vendor_pattern TEXT,
    device_type_pattern TEXT,
    model_pattern TEXT,
    os_pattern TEXT,
    sysdescr_pattern TEXT,
    sysobjectid_prefix TEXT,
    score INTEGER DEFAULT 0,
    probe_oids_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS global_oid_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL,
    scope TEXT DEFAULT 'global',
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
CREATE TABLE IF NOT EXISTS mib_product_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor TEXT,
    product_line TEXT,
    product_name TEXT,
    device_type TEXT,
    os_family TEXT,
    os_major TEXT,
    release_series TEXT,
    doc_version TEXT,
    software_version TEXT,
    reference_name TEXT NOT NULL,
    source_file TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    sheet_count INTEGER DEFAULT 0,
    object_count INTEGER DEFAULT 0,
    trap_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mib_product_reference_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    sheet_names_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mib_product_object_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    module_name TEXT,
    mib_file_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    object_scope TEXT,
    access_from_reference TEXT,
    data_type_from_reference TEXT,
    value_range TEXT,
    chinese_description TEXT,
    implementation_spec TEXT,
    operation_support TEXT,
    table_parent_name TEXT,
    table_index_info TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mib_product_object_oid ON mib_product_object_overrides(numeric_oid);
CREATE INDEX IF NOT EXISTS idx_mib_product_object_name ON mib_product_object_overrides(object_name);
CREATE TABLE IF NOT EXISTS mib_product_trap_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    category_name TEXT,
    module_name TEXT,
    mib_file_name TEXT,
    trap_name TEXT,
    trap_oid TEXT,
    trap_title TEXT,
    trap_type TEXT,
    trap_level TEXT,
    clear_trap_oid TEXT,
    clear_trap_name TEXT,
    default_status TEXT,
    trigger_reason TEXT,
    system_impact TEXT,
    status_control TEXT,
    varbind_oids TEXT,
    varbind_names TEXT,
    varbind_descriptions TEXT,
    varbind_index_nodes TEXT,
    varbind_types TEXT,
    varbind_value_ranges TEXT,
    suggestion TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mib_product_trap_oid ON mib_product_trap_overrides(trap_oid);
CREATE INDEX IF NOT EXISTS idx_mib_product_trap_name ON mib_product_trap_overrides(trap_name);
CREATE TABLE IF NOT EXISTS mib_product_reference_tree_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    parent_id INTEGER,
    node_type TEXT NOT NULL,
    node_key TEXT,
    node_name TEXT NOT NULL,
    display_name TEXT,
    category_name TEXT,
    module_name TEXT,
    mib_file_name TEXT,
    root_node_name TEXT,
    parent_node_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    meaning TEXT,
    sort_order INTEGER DEFAULT 0,
    object_count INTEGER DEFAULT 0,
    enabled_default INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mib_product_reference_tree_ref ON mib_product_reference_tree_nodes(reference_id, parent_id, node_type);
CREATE INDEX IF NOT EXISTS idx_mib_product_reference_tree_module ON mib_product_reference_tree_nodes(reference_id, module_name);
CREATE TABLE IF NOT EXISTS mib_product_reference_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    tree_node_id INTEGER,
    sheet_name TEXT,
    category_name TEXT,
    module_name TEXT,
    mib_file_name TEXT,
    root_node_name TEXT,
    parent_node_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    access_from_reference TEXT,
    data_type_from_reference TEXT,
    value_range TEXT,
    meaning TEXT,
    function_description TEXT,
    implementation_spec TEXT,
    operation_support TEXT,
    mib_object_id INTEGER,
    match_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mib_product_reference_objects_ref ON mib_product_reference_objects(reference_id, category_name, module_name);
CREATE INDEX IF NOT EXISTS idx_mib_product_reference_objects_oid ON mib_product_reference_objects(numeric_oid);
CREATE TABLE IF NOT EXISTS h3c_mib_canonical_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stable_key TEXT NOT NULL UNIQUE,
    key_type TEXT NOT NULL,
    module_name TEXT,
    mib_file_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS h3c_product_reference_overlays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_id INTEGER NOT NULL,
    canonical_object_id INTEGER,
    stable_key TEXT NOT NULL,
    category_name TEXT,
    category_number TEXT,
    category_title TEXT,
    module_name TEXT,
    mib_file_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    access_from_reference TEXT,
    data_type_from_reference TEXT,
    value_range TEXT,
    chinese_description TEXT,
    function_description TEXT,
    implementation_spec TEXT,
    operation_support TEXT,
    match_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(reference_id, stable_key)
);
CREATE INDEX IF NOT EXISTS idx_h3c_product_reference_overlays_ref ON h3c_product_reference_overlays(reference_id);
CREATE INDEX IF NOT EXISTS idx_h3c_product_reference_overlays_key ON h3c_product_reference_overlays(stable_key);
CREATE TABLE IF NOT EXISTS h3c_product_reference_compare_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    left_reference_id INTEGER NOT NULL,
    right_reference_id INTEGER NOT NULL,
    item_type TEXT NOT NULL,
    diff_type TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    module_name TEXT,
    mib_file_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    field_name TEXT,
    left_value TEXT,
    right_value TEXT,
    summary TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_h3c_product_reference_compare_pair ON h3c_product_reference_compare_results(left_reference_id, right_reference_id, diff_type);
CREATE TABLE IF NOT EXISTS mib_object_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER,
    module_name TEXT,
    object_name TEXT,
    numeric_oid TEXT,
    source_text TEXT,
    translated_text TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(module_name, object_name, numeric_oid, source_text)
);
"""


BUILTIN_OBJECTS = (
    ("SNMPv2-MIB", "sysDescr", "1.3.6.1.2.1.1.1", "DisplayString", "read-only", "系统描述", 1, 0),
    ("SNMPv2-MIB", "sysObjectID", "1.3.6.1.2.1.1.2", "OBJECT IDENTIFIER", "read-only", "设备对象标识", 1, 0),
    ("SNMPv2-MIB", "sysUpTime", "1.3.6.1.2.1.1.3", "TimeTicks", "read-only", "系统运行时间", 1, 0),
    ("SNMPv2-MIB", "sysName", "1.3.6.1.2.1.1.5", "DisplayString", "read-write", "系统名称", 1, 0),
    ("IF-MIB", "ifTable", "1.3.6.1.2.1.2.2", "SEQUENCE OF IfEntry", "not-accessible", "接口表", 0, 1),
    ("IF-MIB", "ifDescr", "1.3.6.1.2.1.2.2.1.2", "DisplayString", "read-only", "接口描述", 0, 0),
    ("IF-MIB", "ifType", "1.3.6.1.2.1.2.2.1.3", "INTEGER", "read-only", "接口类型", 0, 0),
    ("IF-MIB", "ifAdminStatus", "1.3.6.1.2.1.2.2.1.7", "INTEGER", "read-write", "接口管理状态", 0, 0),
    ("IF-MIB", "ifOperStatus", "1.3.6.1.2.1.2.2.1.8", "INTEGER", "read-only", "接口运行状态", 0, 0),
    ("IF-MIB", "ifHCInOctets", "1.3.6.1.2.1.31.1.1.1.6", "Counter64", "read-only", "接口入方向字节计数", 0, 0),
    ("IF-MIB", "ifHCOutOctets", "1.3.6.1.2.1.31.1.1.1.10", "Counter64", "read-only", "接口出方向字节计数", 0, 0),
    ("LLDP-MIB", "lldpRemTable", "1.0.8802.1.1.2.1.4.1", "SEQUENCE OF LldpRemEntry", "not-accessible", "LLDP 邻居表", 0, 1),
    ("ENTITY-MIB", "entPhysicalDescr", "1.3.6.1.2.1.47.1.1.1.1.2", "SnmpAdminString", "read-only", "实体描述", 0, 0),
    ("HOST-RESOURCES-MIB", "hrSystemUptime", "1.3.6.1.2.1.25.1.1", "TimeTicks", "read-only", "主机运行时间", 1, 0),
)


STANDARD_DEPENDENCY_MODULES = (
    "SNMPv2-SMI",
    "SNMPv2-TC",
    "SNMPv2-CONF",
    "SNMP-FRAMEWORK-MIB",
    "IF-MIB",
    "INET-ADDRESS-MIB",
    "IANAifType-MIB",
    "BRIDGE-MIB",
    "Q-BRIDGE-MIB",
    "ENTITY-MIB",
    "HOST-RESOURCES-MIB",
    "LLDP-MIB",
    "IEEE8021-PAE-MIB",
    "RFC1155-SMI",
    "RFC-1212",
    "RFC-1215",
)

H3C_CORE_DEPENDENCY_MODULES = (
    "HH3C-OID-MIB",
    "HH3C-COMMON-MIB",
    "HH3C-TC-MIB",
    "HH3C-DOT11-REF-MIB",
)

H3C_WIRELESS_MODULES = (
    "HH3C-DOT11-REF-MIB",
    "HH3C-DOT11-APMT-MIB",
    "HH3C-DOT11-STATION-MIB",
    "HH3C-DOT11S-MESH-MIB",
    "HH3C-DOT11-ACMT-MIB",
    "HH3C-DOT11-CFG-MIB",
    "HH3C-DOT11-RRM-MIB",
    "HH3C-WLANMT-MIB",
)


BUILTIN_TEMPLATES = (
    ("系统信息", "SNMPv2-MIB", "sysName", "1.3.6.1.2.1.1.5.0", "Get"),
    ("系统描述", "SNMPv2-MIB", "sysDescr", "1.3.6.1.2.1.1.1.0", "Get"),
    ("系统运行时间", "SNMPv2-MIB", "sysUpTime", "1.3.6.1.2.1.1.3.0", "Get"),
    ("接口基础信息", "IF-MIB", "ifTable", "1.3.6.1.2.1.2.2", "BulkWalk"),
    ("接口流量", "IF-MIB", "ifHCInOctets", "1.3.6.1.2.1.31.1.1.1.6", "BulkWalk"),
    ("接口错误包", "IF-MIB", "ifInErrors", "1.3.6.1.2.1.2.2.1.14", "BulkWalk"),
    ("LLDP 邻居", "LLDP-MIB", "lldpRemTable", "1.0.8802.1.1.2.1.4.1", "BulkWalk"),
    ("实体信息", "ENTITY-MIB", "entPhysicalDescr", "1.3.6.1.2.1.47.1.1.1.1.2", "BulkWalk"),
)


H3C_MESH_MODULE = "HH3C-DOT11S-MESH-MIB"
H3C_MESH_ROOT_OID = "1.3.6.1.4.1.25506.2.75.11"
H3C_MESH_TEMPLATES = (
    (
        "Mesh 链路状态模板",
        "hh3cDot11sMeshLinkStatusTable",
        "1.3.6.1.4.1.25506.2.75.11.3.1",
        "BulkWalk",
        [
            "Mesh 链路名称",
            "本端 BSSID",
            "对端 MAC",
            "链路时长",
            "active/dormant",
            "SNR",
            "Noise",
            "对端 SNR",
            "对端 Noise",
            "对端 IP",
            "对端系统名",
        ],
    ),
    (
        "Mesh 链路统计模板",
        "hh3cDot11sMeshLinkStatisTable",
        "1.3.6.1.4.1.25506.2.75.11.3.2",
        "BulkWalk",
        [
            "Rx/Tx 字节",
            "Rx/Tx 包数",
            "广播",
            "组播",
            "丢弃包",
            "Mesh 接口名",
            "Counter32 字段需周期采样计算速率",
        ],
    ),
    (
        "Mesh 邻居状态模板",
        "hh3cDot11sMeshNbrStatusTable",
        "1.3.6.1.4.1.25506.2.75.11.3.3",
        "BulkWalk",
        ["邻居 Radio", "Mesh ID", "BSSID", "Peer MAC", "链路状态", "信道", "链路时长", "RSSI", "SNR"],
    ),
    (
        "Mesh 链路切换 Trap 解析模板",
        "hh3cDot11sMeshLinkSwitchTrap",
        "1.3.6.1.4.1.25506.2.75.11.4.0.1",
        "Trap",
        ["hh3cDot11sMeshLinkBSSIDMAC", "hh3cDot11sMeshLinkPeerMAC"],
    ),
)


class GlobalMibRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path)

    def initialize(self) -> None:
        with self.connect() as conn:
            initialize_sqlite_wal(conn)
            conn.executescript(GLOBAL_MIB_SCHEMA)
            self._ensure_schema_columns(conn)
            self._rebuild_mib_files_without_hash_unique(conn)
            self._write_schema_version(conn)
            self.seed_builtin(conn)
            conn.commit()

    def _ensure_schema_columns(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(conn, "mib_files", "source_package_id", "INTEGER")
        self._ensure_column(conn, "mib_modules", "source_package_id", "INTEGER")
        self._ensure_column(conn, "dictionary_sets", "source_package_id", "INTEGER")
        for column, definition in {
            "category_name": "TEXT",
            "root_node_name": "TEXT",
            "parent_node_name": "TEXT",
            "function_description": "TEXT",
            "mib_object_id": "INTEGER",
            "match_status": "TEXT",
        }.items():
            self._ensure_column(conn, "mib_product_object_overrides", column, definition)
        self._ensure_column(conn, "mib_product_trap_overrides", "category_name", "TEXT")
        for column, definition in {
            "node_key": "TEXT",
            "category_name": "TEXT",
            "mib_file_name": "TEXT",
            "root_node_name": "TEXT",
            "parent_node_name": "TEXT",
            "object_name": "TEXT",
            "object_count": "INTEGER DEFAULT 0",
        }.items():
            self._ensure_column(conn, "mib_product_reference_tree_nodes", column, definition)
        for column, definition in {
            "sheet_name": "TEXT",
            "access_from_reference": "TEXT",
            "data_type_from_reference": "TEXT",
            "value_range": "TEXT",
            "implementation_spec": "TEXT",
        }.items():
            self._ensure_column(conn, "mib_product_reference_objects", column, definition)
        for column, definition in {
            "device_type": "TEXT",
            "os_family": "TEXT",
            "os_major": "TEXT",
            "release_series": "TEXT",
            "doc_version": "TEXT",
            "sheet_count": "INTEGER DEFAULT 0",
            "object_count": "INTEGER DEFAULT 0",
            "trap_count": "INTEGER DEFAULT 0",
        }.items():
            self._ensure_column(conn, "mib_product_references", column, definition)

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER {'TABLE'} {table} ADD COLUMN {column} {definition}")

    def _rebuild_mib_files_without_hash_unique(self, conn: sqlite3.Connection) -> None:
        table_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'mib_files'").fetchone()
        if table_sql is None or "UNIQUE(file_hash)" not in str(table_sql["sql"]):
            return
        conn.execute("ALTER TABLE mib_files RENAME TO mib_files_old")
        conn.executescript(
            """
            CREATE TABLE mib_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                source_package_id INTEGER,
                file_name TEXT NOT NULL,
                raw_path TEXT NOT NULL,
                compiled_path TEXT,
                module_name TEXT,
                file_hash TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                compile_status TEXT NOT NULL,
                missing_dependencies_json TEXT DEFAULT '[]',
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO mib_files
            (id, source_id, source_package_id, file_name, raw_path, compiled_path, module_name, file_hash, file_size, compile_status, missing_dependencies_json, error_message, created_at, updated_at)
            SELECT id, source_id, source_package_id, file_name, raw_path, compiled_path, module_name, file_hash, file_size, compile_status, missing_dependencies_json, error_message, created_at, updated_at
            FROM mib_files_old;
            DROP TABLE mib_files_old;
            """
        )

    def _write_schema_version(self, conn: sqlite3.Connection) -> None:
        now = _now()
        conn.execute(
            """
            INSERT INTO schema_metadata (key, value, created_at, updated_at)
            VALUES ('schema_version', ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (GLOBAL_MIB_SCHEMA_VERSION, now, now),
        )

    def seed_builtin(self, conn: sqlite3.Connection | None = None) -> None:
        owns_conn = conn is None
        conn = conn or self.connect()
        try:
            now = _now()
            source_id = self._ensure_source(conn, "标准组织", "内置标准 MIB", "builtin")
            module_ids: dict[str, int] = {}
            for module_name in sorted(set(STANDARD_DEPENDENCY_MODULES) | {item[0] for item in BUILTIN_OBJECTS}):
                row = conn.execute(
                    "SELECT id FROM mib_modules WHERE module_name = ? AND file_id IS NULL AND vendor = 'IETF'",
                    (module_name,),
                ).fetchone()
                if row is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO mib_modules
                        (file_id, source_package_id, module_name, module_version, vendor, status, compiled_path, object_count, table_count, trap_count, notification_count, error_message, created_at, updated_at)
                        VALUES (NULL, NULL, ?, 'builtin', 'IETF', 'compiled', '', 0, 0, 0, 0, '', ?, ?)
                        """,
                        (module_name, now, now),
                    )
                    module_id = int(cursor.lastrowid)
                else:
                    module_id = int(row["id"])
                module_ids[module_name] = module_id
            for module_name, name, oid, syntax, access, description, is_scalar, is_table in BUILTIN_OBJECTS:
                module_id = module_ids[module_name]
                exists = conn.execute(
                    "SELECT 1 FROM mib_objects WHERE module_id = ? AND name = ? AND oid = ? LIMIT 1",
                    (module_id, name, oid),
                ).fetchone()
                if exists:
                    continue
                parent_oid = ".".join(oid.split(".")[:-1])
                conn.execute(
                    """
                    INSERT INTO mib_objects
                    (module_id, name, oid, parent_oid, syntax, access, status, description, is_scalar, is_table, is_table_entry, is_column, is_trap, is_notification, table_name, entry_name, index_def, enum_map_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'current', ?, ?, ?, 0, ?, 0, 0, ?, '', '', ?, ?, ?)
                    """,
                    (
                        module_id,
                        name,
                        oid,
                        parent_oid,
                        syntax,
                        access,
                        description,
                        int(is_scalar),
                        int(is_table),
                        0 if is_table else 1,
                        name if is_table else "",
                        _enum_map_for(name),
                        now,
                        now,
                    ),
                )
            self._refresh_module_counts(conn)
            dictionary_id = self.ensure_dictionary_set(
                DictionarySetRecord(
                    name="内置通用字典",
                    vendor="标准",
                    device_type="通用",
                    description="设备基础信息、接口、LLDP、实体信息等通用 SNMP 对象。",
                    is_builtin=1,
                    enabled_by_default=1,
                ),
                conn=conn,
            )
            for module_id in module_ids.values():
                self.add_dictionary_module(dictionary_id, module_id, conn=conn)
            rule_exists = conn.execute("SELECT 1 FROM dictionary_match_rules WHERE dictionary_set_id = ? LIMIT 1", (dictionary_id,)).fetchone()
            if rule_exists is None:
                conn.execute(
                    """
                    INSERT INTO dictionary_match_rules
                    (dictionary_set_id, vendor_pattern, device_type_pattern, model_pattern, os_pattern, sysdescr_pattern, sysobjectid_prefix, score, probe_oids_json, created_at, updated_at)
                    VALUES (?, '', '', '', '', '', '', 100, ?, ?, ?)
                    """,
                    (dictionary_id, json.dumps(["1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.2.2.1.2"], ensure_ascii=False), now, now),
                )
            for name, module, obj, oid, method in BUILTIN_TEMPLATES:
                exists = conn.execute(
                    "SELECT 1 FROM global_oid_templates WHERE template_name = ? AND numeric_oid = ? LIMIT 1",
                    (name, oid),
                ).fetchone()
                if exists:
                    continue
                conn.execute(
                    """
                    INSERT INTO global_oid_templates
                    (template_name, scope, vendor, device_type, dictionary_set_id, module_name, object_name, numeric_oid, query_method, decoder, columns_json, created_from_mib_module, created_from_mib_file, created_at, updated_at)
                    VALUES (?, 'global', '标准', '通用', ?, ?, ?, ?, ?, '', '[]', ?, '', ?, ?)
                    """,
                    (name, dictionary_id, module, obj, oid, method, module, now, now),
                )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    def create_source(self, *, vendor: str, source_name: str, source_type: str = "manual", source_url: str = "", product_line: str = "", product_name: str = "", software_version: str = "", description: str = "") -> int:
        with self.connect() as conn:
            source_id = self._ensure_source(
                conn,
                vendor=vendor,
                source_name=source_name,
                source_type=source_type,
                source_url=source_url,
                product_line=product_line,
                product_name=product_name,
                software_version=software_version,
                description=description,
            )
            conn.commit()
            return source_id

    def _ensure_source(self, conn: sqlite3.Connection, vendor: str, source_name: str, source_type: str, source_url: str = "", product_line: str = "", product_name: str = "", software_version: str = "", description: str = "") -> int:
        row = conn.execute(
            "SELECT id FROM mib_sources WHERE vendor = ? AND source_name = ? AND source_type = ? LIMIT 1",
            (vendor, source_name, source_type),
        ).fetchone()
        if row is not None:
            return int(row["id"])
        now = _now()
        cursor = conn.execute(
            """
            INSERT INTO mib_sources
            (vendor, source_name, source_type, source_url, product_line, product_name, software_version, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (vendor, source_name, source_type, source_url, product_line, product_name, software_version, description, now, now),
        )
        return int(cursor.lastrowid)

    def get_file_by_hash(self, file_hash: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM mib_files WHERE file_hash = ?", (file_hash,)).fetchone()

    def ensure_source_package(self, *, source_id: int | None, vendor: str, product_line: str, version_line: str, package_version: str, package_name: str, source_type: str, source_file: str, file_hash: str, extract_path: str) -> int:
        now = _now()
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM mib_source_packages WHERE file_hash = ? LIMIT 1", (file_hash,)).fetchone()
            if row is not None:
                package_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE mib_source_packages SET source_id = ?, vendor = ?, product_line = ?, version_line = ?, package_version = ?, package_name = ?, source_type = ?, source_file = ?, extract_path = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (source_id, vendor, product_line, version_line, package_version, package_name, source_type, source_file, extract_path, now, package_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO mib_source_packages
                    (source_id, vendor, product_line, version_line, package_version, package_name, source_type, source_file, file_hash, extract_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source_id, vendor, product_line, version_line, package_version, package_name, source_type, source_file, file_hash, extract_path, now, now),
                )
                package_id = int(cursor.lastrowid)
            conn.commit()
            return package_id

    def get_source_package_by_hash(self, file_hash: str) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM mib_source_packages WHERE file_hash = ? LIMIT 1", (file_hash,)).fetchone()
            return dict(row) if row is not None else None

    def remove_source_package_by_file_hash(self, file_hash: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM mib_source_packages WHERE file_hash = ? LIMIT 1", (file_hash,)).fetchone()
            if row is None:
                return
            package_id = int(row["id"])
            module_ids = [int(item["id"]) for item in conn.execute("SELECT id FROM mib_modules WHERE source_package_id = ?", (package_id,)).fetchall()]
            for module_id in module_ids:
                conn.execute("DELETE FROM mib_objects WHERE module_id = ?", (module_id,))
                conn.execute("DELETE FROM mib_dependencies WHERE module_id = ?", (module_id,))
            file_ids = [int(item["id"]) for item in conn.execute("SELECT id FROM mib_files WHERE source_package_id = ?", (package_id,)).fetchall()]
            for file_id in file_ids:
                conn.execute("DELETE FROM mib_compile_reports WHERE file_id = ?", (file_id,))
            conn.execute("DELETE FROM dictionary_set_modules WHERE mib_module_id IN (SELECT id FROM mib_modules WHERE source_package_id = ?)", (package_id,))
            conn.execute("DELETE FROM dictionary_sets WHERE source_package_id = ?", (package_id,))
            conn.execute("DELETE FROM mib_modules WHERE source_package_id = ?", (package_id,))
            conn.execute("DELETE FROM mib_files WHERE source_package_id = ?", (package_id,))
            conn.execute("DELETE FROM mib_source_packages WHERE id = ?", (package_id,))
            conn.commit()

    def insert_mib_file(self, *, source_id: int | None, source_package_id: int | None = None, file_name: str, raw_path: str, compiled_path: str, module_name: str, file_hash: str, file_size: int, compile_status: str, missing_dependencies: list[str], error_message: str) -> int:
        now = _now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mib_files
                (source_id, source_package_id, file_name, raw_path, compiled_path, module_name, file_hash, file_size, compile_status, missing_dependencies_json, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, source_package_id, file_name, raw_path, compiled_path, module_name, file_hash, file_size, compile_status, json.dumps(missing_dependencies, ensure_ascii=False), error_message, now, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def upsert_module_with_objects(self, *, file_id: int, source_package_id: int | None = None, module_name: str, vendor: str, status: str, compiled_path: str, objects: Iterable[MibObjectRecord], dependencies: list[str], missing_dependencies: list[str], error_message: str) -> int:
        now = _now()
        objects = list(objects)
        is_compiled = status == "compiled"
        stored_objects = objects if is_compiled else []
        table_count = sum(1 for item in stored_objects if item.is_table)
        trap_count = sum(1 for item in stored_objects if item.is_trap)
        notification_count = sum(1 for item in stored_objects if item.is_notification)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mib_modules
                (file_id, source_package_id, module_name, module_version, vendor, status, compiled_path, object_count, table_count, trap_count, notification_count, error_message, created_at, updated_at)
                VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, source_package_id, module_name, vendor, status, compiled_path, len(stored_objects), table_count, trap_count, notification_count, error_message, now, now),
            )
            module_id = int(cursor.lastrowid)
            for item in stored_objects:
                conn.execute(
                    """
                    INSERT INTO mib_objects
                    (module_id, name, oid, parent_oid, syntax, access, status, description, is_scalar, is_table, is_table_entry, is_column, is_trap, is_notification, table_name, entry_name, index_def, enum_map_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        module_id,
                        item.name,
                        item.oid,
                        item.parent_oid,
                        item.syntax,
                        item.access,
                        item.status,
                        item.description,
                        item.is_scalar,
                        item.is_table,
                        item.is_table_entry,
                        item.is_column,
                        item.is_trap,
                        item.is_notification,
                        item.table_name,
                        item.entry_name,
                        item.index_def,
                        item.enum_map_json,
                        now,
                        now,
                    ),
                )
            for dependency in dependencies:
                resolved = 0 if dependency in missing_dependencies else 1
                conn.execute(
                    "INSERT INTO mib_dependencies (module_id, dependency_module, resolved, created_at) VALUES (?, ?, ?, ?)",
                    (module_id, dependency, resolved, now),
                )
            conn.execute(
                """
                INSERT INTO mib_compile_reports
                (file_id, module_name, status, report_path, missing_dependencies_json, error_message, created_at)
                VALUES (?, ?, ?, '', ?, ?, ?)
                """,
                (file_id, module_name, status, json.dumps(missing_dependencies, ensure_ascii=False), error_message, now),
            )
            if is_compiled and module_name.upper() == H3C_MESH_MODULE:
                self._ensure_h3c_mesh_dictionary_and_templates(conn, module_id, source_package_id=source_package_id)
            conn.commit()
            return module_id

    def ensure_dictionary_set(self, record: DictionarySetRecord, *, conn: sqlite3.Connection | None = None) -> int:
        owns_conn = conn is None
        conn = conn or self.connect()
        try:
            row = conn.execute("SELECT id FROM dictionary_sets WHERE name = ?", (record.name,)).fetchone()
            now = _now()
            if row is not None:
                dictionary_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE dictionary_sets SET source_package_id = ?, vendor = ?, device_type = ?, model_pattern = ?, os_pattern = ?, sysobjectid_prefix = ?, description = ?, is_builtin = ?, enabled_by_default = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (record.source_package_id, record.vendor, record.device_type, record.model_pattern, record.os_pattern, record.sysobjectid_prefix, record.description, int(record.is_builtin), int(record.enabled_by_default), now, dictionary_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO dictionary_sets
                    (source_package_id, name, vendor, device_type, model_pattern, os_pattern, sysobjectid_prefix, description, is_builtin, enabled_by_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record.source_package_id, record.name, record.vendor, record.device_type, record.model_pattern, record.os_pattern, record.sysobjectid_prefix, record.description, int(record.is_builtin), int(record.enabled_by_default), now, now),
                )
                dictionary_id = int(cursor.lastrowid)
            if owns_conn:
                conn.commit()
            return dictionary_id
        finally:
            if owns_conn:
                conn.close()

    def add_dictionary_module(self, dictionary_set_id: int, module_id: int, priority: int = 100, *, conn: sqlite3.Connection | None = None) -> None:
        owns_conn = conn is None
        conn = conn or self.connect()
        try:
            now = _now()
            conn.execute(
                """
                INSERT INTO dictionary_set_modules
                (dictionary_set_id, mib_module_id, priority, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(dictionary_set_id, mib_module_id) DO UPDATE SET priority = excluded.priority, enabled = 1, updated_at = excluded.updated_at
                """,
                (dictionary_set_id, module_id, priority, now, now),
            )
            if owns_conn:
                conn.commit()
        finally:
            if owns_conn:
                conn.close()

    def list_modules(self, module_ids: list[int] | None = None) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if module_ids is not None:
            if not module_ids:
                return []
            placeholders = ",".join("?" for _ in module_ids)
            clauses.append(f"m.id IN ({placeholders})")
            params.extend(module_ids)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*, p.package_name, p.version_line, p.package_version
                FROM mib_modules m
                LEFT JOIN mib_source_packages p ON p.id = m.source_package_id
                {where}
                ORDER BY m.module_name, m.id
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def list_dictionary_modules(self, dictionary_set_id: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*, dsm.priority, p.package_name, p.version_line, p.package_version
                FROM dictionary_set_modules dsm
                JOIN mib_modules m ON m.id = dsm.mib_module_id
                LEFT JOIN mib_source_packages p ON p.id = m.source_package_id
                WHERE dsm.dictionary_set_id = ? AND dsm.enabled = 1
                ORDER BY dsm.priority, m.module_name, m.id
                """,
                (int(dictionary_set_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def find_modules_by_names(self, module_names: Iterable[str], *, version_line: str = "") -> list[dict[str, object]]:
        names = sorted({str(name).strip() for name in module_names if str(name).strip()})
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        clauses = [f"m.module_name IN ({placeholders})", "m.status = 'compiled'"]
        params: list[object] = list(names)
        if version_line:
            clauses.append("p.version_line = ?")
            params.append(version_line)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*, p.package_name, p.version_line, p.package_version
                FROM mib_modules m
                LEFT JOIN mib_source_packages p ON p.id = m.source_package_id
                WHERE {' AND '.join(clauses)}
                ORDER BY m.module_name, m.id
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def list_files(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT f.*, p.package_name, p.version_line, p.package_version
                FROM mib_files f
                LEFT JOIN mib_source_packages p ON p.id = f.source_package_id
                ORDER BY f.created_at DESC, f.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_source_packages(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM mib_files f WHERE f.source_package_id = p.id) AS file_count,
                       (SELECT COUNT(*) FROM mib_modules m WHERE m.source_package_id = p.id) AS module_count
                FROM mib_source_packages p
                ORDER BY p.created_at DESC, p.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def startup_summary(self) -> dict[str, object]:
        with self.connect() as conn:
            packages = conn.execute(
                """
                SELECT source_type, version_line, COUNT(*) AS package_count
                FROM mib_source_packages
                GROUP BY source_type, version_line
                """
            ).fetchall()
            return {
                "module_count": int(conn.execute("SELECT COUNT(*) FROM mib_modules").fetchone()[0] or 0),
                "object_count": int(conn.execute("SELECT COUNT(*) FROM mib_objects").fetchone()[0] or 0),
                "dictionary_count": int(conn.execute("SELECT COUNT(*) FROM dictionary_sets").fetchone()[0] or 0),
                "product_reference_count": int(conn.execute("SELECT COUNT(*) FROM mib_product_references").fetchone()[0] or 0),
                "h3c_v5_registered": any(str(row["source_type"]) == "builtin_h3c_comware_package" and str(row["version_line"]) == "V5" for row in packages),
                "h3c_v7v9_registered": any(str(row["source_type"]) == "builtin_h3c_comware_package" and str(row["version_line"]) == "V7/V9" for row in packages),
            }

    def list_dictionary_sets(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM dictionary_sets ORDER BY is_builtin DESC, name").fetchall()
            return [dict(row) for row in rows]

    def list_objects(self, search: str = "", module_name: str = "", limit: int = 1000, source_filter: str = "", dictionary_ids: list[int] | None = None, module_id: int | None = None, module_ids: list[int] | None = None) -> list[dict[str, object]]:
        clauses: list[str] = ["o.oid <> ''", "o.oid GLOB '[1-9]*'", "o.oid NOT LIKE '%.%.'", "o.oid NOT LIKE '% %'"]
        params: list[object] = []
        if search:
            like = f"%{search}%"
            clauses.append(
                """
                (o.name LIKE ? OR o.oid LIKE ? OR o.description LIKE ?
                 OR EXISTS (
                    SELECT 1 FROM mib_product_object_overrides po
                    WHERE (po.numeric_oid = o.oid OR po.object_name = o.name)
                      AND (po.chinese_description LIKE ? OR po.implementation_spec LIKE ? OR po.operation_support LIKE ?)
                 ))
                """
            )
            params.extend([like, like, like, like, like, like])
        if module_name:
            clauses.append("m.module_name = ?")
            params.append(module_name)
        if module_id:
            clauses.append("m.id = ?")
            params.append(int(module_id))
        if module_ids is not None:
            if not module_ids:
                return []
            placeholders = ",".join("?" for _ in module_ids)
            clauses.append(f"m.id IN ({placeholders})")
            params.extend(int(item) for item in module_ids)
        if source_filter == "h3c_v5":
            clauses.append("p.vendor = 'H3C' AND p.version_line = 'V5'")
        elif source_filter == "h3c_v7v9":
            clauses.append("p.vendor = 'H3C' AND p.version_line = 'V7/V9'")
        elif source_filter == "standard":
            clauses.append("(m.module_name LIKE 'SNMP%' OR m.module_name LIKE 'IF-%' OR m.module_name LIKE 'IANA%' OR m.module_name LIKE 'INET-%' OR m.module_name LIKE 'IEEE%' OR m.module_name LIKE 'LLDP-%' OR m.module_name LIKE 'ENTITY-%' OR m.module_name LIKE 'HOST-%' OR m.module_name LIKE 'Q-BRIDGE%' OR m.module_name LIKE 'BRIDGE-%' OR m.module_name LIKE 'RFC%')")
        elif source_filter == "h3c_common":
            clauses.append("m.module_name LIKE 'HH3C-%' AND m.module_name NOT LIKE '%DOT11%' AND m.module_name NOT LIKE '%WLAN%'")
        elif source_filter == "h3c_wireless":
            clauses.append("(m.module_name LIKE '%DOT11%' OR m.module_name LIKE '%WLAN%')")
        elif source_filter == "builtin_common":
            clauses.append("m.file_id IS NULL")
        elif source_filter == "user_import":
            clauses.append("(p.source_type IS NULL OR p.source_type <> 'builtin_h3c_comware_package') AND m.file_id IS NOT NULL")
        if dictionary_ids:
            placeholders = ",".join("?" for _ in dictionary_ids)
            clauses.append(f"m.id IN (SELECT mib_module_id FROM dictionary_set_modules WHERE dictionary_set_id IN ({placeholders}) AND enabled = 1)")
            params.extend(dictionary_ids)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT o.*, m.module_name, m.source_package_id, p.package_name, p.version_line, p.package_version
                FROM mib_objects o
                LEFT JOIN mib_modules m ON m.id = o.module_id
                LEFT JOIN mib_source_packages p ON p.id = m.source_package_id
                {where}
                ORDER BY o.oid
                LIMIT ?
                """,
                params,
            ).fetchall()
            return sorted((dict(row) for row in rows), key=lambda row: (_oid_sort_key(row.get("oid")), str(row.get("name") or "")))

    def list_oid_children(self, parent_oid: str, *, source_filter: str = "", dictionary_ids: list[int] | None = None, module_ids: list[int] | None = None, limit: int = 500) -> list[dict[str, object]]:
        child_like = f"{parent_oid}.%"
        clauses = [
            "(o.parent_oid = ? OR (o.oid LIKE ? AND substr(o.oid, length(?) + 2) NOT LIKE '%.%'))",
            "o.oid <> ''",
            "o.oid GLOB '[1-9]*'",
            "o.oid NOT LIKE '%.%.'",
            "o.oid NOT LIKE '% %'",
        ]
        params: list[object] = [parent_oid, child_like, parent_oid]
        if source_filter == "h3c_v5":
            clauses.append("p.vendor = 'H3C' AND p.version_line = 'V5'")
        elif source_filter == "h3c_v7v9":
            clauses.append("p.vendor = 'H3C' AND p.version_line = 'V7/V9'")
        elif source_filter == "standard":
            clauses.append("(m.module_name LIKE 'SNMP%' OR m.module_name LIKE 'IF-%' OR m.module_name LIKE 'IANA%' OR m.module_name LIKE 'INET-%' OR m.module_name LIKE 'IEEE%' OR m.module_name LIKE 'LLDP-%' OR m.module_name LIKE 'ENTITY-%' OR m.module_name LIKE 'HOST-%' OR m.module_name LIKE 'Q-BRIDGE%' OR m.module_name LIKE 'BRIDGE-%' OR m.module_name LIKE 'RFC%')")
        elif source_filter == "h3c_common":
            clauses.append("m.module_name LIKE 'HH3C-%' AND m.module_name NOT LIKE '%DOT11%' AND m.module_name NOT LIKE '%WLAN%'")
        elif source_filter == "h3c_wireless":
            clauses.append("(m.module_name LIKE '%DOT11%' OR m.module_name LIKE '%WLAN%')")
        elif source_filter == "builtin_common":
            clauses.append("m.file_id IS NULL")
        elif source_filter == "user_import":
            clauses.append("(p.source_type IS NULL OR p.source_type <> 'builtin_h3c_comware_package') AND m.file_id IS NOT NULL")
        if dictionary_ids:
            placeholders = ",".join("?" for _ in dictionary_ids)
            clauses.append(f"m.id IN (SELECT mib_module_id FROM dictionary_set_modules WHERE dictionary_set_id IN ({placeholders}) AND enabled = 1)")
            params.extend(dictionary_ids)
        if module_ids is not None:
            if not module_ids:
                return []
            placeholders = ",".join("?" for _ in module_ids)
            clauses.append(f"m.id IN ({placeholders})")
            params.extend(int(item) for item in module_ids)
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT o.*, m.module_name, m.source_package_id, m.file_id, p.package_name, p.version_line, p.package_version
                FROM mib_objects o
                LEFT JOIN mib_modules m ON m.id = o.module_id
                LEFT JOIN mib_source_packages p ON p.id = m.source_package_id
                WHERE {' AND '.join(clauses)}
                ORDER BY o.oid, o.name
                LIMIT ?
                """,
                params,
            ).fetchall()
            return sorted((dict(row) for row in rows), key=lambda row: (_oid_sort_key(row.get("oid")), str(row.get("name") or "")))

    def get_object_translation(self, *, module_name: str, object_name: str, numeric_oid: str, source_text: str) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM mib_object_translations
                WHERE module_name = ? AND object_name = ? AND numeric_oid = ? AND source_text = ?
                LIMIT 1
                """,
                (module_name, object_name, numeric_oid, source_text),
            ).fetchone()
            return dict(row) if row is not None else None

    def upsert_object_translation(self, *, object_id: int | None, module_name: str, object_name: str, numeric_oid: str, source_text: str, translated_text: str, source: str = "local_terms") -> None:
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mib_object_translations
                (object_id, module_name, object_name, numeric_oid, source_text, translated_text, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(module_name, object_name, numeric_oid, source_text) DO UPDATE SET
                    translated_text = excluded.translated_text,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (object_id, module_name, object_name, numeric_oid, source_text, translated_text, source, now, now),
            )
            conn.commit()

    def list_templates(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM global_oid_templates ORDER BY template_name").fetchall()
            return [dict(row) for row in rows]

    def list_missing_dependency_summary(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.dependency_module,
                       COUNT(DISTINCT d.module_id) AS affected_count,
                       GROUP_CONCAT(DISTINCT m.module_name) AS affected_modules
                FROM mib_dependencies d
                JOIN mib_modules m ON m.id = d.module_id
                WHERE d.resolved = 0
                GROUP BY d.dependency_module
                ORDER BY affected_count DESC, d.dependency_module
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_missing_dependency_files(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT f.*
                FROM mib_files f
                WHERE f.compile_status = 'missing_dependencies'
                ORDER BY f.updated_at DESC, f.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_module_paths(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT module_name, raw_path, source_package_id FROM mib_files WHERE module_name <> ''").fetchall()
            return [dict(row) for row in rows]

    def create_template(self, *, name: str, oid: str, method: str, module_name: str = "", object_name: str = "", dictionary_set_id: int | None = None) -> int:
        now = _now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO global_oid_templates
                (template_name, scope, vendor, device_type, dictionary_set_id, module_name, object_name, numeric_oid, query_method, decoder, columns_json, created_from_mib_module, created_from_mib_file, created_at, updated_at)
                VALUES (?, 'global', '', '', ?, ?, ?, ?, ?, '', '[]', ?, '', ?, ?)
                """,
                (name, dictionary_set_id, module_name, object_name, oid, method, module_name, now, now),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def replace_file_compile_result(self, *, file_id: int, source_package_id: int | None, module_name: str, vendor: str, status: str, compiled_path: str, objects: Iterable[MibObjectRecord], dependencies: list[str], missing_dependencies: list[str], error_message: str) -> int:
        now = _now()
        with self.connect() as conn:
            module_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM mib_modules WHERE file_id = ?", (file_id,)).fetchall()]
            for module_id in module_ids:
                conn.execute("DELETE FROM mib_objects WHERE module_id = ?", (module_id,))
                conn.execute("DELETE FROM mib_dependencies WHERE module_id = ?", (module_id,))
            conn.execute("DELETE FROM mib_modules WHERE file_id = ?", (file_id,))
            conn.execute(
                """
                UPDATE mib_files
                SET source_package_id = ?, module_name = ?, compiled_path = ?, compile_status = ?, missing_dependencies_json = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (source_package_id, module_name, compiled_path, status, json.dumps(missing_dependencies, ensure_ascii=False), error_message, now, file_id),
            )
            conn.commit()
        return self.upsert_module_with_objects(
            file_id=file_id,
            source_package_id=source_package_id,
            module_name=module_name,
            vendor=vendor,
            status=status,
            compiled_path=compiled_path,
            objects=objects,
            dependencies=dependencies,
            missing_dependencies=missing_dependencies,
            error_message=error_message,
        )

    def ensure_h3c_comware_dictionaries(self, source_package_id: int, version_line: str) -> None:
        version_label = "V5" if version_line == "V5" else "V7/V9"
        prefix = f"H3C Comware {version_label}"
        definitions = (
            (f"{prefix} 通用字典", "通用", ("HH3C-OID-MIB", "HH3C-COMMON-MIB", "HH3C-TC-MIB", "SNMPv2-MIB", "IF-MIB", "ENTITY-MIB", "LLDP-MIB")),
            (f"H3C {version_label} 无线 AC 字典", "无线 AC", H3C_WIRELESS_MODULES),
            (f"H3C {version_label} Dot11 Mesh 字典", "无线 Mesh", H3C_WIRELESS_MODULES),
            (f"H3C {version_label} Trap 字典", "Trap", ("HH3C-OID-MIB", "HH3C-COMMON-MIB", "HH3C-TRAP-MIB", "HH3C-SNMP-EXT-MIB")),
            (f"H3C {version_label} 光模块 / 实体扩展字典", "光模块/实体", ("HH3C-ENTITY-EXT-MIB", "HH3C-TRANSCEIVER-MIB", "ENTITY-MIB")),
        )
        with self.connect() as conn:
            module_rows = conn.execute(
                "SELECT id, module_name FROM mib_modules WHERE source_package_id = ? AND status = 'compiled'",
                (source_package_id,),
            ).fetchall()
            module_ids: dict[str, int] = {str(row["module_name"]): int(row["id"]) for row in module_rows}
            for name, device_type, module_names in definitions:
                dictionary_id = self.ensure_dictionary_set(
                    DictionarySetRecord(
                        source_package_id=source_package_id,
                        name=name,
                        vendor="H3C",
                        device_type=device_type,
                        model_pattern="WX" if "无线 AC" in name else "",
                        os_pattern=version_label,
                        description=f"{name}，绑定 H3C 官方 Comware {version_label} MIB 基线包。",
                        is_builtin=0,
                        enabled_by_default=0,
                    ),
                    conn=conn,
                )
                for priority, module_name in enumerate(module_names, start=1):
                    module_id = module_ids.get(module_name)
                    if module_id is not None:
                        self.add_dictionary_module(dictionary_id, module_id, priority=priority, conn=conn)
            conn.commit()

    def get_product_reference_by_hash(self, file_hash: str) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM mib_product_references WHERE file_hash = ?", (file_hash,)).fetchone()
            return dict(row) if row is not None else None

    def insert_product_reference(
        self,
        *,
        vendor: str,
        product_line: str,
        product_name: str,
        device_type: str = "",
        os_family: str = "",
        os_major: str = "",
        release_series: str = "",
        doc_version: str = "",
        software_version: str = "",
        reference_name: str = "",
        source_file: str = "",
        file_hash: str = "",
        source_path: str = "",
        stored_path: str = "",
        sheet_names: list[str] | None = None,
        object_overrides: Iterable[dict[str, str]] = (),
        trap_overrides: Iterable[dict[str, str]] = (),
    ) -> int:
        now = _now()
        sheet_names = list(sheet_names or [])
        object_rows = list(object_overrides)
        trap_rows = list(trap_overrides)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO mib_product_references
                (vendor, product_line, product_name, device_type, os_family, os_major, release_series, doc_version, software_version, reference_name, source_file, file_hash, sheet_count, object_count, trap_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (vendor, product_line, product_name, device_type, os_family, os_major, release_series, doc_version, software_version, reference_name, source_file, file_hash, len(sheet_names), len(object_rows), len(trap_rows), now, now),
            )
            reference_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO mib_product_reference_files
                (reference_id, file_name, source_path, stored_path, file_hash, sheet_names_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (reference_id, Path(source_file).name, source_path, stored_path, file_hash, json.dumps(sheet_names, ensure_ascii=False), now, now),
            )
            self._insert_product_object_overrides(conn, reference_id, object_rows, now)
            self._insert_product_trap_overrides(conn, reference_id, trap_rows, now)
            self._insert_product_reference_tree_nodes(conn, reference_id, reference_name, object_rows, trap_rows, now)
            conn.commit()
            return reference_id

    def replace_product_reference_content(self, reference_id: int, *, sheet_names: list[str] | None = None, object_overrides: Iterable[dict[str, str]] = (), trap_overrides: Iterable[dict[str, str]] = ()) -> None:
        now = _now()
        sheet_names = list(sheet_names or [])
        object_rows = list(object_overrides)
        trap_rows = list(trap_overrides)
        with self.connect() as conn:
            reference = conn.execute("SELECT reference_name FROM mib_product_references WHERE id = ?", (int(reference_id),)).fetchone()
            if reference is None:
                return
            conn.execute("DELETE FROM mib_product_object_overrides WHERE reference_id = ?", (int(reference_id),))
            conn.execute("DELETE FROM mib_product_trap_overrides WHERE reference_id = ?", (int(reference_id),))
            conn.execute("DELETE FROM mib_product_reference_tree_nodes WHERE reference_id = ?", (int(reference_id),))
            conn.execute("DELETE FROM mib_product_reference_objects WHERE reference_id = ?", (int(reference_id),))
            conn.execute(
                """
                UPDATE mib_product_references
                SET sheet_count = ?, object_count = ?, trap_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (len(sheet_names), len(object_rows), len(trap_rows), now, int(reference_id)),
            )
            conn.execute(
                """
                UPDATE mib_product_reference_files
                SET sheet_names_json = ?, updated_at = ?
                WHERE reference_id = ?
                """,
                (json.dumps(sheet_names, ensure_ascii=False), now, int(reference_id)),
            )
            self._insert_product_object_overrides(conn, int(reference_id), object_rows, now)
            self._insert_product_trap_overrides(conn, int(reference_id), trap_rows, now)
            self._insert_product_reference_tree_nodes(conn, int(reference_id), str(reference["reference_name"] or ""), object_rows, trap_rows, now)
            conn.commit()

    def list_product_references(self) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*,
                       (SELECT COUNT(*) FROM mib_product_object_overrides o WHERE o.reference_id = r.id) AS object_override_count,
                       (SELECT COUNT(*) FROM mib_product_trap_overrides t WHERE t.reference_id = r.id) AS trap_override_count
                FROM mib_product_references r
                ORDER BY r.created_at DESC, r.id DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_product_reference(self, reference_id: int) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM mib_product_references WHERE id = ?", (int(reference_id),)).fetchone()
            return dict(row) if row is not None else None

    def list_product_object_overrides(self, reference_id: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mib_product_object_overrides
                WHERE reference_id = ?
                ORDER BY module_name, numeric_oid, object_name, id
                """,
                (int(reference_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_product_reference_objects(self, reference_id: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mib_product_reference_objects
                WHERE reference_id = ?
                ORDER BY category_name, module_name, mib_file_name, root_node_name, parent_node_name, numeric_oid, object_name, id
                """,
                (int(reference_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_product_trap_overrides(self, reference_id: int) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mib_product_trap_overrides
                WHERE reference_id = ?
                ORDER BY module_name, trap_oid, trap_name, id
                """,
                (int(reference_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def replace_product_reference_overlays(self, reference_id: int, rows: Iterable[dict[str, object]]) -> int:
        now = _now()
        overlay_rows = list(rows)
        with self.connect() as conn:
            conn.execute("DELETE FROM h3c_product_reference_overlays WHERE reference_id = ?", (int(reference_id),))
            count = 0
            for row in overlay_rows:
                stable_key = str(row.get("stable_key") or "").strip()
                if not stable_key:
                    continue
                cursor = conn.execute(
                    """
                    INSERT INTO h3c_mib_canonical_objects
                    (stable_key, key_type, module_name, mib_file_name, object_name, numeric_oid, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(stable_key) DO UPDATE SET
                        module_name = COALESCE(NULLIF(excluded.module_name, ''), module_name),
                        mib_file_name = COALESCE(NULLIF(excluded.mib_file_name, ''), mib_file_name),
                        object_name = COALESCE(NULLIF(excluded.object_name, ''), object_name),
                        numeric_oid = COALESCE(NULLIF(excluded.numeric_oid, ''), numeric_oid),
                        updated_at = excluded.updated_at
                    """,
                    (
                        stable_key,
                        str(row.get("key_type") or "object"),
                        str(row.get("module_name") or ""),
                        str(row.get("mib_file_name") or ""),
                        str(row.get("object_name") or ""),
                        str(row.get("numeric_oid") or ""),
                        now,
                        now,
                    ),
                )
                canonical = conn.execute("SELECT id FROM h3c_mib_canonical_objects WHERE stable_key = ?", (stable_key,)).fetchone()
                canonical_id = int(canonical["id"]) if canonical is not None else int(cursor.lastrowid)
                conn.execute(
                    """
                    INSERT INTO h3c_product_reference_overlays
                    (reference_id, canonical_object_id, stable_key, category_name, category_number, category_title, module_name, mib_file_name, object_name, numeric_oid, access_from_reference, data_type_from_reference, value_range, chinese_description, function_description, implementation_spec, operation_support, match_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(reference_id),
                        canonical_id,
                        stable_key,
                        str(row.get("category_name") or ""),
                        str(row.get("category_number") or ""),
                        str(row.get("category_title") or ""),
                        str(row.get("module_name") or ""),
                        str(row.get("mib_file_name") or ""),
                        str(row.get("object_name") or ""),
                        str(row.get("numeric_oid") or ""),
                        str(row.get("access_from_reference") or ""),
                        str(row.get("data_type_from_reference") or ""),
                        str(row.get("value_range") or ""),
                        str(row.get("chinese_description") or ""),
                        str(row.get("function_description") or ""),
                        str(row.get("implementation_spec") or ""),
                        str(row.get("operation_support") or ""),
                        str(row.get("match_status") or ""),
                        now,
                        now,
                    ),
                )
                count += 1
            conn.commit()
            return count

    def replace_product_reference_compare_results(self, left_reference_id: int, right_reference_id: int, rows: Iterable[dict[str, object]]) -> int:
        now = _now()
        compare_rows = list(rows)
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM h3c_product_reference_compare_results WHERE left_reference_id = ? AND right_reference_id = ?",
                (int(left_reference_id), int(right_reference_id)),
            )
            count = 0
            for row in compare_rows:
                conn.execute(
                    """
                    INSERT INTO h3c_product_reference_compare_results
                    (left_reference_id, right_reference_id, item_type, diff_type, stable_key, module_name, mib_file_name, object_name, numeric_oid, field_name, left_value, right_value, summary, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(left_reference_id),
                        int(right_reference_id),
                        str(row.get("item_type") or ""),
                        str(row.get("diff_type") or ""),
                        str(row.get("stable_key") or ""),
                        str(row.get("module_name") or ""),
                        str(row.get("mib_file_name") or ""),
                        str(row.get("object_name") or ""),
                        str(row.get("numeric_oid") or ""),
                        str(row.get("field_name") or ""),
                        str(row.get("left_value") or ""),
                        str(row.get("right_value") or ""),
                        str(row.get("summary") or ""),
                        now,
                    ),
                )
                count += 1
            conn.commit()
            return count

    def list_product_reference_compare_results(
        self,
        left_reference_id: int,
        right_reference_id: int,
        *,
        diff_type: str = "",
        keyword: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        clauses = ["left_reference_id = ?", "right_reference_id = ?"]
        params: list[object] = [int(left_reference_id), int(right_reference_id)]
        if diff_type:
            clauses.append("diff_type = ?")
            params.append(diff_type)
        if keyword:
            like = f"%{keyword}%"
            clauses.append("(stable_key LIKE ? OR module_name LIKE ? OR object_name LIKE ? OR numeric_oid LIKE ? OR summary LIKE ?)")
            params.extend([like, like, like, like, like])
        params.extend([int(limit), int(offset)])
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM h3c_product_reference_compare_results
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    CASE diff_type
                        WHEN 'removed' THEN 1
                        WHEN 'added' THEN 2
                        WHEN 'changed' THEN 3
                        WHEN 'category_changed' THEN 4
                        ELSE 9
                    END,
                    item_type,
                    module_name,
                    numeric_oid,
                    object_name,
                    id
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def find_product_object_override(self, *, module_name: str = "", object_name: str = "", numeric_oid: str = "") -> dict[str, object] | None:
        clauses: list[str] = []
        params: list[object] = []
        if numeric_oid:
            clauses.append("o.numeric_oid = ?")
            params.append(numeric_oid)
        if object_name:
            clauses.append("o.object_name = ?")
            params.append(object_name)
        if not clauses:
            return None
        module_clause = ""
        if module_name:
            module_clause = "AND (o.module_name = ? OR o.module_name = '')"
            params.append(module_name)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT o.*, r.reference_name, r.vendor, r.product_line, r.product_name, r.software_version
                FROM mib_product_object_overrides o
                JOIN mib_product_references r ON r.id = o.reference_id
                WHERE ({' OR '.join(clauses)}) {module_clause}
                ORDER BY CASE WHEN o.numeric_oid = ? THEN 0 ELSE 1 END, r.updated_at DESC, o.id DESC
                LIMIT 1
                """,
                [*params, numeric_oid],
            ).fetchone()
            return dict(row) if row is not None else None

    def find_product_trap_override(self, *, module_name: str = "", trap_name: str = "", trap_oid: str = "") -> dict[str, object] | None:
        clauses: list[str] = []
        params: list[object] = []
        if trap_oid:
            clauses.append("t.trap_oid = ?")
            params.append(trap_oid)
        if trap_name:
            clauses.append("t.trap_name = ?")
            params.append(trap_name)
        if not clauses:
            return None
        module_clause = ""
        if module_name:
            module_clause = "AND (t.module_name = ? OR t.module_name = '')"
            params.append(module_name)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT t.*, r.reference_name, r.vendor, r.product_line, r.product_name, r.software_version
                FROM mib_product_trap_overrides t
                JOIN mib_product_references r ON r.id = t.reference_id
                WHERE ({' OR '.join(clauses)}) {module_clause}
                ORDER BY CASE WHEN t.trap_oid = ? THEN 0 ELSE 1 END, r.updated_at DESC, t.id DESC
                LIMIT 1
                """,
                [*params, trap_oid],
            ).fetchone()
            return dict(row) if row is not None else None

    def list_product_reference_tree_nodes(self, reference_id: int, parent_id: int | None = None) -> list[dict[str, object]]:
        clause = "parent_id IS NULL" if parent_id is None else "parent_id = ?"
        params: list[object] = [int(reference_id)] if parent_id is None else [int(reference_id), int(parent_id)]
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM mib_product_reference_tree_nodes
                WHERE reference_id = ? AND {clause}
                ORDER BY sort_order, display_name, node_name, id
                """,
                params,
            ).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                item["sort_oid"] = self._product_tree_node_sort_oid(conn, int(item.get("id") or 0), str(item.get("numeric_oid") or ""))
            return sorted(items, key=_product_tree_sort_key)

    def _product_tree_node_sort_oid(self, conn: sqlite3.Connection, node_id: int, numeric_oid: str = "") -> str:
        if _is_numeric_oid(numeric_oid):
            return numeric_oid.strip().strip(".")
        rows = conn.execute(
            """
            WITH RECURSIVE descendants(id, numeric_oid) AS (
                SELECT id, numeric_oid
                FROM mib_product_reference_tree_nodes
                WHERE parent_id = ?
                UNION ALL
                SELECT child.id, child.numeric_oid
                FROM mib_product_reference_tree_nodes child
                JOIN descendants parent ON child.parent_id = parent.id
            )
            SELECT numeric_oid
            FROM descendants
            WHERE numeric_oid IS NOT NULL AND numeric_oid <> ''
            """,
            (int(node_id),),
        ).fetchall()
        oids = [str(row["numeric_oid"]).strip().strip(".") for row in rows if _is_numeric_oid(row["numeric_oid"])]
        return min(oids, key=_oid_sort_key) if oids else ""

    def rebuild_product_reference_tree(self, reference_id: int) -> dict[str, int]:
        now = _now()
        reference_id = int(reference_id)
        with self.connect() as conn:
            reference = conn.execute("SELECT reference_name FROM mib_product_references WHERE id = ?", (reference_id,)).fetchone()
            if reference is None:
                raise ValueError(f"Product reference not found: {reference_id}")
            object_rows = [dict(row) for row in conn.execute("SELECT * FROM mib_product_reference_objects WHERE reference_id = ? ORDER BY id", (reference_id,)).fetchall()]
            if not object_rows:
                override_rows = conn.execute(
                    """
                    SELECT category_name, module_name, mib_file_name, root_node_name, parent_node_name,
                           object_name, numeric_oid, access_from_reference, data_type_from_reference,
                           value_range, chinese_description, function_description, implementation_spec,
                           operation_support
                    FROM mib_product_object_overrides
                    WHERE reference_id = ?
                    ORDER BY category_name, module_name, mib_file_name, root_node_name, parent_node_name, numeric_oid, object_name, id
                    """,
                    (reference_id,),
                ).fetchall()
                object_rows = [dict(row) for row in override_rows]
            trap_rows = [dict(row) for row in conn.execute("SELECT * FROM mib_product_trap_overrides WHERE reference_id = ? ORDER BY category_name, module_name, mib_file_name, trap_oid, trap_name, id", (reference_id,)).fetchall()]
            if not object_rows and not trap_rows:
                raise ValueError("该产品参考表没有解析对象，请重新导入 Excel")

            self._insert_product_reference_tree_nodes(conn, reference_id, str(reference["reference_name"] or f"reference:{reference_id}"), object_rows, trap_rows, now)
            node_count = int(conn.execute("SELECT COUNT(*) FROM mib_product_reference_tree_nodes WHERE reference_id = ?", (reference_id,)).fetchone()[0] or 0)
            category_count = int(conn.execute("SELECT COUNT(*) FROM mib_product_reference_tree_nodes WHERE reference_id = ? AND node_type = 'category'", (reference_id,)).fetchone()[0] or 0)
            module_count = int(conn.execute("SELECT COUNT(*) FROM mib_product_reference_tree_nodes WHERE reference_id = ? AND node_type = 'module'", (reference_id,)).fetchone()[0] or 0)
            object_count = int(conn.execute("SELECT COUNT(*) FROM mib_product_reference_objects WHERE reference_id = ?", (reference_id,)).fetchone()[0] or 0)
            conn.execute(
                "UPDATE mib_product_references SET object_count = ?, trap_count = ?, updated_at = ? WHERE id = ?",
                (object_count, len(trap_rows), now, reference_id),
            )
            conn.commit()
            return {
                "reference_id": reference_id,
                "node_count": node_count,
                "category_count": category_count,
                "module_count": module_count,
                "object_count": object_count,
                "trap_count": len(trap_rows),
            }

    def list_product_reference_module_names(self, reference_id: int, *, category_name: str = "") -> list[str]:
        params: list[object] = [int(reference_id)]
        category_join = ""
        category_where = ""
        if category_name:
            category_join = "JOIN mib_product_reference_tree_nodes c ON c.id = n.parent_id"
            category_where = "AND c.node_name = ?"
            params.append(category_name)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT n.module_name
                FROM mib_product_reference_tree_nodes n
                {category_join}
                WHERE n.reference_id = ? AND n.node_type IN ('module', 'mib_module') AND n.module_name <> '' {category_where}
                ORDER BY n.module_name
                """,
                params,
            ).fetchall()
            return [str(row["module_name"]) for row in rows]

    def product_reference_node_children_modules(self, node_id: int) -> list[str]:
        with self.connect() as conn:
            node = conn.execute("SELECT * FROM mib_product_reference_tree_nodes WHERE id = ?", (int(node_id),)).fetchone()
            if node is None:
                return []
            if str(node["node_type"]) in {"module", "mib_module"}:
                return [str(node["module_name"])]
            rows = conn.execute(
                """
                SELECT DISTINCT module_name FROM mib_product_reference_tree_nodes
                WHERE reference_id = ? AND parent_id = ? AND node_type IN ('module', 'mib_module') AND module_name <> ''
                ORDER BY module_name
                """,
                (int(node["reference_id"]), int(node_id)),
            ).fetchall()
            return [str(row["module_name"]) for row in rows]

    def module_exists(self, module_name: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM mib_modules WHERE module_name = ? LIMIT 1", (module_name,)).fetchone() is not None

    def _insert_product_object_overrides(self, conn: sqlite3.Connection, reference_id: int, rows: Iterable[dict[str, str]], now: str) -> None:
        for row in rows:
            mib_object_id, match_status = self._match_mib_object(conn, module_name=row.get("module_name", ""), object_name=row.get("object_name", ""), numeric_oid=row.get("numeric_oid", ""))
            conn.execute(
                """
                INSERT INTO mib_product_object_overrides
                (reference_id, category_name, module_name, mib_file_name, root_node_name, parent_node_name, object_name, numeric_oid, object_scope, access_from_reference, data_type_from_reference, value_range, chinese_description, function_description, implementation_spec, operation_support, table_parent_name, table_index_info, mib_object_id, match_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_id,
                    row.get("category_name", ""),
                    row.get("module_name", ""),
                    row.get("mib_file_name", ""),
                    row.get("root_node_name", ""),
                    row.get("parent_node_name", ""),
                    row.get("object_name", ""),
                    row.get("numeric_oid", ""),
                    row.get("object_scope", ""),
                    row.get("access_from_reference", ""),
                    row.get("data_type_from_reference", ""),
                    row.get("value_range", ""),
                    row.get("chinese_description", ""),
                    row.get("function_description", ""),
                    row.get("implementation_spec", ""),
                    row.get("operation_support", ""),
                    row.get("table_parent_name", ""),
                    row.get("table_index_info", ""),
                    mib_object_id,
                    match_status,
                    now,
                    now,
                ),
            )

    def _insert_product_trap_overrides(self, conn: sqlite3.Connection, reference_id: int, rows: Iterable[dict[str, str]], now: str) -> None:
        for row in rows:
            conn.execute(
                """
                INSERT INTO mib_product_trap_overrides
                (reference_id, category_name, module_name, mib_file_name, trap_name, trap_oid, trap_title, trap_type, trap_level, clear_trap_oid, clear_trap_name, default_status, trigger_reason, system_impact, status_control, varbind_oids, varbind_names, varbind_descriptions, varbind_index_nodes, varbind_types, varbind_value_ranges, suggestion, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_id,
                    row.get("category_name", ""),
                    row.get("module_name", ""),
                    row.get("mib_file_name", ""),
                    row.get("trap_name", ""),
                    row.get("trap_oid", ""),
                    row.get("trap_title", ""),
                    row.get("trap_type", ""),
                    row.get("trap_level", ""),
                    row.get("clear_trap_oid", ""),
                    row.get("clear_trap_name", ""),
                    row.get("default_status", ""),
                    row.get("trigger_reason", ""),
                    row.get("system_impact", ""),
                    row.get("status_control", ""),
                    row.get("varbind_oids", ""),
                    row.get("varbind_names", ""),
                    row.get("varbind_descriptions", ""),
                    row.get("varbind_index_nodes", ""),
                    row.get("varbind_types", ""),
                    row.get("varbind_value_ranges", ""),
                    row.get("suggestion", ""),
                    now,
                    now,
                ),
            )

    def _insert_product_reference_tree_nodes(self, conn: sqlite3.Connection, reference_id: int, reference_name: str, object_rows: Iterable[dict[str, str]], trap_rows: Iterable[dict[str, str]], now: str) -> None:
        conn.execute("DELETE FROM mib_product_reference_tree_nodes WHERE reference_id = ?", (reference_id,))
        conn.execute("DELETE FROM mib_product_reference_objects WHERE reference_id = ?", (reference_id,))
        node_cache: dict[tuple[int | None, str, str], int] = {}

        def ensure_node(parent_id: int | None, node_type: str, display_name: str, row: dict[str, str], sort_order: int = 100, enabled_default: int = 0) -> int:
            display = display_name.strip()
            if not display:
                return int(parent_id or 0)
            key = (parent_id, node_type, display)
            if key in node_cache:
                return node_cache[key]
            is_leaf = node_type in {"object", "trap"}
            cursor = conn.execute(
                """
                INSERT INTO mib_product_reference_tree_nodes
                (reference_id, parent_id, node_type, node_key, node_name, display_name, category_name, module_name, mib_file_name, root_node_name, parent_node_name, object_name, numeric_oid, meaning, sort_order, object_count, enabled_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    reference_id,
                    parent_id,
                    node_type,
                    display,
                    display,
                    display,
                    row.get("category_name", ""),
                    row.get("module_name", ""),
                    row.get("mib_file_name", ""),
                    row.get("root_node_name", ""),
                    row.get("parent_node_name", ""),
                    (row.get("object_name", "") or row.get("trap_name", "")) if is_leaf else "",
                    (row.get("numeric_oid", "") or row.get("trap_oid", "")) if is_leaf else "",
                    row.get("chinese_description", "") or row.get("function_description", "") or row.get("implementation_spec", ""),
                    sort_order,
                    enabled_default,
                    now,
                    now,
                ),
            )
            node_id = int(cursor.lastrowid)
            node_cache[key] = node_id
            return node_id

        root_id = ensure_node(None, "reference_root", reference_name or f"reference:{reference_id}", {}, sort_order=0, enabled_default=1)
        for row in object_rows:
            object_name = str(row.get("object_name") or row.get("numeric_oid") or "").strip()
            if not object_name:
                continue
            parent_id = root_id
            for node_type, field in (("category", "category_name"), ("module", "module_name"), ("mib_file", "mib_file_name"), ("root_node", "root_node_name"), ("parent_node", "parent_node_name")):
                value = str(row.get(field) or "").strip()
                if value:
                    parent_id = ensure_node(parent_id, node_type, value, row, enabled_default=1 if node_type == "category" and _category_default_enabled(value) else 0)
            leaf_label = f"{object_name} ({row.get('numeric_oid')})" if row.get("numeric_oid") else object_name
            leaf_id = ensure_node(parent_id, "object", leaf_label, row, sort_order=200)
            mib_object_id, match_status = self._match_mib_object(conn, module_name=row.get("module_name", ""), object_name=row.get("object_name", ""), numeric_oid=row.get("numeric_oid", ""))
            self._insert_product_reference_object(conn, reference_id, leaf_id, row, mib_object_id, match_status, now)
            self._increment_tree_counts(conn, leaf_id)
        for row in trap_rows:
            module_name = str(row.get("module_name") or row.get("mib_file_name") or "").strip()
            if not module_name:
                continue
            trap_name = str(row.get("trap_name") or row.get("trap_oid") or "").strip()
            if not trap_name:
                continue
            parent_id = root_id
            for node_type, field in (("category", "category_name"), ("module", "module_name"), ("mib_file", "mib_file_name")):
                value = str(row.get(field) or "").strip()
                if value:
                    parent_id = ensure_node(parent_id, node_type, value, row, enabled_default=1 if node_type == "category" and _category_default_enabled(value) else 0)
            leaf_label = f"{trap_name} ({row.get('trap_oid')})" if row.get("trap_oid") else trap_name
            leaf_id = ensure_node(parent_id, "trap", leaf_label, row, sort_order=300)
            self._increment_tree_counts(conn, leaf_id)

    def _match_mib_object(self, conn: sqlite3.Connection, *, module_name: str = "", object_name: str = "", numeric_oid: str = "") -> tuple[int | None, str]:
        if numeric_oid:
            row = conn.execute("SELECT id FROM mib_objects WHERE oid = ? ORDER BY id LIMIT 1", (numeric_oid,)).fetchone()
            if row is not None:
                return int(row["id"]), "matched_by_oid"
        if module_name and object_name:
            row = conn.execute(
                """
                SELECT o.id
                FROM mib_objects o
                JOIN mib_modules m ON m.id = o.module_id
                WHERE m.module_name = ? AND o.name = ?
                ORDER BY o.id LIMIT 1
                """,
                (module_name, object_name),
            ).fetchone()
            if row is not None:
                return int(row["id"]), "matched_by_name"
        return None, "product_reference_only" if (object_name or numeric_oid) else "mib_not_found"

    def _insert_product_reference_object(self, conn: sqlite3.Connection, reference_id: int, tree_node_id: int, row: dict[str, str], mib_object_id: int | None, match_status: str, now: str) -> None:
        conn.execute(
            """
            INSERT INTO mib_product_reference_objects
            (reference_id, tree_node_id, sheet_name, category_name, module_name, mib_file_name, root_node_name, parent_node_name, object_name, numeric_oid, access_from_reference, data_type_from_reference, value_range, meaning, function_description, implementation_spec, operation_support, mib_object_id, match_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_id,
                tree_node_id,
                row.get("sheet_name", ""),
                row.get("category_name", ""),
                row.get("module_name", ""),
                row.get("mib_file_name", ""),
                row.get("root_node_name", ""),
                row.get("parent_node_name", ""),
                row.get("object_name", ""),
                row.get("numeric_oid", ""),
                row.get("access_from_reference", ""),
                row.get("data_type_from_reference", ""),
                row.get("value_range", ""),
                row.get("chinese_description", ""),
                row.get("function_description", ""),
                row.get("implementation_spec", ""),
                row.get("operation_support", ""),
                mib_object_id,
                match_status,
                now,
                now,
            ),
        )

    def _increment_tree_counts(self, conn: sqlite3.Connection, node_id: int) -> None:
        current: int | None = node_id
        while current:
            row = conn.execute("SELECT parent_id FROM mib_product_reference_tree_nodes WHERE id = ?", (current,)).fetchone()
            conn.execute("UPDATE mib_product_reference_tree_nodes SET object_count = object_count + 1 WHERE id = ?", (current,))
            current = int(row["parent_id"]) if row is not None and row["parent_id"] is not None else None

    def _ensure_h3c_mesh_dictionary_and_templates(self, conn: sqlite3.Connection, module_id: int, source_package_id: int | None = None) -> None:
        dictionary_id = self.ensure_dictionary_set(
            DictionarySetRecord(
                source_package_id=source_package_id,
                name="H3C Mesh 字典",
                vendor="H3C",
                device_type="无线 Mesh",
                sysobjectid_prefix=H3C_MESH_ROOT_OID,
                description="HH3C-DOT11S-MESH-MIB 自动识别字典。SNMP Mesh 用于状态快照、低频统计、Trap、拓扑补充和实机验证，不替换现有 CLI 秒级采集。",
                is_builtin=0,
                enabled_by_default=0,
            ),
            conn=conn,
        )
        self.add_dictionary_module(dictionary_id, module_id, priority=10, conn=conn)
        now = _now()
        for template_name, object_name, oid, method, columns in H3C_MESH_TEMPLATES:
            exists = conn.execute(
                "SELECT 1 FROM global_oid_templates WHERE template_name = ? AND numeric_oid = ? LIMIT 1",
                (template_name, oid),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO global_oid_templates
                (template_name, scope, vendor, device_type, dictionary_set_id, module_name, object_name, numeric_oid, query_method, decoder, columns_json, created_from_mib_module, created_from_mib_file, created_at, updated_at)
                VALUES (?, 'dictionary', 'H3C', '无线 Mesh', ?, ?, ?, ?, ?, '', ?, ?, '', ?, ?)
                """,
                (template_name, dictionary_id, H3C_MESH_MODULE, object_name, oid, method, json.dumps(columns, ensure_ascii=False), H3C_MESH_MODULE, now, now),
            )

    def _refresh_module_counts(self, conn: sqlite3.Connection) -> None:
        for row in conn.execute("SELECT id FROM mib_modules").fetchall():
            module_id = int(row["id"])
            counts = conn.execute(
                """
                SELECT COUNT(*) AS object_count,
                       SUM(CASE WHEN is_table = 1 THEN 1 ELSE 0 END) AS table_count,
                       SUM(CASE WHEN is_trap = 1 THEN 1 ELSE 0 END) AS trap_count,
                       SUM(CASE WHEN is_notification = 1 THEN 1 ELSE 0 END) AS notification_count
                FROM mib_objects WHERE module_id = ?
                """,
                (module_id,),
            ).fetchone()
            conn.execute(
                "UPDATE mib_modules SET object_count = ?, table_count = ?, trap_count = ?, notification_count = ? WHERE id = ?",
                (int(counts["object_count"] or 0), int(counts["table_count"] or 0), int(counts["trap_count"] or 0), int(counts["notification_count"] or 0), module_id),
            )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _enum_map_for(name: str) -> str:
    if name in {"ifAdminStatus", "ifOperStatus"}:
        return json.dumps({"1": "up", "2": "down", "3": "testing"}, ensure_ascii=False)
    return "{}"


def _category_default_enabled(category_name: str) -> bool:
    text = category_name.upper()
    return any(keyword in text for keyword in ("WLAN", "接口", "设备", "网络管理", "监控"))
