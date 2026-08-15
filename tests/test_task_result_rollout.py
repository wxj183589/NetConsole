from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_result_rollout import TaskResultStorageState
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutError,
    TaskResultRolloutService,
)
from netconsole.services.site_storage import SiteRecord, SiteRegistryRepository
from scripts.maintenance.manage_task_result_rollout import main as rollout_cli_main


def _terminal(task_id: str) -> tuple[TaskSnapshot, TaskEvent]:
    result = {"task": task_id, "rows": 3, "status": "ok"}
    timestamp = "2026-08-16T03:00:00Z"
    return (
        TaskSnapshot(
            task_id=task_id,
            task_type="rollout_test",
            task_name="Rollout Test",
            status=TaskState.COMPLETED,
            created_time=timestamp,
            finished_time=timestamp,
            updated_time=timestamp,
            progress=100,
            result=result,
        ),
        TaskEvent(
            event_id=f"finished-{task_id}",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="test",
            payload={"message": "done", "result": result},
        ),
    )


def _enable(service: TaskResultRolloutService) -> None:
    service.enable_dual_write(
        expected_revision=1,
        reason="isolated rollout test",
        updated_by="pytest",
    )


def test_new_database_defaults_to_legacy_dual_full(tmp_path: Path) -> None:
    service = TaskResultRolloutService(tmp_path / "tasks.db")
    status = service.status()

    assert status == {
        "schema_version": 4,
        "task_result_storage_state": "LEGACY_DUAL_FULL",
        "revision": 1,
        "updated_at": status["updated_at"],
        "task_results_rows": 0,
        "dual_write_active": False,
        "ref_authority_active": False,
    }
    assert str(status["updated_at"])


def test_old_database_upgrade_adds_capability_but_keeps_rollout_off(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE task_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO task_schema_meta VALUES ('schema_version', '3');
            CREATE TABLE task_snapshots (
                task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL, task_name TEXT NOT NULL,
                created_time TEXT NOT NULL, started_time TEXT NOT NULL DEFAULT '',
                finished_time TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT '',
                current INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '',
                device TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT '',
                result_path TEXT NOT NULL DEFAULT '', error_message TEXT NOT NULL DEFAULT '',
                result_json TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL DEFAULT 'local',
                site_name TEXT NOT NULL DEFAULT 'demo', owner_pid INTEGER NOT NULL DEFAULT 0,
                resource_keys_json TEXT NOT NULL DEFAULT '[]', updated_time TEXT NOT NULL
            );
            CREATE TABLE task_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE, task_id TEXT NOT NULL,
                event_type TEXT NOT NULL, event_time TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'service',
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )

    repository = TaskRepository(path)
    status = repository.task_result_rollout_status()
    snapshot, event = _terminal("upgraded-task")
    assert repository.record(snapshot, event)

    with sqlite3.connect(path) as conn:
        schema_version = conn.execute(
            "SELECT value FROM task_schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        result_count = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
    assert schema_version == "4"
    assert result_count == 0
    assert status.state == TaskResultStorageState.LEGACY_DUAL_FULL
    assert repository.get("upgraded-task").result == snapshot.result


@pytest.mark.parametrize("count", [10, 100, 1_000])
def test_default_terminal_tasks_never_write_task_results(
    tmp_path: Path,
    count: int,
) -> None:
    path = tmp_path / f"tasks-{count}.db"
    repository = TaskRepository(path)
    for index in range(count):
        snapshot, event = _terminal(f"task-{index:04d}")
        assert repository.record(snapshot, event)

    with sqlite3.connect(path) as conn:
        result_count = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM task_snapshots"
        ).fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        snapshot_result = json.loads(
            conn.execute(
                "SELECT result_json FROM task_snapshots ORDER BY task_id LIMIT 1"
            ).fetchone()[0]
        )
        event_result = json.loads(
            conn.execute(
                "SELECT payload_json FROM task_events ORDER BY sequence LIMIT 1"
            ).fetchone()[0]
        )["result"]
    assert result_count == 0
    assert snapshot_count == event_count == count
    assert snapshot_result == event_result


