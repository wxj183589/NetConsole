from __future__ import annotations

import hashlib
import ipaddress
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping
from uuid import uuid4


LINE_SINGLE = "line_single"
STATION_INDEPENDENT = "station_independent"
STATION_GROUPED = "station_grouped"
PLANNING_MODES = {LINE_SINGLE, STATION_INDEPENDENT, STATION_GROUPED}
DEFAULT_ALLOCATION_STRATEGY = "station_then_point"
REALLOCATION_ONLY_UNLOCKED = "only_unlocked"
REALLOCATION_ALL = "all"


@dataclass(frozen=True)
class PlanningIssue:
    code: str
    severity: str
    message: str
    blocking: bool
    field_name: str = ""
    group_id: str = ""
    station_id: str = ""
    ap_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def stable_legacy_station_id(station_name: object) -> str:
    normalized = str(station_name or "").strip().casefold()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"legacy-station:{digest}"


def station_inputs(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for fallback_sequence, row in enumerate(rows):
        if not bool(row.get("enabled", True)):
            continue
        station_id = str(row.get("id") or row.get("station_id") or "").strip()
        station_name = str(row.get("name") or row.get("station_name") or "").strip()
        if not station_id:
            station_id = stable_legacy_station_id(station_name)
        raw_sequence = (
            row.get("sort_order")
            if row.get("sort_order") not in (None, "")
            else row.get("station_sequence")
        )
        sequence = (
            fallback_sequence if raw_sequence in (None, "") else int(raw_sequence)
        )
        result.append(
            {
                "station_id": station_id,
                "station_name": station_name,
                "station_sequence": sequence,
                "ap_count": max(0, int(row.get("ap_count") or 0)),
            }
        )
    result.sort(
        key=lambda item: (
            int(item["station_sequence"]),
            _natural_key(item["station_name"]),
            str(item["station_id"]),
        )
    )
    for sequence, item in enumerate(result):
        item["station_sequence"] = sequence
    return result


def normalize_plan_draft(
    raw: Mapping[str, Any],
    stations: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    station_rows = station_inputs(stations)
    by_id = {str(row["station_id"]): row for row in station_rows}
    by_name = {
        str(row["station_name"]).casefold(): row
        for row in station_rows
        if str(row["station_name"])
    }
    planning_raw = (
        raw.get("planning") if isinstance(raw.get("planning"), Mapping) else raw
    )
    mode = str((planning_raw or {}).get("planning_mode") or STATION_INDEPENDENT).strip()
    auto_count = int((planning_raw or {}).get("auto_group_station_count") or 1)
    revision = int((planning_raw or {}).get("revision") or 0)
    planning = {
        "line_id": str((planning_raw or {}).get("line_id") or "current").strip()
        or "current",
        "planning_mode": mode,
        "auto_group_station_count": auto_count,
        "address_allocation_strategy": str(
            (planning_raw or {}).get("address_allocation_strategy")
            or DEFAULT_ALLOCATION_STRATEGY
        ).strip()
        or DEFAULT_ALLOCATION_STRATEGY,
        "revision": revision,
        "updated_at": str((planning_raw or {}).get("updated_at") or ""),
    }
    normalized_groups: list[dict[str, object]] = []
    raw_groups = raw.get("groups") or []
    if not isinstance(raw_groups, list):
        raise ValueError("VLAN 组数据格式无效")
    for fallback_sequence, group_raw in enumerate(raw_groups):
        if not isinstance(group_raw, Mapping):
            continue
        group_id = str(group_raw.get("group_id") or f"vlan-group-{uuid4().hex}").strip()
        members: list[dict[str, object]] = []
        raw_members = group_raw.get("members") or []
        if not isinstance(raw_members, list):
            raise ValueError("VLAN 组成员格式无效")
        for fallback_member_sequence, member_raw in enumerate(raw_members):
            if not isinstance(member_raw, Mapping):
                continue
            station_id = str(member_raw.get("station_id") or "").strip()
            station_name = str(member_raw.get("station_name") or "").strip()
            station = by_id.get(station_id) or by_name.get(station_name.casefold())
            if station is not None:
                station_id = str(station["station_id"])
                station_name = str(station["station_name"])
                station_sequence = int(station["station_sequence"])
                ap_count = int(station["ap_count"])
            else:
                station_id = station_id or stable_legacy_station_id(station_name)
                station_sequence = int(
                    member_raw.get("station_sequence")
                    if member_raw.get("station_sequence") not in (None, "")
                    else fallback_member_sequence
                )
                ap_count = max(0, int(member_raw.get("ap_count") or 0))
            members.append(
                {
                    "station_id": station_id,
                    "station_name": station_name,
                    "station_sequence": station_sequence,
                    "ap_count": ap_count,
                }
            )
        members.sort(
            key=lambda item: (
                int(item["station_sequence"]),
                _natural_key(item["station_name"]),
            )
        )
        prefix = _optional_int(
            group_raw.get("prefix_length")
            if group_raw.get("prefix_length") not in (None, "")
            else group_raw.get("mask_length")
        )
        management_vlan = _optional_int(
            group_raw.get("management_vlan")
            if group_raw.get("management_vlan") not in (None, "")
            else group_raw.get("ap_management_vlan")
        )
        network_address = str(
            group_raw.get("network_address") or group_raw.get("subnet") or ""
        ).strip()
        ap_start_ip = str(
            group_raw.get("ap_start_ip") or group_raw.get("ap_start_address") or ""
        ).strip()
        network = _network(network_address, prefix, ap_start_ip)
        if network is not None:
            network_address = str(network.network_address)
            prefix = network.prefixlen
        subnet_mask = (
            str(network.netmask)
            if network is not None
            else str(group_raw.get("subnet_mask") or "").strip()
        )
        normalized_groups.append(
            {
                "group_id": group_id,
                "line_id": str(group_raw.get("line_id") or planning["line_id"]),
                "group_code": str(
                    group_raw.get("group_code") or f"G{fallback_sequence + 1:03d}"
                ).strip(),
                "group_name": str(
                    group_raw.get("group_name") or f"VLAN 组 {fallback_sequence + 1}"
                ).strip(),
                "sequence": int(
                    group_raw.get("sequence")
                    if group_raw.get("sequence") not in (None, "")
                    else fallback_sequence
                ),
                "management_vlan": management_vlan,
                "legacy_management_vlans": str(
                    group_raw.get("legacy_management_vlans") or ""
                ).strip(),
                "network_address": network_address,
                "prefix_length": prefix,
                "subnet_mask": subnet_mask,
                "default_gateway": str(
                    group_raw.get("default_gateway")
                    or group_raw.get("ap_gateway")
                    or ""
                ).strip(),
                "ap_start_ip": ap_start_ip,
                "ap_end_ip": str(group_raw.get("ap_end_ip") or "").strip(),
                "address_allocation_strategy": str(
                    group_raw.get("address_allocation_strategy")
                    or planning["address_allocation_strategy"]
                ).strip()
                or DEFAULT_ALLOCATION_STRATEGY,
                "notes": str(
                    group_raw.get("notes") or group_raw.get("remark") or ""
                ).strip(),
                "created_at": str(group_raw.get("created_at") or ""),
                "updated_at": str(group_raw.get("updated_at") or ""),
                "members": members,
            }
        )
    normalized_groups.sort(
        key=lambda item: (int(item["sequence"]), str(item["group_code"]))
    )
    for sequence, group in enumerate(normalized_groups):
        group["sequence"] = sequence
    assignments = _normalize_assignments(raw.get("assignments"), normalized_groups)
    allocations = _normalize_allocations(raw.get("allocations"), normalized_groups)
    return {
        "planning": planning,
        "groups": normalized_groups,
        "assignments": assignments,
        "allocations": allocations,
    }


def auto_group_draft(
    *,
    stations: Iterable[Mapping[str, Any]],
    planning_mode: str,
    auto_group_station_count: int = 1,
    current_draft: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    station_rows = station_inputs(stations)
    if planning_mode not in PLANNING_MODES:
        raise ValueError("AP 管理 VLAN 规划方式无效")
    if planning_mode == STATION_GROUPED and auto_group_station_count not in {
        1,
        2,
        3,
        4,
    }:
        raise ValueError("按站点分组时每组站点数量只能为 1～4")
    current = normalize_plan_draft(current_draft or {}, station_rows)
    current_groups = list(current["groups"])
    by_members = {
        tuple(str(member["station_id"]) for member in group["members"]): group
        for group in current_groups
    }
    by_station: dict[str, Mapping[str, Any]] = {}
    for group in current_groups:
        for member in group["members"]:
            by_station[str(member["station_id"])] = group
    if planning_mode == LINE_SINGLE:
        chunks = [station_rows] if station_rows else []
    elif planning_mode == STATION_INDEPENDENT:
        chunks = [[station] for station in station_rows]
    else:
        chunks = [
            station_rows[index : index + auto_group_station_count]
            for index in range(0, len(station_rows), auto_group_station_count)
        ]
    groups: list[dict[str, object]] = []
    for sequence, chunk in enumerate(chunks):
        member_key = tuple(str(row["station_id"]) for row in chunk)
        exact = by_members.get(member_key)
        seed = exact or (by_station.get(member_key[0]) if member_key else None)
        group = _new_group_from_seed(seed, sequence)
        group["members"] = [dict(row) for row in chunk]
        if exact is None:
            group["group_id"] = f"vlan-group-{uuid4().hex}"
            group["group_code"] = f"G{sequence + 1:03d}"
            group["group_name"] = _default_group_name(chunk, sequence)
        groups.append(group)
    return normalize_plan_draft(
        {
            "planning": {
                **dict(current["planning"]),
                "planning_mode": planning_mode,
                "auto_group_station_count": (
                    auto_group_station_count if planning_mode == STATION_GROUPED else 1
                ),
            },
            "groups": groups,
            "assignments": list(current["assignments"]),
            "allocations": list(current["allocations"]),
        },
        station_rows,
    )


def validate_plan(
    draft: Mapping[str, Any],
    *,
    stations: Iterable[Mapping[str, Any]],
    aps: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, object]]:
    station_rows = station_inputs(stations)
    normalized = normalize_plan_draft(draft, station_rows)
    planning = normalized["planning"]
    groups = list(normalized["groups"])
    issues: list[PlanningIssue] = []
    mode = str(planning["planning_mode"])
    if mode not in PLANNING_MODES:
        issues.append(
            _error(
                "PLANNING_MODE_INVALID", "AP 管理 VLAN 规划方式无效", "planning_mode"
            )
        )
    auto_count = int(planning["auto_group_station_count"])
    if mode == STATION_GROUPED and auto_count not in {1, 2, 3, 4}:
        issues.append(
            _error(
                "AUTO_GROUP_SIZE_INVALID",
                "每组站点数量只能为 1～4",
                "auto_group_station_count",
            )
        )
    if station_rows and not groups:
        issues.append(
            _error(
                "VLAN_GROUP_REQUIRED", "当前线路存在站点，至少需要一个 AP 管理 VLAN 组"
            )
        )

    expected_ids = [str(row["station_id"]) for row in station_rows]
    position = {station_id: index for index, station_id in enumerate(expected_ids)}
    memberships: list[tuple[str, str]] = []
    for group in groups:
        group_id = str(group["group_id"])
        members = list(group["members"])
        if not members:
            issues.append(
                _error(
                    "VLAN_GROUP_EMPTY",
                    f"{group['group_name']} 没有站点",
                    "members",
                    group_id=group_id,
                )
            )
        if mode == STATION_GROUPED and len(members) > 4:
            issues.append(
                _error(
                    "VLAN_GROUP_TOO_LARGE",
                    f"{group['group_name']} 包含 {len(members)} 个站点，分组模式最多 4 个",
                    "members",
                    group_id=group_id,
                )
            )
        if mode == STATION_INDEPENDENT and len(members) != 1:
            issues.append(
                _error(
                    "INDEPENDENT_GROUP_SIZE_INVALID",
                    f"{group['group_name']} 在每站独立模式下必须只包含一个站点",
                    "members",
                    group_id=group_id,
                )
            )
        member_positions: list[int] = []
        for member in members:
            station_id = str(member["station_id"])
            memberships.append((station_id, group_id))
            if station_id in position:
                member_positions.append(position[station_id])
            elif station_rows:
                issues.append(
                    _error(
                        "STATION_MEMBER_UNKNOWN",
                        f"{group['group_name']} 引用了不存在的站点“{member['station_name']}”",
                        "members",
                        group_id=group_id,
                        station_id=station_id,
                    )
                )
        if member_positions and member_positions != list(
            range(min(member_positions), max(member_positions) + 1)
        ):
            issues.append(
                _error(
                    "VLAN_GROUP_NOT_CONTIGUOUS",
                    f"{group['group_name']} 的站点范围不连续",
                    "members",
                    group_id=group_id,
                )
            )
        issues.extend(_validate_group_network(group))

    counts = Counter(station_id for station_id, _group_id in memberships)
    for station in station_rows:
        station_id = str(station["station_id"])
        if counts[station_id] == 0:
            issues.append(
                _error(
                    "STATION_UNASSIGNED",
                    f"站点“{station['station_name']}”尚未分配 VLAN 组",
                    "members",
                    station_id=station_id,
                )
            )
        elif counts[station_id] > 1:
            issues.append(
                _error(
                    "STATION_ASSIGNED_MULTIPLE_GROUPS",
                    f"站点“{station['station_name']}”重复归属 {counts[station_id]} 个 VLAN 组",
                    "members",
                    station_id=station_id,
                )
            )
    if mode == LINE_SINGLE and station_rows and len(groups) != 1:
        issues.append(
            _error(
                "LINE_SINGLE_GROUP_COUNT_INVALID",
                "全线统一 VLAN 模式必须且只能有一个 VLAN 组",
            )
        )

    issues.extend(_cross_group_warnings(groups))
    allocations, allocation_issues, _derived_assignments = allocate_addresses(
        normalized,
        stations=station_rows,
        aps=aps,
        reallocation_policy=REALLOCATION_ONLY_UNLOCKED,
    )
    issues.extend(PlanningIssue(**issue) for issue in allocation_issues)
    planned_ips = [
        str(row.get("planned_ip") or "")
        for row in allocations
        if str(row.get("planned_ip") or "")
    ]
    duplicates = {ip for ip, count in Counter(planned_ips).items() if count > 1}
    for duplicate in sorted(duplicates):
        issues.append(
            _error("AP_IP_DUPLICATE", f"AP 规划地址 {duplicate} 重复", "planned_ip")
        )
    return [issue.to_dict() for issue in _dedupe_issues(issues)]


def allocate_addresses(
    draft: Mapping[str, Any],
    *,
    stations: Iterable[Mapping[str, Any]],
    aps: Iterable[Mapping[str, Any]],
    reallocation_policy: str = REALLOCATION_ONLY_UNLOCKED,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    if reallocation_policy not in {REALLOCATION_ONLY_UNLOCKED, REALLOCATION_ALL}:
        raise ValueError("地址重算策略无效")
    station_rows = station_inputs(stations)
    normalized = normalize_plan_draft(draft, station_rows)
    groups = {str(group["group_id"]): group for group in normalized["groups"]}
    group_by_station = {
        str(member["station_id"]): group
        for group in normalized["groups"]
        for member in group["members"]
    }
    station_by_name = {str(row["station_name"]).casefold(): row for row in station_rows}
    assignment_by_target = {
        str(row["target_id"]): row for row in normalized["assignments"]
    }
    existing_by_ap = {str(row["ap_id"]): row for row in normalized["allocations"]}
    ap_rows = [dict(row) for row in aps]
    resolved: list[tuple[dict[str, Any], Mapping[str, Any], str, str]] = []
    derived_assignments: list[dict[str, object]] = []
    issues: list[PlanningIssue] = []
    for ap in ap_rows:
        ap_id = str(ap.get("id") or ap.get("ap_id") or "").strip()
        group, source, station_id = _effective_group_for_ap(
            ap,
            groups=groups,
            group_by_station=group_by_station,
            station_by_name=station_by_name,
            assignment_by_target=assignment_by_target,
        )
        if group is None:
            issues.append(
                _error(
                    "AP_VLAN_GROUP_UNRESOLVED",
                    f"AP“{ap.get('name') or ap.get('ap_name') or ap_id}”无法获得有效 VLAN 组",
                    "group_id",
                    ap_id=ap_id,
                )
            )
            continue
        if source == "interval_start_default" and ap_id not in assignment_by_target:
            derived_assignments.append(
                {
                    "assignment_id": f"assignment-{uuid4().hex}",
                    "assignment_type": "interval_default",
                    "target_id": ap_id,
                    "group_id": str(group["group_id"]),
                    "source": source,
                    "updated_at": "",
                }
            )
        resolved.append((ap, group, source, station_id))

    reserved_ips: set[str] = set()
    for ap, _group, _source, _station_id in resolved:
        existing = existing_by_ap.get(str(ap.get("id") or ap.get("ap_id") or ""))
        if (
            existing
            and reallocation_policy == REALLOCATION_ONLY_UNLOCKED
            and bool(existing.get("is_locked") or existing.get("is_manual"))
            and str(existing.get("planned_ip") or "")
        ):
            reserved_ips.add(str(existing["planned_ip"]))

    by_group: dict[str, list[tuple[dict[str, Any], Mapping[str, Any], str, str]]] = {}
    station_sequence = {
        str(row["station_id"]): int(row["station_sequence"]) for row in station_rows
    }

    def allocation_station_sequence(
        item: tuple[dict[str, Any], Mapping[str, Any], str, str],
    ) -> int:
        if item[3]:
            return station_sequence.get(item[3], 10**9)
        start_name = str(
            item[0].get("section_start_station")
            or (item[0].get("base_metadata") or {}).get("section_start_station")
            or ""
        ).strip()
        start_station = station_by_name.get(start_name.casefold())
        return (
            station_sequence.get(str(start_station["station_id"]), 10**9)
            if start_station is not None
            else 10**9
        )

    for item in resolved:
        by_group.setdefault(str(item[1]["group_id"]), []).append(item)
    allocations: list[dict[str, object]] = []
    for group_id, group_items in by_group.items():
        group = groups[group_id]
        network = _network(
            group.get("network_address"),
            _optional_int(group.get("prefix_length")),
            group.get("ap_start_ip"),
        )
        start_ip = _address(group.get("ap_start_ip"))
        if network is None or start_ip is None:
            for ap, _group, _source, _station_id in group_items:
                issues.append(
                    _error(
                        "GROUP_ADDRESS_CONFIG_INCOMPLETE",
                        f"{group['group_name']} 缺少可用的网段、掩码或 AP 起始地址",
                        "ap_start_ip",
                        group_id=group_id,
                        ap_id=str(ap.get("id") or ""),
                    )
                )
            continue
        gateway = _address(group.get("default_gateway"))
        blocked = {
            str(network.network_address),
            str(network.broadcast_address),
            *(str(value) for value in (gateway,) if value is not None),
            *reserved_ips,
        }
        candidates = _candidate_addresses(network, start_ip, blocked)
        group_items.sort(
            key=lambda item: (
                allocation_station_sequence(item),
                _natural_key(item[0].get("point_code") or item[0].get("ap_point_code")),
                _natural_key(item[0].get("name") or item[0].get("ap_name")),
                str(item[0].get("id") or item[0].get("ap_id") or ""),
            )
        )
        for allocation_order, (ap, _group, source, station_id) in enumerate(
            group_items
        ):
            ap_id = str(ap.get("id") or ap.get("ap_id") or "")
            existing = existing_by_ap.get(ap_id)
            keep_existing = bool(
                existing
                and reallocation_policy == REALLOCATION_ONLY_UNLOCKED
                and bool(existing.get("is_locked") or existing.get("is_manual"))
                and str(existing.get("planned_ip") or "")
            )
            if keep_existing:
                planned_ip = str(existing["planned_ip"])
                is_manual = bool(existing.get("is_manual"))
                is_locked = bool(existing.get("is_locked"))
                allocation_source = str(existing.get("source") or "manual")
            else:
                try:
                    planned_ip = next(candidates)
                except StopIteration:
                    issues.append(
                        _error(
                            "ADDRESS_CAPACITY_INSUFFICIENT",
                            f"{group['group_name']} 的可用地址容量不足",
                            "ap_start_ip",
                            group_id=group_id,
                            ap_id=ap_id,
                        )
                    )
                    break
                reserved_ips.add(planned_ip)
                is_manual = False
                is_locked = False
                allocation_source = "generated"
            allocations.append(
                {
                    "ap_id": ap_id,
                    "ap_name": str(ap.get("name") or ap.get("ap_name") or ""),
                    "point_code": str(
                        ap.get("point_code") or ap.get("ap_point_code") or ""
                    ),
                    "station_id": station_id,
                    "station_name": str(
                        ap.get("station") or ap.get("station_name") or ""
                    ),
                    "section_name": str(
                        ap.get("section") or ap.get("section_name") or ""
                    ),
                    "group_id": group_id,
                    "planned_ip": planned_ip,
                    "allocation_order": allocation_order,
                    "is_manual": is_manual,
                    "is_locked": is_locked,
                    "source": allocation_source,
                    "group_source": source,
                    "updated_at": str((existing or {}).get("updated_at") or ""),
                }
            )
    issues.extend(_validate_allocations(allocations, groups))
    return (
        allocations,
        [issue.to_dict() for issue in _dedupe_issues(issues)],
        derived_assignments,
    )


def enrich_plan(
    draft: Mapping[str, Any],
    *,
    stations: Iterable[Mapping[str, Any]],
    aps: Iterable[Mapping[str, Any]] = (),
    reallocation_policy: str = REALLOCATION_ONLY_UNLOCKED,
) -> dict[str, object]:
    station_rows = station_inputs(stations)
    normalized = normalize_plan_draft(draft, station_rows)
    allocations, allocation_issues, derived_assignments = allocate_addresses(
        normalized,
        stations=station_rows,
        aps=aps,
        reallocation_policy=reallocation_policy,
    )
    assignment_targets = {str(row["target_id"]) for row in normalized["assignments"]}
    assignments = [
        *list(normalized["assignments"]),
        *[
            row
            for row in derived_assignments
            if str(row["target_id"]) not in assignment_targets
        ],
    ]
    prepared = {
        **normalized,
        "assignments": assignments,
        "allocations": allocations,
    }
    issues = validate_plan(prepared, stations=station_rows, aps=aps)
    known_issue_keys = {
        (str(row["code"]), str(row.get("group_id") or ""), str(row.get("ap_id") or ""))
        for row in issues
    }
    for issue in allocation_issues:
        key = (
            str(issue["code"]),
            str(issue.get("group_id") or ""),
            str(issue.get("ap_id") or ""),
        )
        if key not in known_issue_keys:
            issues.append(issue)
    groups = _group_statistics(
        list(prepared["groups"]),
        station_rows=station_rows,
        allocations=allocations,
        issues=issues,
    )
    station_details = _station_details(groups, station_rows, allocations)
    return {
        **prepared,
        "groups": groups,
        "station_details": station_details,
        "issues": issues,
        "valid": not any(bool(issue.get("blocking")) for issue in issues),
        "unassigned_station_count": sum(
            not str(row.get("group_id") or "") for row in station_details
        ),
    }


def plan_impact(
    current: Mapping[str, Any],
    proposed: Mapping[str, Any],
    *,
    stations: Iterable[Mapping[str, Any]],
    aps: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    current_view = enrich_plan(current, stations=stations, aps=aps)
    proposed_view = enrich_plan(proposed, stations=stations, aps=aps)
    current_stations = {
        str(row["station_id"]): row for row in current_view["station_details"]
    }
    proposed_stations = {
        str(row["station_id"]): row for row in proposed_view["station_details"]
    }
    current_allocations = {
        str(row["ap_id"]): row for row in current_view["allocations"]
    }
    proposed_allocations = {
        str(row["ap_id"]): row for row in proposed_view["allocations"]
    }
    affected_stations = 0
    vlan_changes = 0
    gateway_changes = 0
    for station_id in set(current_stations) | set(proposed_stations):
        before = current_stations.get(station_id, {})
        after = proposed_stations.get(station_id, {})
        keys = (
            "group_id",
            "management_vlan",
            "network_address",
            "prefix_length",
            "default_gateway",
        )
        if any(before.get(key) != after.get(key) for key in keys):
            affected_stations += 1
        if before.get("management_vlan") != after.get("management_vlan"):
            vlan_changes += 1
        if before.get("default_gateway") != after.get("default_gateway"):
            gateway_changes += 1
    affected_aps = 0
    ip_changes = 0
    for ap_id in set(current_allocations) | set(proposed_allocations):
        before = current_allocations.get(ap_id, {})
        after = proposed_allocations.get(ap_id, {})
        if before.get("group_id") != after.get("group_id") or before.get(
            "planned_ip"
        ) != after.get("planned_ip"):
            affected_aps += 1
        if before.get("planned_ip") != after.get("planned_ip"):
            ip_changes += 1
    return {
        "old_group_count": len(current_view["groups"]),
        "new_group_count": len(proposed_view["groups"]),
        "affected_station_count": affected_stations,
        "affected_ap_count": affected_aps,
        "vlan_change_count": vlan_changes,
        "ip_change_count": ip_changes,
        "gateway_change_count": gateway_changes,
        "manual_address_override_count": sum(
            bool(row.get("is_manual") or row.get("is_locked"))
            for row in current_view["allocations"]
        ),
        "conflict_count": sum(
            bool(row.get("blocking")) for row in proposed_view["issues"]
        ),
        "warning_count": sum(
            not bool(row.get("blocking")) for row in proposed_view["issues"]
        ),
        "issues": proposed_view["issues"],
    }


def effective_network(
    draft: Mapping[str, Any],
    *,
    stations: Iterable[Mapping[str, Any]],
    station_id: str = "",
    ap_id: str = "",
) -> dict[str, object] | None:
    normalized = normalize_plan_draft(draft, stations)
    groups = {str(group["group_id"]): group for group in normalized["groups"]}
    group_id = ""
    source = ""
    if ap_id:
        assignment = next(
            (
                row
                for row in normalized["assignments"]
                if str(row["target_id"]) == ap_id
            ),
            None,
        )
        allocation = next(
            (row for row in normalized["allocations"] if str(row["ap_id"]) == ap_id),
            None,
        )
        effective = allocation or assignment or {}
        group_id = str(effective.get("group_id") or "")
        source = str(
            effective.get("group_source") or effective.get("source") or ""
        )
    if not group_id and station_id:
        group = next(
            (
                group
                for group in normalized["groups"]
                if any(
                    str(member["station_id"]) == station_id
                    for member in group["members"]
                )
            ),
            None,
        )
        if group is not None:
            group_id = str(group["group_id"])
            source = "station_inherited"
    group = groups.get(group_id)
    if group is None:
        return None
    return _network_payload(group, source=source or "group")


def build_point_table_rows(
    draft: Mapping[str, Any],
    *,
    stations: Iterable[Mapping[str, Any]],
    aps: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    view = enrich_plan(draft, stations=stations, aps=aps)
    if not view["valid"]:
        first = next(issue for issue in view["issues"] if bool(issue.get("blocking")))
        raise ValueError(str(first["message"]))
    groups = {str(group["group_id"]): group for group in view["groups"]}
    ap_by_id = {str(row.get("id") or row.get("ap_id") or ""): row for row in aps}
    result: list[dict[str, object]] = []
    for allocation in view["allocations"]:
        ap = ap_by_id.get(str(allocation["ap_id"]), {})
        group = groups[str(allocation["group_id"])]
        result.append(
            {
                "ap_id": allocation["ap_id"],
                "station": str(
                    ap.get("station") or allocation.get("station_name") or ""
                ),
                "section": str(
                    ap.get("section") or allocation.get("section_name") or ""
                ),
                "ap_name": str(ap.get("name") or allocation.get("ap_name") or ""),
                "point_code": str(
                    ap.get("point_code") or allocation.get("point_code") or ""
                ),
                "ap_ip": allocation["planned_ip"],
                "management_vlan": group["management_vlan"],
                "subnet_mask": group["subnet_mask"],
                "prefix_length": group["prefix_length"],
                "default_gateway": group["default_gateway"],
                "vlan_group_id": group["group_id"],
                "vlan_group_code": group["group_code"],
                "vlan_group_name": group["group_name"],
                "allocation_source": allocation["source"],
                "is_locked": allocation["is_locked"],
            }
        )
    return result


def legacy_rows_to_draft(
    rows: Iterable[Mapping[str, Any]],
    *,
    stations: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    station_rows = station_inputs(stations)
    by_name = {str(row["station_name"]).casefold(): row for row in station_rows}
    groups: list[dict[str, object]] = []
    for sequence, row in enumerate(rows):
        station_name = str(row.get("station_name") or "").strip()
        station = by_name.get(station_name.casefold()) or {
            "station_id": stable_legacy_station_id(station_name),
            "station_name": station_name,
            "station_sequence": sequence,
            "ap_count": int(row.get("ap_count") or 0),
        }
        vlan_tokens = _vlan_tokens(
            row.get("ap_management_vlans")
            if row.get("ap_management_vlans") not in (None, "")
            else row.get("management_vlan")
        )
        primary_vlan = min(vlan_tokens) if vlan_tokens else None
        groups.append(
            {
                "group_id": str(row.get("group_id") or f"legacy-plan-{sequence + 1}"),
                "group_code": str(row.get("group_code") or f"G{sequence + 1:03d}"),
                "group_name": str(
                    row.get("group_name") or station_name or f"VLAN 组 {sequence + 1}"
                ),
                "sequence": sequence,
                "management_vlan": primary_vlan,
                "legacy_management_vlans": ",".join(
                    str(value) for value in sorted(vlan_tokens)
                )
                if len(vlan_tokens) > 1
                else "",
                "network_address": str(row.get("network_address") or ""),
                "prefix_length": row.get("prefix_length") or row.get("mask_length"),
                "default_gateway": str(
                    row.get("default_gateway") or row.get("ap_gateway") or ""
                ),
                "ap_start_ip": str(
                    row.get("ap_start_ip") or row.get("ap_start_address") or ""
                ),
                "address_allocation_strategy": DEFAULT_ALLOCATION_STRATEGY,
                "notes": str(row.get("notes") or row.get("remark") or ""),
                "members": [station],
            }
        )
    return normalize_plan_draft(
        {
            "planning": {
                "line_id": "current",
                "planning_mode": STATION_INDEPENDENT,
                "auto_group_station_count": 1,
                "address_allocation_strategy": DEFAULT_ALLOCATION_STRATEGY,
                "revision": 0,
            },
            "groups": groups,
        },
        station_rows,
    )


def project_legacy_station_rows(draft: Mapping[str, Any]) -> list[dict[str, object]]:
    normalized = normalize_plan_draft(
        draft, _stations_from_groups(draft.get("groups") or [])
    )
    rows: list[dict[str, object]] = []
    for group in normalized["groups"]:
        vlan_text = str(group.get("legacy_management_vlans") or "").strip()
        if not vlan_text and group.get("management_vlan") is not None:
            vlan_text = str(group["management_vlan"])
        for member in group["members"]:
            rows.append(
                {
                    "station_name": member["station_name"],
                    "ap_count": member["ap_count"],
                    "ap_start_address": group["ap_start_ip"],
                    "mask_length": group["prefix_length"],
                    "ap_gateway": group["default_gateway"],
                    "ap_management_vlans": vlan_text,
                    "remark": group["notes"],
                    "sort_order": member["station_sequence"],
                }
            )
    rows.sort(
        key=lambda row: (int(row["sort_order"]), _natural_key(row["station_name"]))
    )
    return rows


def export_rows(draft: Mapping[str, Any]) -> list[dict[str, object]]:
    normalized = normalize_plan_draft(
        draft, _stations_from_groups(draft.get("groups") or [])
    )
    planning = normalized["planning"]
    allocations_by_station: dict[str, list[Mapping[str, Any]]] = {}
    for allocation in normalized["allocations"]:
        allocations_by_station.setdefault(
            str(allocation.get("station_id") or ""), []
        ).append(allocation)
    rows: list[dict[str, object]] = []
    for group in normalized["groups"]:
        members = list(group["members"])
        start_station = str(members[0]["station_name"]) if members else ""
        end_station = str(members[-1]["station_name"]) if members else ""
        for member in members or [{}]:
            station_id = str(member.get("station_id") or "")
            station_allocations = allocations_by_station.get(station_id, [])
            rows.append(
                {
                    "planning_mode": planning["planning_mode"],
                    "group_code": group["group_code"],
                    "group_name": group["group_name"],
                    "start_station_name": start_station,
                    "end_station_name": end_station,
                    "station_ids": ",".join(
                        str(item["station_id"]) for item in members
                    ),
                    "station_names": "、".join(
                        str(item["station_name"]) for item in members
                    ),
                    "station_name": str(member.get("station_name") or ""),
                    "ap_count": int(member.get("ap_count") or 0),
                    "management_vlan": group["management_vlan"],
                    "network_address": group["network_address"],
                    "prefix_length": group["prefix_length"],
                    "subnet_mask": group["subnet_mask"],
                    "default_gateway": group["default_gateway"],
                    "ap_start_ip": group["ap_start_ip"],
                    "ap_end_ip": group["ap_end_ip"],
                    "allocation_order": min(
                        (
                            int(row.get("allocation_order") or 0)
                            for row in station_allocations
                        ),
                        default=0,
                    ),
                    "is_locked": any(
                        bool(row.get("is_locked")) for row in station_allocations
                    ),
                    "notes": group["notes"],
                    # 兼容旧模板消费者。
                    "ap_start_address": group["ap_start_ip"],
                    "mask_length": group["prefix_length"],
                    "ap_gateway": group["default_gateway"],
                    "ap_management_vlans": str(group["management_vlan"] or ""),
                    "remark": group["notes"],
                }
            )
    return rows


def _validate_group_network(group: Mapping[str, Any]) -> list[PlanningIssue]:
    group_id = str(group["group_id"])
    name = str(group["group_name"])
    issues: list[PlanningIssue] = []
    vlan = _optional_int(group.get("management_vlan"))
    if vlan is None or not 1 <= vlan <= 4094:
        issues.append(
            _error(
                "MANAGEMENT_VLAN_INVALID",
                f"{name} 的管理 VLAN 必须在 1～4094 范围内",
                "management_vlan",
                group_id=group_id,
            )
        )
    network = _network(
        group.get("network_address"),
        _optional_int(group.get("prefix_length")),
        group.get("ap_start_ip"),
    )
    start = _address(group.get("ap_start_ip"))
    gateway = _address(group.get("default_gateway"))
    if "X" in str(group.get("ap_start_ip") or "").upper():
        issues.append(
            _warning(
                "LEGACY_AP_START_PLACEHOLDER",
                f"{name} 保留了旧模板占位地址，正式点表生成前必须替换为完整 IPv4 地址",
                "ap_start_ip",
                group_id=group_id,
            )
        )
        return issues
    if (
        any(
            str(group.get(field) or "").strip()
            for field in ("network_address", "ap_start_ip", "default_gateway")
        )
        and network is None
    ):
        issues.append(
            _error(
                "GROUP_SUBNET_INVALID",
                f"{name} 的子网或掩码无效",
                "network_address",
                group_id=group_id,
            )
        )
        return issues
    if network is None:
        return issues
    for field_name, address, label in (
        ("default_gateway", gateway, "网关"),
        ("ap_start_ip", start, "AP 起始地址"),
    ):
        if address is None:
            issues.append(
                _error(
                    f"{field_name.upper()}_INVALID",
                    f"{name} 的{label}无效",
                    field_name,
                    group_id=group_id,
                )
            )
            continue
        if address not in network:
            issues.append(
                _error(
                    f"{field_name.upper()}_OUTSIDE_SUBNET",
                    f"{name} 的{label}不在组内子网",
                    field_name,
                    group_id=group_id,
                )
            )
        elif address in {network.network_address, network.broadcast_address}:
            issues.append(
                _error(
                    f"{field_name.upper()}_RESERVED",
                    f"{name} 的{label}不能使用网络地址或广播地址",
                    field_name,
                    group_id=group_id,
                )
            )
    if start is not None and gateway is not None and start == gateway:
        issues.append(
            _error(
                "AP_START_EQUALS_GATEWAY",
                f"{name} 的 AP 起始地址不能使用网关地址",
                "ap_start_ip",
                group_id=group_id,
            )
        )
    required_count = sum(
        int(member.get("ap_count") or 0) for member in group.get("members") or []
    )
    if start is not None:
        available = _available_address_count(
            network,
            start,
            {
                str(network.network_address),
                str(network.broadcast_address),
                *(str(item) for item in (gateway,) if item is not None),
            },
        )
        if required_count > available:
            issues.append(
                _error(
                    "ADDRESS_CAPACITY_INSUFFICIENT",
                    f"{name} 地址容量不足：需要 {required_count} 个地址，但从起始地址起只有 {available} 个可用地址",
                    "ap_start_ip",
                    group_id=group_id,
                )
            )
        elif available and required_count / available >= 0.8:
            issues.append(
                _warning(
                    "ADDRESS_UTILIZATION_HIGH",
                    f"{name} 从起始地址起的地址利用率已达到 {required_count / available:.0%}",
                    "ap_start_ip",
                    group_id=group_id,
                )
            )
        usable_hosts = max(0, network.num_addresses - 2)
        first_host = int(network.network_address) + 1
        reserved_before_start = max(0, int(start) - first_host)
        if (
            usable_hosts
            and reserved_before_start >= max(16, required_count * 2)
            and reserved_before_start / usable_hosts >= 0.25
        ):
            issues.append(
                _warning(
                    "ADDRESS_RESERVATION_HIGH",
                    f"{name} 在 AP 起始地址前预留了 {reserved_before_start} 个主机地址",
                    "ap_start_ip",
                    group_id=group_id,
                )
            )
    return issues


def _cross_group_warnings(groups: list[Mapping[str, Any]]) -> list[PlanningIssue]:
    issues: list[PlanningIssue] = []
    for index, group in enumerate(groups):
        for other in groups[index + 1 :]:
            same_vlan = group.get("management_vlan") is not None and group.get(
                "management_vlan"
            ) == other.get("management_vlan")
            same_gateway = bool(group.get("default_gateway")) and (
                group.get("default_gateway") == other.get("default_gateway")
            )
            same_subnet = bool(group.get("network_address")) and (
                group.get("network_address") == other.get("network_address")
                and group.get("prefix_length") == other.get("prefix_length")
            )
            if same_vlan:
                issues.append(
                    _warning(
                        "MANAGEMENT_VLAN_REUSED",
                        f"{group['group_name']} 与 {other['group_name']} 使用相同 VLAN ID；隔离二层域中允许重复",
                        "management_vlan",
                        group_id=str(group["group_id"]),
                    )
                )
            if same_gateway:
                issues.append(
                    _warning(
                        "GATEWAY_REUSED",
                        f"{group['group_name']} 与 {other['group_name']} 使用相同网关",
                        "default_gateway",
                        group_id=str(group["group_id"]),
                    )
                )
            if same_subnet:
                issues.append(
                    _warning(
                        "SUBNET_REUSED",
                        f"{group['group_name']} 与 {other['group_name']} 使用相同子网",
                        "network_address",
                        group_id=str(group["group_id"]),
                    )
                )
            if (
                int(other.get("sequence") or 0) == int(group.get("sequence") or 0) + 1
                and same_vlan
                and same_gateway
                and same_subnet
            ):
                issues.append(
                    _warning(
                        "ADJACENT_GROUPS_NETWORK_EQUAL",
                        f"{group['group_name']} 与 {other['group_name']} 网络参数一致，可以考虑合并",
                        group_id=str(group["group_id"]),
                    )
                )
    return issues


def _validate_allocations(
    allocations: list[Mapping[str, Any]],
    groups: Mapping[str, Mapping[str, Any]],
) -> list[PlanningIssue]:
    issues: list[PlanningIssue] = []
    for row in allocations:
        group = groups.get(str(row.get("group_id") or ""))
        if group is None:
            continue
        address = _address(row.get("planned_ip"))
        network = _network(
            group.get("network_address"),
            _optional_int(group.get("prefix_length")),
            group.get("ap_start_ip"),
        )
        gateway = _address(group.get("default_gateway"))
        if address is None:
            issues.append(
                _error(
                    "AP_IP_INVALID",
                    f"AP“{row.get('ap_name') or row.get('ap_id')}”的规划地址无效",
                    "planned_ip",
                    group_id=str(group["group_id"]),
                    ap_id=str(row.get("ap_id") or ""),
                )
            )
        elif network is not None and address not in network:
            issues.append(
                _error(
                    "AP_IP_OUTSIDE_SUBNET",
                    f"AP“{row.get('ap_name') or row.get('ap_id')}”的规划地址不在组内子网",
                    "planned_ip",
                    group_id=str(group["group_id"]),
                    ap_id=str(row.get("ap_id") or ""),
                )
            )
        elif network is not None and address in {
            network.network_address,
            network.broadcast_address,
        }:
            issues.append(
                _error(
                    "AP_IP_RESERVED",
                    f"AP“{row.get('ap_name') or row.get('ap_id')}”使用了网络地址或广播地址",
                    "planned_ip",
                    group_id=str(group["group_id"]),
                    ap_id=str(row.get("ap_id") or ""),
                )
            )
        elif gateway is not None and address == gateway:
            issues.append(
                _error(
                    "AP_IP_EQUALS_GATEWAY",
                    f"AP“{row.get('ap_name') or row.get('ap_id')}”使用了网关地址",
                    "planned_ip",
                    group_id=str(group["group_id"]),
                    ap_id=str(row.get("ap_id") or ""),
                )
            )
    return issues


def _effective_group_for_ap(
    ap: Mapping[str, Any],
    *,
    groups: Mapping[str, Mapping[str, Any]],
    group_by_station: Mapping[str, Mapping[str, Any]],
    station_by_name: Mapping[str, Mapping[str, Any]],
    assignment_by_target: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, str, str]:
    ap_id = str(ap.get("id") or ap.get("ap_id") or "")
    station_name = str(ap.get("station") or ap.get("station_name") or "").strip()
    station = station_by_name.get(station_name.casefold())
    start_name = str(
        ap.get("section_start_station")
        or (ap.get("base_metadata") or {}).get("section_start_station")
        or ""
    ).strip()
    start_station = station_by_name.get(start_name.casefold())
    station_id = str((station or {}).get("station_id") or "")
    explicit = assignment_by_target.get(ap_id)
    explicit_type = str((explicit or {}).get("assignment_type") or "")
    if (
        explicit
        and explicit_type == "ap_override"
        and str(explicit.get("group_id") or "") in groups
    ):
        return (
            groups[str(explicit["group_id"])],
            str(
                explicit.get("source")
                or explicit.get("assignment_type")
                or "ap_override"
            ),
            station_id,
        )
    if station is not None:
        station_id = str(station["station_id"])
        group = group_by_station.get(station_id)
        if group is not None:
            return group, "station_inherited", station_id
    section_id = str((ap.get("base_metadata") or {}).get("section_id") or "")
    section_name = str(ap.get("section") or ap.get("section_name") or "")
    for target_id in (section_id, f"section:{section_name}" if section_name else ""):
        explicit_section = assignment_by_target.get(target_id)
        if explicit_section and str(explicit_section.get("group_id") or "") in groups:
            return (
                groups[str(explicit_section["group_id"])],
                str(explicit_section.get("source") or "section_default"),
                "",
            )
    if (
        explicit
        and explicit_type == "interval_default"
        and str(explicit.get("group_id") or "") in groups
    ):
        return (
            groups[str(explicit["group_id"])],
            str(explicit.get("source") or "interval_start_default"),
            "",
        )
    if start_station is not None:
        station_id = str(start_station["station_id"])
        group = group_by_station.get(station_id)
        if group is not None:
            return group, "interval_start_default", ""
    return None, "unresolved", ""


def _group_statistics(
    groups: list[dict[str, object]],
    *,
    station_rows: list[dict[str, object]],
    allocations: list[dict[str, object]],
    issues: list[dict[str, object]],
) -> list[dict[str, object]]:
    station_by_id = {str(row["station_id"]): row for row in station_rows}
    allocations_by_group: dict[str, list[dict[str, object]]] = {}
    for allocation in allocations:
        allocations_by_group.setdefault(str(allocation["group_id"]), []).append(
            allocation
        )
    issues_by_group: dict[str, list[dict[str, object]]] = {}
    for issue in issues:
        issues_by_group.setdefault(str(issue.get("group_id") or ""), []).append(issue)
    result: list[dict[str, object]] = []
    for group in groups:
        members = list(group["members"])
        member_rows = [
            station_by_id.get(str(member["station_id"]), member) for member in members
        ]
        group_allocations = allocations_by_group.get(str(group["group_id"]), [])
        network = _network(
            group.get("network_address"),
            _optional_int(group.get("prefix_length")),
            group.get("ap_start_ip"),
        )
        gateway = _address(group.get("default_gateway"))
        address_capacity = 0
        if network is not None and _address(group.get("ap_start_ip")) is not None:
            address_capacity = _available_address_count(
                network,
                _address(group.get("ap_start_ip")),
                {
                    str(network.network_address),
                    str(network.broadcast_address),
                    *(str(item) for item in (gateway,) if item is not None),
                },
            )
        used_addresses = [
            str(row["planned_ip"])
            for row in group_allocations
            if _address(row.get("planned_ip")) is not None
        ]
        group_issues = [
            issue
            for issue in issues_by_group.get(str(group["group_id"]), [])
            if issue.get("group_id")
        ]
        result.append(
            {
                **group,
                "start_station_name": str(member_rows[0].get("station_name") or "")
                if member_rows
                else "",
                "end_station_name": str(member_rows[-1].get("station_name") or "")
                if member_rows
                else "",
                "station_count": len(members),
                "ap_count": max(
                    len(group_allocations),
                    sum(int(row.get("ap_count") or 0) for row in member_rows),
                ),
                "ap_end_ip": max(
                    used_addresses,
                    key=lambda value: int(ipaddress.ip_address(value)),
                    default=str(group.get("ap_end_ip") or ""),
                ),
                "address_capacity": address_capacity,
                "used_address_count": len(used_addresses),
                "validation_status": (
                    "error"
                    if any(bool(issue.get("blocking")) for issue in group_issues)
                    else "warning"
                    if group_issues
                    else "valid"
                ),
                "issues": group_issues,
            }
        )
    return result


def _station_details(
    groups: list[dict[str, object]],
    station_rows: list[dict[str, object]],
    allocations: list[dict[str, object]],
) -> list[dict[str, object]]:
    group_by_station = {
        str(member["station_id"]): group
        for group in groups
        for member in group["members"]
    }
    allocations_by_station: dict[str, list[dict[str, object]]] = {}
    for allocation in allocations:
        allocations_by_station.setdefault(
            str(allocation.get("station_id") or ""), []
        ).append(allocation)
    details: list[dict[str, object]] = []
    for station in station_rows:
        station_id = str(station["station_id"])
        group = group_by_station.get(station_id)
        rows = allocations_by_station.get(station_id, [])
        addresses = [
            str(row["planned_ip"]) for row in rows if str(row.get("planned_ip") or "")
        ]
        details.append(
            {
                **station,
                "group_id": str((group or {}).get("group_id") or ""),
                "group_code": str((group or {}).get("group_code") or ""),
                "group_name": str((group or {}).get("group_name") or "未分配"),
                "ap_start_ip": min(
                    addresses,
                    key=lambda value: int(ipaddress.ip_address(value)),
                    default="",
                ),
                "ap_end_ip": max(
                    addresses,
                    key=lambda value: int(ipaddress.ip_address(value)),
                    default="",
                ),
                "management_vlan": (group or {}).get("management_vlan"),
                "network_address": str((group or {}).get("network_address") or ""),
                "prefix_length": (group or {}).get("prefix_length"),
                "subnet_mask": str((group or {}).get("subnet_mask") or ""),
                "default_gateway": str((group or {}).get("default_gateway") or ""),
                "source": "vlan_group_inherited" if group else "unassigned",
                "notes": str((group or {}).get("notes") or ""),
            }
        )
    return details


def _normalize_assignments(
    value: object,
    groups: list[Mapping[str, Any]],
) -> list[dict[str, object]]:
    group_ids = {str(group["group_id"]) for group in groups}
    result: list[dict[str, object]] = []
    if not isinstance(value, list):
        return result
    for row in value:
        if not isinstance(row, Mapping):
            continue
        target_id = str(row.get("target_id") or "").strip()
        group_id = str(row.get("group_id") or "").strip()
        if not target_id or group_id not in group_ids:
            continue
        result.append(
            {
                "assignment_id": str(
                    row.get("assignment_id") or f"assignment-{uuid4().hex}"
                ),
                "assignment_type": str(row.get("assignment_type") or "ap_override"),
                "target_id": target_id,
                "group_id": group_id,
                "source": str(
                    row.get("source") or row.get("assignment_type") or "ap_override"
                ),
                "updated_at": str(row.get("updated_at") or ""),
            }
        )
    by_target: dict[str, dict[str, object]] = {}
    for row in result:
        by_target[str(row["target_id"])] = row
    return list(by_target.values())


def _normalize_allocations(
    value: object,
    groups: list[Mapping[str, Any]],
) -> list[dict[str, object]]:
    group_ids = {str(group["group_id"]) for group in groups}
    result: list[dict[str, object]] = []
    if not isinstance(value, list):
        return result
    for row in value:
        if not isinstance(row, Mapping):
            continue
        ap_id = str(row.get("ap_id") or "").strip()
        group_id = str(row.get("group_id") or "").strip()
        if not ap_id or group_id not in group_ids:
            continue
        result.append(
            {
                "ap_id": ap_id,
                "ap_name": str(row.get("ap_name") or ""),
                "point_code": str(row.get("point_code") or ""),
                "station_id": str(row.get("station_id") or ""),
                "station_name": str(row.get("station_name") or ""),
                "section_name": str(row.get("section_name") or ""),
                "group_id": group_id,
                "planned_ip": str(row.get("planned_ip") or "").strip(),
                "allocation_order": int(row.get("allocation_order") or 0),
                "is_manual": bool(row.get("is_manual")),
                "is_locked": bool(row.get("is_locked")),
                "source": str(row.get("source") or "generated"),
                "group_source": str(row.get("group_source") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
        )
    by_ap: dict[str, dict[str, object]] = {}
    for row in result:
        by_ap[str(row["ap_id"])] = row
    return list(by_ap.values())


def _new_group_from_seed(
    seed: Mapping[str, Any] | None,
    sequence: int,
) -> dict[str, object]:
    return {
        "group_id": str((seed or {}).get("group_id") or f"vlan-group-{uuid4().hex}"),
        "line_id": str((seed or {}).get("line_id") or "current"),
        "group_code": str((seed or {}).get("group_code") or f"G{sequence + 1:03d}"),
        "group_name": str((seed or {}).get("group_name") or f"VLAN 组 {sequence + 1}"),
        "sequence": sequence,
        "management_vlan": (seed or {}).get("management_vlan"),
        "legacy_management_vlans": str(
            (seed or {}).get("legacy_management_vlans") or ""
        ),
        "network_address": str((seed or {}).get("network_address") or ""),
        "prefix_length": (seed or {}).get("prefix_length"),
        "subnet_mask": str((seed or {}).get("subnet_mask") or ""),
        "default_gateway": str((seed or {}).get("default_gateway") or ""),
        "ap_start_ip": str((seed or {}).get("ap_start_ip") or ""),
        "ap_end_ip": str((seed or {}).get("ap_end_ip") or ""),
        "address_allocation_strategy": str(
            (seed or {}).get("address_allocation_strategy")
            or DEFAULT_ALLOCATION_STRATEGY
        ),
        "notes": str((seed or {}).get("notes") or ""),
        "members": [],
    }


def _default_group_name(chunk: list[dict[str, object]], sequence: int) -> str:
    if not chunk:
        return f"VLAN 组 {sequence + 1}"
    first = str(chunk[0]["station_name"])
    last = str(chunk[-1]["station_name"])
    return first if first == last else f"{first}～{last}"


def _network(
    network_address: object,
    prefix_length: int | None,
    ap_start_ip: object = "",
) -> ipaddress.IPv4Network | None:
    text = str(network_address or "").strip()
    try:
        if "/" in text:
            network = ipaddress.ip_network(text, strict=False)
        elif text and prefix_length is not None:
            network = ipaddress.ip_network(f"{text}/{prefix_length}", strict=False)
        elif str(ap_start_ip or "").strip() and prefix_length is not None:
            network = ipaddress.ip_network(
                f"{str(ap_start_ip).strip()}/{prefix_length}",
                strict=False,
            )
        else:
            return None
    except ValueError:
        return None
    return network if isinstance(network, ipaddress.IPv4Network) else None


def _address(value: object) -> ipaddress.IPv4Address | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    return address if isinstance(address, ipaddress.IPv4Address) else None


def _candidate_addresses(
    network: ipaddress.IPv4Network,
    start: ipaddress.IPv4Address,
    blocked: set[str],
):
    first = max(int(start), int(network.network_address) + 1)
    last = int(network.broadcast_address) - 1
    for raw in range(first, last + 1):
        value = str(ipaddress.IPv4Address(raw))
        if value not in blocked:
            yield value


def _available_address_count(
    network: ipaddress.IPv4Network,
    start: ipaddress.IPv4Address,
    blocked: set[str],
) -> int:
    first = max(int(start), int(network.network_address) + 1)
    last = int(network.broadcast_address) - 1
    if first > last:
        return 0
    blocked_in_range = 0
    for value in blocked:
        address = _address(value)
        if address is not None and first <= int(address) <= last:
            blocked_in_range += 1
    return max(0, last - first + 1 - blocked_in_range)


def _network_payload(group: Mapping[str, Any], *, source: str) -> dict[str, object]:
    return {
        "vlan_group_id": group["group_id"],
        "vlan_group_code": group["group_code"],
        "vlan_group_name": group["group_name"],
        "management_vlan": group["management_vlan"],
        "network_address": group["network_address"],
        "prefix_length": group["prefix_length"],
        "subnet_mask": group["subnet_mask"],
        "default_gateway": group["default_gateway"],
        "ap_start_ip": group["ap_start_ip"],
        "ap_end_ip": group.get("ap_end_ip") or "",
        "address_allocation_strategy": group["address_allocation_strategy"],
        "source": source,
    }


def _error(
    code: str,
    message: str,
    field_name: str = "",
    *,
    group_id: str = "",
    station_id: str = "",
    ap_id: str = "",
) -> PlanningIssue:
    return PlanningIssue(
        code=code,
        severity="error",
        message=message,
        blocking=True,
        field_name=field_name,
        group_id=group_id,
        station_id=station_id,
        ap_id=ap_id,
    )


def _warning(
    code: str,
    message: str,
    field_name: str = "",
    *,
    group_id: str = "",
) -> PlanningIssue:
    return PlanningIssue(
        code=code,
        severity="warning",
        message=message,
        blocking=False,
        field_name=field_name,
        group_id=group_id,
    )


def _dedupe_issues(issues: Iterable[PlanningIssue]) -> list[PlanningIssue]:
    result: list[PlanningIssue] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for issue in issues:
        key = (
            issue.code,
            issue.group_id,
            issue.station_id,
            issue.ap_id,
            issue.message,
        )
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _vlan_tokens(value: object) -> set[int]:
    result: set[int] = set()
    for token in re.split(r"[,，;；\s]+", str(value or "").strip()):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            if left.isdigit() and right.isdigit():
                result.update(range(int(left), int(right) + 1))
        elif token.isdigit():
            result.add(int(token))
    return {value for value in result if 1 <= value <= 4094}


def _natural_key(value: object) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", str(value or ""))
    )


def _stations_from_groups(groups: object) -> list[dict[str, object]]:
    if not isinstance(groups, list):
        return []
    result: dict[str, dict[str, object]] = {}
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        members = group.get("members")
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, Mapping):
                continue
            station_id = str(member.get("station_id") or "")
            result[station_id] = {
                "id": station_id,
                "name": str(member.get("station_name") or ""),
                "sort_order": member.get("station_sequence"),
                "ap_count": member.get("ap_count"),
                "enabled": True,
            }
    return list(result.values())


__all__ = [
    "DEFAULT_ALLOCATION_STRATEGY",
    "LINE_SINGLE",
    "PLANNING_MODES",
    "REALLOCATION_ALL",
    "REALLOCATION_ONLY_UNLOCKED",
    "STATION_GROUPED",
    "STATION_INDEPENDENT",
    "allocate_addresses",
    "auto_group_draft",
    "build_point_table_rows",
    "effective_network",
    "enrich_plan",
    "export_rows",
    "legacy_rows_to_draft",
    "normalize_plan_draft",
    "plan_impact",
    "project_legacy_station_rows",
    "stable_legacy_station_id",
    "station_inputs",
    "validate_plan",
]
