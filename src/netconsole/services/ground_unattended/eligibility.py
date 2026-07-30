from __future__ import annotations

import ipaddress
import re
import unicodedata
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
from netconsole.services.rail_transit.station_source_utils import (
    canonical_station_name,
)
from netconsole.services.rail_transit.train_identity import canonical_train_id_for
from netconsole.services.rail_transit.trackside_ap_location import (
    DEPOT_PING_LOCATION_CLASSES,
    location_class_is_explicit,
    resolve_trackside_ap_location,
)


@dataclass(frozen=True)
class StationaryTracker:
    ap_identity: str = ""
    since: str = ""


@dataclass(frozen=True)
class ClassificationResult:
    train: GroundUnattendedTrainDTO
    tracker: StationaryTracker


@dataclass(frozen=True)
class EligibilityDecision:
    status: str
    reason: str
    location_class: str
    mainline_eligible: bool = False
    ping_eligible: bool = False
    deep_collection_eligible: bool = False
    ping_inclusion_reason: str = ""
    ping_exclusion_reason: str = ""
    deep_exclusion_reason: str = ""


@dataclass(frozen=True)
class LocationResolution:
    ap: TracksideApDTO | None = None
    station: StationDTO | None = None
    section: SectionDTO | None = None
    match_level: str = "UNMATCHED"
    match_reason: str = "当前 AP 和站点均无法与基础资料匹配"
    canonical_station_name: str = ""