def test_explicit_dual_write_is_persisted_revision_safe_and_audited(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    service = TaskResultRolloutService(path)
    _enable(service)
    restarted = TaskResultRolloutService(path)
    status = restarted.status()
    assert status["task_result_storage_state"] == "TASK_RESULTS_DUAL_WRITE"
    assert status["revision"] == 2

    snapshot, event = _terminal("dual-task")
    assert restarted.repository.record(snapshot, event)
    assert not restarted.repository.record(snapshot, event)
    persisted = restarted.repository.get("dual-task")
    assert persisted is not None and persisted.result_id
    assert restarted.repository.task_result_count() == 1
    authority = restarted.repository.get_result(persisted.result_id)
    assert authority is not None and authority["result"] == snapshot.result
    assert restarted.repository.list_task_result_rollout_audit() == [
        {
            "revision": 2,
            "from_state": "LEGACY_DUAL_FULL",
            "to_state": "TASK_RESULTS_DUAL_WRITE",
            "changed_at": status["updated_at"],
            "changed_by": "pytest",
            "reason": "isolated rollout test",
            "schema_version": 4,
        }
    ]

    with pytest.raises(TaskResultRolloutError) as stale:
        restarted.disable_dual_write(
            expected_revision=1,
            reason="stale rollback",
            updated_by="pytest",
        )
    assert stale.value.code == "TASK_RESULT_ROLLOUT_REVISION_CONFLICT"


def test_dual_write_rollback_keeps_existing_results_and_stops_future_writes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.db"
    service = TaskResultRolloutService(path)
    _enable(service)
    first_snapshot, first_event = _terminal("before-rollback")
    assert service.repository.record(first_snapshot, first_event)
    first = service.repository.get("before-rollback")
    assert first is not None and first.result_id

    service.disable_dual_write(
        expected_revision=2,
        reason="stop compatibility writes",
        updated_by="pytest",
    )
    second_snapshot, second_event = _terminal("after-rollback")
    assert service.repository.record(second_snapshot, second_event)

    assert service.repository.task_result_count() == 1
    assert service.repository.get_result(first.result_id)["result"] == first_snapshot.result
    assert service.repository.get("after-rollback").result_id == ""
    assert service.status()["revision"] == 3


@pytest.mark.parametrize(
    ("target", "code"),
    [
        (
            TaskResultStorageState.TASK_RESULTS_VERIFIED,
            "TASK_RESULT_VERIFIED_APPLY_DISABLED",
        ),
        (
            TaskResultStorageState.RESULT_REF_AUTHORITY,
            "TASK_RESULT_REF_AUTHORITY_DISABLED",
        ),
    ],
)
def test_future_rollout_states_cannot_be_applied(
    tmp_path: Path,
    target: TaskResultStorageState,
    code: str,
) -> None:
    service = TaskResultRolloutService(tmp_path / "tasks.db")
    with pytest.raises(TaskResultRolloutError) as blocked:
        service.transition(
            target,
            expected_revision=1,
            reason="must remain blocked",
            updated_by="pytest",
        )
    assert blocked.value.code == code
    assert service.status()["task_result_storage_state"] == "LEGACY_DUAL_FULL"


def test_default_websocket_terminal_payload_remains_full(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    service = TaskApplicationService(paths, site_name="demo", reconcile_on_start=False)
    service.create_external_task(
        task_id="default-live-result",
        task_type="agent_task",
        task_name="Default Live Result",
        source="agent",
    )
    stream = service.events.open_stream()
    result = {"status": "COMPLETED", "rows": 7}
    snapshot = service.record_external_event(
        "default-live-result",
        "finished",
        {"message": "done", "result": result},
        source="agent",
        event_id="default-live-finished",
        event_time="2026-08-16T03:00:00Z",
    )
    live = stream.get(timeout=1)
    stream.close()

    assert snapshot.result == result and snapshot.result_id == ""
    assert live["payload"]["result"] == result
    assert service.repository("demo").task_result_count() == 0


def test_rollout_cli_requires_explicit_apply_and_persists_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_root = tmp_path / "data"
    paths = PathResolver(app_root=tmp_path, data_root=data_root)
    site_root = paths.site_dir("demo")
    (site_root / "db").mkdir(parents=True)
    SiteRegistryRepository(paths).register(SiteRecord("demo", "Demo", site_root))

    common = ["--data-root", str(data_root), "--site-id", "demo"]
    assert rollout_cli_main(["status", *common]) == 0
    assert json.loads(capsys.readouterr().out)["task_result_storage_state"] == (
        "LEGACY_DUAL_FULL"
    )

    with pytest.raises(SystemExit, match="explicit --apply"):
        rollout_cli_main(
            [
                "enable-dual-write",
                *common,
                "--expected-revision",
                "1",
                "--reason",
                "controlled test rollout",
            ]
        )
    assert rollout_cli_main(
        [
            "enable-dual-write",
            *common,
            "--expected-revision",
            "1",
            "--reason",
            "controlled test rollout",
            "--apply",
        ]
    ) == 0
    enabled = json.loads(capsys.readouterr().out)
    assert enabled["task_result_storage_state"] == "TASK_RESULTS_DUAL_WRITE"
    assert enabled["revision"] == 2
