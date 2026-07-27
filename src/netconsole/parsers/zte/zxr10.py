from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from netconsole.models.trackside_switch import (
    ParseStatus,
    ParserVerificationStatus,
)
from netconsole.utils.text_encoding import (
    PAGER_PROMPT_RE,
    clean_interactive_device_text,
)

T = TypeVar("T")

PROMPT_OR_COMMAND_RE = re.compile(
    r"^\s*(?:[A-Za-z0-9_.:/()-]+(?:\(config[^)]*\))?[>#]\s*)?"
    r"show\s+\S+",
    re.IGNORECASE,
)
INTERFACE_NAME_RE = re.compile(
    r"^(?:xgei|xxvgei|xlgei|cgei)-\d+(?:/\d+){3}(?::\d+)?$|"
    r"^sci-[A-Za-z0-9/.:_-]+$|^mgmt_eth$",
    re.IGNORECASE,
)
TRACKSIDE_PHYSICAL_PREFIXES = ("xgei-", "xxvgei-", "xlgei-", "cgei-")
MISSING_VALUES = {"", "n/a", "na", "---", "unsupported", "offline"}
UNSUPPORTED_MARKERS = (
    "invalid command",
    "unrecognized command",
    "% invalid input",
    "invalid input",
    "incomplete command",
    "ambiguous command",
)
ZTE_PARSER_VERSION = "zte-zxr10-5960x-es-v2.document-sample.v1"
ZTE_VERIFICATION_STATUS = ParserVerificationStatus.DOCUMENT_SAMPLE_ONLY.value


@dataclass(frozen=True)
class ZteParseResult(Generic[T]):
    value: T
    warnings: tuple[str, ...] = field(default_factory=tuple)
    status: str = "OK"

    @property
    def parser_version(self) -> str:
        return ZTE_PARSER_VERSION

    @property
    def verification_status(self) -> str:
        if self.status == ParseStatus.SAMPLE_REQUIRED.value:
            return ParserVerificationStatus.SAMPLE_REQUIRED.value
        return ZTE_VERIFICATION_STATUS


def normalize_zte_cli_text(raw: object, *, remove_pager: bool = True) -> str:
    return clean_interactive_device_text(raw, remove_pager=remove_pager)


