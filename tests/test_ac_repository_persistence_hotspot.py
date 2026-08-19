from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository


def _rows(count: int) -> list[dict[str, object | None]]:
    return [
        {
            "ap_uuid": f"ap-{index}",
            "ap_name": f"AP-{index}",
            "ap_mac": f"0011-2233-{index // 256:02x}{index % 256:02x}",
            "ap_ip": f"10.1.{index // 254}.{index % 254 + 1}",
            "apid": str(index),
            # Keep one stable field absent so the history fallback cache is
            # exercised on the second refresh.
            "model": None,
            "serial_number": f"SN-{index}",
            "state": "R/M",
            "rid1_status": "Up",
            "rid1_channel": "149",
            "rid1_bbssid": f"0011-2233-{index // 256:02x}{index % 256:02x}",
            "lldp_local_interface": f"GE1/0/{index % 48 + 1}",
            "lldp_neighbor_name": "SW",
            "lldp_neighbor_interface": f"GE1/0/{index % 48 + 1}",
            "lldp_neighbor_mac": f"0022-3344-{index // 256:02x}{index % 256:02x}",
        }
        for index in range(count)
    ]


def test_fit_ap_resource_refresh_prefetches_history_for_1000_rows(tmp_path, monkeypatch):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = AcRepository(database)
    rows = _rows(1000)

    repository.replace_fit_ap_resources("ac-1", rows)
    with database.connect() as connection:
        first_outbox_count = connection.execute(
            "SELECT COUNT(*) FROM history_outbox"
        ).fetchone()[0]

    batched_history_calls: list[tuple[str, ...]] = []
    original_batch_query = repository.history_store.query_events_for_entities

    def batch_query(*, kind, entity_keys, event_types=None):
        keys = tuple(entity_keys)
        batched_history_calls.append(keys)
        return original_batch_query(
            kind=kind,
            entity_keys=keys,
            event_types=event_types,
        )

    def fail_per_ap_query(*args, **kwargs):
        raise AssertionError("per-AP history query must not run during batch refresh")

    monkeypatch.setattr(
        repository.history_store,
        "query_events_for_entities",
        batch_query,
    )
    monkeypatch.setattr(repository.history_store, "query_events", fail_per_ap_query)

    repository.replace_fit_ap_resources("ac-1", rows)

    assert len(batched_history_calls) == 1
    assert len(batched_history_calls[0]) == 1000
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM ac_fit_ap_resources WHERE ac_device_uuid = 'ac-1'"
        ).fetchone()[0] == 1000
        assert connection.execute(
            "SELECT COUNT(*) FROM ap_entities WHERE ac_device_uuid = 'ac-1'"
        ).fetchone()[0] == 1000
        # Replaying an unchanged 1000-row snapshot remains change-aware.
        assert connection.execute(
            "SELECT COUNT(*) FROM history_outbox"
        ).fetchone()[0] == first_outbox_count
