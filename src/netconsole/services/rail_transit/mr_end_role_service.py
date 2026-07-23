from __future__ import annotations

from typing import Literal


MrPositionCode = Literal["CT", "CW", "unknown"]
MrPhysicalEnd = Literal["car_1_end", "car_6_end", "unknown"]
TravelDirection = Literal["increasing", "decreasing", "stopped", "turnback_transition", "unknown"]
RunningEndRole = Literal["leading_end", "trailing_end", "turnback_transition", "unknown"]
MeshSignalModel = Literal[
    "LEADING_END_FAST_DROP",
    "TRAILING_END_SMOOTH_CROSSOVER",
    "COVERAGE_GAP",
    "LATE_SWITCH",
    "PINGPONG",
    "INVALID_SIGNAL_GAP",
    "INSUFFICIENT_EVIDENCE",
]


_POSITION_TO_PHYSICAL_END: dict[str, tuple[MrPositionCode, MrPhysicalEnd, int | None]] = {
    "CT": ("CT", "car_1_end", 1),
    "CW": ("CW", "car_6_end", 6),
}


def mr_position(position_code: str) -> tuple[MrPositionCode, MrPhysicalEnd, int | None]:
    """Return fixed installation facts without inferring a current running role."""
    return _POSITION_TO_PHYSICAL_END.get(str(position_code or "").strip().upper(), ("unknown", "unknown", None))


def resolve_running_end_role(
    travel_direction: TravelDirection | str,
    increasing_direction_leading_end: MrPhysicalEnd | str,
    physical_end: MrPhysicalEnd | str,
) -> RunningEndRole:
    """Resolve the current running end from formal direction and formation data only."""
    direction = str(travel_direction or "").strip()
    if direction == "turnback_transition":
        return "turnback_transition"
    if direction not in {"increasing", "decreasing"}:
        return "unknown"

    leading_end = str(increasing_direction_leading_end or "").strip()
    current_end = str(physical_end or "").strip()
    if leading_end not in {"car_1_end", "car_6_end"} or current_end not in {"car_1_end", "car_6_end"}:
        return "unknown"

    is_leading = current_end == leading_end
    if direction == "decreasing":
        is_leading = not is_leading
    return "leading_end" if is_leading else "trailing_end"


def physical_end_label(value: MrPhysicalEnd | str) -> str:
    return {"car_1_end": "1车厢端", "car_6_end": "6车厢端"}.get(str(value or ""), "未知")


def running_end_role_label(value: RunningEndRole | str) -> str:
    return {
        "leading_end": "行驶方向头端",
        "trailing_end": "行驶方向尾端",
        "turnback_transition": "暂不判定",
    }.get(str(value or ""), "暂不判定")


def signal_model_label(value: MeshSignalModel | str) -> str:
    return {
        "LEADING_END_FAST_DROP": "行驶头端型快速衰减",
        "TRAILING_END_SMOOTH_CROSSOVER": "行驶尾端型平滑交叉",
        "COVERAGE_GAP": "覆盖缺口",
        "LATE_SWITCH": "切换过晚",
        "PINGPONG": "链路乒乓",
        "INVALID_SIGNAL_GAP": "信号数据缺口",
        "INSUFFICIENT_EVIDENCE": "证据不足",
    }.get(str(value or ""), "未知")
