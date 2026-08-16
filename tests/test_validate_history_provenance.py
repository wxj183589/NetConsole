from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.services.history_store import HistoryStore
from scripts.maintenance.validate_history_provenance import (
    HistoryProvenanceValidationError,
    validate_history_provenance,
)


def test_read_only_audit_covers_devices_catalog_and_all_registered_shards(
    tmp_path: Path,
) -> None:
    devices, history_root, _store = _healthy_history(tmp_path)
    before = {path: _sha256(path) for path in _database_files(devices, history_root)}
    output = tmp_path / "reports" / "HISTORY_PROVENANCE_AUDIT.json"

    report = validate_history_provenance(
        devices_database=devices,
        history_root=history_root,
        output_path=output,
        development_root=tmp_path,
    )

    assert report["status"] == "PASS"
    assert report["mode"] == "READ_ONLY_AUDIT"
    assert report["backfill"] is None
    assert report["catalog_registered_shards"] == 2
    assert report["audited_shards"] == 2
    assert [item["role"] for item in report["databases"]] == [
        "devices",
        "catalog",
        "shard",
        "shard",
    ]
    for database in report["databases"]:
        assert database["quick_check"] == ["ok"]
        assert database["integrity_check"] == ["ok"]
        assert database["foreign_key_check"] == []
    for shard in (item for item in report["databases"] if item["role"] == "shard"):
        assert shard["event_counts"]["history_events_v2"] == 1
        assert shard["event_counts"]["legacy_events_v2"] == 1
        assert shard["provenance_count"] == 1
        assert shard["missing_provenance"] == 0
        assert shard["duplicate_source_identity_count"] == 0
        assert shard["provenance_without_rowid"] is True
        assert shard["unique_source_index_present"] is True
        assert shard["redundant_source_index_absent"] is True
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert before == {
        path: _sha256(path) for path in _database_files(devices, history_root)
    }


def test_apply_requires_guard_and_repairs_old_provenance_idempotently(
    tmp_path: Path,
) -> None:
    devices, history_root, _store = _healthy_history(tmp_path, months=("2026-08",))
    shard_path = history_root / "devices-2026-08.db"
    with connect_sqlite(shard_path, foreign_keys=True) as shard:
        shard.execute("DROP TABLE history_event_provenance_v2")
        shard.executescript(
            """
            CREATE TABLE history_event_provenance_v2 (
                event_id BLOB PRIMARY KEY,
                source_table TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                FOREIGN KEY(event_id) REFERENCES history_events_v2(event_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX idx_history_event_provenance_v2_source
                ON history_event_provenance_v2(source_table, source_id);
            CREATE UNIQUE INDEX ux_history_event_provenance_v2_source
                ON history_event_provenance_v2(source_table, source_id);
            """
        )
        shard.commit()

    with pytest.raises(
        HistoryProvenanceValidationError,
        match="requires --allow-development-root-only",
    ):
        validate_history_provenance(
            devices_database=devices,
            history_root=history_root,
            output_path=tmp_path / "unguarded.json",
            apply_backfill=True,
            development_root=tmp_path,
        )

    first = validate_history_provenance(
        devices_database=devices,
        history_root=history_root,
        output_path=tmp_path / "first.json",
        apply_backfill=True,
        allow_development_root_only=True,
        batch_size=1,
        development_root=tmp_path,
    )
    second = validate_history_provenance(
        devices_database=devices,
        history_root=history_root,
        output_path=tmp_path / "second.json",
        apply_backfill=True,
        allow_development_root_only=True,
        batch_size=1,
        development_root=tmp_path,
    )

    assert first["status"] == "PASS"
    assert first["backfill"]["backfilled"] == 1
    assert first["backfill"]["shards"][0]["provenance_storage_optimized"] is True
    assert second["status"] == "PASS"
    assert second["backfill"]["backfilled"] == 0
    assert second["backfill"]["shards"][0]["provenance_storage_optimized"] is False


def test_audit_reports_missing_and_duplicate_provenance(tmp_path: Path) -> None:
    devices, history_root, _store = _healthy_history(
        tmp_path, months=("2026-08",), events_per_month=2
    )
    shard_path = history_root / "devices-2026-08.db"
    with connect_sqlite(shard_path, foreign_keys=True) as shard:
        event_ids = [row[0] for row in shard.execute("SELECT event_id FROM history_events_v2")]
        shard.execute("DROP INDEX ux_history_event_provenance_v2_source")
        shard.execute("DELETE FROM history_event_provenance_v2")
        shard.executemany(
            "INSERT INTO history_event_provenance_v2(event_id, source_table, source_id) "
            "VALUES (?, 'device_facts_history', 900)",
            [(event_ids[0],), (event_ids[1],)],
        )
        shard.commit()

    report = validate_history_provenance(
        devices_database=devices,
        history_root=history_root,
        output_path=tmp_path / "failed-audit.json",
        development_root=tmp_path,
    )

    shard = next(item for item in report["databases"] if item["role"] == "shard")
    assert report["status"] == "FAIL"
    assert shard["missing_provenance"] == 0
    assert shard["duplicate_source_identity_count"] == 1
    assert shard["unique_source_index_present"] is False


def test_rejects_out_of_root_paths_and_existing_output(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    devices, history_root, _store = _healthy_history(outside, months=("2026-08",))
    allowed.mkdir()

    with pytest.raises(HistoryProvenanceValidationError, match="below D:/study"):
        validate_history_provenance(
            devices_database=devices,
            history_root=history_root,
            output_path=allowed / "audit.json",
            development_root=allowed,
        )

    devices, history_root, _store = _healthy_history(allowed, months=("2026-08",))
    output = allowed / "audit.json"
    output.write_text("protected", encoding="utf-8")
    with pytest.raises(HistoryProvenanceValidationError, match="refusing to overwrite"):
        validate_history_provenance(
            devices_database=devices,
            history_root=history_root,
            output_path=output,
            development_root=allowed,
        )
    assert output.read_text(encoding="utf-8") == "protected"


def _healthy_history(
    root: Path,
    *,
    months: tuple[str, ...] = ("2026-07", "2026-08"),
    events_per_month: int = 1,
) -> tuple[Path, Path, HistoryStore]:
    devices = root / "site" / "db" / "devices.db"
    devices.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(devices) as connection:
        connection.execute("CREATE TABLE device_current(id INTEGER PRIMARY KEY)")
    history_root = root / "site" / "history"
    store = HistoryStore(devices, site_id="test", history_root=history_root)
    source_id = 40
    for month in months:
        events = []
        for offset in range(events_per_month):
            source_id += 1
            collected_at = f"{month}-01T10:{offset:02d}:00"
            events.append(
                HistoryStore.legacy_migration_event(
                    "device_facts_history",
                    {
                        "id": source_id,
                        "device_uuid": f"device-{source_id}",
                        "model": "S6520",
                        "collected_at": collected_at,
                        "created_at": collected_at,
                    },
                )
            )
        assert store.copy_legacy_migration_events(events) == (
            events_per_month,
            events_per_month,
        )
    return devices, history_root, store


def _database_files(devices: Path, history_root: Path) -> list[Path]:
    return [devices, *sorted(history_root.glob("*.db"))]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
