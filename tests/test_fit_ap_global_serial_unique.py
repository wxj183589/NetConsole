from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from netconsole.core.database import (
    AC_FIT_AP_DETAILS_SCHEMA,
    AC_FIT_AP_RADIO_DETAILS_SCHEMA,
    AC_FIT_AP_RESOURCES_SCHEMA,
    CURRENT_SCHEMA_VERSION,
    Database,
    FIT_AP_LLDP_BOUNDED_SCHEMA,
    FitApSerialGlobalConflictError,
)
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.lldp_retention import upsert_lldp_current_and_history


RESOURCE_SERIAL_INDEX = "idx_ac_fit_ap_resources_serial_identity_ac"
ENTITY_SERIAL_INDEX = "idx_ap_entities_serial_identity_global"


def _database(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def _index_columns(connection, index_name):
    return tuple(
        row["name"]
        for row in connection.execute(
            f"PRAGMA index_info('{index_name}')"
        ).fetchall()
    )


def _insert_entity(connection, ap_uuid, serial_number, *, site_id="site-a"):
    connection.execute(
        """
        INSERT INTO ap_entities (
            ap_uuid, site_id, serial_number, created_at, updated_at
        ) VALUES (?, ?, ?, '2026-08-31T00:00:00', '2026-08-31T00:00:00')
        """,
        (ap_uuid, site_id, serial_number),
    )


def _insert_resource(connection, ac_device_uuid, ap_uuid, serial_number, *, apid=""):
    connection.execute(
        """
        INSERT INTO ac_fit_ap_resources (
            ac_device_uuid, ap_uuid, apid, serial_number,
            collected_at, updated_at
        ) VALUES (?, ?, ?, ?, '2026-08-31T00:00:00', '2026-08-31T00:00:00')
        """,
        (ac_device_uuid, ap_uuid, apid, serial_number),
    )


def _drop_table(connection, table_name):
    for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (table_name,),
    ).fetchall():
        connection.execute(f'DROP TRIGGER "{row["name"]}"')
    for row in connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
        (table_name,),
    ).fetchall():
        if row["sql"]:
            connection.execute(f'DROP INDEX "{row["name"]}"')
    connection.execute(f'DROP TABLE "{table_name}"')


def test_fresh_database_has_entity_global_and_resource_ac_scoped_identity(tmp_path):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        resource_indexes = {
            row["name"]: dict(row)
            for row in connection.execute(
                "PRAGMA index_list('ac_fit_ap_resources')"
            ).fetchall()
        }
        entity_indexes = {
            row["name"]: dict(row)
            for row in connection.execute(
                "PRAGMA index_list('ap_entities')"
            ).fetchall()
        }
        assert _index_columns(connection, RESOURCE_SERIAL_INDEX) == (
            "ac_device_uuid",
            "serial_identity_key",
        )
        assert resource_indexes[RESOURCE_SERIAL_INDEX]["unique"] == 1
        assert resource_indexes[RESOURCE_SERIAL_INDEX]["partial"] == 1
        assert _index_columns(connection, ENTITY_SERIAL_INDEX) == (
            "serial_identity_key",
        )
        assert entity_indexes[ENTITY_SERIAL_INDEX]["unique"] == 1
        assert entity_indexes[ENTITY_SERIAL_INDEX]["partial"] == 1
        resource_unique_columns = {
            _index_columns(connection, name)
            for name, index in resource_indexes.items()
            if index["unique"]
        }
        assert ("ac_device_uuid", "ap_uuid") in resource_unique_columns
        assert ("ap_uuid",) not in resource_unique_columns
        assert "serial_identity_key" not in {
            row["name"]
            for table in ("fit_ap_resource_recent", "ac_fit_ap_resource_history")
            for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        }
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_direct_sql_allows_same_physical_serial_in_two_ac_resources(tmp_path):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        _insert_entity(connection, "ap-x", "SN001")
        _insert_resource(connection, "ac-a", "ap-x", " SN001 ", apid="10")
        _insert_resource(connection, "ac-b", "ap-x", "sn001", apid="253")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_resource(connection, "ac-a", "other", "SN001", apid="11")
        connection.commit()

        rows = connection.execute(
            """
            SELECT ac_device_uuid, ap_uuid, apid, serial_identity_key
            FROM ac_fit_ap_resources ORDER BY ac_device_uuid
            """
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("ac-a", "ap-x", "10", "sn001"),
            ("ac-b", "ap-x", "253", "sn001"),
        ]


