from __future__ import annotations

import json
import os
import sqlite3
import threading
import zipfile
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services import site_retention as retention_module
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)
from netconsole.services.site_retention import SiteRetentionService
from netconsole.services.site_storage import SiteApplicationService, SiteStorageError


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _paths(tmp_path: Path) -> PathResolver:
    app_root = tmp_path / "app"
    app_root.mkdir()
    return PathResolver(app_root=app_root, data_root=tmp_path / "data")


def _site(tmp_path: Path) -> tuple[PathResolver, Path]:
    paths = _paths(tmp_path)
    created = SiteApplicationService(paths).create_site("line-12", "宁波地铁12号线")
    return paths, Path(str(created["path"]))


def _write_devices_database(path: Path, schema_version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO schema_metadata VALUES ('schema_version', ?, '', '')",
            (schema_version,),
        )
        connection.execute("INSERT INTO devices(name) VALUES ('device')")
        connection.commit()


def _set_age(path: Path, days: int) -> None:
    timestamp = (NOW.timestamp() - days * 86400)
    os.utime(path, (timestamp, timestamp))


def _candidate(report: dict[str, object], name: str) -> dict[str, object]:
    return next(
        item
        for item in report["candidates"]  # type: ignore[index]
        if isinstance(item, dict) and item.get("display_name") == name
    )


def test_scan_keeps_current_and_recent_rollbacks_but_deletes_old_version(
    tmp_path: Path,
) -> None:
    paths, root = _site(tmp_path)
    backups = root / "files" / "backups" / "database-migrations"
    recent = backups / "devices-before-recent.sqlite"
    stable = backups / "devices-before-stable.sqlite"
    old = backups / "devices-before-old.sqlite"
    _write_devices_database(recent, "2026.08.01.recent")
    _write_devices_database(stable, "2026.07.31.stable")
    _write_devices_database(old, "2026.07.01.old")
    _set_age(recent, 10)
    _set_age(stable, 20)
    _set_age(old, 100)

    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")

    current = next(
        item
        for item in report["candidates"]  # type: ignore[index]
        if isinstance(item, dict)
        and item.get("category") == "current_database"
        and item.get("display_name") == "devices.db"
    )
    assert current["safe"] is False
    assert current["status"] == "current_use"
    assert _candidate(report, recent.name)["status"] == "recent_rollback"
    assert _candidate(report, stable.name)["status"] == "recent_stable"
    old_candidate = _candidate(report, old.name)
    assert old_candidate["safe"] is True
    assert old_candidate["recommended_action"] == "delete"

    result = service.apply(
        "line-12",
        scan_token=str(report["scan_token"]),
        candidate_ids=[str(old_candidate["candidate_id"])],
    )

    assert result["success_count"] == 1
    assert not old.exists()
    assert recent.exists()
    assert stable.exists()
    assert (root / "db" / "devices.db").exists()


def test_scan_archives_30_to_90_day_backup_with_conservative_estimate(
    tmp_path: Path,
) -> None:
    paths, root = _site(tmp_path)
    backups = root / "files" / "backups" / "database-migrations"
    recent = backups / "devices-before-recent.sqlite"
    stable = backups / "devices-before-stable.sqlite"
    archive_target = backups / "devices-before-archive.sqlite"
    for path, version in (
        (recent, "2026.08.01.recent"),
        (stable, "2026.07.31.stable"),
        (archive_target, "2026.07.01.archive"),
    ):
        _write_devices_database(path, version)
    with closing(sqlite3.connect(archive_target)) as connection:
        connection.executemany(
            "INSERT INTO devices(name) VALUES (?)",
            [("repeated-device-name-" * 20,) for _ in range(5000)],
        )
        connection.commit()
    _set_age(recent, 10)
    _set_age(stable, 20)
    _set_age(archive_target, 45)

    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")
    candidate = _candidate(report, archive_target.name)

    assert candidate["safe"] is True
    assert candidate["recommended_action"] == "archive"
    assert 0 < int(candidate["estimated_release_bytes"]) < int(candidate["size_bytes"])

    result = service.apply(
        "line-12",
        scan_token=str(report["scan_token"]),
        candidate_ids=[str(candidate["candidate_id"])],
    )

    assert result["success_count"] == 1
    assert not archive_target.exists()
    archive_path = root / str(result["results"][0]["archive_path"])  # type: ignore[index]
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert archive_target.name in archive.namelist()


