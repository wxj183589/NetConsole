from __future__ import annotations

import json
from pathlib import Path

from scripts.storage.generate_storage_retention_policy import generate_storage_retention_policy


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _inputs(root: Path) -> None:
    _write(root / "RAIL_TRANSIT_ANALYSIS.json", {
        "total_size_bytes": 1000,
        "extension_summary": [
            {"extension": ".sqlite", "size_bytes": 600, "file_count": 3},
            {"extension": ".log", "size_bytes": 200, "file_count": 2},
            {"extension": ".json", "size_bytes": 50, "file_count": 2},
            {"extension": ".zip", "size_bytes": 50, "file_count": 1},
        ],
    })
    _write(root / "BACKUP_ANALYSIS.json", {
        "total_size_bytes": 500,
        "total_files": 3,
        "backups": [
            {"backup_type": "PRODUCTION_MAINTENANCE", "size_bytes": 400},
            {"backup_type": "DATABASE_MIGRATION", "size_bytes": 100},
        ],
    })
    _write(root / "HISTORY_DB_ANALYSIS.json", {
        "total_size_bytes": 300,
        "total_files": 1,
        "databases": [{"path": "db/history/devices.db", "tables": [{"table_name": "history_events_v2", "size_bytes": 200, "row_count": 10}]}],
    })
    _write(root / "TOP_TABLE_USAGE.json", {
        "tables": [
            {"database": "db/tasks.db", "table_name": "task_results", "size_bytes": 100},
            {"database": "db/tasks.db", "table_name": "task_events", "size_bytes": 50},
        ],
    })


def test_policy_generates_policy_and_priority_markdown(tmp_path: Path) -> None:
    source = tmp_path / "inputs"
    output = tmp_path / "output"
    _inputs(source)
    (source / "STORAGE_LIFECYCLE_REPORT.md").write_text("lifecycle", encoding="utf-8")
    (source / "STORAGE_GOVERNANCE_MATRIX.md").write_text("matrix", encoding="utf-8")

    result = generate_storage_retention_policy(source, output)

    assert result["missing_reports"] == []
    policy = (output / "STORAGE_RETENTION_POLICY.md").read_text(encoding="utf-8")
    priority = (output / "STORAGE_GOVERNANCE_PRIORITY.md").read_text(encoding="utf-8")
    assert "## rail_transit Storage Policy" in policy
    assert "## Backup Storage Policy" in policy
    assert "## History Storage Policy" in policy
    assert "## Task Storage Policy" in policy
    assert "## Current Stage Restrictions" in policy
    assert "建议评估" in policy
    assert "| rail_transit analysis sqlite |" in priority
    assert "| files/backups |" in priority


def test_empty_input_reports_gaps_and_still_generates(tmp_path: Path) -> None:
    source = tmp_path / "empty"
    source.mkdir()
    output = tmp_path / "output"

    result = generate_storage_retention_policy(source, output)

    assert len(result["missing_reports"]) == 6
    policy = (output / "STORAGE_RETENTION_POLICY.md").read_text(encoding="utf-8")
    assert "## Input Gaps" in policy
    assert "需要人工确认" in policy


def test_missing_fields_do_not_block_markdown(tmp_path: Path) -> None:
    source = tmp_path / "inputs"
    source.mkdir()
    for name in ("RAIL_TRANSIT_ANALYSIS.json", "BACKUP_ANALYSIS.json", "HISTORY_DB_ANALYSIS.json", "TOP_TABLE_USAGE.json"):
        _write(source / name, {})
    output = tmp_path / "output"

    generate_storage_retention_policy(source, output)

    policy = (output / "STORAGE_RETENTION_POLICY.md").read_text(encoding="utf-8")
    priority = (output / "STORAGE_GOVERNANCE_PRIORITY.md").read_text(encoding="utf-8")
    assert "ANALYSIS_DATABASE" in policy
    assert "P1" in priority
