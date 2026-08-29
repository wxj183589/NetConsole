from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.repositories.history_store import TaskHistoryStore
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)
from scripts.maintenance.task_result_maintenance import (
    TaskResultMaintenanceService,
)
from scripts.maintenance.validate_database_functional_compatibility import (
    FunctionalCompatibilityError,
    OUTPUT_FILENAMES,
    _profile_history_evidence,
    validate_database_functional_compatibility,
)
from scripts.maintenance.finalize_functional_compatibility import MATRIX_DEFINITIONS


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_final_replace_history_evidence_is_post_replace_parity(tmp_path: Path) -> None:
    evidence = tmp_path / "POST_FINAL_REPLACE_PARITY-device_facts_history.json"
    evidence.write_text(
        json.dumps(
            {
                "source_table": "device_facts_history",
                "expected_count": 1,
                "actual_count": 1,
                "result": "PASS",
            }
        ),
        encoding="utf-8",
    )

    profile = _profile_history_evidence(tmp_path)

    assert profile["status"] == "PASS"
    assert profile["post_replace_parity_count"] == 1
    assert profile["migration_parity_count"] == 0


def _checkpoint_task_inputs(inputs: dict[str, Path]) -> None:
    for key in ("before_tasks", "after_tasks"):
        database = inputs[key]
        with closing(Database(database).connect()) as connection:
            checkpoint = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            assert checkpoint is not None and int(checkpoint[0]) == 0


def _create_devices(path: Path, *, include_legacy: bool, changed: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(Database(path).connect()) as connection:
        connection.execute(
            "CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO schema_metadata VALUES ('schema_version', ?)",
            ("after" if not include_legacy else "before",),
        )
        connection.execute(
            "CREATE TABLE devices (device_uuid TEXT PRIMARY KEY, name TEXT, payload TEXT)"
        )
        rows = [
            ("device-2", "B", "secret-device-payload-2"),
            (
                "device-1",
                "A",
                "changed-secret-payload" if changed else "secret-device-payload-1",
            ),
        ]
        if include_legacy:
            rows.reverse()
        connection.executemany("INSERT INTO devices VALUES (?, ?, ?)", rows)
        connection.execute(
            "CREATE TABLE ac_fit_ap_unauthenticated_history "
            "(id INTEGER PRIMARY KEY, ac_device_uuid TEXT, collected_at TEXT)"
        )
        connection.execute(
            "INSERT INTO ac_fit_ap_unauthenticated_history "
            "VALUES (1, 'ac-secret', '2026-08-01T00:00:00')"
        )
        if include_legacy:
            connection.execute(
                "CREATE TABLE device_facts_history "
                "(id INTEGER PRIMARY KEY, device_uuid TEXT, collected_at TEXT)"
            )
            connection.execute(
                "INSERT INTO device_facts_history "
                "VALUES (1, 'device-1', '2026-08-01T00:00:00')"
            )
        connection.commit()


def _task_snapshot(task_id: str = "task-real") -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task_id,
        task_type="database_validation",
        task_name="Functional compatibility",
        status=TaskState.COMPLETED,
        created_time="2026-08-01T00:00:00Z",
        updated_time="2026-08-01T00:01:00Z",
        started_time="2026-08-01T00:00:10Z",
        finished_time="2026-08-01T00:01:00Z",
        result_path="D:/study/secret-report.xlsx",
        result={
            "artifact_id": "secret-artifact-id",
            "secret": "secret-result-payload",
        },
        source="worker",
        site_name="line-12",
    )


def _task_event(task_id: str = "task-real") -> TaskEvent:
    return TaskEvent(
        event_id=f"finished-{task_id}",
        task_id=task_id,
        type="finished",
        time="2026-08-01T00:01:00Z",
        source="worker",
        payload={
            "message": "secret-event-message",
            "result": {
                "artifact_id": "secret-artifact-id",
                "secret": "secret-result-payload",
            },
        },
    )