def test_exact_duplicate_known_backup_can_be_deleted_but_unknown_cannot(
    tmp_path: Path,
) -> None:
    paths, root = _site(tmp_path)
    backups = root / "files" / "backups" / "database-migrations"
    known_new = backups / "devices-copy-new.sqlite"
    known_old = backups / "devices-copy-old.sqlite"
    _write_devices_database(known_new, "2026.08.01.copy")
    known_old.write_bytes(known_new.read_bytes())
    _set_age(known_new, 5)
    _set_age(known_old, 10)

    unknown_new = backups / "legacy-copy-new.sqlite"
    unknown_old = backups / "legacy-copy-old.sqlite"
    with closing(sqlite3.connect(unknown_new)) as connection:
        connection.execute("CREATE TABLE legacy_payload(value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_payload VALUES ('unknown')")
        connection.commit()
    unknown_old.write_bytes(unknown_new.read_bytes())
    _set_age(unknown_new, 100)
    _set_age(unknown_old, 110)

    report = SiteRetentionService(paths, now=lambda: NOW).scan("line-12")
    known = _candidate(report, known_old.name)
    unknown = _candidate(report, unknown_old.name)

    assert known["status"] == "duplicate_backup"
    assert known["safe"] is True
    assert known["recommended_action"] == "delete"
    assert unknown["status"] == "unknown_database"
    assert unknown["safe"] is False
    assert unknown["recommended_action"] == "keep"


def test_unreferenced_database_cannot_prove_backup_is_outdated(tmp_path: Path) -> None:
    paths, root = _site(tmp_path)
    current = root / "db" / "legacy-devices.sqlite"
    backups = root / "files" / "backups" / "database-migrations"
    recent = backups / "devices-recent.sqlite"
    stable = backups / "devices-stable.sqlite"
    backup = backups / "devices-old.sqlite"
    (root / "db" / "devices.db").unlink()
    _write_devices_database(current, "2026.08.10.current")
    _write_devices_database(recent, "2026.08.01.recent")
    _write_devices_database(stable, "2026.07.31.stable")
    _write_devices_database(backup, "2026.07.01.old")
    _set_age(recent, 10)
    _set_age(stable, 20)
    _set_age(backup, 100)

    report = SiteRetentionService(paths, now=lambda: NOW).scan("line-12")
    current_candidate = _candidate(report, current.name)
    backup_candidate = _candidate(report, backup.name)

    assert current_candidate["details"]["code_reference"] == "protected_unverified"
    assert backup_candidate["safe"] is False
    assert backup_candidate["recommended_action"] == "keep"
    assert "当前 schema" in str(backup_candidate["reason"])


def test_nonempty_backup_wal_blocks_automatic_cleanup(tmp_path: Path) -> None:
    paths, root = _site(tmp_path)
    backups = root / "files" / "backups" / "database-migrations"
    recent = backups / "devices-before-recent.sqlite"
    stable = backups / "devices-before-stable.sqlite"
    old = backups / "devices-before-old.sqlite"
    _write_devices_database(recent, "2026.08.01.recent")
    _write_devices_database(stable, "2026.07.31.stable")
    _write_devices_database(old, "2026.07.01.old")
    _set_age(recent, 10)
    _set_age(stable, 20)
    _set_age(old, 100)

    connection = sqlite3.connect(old)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("INSERT INTO devices(name) VALUES ('pending-wal')")
        connection.commit()
        assert old.with_name(f"{old.name}-wal").stat().st_size > 0
        _set_age(old, 100)

        candidate = _candidate(
            SiteRetentionService(paths, now=lambda: NOW).scan("line-12"), old.name
        )
    finally:
        connection.close()

    assert candidate["safe"] is False
    assert candidate["recommended_action"] == "keep"
    assert "WAL" in str(candidate["reason"])


def test_apply_rejects_changed_candidate_after_scan(tmp_path: Path) -> None:
    paths, root = _site(tmp_path)
    backup = root / "files" / "backups" / "database-migrations" / "old.sqlite"
    retained = backup.with_name("recent.sqlite")
    stable = backup.with_name("stable.sqlite")
    _write_devices_database(retained, "2026.08.01.recent")
    _write_devices_database(stable, "2026.07.31.stable")
    _write_devices_database(backup, "2026.07.01.old")
    _set_age(retained, 10)
    _set_age(stable, 20)
    _set_age(backup, 100)
    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")
    candidate = _candidate(report, backup.name)

    with closing(sqlite3.connect(backup)) as connection:
        connection.execute("INSERT INTO devices(name) VALUES ('changed')")
        connection.commit()

    with pytest.raises(SiteStorageError) as stale:
        service.apply(
            "line-12",
            scan_token=str(report["scan_token"]),
            candidate_ids=[str(candidate["candidate_id"])],
        )

    assert stale.value.code == "SITE_RETENTION_SCAN_STALE"
    assert backup.exists()


