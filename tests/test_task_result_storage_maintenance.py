from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from scripts.maintenance.compact_task_result_storage import compact_database
from scripts.maintenance.migrate_task_result_blobs import migrate_database
from netconsole.repositories.task_result_blob_repository import read_blob


def _legacy_result_database(path: Path) -> tuple[str, str, str]:
    result = {"status": "SUCCESS", "rows": ["payload"] * 4000}
    canonical = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result_id = "tr-" + hashlib.sha256(
        f"task-legacy\0finished\0{digest}".encode("utf-8")
    ).hexdigest()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE task_results ("
            "result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
            "terminal_event_type TEXT NOT NULL, canonical_json TEXT NOT NULL, "
            "sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, "
            "schema_version INTEGER NOT NULL, created_time TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO task_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result_id,
                "task-legacy",
                "finished",
                canonical,
                digest,
                len(canonical.encode("utf-8")),
                1,
                "2026-08-27T01:00:00Z",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return result_id, canonical, digest


def test_migrate_then_compact_preserves_result_and_retires_body_projection(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    result_id, canonical, digest = _legacy_result_database(database)

    migrated = migrate_database(
        "demo",
        database,
        apply=True,
        limit=None,
        batch_size=10,
        verify=True,
        resume=False,
    )
    assert migrated["processed_rows"] == 1
    assert migrated["written_blobs"] == 1

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM task_result_blobs"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT canonical_json FROM task_results WHERE result_id=?",
            (result_id,),
        ).fetchone()[0] == canonical
    finally:
        connection.close()

    compacted = compact_database(
        "demo",
        database,
        staging_dir=tmp_path / "staging",
        apply=True,
    )
    assert compacted["status"] == "PASS"
    assert compacted["replaced"] is True
    assert compacted["gates"]["task_result_parity"] is True

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT canonical_json, content_sha256, blob_ready FROM task_results "
            "WHERE result_id=?",
            (result_id,),
        ).fetchone()
        assert tuple(row) == ("", digest, 1)
        blob = read_blob(
            connection,
            content_sha256=digest,
            expected_bytes=len(canonical.encode("utf-8")),
        )
    finally:
        connection.close()
    assert blob == canonical


def test_migrate_repairs_authority_metadata_when_physical_schema_is_legacy(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    result_id, _, digest = _legacy_result_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE task_snapshots (task_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO task_snapshots(task_id) VALUES (?)", ("task-legacy",))
        connection.execute(
            "CREATE TABLE task_result_storage_rollout ("
            "singleton_id INTEGER PRIMARY KEY, state TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO task_result_storage_rollout(singleton_id,state) VALUES (1, 'RESULT_REF_AUTHORITY')"
        )
        connection.commit()

    migrated = migrate_database(
        "demo",
        database,
        apply=True,
        limit=None,
        batch_size=10,
        verify=True,
        resume=False,
    )

    assert migrated["status"] == "PASS"
    assert migrated["authority"]["rollout_state"] == "RESULT_REF_AUTHORITY"
    assert migrated["authority"]["physical_schema_ready"] is True
    assert migrated["authority"]["missing_blob"] == 0
    assert migrated["authority"]["hash_mismatch"] == 0
    assert migrated["authority"]["task_result_parent_orphans"] == 0
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT content_sha256, blob_ready FROM task_results WHERE result_id=?",
            (result_id,),
        ).fetchone()
        assert row == (digest, 1)
        assert connection.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0] == 1
