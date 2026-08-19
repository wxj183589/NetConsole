from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.history_legacy_migration_repository import (
    HistoryLegacyMigrationRepository,
    TableCheckpoint,
)


LEGACY_HISTORY_TABLES = (
    "ac_fit_ap_resource_history",
    "ac_fit_ap_radio_history",
    "ac_fit_ap_lldp_history",
    "ac_fit_ap_optical_history",
    "ap_lldp_history",
    "ap_optical_history",
)


def _repository(tmp_path) -> AcRepository:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return AcRepository(database)


def _record_event(
    repository: AcRepository,
    *,
    kind: str,
    entity_key: str,
    payload: dict[str, object],
    collected_at: str = "2026-08-01T10:00:00",
) -> None:
    with repository.database.connect() as conn:
        repository.history_store.record_event(
            conn,
            kind=kind,
            entity_key=entity_key,
            payload=payload,
            collected_at=collected_at,
            meaningful_fields=tuple(sorted(payload)),
        )
        conn.commit()


def _mark_shard_authoritative(repository: AcRepository, *source_tables: str) -> None:
    journal = HistoryLegacyMigrationRepository(
        repository.history_store.history_root / "catalog.db"
    )
    journal.create_or_load(
        migration_id="cutover",
        source_database_identity="fixture",
        source_schema_version="fixture",
        site_id="fixture",
        chunk_rows=1,
        now="2026-08-01T00:00:00",
    )
    for source_table in source_tables:
        journal.upsert_table_checkpoint(
            TableCheckpoint(
                migration_id="cutover",
                source_table=source_table,
                source_range="0..0",
                last_source_key=0,
                copied_count=0,
                verified_count=0,
                duplicate_count=0,
                error_count=0,
                status="VERIFIED",
                updated_at="2026-08-01T00:00:00",
            )
        )
        verified = journal.transition_authority(
            "cutover",
            source_table,
            to_state="SHARD_VERIFIED",
            expected_revision=0,
            reason="fixture copy verified",
            now="2026-08-01T00:00:01",
        )
        journal.transition_authority(
            "cutover",
            source_table,
            to_state="SHARD_AUTHORITY",
            expected_revision=verified.cutover_revision,
            reason="fixture consumer validation",
            now="2026-08-01T00:00:02",
        )