def _prepare_rehearsal(
    root: Path,
    *,
    changed: bool = False,
    evidence_pass: bool = True,
    archive_after_event: bool = True,
):
    before_root = root / "before"
    after_root = root / "after"
    before_devices = before_root / "devices.db"
    after_devices = after_root / "devices.db"
    before_tasks = before_root / "tasks.db"
    after_tasks = after_root / "tasks.db"
    before_history = before_root / "history"
    after_history = after_root / "history"
    before_observations = before_root / "consumer-observations.json"
    after_observations = after_root / "consumer-observations.json"

    _create_devices(before_devices, include_legacy=True)
    _create_devices(after_devices, include_legacy=False, changed=changed)
    before_repository = TaskRepository(before_tasks)
    assert before_repository.record(_task_snapshot(), _task_event())
    with (
        closing(Database(before_tasks).connect()) as source,
        closing(Database(after_tasks).connect()) as target,
    ):
        source.backup(target)

    after_repository = TaskRepository(after_tasks)
    if archive_after_event:
        with closing(after_repository._connect()) as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT sequence, event_id, task_id, event_type, event_time, "
                    "source, payload_json FROM task_events WHERE task_id='task-real'"
                ).fetchall()
            ]
        task_history = TaskHistoryStore(
            after_tasks, site_id="demo", history_root=after_history
        )
        inserted, verified = task_history.archive_event_rows(rows)
        assert (inserted, verified) == (1, 1)
        task_history.store.seal_open_shards()
        with closing(after_repository._connect()) as connection:
            connection.execute("DELETE FROM task_events WHERE task_id='task-real'")
            connection.commit()

    compatibility = _task_snapshot("database-footprint-ref-compatibility")
    assert after_repository.record(
        replace(compatibility, result={"ignored": True}, result_path=""),
        _task_event("database-footprint-ref-compatibility"),
    )

    before_history.mkdir(parents=True, exist_ok=True)
    after_history.mkdir(parents=True, exist_ok=True)
    (before_history / "MIGRATION_PARITY.json").write_text(
        json.dumps(
            {
                "source_table": "device_facts_history",
                "expected_count": 1,
                "actual_count": 1,
                "history_health": {"status": "ready"},
                "result": "PASS",
            }
        ),
        encoding="utf-8",
    )
    (after_history / "POST_REPLACE_PARITY.json").write_text(
        json.dumps(
            {
                "stage": "POST_REPLACE_PARITY",
                "result": "PASS" if evidence_pass else "FAIL",
            }
        ),
        encoding="utf-8",
    )
    snapshot_root = root / "ningbo-line-12-isolated-snapshot"
    snapshot_root.mkdir(parents=True, exist_ok=True)

    def write_observations(path: Path, side: str) -> None:
        observations: dict[str, object] = {}
        for name, _core_ids, _tests in MATRIX_DEFINITIONS:
            safe_name = name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")
            source = path.parent / f"{side}-{safe_name}.json"
            source.write_text(
                json.dumps({"consumer": name, "side": side}, sort_keys=True),
                encoding="utf-8",
            )
            observations[name] = {
                "status": "PASS",
                "query": f"read_only_query:{name}:{side}",
                "query_digest": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_paths": [str(source)],
                "producer": f"{name} producer",
                "repository": f"{name} repository",
                "consumer": f"{name} consumer",
                "lifecycle_owner": f"{name} owner",
                "authority_evidence": {
                    "status": "PASS",
                    "authority": f"{name} authority",
                    "test_ids": ["tests/test_database_functional_compatibility.py"],
                },
            }
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "snapshot_binding": {
                        "site_id": "ningbo-line-12",
                        "snapshot_id": "pytest-ningbo-line-12",
                        "root": str(snapshot_root),
                        "isolated_copy": True,
                    },
                    "observations": observations,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    write_observations(before_observations, "before")
    write_observations(after_observations, "after")
    inputs = {
        "before_devices": before_devices,
        "after_devices": after_devices,
        "before_tasks": before_tasks,
        "after_tasks": after_tasks,
        "before_history_evidence": before_history,
        "after_history_evidence": after_history,
        "before_consumer_observations": before_observations,
        "after_consumer_observations": after_observations,
    }
    _checkpoint_task_inputs(inputs)
    return inputs


def _run(
    root: Path,
    inputs: dict[str, Path],
    *,
    output: str = "output",
    checkpoint_tasks: bool = True,
):
    if checkpoint_tasks and any(
        wal_path.is_file() and wal_path.stat().st_size > 0
        for key in ("before_tasks", "after_tasks")
        for wal_path in (inputs[key].with_name(f"{inputs[key].name}-wal"),)
    ):
        _checkpoint_task_inputs(inputs)
    return validate_database_functional_compatibility(
        **inputs,
        output_dir=root / output,
        development_root=root,
    )


