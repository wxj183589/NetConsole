from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from netconsole.core.sources.rail_transit.station_source_utils import (
    canonical_station_name,
    parse_station_source_value,
)


StationImportMatchStatus = Literal["resolved", "missing", "ambiguous"]


@dataclass(frozen=True)
class StationImportMatch:
    status: StationImportMatchStatus
    station_id: str = ""
    station_name: str = ""
    candidate_ids: tuple[str, ...] = ()
    candidate_names: tuple[str, ...] = ()
    method: str = ""


def resolve_station_import_match(
    values: Mapping[str, Any],
    formal_stations: Sequence[Mapping[str, Any] | Any],
) -> StationImportMatch:
    """Resolve an imported station against the current site's formal stations.

    Matching is deliberately limited to a validated station ID or exact
    station-source aliases. AP identity, network data and fuzzy text are not
    valid station evidence here.
    """

    requested_site_id = _text(values.get("site_id"))
    stations = []
    for station in formal_stations:
        if not _text(_value(station, "id")):
            continue
        if _text(_value(station, "source_kind")) == "legacy_ap_derived":
            continue
        station_site_id = _text(_value(station, "site_id"))
        if requested_site_id and station_site_id and station_site_id != requested_site_id:
            continue
        stations.append(station)
    by_id = {_text(_value(station, "id")): station for station in stations}
    station_id = _text(values.get("station_id"))
    station_name = _text(values.get("station_name"))

    if station_id and station_id in by_id:
        name_candidates = _candidate_stations(station_name, stations)
        if name_candidates and station_id not in {_text(_value(item, "id")) for item in name_candidates}:
            return _ambiguous([by_id[station_id], *name_candidates], method="station_id_name_conflict")
        station = by_id[station_id]
        return _resolved(station, method="station_id_exact")

    candidates = _candidate_stations(station_name, stations)
    if len(candidates) == 1:
        return _resolved(candidates[0], method="station_name_exact")
    if len(candidates) > 1:
        return _ambiguous(candidates, method="station_name_ambiguous")
    return StationImportMatch(status="missing", method="station_name_missing")


def _candidate_stations(station_name: str, stations: Sequence[Mapping[str, Any] | Any]) -> list[Any]:
    aliases = _station_aliases(station_name)
    if not aliases:
        return []
    result: list[Any] = []
    for station in stations:
        station_aliases = set()
        for field in ("name", "canonical_station_name", "source_station_value"):
            station_aliases.update(_station_aliases(_value(station, field)))
        if aliases & station_aliases:
            result.append(station)
    return result


def _station_aliases(value: Any) -> set[str]:
    text = _text(value)
    if not text:
        return set()
    parsed = parse_station_source_value(text)
    aliases: set[str] = set()
    for candidate in (
        canonical_station_name(text),
        str(parsed.canonical_station_name or "").strip(),
    ):
        alias = candidate.casefold().strip()
        if not alias:
            continue
        aliases.add(alias)
        if alias.endswith("站") and not alias.endswith("车站"):
            aliases.add(alias[:-1])
        elif not alias.endswith(("站", "段", "场")):
            aliases.add(f"{alias}站")
    return aliases


def _resolved(station: Any, *, method: str) -> StationImportMatch:
    station_id = _text(_value(station, "id"))
    station_name = _text(_value(station, "name"))
    return StationImportMatch(
        status="resolved",
        station_id=station_id,
        station_name=station_name,
        candidate_ids=(station_id,) if station_id else (),
        candidate_names=(station_name,) if station_name else (),
        method=method,
    )


def _ambiguous(stations: Sequence[Any], *, method: str) -> StationImportMatch:
    ordered: list[Any] = []
    seen: set[str] = set()
    for station in stations:
        station_id = _text(_value(station, "id"))
        if not station_id or station_id in seen:
            continue
        seen.add(station_id)
        ordered.append(station)
    return StationImportMatch(
        status="ambiguous",
        candidate_ids=tuple(_text(_value(station, "id")) for station in ordered),
        candidate_names=tuple(_text(_value(station, "name")) for station in ordered),
        method=method,
    )


def _value(item: Mapping[str, Any] | Any, field: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = ["StationImportMatch", "resolve_station_import_match"]
