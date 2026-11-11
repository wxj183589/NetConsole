from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from scripts.maintenance.audit_mesh_database_cleanup import (
    _sqlite_metadata,
    audit_root,
    audit_roots,
    backup_candidates,
    isolate_backups,
    write_reports,
)


def _db(path: Path, statements: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(";\n".join(statements))
        connection.commit()


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
    assert metadata["auditor_shm_side_effect_observed"] is True
    assert metadata["unexplained_shm_change"] is False
    assert metadata["settled_snapshot_stable"] is True


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
