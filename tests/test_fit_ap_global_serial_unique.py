from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from netconsole.core.database import (
    CURRENT_SCHEMA_VERSION,
    Database,
    FitApSerialGlobalConflictError,
)
from netconsole.repositories.ac_repository import AcRepository


GLOBAL_SERIAL_INDEX = "idx_ac_fit_ap_resources_serial_identity_global"
SERIAL_TRIGGERS = (
    "trg_ac_fit_ap_resources_serial_identity_insert",
    "trg_ac_fit_ap_resources_serial_identity_update",
)


def _database(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def _insert_resource(connection, ac_device_uuid, ap_uuid, serial_number):
    connection.execute(
        """
        INSERT INTO ac_fit_ap_resources (
            ac_device_uuid, ap_uuid, serial_number, collected_at, updated_at
        ) VALUES (?, ?, ?, '2026-08-31T00:00:00', '2026-08-31T00:00:00')
        """,
        (ac_device_uuid, ap_uuid, serial_number),
    )


def _index_columns(connection, index_name):
    return tuple(
        row["name"]
        for row in connection.execute(
            f"PRAGMA index_info('{index_name}')"
        ).fetchall()
    )


def _drop_serial_identity_objects(connection, *, drop_column=False):
    for trigger_name in SERIAL_TRIGGERS:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    connection.execute(f"DROP INDEX IF EXISTS {GLOBAL_SERIAL_INDEX}")
    if drop_column:
        connection.execute(
            "ALTER TABLE ac_fit_ap_resources DROP COLUMN serial_identity_key"
        )


def test_fresh_database_has_global_identity_without_history_constraints(tmp_path):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        columns = {
            row["name"] for row in connection.execute(
                "PRAGMA table_info(ac_fit_ap_resources)"
            ).fetchall()
        }
        indexes = {
            row["name"]: dict(row)
            for row in connection.execute(
                "PRAGMA index_list('ac_fit_ap_resources')"
            ).fetchall()
        }
        object_names = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type IN ('index', 'trigger')
                """
            ).fetchall()
        }
        history_index_names = {
            row["name"]
            for table in ("fit_ap_resource_recent", "ac_fit_ap_resource_history")
            for row in connection.execute(f"PRAGMA index_list('{table}')").fetchall()
        }

        assert "serial_identity_key" in columns
        assert indexes[GLOBAL_SERIAL_INDEX]["unique"] == 1
        assert indexes[GLOBAL_SERIAL_INDEX]["partial"] == 1
        assert _index_columns(connection, GLOBAL_SERIAL_INDEX) == (
            "serial_identity_key",
        )
        assert SERIAL_TRIGGERS[0] in object_names
        assert SERIAL_TRIGGERS[1] in object_names
        assert "serial_identity_key" not in history_index_names

        unique_columns = {
            _index_columns(connection, index_name)
            for index_name, index in indexes.items()
            if index["unique"]
        }
        assert ("ap_uuid",) in unique_columns
        assert ("ac_device_uuid", "serial_number") in unique_columns


def test_direct_sql_cross_ac_duplicate_is_blocked_by_sqlite(tmp_path):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        _insert_resource(connection, "ac-a", "ap-a", " SN001 ")
        first = connection.execute(
            """
            SELECT serial_number, serial_identity_key
            FROM ac_fit_ap_resources WHERE ap_uuid = 'ap-a'
            """
        ).fetchone()
        assert first["serial_number"] == " SN001 "
        assert first["serial_identity_key"] == "sn001"
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="serial_identity_key"):
            _insert_resource(connection, "ac-b", "ap-b", "ＳＮ００１")
        connection.rollback()

        assert connection.execute(
            "SELECT COUNT(*) FROM ac_fit_ap_resources"
        ).fetchone()[0] == 1


def test_repository_reconciliation_across_ac_preserves_canonical_ap_uuid(tmp_path):
    database = _database(tmp_path)
    repository = AcRepository(database)

    repository.replace_fit_ap_resources(
        "ac-a", [{"ap_uuid": "canonical", "ap_name": "old", "serial_number": "SN001"}]
    )
    result = repository.replace_fit_ap_resources(
        "ac-b", [{"ap_uuid": "incoming", "ap_name": "new", "serial_number": " sn001 "}]
    )

    with closing(database.connect()) as connection:
        resources = connection.execute(
            "SELECT ap_uuid, serial_identity_key, ap_name FROM ac_fit_ap_resources"
        ).fetchall()
        entities = connection.execute(
            "SELECT ap_uuid FROM ap_entities WHERE serial_number IS NOT NULL"
        ).fetchall()

    assert result.serial_identity_conflicts == 0
    assert [dict(row) for row in resources] == [
        {"ap_uuid": "canonical", "serial_identity_key": "sn001", "ap_name": "new"}
    ]
    assert [row["ap_uuid"] for row in entities] == ["canonical"]
    assert "serial_identity_key" not in repository.list_fit_ap_resources("ac-a")[0]


@pytest.mark.parametrize(
    "invalid_serial",
    [None, "", "-", "--", "N/A", "NA", "NONE", "NULL", "UNKNOWN"],
)
def test_invalid_serials_are_excluded_from_global_identity(tmp_path, invalid_serial):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        _insert_resource(connection, "ac-a", f"ap-a-{invalid_serial}", invalid_serial)
        _insert_resource(connection, "ac-b", f"ap-b-{invalid_serial}", invalid_serial)
        rows = connection.execute(
            """
            SELECT serial_number, serial_identity_key
            FROM ac_fit_ap_resources ORDER BY ap_uuid
            """
        ).fetchall()

    assert len(rows) == 2
    assert all(row["serial_identity_key"] is None for row in rows)


def test_old_database_upgrade_adds_identity_objects_and_is_idempotent(tmp_path):
    database = _database(tmp_path)
    with closing(database.connect()) as connection:
        _drop_serial_identity_objects(connection, drop_column=True)
        connection.execute(
            "UPDATE schema_metadata SET value = '2026.08.30.ap_optical_treatment_serial_backfill_v1' "
            "WHERE key = 'schema_version'"
        )
        connection.commit()

    database.initialize()
    database.initialize()

    with closing(database.connect()) as connection:
        assert "serial_identity_key" in {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(ac_fit_ap_resources)"
            ).fetchall()
        }
        assert _index_columns(connection, GLOBAL_SERIAL_INDEX) == (
            "serial_identity_key",
        )
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_upgrade_stops_on_existing_global_serial_conflict_without_winner(tmp_path):
    database = _database(tmp_path)
    with closing(database.connect()) as connection:
        _drop_serial_identity_objects(connection, drop_column=True)
        _insert_resource(connection, "ac-a", "ap-a", "SN-CONFLICT")
        _insert_resource(connection, "ac-b", "ap-b", "sn-conflict")
        connection.execute(
            "UPDATE schema_metadata SET value = '2026.08.30.ap_optical_treatment_serial_backfill_v1' "
            "WHERE key = 'schema_version'"
        )
        connection.commit()

    with pytest.raises(FitApSerialGlobalConflictError, match="GLOBAL_SERIAL_CONFLICT"):
        database.initialize()

    with closing(database.connect()) as connection:
        rows = connection.execute(
            "SELECT ap_uuid, ac_device_uuid, serial_number FROM ac_fit_ap_resources ORDER BY ap_uuid"
        ).fetchall()
        assert [(row["ap_uuid"], row["ac_device_uuid"], row["serial_number"]) for row in rows] == [
            ("ap-a", "ac-a", "SN-CONFLICT"),
            ("ap-b", "ac-b", "sn-conflict"),
        ]
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?",
            (GLOBAL_SERIAL_INDEX,),
        ).fetchone()
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0] == "2026.08.30.ap_optical_treatment_serial_backfill_v1"
