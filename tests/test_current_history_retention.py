from __future__ import annotations

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository


def _database(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def _table_exists(database: Database, table: str) -> bool:
    with database.connect_readonly() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            is not None
        )


def test_four_retired_history_kinds_use_current_and_recent10(tmp_path) -> None:
    database = _database(tmp_path)
    facts = DeviceFactRepository(database)
    ac = AcRepository(database)

    facts.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "SW-1",
            "model": "S6520",
            "uptime": 10,
            "collected_at": "2026-08-29T00:00:00Z",
        }
    )
    facts.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "SW-1",
            "model": "S6520",
            "uptime": 20,
            "collected_at": "2026-08-29T00:01:00Z",
        }
    )
    facts.upsert_device_fact(
        {
            "device_uuid": "device-1",
            "sysname": "SW-2",
            "model": "S6520",
            "collected_at": "2026-08-29T00:02:00Z",
        }
    )

    resource = {
        "ap_uuid": "ap-1",
        "ap_name": "AP-1",
        "ap_mac": "0011-2233-4401",
        "serial_number": "SN-1",
        "state": "R/M",
        "collected_at": "2026-08-29T00:00:00Z",
    }
    ac.replace_fit_ap_resources("ac-1", [resource])
    ac.replace_fit_ap_resources("ac-1", [{**resource, "state": "I", "collected_at": "2026-08-29T00:01:00Z"}])

    unauth = {
        "inferred_ap_mac": "0011-2233-4499",
        "ap_name": "UNKNOWN-1",
        "state": "new",
    }
    summary = {"total": 1, "collected_at": "2026-08-29T00:00:00Z"}
    ac.replace_fit_ap_unauthenticated("ac-1", summary, [unauth])
    ac.replace_fit_ap_unauthenticated(
        "ac-1", {**summary, "collected_at": "2026-08-29T00:01:00Z"}, [{**unauth, "state": "seen"}]
    )

    station = {"site": "站点A", "total": 10, "online": 9, "offline": 1, "online_rate": "90%"}
    ac.save_station_online_summary_history([station], collected_at="2026-08-29T00:00:00Z")
    ac.save_station_online_summary_history([station], collected_at="2026-08-29T00:01:00Z")
    ac.save_station_online_summary_history(
        [{**station, "online": 8, "offline": 2}], collected_at="2026-08-29T00:02:00Z"
    )

    assert facts.get_device_fact("device-1")["sysname"] == "SW-2"
    assert [row["sysname"] for row in facts.list_fact_history("device-1")] == ["SW-2", "SW-1"]
    assert len(ac.list_fit_ap_resource_history("ac-1")) == 2
    assert len(ac.list_fit_ap_unauthenticated_history("ac-1")) == 2
    assert ac.count_station_online_summary_history("站点A") == 2

    with database.connect_readonly() as conn:
        assert conn.execute("SELECT COUNT(*) FROM device_fact_recent WHERE device_uuid='device-1'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fit_ap_resource_recent WHERE ac_device_uuid='ac-1' AND ap_uuid='ap-1'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM fit_ap_unauthenticated_recent WHERE ac_device_uuid='ac-1'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM station_online_summary_recent WHERE site_name='站点A'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM station_online_summary_current WHERE site_name='站点A'").fetchone()[0] == 1
    assert not _table_exists(database, "history_outbox")
    assert not (tmp_path / "history").exists()


def test_recent10_is_bounded_per_resource(tmp_path) -> None:
    database = _database(tmp_path)
    facts = DeviceFactRepository(database)
    for index in range(12):
        facts.upsert_device_fact(
            {
                "device_uuid": "device-1",
                "sysname": f"SW-{index}",
                "collected_at": f"2026-08-29T00:{index:02d}:00Z",
            }
        )
    with database.connect_readonly() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM device_fact_recent WHERE device_uuid='device-1'"
        ).fetchone()[0]
    assert count == 10
    assert facts.get_device_fact("device-1")["sysname"] == "SW-11"


def test_new_site_initialization_and_current_writes_never_create_history_directory(tmp_path) -> None:
    paths = PathResolver(tmp_path / "data")
    site_root = paths.ensure_site_dirs("new-site")
    database = Database(site_root / "db" / "devices.db")
    database.initialize()
    DeviceFactRepository(database).upsert_device_fact(
        {"device_uuid": "new-device", "sysname": "NEW", "collected_at": "2026-08-29T00:00:00Z"}
    )
    assert not (site_root / "db" / "history").exists()


def test_legacy_history_tables_and_external_events_are_not_runtime_inputs(tmp_path) -> None:
    database = _database(tmp_path)
    facts = DeviceFactRepository(database)
    ac = AcRepository(database)
    with database.connect() as conn:
        conn.execute(
            "INSERT INTO device_facts_history (device_uuid, sysname, collected_at, created_at) VALUES (?, ?, ?, ?)",
            ("legacy-device", "LEGACY", "2026-08-29T00:00:00Z", "2026-08-29T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO ac_fit_ap_resource_history (ac_device_uuid, ap_uuid, ap_name, collected_at, created_at) VALUES (?, ?, ?, ?, ?)",
            ("ac-1", "legacy-ap", "LEGACY", "2026-08-29T00:00:00Z", "2026-08-29T00:00:00Z"),
        )
        conn.commit()
    assert facts.list_fact_history("legacy-device") == []
    assert ac.list_fit_ap_resource_history("ac-1") == []
    assert not (tmp_path / "history").exists()
