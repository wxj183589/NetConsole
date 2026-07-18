from __future__ import annotations

import sqlite3
from contextlib import closing

from scripts.maintenance.clean_test_artifacts import apply_cleanup, build_cleanup_plan
from scripts.maintenance.migrate_legacy_runtime_data import apply_plan, build_plan


def test_migration_plan_maps_only_runtime_roots_and_reports_conflicts(tmp_path):
    repo = tmp_path / "repo"
    destination = tmp_path / "destination"
    _write(repo / ".local" / "data" / "sites" / "demo" / "value.txt", "primary")
    _write(repo / ".local" / "runtime" / "logs" / "app.log", "log")
    _write(repo / ".local" / "acceptance" / "keep.txt", "keep")
    _write(repo / "data" / "sites" / "demo" / "value.txt", "different")

    plan = build_plan(repo, destination)

    by_source = {(item.source_label, item.relative_path): item for item in plan}
    assert by_source[("legacy-local-data", "sites/demo/value.txt")].destination_path == "data/sites/demo/value.txt"
    assert by_source[("legacy-local-runtime", "logs/app.log")].destination_path == "runtime/logs/app.log"
    assert by_source[("legacy-root-data", "sites/demo/value.txt")].action == "conflict"
    assert all("acceptance" not in item.relative_path for item in plan)


def test_migration_apply_copies_regular_files_and_uses_sqlite_backup(tmp_path):
    repo = tmp_path / "repo"
    destination = tmp_path / "destination"
    _write(repo / ".local" / "data" / "config" / "settings.json", "{}")
    database = repo / ".local" / "data" / "sites" / "demo" / "db" / "devices.db"
    database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE facts(value TEXT)")
        connection.execute("INSERT INTO facts VALUES ('preserved')")
        connection.commit()

    result = apply_plan(repo, destination, build_plan(repo, destination))

    assert {entry.action for entry in result} == {"copied"}
    assert (destination / "data" / "config" / "settings.json").read_text(encoding="utf-8") == "{}"
    copied_database = destination / "data" / "sites" / "demo" / "db" / "devices.db"
    with closing(sqlite3.connect(f"{copied_database.as_uri()}?mode=ro", uri=True)) as connection:
        assert connection.execute("SELECT value FROM facts").fetchone()[0] == "preserved"


def test_migration_apply_can_preserve_conflicts_without_overwrite(tmp_path):
    repo = tmp_path / "repo"
    destination = tmp_path / "destination"
    _write(repo / ".local" / "data" / "config" / "settings.json", "primary")
    _write(repo / "data" / "config" / "settings.json", "legacy")

    plan = build_plan(repo, destination)
    result = apply_plan(repo, destination, plan, skip_conflicts=True)

    assert (destination / "data" / "config" / "settings.json").read_text(encoding="utf-8") == "primary"
    assert any(entry.action == "conflict" for entry in result)


def test_cleanup_plan_only_removes_explicit_top_level_test_artifacts(tmp_path):
    repo = tmp_path / "repo"
    _write(repo / ".local" / "pytest-crash" / "result.db", "test")
    _write(repo / ".local" / "qt-final-acceptance.png", "image")
    _write(repo / ".local" / "data" / "sites" / "real.db", "business")
    _write(repo / ".local" / "acceptance" / "keep.db", "acceptance")
    _write(repo / ".local" / "tmp" / "unknown.bin", "unknown")

    plan = build_cleanup_plan(repo)

    assert {entry.name for entry in plan} == {"pytest-crash", "qt-final-acceptance.png"}
    result = apply_cleanup(repo, plan)
    assert {entry.action for entry in result} == {"deleted"}
    assert not (repo / ".local" / "pytest-crash").exists()
    assert not (repo / ".local" / "qt-final-acceptance.png").exists()
    assert (repo / ".local" / "data" / "sites" / "real.db").exists()
    assert (repo / ".local" / "acceptance" / "keep.db").exists()
    assert (repo / ".local" / "tmp" / "unknown.bin").exists()


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
