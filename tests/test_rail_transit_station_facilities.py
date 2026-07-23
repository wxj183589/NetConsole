from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.application.rail_transit.base_data_application_service import (
    BaseDataFieldValidationError,
    RailTransitBaseDataApplicationService,
)
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataRepository,
)
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.station_source_utils import (
    normalize_track_facilities,
)
from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture


def test_main_station_defaults_to_underground_island_without_overwriting_explicit_values() -> None:
    defaulted = RailTransitBaseDataApplicationService._station_values(
        {"name": "新站", "node_type": "station", "path_code": "MAIN"},
        "create",
    )
    explicit = RailTransitBaseDataApplicationService._station_values(
        {
            "name": "高架站",
            "node_type": "station",
            "path_code": "MAIN",
            "structure_type": "elevated",
            "platform_layout": "side",
        },
        "create",
    )
    special = RailTransitBaseDataApplicationService._station_values(
        {"name": "停车场", "node_type": "parking_lot", "path_code": "UNASSIGNED"},
        "create",
    )

    assert (defaulted["structure_type"], defaulted["platform_layout"]) == ("underground", "island")
    assert (explicit["structure_type"], explicit["platform_layout"]) == ("elevated", "side")
    assert (special["structure_type"], special["platform_layout"]) == ("unknown", "unknown")


def test_custom_main_path_station_uses_the_same_structure_defaults() -> None:
    values = RailTransitBaseDataApplicationService._station_values(
        {"name": "支线主站", "node_type": "station", "path_code": "LINE-A"},
        "create",
        main_path_code="LINE-A",
    )

    assert (values["structure_type"], values["platform_layout"]) == (
        "underground",
        "island",
    )


def test_legacy_turnback_type_maps_to_multiple_facilities_and_depot_connection_does_not_enable_turnback() -> None:
    assert normalize_track_facilities(None, legacy_turnback_type="pocket_track") == [
        "turnback_track",
        "storage_track",
    ]
    values = RailTransitBaseDataApplicationService._station_values(
        {
            "name": "车辆段接轨站",
            "track_facilities": ["depot_connection"],
            "turnback_capable": False,
        },
        "create",
    )
    assert values["track_facilities"] == ["depot_connection"]
    assert values["turnback_capable"] is False


def test_center_mileage_parses_without_prefix_and_invalid_value_is_not_zero() -> None:
    values = RailTransitBaseDataApplicationService._station_values(
        {"name": "里程站", "center_mileage_text": "12+345.5"},
        "create",
    )
    assert values["center_mileage_text"] == "12+345.5"
    assert values["center_mileage_m"] == 12345.5

    with pytest.raises(BaseDataFieldValidationError) as exc_info:
        RailTransitBaseDataApplicationService._station_values(
            {"name": "错误站", "center_mileage_text": "NOT-MILEAGE"},
            "create",
        )
    assert exc_info.value.code == "station_center_mileage_invalid"


def test_multiple_facilities_and_center_mileage_round_trip_through_base_metadata(
    tmp_path: Path,
) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    repository = RailTransitBaseDataRepository(paths)
    values = RailTransitBaseDataApplicationService._station_values(
        {
            "name": "高桥西",
            "code": "11",
            "sort_order": 11,
            "node_type": "station",
            "path_code": "MAIN",
            "center_mileage_text": "K12+345",
            "turnback_capable": True,
            "track_facilities": [
                "turnback_track",
                "storage_track",
                "depot_connection",
                "storage_track",
            ],
            "turnback_direction": "both",
            "is_line_terminal": True,
            "terminal_extension_enabled": True,
            "terminal_endpoint_label": "端点",
            "terminal_extension_distance_m": 180.5,
            "terminal_endpoint_mileage_text": "K12+165",
        },
        "create",
    )
    repository.apply_base_data_changes(
        "demo",
        repository.base_data_revision("demo"),
        [{
            "entity_type": "station",
            "action": "create",
            "entity_id": "new:station",
            "values": values,
        }],
    )

    stations = RailTransitBaseDataQueryService(paths).list_stations(
        "demo",
        page=1,
        page_size=200,
    ).items
    saved = next(station for station in stations if station.name == "高桥西")
    assert saved.track_facilities == [
        "turnback_track",
        "storage_track",
        "depot_connection",
    ]
    assert saved.turnback_type == "other"
    assert saved.center_mileage_text == "K12+345"
    assert saved.center_mileage_m == 12345
    assert saved.terminal_extension_distance_m == 180.5
