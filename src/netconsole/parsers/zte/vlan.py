from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")

ZTE_VLAN_PARSER_VERSION = "zte-zxr10-vlan.v1"
VLAN_MIN = 1
VLAN_MAX = 4094
MAX_EXPANDED_INTERFACES = 512
_INTERFACE_PREFIX = r"(?:gei|sci|xgei|xgeis|cgei|xxvgei|xlgei)"
_INTERFACE_RE = re.compile(
    rf"(?P<name>{_INTERFACE_PREFIX}-[A-Za-z0-9_.:-]+(?:/[A-Za-z0-9_.:-]+)*/"
    r"(?P<start>\d+)(?:-(?P<end>\d+))?)",
    re.IGNORECASE,
)
_INTERFACE_NAME_RE = re.compile(
    rf"^{_INTERFACE_PREFIX}-[A-Za-z0-9_.:/-]+$",
    re.IGNORECASE,
)
_UNSUPPORTED_MARKERS = (
    "invalid command",
    "unrecognized command",
    "incomplete command",
    "ambiguous command",
    "permission denied",
)
_STABLE_FIELDS = (
    "port_mode",
    "port_status",
    "pvid",
    "native_vlan",
    "tagged_vlans",
    "untagged_vlans",
)


@dataclass(frozen=True)
class ZteVlanParseResult(Generic[T]):
    value: T
    warnings: tuple[str, ...] = ()
    status: str = "OK"
    parser_version: str = ZTE_VLAN_PARSER_VERSION


@dataclass(frozen=True)
class ZteInterfaceVlanMergeResult:
    interfaces: list[dict[str, object | None]]
    warnings: tuple[dict[str, object | None], ...]
    stats: dict[str, int]


def parse_switchvlan_running_config(
    raw: str,
) -> ZteVlanParseResult[list[dict[str, object | None]]]:
    text = _normalize_text(raw)
    if _unsupported(text):
        return ZteVlanParseResult([], ("设备不支持 show running-config switchvlan",), "UNSUPPORTED")
    header_seen = bool(re.search(r"(?mi)^\s*switchvlan-configuration\s*$", text))
    rows: list[dict[str, object | None]] = []
    warnings: list[str] = []
    current: dict[str, object | None] | None = None
    recognized_lines = 0

    def finish() -> None:
        nonlocal current
        if current is not None:
            current["tagged_vlans"] = _sorted_vlan_strings(
                current.get("tagged_vlans")
            )
            current["untagged_vlans"] = _sorted_vlan_strings(
                current.get("untagged_vlans")
            )
            rows.append(current)
        current = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        interface_match = re.fullmatch(
            rf"interface\s+({_INTERFACE_PREFIX}-[A-Za-z0-9_.:/-]+)",
            line,
            re.IGNORECASE,
        )
        if interface_match:
            finish()
            interface_name = interface_match.group(1)
            current = {
                "interface_name": interface_name,
                "normalized_name": interface_name.casefold(),
                "port_mode": None,
                "port_status": None,
                "pvid": None,
                "native_vlan": None,
                "tagged_vlans": [],
                "untagged_vlans": [],
                "pvid_source": None,
            }
            recognized_lines += 1
            continue
        if line == "$":
            finish()
            continue
        if current is None or not line or line.startswith("!"):
            continue
        mode_match = re.fullmatch(
            r"switchport\s+mode\s+(access|trunk|hybrid)",
            line,
            re.IGNORECASE,
        )
        if mode_match:
            mode = mode_match.group(1).casefold()
            current["port_mode"] = mode
            current["port_status"] = mode
            recognized_lines += 1
            continue
        native_match = re.fullmatch(
            r"switchport\s+hybrid\s+native\s+vlan\s+(\d+)",
            line,
            re.IGNORECASE,
        )
        if native_match:
            vlan = _valid_vlan(native_match.group(1))
            if vlan is None:
                warnings.append(
                    f"第 {line_number} 行 Native VLAN 超出 1-4094: {line}"
                )
            else:
                value = str(vlan)
                current["native_vlan"] = value
                current["pvid"] = value
                current["pvid_source"] = "show_running_config_switchvlan"
                recognized_lines += 1
            continue
        trunk_native_match = re.fullmatch(
            r"switchport\s+trunk\s+native\s+vlan\s+(\d+)",
            line,
            re.IGNORECASE,
        )
        if trunk_native_match:
            vlan = _valid_vlan(trunk_native_match.group(1))
            if vlan is None:
                warnings.append(
                    f"第 {line_number} 行 Trunk Native VLAN 超出 1-4094: {line}"
                )
            else:
                current["native_vlan"] = str(vlan)
                recognized_lines += 1
            continue
        access_match = re.fullmatch(
            r"switchport\s+access\s+vlan\s+(\d+)",
            line,
            re.IGNORECASE,
        )
        if access_match:
            vlan = _valid_vlan(access_match.group(1))
            if vlan is None:
                warnings.append(
                    f"第 {line_number} 行 Access VLAN 超出 1-4094: {line}"
                )
            else:
                value = str(vlan)
                current["pvid"] = value
                current["untagged_vlans"] = [
                    *_vlan_list(current.get("untagged_vlans")),
                    value,
                ]
                current["pvid_source"] = "show_running_config_switchvlan"
                recognized_lines += 1
            continue
        trunk_match = re.fullmatch(
            r"switchport\s+trunk\s+vlan\s+(.+)",
            line,
            re.IGNORECASE,
        )
        if trunk_match:
            vlans, vlan_warnings = expand_vlan_expression(trunk_match.group(1))
            warnings.extend(
                f"第 {line_number} 行 {warning}" for warning in vlan_warnings
            )
            current["tagged_vlans"] = [
                *_vlan_list(current.get("tagged_vlans")),
                *(str(vlan) for vlan in vlans),
            ]
            recognized_lines += 1
            continue
        member_match = re.fullmatch(
            r"switchport\s+hybrid\s+vlan\s+(.+?)\s+(tag|untag)",
            line,
            re.IGNORECASE,
        )
        if member_match:
            vlans, vlan_warnings = expand_vlan_expression(member_match.group(1))
            warnings.extend(
                f"第 {line_number} 行 {warning}" for warning in vlan_warnings
            )
            field = (
                "tagged_vlans"
                if member_match.group(2).casefold() == "tag"
                else "untagged_vlans"
            )
            current[field] = [
                *_vlan_list(current.get(field)),
                *(str(vlan) for vlan in vlans),
            ]
            recognized_lines += 1
            continue
        if line.casefold().startswith("switchport "):
            warnings.append(f"第 {line_number} 行存在未识别 switchport 语法: {line}")
    finish()
    if rows:
        return ZteVlanParseResult(rows, tuple(warnings), "OK")
    if header_seen:
        return ZteVlanParseResult([], tuple(warnings), "EMPTY")
    if recognized_lines == 0:
        warnings.append("未找到 switchvlan-configuration 或接口配置块")
    return ZteVlanParseResult([], tuple(warnings), "NOT_RECOGNIZED")


