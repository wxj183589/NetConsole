from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import netconsole.backend.api.main as backend_main
import netconsole.core.paths as paths_module
import netconsole.core.runtime_environment as runtime_environment
import netconsole.services.ap_identity.query_service as ap_identity_query_service_module
import netconsole.services.production_database_maintenance as production_module
import scripts.backfill_ap_optical_treatment_events as optical_backfill
import scripts.maintenance.backfill_trackside_ap_station_identity as station_backfill
import scripts.maintenance.upgrade_ap_extension_schema as ap_schema
import scripts.maintenance.upgrade_task_cleanup_schema as task_schema
from netconsole.core.database import (
    CURRENT_SCHEMA_VERSION,
    Database,
    DatabaseMaintenanceRequiredError,
)
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.core.runtime_environment import (
    ProductionWriteBlockedError,
    require_non_production_data_root,
    write_data_environment,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.production_database_maintenance import (
    ProductionMaintenanceError,
)


def _production_info() -> DataEnvironmentInfo:
    return DataEnvironmentInfo(
        DataEnvironmentMode.PRODUCTION,
        created_from="p7-test-fixture",
        readonly_warning=True,
    )


def _registry(root: Path, *, site_id: str = "sxl1", directory: str | None = None) -> Path:
    directory = directory or site_id
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    path = config / "site_registry.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": site_id,
                        "display_name": production_module.PRODUCTION_SITE_ALLOWLIST[site_id],
                        "relative_path": f"sites/{directory}",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _database(root: Path, site_id: str = "sxl1") -> Path:
    path = root / "sites" / site_id / "db" / "devices.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    Database(path).initialize()
    return path


def _production_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _production_info()
    monkeypatch.setattr(ap_schema, "data_environment", lambda _root: info)
    monkeypatch.setattr(runtime_environment, "data_environment", lambda _root=None: info)
    monkeypatch.setattr(paths_module, "data_environment", lambda _root=None: info)


def _production_identity_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            INSERT INTO ap_extension_points (
                site_id, station_id, station_name, section_id, section_name,
                ap_point_code, ap_name, ap_vendor, ap_mac_norm, ap_mac_display,
                created_at, updated_at
            ) VALUES (
                'sxl1', 'station-1', 'Station 1', 'section-1', 'Section 1',
                'AP-001', 'AP 001', 'H3C', '487397cce9af', '4873-97cc-e9af',
                '2026-09-22T00:00:00Z', '2026-09-22T00:00:00Z'
            )
            """
        )
        connection.commit()
    return root, database


def _initialize_production_fixture(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _production_patches(monkeypatch)
    monkeypatch.setattr(
        backend_main,
        "_recover_orphaned_collect_runs",
        lambda *_args, **_kwargs: [],
    )
    backend_main._initialize_active_site_database(
        PathResolver(data_root=root),
        "sxl1",
        production_site_id="sxl1",
    )


def _source_snapshot(database: Path) -> tuple[object, ...]:
    with closing(sqlite3.connect(database)) as connection:
        source_rows = connection.execute(
            """
            SELECT id, site_id, station_id, ap_name, ap_mac_norm,
                   ap_mac_display, updated_at
            FROM ap_extension_points
            ORDER BY id
            """
        ).fetchall()
        source_revision = connection.execute(
            """
            SELECT site_id, revision, updated_at
            FROM ap_identity_source_state
            ORDER BY site_id
            """
        ).fetchall()
    return tuple(source_rows), tuple(source_revision)


def _identity_index_snapshot(database: Path) -> tuple[object, ...]:
    tables = (
        "ap_identity_entities",
        "ap_identity_mac_aliases",
        "ap_identity_h3c_prefixes",
        "ap_identity_conflicts",
        "ap_identity_index_state",
    )
    with closing(sqlite3.connect(database)) as connection:
        return tuple(
            (
                table,
                tuple(
                    connection.execute(
                        f"SELECT * FROM {table} ORDER BY 1"
                    ).fetchall()
                ),
            )
            for table in tables
        )


def test_test_mode_cannot_downgrade_production_or_escape_isolated_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")
    marked_production = tmp_path / "marked-production"
    write_data_environment(
        marked_production,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    with pytest.raises(ProductionWriteBlockedError, match="Production"):
        require_non_production_data_root(marked_production, "p7-test")

    with pytest.raises(ProductionWriteBlockedError, match="非隔离"):
        require_non_production_data_root(Path(__file__).resolve().parents[1], "p7-test")


def test_ap_schema_reads_production_marker_even_in_test_process_mode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "marked-production"
    _registry(root)
    database = _database(root)
    write_data_environment(
        root,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    before = database.read_bytes()

    assert ap_schema.main(
        ["--data-dir", str(root), "--site", "sxl1"]
    ) == 1
    assert database.read_bytes() == before


def test_ap_schema_production_uses_canonical_site_and_identity_bound_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_metadata SET value=? WHERE key='schema_version'",
            ("2026.06.23.device_ap_rebuild_mac",),
        )
        connection.execute("DROP TABLE ap_extension_points")
        connection.execute("DROP TABLE ap_extension_import_batches")
        connection.commit()
    _production_patches(monkeypatch)

    assert ap_schema.main(
        [
            "--data-dir",
            str(root),
            "--site",
            "sxl1",
            "--allow-production-write",
            "--operation-id",
            "p7-schema-test",
        ]
    ) == 0
    backups = list(database.parent.glob("devices.before_ap_extension_schema_*.db"))
    assert len(backups) == 1
    evidence = backups[0].with_suffix(backups[0].suffix + ".json")
    assert json.loads(evidence.read_text(encoding="utf-8"))["site_id"] == "sxl1"
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_ap_schema_backup_captures_committed_wal_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            """
            INSERT INTO devices (
                device_uuid, name, primary_address, created_at, updated_at
            ) VALUES ('wal-device', 'WAL device', '192.0.2.10', 'now', 'now')
            """
        )
        connection.execute(
            "UPDATE schema_metadata SET value=? WHERE key='schema_version'",
            ("2026.06.23.device_ap_rebuild_mac",),
        )
        connection.execute("DROP TABLE ap_extension_points")
        connection.execute("DROP TABLE ap_extension_import_batches")
        connection.commit()
        wal_path = Path(f"{database}-wal")
        assert wal_path.is_file() and wal_path.stat().st_size > 0

        _production_patches(monkeypatch)
        assert ap_schema.main(
            [
                "--data-dir",
                str(root),
                "--site",
                "sxl1",
                "--allow-production-write",
                "--operation-id",
                "p7-wal-schema-test",
            ]
        ) == 0
    finally:
        connection.close()

    backup = next(database.parent.glob("devices.before_ap_extension_schema_*.db"))
    with sqlite3.connect(backup) as backup_connection:
        assert backup_connection.execute(
            "SELECT device_uuid FROM devices WHERE device_uuid='wal-device'"
        ).fetchone() == ("wal-device",)


def test_production_startup_accepts_legacy_app_config_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    _database(root)
    (root / "config" / "app.json").write_text(
        json.dumps({"current_site": "sxl1"}), encoding="utf-8"
    )
    _production_patches(monkeypatch)
    monkeypatch.setattr(backend_main, "_recover_orphaned_collect_runs", lambda *_args, **_kwargs: [])

    assert backend_main._current_site_name(PathResolver(data_root=root)) == "sxl1"


def test_ap_schema_production_rejects_direct_db_and_no_backup_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    before = database.read_bytes()
    _production_patches(monkeypatch)

    assert ap_schema.main(
        [
            "--data-dir",
            str(root),
            "--db",
            str(database),
            "--allow-production-write",
        ]
    ) == 1
    assert database.read_bytes() == before
    assert ap_schema.main(
        [
            "--data-dir",
            str(root),
            "--site",
            "sxl1",
            "--allow-production-write",
            "--no-backup",
        ]
    ) == 1
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    ("module", "args"),
    [
        (task_schema, lambda db: ["--database", str(db)]),
        (optical_backfill, lambda db: ["--site", "sxl1", "--database", str(db)]),
        (station_backfill, lambda db: ["--database-copy", str(db), "--site", "sxl1"]),
    ],
)
def test_development_only_tools_reject_relocated_production(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    args,
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    if module is task_schema:
        monkeypatch.setattr(task_schema, "data_root_for_path", lambda _path: root)
    elif module is optical_backfill:
        monkeypatch.setattr(optical_backfill, "data_root_for_path", lambda _path: root)
    else:
        monkeypatch.setattr(station_backfill, "data_root_for_path", lambda _path: root)
    monkeypatch.setattr(runtime_environment, "data_environment", lambda _root=None: _production_info())
    with pytest.raises(SystemExit, match="Production"):
        module.main(args(database))


def test_production_resolver_rejects_unlisted_site_without_directory_discovery(
    tmp_path: Path,
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root, site_id="sxl1")
    unlisted = root / "sites" / "fake-tenth-site" / "db" / "devices.db"
    unlisted.parent.mkdir(parents=True)
    unlisted.write_bytes(b"sentinel")
    paths = PathResolver(data_root=root)
    with pytest.raises(ProductionMaintenanceError, match="NOT_ALLOWLISTED"):
        production_module.resolve_production_database_scope(
            paths, "fake-tenth-site", "devices.db"
        )
    assert unlisted.read_bytes() == b"sentinel"


def test_production_startup_current_schema_is_canonical_and_ap_index_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    ApIdentityQueryService(Database(database)).ensure_index("fixture")
    _production_patches(monkeypatch)
    paths = PathResolver(data_root=root)
    stages: list[str] = []
    monkeypatch.setattr(backend_main, "_recover_orphaned_collect_runs", lambda *_args, **_kwargs: [])

    backend_main._initialize_active_site_database(
        paths,
        "sxl1",
        production_site_id="sxl1",
        startup_stage=stages.append,
    )
    assert stages == [
        "active_site_database_initializing",
        "active_site_database_ready",
        "ap_identity_index_initializing",
        "ap_identity_index_ready",
    ]


def test_production_startup_rebuilds_missing_identity_index_with_source_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, database = _production_identity_fixture(tmp_path)
    before = ApIdentityQueryService(Database(database)).revision_state()
    assert before.status == "missing"
    assert before.current_source_revision > 0

    _initialize_production_fixture(root, monkeypatch)

    state = ApIdentityQueryService(Database(database)).revision_state()
    assert state.status == "ready"
    assert state.revision > 0
    assert state.indexed_source_revision == state.current_source_revision


def test_production_startup_rebuilds_stale_identity_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, database = _production_identity_fixture(tmp_path)
    service = ApIdentityQueryService(Database(database))
    service.ensure_index("fixture")
    before = service.revision_state()

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE ap_extension_points SET ap_name=?, updated_at=? WHERE id=1",
            ("AP 001 changed", "2026-09-22T00:01:00Z"),
        )
        connection.commit()

    stale = service.revision_state()
    assert stale.status == "stale"
    assert stale.current_source_revision > before.current_source_revision

    _initialize_production_fixture(root, monkeypatch)

    ready = ApIdentityQueryService(Database(database)).revision_state()
    assert ready.status == "ready"
    assert ready.revision > before.revision
    assert ready.indexed_source_revision == ready.current_source_revision


def test_production_startup_ready_identity_index_is_noop_and_source_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, database = _production_identity_fixture(tmp_path)
    service = ApIdentityQueryService(Database(database))
    service.ensure_index("fixture")
    source_before = _source_snapshot(database)
    index_before = _identity_index_snapshot(database)

    _initialize_production_fixture(root, monkeypatch)

    assert _source_snapshot(database) == source_before
    assert _identity_index_snapshot(database) == index_before


def test_production_startup_builder_failure_preserves_old_index_and_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, database = _production_identity_fixture(tmp_path)
    service = ApIdentityQueryService(Database(database))
    service.ensure_index("fixture")

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE ap_extension_points SET ap_name=?, updated_at=? WHERE id=1",
            ("AP 001 changed", "2026-09-22T00:02:00Z"),
        )
        connection.commit()
    source_before = _source_snapshot(database)
    index_before = _identity_index_snapshot(database)

    def fail_builder(*_args, **_kwargs):
        raise RuntimeError("synthetic AP Identity builder failure")

    monkeypatch.setattr(
        ap_identity_query_service_module,
        "build_ap_identity_index",
        fail_builder,
    )
    with pytest.raises(RuntimeError, match="synthetic AP Identity builder failure"):
        service.rebuild_index("synthetic_failure")

    assert _source_snapshot(database) == source_before
    assert _identity_index_snapshot(database) == index_before
    assert ApIdentityQueryService(Database(database)).revision_state().status == "stale"


def test_production_startup_rejects_unlisted_site_before_database_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    root.mkdir(parents=True)
    config = root / "config"
    config.mkdir()
    (config / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "fake-tenth-site",
                        "display_name": "Fake",
                        "relative_path": "sites/fake-tenth-site",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_database = root / "sites" / "fake-tenth-site" / "db" / "devices.db"
    fake_database.parent.mkdir(parents=True)
    fake_database.write_bytes(b"sentinel")
    _production_patches(monkeypatch)
    with pytest.raises(RuntimeError, match="canonical"):
        backend_main._initialize_active_site_database(
            PathResolver(data_root=root),
            "fake-tenth-site",
            production_site_id="fake-tenth-site",
        )
    assert fake_database.read_bytes() == b"sentinel"


def test_production_startup_rejects_maintenance_grade_schema_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "relocated-production"
    _registry(root)
    database = _database(root)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE schema_metadata SET value=? WHERE key='schema_version'",
            ("old-schema",),
        )
        connection.commit()
    before = database.read_bytes()
    _production_patches(monkeypatch)
    with pytest.raises(DatabaseMaintenanceRequiredError, match="explicit database maintenance"):
        Database(database).initialize(startup_policy="production_safe")
    assert database.read_bytes() == before


def test_failed_default_migration_rolls_back_schema_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path / "isolated")
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE ap_identity_radio_evidence")
        connection.execute("DROP TABLE ap_identity_index_state")
        connection.commit()
    before = database.read_bytes()

    def fail(_self, _connection):
        raise RuntimeError("synthetic migration failure")

    monkeypatch.setattr(Database, "_apply_additive_schema_updates", fail)
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        Database(database).initialize()
    assert database.read_bytes() == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ap_identity_index_state'"
        ).fetchone() is None


def test_production_startup_allows_empty_identity_schema_bootstrap(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path / "isolated")
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE ap_identity_radio_evidence")
        connection.execute("DROP TABLE ap_identity_index_state")
        connection.commit()
    Database(database).initialize(startup_policy="production_safe")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()[0] == CURRENT_SCHEMA_VERSION
        assert connection.execute(
            "SELECT COUNT(*) FROM ap_identity_index_state"
        ).fetchone()[0] == 1


def test_development_bootstrap_and_repeat_initialize_remain_supported(tmp_path: Path) -> None:
    database = tmp_path / "isolated" / "devices.db"
    Database(database).initialize()
    first = database.read_bytes()
    Database(database).initialize()
    assert database.read_bytes() == first


def test_ap_identity_automatic_safe_only_rebuilds_derived_index_without_source_mutation(
    tmp_path: Path,
) -> None:
    _root, database = _production_identity_fixture(tmp_path)
    service = ApIdentityQueryService(Database(database))
    source_before = _source_snapshot(database)

    result = service.ensure_index("startup", automatic_safe_only=True)

    assert result is not None
    assert _source_snapshot(database) == source_before
    state = service.revision_state()
    assert state.status == "ready"
    assert state.revision > 0
    assert state.indexed_source_revision == state.current_source_revision
