from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.maintenance.production_cutover_runtime_smoke import (
    _device_smoke,
    _inspect_component_resume_journals,
    _task_smoke,
)


def _journal(root: Path, name: str, **fields: object) -> Path:
    path = root / "runtime" / "database_upgrade" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "operation_id": name,
                "recovery_strategy": "component_resume",
                **fields,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_terminal_component_resume_journal_is_protected_and_not_moved(tmp_path: Path) -> None:
    journal = _journal(
        tmp_path,
        "old-failed-cutover",
        stage="completed",
        switched=True,
        error="restart verification failed",
        rollback_error="WinError 5",
    )

    result = _inspect_component_resume_journals(tmp_path)

    assert result["status"] == "PASS"
    assert result["active_blocking_count"] == 0
    assert result["journals"][0]["classification"] == "TERMINAL_PROTECTED"
    assert journal.is_file()
    assert result["journals"][0]["journal_sha256"]


def test_live_component_resume_artifact_blocks_without_mutating_state(tmp_path: Path) -> None:
    candidate = tmp_path / "staging" / "production-maintenance" / "live" / "tasks.db.candidate"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"candidate")
    journal = _journal(
        tmp_path,
        "live-cutover",
        stage="switched",
        switched=True,
        shadow_path=str(candidate),
    )

    result = _inspect_component_resume_journals(tmp_path)

    assert result["status"] == "FAIL"
    assert result["active_blocking_count"] == 1
    assert result["active_blocking"][0]["artifacts"][0]["size"] == len(b"candidate")
    assert journal.is_file()
    assert candidate.is_file()


def test_task_and_device_smoke_use_live_counts_instead_of_historical_constants(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    db_dir = site / "db"
    db_dir.mkdir(parents=True)
    with sqlite3.connect(db_dir / "tasks.db") as connection:
        for table in (
            "task_results",
            "task_snapshots",
            "task_events",
            "online_mr_task_sessions",
        ):
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.execute(f"INSERT INTO {table} DEFAULT VALUES")
        connection.commit()

    with sqlite3.connect(db_dir / "devices.db") as connection:
        for table in (
            "devices",
            "ac_fit_ap_resources",
            "device_lldp_neighbors",
            "device_optical_modules",
            "device_interfaces",
            "fit_ap_lldp_current",
            "optical_current",
        ):
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.execute(f"INSERT INTO {table} DEFAULT VALUES")
        connection.commit()

    history = db_dir / "history"
    history.mkdir()
    with sqlite3.connect(history / "devices-2026-08.db") as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO records DEFAULT VALUES")
        connection.commit()
    ground = site / "files" / "rail_transit" / "ground_unattended"
    ground.mkdir(parents=True)
    (ground / "index.sqlite").write_bytes(b"index")
    (site / "files" / "rail_transit" / "mr_raw_mesh" / "session").mkdir(
        parents=True
    )
    (site / "files" / "rail_transit" / "mr_raw_mesh" / "session" / "mesh.sqlite").write_bytes(
        b"mesh"
    )
    online = site / "files" / "rail_transit" / "online_mr" / "parsed"
    online.mkdir(parents=True)
    (online / "vehicle_mr_online.sqlite").write_bytes(b"online")
    (site / "files" / "imports").mkdir(parents=True)

    task_result = _task_smoke(site)
    device_result = _device_smoke(site)

    assert task_result["status"] == "PASS"
    assert task_result["counts"]["task_results"] == 1
    assert device_result["status"] == "PASS"
    assert device_result["devices"]["devices"] == 1