def parse_device_identity(raw: str) -> ZteParseResult[dict[str, object | None]]:
    text = normalize_zte_cli_text(raw)
    warnings: list[str] = []
    if not re.search(r"\bZTE\b", text, re.IGNORECASE) or not re.search(
        r"\bZXR10\b", text, re.IGNORECASE
    ):
        return ZteParseResult({}, ("输出未识别为 ZTE ZXR10 show version",), "NOT_RECOGNIZED")
    if not (
        re.search(r"\b(?:59X|5960X)-ES\b", text, re.IGNORECASE)
        or re.search(r"\b5960X-[A-Za-z0-9-]+-ES\b", text, re.IGNORECASE)
    ):
        return ZteParseResult(
            {},
            ("ZTE ZXR10 型号不属于当前支持的 5960X-ES V2 范围",),
            "NOT_RECOGNIZED",
        )

    version_match = re.search(
        r"Version\s*:\s*(?:(?:ZXR10\s+)?(?:59X|5960X)-ES\s+)?"
        r"(?P<version>V\d+(?:\.\d+){3}(?:B\d+)?)",
        text,
        re.IGNORECASE,
    )
    build_match = re.search(r"(?mi)^\s*Built on\s+(.+?)\s*$", text)
    image_match = re.search(r"(?mi)^\s*System image file is\s*<([^>]+)>", text)
    board_match = re.search(r"(?mi)^\s*Board Name\s*:\s*(.+?)\s*$", text)
    uptime_match = re.search(
        r"(?:System uptime|Uptime)\s+is\s+"
        r"(?:(\d+)\s+day\(s\),?\s*)?"
        r"(?:(\d+)\s+hour\(s\),?\s*)?"
        r"(?:(\d+)\s+minute\(s\),?\s*)?"
        r"(?:(\d+)\s+second\(s\))?",
        text,
        re.IGNORECASE,
    )
    software_version = version_match.group("version").upper() if version_match else None
    if not software_version:
        warnings.append("未解析到软件版本")
    base_match = re.match(r"(V\d+(?:\.\d+){3})", software_version or "", re.IGNORECASE)
    uptime_seconds = None
    if uptime_match:
        days, hours, minutes, seconds = (
            int(value or 0) for value in uptime_match.groups()
        )
        uptime_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
    else:
        warnings.append("未解析到运行时长")
    board_name = board_match.group(1).strip() if board_match else None
    model = "5960X-ES"
    if board_name and re.search(r"5960X-[A-Za-z0-9-]+-ES", board_name, re.IGNORECASE):
        model = board_name
    return ZteParseResult(
        {
            "vendor": "ZTE",
            "platform": "ZXR10",
            "platform_family": "ZXR10",
            "product_family": "5960X-ES",
            "model": model,
            "software_version": software_version,
            "build_version": software_version,
            "base_version": base_match.group(1).upper() if base_match else None,
            "build_time": build_match.group(1).strip() if build_match else None,
            "image_file": image_match.group(1).strip() if image_match else None,
            "uptime_seconds": uptime_seconds,
            "uptime": str(uptime_seconds) if uptime_seconds is not None else None,
            "board_name": board_name,
            "raw_command": "show version",
            **_parser_metadata(ParseStatus.PARSED, warnings=warnings),
        },
        tuple(warnings),
    )


def parse_interfaces(raw: str) -> ZteParseResult[list[dict[str, object | None]]]:
    text = normalize_zte_cli_text(raw)
    rows: list[dict[str, object | None]] = []
    warnings: list[str] = []
    header_seen = False
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if re.match(
            r"^Interface\s+Attribute\s+Mode\s+BW\s+Admin\s+Phy\s+Prot(?:\s+Description)?$",
            line,
            re.IGNORECASE,
        ):
            header_seen = True
            continue
        if not line or PROMPT_OR_COMMAND_RE.match(line) or PAGER_PROMPT_RE.search(line):
            continue
        parts = line.split(None, 7)
        if not parts or not INTERFACE_NAME_RE.fullmatch(parts[0]):
            continue
        if len(parts) < 7:
            warnings.append(f"第 {line_number} 行接口字段不足")
            continue
        admin, physical, protocol = (value.casefold() for value in parts[4:7])
        oper_status = _oper_status(admin, physical, protocol)
        media = parts[1]
        name = parts[0]
        rows.append(
            {
                "interface_name": name,
                "normalized_name": name.casefold(),
                "media_attribute": media,
                "media_type": media,
                "duplex_mode": parts[2],
                "duplex": parts[2],
                "bandwidth": parts[3],
                "speed": parts[3],
                "admin_status": admin,
                "physical_status": physical,
                "protocol_status": protocol,
                "admin_up": admin == "up",
                "physical_up": physical == "up",
                "protocol_up": protocol == "up",
                "oper_status": oper_status,
                "link_status": oper_status,
                "description": parts[7].strip() if len(parts) == 8 else "",
                "interface_type": (
                    "二层"
                    if name.casefold().startswith(TRACKSIDE_PHYSICAL_PREFIXES)
                    else "逻辑/管理"
                ),
                "port_status": media.casefold(),
                "trackside_candidate": name.casefold().startswith(
                    TRACKSIDE_PHYSICAL_PREFIXES
                ),
                "raw_line": raw_line,
                **_parser_metadata(ParseStatus.PARSED),
            }
        )
    if not header_seen:
        warnings.append("未找到 show interface brief 表头")
    status = "OK" if rows else "EMPTY"
    return ZteParseResult(rows, tuple(warnings), status)


