from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from netconsole.models.device import Device
from netconsole.repositories.trackside_optical_result_repository import TracksideOpticalResultRepository
from netconsole.services.rail_transit import trackside_optical_collection
from netconsole.services.rail_transit.trackside_optical_collection import (
    TracksideDeviceCollectionResult,
    TracksideOpticalTarget,
)


def test_repository_creates_unchanged_optical_results_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "trackside_update_results.sqlite"

    TracksideOpticalResultRepository(db_path).append_rows([])

    with sqlite3.connect(db_path) as conn:
        columns = conn.execute("PRAGMA table_info(optical_results)").fetchall()
    assert [(row[1], row[2], row[5]) for row in columns] == [
        ("id", "INTEGER", 1),
        ("device_name", "TEXT", 0),
        ("device_ip", "TEXT", 0),
        ("device_type", "TEXT", 0),
        ("group_name", "TEXT", 0),
        ("interface_name", "TEXT", 0),
        ("module_type", "TEXT", 0),
        ("rx_power", "TEXT", 0),
        ("tx_power", "TEXT", 0),
        ("rx_status", "TEXT", 0),
        ("tx_status", "TEXT", 0),
        ("collected_at", "TEXT", 0),
        ("raw_log_path", "TEXT", 0),
        ("error_message", "TEXT", 0),
    ]


def test_repository_preserves_success_row_mapping_and_insert_order(tmp_path: Path) -> None:
    db_path = tmp_path / "trackside_update_results.sqlite"
    repository = TracksideOpticalResultRepository(db_path)

    repository.append_rows(
        [
            {
                "device_name": "SW-A",
                "device_ip": "10.0.0.1",
                "device_type": "SWITCH",
                "group_name": "车站",
                "interface_name": "GigabitEthernet1/0/1",
                "module_model": "SFP-GE-LX-SM1310",
                "rx_power": "-6.10",
                "tx_power": "-2.20",
                "optical_alarm_status": "normal",
                "tx_status": "unknown",
                "collected_at": "2026-07-19T10:00:00",
                "raw_log_path": "",
                "error_message": None,
            },
            {
                "device_name": "SW-B",
                "device_ip": "10.0.0.2",
                "device_type": "SWITCH",
                "group_name": "车辆段",
                "interface_name": "GigabitEthernet1/0/2",
                "module_model": "SFP-GE-SX-MM850",
                "rx_power": "-7.20",
                "tx_power": "-3.30",
                "optical_alarm_status": "warning",
                "tx_status": "unknown",
                "collected_at": "2026-07-19T10:00:01",
                "raw_log_path": "relative/raw.log",
                "error_message": None,
            },
        ]
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT device_name, interface_name, module_type, rx_power, tx_power,
                   rx_status, tx_status, collected_at, raw_log_path, error_message
            FROM optical_results
            ORDER BY id
            """
        ).fetchall()
    assert rows == [
        (
            "SW-A",
            "GigabitEthernet1/0/1",
            "SFP-GE-LX-SM1310",
            "-6.10",
            "-2.20",
            "normal",
            "unknown",
            "2026-07-19T10:00:00",
            "",
            None,
        ),
        (
            "SW-B",
            "GigabitEthernet1/0/2",
            "SFP-GE-SX-MM850",
            "-7.20",
            "-3.30",
            "warning",
            "unknown",
            "2026-07-19T10:00:01",
            "relative/raw.log",
            None,
        ),
    ]


def test_collection_writes_failure_result_as_one_row(tmp_path: Path) -> None:
    target = TracksideOpticalTarget(
        key="device:1",
        name="SW-FAIL",
        host="10.0.0.99",
        port=22,
        protocol="SSH",
        target_type="SWITCH",
        group_name="车站",
        device=Device(name="SW-FAIL", ip_address="10.0.0.99"),
    )
    result = TracksideDeviceCollectionResult(
        target=target,
        success=False,
        raw_log_path="relative/failure.log",
        error_message="connection failed",
    )
    db_path = tmp_path / "trackside_update_results.sqlite"

    trackside_optical_collection._write_sqlite_rows(db_path, result)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT * FROM optical_results").fetchone()
    assert row[1:5] == ("SW-FAIL", "10.0.0.99", "SWITCH", "车站")
    assert row[5:11] == (None, None, None, None, None, None)
    assert row[11]
    assert row[12:] == ("relative/failure.log", "connection failed")


def test_collection_preserves_explicit_no_module_status() -> None:
    target = TracksideOpticalTarget(
        key="device:1",
        name="SW-NO-MODULE",
        host="10.0.0.98",
        port=22,
        protocol="SSH",
        target_type="SWITCH",
        group_name="车站",
        device=Device(name="SW-NO-MODULE", ip_address="10.0.0.98"),
    )

    row = trackside_optical_collection._result_row(
        target,
        {
            "interface_name": "GigabitEthernet2/0/3",
            "status": "no_module",
        },
    )

    assert row["status"] == "success"
    assert row["optical_alarm_status"] == "no_module"


def test_collection_has_no_direct_sqlite_calls() -> None:
    source_path = Path(trackside_optical_collection.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, ast.Import) and any(alias.name == "sqlite3" for alias in node.names)
        or isinstance(node, ast.ImportFrom) and node.module == "sqlite3"
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"connect", "execute"}
        for node in ast.walk(tree)
    )
