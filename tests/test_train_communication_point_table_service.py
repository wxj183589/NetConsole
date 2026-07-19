from __future__ import annotations

import json
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.rail_transit.train_communication_point_table_service import (
    MISSING_POINT_TABLE_REVISION,
    POINT_TABLE_CONFIGURED,
    POINT_TABLE_INVALID,
    POINT_TABLE_MISSING,
    TrainCommunicationPointTableService,
)


def _row(node_name: str, *, address: str = "10.0.0.1", device_id: str = "") -> dict[str, str]:
    return {
        "train_id": "01",
        "train_no": "01",
        "display_name": "01车",
        "node_name": node_name,
        "node_type": "SERVER" if node_name.endswith("SRV") else "SW" if node_name.endswith("SW") else "MR",
        "device_id": device_id,
        "primary_address": address,
    }


def _write_table(paths: PathResolver, rows: list[dict[str, str]]) -> None:
    directory = paths.car_network_diagnostic_parsed_dir("demo")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "point_table.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_inspection_requires_all_six_nodes_but_allows_ip_only_server(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    rows = [_row(name, address=f"10.0.0.{index}", device_id=str(index)) for index, name in enumerate(
        ("TC1-MR", "TC1-SW", "TC1-SRV", "TC2-MR", "TC2-SW", "TC2-SRV"), 1
    )]
    rows[2]["device_id"] = ""
    _write_table(paths, rows)

    inspection = TrainCommunicationPointTableService(paths).inspect("demo", "01")

    assert inspection.status == POINT_TABLE_CONFIGURED
    assert inspection.missing_nodes == ()


def test_inspection_reports_missing_duplicate_and_unconfigured_nodes(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    _write_table(paths, [_row("TC1-MR", address="10.0.0.1", device_id="1"), _row("TC1-MR", address="10.0.0.2", device_id="2")])

    inspection = TrainCommunicationPointTableService(paths).inspect("demo", "01")

    assert inspection.status == POINT_TABLE_INVALID
    assert inspection.duplicate_nodes == ("TC1-MR",)
    assert "TC1-SW" in inspection.missing_nodes
    assert "TC1-MR" not in inspection.unconfigured_nodes


def test_inspection_distinguishes_missing_file_and_other_train(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    service = TrainCommunicationPointTableService(paths)

    missing = service.inspect("demo", "01")
    assert missing.status == POINT_TABLE_MISSING
    assert missing.revision == MISSING_POINT_TABLE_REVISION
    _write_table(paths, [_row("TC1-MR")])
    assert service.inspect("demo", "02").status == POINT_TABLE_MISSING