def parse_interface_detail(raw: str) -> ZteParseResult[dict[str, object | None]]:
    text = normalize_zte_cli_text(raw)
    warnings: list[str] = []
    header = re.search(
        r"(?mi)^\s*(?P<name>[A-Za-z][A-Za-z0-9/.:_-]+)\s+is\s+"
        r"(?P<state>up|down),\s*ifindex\s*:\s*(?P<ifindex>\d+)",
        text,
    )
    if not header:
        return ZteParseResult({}, ("未找到接口详情起始行",), "PARSE_FAILED")
    item: dict[str, object | None] = {
        "interface_name": header.group("name"),
        "normalized_name": header.group("name").casefold(),
        "ifindex": int(header.group("ifindex")),
        "physical_status": header.group("state").casefold(),
        "link_status": header.group("state").upper(),
        "raw_line": header.group(0),
        **_parser_metadata(ParseStatus.PARSED),
    }
    line_protocol = re.search(
        r"(?mi)^\s*Line protocol is\s+(up|down),"
        r"\s*IPv4 protocol is\s+(up|down),\s*IPv6 protocol is\s+(up|down),?",
        text,
    )
    if line_protocol:
        item.update(
            {
                "protocol_status": line_protocol.group(1).casefold(),
                "ipv4_protocol_status": line_protocol.group(2).casefold(),
                "ipv6_protocol_status": line_protocol.group(3).casefold(),
            }
        )
    else:
        warnings.append("未解析到 Line protocol 状态")
    scalar_patterns: tuple[tuple[str, str], ...] = (
        ("detected_status", r"(?mi)^\s*detected status is\s+(.+?)\s*$"),
        ("last_physical_up_time", r"(?mi)^\s*Last (?:physical|line protocol) up time\s*:\s*(.+?)\s*$"),
        ("last_physical_down_time", r"(?mi)^\s*Last (?:physical|line protocol) down time\s*:\s*(.+?)\s*$"),
        ("port_media", r"(?mi)^\s*The port is\s+(.+?)\s*$"),
        ("negotiation", r"(?mi)^\s*Negotiation\s+(.+?)\s*$"),
        ("bandwidth", r"(?mi)^\s*BW\s+(.+?)\s*$"),
        ("description", r"(?mi)^\s*Description\s*:\s*(.+?)\s*$"),
    )
    for field_name, pattern in scalar_patterns:
        match = re.search(pattern, text)
        if match:
            item[field_name] = match.group(1).strip()
    item["speed"] = item.get("bandwidth")
    mac_match = re.search(
        r"(?mi)^\s*Hardware is .+?,\s*address is\s+([0-9A-Fa-f.:-]+)\s*$", text
    )
    if mac_match:
        item["mac_address"] = _normalize_mac(mac_match.group(1))
    input_match = re.search(r"(?mi)^\s*Input\s*:\s*(.+?)\s*$", text)
    output_match = re.search(r"(?mi)^\s*Output\s*:\s*(.+?)\s*$", text)
    item["input_rate"] = input_match.group(1).strip() if input_match else None
    item["output_rate"] = output_match.group(1).strip() if output_match else None
    counter_fields = {
        "crc_error": "In_CRC_ERROR",
        "drop_events": "In_DropEvents",
        "symbol_error": "In_SymbolError",
        "mac_rx_error": "In_MacRxError",
    }
    for field_name, label in counter_fields.items():
        match = re.search(rf"\b{re.escape(label)}\s+(\S+)", text, re.IGNORECASE)
        item[field_name] = _optional_number(match.group(1)) if match else None
    item["media_type"] = item.get("port_media")
    item["warnings"] = list(warnings)
    return ZteParseResult(item, tuple(warnings))