def _enable_result_ref_authority(
    root: Path, inputs: dict[str, Path]
) -> dict[str, object]:
    tasks = inputs["after_tasks"]
    _restore_legacy_full_only_task(tasks, task_id="task-real")
    rollout = TaskResultRolloutService(tasks)
    if rollout.status()["task_result_storage_state"] != "LEGACY_DUAL_FULL":
        with sqlite3.connect(tasks) as connection:
            connection.execute(
                "UPDATE task_result_storage_rollout SET state='LEGACY_DUAL_FULL', "
                "revision=1, updated_by='pytest-fixture', reason='legacy fixture' "
                "WHERE singleton_id=1"
            )
            connection.commit()
    rollout.enable_dual_write(
        expected_revision=1,
        reason="functional authority fixture",
        updated_by="pytest",
    )
    maintenance = TaskResultMaintenanceService(
        PathResolver(app_root=root, data_root=root / "runtime"),
        site_id="line-12",
        tasks_database=tasks,
        development_root=root,
    )
    backfill = maintenance.backfill(
        apply=True,
        allow_development_root_only=True,
    )
    ref = maintenance.enable_ref_authority(
        expected_revision=2,
        reason="functional authority fixture",
        updated_by="pytest",
        apply=True,
        allow_development_root_only=True,
    )
    return {"backfill": backfill, "ref": ref}


def _restore_legacy_full_only_task(database: Path, *, task_id: str) -> None:
    """Make one isolated fixture row represent the pre-authority storage contract."""

    snapshot = _task_snapshot(task_id)
    event = _task_event(task_id)
    with closing(Database(database).connect()) as connection:
        connection.execute(
            "DELETE FROM task_results WHERE task_id=?",
            (task_id,),
        )
        connection.execute(
            "UPDATE task_snapshots SET result_json=?, result_id='', "
            "result_hash='', result_summary_json='{}' WHERE task_id=?",
            (
                json.dumps(snapshot.result, ensure_ascii=False, separators=(",", ":")),
                task_id,
            ),
        )
        connection.execute(
            "UPDATE task_events SET payload_json=? WHERE task_id=? "
            "AND event_type='finished'",
            (
                json.dumps(event.payload, ensure_ascii=False, separators=(",", ":")),
                task_id,
            ),
        )
        connection.commit()


def test_functional_compatibility_passes_repository_readthrough_without_payload_leak(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root)
    database_hashes = {
        name: _sha256(path)
        for name, path in inputs.items()
        if name.endswith("devices") or name.endswith("tasks")
    }

    result = _run(root, inputs, checkpoint_tasks=False)

    assert result["status"] == "PASS"
    assert set(result["outputs"]) == set(OUTPUT_FILENAMES)
    reports = {
        name: json.loads(path.read_text(encoding="utf-8"))
        for name, path in result["outputs"].items()
    }
    assert len({report["git_head"] for report in reports.values()}) == 1
    assert all(
        report["generator"]["script_path"]
        == "scripts/maintenance/validate_database_functional_compatibility.py"
        and len(report["generator"]["script_sha256"]) == 64
        for report in reports.values()
    )
    assert reports["FUNCTIONAL_BASELINE.json"]["status"] == "PASS"
    assert reports["FUNCTIONAL_AFTER.json"]["status"] == "PASS"
    compatibility = reports["FUNCTIONAL_COMPATIBILITY.json"]
    assert compatibility["status"] == "PASS"
    assert all(item["status"] == "PASS" for item in compatibility["checks"])
    assert (
        reports["FUNCTIONAL_AFTER.json"]["profiles"]["task_repository"]["events"][
            "count"
        ]
        == 1
    )
    assert (
        reports["FUNCTIONAL_AFTER.json"]["profiles"]["task_repository"][
            "snapshots"
        ]["count"]
        == 1
    )
    serialized = json.dumps(reports, ensure_ascii=False)
    for secret in (
        "secret-device-payload",
        "secret-result-payload",
        "secret-event-message",
        "secret-artifact-id",
        "ac-secret",
    ):
        assert secret not in serialized
    assert database_hashes == {
        name: _sha256(path)
        for name, path in inputs.items()
        if name.endswith("devices") or name.endswith("tasks")
    }
    assert not list((root / "output").glob(".*.tmp"))

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _run(root, inputs)