def parse_vlan_table(
    raw: str,
) -> ZteVlanParseResult[list[dict[str, object | None]]]:
    text = _normalize_text(raw)
    if _unsupported(text):
        return ZteVlanParseResult([], ("设备不支持 show vlan",), "UNSUPPORTED")
    lines = text.splitlines()
    header_index = -1
    starts: tuple[int, int, int, int, int] | None = None
    for index, line in enumerate(lines):
        lowered = line.casefold()
        positions = tuple(
            lowered.find(label)
            for label in ("vlan", "name", "pvidports", "untagports", "tagports")
        )
        if all(position >= 0 for position in positions) and list(positions) == sorted(
            positions
        ):
            header_index = index
            starts = positions
            break
    if starts is None:
        return ZteVlanParseResult([], ("未找到 show vlan 表头列",), "NOT_RECOGNIZED")

    warnings: list[str] = []
    rows: list[dict[str, object | None]] = []
    current: dict[str, object | None] | None = None
    vlan_start, name_start, pvid_start, untag_start, tag_start = starts
    boundaries = (vlan_start, name_start, pvid_start, untag_start, tag_start)

    def finish() -> None:
        nonlocal current
        if current is not None:
            for field in ("pvid_ports", "untagged_ports", "tagged_ports"):
                current[field] = _unique_interfaces(current.get(field))
            rows.append(current)
        current = None

    for line_number, raw_line in enumerate(
        lines[header_index + 1 :], start=header_index + 2
    ):
        if not raw_line.strip() or set(raw_line.strip()) <= {"-", "=", " "}:
            continue
        padded = raw_line.ljust(tag_start + 1)
        cells = (
            padded[boundaries[0] : boundaries[1]].strip(),
            padded[boundaries[1] : boundaries[2]].strip(),
            padded[boundaries[2] : boundaries[3]].strip(),
            padded[boundaries[3] : boundaries[4]].strip(),
            padded[boundaries[4] :].strip(),
        )
        vlan_text, name, pvid_cell, untag_cell, tag_cell = cells
        if vlan_text:
            if not vlan_text.isdigit():
                if re.search(r"[>#]\s*$", raw_line):
                    continue
                warnings.append(f"第 {line_number} 行 VLAN 列无法识别: {vlan_text}")
                continue
            vlan_id = _valid_vlan(vlan_text)
            if vlan_id is None:
                warnings.append(f"第 {line_number} 行 VLAN 超出 1-4094: {vlan_text}")
                continue
            finish()
            current = {
                "vlan_id": vlan_id,
                "name": name,
                "pvid_ports": [],
                "untagged_ports": [],
                "tagged_ports": [],
            }
        elif current is None:
            continue
        for field, cell in (
            ("pvid_ports", pvid_cell),
            ("untagged_ports", untag_cell),
            ("tagged_ports", tag_cell),
        ):
            ports, port_warnings = expand_interface_list(cell)
            current[field] = [*_interface_list(current.get(field)), *ports]
            warnings.extend(
                f"第 {line_number} 行 {field}: {warning}"
                for warning in port_warnings
            )
    finish()
    return ZteVlanParseResult(
        rows,
        tuple(warnings),
        "OK" if rows else "EMPTY",
    )


