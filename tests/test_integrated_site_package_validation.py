from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.database import CURRENT_SCHEMA_VERSION, Database
from netconsole.core.paths import PathResolver
from netconsole.services.site_storage import SiteApplicationService, SitePackageService
from scripts.maintenance.validate_integrated_site_package import (
    _ap_identity_contract,
    _authority_file_profile,
    _copy_registered_package_authorities,
    _evidence_binding,
    _expand_integer_ranges,
    _load_site_storage_registry,
    _package_manifest_members,
    _package_policy_class,
    _registered_authority_parity,
    _registered_authority_profile,
    _registered_export_contract,
    _require_inside,
    _readonly_connection,
    _rows_by_sequence,
    _sqlite_backup,
)


def test_integrated_site_package_evidence_binding_uses_current_script() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "maintenance"
        / "validate_integrated_site_package.py"
    )

    binding = _evidence_binding(script)

    assert len(binding["git_head"]) == 40
    assert binding["script_path"] == (
        "scripts/maintenance/validate_integrated_site_package.py"
    )
    assert binding["script_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()


def _create_authority_database(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE facts (fact_id TEXT PRIMARY KEY, artifact_ref TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX facts_artifact_ref_idx ON facts(artifact_ref)")
        connection.executemany("INSERT INTO facts VALUES (?, ?)", rows)


def _storage_registry_fixture(path: Path) -> Path:
    stores = [
        (
            "site.devices.current",
            "sites/{site_id}/db/devices.db",
            "FULL_MIGRATION snapshot",
        ),
        (
            "site.devices.sqlite_sidecars",
            "sites/{site_id}/db/devices.db-*",
            "exclude sidecars",
        ),
        (
            "site.metadata",
            "sites/{site_id}/site_meta.json",
            "include and validate in every package containing site authority",
        ),
        (
            "site.agents",
            "sites/{site_id}/db/agents.db",
            "FULL_MIGRATION include; sanitized package exclude",
        ),
        (
            "site.ground.index",
            "sites/{site_id}/files/rail_transit/ground_unattended/index.sqlite",
            "include operational/recovery state and packaged history references",
        ),
        (
            "site.ground.active_raw",
            "sites/{site_id}/files/rail_transit/ground_unattended/active/YYYY-MM-DD/**",
            "include according to Ground recovery/export contract",
        ),
        (
            "site.online_mr.session_raw",
            "sites/{site_id}/files/rail_transit/online_mr/{profile_id}/sessions/{session_id}/raw/**",
            "include one raw authority or hash-linked package, never silent omission",
        ),
        (
            "site.online_mr.session_metadata",
            "sites/{site_id}/files/rail_transit/online_mr/{profile_id}/sessions/{session_id}/session_meta.json",
            "include with every packaged Online MR session",
        ),
        (
            "site.mesh.catalog",
            "sites/{site_id}/files/rail_transit/mr_raw_mesh/catalog.sqlite",
            "include catalog with raw and selected parsed authority",
        ),
        (
            "site.mesh.aggregate",
            "sites/{site_id}/files/rail_transit/mr_raw_mesh/{profile_id}/mesh.sqlite",
            "include or declare rebuildable from included raw+catalog",
        ),
        (
            "site.mesh.aggregate_sidecars",
            "sites/{site_id}/files/rail_transit/mr_raw_mesh/{profile_id}/mesh.sqlite-*",
            "exclude sidecars; snapshot the database through SQLite Online Backup",
        ),
        (
            "site.traffic.runs",
            "sites/{site_id}/files/network_tools/traffic/parsed/traffic_runs.sqlite",
            "FULL_MIGRATION include; share package policy explicit",
        ),
        (
            "site.wps.sync",
            "sites/{site_id}/sync/wps_sync.sqlite",
            "FULL_MIGRATION include; METADATA_ONLY may omit",
        ),
        (
            "site.sync.baseline",
            "sites/{site_id}/sync/baselines/**",
            "FULL_MIGRATION include; METADATA_ONLY may omit",
        ),
        (
            "site.sync.import_audit",
            "sites/{site_id}/sync/imports/**",
            "FULL_MIGRATION include; METADATA_ONLY may omit",
        ),
        (
            "site.optional.metadata",
            "sites/{site_id}/metadata/optional.json",
            "explicit metadata-only inclusion",
        ),
        (
            "unknown.legacy.protected",
            "sites/{site_id}/legacy/**",
            "PROTECT until explicit compatibility proof",
        ),
    ]
    value = {
        "version": 1,
        "unknown_policy": "PROTECT",
        "stores": [
            {
                "id": store_id,
                "relative_path": relative_path,
                "owner": store_id,
                "authority": f"{store_id} authority",
                "data_type": "OPERATIONAL_CURRENT",
                "site_package_policy": policy,
                "source_locations": [f"src/{store_id}.py"],
            }
            for store_id, relative_path, policy in stores
        ],
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_integrated_validation_expands_only_ordered_non_overlapping_ranges() -> None:
    assert _expand_integer_ranges(
        [{"start": 2, "end": 4}, {"start": 7, "end": 7}]
    ) == [2, 3, 4, 7]
    with pytest.raises(ValueError, match="ordered"):
        _expand_integer_ranges([{"start": 2, "end": 4}, {"start": 4, "end": 6}])


def test_integrated_validation_refuses_output_root_or_escape(tmp_path: Path) -> None:
    root = tmp_path / "run"
    child = root / "integrated"
    assert _require_inside(child, root, label="case") == child.resolve()
    with pytest.raises(ValueError, match="child"):
        _require_inside(root, root, label="case")
    with pytest.raises(ValueError, match="child"):
        _require_inside(tmp_path / "outside", root, label="case")


def test_integrated_validation_reads_selected_events_without_writing_source(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE task_events (sequence INTEGER PRIMARY KEY,event_id TEXT,"
            "task_id TEXT,event_type TEXT,event_time TEXT,source TEXT,payload_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO task_events VALUES (?,?,?,?,?,?,?)",
            [
                (1, "event-1", "task", "log", "2026-01-01T00:00:00Z", "service", "{}"),
                (2, "event-2", "task", "log", "2026-01-01T00:00:01Z", "service", "{}"),
                (3, "event-3", "task", "log", "2026-01-01T00:00:02Z", "service", "{}"),
            ],
        )
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    rows = _rows_by_sequence(database, [1, 3])
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    assert [row["event_id"] for row in rows] == ["event-1", "event-3"]
    assert before == after


def test_integrated_validation_online_backup_preserves_source_and_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO facts(payload) VALUES (?)", (json.dumps({"value": 1}),))
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = _sqlite_backup(source, target)
    with _readonly_connection(target) as connection:
        row = connection.execute("SELECT payload FROM facts").fetchone()
        assert row is not None
        assert row[0] == '{"value": 1}'
    assert result["quick_check"] == "ok"
    assert result["source_sha256_before"] == before
    assert result["source_sha256_after"] == before
    assert not Path(f"{target}-wal").exists()
    assert not Path(f"{target}-shm").exists()


def test_integrated_identity_contract_reports_revision_preserving_initialize(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    with database.connect() as connection:
        revision = int(
            connection.execute(
                "SELECT revision FROM ap_identity_source_state WHERE site_id='current'"
            ).fetchone()[0]
        )
        connection.execute("DROP TABLE ap_identity_radio_evidence")
        connection.execute(
            "UPDATE schema_metadata SET value='legacy' WHERE key='schema_version'"
        )
        connection.commit()

    contract = _ap_identity_contract(
        database.path,
        reason="integrated_validation_test",
    )

    assert contract["schema_version_before_initialize"] == "legacy"
    assert contract["schema_version_after_initialize"] == CURRENT_SCHEMA_VERSION
    assert contract["source_revision_before_initialize"] == revision
    assert contract["source_revision_after_initialize"] == revision
    assert contract["source_revision_preserved_by_initialize"] is True
    assert contract["radio_evidence_existed_before_initialize"] is False


def test_integrated_registry_authorities_copy_and_compare_table_semantics(
    tmp_path: Path,
) -> None:
    registry = _storage_registry_fixture(tmp_path / "storage_registry.json")
    stores = _load_site_storage_registry(registry)
    source = tmp_path / "source-site"
    target = tmp_path / "target-site"
    _create_authority_database(source / "db" / "agents.db", [("agent", "artifact-agent")])
    _create_authority_database(
        source / "files" / "rail_transit" / "ground_unattended" / "index.sqlite",
        [("ground", "artifact-ground")],
    )
    ground_raw = (
        source
        / "files"
        / "rail_transit"
        / "ground_unattended"
        / "active"
        / "2026-08-16"
        / "syslog.ndjson"
    )
    ground_raw.parent.mkdir(parents=True)
    ground_raw.write_text('{"message":"ground"}\n', encoding="utf-8")
    session = (
        source
        / "files"
        / "rail_transit"
        / "online_mr"
        / "mr-1"
        / "sessions"
        / "session-1"
    )
    (session / "raw").mkdir(parents=True)
    (session / "raw" / "mesh_link_raw.log").write_text("mesh raw", encoding="utf-8")
    (session / "session_meta.json").write_text(
        json.dumps({"session_id": "session-1", "artifact_ref": "artifact-session"}),
        encoding="utf-8",
    )
    _create_authority_database(
        source / "files" / "rail_transit" / "mr_raw_mesh" / "catalog.sqlite",
        [("mesh-source", "artifact-mesh")],
    )
    _create_authority_database(
        source / "files" / "rail_transit" / "mr_raw_mesh" / "profile-1" / "mesh.sqlite",
        [("mesh-row", "artifact-mesh")],
    )
    sidecar = (
        source
        / "files"
        / "rail_transit"
        / "mr_raw_mesh"
        / "profile-1"
        / "mesh.sqlite-wal"
    )
    sidecar.write_bytes(b"")
    traffic = source / "files" / "network_tools" / "traffic" / "parsed" / "traffic_runs.sqlite"
    _create_authority_database(traffic, [("traffic", "artifact-traffic")])
    _create_authority_database(
        source / "sync" / "wps_sync.sqlite",
        [("sync", "artifact-sync")],
    )
    _create_authority_database(
        source / "sync" / "baselines" / "baseline-one" / "devices.db",
        [("baseline", "artifact-baseline")],
    )
    import_audit = source / "sync" / "imports" / "return-one.json"
    import_audit.parent.mkdir(parents=True)
    import_audit.write_text(
        json.dumps({"package_id": "return-one", "artifact_ref": "artifact-return"}),
        encoding="utf-8",
    )

    copied = _copy_registered_package_authorities(source, target, stores)

    assert copied["stores_copied"] == 11
    assert copied["sqlite_files_copied"] == 7
    assert not (target / sidecar.relative_to(source)).exists()
    source_profile = _registered_authority_profile(source, stores)
    target_profile = _registered_authority_profile(target, stores)
    parity = _registered_authority_parity(source_profile, target_profile)
    assert parity["status"] == "PASS"
    assert source_profile["artifact_reference_count"] >= 6

    with sqlite3.connect(target / traffic.relative_to(source)) as connection:
        connection.execute(
            "UPDATE facts SET artifact_ref='changed' WHERE fact_id='traffic'"
        )
    changed = _registered_authority_parity(
        source_profile,
        _registered_authority_profile(target, stores),
    )
    assert changed["status"] == "FAIL"
    assert any(
        item["store_id"] == "site.traffic.runs" for item in changed["differences"]
    )

    with sqlite3.connect(target / traffic.relative_to(source)) as connection:
        connection.execute(
            "UPDATE facts SET artifact_ref='artifact-traffic' WHERE fact_id='traffic'"
        )
        connection.execute("DROP INDEX facts_artifact_ref_idx")
    changed_schema = _registered_authority_parity(
        source_profile,
        _registered_authority_profile(target, stores),
    )
    assert changed_schema["status"] == "FAIL"
    assert any(
        item["store_id"] == "site.traffic.runs"
        for item in changed_schema["differences"]
    )


def test_integrated_registry_export_contract_enforces_required_and_metadata_only(
    tmp_path: Path,
) -> None:
    stores = _load_site_storage_registry(
        _storage_registry_fixture(tmp_path / "storage_registry.json")
    )
    source = tmp_path / "site"
    _create_authority_database(source / "db" / "agents.db", [("agent", "artifact")])
    _create_authority_database(
        source / "sync" / "wps_sync.sqlite", [("sync", "artifact-sync")]
    )
    optional_metadata = source / "metadata" / "optional.json"
    optional_metadata.parent.mkdir(parents=True)
    optional_metadata.write_text('{"status":"optional"}', encoding="utf-8")
    sidecar = (
        source
        / "files"
        / "rail_transit"
        / "mr_raw_mesh"
        / "profile-1"
        / "mesh.sqlite-wal"
    )
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(b"runtime-only")
    profile = _registered_authority_profile(source, stores)

    metadata_omitted = _registered_export_contract(
        profile,
        {"site/db/agents.db", "site/sync/wps_sync.sqlite"},
    )
    assert metadata_omitted["status"] == "PASS"
    assert metadata_omitted["required_missing_files"] == 0

    missing_sync_authority = _registered_export_contract(
        profile,
        {"site/db/agents.db"},
    )
    assert missing_sync_authority["status"] == "FAIL"
    assert missing_sync_authority["required_missing_files"] == 1

    leaked_metadata_and_sidecar = _registered_export_contract(
        profile,
        {
            "site/db/agents.db",
            "site/sync/wps_sync.sqlite",
            "site/metadata/optional.json",
            "site/files/rail_transit/mr_raw_mesh/profile-1/mesh.sqlite-wal",
        },
    )
    assert leaked_metadata_and_sidecar["status"] == "FAIL"
    assert leaked_metadata_and_sidecar["excluded_included_files"] == 2


def test_registered_authority_profile_rejects_nonempty_wal_snapshot(
    tmp_path: Path,
) -> None:
    stores = _load_site_storage_registry(
        _storage_registry_fixture(tmp_path / "storage_registry.json")
    )
    source = tmp_path / "site"
    database = source / "files" / "rail_transit" / "mr_raw_mesh" / "profile-1" / "mesh.sqlite"
    _create_authority_database(database, [("mesh", "artifact")])
    database.with_name("mesh.sqlite-wal").write_bytes(b"not-checkpointed")

    with pytest.raises(sqlite3.DatabaseError, match="non-empty WAL"):
        _registered_authority_profile(source, stores)


def test_registered_authority_profile_fails_closed_for_unregistered_file(
    tmp_path: Path,
) -> None:
    stores = _load_site_storage_registry(
        _storage_registry_fixture(tmp_path / "storage_registry.json")
    )
    source = tmp_path / "site"
    rogue = source / "unowned" / "raw.log"
    rogue.parent.mkdir(parents=True)
    rogue.write_text("protect", encoding="utf-8")

    profile = _registered_authority_profile(source, stores)
    contract = _registered_export_contract(profile, set())

    assert profile["registry_coverage"] == {
        "status": "FAIL",
        "files": 1,
        "unregistered_files": ["unowned/raw.log"],
        "ambiguous_files": {},
    }
    assert contract["status"] == "FAIL"


def test_registered_authority_profile_covers_unknown_protected_site_store(
    tmp_path: Path,
) -> None:
    stores = _load_site_storage_registry(
        _storage_registry_fixture(tmp_path / "storage_registry.json")
    )
    source = tmp_path / "site"
    protected = source / "legacy" / "evidence.bin"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"protected")

    profile = _registered_authority_profile(source, stores)

    assert profile["registry_coverage"] == {
        "status": "PASS",
        "files": 1,
        "unregistered_files": [],
        "ambiguous_files": {},
    }
    assert profile["stores"]["unknown.legacy.protected"]["file_count"] == 1


def test_integrated_registry_policy_is_explicit_and_unknown_is_conditional() -> None:
    assert _package_policy_class("FULL_MIGRATION include") == "REQUIRED"
    assert (
        _package_policy_class("FULL_MIGRATION include; METADATA_ONLY may omit")
        == "REQUIRED"
    )
    assert _package_policy_class("include with every package") == "REQUIRED"
    assert _package_policy_class("exclude sidecars") == "EXCLUDED"
    assert _package_policy_class("explicit metadata-only inclusion") == "METADATA_ONLY"
    assert _package_policy_class("preserve Artifact reference") == "CONDITIONAL"


def test_registered_authority_invalid_json_is_protected_as_raw_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.json"
    path.write_bytes(b"")

    profile = _authority_file_profile(path)

    assert profile["kind"] == "json"
    assert profile["parse_status"] == "INVALID_PROTECTED"
    assert profile["semantic_digest"] == hashlib.sha256(b"").hexdigest()


def test_registered_sqlite_authority_quotes_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "quoted.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            'CREATE TABLE "facts""quoted" '
            '("fact""id" TEXT PRIMARY KEY, "artifact""ref" TEXT NOT NULL)'
        )
        connection.execute(
            'INSERT INTO "facts""quoted" VALUES (?, ?)',
            ("fact-1", "artifact-1"),
        )

    profile = _authority_file_profile(path)

    assert profile["kind"] == "sqlite"
    assert profile["tables"]['facts"quoted']["rows"] == 1
    assert profile["references"]["count"] == 1


def test_registered_authorities_round_trip_to_isolated_site_and_restart(
    tmp_path: Path,
) -> None:
    stores = _load_site_storage_registry(
        _storage_registry_fixture(tmp_path / "storage_registry.json")
    )
    source_paths = PathResolver(data_root=tmp_path / "source-root")
    source_sites = SiteApplicationService(source_paths)
    source_sites.create_site("source-site", "源局点")
    source = source_paths.site_dir("source-site")
    _create_authority_database(source / "db" / "agents.db", [("agent", "artifact")])
    _create_authority_database(
        source / "files" / "rail_transit" / "ground_unattended" / "index.sqlite",
        [("ground", "artifact-ground")],
    )
    ground_raw = (
        source
        / "files"
        / "rail_transit"
        / "ground_unattended"
        / "active"
        / "2026-08-16"
        / "ping.ndjson"
    )
    ground_raw.parent.mkdir(parents=True)
    ground_raw.write_text('{"rtt_ms":1.25}\n', encoding="utf-8")
    session = (
        source
        / "files"
        / "rail_transit"
        / "online_mr"
        / "mr-1"
        / "sessions"
        / "session-1"
    )
    (session / "raw").mkdir(parents=True)
    (session / "raw" / "mesh_link_raw.log").write_text("raw", encoding="utf-8")
    (session / "session_meta.json").write_text(
        json.dumps({"session_id": "session-1", "artifact_ref": "artifact-session"}),
        encoding="utf-8",
    )
    _create_authority_database(
        source / "files" / "rail_transit" / "mr_raw_mesh" / "catalog.sqlite",
        [("source", "artifact-mesh")],
    )
    _create_authority_database(
        source / "files" / "rail_transit" / "mr_raw_mesh" / "profile" / "mesh.sqlite",
        [("parsed", "artifact-mesh")],
    )
    _create_authority_database(
        source / "files" / "network_tools" / "traffic" / "parsed" / "traffic_runs.sqlite",
        [("traffic", "artifact-traffic")],
    )
    _create_authority_database(
        source / "sync" / "wps_sync.sqlite",
        [("sync", "artifact-sync")],
    )
    _create_authority_database(
        source / "sync" / "baselines" / "baseline-one" / "devices.db",
        [("baseline", "artifact-baseline")],
    )
    baseline_manifest = source / "sync" / "baselines" / "baseline-one" / "manifest.json"
    baseline_manifest.write_text(
        json.dumps({"baseline_id": "baseline-one", "base_revision": 4}),
        encoding="utf-8",
    )
    import_audit = source / "sync" / "imports" / "return-one.json"
    import_audit.parent.mkdir(parents=True)
    import_audit.write_text(
        json.dumps({"package_id": "return-one", "applied_revision": 5}),
        encoding="utf-8",
    )
    sidecar = (
        source
        / "files"
        / "rail_transit"
        / "mr_raw_mesh"
        / "profile"
        / "mesh.sqlite-shm"
    )
    sidecar.write_bytes(b"runtime")
    source_profile = _registered_authority_profile(source, stores)

    package = tmp_path / "full.ncsite"
    SitePackageService(source_paths, source_sites).export_site("source-site", package)
    export_contract = _registered_export_contract(
        source_profile,
        _package_manifest_members(package),
    )
    assert export_contract["status"] == "PASS", export_contract

    target_paths = PathResolver(data_root=tmp_path / "target-root")
    target_sites = SiteApplicationService(target_paths)
    SitePackageService(target_paths, target_sites).import_site(
        package,
        site_id="restored-site",
        display_name="恢复局点",
    )
    del target_sites
    restarted_paths = PathResolver(data_root=tmp_path / "target-root")
    restarted_sites = SiteApplicationService(restarted_paths)
    restored = restarted_sites.registry.get("restored-site").root_path
    target_profile = _registered_authority_profile(restored, stores)

    parity = _registered_authority_parity(source_profile, target_profile)
    assert parity["status"] == "PASS"
    assert source_profile["artifact_reference_count"] == target_profile[
        "artifact_reference_count"
    ]
    assert (restored / "sync" / "wps_sync.sqlite").is_file()
    assert (restored / baseline_manifest.relative_to(source)).read_bytes() == (
        baseline_manifest.read_bytes()
    )
    assert (restored / import_audit.relative_to(source)).read_bytes() == (
        import_audit.read_bytes()
    )
    assert not (restored / sidecar.relative_to(source)).exists()
