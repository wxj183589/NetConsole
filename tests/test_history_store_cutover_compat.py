from __future__ import annotations

import inspect

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.history_store import HistoryStore


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
        HistoryStore(
            repository.database.path,
            history_root=repository.database.path.parent / "legacy-history",
        ).record_event(
            conn,
            kind=kind,
            entity_key=entity_key,
            payload=payload,
            collected_at=collected_at,
            meaningful_fields=tuple(sorted(payload)),
        )
        conn.commit()


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
        conn.execute(
            "UPDATE optical_retention_meta SET value='legacy' WHERE key='authority'"
        )
        conn.commit()


def test_engineering_runtime_has_no_legacy_historystore_dependency() -> None:
    device_methods = (
        "replace_device_interfaces",
        "append_interface_history",
        "replace_optical_modules",
        "append_optical_history",
        "replace_lldp_neighbors",
        "append_lldp_history",
        "list_interface_history",
        "list_optical_history",
        "list_all_optical_history",
        "get_previous_optical_history",
        "list_lldp_history",
        "list_object_history_page",
        "count_object_history",
        "list_object_history_counts",
    )
    ac_methods = (
        "list_fit_ap_optical",
        "list_all_fit_ap_optical",
        "list_fit_ap_optical_history",
        "list_fit_ap_optical_history_by_ap",
        "list_fit_ap_radio_history_by_ap",
        "list_fit_ap_lldp_history_by_ap",
        "list_fit_ap_history_page",
        "count_fit_ap_history",
        "list_all_ap_optical_history",
        "get_previous_ap_optical_history",
        "get_previous_ap_lldp_history",
        "list_latest_ap_lldp_history",
        "list_latest_ap_lldp_histories",
        "list_all_ap_lldp_history",
        "_append_radio_history",
        "_record_fit_ap_optical_history",
        "_append_resource_lldp_history",
    )

    for owner, methods in (
        (DeviceFactRepository, device_methods),
        (AcRepository, ac_methods),
    ):
        for method_name in methods:
            source = inspect.getsource(getattr(owner, method_name))
            assert "history_store" not in source, f"{owner.__name__}.{method_name}"
            assert "_query_legacy_history_rows" not in source, f"{owner.__name__}.{method_name}"


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


def test_engineering_history_readers_ignore_legacy_lldp_rows(tmp_path) -> None:
    repository = _repository(tmp_path)
    ap_uuid = "ap-legacy"
    _insert_legacy_lldp(repository, ap_uuid)

    assert repository.list_fit_ap_lldp_history_by_ap(ap_uuid) == []
    assert repository.list_fit_ap_history_page("lldp", ap_uuid) == []
    assert repository.count_fit_ap_history("lldp", ap_uuid) == 0
    assert repository.list_latest_ap_lldp_history(ap_uuid) is None
    assert repository.list_latest_ap_lldp_histories() == []
    assert repository.list_all_ap_lldp_history() == []
    assert repository.get_previous_ap_lldp_history({"ap_uuid": ap_uuid}) is None


def test_engineering_history_readers_ignore_history_store_events(tmp_path) -> None:
    repository = _repository(tmp_path)
    ap_uuid = "ap-cutover"
    _insert_legacy_lldp(repository, ap_uuid)
    _record_event(
        repository,
        kind="fit_ap_lldp",
        entity_key=ap_uuid,
        payload=_lldp_payload(ap_uuid),
    )

    assert repository.list_fit_ap_lldp_history_by_ap(ap_uuid) == []
    assert repository.list_fit_ap_history_page("lldp", ap_uuid) == []
    assert repository.count_fit_ap_history("lldp", ap_uuid) == 0
    assert repository.list_latest_ap_lldp_history(ap_uuid) is None
    assert repository.list_latest_ap_lldp_histories() == []
    assert repository.list_all_ap_lldp_history() == []
    assert repository.get_previous_ap_lldp_history({"ap_uuid": ap_uuid}) is None


def test_dropped_legacy_tables_do_not_restore_engineering_history_from_events(tmp_path) -> None:
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

    assert repository.list_fit_ap_resource_history("ac-1") == []
    assert repository.list_fit_ap_radio_history_by_ap(ap_uuid) == []
    assert repository.list_fit_ap_optical_history_by_ap(ap_uuid) == []
    assert repository.list_all_ap_optical_history() == []
    assert repository.list_fit_ap_lldp_history_by_ap(ap_uuid) == []
    assert repository.list_fit_ap_history_page("lldp", ap_uuid) == []
    assert repository.count_fit_ap_history("lldp", ap_uuid) == 0
    assert repository.list_latest_ap_lldp_history(ap_uuid) is None
    assert repository.list_latest_ap_lldp_histories() == []
    assert repository.list_all_ap_lldp_history() == []
    assert repository.get_previous_ap_lldp_history({"ap_uuid": ap_uuid}) is None
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


def test_device_fact_history_keeps_fact_compatibility_without_engineering_fallback(tmp_path) -> None:
    repository = _repository(tmp_path)
    facts = DeviceFactRepository(repository.database)
    with repository.database.connect() as conn:
        conn.execute("DROP TABLE device_facts_history")
        conn.commit()
    _record_event(
        repository,
        kind="device_fact",
        entity_key="device-1",
        payload={"device_uuid": "device-1", "model": "S6520"},
    )
    assert facts.list_fact_history("device-1") == []
    assert facts.list_interface_history("device-1", "GE1/0/1") == []
    assert facts.list_optical_history("device-1", "GE1/0/1") == []
    assert facts.list_all_optical_history() == []
    assert facts.get_previous_optical_history("device-1", "GE1/0/1") is None
    assert facts.list_lldp_history("device-1", "GE1/0/1") == []
    assert facts.list_object_history_page("optical", "device-1", "GE1/0/1") == []
    assert facts.count_object_history("optical", "device-1", "GE1/0/1") == 0


def test_fit_ap_refresh_uses_bounded_history_after_legacy_tables_are_retired(tmp_path) -> None:
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

    ap_one = str(resources["AP-1"]["ap_uuid"])
    history = repository.list_fit_ap_lldp_history_by_ap(ap_one, limit=10)
    by_time = {str(row["changed_at"]): row for row in history}
    assert sorted(by_time) == ["2026-08-01T00:32:00"]
    assert by_time["2026-08-01T00:32:00"]["change_kind"] == "change"
    current = repository.list_current_ap_lldp_states([ap_one])
    assert len(current) == 1
    assert current[0]["collected_at"] == "2026-08-01T00:32:00"
    assert current[0]["neighbor_interface"] == "GigabitEthernet1/0/9"
    assert repository.list_fit_ap_radio_history_by_ap(ap_one) == []
    assert repository.list_fit_ap_optical_history_by_ap(ap_one) == []
    assert repository.list_fit_ap_resource_history("ac-1")
