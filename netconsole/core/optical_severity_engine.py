from __future__ import annotations

import re
from dataclasses import dataclass


SEVERITY_RANK = {
    "unknown": 0,
    "not_collected": 0,
    "skipped": 0,
    "": 0,
    "normal": 1,
    "warning": 2,
    "alarm": 3,
    "link_abnormal": 4,
    "no_light": 5,
}

STATUS_COLORS = {
    "normal": "DCFCE7",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "link_down": "FFE4E6",
    "no_light": "E5E7EB",
    "skipped": "F3F4F6",
    "not_collected": "F3F4F6",
    "unknown": "F3F4F6",
}

OPTICAL_STATUS_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "normal": "正常",
        "warning": "提示告警",
        "alarm": "一般告警",
        "link_abnormal": "链路异常",
        "link_down": "链路断开",
        "no_light": "无光",
        "skipped": "未检查",
        "not_collected": "未采集",
        "unknown": "未知",
    },
    "en": {
        "normal": "Normal",
        "warning": "Warning",
        "alarm": "Alarm",
        "link_abnormal": "Link Abnormal",
        "link_down": "Link Down",
        "no_light": "No Light",
        "skipped": "Skipped",
        "not_collected": "Not Collected",
        "unknown": "Unknown",
    },
}


@dataclass(frozen=True)
class OpticalSeverityResult:
    severity: str
    reason: str | None = None


def compute_optical_severity(record: dict) -> OpticalSeverityResult:
    rx_power = _first_float(record, "rx_power", "switch_rx_power", "ap_rx_power")
    if rx_power is None or rx_power <= -35:
        return OpticalSeverityResult("no_light", "RX power is missing or <= -35 dBm")

    port_status = str(_first_value(record, "port_status", "switch_port_status", "ap_port_status") or "").strip().upper()
    if port_status == "DOWN":
        return OpticalSeverityResult("link_abnormal", "Port is DOWN")

    alarm_low = _first_float(record, "alarm_low", "rx_low_alarm")
    if alarm_low is not None and rx_power < alarm_low:
        return OpticalSeverityResult("alarm", "RX power below alarm low threshold")

    warning_low = _first_float(record, "warning_low", "rx_low_warning")
    warning_upper = warning_low + 3 if warning_low is not None else None
    if alarm_low is not None and warning_upper is not None and alarm_low <= rx_power < warning_upper:
        return OpticalSeverityResult("warning", "RX power in warning range")

    return OpticalSeverityResult("normal", None)


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