def test_online_mr_raw_archive_keeps_web_raw_readable_from_session_package(
    tmp_path: Path,
) -> None:
    paths, root = _site(tmp_path)
    session_id = "20260701_120000_test"
    session_dir = (
        root
        / "files"
        / "rail_transit"
        / "online_mr"
        / "MR-01__1"
        / "sessions"
        / session_id
    )
    raw_dir = session_dir / "raw"
    parsed_dir = session_dir / "parsed"
    outputs_dir = session_dir / "outputs"
    raw_dir.mkdir(parents=True)
    parsed_dir.mkdir()
    outputs_dir.mkdir()
    raw = raw_dir / "mesh_link_raw.log"
    raw.write_text("2026-07-01 12:00:00 mesh active\n", encoding="utf-8")
    with closing(sqlite3.connect(parsed_dir / "online_diagnosis.sqlite")) as connection:
        connection.execute("CREATE TABLE parsed_samples(id INTEGER PRIMARY KEY)")
        connection.commit()
    meta = {
        "session_id": session_id,
        "site": "line-12",
        "mr_name": "MR-01",
        "started_at": "2026-07-01T12:00:00Z",
        "ended_at": "2026-07-01T12:10:00Z",
        "status": "STOPPED",
        "finalization_complete": True,
        "package_available": True,
        "data_integrity": "complete",
    }
    (session_dir / "session_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    package = outputs_dir / f"{session_id}.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(raw, "raw/mesh_link_raw.log")
        archive.write(
            parsed_dir / "online_diagnosis.sqlite",
            "parsed/online_diagnosis.sqlite",
        )
        archive.writestr("session_meta.json", json.dumps(meta, ensure_ascii=False))

    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")
    candidate = next(
        item
        for item in report["candidates"]  # type: ignore[index]
        if isinstance(item, dict)
        and item.get("category") == "expired_raw"
        and item.get("details", {}).get("session_id") == session_id
    )
    assert candidate["safe"] is True

    service.apply(
        "line-12",
        scan_token=str(report["scan_token"]),
        candidate_ids=[str(candidate["candidate_id"])],
    )

    assert not raw_dir.exists()
    assert package.exists()
    assert (parsed_dir / "online_diagnosis.sqlite").exists()
    tail = OnlineMrQueryService(paths).read_raw_tail(
        "line-12", session_id, "mesh_link"
    )
    assert tail.exists is True
    assert tail.lines == ["2026-07-01 12:00:00 mesh active"]
    summary = OnlineMrQueryService(paths).get_raw_summary("line-12", session_id)
    assert next(item for item in summary if item.name == "mesh_link").exists is True
    chunk = OnlineMrQueryService(paths).read_log_chunk(
        "line-12", session_id, "mesh_link", limit=10
    )
    assert [line.text for line in chunk.lines] == [
        "2026-07-01 12:00:00 mesh active"
    ]


def test_apply_blocks_when_another_task_is_active(tmp_path: Path) -> None:
    paths, root = _site(tmp_path)
    backups = root / "files" / "backups" / "database-migrations"
    recent = backups / "devices-before-recent.sqlite"
    stable = backups / "devices-before-stable.sqlite"
    old = backups / "devices-before-old.sqlite"
    _write_devices_database(recent, "2026.08.01.recent")
    _write_devices_database(stable, "2026.07.31.stable")
    _write_devices_database(old, "2026.07.01.old")
    _set_age(recent, 10)
    _set_age(stable, 20)
    _set_age(old, 100)
    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")
    candidate = _candidate(report, old.name)

    TaskRepository(root / "db" / "tasks.db").save(
        TaskSnapshot(
            task_id="other-running-task",
            task_type="device_collect",
            task_name="设备采集",
            status=TaskState.RUNNING,
            created_time="2026-08-13T00:00:00Z",
            updated_time="2026-08-13T00:01:00Z",
            site_name="line-12",
        )
    )

    with pytest.raises(SiteStorageError) as blocked:
        service.apply(
            "line-12",
            scan_token=str(report["scan_token"]),
            candidate_ids=[str(candidate["candidate_id"])],
            current_job_id="retention-job",
        )

    assert blocked.value.code == "SITE_HAS_ACTIVE_TASKS"
    assert old.exists()


def test_task_retention_is_typed_preview_only_and_keeps_events_unchanged(
    tmp_path: Path,
) -> None:
    paths, root = _site(tmp_path)
    task_db = root / "db" / "tasks.db"
    TaskRepository(task_db)
    with closing(sqlite3.connect(task_db)) as connection:
        connection.execute(
            """
            INSERT INTO task_events(
                event_id, task_id, event_type, event_time, source, payload_json
            ) VALUES ('old-event', 'old-task', 'log', '2026-04-01T00:00:00Z', 'test', '{}')
            """
        )
        connection.commit()
        connection.execute(
            """
            INSERT INTO task_events(
                event_id, task_id, event_type, event_time, source, payload_json
            ) VALUES ('recent-event', 'recent-task', 'log', '2026-08-01T00:00:00Z', 'test', '{}')
            """
        )
        connection.commit()
    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")
    candidate = next(
        item
        for item in report["candidates"]  # type: ignore[index]
        if isinstance(item, dict) and item.get("category") == "task_history"
    )
    assert candidate["safe"] is False
    assert candidate["recommended_action"] == "preview"
    assert candidate["status"] == "USER_POLICY_REQUIRED"
    assert candidate["details"]["apply_enabled"] is False  # type: ignore[index]
    assert candidate["details"]["vacuum"] is False  # type: ignore[index]
    event_breakdown = candidate["details"]["task_event_breakdown"]  # type: ignore[index]
    log_preview = next(item for item in event_breakdown if item["event_type"] == "log")
    assert log_preview["retention_days"] == 30
    assert log_preview["would_delete_rows"] == 1
    assert int(candidate["details"]["would_delete_bytes_estimate"]) > 0  # type: ignore[index]

    with pytest.raises(SiteStorageError) as blocked:
        service.apply(
            "line-12",
            scan_token=str(report["scan_token"]),
            candidate_ids=[str(candidate["candidate_id"])],
        )

    assert blocked.value.code == "SITE_RETENTION_CANDIDATE_BLOCKED"
    with closing(sqlite3.connect(task_db)) as connection:
        rows = connection.execute(
            "SELECT event_id FROM task_events ORDER BY event_id"
        ).fetchall()
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    assert rows == [("old-event",), ("recent-event",)]
    assert quick_check == "ok"


def test_task_retention_preview_breaks_down_type_status_and_authority_result(
    tmp_path: Path,
) -> None:
    paths, root = _site(tmp_path)
    task_db = root / "db" / "tasks.db"
    repository = TaskRepository(task_db)
    TaskResultRolloutService(task_db).enable_dual_write(
        expected_revision=1,
        reason="typed retention authority fixture",
        updated_by="pytest",
    )
    old_time = "2026-04-01T00:00:00Z"
    result = {"producer": "ac_fit_ap_resources_refresh", "rows": 500}
    snapshot = TaskSnapshot(
        task_id="old-terminal-task",
        task_type="ac_fit_ap_resources_refresh",
        task_name="刷新 FIT-AP 资源",
        status=TaskState.COMPLETED,
        created_time=old_time,
        finished_time=old_time,
        updated_time=old_time,
        progress=100,
        result=result,
        site_name="line-12",
    )
    event = TaskEvent(
        event_id="old-terminal-event",
        task_id=snapshot.task_id,
        type="finished",
        time=old_time,
        source="worker",
        payload={"result": result},
    )
    assert repository.record(snapshot, event)
    repository.save(
        TaskSnapshot(
            task_id="active-task",
            task_type="device_collect",
            task_name="设备采集",
            status=TaskState.RUNNING,
            created_time=old_time,
            updated_time=old_time,
            site_name="line-12",
        )
    )

    report = SiteRetentionService(paths, now=lambda: NOW).scan("line-12")
    candidate = next(
        item
        for item in report["candidates"]  # type: ignore[index]
        if isinstance(item, dict) and item.get("category") == "task_history"
    )
    details = candidate["details"]
    snapshots = details["task_snapshot_breakdown"]
    completed = next(
        item for item in snapshots if item["task_type"] == "ac_fit_ap_resources_refresh"
    )
    active = next(item for item in snapshots if item["task_type"] == "device_collect")
    assert completed["status"] == "COMPLETED"
    assert completed["would_delete_rows"] == 1
    assert active["policy"] == "NEVER_WHILE_ACTIVE"
    assert active["would_delete_rows"] == 0
    results = details["task_result_breakdown"]
    assert len(results) == 1
    result_preview = results[0]
    assert result_preview["terminal_event_type"] == "finished"
    assert result_preview["total_rows"] == 1
    assert result_preview["retention_days"] == 90
    assert result_preview["cutoff"] == "2026-05-15T12:00:00+00:00"
    assert result_preview["would_delete_rows"] == 1
    assert result_preview["would_delete_bytes_estimate"] > 0
    assert result_preview["authority_copies_after_retention"] == 1


def test_retention_database_lock_wraps_storage_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, root = _site(tmp_path)
    backups = root / "files" / "backups" / "database-migrations"
    recent = backups / "devices-before-recent.sqlite"
    stable = backups / "devices-before-stable.sqlite"
    old = backups / "devices-before-old.sqlite"
    _write_devices_database(recent, "2026.08.01.recent")
    _write_devices_database(stable, "2026.07.31.stable")
    _write_devices_database(old, "2026.07.01.old")
    _set_age(recent, 10)
    _set_age(stable, 20)
    _set_age(old, 100)
    active_database_locks: list[str] = []

    @contextmanager
    def database_lock(_paths: PathResolver, key: str):
        active_database_locks.append(key)
        try:
            yield
        finally:
            active_database_locks.pop()

    original_storage_lock = retention_module.storage_lock

    @contextmanager
    def storage_lock(paths_value: PathResolver, name: str):
        assert active_database_locks == [site_database_maintenance_key("line-12")]
        with original_storage_lock(paths_value, name):
            yield

    monkeypatch.setattr(retention_module, "database_maintenance_lock", database_lock)
    monkeypatch.setattr(retention_module, "storage_lock", storage_lock)
    service = SiteRetentionService(paths, now=lambda: NOW)
    report = service.scan("line-12")
    candidate = _candidate(report, old.name)
    service.apply(
        "line-12",
        scan_token=str(report["scan_token"]),
        candidate_ids=[str(candidate["candidate_id"])],
    )
    assert active_database_locks == []


def test_future_compact_lock_serializes_retention_preview(tmp_path: Path) -> None:
    paths, _root = _site(tmp_path)
    key = site_database_maintenance_key("line-12")
    compact_entered = threading.Event()
    release_compact = threading.Event()
    retention_completed = threading.Event()

    def compact() -> None:
        with database_maintenance_lock(paths, key):
            compact_entered.set()
            release_compact.wait(timeout=5)

    def preview() -> None:
        SiteRetentionService(paths, now=lambda: NOW).scan("line-12")
        retention_completed.set()

    compact_thread = threading.Thread(target=compact)
    retention_thread = threading.Thread(target=preview)
    compact_thread.start()
    assert compact_entered.wait(timeout=2)
    retention_thread.start()
    assert not retention_completed.wait(timeout=0.1)
    release_compact.set()
    compact_thread.join(timeout=2)
    retention_thread.join(timeout=2)
    assert retention_completed.is_set()


def test_typed_task_retention_exact_apply_preserves_active_mr_ground_and_artifact(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    task_db = tmp_path / "rehearsal" / "tasks.db"
    rollout = TaskResultRolloutService(task_db)
    rollout.enable_dual_write(
        expected_revision=1,
        reason="typed retention fixture",
        updated_by="pytest",
    )
    repository = TaskRepository(task_db)
    old_time = "2026-01-01T00:00:00Z"

    def terminal(task_id: str, task_type: str, result: dict[str, object]) -> None:
        snapshot = TaskSnapshot(
            task_id=task_id,
            task_type=task_type,
            task_name=task_id,
            status=TaskState.COMPLETED,
            created_time=old_time,
            finished_time=old_time,
            updated_time=old_time,
            progress=100,
            result=result,
            site_name="line-12",
        )
        event = TaskEvent(
            event_id=f"finished-{task_id}",
            task_id=task_id,
            type="finished",
            time=old_time,
            source="pytest",
            payload={"result": result},
        )
        assert repository.record(snapshot, event)

    terminal("ordinary-old", "device_collect", {"rows": 10})
    terminal("mr-old", "online_mr_collect", {"rows": 20})
    terminal("ground-old", "ground_unattended_collect", {"rows": 30})
    terminal("artifact-old", "report_export", {"artifact_id": "artifact-1"})
    repository.save(
        TaskSnapshot(
            task_id="active-old",
            task_type="device_collect",
            task_name="active-old",
            status=TaskState.RUNNING,
            created_time=old_time,
            updated_time=old_time,
            site_name="line-12",
        )
    )
    artifact = tmp_path / "rehearsal" / "artifact.xlsx"
    artifact.write_bytes(b"artifact")
    with closing(sqlite3.connect(task_db)) as connection:
        connection.executescript(
            """
            CREATE TABLE online_mr_task_sessions (
                controller_task_id TEXT PRIMARY KEY,
                session_id TEXT,
                site_id TEXT NOT NULL
            );
            INSERT INTO online_mr_task_sessions VALUES
                ('mr-old', 'session-1', 'line-12');
            """
        )
        connection.executemany(
            "INSERT INTO task_events "
            "(event_id, task_id, event_type, event_time, source, payload_json) "
            "VALUES (?, ?, ?, ?, 'pytest', '{}')",
            [
                ("progress-ordinary", "ordinary-old", "progress", old_time),
                ("log-ordinary", "ordinary-old", "log", old_time),
                ("progress-active", "active-old", "progress", old_time),
            ],
        )
        connection.commit()

    service = SiteRetentionService(paths, now=lambda: NOW)
    plan = service.preview_typed_task_retention(
        "line-12",
        tasks_database=task_db,
        development_root=tmp_path,
    )

    assert plan["policy"]["status"] == "REHEARSAL_POLICY_ONLY"
    assert plan["expected_counts"] == {
        "events": 3,
        "snapshots": 1,
        "results": 1,
    }
    assert plan["protected"] == {
        "total": 4,
        "active": 1,
        "online_mr": 1,
        "ground": 1,
        "artifact": 1,
        "task_ids": ["active-old", "artifact-old", "ground-old", "mr-old"],
    }
    result = service.apply_typed_task_retention(
        plan,
        expected_plan_digest=str(plan["plan_digest"]),
        apply=True,
        allow_development_root_only=True,
        development_root=tmp_path,
    )

    assert result["deleted"] == plan["expected_counts"]
    assert result["active_tasks_deleted"] == 0
    assert result["artifacts_deleted"] == 0
    assert artifact.read_bytes() == b"artifact"
    with closing(sqlite3.connect(task_db)) as connection:
        remaining = {
            str(row[0])
            for row in connection.execute("SELECT task_id FROM task_snapshots")
        }
        mapping_count = connection.execute(
            "SELECT COUNT(*) FROM online_mr_task_sessions"
        ).fetchone()[0]
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    assert remaining == {"active-old", "artifact-old", "ground-old", "mr-old"}
    assert mapping_count == 1
    assert quick_check == "ok"


def test_typed_task_retention_rejects_stale_database_and_outside_root(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    task_db = tmp_path / "rehearsal" / "tasks.db"
    repository = TaskRepository(task_db)
    repository.save(
        TaskSnapshot(
            task_id="active",
            task_type="device_collect",
            task_name="active",
            status=TaskState.RUNNING,
            created_time="2026-01-01T00:00:00Z",
            updated_time="2026-01-01T00:00:00Z",
        )
    )
    service = SiteRetentionService(paths, now=lambda: NOW)
    plan = service.preview_typed_task_retention(
        "line-12", tasks_database=task_db, development_root=tmp_path
    )
    with closing(sqlite3.connect(task_db)) as connection:
        connection.execute(
            "UPDATE task_snapshots SET message='changed' WHERE task_id='active'"
        )
        connection.commit()
    with pytest.raises(ValueError, match="source database changed"):
        service.apply_typed_task_retention(
            plan,
            expected_plan_digest=str(plan["plan_digest"]),
            apply=True,
            allow_development_root_only=True,
            development_root=tmp_path,
        )
    with pytest.raises(ValueError, match="must be under"):
        service.preview_typed_task_retention(
            "line-12",
            tasks_database=task_db,
            development_root=tmp_path / "different-root",
        )
