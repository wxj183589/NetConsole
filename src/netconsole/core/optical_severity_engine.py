from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


DERIVED_WARNING_DELTA_DB = 2.01
MAINTENANCE_MARGIN_DB = 3.0
# History-only tolerance.  This is deliberately separate from optical alarm
# thresholds: it suppresses telemetry jitter without changing health status.
OPTICAL_HISTORY_POWER_DELTA_DB = 0.20
AP_DEFAULT_OPTICAL_THRESHOLD_PROFILE = {
    "alarm_low": -19.00,
    "warning_low": -16.99,
}
ZTE_NO_LIGHT_REASON = "设备未返回接收光功率"
ZTE_NO_MODULE_FIELDS = frozenset(
    {
        "rx_power",
        "rx_power_dbm",
        "tx_power",
        "tx_power_dbm",
        "temperature",
        "temperature_c",
        "temperature_celsius",
        "voltage",
        "voltage_v",
        "supply_voltage_1_v",
        "supply_voltage_2_v",
        "bias_current",
        "tx_bias_ma",
        "tx_bias_current_ma",
        "module_type",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "vendor_name",
        "wavelength",
        "wavelength_nm",
        "tx_wavelength_nm",
        "rx_wavelength_nm",
        "transmission_distance",
        "transfer_distance_smf_m",
        "connector",
        "connector_type",
        "transceiver_type",
        "transceiver_mode",
        "directionality",
        "ethernet_compliance",
        "vendor_part_number",
        "vendor_revision",
        "vendor_serial_number",
        "authentication",
        "authentication_code",
        "product_serial_number",
        "product_sn",
        "product_date",
        "speed",
        "receiver_sensitivity_dbm",
        "receiver_overload_dbm",
        "rx_low_alarm",
        "rx_low_alarm_dbm",
        "rx_low_threshold_dbm",
        "rx_high_alarm",
        "rx_high_alarm_dbm",
        "rx_high_threshold_dbm",
        "tx_low_alarm",
        "tx_low_alarm_dbm",
        "tx_low_threshold_dbm",
        "tx_high_alarm",
        "tx_high_alarm_dbm",
        "tx_high_threshold_dbm",
        "rx_low_warning",
        "rx_high_warning",
        "tx_low_warning",
        "tx_high_warning",
    }
)

SEVERITY_RANK = {
    "unknown": 0,
    "not_collected": 0,
    "not_applicable": 0,
    "skipped": 0,
    "offline": 0,
    "no_module": 0,
    "": 0,
    "normal": 1,
    "notice": 2,
    "warning": 3,
    "alarm": 4,
    "abnormal": 4,
    "link_abnormal": 5,
    "link_down": 5,
    "no_light": 6,
    "unverified": 0,
    "dom_unavailable": 0,
}

OPTICAL_HEALTH_WARNING_STATUSES = frozenset({"notice", "warning", "alarm", "abnormal"})
OPTICAL_HEALTH_CRITICAL_STATUSES = frozenset({"critical", "link_abnormal", "link_down", "no_light"})
OPTICAL_HEALTH_NO_DATA_STATUSES = frozenset(
    {
        "",
        "unknown",
        "not_collected",
        "not_applicable",
        "skipped",
        "offline",
        "no_module",
        "unverified",
        "dom_unavailable",
    }
)
OPTICAL_DATA_STALE_AFTER = timedelta(hours=24)

STATUS_COLORS = {
    "normal": "DCFCE7",
    "notice": "FEF9C3",
    "warning": "FEF9C3",
    "alarm": "FEE2E2",
    "abnormal": "FEE2E2",
    "link_abnormal": "FFE4E6",
    "link_down": "FFE4E6",
    "no_light": "E5E7EB",
    "no_module": "F3F4F6",
    "skipped": "F3F4F6",
    "offline": "E5E7EB",
    "not_collected": "F3F4F6",
    "not_applicable": "F3F4F6",
    "unknown": "F3F4F6",
    "unverified": "FEF9C3",
    "dom_unavailable": "F3F4F6",
}