def test_entity_serial_is_global_casefold_unique(tmp_path):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        _insert_entity(connection, "ap-x", "SN001")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_entity(connection, "ap-y", " sn001 ", site_id="site-b")


def test_repository_cross_ac_keeps_two_resources_and_one_entity(tmp_path):
    database = _database(tmp_path)
    repository = AcRepository(database)

    first = repository.replace_fit_ap_resources(
        "ac-a",
        [
            {
                "ap_uuid": "incoming-a",
                "ap_name": "AC-A AP",
                "apid": "10",
                "ap_ip": "10.0.0.1",
                "state": "Run",
                "serial_number": "SN001",
            }
        ],
    )
    second = repository.replace_fit_ap_resources(
        "ac-b",
        [
            {
                "ap_uuid": "incoming-b",
                "ap_name": "AC-B AP",
                "apid": "253",
                "ap_ip": "10.0.0.2",
                "state": "Idle",
                "serial_number": " sn001 ",
            }
        ],
    )

    with closing(database.connect()) as connection:
        resources = connection.execute(
            """
            SELECT ac_device_uuid, ap_uuid, ap_name, apid, ap_ip, state
            FROM ac_fit_ap_resources ORDER BY ac_device_uuid
            """
        ).fetchall()
        entity_count = connection.execute(
            "SELECT COUNT(*) FROM ap_entities WHERE serial_identity_key='sn001'"
        ).fetchone()[0]

    assert first.serial_identity_conflicts == 0
    assert second.serial_identity_conflicts == 0
    assert [
        (row["ac_device_uuid"], row["ap_name"], row["apid"], row["ap_ip"], row["state"])
        for row in resources
    ] == [
        ("ac-a", "AC-A AP", "10", "10.0.0.1", "Run"),
        ("ac-b", "AC-B AP", "253", "10.0.0.2", "Idle"),
    ]
    assert resources[0]["ap_uuid"] == resources[1]["ap_uuid"]
    assert entity_count == 1
    assert [row["apid"] for row in repository.list_fit_ap_resources("ac-a")] == ["10"]
    assert [row["apid"] for row in repository.list_fit_ap_resources("ac-b")] == ["253"]


def test_site_aggregate_keeps_independent_ap_batches_and_reuses_apid(tmp_path):
    database = _database(tmp_path)
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        "ac-a",
        [
            {"ap_uuid": f"a-{index}", "apid": "1", "serial_number": f"SN00{index}"}
            for index in range(1, 5)
        ],
    )
    repository.replace_fit_ap_resources(
        "ac-b",
        [
            {"ap_uuid": f"b-{index}", "apid": "1", "serial_number": f"SN00{index}"}
            for index in range(5, 9)
        ],
    )

    assert len(repository.list_fit_ap_resources("ac-a")) == 4
    assert len(repository.list_fit_ap_resources("ac-b")) == 4
    aggregate = repository.list_all_fit_ap_resources_with_metadata()
    assert len(aggregate) == 8
    assert [row["apid"] for row in aggregate].count("1") == 8


def test_batch_optical_lookup_keeps_same_physical_ap_for_each_ac(tmp_path):
    database = _database(tmp_path)
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        "ac-a",
        [{"ap_uuid": "incoming-a", "ap_mac": "0000-0000-0001", "serial_number": "SN001"}],
    )
    repository.replace_fit_ap_resources(
        "ac-b",
        [{"ap_uuid": "incoming-b", "ap_mac": "0000-0000-0001", "serial_number": "SN001"}],
    )
    repository.replace_fit_ap_optical(
        "ac-a",
        [{"ap_name": "AP-A", "ap_mac": "0000-0000-0001", "rx_power": "-8.1"}],
    )
    repository.replace_fit_ap_optical(
        "ac-b",
        [{"ap_name": "AP-B", "ap_mac": "0000-0000-0001", "rx_power": "-18.2"}],
    )

    rows = repository.list_fit_ap_optical_for_macs(["0000-0000-0001"])

    assert {(row["ac_device_uuid"], row["rx_power"]) for row in rows} == {
        ("ac-a", "-8.1"),
        ("ac-b", "-18.2"),
    }