def _insert_legacy_lldp(repository: AcRepository, ap_uuid: str) -> None:
    with repository.database.connect() as conn:
        conn.execute(
            """
            INSERT INTO ac_fit_ap_lldp_history
                (ac_device_uuid, ap_uuid, ap_name, local_interface,
                 local_interface_normalized, lldp_neighbor, neighbor_interface,
                 neighbor_mac, neighbor_mac_normalized, neighbor_device_name,
                 neighbor_name, collected_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ac-1",
                ap_uuid,
                "AP-1",
                "GigabitEthernet1/0/1",
                "GigabitEthernet1/0/1",
                "SW-LEGACY",
                "GigabitEthernet1/0/2",
                "00:11:22:33:44:55",
                "001122334455",
                "SW-LEGACY",
                "SW-LEGACY",
                "2026-08-01T09:00:00",
                "2026-08-01T09:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO ap_lldp_history
                (history_uuid, ap_uuid, ap_name, neighbor_switch_name,
                 neighbor_switch_sysname, neighbor_interface, collected_at,
                 is_latest, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                "legacy-lldp-1",
                ap_uuid,
                "AP-1",
                "SW-LEGACY",
                "SW-LEGACY",
                "GigabitEthernet1/0/2",
                "2026-08-01T09:00:00",
                "2026-08-01T09:00:00",
            ),
        )
        conn.commit()


def _drop_legacy_history_tables(repository: AcRepository) -> None:
    with repository.database.connect() as conn:
        for table in LEGACY_HISTORY_TABLES:
            conn.execute(f"DROP TABLE {table}")
        conn.commit()


def _lldp_payload(ap_uuid: str, neighbor: str = "SW-HISTORY") -> dict[str, object]:
    return {
        "ac_device_uuid": "ac-1",
        "ap_uuid": ap_uuid,
        "ap_name": "AP-1",
        "local_interface": "GigabitEthernet1/0/1",
        "local_interface_normalized": "GigabitEthernet1/0/1",
        "lldp_neighbor": neighbor,
        "neighbor_name": neighbor,
        "neighbor_device_name": neighbor,
        "neighbor_interface": "GigabitEthernet1/0/2",
        "neighbor_mac": "00:11:22:33:44:55",
        "neighbor_mac_normalized": "001122334455",
    }


def test_legacy_authority_reads_legacy_lldp_without_history_events(tmp_path) -> None:
    repository = _repository(tmp_path)
    ap_uuid = "ap-legacy"
    _insert_legacy_lldp(repository, ap_uuid)

    assert repository.list_fit_ap_lldp_history_by_ap(ap_uuid)[0]["lldp_neighbor"] == "SW-LEGACY"
    assert repository.list_fit_ap_history_page("lldp", ap_uuid)[0]["lldp_neighbor"] == "SW-LEGACY"
    assert repository.count_fit_ap_history("lldp", ap_uuid) == 1
    assert repository.list_latest_ap_lldp_history(ap_uuid)["neighbor_interface"] == "GigabitEthernet1/0/2"
    assert repository.list_latest_ap_lldp_histories()[0]["ap_uuid"] == ap_uuid
    assert repository.list_all_ap_lldp_history()[0]["ap_uuid"] == ap_uuid
    assert repository.get_previous_ap_lldp_history({"ap_uuid": ap_uuid}) is not None


def test_shard_authority_excludes_existing_legacy_lldp_rows(tmp_path) -> None:
    repository = _repository(tmp_path)
    ap_uuid = "ap-cutover"
    _insert_legacy_lldp(repository, ap_uuid)
    _mark_shard_authoritative(
        repository,
        "ac_fit_ap_lldp_history",
        "ap_lldp_history",
    )
    _record_event(
        repository,
        kind="fit_ap_lldp",
        entity_key=ap_uuid,
        payload=_lldp_payload(ap_uuid),
    )

    assert [row["lldp_neighbor"] for row in repository.list_fit_ap_lldp_history_by_ap(ap_uuid)] == ["SW-HISTORY"]
    assert [row["lldp_neighbor"] for row in repository.list_fit_ap_history_page("lldp", ap_uuid)] == ["SW-HISTORY"]
    assert repository.count_fit_ap_history("lldp", ap_uuid) == 1
    assert repository.list_latest_ap_lldp_history(ap_uuid)["lldp_neighbor"] == "SW-HISTORY"
    assert [row["lldp_neighbor"] for row in repository.list_latest_ap_lldp_histories()] == ["SW-HISTORY"]
    assert [row["lldp_neighbor"] for row in repository.list_all_ap_lldp_history()] == ["SW-HISTORY"]
    assert repository.get_previous_ap_lldp_history({"ap_uuid": ap_uuid})["lldp_neighbor"] == "SW-HISTORY"


def test_dropped_legacy_tables_read_history_store_and_keep_counts_consistent(tmp_path) -> None:
    repository = _repository(tmp_path)
    ap_uuid = "ap-dropped"
    _drop_legacy_history_tables(repository)
    _record_event(
        repository,
        kind="fit_ap_resource",
        entity_key=f"ac-1:{ap_uuid}",
        payload={"ac_device_uuid": "ac-1", "ap_uuid": ap_uuid, "ap_name": "AP-1"},
    )
    _record_event(
        repository,
        kind="fit_ap_radio",
        entity_key=f"{ap_uuid}:1",
        payload={"ac_device_uuid": "ac-1", "ap_uuid": ap_uuid, "rid": 1},
    )
    _record_event(
        repository,
        kind="fit_ap_lldp",
        entity_key=ap_uuid,
        payload=_lldp_payload(ap_uuid),
    )
    _record_event(
        repository,
        kind="fit_ap_optical",
        entity_key=ap_uuid,
        payload={"ac_device_uuid": "ac-1", "ap_uuid": ap_uuid, "rx_power": "-8.1"},
    )

    assert repository.list_fit_ap_resource_history("ac-1")[0]["ap_uuid"] == ap_uuid
    assert repository.list_fit_ap_radio_history_by_ap(ap_uuid)[0]["rid"] == 1
    assert repository.list_fit_ap_optical_history_by_ap(ap_uuid)[0]["rx_power"] == "-8.1"
    assert repository.list_all_ap_optical_history()[0]["ap_uuid"] == ap_uuid
    assert repository.list_fit_ap_lldp_history_by_ap(ap_uuid)[0]["lldp_neighbor"] == "SW-HISTORY"
    assert repository.list_fit_ap_history_page("lldp", ap_uuid)[0]["ap_uuid"] == ap_uuid
    assert repository.count_fit_ap_history("lldp", ap_uuid) == 1
    assert repository.list_latest_ap_lldp_history(ap_uuid)["ap_uuid"] == ap_uuid
    assert repository.list_latest_ap_lldp_histories()[0]["ap_uuid"] == ap_uuid
    assert repository.list_all_ap_lldp_history()[0]["ap_uuid"] == ap_uuid
    assert repository.get_previous_ap_lldp_history({"ap_uuid": ap_uuid}) is not None
    with repository.database.connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_dropped_legacy_tables_without_history_events_return_empty_results(tmp_path) -> None:
    repository = _repository(tmp_path)
    _drop_legacy_history_tables(repository)

    assert repository.list_fit_ap_resource_history("ac-1") == []
    assert repository.list_fit_ap_radio_history_by_ap("missing") == []
    assert repository.list_fit_ap_optical_history_by_ap("missing") == []
    assert repository.list_all_ap_optical_history() == []
    assert repository.list_fit_ap_lldp_history_by_ap("missing") == []
    assert repository.list_fit_ap_history_page("lldp", "missing") == []
    assert repository.count_fit_ap_history("lldp", "missing") == 0
    assert repository.list_latest_ap_lldp_history("missing") is None
    assert repository.list_latest_ap_lldp_histories() == []
    assert repository.list_all_ap_lldp_history() == []
    assert repository.get_previous_ap_lldp_history({"ap_uuid": "missing"}) is None


def test_device_fact_history_reads_history_store_after_legacy_tables_are_retired(tmp_path) -> None:
    repository = _repository(tmp_path)
    facts = DeviceFactRepository(repository.database)
    with repository.database.connect() as conn:
        for table in (
            "device_facts_history",
            "device_interfaces_history",
            "device_optical_modules_history",
            "device_lldp_neighbors_history",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.commit()
    _record_event(
        repository,
        kind="device_fact",
        entity_key="device-1",
        payload={"device_uuid": "device-1", "model": "S6520"},
    )
    _record_event(
        repository,
        kind="device_interface",
        entity_key="device-1:GE1/0/1",
        payload={"device_uuid": "device-1", "interface_name": "GE1/0/1"},
    )
    _record_event(
        repository,
        kind="device_optical",
        entity_key="device-1:GE1/0/1",
        payload={
            "device_uuid": "device-1",
            "interface_name": "GE1/0/1",
            "rx_power": "-8.1",
        },
    )
    _record_event(
        repository,
        kind="device_lldp",
        entity_key="device-1:GE1/0/1",
        payload={
            "device_uuid": "device-1",
            "local_interface": "GE1/0/1",
            "neighbor_interface": "GE1/0/2",
        },
    )

    assert facts.list_fact_history("device-1")[0]["model"] == "S6520"
    assert facts.list_interface_history("device-1", "GE1/0/1")
    assert facts.list_optical_history("device-1", "GE1/0/1")[0]["rx_power"] == "-8.1"
    assert facts.list_all_optical_history()[0]["device_uuid"] == "device-1"
    assert facts.get_previous_optical_history("device-1", "GE1/0/1") is not None
    assert facts.list_lldp_history("device-1", "GE1/0/1")
    assert facts.list_object_history_page("optical", "device-1", "GE1/0/1")
    assert facts.count_object_history("optical", "device-1", "GE1/0/1") == 1


def test_fit_ap_refresh_uses_history_store_after_legacy_tables_are_retired(tmp_path) -> None:
    repository = _repository(tmp_path)
    _drop_legacy_history_tables(repository)
    first_round = [
        {
            "ap_name": "AP-1",
            "ap_mac": "0011-2233-4401",
            "serial_number": "SN-1",
            "rid1_status": "up",
            "rid1_channel": "149",
            "lldp_local_interface": "GigabitEthernet1/0/1",
            "lldp_neighbor_name": "SW-1",
            "lldp_neighbor_mac": "00:11:22:33:44:51",
            "lldp_neighbor_interface": "GigabitEthernet1/0/2",
            "collected_at": "2026-08-01T00:00:00",
        },
        {
            "ap_name": "AP-2",
            "ap_mac": "0011-2233-4402",
            "serial_number": "SN-2",
            "rid1_status": "up",
            "rid1_channel": "153",
            "lldp_local_interface": "GigabitEthernet1/0/3",
            "lldp_neighbor_name": "SW-2",
            "lldp_neighbor_mac": "00:11:22:33:44:52",
            "lldp_neighbor_interface": "GigabitEthernet1/0/4",
            "collected_at": "2026-08-01T00:00:00",
        },
    ]

    repository.replace_fit_ap_resources("ac-1", first_round)
    resources = {row["ap_name"]: row for row in repository.list_fit_ap_resources("ac-1")}
    second_round = [
        {**row, "collected_at": "2026-08-01T00:31:00"} for row in first_round
    ]
    repository.replace_fit_ap_resources("ac-1", second_round)
    ap_one = str(resources["AP-1"]["ap_uuid"])
    with repository.database.connect() as conn:
        repeated_state = conn.execute(
            "SELECT last_recorded_at, last_seen_at FROM history_state "
            "WHERE kind='fit_ap_lldp' AND entity_key=?",
            (ap_one,),
        ).fetchone()
    assert tuple(repeated_state) == (
        "2026-08-01T00:00:00",
        "2026-08-01T00:31:00",
    )
    third_round = [
        {
            **row,
            "lldp_neighbor_interface": "GigabitEthernet1/0/9"
            if row["ap_name"] == "AP-1"
            else row["lldp_neighbor_interface"],
            "collected_at": "2026-08-01T00:32:00",
        }
        for row in first_round
    ]
    repository.replace_fit_ap_resources("ac-1", third_round)
    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {
                "ap_uuid": resources["AP-1"]["ap_uuid"],
                "ap_name": "AP-1",
                "rx_power": "-8.1",
                "collected_at": "2026-08-01T00:32:00",
            },
            {
                "ap_uuid": resources["AP-2"]["ap_uuid"],
                "ap_name": "AP-2",
                "rx_power": "-8.2",
                "collected_at": "2026-08-01T00:32:00",
            },
        ],
    )

    history = repository.list_fit_ap_lldp_history_by_ap(ap_one, limit=10)
    by_time = {str(row["collected_at"]): row for row in history}
    assert by_time["2026-08-01T00:00:00"]["is_changed"] == 1
    assert "2026-08-01T00:31:00" not in by_time
    assert by_time["2026-08-01T00:32:00"]["is_changed"] == 1
    with repository.database.connect() as conn:
        changed_state = conn.execute(
            "SELECT last_recorded_at, last_seen_at FROM history_state "
            "WHERE kind='fit_ap_lldp' AND entity_key=?",
            (ap_one,),
        ).fetchone()
    assert tuple(changed_state) == (
        "2026-08-01T00:32:00",
        "2026-08-01T00:32:00",
    )
    assert repository.list_fit_ap_radio_history_by_ap(ap_one)
    assert repository.list_fit_ap_optical_history_by_ap(ap_one)
    assert repository.list_fit_ap_resource_history("ac-1")