OPTICAL_STATUS_LABELS: dict[str, dict[str, str]] = {
    "zh": {
        "normal": "正常",
        "notice": "偏低关注",
        "warning": "提示告警",
        "alarm": "一般告警",
        "abnormal": "光衰大",
        "link_abnormal": "链路异常",
        "link_down": "链路断开",
        "no_light": "无光",
        "no_module": "无光模块",
        "skipped": "未检查",
        "not_collected": "未采集",
        "not_applicable": "不适用",
        "unknown": "未知",
        "unverified": "状态未知/第三方模块",
        "dom_unavailable": "不支持 DOM",
    },
    "en": {
        "normal": "Normal",
        "notice": "Notice",
        "warning": "Warning",
        "alarm": "Alarm",
        "abnormal": "High Attenuation",
        "link_abnormal": "Link Abnormal",
        "link_down": "Link Down",
        "no_light": "No Light",
        "no_module": "No Module",
        "skipped": "Skipped",
        "not_collected": "Not Collected",
        "not_applicable": "Not Applicable",
        "unknown": "Unknown",
        "unverified": "Unverified / Third-party Module",
        "dom_unavailable": "DOM Unavailable",
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
    If AP-side thresholds are missing, a centralized default AP profile is used.
    """
    if is_optical_module_absent(record):
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
    if device_type == "ap" and (alarm_low is None or warning_low is None):
        alarm_low, warning_low = _apply_ap_default_threshold_profile(alarm_low, warning_low)
        warning_source = "default_profile"
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


def compute_zte_optical_severity(record: dict) -> OpticalSeverityResult:
    """Use only ZTE device-reported module state and native RX/TX thresholds."""

    reported_status = str(
        _first_value(
            record,
            "device_reported_status",
            "vendor_status",
            "module_status",
            "status",
        )
        or ""
    ).strip().casefold()
    if (
        is_optical_module_absent(record)
        or _is_false(_first_value(record, "module_online"))
        or reported_status == "offline"
    ):
        return OpticalSeverityResult(
            "no_module",
            "设备返回 offline，未检测到光模块",
            warning_source="zte_device",
            source_label="ZTE device reported",
        )

    rx_power = _first_float(record, "rx_power", "rx_power_dbm")
    if reported_status == "unknown" or rx_power is None:
        return OpticalSeverityResult(
            "no_light",
            ZTE_NO_LIGHT_REASON,
            warning_source="zte_device",
            source_label="ZTE device reported",
        )

    rx_low = _first_float(record, "rx_low_alarm", "rx_low_alarm_dbm")
    rx_high = _first_float(record, "rx_high_alarm", "rx_high_alarm_dbm")
    tx_power = _first_float(record, "tx_power", "tx_power_dbm")
    tx_low = _first_float(record, "tx_low_alarm", "tx_low_alarm_dbm")
    tx_high = _first_float(record, "tx_high_alarm", "tx_high_alarm_dbm")
    comparisons = (
        ("rx_low", rx_power, rx_low, rx_power < rx_low if rx_low is not None else False),
        ("rx_high", rx_power, rx_high, rx_power > rx_high if rx_high is not None else False),
        (
            "tx_low",
            tx_power,
            tx_low,
            tx_power < tx_low if tx_power is not None and tx_low is not None else False,
        ),
        (
            "tx_high",
            tx_power,
            tx_high,
            tx_power > tx_high if tx_power is not None and tx_high is not None else False,
        ),
    )
    reason_by_kind = {
        "rx_low": "RX power {value:.1f} dBm is below module low alarm threshold {threshold:.1f} dBm",
        "rx_high": "RX power {value:.1f} dBm is above module high alarm threshold {threshold:.1f} dBm",
        "tx_low": "TX power {value:.1f} dBm is below module low alarm threshold {threshold:.1f} dBm",
        "tx_high": "TX power {value:.1f} dBm is above module high alarm threshold {threshold:.1f} dBm",
    }
    for kind, value, threshold, matched in comparisons:
        if matched and value is not None and threshold is not None:
            return OpticalSeverityResult(
                "abnormal",
                reason_by_kind[kind].format(value=value, threshold=threshold),
                rx_power=rx_power,
                alarm_low=rx_low,
                warning_source="zte_native",
                source_label="ZTE native threshold",
            )

    thresholds_complete = rx_low is not None and rx_high is not None
    if tx_power is not None:
        thresholds_complete = (
            thresholds_complete and tx_low is not None and tx_high is not None
        )
    if thresholds_complete or reported_status == "normal":
        return OpticalSeverityResult(
            "normal",
            "ZTE optical power is within module alarm thresholds",
            rx_power=rx_power,
            alarm_low=rx_low,
            warning_source="zte_native" if thresholds_complete else "zte_device",
            source_label=(
                "ZTE native threshold"
                if thresholds_complete
                else "ZTE device reported"
            ),
        )
    return OpticalSeverityResult(
        "unknown",
        "Device did not report optical power thresholds; threshold evaluation is unavailable",
        rx_power=rx_power,
        warning_source="missing",
        source_label="ZTE threshold missing",
    )


def is_zte_optical_record(record: dict) -> bool:
    vendor = str(record.get("device_vendor") or "").strip().casefold()
    threshold_source = str(record.get("threshold_source") or "").strip().casefold()
    return vendor == "zte" or threshold_source.startswith("zte_")


def normalize_zte_optical_record(record: dict) -> dict:
    """Return one canonical ZTE optical record for storage, DTOs and exports."""

    normalized = dict(record)
    result = compute_zte_optical_severity(normalized)
    status = result.severity
    normalized["device_vendor"] = "ZTE"
    normalized["status"] = status
    normalized["normalized_status"] = status.upper()
    normalized["module_present"] = status != "no_module"
    normalized["module_online"] = status != "no_module"
    normalized["severity_reason"] = result.reason
    if status == "no_module":
        for field in ZTE_NO_MODULE_FIELDS:
            normalized[field] = None
        normalized["dom_supported"] = False
    elif status == "no_light":
        normalized["dom_supported"] = False
    return normalized


def optical_history_state_changed(
    previous: dict[str, object], current: dict[str, object]
) -> bool:
    """Compare optical business state while ignoring sub-tolerance power jitter."""

    for field in (
        "module_present",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
        "device_vendor",
        "device_reported_status",
        "threshold_source",
        "transceiver_mode",
        "vendor_part_number",
        "vendor_revision",
        "vendor_serial_number",
        "status",
        "rx_low_alarm",
        "rx_high_alarm",
        "tx_low_alarm",
        "tx_high_alarm",
        "rx_low_warning",
        "rx_high_warning",
        "tx_low_warning",
        "tx_high_warning",
    ):
        if _history_text(previous.get(field)) != _history_text(current.get(field)):
            return True
    return any(
        _optical_history_power_changed(previous.get(field), current.get(field))
        for field in ("rx_power", "tx_power")
    )


def worse_optical_severity(left: str, right: str) -> str:
    return left if SEVERITY_RANK.get(left, 0) >= SEVERITY_RANK.get(right, 0) else right


def classify_optical_health(status: object) -> str:
    """Map collector severity to the shared current optical health contract."""
    normalized = str(status or "").strip().casefold()
    if normalized in OPTICAL_HEALTH_CRITICAL_STATUSES:
        return "critical"
    if normalized in OPTICAL_HEALTH_WARNING_STATUSES:
        return "warning"
    if normalized in OPTICAL_HEALTH_NO_DATA_STATUSES:
        return "no_data"
    return "normal"


def is_optical_health_abnormal(status: object) -> bool:
    return classify_optical_health(status) in {"warning", "critical"}


def classify_optical_freshness(
    *timestamps: object,
    now: datetime | None = None,
    stale_after: timedelta = OPTICAL_DATA_STALE_AFTER,
) -> str:
    parsed = [_parse_timestamp(value) for value in timestamps]
    valid = [value for value in parsed if value is not None]
    if not valid:
        return "unknown"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return "stale" if current - max(valid) > stale_after else "fresh"


def is_optical_module_absent(record: dict) -> bool:
    """Recognize only an explicit device indication that a module is absent."""
    module_present = _first_value(record, "module_present", "has_module")
    if _is_false(module_present) or _is_true(_first_value(record, "no_module")):
        return True
    return any(
        str(record.get(field) or "").strip().casefold()
        in {"no_module", "no module", "no-module", "no transceiver", "no-transceiver", "无光模块", "未插光模块", "光模块不存在"}
        for field in ("module_status", "transceiver_status", "optical_alarm_status", "status")
    )


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


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


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


def _optical_history_power_changed(previous: object, current: object) -> bool:
    previous_value = _to_float(previous)
    current_value = _to_float(current)
    if previous_value is None or current_value is None:
        return _history_text(previous) != _history_text(current)
    return abs(current_value - previous_value) >= OPTICAL_HISTORY_POWER_DELTA_DB


def _history_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().casefold()


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
    if warning_source == "default_profile":
        return "AP default profile" if device_type == "ap" else "default profile"
    return "threshold missing"


def _apply_ap_default_threshold_profile(
    alarm_low: float | None,
    warning_low: float | None,
) -> tuple[float | None, float | None]:
    return (
        alarm_low if alarm_low is not None else AP_DEFAULT_OPTICAL_THRESHOLD_PROFILE["alarm_low"],
        warning_low if warning_low is not None else AP_DEFAULT_OPTICAL_THRESHOLD_PROFILE["warning_low"],
    )
