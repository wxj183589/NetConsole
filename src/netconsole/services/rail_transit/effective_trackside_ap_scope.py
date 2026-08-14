from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.services.ap_online_overview import is_fit_ap_online
from netconsole.services.neighbor_matcher import (
    NeighborDeviceIdentityIndex,
    NeighborMatchResult,
    is_generic_neighbor_name,
)
from netconsole.services.rail_transit.station_source_utils import (
    canonical_station_name,
    format_station_display_name,
)
from netconsole.services.rail_transit.trackside_ap_runtime_snapshot import (
    TracksideApRuntimeSnapshot,
    build_trackside_ap_runtime_snapshot,
    deduplicate_lldp_snapshot_rows,
    select_latest_lldp_snapshot_rows,
)


_BASE_STATION = "__base_station__"
_BASE_SECTION = "__base_section__"
_IN_SERVICE_STATES = {
    "",
    "active",
    "enabled",
    "included",
    "in_service",
    "normal",
    "参与当前调试",
    "在用",
}
_EXCLUDED_SCOPE_STATES = {
    "excluded",
    "not_included",
    "out_of_scope",
    "disabled",
    "排除",
    "明确排除",
    "不纳入",
    "未纳入当前项目",
}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled", "否"}
_BASE_DATA_MISSING_REASON = (
    "在线 AP 尚未匹配轨旁 AP 基础资料；基础资料仅作补充，不影响业务生成。"
)


@dataclass(frozen=True)
class TracksideApScopeContext:
    site_id: str
    project_id: str = ""
    line_name: str = ""
    project_phase: str = ""

    @classmethod
    def from_metadata(
        cls,
        site_id: str,
        metadata: Mapping[str, object] | None = None,
    ) -> "TracksideApScopeContext":
        values = metadata or {}
        return cls(
            site_id=str(site_id or "").strip(),
            project_id=str(values.get("project_id") or site_id or "").strip(),
            line_name=str(values.get("line_name") or "").strip(),
            project_phase=str(
                values.get("construction_phase_id")
                or values.get("project_phase_id")
                or values.get("project_phase")
                or ""
            ).strip(),
        )


@dataclass(frozen=True)
class TracksideApScopeExcludedItem:
    source: str
    item_id: str
    device_name: str = ""
    station_name: str = ""
    operation_status: str = ""
    project_phase: str = ""
    reason: str = ""
    mac: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "item_id": self.item_id,
            "device_name": self.device_name,
            "station_name": self.station_name,
            "operation_status": self.operation_status,
            "project_phase": self.project_phase,
            "reason": self.reason,
            "mac": self.mac,
        }


@dataclass(frozen=True)
class TracksideApScopeUnmatchedOnlineItem:
    source: str
    item_id: str
    ap_name: str = ""
    mac: str = ""
    ac_status: str = ""
    runtime_station_text: str = ""
    reason: str = ""
    suggested_action: str = ""
    association_status: str = "unknown"
    reason_code: str = ""
    observed_association_status: str = "unknown"
    observed_switch_device_id: str = ""
    observed_switch_device_name: str = ""
    observed_port: str = ""
    observed_match_method: str = ""
    planning_status: str = "unknown"
    planned_switch_device_id: str = ""
    planned_switch_device_name: str = ""
    planned_port: str = ""
    fit_ap_collected_at: str = ""
    lldp_collected_at: str = ""
    lldp_candidate_count: int = 0
    ap_mac_raw: str = ""
    ap_mac_normalized: str = ""
    planning_record_id: str = ""
    planning_station_name: str = ""
    plan_station_id: str = ""
    planning_match_method: str = ""
    lldp_exists: bool = False
    lldp_local_interface: str = ""
    lldp_remote_device_name: str = ""
    lldp_system_name: str = ""
    lldp_management_ip: str = ""
    lldp_chassis_id: str = ""
    switch_candidate_count: int = 0
    matched_switch_device_id: str = ""
    switch_match_method: str = ""
    failure_stage: str = ""
    source_revisions: dict[str, str] = field(default_factory=dict)
    snapshot_revision: str = ""
    snapshot_created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "item_id": self.item_id,
            "ap_name": self.ap_name,
            "mac": self.mac,
            "ac_status": self.ac_status,
            "runtime_station_text": self.runtime_station_text,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
            "association_status": self.association_status,
            "reason_code": self.reason_code,
            "observed_association_status": self.observed_association_status,
            "observed_switch_device_id": self.observed_switch_device_id,
            "observed_switch_device_name": self.observed_switch_device_name,
            "observed_port": self.observed_port,
            "observed_match_method": self.observed_match_method,
            "planning_status": self.planning_status,
            "planned_switch_device_id": self.planned_switch_device_id,
            "planned_switch_device_name": self.planned_switch_device_name,
            "planned_port": self.planned_port,
            "fit_ap_collected_at": self.fit_ap_collected_at,
            "lldp_collected_at": self.lldp_collected_at,
            "lldp_candidate_count": self.lldp_candidate_count,
            "ap_mac_raw": self.ap_mac_raw,
            "ap_mac_normalized": self.ap_mac_normalized,
            "planning_record_id": self.planning_record_id,
            "planning_station_name": self.planning_station_name,
            "plan_station_id": self.plan_station_id,
            "planning_match_method": self.planning_match_method,
            "lldp_exists": self.lldp_exists,
            "lldp_local_interface": self.lldp_local_interface,
            "lldp_remote_device_name": self.lldp_remote_device_name,
            "lldp_system_name": self.lldp_system_name,
            "lldp_management_ip": self.lldp_management_ip,
            "lldp_chassis_id": self.lldp_chassis_id,
            "switch_candidate_count": self.switch_candidate_count,
            "matched_switch_device_id": self.matched_switch_device_id,
            "switch_match_method": self.switch_match_method,
            "failure_stage": self.failure_stage,
            "source_revisions": dict(self.source_revisions),
            "snapshot_revision": self.snapshot_revision,
            "snapshot_created_at": self.snapshot_created_at,
        }


@dataclass(frozen=True)
class EffectiveTracksideApReference:
    reference_id: str
    station_id: str
    station_name: str
    ap_name: str
    ap_mac: str
    ap_uuid: str
    operation_status: str
    project_phase: str
    row: dict[str, object | None] = field(compare=False)


