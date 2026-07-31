from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.maintenance.backfill_trackside_ap_station_identity import (
    _db_hash,
    build_report,
)


def _create_database(path: Path, *, duplicate_station_name: bool = False) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ap_extension_points (
            id INTEGER PRIMARY KEY,
            site_id TEXT,
            belong_type TEXT,
            station_name TEXT,
            ap_mac_norm TEXT,
            ap_mac_display TEXT,
            raw_payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ac_fit_ap_resources (
            ap_mac TEXT,
            state TEXT,
            site TEXT,
            lldp_neighbor_mac TEXT,
            lldp_source TEXT
        );
        CREATE TABLE ac_fit_ap_lldp_history (
            ap_mac TEXT,
            neighbor_mac TEXT,
            collected_at TEXT
        );
        CREATE TABLE ap_lldp_history (
            ap_mac TEXT,
            neighbor_switch_name TEXT,
            collected_at TEXT
        );
        """
    )
    stations = [
        (1, "demo", "__base_station__", "站A", "", "", json.dumps({"node_uid": "node-a"}), "t", "t"),
    ]
    if duplicate_station_name:
        stations.append(
            (2, "demo", "__base_station__", "站A", "", "", json.dumps({"node_uid": "node-a2"}), "t", "t")
        )
    conn.executemany(
        "INSERT INTO ap_extension_points VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        stations,
    )
    conn.executemany(
        "INSERT INTO ap_extension_points VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (10, "demo", None, "站A", "AA-BB-CC-DD-EE-01", "", "{}", "t", "t"),
            (11, "other", None, "站A", "aa:bb:cc:dd:ee:02", "", "{}", "t", "t"),
            (12, "demo", None, "站A", "aa:bb:cc:dd:ee:03", "", json.dumps({"station_id": "station:existing"}), "t", "t"),
            (13, "demo", None, "", "not-a-mac", "", "{}", "t", "t"),
        ],
    )
    conn.execute(
        "INSERT INTO ac_fit_ap_resources VALUES (?, ?, ?, ?, ?)",
        ("aa:bb:cc:dd:ee:01", "online", "demo", "aa:bb:cc:dd:ee:01", "current"),
    )
    conn.execute(
        "INSERT INTO ac_fit_ap_lldp_history VALUES (?, ?, ?)",
        ("aa:bb:cc:dd:ee:01", "", "t"),
    )
    conn.execute(
        "INSERT INTO ap_lldp_history VALUES (?, ?, ?)",
        ("aa:bb:cc:dd:ee:03", "站A", "t"),
    )
    conn.commit()
    conn.close()


def test_dry_run_is_read_only_and_filters_site(tmp_path: Path) -> None:
    database = tmp_path / "devices.db"
    _create_database(database)
    before = database.read_bytes()

    report = build_report(database, "demo", apply=False)

    assert report["mode"] == "dry-run"
    assert report["counts"]["total_trackside_ap"] == 3
    assert report["counts"]["valid_mac"] == 2
    assert report["counts"]["invalid_mac"] == 1
    assert report["counts"]["station_id_existing"] == 1
    assert report["counts"]["safe_backfill"] == 1
    assert report["counts"]["current_lldp_hits"] == 1
    assert report["counts"]["historical_lldp_hits"] == 1
    assert report["counts"]["online_before"] == 0
    assert report["counts"]["online_after"] == 1
    assert database.read_bytes() == before


def test_apply_is_idempotent_and_does_not_overwrite_existing_station_id(tmp_path: Path) -> None:
    database = tmp_path / "devices.db"
    _create_database(database)
    hash_conn = sqlite3.connect(database)
    first_hash = _db_hash(hash_conn)
    hash_conn.close()

    first = build_report(database, "demo", apply=True, expected_hash=first_hash)
    assert first["counts"]["safe_backfill_applied"] == 1
    assert first["counts"]["station_id_after"] == 2

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    metadata = json.loads(conn.execute("SELECT raw_payload_json FROM ap_extension_points WHERE id = 10").fetchone()[0])
    existing = json.loads(conn.execute("SELECT raw_payload_json FROM ap_extension_points WHERE id = 12").fetchone()[0])
    second_hash = _db_hash(conn)
    conn.close()
    assert metadata["station_id"] == "station:0702c1cc60ff"
    assert existing["station_id"] == "station:existing"

    second = build_report(database, "demo", apply=True, expected_hash=second_hash)
    assert second["counts"]["safe_backfill_applied"] == 0
    assert second["before_hash"] == second["after_hash"]


def test_duplicate_station_name_and_hash_mismatch_are_blocked(tmp_path: Path) -> None:
    database = tmp_path / "devices.db"
    _create_database(database, duplicate_station_name=True)

    report = build_report(database, "demo", apply=False)
    assert report["counts"].get("safe_backfill", 0) == 0
    assert report["counts"]["ambiguous"] == 1

    with pytest.raises(SystemExit, match="不匹配"):
        build_report(database, "demo", apply=True, expected_hash="wrong")