def parse_optical_summary(raw: str) -> ZteParseResult[list[dict[str, object | None]]]:
    text = normalize_zte_cli_text(raw)
    rows: list[dict[str, object | None]] = []
    warnings: list[str] = []
    header_seen = False
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if re.match(
            r"^Interface\s+Type\s+Wavelength\s+RxPower\(dBm\)\s+"
            r"TxPower\(dBm\)\s+Status$",
            line,
            re.IGNORECASE,
        ):
            header_seen = True
            continue
        if not line or PROMPT_OR_COMMAND_RE.match(line):
            continue
        parts = line.split()
        if not parts or not INTERFACE_NAME_RE.fullmatch(parts[0]):
            continue
        interface_name = parts[0]
        if len(parts) >= 2 and parts[1].casefold() == "offline":
            rows.append(
                {
                    "interface_name": interface_name,
                    "module_online": False,
                    "module_present": False,
                    "dom_supported": False,
                    "vendor_status": "offline",
                    "normalized_status": "OFFLINE",
                    "status": "offline",
                    "raw_output": "",
                    **_parser_metadata(ParseStatus.PARSED),
                }
            )
            continue
        if len(parts) < 6:
            warnings.append(f"第 {line_number} 行光模块摘要字段不足")
            continue
        rx_value, rx_low, rx_high = _parse_power_threshold(parts[-3])
        tx_value, tx_low, tx_high = _parse_power_threshold(parts[-2])
        vendor_status = parts[-1]
        normalized_status = _normalize_optical_status(
            vendor_status, rx_value, tx_value
        )
        rows.append(
            {
                "interface_name": interface_name,
                "module_online": True,
                "module_present": True,
                "dom_supported": any(
                    value is not None for value in (rx_value, tx_value)
                ),
                "module_type": " ".join(parts[1:-4]),
                "module_model": " ".join(parts[1:-4]),
                "wavelength_nm": _optional_number(parts[-4]),
                "wavelength": _optional_number(parts[-4]),
                "rx_power_dbm": rx_value,
                "rx_power": rx_value,
                "rx_low_threshold_dbm": rx_low,
                "rx_high_threshold_dbm": rx_high,
                "rx_low_alarm": rx_low,
                "rx_high_alarm": rx_high,
                "tx_power_dbm": tx_value,
                "tx_power": tx_value,
                "tx_low_threshold_dbm": tx_low,
                "tx_high_threshold_dbm": tx_high,
                "tx_low_alarm": tx_low,
                "tx_high_alarm": tx_high,
                "vendor_status": vendor_status,
                "normalized_status": normalized_status,
                "status": normalized_status.casefold(),
                "raw_output": "",
                **_parser_metadata(ParseStatus.PARSED),
            }
        )
    if not header_seen:
        warnings.append("未找到 show opticalinfo brief 表头")
    return ZteParseResult(rows, tuple(warnings), "OK" if rows else "EMPTY")


