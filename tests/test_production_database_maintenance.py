from __future__ import annotations

import gc
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.production_database_maintenance import (
    PRODUCTION_AUTHORIZATION_TOKEN,
    PRODUCTION_GATE_KEYS,
    ProductionMaintenanceCapability,
    ProductionMaintenanceError,
    ProductionHistoryRetirementExecutor,
    ProductionRollbackOwner,
    build_exact_manifest,
    write_exact_manifest,
)
from netconsole.services.database_footprint_maintenance import sqlite_quick_profile
from netconsole.services.database_upgrade.sqlite_consistency import sqlite_backup
from netconsole.repositories.task_repository import TaskRepository
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from scripts.maintenance.production_database_maintenance import main as production_main


HEAD = "ce2f0d98f9e8305b36a004ef0b7bdbc6fd2ad237"
ROOT = Path(__file__).resolve().parents[1]


def _site(tmp_path: Path) -> tuple[PathResolver, Path, Path]:
    root = tmp_path / "data"
    site = root / "sites" / "宁波地铁12号线"
    site.mkdir(parents=True)
    (site / "db").mkdir()
    for name in ("devices.db", "tasks.db"):
        with closing(sqlite3.connect(site / "db" / name)) as connection:
            connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT INTO records(value) VALUES (?)", [("a",), ("b",)])
            connection.commit()
    config = root / "config"
    config.mkdir()
    (config / "application.json").write_text(
        json.dumps({"current_site": "legacy-dfd356e96ea0"}), encoding="utf-8"
    )
    (config / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "legacy-dfd356e96ea0",
                        "display_name": "宁波地铁12号线",
                        "relative_path": "sites/宁波地铁12号线",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return PathResolver(data_root=root), site, root


def _owner(
    database: str,
    *,
    operation_id: str,
    source_identity: str,
    source_sha256: str,
    schema_fingerprint: str,
    backup_sha256: str,
    backup_size: int,
    backup_relative_path: str,
) -> ProductionRollbackOwner:
    return ProductionRollbackOwner(
        backup_set_id=f"verified-{database}",
        site_id="legacy-dfd356e96ea0",
        operation_id=operation_id,
        database=database,
        source_identity=source_identity,
        source_sha256=source_sha256,
        source_revision=source_sha256,
        created_at="2026-08-17T00:00:00Z",
        verified_at="2026-08-17T00:00:01Z",
        quick_check="ok",
        schema_fingerprint=schema_fingerprint,
        rollback_required=True,
        observation_state="VERIFIED",
        superseded_by="",
        retire_state="PROTECT",
        backup_sha256=backup_sha256,
        backup_size=backup_size,
        backup_relative_path=backup_relative_path,
    )


def _backup(paths: PathResolver, database: str) -> tuple[Path, dict[str, object]]:
    site = paths.data_root / "sites" / "宁波地铁12号线"
    backup_set_id = f"verified-{database}"
    relative = (
        Path("files")
        / "backups"
        / "production-maintenance"
        / backup_set_id
        / "database.sqlite"
    )
    target = site / relative
    if not target.exists():
        sqlite_backup(site / "db" / database, target)
    return target, {
        "relative": relative.as_posix(),
        **sqlite_quick_profile(target, immutable=True),
    }


def _capability(
    paths: PathResolver,
    *,
    operation_id: str = "test-operation",
    source_identity: str = "snapshot-identity",
) -> ProductionMaintenanceCapability:
    site = paths.data_root / "sites" / "宁波地铁12号线" / "db"
    profiles = {
        name: sqlite_quick_profile(site / name, immutable=True)
        for name in ("devices.db", "tasks.db")
    }
    backups = {
        name: _backup(paths, name)[1]
        for name in ("devices.db", "tasks.db")
    }
    return ProductionMaintenanceCapability(
        paths,
        site_id="legacy-dfd356e96ea0",
        authoritative_git_head=HEAD,
        rollback_owners={
            ("legacy-dfd356e96ea0", "devices.db"): _owner(
                "devices.db",
                operation_id=operation_id,
                source_identity=source_identity,
                source_sha256=profiles["devices.db"]["sha256"],
                schema_fingerprint=profiles["devices.db"]["schema_digest"],
                backup_sha256=backups["devices.db"]["sha256"],
                backup_size=backups["devices.db"]["size_bytes"],
                backup_relative_path=backups["devices.db"]["relative"],
            ),
            ("legacy-dfd356e96ea0", "tasks.db"): _owner(
                "tasks.db",
                operation_id=operation_id,
                source_identity=source_identity,
                source_sha256=profiles["tasks.db"]["sha256"],
                schema_fingerprint=profiles["tasks.db"]["schema_digest"],
                backup_sha256=backups["tasks.db"]["sha256"],
                backup_size=backups["tasks.db"]["size_bytes"],
                backup_relative_path=backups["tasks.db"]["relative"],
            ),
        },
    )


def _manifest(tmp_path: Path, database: Path, *, candidate: Path | None = None) -> Path:
    value = build_exact_manifest(
        database,
        candidate=candidate or database,
        site_id="legacy-dfd356e96ea0",
        row_identity={"table": "records", "key": "id"},
        expected_count=2,
        generated_git_head=HEAD,
        plan_kind="test",
    )
    return write_exact_manifest(tmp_path / "manifest.json", value)


def _candidate(paths: PathResolver, operation_id: str, database: str) -> Path:
    path = (
        paths.staging_dir
        / "production-maintenance"
        / operation_id
        / f"{database}.candidate"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _gates() -> dict[str, bool]:
    return {key: True for key in PRODUCTION_GATE_KEYS}


def test_history_retirement_resume_proof_requires_a_planned_missing_prefix() -> None:
    planned = [1, 2, 3, 4]
    assert ProductionHistoryRetirementExecutor._resume_absent_count(
        planned,
        [3, 4],
        rows_before=4,
        before_count=2,
    ) == 2
    with pytest.raises(ProductionMaintenanceError, match="out-of-plan"):
        ProductionHistoryRetirementExecutor._resume_absent_count(
            planned,
            [1, 3, 4],
            rows_before=4,
            before_count=3,
        )


def _promoted_manifest(
    capability: ProductionMaintenanceCapability,
    manifest: Path,
    candidate: Path,
    *,
    operation_id: str,
) -> Path:
    database = str(json.loads(manifest.read_text(encoding="utf-8"))["database"])
    result = capability.promote_executable_manifest(
        manifest,
        operation_id=operation_id,
        candidate=candidate,
        rollback_owner=capability._owner(database),
        history_state="COMPLETED" if database == "devices.db" else "NOT_APPLICABLE",
        task_state="RESULT_REF_AUTHORITY" if database == "tasks.db" else "NOT_APPLICABLE",
        retirement_state="COMPLETED",
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        gates=_gates(),
    )
    return Path(str(result["path"]))


def test_production_capability_requires_exact_allowlist(tmp_path: Path) -> None:
    paths, _, _ = _site(tmp_path)
    with pytest.raises(ProductionMaintenanceError, match="allowlist"):
        ProductionMaintenanceCapability(
            paths,
            site_id="other-site",
            authoritative_git_head=HEAD,
        )


def test_storage_registry_has_protected_pending_production_rollback_owners() -> None:
    owners = ProductionMaintenanceCapability.load_rollback_owners(
        ROOT / "config" / "storage_registry.yaml"
    )
    assert set(owners) == {
        ("legacy-dfd356e96ea0", "devices.db"),
        ("legacy-dfd356e96ea0", "tasks.db"),
    }
    assert all(owner.retire_state == "PROTECT" for owner in owners.values())
    assert all(owner.observation_state == "PENDING_PRODUCTION_BACKUP" for owner in owners.values())
    assert not any(owner.verified() for owner in owners.values())


def test_rollback_bootstrap_creates_and_reuses_verified_runtime_evidence(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    database = site / "db" / "devices.db"
    profile = sqlite_quick_profile(database)
    relative = (
        Path("files")
        / "backups"
        / "production-maintenance"
        / "pending-devices"
        / "database.sqlite"
    )
    contract = ProductionRollbackOwner(
        backup_set_id="pending-devices",
        site_id="legacy-dfd356e96ea0",
        operation_id="PENDING_PRODUCTION_CUTOVER",
        database="devices.db",
        source_identity="",
        source_sha256=str(profile["sha256"]),
        source_revision=str(profile["sha256"]),
        created_at="",
        verified_at="",
        quick_check="pending",
        schema_fingerprint=str(profile["schema_digest"]),
        rollback_required=True,
        observation_state="PENDING_PRODUCTION_BACKUP",
        superseded_by="",
        retire_state="PROTECT",
        backup_relative_path=relative.as_posix(),
    )
    capability = ProductionMaintenanceCapability(
        paths,
        site_id="legacy-dfd356e96ea0",
        authoritative_git_head=HEAD,
        rollback_owners={("legacy-dfd356e96ea0", "devices.db"): contract},
    )

    first = capability.bootstrap_rollback(
        "devices.db",
        owner_contract=contract,
        operation_id="bootstrap-devices",
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
    )
    second = capability.bootstrap_rollback(
        "devices.db",
        owner_contract=contract,
        operation_id="bootstrap-devices",
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
    )

    assert first == second
    assert first.verified() is True
    rollback = site / relative
    assert sqlite_quick_profile(rollback)["table_counts"] == profile["table_counts"]
    assert rollback.with_name("rollback-owner-bootstrap-devices.json").is_file()


def test_manifest_stays_not_executable_until_current_gates_are_promoted(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "manifest-promotion", "devices.db")
    sqlite_backup(active, candidate)
    manifest = _manifest(tmp_path, active, candidate=candidate)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    capability = _capability(
        paths,
        operation_id="manifest-promotion",
        source_identity=str(raw["database_identity"]),
    )
    assert raw["execution_status"] == "NOT_EXECUTABLE"
    assert raw["blocking_prerequisites"]
    with pytest.raises(ProductionMaintenanceError, match="promotion blocked"):
        capability.promote_executable_manifest(
            manifest,
            operation_id="manifest-promotion",
            candidate=candidate,
            rollback_owner=capability._owner("devices.db"),
            history_state="COMPLETED",
            task_state="NOT_APPLICABLE",
            retirement_state="COMPLETED",
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates={**_gates(), "restart": False},
        )
    assert not (
        paths.staging_dir
        / "production-maintenance"
        / "manifest-promotion"
        / "devices.db.executable-manifest.json"
    ).exists()


def test_execute_cutover_chain_reaches_executable_without_replacing_tasks_db(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    tasks = site / "db" / "tasks.db"
    TaskRepository(tasks)
    with closing(sqlite3.connect(tasks)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    capability = _capability(
        paths,
        operation_id="chain-tasks",
        source_identity="chain-tasks-source",
    )
    owner = capability._rollback_owners[("legacy-dfd356e96ea0", "tasks.db")]
    before = sqlite_quick_profile(tasks, immutable=True)
    gc.collect()

    result = capability.execute_cutover_chain(
        "tasks.db",
        operation_id="chain-tasks",
        owner_contract=owner,
        row_identity={"table": "records", "key": "id"},
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        gates=_gates(),
        perform_replace=False,
    )

    assert result["status"] == "EXECUTABLE"
    assert result["replacement_performed"] is False
    assert result["task"]["status"] == "COMPLETED"
    assert result["task"]["authority"]["state"] == "RESULT_REF_AUTHORITY"
    manifest = result["manifest"]["manifest"]
    assert manifest["execution_status"] == "EXECUTABLE"
    assert sqlite_quick_profile(tasks, immutable=True)["sha256"] != before["sha256"]


def test_execute_cutover_chain_protects_invalid_task_rows(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    tasks = site / "db" / "tasks.db"
    repository = TaskRepository(tasks)
    timestamp = "2026-08-16T03:00:00Z"
    snapshot = TaskSnapshot(
        task_id="invalid-terminal",
        task_type="device_connection_test",
        task_name="Invalid terminal",
        status=TaskState.CANCELLED,
        created_time=timestamp,
        finished_time=timestamp,
        updated_time=timestamp,
        result={},
    )
    event = TaskEvent(
        event_id="invalid-terminal-cancelled",
        task_id=snapshot.task_id,
        type="cancelled",
        time=timestamp,
        source="test",
        payload={"message": "cancelled"},
    )
    assert repository.record(snapshot, event)
    with closing(sqlite3.connect(tasks)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    del repository
    gc.collect()
    capability = _capability(
        paths,
        operation_id="chain-tasks-invalid-protected",
        source_identity="chain-tasks-invalid-protected-source",
    )
    owner = capability._rollback_owners[("legacy-dfd356e96ea0", "tasks.db")]

    result = capability.execute_cutover_chain(
        "tasks.db",
        operation_id="chain-tasks-invalid-protected",
        owner_contract=owner,
        row_identity={"table": "records", "key": "id"},
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        gates=_gates(),
        perform_replace=False,
    )

    assert result["status"] == "EXECUTABLE"
    assert result["task"]["authority"]["state"] == "RESULT_REF_AUTHORITY"
    assert result["task"]["protected_invalid_count"] == 1
    with closing(sqlite3.connect(tasks)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 0
        assert connection.execute(
            "SELECT result_json FROM task_snapshots WHERE task_id='invalid-terminal'"
        ).fetchone()[0] == "{}"


def test_preflight_rejects_stale_source_and_requires_production_mode(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    manifest = _manifest(tmp_path, site / "db" / "devices.db")
    with closing(sqlite3.connect(site / "db" / "devices.db")) as connection:
        connection.execute("INSERT INTO records(value) VALUES ('changed')")
        connection.commit()
    capability = _capability(paths)
    with pytest.raises(ProductionMaintenanceError, match="mode=production"):
        capability.preflight(
            manifest,
            mode="development",
            writer_quiescent=True,
            gates=_gates(),
        )
    with pytest.raises(ProductionMaintenanceError, match="STALE_SOURCE"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )


def test_preflight_rejects_tampered_manifest_missing_owner_and_active_writer(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    manifest = _manifest(tmp_path, site / "db" / "devices.db")
    without_owner = ProductionMaintenanceCapability(
        paths,
        site_id="legacy-dfd356e96ea0",
        authoritative_git_head=HEAD,
    )
    with pytest.raises(ProductionMaintenanceError, match="owner is not registered"):
        without_owner.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )
    capability = _capability(paths)
    with pytest.raises(ProductionMaintenanceError, match="quiescence"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=False,
            gates=_gates(),
        )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["expected_count"] = 3
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ProductionMaintenanceError, match="STALE_PLAN"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )


def test_execute_replace_requires_explicit_authorization_and_supports_rollback(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-replace", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    capability = _capability(
        paths,
        operation_id="op-replace",
        source_identity=source_identity,
    )
    rollback_path = _backup(paths, "devices.db")[0]
    rollback_sha = sqlite_quick_profile(rollback_path)["sha256"]
    with pytest.raises(ProductionMaintenanceError, match="authorization"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization="",
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-no-auth",
            restart_verifier=lambda: True,
            functional_gate=lambda: True,
        )
    manifest = _promoted_manifest(
        capability, manifest, candidate, operation_id="op-replace"
    )
    result = capability.execute_replace(
        manifest,
        candidate=candidate,
        rollback=rollback_path,
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        gates=_gates(),
        operation_id="op-replace",
        restart_verifier=lambda: True,
        functional_gate=lambda: True,
    )
    assert result["replaced"] is True
    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "candidate"
    restored = capability.rollback(
        "devices.db",
        rollback_path,
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        operation_id="op-rollback",
    )
    assert restored["rolled_back"] is True
    assert rollback_path.is_file()
    assert sqlite_quick_profile(rollback_path)["sha256"] == rollback_sha
    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2


def test_post_switch_restart_failure_rolls_back_and_finalizes_journal(tmp_path: Path) -> None:
    paths, site, root = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-restart-failure", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    capability = _capability(
        paths,
        operation_id="op-restart-failure",
        source_identity=source_identity,
    )
    rollback_path = _backup(paths, "devices.db")[0]
    rollback_sha = sqlite_quick_profile(rollback_path)["sha256"]
    manifest = _promoted_manifest(
        capability,
        manifest,
        candidate,
        operation_id="op-restart-failure",
    )

    with pytest.raises(ProductionMaintenanceError, match="rollback completed"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-restart-failure",
            restart_verifier=lambda: False,
            functional_gate=lambda: True,
        )

    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM records ORDER BY id").fetchall() == [
            ("a",),
            ("b",),
        ]
    journal = json.loads(
        (root / "runtime" / "database_upgrade" / "op-restart-failure.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["stage"] == "failed_rolled_back"
    assert journal["rollback_performed"] is True
    assert rollback_path.is_file()
    assert sqlite_quick_profile(rollback_path)["sha256"] == rollback_sha


def test_execute_rejects_candidate_content_drift_with_same_total_rows(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-candidate-drift", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    capability = _capability(
        paths,
        operation_id="op-candidate-drift",
        source_identity=source_identity,
    )
    rollback_path = _backup(paths, "devices.db")[0]
    active_sha = sqlite_quick_profile(active)["sha256"]
    manifest = _promoted_manifest(
        capability,
        manifest,
        candidate,
        operation_id="op-candidate-drift",
    )
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("UPDATE records SET value = 'drifted' WHERE id = 1")
        connection.commit()

    with pytest.raises(ProductionMaintenanceError, match="candidate identity mismatch"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-candidate-drift",
            restart_verifier=lambda: True,
            functional_gate=lambda: True,
        )

    assert sqlite_quick_profile(active)["sha256"] == active_sha


def test_preflight_uses_immutable_reads_and_rejects_nonempty_wal(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    manifest = _manifest(tmp_path, active)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    capability = _capability(paths, source_identity=source_identity)
    wal = active.with_name(f"{active.name}-wal")
    shm = active.with_name(f"{active.name}-shm")
    assert not wal.exists()
    assert not shm.exists()

    capability.preflight(
        manifest,
        mode="production",
        writer_quiescent=True,
        gates=_gates(),
    )
    assert not wal.exists()
    assert not shm.exists()

    wal.write_bytes(b"active-wal")
    with pytest.raises(ProductionMaintenanceError, match="sidecars are active"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )
    assert wal.read_bytes() == b"active-wal"
    assert not shm.exists()


def test_manifest_cli_refuses_conflicting_or_existing_output(tmp_path: Path) -> None:
    _paths, site, root = _site(tmp_path)
    source = site / "db" / "devices.db"
    manifest = root / "manifest.json"
    common = [
        "manifest",
        "--data-root",
        str(root),
        "--site-id",
        "legacy-dfd356e96ea0",
        "--source",
        str(source),
        "--candidate",
        str(source),
        "--manifest",
        str(manifest),
        "--git-head",
        HEAD,
        "--expected-count",
        "2",
        "--row-identity",
        "table=records",
        "--row-identity",
        "key=id",
    ]

    with pytest.raises(SystemExit, match="must differ"):
        production_main([*common, "--output", str(manifest)])
    assert not manifest.exists()

    output = root / "existing-output.json"
    output.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="output already exists"):
        production_main([*common, "--output", str(output)])
    assert output.read_text(encoding="utf-8") == "preserve"
    assert not manifest.exists()
