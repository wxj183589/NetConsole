"""DEV-only migration for bounded LLDP/optical current state.

The migration is intentionally a candidate-first operation.  It reads only
``sites/*/db/devices.db`` below a directory named ``NetConsoleData-dev`` and
never writes to that source tree unless the caller explicitly requests the
separate cutover step after a candidate has been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from netconsole.core.database import Database
from netconsole.repositories.history_store import HistoryStore
from netconsole.services.lldp_retention import build_lldp_projection, upsert_lldp_current_and_history
from netconsole.services.optical_retention import (
    build_optical_projection,
    optical_ap_identity,
    update_ap_optical_treatment,
    upsert_optical_current_and_history,
)


TARGET_PRIMARY_TABLES = frozenset(
    {
        "ac_fit_ap_lldp_history",
        "ap_lldp_history",
        "ac_fit_ap_optical_history",
        "ap_optical_history",
        "history_outbox",
        "history_state",
    }
)
TARGET_HISTORY_KINDS = frozenset({"fit_ap_lldp", "fit_ap_optical"})
CURRENT_SOURCE_TABLES = frozenset({"ac_fit_ap_resources", "ac_fit_ap_optical"})


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value: object) -> str:
    return str(value or "").strip()


def _row_time(row: dict[str, Any]) -> str:
    for key in (
        "lldp_collected_at",
        "optical_collected_at",
        "collected_at",
        "updated_at",
        "created_at",
    ):
        value = _text(row.get(key))
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


def _normalize_generic_lldp(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("neighbor_switch_name") or row.get("neighbor_switch_sysname"):
        return {
            **row,
            "ac_device_uuid": row.get("source_device_uuid") or row.get("ac_device_uuid") or "",
            "lldp_source": row.get("source") or "ap_lldp_history",
            "lldp_neighbor_name": row.get("neighbor_switch_name")
            or row.get("neighbor_switch_sysname")
            or "",
            "lldp_neighbor_interface": row.get("neighbor_interface") or "",
            "lldp_neighbor_mac": row.get("neighbor_switch_mac") or row.get("neighbor_mac") or "",
        }
    return row


def _normalize_optical(row: dict[str, Any], *, source_table: str) -> dict[str, Any]:
    if source_table == "ap_optical_history":
        return {
            **row,
            "ac_device_uuid": row.get("device_uuid") or row.get("ac_device_uuid") or "",
            "status": row.get("alarm_status") or row.get("status") or "",
            "source": row.get("data_source") or row.get("source") or source_table,
        }
    return {**row, "source": row.get("source") or source_table}


def _source_revision(row: dict[str, Any]) -> str:
    return _text(
        row.get("source_revision")
        or row.get("event_id")
        or row.get("collect_run_uuid")
        or row.get("session_id")
    )


def _load_source_rows(db_path: Path, site_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load legacy/current rows plus committed shard events for one site."""

    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        lldp_rows: list[dict[str, Any]] = []
        optical_rows: list[dict[str, Any]] = []
        for table in ("ac_fit_ap_lldp_history", "ap_lldp_history"):
            lldp_rows.extend(_normalize_generic_lldp(row) for row in _rows(conn, table))
        for row in _rows(conn, "ac_fit_ap_resources"):
            if any(
                row.get(key) not in (None, "")
                for key in ("lldp_local_interface", "lldp_neighbor", "neighbor_interface", "neighbor_mac")
            ):
                lldp_rows.append({**row, "source": row.get("lldp_source") or "resource_current"})
        for table in ("ac_fit_ap_optical_history", "ap_optical_history"):
            optical_rows.extend(
                _normalize_optical(row, source_table=table) for row in _rows(conn, table)
            )
        optical_rows.extend(
            {**row, "source": row.get("source") or "optical_current"}
            for row in _rows(conn, "ac_fit_ap_optical")
        )

    store = HistoryStore(db_path, site_id=site_id)
    lldp_rows.extend(store.query_events(kind="fit_ap_lldp", limit=10_000_000))
    optical_rows.extend(store.query_events(kind="fit_ap_optical", limit=10_000_000))
    return lldp_rows, optical_rows


def _ordered(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (_row_time(row), _text(row.get("event_id")), int(row.get("id") or 0)),
    )


