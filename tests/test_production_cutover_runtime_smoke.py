from __future__ import annotations

import json
from pathlib import Path

from scripts.maintenance.production_cutover_runtime_smoke import (
    _inspect_component_resume_journals,
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
