from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path

import pytest

from scripts.maintenance.tasks_db_compaction import (
    _apply_result_projection_cleanup,
    _connect_read_only,
    _quick_check,
    _task_db_audit,
    _task_semantics,
)


def _make_tasks_db(path: Path, *, include_artifact_finalized: bool = False) -> None:
    result = {"success": True, "summary": "same canonical result", "artifact_id": "a-1"}
    snapshot_result = {**result, "sha256": "file-sha256", "size_bytes": 12} if include_artifact_finalized else result
    encoded = json.dumps(snapshot_result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE task_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE task_result_storage_rollout (
                singleton_id INTEGER PRIMARY KEY, state TEXT NOT NULL,
                revision INTEGER NOT NULL, updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL, reason TEXT NOT NULL, schema_version INTEGER NOT NULL
            );
            CREATE TABLE task_result_storage_rollout_audit (
                revision INTEGER PRIMARY KEY, from_state TEXT NOT NULL,
                to_state TEXT NOT NULL, changed_at TEXT NOT NULL,
                changed_by TEXT NOT NULL, reason TEXT NOT NULL, schema_version INTEGER NOT NULL
            );
            CREATE TABLE task_snapshots (
                task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL, task_name TEXT NOT NULL,
                created_time TEXT NOT NULL, started_time TEXT NOT NULL, finished_time TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL, result_json TEXT NOT NULL,
                result_id TEXT NOT NULL, result_hash TEXT NOT NULL,
                result_summary_json TEXT NOT NULL, error_message TEXT NOT NULL,
                updated_time TEXT NOT NULL, resource_keys_json TEXT NOT NULL
            );
            CREATE TABLE task_results (
                result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                terminal_event_type TEXT NOT NULL, canonical_json TEXT NOT NULL,
                sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL,
                schema_version INTEGER NOT NULL, created_time TEXT NOT NULL
            );
            CREATE TABLE task_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL, event_type TEXT NOT NULL, event_time TEXT NOT NULL,
                source TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            INSERT INTO task_schema_meta VALUES ('schema_version', '4');
            INSERT INTO task_result_storage_rollout VALUES
                (1, 'LEGACY_DUAL_FULL', 1, '2026-08-27T00:00:00Z', 'test', 'test', 4);
            """
        )
        connection.execute(
            "INSERT INTO task_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "task-1", "export_report", "Export", "2026-08-27T00:00:00Z",
                "2026-08-27T00:00:01Z", "2026-08-27T00:00:02Z", "COMPLETED", 100,
                encoded, "", "", "{}", "", "2026-08-27T00:00:02Z", "[]",
            ),
        )
        connection.execute(
            "INSERT INTO task_events(event_id, task_id, event_type, event_time, source, payload_json) "
            "VALUES (?, ?, 'finished', ?, 'test', ?)",
            (
                "event-1", "task-1", "2026-08-27T00:00:02Z",
                json.dumps({"result": result, "message": "done"}, ensure_ascii=False),
            ),
        )
        if include_artifact_finalized:
            finalized = {**result, "sha256": "file-sha256", "size_bytes": 12}
            connection.execute(
                "INSERT INTO task_events(event_id, task_id, event_type, event_time, source, payload_json) "
                "VALUES (?, ?, 'artifact_finalized', ?, 'test', ?)",
                (
                    "event-2", "task-1", "2026-08-27T00:00:03Z",
                    json.dumps({"result": finalized}, ensure_ascii=False),
                ),
            )
        connection.commit()


def test_audit_reports_full_projection_duplicate_and_payload_stats(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    _make_tasks_db(database)

    report = _task_db_audit(database, site="test")

    assert report["quick_check"] == "ok"
    assert report["task_storage"]["semantics"]["task_rows"] == 1
    assert report["task_storage"]["semantics"]["event_rows"] == 1
    assert report["task_storage"]["duplication"]["duplicate_payload_rows"] == 1
    result_fields = {
        (item["table"], item["column"]): item
        for item in report["payload_fields"]
    }
    assert result_fields[("task_snapshots", "result_json")]["total_payload_bytes"] > 0
    assert result_fields[("task_events", "payload_json")]["total_payload_bytes"] > 0


def test_apply_preserves_task_and_event_rows_and_removes_full_copies(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    _make_tasks_db(database)
    before = _task_db_audit(database, site="test")

    mutation = _apply_result_projection_cleanup(database)
    after = _task_db_audit(database, site="test")

    assert mutation["result_rows_created"] == 1
    assert mutation["snapshot_full_results_removed"] == 1
    assert mutation["event_full_results_removed"] == 1
    assert mutation["obsolete_snapshot_rows_removed"] == 0
    assert before["task_storage"]["semantics"]["task_list_digest"] == after["task_storage"]["semantics"]["task_list_digest"]
    assert before["task_storage"]["semantics"]["task_detail_digest"] == after["task_storage"]["semantics"]["task_detail_digest"]
    assert _quick_check(database)["pass"]
    with sqlite3.connect(database) as connection:
        snapshot = connection.execute(
            "SELECT result_json, result_id FROM task_snapshots WHERE task_id='task-1'"
        ).fetchone()
        event = connection.execute(
            "SELECT payload_json FROM task_events WHERE event_id='event-1'"
        ).fetchone()
        assert snapshot[0] == "{}"
        assert snapshot[1]
        assert "result" not in json.loads(event[0])
        assert connection.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1


def test_apply_path_is_not_allowed_outside_dev_root(tmp_path: Path) -> None:
    from scripts.maintenance.tasks_db_compaction import DIAGNOSTIC_ROOT, run

    with pytest.raises(ValueError, match="DEV-only"):
        run(
            mode="apply",
            data_root=tmp_path,
            output_dir=DIAGNOSTIC_ROOT / "test-apply-guard",
        )


def test_artifact_finalized_is_preferred_without_erasing_prior_event(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    _make_tasks_db(database, include_artifact_finalized=True)

    mutation = _apply_result_projection_cleanup(database)

    assert mutation["conflict_tasks"] == []
    assert mutation["event_full_results_removed"] == 1
    with sqlite3.connect(database) as connection:
        events = {
            row[0]: json.loads(row[1])
            for row in connection.execute(
                "SELECT event_type, payload_json FROM task_events ORDER BY sequence"
            )
        }
        assert "result" in events["finished"]
        assert "result" not in events["artifact_finalized"]


def test_empty_canonical_result_reference_is_preserved(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    _make_tasks_db(database)
    empty_hash = hashlib.sha256(b"{}").hexdigest()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO task_snapshots "
            "(task_id, task_type, task_name, created_time, started_time, finished_time, "
            "status, progress, result_json, result_id, result_hash, result_summary_json, "
            "error_message, updated_time, resource_keys_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cancelled-empty", "export", "Export", "2026-08-27T00:00:00Z", "",
                "2026-08-27T00:00:01Z", "CANCELLED", 0, "{}", "tr-empty", empty_hash,
                "{}", "", "2026-08-27T00:00:01Z", "[]",
            ),
        )
        connection.execute(
            "INSERT INTO task_results "
            "(result_id, task_id, terminal_event_type, canonical_json, sha256, byte_size, schema_version, created_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "tr-empty", "cancelled-empty", "cancelled", "{}", empty_hash, 2, 1,
                "2026-08-27T00:00:01Z",
            ),
        )

    before = _task_semantics(_connect_read_only(database))
    mutation = _apply_result_projection_cleanup(database)
    after = _task_semantics(_connect_read_only(database))

    assert mutation["invalid_snapshot_refs_removed"] == 0
    assert before["task_list_digest"] == after["task_list_digest"]
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT result_id, result_hash FROM task_snapshots WHERE task_id=?",
            ("cancelled-empty",),
        ).fetchone()
        assert row[0].startswith("tr-")
        assert row[1] == empty_hash
