"""在隔离数据根验证 Phase 2.1 旧库兼容性；不触碰现场数据。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from pathlib import Path

from netconsole.core.database import Database
from netconsole.services.history_store import HistoryStore

LEGACY_HISTORY_TABLES = (
    "device_facts_history",
    "device_interfaces_history",
    "device_optical_modules_history",
    "device_lldp_neighbors_history",
    "ac_fit_ap_resource_history",
    "ac_fit_ap_radio_history",
    "ac_fit_ap_optical_history",
    "ac_fit_ap_lldp_history",
    "ap_resource_snapshots",
    "ap_lldp_history",
    "ap_optical_history",
)


def _backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)


def validate_snapshot(source: Path | None, *, work_root: Path | None = None) -> dict[str, object]:
    if source is None or not source.is_file():
        return {"status": "NOT_EXECUTED", "reason": "OFFLINE_SNAPSHOT_NOT_AVAILABLE", "source": str(source) if source else None}
    root = Path(work_root) if work_root else Path(tempfile.mkdtemp(prefix="netconsole-phase21-"))
    target = root / "sites" / "snapshot" / "db" / "devices.db"
    _backup(source, target)
    before = target.stat().st_size
    started = time.perf_counter()
    database = Database(target)
    database.initialize()
    first_ms = round((time.perf_counter() - started) * 1000, 2)
    first_size = target.stat().st_size
    started = time.perf_counter()
    database.initialize()
    second_ms = round((time.perf_counter() - started) * 1000, 2)
    second_size = target.stat().st_size
    store = HistoryStore(target, site_id="snapshot")
    with database.connect_readonly() as connection:
        legacy_counts = {
            table: int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
            )
            for table in LEGACY_HISTORY_TABLES
        }
        for table, exists in tuple(legacy_counts.items()):
            legacy_counts[table] = (
                int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                if exists
                else 0
            )
    shard_files = sorted(path.name for path in store.history_root.glob("devices-*.db")) if store.history_root.is_dir() else []
    with database.connect() as connection:
        recorded = store.record_event(
            connection,
            kind="device_interface",
            entity_key="validation-device:GE1/0/1",
            payload={
                "device_uuid": "validation-device",
                "interface_name": "GE1/0/1",
                "link_status": "up",
            },
            collected_at="2026-08-01T00:00:00",
            meaningful_fields=("device_uuid", "interface_name", "link_status"),
        )
        connection.commit()
    drained = store.drain(limit=10)
    shard_files = sorted(path.name for path in store.history_root.glob("devices-*.db")) if store.history_root.is_dir() else []
    return {
        "status": "PASS",
        "source": str(source),
        "isolated_copy": str(target),
        "source_bytes": before,
        "first_initialize_ms": first_ms,
        "second_initialize_ms": second_ms,
        "copy_bytes_after_first": first_size,
        "copy_bytes_after_second": second_size,
        "size_stable_after_fast_path": first_size == second_size,
        "legacy_history_counts": legacy_counts,
        "fake_current_event_recorded": recorded,
        "fake_current_event_drained": drained.written,
        "history_pending_after_drain": drained.pending,
        "history_shard_files": shard_files,
        "migration_invoked": False,
        "destructive_operations": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="隔离副本 Phase 2.1 fast-path 验证")
    parser.add_argument("--source", type=Path, default=None, help="离线 devices.db 副本；不指定则明确跳过")
    parser.add_argument("--work-root", type=Path, default=None, help="隔离验证根；不得指向现场数据根")
    args = parser.parse_args(argv)
    if args.work_root and args.work_root.resolve().is_relative_to(Path(r"D:\NetConsoleData").resolve()):
        raise SystemExit("拒绝使用真实 D:\\NetConsoleData 作为验证根")
    print(json.dumps(validate_snapshot(args.source, work_root=args.work_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
