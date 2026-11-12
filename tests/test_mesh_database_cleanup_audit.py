from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.maintenance import audit_mesh_database_cleanup as audit_module
from scripts.maintenance.audit_mesh_database_cleanup import (
    _sqlite_metadata,
    audit_root,
    audit_roots,
    audit_v4,
    audit_v41,
    backup_candidates,
    isolate_backups,
    _v41_backup_candidates,
    _handle_group_audit,
    _v41_isolate_backup_manifest,
    _v41_rollback_isolation,
    _v41_validate_authorization,
    write_reports,
    write_v4_reports,
)


def _db(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(";\n".join(statements))
        connection.commit()
    finally:
        connection.close()


def _mesh_fixture(tmp_path: Path, *, fallback: bool = False) -> tuple[Path, Path, Path]:
    root = tmp_path / "data"
    mesh = root / "sites" / "site-a" / "files" / "rail_transit" / "mr_raw_mesh"
    profile = mesh / "MR-CT"
    parsed = profile / "parsed" / "source.mesh.sqlite"
    catalog = mesh / "catalog.sqlite"
    _db(
        catalog,
        [
            "CREATE TABLE mr_profiles (mr_id TEXT, display_name TEXT, safe_folder_name TEXT)",
            "CREATE TABLE mesh_session_index (session_id TEXT, mr_id TEXT, source_file_id INTEGER)",
            "INSERT INTO mr_profiles VALUES ('mr-1', 'MR-CT', 'MR-CT')",
            "INSERT INTO mesh_session_index VALUES ('mr-1:1', 'mr-1', 1)",
        ],
    )
    parsed_value = "Z:/old-root/source.mesh.sqlite" if fallback else str(parsed)
    index = profile / "mesh.sqlite"
    _db(
        index,
        [
            "CREATE TABLE source_files (id INTEGER, parsed_db_path TEXT, parsed_relative_path TEXT, original_filename TEXT, archived_filename TEXT, sha256 TEXT, content_sha256 TEXT)",
            "INSERT INTO source_files VALUES (1, '', '', 'source.log', 'source.log', 'source-hash', 'content-hash')",
        ],
    )
    with sqlite3.connect(index) as connection:
        connection.execute(
            "UPDATE source_files SET parsed_db_path = ?, parsed_relative_path = ? WHERE id = 1",
            (parsed_value, "" if fallback else "parsed/source.mesh.sqlite"),
        )
        connection.commit()
    _db(
        parsed,
        [
            "CREATE TABLE schema_meta (key TEXT, value TEXT)",
            "INSERT INTO schema_meta VALUES ('schema_version', 'meshlog_compact_v3_tagged_samples')",
            "CREATE TABLE source_files (id INTEGER, original_filename TEXT, archived_filename TEXT, sha256 TEXT, content_sha256 TEXT)",
            "INSERT INTO source_files VALUES (1, 'source.log', 'source.log', 'source-hash', 'content-hash')",
        ],
    )
    raw = profile / "raw" / "source.log"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("raw evidence", encoding="utf-8")
    _db(
        root / "sites" / "site-a" / "db" / "tasks.db",
        [
            "CREATE TABLE task_snapshots (task_id TEXT, task_type TEXT, status TEXT, result_json TEXT)",
        ],
    )
    return root, index, parsed


def _v4_mesh_fixture(tmp_path: Path) -> tuple[Path, list[Path], list[Path]]:
    root, _, parsed = _mesh_fixture(tmp_path)
    rebuilds: list[Path] = []
    formals: list[Path] = []
    for index in range(7):
        formal = parsed.with_name(f"formal-{index}.mesh.sqlite")
        shutil.copy2(parsed, formal)
        rebuild = formal.with_name(
            f".{formal.name}.0123456789abcdef0123456789abcdef.rebuild.sqlite"
        )
        shutil.copy2(formal, rebuild)
        formals.append(formal)
        rebuilds.append(rebuild)
    return root, rebuilds, formals


def _v41_candidate_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    root, _, parsed = _mesh_fixture(tmp_path)
    rebuild = parsed.with_name(
        f".{parsed.name}.0123456789abcdef0123456789abcdef.rebuild.sqlite"
    )
    shutil.copy2(parsed, rebuild)
    record = _records(audit_root(root, maintenance_window_authorized=True), rebuild.name)[0]
    candidate = {
        "path": str(rebuild),
        "formal_database_path": record["rebuild_review"]["formal_database_path"],
        "record": record,
        "rebuild_review": record["rebuild_review"],
        "reference_check": "PASS",
        "windows_handle_status": "HANDLE_FREE_CONFIRMED",
        "orphan_candidate": True,
    }
    return root, rebuild, candidate


def _insert_task(root: Path, task_id: str, status: str, result: object = None) -> None:
    tasks = root / "sites" / "site-a" / "db" / "tasks.db"
    with sqlite3.connect(tasks) as connection:
        connection.execute(
            "INSERT INTO task_snapshots VALUES (?, ?, ?, ?)",
            (
                task_id,
                "mesh_source_rebuild",
                status,
                json.dumps(result, ensure_ascii=False) if result is not None else "{}",
            ),
        )
        connection.commit()


def _stale_sidecar_database(tmp_path: Path) -> Path:
    database = tmp_path / "stale.sqlite"
    ready = tmp_path / "writer.ready"
    child_code = """
import sqlite3
import sys
import time

database = sys.argv[1]
ready = sys.argv[2]
connection = sqlite3.connect(database)
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("CREATE TABLE sample(value INTEGER)")
connection.commit()
connection.execute("INSERT INTO sample VALUES (1)")
connection.commit()
connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
open(ready, "w", encoding="ascii").close()
time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(database), str(ready)]
    )
    try:
        for _ in range(100):
            if ready.is_file():
                break
            time.sleep(0.05)
        assert ready.is_file(), "isolated WAL writer did not become ready"
    finally:
        process.kill()
        process.wait(timeout=5)
    assert database.is_file()
    assert database.with_name(database.name + "-wal").is_file()
    assert database.with_name(database.name + "-shm").is_file()
    return database


def _records(audit: dict[str, object], name: str) -> list[dict[str, object]]:
    return [
        record
        for record in audit["records"]  # type: ignore[index]
        if str(record.get("basename")) == name
    ]


def test_exact_source_and_session_references_protect_parsed_database(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    before_raw = (parsed.parent.parent / "raw" / "source.log").read_bytes()

    audit = audit_roots([root], maintenance_window_authorized=True)
    record = _records(audit, parsed.name)[0]

    assert record["status"] == "SESSION_REFERENCED"
    assert record["source_record_count"] == 1
    assert record["analysis_session_reference_count"] == 1
    assert record["filename_fallback_reference_count"] == 0
    assert (parsed.parent.parent / "raw" / "source.log").read_bytes() == before_raw


def test_filename_fallback_reference_is_not_an_orphan(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path, fallback=True)

    audit = audit_root(root, maintenance_window_authorized=True)
    record = _records(audit, parsed.name)[0]

    assert record["status"] == "SESSION_REFERENCED"
    assert record["filename_fallback_reference_count"] == 1


def test_wal_sidecar_protects_database(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    parsed.with_name(parsed.name + "-wal").write_bytes(b"active wal")

    audit = audit_root(root, maintenance_window_authorized=True)
    record = _records(audit, parsed.name)[0]

    assert record["status"] == "SESSION_REFERENCED"
    assert record["activity_state"] == "SIDECAR_PRESENT_UNCONFIRMED"
    assert record["wal_bytes"] == len(b"active wal")


def test_unknown_and_corrupt_databases_are_protected(tmp_path: Path) -> None:
    root, _, _ = _mesh_fixture(tmp_path)
    unknown = root / "sites" / "site-a" / "files" / "rail_transit" / "mr_raw_mesh" / "legacy.sqlite"
    unknown.write_bytes(b"not a sqlite database")

    audit = audit_root(root, maintenance_window_authorized=True)
    record = _records(audit, unknown.name)[0]

    assert record["status"] == "INSPECTION_FAILED"
    assert record["allowed_for_backup"] is False


def test_active_task_reference_protects_unknown_candidate(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    _insert_task(root, "task-1", "RUNNING", {"parsed_db": str(parsed)})
    # Remove the source index's reference but keep the registered Profile. The
    # task evidence must still prevent any cleanup decision.
    with sqlite3.connect(parsed.parent.parent / "mesh.sqlite") as connection:
        connection.execute("DELETE FROM source_files")
        connection.commit()

    audit = audit_root(root, maintenance_window_authorized=True)
    record = _records(audit, parsed.name)[0]

    assert record["status"] == "TASK_ACTIVE_PROTECT"
    assert record["activity_task_reference_count"] >= 1
    assert record["historical_task_reference_count"] == 0


def test_runtime_process_protects_without_claiming_every_database_is_active(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)

    audit = audit_root(
        root,
        runtime_processes=["NetConsoleBackend.exe"],
        maintenance_window_authorized=True,
    )
    record = _records(audit, parsed.name)[0]

    assert record["activity_state"] == "ACTIVITY_UNKNOWN"
    assert record["status"] == "SESSION_REFERENCED"
    assert record["allowed_for_backup"] is False


def test_rebuild_internal_identity_is_not_a_physical_session_reference(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    rebuild = parsed.with_name(
        f".{parsed.name}.0123456789abcdef0123456789abcdef.rebuild.sqlite"
    )
    shutil.copy2(parsed, rebuild)

    audit = audit_root(root, maintenance_window_authorized=True)
    record = _records(audit, rebuild.name)[0]

    assert record["database_type"] == "rebuild_temp"
    assert record["source_reference_count"] == 0
    assert record["session_reference_count"] == 0
    assert record["internal_source_identity_count"] == 1
    assert record["rebuild_review"]["formal_database_healthy"] is True
    assert record["status"] == "ORPHAN_CANDIDATE"
    assert record["allowed_for_backup"] is True


def test_recovery_journal_protects_rebuild_database(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    rebuild = parsed.with_name(
        f".{parsed.name}.fedcba9876543210fedcba9876543210.rebuild.sqlite"
    )
    shutil.copy2(parsed, rebuild)
    journal = rebuild.parent / "recovery-journal.json"
    journal.write_text(json.dumps({"database": str(rebuild)}), encoding="utf-8")

    audit = audit_root(root, maintenance_window_authorized=True)
    record = _records(audit, rebuild.name)[0]

    assert record["recovery_reference_count"] == 1
    assert record["status"] == "RECOVERY_PROTECT"
    assert record["allowed_for_backup"] is False


def test_repeated_audit_keeps_identity_and_status_stable(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)

    first = _records(
        audit_root(root, maintenance_window_authorized=True), parsed.name
    )[0]
    second = _records(
        audit_root(root, maintenance_window_authorized=True), parsed.name
    )[0]

    assert first["file_identity"] == second["file_identity"]
    assert first["sha256"] == second["sha256"]
    assert first["status"] == second["status"] == "SESSION_REFERENCED"


def test_generic_catalog_and_index_names_are_not_task_physical_references(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    _insert_task(
        root,
        "task-1",
        "COMPLETED",
        {"path": "catalog.sqlite", "db": "mesh.sqlite"},
    )

    audit = audit_root(root, maintenance_window_authorized=True)
    catalog = _records(audit, "catalog.sqlite")[0]
    index = _records(audit, "mesh.sqlite")[0]
    parsed_record = _records(audit, parsed.name)[0]

    assert catalog["historical_task_reference_count"] == 0
    assert index["historical_task_reference_count"] == 0
    assert parsed_record["historical_task_reference_count"] == 0


def test_read_only_probe_separates_auditor_shm_effect_from_external_changes(tmp_path: Path) -> None:
    database = _stale_sidecar_database(tmp_path)

    metadata = _sqlite_metadata(database)

    assert metadata["quick_check"] == "ok"
    assert metadata["integrity_check"] == "ok"
    assert metadata["wal_size"] == 0
    assert metadata["shm_size"] == 32768
    assert metadata["probe_count"] == 2
    assert metadata["main_changed_during_observation"] is False
    assert metadata["wal_changed_during_observation"] is False
    assert metadata["shm_changed_during_first_probe"] is True
    assert metadata["shm_changed_during_second_probe"] is True
    assert metadata["auditor_shm_side_effect_observed"] is False
    assert metadata["unexplained_shm_change"] is True
    assert metadata["settled_snapshot_stable"] is False


def test_wal_nonzero_fails_closed_even_with_maintenance_window(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    writer = sqlite3.connect(parsed)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE pending_write(value INTEGER)")
        writer.commit()

        audit = audit_root(root, maintenance_window_authorized=True)
        record = _records(audit, parsed.name)[0]

        assert record["wal_bytes"] > 0
        assert record["activity_state"] == "SIDECAR_PRESENT_UNCONFIRMED"
        assert record["allowed_for_backup"] is False
    finally:
        writer.close()


def test_no_maintenance_window_keeps_stable_database_blocked(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)

    audit = audit_root(root)
    record = _records(audit, parsed.name)[0]

    assert record["activity_state"] == "ACTIVITY_UNKNOWN"
    assert record["allowed_for_backup"] is False


def test_v3_json_and_markdown_rebuild_reference_counts_match(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    rebuild = parsed.with_name(
        f".{parsed.name}.0123456789abcdef0123456789abcdef.rebuild.sqlite"
    )
    shutil.copy2(parsed, rebuild)
    audit = audit_roots([root], maintenance_window_authorized=True)
    output = tmp_path / "reports"
    write_reports(audit, output)

    payload = json.loads(
        (output / "MESH_ORPHAN_CANDIDATES_V3.json").read_text(encoding="utf-8")
    )
    rebuild_json = next(
        item for item in payload["rebuild_review"] if item["basename"] == rebuild.name
    )
    assert rebuild_json["source_reference_count"] == 0
    assert rebuild_json["session_reference_count"] == 0
    assert rebuild_json["internal_source_identity_count"] == 1

    markdown = (output / "MESH_DATABASE_V3_FINAL_REPORT.md").read_text(encoding="utf-8")
    header = next(
        line for line in markdown.splitlines() if line.startswith("| 文件名 | 大小 |")
    )
    row = next(line for line in markdown.splitlines() if rebuild.name in line)
    header_fields = [field.strip() for field in header.split("|")[1:-1]]
    row_fields = [field.strip() for field in row.split("|")[1:-1]]
    values = dict(zip(header_fields, row_fields, strict=True))
    assert values["物理来源引用"] == "0"
    assert values["物理会话引用"] == "0"
    assert values["文件名回退"] == "0"
    assert values["内部来源身份"] == "1"
    assert values["正式库会话接管"] == "1"


def test_v4_without_maintenance_authorization_writes_empty_manifests(tmp_path: Path, monkeypatch) -> None:
    root, rebuilds, formals = _v4_mesh_fixture(tmp_path)
    v3_output = tmp_path / "v3"
    write_reports(audit_roots([root], maintenance_window_authorized=True), v3_output)
    before = {path: path.read_bytes() for path in [*rebuilds, *formals]}
    monkeypatch.setattr(
        audit_module,
        "_runtime_process_evidence",
        lambda: {
            "backend_worker": ["NetConsoleBackend.exe"],
            "electron": [],
            "python_mesh": [],
            "handle_probe": "UNAVAILABLE",
            "notes": ["test"],
        },
    )

    audit = audit_v4([root], previous_report_dir=v3_output)
    v4_output = tmp_path / "v4"
    write_v4_reports(audit, v4_output)

    assert len(audit["target_results"]) == 7
    assert audit["status"]["activity_verification"] == "PARTIAL"
    assert audit["status"]["reference_check"] == "PASS"
    assert audit["status"]["backup_verification"] == "NOT_EXECUTED"
    assert audit["status"]["isolation"] == "NOT_EXECUTED"
    assert audit["status"]["production_isolation"] == "NOT_EXECUTED"
    assert audit["status"]["orphan_candidates"] == 0
    assert audit["status"]["databases_isolated"] == 0
    assert audit["status"]["databases_removed"] == 0
    assert audit["status"]["overall_status"] == "BLOCKED"
    assert "ACTIVITY_UNKNOWN" in audit["target_results"][0]["blockers"]
    assert json.loads(
        (v4_output / "MESH_DATABASE_V4_BACKUP_MANIFEST.json").read_text(encoding="utf-8")
    )["entries"] == []
    assert json.loads(
        (v4_output / "MESH_DATABASE_V4_ISOLATION_MANIFEST.json").read_text(encoding="utf-8")
    )["entries"] == []
    assert {path: path.read_bytes() for path in [*rebuilds, *formals]} == before


def test_v4_identity_drift_blocks_exact_rebuild_scope(tmp_path: Path, monkeypatch) -> None:
    root, _, _ = _v4_mesh_fixture(tmp_path)
    v3_output = tmp_path / "v3"
    write_reports(audit_roots([root], maintenance_window_authorized=True), v3_output)
    candidate_path = v3_output / "MESH_ORPHAN_CANDIDATES_V3.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    payload["rebuild_review"][0]["sha256"] = "0" * 64
    candidate_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        audit_module,
        "_runtime_process_evidence",
        lambda: {
            "backend_worker": [],
            "electron": [],
            "python_mesh": [],
            "handle_probe": "UNAVAILABLE",
            "notes": [],
        },
    )

    audit = audit_v4([root], previous_report_dir=v3_output)

    drifted = audit["target_results"][0]
    assert "V3_IDENTITY_DRIFT" in drifted["blockers"]
    assert audit["status"]["orphan_candidates"] == 0
    assert audit["status"]["data_safety"] == "PASS"


def test_v4_corrupt_formal_database_blocks_candidate(tmp_path: Path, monkeypatch) -> None:
    root, _, formals = _v4_mesh_fixture(tmp_path)
    v3_output = tmp_path / "v3"
    write_reports(audit_roots([root], maintenance_window_authorized=True), v3_output)
    formals[0].write_bytes(b"corrupt formal database")
    monkeypatch.setattr(
        audit_module,
        "_runtime_process_evidence",
        lambda: {
            "backend_worker": [],
            "electron": [],
            "python_mesh": [],
            "handle_probe": "UNAVAILABLE",
            "notes": [],
        },
    )

    audit = audit_v4([root], previous_report_dir=v3_output)

    blocked = audit["target_results"][0]
    assert blocked["orphan_candidate"] is False
    assert "FORMAL_DATABASE_UNHEALTHY" in blocked["blockers"]
    assert audit["status"]["orphan_candidates"] == 0


def test_v4_wal_and_recovery_evidence_remain_protected(tmp_path: Path, monkeypatch) -> None:
    root, rebuilds, _ = _v4_mesh_fixture(tmp_path)
    v3_output = tmp_path / "v3"
    write_reports(audit_roots([root], maintenance_window_authorized=True), v3_output)
    rebuilds[0].with_name(rebuilds[0].name + "-wal").write_bytes(b"pending")
    (rebuilds[0].parent / "recovery-journal.json").write_text(
        json.dumps({"database": str(rebuilds[0])}), encoding="utf-8"
    )
    monkeypatch.setattr(
        audit_module,
        "_runtime_process_evidence",
        lambda: {
            "backend_worker": [],
            "electron": [],
            "python_mesh": [],
            "handle_probe": "UNAVAILABLE",
            "notes": [],
        },
    )

    audit = audit_v4([root], previous_report_dir=v3_output)

    protected = audit["target_results"][0]
    assert protected["orphan_candidate"] is False
    assert "RECOVERY_REFERENCE" in protected["blockers"]
    assert any(
        state in protected["blockers"]
        for state in ("SIDECAR_PRESENT_UNCONFIRMED", "ACTIVITY_UNKNOWN")
    )


def test_v41_native_handle_probe_reports_a_safe_result_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "probe.sqlite"
    _db(database, ["CREATE TABLE sample(value INTEGER)", "INSERT INTO sample VALUES (1)"])
    before = database.read_bytes()

    result = _handle_group_audit([database, database.with_name(database.name + "-wal")])

    assert result["status"] in {
        "HANDLE_FREE_CONFIRMED",
        "HANDLE_UNCONFIRMED",
        "HANDLE_PROBE_FAILED",
        "HANDLE_OCCUPIED",
    }
    assert database.read_bytes() == before


def test_v41_backup_isolation_and_rollback_are_independent_and_idempotent(tmp_path: Path) -> None:
    root, rebuild, candidate = _v41_candidate_fixture(tmp_path)
    authorization = {"status": "PASS", "payload": {"operator": "test"}}
    backup_path = tmp_path / "backup-manifest.json"

    backup = _v41_backup_candidates(
        [candidate],
        audit_id="test-backup",
        authorization=authorization,
        manifest_path=backup_path,
    )

    assert backup["backup_workflow"] == "PASS"
    assert backup["backup_success_count"] == 1
    backup_entry = backup["entries"][0]
    assert backup_entry["state"] == "BACKUP_VERIFIED"
    assert Path(backup_entry["backup_database_path"]).is_file()
    assert backup_entry["backup_validation"]["quick_check"] == "ok"
    assert backup_entry["backup_validation"]["integrity_check"] == "ok"
    assert rebuild.is_file()

    isolation_path = tmp_path / "isolation-manifest.json"
    isolation = _v41_isolate_backup_manifest(
        backup,
        audit_id="test-isolation",
        handle_groups={str(rebuild.resolve()): {"status": "HANDLE_FREE_CONFIRMED"}},
        authorization=authorization,
        manifest_path=isolation_path,
    )

    assert isolation["workflow"] == "PASS"
    assert isolation["isolated_count"] == 1
    moved = isolation["entries"][0]["moved_files"]
    assert not rebuild.exists()
    assert all(Path(item["target"]).is_file() for item in moved)
    assert isolation["actual_released_bytes"] == 0

    rolled_back = _v41_rollback_isolation(isolation, manifest_path=isolation_path)
    assert rolled_back["rollback_workflow"] == "PASS"
    assert rebuild.is_file()
    assert all(not Path(item["target"]).exists() for item in moved)

    repeated = _v41_rollback_isolation(rolled_back, manifest_path=isolation_path)
    assert repeated["rollback_workflow"] == "PASS"
    assert rebuild.is_file()


def test_v41_rollback_conflict_never_deletes_new_source(tmp_path: Path) -> None:
    root, rebuild, candidate = _v41_candidate_fixture(tmp_path)
    authorization = {"status": "PASS", "payload": {"operator": "test"}}
    backup = _v41_backup_candidates([candidate], audit_id="conflict-backup", authorization=authorization)
    isolation = _v41_isolate_backup_manifest(
        backup,
        audit_id="conflict-isolation",
        handle_groups={str(rebuild.resolve()): {"status": "HANDLE_FREE_CONFIRMED"}},
        authorization=authorization,
    )
    moved = isolation["entries"][0]["moved_files"]
    rebuild.write_bytes(b"new file must not be overwritten")

    rolled_back = _v41_rollback_isolation(isolation)
    assert rolled_back["rollback_workflow"] == "FAIL"
    assert rolled_back["entries"][0]["state"] == "ROLLBACK_REQUIRED"
    assert rebuild.read_bytes() == b"new file must not be overwritten"
    assert Path(moved[0]["target"]).is_file()


def test_v41_audit_only_does_not_authorize_backup_or_isolation(tmp_path: Path, monkeypatch) -> None:
    root, rebuilds, _ = _v4_mesh_fixture(tmp_path)
    v3_output = tmp_path / "v3"
    v4_output = tmp_path / "v4"
    write_reports(audit_roots([root], maintenance_window_authorized=True), v3_output)
    v4_output.mkdir()
    candidate_manifest = v4_output / "MESH_DATABASE_V4_CANDIDATES.json"
    baseline_v4 = audit_v4([root], previous_report_dir=v3_output)
    baseline_v4["validation"] = {"test_result": "fixture"}
    write_v4_reports(baseline_v4, v4_output)
    before = {path: path.read_bytes() for path in rebuilds}
    monkeypatch.setattr(
        audit_module,
        "_handle_group_audit",
        lambda paths: {
            "status": "HANDLE_FREE_CONFIRMED",
            "paths": [str(Path(path)) for path in paths],
            "files": [],
            "restart_manager": {"status": "EMPTY", "processes": []},
        },
    )

    audit = audit_v41(
        [root],
        previous_report_dir=v3_output,
        v4_report_dir=v4_output,
        output_dir=tmp_path / "v4.1",
        execution_mode="AUDIT_ONLY",
    )

    assert audit["status"]["maintenance_authorized"] == "NO"
    assert audit["status"]["production_backup"] == "NOT_EXECUTED"
    assert audit["status"]["production_isolation"] == "NOT_EXECUTED"
    assert audit["status"]["overall_status"] == "BLOCKED"
    assert all(
        "WINDOWS_HANDLE_UNCONFIRMED" not in item["blockers"]
        for item in audit["target_results"]
    )
    assert {path: path.read_bytes() for path in rebuilds} == before
    assert candidate_manifest.is_file()


def test_v41_authorization_is_required_and_binds_exact_scope_and_manifest_hash(tmp_path: Path) -> None:
    candidate_manifest = tmp_path / "MESH_DATABASE_V4_CANDIDATES.json"
    candidate_path = tmp_path / "data" / "sites" / "site-a" / "candidate.rebuild.sqlite"
    candidate_manifest.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "path": str(candidate_path),
                        "record": {
                            "data_root": str(tmp_path / "data"),
                            "site": "site-a",
                            "mr_profile_id": "mr-1",
                            "canonical_path": str(candidate_path),
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    window_start = datetime.now(timezone.utc) - timedelta(minutes=1)
    window_end = datetime.now(timezone.utc) + timedelta(minutes=1)
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(
        json.dumps(
            {
                "format": "netconsole-mesh-maintenance-authorization-v1",
                "mode": "BACKUP_ONLY",
                "authorized": True,
                "confirmation": {
                    "confirmed": True,
                    "operator": "test-operator",
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                },
                "operation_scope": "exact V4 candidate backup only",
                "maintenance_window": {
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                },
                "data_roots": [str(tmp_path / "data")],
                "sites": ["site-a"],
                "mr_profiles": ["mr-1"],
                "candidate_paths": [str(candidate_path)],
                "candidate_manifest": str(candidate_manifest),
                "candidate_manifest_sha256": audit_module.sha256_file(candidate_manifest),
            }
        ),
        encoding="utf-8",
    )

    missing = _v41_validate_authorization(
        None,
        requested_mode="BACKUP_ONLY",
        candidate_manifest_path=candidate_manifest,
        candidate_manifest=json.loads(candidate_manifest.read_text(encoding="utf-8")),
    )
    assert missing["status"] == "NOT_PROVIDED"
    assert missing["errors"]

    valid = _v41_validate_authorization(
        authorization_path,
        requested_mode="BACKUP_ONLY",
        candidate_manifest_path=candidate_manifest,
        candidate_manifest=json.loads(candidate_manifest.read_text(encoding="utf-8")),
    )
    assert valid["status"] == "PASS"

    candidate_manifest.write_text(candidate_manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    drifted = _v41_validate_authorization(
        authorization_path,
        requested_mode="BACKUP_ONLY",
        candidate_manifest_path=candidate_manifest,
        candidate_manifest=json.loads(candidate_manifest.read_text(encoding="utf-8")),
    )
    assert drifted["status"] == "FAIL"
    assert any("SHA-256" in error for error in drifted["errors"])


def test_audit_does_not_modify_raw_evidence(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    raw = parsed.parent.parent / "raw" / "source.log"
    before = raw.read_bytes()
    before_mtime = raw.stat().st_mtime_ns

    audit_root(root, maintenance_window_authorized=True)

    assert raw.read_bytes() == before
    assert raw.stat().st_mtime_ns == before_mtime


def test_backup_and_isolate_reject_non_candidates_without_mutation(tmp_path: Path) -> None:
    root, _, parsed = _mesh_fixture(tmp_path)
    before = parsed.read_bytes()
    candidate = {
        "path": str(parsed),
        "status": "SESSION_REFERENCED",
        "data_root": str(root),
        "site": "site-a",
        "safe_folder_name": "MR-CT",
        "schema_version": "meshlog_compact_v3_tagged_samples",
        "size_bytes": parsed.stat().st_size,
        "sha256": "wrong",
    }

    backup = backup_candidates([candidate], audit_id="audit")
    isolated = isolate_backups(backup, audit_id="audit")

    assert backup["backup_success_count"] == 0
    assert backup["backup_failure_count"] == 1
    assert isolated["isolated_count"] == 0
    assert parsed.is_file()
    assert parsed.read_bytes() == before