def test_repository_full_replace_isolated_to_one_ac(tmp_path):
    database = _database(tmp_path)
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        "ac-a",
        [
            {"ap_uuid": "a1", "serial_number": "SN001"},
            {"ap_uuid": "a2", "serial_number": "SN002"},
        ],
    )
    repository.replace_fit_ap_resources(
        "ac-b",
        [
            {"ap_uuid": "b1", "serial_number": "SN005"},
            {"ap_uuid": "b2", "serial_number": "SN006"},
        ],
    )

    repository.replace_fit_ap_resources(
        "ac-a", [{"ap_uuid": "a1", "serial_number": "SN001"}]
    )

    assert {row["serial_number"] for row in repository.list_fit_ap_resources("ac-a")} == {"SN001"}
    assert {row["serial_number"] for row in repository.list_fit_ap_resources("ac-b")} == {"SN005", "SN006"}


def test_ac_scoped_detail_radio_and_lldp_current_do_not_cross_overwrite(tmp_path):
    database = _database(tmp_path)
    repository = AcRepository(database)
    repository.upsert_fit_ap_detail(
        {
            "ac_device_uuid": "ac-a",
            "ap_uuid": "ap-x",
            "ap_name": "A",
        }
    )
    repository.upsert_fit_ap_detail(
        {
            "ac_device_uuid": "ac-b",
            "ap_uuid": "ap-x",
            "ap_name": "B",
        }
    )
    repository.replace_fit_ap_radio_details(
        "ac-a", "ap-x", [{"radio_id": 1, "channel": "10"}]
    )
    repository.replace_fit_ap_radio_details(
        "ac-b", "ap-x", [{"radio_id": 1, "channel": "253"}]
    )

    with closing(database.connect()) as connection:
        upsert_lldp_current_and_history(
            connection,
                {
                    "ac_device_uuid": "ac-a",
                    "ap_uuid": "ap-x",
                    "ap_mac": "0011-2233-4455",
                    "lldp_local_interface": "GE1/0/1",
                    "lldp_neighbor_mac": "903f-8645-6e00",
                    "lldp_neighbor_interface": "GE2/0/1",
                },
            now="2026-08-31T00:00:00",
        )
        upsert_lldp_current_and_history(
            connection,
            {
                "ac_device_uuid": "ac-b",
                "ap_uuid": "ap-x",
                    "ap_mac": "0011-2233-4455",
                    "lldp_local_interface": "GE2/0/1",
                    "lldp_neighbor_mac": "903f-8645-6e00",
                    "lldp_neighbor_interface": "GE2/0/2",
            },
            now="2026-08-31T00:00:01",
        )
        upsert_lldp_current_and_history(
            connection,
            {
                "ac_device_uuid": "ac-a",
                "ap_uuid": "ap-x",
                "ap_mac": "0011-2233-4455",
                "lldp_local_interface": "GE1/0/2",
                "lldp_neighbor_mac": "903f-8645-6e00",
                "lldp_neighbor_interface": "GE2/0/3",
            },
            now="2026-08-31T00:00:02",
        )
        upsert_lldp_current_and_history(
            connection,
            {
                "ac_device_uuid": "ac-b",
                "ap_uuid": "ap-x",
                "ap_mac": "0011-2233-4455",
                "lldp_local_interface": "GE2/0/2",
                "lldp_neighbor_mac": "903f-8645-6e00",
                "lldp_neighbor_interface": "GE2/0/4",
            },
            now="2026-08-31T00:00:03",
        )
        connection.commit()

    assert repository.get_fit_ap_detail("ap-x", "ac-a")["ap_name"] == "A"
    assert repository.get_fit_ap_detail("ap-x", "ac-b")["ap_name"] == "B"
    assert repository.list_fit_ap_radio_details("ap-x", "ac-a")[0]["channel"] == "10"
    assert repository.list_fit_ap_radio_details("ap-x", "ac-b")[0]["channel"] == "253"
    with closing(database.connect()) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM fit_ap_lldp_current WHERE ap_uuid='ap-x'"
        ).fetchone()[0] == 2
    assert [
        row["local_interface"]
        for row in repository.list_fit_ap_lldp_history_by_ap(
            "ap-x", ac_device_uuid="ac-a"
        )
    ] == ["GigabitEthernet1/0/2"]
    assert [
        row["local_interface"]
        for row in repository.list_fit_ap_lldp_history_by_ap(
            "ap-x", ac_device_uuid="ac-b"
        )
    ] == ["GigabitEthernet2/0/2"]


