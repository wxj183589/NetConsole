from __future__ import annotations

import pytest

from netconsole.services.rail_transit.mr_end_role_service import (
    mr_position,
    physical_end_label,
    resolve_running_end_role,
    running_end_role_label,
    signal_model_label,
)


@pytest.mark.parametrize(
    ("position_code", "expected"),
    [
        ("CT", ("CT", "car_1_end", 1)),
        ("CW", ("CW", "car_6_end", 6)),
        ("TC", ("unknown", "unknown", None)),
    ],
)
def test_mr_position_keeps_ct_and_cw_as_fixed_physical_installation(position_code: str, expected: tuple[object, ...]) -> None:
    assert mr_position(position_code) == expected


@pytest.mark.parametrize(
    ("travel_direction", "physical_end", "expected"),
    [
        ("increasing", "car_1_end", "leading_end"),
        ("increasing", "car_6_end", "trailing_end"),
        ("decreasing", "car_1_end", "trailing_end"),
        ("decreasing", "car_6_end", "leading_end"),
    ],
)
def test_running_end_role_uses_direction_and_formation_reference(
    travel_direction: str,
    physical_end: str,
    expected: str,
) -> None:
    assert resolve_running_end_role(travel_direction, "car_1_end", physical_end) == expected


def test_running_end_role_does_not_infer_through_turnback_or_missing_formation_reference() -> None:
    assert resolve_running_end_role("turnback_transition", "car_1_end", "car_1_end") == "turnback_transition"
    assert resolve_running_end_role("increasing", "unknown", "car_1_end") == "unknown"


@pytest.mark.parametrize(
    ("travel_direction", "physical_end", "expected"),
    [
        ("increasing", "car_1_end", "trailing_end"),
        ("increasing", "car_6_end", "leading_end"),
        ("decreasing", "car_1_end", "leading_end"),
        ("decreasing", "car_6_end", "trailing_end"),
    ],
)
def test_running_end_role_supports_car_6_as_the_increasing_direction_leading_end(
    travel_direction: str,
    physical_end: str,
    expected: str,
) -> None:
    assert resolve_running_end_role(travel_direction, "car_6_end", physical_end) == expected


def test_end_role_labels_keep_physical_position_role_and_signal_model_separate() -> None:
    assert physical_end_label("car_1_end") == "1车厢端"
    assert physical_end_label("car_6_end") == "6车厢端"
    assert running_end_role_label("leading_end") == "行驶方向头端"
    assert running_end_role_label("trailing_end") == "行驶方向尾端"
    assert running_end_role_label("turnback_transition") == "暂不判定"
    assert signal_model_label("LEADING_END_FAST_DROP") == "行驶头端型快速衰减"
    assert signal_model_label("TRAILING_END_SMOOTH_CROSSOVER") == "行驶尾端型平滑交叉"
