"""Audit and explicitly repair legacy History Store provenance on development copies."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from netconsole.services.history_store import HistoryStore


DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
_PROVENANCE_TABLE = "history_event_provenance_v2"
_UNIQUE_SOURCE_INDEX = "ux_history_event_provenance_v2_source"
_REDUNDANT_SOURCE_INDEX = "idx_history_event_provenance_v2_source"


class HistoryProvenanceValidationError(ValueError):
    """Raised when provenance maintenance cannot stay inside its safe boundary."""


def validate_history_provenance(
    *,
    devices_database: Path,
    history_root: Path,
    output_path: Path,
    apply_backfill: bool = False,
    allow_development_root_only: bool = False,
    batch_size: int = 1000,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
) -> dict[str, Any]:
    """Audit devices, catalog and every registered shard, optionally backfilling first."""

    development = development_root.resolve(strict=True)
    if os.name == "nt":
        fixed_development = DEFAULT_DEVELOPMENT_ROOT.resolve(strict=True)
        if not development.is_relative_to(fixed_development):
            raise HistoryProvenanceValidationError(
                "development root must remain below D:/study"
            )
    devices = _input_file(devices_database, development, label="devices database")
    history = _input_directory(history_root, development, label="history root")
    output = _output_file(output_path, development)
    if output.exists():
        raise HistoryProvenanceValidationError(
            f"refusing to overwrite history provenance evidence: {output}"
        )
    if apply_backfill and not allow_development_root_only:
        raise HistoryProvenanceValidationError(
            "--apply-backfill requires --allow-development-root-only"
        )
    if int(batch_size) <= 0:
        raise HistoryProvenanceValidationError("batch_size must be positive")

    backfill: dict[str, Any] | None = None
    if apply_backfill:
        backfill = HistoryStore(
            devices,
            history_root=history,
        ).backfill_legacy_provenance(batch_size=int(batch_size))

    report = _audit(devices=devices, history_root=history)
    report.update(
        {
            "format": "netconsole-history-provenance-audit-v1",
            "schema_version": 1,
            "mode": "APPLY_BACKFILL_THEN_AUDIT" if apply_backfill else "READ_ONLY_AUDIT",
            "development_root": str(development),
            "backfill": backfill,
        }
    )
    _atomic_json(output, report)
    return report


def _audit(*, devices: Path, history_root: Path) -> dict[str, Any]:
    catalog_path = history_root / "catalog.db"
    databases: list[dict[str, Any]] = [
        _audit_database(devices, role="devices", shard_id=None)
    ]
    findings: list[str] = []
    catalog_rows: list[dict[str, Any]] = []
    if not catalog_path.is_file():
        findings.append(f"history catalog is missing: {catalog_path}")
    else:
        catalog_audit = _audit_database(catalog_path, role="catalog", shard_id=None)
        databases.append(catalog_audit)
        try:
            with closing(_connect_readonly(catalog_path)) as catalog:
                if not _table_exists(catalog, "history_catalog"):
                    findings.append("history catalog table is missing")
                else:
                    catalog_rows = [
                        dict(row)
                        for row in catalog.execute(
                            "SELECT shard_id, relative_path, status "
                            "FROM history_catalog ORDER BY shard_id"
                        ).fetchall()
                    ]
        except sqlite3.Error as exc:
            findings.append(f"history catalog cannot be enumerated: {exc}")

    seen_paths: set[Path] = set()
    for row in catalog_rows:
        relative_path = str(row.get("relative_path") or "")
        shard_path = _safe_catalog_shard_path(history_root, relative_path)
        shard_id = str(row.get("shard_id") or "")
        if shard_path is None:
            findings.append(f"catalog shard path is invalid: {shard_id}: {relative_path}")
            continue
        if shard_path in seen_paths:
            findings.append(f"catalog shard path is duplicated: {shard_path}")
            continue
        seen_paths.add(shard_path)
        if not shard_path.is_file():
            findings.append(f"catalog shard is missing: {shard_id}: {shard_path}")
            continue
        databases.append(_audit_database(shard_path, role="shard", shard_id=shard_id))

    for database in databases:
        findings.extend(str(item) for item in database["findings"])
    return {
        "status": "PASS" if not findings else "FAIL",
        "devices_database": str(devices),
        "history_root": str(history_root),
        "catalog_registered_shards": len(catalog_rows),
        "audited_shards": sum(1 for item in databases if item["role"] == "shard"),
        "databases": databases,
        "findings": findings,
    }


def _audit_database(path: Path, *, role: str, shard_id: str | None) -> dict[str, Any]:
    findings: list[str] = []
    result: dict[str, Any] = {
        "role": role,
        "shard_id": shard_id,
        "path": str(path),
        "quick_check": [],
        "integrity_check": [],
        "foreign_key_check": [],
        "event_counts": {
            "history_outbox": 0,
            "history_events": 0,
            "history_events_v2": 0,
            "legacy_events_v2": 0,
        },
        "provenance_count": 0,
        "missing_provenance": 0,
        "duplicate_source_identity_count": 0,
        "duplicate_source_identities": [],
        "provenance_without_rowid": None,
        "unique_source_index_present": None,
        "redundant_source_index_absent": None,
        "findings": findings,
    }
    try:
        with closing(_connect_readonly(path)) as connection:
            result["quick_check"] = _pragma_rows(connection, "quick_check")
            result["integrity_check"] = _pragma_rows(connection, "integrity_check")
            result["foreign_key_check"] = [
                list(row) for row in connection.execute("PRAGMA foreign_key_check")
            ]
            if result["quick_check"] != ["ok"]:
                findings.append(f"{role} quick_check failed: {path}")
            if result["integrity_check"] != ["ok"]:
                findings.append(f"{role} integrity_check failed: {path}")
            if result["foreign_key_check"]:
                findings.append(f"{role} foreign_key_check failed: {path}")
            for table in ("history_outbox", "history_events", "history_events_v2"):
                if _table_exists(connection, table):
                    result["event_counts"][table] = _count(connection, table)
            if role == "shard":
                _audit_shard_provenance(connection, result, findings, path)
    except sqlite3.Error as exc:
        findings.append(f"{role} database audit failed: {path}: {exc}")
    return result


def _audit_shard_provenance(
    connection: sqlite3.Connection,
    result: dict[str, Any],
    findings: list[str],
    path: Path,
) -> None:
    required_tables = {
        "history_events_v2",
        "history_event_types_v2",
        _PROVENANCE_TABLE,
    }
    missing_tables = sorted(
        table for table in required_tables if not _table_exists(connection, table)
    )
    if missing_tables:
        findings.append(
            f"shard provenance schema is incomplete: {path}: {','.join(missing_tables)}"
        )
        result["provenance_without_rowid"] = False
        result["unique_source_index_present"] = False
        result["redundant_source_index_absent"] = False
        return

    result["event_counts"]["legacy_events_v2"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM history_events_v2 AS e "
            "JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id "
            "WHERE t.name='legacy'"
        ).fetchone()[0]
    )
    result["provenance_count"] = _count(connection, _PROVENANCE_TABLE)
    result["missing_provenance"] = int(
        connection.execute(
            "SELECT COUNT(*) FROM history_events_v2 AS e "
            "JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id "
            "LEFT JOIN history_event_provenance_v2 AS p ON p.event_id=e.event_id "
            "WHERE t.name='legacy' AND p.event_id IS NULL"
        ).fetchone()[0]
    )
    duplicates = [
        {
            "source_table": str(row[0]),
            "source_id": int(row[1]),
            "count": int(row[2]),
        }
        for row in connection.execute(
            "SELECT source_table, source_id, COUNT(*) AS total "
            "FROM history_event_provenance_v2 "
            "GROUP BY source_table, source_id HAVING COUNT(*) > 1 "
            "ORDER BY source_table, source_id"
        )
    ]
    result["duplicate_source_identities"] = duplicates
    result["duplicate_source_identity_count"] = len(duplicates)
    table_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (_PROVENANCE_TABLE,),
    ).fetchone()
    result["provenance_without_rowid"] = bool(
        table_row and "WITHOUT ROWID" in str(table_row[0] or "").upper()
    )
    indexes = {
        str(row[1]): {
            "unique": bool(row[2]),
            "partial": bool(row[4]),
            "columns": [
                str(info[0])
                for info in connection.execute(
                    "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
                    (str(row[1]),),
                )
            ],
        }
        for row in connection.execute("PRAGMA index_list('history_event_provenance_v2')")
    }
    unique_index = indexes.get(_UNIQUE_SOURCE_INDEX)
    result["unique_source_index_present"] = bool(
        unique_index
        and unique_index["unique"]
        and not unique_index["partial"]
        and unique_index["columns"] == ["source_table", "source_id"]
    )
    result["redundant_source_index_absent"] = _REDUNDANT_SOURCE_INDEX not in indexes
    if result["missing_provenance"]:
        findings.append(f"shard has missing legacy provenance: {path}")
    if duplicates:
        findings.append(f"shard has duplicate source identity: {path}")
    if not result["provenance_without_rowid"]:
        findings.append(f"shard provenance table is not WITHOUT ROWID: {path}")
    if not result["unique_source_index_present"]:
        findings.append(f"shard provenance unique source index is invalid: {path}")
    if not result["redundant_source_index_absent"]:
        findings.append(f"shard provenance redundant source index remains: {path}")


def _pragma_rows(connection: sqlite3.Connection, pragma: str) -> list[str]:
    return [str(row[0]) for row in connection.execute(f"PRAGMA {pragma}")]


def _count(connection: sqlite3.Connection, table: str) -> int:
    allowed = {
        "history_outbox",
        "history_events",
        "history_events_v2",
        _PROVENANCE_TABLE,
    }
    if table not in allowed:
        raise HistoryProvenanceValidationError(f"unsupported count table: {table}")
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve(strict=True).as_uri()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _safe_catalog_shard_path(history_root: Path, relative_path: str) -> Path | None:
    candidate = Path(relative_path)
    if not relative_path or candidate.is_absolute():
        return None
    resolved = (history_root / candidate).resolve()
    if resolved == history_root or not resolved.is_relative_to(history_root):
        return None
    return resolved


def _input_file(path: Path, development_root: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(development_root):
        raise HistoryProvenanceValidationError(
            f"{label} must be a file below D:/study: {resolved}"
        )
    return resolved


def _input_directory(path: Path, development_root: Path, *, label: str) -> Path:
    original = path.absolute()
    if original.is_symlink() or (
        hasattr(original, "is_junction") and original.is_junction()
    ):
        raise HistoryProvenanceValidationError(f"{label} cannot be a link or junction")
    resolved = original.resolve(strict=True)
    if not resolved.is_dir() or not resolved.is_relative_to(development_root):
        raise HistoryProvenanceValidationError(
            f"{label} must be a directory below D:/study: {resolved}"
        )
    return resolved


def _output_file(path: Path, development_root: Path) -> Path:
    resolved = path.resolve()
    if resolved == development_root or not resolved.is_relative_to(development_root):
        raise HistoryProvenanceValidationError(
            f"output must remain below D:/study: {resolved}"
        )
    return resolved


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                (
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n"
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices-db", type=Path, required=True)
    parser.add_argument("--history-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply-backfill", action="store_true")
    parser.add_argument("--allow-development-root-only", action="store_true")
    parser.add_argument("--batch-size", type=int, default=1000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = validate_history_provenance(
        devices_database=args.devices_db,
        history_root=args.history_root,
        output_path=args.output,
        apply_backfill=args.apply_backfill,
        allow_development_root_only=args.allow_development_root_only,
        batch_size=args.batch_size,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