@dataclass
class EffectiveTracksideApScope:
    context: TracksideApScopeContext
    station_names: dict[str, str]
    station_sort_orders: dict[str, int]
    references: list[EffectiveTracksideApReference]
    resources: list[dict[str, object | None]]
    runtime_resources: list[dict[str, object | None]]
    plans_by_station: dict[str, dict[str, object | None]]
    online_reference_ids: set[str]
    excluded_items: list[TracksideApScopeExcludedItem]
    unmatched_online_items: list[TracksideApScopeUnmatchedOnlineItem] = field(
        default_factory=list
    )
    fit_ap_resource_total_count: int = 0
    fit_ap_online_total_count: int = 0
    fit_ap_offline_total_count: int = 0
    fit_ap_unknown_total_count: int = 0
    excluded_device_total_count: int | None = None
    unmatched_online_total_count: int | None = None
    ambiguous_online_total_count: int = 0
    unmatched_status_counts: dict[str, int] = field(default_factory=dict)
    updated_at: str = ""
    _reference_by_id: dict[str, EffectiveTracksideApReference] = field(
        default_factory=dict,
        repr=False,
    )
    _identity_index: dict[tuple[str, str], set[str]] = field(
        default_factory=dict,
        repr=False,
    )
    _all_reference_by_id: dict[str, EffectiveTracksideApReference] = field(
        default_factory=dict,
        repr=False,
    )
    _all_identity_index: dict[tuple[str, str], set[str]] = field(
        default_factory=dict,
        repr=False,
    )
    runtime_snapshot: TracksideApRuntimeSnapshot = field(
        default_factory=TracksideApRuntimeSnapshot
    )

    @property
    def eligible_station_ids(self) -> set[str]:
        return set(self.station_scope_ids)

    @property
    def station_scope_ids(self) -> set[str]:
        return set(self.station_names)

    @property
    def scope_station_count(self) -> int:
        return len(self.eligible_station_ids)

    @property
    def scope_device_count(self) -> int:
        return len(self.references)

    @property
    def scope_ap_reference_count(self) -> int:
        return len(self.references)

    @property
    def fit_ap_matched_count(self) -> int:
        return len(self.resources)

    @property
    def fit_ap_matched_online_count(self) -> int:
        return len(self.online_reference_ids)

    @property
    def fit_ap_unmatched_online_count(self) -> int:
        return (
            self.unmatched_online_total_count
            if self.unmatched_online_total_count is not None
            else len(self.unmatched_online_items)
        )

    @property
    def fit_ap_lldp_snapshot_stale_count(self) -> int:
        return self._unmatched_status_count("lldp_snapshot_stale")

    @property
    def fit_ap_lldp_exact_match_pending_count(self) -> int:
        return self._unmatched_status_count("lldp_exact_match_pending")

    @property
    def fit_ap_current_conflict_count(self) -> int:
        return self._unmatched_status_count("lldp_conflict_current")

    @property
    def fit_ap_ambiguous_online_count(self) -> int:
        return self._unmatched_status_count("ambiguous")

    @property
    def fit_ap_station_master_missing_count(self) -> int:
        return self._unmatched_status_count("station_master_missing")

    @property
    def fit_ap_unknown_association_count(self) -> int:
        return self._unmatched_status_count("unknown")

    @property
    def fit_ap_planning_missing_count(self) -> int:
        return self._unmatched_status_count("planning_missing")

    @property
    def fit_ap_switch_not_found_count(self) -> int:
        return self._unmatched_status_count("switch_not_found")

    @property
    def fit_ap_switch_identity_ambiguous_count(self) -> int:
        return self._unmatched_status_count("switch_identity_ambiguous")

    @property
    def fit_ap_switch_data_incomplete_count(self) -> int:
        return self._unmatched_status_count("switch_data_incomplete")

    @property
    def fit_ap_plan_not_found_count(self) -> int:
        return self._unmatched_status_count("ap_plan_not_found")

    @property
    def fit_ap_plan_station_missing_count(self) -> int:
        return self._unmatched_status_count("plan_station_missing")

    @property
    def fit_ap_plan_station_invalid_count(self) -> int:
        return self._unmatched_status_count("plan_station_invalid")

    def _unmatched_status_count(self, status: str) -> int:
        if self.unmatched_status_counts:
            return self.unmatched_status_counts.get(status, 0)
        return sum(
            1
            for item in self.unmatched_online_items
            if item.association_status == status
        )

    def unmatched_online_summary(self) -> str:
        parts: list[str] = []
        pending = (
            self.fit_ap_lldp_snapshot_stale_count
            + self.fit_ap_lldp_exact_match_pending_count
        )
        conflict = (
            self.fit_ap_current_conflict_count
            + self.fit_ap_ambiguous_online_count
        )
        invalid_plan_station = (
            self.fit_ap_plan_station_missing_count
            + self.fit_ap_plan_station_invalid_count
        )
        if pending:
            parts.append(f"{pending} 个等待 LLDP 数据同步")
        if conflict:
            parts.append(f"{conflict} 个存在当前 LLDP 冲突")
        if self.fit_ap_switch_not_found_count:
            parts.append(
                f"{self.fit_ap_switch_not_found_count} 个已有 AC 侧 LLDP，"
                "但上联交换机未匹配设备管理记录"
            )
        if self.fit_ap_switch_identity_ambiguous_count:
            parts.append(
                f"{self.fit_ap_switch_identity_ambiguous_count} 个上联交换机身份冲突"
            )
        if self.fit_ap_switch_data_incomplete_count:
            parts.append(
                f"{self.fit_ap_switch_data_incomplete_count} 个交换机站点资料不完整"
            )
        if self.fit_ap_plan_not_found_count:
            parts.append(f"{self.fit_ap_plan_not_found_count} 个站点缺少 AP 规划")
        if invalid_plan_station:
            parts.append(f"{invalid_plan_station} 个规划站点缺失或无效")
        basic_missing = (
            self.fit_ap_planning_missing_count
            + self.fit_ap_station_master_missing_count
        )
        if basic_missing:
            parts.append(f"{basic_missing} 个缺少其他基础资料")
        if self.fit_ap_unknown_association_count:
            parts.append(
                f"{self.fit_ap_unknown_association_count} 个处于未知关联状态"
            )
        if not parts:
            return ""
        return (
            f"数据质量提示：另有 {self.fit_ap_unmatched_online_count} 个 AC 在线 AP "
            "暂未计入业务统计；其中 "
            + "；".join(parts)
            + "。"
        )

    @property
    def excluded_device_count(self) -> int:
        if self.excluded_device_total_count is not None:
            return self.excluded_device_total_count
        return len(
            {
                ("mac", item.mac)
                if item.mac
                else (item.source, item.item_id)
                for item in self.excluded_items
            }
        )

    @property
    def scope_description(self) -> str:
        parts = ["当前项目"]
        if self.context.project_phase:
            parts.append(self.context.project_phase)
        parts.append("当前工作范围轨旁 AP")
        return " · ".join(parts)

    def match_reference(
        self,
        row: Mapping[str, object | None],
    ) -> EffectiveTracksideApReference | None:
        direct = _reference_id(row.get("_scope_reference_id") or row.get("extension_id"))
        if direct and direct in self._reference_by_id:
            return self._reference_by_id[direct]
        for key in _identity_keys(row):
            candidates = self._identity_index.get(key, set())
            if len(candidates) == 1:
                return self._reference_by_id[next(iter(candidates))]
            if len(candidates) > 1:
                return None
        return None

    def filter_identity_rows(
        self,
        rows: Iterable[dict[str, object | None]],
    ) -> list[dict[str, object | None]]:
        result: list[dict[str, object | None]] = []
        for row in rows:
            reference = self.match_reference(row)
            if reference is None:
                continue
            result.append(
                {
                    **row,
                    "_scope_reference_id": reference.reference_id,
                    "station_id": reference.station_id,
                    "site": reference.station_name,
                    "site_name": reference.station_name,
                }
            )
        return result

    def filter_business_rows(
        self,
        rows: Iterable[dict[str, object | None]],
        *,
        switch_device_ids: set[str] | None = None,
    ) -> list[dict[str, object | None]]:
        return self.filter_switch_scope_rows(rows, switch_device_ids=switch_device_ids)

    def filter_switch_scope_rows(
        self,
        rows: Iterable[dict[str, object | None]],
        *,
        switch_device_ids: set[str] | None = None,
    ) -> list[dict[str, object | None]]:
        result: list[dict[str, object | None]] = []
        seen: set[tuple[str, str, str]] = set()
        for row in rows:
            device_id = str(row.get("device_uuid") or "").strip()
            if switch_device_ids and device_id not in switch_device_ids:
                continue
            reference = self.match_reference(row)
            if reference is None and self._has_excluded_reference_match(row):
                continue
            enriched = dict(row)
            if reference is not None:
                enriched.update(
                    {
                        "_scope_reference_id": reference.reference_id,
                        "station_id": reference.station_id,
                        "site": reference.station_name,
                        "site_name": reference.station_name,
                    }
                )
            else:
                station_id = str(row.get("station_id") or "").strip()
                station_name = str(
                    row.get("site")
                    or row.get("site_name")
                    or row.get("station_name")
                    or ""
                ).strip()
                if not station_id:
                    # Device management defines the switch-port business
                    # skeleton. A formal base-data station ID is optional
                    # enrichment and must not suppress that runtime row.
                    if switch_device_ids is None or not station_name:
                        continue
                    enriched["site"] = station_name
                    enriched["site_name"] = station_name
                    enriched["station_id"] = ""
                    enriched["effective_station_id"] = ""
                    enriched["station_consistency_status"] = "unresolved"
                    enriched["station_consistency_reason"] = "STATION_ID_MISSING"
                elif station_id in self.station_scope_ids:
                    enriched["station_id"] = station_id
                    enriched["site"] = self.station_names.get(station_id, station_name)
                    enriched["site_name"] = enriched["site"]
                else:
                    continue
            key = (
                str(enriched.get("device_uuid") or enriched.get("device_name") or ""),
                str(enriched.get("interface_name") or ""),
                str(enriched.get("_scope_reference_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(enriched)
        return result

    def _has_excluded_reference_match(
        self,
        row: Mapping[str, object | None],
    ) -> bool:
        direct = _reference_id(row.get("_scope_reference_id") or row.get("extension_id"))
        if direct and direct in self._all_reference_by_id:
            return direct not in self._reference_by_id
        for key in _identity_keys(row):
            candidates = self._all_identity_index.get(key, set())
            if len(candidates) == 1:
                return next(iter(candidates)) not in self._reference_by_id
            if len(candidates) > 1:
                return True
        return False

    def _resolve_scope_station_id(self, station_id: str, station_name: str) -> str:
        del station_name
        if station_id in self.station_scope_ids:
            return station_id
        return ""

    def station_statistics(self) -> list[dict[str, object | None]]:
        online_by_station: dict[str, int] = defaultdict(int)
        for reference_id in self.online_reference_ids:
            reference = self._reference_by_id.get(reference_id)
            if reference is not None:
                online_by_station[reference.station_id] += 1

        rows: list[dict[str, object | None]] = []
        for station_id in sorted(
            self.plans_by_station,
            key=lambda value: (
                self.station_sort_orders.get(value, 2**31 - 1),
                self.station_names.get(value, ""),
            ),
        ):
            plan = self.plans_by_station[station_id]
            planning_missing = False
            planned = max(int(plan.get("ap_count") or 0), 0)
            observed_online = online_by_station.get(station_id, 0)
            actual = min(observed_online, planned)
            status = "normal"
            warning = ""
            if planned == 0 and observed_online > 0:
                status = "unplanned_online"
                warning = "存在未纳入规划的在线 AP。"
            elif observed_online > planned:
                status = "over_planned"
                warning = "实际上线 AP 数量超过当前规划数量，请检查规划资料或 AP 归属关系。"
            count_anomaly = status in {"unplanned_online", "over_planned"}
            rows.append(
                {
                    "station_id": station_id,
                    "station_name": self.station_names.get(station_id, ""),
                    "planned_ap_count": planned,
                    "actual_online_count": actual,
                    "offline_count": max(planned - actual, 0),
                    "online_rate": (
                        round(actual * 100 / planned, 1)
                        if planned > 0 and status == "normal"
                        else None
                    ),
                    "remark": str((plan or {}).get("remark") or ""),
                    "planning_missing": planning_missing,
                    "count_anomaly": count_anomaly,
                    "status": status,
                    "warning": warning,
                }
            )
        return rows

    def overview_export_rows(self) -> list[dict[str, object | None]]:
        station_rows = self.station_statistics()
        result: list[dict[str, object | None]] = []
        for row in station_rows:
            remark = str(row.get("remark") or "")
            warning = str(row.get("warning") or "")
            result.append(
                {
                    "site": row["station_name"],
                    "total": (
                        None
                        if row.get("planning_missing")
                        else row["planned_ap_count"]
                    ),
                    "online": row["actual_online_count"],
                    "offline": row["offline_count"],
                    "online_rate": (
                        f"{float(row['online_rate']):.1f}%"
                        if row.get("online_rate") is not None
                        else "—"
                    ),
                    "remark": "；".join(value for value in (remark, warning) if value),
                    "status": row["status"],
                }
            )
        planned_total = sum(int(row["planned_ap_count"] or 0) for row in station_rows)
        matched_online_total = sum(
            int(row["actual_online_count"] or 0) for row in station_rows
        )
        stale_total = self.fit_ap_lldp_snapshot_stale_count + self.fit_ap_lldp_exact_match_pending_count
        conflict_total = self.fit_ap_current_conflict_count + self.fit_ap_ambiguous_online_count
        real_missing_total = (
            self.fit_ap_planning_missing_count
            + self.fit_ap_station_master_missing_count
            + self.fit_ap_switch_data_incomplete_count
        )
        online_total = min(matched_online_total, planned_total)
        total_anomaly = any(bool(row.get("count_anomaly")) for row in station_rows)
        total_remark = (
            f"AC AP 资源 {self.fit_ap_resource_total_count} 个；"
            f"实际上线 {self.fit_ap_online_total_count} 个；"
            f"已关联上线 {matched_online_total} 个；"
            f"等待 LLDP 同步 {stale_total} 个；当前 LLDP 冲突 {conflict_total} 个；"
            f"交换机未匹配 {self.fit_ap_switch_not_found_count} 个；"
            f"交换机身份冲突 {self.fit_ap_switch_identity_ambiguous_count} 个；"
            f"AP 规划缺失 {self.fit_ap_plan_not_found_count} 个；"
            f"规划站点无效 {self.fit_ap_plan_station_missing_count + self.fit_ap_plan_station_invalid_count} 个；"
            f"基础资料待补充 {real_missing_total} 个；状态未知 {self.fit_ap_unknown_total_count} 个。"
        )
        if summary := self.unmatched_online_summary():
            total_remark = f"{total_remark} {summary}"
        if total_anomaly:
            total_remark = f"{total_remark} 统计范围存在数量异常，请查看分站状态。"
        result.append(
            {
                "site": "合计",
                "total": planned_total,
                "online": online_total,
                "offline": max(planned_total - online_total, 0),
                "online_rate": (
                    f"{online_total / planned_total:.1%}"
                    if planned_total > 0 and not total_anomaly
                    else "—"
                ),
                "remark": total_remark,
                "status": "anomaly" if total_anomaly else "normal",
            }
        )
        return result


def resolve_effective_trackside_ap_scope_from_database(
    database: Database,
    *,
    site_id: str,
    context: TracksideApScopeContext | None = None,
    resource_rows: Iterable[Mapping[str, object | None]] | None = None,
    runtime_station_rows: Iterable[Mapping[str, object | None]] | None = None,
    switch_identity_rows: Iterable[Mapping[str, object | None]] | None = None,
    lightweight: bool = False,
    detail_limit: int | None = None,
) -> EffectiveTracksideApScope:
    repository = AcRepository(database)
    plans = repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
    extension_points = (
        repository.list_trackside_ap_scope_reference_rows()
        if lightweight
        else repository.list_ap_extension_points()
    )
    return resolve_effective_trackside_ap_scope(
        context=context or TracksideApScopeContext(site_id=site_id, project_id=site_id),
        station_rows=extension_points,
        plan_rows=plans,
        reference_rows=extension_points,
        resource_rows=(
            resource_rows
            if resource_rows is not None
            else repository.list_fit_ap_online_scope_rows()
            if lightweight
            else repository.list_all_fit_ap_resources_with_metadata()
        ),
        runtime_station_rows=(
            runtime_station_rows
            if runtime_station_rows is not None
            else repository.list_trackside_ap_runtime_station_evidence_rows()
        ),
        switch_identity_rows=(
            switch_identity_rows
            if switch_identity_rows is not None
            else repository.list_trackside_switch_identity_rows()
        ),
        detail_limit=detail_limit,
    )


def resolve_effective_trackside_ap_scope(
    *,
    context: TracksideApScopeContext,
    station_rows: Iterable[Mapping[str, object | None]],
    plan_rows: Iterable[Mapping[str, object | None]],
    reference_rows: Iterable[Mapping[str, object | None]],
    resource_rows: Iterable[Mapping[str, object | None]],
    runtime_station_rows: Iterable[Mapping[str, object | None]] | None = None,
    switch_identity_rows: Iterable[Mapping[str, object | None]] | None = None,
    runtime_snapshot: TracksideApRuntimeSnapshot | None = None,
    detail_limit: int | None = None,
) -> EffectiveTracksideApScope:
    all_station_rows = [dict(row) for row in station_rows]
    plans = [dict(row) for row in plan_rows]
    resources_input = [dict(row) for row in resource_rows]
    station_names, station_sort_orders, station_aliases, station_node_uids = (
        _build_station_index(context.site_id, all_station_rows, plans)
    )
    plans_by_station, plan_rows_by_station_name = _build_plan_index(
        plans,
        station_names,
        station_aliases,
        station_node_uids,
    )
    switch_identity_index = (
        NeighborDeviceIdentityIndex(switch_identity_rows)
        if switch_identity_rows is not None
        else None
    )
    selected_runtime_rows = deduplicate_lldp_snapshot_rows(
        select_latest_lldp_snapshot_rows(runtime_station_rows or ())
    )
    runtime_station_index = _build_runtime_station_index(
        context,
        station_names,
        station_aliases,
        selected_runtime_rows,
    )
    runtime_station_master_missing_macs = _build_runtime_station_master_missing_macs(
        context,
        station_names,
        station_aliases,
        selected_runtime_rows,
    )
    snapshot = runtime_snapshot or build_trackside_ap_runtime_snapshot(
        fit_ap_rows=resources_input,
        switch_lldp_rows=selected_runtime_rows,
    )
    excluded: list[TracksideApScopeExcludedItem] = []
    unmatched_online: list[TracksideApScopeUnmatchedOnlineItem] = []
    excluded_keys: set[tuple[str, str]] = set()
    unmatched_online_keys: set[tuple[str, str]] = set()
    ambiguous_online_keys: set[tuple[str, str]] = set()
    unmatched_status_counts: dict[str, int] = defaultdict(int)

    def add_excluded(item: TracksideApScopeExcludedItem) -> None:
        key = ("mac", item.mac) if item.mac else (item.source, item.item_id)
        excluded_keys.add(key)
        if (
            item.source == "fit_ap_online_excluded"
            and "多" in item.reason
        ):
            ambiguous_online_keys.add(key)
        if detail_limit is None or len(excluded) < detail_limit:
            excluded.append(item)

    def add_unmatched(
        key: tuple[str, str],
        item: TracksideApScopeUnmatchedOnlineItem,
    ) -> None:
        if key in unmatched_online_keys:
            return
        unmatched_online_keys.add(key)
        unmatched_status_counts[item.association_status] += 1
        app_logger.log_debug(
            "trackside_ap_association.unresolved",
            (
                f"site_id={context.site_id} ap_mac={item.mac} "
                f"device_id={item.matched_switch_device_id} "
                f"reason_code={item.reason_code} stage={item.failure_stage}"
            ),
        )
        if detail_limit is None or len(unmatched_online) < detail_limit:
            unmatched_online.append(item)
    all_references: dict[str, EffectiveTracksideApReference] = {}
    eligible: dict[str, EffectiveTracksideApReference] = {}

    for row in reference_rows:
        values = dict(row)
        if str(values.get("belong_type") or "") in {_BASE_STATION, _BASE_SECTION}:
            continue
        metadata = _metadata(values.get("raw_payload_json"))
        reference_id = _reference_id(values.get("id"))
        station_name = str(values.get("station_name") or "").strip()
        operation_status = str(
            metadata.get("work_scope_status")
            or metadata.get("operation_status")
            or values.get("work_scope_status")
            or values.get("operation_status")
            or ""
        ).strip()
        project_phase = str(
            metadata.get("construction_phase_id")
            or metadata.get("project_phase_id")
            or metadata.get("project_phase")
            or ""
        ).strip()
        ap_name = str(values.get("ap_name") or metadata.get("ap_name") or "").strip()
        ap_mac = normalize_mac(
            values.get("ap_mac_norm")
            or values.get("ap_mac_display")
            or metadata.get("ap_mac")
        ) or ""
        ap_uuid = str(metadata.get("ap_uuid") or "").strip()
        station_id, station_reason = _resolve_station_id(
            values,
            metadata,
            station_aliases,
            station_node_uids,
        )
        reference = EffectiveTracksideApReference(
            reference_id=reference_id,
            station_id=station_id,
            station_name=station_names.get(station_id, station_name),
            ap_name=ap_name,
            ap_mac=ap_mac,
            ap_uuid=ap_uuid,
            operation_status=operation_status,
            project_phase=project_phase,
            row=values,
        )
        all_references[reference_id] = reference
        reason = _reference_exclusion_reason(
            values,
            metadata,
            context,
            station_reason,
            operation_status,
            project_phase,
            reference,
        )
        if reason:
            add_excluded(_excluded_reference(reference, reason))
        else:
            eligible[reference_id] = reference

    aliases: dict[str, str] = {}
    for reference_ids in _group_reference_identities(eligible.values()):
        if len(reference_ids) <= 1:
            continue
        stations = {eligible[reference_id].station_id for reference_id in reference_ids}
        if len(stations) == 1:
            selected = min(reference_ids)
            for duplicate_id in reference_ids:
                if duplicate_id == selected:
                    continue
                aliases[duplicate_id] = selected
                duplicate = eligible.pop(duplicate_id)
                add_excluded(_excluded_reference(duplicate, "同一 AP 稳定身份重复，已去重。"))
        else:
            for ambiguous_id in reference_ids:
                ambiguous = eligible.pop(ambiguous_id)
                add_excluded(
                    _excluded_reference(
                        ambiguous,
                        "同一 AP 稳定身份关联到多个站点，需人工处理。",
                    )
                )

    all_identity_index = _build_identity_index(all_references.values(), aliases)
    eligible_identity_index = _build_identity_index(eligible.values())
    scope_references = dict(eligible)
    resources: list[dict[str, object | None]] = []
    online_reference_ids: set[str] = set()
    updated_at = ""
    resource_identity_index: dict[tuple[str, str], set[str]] = defaultdict(set)
    runtime_identity_keys: set[tuple[str, str]] = set()
    online_resource_total = 0
    offline_resource_total = 0
    unknown_resource_total = 0
    matched_resources: dict[str, dict[str, object | None]] = {}
    runtime_resources_by_key: dict[tuple[str, str], dict[str, object | None]] = {}
    for resource in resources_input:
        switch_match: NeighborMatchResult | None = None
        diagnostic_plan: dict[str, object | None] | None = None
        association_diagnostic: tuple[str, str, str, str] | None = None
        resolved_plan_station_id = ""
        runtime_key = _runtime_resource_key(resource)
        runtime_identity_keys.add(runtime_key)
        current_runtime = runtime_resources_by_key.get(runtime_key)
        if current_runtime is None or _resource_preference_key(resource) > _resource_preference_key(current_runtime):
            runtime_resources_by_key[runtime_key] = resource
        reference_id, reason = _match_resource_reference(
            resource,
            all_references,
            all_identity_index,
            eligible,
            aliases,
        )
        binding_source = "base_data"
        if not reference_id and reason == _BASE_DATA_MISSING_REASON:
            mac = normalize_mac(resource.get("ap_mac")) or ""
            station_ids = runtime_station_index.get(mac, set())
            if len(station_ids) == 1:
                station_id = next(iter(station_ids))
                reference_id = f"runtime-lldp:{mac}"
                if reference_id not in scope_references:
                    runtime_reference = EffectiveTracksideApReference(
                        reference_id=reference_id,
                        station_id=station_id,
                        station_name=station_names[station_id],
                        ap_name=str(resource.get("ap_name") or "").strip(),
                        ap_mac=mac,
                        ap_uuid=str(resource.get("ap_uuid") or "").strip(),
                        operation_status="included",
                        project_phase=context.project_phase,
                        row={"_scope_binding_source": "switch_lldp_exact"},
                    )
                    scope_references[reference_id] = runtime_reference
                    eligible_identity_index.setdefault(("mac", mac), set()).add(
                        reference_id
                    )
                binding_source = "switch_lldp_exact"
                reason = ""
            elif len(station_ids) > 1:
                reason = "交换机 LLDP 精确证据关联到多个站点，需人工处理。"
            elif (
                switch_identity_index is not None
                and _has_ac_lldp_switch_identity(resource)
                and _scope_token(resource.get("lldp_match_status"))
                not in {"conflict", "ambiguous", "multiple"}
            ):
                switch_match = switch_identity_index.resolve(resource)
                if switch_match.match_status == "ambiguous":
                    association_diagnostic = (
                        "switch_identity_ambiguous",
                        "SWITCH_IDENTITY_AMBIGUOUS",
                        "AC 侧 LLDP 交换机身份命中当前局点内多个设备，不能自动选择。",
                        "核对 LLDP system name、管理地址或 chassis ID，消除同局点重复身份后刷新。",
                    )
                elif switch_match.match_status != "matched":
                    association_diagnostic = (
                        "switch_not_found",
                        "SWITCH_NOT_FOUND",
                        "AC 侧 LLDP 已存在，但未在当前局点设备管理中找到唯一的上联交换机。",
                        "在设备管理中补充对应交换机，或核对 system name、管理地址和 chassis ID。",
                    )
                else:
                    resolved_plan_station_id = _switch_station_id(
                        switch_match,
                        station_names,
                        station_aliases,
                        station_node_uids,
                    )
                    if not resolved_plan_station_id:
                        association_diagnostic = (
                            "switch_data_incomplete",
                            "SWITCH_DATA_INCOMPLETE",
                            "已匹配上联交换机，但交换机缺少可唯一解析的当前局点归属站点。",
                            "补充交换机 station_id，或将交换机站点名称修正为当前局点内的唯一正式站点。",
                        )
                    else:
                        diagnostic_plan = plans_by_station.get(resolved_plan_station_id)
                        if diagnostic_plan is None:
                            plan_candidates = _plan_rows_for_station(
                                resolved_plan_station_id,
                                station_names,
                                plan_rows_by_station_name,
                            )
                            diagnostic_plan = plan_candidates[0] if plan_candidates else None
                            association_diagnostic = _missing_plan_diagnostic(
                                plan_candidates
                            )
                        else:
                            reference_id = f"runtime-lldp:{mac}"
                            if reference_id not in scope_references:
                                runtime_reference = EffectiveTracksideApReference(
                                    reference_id=reference_id,
                                    station_id=resolved_plan_station_id,
                                    station_name=station_names[resolved_plan_station_id],
                                    ap_name=str(resource.get("ap_name") or "").strip(),
                                    ap_mac=mac,
                                    ap_uuid=str(resource.get("ap_uuid") or "").strip(),
                                    operation_status="included",
                                    project_phase=context.project_phase,
                                    row={
                                        "_scope_binding_source": "ac_lldp_switch_identity",
                                        "switch_device_uuid": switch_match.device_uuid,
                                        "switch_match_method": switch_match.matched_by,
                                    },
                                )
                                scope_references[reference_id] = runtime_reference
                                eligible_identity_index.setdefault(
                                    ("mac", mac), set()
                                ).add(reference_id)
                            binding_source = "ac_lldp_switch_identity"
                            reason = ""
        online = is_fit_ap_online(resource)
        if online:
            online_resource_total += 1
        elif any(
            str(resource.get(field) or "").strip()
            for field in ("state", "state_raw", "state_display")
        ):
            offline_resource_total += 1
        else:
            unknown_resource_total += 1
        updated_at = max(
            updated_at,
            str(resource.get("updated_at") or resource.get("collected_at") or ""),
        )
        if not reference_id:
            if online:
                item_id = str(
                    resource.get("ap_uuid")
                    or resource.get("ap_mac")
                    or resource.get("ap_name")
                    or ""
                )
                runtime_station_text = str(
                    resource.get("site_name")
                    or resource.get("site")
                    or resource.get("extension_station_name")
                    or ""
                )
                if reason in {
                    "匹配到的轨旁 AP 资料不在当前有效范围。",
                    "AP 稳定身份匹配到多条资料，需人工处理。",
                }:
                    add_excluded(
                        TracksideApScopeExcludedItem(
                            source="fit_ap_online_excluded",
                            item_id=item_id,
                            device_name=str(resource.get("ap_name") or ""),
                            station_name=runtime_station_text,
                            operation_status=str(
                                resource.get("state")
                                or resource.get("state_raw")
                                or resource.get("state_display")
                                or ""
                            ),
                            reason=reason,
                            mac=normalize_mac(resource.get("ap_mac")) or "",
                        )
                    )
                else:
                    (
                        association_status,
                        reason_code,
                        diagnostic_reason,
                        suggested_action,
                    ) = association_diagnostic or _unmatched_online_diagnostics(
                        resource,
                        reason,
                        snapshot,
                        bool(runtime_station_rows),
                        len(runtime_station_index.get(normalize_mac(resource.get("ap_mac")) or "", set())),
                        normalize_mac(resource.get("ap_mac")) in runtime_station_master_missing_macs,
                    )
                    if association_status == "lldp_conflict_current" or "多个站点" in diagnostic_reason:
                        ambiguous_online_keys.add(_runtime_resource_key(resource))
                    add_unmatched(
                        _runtime_resource_key(resource),
                        TracksideApScopeUnmatchedOnlineItem(
                            source="fit_ap_online",
                            item_id=item_id,
                            ap_name=str(resource.get("ap_name") or ""),
                            mac=normalize_mac(resource.get("ap_mac")) or "",
                            ac_status=str(
                                resource.get("state_display")
                                or resource.get("state_raw")
                                or resource.get("state")
                                or ""
                            ),
                            runtime_station_text=runtime_station_text,
                            reason=diagnostic_reason,
                            suggested_action=suggested_action,
                            association_status=association_status,
                            reason_code=reason_code,
                            observed_association_status=(
                                "RESOLVED"
                                if switch_match is not None
                                and switch_match.match_status == "matched"
                                else "AMBIGUOUS"
                                if switch_match is not None
                                and switch_match.match_status == "ambiguous"
                                else "INSUFFICIENT_IDENTITY"
                                if association_status == "insufficient_lldp_identity"
                                else "NOT_FOUND"
                            ),
                            observed_switch_device_id=(
                                str(switch_match.device_uuid or "")
                                if switch_match is not None
                                else ""
                            ),
                            observed_switch_device_name=(
                                str(switch_match.device_name or "")
                                if switch_match is not None
                                else ""
                            ),
                            observed_port=str(
                                resource.get("lldp_neighbor_interface")
                                or resource.get("neighbor_interface")
                                or resource.get("lldp_local_interface")
                                or ""
                            ),
                            observed_match_method=(
                                str(switch_match.matched_by or "")
                                if switch_match is not None
                                else ""
                            ),
                            planning_status=(
                                "RESOLVED"
                                if diagnostic_plan is not None
                                else "MISSING"
                                if switch_match is not None
                                and switch_match.match_status == "matched"
                                else "NOT_EVALUATED"
                            ),
                            planned_switch_device_id=str(
                                (diagnostic_plan or {}).get("switch_device_id")
                                or (diagnostic_plan or {}).get("planned_switch_device_id")
                                or ""
                            ),
                            planned_switch_device_name=str(
                                (diagnostic_plan or {}).get("switch_device_name")
                                or (diagnostic_plan or {}).get("planned_switch_device_name")
                                or ""
                            ),
                            planned_port=str(
                                (diagnostic_plan or {}).get("port")
                                or (diagnostic_plan or {}).get("planned_port")
                                or ""
                            ),
                            fit_ap_collected_at=snapshot.fit_ap_collected_at,
                            lldp_collected_at=str(
                                resource.get("lldp_collected_at")
                                or resource.get("lldp_updated_at")
                                or snapshot.switch_lldp_collected_at
                                or ""
                            ),
                            lldp_candidate_count=len(runtime_station_index.get(normalize_mac(resource.get("ap_mac")) or "", set())),
                            ap_mac_raw=str(resource.get("ap_mac") or ""),
                            ap_mac_normalized=normalize_mac(resource.get("ap_mac")) or "",
                            planning_record_id=_plan_record_id(diagnostic_plan),
                            planning_station_name=str(
                                (diagnostic_plan or {}).get("station_name") or ""
                            ),
                            plan_station_id=(
                                resolved_plan_station_id
                                or str((diagnostic_plan or {}).get("station_id") or "")
                            ),
                            planning_match_method=(
                                "switch_station_id"
                                if diagnostic_plan is not None
                                else ""
                            ),
                            lldp_exists=(
                                _has_ac_lldp_switch_identity(resource)
                                or bool(runtime_station_index.get(normalize_mac(resource.get("ap_mac")) or "", set()))
                            ),
                            lldp_local_interface=str(
                                resource.get("lldp_local_interface") or ""
                            ),
                            lldp_remote_device_name=str(
                                resource.get("neighbor_device_name")
                                or resource.get("lldp_neighbor_name")
                                or ""
                            ),
                            lldp_system_name=str(
                                resource.get("lldp_system_name")
                                or resource.get("lldp_neighbor_name")
                                or ""
                            ),
                            lldp_management_ip=str(
                                resource.get("lldp_management_ip")
                                or resource.get("lldp_neighbor_ip")
                                or ""
                            ),
                            lldp_chassis_id=str(
                                resource.get("lldp_chassis_id")
                                or resource.get("lldp_neighbor_mac")
                                or ""
                            ),
                            switch_candidate_count=(
                                switch_match.candidate_count if switch_match else 0
                            ),
                            matched_switch_device_id=(
                                str(switch_match.device_uuid or "")
                                if switch_match
                                else ""
                            ),
                            switch_match_method=(
                                str(switch_match.matched_by or "")
                                if switch_match
                                else ""
                            ),
                            failure_stage=_failure_stage(association_status),
                            source_revisions={
                                "station_data_revision": snapshot.station_data_revision,
                                "ap_identity_revision": snapshot.ap_identity_revision,
                                "fit_ap_generation": snapshot.fit_ap_generation,
                                "switch_lldp_generation": snapshot.switch_lldp_generation,
                            },
                            snapshot_revision=_runtime_snapshot_revision(snapshot),
                            snapshot_created_at=max(
                                snapshot.fit_ap_collected_at,
                                snapshot.switch_lldp_collected_at,
                                snapshot.optical_collected_at,
                            ),
                        ),
                    )
            continue
        reference = scope_references[reference_id]
        enriched = {
            **resource,
            "_scope_reference_id": reference_id,
            "_scope_binding_source": binding_source,
            "station_id": reference.station_id,
            "site": reference.station_name,
            "site_name": reference.station_name,
        }
        current = matched_resources.get(reference_id)
        if current is None or _resource_preference_key(enriched) > _resource_preference_key(current):
            matched_resources[reference_id] = enriched
        for key in _identity_keys(resource):
            resource_identity_index[key].add(reference_id)
        if online:
            online_reference_ids.add(reference_id)

    resources = list(matched_resources.values())
    runtime_resources = list(runtime_resources_by_key.values())
    online_resource_total = sum(1 for resource in runtime_resources if is_fit_ap_online(resource))
    offline_resource_total = sum(
        1
        for resource in runtime_resources
        if not is_fit_ap_online(resource)
        and any(
            str(resource.get(field) or "").strip()
            for field in ("state", "state_raw", "state_display")
        )
    )
    unknown_resource_total = len(runtime_resources) - online_resource_total - offline_resource_total
    for key, values in resource_identity_index.items():
        eligible_identity_index.setdefault(key, set()).update(values)

    return EffectiveTracksideApScope(
        context=context,
        station_names=station_names,
        station_sort_orders=station_sort_orders,
        references=list(eligible.values()),
        resources=resources,
        runtime_resources=runtime_resources,
        plans_by_station=plans_by_station,
        online_reference_ids=online_reference_ids,
        excluded_items=excluded,
        unmatched_online_items=unmatched_online,
        fit_ap_resource_total_count=len(runtime_identity_keys),
        fit_ap_online_total_count=online_resource_total,
        fit_ap_offline_total_count=offline_resource_total,
        fit_ap_unknown_total_count=unknown_resource_total,
        excluded_device_total_count=len(excluded_keys),
        unmatched_online_total_count=len(unmatched_online_keys),
        ambiguous_online_total_count=len(ambiguous_online_keys),
        unmatched_status_counts=dict(unmatched_status_counts),
        updated_at=updated_at,
        _reference_by_id=scope_references,
        _identity_index=eligible_identity_index,
        _all_reference_by_id=all_references,
        _all_identity_index=all_identity_index,
        runtime_snapshot=snapshot,
    )


def _build_runtime_station_index(
    context: TracksideApScopeContext,
    station_names: Mapping[str, str],
    station_aliases: Mapping[str, set[str]],
    rows: Iterable[Mapping[str, object | None]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        station_id = str(row.get("station_id") or "").strip()
        mac = normalize_mac(row.get("ap_mac") or row.get("observed_ap_mac")) or ""
        if not mac:
            continue
        project_phase = str(row.get("project_phase") or "").strip()
        if context.project_phase and (
            not project_phase
            or _scope_token(project_phase) != _scope_token(context.project_phase)
        ):
            continue
        if station_id not in station_names:
            station_key = _station_key(
                row.get("device_station")
                or row.get("formal_station_name")
                or row.get("station_name")
            )
            candidates = station_aliases.get(station_key, set())
            station_id = next(iter(candidates)) if len(candidates) == 1 else ""
        if not station_id:
            continue
        result[mac].add(station_id)
    return result


def _build_runtime_station_master_missing_macs(
    context: TracksideApScopeContext,
    station_names: Mapping[str, str],
    station_aliases: Mapping[str, set[str]],
    rows: Iterable[Mapping[str, object | None]],
) -> set[str]:
    result: set[str] = set()
    for row in rows:
        project_phase = str(row.get("project_phase") or "").strip()
        if context.project_phase and (
            not project_phase
            or _scope_token(project_phase) != _scope_token(context.project_phase)
        ):
            continue
        mac = normalize_mac(row.get("ap_mac") or row.get("observed_ap_mac")) or ""
        if not mac:
            continue
        station_id = str(row.get("station_id") or "").strip()
        if station_id in station_names:
            continue
        station_key = _station_key(
            row.get("device_station")
            or row.get("formal_station_name")
            or row.get("station_name")
        )
        if len(station_aliases.get(station_key, set())) == 1:
            continue
        result.add(mac)
    return result


def _build_station_index(
    site_id: str,
    station_rows: list[dict[str, object | None]],
    plans: list[dict[str, object | None]],
) -> tuple[dict[str, str], dict[str, int], dict[str, set[str]], dict[str, str]]:
    station_names: dict[str, str] = {}
    station_sort_orders: dict[str, int] = {}
    station_aliases: dict[str, set[str]] = defaultdict(set)
    station_node_uids: dict[str, str] = {}

    for row in station_rows:
        if str(row.get("belong_type") or "") != _BASE_STATION:
            continue
        metadata = _metadata(row.get("raw_payload_json"))
        name = format_station_display_name(
            row.get("station_name"),
            source_station_value=metadata.get("source_station_value"),
            source_order_text=metadata.get("source_order_text"),
            sort_order=metadata.get("sort_order"),
            source_kind=metadata.get("source_kind"),
        )
        node_uid = str(metadata.get("node_uid") or "").strip()
        if not node_uid:
            identity = f"ap:{row.get('id')}"
            node_uid = str(
                uuid5(
                    NAMESPACE_URL,
                    f"netconsole:{site_id}:station:{identity}",
                )
            )
        station_id = str(
            row.get("station_id") or metadata.get("station_id") or ""
        ).strip() or _derived_station_id(node_uid)
        station_names[station_id] = name
        station_sort_orders[station_id] = _integer(metadata.get("sort_order"), 2**31 - 1)
        station_node_uids[node_uid] = station_id
        for value in (
            name,
            metadata.get("canonical_station_name"),
            metadata.get("source_station_value"),
        ):
            key = _station_key(value)
            if key:
                station_aliases[key].add(station_id)

    for index, plan in enumerate(plans):
        raw_station_id = str(plan.get("station_id") or "").strip()
        station_id = station_node_uids.get(raw_station_id, raw_station_id)
        if not station_id:
            continue
        if station_id in station_names:
            station_sort_orders.setdefault(
                station_id,
                _integer(plan.get("sequence_no"), index + 1),
            )
        if raw_station_id and raw_station_id != station_id:
            station_node_uids[raw_station_id] = station_id
    return station_names, station_sort_orders, station_aliases, station_node_uids


def _build_plan_index(
    plans: Iterable[Mapping[str, object | None]],
    station_names: Mapping[str, str],
    station_aliases: Mapping[str, set[str]],
    station_node_uids: Mapping[str, str],
) -> tuple[
    dict[str, dict[str, object | None]],
    dict[str, list[dict[str, object | None]]],
]:
    plans_by_station: dict[str, dict[str, object | None]] = {}
    plans_by_name: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    for raw in plans:
        plan = dict(raw)
        station_id, _reason = _resolve_plan_station_id(
            plan,
            station_aliases,
            station_node_uids,
        )
        if station_id and station_id in station_names:
            plans_by_station[station_id] = plan
        name_key = _station_key(plan.get("station_name"))
        if name_key:
            plans_by_name[name_key].append(plan)
    return plans_by_station, plans_by_name


def _has_ac_lldp_switch_identity(
    resource: Mapping[str, object | None],
) -> bool:
    stable_fields = (
        "switch_device_uuid",
        "neighbor_device_uuid",
        "lldp_neighbor_device_uuid",
        "lldp_neighbor_device_id",
        "lldp_neighbor_mac_normalized",
        "lldp_neighbor_mac",
        "neighbor_mac",
        "chassis_id",
        "lldp_chassis_id",
        "lldp_management_ip",
        "lldp_neighbor_ip",
        "neighbor_ip",
        "management_ip",
    )
    if any(str(resource.get(field) or "").strip() for field in stable_fields):
        return True
    return any(
        str(resource.get(field) or "").strip()
        and not is_generic_neighbor_name(resource.get(field))
        for field in (
            "lldp_neighbor_name",
            "lldp_neighbor",
            "neighbor_device_name",
            "neighbor_sysname",
            "lldp_system_name",
        )
    )


def _switch_station_id(
    match: NeighborMatchResult,
    station_names: Mapping[str, str],
    station_aliases: Mapping[str, set[str]],
    station_node_uids: Mapping[str, str],
) -> str:
    direct = str(match.station_id or "").strip()
    if direct:
        mapped = station_node_uids.get(direct, direct)
        return mapped if mapped in station_names else ""
    station_key = _station_key(match.station)
    candidates = station_aliases.get(station_key, set()) if station_key else set()
    return next(iter(candidates)) if len(candidates) == 1 else ""


def _plan_rows_for_station(
    station_id: str,
    station_names: Mapping[str, str],
    plans_by_name: Mapping[str, list[dict[str, object | None]]],
) -> list[dict[str, object | None]]:
    key = _station_key(station_names.get(station_id))
    return list(plans_by_name.get(key, ())) if key else []


def _missing_plan_diagnostic(
    plan_candidates: Iterable[Mapping[str, object | None]],
) -> tuple[str, str, str, str]:
    candidates = list(plan_candidates)
    if not candidates:
        return (
            "ap_plan_not_found",
            "AP_PLAN_NOT_FOUND",
            "已通过 LLDP 和交换机确定站点，但该站点没有轨旁 AP 规划记录。",
            "在 AP 规划维护中为该站点新增规划后刷新。",
        )
    if any(not str(plan.get("station_id") or "").strip() for plan in candidates):
        return (
            "plan_station_missing",
            "PLAN_STATION_MISSING",
            "找到同名 AP 规划记录，但规划未填写正式归属站点。",
            "在 AP 规划维护中选择当前局点的正式站点后刷新。",
        )
    return (
        "plan_station_invalid",
        "PLAN_STATION_INVALID",
        "找到同名 AP 规划记录，但规划引用的站点不属于当前局点有效站点。",
        "修正规划的 station_id，确保其指向当前局点内启用的正式站点。",
    )


def _plan_record_id(plan: Mapping[str, object | None] | None) -> str:
    if not plan:
        return ""
    return str(plan.get("id") or plan.get("plan_id") or "")


def _failure_stage(association_status: str) -> str:
    if association_status in {
        "switch_not_found",
        "insufficient_lldp_identity",
        "switch_identity_ambiguous",
        "switch_data_incomplete",
    }:
        return "switch_identity"
    if association_status in {
        "ap_plan_not_found",
        "plan_station_missing",
        "plan_station_invalid",
        "planning_missing",
        "station_master_missing",
    }:
        return "planning"
    if association_status.startswith("lldp_") or association_status == "ambiguous":
        return "lldp"
    return "unknown"


def _runtime_snapshot_revision(snapshot: TracksideApRuntimeSnapshot) -> str:
    return hashlib.sha256(
        json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _resolve_station_id(
    row: Mapping[str, object | None],
    metadata: Mapping[str, object],
    station_aliases: Mapping[str, set[str]],
    station_node_uids: Mapping[str, str],
) -> tuple[str, str]:
    direct = str(
        metadata.get("station_id")
        or metadata.get("station_node_uid")
        or metadata.get("station_uid")
        or row.get("station_id")
        or row.get("station_node_uid")
        or row.get("station_uid")
        or ""
    ).strip()
    if direct:
        mapped = station_node_uids.get(direct, direct)
        known = {value for values in station_aliases.values() for value in values}
        if mapped in known:
            return mapped, ""
        return "", "关联的 station_id 不属于当前有效站点。"
    station_key = _station_key(
        row.get("station_name")
        or metadata.get("canonical_station_name")
        or metadata.get("station_name")
    )
    candidates = station_aliases.get(station_key, set()) if station_key else set()
    if len(candidates) == 1:
        return next(iter(candidates)), ""
    if len(candidates) > 1:
        return "", "缺少有效 station_id，且精确站名对应多个正式站点。"
    return "", "缺少有效 station_id，且精确站名未命中当前正式站点。"


def _resolve_plan_station_id(
    plan: Mapping[str, object | None],
    station_aliases: Mapping[str, set[str]],
    station_node_uids: Mapping[str, str],
) -> tuple[str, str]:
    direct = str(plan.get("station_id") or "").strip()
    if direct:
        mapped = station_node_uids.get(direct, direct)
        known = {value for values in station_aliases.values() for value in values}
        if mapped in known:
            return mapped, ""
    return "", "规划缺少当前有效 station_id；站名不参与正式关联。"


def _reference_exclusion_reason(
    row: Mapping[str, object | None],
    metadata: Mapping[str, object],
    context: TracksideApScopeContext,
    station_reason: str,
    operation_status: str,
    project_phase: str,
    reference: EffectiveTracksideApReference,
) -> str:
    row_site_id = str(row.get("site_id") or metadata.get("site_id") or "").strip()
    if row_site_id and row_site_id != context.site_id:
        return "不属于当前局点。"
    row_project_id = str(metadata.get("project_id") or "").strip()
    if row_project_id and context.project_id and row_project_id != context.project_id:
        return "不属于当前项目。"
    row_line_name = str(row.get("line_name") or metadata.get("line_name") or "").strip()
    if (
        row_line_name
        and context.line_name
        and _scope_token(row_line_name) != _scope_token(context.line_name)
    ):
        return "不属于当前线路。"
    if _scope_token(operation_status) not in _IN_SERVICE_STATES:
        return "当前工作状态不是参与当前调试。"
    for key in ("enabled", "include_in_statistics", "participates_in_statistics"):
        if _is_false(metadata.get(key)):
            return "已明确设置为不参与当前统计。"
    scope_status = _scope_token(metadata.get("project_scope_status"))
    if scope_status in _EXCLUDED_SCOPE_STATES:
        return "已明确排除在当前项目范围外。"
    if context.project_phase:
        if not project_phase:
            return "缺少当前项目要求的建设阶段。"
        if _scope_token(project_phase) != _scope_token(context.project_phase):
            return "建设阶段与当前项目不一致。"
    if station_reason:
        return station_reason
    if not reference.ap_mac:
        return "缺少可用于关联的稳定 AP 身份。"
    return ""


def _group_reference_identities(
    references: Iterable[EffectiveTracksideApReference],
) -> list[list[str]]:
    items = list(references)
    parent = {reference.reference_id: reference.reference_id for reference in items}

    def find(reference_id: str) -> str:
        while parent[reference_id] != reference_id:
            parent[reference_id] = parent[parent[reference_id]]
            reference_id = parent[reference_id]
        return reference_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    identity_owner: dict[tuple[str, str], str] = {}
    for reference in items:
        stable_keys = [
            key
            for key in _reference_identity_keys(reference)
            if key[0] in {"uuid", "mac"}
        ]
        for key in stable_keys:
            owner = identity_owner.setdefault(key, reference.reference_id)
            union(owner, reference.reference_id)

    grouped: dict[str, list[str]] = defaultdict(list)
    for reference in items:
        grouped[find(reference.reference_id)].append(reference.reference_id)
    return [reference_ids for reference_ids in grouped.values() if len(reference_ids) > 1]


def _build_identity_index(
    references: Iterable[EffectiveTracksideApReference],
    aliases: Mapping[str, str] | None = None,
) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for reference in references:
        reference_id = (aliases or {}).get(reference.reference_id, reference.reference_id)
        for key in _reference_identity_keys(reference):
            result[key].add(reference_id)
    return result


def _match_resource_reference(
    resource: Mapping[str, object | None],
    all_references: Mapping[str, EffectiveTracksideApReference],
    all_identity_index: Mapping[tuple[str, str], set[str]],
    eligible: Mapping[str, EffectiveTracksideApReference],
    aliases: Mapping[str, str],
) -> tuple[str, str]:
    direct = _reference_id(resource.get("extension_id"))
    if direct in all_references:
        direct = aliases.get(direct, direct)
        if direct in eligible:
            return direct, ""
        return "", "匹配到的轨旁 AP 资料不在当前有效范围。"
    for key in _identity_keys(resource):
        candidates = all_identity_index.get(key, set())
        if len(candidates) == 1:
            reference_id = next(iter(candidates))
            if reference_id in eligible:
                return reference_id, ""
            return "", "匹配到的轨旁 AP 资料不在当前有效范围。"
        if len(candidates) > 1:
            return "", "AP 稳定身份匹配到多条资料，需人工处理。"
    return "", _BASE_DATA_MISSING_REASON


def _unmatched_online_diagnostics(
    resource: Mapping[str, object | None],
    reason: str,
    snapshot: TracksideApRuntimeSnapshot | None = None,
    has_runtime_rows: bool = False,
    candidate_count: int = 0,
    station_master_missing: bool = False,
) -> tuple[str, str, str, str]:
    """Explain why an online AP stays unresolved without weakening identity rules."""

    lldp_status = _scope_token(resource.get("lldp_match_status"))
    lldp_names = (
        resource.get("lldp_neighbor_name")
        or resource.get("lldp_neighbor")
        or resource.get("neighbor_device_name")
        or resource.get("neighbor_sysname")
        or resource.get("lldp_system_name")
    )
    if lldp_names and is_generic_neighbor_name(lldp_names) and not _has_ac_lldp_switch_identity(resource):
        return (
            "insufficient_lldp_identity",
            "INSUFFICIENT_LLDP_IDENTITY",
            "LLDP 仅提供通用交换机名称，缺少可唯一匹配的 chassis、管理地址或系统名。",
            "重新采集包含交换机 chassis ID 或管理地址的 LLDP，并核对当前局点范围。",
        )
    if lldp_status == "conflict":
        return (
            "lldp_conflict_current",
            "LLDP_CONFLICT_CURRENT",
            "AC 侧 LLDP 结果冲突，且未发现当前车站交换机的精确 AP MAC 证据。",
            "重新采集对应车站交换机 LLDP，确认 AP MAC 唯一归属；或补充轨旁 AP 基础资料 MAC 后重新刷新。",
        )
    if lldp_status in {"ambiguous", "multiple"}:
        return (
            "ambiguous",
            "LLDP_AMBIGUOUS",
            "AC 侧 LLDP 结果关联到多个候选，且未发现唯一车站交换机 AP MAC 证据，需人工处理。",
            "核对车站交换机 station_id 与 LLDP 邻居 MAC，消除多候选后重新刷新。",
        )
    if "多个站点" in reason:
        return (
            "ambiguous",
            "LLDP_STATION_AMBIGUOUS",
            reason,
            "检查车站交换机 station_id 与 LLDP 邻居 MAC 后重新刷新。",
        )
    if snapshot is not None and snapshot.snapshot_status == "lldp_stale":
        return (
            "lldp_snapshot_stale",
            "LLDP_SNAPSHOT_STALE",
            "FIT-AP 已在线，但当前车站交换机 LLDP 快照早于 FIT-AP，等待 LLDP 同步。",
            "完成车站交换机 LLDP 采集后刷新当前拓扑。",
        )
    if candidate_count > 1:
        return (
            "lldp_conflict_current",
            "LLDP_CONFLICT_CURRENT",
            "当前车站交换机 LLDP 对同一 AP 存在多个站点候选，需人工处理。",
            "核对当前完整 LLDP 快照中的站点和接口后重新刷新。",
        )
    if station_master_missing:
        return (
            "station_master_missing",
            "STATION_MASTER_MISSING",
            "当前 LLDP 已发现该 AP，但对端交换机没有可用的正式站点主数据。",
            "补充交换机 station_id 或站点主数据后重新刷新当前拓扑。",
        )
    if has_runtime_rows:
        return (
            "lldp_exact_match_pending",
            "LLDP_EXACT_MATCH_PENDING",
            "当前车站交换机 LLDP 尚未发现该 AP 的精确 MAC 记录，等待同步。",
            "完成车站交换机 LLDP 采集后刷新当前拓扑。",
        )
    return (
        "planning_missing",
        "BASE_DATA_MISSING",
        reason or _BASE_DATA_MISSING_REASON,
        "可按需补充轨旁 AP 基础资料 MAC，以完善站点和工程属性。",
    )


def _excluded_reference(
    reference: EffectiveTracksideApReference,
    reason: str,
) -> TracksideApScopeExcludedItem:
    return TracksideApScopeExcludedItem(
        source="trackside_ap_reference",
        item_id=reference.reference_id,
        device_name=reference.ap_name,
        station_name=reference.station_name,
        operation_status=reference.operation_status,
        project_phase=reference.project_phase,
        reason=reason,
        mac=reference.ap_mac,
    )


def _reference_identity_keys(
    reference: EffectiveTracksideApReference,
) -> list[tuple[str, str]]:
    return [("mac", reference.ap_mac)] if reference.ap_mac else []


def _identity_keys(row: Mapping[str, object | None]) -> list[tuple[str, str]]:
    mac = normalize_mac(row.get("ap_mac") or row.get("mac"))
    return [("mac", mac)] if mac else []


def _runtime_resource_key(row: Mapping[str, object | None]) -> tuple[str, str]:
    """Return one stable key for de-duplicating the same AP reported by ACs."""

    for key in _identity_keys(row):
        if key[0] == "mac":
            return key
    ac_uuid = _text_key(row.get("ac_device_uuid") or row.get("device_uuid"))
    ap_id = _text_key(row.get("ap_id") or row.get("apid"))
    if ac_uuid and ap_id:
        return "apid", f"{ac_uuid}:{ap_id}"
    fallback = _text_key(
        row.get("id")
        or row.get("resource_id")
        or row.get("extension_id")
        or row.get("source_ref")
    )
    return "row", fallback or hashlib.sha1(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _resource_preference_key(row: Mapping[str, object | None]) -> tuple[int, str]:
    """Prefer the freshest runtime copy when multiple ACs report one AP."""

    return (
        int(bool(is_fit_ap_online(row))),
        str(row.get("updated_at") or row.get("collected_at") or ""),
    )


def _metadata(value: object) -> dict[str, object]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _reference_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith("ap:") else f"ap:{text}"


def _derived_station_id(node_uid: str) -> str:
    digest = hashlib.sha1(node_uid.encode("utf-8")).hexdigest()[:12]
    return f"station:{digest}"


def _station_key(value: object) -> str:
    return canonical_station_name(value).strip().casefold()


def _scope_token(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _text_key(value: object) -> str:
    return _scope_token(value)


def _name_key(value: object) -> str:
    text = _scope_token(value)
    return re.sub(r"[\s_\-:./\\|,;，。；、]+", "", text)


def _is_false(value: object) -> bool:
    return value is False or _scope_token(value) in _FALSE_VALUES


def _integer(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "EffectiveTracksideApReference",
    "EffectiveTracksideApScope",
    "TracksideApScopeContext",
    "TracksideApScopeExcludedItem",
    "TracksideApScopeUnmatchedOnlineItem",
    "resolve_effective_trackside_ap_scope",
    "resolve_effective_trackside_ap_scope_from_database",
]
