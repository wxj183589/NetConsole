from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.mesh_storage_service import MeshStorageService


TOKEN = "database-upgrade-session-token-123456"


class _ProcessAdapter:
    def __init__(self) -> None:
        self.jobs = []

    def start_job(self, job) -> None:
        self.jobs.append(job)

    def cancel_job(self, _task_id: str) -> bool:
        return True


def _client(tmp_path: Path) -> tuple[TestClient, PathResolver, _ProcessAdapter]:
    paths = PathResolver(app_root=tmp_path / "app", data_root=tmp_path / "data")
    app = create_app(RuntimeMode.DESKTOP, paths=paths, desktop_session_token=TOKEN)
    process = _ProcessAdapter()
    app.state.site_process_adapter = process
    return (
        TestClient(app, base_url="http://127.0.0.1", headers={"X-NetConsole-Session": TOKEN}),
        paths,
        process,
    )


def test_database_status_and_upgrade_submission_are_scoped_to_current_site(tmp_path: Path) -> None:
    client, paths, process = _client(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("列车07-MR-CT")
    database = paths.mesh_mr_db_path("demo", profile.safe_folder_name)
    MeshMrRepository(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE schema_meta SET value = 'old' WHERE key = 'schema_version'")
        connection.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        connection.commit()

    status = client.get("/api/database-upgrades")
    assert status.status_code == 200, status.text
    assert status.json()["site_id"] == "demo"
    assert status.json()["databases"][0]["needs_upgrade"] is True

    submitted = client.post("/api/database-upgrades/upgrade", json={"database_kind": "mesh_derived", "profile_id": profile.mr_id})
    assert submitted.status_code == 202, submitted.text
    assert process.jobs[-1].task_type == "database_upgrade"
    assert process.jobs[-1].params["site_id"] == "demo"
    assert process.jobs[-1].params["profile_id"] == profile.mr_id
    assert process.jobs[-1].params["owner"] == "database-upgrade"


def test_restore_and_delete_require_confirmation_and_submit_backup_id_only(tmp_path: Path) -> None:
    client, paths, process = _client(tmp_path)
    database = tmp_path / "data" / "sites" / "demo" / "files" / "mesh.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.commit()
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="demo:列车07-MR-CT",
        task_id="seed",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_id = str(backup["backup_id"])

    assert client.post(f"/api/database-upgrades/backups/{backup_id}/restore", json={"confirmed": False}).status_code == 422
    restored = client.post(f"/api/database-upgrades/backups/{backup_id}/restore", json={"confirmed": True})
    assert restored.status_code == 202, restored.text
    assert process.jobs[-1].params == {
        "backup_id": backup_id,
        "confirmed": True,
        "site_name": "demo",
        "task_name": "恢复数据库备份",
        "owner": "database-upgrade",
        "resource_keys": [f"database-backup:{backup_id}", "mesh-import:demo"],
        "resource_conflict_message": "当前数据库或备份已有维护任务正在执行",
    }

    assert client.post(f"/api/database-upgrades/backups/{backup_id}/delete", json={"confirmed": False}).status_code == 422
    deleted = client.post(f"/api/database-upgrades/backups/{backup_id}/delete", json={"confirmed": True})
    assert deleted.status_code == 202, deleted.text
    assert process.jobs[-1].params["backup_id"] == backup_id


def test_backup_actions_reject_a_backup_from_another_site(tmp_path: Path) -> None:
    client, paths, process = _client(tmp_path)
    database = tmp_path / "data" / "sites" / "other" / "files" / "mesh.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.commit()
    backup = DatabaseBackupStore(paths).create(
        source_path=database,
        database_kind="mesh_derived",
        scope_type="site_profile",
        scope_id="other:列车01-MR-CT",
        task_id="seed",
        old_version="old",
        target_version="new",
        strategy="SCHEMA_MIGRATION",
    )
    backup_id = str(backup["backup_id"])

    assert client.post(f"/api/database-upgrades/backups/{backup_id}/validate").status_code == 404
    assert client.post(
        f"/api/database-upgrades/backups/{backup_id}/restore",
        json={"confirmed": True},
    ).status_code == 404
    assert client.post(
        f"/api/database-upgrades/backups/{backup_id}/delete",
        json={"confirmed": True},
    ).status_code == 404
    assert process.jobs == []
