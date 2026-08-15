from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from scripts.maintenance.profile_tasks_db import profile_tasks_database


def _snapshot(task_id: str, result: dict[str, object]) -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task_id,
        task_type="device_list_page",
        task_name="设备列表",
        status=TaskState.COMPLETED,
        created_time="2026-08-10T00:00:00Z",
        updated_time="2026-08-10T00:01:00Z",
        finished_time="2026-08-10T00:01:00Z",
        result=result,
        progress=100,
    )


def test_light_profile_reads_only_physical_and_schema_metadata(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    TaskRepository(database).save(_snapshot("task-1", {"items": [1, 2, 3]}))
    before = (database.stat().st_size, database.stat().st_mtime_ns)

    result = profile_tasks_database(database, deep=False)

    assert result["result"] == "PROFILE_LIGHT_COMPLETE"
    assert result["physical"]["file_size_bytes"] == before[0]
    assert result["schema"]["table_count"] >= 3
    assert "top_tables" not in result
    assert (database.stat().st_size, database.stat().st_mtime_ns) == before


def test_deep_profile_quantifies_duplicate_results_progress_and_orphans(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    repository = TaskRepository(database)
    result_payload = {"items": [{"name": "ap-1", "value": "x" * 1000}]}
    snapshot = _snapshot("task-1", result_payload)
    repository.save(snapshot)
    progress = {"current": 1, "total": 2, "message": "same"}
    assert repository.record(
        snapshot,
        TaskEvent("progress-1", "task-1", "progress", "2026-08-10T00:00:00Z", progress),
    )
    # Insert historical duplicate directly so the profiler measures legacy amplification,
    # independent of the new write-time sampling behavior.
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO task_events(event_id,task_id,event_type,event_time,source,payload_json) "
            "VALUES ('progress-2','task-1','progress','2026-08-10T00:00:01Z','worker',?)",
            ('{"current":1,"total":2,"message":"same"}',),
        )
        conn.execute(
            "INSERT INTO task_events(event_id,task_id,event_type,event_time,source,payload_json) "
            "VALUES ('finished-1','task-1','finished','2026-08-10T00:01:00Z','worker',?)",
            ('{"result":{"items":[{"value":"' + "x" * 1000 + '","name":"ap-1"}]}}',),
        )
        conn.commit()
    snapshot_database = tmp_path / "snapshot" / "tasks.db"
    snapshot_database.parent.mkdir()
    with sqlite3.connect(database) as source_conn, sqlite3.connect(snapshot_database) as target_conn:
        source_conn.backup(target_conn)
    before = (snapshot_database.stat().st_size, snapshot_database.stat().st_mtime_ns)

    result = profile_tasks_database(snapshot_database, deep=True)

    assert result["result"] == "PROFILE_COMPLETE"
    assert result["allocation"]["method"] in {
        "sqlite_dbstat",
        "logical_weight_normalized_fallback",
    }
    assert result["tasks"]["repeated_progress"]["repeated_rows"] == 1
    duplication = result["tasks"]["terminal_result_duplication"]
    assert duplication["semantically_identical_results"] == 1
    assert duplication["action_this_phase"] == "OBSERVE_ONLY"
    assert result["tasks"]["orphans"]["events_without_snapshot"] == 0
    assert result["recommendation"]["option"] == "D"
    assert result["retention"] == "NOT STARTED"
    assert (snapshot_database.stat().st_size, snapshot_database.stat().st_mtime_ns) == before