@pytest.mark.parametrize("invalid_serial", [None, "", "-", "N/A", "UNKNOWN"])
def test_invalid_serials_have_no_strong_identity(tmp_path, invalid_serial):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        _insert_resource(connection, "ac-a", f"ap-a-{invalid_serial}", invalid_serial)
        _insert_resource(connection, "ac-b", f"ap-b-{invalid_serial}", invalid_serial)
        rows = connection.execute(
            "SELECT serial_number, serial_identity_key FROM ac_fit_ap_resources ORDER BY id"
        ).fetchall()

    assert len(rows) == 2
    assert all(row["serial_identity_key"] is None for row in rows)


def test_old_database_upgrade_rebuilds_scoped_current_tables_without_clearing_rows(tmp_path):
    database = _database(tmp_path)

    with closing(database.connect()) as connection:
        _drop_table(connection, "ac_fit_ap_resources")
        old_resources = (
            AC_FIT_AP_RESOURCES_SCHEMA
            .replace("    ap_uuid TEXT NOT NULL,", "    ap_uuid TEXT NOT NULL UNIQUE,", 1)
            .replace("UNIQUE(ac_device_uuid, ap_uuid)", "UNIQUE(ac_device_uuid, serial_number)")
        )
        connection.executescript(old_resources)
        connection.execute(
            "CREATE UNIQUE INDEX idx_ac_fit_ap_resources_serial_identity_global "
            "ON ac_fit_ap_resources(serial_identity_key) "
            "WHERE serial_identity_key IS NOT NULL AND serial_identity_key <> ''"
        )
        _insert_resource(connection, "ac-a", "ap-x", "SN-X")
        _drop_table(connection, "ac_fit_ap_details")
        old_details = AC_FIT_AP_DETAILS_SCHEMA.replace(
            "    ac_device_uuid TEXT NOT NULL,\n    ap_uuid TEXT NOT NULL,",
            "    ap_uuid TEXT PRIMARY KEY,\n    ac_device_uuid TEXT NOT NULL,",
        ).replace(",\n    PRIMARY KEY(ac_device_uuid, ap_uuid)", "")
        connection.executescript(old_details)
        connection.execute(
            "INSERT INTO ac_fit_ap_details(ap_uuid,ac_device_uuid,ap_name,collected_at,created_at,updated_at) "
            "VALUES('ap-x','ac-a','A','t','t','t')"
        )

        _drop_table(connection, "ac_fit_ap_radio_details")
        old_radio = (
            AC_FIT_AP_RADIO_DETAILS_SCHEMA
            .replace("    ac_device_uuid TEXT NOT NULL,\n", "")
            .replace("PRIMARY KEY(ac_device_uuid, ap_uuid, radio_id)", "PRIMARY KEY(ap_uuid, radio_id)")
            .replace(
                "ON ac_fit_ap_radio_details(ac_device_uuid, ap_uuid, radio_id)",
                "ON ac_fit_ap_radio_details(ap_uuid, radio_id)",
            )
        )
        connection.executescript(old_radio)
        connection.execute(
            "INSERT INTO ac_fit_ap_radio_details(ap_uuid,radio_id,collected_at,created_at,updated_at) "
            "VALUES('ap-x',1,'t','t','t')"
        )

        _drop_table(connection, "fit_ap_lldp_current")
        old_lldp = (
            FIT_AP_LLDP_BOUNDED_SCHEMA
            .replace("    resource_key TEXT NOT NULL,", "    resource_key TEXT PRIMARY KEY,")
            .replace("    ap_uuid TEXT NOT NULL,", "    ap_uuid TEXT NOT NULL UNIQUE,", 1)
            .replace(",\n    PRIMARY KEY(ac_device_uuid, ap_uuid)", "")
        )
        connection.executescript(old_lldp)
        connection.execute(
            "INSERT INTO fit_ap_lldp_current(resource_key,ac_device_uuid,ap_uuid,ap_name) "
            "VALUES('ap-x','ac-a','ap-x','A')"
        )
        connection.execute(
            "UPDATE schema_metadata SET value='2026.08.31.fit_ap_global_serial_unique_v1' "
            "WHERE key='schema_version'"
        )
        connection.commit()

    database.initialize()

    with closing(database.connect()) as connection:
        assert _index_columns(connection, "sqlite_autoindex_ac_fit_ap_details_1") == (
            "ac_device_uuid",
            "ap_uuid",
        )
        assert _index_columns(connection, "sqlite_autoindex_ac_fit_ap_radio_details_1") == (
            "ac_device_uuid",
            "ap_uuid",
            "radio_id",
        )
        assert _index_columns(connection, "sqlite_autoindex_fit_ap_lldp_current_1") == (
            "ac_device_uuid",
            "ap_uuid",
        )
        assert connection.execute(
            "SELECT ac_device_uuid FROM ac_fit_ap_details"
        ).fetchone()[0] == "ac-a"
        assert connection.execute(
            "SELECT ap_uuid FROM ac_fit_ap_resources"
        ).fetchone()[0] == "ap-x"
        assert _index_columns(
            connection, "idx_ac_fit_ap_resources_serial_identity_ac"
        ) == ("ac_device_uuid", "serial_identity_key")
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE name='idx_ac_fit_ap_resources_serial_identity_global'"
        ).fetchone()
        assert connection.execute(
            "SELECT ac_device_uuid FROM ac_fit_ap_radio_details"
        ).fetchone()[0] == "ac-a"
        assert connection.execute(
            "SELECT ac_device_uuid FROM fit_ap_lldp_current"
        ).fetchone()[0] == "ac-a"