def test_functional_compatibility_rejects_non_checkpointed_wal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root)
    with closing(Database(inputs["after_tasks"]).connect()) as connection:
        connection.execute(
            "UPDATE task_snapshots SET message='pending WAL' "
            "WHERE task_id='task-real'"
        )
        connection.commit()
        wal_path = inputs["after_tasks"].with_name(
            f"{inputs['after_tasks'].name}-wal"
        )
        assert wal_path.stat().st_size > 0

        with pytest.raises(
            FunctionalCompatibilityError,
            match="non-empty WAL",
        ):
            _run(
                root,
                inputs,
                output="wal-output",
                checkpoint_tasks=False,
            )

    assert not (root / "wal-output" / "FUNCTIONAL_AFTER.json").exists()


def test_functional_compatibility_reports_hash_only_differences_and_failed_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root, changed=True, evidence_pass=False)

    result = _run(root, inputs)

    assert result["status"] == "FAIL"
    report = json.loads(
        result["outputs"]["FUNCTIONAL_COMPATIBILITY.json"].read_text(
            encoding="utf-8"
        )
    )
    failed = {item["id"]: item for item in report["checks"] if item["status"] == "FAIL"}
    assert "devices.current_business_tables" in failed
    assert "history.migration_and_post_replace_parity" in failed
    assert failed["devices.current_business_tables"]["differences"]
    serialized = json.dumps(report, ensure_ascii=False)
    assert "changed-secret-payload" not in serialized
    assert "secret-result-payload" not in serialized


def test_functional_compatibility_separates_valid_storage_authority_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root, archive_after_event=False)
    rollout = _enable_result_ref_authority(root, inputs)

    result = _run(root, inputs, output="authority-output")

    assert result["status"] == "PASS"
    assert rollout["backfill"]["new_result_rows"] == 1
    report = json.loads(
        result["outputs"]["FUNCTIONAL_AFTER.json"].read_text(encoding="utf-8")
    )
    authority = report["profiles"]["task_repository"]["storage_authority"]
    assert authority == {
        "status": "PASS",
        "result_rows": 1,
        "snapshot_refs": 1,
        "event_refs": 1,
        "resolved_snapshot_refs": 1,
        "resolved_event_refs": 1,
        "binding_hash": authority["binding_hash"],
        "validation_errors": [],
        "validation_error_counts": {},
    }
    compatibility = json.loads(
        result["outputs"]["FUNCTIONAL_COMPATIBILITY.json"].read_text(
            encoding="utf-8"
        )
    )
    task_check = next(
        item
        for item in compatibility["checks"]
        if item["id"] == "tasks.repository_transparent_read"
    )
    assert task_check["status"] == "PASS"
    assert task_check["differences"] == []


def test_functional_compatibility_still_fails_on_resolved_result_change(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root, archive_after_event=False)
    _enable_result_ref_authority(root, inputs)
    changed_result = {
        "artifact_id": "secret-artifact-id",
        "secret": "changed-result-value",
    }
    repository = TaskRepository(inputs["after_tasks"])
    current = repository.get("task-real")
    assert current is not None
    assert repository.record(
        replace(
            current,
            result=changed_result,
            updated_time="2026-08-01T00:02:00Z",
        ),
        TaskEvent(
            event_id="artifact-finalized-task-real",
            task_id="task-real",
            type="artifact_finalized",
            time="2026-08-01T00:02:00Z",
            source="artifact_reconciliation",
            payload={"message": "ready", "result": changed_result},
        ),
    )

    result = _run(root, inputs, output="changed-result-output")

    assert result["status"] == "FAIL"
    after = json.loads(
        result["outputs"]["FUNCTIONAL_AFTER.json"].read_text(encoding="utf-8")
    )
    assert (
        after["profiles"]["task_repository"]["storage_authority"]["status"]
        == "PASS"
    )
    compatibility = json.loads(
        result["outputs"]["FUNCTIONAL_COMPATIBILITY.json"].read_text(
            encoding="utf-8"
        )
    )
    task_check = next(
        item
        for item in compatibility["checks"]
        if item["id"] == "tasks.repository_transparent_read"
    )
    assert task_check["status"] == "FAIL"
    assert {item["item"] for item in task_check["differences"]} >= {
        "snapshots.result",
        "snapshots.semantic",
    }


