from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.services.site_sync import _mapping_identity_conflicts


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/rail-transit/online-mr/TASK_SESSION_CONTRACT.md"


def test_online_mr_session_contract_names_all_shared_consumers() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for marker in (
        "operational authority",
        "OnlineMrApplicationService",
        "restart / resume / reconcile",
        "Site Return Package",
        "import/export",
        "Ground Unattended",
        "Renderer UI",
        "cleanup / retention",
        "task_results",
        "schema v3",
    ):
        assert marker in text


def test_session_mapping_identity_conflict_is_fail_closed() -> None:
    rows = [
        {
            "controller_task_id": "controller-local",
            "session_id": "session-1",
            "agent_id": "agent-1",
            "agent_task_id": "agent-task-1",
        },
        {
            "controller_task_id": "controller-returned",
            "session_id": "session-1",
            "agent_id": "agent-1",
            "agent_task_id": "agent-task-2",
        },
    ]
    conflicts = _mapping_identity_conflicts(rows)
    assert {item.field for item in conflicts} == {"session_id"}
    assert conflicts[0].entity_type == "online_mr_task_session"


def test_session_mapping_schema_keeps_operational_identity_and_no_credentials(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    repository = OnlineMrTaskSessionRepository(database, site_id="site-a")
    with sqlite3.connect(database) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(online_mr_task_sessions)"
            )
        }
        assert {"controller_task_id", "session_id", "mapping_state", "agent_task_id", "remote_package_id", "deadline_at"} <= columns
        assert not {"password", "token", "config"} & columns
    assert repository.schema_version() == 3


def test_terminal_mapping_is_not_an_active_recovery_candidate(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    repository = OnlineMrTaskSessionRepository(database, site_id="site-a")
    assert repository.list_active() == []
