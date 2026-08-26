from __future__ import annotations

import sqlite3

from netconsole.core.database import Database
from netconsole.services.device_state_retention import (
    upsert_device_lldp_current_and_history,
    upsert_device_optical_current_and_history,
)
from netconsole.services.interface_retention import upsert_interface_current_and_history
from netconsole.services.radio_retention import upsert_radio_current_and_history


def _database(tmp_path) -> Database:
    path = tmp_path / "sites" / "site-a" / "db" / "devices.db"
    path.parent.mkdir(parents=True)
    database = Database(path)
    database.initialize()
    return database


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_radio_same_state_does_not_grow_recent_and_changes_are_bounded(tmp_path) -> None:
    database = _database(tmp_path)
    row = {
        "ap_uuid": "ap-1",
        "ap_name": "AP-1",
        "ap_mac": "00:11:22:33:44:55",
        "status": "Up",
        "mode": "802.11ax",
        "band": "5GHz",
        "channel": "149",
        "bandwidth": "80",
        "usage": "0",
        "tx_power": "10",
        "clients": 3,
        "bbssid": "00:11:22:33:44:66",
    }
    conn = database.connect()
    try:
        upsert_radio_current_and_history(conn, row, site_id="site-a", radio_id=1, now="2026-08-26T10:00:00")
        for index in range(1000):
            upsert_radio_current_and_history(
                conn, {**row, "collected_at": f"2026-08-26T10:{index // 60:02d}:{index % 60:02d}"},
                site_id="site-a", radio_id=1,
            )
        assert _count(conn, "fit_ap_radio_current") == 1
        assert _count(conn, "fit_ap_radio_history") == 0
        for index in range(100):
            upsert_radio_current_and_history(
                conn, {**row, "channel": str(1 + index), "collected_at": f"2026-08-27T00:{index:02d}:00"},
                site_id="site-a", radio_id=1,
            )
        assert _count(conn, "fit_ap_radio_history") == 10
        duplicate_count = conn.execute(
            "SELECT COUNT(*) FROM (SELECT state_fingerprint, COUNT(*) AS total "
            "FROM fit_ap_radio_history GROUP BY state_fingerprint HAVING total > 1)"
        ).fetchone()[0]
        assert duplicate_count == 0
    finally:
        conn.close()


def test_interface_same_state_and_changes_are_bounded(tmp_path) -> None:
    database = _database(tmp_path)
    row = {"device_uuid": "sw-1", "interface_name": "GigabitEthernet1/0/1", "link_status": "UP", "speed": "1G", "duplex": "FULL", "pvid": "100"}
    conn = database.connect()
    try:
        upsert_interface_current_and_history(conn, row, site_id="site-a", now="2026-08-26T10:00:00")
        for index in range(1000):
            upsert_interface_current_and_history(conn, {**row, "updated_at": f"2026-08-26T10:{index // 60:02d}:{index % 60:02d}"}, site_id="site-a")
        assert _count(conn, "device_interfaces") == 1
        assert _count(conn, "device_interfaces_history") == 0
        for index in range(100):
            upsert_interface_current_and_history(conn, {**row, "pvid": str(index), "collected_at": f"2026-08-27T00:{index:02d}:00"}, site_id="site-a")
        assert _count(conn, "device_interfaces_history") == 10
    finally:
        conn.close()


def test_device_lldp_and_optical_same_state_do_not_create_recent(tmp_path) -> None:
    database = _database(tmp_path)
    lldp = {"device_uuid": "sw-1", "local_interface": "GigabitEthernet1/0/1", "chassis_id": "00:aa:bb:cc:dd:ee", "neighbor_interface": "GE1/0/2", "neighbor_sysname": "SW-2"}
    optical = {"device_uuid": "sw-1", "interface_name": "GigabitEthernet1/0/1", "rx_power": "-7.77", "tx_power": "-2.00", "status": "normal"}
    conn = database.connect()
    try:
        upsert_device_lldp_current_and_history(conn, lldp, site_id="site-a", now="2026-08-26T10:00:00")
        upsert_device_optical_current_and_history(conn, optical, site_id="site-a", now="2026-08-26T10:00:00")
        for index in range(1000):
            timestamp = f"2026-08-26T{index // 3600:02d}:{(index // 60) % 60:02d}:{index % 60:02d}"
            upsert_device_lldp_current_and_history(conn, {**lldp, "collected_at": timestamp}, site_id="site-a")
            upsert_device_optical_current_and_history(conn, {**optical, "collected_at": timestamp}, site_id="site-a")
        assert _count(conn, "device_lldp_neighbors_history") == 0
        assert _count(conn, "device_optical_modules_history") == 0
        for index in range(100):
            upsert_device_lldp_current_and_history(conn, {**lldp, "neighbor_sysname": f"SW-{index + 2}"}, site_id="site-a")
            upsert_device_optical_current_and_history(conn, {**optical, "rx_power": f"-{8 + index / 100:.2f}"}, site_id="site-a")
        assert _count(conn, "device_lldp_neighbors_history") <= 10
        assert _count(conn, "device_optical_modules_history") == 10
    finally:
        conn.close()
