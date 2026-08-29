from __future__ import annotations

import sqlite3
from pathlib import Path

import scripts.maintenance.compact_task_result_production as compaction
from netconsole.repositories.task_repository import TaskRepository


def test_production_compaction_plan_is_target_scoped_and_below_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "NetConsoleData"
    db = root / "sites" / "demo" / "db" / "tasks.db"
    db.parent.mkdir(parents=True)
    TaskRepository(db)
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    monkeypatch.setattr(compaction, "PRODUCTION_ROOT", root)

    plan = compaction.build_compaction_plan(
        db,
        site_id="demo",
        data_root=root,
        generated_at="2026-08-29T01:00:00Z",
    )

    assert plan["digest_scope"] == "TASK_DB_PHYSICAL_COMPACTION_TARGET"
    assert plan["site_directory"] == "demo"
    assert plan["physical_compaction_recommended"] is False
    result = compaction.apply_compaction_plan(
        compaction.write_compaction_plan(plan, tmp_path / "plan.json"),
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path / "backup.db",
        authorization=compaction.AUTHORIZATION,
    )
    assert result["mode"] == "SKIPPED_BELOW_THRESHOLD"
    assert not (tmp_path / "backup.db").exists()
