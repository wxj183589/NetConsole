from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.services.ap_online_overview import is_fit_ap_online
from netconsole.services.rail_transit.station_source_utils import (
    canonical_station_name,
    format_station_display_name,
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

    def to_dict(self) -> dict[str, str]:
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

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "item_id": self.item_id,
            "ap_name": self.ap_name,
            "mac": self.mac,
            "ac_status": self.ac_status,
            "runtime_station_text": self.runtime_station_text,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
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
    plans_by_station: dict[str, dict[str, object | None]]
    online_reference_ids: set[str]
    excluded_items: list[TracksideApScopeExcludedItem]
    unmatched_online_items: list[TracksideApScopeUnmatchedOnlineItem] = field(
        default_factory=list
    )
    fit_ap_resource_total_count: int = 0
    excluded_device_total_count: int | None = None
    unmatched_online_total_count: int | None = None
    ambiguous_online_total_count: int = 0
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
    def fit_ap_unmatched_online_count(self) -> int:
        return (
            self.unmatched_online_total_count
            if self.unmatched_online_total_count is not None
            else len(self.unmatched_online_items)
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
            self.station_scope_ids,
            key=lambda value: (
                self.station_sort_orders.get(value, 2**31 - 1),
                self.station_names.get(value, ""),
            ),
        ):
            plan = self.plans_by_station.get(station_id)
            planning_missing = plan is None
            planned = int((plan or {}).get("ap_count") or 0)
            actual = online_by_station.get(station_id, 0)
            status = "normal"
            warning = ""
            if planning_missing:
                status = "planning_missing"
                warning = "缺少规划资料。"
            elif planned == 0 and actual > 0:
                status = "unplanned_online"
                warning = "存在未纳入规划的在线 AP。"
            elif actual > planned:
                status = "over_planned"
                warning = "实际上线 AP 数量超过当前规划数量，请检查规划资料或 AP 归属关系。"
            count_anomaly = status in {"unplanned_online", "over_planned"} or (
                planning_missing and actual > 0
            )
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
        online_total = sum(int(row["actual_online_count"] or 0) for row in station_rows)
        total_anomaly = any(bool(row.get("count_anomaly")) for row in station_rows)
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
                "remark": "统计范围存在数量异常，请查看分站状态。" if total_anomaly else "",
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
    detail_limit: int | None = None,
) -> EffectiveTracksideApScope:
    all_station_rows = [dict(row) for row in station_rows]
    plans = [dict(row) for row in plan_rows]
    resources_input = [dict(row) for row in resource_rows]
    station_names, station_sort_orders, station_aliases, station_node_uids = (
        _build_station_index(context.site_id, all_station_rows, plans)
    )
    runtime_station_index = _build_runtime_station_index(
        context,
        station_names,
        runtime_station_rows or (),
    )
    excluded: list[TracksideApScopeExcludedItem] = []
    unmatched_online: list[TracksideApScopeUnmatchedOnlineItem] = []
    excluded_keys: set[tuple[str, str]] = set()
    unmatched_online_keys: set[tuple[str, str]] = set()
    ambiguous_online_keys: set[tuple[str, str]] = set()

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
    matched_resources: dict[str, dict[str, object | None]] = {}
    for resource in resources_input:
        runtime_identity_keys.add(_runtime_resource_key(resource))
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
        online = is_fit_ap_online(resource)
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
                    diagnostic_reason, suggested_action = _unmatched_online_diagnostics(
                        resource,
                        reason,
                    )
                    if "多个站点" in diagnostic_reason:
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
    for key, values in resource_identity_index.items():
        eligible_identity_index.setdefault(key, set()).update(values)

    plans_by_station: dict[str, dict[str, object | None]] = {}
    station_scope_ids = set(station_names)
    for plan in plans:
        station_id, _reason = _resolve_plan_station_id(
            plan,
            station_aliases,
            station_node_uids,
        )
        if station_id and station_id in station_scope_ids:
            plans_by_station[station_id] = plan

    return EffectiveTracksideApScope(
        context=context,
        station_names=station_names,
        station_sort_orders=station_sort_orders,
        references=list(eligible.values()),
        resources=resources,
        plans_by_station=plans_by_station,
        online_reference_ids=online_reference_ids,
        excluded_items=excluded,
        unmatched_online_items=unmatched_online,
        fit_ap_resource_total_count=len(runtime_identity_keys),
        excluded_device_total_count=len(excluded_keys),
        unmatched_online_total_count=len(unmatched_online_keys),
        ambiguous_online_total_count=len(ambiguous_online_keys),
        updated_at=updated_at,
        _reference_by_id=scope_references,
        _identity_index=eligible_identity_index,
        _all_reference_by_id=all_references,
        _all_identity_index=all_identity_index,
    )


def _build_runtime_station_index(
    context: TracksideApScopeContext,
    station_names: Mapping[str, str],
    rows: Iterable[Mapping[str, object | None]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        station_id = str(row.get("station_id") or "").strip()
        mac = normalize_mac(row.get("ap_mac") or row.get("observed_ap_mac")) or ""
        if not station_id or station_id not in station_names or not mac:
            continue
        project_phase = str(row.get("project_phase") or "").strip()
        if context.project_phase and (
            not project_phase
            or _scope_token(project_phase) != _scope_token(context.project_phase)
        ):
            continue
        result[mac].add(station_id)
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
    del station_aliases
    return "", "缺少有效 station_id；历史站名仅供诊断，不能建立正式关联。"


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
) -> tuple[str, str]:
    """Explain why an online AP stays unresolved without weakening identity rules."""

    lldp_status = _scope_token(resource.get("lldp_match_status"))
    if lldp_status == "conflict":
        return (
            "AC 侧 LLDP 结果冲突，且未发现当前车站交换机的精确 AP MAC 证据。",
            "重新采集对应车站交换机 LLDP，确认 AP MAC 唯一归属；或补充轨旁 AP 基础资料 MAC 后重新刷新。",
        )
    if lldp_status in {"ambiguous", "multiple"}:
        return (
            "AC 侧 LLDP 结果关联到多个候选，且未发现唯一车站交换机 AP MAC 证据，需人工处理。",
            "核对车站交换机 station_id 与 LLDP 邻居 MAC，消除多候选后重新刷新。",
        )
    if "多个站点" in reason:
        return (
            reason,
            "检查车站交换机 station_id 与 LLDP 邻居 MAC 后重新刷新。",
        )
    return (
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
