from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from netconsole.models.api.ac_mesh_link import AcMeshMrStatusDTO
from netconsole.models.api.ground_unattended import (
    GroundUnattendedEndpointDTO,
    GroundUnattendedTrainDTO,
)
from netconsole.models.api.rail_transit_base_data import (
    RailTransitSummaryDTO,
    SectionDTO,
    StationDTO,
    TracksideApDTO,
    VehicleMrDTO,
)
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.services.rail_transit.train_identity import canonical_train_id_for


@dataclass(frozen=True)
class StationaryTracker:
    ap_identity: str = ""
    since: str = ""


@dataclass(frozen=True)
class ClassificationResult:
    train: GroundUnattendedTrainDTO
    tracker: StationaryTracker


class GroundUnattendedEligibilityClassifier:
    """仅使用基础资料结构和精确 AP 身份判断正线资格。"""

    def classify_all(
        self,
        *,
        summary: RailTransitSummaryDTO,
        stations: Iterable[StationDTO],
        sections: Iterable[SectionDTO],
        aps: Iterable[TracksideApDTO],
        mrs: Iterable[VehicleMrDTO],
        ac_rows: Iterable[AcMeshMrStatusDTO],
        trackers: dict[str, StationaryTracker],
        stationary_exclusion_minutes: int,
        now: datetime,
    ) -> list[ClassificationResult]:
        station_by_name = _unique_by_name(stations)
        section_by_name = _unique_by_name(sections)
        ap_by_id = {item.id: item for item in aps if item.id}
        ap_by_mac = _unique_by_value(aps, lambda item: _mac_key(item.mac))
        ap_by_name = _unique_by_value(aps, lambda item: item.name.strip().casefold())
        mr_groups: dict[str, list[VehicleMrDTO]] = {}
        for mr in mrs:
            key = _train_key(mr.train_id or mr.train_no)
            if key:
                mr_groups.setdefault(key, []).append(mr)
        ac_groups: dict[str, list[AcMeshMrStatusDTO]] = {}
        for row in ac_rows:
            key = _train_key(row.train_no)
            if key:
                ac_groups.setdefault(key, []).append(row)

        results: list[ClassificationResult] = []
        for key in sorted(set(mr_groups) | set(ac_groups)):
            base_mrs = mr_groups.get(key, [])
            online_rows = ac_groups.get(key, [])
            train_id = base_mrs[0].train_id if base_mrs else f"mesh:{key}"
            train_no = base_mrs[0].train_no if base_mrs else online_rows[0].train_no
            representative = self._representative_row(online_rows)
            ap = self._match_ap(representative, ap_by_id, ap_by_mac, ap_by_name)
            previous = trackers.get(train_id, StationaryTracker())
            tracker, same_ap_seconds = self._stationary_tracker(
                previous, ap, representative, now
            )
            status, reason, ping_eligible, deep_eligible = self._eligibility(
                summary=summary,
                station_by_name=station_by_name,
                section_by_name=section_by_name,
                ap=ap,
                row=representative,
                same_ap_seconds=same_ap_seconds,
                stationary_seconds=max(60, int(stationary_exclusion_minutes) * 60),
            )
            endpoints = self._endpoints(base_mrs, online_rows)
            if not any(
                item.online_status == "ONLINE" and item.management_ip
                for item in endpoints
            ):
                ping_eligible = False
                if status == "MAINLINE":
                    status, reason, deep_eligible = (
                        "OFFLINE",
                        "当前没有可用的在线 MR 管理地址",
                        False,
                    )
            results.append(
                ClassificationResult(
                    train=GroundUnattendedTrainDTO(
                        train_id=train_id,
                        train_no=train_no,
                        train_name=train_id,
                        ping_eligible=ping_eligible,
                        deep_collection_eligible=deep_eligible,
                        eligibility_status=status,  # type: ignore[arg-type]
                        exclusion_reason=reason,
                        current_ap_name=(
                            representative.peer_ap_name if representative else ""
                        ),
                        current_ap_mac=(
                            representative.peer_ap_mac if representative else ""
                        ),
                        station=(
                            ap.station
                            if ap
                            else representative.station
                            if representative
                            else ""
                        ),
                        section=(
                            ap.section
                            if ap
                            else representative.section
                            if representative
                            else ""
                        ),
                        mileage=(
                            ap.mileage.normalized
                            if ap
                            else representative.mileage
                            if representative
                            else ""
                        ),
                        rssi=representative.rssi if representative else None,
                        same_ap_duration_seconds=same_ap_seconds,
                        ac_received_at=representative.last_seen_at
                        if representative
                        else "",
                        endpoints=endpoints,
                        updated_at=now.isoformat(timespec="milliseconds"),
                    ),
                    tracker=tracker,
                )
            )
        return results

    @staticmethod
    def _representative_row(rows: list[AcMeshMrStatusDTO]) -> AcMeshMrStatusDTO | None:
        candidates = [row for row in rows if row.online_status == "online"] or rows
        return max(candidates, key=lambda item: item.last_seen_at or "", default=None)

    @staticmethod
    def _match_ap(
        row: AcMeshMrStatusDTO | None,
        by_id: dict[str, TracksideApDTO],
        by_mac: dict[str, TracksideApDTO],
        by_name: dict[str, TracksideApDTO],
    ) -> TracksideApDTO | None:
        if row is None:
            return None
        if row.peer_ap_id and row.peer_ap_id in by_id:
            return by_id[row.peer_ap_id]
        mac = _mac_key(row.peer_ap_mac)
        if mac and mac in by_mac:
            return by_mac[mac]
        name = row.peer_ap_name.strip().casefold()
        return by_name.get(name) if name else None

    @staticmethod
    def _stationary_tracker(
        previous: StationaryTracker,
        ap: TracksideApDTO | None,
        row: AcMeshMrStatusDTO | None,
        now: datetime,
    ) -> tuple[StationaryTracker, int]:
        identity = ""
        if ap is not None:
            identity = f"id:{ap.id}"
        elif row is not None:
            identity = (
                f"mac:{_mac_key(row.peer_ap_mac)}" if _mac_key(row.peer_ap_mac) else ""
            )
        if not identity:
            return StationaryTracker(), 0
        if previous.ap_identity != identity or not previous.since:
            return StationaryTracker(
                identity, now.isoformat(timespec="milliseconds")
            ), 0
        try:
            since = datetime.fromisoformat(previous.since)
            if since.tzinfo is None and now.tzinfo is not None:
                since = since.replace(tzinfo=now.tzinfo)
            duration = max(0, int((now - since).total_seconds()))
        except ValueError:
            return StationaryTracker(
                identity, now.isoformat(timespec="milliseconds")
            ), 0
        return previous, duration

    @staticmethod
    def _eligibility(
        *,
        summary: RailTransitSummaryDTO,
        station_by_name: dict[str, StationDTO],
        section_by_name: dict[str, SectionDTO],
        ap: TracksideApDTO | None,
        row: AcMeshMrStatusDTO | None,
        same_ap_seconds: int,
        stationary_seconds: int,
    ) -> tuple[str, str, bool, bool]:
        if row is None or row.data_status in {"no_data", "error"}:
            return "AC_UNKNOWN", "暂无有效 AC 在线状态", False, False
        if row.data_status != "fresh" or row.online_status == "stale":
            return "AC_STALE", "AC 在线状态已过期，暂停新的深度采集", False, False
        if row.online_status != "online":
            return "OFFLINE", "车辆当前未在线", False, False
        if ap is None:
            return (
                "AP_UNMATCHED",
                "当前 AP 无法与轨道交通基础资料精确匹配",
                False,
                False,
            )

        metadata = {
            str(key).casefold(): value for key, value in ap.base_metadata.items()
        }
        explicit_type = (
            str(metadata.get("belong_type") or ap.record_kind or "").strip().casefold()
        )
        facilities = _metadata_tokens(
            metadata.get("track_facilities"),
            metadata.get("track_facility"),
            metadata.get("facility_type"),
        )
        if explicit_type == "depot":
            return "DEPOT", "当前 AP 基础资料明确归属于车辆段", False, False
        if explicit_type == "parking_lot":
            return "PARKING_LOT", "当前 AP 基础资料明确归属于停车场", False, False
        if explicit_type == "storage_track" or "storage_track" in facilities:
            return "STORAGE_TRACK", "当前 AP 基础资料明确归属于存车线", False, False

        station = (
            station_by_name.get(ap.station.strip().casefold()) if ap.station else None
        )
        section = (
            section_by_name.get(ap.section.strip().casefold()) if ap.section else None
        )
        main_path = summary.main_path_code.strip().casefold()
        if station is not None:
            if station.node_type == "depot":
                return "DEPOT", "当前 AP 归属节点为车辆段", False, False
            if station.node_type == "parking_lot":
                return "PARKING_LOT", "当前 AP 归属节点为停车场", False, False
            if "storage_track" in station.track_facilities:
                return "STORAGE_TRACK", "当前站点设施为存车线", False, False
            if not station.participates_in_direction:
                return "NON_MAIN_PATH", "当前站点未参与正线方向判断", False, False
            if station.path_code.strip().casefold() != main_path:
                return "NON_MAIN_PATH", "当前站点不属于局点主路径", False, False
        if section is not None:
            if section.section_kind == "depot_connection":
                return "DEPOT_CONNECTION", "当前区间为出入段连接线", False, False
            if section.path_code.strip().casefold() != main_path:
                return "NON_MAIN_PATH", "当前区间不属于局点主路径", False, False
        if station is None and section is None:
            ap_path = str(metadata.get("path_code") or "").strip().casefold()
            if ap_path and ap_path != main_path:
                return "NON_MAIN_PATH", "当前 AP 不属于局点主路径", False, False
        if same_ap_seconds >= stationary_seconds:
            return (
                "MAINLINE_STATIONARY",
                f"同一正线 AP 连续停留 {same_ap_seconds // 60} 分钟，长 Ping 继续、暂停新的深度采集",
                True,
                False,
            )
        return "MAINLINE", "正线在线", True, True

    @staticmethod
    def _endpoints(
        base_mrs: list[VehicleMrDTO],
        online_rows: list[AcMeshMrStatusDTO],
    ) -> list[GroundUnattendedEndpointDTO]:
        result: list[GroundUnattendedEndpointDTO] = []
        for endpoint in ("CT", "CW"):
            base = next(
                (item for item in base_mrs if item.mr_position_code == endpoint), None
            )
            ac = next(
                (
                    item
                    for item in online_rows
                    if str(item.car_end or "").strip().upper()
                    in ({"CT"} if endpoint == "CT" else {"CW", "TC"})
                ),
                None,
            )
            result.append(
                GroundUnattendedEndpointDTO(
                    endpoint=endpoint,  # type: ignore[arg-type]
                    mr_id=(
                        base.id if base else ac.mr_device_id or ac.mr_id if ac else ""
                    ),
                    mr_name=(base.name if base else ac.mr_name if ac else ""),
                    device_id=base.device_id if base else None,
                    management_ip=(
                        base.management_ip if base else ac.management_ip if ac else ""
                    ),
                    online_status=str(ac.online_status or "unknown").upper()
                    if ac
                    else "UNKNOWN",
                )
            )
        return result


def _train_key(value: str) -> str:
    return canonical_train_id_for(value) or str(value or "").strip().casefold()


def _mac_key(value: str) -> str:
    return str(normalize_mac(value) or "").replace(":", "")


def _unique_by_name(items: Iterable[StationDTO | SectionDTO]):
    return _unique_by_value(items, lambda item: item.name.strip().casefold())


def _unique_by_value(items: Iterable, key):
    result = {}
    duplicates = set()
    for item in items:
        value = key(item)
        if not value:
            continue
        if value in result:
            duplicates.add(value)
        else:
            result[value] = item
    for value in duplicates:
        result.pop(value, None)
    return result


def _metadata_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, (list, tuple, set)):
            pending.extend(value)
            continue
        for token in re.split(r"[,;|/、，\s]+", str(value or "")):
            normalized = token.strip("[](){}'\"").casefold()
            if normalized:
                tokens.add(normalized)
    return tokens


__all__ = [
    "ClassificationResult",
    "GroundUnattendedEligibilityClassifier",
    "StationaryTracker",
]
