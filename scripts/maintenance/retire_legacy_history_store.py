"""Candidate-first retirement of the external HistoryStore.

The default command only builds and verifies isolated candidate databases.
Production deletion requires both ``--apply`` and the exact explicit
authorization token.  The script only operates on registered site roots and
never touches an unregistered directory such as ``sites/x``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.database import Database
from netconsole.repositories.history_store import HistoryStore
from netconsole.services.current_history_retention import (
    MAX_RECENT_PER_RESOURCE,
    record_device_fact_change,
    record_fit_ap_resource_change,
    record_fit_ap_unauthenticated_change,
    upsert_station_online_summary,
)

AUTHORIZATION_TOKEN = "LEGACY_HISTORY_RETIREMENT_AUTHORIZED"
TARGET_PRODUCTION_ROOT = Path(r"D:\NetConsoleData")
LEGACY_KINDS = (
    "fit_ap_resource",
    "device_fact",
    "fit_ap_unauthenticated",
    "station_online_summary",
)
LEGACY_RUNTIME_TABLES = ("history_outbox", "history_state")
SITE_REGISTRY_NAME = "site_registry.json"
REPORT_SCHEMA_VERSION = 1
BUSINESS_CURRENT_TABLES = (
    "devices",
    "device_facts",
    "ac_fit_ap_resources",
    "ac_fit_ap_unauthenticated",
    "ac_fit_ap_unauthenticated_summary",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "event_id",
            "event_type",
            "legacy_source_table",
            "legacy_source_id",
        }
    }
    nested = payload.pop("payload", None)
    if isinstance(nested, dict):
        return {**nested, **payload}
    return payload


def _event_time(row: dict[str, Any]) -> str:
    for field in ("collected_at", "updated_at", "created_at"):
        value = _text(row.get(field))
        if value:
            return value
    return "1970-01-01T00:00:00"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _registered_sites(data_root: Path) -> list[dict[str, str]]:
    registry_path = data_root / "config" / SITE_REGISTRY_NAME
    value = json.loads(registry_path.read_text(encoding="utf-8"))
    records: list[dict[str, str]] = []
    for item in value.get("sites", []) if isinstance(value, dict) else []:
        if not isinstance(item, dict):
            continue
        site_id = _text(item.get("site_id"))
        relative = _text(item.get("relative_path")) or f"sites/{site_id}"
        root = (data_root / relative).resolve()
        sites_root = (data_root / "sites").resolve()
        if not site_id or root.parent != sites_root or not root.is_dir():
            continue
        records.append(
            {
                "site_id": site_id,
                "display_name": _text(item.get("display_name")) or site_id,
                "directory_name": root.name,
                "relative_path": str(root.relative_to(data_root)),
            }
        )
    return records


def _history_manifest(history_root: Path) -> dict[str, Any]:
    if not history_root.exists():
        return {"exists": False, "bytes": 0, "files": []}
    if history_root.is_symlink() or not history_root.is_dir():
        raise RuntimeError(f"HistoryStore root is not a normal directory: {history_root}")
    files: list[dict[str, Any]] = []
    for path in sorted(history_root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"HistoryStore root contains a symlink: {path}")
        if not path.is_file():
            continue
        files.append(
            {
                "relative_path": str(path.relative_to(history_root)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "exists": True,
        "bytes": sum(int(item["size"]) for item in files),
        "files": files,
    }


def _sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
    finally:
        target_conn.close()
        source_conn.close()


def _read_events(db_path: Path, history_root: Path) -> dict[str, list[dict[str, Any]]]:
    if not history_root.exists():
        return {kind: [] for kind in LEGACY_KINDS}
    store = HistoryStore(db_path, history_root=history_root)
    return {
        kind: [dict(row) for row in store.query_events(kind=kind, limit=1_000_000)]
        for kind in LEGACY_KINDS
    }


def _business_current_columns(path: Path) -> dict[str, tuple[str, ...]]:
    with Database(path).connect_readonly() as conn:
        result: dict[str, tuple[str, ...]] = {}
        for table in BUSINESS_CURRENT_TABLES:
            if not _table_exists(conn, table):
                result[table] = ()
                continue
            result[table] = tuple(
                str(row[1])
                for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            )
        return result


def _business_current_digest(
    path: Path, *, columns_by_table: dict[str, tuple[str, ...]] | None = None
) -> str:
    digest = hashlib.sha256()
    with Database(path).connect_readonly() as conn:
        tables: list[dict[str, Any]] = []
        for table in BUSINESS_CURRENT_TABLES:
            source_columns = (
                columns_by_table.get(table)
                if columns_by_table is not None
                else None
            )
            if source_columns == () or (source_columns is None and not _table_exists(conn, table)):
                tables.append({"table": table, "rows": []})
                continue
            columns = source_columns or tuple(
                str(row[1])
                for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            )
            available = {
                str(row[1])
                for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            missing = [column for column in columns if column not in available]
            if missing:
                raise RuntimeError(
                    f"candidate database lost current columns for {table}: {missing}"
                )
            projection = ", ".join(f'"{column}"' for column in columns)
            rows = [
                dict(row)
                for row in conn.execute(
                    f'SELECT {projection} FROM "{table}" ORDER BY rowid'
                ).fetchall()
            ]
            tables.append({"table": table, "rows": _json_value(rows)})
    digest.update(json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def _replay_events(conn: sqlite3.Connection, events: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    previous_fact: dict[str, dict[str, Any]] = {}
    previous_resource: dict[tuple[str, str], dict[str, Any]] = {}
    previous_unauth: dict[tuple[str, str], dict[str, Any]] = {}
    stats: dict[str, int] = {}
    for kind in LEGACY_KINDS:
        rows = sorted(events.get(kind, []), key=lambda row: (_event_time(row), _text(row.get("event_id"))))
        recent = 0
        for raw in rows:
            payload = _event_payload(raw)
            timestamp = _event_time(payload)
            if kind == "device_fact":
                key = _text(payload.get("device_uuid"))
                if not key:
                    continue
                if record_device_fact_change(
                    conn,
                    payload,
                    previous=previous_fact.get(key),
                    now=timestamp,
                ):
                    recent += 1
                previous_fact[key] = payload
            elif kind == "fit_ap_resource":
                key = (_text(payload.get("ac_device_uuid")), _text(payload.get("ap_uuid")))
                if not all(key):
                    continue
                if record_fit_ap_resource_change(
                    conn,
                    payload,
                    previous=previous_resource.get(key),
                    now=timestamp,
                ):
                    recent += 1
                previous_resource[key] = payload
            elif kind == "fit_ap_unauthenticated":
                from netconsole.services.current_history_retention import unauthenticated_identity_key

                identity_key = unauthenticated_identity_key(payload)
                key = (_text(payload.get("ac_device_uuid")), identity_key)
                if not all(key):
                    continue
                if record_fit_ap_unauthenticated_change(
                    conn,
                    payload,
                    previous=previous_unauth.get(key),
                    identity_key=identity_key,
                    now=timestamp,
                ):
                    recent += 1
                previous_unauth[key] = payload
            else:
                if upsert_station_online_summary(conn, payload, collected_at=timestamp, now=timestamp):
                    recent += 1
        stats[f"{kind}_source_rows"] = len(rows)
        stats[f"{kind}_recent_migrated"] = recent
    return stats


def _current_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = {
        "fit_ap_resource_current": "ac_fit_ap_resources",
        "device_fact_current": "device_facts",
        "fit_ap_unauth_current": "ac_fit_ap_unauthenticated",
        "station_summary_current": "station_online_summary_current",
        "fit_ap_resource_recent": "fit_ap_resource_recent",
        "device_fact_recent": "device_fact_recent",
        "fit_ap_unauth_recent": "fit_ap_unauthenticated_recent",
        "station_summary_recent": "station_online_summary_recent",
    }
    result: dict[str, int] = {}
    for key, table in tables.items():
        result[key] = (
            int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            if _table_exists(conn, table)
            else 0
        )
    return result


def _retire_legacy_runtime_tables(conn: sqlite3.Connection) -> dict[str, int]:
    """Drop only the two tables owned exclusively by the retired HistoryStore."""
    removed: dict[str, int] = {}
    for table in LEGACY_RUNTIME_TABLES:
        if not _table_exists(conn, table):
            removed[table] = 0
            continue
        removed[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        conn.execute(f'DROP TABLE "{table}"')
    return removed


def _verify_candidate(path: Path) -> dict[str, Any]:
    database = Database(path)
    with database.connect_readonly() as conn:
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        integrity_check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        counts = _current_counts(conn)
        legacy_runtime_tables = [
            table for table in LEGACY_RUNTIME_TABLES if _table_exists(conn, table)
        ]
        limits = {
            "fit_ap_resource": int(
                conn.execute(
                    "SELECT MAX(total) FROM (SELECT COUNT(*) AS total FROM fit_ap_resource_recent GROUP BY ac_device_uuid, ap_uuid)"
                ).fetchone()[0]
                or 0
            ),
            "device_fact": int(
                conn.execute(
                    "SELECT MAX(total) FROM (SELECT COUNT(*) AS total FROM device_fact_recent GROUP BY device_uuid)"
                ).fetchone()[0]
                or 0
            ),
            "fit_ap_unauthenticated": int(
                conn.execute(
                    "SELECT MAX(total) FROM (SELECT COUNT(*) AS total FROM fit_ap_unauthenticated_recent GROUP BY ac_device_uuid, identity_key)"
                ).fetchone()[0]
                or 0
            ),
            "station_online_summary": int(
                conn.execute(
                    "SELECT MAX(total) FROM (SELECT COUNT(*) AS total FROM station_online_summary_recent GROUP BY site_name)"
                ).fetchone()[0]
                or 0
            ),
        }
        history_dir = path.parent / "history"
    return {
        "quick_check": quick_check,
        "integrity_check": integrity_check,
        "counts": counts,
        "max_recent_per_resource": limits,
        "history_directory_created": history_dir.exists(),
        "status": "PASS"
        if quick_check.lower() == "ok"
        and integrity_check.lower() == "ok"
        and max(limits.values(), default=0) <= MAX_RECENT_PER_RESOURCE
        and not legacy_runtime_tables
        and not history_dir.exists()
        else "FAIL",
        "legacy_runtime_tables": legacy_runtime_tables,
    }


def prepare(data_root: Path, candidate_root: Path) -> dict[str, Any]:
    data_root = data_root.resolve()
    candidate_root = candidate_root.resolve()
    sites = _registered_sites(data_root)
    candidate_root.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "PASS",
        "mode": "candidate",
        "generated_at": _now(),
        "data_root": str(data_root),
        "registered_site_count": len(sites),
        "max_recent_per_resource": MAX_RECENT_PER_RESOURCE,
        "sites": [],
    }
    for site in sites:
        source_site = data_root / site["relative_path"]
        source_db = source_site / "db" / "devices.db"
        history_root = source_site / "db" / "history"
        candidate_db = candidate_root / site["relative_path"] / "db" / "devices.db"
        source_manifest = {
            "devices_sha256": _sha256(source_db) if source_db.is_file() else "",
            "history": _history_manifest(history_root),
        }
        if not source_db.is_file() or source_db.is_symlink():
            report["sites"].append(
                {**site, "status": "SKIPPED_NO_DEVICES_DB", "source_manifest": source_manifest}
            )
            continue
        events = _read_events(source_db, history_root)
        digest_columns = _business_current_columns(source_db)
        current_digest_before = _business_current_digest(
            source_db, columns_by_table=digest_columns
        )
        _sqlite_backup(source_db, candidate_db)
        Database(candidate_db).initialize()
        with Database(candidate_db).connect() as conn:
            stats = _replay_events(conn, events)
            legacy_runtime_tables_removed = _retire_legacy_runtime_tables(conn)
            conn.execute(
                "INSERT INTO schema_metadata(key,value,created_at,updated_at) VALUES ('history_store_authority','retired',?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (_now(), _now()),
            )
            conn.commit()
        verification = _verify_candidate(candidate_db)
        current_digest_after = _business_current_digest(
            candidate_db, columns_by_table=digest_columns
        )
        current_fact_loss = current_digest_before != current_digest_after
        source_rows = sum(int(stats.get(f"{kind}_source_rows", 0)) for kind in LEGACY_KINDS)
        recent_rows = sum(int(stats.get(f"{kind}_recent_migrated", 0)) for kind in LEGACY_KINDS)
        item = {
            **site,
            "status": verification["status"],
            "source_manifest": source_manifest,
            "candidate_database": str(candidate_db),
            "business_current_fact_loss": int(current_fact_loss),
            "business_current_digest_before": current_digest_before,
            "business_current_digest_after": current_digest_after,
            "fit_ap_resource_current_migrated": int(verification["counts"].get("fit_ap_resource_current", 0)),
            "device_fact_current_migrated": int(verification["counts"].get("device_fact_current", 0)),
            "fit_ap_unauth_current_migrated": int(verification["counts"].get("fit_ap_unauth_current", 0)),
            "station_summary_current_migrated": int(verification["counts"].get("station_summary_current", 0)),
            "legacy_rows_seen": source_rows,
            "legacy_rows_discarded": max(0, source_rows - recent_rows),
            **stats,
            "verification": verification,
            "legacy_runtime_tables_removed": legacy_runtime_tables_removed,
            "legacy_runtime_rows_discarded": sum(legacy_runtime_tables_removed.values()),
        }
        report["sites"].append(item)
        if verification["status"] != "PASS":
            report["status"] = "FAIL"
        if current_fact_loss:
            report["status"] = "FAIL"
    report["legacy_history_bytes_before"] = sum(
        int(item.get("source_manifest", {}).get("history", {}).get("bytes", 0))
        for item in report["sites"]
    )
    report["legacy_history_directory_count_before"] = sum(
        1
        for item in report["sites"]
        if bool(item.get("source_manifest", {}).get("history", {}).get("exists"))
    )
    report["business_current_fact_loss"] = sum(
        int(item.get("business_current_fact_loss", 0)) for item in report["sites"]
    )
    report["legacy_rows_discarded"] = sum(
        int(item.get("legacy_rows_discarded", 0)) for item in report["sites"]
    )
    (candidate_root / "retirement-candidate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _assert_source_unchanged(data_root: Path, item: dict[str, Any]) -> None:
    site_root = data_root / str(item["relative_path"])
    db_path = site_root / "db" / "devices.db"
    expected = str(item.get("source_manifest", {}).get("devices_sha256") or "")
    if expected and _sha256(db_path) != expected:
        raise RuntimeError(f"Production devices.db changed after candidate preparation: {db_path}")
    actual_history = _history_manifest(site_root / "db" / "history")
    if actual_history != item.get("source_manifest", {}).get("history", {}):
        raise RuntimeError(f"Production HistoryStore source changed after candidate preparation: {site_root}")


def _safe_history_root(site_root: Path) -> Path:
    site_root = site_root.resolve()
    raw_history_root = site_root / "db" / "history"
    if raw_history_root.is_symlink():
        raise RuntimeError(f"unsafe HistoryStore deletion target: {raw_history_root}")
    history_root = raw_history_root.resolve()
    if history_root.parent != (site_root / "db").resolve():
        raise RuntimeError(f"unsafe HistoryStore deletion target: {history_root}")
    return history_root


def apply(data_root: Path, candidate_root: Path, backup_root: Path) -> dict[str, Any]:
    data_root = data_root.resolve()
    candidate_root = candidate_root.resolve()
    backup_root = backup_root.resolve()
    if data_root != TARGET_PRODUCTION_ROOT.resolve():
        raise RuntimeError(f"--apply only accepts the exact production root {TARGET_PRODUCTION_ROOT}")
    if backup_root == data_root or data_root in backup_root.parents:
        raise RuntimeError("rollback backup must be outside the production data root")
    report_path = candidate_root / "retirement-candidate.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise RuntimeError("candidate verification did not pass")
    backup_root.mkdir(parents=True, exist_ok=False)
    changed: list[dict[str, Any]] = []
    try:
        for item in report.get("sites", []):
            if str(item.get("status")) == "SKIPPED_NO_DEVICES_DB":
                continue
            _assert_source_unchanged(data_root, item)
            site_root = data_root / str(item["relative_path"])
            db_path = site_root / "db" / "devices.db"
            candidate_db = Path(str(item["candidate_database"]))
            if not candidate_db.is_file():
                raise RuntimeError(f"candidate database is missing: {candidate_db}")
            backup_db = backup_root / str(item["relative_path"]) / "db" / "devices.db"
            _sqlite_backup(db_path, backup_db)
            source_history = site_root / "db" / "history"
            backup_history = backup_root / str(item["relative_path"]) / "db" / "history"
            if source_history.exists():
                shutil.copytree(source_history, backup_history, symlinks=False)
            changed.append({**item, "production_database": str(db_path), "backup": str(backup_root / str(item["relative_path"]))})
            temporary = db_path.with_name(f".{db_path.name}.history-retirement.tmp")
            shutil.copy2(candidate_db, temporary)
            os.replace(temporary, db_path)
            if source_history.exists():
                shutil.rmtree(_safe_history_root(site_root))
        post = verify_production(data_root)
        if post["status"] != "PASS":
            raise RuntimeError(f"post-apply verification failed: {post}")
    except Exception:
        for item in reversed(changed):
            site_root = data_root / str(item["relative_path"])
            backup_site = backup_root / str(item["relative_path"])
            backup_db = backup_site / "db" / "devices.db"
            if backup_db.is_file():
                shutil.copy2(backup_db, site_root / "db" / "devices.db")
            backup_history = backup_site / "db" / "history"
            history_root = site_root / "db" / "history"
            if backup_history.is_dir() and not history_root.exists():
                shutil.copytree(backup_history, history_root, symlinks=False)
        raise
    result = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "PASS",
        "mode": "production_apply",
        "generated_at": _now(),
        "backup_root": str(backup_root),
        "sites": changed,
        "post_verification": post,
    }
    (backup_root / "retirement-apply.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def verify_production(data_root: Path) -> dict[str, Any]:
    data_root = data_root.resolve()
    sites = _registered_sites(data_root)
    results: list[dict[str, Any]] = []
    for site in sites:
        site_root = data_root / site["relative_path"]
        db_path = site_root / "db" / "devices.db"
        history_root = site_root / "db" / "history"
        if not db_path.is_file():
            results.append({**site, "status": "SKIPPED_NO_DEVICES_DB"})
            continue
        verification = _verify_candidate(db_path)
        history = _history_manifest(history_root)
        verification["history"] = history
        verification["status"] = "PASS" if verification["status"] == "PASS" and not history["exists"] else "FAIL"
        results.append({**site, **verification})
    history_bytes = sum(int(item.get("history", {}).get("bytes", 0)) for item in results)
    history_dirs = sum(1 for item in results if bool(item.get("history", {}).get("exists")))
    status = "PASS" if all(str(item.get("status")) in {"PASS", "SKIPPED_NO_DEVICES_DB"} for item in results) else "FAIL"
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "mode": "production_verify",
        "generated_at": _now(),
        "registered_site_count": len(sites),
        "history_bytes_after": history_bytes,
        "history_directory_count_after": history_dirs,
        "history_catalog_count_after": sum(
            len(list((data_root / item["relative_path"] / "db" / "history").glob("catalog.db")))
            for item in sites
        ),
        "history_month_shard_count_after": sum(
            len(list((data_root / item["relative_path"] / "db" / "history").glob("devices-*.db")))
            for item in sites
        ),
        "sites": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "apply", "verify"))
    parser.add_argument("--data-root", type=Path, default=TARGET_PRODUCTION_ROOT)
    parser.add_argument("--candidate-root", type=Path, required=False)
    parser.add_argument("--backup-root", type=Path, required=False)
    parser.add_argument("--authorization", default="")
    parser.add_argument("--output", type=Path, required=False)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "prepare":
        candidate_root = args.candidate_root or Path("D:/study/diagnostic/NetConsole/history-store-retirement-candidate")
        result = prepare(args.data_root, candidate_root)
    elif args.command == "verify":
        result = verify_production(args.data_root)
    else:
        if args.authorization != AUTHORIZATION_TOKEN:
            raise SystemExit("production apply requires --authorization LEGACY_HISTORY_RETIREMENT_AUTHORIZED")
        if args.candidate_root is None:
            raise SystemExit("apply requires --candidate-root")
        backup_root = args.backup_root or Path("D:/study/backup/NetConsole/history-store-retirement") / datetime.now().strftime("%Y%m%d-%H%M%S")
        result = apply(args.data_root, args.candidate_root, backup_root)
    output = args.output
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
