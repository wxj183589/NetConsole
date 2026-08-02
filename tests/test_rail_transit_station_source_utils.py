from __future__ import annotations

import pytest

from netconsole.services.rail_transit.station_source_utils import (
    format_station_display_name,
    parse_station_source_value,
    station_identity_key,
)


@pytest.mark.parametrize(
    "value",
    [
        "01小洋江站",
        "01.小洋江站",
        "01-小洋江站",
        "01_小洋江站",
        "01 小洋江站",
        "01、小洋江站",
        "01、 小洋江站",
        "01:小洋江站",
        "01：小洋江站",
        "1.小洋江站",
        "  01、小洋江站  ",
    ],
)
def test_numeric_station_prefix_is_auxiliary_order(value: str) -> None:
    parsed = parse_station_source_value(value)

    assert parsed.source_station_value == value
    assert parsed.source_order == 1
    assert parsed.sort_order == 1
    assert parsed.name == "小洋江站"
    assert parsed.canonical_station_name == "小洋江站"
    assert parsed.source_station_key == station_identity_key(
        "小洋江站", "station", "MAIN"
    )
    assert parsed.parse_warning == ""
    assert parsed.parse_error == ""


def test_station_without_numeric_prefix_remains_valid() -> None:
    parsed = parse_station_source_value("小洋江站")

    assert parsed.source_order_text == ""
    assert parsed.source_order is None
    assert parsed.sort_order is None
    assert parsed.name == "小洋江站"
    assert parsed.parse_warning == ""
    assert parsed.parse_error == ""


@pytest.mark.parametrize(
    ("value", "source", "expected"),
    [
        ("小洋江站", "01小洋江站", "01-小洋江站"),
        ("小洋江站", "01-小洋江站", "01-小洋江站"),
        ("01小洋江站", "", "01-小洋江站"),
        ("10大目湾站", "", "10-大目湾站"),
    ],
)
def test_station_display_name_preserves_numeric_source_prefix(
    value: str,
    source: str,
    expected: str,
) -> None:
    assert format_station_display_name(value, source_station_value=source) == expected


def test_device_station_source_can_restore_prefix_from_order_metadata() -> None:
    assert (
        format_station_display_name(
            "小洋江站",
            sort_order=1,
            source_kind="device_station_field",
        )
        == "01-小洋江站"
    )


@pytest.mark.parametrize(
    ("value", "node_type"),
    [
        ("11云龙车辆段", "depot"),
        ("12某某停车场", "parking_lot"),
    ],
)
def test_special_node_keeps_source_order_but_does_not_take_main_order(
    value: str,
    node_type: str,
) -> None:
    parsed = parse_station_source_value(value)

    assert parsed.source_order == int(value[:2])
    assert parsed.sort_order is None
    assert parsed.node_type == node_type
    assert parsed.path_code == "UNASSIGNED"
    assert parsed.participates_in_direction is False


@pytest.mark.parametrize("value", ["1", "01", "123", "1234站"])
def test_invalid_numeric_station_value_is_blocking_parse_error(value: str) -> None:
    parsed = parse_station_source_value(value)

    assert parsed.parse_error
