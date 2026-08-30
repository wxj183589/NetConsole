from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.h3c_ac_collect_service import FIT_AP_RESOURCE_OPTIONAL_COMMANDS


def _repository(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database, AcRepository(database)


def _rows(repository: AcRepository, database: Database, ac_uuid: str = "ac-1"):
    resources = repository.list_fit_ap_resources(ac_uuid)
    with database.connect() as conn:
        entities = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM ap_entities WHERE ac_device_uuid = ? ORDER BY ap_uuid",
                (ac_uuid,),
            ).fetchall()
        ]
    return resources, entities


def test_fit_ap_empty_serial_insert_does_not_enter_identity_key(tmp_path):
    database, repository = _repository(tmp_path)

    result = repository.replace_fit_ap_resources(
        "ac-1", [{"ap_uuid": "ap-empty", "ap_name": "AP-empty", "serial_number": ""}]
    )

    resources, entities = _rows(repository, database)
    assert result.serial_identity_conflicts == 0
    assert len(resources) == len(entities) == 1
    assert resources[0]["serial_number"] is None
    assert entities[0]["serial_number"] is None


def test_fit_ap_same_uuid_is_updated_in_place(tmp_path):
    _database, repository = _repository(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1", [{"ap_uuid": "ap-1", "ap_name": "old", "serial_number": "SN-1"}]
    )

    result = repository.replace_fit_ap_resources(
        "ac-1", [{"ap_uuid": "ap-1", "ap_name": "new", "serial_number": "SN-1"}]
    )

    resource = repository.list_fit_ap_resources("ac-1")[0]
    assert result.serial_identity_conflicts == 0
    assert resource["ap_uuid"] == "ap-1"
    assert resource["ap_name"] == "new"
    assert len(repository.list_fit_ap_resources("ac-1")) == 1


def test_fit_ap_new_uuid_same_serial_resolves_to_existing_canonical(tmp_path):
    database, repository = _repository(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1", [{"ap_uuid": "canonical", "ap_name": "AP-1", "serial_number": "SN-2"}]
    )

    result = repository.replace_fit_ap_resources(
        "ac-1", [{"ap_uuid": "incoming", "ap_name": "AP-1-new", "serial_number": "SN-2"}]
    )

    resources, entities = _rows(repository, database)
    assert result.serial_identity_conflicts == 0
    assert resources[0]["ap_uuid"] == entities[0]["ap_uuid"] == "canonical"
    assert resources[0]["ap_name"] == "AP-1-new"
    assert len(resources) == len(entities) == 1


def test_fit_ap_same_batch_serial_rows_merge_complementary_fields(tmp_path):
    database, repository = _repository(tmp_path)

    result = repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "AP-merge",
                "ap_mac": "0011-2233-4455",
                "serial_number": "SN-3",
                "rid1_channel": "149",
            },
            {
                "ap_name": "AP-merge",
                "ap_mac": "0011-2233-4455",
                "serial_number": "SN-3",
                "rid1_usage": "27",
            },
        ],
    )

    resources, entities = _rows(repository, database)
    assert result.batch_serial_duplicates == 1
    assert result.batch_serial_merged == 1
    assert result.serial_identity_conflicts == 0
    assert len(resources) == len(entities) == 1
    assert resources[0]["rid1_channel"] == "149"
    assert resources[0]["rid1_usage"] == "27"


def test_fit_ap_same_serial_and_mac_is_idempotent(tmp_path):
    _database, repository = _repository(tmp_path)
    row = {"ap_name": "AP-same", "ap_mac": "0011-2233-4455", "serial_number": "SN-4"}

    repository.replace_fit_ap_resources("ac-1", [row])
    result = repository.replace_fit_ap_resources("ac-1", [dict(row)])

    assert result.serial_identity_conflicts == 0
    assert len(repository.list_fit_ap_resources("ac-1")) == 1


def test_fit_ap_mac_change_with_canonical_uuid_merges_to_same_entity(tmp_path):
    database, repository = _repository(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [{"ap_uuid": "canonical", "ap_mac": "0011-2233-4455", "serial_number": "SN-5"}],
    )

    result = repository.replace_fit_ap_resources(
        "ac-1",
        [{"ap_uuid": "canonical", "ap_mac": "0011-2233-5566", "serial_number": "SN-5"}],
    )

    resources, entities = _rows(repository, database)
    assert result.serial_identity_conflicts == 0
    assert len(resources) == len(entities) == 1
    assert resources[0]["ap_uuid"] == entities[0]["ap_uuid"] == "canonical"
    assert resources[0]["ap_mac"] == "0011-2233-5566"


