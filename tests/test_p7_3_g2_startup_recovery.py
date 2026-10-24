from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api import main as backend_main
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.database_upgrade.journal import (
    DatabaseUpgradeJournal,
    recover_incomplete_upgrades,
)
from netconsole.services.site_package_staging import SitePackageStagingRecovery


def _database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        connection.commit()


def _journal_paths(paths: PathResolver, operation_id: str) -> tuple[Path, Path, Path]:
    active = paths.mesh_mr_db_path("demo", "profile")
    return (
        active,
        active.with_name(f"{active.name}.new.{operation_id}"),
        active.with_name(f"{active.name}.rollback.{operation_id}"),
    )


def test_corrupt_journal_is_detected_preserved_and_blocks_app_start(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    journal_path = paths.database_upgrade_journal_dir / "corrupt-operation.json"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text('{"operation_id": "corrupt-operation",', encoding="utf-8")
    before = journal_path.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_UPGRADE_JOURNAL_CORRUPT"
    assert journal_path.read_bytes() == before
    assert Path(result[0]["recovery_evidence_path"]).is_file()
    with pytest.raises(RuntimeError, match="DATABASE_STARTUP_RECOVERY_BLOCKED"):
        create_app(RuntimeMode.TEST, paths=paths)


def test_missing_authority_blocks_without_database_or_journal_mutation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "missing-authority")
    _database(active, "old")
    journal_path = paths.database_upgrade_journal_dir / "missing-authority.json"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "operation_id": "missing-authority",
        "schema_version": 1,
        "stage": "switched",
        "active_path": str(active),
        "shadow_path": str(shadow),
        "rollback_path": str(rollback),
        "database_kind": "mesh_derived",
        "scope_type": "site_profile",
        "scope_id": "demo:profile",
        "maintenance_lock": "database-upgrade:site_profile:demo:profile",
    }
    journal_path.write_text(json.dumps(payload), encoding="utf-8")
    journal_before = journal_path.read_bytes()
    database_before = active.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_STARTUP_AUTHORITY_REQUIRED"
    assert journal_path.read_bytes() == journal_before
    assert active.read_bytes() == database_before
    assert not shadow.exists()
    assert not rollback.exists()


def test_journal_artifact_tampering_is_rejected_before_mutation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "tampered-operation")
    _database(active, "old")
    journal = DatabaseUpgradeJournal(paths, "tampered-operation")
    journal.update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        maintenance_lock="database-upgrade:site_profile:demo:profile",
    )
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    payload["active_path"] = str(tmp_path / "outside.sqlite")
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    before = journal.path.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_RECOVERY_ARTIFACT_MISMATCH"
    assert journal.path.read_bytes() == before
    assert active.read_bytes()
    assert not (tmp_path / "outside.sqlite").exists()


def test_journal_artifact_key_deletion_is_rejected_before_mutation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "deleted-artifact")
    _database(active, "new")
    _database(rollback, "old")
    journal = DatabaseUpgradeJournal(paths, "deleted-artifact")
    journal.update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        maintenance_lock="database-upgrade:site_profile:demo:profile",
    )
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    del payload["rollback_path"]
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    before = active.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_RECOVERY_ARTIFACT_MISMATCH"
    assert active.read_bytes() == before
    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("new",)


def test_journal_backup_artifact_key_deletion_is_rejected_before_mutation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "deleted-backup-artifact")
    backup = paths.database_upgrade_backups_dir / "deleted-backup-artifact"
    backup.mkdir(parents=True)
    _database(active, "new")
    _database(rollback, "old")
    journal = DatabaseUpgradeJournal(paths, "deleted-backup-artifact")
    journal.update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        backup_path=str(backup),
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        maintenance_lock="database-upgrade:site_profile:demo:profile",
    )
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    del payload["backup_path"]
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    before = active.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_RECOVERY_ARTIFACT_MISMATCH"
    assert active.read_bytes() == before
    assert rollback.is_file()


def test_component_resume_with_switch_or_live_artifact_blocks_startup(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "component-resume-active")
    _database(active, "active")
    _database(shadow, "candidate")
    journal_path = paths.database_upgrade_journal_dir / "component-resume-active.json"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "operation_id": "component-resume-active",
                "stage": "switched",
                "recovery_strategy": "component_resume",
                "active_path": str(active),
                "shadow_path": str(shadow),
                "rollback_path": str(rollback),
                "switched": False,
            }
        ),
        encoding="utf-8",
    )
    journal_before = journal_path.read_bytes()
    active_before = active.read_bytes()
    shadow_before = shadow.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_COMPONENT_RESUME_ACTIVE"
    assert journal_path.read_bytes() == journal_before
    assert active.read_bytes() == active_before
    assert shadow.read_bytes() == shadow_before