def parse_optical_detail(
    raw: str, interface_name: str | None = None
) -> ZteParseResult[dict[str, object | None]]:
    text = normalize_zte_cli_text(raw)
    warnings: list[str] = []
    selected_interface = str(interface_name or "").strip()
    if not selected_interface:
        for line in text.splitlines():
            value = line.strip()
            if INTERFACE_NAME_RE.fullmatch(value):
                selected_interface = value
                break
    online = bool(re.search(r"The optical module is online", text, re.IGNORECASE))
    offline = bool(re.search(r"The optical module is offline|\boffline\b", text, re.IGNORECASE))
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if ":" not in line or PROMPT_OR_COMMAND_RE.match(line):
            continue
        key, value = line.split(":", 1)
        fields[_normalize_key(key)] = value.strip()
    rx_power = _number_field(fields, "measured_rx_input_power")
    tx_power = _number_field(fields, "measured_tx_output_power")
    temperature = _number_field(fields, "measured_transceiver_temperature")
    voltage_1 = _number_field(fields, "supply_voltage_1")
    voltage_2 = _number_field(fields, "supply_voltage_2")
    dom_supported = any(
        value is not None for value in (rx_power, tx_power, temperature, voltage_1, voltage_2)
    )
    if not selected_interface:
        warnings.append("未解析到光模块接口名称")
    if not online and not offline and not fields:
        return ZteParseResult({}, tuple(warnings or ["光模块详情为空"]), "EMPTY")
    status = "normal" if online else "offline" if offline else (
        "unverified" if dom_supported else "dom_unavailable"
    )
    item: dict[str, object | None] = {
        "interface_name": selected_interface,
        "module_present": not offline,
        "module_online": online,
        "dom_supported": dom_supported,
        "module_type": _text_field(fields, "transceiver_type"),
        "module_model": _text_field(fields, "vendor_pn")
        or _text_field(fields, "transceiver_type"),
        "connector": _text_field(fields, "connector_type_code"),
        "connector_type": _text_field(fields, "connector_type_code"),
        "transceiver_mode": _text_field(fields, "transceiver_mode"),
        "directionality": _text_field(fields, "directionality"),
        "ethernet_compliance": _text_field(fields, "ethernet_compliance_codes"),
        "wavelength_nm": _number_field(fields, "laser_tx_wavelength")
        or _number_field(fields, "laser_rx_wavelength"),
        "wavelength": _number_field(fields, "laser_tx_wavelength")
        or _number_field(fields, "laser_rx_wavelength"),
        "rx_power_dbm": rx_power,
        "rx_power": rx_power,
        "tx_power_dbm": tx_power,
        "tx_power": tx_power,
        "tx_bias_ma": _number_field(fields, "measured_tx_bias_current"),
        "bias_current": _number_field(fields, "measured_tx_bias_current"),
        "temperature_c": temperature,
        "temperature": temperature,
        "voltage_v": voltage_1 if voltage_1 is not None else voltage_2,
        "voltage": voltage_1 if voltage_1 is not None else voltage_2,
        "receiver_sensitivity_dbm": _number_field(fields, "receiver_sensitivity"),
        "receiver_overload_dbm": _number_field(fields, "receiver_overload"),
        "rx_alarm_high_dbm": _number_field(
            fields, "default_rx_power_prehighalarm_thresholds"
        ),
        "rx_high_alarm": _number_field(
            fields, "default_rx_power_prehighalarm_thresholds"
        ),
        "rx_alarm_low_dbm": _number_field(
            fields, "default_rx_power_prelowalarm_thresholds"
        ),
        "rx_low_alarm": _number_field(
            fields, "default_rx_power_prelowalarm_thresholds"
        ),
        "tx_alarm_high_dbm": _number_field(
            fields, "default_tx_power_prehighalarm_thresholds"
        ),
        "tx_high_alarm": _number_field(
            fields, "default_tx_power_prehighalarm_thresholds"
        ),
        "tx_alarm_low_dbm": _number_field(
            fields, "default_tx_power_prelowalarm_thresholds"
        ),
        "tx_low_alarm": _number_field(
            fields, "default_tx_power_prelowalarm_thresholds"
        ),
        "vendor_name": _text_field(fields, "vendor_name"),
        "module_vendor": _text_field(fields, "vendor_name"),
        "vendor_part_number": _text_field(fields, "vendor_pn"),
        "vendor_revision": _text_field(fields, "vendor_rev"),
        "vendor_serial_number": _text_field(fields, "vendor_sn"),
        "module_serial_number": _text_field(fields, "vendor_sn"),
        "authentication": _text_field(fields, "authentication"),
        "product_sn": _text_field(fields, "productsn"),
        "product_date": _text_field(fields, "productdate"),
        "speed": _text_field(fields, "speed"),
        "normalized_status": status.upper(),
        "status": status,
        "raw_output": "",
        **_parser_metadata(ParseStatus.PARSED, warnings=warnings),
    }
    return ZteParseResult(item, tuple(warnings))


