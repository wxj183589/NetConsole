from __future__ import annotations

import hashlib
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.repositories.task_repository import TaskRepository


LEGACY_TASK_RESULTS_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER trg_task_results_immutable
BEFORE UPDATE ON task_results
WHEN NOT (
    OLD.result_id = NEW.result_id
    AND OLD.task_id = NEW.task_id
    AND OLD.terminal_event_type = NEW.terminal_event_type
    AND OLD.canonical_json = NEW.canonical_json
    AND OLD.sha256 = NEW.sha256
    AND OLD.byte_size = NEW.byte_size
    AND OLD.schema_version = NEW.schema_version
    AND OLD.created_time = NEW.created_time
    AND OLD.content_sha256 = NEW.content_sha256
    AND OLD.blob_codec = NEW.blob_codec
    AND OLD.blob_ready = NEW.blob_ready
)
BEGIN
    SELECT RAISE(ABORT, 'task_results rows are immutable');
END;
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkpoint(path: Path) -> None:
    with connect_sqlite(path, foreign_keys=True) as connection:
        assert tuple(connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()) == (
            0,
            0,
            0,
        )


def _trigger_sql(path: Path) -> str:
    with connect_sqlite(path, foreign_keys=True) as connection:
        return str(
            connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='trigger' AND name='trg_task_results_immutable'"
            ).fetchone()[0]
        )


def test_reopening_current_task_repository_is_physically_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tasks.db"
    TaskRepository(database)
    _checkpoint(database)
    before = _sha256(database)

    TaskRepository(database)
    _checkpoint(database)

    assert _sha256(database) == before
    with connect_sqlite(database, foreign_keys=True) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_legacy_task_result_trigger_is_upgraded_once(tmp_path: Path) -> None:
    database = tmp_path / "tasks.db"
    TaskRepository(database)
    with connect_sqlite(database, foreign_keys=True) as connection:
        connection.execute("DROP TRIGGER trg_task_results_immutable")
        connection.execute(LEGACY_TASK_RESULTS_IMMUTABLE_TRIGGER_SQL)
        connection.commit()
    _checkpoint(database)

    TaskRepository(database)
    _checkpoint(database)
    upgraded = _sha256(database)
    trigger_sql = _trigger_sql(database)
    assert "OLD.blob_ready = 0" in trigger_sql
    assert "NEW.blob_codec = 'zlib'" in trigger_sql

    TaskRepository(database)
    _checkpoint(database)
    assert _sha256(database) == upgraded