def expand_interface_list(value: str) -> tuple[list[str], tuple[str, ...]]:
    text = str(value or "").strip()
    if not text:
        return [], ()
    interfaces: list[str] = []
    warnings: list[str] = []
    consumed: list[tuple[int, int]] = []
    for match in _INTERFACE_RE.finditer(text):
        consumed.append(match.span())
        expression = match.group("name")
        start = int(match.group("start"))
        end_text = match.group("end")
        if end_text is None:
            interfaces.append(expression)
            continue
        end = int(end_text)
        if start > end:
            warnings.append(f"接口范围倒序，已忽略: {expression}")
            continue
        count = end - start + 1
        if count > MAX_EXPANDED_INTERFACES:
            warnings.append(
                f"接口范围超过 {MAX_EXPANDED_INTERFACES} 条安全上限，已忽略: {expression}"
            )
            continue
        prefix = expression[: expression.rfind("/") + 1]
        interfaces.extend(f"{prefix}{port}" for port in range(start, end + 1))
    remainder = list(text)
    for start, end in consumed:
        remainder[start:end] = " " * (end - start)
    unknown = "".join(remainder)
    unknown = re.sub(r"[\s,;]+", "", unknown)
    if unknown:
        warnings.append(f"未识别接口表达式片段: {unknown}")
    return _unique_interfaces(interfaces), tuple(warnings)


def expand_vlan_expression(value: str) -> tuple[list[int], tuple[str, ...]]:
    text = re.sub(r"\bto\b", "-", str(value or ""), flags=re.IGNORECASE)
    parts = [part for part in re.split(r"[\s,;]+", text.strip()) if part]
    result: set[int] = set()
    warnings: list[str] = []
    for part in parts:
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if match is None:
            warnings.append(f"未识别 VLAN 表达式: {part}")
            continue
        start = _valid_vlan(match.group(1))
        end = _valid_vlan(match.group(2) or match.group(1))
        if start is None or end is None:
            warnings.append(f"VLAN 超出 1-4094: {part}")
            continue
        if start > end:
            warnings.append(f"VLAN 范围倒序，已忽略: {part}")
            continue
        result.update(range(start, end + 1))
    return sorted(result), tuple(warnings)