def test_component_resume_active_database_is_not_mistaken_for_artifact(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, _shadow, _rollback = _journal_paths(paths, "component-resume-no-switch")
    _database(active, "active")
    journal_path = paths.database_upgrade_journal_dir / "component-resume-no-switch.json"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "operation_id": "component-resume-no-switch",
                "stage": "created",
                "recovery_strategy": "component_resume",
                "active_path": str(active),
                "switched": False,
            }
        ),
        encoding="utf-8",
    )

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "skipped"
    assert result[0]["recovery_status"] == "COMPONENT_RESUME_DELEGATED"
    assert active.is_file()


def test_parsed_artifact_tampering_is_rejected_before_mutation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "parsed-artifact")
    _database(active, "new")
    parsed_root = active.parent / "parsed"
    parsed_root.mkdir(parents=True, exist_ok=True)
    journal = DatabaseUpgradeJournal(paths, "parsed-artifact")
    journal.update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        maintenance_lock="database-upgrade:site_profile:demo:profile",
        adapter_state={
            "active_parsed_path": str(parsed_root / "active"),
            "shadow_parsed_path": str(parsed_root / "shadow"),
            "rollback_parsed_path": str(parsed_root / "rollback"),
        },
    )
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    payload["adapter_state"]["active_parsed_path"] = str(parsed_root / "other")
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    before = active.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_RECOVERY_PARSED_ARTIFACT_MISMATCH"
    assert active.read_bytes() == before


def test_parsed_artifact_key_deletion_is_rejected_before_mutation(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "deleted-parsed-artifact")
    _database(active, "new")
    parsed_root = active.parent / "parsed"
    parsed_root.mkdir(parents=True, exist_ok=True)
    journal = DatabaseUpgradeJournal(paths, "deleted-parsed-artifact")
    journal.update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        maintenance_lock="database-upgrade:site_profile:demo:profile",
        adapter_state={
            "active_parsed_path": str(parsed_root / "active"),
            "shadow_parsed_path": str(parsed_root / "shadow"),
            "rollback_parsed_path": str(parsed_root / "rollback"),
        },
    )
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    del payload["adapter_state"]["rollback_parsed_path"]
    journal.path.write_text(json.dumps(payload), encoding="utf-8")
    before = active.read_bytes()

    result = recover_incomplete_upgrades(paths)

    assert result[0]["status"] == "blocked"
    assert result[0]["recovery_block_code"] == "DATABASE_RECOVERY_PARSED_ARTIFACT_MISMATCH"
    assert active.read_bytes() == before


def test_authorized_recovery_is_idempotent_and_concurrency_safe(tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)
    active, shadow, rollback = _journal_paths(paths, "recoverable-operation")
    _database(active, "old")
    active.replace(rollback)
    _database(shadow, "new")
    shadow.replace(active)
    DatabaseUpgradeJournal(paths, "recoverable-operation").update(
        "switched",
        active_path=str(active),
        shadow_path=str(shadow),
        rollback_path=str(rollback),
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:profile",
        maintenance_lock="database-upgrade:site_profile:demo:profile",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _item: recover_incomplete_upgrades(paths), (1, 2)))

    recovered = [item for result in results for item in result if item.get("status") == "recovered"]
    assert len(recovered) == 1
    assert recovered[0]["stage"] == "recovered_rollback"
    assert all(item.get("status") != "blocked" for result in results for item in result)
    assert not recover_incomplete_upgrades(paths)
    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("old",)


def test_staging_partial_recovery_blocks_lifespan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    paths = PathResolver(data_root=tmp_path)

    def partial_recovery(_service) -> SitePackageStagingRecovery:
        return SitePackageStagingRecovery(failures=[{"code": "SYNTHETIC_FAILURE", "message": "fixture"}])

    monkeypatch.setattr(backend_main.SitePackageService, "recover_orphaned_staging", partial_recovery)
    app = create_app(RuntimeMode.TEST, paths=paths)

    with pytest.raises(RuntimeError, match="SITE_PACKAGE_STAGING_RECOVERY_BLOCKED"):
        with TestClient(app):
            pass

    assert (paths.runtime_dir / "database_upgrade_recovery_blocks").is_dir()