def test_fit_ap_same_serial_multiple_macs_is_explicit_conflict_and_preserves_original(tmp_path):
    database, repository = _repository(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1",
        [{"ap_uuid": "canonical", "ap_mac": "0011-2233-4455", "serial_number": "SN-6"}],
    )

    result = repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_mac": "0011-2233-5566", "serial_number": "SN-6"},
            {"ap_mac": "0011-2233-6677", "serial_number": "SN-6"},
        ],
    )

    resources, entities = _rows(repository, database)
    assert result.batch_serial_duplicates == 1
    assert result.batch_serial_merged == 0
    assert result.serial_identity_conflicts == 1
    assert len(resources) == len(entities) == 1
    assert resources[0]["ap_uuid"] == "canonical"
    assert resources[0]["ap_mac"] == "0011-2233-4455"


def test_fit_ap_new_conflicting_serial_batch_is_skipped_without_deleting_existing_rows(tmp_path):
    database, repository = _repository(tmp_path)
    repository.replace_fit_ap_resources(
        "ac-1", [{"ap_uuid": "known", "ap_name": "known", "serial_number": "SN-known"}]
    )

    result = repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_mac": "0011-2233-5566", "serial_number": "SN-new"},
            {"ap_mac": "0011-2233-6677", "serial_number": "SN-new"},
        ],
    )

    resources, entities = _rows(repository, database)
    assert result.serial_identity_conflicts == 1
    assert len(resources) == len(entities) == 1
    assert resources[0]["ap_uuid"] == "known"


def test_fit_ap_different_serial_same_mac_is_not_merged(tmp_path):
    database, repository = _repository(tmp_path)

    result = repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_mac": "0011-2233-4455", "serial_number": "SN-7"},
            {"ap_mac": "0011-2233-4455", "serial_number": "SN-8"},
        ],
    )

    resources, entities = _rows(repository, database)
    assert result.serial_identity_conflicts == 1
    assert len(resources) == len(entities) == 1
    assert resources[0]["serial_number"] == "SN-7"


def test_fit_ap_invalid_serial_sentinels_are_weak_identity(tmp_path):
    database, repository = _repository(tmp_path)

    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_mac": "0011-2233-4455", "serial_number": "--"},
            {"ap_mac": "0011-2233-5566", "serial_number": "UNKNOWN"},
        ],
    )

    resources, entities = _rows(repository, database)
    assert len(resources) == len(entities) == 2
    assert {row["serial_number"] for row in resources} == {None}


def test_fit_ap_unauthenticated_source_remains_separate_from_fit_resources(tmp_path):
    database, repository = _repository(tmp_path)
    assert "display wlan ap unauthenticated" in FIT_AP_RESOURCE_OPTIONAL_COMMANDS

    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "AP-auth", "serial_number": "SN-9"}])
    repository.replace_fit_ap_unauthenticated(
        "ac-1",
        {"snapshot_status": "SUCCESS_WITH_ROWS"},
        [{"ap_name": "AP-unauth", "apid": "99", "source": "wlan_ap_unauthenticated"}],
    )

    resources, _entities = _rows(repository, database)
    assert [row["ap_name"] for row in resources] == ["AP-auth"]
    with database.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ac_fit_ap_unauthenticated WHERE ac_device_uuid = ?",
            ("ac-1",),
        ).fetchone()[0] == 1


def test_fit_ap_resource_serial_unique_constraint_is_kept_in_new_database(tmp_path):
    database, _repo = _repository(tmp_path)
    with database.connect() as conn:
        indexes = conn.execute("PRAGMA index_list('ac_fit_ap_resources')").fetchall()
        unique_indexes = [row for row in indexes if row[2]]
        columns = {
            tuple(item[2] for item in conn.execute(f"PRAGMA index_info('{row[1]}')").fetchall())
            for row in unique_indexes
        }

    assert ("ac_device_uuid", "ap_uuid") in columns
    assert ("ac_device_uuid", "serial_identity_key") in columns
    assert ("ap_uuid",) not in columns
    assert ("ac_device_uuid", "serial_number") not in columns