def test_upgrade_stops_on_existing_global_serial_conflict_without_winner(tmp_path):
    database = _database(tmp_path)
    with closing(database.connect()) as connection:
        connection.execute("DROP INDEX idx_ap_entities_serial_identity_global")
        connection.execute("DROP TRIGGER trg_ap_entities_serial_identity_insert")
        connection.execute("DROP TRIGGER trg_ap_entities_serial_identity_update")
        connection.execute("ALTER TABLE ap_entities DROP COLUMN serial_identity_key")
        connection.execute(
            "CREATE UNIQUE INDEX idx_ap_entities_site_serial ON ap_entities(site_id, serial_number) "
            "WHERE serial_number IS NOT NULL AND trim(serial_number) != ''"
        )
        _insert_entity(connection, "ap-a", "SN-CONFLICT", site_id="site-a")
        _insert_entity(connection, "ap-b", "sn-conflict", site_id="site-b")
        connection.execute(
            "UPDATE schema_metadata SET value='2026.08.31.fit_ap_global_serial_unique_v1' "
            "WHERE key='schema_version'"
        )
        connection.commit()

    with pytest.raises(FitApSerialGlobalConflictError, match="GLOBAL_SERIAL_CONFLICT"):
        database.initialize()

    with closing(database.connect()) as connection:
        assert connection.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()[0] == "2026.08.31.fit_ap_global_serial_unique_v1"
        assert connection.execute("SELECT COUNT(*) FROM ap_entities").fetchone()[0] == 2
        assert "serial_identity_key" not in {
            row["name"]
            for row in connection.execute("PRAGMA table_info(ap_entities)").fetchall()
        }
