from __future__ import annotations

from types import SimpleNamespace
import json
from pathlib import Path

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataRepository,
)
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.station_ordering import (
    canonicalize_trackside_ap_plan_rows,
    sort_rail_stations,
)


def _station(
    station_id: str,
    name: str,
    *,
    sort_order: int | None = None,
    node_type: str = "station",
    participates_in_direction: bool | None = None,
) -> dict[str, object]:
    return {
        "id": station_id,
        "name": name,
        "sort_order": sort_order,
        "node_type": node_type,
        "participates_in_direction": (
            node_type == "station"
            if participates_in_direction is None
            else participates_in_direction
        ),
    }


def test_station_order_is_numeric_and_not_input_or_identifier_order() -> None:
    rows = [
        _station("station:920", "站点920", sort_order=920),
        _station("station:901", "站点901", sort_order=901),
        _station("station:910", "站点910", sort_order=910),
    ]

    assert [row["id"] for row in sort_rail_stations(rows)] == [
        "station:901",
        "station:910",
        "station:920",
    ]

    object_rows = [
        SimpleNamespace(
            id=row["id"],
            name=row["name"],
            sort_order=row["sort_order"],
            node_type=row["node_type"],
            participates_in_direction=row["participates_in_direction"],
        )
        for row in rows
    ]
    assert [row.id for row in sort_rail_stations(object_rows)] == [
        "station:901",
        "station:910",
        "station:920",
    ]


def test_plan_order_follows_station_order_and_appends_non_mainline_nodes() -> None:
    stations = [
        _station("station:920", "站点920", sort_order=920),
        _station("station:901", "站点901", sort_order=901),
        _station("station:930", "站点930", sort_order=930),
        _station("station:27", "27车辆段", node_type="depot"),
        _station("station:9", "9停车场", node_type="parking_lot"),
    ]
    rows = [
        {"station_id": "station:27", "station_name": "27车辆段", "sequence_no": 1},
        {"station_id": "station:920", "station_name": "站点920", "sequence_no": 2},
        {"station_id": "station:9", "station_name": "9停车场", "sequence_no": 3},
        {"station_id": "station:901", "station_name": "站点901", "sequence_no": 4},
        {"station_id": "station:930", "station_name": "站点930", "sequence_no": 5},
    ]

    result = canonicalize_trackside_ap_plan_rows(rows, stations)

    assert [row["station_id"] for row in result] == [
        "station:901",
        "station:920",
        "station:930",
        "station:27",
        "station:9",
    ]
    assert [row["sequence_no"] for row in result] == [901, 920, 930, 931, 932]
    assert [row["planning_order"] for row in result] == [None, None, None, None, None]


def test_explicit_non_mainline_planning_order_is_preserved() -> None:
    stations = [
        _station("station:1", "一号站", sort_order=930),
        _station("station:27", "27车辆段", node_type="depot"),
        _station("station:9", "9停车场", node_type="parking_lot"),
    ]
    rows = [
        {
            "station_id": "station:27",
            "station_name": "27车辆段",
            "sequence_no": 2,
        },
        {
            "station_id": "station:9",
            "station_name": "9停车场",
            "sequence_no": 940,
            "planning_order": 940,
        },
        {"station_id": "station:1", "station_name": "一号站", "sequence_no": 1},
    ]

    result = canonicalize_trackside_ap_plan_rows(rows, stations)

    assert [row["station_id"] for row in result] == [
        "station:1",
        "station:9",
        "station:27",
    ]
    assert [row["sequence_no"] for row in result] == [930, 940, 941]
    assert result[1]["planning_order"] == 940


def test_station_and_edit_snapshot_share_the_same_canonical_order(tmp_path: Path) -> None:
    from tests.support.rail_transit_base_data_fixture import (
        build_rail_transit_base_data_fixture,
    )

    paths, db_path = build_rail_transit_base_data_fixture(tmp_path)
    database = Database(db_path)
    now = "2026-09-01T00:00:00"
    metadata = [
        ("station:a", "车站A", 920),
        ("station:b", "车站B", 901),
        ("station:c", "车站C", 910),
    ]
    with database.connect() as connection:
        connection.executemany(
            """
            INSERT INTO ap_extension_points (
                site_id, belong_type, station_id, station_name,
                raw_payload_json, source_file, created_at, updated_at
            ) VALUES ('demo', '__base_station__', ?, ?, ?, 'test', ?, ?)
            """,
            [
                (
                    station_id,
                    name,
                    json.dumps(
                        {
                            "node_uid": station_id,
                            "node_type": "station",
                            "participates_in_direction": True,
                            "sort_order": sort_order,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                    now,
                )
                for station_id, name, sort_order in metadata
            ],
        )
        connection.commit()
    AcRepository(database).replace_trackside_ap_plan_rows(
        "unified",
        [
            {
                "station_id": station_id,
                "station_name": name,
                "sequence_no": index,
                "planning_order": None,
                "ap_count": 0,
                "management_vlan": None,
                "remark": "",
            }
            for index, (station_id, name, _sort_order) in enumerate(metadata, start=1)
        ],
    )

    service = RailTransitBaseDataQueryService(paths)
    station_ids = [row.id for row in service.list_stations("demo").items]
    snapshot_ids = [row.station_id for row in service.get_edit_snapshot("demo")["trackside_ap_plans"]]

    assert station_ids[:3] == ["station:b", "station:c", "station:a"]
    assert snapshot_ids == ["station:b", "station:c", "station:a"]

    base_repository = RailTransitBaseDataRepository(paths)
    expected_revision = base_repository.base_data_revision("demo")
    result = base_repository.apply_base_data_changes(
        "demo",
        expected_revision,
        [
            {
                "entity_type": "trackside_ap_plan",
                "action": "replace",
                "values": {
                    "rows": [
                        {
                            "station_id": station_id,
                            "station_name": name,
                            "sequence_no": index,
                            "planning_order": None,
                            "ap_count": 0,
                            "management_vlan": None,
                            "remark": "",
                        }
                        for index, (station_id, name, _sort_order) in enumerate(
                            reversed(metadata),
                            start=1,
                        )
                    ]
                },
            }
        ],
    )

    assert result["planning_row_count"] == 3
    with Database(db_path).connect_readonly() as connection:
        persisted = connection.execute(
            """
            SELECT station_id, sequence_no, planning_order
            FROM ac_trackside_ap_plan
            WHERE mode = 'unified'
            ORDER BY sequence_no
            """
        ).fetchall()
    assert [row["station_id"] for row in persisted] == [
        "station:b",
        "station:c",
        "station:a",
    ]
    assert [row["sequence_no"] for row in persisted] == [901, 910, 920]
    assert [row["planning_order"] for row in persisted] == [None, None, None]
