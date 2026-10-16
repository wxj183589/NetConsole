from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.application.rail_transit.base_data_application_service import (
    RailTransitBaseDataApplicationService,
)
from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import ImportPreviewRowDTO
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataRepository,
)
from netconsole.services.database_upgrade import history as history_module
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.coordinator import (
    DatabaseUpgradeCoordinator,
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.database_upgrade.history import LegacyDatabaseArchiveService
from netconsole.services.database_upgrade.management_service import (
    DatabaseUpgradeManagementService,
)
from netconsole.services.database_upgrade.models import (
    DatabaseDescriptor,
    DatabaseUpgradeStrategy,
)
from netconsole.services.rail_transit.base_data_import_service import (
    RailTransitBaseDataImportService,
)
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard
from tests.support.rail_transit_base_data_fixture import (
    build_rail_transit_base_data_fixture,
    mark_base_data_copy,
)


def _write_guard(paths: object, *, rollback_enabled: bool = True) -> BaseDataWriteGuard:
    return BaseDataWriteGuard(
        paths,  # type: ignore[arg-type]
        feature_enabled=True,
        write_enabled=True,
        copy_write_enabled=True,
        rollback_enabled=rollback_enabled,
    )


def _base_service(paths: object) -> RailTransitBaseDataApplicationService:
    return RailTransitBaseDataApplicationService(
        paths,  # type: ignore[arg-type]
        RailTransitBaseDataQueryService(paths),  # type: ignore[arg-type]
        _write_guard(paths),
        RailTransitBaseDataRepository(paths),  # type: ignore[arg-type]
    )


def _import_service(paths: object) -> RailTransitBaseDataImportService:
    return RailTransitBaseDataImportService(
        paths,  # type: ignore[arg-type]
        repository=RailTransitBaseDataRepository(paths),  # type: ignore[arg-type]
        guard=_write_guard(paths),  # type: ignore[arg-type]
    )


def _assert_waits_for_site_lock(paths, operation) -> None:
    finished = threading.Event()
    errors: list[Exception] = []

    def run() -> None:
        try:
            operation()
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            finished.set()

    with database_maintenance_lock(paths, site_database_maintenance_key("demo")):
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert not finished.wait(0.2)
    assert finished.wait(10)
    worker.join(timeout=1)
    assert not errors, errors


def test_base_data_save_and_clear_share_site_maintenance_lock(tmp_path: Path) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    service = _base_service(paths)

    revision = service.repository.base_data_revision("demo")
    _assert_waits_for_site_lock(
        paths,
        lambda: service.save_changes(
            "demo",
            revision,
            [],
            explicit_confirmation=True,
        ),
    )

    revision = service.repository.base_data_revision("demo")
    _assert_waits_for_site_lock(
        paths,
        lambda: service.clear_all("demo", revision, explicit_confirmation=True),
    )


def _build_plan(service: RailTransitBaseDataImportService):
    return service.build_merge_plan(
        site_id="demo",
        rows=[
            ImportPreviewRowDTO(
                row_number=1,
                values={"ap_name": "AP-New-Phase2D", "ap_mac_norm": "001122334499"},
            )
        ],
        source_file_name="isolated-phase2d.xlsx",
        source_file_sha256="d" * 64,
    )


def test_base_data_import_and_rollback_share_site_maintenance_lock(tmp_path: Path) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    service = _import_service(paths)
    plan = _build_plan(service)

    _assert_waits_for_site_lock(
        paths,
        lambda: service.apply_merge_plan(plan, confirmed=True, owner="phase2d-test"),
    )
    audit = service.get_operation("demo", plan.plan_id)
    assert audit.status == "APPLIED"

    _assert_waits_for_site_lock(
        paths,
        lambda: service.rollback_import(
            site_id="demo",
            operation_id=plan.plan_id,
            explicit_confirmation=True,
        ),
    )
    assert service.get_operation("demo", plan.plan_id).status == "ROLLED_BACK"


def _create_marker_database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (value,))
        connection.commit()


