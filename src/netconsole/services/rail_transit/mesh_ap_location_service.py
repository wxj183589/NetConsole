from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from netconsole.core.database import Database
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import format_mac, normalize_mac_key
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


@dataclass(frozen=True)
class MeshApLocation:
    name: str = ""
    point_code: str = ""
    mac: str = ""
    station: str = ""
    section: str = ""
    section_start_station: str = ""
    section_end_station: str = ""
    mileage: str = ""
    line_side: str = ""
    direction: str = ""
    identity_status: str = "unresolved"
    identity_source: str = ""
    identity_reason: str = ""

    def to_serializable(self) -> dict[str, str]:
        return {
            "name": self.name,
            "point_code": self.point_code,
            "mac": format_mac(self.mac),
            "station": self.station,
            "section": self.section,
            "section_start_station": self.section_start_station,
            "section_end_station": self.section_end_station,
            "mileage": self.mileage,
            "line_side": self.line_side,
            "direction": self.direction,
            "identity_status": self.identity_status,
            "identity_source": self.identity_source,
            "identity_reason": self.identity_reason,
        }


class MeshApLocationSnapshot:
    def __init__(self, locations: Iterable[MeshApLocation] = ()) -> None:
        self._locations = tuple(locations)
        self._by_mac: dict[str, MeshApLocation | None] = {}
        for location in self._locations:
            mac = normalize_mac_key(location.mac)
            if mac:
                if mac in self._by_mac:
                    self._by_mac[mac] = None  # type: ignore[assignment]
                else:
                    self._by_mac[mac] = location

    @classmethod
    def from_base_data_items(cls, items: Iterable[object]) -> MeshApLocationSnapshot:
        locations: list[MeshApLocation] = []
        for item in items:
            mileage = getattr(getattr(item, "mileage", None), "raw", "")
            mac = format_mac(getattr(item, "mac", ""))
            direction = str(getattr(item, "direction", "") or "")
            locations.append(
                MeshApLocation(
                    name=str(
                        getattr(item, "name", "")
                        or getattr(item, "point_code", "")
                        or ""
                    ),
                    point_code=str(getattr(item, "point_code", "") or ""),
                    mac=mac or "",
                    station=str(getattr(item, "station", "") or ""),
                    section=str(getattr(item, "section", "") or ""),
                    section_start_station=str(
                        getattr(item, "section_start_station", "") or ""
                    ),
                    section_end_station=str(
                        getattr(item, "section_end_station", "") or ""
                    ),
                    mileage=str(mileage or ""),
                    line_side=str(getattr(item, "line_side", "") or direction),
                    direction=direction,
                    identity_status="matched" if mac else "unresolved",
                    identity_source="BASE_DATA_AP_MAC" if mac else "",
                )
            )
        return cls(locations)

    @classmethod
    def from_identity_entities(
        cls,
        rows: Iterable[Mapping[str, object]],
    ) -> MeshApLocationSnapshot:
        return cls(
            MeshApLocation(
                name=str(row.get("ap_name") or row.get("point_code") or ""),
                point_code=str(row.get("point_code") or ""),
                mac=format_mac(row.get("ap_mac")),
                station=str(row.get("station") or ""),
                section=str(row.get("section") or ""),
                mileage=str(row.get("mileage") or ""),
                direction=str(row.get("direction") or ""),
                identity_status=str(row.get("identity_status") or "matched"),
                identity_source=str(row.get("source") or ""),
                identity_reason=str(row.get("data_quality_warning") or ""),
            )
            for row in rows
        )

    @classmethod
    def from_serializable(cls, rows: Iterable[Mapping[str, object]]) -> MeshApLocationSnapshot:
        return cls(
            MeshApLocation(
                name=str(row.get("name") or row.get("point_code") or ""),
                point_code=str(row.get("point_code") or ""),
                mac=format_mac(row.get("mac")),
                station=str(row.get("station") or ""),
                section=str(row.get("section") or ""),
                section_start_station=str(row.get("section_start_station") or ""),
                section_end_station=str(row.get("section_end_station") or ""),
                mileage=str(row.get("mileage") or ""),
                line_side=str(row.get("line_side") or row.get("direction") or ""),
                direction=str(row.get("direction") or ""),
                identity_status=str(row.get("identity_status") or "unresolved"),
                identity_source=str(row.get("identity_source") or ""),
                identity_reason=str(row.get("identity_reason") or ""),
            )
            for row in rows
        )

    def to_serializable(self) -> list[dict[str, str]]:
        return [location.to_serializable() for location in self._locations]

    def values(self) -> tuple[MeshApLocation, ...]:
        return self._locations

    def with_identity_entities(
        self,
        rows: Iterable[Mapping[str, object]],
    ) -> MeshApLocationSnapshot:
        base_mac_keys = {
            mac_key
            for location in self._locations
            if (mac_key := normalize_mac_key(location.mac))
        }
        identity_locations = self.from_identity_entities(rows).values()
        return MeshApLocationSnapshot(
            (
                *self._locations,
                *(
                    location
                    for location in identity_locations
                    if normalize_mac_key(location.mac) not in base_mac_keys
                ),
            )
        )

    def resolve(self, row: Mapping[str, Any]) -> MeshApLocation:
        mac_key = normalize_mac_key(
            row.get("canonical_ap_mac")
            or row.get("peer_ap_mac")
            or row.get("ap_mac")
        )
        name = str(row.get("peer_ap_name") or row.get("ap_name") or "")
        location = self._by_mac.get(mac_key) if mac_key else None
        if location is not None:
            return location
        reason = "缺少规范 AP MAC" if not mac_key else "未找到唯一 AP Identity"
        return MeshApLocation(
            name=name,
            point_code=str(row.get("point_code") or row.get("ap_point_code") or ""),
            mac=format_mac(mac_key) if mac_key else "",
            station=str(row.get("peer_site") or row.get("station") or row.get("belong_station") or ""),
            section=str(row.get("peer_section") or row.get("section") or row.get("belong_section") or ""),
            section_start_station=str(row.get("section_start_station") or ""),
            section_end_station=str(row.get("section_end_station") or ""),
            mileage=str(row.get("mileage") or ""),
            line_side=str(row.get("line_side") or row.get("direction") or ""),
            direction=str(row.get("direction") or ""),
            identity_status=(
                "ambiguous"
                if mac_key
                and mac_key in self._by_mac
                and self._by_mac[mac_key] is None
                else "unresolved"
            ),
            identity_source="",
            identity_reason=reason,
        )


