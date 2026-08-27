from __future__ import annotations

import sqlite3

from netconsole.core.database import Database
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.demo_data import insert_demo_devices


def _max_recent(conn: sqlite3.Connection, table: str, group_by: str) -> int:
    return int(
        conn.execute(
            f"SELECT COALESCE(MAX(total), 0) FROM ("
            f"SELECT {group_by}, COUNT(*) AS total FROM {table} GROUP BY {group_by})"
        ).fetchone()[0]
    )


def test_demo_engineering_data_uses_bounded_recent10_without_duplicates(tmp_path) -> None:
    database = Database(tmp_path / "demo" / "db" / "devices.db")
    database.initialize()
    assert insert_demo_devices(DeviceRepository(database)) == 8

    with database.connect_readonly() as conn:
        assert _max_recent(
            conn,
            "device_interfaces_history",
            "site_id, device_uuid, interface_name",
        ) <= 10
        assert _max_recent(
            conn,
            "device_optical_modules_history",
            "site_id, device_uuid, interface_name",
        ) <= 10
        assert _max_recent(
            conn,
            "device_lldp_neighbors_history",
            "site_id, device_uuid, local_interface, chassis_id, neighbor_interface",
        ) <= 10
        for table, key in (
            (
                "device_interfaces_history",
                "site_id, device_uuid, interface_name, state_fingerprint",
            ),
            (
                "device_optical_modules_history",
                "site_id, device_uuid, interface_name, state_fingerprint",
            ),
            (
                "device_lldp_neighbors_history",
                "site_id, device_uuid, local_interface, chassis_id, neighbor_interface, state_fingerprint",
            ),
        ):
            duplicate_groups = conn.execute(
                f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            assert duplicate_groups == 0

        assert conn.execute("SELECT COUNT(*) FROM device_interfaces_history").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM device_optical_modules_history").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM device_lldp_neighbors_history").fetchone()[0] > 0
