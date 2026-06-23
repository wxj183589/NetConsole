from __future__ import annotations

import re
from dataclasses import dataclass


DERIVED_WARNING_DELTA_DB = 2.01
MAINTENANCE_MARGIN_DB = 3.0

SEVERITY_RANK = {
    "unknown": 0,
    "not_collected": 0,
    "skipped": 0,
    "offline": 0,
    "no_module": 0,
    "": 0,
    "normal": 1,
    "notice": 2,
    "warning": 3,
    "alarm": 4,
    "link_abnormal": 5,
    "link_down": 5,
    "no_light": 6,
}

STATUS_COLORS = {
    "normal": "DCFCE7",
    "notice": "FEF9C3",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "link_down": "FFE4E6",
    "no_light": "E5E7EB",
    "no_module": "F3F4F6",
    "skipped": "F3F4F6",
    "offline": "E5E7EB",
    "not_collected": "F3F4F6",
    "unknown": "F3F4F6",
}

OPTICAL_STATUS_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "normal": "正常",
        "notice": "偏低关注",
        "warning": "提示告警",
        "alarm": "一般告警",
        "link_abnormal": "链路异常",
        "link_down": "链路断开",
        "no_light": "无光",
        "no_module": "无光模块",
        "skipped": "未检查",
        "not_collected": "未采集",
        "unknown": "未知",
    },
    "en": {
        "normal": "Normal",
        "notice": "Notice",
        "warning": "Warning",
        "alarm": "Alarm",
        "link_abnormal": "Link Abnormal",
        "link_down": "Link Down",
        "no_light": "No Light",
        "no_module": "No Module",
        "skipped": "Skipped",
        "not_collected": "Not Collected",
        "unknown": "Unknown",
    },
}


@dataclass(frozen=True)
class OpticalSeverityResult:
    severity: str
    reason: str | None = None
    rx_power: float | None = None
    alarm_low: float | None = None
    warning_low: float | None = None
    maintenance_normal_line: float | None = None
    warning_source: str = "missing"
    source_label: str = "threshold missing"


def compute_optical_severity(record: dict) -> OpticalSeverityResult:
    """Compute RX optical status using native thresholds or traceable derivation.

    Status model:
    - normal: rx >= warning + 3 dB
    - notice: warning <= rx < warning + 3 dB
    - warning: alarm <= rx < warning
    - alarm: rx < alarm

    If warning is missing but alarm exists, warning is derived as alarm + 2.01 dB.
    If both warning and alarm are missing, the status is unknown instead of normal.
    """
    module_present = _first_value(record, "module_present", "has_module")
    if _is_false(module_present) or _is_true(_first_value(record, "no_module")):
        return OpticalSeverityResult("no_module", "Optical module is not present")

    rx_power = _first_float(record, "rx_power", "switch_rx_power", "ap_rx_power")
    if rx_power is None or rx_power <= -35:
        return OpticalSeverityResult("no_light", "RX power is missing or <= -35 dBm", rx_power=rx_power)

    port_status = str(_first_value(record, "port_status", "switch_port_status", "ap_port_status") or "").strip().upper()
    if port_status == "DOWN":
        return OpticalSeverityResult("link_abnormal", "Port is DOWN", rx_power=rx_power)

    alarm_low = _first_float(record, "alarm_low", "rx_low_alarm")
    warning_low = _first_float(record, "warning_low", "rx_low_warning")
    device_type = str(_first_value(record, "device_type", "source_type") or "").strip().casefold()
    warning_source = "native" if warning_low is not None else "missing"
    if warning_low is None and alarm_low is not None:
        warning_low = round(alarm_low + DERIVED_WARNING_DELTA_DB, 2)
        warning_source = "derived"
    source_label = _source_label(device_type, warning_source)

    if warning_low is None:
        return OpticalSeverityResult(
            "unknown",
            "RX threshold is missing",
            rx_power=rx_power,
            alarm_low=alarm_low,
            warning_low=None,
            maintenance_normal_line=None,
            warning_source=warning_source,
            source_label=source_label,
        )

    normal_line = round(warning_low + MAINTENANCE_MARGIN_DB, 2)
    if rx_power >= normal_line:
        severity = "normal"
        reason = "RX power is above maintenance normal line"
    elif warning_low <= rx_power < normal_line:
        severity = "notice"
        reason = "RX power is below maintenance normal line"
    elif alarm_low is None or alarm_low <= rx_power < warning_low:
        severity = "warning"
        reason = "RX power is between alarm low and warning low threshold"
    else:
        severity = "alarm"
        reason = "RX power below alarm low threshold"

    return OpticalSeverityResult(
        severity,
        reason,
        rx_power=rx_power,
        alarm_low=alarm_low,
        warning_low=warning_low,
        maintenance_normal_line=normal_line,
        warning_source=warning_source,
        source_label=source_label,
    )


def worse_optical_severity(left: str, right: str) -> str:
    return left if SEVERITY_RANK.get(left, 0) >= SEVERITY_RANK.get(right, 0) else right


def display_optical_status(status: object, language: str = "zh") -> str:
    raw = str(status or "unknown").strip()
    lang = "en" if str(language or "").lower().startswith("en") else "zh"
    return OPTICAL_STATUS_LABELS.get(lang, OPTICAL_STATUS_LABELS["zh"]).get(
        raw, raw or OPTICAL_STATUS_LABELS[lang]["unknown"]
    )


def _first_value(record: dict, *keys: str) -> object:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_float(record: dict, *keys: str) -> float | None:
    return _to_float(_first_value(record, *keys))


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _is_false(value: object) -> bool:
    if value is None or value == "":
        return False
    return str(value).strip().casefold() in {"0", "false", "no", "n", "none", "null", "absent", "not_present"}


def _is_true(value: object) -> bool:
    if value is None or value == "":
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "present", "no_module"}


def _source_label(device_type: str, warning_source: str) -> str:
    if warning_source == "native":
        return "AP native" if device_type == "ap" else "switch native"
    if warning_source == "derived":
        return "AP derived" if device_type == "ap" else "switch derived"
    return "threshold missing"