def _plan_lldp(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current: dict[str, str] = {}
    history: Counter[str] = Counter()
    invalid = 0
    for row in _ordered(rows):
        try:
            projection = build_lldp_projection(row, source_revision=_source_revision(row), fallback_time=_row_time(row))
        except (TypeError, ValueError):
            invalid += 1
            continue
        key = str(projection["resource_key"])
        fingerprint = str(projection["state_fingerprint"])
        if key in current and current[key] != fingerprint:
            history[key] += 1
        current[key] = fingerprint
    return {
        "source_rows": len(rows),
        "invalid_rows": invalid,
        "current_rows": len(current),
        "true_change_events": sum(history.values()),
        "retained_history_rows": sum(min(value, 10) for value in history.values()),
        "max_history_per_ap": max(history.values(), default=0),
    }


def _plan_optical(rows: list[dict[str, Any]]) -> dict[str, Any]:
    current: dict[tuple[str, str], str] = {}
    history: Counter[tuple[str, str]] = Counter()
    issue_aps: set[str] = set()
    skipped = 0
    for row in _ordered(rows):
        try:
            identity = optical_ap_identity(row)
        except ValueError:
            skipped += 1
            continue
        for side in ("AP", "SWITCH"):
            projection = build_optical_projection(row, site_id="preview", side=side, now=_row_time(row))
            if projection is None:
                if side == "AP":
                    skipped += 1
                continue
            key = (identity, side)
            fingerprint = str(projection["state_fingerprint"])
            if key in current and current[key] != fingerprint:
                history[key] += 1
            current[key] = fingerprint
            if str(projection.get("status") or "") in {"abnormal", "alarm", "link_abnormal", "link_down", "no_light", "notice", "warning"}:
                issue_aps.add(identity)
    return {
        "source_rows": len(rows),
        "skipped_rows": skipped,
        "current_rows": len(current),
        "current_ap_rows": sum(1 for _identity, side in current if side == "AP"),
        "current_switch_rows": sum(1 for _identity, side in current if side == "SWITCH"),
        "true_change_events": sum(history.values()),
        "retained_history_rows": sum(min(value, 10) for value in history.values()),
        "max_history_per_ap_side": max(history.values(), default=0),
        "aps_with_abnormal_observation": len(issue_aps),
    }


def _backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    for stale in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
        if stale.exists():
            stale.unlink()
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _clear_bounded_targets(conn: sqlite3.Connection) -> None:
    for table in (
        "fit_ap_lldp_current",
        "fit_ap_lldp_history",
        "optical_current",
        "optical_history",
        "ap_optical_treatment",
    ):
        if _table_exists(conn, table):
            conn.execute(f'DELETE FROM "{table}"')
    for table in (
        "ac_fit_ap_lldp_history",
        "ap_lldp_history",
        "ac_fit_ap_optical_history",
        "ap_optical_history",
    ):
        if _table_exists(conn, table):
            conn.execute(f'DELETE FROM "{table}"')
    if _table_exists(conn, "history_outbox"):
        conn.execute(
            "DELETE FROM history_outbox WHERE kind IN ('fit_ap_lldp', 'fit_ap_optical')"
        )
    if _table_exists(conn, "history_state"):
        conn.execute(
            "DELETE FROM history_state WHERE kind IN ('fit_ap_lldp', 'fit_ap_optical')"
        )
    conn.execute(
        "INSERT INTO fit_ap_lldp_retention_meta(key,value) VALUES('authority','bounded_v1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )
    conn.execute(
        "INSERT INTO optical_retention_meta(key,value) VALUES('authority','bounded_v1') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def _replay_candidate(
    candidate_db: Path,
    site_id: str,
    lldp_rows: list[dict[str, Any]],
    optical_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    database = Database(candidate_db)
    database.initialize()
    with database.connect() as conn:
        _clear_bounded_targets(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        for index, row in enumerate(_ordered(lldp_rows), 1):
            try:
                upsert_lldp_current_and_history(
                    conn,
                    row,
                    source_revision=_source_revision(row),
                    now=_row_time(row),
                )
            except (TypeError, ValueError, sqlite3.Error):
                continue
            if index % 5000 == 0:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
        for index, row in enumerate(_ordered(optical_rows), 1):
            timestamp = _row_time(row)
            try:
                ap_projection = upsert_optical_current_and_history(
                    conn, row, site_id=site_id, side="AP", now=timestamp
                )
                if ap_projection is not None:
                    update_ap_optical_treatment(
                        conn,
                        site_id=site_id,
                        ap_identity=str(ap_projection["ap_identity"]),
                        source_row=row,
                        now=timestamp,
                    )
                switch_projection = upsert_optical_current_and_history(
                    conn, row, site_id=site_id, side="SWITCH", now=timestamp
                )
                if switch_projection is not None:
                    update_ap_optical_treatment(
                        conn,
                        site_id=site_id,
                        ap_identity=str(switch_projection["ap_identity"]),
                        source_row=row,
                        now=timestamp,
                    )
            except (TypeError, ValueError, sqlite3.Error):
                continue
            if index % 5000 == 0:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
        conn.commit()
    conn.close()
    _vacuum_database(candidate_db)
    return _candidate_verification(candidate_db, site_id)


def _vacuum_database(path: Path) -> None:
    vacuum_path = path.with_name(f"{path.stem}.vacuum{path.suffix}")
    if vacuum_path.exists():
        vacuum_path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.execute("VACUUM INTO ?", (str(vacuum_path),))
    finally:
        conn.close()
    os.replace(vacuum_path, path)
    for sidecar in (Path(f"{path}-wal"), Path(f"{path}-shm")):
        if sidecar.exists():
            sidecar.unlink()


def _candidate_verification(path: Path, site_id: str) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        result: dict[str, Any] = {"quick_check": quick_check}
        for table in (
            "fit_ap_lldp_current",
            "fit_ap_lldp_history",
            "optical_current",
            "optical_history",
            "ap_optical_treatment",
            "ac_fit_ap_lldp_history",
            "ap_lldp_history",
            "ac_fit_ap_optical_history",
            "ap_optical_history",
        ):
            result[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        result["lldp_max_history_per_ap"] = int(
            conn.execute(
                "SELECT COALESCE(MAX(total),0) FROM (SELECT resource_key,COUNT(*) total FROM fit_ap_lldp_history GROUP BY resource_key)"
            ).fetchone()[0]
        )
        result["optical_max_history_per_side"] = int(
            conn.execute(
                "SELECT COALESCE(MAX(total),0) FROM (SELECT site_id,ap_identity,side,COUNT(*) total FROM optical_history GROUP BY site_id,ap_identity,side)"
            ).fetchone()[0]
        )
        result["treatment_duplicate_groups"] = int(
            conn.execute(
                "SELECT COUNT(*) FROM (SELECT site_id,ap_identity,COUNT(*) total FROM ap_optical_treatment GROUP BY site_id,ap_identity HAVING total>1)"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(paths: Iterable[Path]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in paths:
        if path.is_file():
            stat = path.stat()
            result[str(path)] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _sha256(path),
            }
    return result


def _table_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        tables = [
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if str(row[0]) not in TARGET_PRIMARY_TABLES
        ]
        return {table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in sorted(tables)}


def _compact_history_candidate(history_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"shards": []}
    catalog_path = history_root / "catalog.db"
    for shard in sorted(history_root.glob("devices-*.db")):
        before: Counter[str] = Counter()
        conn = sqlite3.connect(shard)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            if _table_exists(conn, "history_events"):
                before.update({str(row[0]): int(row[1]) for row in conn.execute("SELECT kind,COUNT(*) FROM history_events GROUP BY kind")})
                conn.execute("DELETE FROM history_events WHERE kind IN (?,?)", tuple(TARGET_HISTORY_KINDS))
            if _table_exists(conn, "history_events_v2"):
                before.update({str(row[0]): int(row[1]) for row in conn.execute("SELECT k.name,COUNT(*) FROM history_events_v2 e JOIN history_kinds_v2 k ON k.kind_id=e.kind_id GROUP BY k.name")})
                conn.execute("DELETE FROM history_event_provenance_v2 WHERE event_id IN (SELECT e.event_id FROM history_events_v2 e JOIN history_kinds_v2 k ON k.kind_id=e.kind_id WHERE k.name IN (?,?))", tuple(TARGET_HISTORY_KINDS))
                conn.execute("DELETE FROM history_events_v2 WHERE kind_id IN (SELECT kind_id FROM history_kinds_v2 WHERE name IN (?,?))", tuple(TARGET_HISTORY_KINDS))
            conn.commit()
        finally:
            conn.close()
        _vacuum_database(shard)
        result["shards"].append({"path": str(shard), "before_kind_counts": dict(before), "after_size": shard.stat().st_size})
    if catalog_path.is_file():
        conn = sqlite3.connect(catalog_path)
        try:
            catalog_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(history_catalog)")
            }
            for shard in sorted(history_root.glob("devices-*.db")):
                row_count = 0
                with sqlite3.connect(f"file:{shard.resolve()}?mode=ro", uri=True) as shard_conn:
                    if _table_exists(shard_conn, "history_events"):
                        row_count += int(shard_conn.execute("SELECT COUNT(*) FROM history_events").fetchone()[0])
                    if _table_exists(shard_conn, "history_events_v2"):
                        row_count += int(shard_conn.execute("SELECT COUNT(*) FROM history_events_v2").fetchone()[0])
                assignments = ["row_count=?"]
                values: list[object] = [row_count]
                if "size_bytes" in catalog_columns:
                    assignments.append("size_bytes=?")
                    values.append(shard.stat().st_size)
                if "sha256" in catalog_columns:
                    assignments.append("sha256=?")
                    values.append(_sha256(shard))
                values.append(shard.name)
                conn.execute(
                    f"UPDATE history_catalog SET {', '.join(assignments)} WHERE relative_path=?",
                    values,
                )
            conn.commit()
        finally:
            conn.close()
        _vacuum_database(catalog_path)
    return result


def _resolve_data_root(value: str) -> Path:
    path = Path(value).resolve()
    if path.name != "NetConsoleData-dev" or not path.is_dir():
        raise ValueError("data_root must be an existing directory named NetConsoleData-dev")
    return path


def _active_sites(data_root: Path, selected: set[str] | None) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for db in sorted(data_root.glob("sites/*/db/devices.db")):
        site_id = db.parent.parent.name
        if selected and site_id not in selected:
            continue
        result.append((site_id, db))
    return result


def migrate(
    *,
    data_root: Path,
    output: Path,
    candidate_root: Path,
    selected_sites: set[str] | None = None,
    apply: bool = False,
    cutover: bool = False,
) -> dict[str, Any]:
    data_root = _resolve_data_root(str(data_root))
    sites = _active_sites(data_root, selected_sites)
    if not sites:
        raise ValueError("no active site database found below data_root/sites/*/db/devices.db")
    candidate_root = candidate_root.resolve()
    candidate_root.mkdir(parents=True, exist_ok=True) if apply else None
    report: dict[str, Any] = {
        "generated_at": _now(),
        "mode": "cutover" if cutover else "apply" if apply else "dry_run",
        "data_root": str(data_root),
        "candidate_root": str(candidate_root),
        "production_data_touched": False,
        "sites": [],
    }
    for site_id, db_path in sites:
        history_root = db_path.parent / "history"
        manifest_paths = [db_path, history_root / "catalog.db", *sorted(history_root.glob("devices-*.db"))]
        before_manifest = _manifest(manifest_paths)
        lldp_rows, optical_rows = _load_source_rows(db_path, site_id)
        site_report: dict[str, Any] = {
            "site_id": site_id,
            "source_database": str(db_path),
            "source_manifest_before": before_manifest,
            "lldp": _plan_lldp(lldp_rows),
            "optical": _plan_optical(optical_rows),
            "source_table_counts": _table_counts(db_path),
        }
        if apply:
            site_candidate = candidate_root / "sites" / site_id / "db"
            site_candidate.mkdir(parents=True, exist_ok=True)
            candidate_db = site_candidate / "devices.db"
            _backup_database(db_path, candidate_db)
            candidate_history = site_candidate / "history"
            if candidate_history.exists():
                shutil.rmtree(candidate_history)
            if history_root.is_dir():
                shutil.copytree(history_root, candidate_history)
                lock_path = candidate_history / ".history-append.lock"
                if lock_path.exists():
                    lock_path.unlink()
            candidate_verify = _replay_candidate(candidate_db, site_id, lldp_rows, optical_rows)
            compact_verify = _compact_history_candidate(candidate_history) if candidate_history.is_dir() else {"shards": []}
            site_report["candidate_database"] = str(candidate_db)
            site_report["candidate_verification"] = candidate_verify
            site_report["history_compaction"] = compact_verify
            site_report["candidate_table_counts"] = _table_counts(candidate_db)
            site_report["source_manifest_after_read"] = _manifest(manifest_paths)
            if site_report["source_manifest_before"] != site_report["source_manifest_after_read"]:
                raise RuntimeError(f"source changed during migration read: {site_id}")
        report["sites"].append(site_report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if cutover:
        if not apply:
            raise ValueError("cutover requires apply")
        _cutover_candidates(data_root, candidate_root, report)
    return report


def _cutover_candidates(data_root: Path, candidate_root: Path, report: dict[str, Any]) -> None:
    rollback_root = Path(r"D:\study\backup\NetConsole") / f"lldp-optical-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    moved: list[tuple[Path, Path]] = []
    try:
        for site in report["sites"]:
            site_id = str(site["site_id"])
            source_db = data_root / "sites" / site_id / "db" / "devices.db"
            candidate_db = candidate_root / "sites" / site_id / "db" / "devices.db"
            if not candidate_db.is_file():
                raise RuntimeError(f"missing candidate database: {candidate_db}")
            source_history = source_db.parent / "history"
            candidate_history = candidate_db.parent / "history"
            rollback_site = rollback_root / "sites" / site_id / "db"
            rollback_site.mkdir(parents=True, exist_ok=True)
            rollback_db = rollback_site / "devices.db"
            for suffix in ("-wal", "-shm"):
                source_sidecar = Path(f"{source_db}{suffix}")
                if source_sidecar.exists():
                    rollback_sidecar = Path(f"{rollback_db}{suffix}")
                    os.replace(source_sidecar, rollback_sidecar)
                    moved.append((rollback_sidecar, source_sidecar))
            os.replace(source_db, rollback_db)
            moved.append((rollback_db, source_db))
            os.replace(candidate_db, source_db)
            if source_history.exists():
                rollback_history = rollback_site / "history"
                os.replace(source_history, rollback_history)
                moved.append((rollback_history, source_history))
            if candidate_history.exists():
                os.replace(candidate_history, source_history)
        report["cutover"] = {"status": "completed", "rollback_root": str(rollback_root)}
    except Exception:
        for rollback, source in reversed(moved):
            if source.exists():
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            os.replace(rollback, source)
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DEV-only bounded LLDP/optical retention migration")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", default="LLDP_RETENTION_MIGRATION_PREVIEW.json")
    parser.add_argument("--candidate-root", default=r"D:\study\diagnostic\NetConsole\lldp-optical-migration")
    parser.add_argument("--site", action="append", dest="sites")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cutover", action="store_true")
    parser.add_argument("--cutover-only", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.cutover_only:
        if args.cutover or args.apply:
            raise ValueError("cutover-only cannot be combined with apply or cutover")
        data_root = _resolve_data_root(args.data_root)
        output_path = Path(args.output)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        candidate_root = Path(args.candidate_root).resolve()
        for site in report.get("sites", []):
            site_id = str(site["site_id"])
            source_db = data_root / "sites" / site_id / "db" / "devices.db"
            source_history = source_db.parent / "history"
            source_manifest = _manifest(
                [source_db, source_history / "catalog.db", *sorted(source_history.glob("devices-*.db"))]
            )
            if source_manifest != site.get("source_manifest_after_read"):
                raise RuntimeError(f"source changed after candidate build: {site_id}")
            candidate_db = candidate_root / "sites" / site_id / "db" / "devices.db"
            actual = _candidate_verification(candidate_db, site_id)
            if actual["quick_check"] != "ok" or actual["lldp_max_history_per_ap"] > 10 or actual["optical_max_history_per_side"] > 10 or actual["treatment_duplicate_groups"] != 0:
                raise RuntimeError(f"candidate gate failed before cutover: {site_id}: {actual}")
            site["candidate_verification_before_cutover"] = actual
        report["mode"] = "cutover"
        _cutover_candidates(data_root, candidate_root, report)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"mode": report["mode"], "sites": len(report["sites"]), "output": str(output_path.resolve())}, ensure_ascii=False))
        return 0
    report = migrate(
        data_root=Path(args.data_root),
        output=Path(args.output),
        candidate_root=Path(args.candidate_root),
        selected_sites=set(args.sites or []),
        apply=bool(args.apply or args.cutover),
        cutover=bool(args.cutover),
    )
    print(json.dumps({"mode": report["mode"], "sites": len(report["sites"]), "output": str(Path(args.output).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