def test_functional_compatibility_fails_closed_on_wrong_result_reference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root, archive_after_event=False)
    _enable_result_ref_authority(root, inputs)
    excluded_task_id = "database-footprint-ref-compatibility"
    repository = TaskRepository(inputs["after_tasks"])
    excluded_event = replace(
        _task_event(excluded_task_id),
        event_id="finished-excluded-authority",
        time="2026-08-01T00:02:00Z",
    )
    assert repository.record(_task_snapshot(excluded_task_id), excluded_event)
    _restore_legacy_full_only_task(inputs["after_tasks"], task_id=excluded_task_id)
    maintenance = TaskResultMaintenanceService(
        PathResolver(app_root=root, data_root=root / "runtime"),
        site_id="line-12",
        tasks_database=inputs["after_tasks"],
        development_root=root,
    )
    assert maintenance.backfill(
        apply=True, allow_development_root_only=True
    )["new_result_rows"] == 1
    excluded = repository.get(excluded_task_id)
    assert excluded is not None and excluded.result_id
    with closing(Database(inputs["after_tasks"]).connect()) as connection:
        connection.execute(
            "UPDATE task_snapshots SET result_id=?, result_hash=?, "
            "result_summary_json=? WHERE task_id='task-real'",
            (
                excluded.result_id,
                excluded.result_hash,
                json.dumps(excluded.result_summary, separators=(",", ":")),
            ),
        )
        connection.commit()

    result = _run(root, inputs, output="wrong-ref-output")

    assert result["status"] == "FAIL"
    after = json.loads(
        result["outputs"]["FUNCTIONAL_AFTER.json"].read_text(encoding="utf-8")
    )
    authority = after["profiles"]["task_repository"]["storage_authority"]
    assert authority["status"] == "FAIL"
    assert authority["validation_error_counts"] == {
        "result_ref_task_mismatch": 1,
        "snapshot_repository_readthrough_invalid": 1,
    }
    compatibility = json.loads(
        result["outputs"]["FUNCTIONAL_COMPATIBILITY.json"].read_text(
            encoding="utf-8"
        )
    )
    task_check = next(
        item
        for item in compatibility["checks"]
        if item["id"] == "tasks.repository_transparent_read"
    )
    assert task_check["status"] == "FAIL"
    assert "after.storage_authority.integrity" in {
        item["item"] for item in task_check["differences"]
    }


def test_functional_compatibility_accepts_failed_snapshot_with_finished_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root)
    result_payload = {"data_persisted": False, "worker_exit_code": 1}
    snapshot = replace(
        _task_snapshot("legacy-failed-finished"),
        status=TaskState.FAILED,
        result=result_payload,
        error_message="legacy terminal state",
    )
    event = replace(
        _task_event("legacy-failed-finished"),
        payload={"message": "legacy result", "result": result_payload},
    )
    for database in (inputs["before_tasks"], inputs["after_tasks"]):
        assert TaskRepository(database).record(snapshot, event)
    with closing(Database(inputs["after_tasks"]).connect()) as connection:
        connection.execute(
            "DELETE FROM task_events "
            "WHERE task_id='database-footprint-ref-compatibility'"
        )
        connection.execute(
            "UPDATE task_events SET sequence=2 "
            "WHERE task_id='legacy-failed-finished'"
        )
        connection.commit()
    _enable_result_ref_authority(root, inputs)

    result = _run(root, inputs, output="legacy-terminal-output")

    assert result["status"] == "PASS"
    after = json.loads(
        result["outputs"]["FUNCTIONAL_AFTER.json"].read_text(encoding="utf-8")
    )
    authority = after["profiles"]["task_repository"]["storage_authority"]
    assert authority["status"] == "PASS"
    assert authority["resolved_snapshot_refs"] == 2
    assert authority["resolved_event_refs"] == 1


def test_functional_compatibility_rejects_output_outside_development_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root)

    with pytest.raises(FunctionalCompatibilityError, match="development root"):
        validate_database_functional_compatibility(
            **inputs,
            output_dir=tmp_path / "outside",
            development_root=root,
        )


def test_functional_compatibility_rejects_output_overlapping_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "development"
    root.mkdir()
    inputs = _prepare_rehearsal(root)

    with pytest.raises(FunctionalCompatibilityError, match="must not overlap"):
        validate_database_functional_compatibility(
            **inputs,
            output_dir=inputs["after_history_evidence"] / "reports",
            development_root=root,
        )