def enrich_mesh_ap_location_row(
    row: Mapping[str, object],
    snapshot: MeshApLocationSnapshot,
) -> dict[str, object]:
    """Apply the same AP location projection used by MESH pages and reports."""
    location = snapshot.resolve(row)
    result = dict(row)
    result["peer_ap_name"] = str(result.get("peer_ap_name") or location.name or "")
    result["peer_ap_mac"] = str(result.get("peer_ap_mac") or location.mac or "")
    result["peer_site"] = location.station or str(result.get("peer_site") or "")
    result["station"] = location.station or str(result.get("station") or result.get("peer_site") or "")
    result["belong_section"] = location.section or str(
        result.get("belong_section") or result.get("peer_section") or ""
    )
    result["peer_section"] = result["belong_section"]
    result["section"] = result["belong_section"]
    result["peer_location"] = location.mileage or str(
        result.get("peer_location") or result.get("mileage") or ""
    )
    result["mileage"] = result["peer_location"]
    result["peer_direction"] = location.line_side or str(
        result.get("peer_direction") or result.get("line_side") or ""
    )
    result["line_side"] = result["peer_direction"]
    return result


class MeshApLocationService:
    def __init__(self, base_query: RailTransitBaseDataQueryService) -> None:
        self.base_query = base_query

    def snapshot(self, site_id: str) -> MeshApLocationSnapshot:
        list_location_items = getattr(self.base_query, "list_ap_location_items", None)
        if callable(list_location_items):
            snapshot = MeshApLocationSnapshot.from_base_data_items(
                list_location_items(site_id)
            )
        else:
            first = self.base_query.list_aps(site_id, page=1, page_size=500)
            items = list(first.items)
            page = 2
            while len(items) < first.total:
                part = self.base_query.list_aps(site_id, page=page, page_size=500)
                if not part.items:
                    break
                items.extend(part.items)
                page += 1
            snapshot = MeshApLocationSnapshot.from_base_data_items(items)
        paths = getattr(self.base_query, "paths", None)
        if paths is not None:
            database = Database(paths.site_db_path(site_id))
            if database.exists():
                identity_query = ApIdentityQueryService(database)
                state = identity_query.index_state()
                if state is not None and int(state.get("revision") or 0) > 0:
                    return snapshot.with_identity_entities(
                        identity_query.list_entities()
                    )
        return snapshot


def normalize_mesh_ap_mac(value: object) -> str:
    """Return the common user-visible H3C MAC form; invalid values are empty."""

    return format_mac(value)


__all__ = [
    "MeshApLocation",
    "MeshApLocationService",
    "MeshApLocationSnapshot",
    "enrich_mesh_ap_location_row",
    "normalize_mesh_ap_mac",
]