def test_backup_same_size_and_mtime_tamper_is_rejected(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(data_root=tmp_path)
    source = tmp_path / "source.sqlite"
    _create_marker_database(source, "old")
    backup = DatabaseBackupStore(paths).create(
        source_path=source,
        database_kind="test_database",
        scope_type="global",
        scope_id="phase2d",
        task_id="phase2d-backup",
        old_version="v1",
        target_version="v2",
        strategy="TEST",
    )
    database = Path(str(backup["path"])) / "database.sqlite"
    stat = database.stat()
    replaced = database.read_bytes().replace(b"old", b"new", 1)
    assert len(replaced) == stat.st_size
    database.write_bytes(replaced)
    os.utime(database, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    result = DatabaseBackupStore(paths).validate(str(backup["backup_id"]))

    assert result["validation"]["size_matches"] is True
    assert result["validation"]["sha256_matches"] is False
    assert result["result_status"] == "INVALID_DATABASE"


def test_legacy_archive_content_race_is_marked_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(data_root=tmp_path)
    profile_root = paths.site_mesh_root("demo") / "profile"
    profile_root.mkdir(parents=True)
    source = profile_root / "mesh.sqlite.schema_archive_race"
    _create_marker_database(source, "old")
    replacement = source.read_bytes().replace(b"old", b"new", 1)
    original_move = history_module.shutil.move

    def race_before_move(src: str, dst: str):
        Path(src).write_bytes(replacement)
        return original_move(src, dst)

    monkeypatch.setattr(history_module.shutil, "move", race_before_move)
    result = LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")

    assert result["moved_count"] == 1
    item = result["items"][0]
    assert item["result_status"] == "INVALID_DATABASE"
    assert item["integrity_check_result"]["size_matches"] is True
    assert item["integrity_check_result"]["sha256_matches"] is False


def test_legacy_archive_does_not_follow_nested_reparse_point(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(data_root=tmp_path)
    outside_profile = tmp_path / "outside" / "profile"
    outside_profile.mkdir(parents=True)
    outside_archive = outside_profile / "mesh.sqlite.schema_archive_outside"
    _create_marker_database(outside_archive, "outside")
    root = paths.site_mesh_root("demo")
    root.mkdir(parents=True)
    os.symlink(outside_profile, root / "linked-profile", target_is_directory=True)

    result = LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")

    assert result["found_count"] == 0
    assert outside_archive.is_file()


def test_legacy_archive_rejects_reparse_point_at_mesh_root(tmp_path: Path) -> None:
    from netconsole.core.paths import PathResolver

    paths = PathResolver(data_root=tmp_path)
    outside_root = tmp_path / "outside-mesh"
    outside_root.mkdir(parents=True)
    outside_archive = outside_root / "mesh.sqlite.schema_archive_outside"
    _create_marker_database(outside_archive, "outside")
    raw_root = paths.site_mesh_root("demo")
    raw_root.parent.mkdir(parents=True)
    os.symlink(outside_root, raw_root, target_is_directory=True)

    result = LegacyDatabaseArchiveService(paths).organize_mesh_archives("demo")

    assert result["found_count"] == 0
    assert outside_archive.is_file()


def test_gui_database_maintenance_does_not_require_cli_write_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "runtime_mode.json").write_text(
        '{"mode":"production","readonly_warning":true}',
        encoding="utf-8",
    )
    paths = PathResolver(data_root=tmp_path)
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)

    service = DatabaseUpgradeManagementService(paths)
    monkeypatch.setattr(
        service.history,
        "organize_mesh_archives",
        lambda site_id: {"site_id": site_id, "moved_count": 0},
    )
    assert service.organize_legacy("demo") == {"site_id": "demo", "moved_count": 0}

    marker = object()

    def fake_upgrade_locked(self, descriptor, **kwargs):
        assert descriptor.database_path == tmp_path / "active.sqlite"
        return marker

    monkeypatch.setattr(DatabaseUpgradeCoordinator, "_upgrade_locked", fake_upgrade_locked)
    descriptor = DatabaseDescriptor(
        database_kind="test",
        scope_type="global",
        scope_id="phase2d-gui",
        database_path=tmp_path / "active.sqlite",
        target_version="v2",
        strategy=DatabaseUpgradeStrategy.SCHEMA_MIGRATION,
        adapter=object(),
    )
    assert DatabaseUpgradeCoordinator(paths).upgrade(descriptor) is marker
