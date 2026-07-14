from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from netconsole.services.ap_extension_import import normalize_ap_mac


MatchStatus = Literal["matched", "create", "conflict"]

BASE_DATA_WRITE_ENV = "RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED"
RUNTIME_FIELDS = {
    "fit_ap_status",
    "management_ip",
    "mesh_status",
    "optical_status",
    "rssi",
    "related_mr",
    "runtime_updated_at",
}
BLOCKING_ISSUE_CODES = {
    "ap_mac_duplicate",
    "mr_mac_duplicate",
    "mr_role_duplicate",
    "static_ip_duplicate",
    "station_reference_missing",
    "section_reference_missing",
    "entity_type_unknown",
    "database_primary_key_conflict",
    "identity_conflict",
}
SOURCE_PRIORITIES = {
    "manual_override": 100,
    "existing_database": 95,
    "official_point_table": 90,
    "ap_extension": 80,
    "import_file": 70,
    "ac_fit_ap": 50,
    "ac_mesh_link": 40,
    "agent_package": 30,
    "online_mr": 20,
}


@dataclass(frozen=True)
class IdentityMatch:
    status: MatchStatus
    entity_id: str = ""
    method: str = ""
    warning: str = ""


def is_runtime_field(field_name: str) -> bool:
    return str(field_name or "").strip().casefold() in RUNTIME_FIELDS


def is_blocking_issue(code: str, severity: str = "") -> bool:
    return str(code or "").strip() in BLOCKING_ISSUE_CODES or severity == "error" and code == "ap_mac_invalid"


def field_action(current: Any, proposed: Any, *, source_type: str) -> str:
    current_text = _text(current)
    proposed_text = _text(proposed)
    if current_text == proposed_text or not proposed_text:
        return "keep_existing"
    if not current_text:
        return "fill_missing"
    if SOURCE_PRIORITIES.get(source_type, 0) > SOURCE_PRIORITIES["existing_database"]:
        return "use_imported"
    return "manual_review"


def match_trackside_ap(source: Mapping[str, Any], existing: Sequence[Mapping[str, Any]]) -> IdentityMatch:
    mac = _mac(source.get("ap_mac_norm") or source.get("ap_mac_display") or source.get("mac"))
    name = _name(source.get("ap_name") or source.get("name"))
    if mac:
        matches = [row for row in existing if _mac(row.get("ap_mac_norm") or row.get("ap_mac_display")) == mac]
        if len(matches) == 1:
            return IdentityMatch("matched", _ap_entity_id(matches[0]), "mac_exact")
        if len(matches) > 1:
            return IdentityMatch("conflict", method="mac_exact", warning="同一 MAC 对应多个正式 AP")
    if name:
        matches = [row for row in existing if _name(row.get("ap_name")) == name]
        if len(matches) == 1:
            current_mac = _mac(matches[0].get("ap_mac_norm") or matches[0].get("ap_mac_display"))
            if mac and current_mac and mac != current_mac:
                return IdentityMatch("conflict", method="name_exact", warning="正式 AP 名称相同但 MAC 不一致")
            return IdentityMatch("matched", _ap_entity_id(matches[0]), "name_exact")
        if len(matches) > 1:
            return IdentityMatch("conflict", method="name_exact", warning="正式 AP 名称存在多个精确候选")
    return IdentityMatch("create", method="no_exact_match")


def match_vehicle_mr(source: Mapping[str, Any], existing: Sequence[Mapping[str, Any]]) -> IdentityMatch:
    selectors = (
        ("device_id", _text(source.get("device_id")), lambda row: _text(row.get("device_id") or row.get("id"))),
        ("static_ip", _text(source.get("management_ip") or source.get("primary_address")), lambda row: _text(row.get("management_ip") or row.get("primary_address"))),
        ("mac_exact", _mac(source.get("mac") or source.get("mac_address")), lambda row: _mac(row.get("mac") or row.get("mac_address"))),
        ("name_exact", _name(source.get("name")), lambda row: _name(row.get("name"))),
    )
    matched: list[tuple[str, str]] = []
    for method, expected, getter in selectors:
        if not expected:
            continue
        ids = {_mr_entity_id(row) for row in existing if getter(row) == expected}
        if len(ids) > 1:
            return IdentityMatch("conflict", method=method, warning=f"{method} 对应多个车载 MR")
        if ids:
            matched.append((method, next(iter(ids))))
    entity_ids = {entity_id for _method, entity_id in matched}
    if len(entity_ids) > 1:
        return IdentityMatch("conflict", method="cross_key", warning="MR 的 ID、静态 IP、MAC 或名称指向不同实体")
    if matched:
        return IdentityMatch("matched", matched[0][1], matched[0][0])
    return IdentityMatch("create", method="no_exact_match")


def import_policy_rows() -> list[dict[str, Any]]:
    return [
        {"entity_type": "ap", "field_name": "ap_name", "priority": ["existing_database", "official_point_table", "ap_extension", "ac_fit_ap", "ac_mesh_link"], "runtime_only": False, "note": "运行时名称只作为候选，不自动覆盖正式名称。"},
        {"entity_type": "ap", "field_name": "ap_mac", "priority": ["existing_database", "official_point_table", "ap_extension", "ac_fit_ap", "ac_mesh_link", "online_mr"], "runtime_only": False, "note": "允许标准化，不允许推断。"},
        {"entity_type": "ap", "field_name": "management_ip", "priority": ["ac_fit_ap"], "runtime_only": True, "note": "FIT-AP IP 可能由 DHCP 分配，不作为正式 AP 身份。"},
        {"entity_type": "ap", "field_name": "location", "priority": ["existing_database", "official_point_table", "ap_extension", "manual_override"], "runtime_only": False, "note": "不从当前关联 AP 或名称推断正式位置。"},
        {"entity_type": "mr", "field_name": "identity", "priority": ["device_id", "static_ip", "mac_exact", "name_exact"], "runtime_only": False, "note": "多个键指向不同实体时必须冲突。"},
    ]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _name(value: Any) -> str:
    return " ".join(_text(value).split()).casefold()


def _mac(value: Any) -> str:
    return normalize_ap_mac(value).normalized


def _ap_entity_id(row: Mapping[str, Any]) -> str:
    value = _text(row.get("id"))
    return value if value.startswith("ap:") else f"ap:{value}"


def _mr_entity_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("device_uuid") or row.get("id"))


__all__ = [
    "BASE_DATA_WRITE_ENV",
    "BLOCKING_ISSUE_CODES",
    "IdentityMatch",
    "SOURCE_PRIORITIES",
    "field_action",
    "import_policy_rows",
    "is_blocking_issue",
    "is_runtime_field",
    "match_trackside_ap",
    "match_vehicle_mr",
]