class GroundUnattendedEligibilityClassifier:
    """分开表达正线资格和位置匹配质量，所有降级均保留明确证据。"""

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
        ping_depot_trains_enabled: bool = False,
    ) -> list[ClassificationResult]:
        station_rows = list(stations)
        section_rows = list(sections)
        ap_rows = list(aps)
        station_by_name = _unique_by_value(
            station_rows, lambda item: canonical_station_name(item.name).casefold()
        )
        station_by_alias = _unique_by_value(
            station_rows,
            lambda item: canonical_station_name(
                item.source_station_value
            ).casefold(),
        )
        section_by_name = _unique_by_value(
            section_rows, lambda item: _location_key(item.name)
        )
        ap_by_id = {item.id: item for item in ap_rows if item.id}
        ap_by_mac = _unique_by_value(ap_rows, lambda item: _mac_key(item.mac))
        ap_by_registry_mac = _unique_ap_registry_macs(ap_rows)

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
            train_no = (
                base_mrs[0].train_no if base_mrs else online_rows[0].train_no
            )
            representative = self._representative_row(online_rows)
            location = self._resolve_location(
                representative,
                station_by_name=station_by_name,
                station_by_alias=station_by_alias,
                section_by_name=section_by_name,
                ap_by_id=ap_by_id,
                ap_by_mac=ap_by_mac,
                ap_by_registry_mac=ap_by_registry_mac,
            )
            previous = trackers.get(train_id, StationaryTracker())
            tracker, same_ap_seconds = self._stationary_tracker(
                previous, location.ap, representative, now
            )
            decision = self._eligibility(
                summary=summary,
                location=location,
                row=representative,
                same_ap_seconds=same_ap_seconds,
                stationary_seconds=max(
                    60, int(stationary_exclusion_minutes) * 60
                ),
                ping_depot_trains_enabled=ping_depot_trains_enabled,
            )
            endpoints = self._endpoints(base_mrs, online_rows)
            has_online_endpoint = any(
                item.online_status == "ONLINE" for item in endpoints
            )
            has_ping_target = any(
                item.ping_target_eligible for item in endpoints
            )
            if (
                decision.status
                not in {"AC_UNKNOWN", "AC_STALE", "OFFLINE"}
                and not has_online_endpoint
            ):
                decision = EligibilityDecision(
                    status="OFFLINE",
                    reason="当前没有在线 MR",
                    location_class=(
                        decision.location_class
                        if decision.location_class != "UNKNOWN"
                        else "OFFLINE"
                    ),
                    ping_exclusion_reason="当前没有在线 MR",
                    deep_exclusion_reason="当前没有在线 MR",
                )
            elif not has_ping_target and decision.ping_eligible:
                address_reason = next(
                    (
                        item.ping_exclusion_reason
                        for item in endpoints
                        if item.online_status == "ONLINE"
                        and item.ping_exclusion_reason
                    ),
                    "当前没有可用的在线 MR 管理地址",
                )
                decision = EligibilityDecision(
                    status=decision.status,
                    reason=address_reason,
                    location_class=decision.location_class,
                    mainline_eligible=decision.mainline_eligible,
                    ping_eligible=False,
                    deep_collection_eligible=False,
                    ping_exclusion_reason=address_reason,
                    deep_exclusion_reason=address_reason,
                )
            raw_ap_name = representative.peer_ap_name if representative else ""
            raw_ap_mac = representative.peer_ap_mac if representative else ""
            results.append(
                ClassificationResult(
                    train=GroundUnattendedTrainDTO(
                        train_id=train_id,
                        train_no=train_no,
                        train_name=train_id,
                        location_class=decision.location_class,  # type: ignore[arg-type]
                        mainline_eligible=decision.mainline_eligible,
                        ping_eligible=decision.ping_eligible,
                        deep_collection_eligible=(
                            decision.deep_collection_eligible
                        ),
                        ping_inclusion_reason=decision.ping_inclusion_reason,
                        ping_exclusion_reason=decision.ping_exclusion_reason,
                        deep_exclusion_reason=decision.deep_exclusion_reason,
                        eligibility_status=decision.status,  # type: ignore[arg-type]
                        exclusion_reason=decision.reason,
                        location_match_level=location.match_level,  # type: ignore[arg-type]
                        location_match_reason=location.match_reason,
                        resolved_ap_id=location.ap.id if location.ap else "",
                        resolved_ap_name=location.ap.name if location.ap else "",
                        raw_peer_ap_name=raw_ap_name,
                        raw_peer_ap_mac=raw_ap_mac,
                        canonical_station_name=location.canonical_station_name,
                        current_ap_name=raw_ap_name,
                        current_ap_mac=raw_ap_mac,
                        station=(
                            location.station.name
                            if location.station
                            else representative.station
                            if representative
                            else ""
                        ),
                        section=(
                            location.section.name
                            if location.section
                            else representative.section
                            if representative
                            else ""
                        ),
                        mileage=(
                            location.ap.mileage.normalized
                            if location.ap
                            else representative.mileage
                            if representative
                            else ""
                        ),
                        rssi=representative.rssi if representative else None,
                        same_ap_duration_seconds=same_ap_seconds,
                        ac_received_at=(
                            representative.last_seen_at if representative else ""
                        ),
                        endpoints=endpoints,
                        updated_at=now.isoformat(timespec="milliseconds"),
                    ),
                    tracker=tracker,
                )
            )
        return results

    @staticmethod
    def _representative_row(
        rows: list[AcMeshMrStatusDTO],
    ) -> AcMeshMrStatusDTO | None:
        candidates = [row for row in rows if row.online_status == "online"] or rows
        return max(candidates, key=lambda item: item.last_seen_at or "", default=None)

    @classmethod
    def _resolve_location(
        cls,
        row: AcMeshMrStatusDTO | None,
        *,
        station_by_name: dict[str, StationDTO],
        station_by_alias: dict[str, StationDTO],
        section_by_name: dict[str, SectionDTO],
        ap_by_id: dict[str, TracksideApDTO],
        ap_by_mac: dict[str, TracksideApDTO],
        ap_by_registry_mac: dict[str, TracksideApDTO],
    ) -> LocationResolution:
        if row is None:
            return LocationResolution(match_reason="暂无 AC 位置数据")

        raw_station_key = canonical_station_name(row.station).casefold()
        station = station_by_name.get(raw_station_key) if raw_station_key else None
        station_level = "STATION_EXACT" if station else "UNMATCHED"
        station_reason = (
            f"AC 站点“{row.station}”规范化后精确匹配基础资料"
            if station
            else ""
        )
        if station is None and raw_station_key:
            station = station_by_alias.get(raw_station_key)
            if station is not None:
                station_level = "STATION_ALIAS"
                station_reason = (
                    f"AC 站点“{row.station}”通过已保存来源别名匹配基础资料"
                )
        section = (
            section_by_name.get(_location_key(row.section)) if row.section else None
        )

        ap, ap_level, ap_reason = cls._match_ap(
            row,
            by_id=ap_by_id,
            by_mac=ap_by_mac,
            by_registry_mac=ap_by_registry_mac,
        )
        if station is None and ap is not None and ap.station:
            ap_station_key = canonical_station_name(ap.station).casefold()
            station = station_by_name.get(ap_station_key)
            if station is None:
                station = station_by_alias.get(ap_station_key)
        if section is None and ap is not None and ap.section:
            section = section_by_name.get(_location_key(ap.section))

        level = ap_level if ap is not None else station_level
        reason = ap_reason if ap is not None else station_reason
        if level == "UNMATCHED" and section is not None:
            level = "STATION_EXACT"
            reason = f"AC 区间“{row.section}”精确匹配基础资料"
        canonical_name = (
            canonical_station_name(station.name)
            if station is not None
            else canonical_station_name(row.station)
        )
        return LocationResolution(
            ap=ap,
            station=station,
            section=section,
            match_level=level,
            match_reason=reason
            or "当前 AP 和站点均无法与基础资料匹配",
            canonical_station_name=canonical_name,
        )

    @staticmethod
    def _match_ap(
        row: AcMeshMrStatusDTO,
        *,
        by_id: dict[str, TracksideApDTO],
        by_mac: dict[str, TracksideApDTO],
        by_registry_mac: dict[str, TracksideApDTO],
    ) -> tuple[TracksideApDTO | None, str, str]:
        mac = _mac_key(row.peer_ap_mac)
        if mac and mac in by_mac:
            return by_mac[mac], "AP_EXACT", "通过 AP MAC 精确匹配"
        if mac and mac in by_registry_mac:
            return (
                by_registry_mac[mac],
                "AP_REGISTRY",
                "通过基础资料中的 Radio/BSSID 映射到 AP",
            )
        if row.peer_ap_id and row.peer_ap_id in by_id:
            return by_id[row.peer_ap_id], "AP_EXACT", "通过 AP ID 精确匹配"
        return None, "UNMATCHED", ""

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
                f"mac:{_mac_key(row.peer_ap_mac)}"
                if _mac_key(row.peer_ap_mac)
                else ""
            )
        if not identity:
            return StationaryTracker(), 0
        if previous.ap_identity != identity or not previous.since:
            return (
                StationaryTracker(
                    identity, now.isoformat(timespec="milliseconds")
                ),
                0,
            )
        try:
            since = datetime.fromisoformat(previous.since)
            if since.tzinfo is None and now.tzinfo is not None:
                since = since.replace(tzinfo=now.tzinfo)
            duration = max(0, int((now - since).total_seconds()))
        except ValueError:
            return (
                StationaryTracker(
                    identity, now.isoformat(timespec="milliseconds")
                ),
                0,
            )
        return previous, duration

    @classmethod
    def _eligibility(
        cls,
        *,
        summary: RailTransitSummaryDTO,
        location: LocationResolution,
        row: AcMeshMrStatusDTO | None,
        same_ap_seconds: int,
        stationary_seconds: int,
        ping_depot_trains_enabled: bool,
    ) -> EligibilityDecision:
        location_class, location_reason, participates = (
            cls._resolved_location_class(summary, location)
        )
        if row is None or row.data_status in {"no_data", "error"}:
            return EligibilityDecision(
                "AC_UNKNOWN",
                "暂无有效 AC 在线状态",
                location_class,
                ping_exclusion_reason="暂无有效 AC 在线状态",
                deep_exclusion_reason="暂无有效 AC 在线状态",
            )
        if row.data_status != "fresh" or row.online_status == "stale":
            return EligibilityDecision(
                "AC_STALE",
                "AC 在线状态已过期，暂停新的任务调度",
                location_class,
                ping_exclusion_reason="AC 在线状态已过期",
                deep_exclusion_reason="AC 在线状态已过期",
            )
        if row.online_status != "online":
            return EligibilityDecision(
                "OFFLINE",
                "车辆当前未在线",
                location_class if location.ap is not None else "OFFLINE",
                ping_exclusion_reason="车辆当前未在线",
                deep_exclusion_reason="车辆当前未在线",
            )
        if location.ap is None:
            return EligibilityDecision(
                "AP_UNMATCHED",
                "当前 AP MAC 未匹配任何轨旁 AP 基础资料",
                "UNKNOWN",
                ping_exclusion_reason="AP 未匹配",
                deep_exclusion_reason="AP 未匹配",
            )
        if location_class in DEPOT_PING_LOCATION_CLASSES:
            status = {
                "DEPOT": "DEPOT",
                "PARKING_YARD": "PARKING_LOT",
                "STABLING": "STORAGE_TRACK",
            }[location_class]
            if ping_depot_trains_enabled:
                return EligibilityDecision(
                    status,
                    f"{location_reason}；已启用车辆段长 Ping",
                    location_class,
                    ping_eligible=True,
                    ping_inclusion_reason="已启用车辆段长 Ping",
                    deep_exclusion_reason="场段列车不参与深度采集",
                )
            return EligibilityDecision(
                status,
                location_reason,
                location_class,
                ping_exclusion_reason="未启用车辆段长 Ping",
                deep_exclusion_reason="场段列车不参与深度采集",
            )
        if location_class != "MAINLINE" or not participates:
            status = (
                "DEPOT_CONNECTION"
                if location_class == "DEPOT_CONNECTION"
                else "NON_MAIN_PATH"
            )
            return EligibilityDecision(
                status,
                location_reason,
                location_class,
                ping_exclusion_reason="当前位置不参与正线长 Ping",
                deep_exclusion_reason="当前位置不参与深度采集",
            )
        if same_ap_seconds >= stationary_seconds:
            return EligibilityDecision(
                "MAINLINE_STATIONARY",
                f"同一正线 AP 连续停留 {same_ap_seconds // 60} 分钟，长 Ping 继续、暂停新的深度采集",
                "MAINLINE",
                mainline_eligible=True,
                ping_eligible=True,
                ping_inclusion_reason="正线在线",
                deep_exclusion_reason="同一正线 AP 停留超过阈值",
            )
        return EligibilityDecision(
            "MAINLINE",
            "正线在线",
            "MAINLINE",
            mainline_eligible=True,
            ping_eligible=True,
            deep_collection_eligible=True,
            ping_inclusion_reason="正线在线",
        )

    @staticmethod
    def _resolved_location_class(
        summary: RailTransitSummaryDTO,
        location: LocationResolution,
    ) -> tuple[str, str, bool]:
        ap = location.ap
        if ap is None:
            return "UNKNOWN", "当前 AP 未匹配轨旁 AP 基础资料", False
        if location_class_is_explicit(ap.location_class_source):
            return (
                ap.location_class,
                f"当前 AP 基础资料明确标记为 {ap.location_class}",
                ap.participates_in_mainline,
            )

        metadata = {
            str(key).casefold(): value
            for key, value in ap.base_metadata.items()
            if str(key).casefold()
            not in {
                "location_class",
                "participates_in_mainline",
                "location_class_source",
            }
        }
        metadata.update(
            {
                "belong_type": metadata.get("belong_type") or ap.record_kind,
                "station_name": ap.station,
                "section_name": ap.section,
            }
        )
        facilities = _metadata_tokens(
            metadata.get("track_facilities"),
            metadata.get("track_facility"),
            metadata.get("facility_type"),
        )
        if "storage_track" in facilities:
            return "STABLING", "当前 AP 基础资料明确归属于存车线", False
        legacy_class, _, _ = resolve_trackside_ap_location(metadata)
        if legacy_class != "MAINLINE":
            return (
                legacy_class,
                f"当前 AP 历史基础资料解析为 {legacy_class}",
                False,
            )

        station = location.station
        if station is not None:
            station_name = canonical_station_name(station.name)
            if station.node_type == "depot":
                return "DEPOT", f"当前车辆位于{station_name}", False
            if station.node_type == "parking_lot":
                return "PARKING_YARD", f"当前车辆位于{station_name}", False
            if "storage_track" in station.track_facilities:
                return "STABLING", "当前站点设施为存车线", False
        section = location.section
        if section is not None and section.section_kind == "depot_connection":
            return "DEPOT_CONNECTION", "当前区间为出入段连接线", False

        main_path = summary.main_path_code.strip().casefold()
        if station is not None and (
            not station.participates_in_direction
            or station.path_code.strip().casefold() != main_path
        ):
            return "NON_MAINLINE", "当前站点不参与局点正线判断", False
        if section is not None and section.path_code.strip().casefold() != main_path:
            return "NON_MAINLINE", "当前区间不属于局点主路径", False
        ap_path = str(metadata.get("path_code") or "").strip().casefold()
        if ap_path and ap_path != main_path:
            return "NON_MAINLINE", "当前 AP 不属于局点主路径", False
        if not ap.participates_in_mainline:
            return "MAINLINE", "当前 AP 已设置为不参与正线判断", False
        return "MAINLINE", "已匹配轨旁 AP，未标记特殊区域，默认正线", True

    @staticmethod
    def _endpoints(
        base_mrs: list[VehicleMrDTO],
        online_rows: list[AcMeshMrStatusDTO],
    ) -> list[GroundUnattendedEndpointDTO]:
        result: list[GroundUnattendedEndpointDTO] = []
        for endpoint in ("CT", "CW"):
            base = next(
                (item for item in base_mrs if item.mr_position_code == endpoint),
                None,
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
            management_ip = (
                base.management_ip
                if base
                else ac.management_ip
                if ac
                else ""
            )
            online_status = (
                str(ac.online_status or "unknown").upper()
                if ac
                else "UNKNOWN"
            )
            address_valid = _valid_management_ip(management_ip)
            ping_target_eligible = (
                online_status == "ONLINE" and address_valid
            )
            ping_exclusion_reason = ""
            if online_status != "ONLINE":
                ping_exclusion_reason = f"{endpoint} 当前不在线"
            elif not management_ip:
                ping_exclusion_reason = f"{endpoint} 未配置管理 IP"
            elif not address_valid:
                ping_exclusion_reason = f"{endpoint} 管理 IP 无效"
            result.append(
                GroundUnattendedEndpointDTO(
                    endpoint=endpoint,  # type: ignore[arg-type]
                    mr_id=(
                        base.id
                        if base
                        else ac.mr_device_id or ac.mr_id
                        if ac
                        else ""
                    ),
                    mr_name=(base.name if base else ac.mr_name if ac else ""),
                    device_id=base.device_id if base else None,
                    management_ip=management_ip,
                    online_status=online_status,
                    ping_target_eligible=ping_target_eligible,
                    ping_exclusion_reason=ping_exclusion_reason,
                )
            )
        return result


def _train_key(value: str) -> str:
    return canonical_train_id_for(value) or str(value or "").strip().casefold()


def _mac_key(value: str) -> str:
    return str(normalize_mac(value) or "").replace(":", "")


def _valid_management_ip(value: object) -> bool:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return bool(
        address.version == 4
        and not address.is_unspecified
        and not address.is_multicast
        and str(address) != "255.255.255.255"
    )


def _location_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


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


def _unique_ap_registry_macs(
    items: Iterable[TracksideApDTO],
) -> dict[str, TracksideApDTO]:
    pairs: list[tuple[str, TracksideApDTO]] = []
    for item in items:
        for radio in item.radios:
            key = _mac_key(radio.bssid)
            if key:
                pairs.append((key, item))
    return _unique_pair_values(pairs)


def _unique_pair_values(
    pairs: Iterable[tuple[str, TracksideApDTO]],
) -> dict[str, TracksideApDTO]:
    result: dict[str, TracksideApDTO] = {}
    duplicates: set[str] = set()
    for key, item in pairs:
        normalized = key.strip().casefold()
        if normalized in result and result[normalized].id != item.id:
            duplicates.add(normalized)
        else:
            result[normalized] = item
    for key in duplicates:
        result.pop(key, None)
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
    "LocationResolution",
    "StationaryTracker",
]
