from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac


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
            "mac": normalize_mac(self.mac) or "",
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
            mac = normalize_mac(location.mac)
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
            mac = normalize_mac(getattr(item, "mac", ""))
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
                    line_side=str(getattr(item, "line_side", "") or ""),
                direction=str(getattr(item, "direction", "") or ""),
                    identity_status="matched" if mac else "unresolved",
                    identity_source="BASE_DATA_AP_MAC" if mac else "",
                )
            )
        return cls(locations)

    @classmethod
    def from_serializable(cls, rows: Iterable[Mapping[str, object]]) -> MeshApLocationSnapshot:
        return cls(
            MeshApLocation(
                name=str(row.get("name") or row.get("point_code") or ""),
                point_code=str(row.get("point_code") or ""),
                mac=normalize_mac(row.get("mac")) or "",
                station=str(row.get("station") or ""),
                section=str(row.get("section") or ""),
                section_start_station=str(row.get("section_start_station") or ""),
                section_end_station=str(row.get("section_end_station") or ""),
                mileage=str(row.get("mileage") or ""),
                line_side=str(row.get("line_side") or ""),
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

    def resolve(self, row: Mapping[str, Any]) -> MeshApLocation:
        mac = normalize_mesh_ap_mac(
            row.get("peer_ap_mac")
            or row.get("active_peer_mac")
            or row.get("peer_mac_normalized")
            or row.get("peer_mac")
            or row.get("ap_mac")
        )
        name = str(row.get("peer_ap_name") or row.get("ap_name") or "")
        location = self._by_mac.get(mac) if mac else None
        if location is not None:
            return location
        reason = "缺少规范 AP MAC" if not mac else "未找到唯一 AP MAC 基础资料"
        return MeshApLocation(
            name=name,
            point_code=str(row.get("point_code") or row.get("ap_point_code") or ""),
            mac=mac,
            station=str(row.get("peer_site") or row.get("station") or row.get("belong_station") or ""),
            section=str(row.get("peer_section") or row.get("section") or row.get("belong_section") or ""),
            section_start_station=str(row.get("section_start_station") or ""),
            section_end_station=str(row.get("section_end_station") or ""),
            mileage=str(row.get("mileage") or ""),
            line_side=str(row.get("line_side") or ""),
            direction=str(row.get("direction") or ""),
            identity_status="ambiguous" if mac and mac in self._by_mac and self._by_mac[mac] is None else "unresolved",
            identity_source="",
            identity_reason=reason,
        )


class MeshApLocationService:
    def __init__(self, base_query: RailTransitBaseDataQueryService) -> None:
        self.base_query = base_query

    def snapshot(self, site_id: str) -> MeshApLocationSnapshot:
        list_location_items = getattr(self.base_query, "list_ap_location_items", None)
        if callable(list_location_items):
            return MeshApLocationSnapshot.from_base_data_items(list_location_items(site_id))
        first = self.base_query.list_aps(site_id, page=1, page_size=500)
        items = list(first.items)
        page = 2
        while len(items) < first.total:
            part = self.base_query.list_aps(site_id, page=page, page_size=500)
            if not part.items:
                break
            items.extend(part.items)
            page += 1
        return MeshApLocationSnapshot.from_base_data_items(items)


def normalize_mesh_ap_mac(value: object) -> str:
    """兼容旧调用方，统一返回公共规范 MAC；非法值返回空串。"""
    return normalize_mac(value) or ""


__all__ = [
    "MeshApLocation",
    "MeshApLocationService",
    "MeshApLocationSnapshot",
    "normalize_mesh_ap_mac",
]
