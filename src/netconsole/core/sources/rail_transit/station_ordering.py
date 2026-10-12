from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


_NON_MAINLINE_NODE_TYPES = {
    "depot",
    "parking_lot",
    "connection_point",
    "other",
}
_NODE_TYPE_RANK = {
    "depot": 0,
    "parking_lot": 1,
    "connection_point": 2,
    "other": 3,
    "unknown": 4,
    "station": 5,
}


def _value(row: Mapping[str, Any] | object, field: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(field, default)
    return getattr(row, field, default)


def _text(row: Mapping[str, Any] | object, field: str, default: str = "") -> str:
    return str(_value(row, field, default) or "").strip()


def _integer(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_projection(row: Mapping[str, Any] | object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        result = dict(row)
    else:
        result = {
            field: _value(row, field)
            for field in (
                "id",
                "station_id",
                "name",
                "station_name",
                "node_type",
                "path_code",
                "center_mileage_m",
                "canonical_station_name",
                "code",
                "source_order",
                "participates_in_direction",
                "sort_order",
                "mainline_order",
                "raw_payload_json",
                "enabled",
            )
            if _value(row, field) is not None
        }
    raw_payload = _value(row, "raw_payload_json", "")
    try:
        metadata = json.loads(str(raw_payload or "{}"))
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    if isinstance(metadata, Mapping):
        for field in (
            "node_type",
            "path_code",
            "center_mileage_m",
            "canonical_station_name",
            "code",
            "source_order",
            "participates_in_direction",
            "sort_order",
        ):
            if field not in result or result[field] in (None, ""):
                result[field] = metadata.get(field)
    if not result.get("id"):
        result["id"] = _value(row, "station_id", "")
    if not result.get("name"):
        result["name"] = _value(row, "station_name", "")
    result.setdefault("node_type", "station")
    result.setdefault("participates_in_direction", result.get("node_type") == "station")
    return result


def valid_mainline_order(row: Mapping[str, Any] | object) -> int | None:
    """Return the numeric mainline order, never a relationship/database id."""

    node_type = _text(row, "node_type", "station").casefold() or "station"
    if node_type in _NON_MAINLINE_NODE_TYPES:
        return None
    if node_type == "station" and _value(row, "participates_in_direction", True) is False:
        return None
    raw_order = _value(row, "sort_order")
    if raw_order in (None, ""):
        raw_order = _value(row, "mainline_order")
    order = _integer(raw_order)
    return order if order is not None and order >= 0 else None


def _fallback_key(row: Mapping[str, Any] | object) -> tuple[Any, ...]:
    node_type = _text(row, "node_type", "unknown").casefold() or "unknown"
    center_mileage = _value(row, "center_mileage_m")
    try:
        center_value = float(center_mileage) if center_mileage not in (None, "") else 0.0
        center_missing = center_mileage in (None, "")
    except (TypeError, ValueError):
        center_value = 0.0
        center_missing = True
    source_order = _integer(_value(row, "source_order"))
    return (
        _NODE_TYPE_RANK.get(node_type, 6),
        _text(row, "path_code").casefold(),
        source_order is None,
        source_order if source_order is not None else 0,
        center_missing,
        center_value,
        _text(row, "canonical_station_name").casefold(),
        _text(row, "code").casefold(),
        _text(row, "name", _text(row, "station_name")).casefold(),
        _text(row, "id", _text(row, "station_id")),
    )


def station_display_order_key(row: Mapping[str, Any] | object) -> tuple[Any, ...]:
    mainline_order = valid_mainline_order(row)
    if mainline_order is not None:
        return (0, mainline_order, *_fallback_key(row))
    return (1, 0, *_fallback_key(row))


def sort_rail_stations(
    rows: Iterable[Mapping[str, Any] | object],
    *,
    reverse: bool = False,
) -> list[Any]:
    """Canonical station order shared by read and edit projections."""

    return sorted(rows, key=station_display_order_key, reverse=reverse)


def _legacy_sequence_is_explicit(sequence_no: int | None, max_mainline_order: int) -> bool:
    """Keep old high planning numbers, but reject old index/id-like values."""

    if sequence_no is None or sequence_no <= 0:
        return False
    return max_mainline_order <= 0 or sequence_no > max_mainline_order


def canonicalize_trackside_ap_plan_rows(
    rows: Iterable[Mapping[str, Any] | object],
    stations: Iterable[Mapping[str, Any] | object] = (),
) -> list[dict[str, Any]]:
    """Return plan rows in canonical order while retaining relationship ids.

    ``planning_order`` is the explicit user-maintained value.  For databases
    created before that field existed, a legacy sequence is only retained when
    it is above the current mainline range; old mainline/index-like values are
    recomputed from station metadata instead.
    """

    station_projections = [_metadata_projection(station) for station in stations]
    station_by_id = {
        _text(station, "id", _text(station, "station_id")): station
        for station in station_projections
        if _text(station, "id", _text(station, "station_id"))
    }
    mainline_orders = [
        order
        for station in station_projections
        if (order := valid_mainline_order(station)) is not None
    ]
    max_mainline_order = max(mainline_orders, default=0)

    prepared: list[dict[str, Any]] = []
    used_display_orders: set[int] = set()
    auto_rows: list[dict[str, Any]] = []
    for index, source in enumerate(rows):
        row = dict(source) if isinstance(source, Mapping) else dict(vars(source))
        station_id = _text(row, "station_id")
        station = station_by_id.get(station_id)
        explicit = _integer(row.get("planning_order"))
        if explicit is not None and explicit <= 0:
            explicit = None
        if explicit is None:
            legacy_sequence = _integer(row.get("sequence_no"))
            if _legacy_sequence_is_explicit(legacy_sequence, max_mainline_order):
                explicit = legacy_sequence
        mainline_order = valid_mainline_order(station) if station is not None else None
        display_order = explicit if explicit is not None else mainline_order
        item = {
            "row": row,
            "station": station,
            "station_id": station_id,
            "explicit": explicit,
            "mainline_order": mainline_order,
            "display_order": display_order,
            "index": index,
        }
        if display_order is None:
            auto_rows.append(item)
        else:
            used_display_orders.add(display_order)
        prepared.append(item)

    def auto_key(item: dict[str, Any]) -> tuple[Any, ...]:
        station = item["station"]
        base = station_display_order_key(station) if station is not None else station_display_order_key(item["row"])
        return (*base, item["station_id"], item["index"])

    next_display_order = max(
        max_mainline_order,
        max(used_display_orders, default=max_mainline_order),
    ) + 1
    for item in sorted(auto_rows, key=auto_key):
        while next_display_order in used_display_orders:
            next_display_order += 1
        item["display_order"] = next_display_order
        used_display_orders.add(next_display_order)
        next_display_order += 1

    def final_key(item: dict[str, Any]) -> tuple[Any, ...]:
        station = item["station"]
        base = station_display_order_key(station) if station is not None else station_display_order_key(item["row"])
        return (
            int(item["display_order"]),
            *base,
            item["station_id"],
            item["index"],
        )

    result: list[dict[str, Any]] = []
    for item in sorted(prepared, key=final_key):
        row = dict(item["row"])
        display_order = int(item["display_order"])
        row["sequence_no"] = display_order
        row["display_order"] = display_order
        row["planning_order"] = item["explicit"]
        result.append(row)
    return result


__all__ = [
    "canonicalize_trackside_ap_plan_rows",
    "sort_rail_stations",
    "station_display_order_key",
    "valid_mainline_order",
]
