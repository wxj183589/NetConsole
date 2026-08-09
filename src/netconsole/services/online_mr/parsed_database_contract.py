from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from netconsole.repositories.online_mr_parsed_database_metadata import (
    CURRENT_PARSED_TABLES,
    ONLINE_MR_REQUIRED_CAPABILITIES,
    PARSER_CAPABILITIES,
    PARSER_CAPABILITY_TABLES,
    PARSER_SCHEMA_VERSION,
    PARSER_VERSION,
)

__all__ = [
    "CURRENT_PARSED_TABLES",
    "ONLINE_MR_REQUIRED_CAPABILITIES",
    "PARSER_CAPABILITIES",
    "PARSER_CAPABILITY_TABLES",
    "PARSER_SCHEMA_VERSION",
    "PARSER_VERSION",
    "ParsedDatabaseContractInspection",
    "capabilities_for_tables",
    "inspect_parsed_database",
    "parse_schema_version",
]

@dataclass(frozen=True)
class ParsedDatabaseContractInspection:
    exists: bool
    readable: bool
    schema_version: int | None
    parser_version: str
    tables: frozenset[str]
    compatible_capabilities: frozenset[str]
    declared_capabilities: frozenset[str]
    effective_capabilities: frozenset[str]
    missing_capabilities: frozenset[str]
    current: bool
    error: str = ""


def capabilities_for_tables(tables: set[str] | frozenset[str]) -> frozenset[str]:
    return frozenset(
        name
        for name, required_tables in PARSER_CAPABILITY_TABLES.items()
        if required_tables.issubset(tables)
    )


def parse_schema_version(value: object) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def inspect_parsed_database(path: str | Path) -> ParsedDatabaseContractInspection:
    database_path = Path(path)
    if not database_path.is_file():
        return ParsedDatabaseContractInspection(
            exists=False,
            readable=False,
            schema_version=None,
            parser_version="",
            tables=frozenset(),
            compatible_capabilities=frozenset(),
            declared_capabilities=frozenset(),
            effective_capabilities=frozenset(),
            missing_capabilities=ONLINE_MR_REQUIRED_CAPABILITIES,
            current=False,
        )
    try:
        with closing(sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as connection:
            tables = frozenset(
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            )
            metadata: dict[str, str] = {}
            if "online_schema_meta" in tables:
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(online_schema_meta)").fetchall()
                }
                if {"key", "value"}.issubset(columns):
                    metadata = {
                        str(row[0]): str(row[1])
                        for row in connection.execute("SELECT key, value FROM online_schema_meta").fetchall()
                    }
            schema_version = parse_schema_version(metadata.get("schema_version"))
            if schema_version is None:
                schema_version = parse_schema_version(connection.execute("PRAGMA user_version").fetchone()[0])
            declared: frozenset[str] = frozenset()
            try:
                raw_capabilities = json.loads(metadata.get("capabilities", "[]"))
                if isinstance(raw_capabilities, list):
                    declared = frozenset(
                        str(value)
                        for value in raw_capabilities
                        if str(value) in ONLINE_MR_REQUIRED_CAPABILITIES
                    )
            except (TypeError, ValueError, json.JSONDecodeError):
                declared = frozenset()
            compatible = capabilities_for_tables(tables)
            effective = compatible.intersection(declared)
            missing = ONLINE_MR_REQUIRED_CAPABILITIES.difference(effective)
            parser_version = metadata.get("parser_version", "")
            current = (
                schema_version is not None
                and schema_version >= PARSER_SCHEMA_VERSION
                and not missing
                and CURRENT_PARSED_TABLES.issubset(tables)
            )
            return ParsedDatabaseContractInspection(
                exists=True,
                readable=True,
                schema_version=schema_version,
                parser_version=parser_version,
                tables=tables,
                compatible_capabilities=compatible,
                declared_capabilities=declared,
                effective_capabilities=effective,
                missing_capabilities=missing,
                current=current,
            )
    except sqlite3.Error as exc:
        return ParsedDatabaseContractInspection(
            exists=True,
            readable=False,
            schema_version=None,
            parser_version="",
            tables=frozenset(),
            compatible_capabilities=frozenset(),
            declared_capabilities=frozenset(),
            effective_capabilities=frozenset(),
            missing_capabilities=ONLINE_MR_REQUIRED_CAPABILITIES,
            current=False,
            error=str(exc),
        )
