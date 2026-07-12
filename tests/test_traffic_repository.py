from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.models.traffic_test import (
    AgentTaskMapping,
    ExecutionTargetDTO,
    ExecutionTargetKind,
    HighFrequencyPingConfig,
    TrafficPingSample,
    TrafficRun,
    TrafficSyncState,
    TrafficTestType,
)
from netconsole.repositories.traffic_run_repository import TrafficRunRepository


NOW = "2026-07-12T12:00:00.000Z"


def _run(
    traffic_run_id: str = "run-1",
    *,
    site_task: str = "task-1",
    executor_kind: ExecutionTargetKind = ExecutionTargetKind.LOCAL,
    agent_id: str = "",
) -> TrafficRun:
    return TrafficRun(
        traffic_run_id=traffic_run_id,
        controller_task_id=site_task,
        test_type=TrafficTestType.HIGH_FREQUENCY_PING,
        role="probe",
        executor_kind=executor_kind,
        agent_id=agent_id,
        normalized_config={"targets": ["192.0.2.1"], "packet_size": 64},
        status=TaskState.RUNNING,
        created_at=NOW,
        updated_at=NOW,
    )


def test_traffic_paths_and_config_contract(tmp_path) -> None:
    paths = PathResolver(tmp_path)
    root = tmp_path / "data" / "sites" / "site-a" / "files" / "network_tools" / "traffic"
    assert paths.traffic_root("site-a") == root
    assert paths.traffic_runs_db_path("site-a") == root / "parsed" / "traffic_runs.sqlite"
    assert paths.traffic_run_events_path("site-a", "run-1") == root / "runs" / "run-1" / "events.jsonl"
    assert paths.traffic_run_summary_path("site-a", "run-1") == root / "runs" / "run-1" / "summary.json"
    assert paths.traffic_run_remote_result_path("site-a", "run-1") == root / "runs" / "run-1" / "remote_result.json"
    with pytest.raises(ValueError):
        paths.traffic_run_dir("site-a", "../escape")

    assert ExecutionTargetDTO(ExecutionTargetKind.LOCAL).agent_id == ""
    with pytest.raises(ValueError):
        ExecutionTargetDTO(ExecutionTargetKind.AGENT)
    assert HighFrequencyPingConfig(("192.0.2.1",), packet_size=65_507).normalized().packet_size == 65_507
    assert HighFrequencyPingConfig(("192.0.2.1",), continuous=True, count=0).normalized().continuous
    for config in (
        HighFrequencyPingConfig(("",)),
        HighFrequencyPingConfig(("192.0.2.1", "192.0.2.1")),
        HighFrequencyPingConfig(("192.0.2.1",), packet_size=0),
        HighFrequencyPingConfig(("192.0.2.1",), continuous=True, count=1),
        HighFrequencyPingConfig(("192.0.2.1",), continuous=False, count=0),
    ):
        with pytest.raises(ValueError):
            config.normalized()