def parse_lldp(raw: str) -> ZteParseResult[list[dict[str, object | None]]]:
    text = normalize_zte_cli_text(raw)
    lowered = text.casefold()
    if any(marker in lowered for marker in UNSUPPORTED_MARKERS):
        return ZteParseResult([], (), "COMMAND_UNSUPPORTED")
    if not text.strip():
        return ZteParseResult([], (), "NO_NEIGHBOR")
    if "lldp" in lowered and any(
        marker in lowered for marker in ("disable", "disabled", "not enabled")
    ):
        return ZteParseResult([], (), "LLDP_DISABLED")
    if any(
        marker in lowered
        for marker in ("no neighbor", "no lldp entry", "neighbor number: 0")
    ):
        return ZteParseResult([], (), "NO_NEIGHBOR")
    return ZteParseResult(
        [],
        ("ZTE LLDP 输出缺少真实 fixture，已保留原始回显，未执行结构化解析",),
        "SAMPLE_REQUIRED",
    )


def _oper_status(admin: str, physical: str, protocol: str) -> str:
    if admin == physical == protocol == "up":
        return "UP"
    if admin == "down":
        return "ADMIN_DOWN"
    if admin == "up" and physical == "down":
        return "PHYSICAL_DOWN"
    if physical == "up" and protocol == "down":
        return "PROTOCOL_DOWN"
    return "UNKNOWN"


def _optional_number(value: object) -> float | int | None:
    text = str(value or "").strip()
    if text.casefold() in MISSING_VALUES:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _parse_power_threshold(
    token: str,
) -> tuple[float | int | None, float | int | None, float | int | None]:
    match = re.match(
        r"^\s*(?P<value>.*?)"
        r"(?:/\[\s*(?P<low>[^,\]]+)\s*,\s*(?P<high>[^\]]+)\s*\])?\s*$",
        token,
    )
    if not match:
        return _optional_number(token), None, None
    return (
        _optional_number(match.group("value")),
        _optional_number(match.group("low")),
        _optional_number(match.group("high")),
    )


def _normalize_optical_status(
    vendor_status: str,
    rx_power: float | int | None,
    tx_power: float | int | None,
) -> str:
    status = str(vendor_status or "").strip().casefold()
    if status == "normal":
        return "NORMAL"
    if status == "abnormal":
        return "ABNORMAL"
    if status == "offline":
        return "OFFLINE"
    if status == "unknown":
        return "UNVERIFIED" if rx_power is not None or tx_power is not None else "DOM_UNAVAILABLE"
    return "UNVERIFIED" if rx_power is not None or tx_power is not None else "DOM_UNAVAILABLE"


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _number_field(fields: dict[str, str], name: str) -> float | int | None:
    return _optional_number(fields.get(name))


def _text_field(fields: dict[str, str], name: str) -> str | None:
    value = str(fields.get(name) or "").strip()
    return None if value.casefold() in MISSING_VALUES else value


def _normalize_mac(value: str) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", value)
    if len(compact) != 12:
        return value.strip().casefold()
    compact = compact.casefold()
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def _parser_metadata(
    parse_status: ParseStatus,
    *,
    warnings: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "warnings": list(warnings),
        "raw_output_ref": "",
        "parser_version": ZTE_PARSER_VERSION,
        "verification_status": ZTE_VERIFICATION_STATUS,
        "parse_status": parse_status.value,
    }


__all__ = [
    "TRACKSIDE_PHYSICAL_PREFIXES",
    "ZTE_PARSER_VERSION",
    "ZTE_VERIFICATION_STATUS",
    "ZteParseResult",
    "normalize_zte_cli_text",
    "parse_device_identity",
    "parse_interface_detail",
    "parse_interfaces",
    "parse_lldp",
    "parse_optical_detail",
    "parse_optical_summary",
]
