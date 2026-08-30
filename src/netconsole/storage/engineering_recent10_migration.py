"""Candidate-first DEV migration for engineering Current + Recent10 state.

The migration intentionally reads the old HistoryStore only for inventory. The
four engineering projections are rebuilt from their primary current/history
tables, which are the durable source rows for this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from netconsole.core.database import Database
from netconsole.services.device_state_retention import (
    upsert_device_lldp_current_and_history,
    upsert_device_optical_current_and_history,
)
from netconsole.services.interface_retention import upsert_interface_current_and_history
from netconsole.services.radio_retention import upsert_radio_current_and_history
from netconsole.storage.lldp_optical_retention_migration import (
    _active_sites,
    _backup_database,
    _manifest,
    _resolve_data_root,
    _vacuum_database,
)


TARGET_HISTORY_TABLES = (
    "ac_fit_ap_radio_history",
    "ac_fit_ap_lldp_history",
    "ap_lldp_history",
    "ac_fit_ap_optical_history",
    "ap_optical_history",
)
BOUNDED_AUTHORITY_TABLES = (
    ("fit_ap_lldp_retention_meta", "fit_ap_lldp"),
    ("fit_ap_radio_retention_meta", "fit_ap_radio"),
    ("device_interface_retention_meta", "device_interface"),
    ("device_lldp_retention_meta", "device_lldp"),
    ("device_optical_retention_meta", "device_optical"),
    ("optical_retention_meta", "fit_ap_optical"),
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value: object) -> str:
    return str(value or "").strip()


def _time(row: dict[str, Any]) -> str:
    for field in ("changed_at", "collected_at", "updated_at", "created_at", "last_seen_at"):
        value = _text(row.get(field))
        if value:
            return value
    return "1970-01-01T00:00:00"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]


def _read_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _site_id(db_path: Path) -> str:
    return db_path.parent.parent.name


def _history_path(db_path: Path) -> Path:
    return db_path.parent / "history"


def _resource_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {str(row.get("ap_uuid") or ""): row for row in _rows(conn, "ac_fit_ap_resources") if row.get("ap_uuid")}


def _radio_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    resources = _resource_map(conn)
    history_rows: list[dict[str, Any]] = []
    for item in _rows(conn, "ac_fit_ap_radio_history"):
        resource = resources.get(str(item.get("ap_uuid") or ""), {})
        history_rows.append({**resource, **item, "radio_id": item.get("rid") or item.get("radio_id")})
    current_rows: list[dict[str, Any]] = []
    for resource in resources.values():
        for radio_id in (1, 2, 3):
            prefix = f"rid{radio_id}_"
            if not any(resource.get(f"{prefix}{field}") not in (None, "") for field in (
                "status", "mode", "band", "channel", "bandwidth", "usage", "tx_power", "clients", "bbssid"
            )):
                continue
            current_rows.append({
                **resource,
                "radio_id": radio_id,
                "status": resource.get(f"{prefix}status"),
                "mode": resource.get(f"{prefix}mode"),
                "band": resource.get(f"{prefix}band"),
                "channel": resource.get(f"{prefix}channel"),
                "bandwidth": resource.get(f"{prefix}bandwidth"),
                "usage": resource.get(f"{prefix}usage"),
                "tx_power": resource.get(f"{prefix}tx_power"),
                "clients": resource.get(f"{prefix}clients"),
                "bbssid": resource.get(f"{prefix}bbssid"),
                "source": "resource_current",
            })
    return [
        *sorted(history_rows, key=lambda row: (_time(row), int(row.get("id") or 0))),
        *sorted(current_rows, key=lambda row: (_time(row), int(row.get("id") or 0))),
    ]


def _interface_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        *sorted(_rows(conn, "device_interfaces_history"), key=lambda row: (_time(row), int(row.get("id") or 0))),
        *sorted(_rows(conn, "device_interfaces"), key=lambda row: (_time(row), int(row.get("id") or 0))),
    ]


def _device_lldp_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        *sorted(_rows(conn, "device_lldp_neighbors_history"), key=lambda row: (_time(row), int(row.get("id") or 0))),
        *sorted(_rows(conn, "device_lldp_neighbors"), key=lambda row: (_time(row), int(row.get("id") or 0))),
    ]


def _device_optical_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        *sorted(_rows(conn, "device_optical_modules_history"), key=lambda row: (_time(row), int(row.get("id") or 0))),
        *sorted(_rows(conn, "device_optical_modules"), key=lambda row: (_time(row), int(row.get("id") or 0))),
    ]


def _plan(rows: Iterable[dict[str, Any]], key_fn, state_fn, *, limit: int = 10) -> dict[str, int]:
    current: dict[Any, str] = {}
    changes: Counter[Any] = Counter()
    source_rows = 0
    no_change = 0
    for row in rows:
        source_rows += 1
        key = key_fn(row)
        state = json.dumps(state_fn(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(state.encode("utf-8")).hexdigest()
        if key in current:
            if current[key] == fingerprint:
                no_change += 1
            else:
                changes[key] += 1
        current[key] = fingerprint
    return {
        "source_rows": source_rows,
        "resource_count": len(current),
        "no_change_rows": no_change,
        "true_change_rows": sum(changes.values()),
        "recent_retained_rows": sum(min(value, limit) for value in changes.values()),
        "over_retention_dropped": sum(max(value - limit, 0) for value in changes.values()),
        "current_rows": len(current),
        "max_recent_per_resource": max(changes.values(), default=0),
    }


def _radio_key(row: dict[str, Any]) -> tuple[str, int]:
    return (_text(row.get("ap_uuid")), int(row.get("radio_id") or row.get("rid") or 0))


def _radio_state(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in ("status", "mode", "band", "channel", "bandwidth", "usage", "tx_power", "clients", "bbssid")}


def _interface_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_text(row.get("device_uuid")), _text(row.get("interface_name")).casefold())


def _interface_state(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {"collected_at", "collect_run_uuid", "raw_log_path", "updated_at", "vlan_config_collected_at", "id", "created_at", "changed_at", "source_revision"}
    return {key: value for key, value in row.items() if key not in ignored}


def _lldp_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (_text(row.get("device_uuid")), _text(row.get("local_interface")).casefold(), _text(row.get("chassis_id") or row.get("neighbor_mac")).casefold(), _text(row.get("neighbor_interface")).casefold())


def _lldp_state(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {"collected_at", "collect_run_uuid", "raw_log_path", "updated_at", "id", "created_at", "changed_at", "source_revision"}
    return {key: value for key, value in row.items() if key not in ignored}


def _optical_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_text(row.get("device_uuid")), _text(row.get("interface_name")).casefold())


def _optical_state(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {"collected_at", "collect_run_uuid", "raw_log_path", "updated_at", "id", "created_at", "changed_at", "source_revision"}
    return {key: value for key, value in row.items() if key not in ignored}


def _clear_rebuild_targets(conn: sqlite3.Connection) -> None:
    for table in (
        "fit_ap_radio_current", "fit_ap_radio_history",
        "device_interfaces", "device_interfaces_history",
        "device_lldp_neighbors", "device_lldp_neighbors_history",
        "device_optical_modules", "device_optical_modules_history",
        "ac_fit_ap_radio_history", "ac_fit_ap_lldp_history", "ap_lldp_history",
        "ac_fit_ap_optical_history", "ap_optical_history",
        "history_outbox", "history_state",
    ):
        if _table_exists(conn, table):
            conn.execute(f'DELETE FROM "{table}"')
    for table, _kind in BOUNDED_AUTHORITY_TABLES:
        if _table_exists(conn, table):
            conn.execute(
                f"INSERT INTO {table}(key,value) VALUES ('authority','bounded_v1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
    conn.execute(
        "INSERT INTO schema_metadata(key,value,created_at,updated_at) "
        "VALUES ('engineering_history_authority','retired',strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at"
    )


def _delete_stale_current_and_recent(
    conn: sqlite3.Connection,
    *,
    current_table: str,
    recent_table: str,
    key_fn,
    valid_keys: set[Any],
) -> None:
    current_rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{current_table}"').fetchall()]
    stale_current_ids = [int(row["id"]) for row in current_rows if key_fn(row) not in valid_keys]
    if stale_current_ids:
        placeholders = ", ".join("?" for _ in stale_current_ids)
        conn.execute(f'DELETE FROM "{current_table}" WHERE id IN ({placeholders})', stale_current_ids)
    recent_rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{recent_table}"').fetchall()]
    stale_recent_ids = [int(row["id"]) for row in recent_rows if key_fn(row) not in valid_keys]
    if stale_recent_ids:
        placeholders = ", ".join("?" for _ in stale_recent_ids)
        conn.execute(f'DELETE FROM "{recent_table}" WHERE id IN ({placeholders})', stale_recent_ids)


def _replay_candidate(path: Path, site_id: str) -> dict[str, Any]:
    database = Database(path)
    database.initialize()
    with closing(_read_db(path)) as source:
        resources = _resource_map(source)
        radio_rows = _radio_rows(source)
        interface_rows = _interface_rows(source)
        lldp_rows = _device_lldp_rows(source)
        optical_rows = _device_optical_rows(source)
        valid_radio_keys = {
            (str(resource.get("ap_uuid") or ""), radio_id)
            for resource in resources.values()
            for radio_id in (1, 2, 3)
            if any(resource.get(f"rid{radio_id}_{field}") not in (None, "") for field in (
                "status", "mode", "band", "channel", "bandwidth", "usage", "tx_power", "clients", "bbssid"
            ))
        }
        valid_interface_keys = {_interface_key(row) for row in _rows(source, "device_interfaces")}
        valid_lldp_keys = {_lldp_key(row) for row in _rows(source, "device_lldp_neighbors")}
        valid_optical_keys = {_optical_key(row) for row in _rows(source, "device_optical_modules")}
    conn = database.connect()
    try:
        _clear_rebuild_targets(conn)
        conn.commit()
        for row in radio_rows:
            radio_id = row.get("radio_id") or row.get("rid")
            if radio_id:
                upsert_radio_current_and_history(conn, row, site_id=site_id, radio_id=radio_id, now=_time(row))
        for row in interface_rows:
            if row.get("device_uuid") and row.get("interface_name"):
                upsert_interface_current_and_history(conn, row, site_id=site_id, now=_time(row))
        for row in lldp_rows:
            if row.get("device_uuid") and row.get("local_interface"):
                upsert_device_lldp_current_and_history(conn, row, site_id=site_id, now=_time(row))
        for row in optical_rows:
            if row.get("device_uuid") and row.get("interface_name"):
                upsert_device_optical_current_and_history(conn, row, site_id=site_id, now=_time(row))
        _delete_stale_current_and_recent(
            conn,
            current_table="fit_ap_radio_current",
            recent_table="fit_ap_radio_history",
            key_fn=lambda row: (_text(row.get("ap_identity")), int(row.get("radio_id") or 0)),
            valid_keys=valid_radio_keys,
        )
        _delete_stale_current_and_recent(
            conn,
            current_table="device_interfaces",
            recent_table="device_interfaces_history",
            key_fn=_interface_key,
            valid_keys=valid_interface_keys,
        )
        _delete_stale_current_and_recent(
            conn,
            current_table="device_lldp_neighbors",
            recent_table="device_lldp_neighbors_history",
            key_fn=_lldp_key,
            valid_keys=valid_lldp_keys,
        )
        _delete_stale_current_and_recent(
            conn,
            current_table="device_optical_modules",
            recent_table="device_optical_modules_history",
            key_fn=_optical_key,
            valid_keys=valid_optical_keys,
        )
        conn.commit()
    finally:
        conn.close()
    _vacuum_database(path)
    return verify_database(path, site_id)


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) if _table_exists(conn, table) else 0


def _max_per_resource(conn: sqlite3.Connection, table: str, group_by: str) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COALESCE(MAX(total),0) FROM (SELECT {group_by}, COUNT(*) AS total FROM {table} GROUP BY {group_by})").fetchone()
    return int(row[0] or 0)


def verify_database(path: Path, site_id: str) -> dict[str, Any]:
    with closing(_read_db(path)) as conn:
        result: dict[str, Any] = {
            "site_id": site_id,
            "quick_check": str(conn.execute("PRAGMA quick_check").fetchone()[0]),
            "radio_current_rows": _count(conn, "fit_ap_radio_current"),
            "radio_recent_rows": _count(conn, "fit_ap_radio_history"),
            "interface_current_rows": _count(conn, "device_interfaces"),
            "interface_recent_rows": _count(conn, "device_interfaces_history"),
            "lldp_current_rows": _count(conn, "device_lldp_neighbors"),
            "lldp_recent_rows": _count(conn, "device_lldp_neighbors_history"),
            "device_optical_current_rows": _count(conn, "device_optical_modules"),
            "device_optical_recent_rows": _count(conn, "device_optical_modules_history"),
            "fit_ap_lldp_current_rows": _count(conn, "fit_ap_lldp_current"),
            "fit_ap_lldp_recent_rows": _count(conn, "fit_ap_lldp_history"),
            "fit_ap_optical_current_rows": _count(conn, "optical_current"),
            "fit_ap_optical_recent_rows": _count(conn, "optical_history"),
            "treatment_rows": _count(conn, "ap_optical_treatment"),
            "treatment_duplicate_groups": 0,
            "radio_max_recent": _max_per_resource(conn, "fit_ap_radio_history", "site_id, ap_identity, radio_id"),
            "interface_max_recent": _max_per_resource(conn, "device_interfaces_history", "site_id, device_uuid, interface_name"),
            "lldp_max_recent": _max_per_resource(conn, "device_lldp_neighbors_history", "site_id, device_uuid, local_interface, chassis_id, neighbor_interface"),
            "device_optical_max_recent": _max_per_resource(conn, "device_optical_modules_history", "site_id, device_uuid, interface_name"),
            "fit_ap_lldp_max_recent": _max_per_resource(conn, "fit_ap_lldp_history", "resource_key"),
            "fit_ap_optical_max_recent": _max_per_resource(conn, "optical_history", "site_id, ap_identity, side"),
        }
        duplicate = conn.execute(
            "SELECT COUNT(*) FROM (SELECT site_id, ap_identity, COUNT(*) AS total FROM ap_optical_treatment GROUP BY site_id, ap_identity HAVING total>1)"
        ).fetchone()
        result["treatment_duplicate_groups"] = int(duplicate[0] or 0)
        result["treatment_rows_over_ap_count"] = int(
            result["treatment_rows"] > _count(conn, "ac_fit_ap_resources")
        )
        result["legacy_direct_radio_rows"] = _count(conn, "ac_fit_ap_radio_history")
        result["legacy_direct_ap_lldp_rows"] = _count(conn, "ac_fit_ap_lldp_history") + _count(conn, "ap_lldp_history")
        result["legacy_direct_ap_optical_rows"] = _count(conn, "ac_fit_ap_optical_history") + _count(conn, "ap_optical_history")
    return result


def _source_plan(db_path: Path, site_id: str) -> dict[str, Any]:
    with closing(_read_db(db_path)) as conn:
        radio = _radio_rows(conn)
        interfaces = _interface_rows(conn)
        lldp = _device_lldp_rows(conn)
        optical = _device_optical_rows(conn)
        return {
            "radio": _plan(radio, _radio_key, _radio_state),
            "interface": _plan(interfaces, _interface_key, _interface_state),
            "lldp": _plan(lldp, _lldp_key, _lldp_state),
            "device_optical": _plan(optical, _optical_key, _optical_state),
            "source_direct_rows": {
                table: len(_rows(conn, table)) for table in TARGET_HISTORY_TABLES
            },
        }


def _history_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def migrate(*, data_root: Path, output: Path, candidate_root: Path, selected_sites: set[str] | None = None, apply: bool = False, cutover: bool = False) -> dict[str, Any]:
    root = _resolve_data_root(str(data_root))
    sites = _active_sites(root, selected_sites)
    if not sites:
        raise ValueError("no DEV site database found")
    report: dict[str, Any] = {
        "generated_at": _now(),
        "mode": "cutover" if cutover else "apply" if apply else "dry_run",
        "data_root": str(root),
        "production_data_touched": False,
        "sites": [],
    }
    if apply:
        candidate_root = candidate_root.resolve()
        candidate_root.mkdir(parents=True, exist_ok=True)
    for site_id, db_path in sites:
        history = _history_path(db_path)
        before = _manifest([db_path, history / "catalog.db", *sorted(history.glob("devices-*.db"))])
        site_report: dict[str, Any] = {
            "site_id": site_id,
            "source_database": str(db_path),
            "legacy_historystore_bytes_before": _history_bytes(history),
            "source_manifest_before": before,
            "plan": _source_plan(db_path, site_id),
        }
        if apply:
            candidate_db = candidate_root / "sites" / site_id / "db" / "devices.db"
            candidate_db.parent.mkdir(parents=True, exist_ok=True)
            _backup_database(db_path, candidate_db)
            candidate_history = candidate_db.parent / "history"
            if candidate_history.exists():
                shutil.rmtree(candidate_history)
            site_report["candidate_database"] = str(candidate_db)
            site_report["candidate_verification"] = _replay_candidate(candidate_db, site_id)
            site_report["candidate_historystore_bytes_after"] = 0
            after = _manifest([db_path, history / "catalog.db", *sorted(history.glob("devices-*.db"))])
            if before != after:
                raise RuntimeError(f"source changed during candidate migration: {site_id}")
            site_report["source_manifest_after_read"] = after
        report["sites"].append(site_report)
    report["legacy_historystore_bytes_before"] = sum(int(site["legacy_historystore_bytes_before"]) for site in report["sites"])
    report["legacy_historystore_bytes_after"] = 0 if apply else None
    if cutover:
        _cutover(root, candidate_root, report)
        report["legacy_historystore_bytes_after"] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _cutover(root: Path, candidate_root: Path, report: dict[str, Any]) -> None:
    rollback_root = Path(r"D:\study\NetConsole-Workspace\NetConsole\.local\tmp\engineering-recent10") / datetime.now().strftime("%Y%m%d-%H%M%S")
    moved: list[tuple[Path, Path]] = []
    try:
        for site in report["sites"]:
            site_id = str(site["site_id"])
            source_db = root / "sites" / site_id / "db" / "devices.db"
            source_history = source_db.parent / "history"
            candidate_db = candidate_root / "sites" / site_id / "db" / "devices.db"
            if not candidate_db.is_file():
                raise RuntimeError(f"candidate missing: {candidate_db}")
            rollback_db = rollback_root / "sites" / site_id / "db" / "devices.db"
            rollback_db.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source_db, rollback_db)
            moved.append((rollback_db, source_db))
            os.replace(candidate_db, source_db)
            if source_history.exists():
                rollback_history = rollback_db.parent / "history"
                os.replace(source_history, rollback_history)
                moved.append((rollback_history, source_history))
            site["legacy_historystore_deleted"] = True
        shutil.rmtree(rollback_root, ignore_errors=True)
        report["cutover"] = {"status": "completed", "rollback_root_removed": True}
    except Exception:
        for rollback, source in reversed(moved):
            if source.exists():
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            if rollback.exists():
                os.replace(rollback, source)
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DEV-only engineering Current + Recent10 migration")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", default="ENGINEERING_RECENT10_MIGRATION_REPORT.json")
    parser.add_argument("--candidate-root", default=r"D:\study\NetConsole-Workspace\diagnostic\engineering-recent10-candidates")
    parser.add_argument("--site", action="append", dest="sites")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cutover", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.cutover and not args.apply:
        # Cutover always rebuilds candidates in the same invocation; this keeps
        # the source manifest gate in one auditable transaction.
        args.apply = True
    report = migrate(
        data_root=Path(args.data_root),
        output=Path(args.output),
        candidate_root=Path(args.candidate_root),
        selected_sites=set(args.sites or []),
        apply=bool(args.apply),
        cutover=bool(args.cutover),
    )
    print(json.dumps({"mode": report["mode"], "sites": len(report["sites"]), "output": str(Path(args.output).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