def test_repository_schema_wal_busy_timeout_foreign_keys_and_idempotence(tmp_path) -> None:
    db_path = PathResolver(tmp_path).traffic_runs_db_path("demo")
    repository = TrafficRunRepository(db_path)
    with repository._connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "traffic_schema_meta",
            "traffic_runs",
            "traffic_agent_tasks",
            "traffic_ping_samples",
        } <= tables
        conn.execute("CREATE TABLE legacy_keep(value TEXT)")
        conn.execute("INSERT INTO legacy_keep VALUES ('保留')")
        conn.commit()

    TrafficRunRepository(db_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM legacy_keep").fetchone()[0] == "保留"
        assert conn.execute("SELECT value FROM traffic_schema_meta WHERE key='schema_version'").fetchone()[0] == "1"


def test_repository_run_mapping_recovery_retry_and_site_isolation(tmp_path) -> None:
    paths = PathResolver(tmp_path)
    first = TrafficRunRepository(paths.traffic_runs_db_path("site-a"))
    second = TrafficRunRepository(paths.traffic_runs_db_path("site-b"))
    original = _run(executor_kind=ExecutionTargetKind.AGENT, agent_id="agent-1")
    first.create(original)
    retry = replace(
        _run("run-2", site_task="task-2", executor_kind=ExecutionTargetKind.AGENT, agent_id="agent-1"),
        retry_of_traffic_run_id=original.traffic_run_id,
        parent_task_id="parent-1",
        correlation_id="pair-1",
    )
    first.create(retry)
    assert second.list() == []
    assert first.get_by_controller_task("task-2") == retry

    mapping = AgentTaskMapping(
        traffic_run_id="run-2",
        controller_task_id="task-2",
        agent_id="agent-1",
        agent_task_id="remote-1",
        agent_task_type="fping",
        created_at=NOW,
        updated_at=NOW,
    )
    first.save_agent_mapping(mapping)
    assert first.get_agent_mapping("run-2") == mapping
    assert first.get_agent_mapping_by_remote_task("agent-1", "remote-1") == mapping
    assert [item.traffic_run_id for item in first.list_recoverable_agent_mappings()] == ["run-2"]

    assert first.delete_agent_mapping("run-2")
    assert not first.delete_agent_mapping("run-2")
    first.save_agent_mapping(mapping)

    first.save(replace(retry, status=TaskState.FAILED, sync_state=TrafficSyncState.ERROR))
    assert [item.traffic_run_id for item in first.list_recoverable_agent_mappings()] == ["run-2"]
    terminal_pending_finalize = replace(
        mapping,
        last_remote_status="completed",
        sync_state=TrafficSyncState.ACTIVE,
    )
    first.save_agent_mapping(terminal_pending_finalize)
    assert [item.traffic_run_id for item in first.list_recoverable_agent_mappings()] == ["run-2"]
    first.save(replace(retry, status=TaskState.COMPLETED, sync_state=TrafficSyncState.COMPLETED))
    assert [item.traffic_run_id for item in first.list_recoverable_agent_mappings()] == ["run-2"]
    first.save_agent_mapping(
        replace(mapping, last_remote_status="running", sync_state=TrafficSyncState.COMPLETED)
    )
    assert first.list_recoverable_agent_mappings() == []
    assert first.delete("run-2")
    assert first.get_agent_mapping("run-2") is None


def test_ping_batch_is_transactional_and_deduplicates_replayed_samples(tmp_path) -> None:
    repository = TrafficRunRepository(PathResolver(tmp_path).traffic_runs_db_path("demo"))
    repository.create(_run())
    samples = [
        TrafficPingSample("run-1", 1, NOW, "192.0.2.1", 1, True, 1.25, packet_size=64),
        TrafficPingSample("run-1", 2, NOW, "192.0.2.2", 1, False, 9.0, timeout=True, error_code="timeout"),
    ]
    assert repository.insert_ping_samples(samples, updated_at=NOW) == 2
    assert repository.insert_ping_samples(samples, updated_at=NOW) == 0
    assert repository.insert_ping_samples(
        [TrafficPingSample("run-1", 3, NOW, "192.0.2.1", 1, True, 1.5)],
        updated_at=NOW,
    ) == 0
    restored = repository.list_ping_samples("run-1")
    assert len(restored) == 2
    assert restored[1].timeout is True and restored[1].rtt_ms is None
    assert repository.get("run-1").last_event_sequence == 2


def test_repository_rejects_secrets_and_absolute_references(tmp_path) -> None:
    repository = TrafficRunRepository(PathResolver(tmp_path).traffic_runs_db_path("demo"))
    with pytest.raises(ValueError):
        repository.create(replace(_run(), normalized_config={"agent_token": "do-not-store"}))
    with pytest.raises(ValueError):
        repository.create(replace(_run("run-2", site_task="task-2"), raw_reference=str(tmp_path / "raw.log")))
    assert not repository.db_path.exists() or b"do-not-store" not in repository.db_path.read_bytes()