def merge_interface_vlan_facts(
    interfaces: list[dict[str, object | None]],
    switchvlan_result: ZteVlanParseResult[list[dict[str, object | None]]] | None,
    vlan_table_result: ZteVlanParseResult[list[dict[str, object | None]]] | None,
    previous_interfaces: list[dict[str, object | None]] | None = None,
) -> ZteInterfaceVlanMergeResult:
    switch_rows = (
        switchvlan_result.value
        if switchvlan_result is not None and switchvlan_result.status == "OK"
        else []
    )
    vlan_rows = (
        vlan_table_result.value
        if vlan_table_result is not None and vlan_table_result.status == "OK"
        else []
    )
    switch_by_interface = {
        _normalize_interface(row.get("interface_name")): row
        for row in switch_rows
        if _normalize_interface(row.get("interface_name"))
    }
    table_by_interface, table_warnings = _vlan_table_interface_facts(vlan_rows)
    previous_by_interface = {
        _normalize_interface(row.get("interface_name")): row
        for row in (previous_interfaces or [])
        if _normalize_interface(row.get("interface_name"))
    }
    warnings: list[dict[str, object | None]] = list(table_warnings)
    stats = {
        "switchvlan_pvid_count": 0,
        "vlan_table_pvid_count": 0,
        "consistent_count": 0,
        "switchvlan_only_count": 0,
        "vlan_only_count": 0,
        "conflict_count": 0,
        "inherited_count": 0,
    }
    merged: list[dict[str, object | None]] = []
    for interface in interfaces:
        item = dict(interface)
        key = _normalize_interface(item.get("interface_name"))
        switch = switch_by_interface.get(key, {})
        table = table_by_interface.get(key, {})
        previous = previous_by_interface.get(key, {})
        interface_warnings: list[dict[str, object | None]] = []
        switch_pvid = _vlan_text(switch.get("pvid"))
        table_pvid = _vlan_text(table.get("pvid"))
        if switch_pvid:
            stats["switchvlan_pvid_count"] += 1
        if table_pvid:
            stats["vlan_table_pvid_count"] += 1
        if switch_pvid and table_pvid:
            if switch_pvid == table_pvid:
                stats["consistent_count"] += 1
            else:
                stats["conflict_count"] += 1
                conflict = {
                    "code": "ZTE_PVID_SOURCE_CONFLICT",
                    "interface_name": item.get("interface_name"),
                    "switchvlan_pvid": switch_pvid,
                    "vlan_table_pvid": table_pvid,
                    "selected_pvid": switch_pvid,
                    "selected_source": "show_running_config_switchvlan",
                }
                warnings.append(conflict)
                interface_warnings.append(conflict)
        elif switch_pvid:
            stats["switchvlan_only_count"] += 1
        elif table_pvid:
            stats["vlan_only_count"] += 1

        current_fields: dict[str, object | None] = {
            "port_mode": switch.get("port_mode"),
            "port_status": switch.get("port_status"),
            "pvid": switch_pvid or table_pvid,
            "native_vlan": switch.get("native_vlan"),
            "tagged_vlans": (
                _vlan_list(switch.get("tagged_vlans"))
                or _vlan_list(table.get("tagged_vlans"))
            ),
            "untagged_vlans": (
                _vlan_list(switch.get("untagged_vlans"))
                or _vlan_list(table.get("untagged_vlans"))
            ),
        }
        inherited_fields: list[str] = []
        for field in _STABLE_FIELDS:
            if _has_stable_value(current_fields.get(field)):
                continue
            prior_value = _previous_stable_value(previous.get(field), field)
            if _has_stable_value(prior_value):
                current_fields[field] = prior_value
                inherited_fields.append(field)
        if inherited_fields:
            stats["inherited_count"] += 1
            preserved = {
                "code": "ZTE_VLAN_STABLE_FIELDS_PRESERVED",
                "interface_name": item.get("interface_name"),
                "fields": inherited_fields,
                "reason": "本次 VLAN 命令未确认这些稳定配置字段",
            }
            warnings.append(preserved)
            interface_warnings.append(preserved)

        selected_pvid = _vlan_text(current_fields.get("pvid"))
        pvid_source: str | None
        if switch_pvid:
            pvid_source = "show_running_config_switchvlan"
        elif table_pvid:
            pvid_source = "show_vlan_pvid_ports"
        elif selected_pvid:
            pvid_source = "previous_snapshot"
        else:
            pvid_source = None
        current_confirmed = bool(switch or table)
        if current_confirmed and inherited_fields:
            config_status = "current_with_inherited_fields"
        elif current_confirmed:
            config_status = "current"
        elif inherited_fields:
            config_status = "inherited"
        else:
            config_status = "unavailable"
        item.update(current_fields)
        item["pvid_source"] = pvid_source
        item["pvid_verified"] = bool(
            switch_pvid and table_pvid and switch_pvid == table_pvid
        )
        item["vlan_config_status"] = config_status
        item["vlan_config_collected_at"] = (
            item.get("collected_at")
            if current_confirmed
            else previous.get("vlan_config_collected_at")
            or previous.get("collected_at")
        )
        item["vlan_warnings"] = interface_warnings
        item["vlan"] = _vlan_summary(item)
        merged.append(item)
    return ZteInterfaceVlanMergeResult(merged, tuple(warnings), stats)


def serialize_vlan_list(value: object) -> str:
    return json.dumps(_vlan_list(value), ensure_ascii=False, separators=(",", ":"))


def serialize_vlan_warnings(value: object) -> str:
    rows = value if isinstance(value, list) else []
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _vlan_table_interface_facts(
    rows: list[dict[str, object | None]],
) -> tuple[
    dict[str, dict[str, object | None]],
    tuple[dict[str, object | None], ...],
]:
    result: dict[str, dict[str, object | None]] = {}
    warnings: list[dict[str, object | None]] = []
    for row in rows:
        vlan = _vlan_text(row.get("vlan_id"))
        if not vlan:
            continue
        for field, target in (
            ("pvid_ports", "pvid"),
            ("untagged_ports", "untagged_vlans"),
            ("tagged_ports", "tagged_vlans"),
        ):
            for interface_name in _interface_list(row.get(field)):
                key = _normalize_interface(interface_name)
                fact = result.setdefault(
                    key,
                    {
                        "interface_name": interface_name,
                        "pvid": None,
                        "tagged_vlans": [],
                        "untagged_vlans": [],
                    },
                )
                if target == "pvid":
                    old_pvid = _vlan_text(fact.get("pvid"))
                    if old_pvid and old_pvid != vlan:
                        warnings.append(
                            {
                                "code": "ZTE_VLAN_TABLE_MULTIPLE_PVID",
                                "interface_name": interface_name,
                                "first_pvid": old_pvid,
                                "second_pvid": vlan,
                            }
                        )
                        continue
                    fact["pvid"] = vlan
                else:
                    fact[target] = _sorted_vlan_strings(
                        [*_vlan_list(fact.get(target)), vlan]
                    )
    return result, tuple(warnings)


def _normalize_text(raw: str) -> str:
    return (
        str(raw or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\x08", "")
        .replace("--More--", "")
        .replace("---- More ----", "")
    )


def _unsupported(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in _UNSUPPORTED_MARKERS)


def _valid_vlan(value: object) -> int | None:
    try:
        vlan = int(str(value))
    except (TypeError, ValueError):
        return None
    return vlan if VLAN_MIN <= vlan <= VLAN_MAX else None


def _normalize_interface(value: object) -> str:
    name = str(value or "").strip()
    return name.casefold() if _INTERFACE_NAME_RE.fullmatch(name) else ""


def _interface_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _vlan_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                value = []
        elif text:
            value = [part for part in re.split(r"[\s,;]+", text) if part]
        else:
            value = []
    if not isinstance(value, (list, tuple, set)):
        return []
    return _sorted_vlan_strings(value)


def _sorted_vlan_strings(value: object) -> list[str]:
    values = {
        vlan
        for item in (value if isinstance(value, (list, tuple, set)) else [])
        if (vlan := _valid_vlan(item)) is not None
    }
    return [str(vlan) for vlan in sorted(values)]


def _unique_interfaces(values: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _interface_list(values):
        key = item.casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _vlan_text(value: object) -> str | None:
    vlan = _valid_vlan(value)
    return str(vlan) if vlan is not None else None


def _has_stable_value(value: object) -> bool:
    if isinstance(value, list):
        return bool(value)
    return value not in (None, "")


def _previous_stable_value(value: object, field: str) -> object:
    if field in {"tagged_vlans", "untagged_vlans"}:
        return _vlan_list(value)
    if field in {"pvid", "native_vlan"}:
        return _vlan_text(value)
    return value


def _vlan_summary(item: dict[str, object | None]) -> str | None:
    parts: list[str] = []
    pvid = _vlan_text(item.get("pvid"))
    native = _vlan_text(item.get("native_vlan"))
    if pvid and native == pvid:
        parts.append(f"Native/PVID {pvid}")
    elif pvid:
        parts.append(f"PVID {pvid}")
        if native:
            parts.append(f"Native {native}")
    elif native:
        parts.append(f"Native {native}")
    tagged = _vlan_list(item.get("tagged_vlans"))
    untagged = _vlan_list(item.get("untagged_vlans"))
    if tagged:
        parts.append(f"Tagged {_compress_vlan_list(tagged)}")
    if untagged:
        parts.append(f"Untagged {_compress_vlan_list(untagged)}")
    return "；".join(parts) or None


def _compress_vlan_list(values: list[str]) -> str:
    numbers = sorted(
        {
            vlan
            for value in values
            if (vlan := _valid_vlan(value)) is not None
        }
    )
    if not numbers:
        return ""
    ranges: list[str] = []
    start = previous = numbers[0]
    for vlan in numbers[1:]:
        if vlan == previous + 1:
            previous = vlan
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = vlan
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


__all__ = [
    "MAX_EXPANDED_INTERFACES",
    "ZTE_VLAN_PARSER_VERSION",
    "ZteInterfaceVlanMergeResult",
    "ZteVlanParseResult",
    "expand_interface_list",
    "expand_vlan_expression",
    "merge_interface_vlan_facts",
    "parse_switchvlan_running_config",
    "parse_vlan_table",
    "serialize_vlan_list",
    "serialize_vlan_warnings",
]
