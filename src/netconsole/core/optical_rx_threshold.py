from __future__ import annotations

from dataclasses import dataclass
import math
import re

from netconsole.core.optical_severity_engine import classify_optical_health


OPTICAL_BUSINESS_RX_MIN_DBM = -13.90

_STATUS_ALIASES = {
    "正常": "normal",
    "偏低关注": "notice",
    "提示告警": "warning",
    "一般告警": "alarm",
    "严重告警": "critical",
    "光衰大": "abnormal",
    "功率异常": "abnormal",
    "链路异常": "link_abnormal",
    "链路断开": "link_down",
    "无光": "no_light",
    "无光模块": "no_module",
    "不适用": "not_applicable",
    "未采集": "not_collected",
}
_FAULT_STATUSES = frozenset({"critical", "link_abnormal", "link_down", "no_light"})
_PRESERVED_NO_DATA_STATUSES = frozenset(
    {
        "not_applicable",
        "no_module",
        "unverified",
        "dom_unavailable",
        "skipped",
        "offline",
    }
)
_BUSINESS_STATUS_RANK = {
    "unknown": 0,
    "not_collected": 0,
    "not_applicable": 0,
    "no_module": 0,
    "dom_unavailable": 0,
    "skipped": 0,
    "offline": 0,
    "normal": 1,
    "notice": 2,
    "warning": 3,
    "alarm": 4,
    "abnormal": 4,
    "critical": 5,
    "link_abnormal": 5,
    "link_down": 5,
    "no_light": 6,
}


@dataclass(frozen=True)
class OpticalRxEvaluation:
    status: str
    rx_dbm: float | None
    threshold_dbm: float


@dataclass(frozen=True)
class DualOpticalRxEvaluation:
    ap: OpticalRxEvaluation
    switch: OpticalRxEvaluation
    status: str
    threshold_dbm: float


def normalize_optical_rx_status(value: object) -> str:
    text = str(value or "").strip().casefold()
    return _STATUS_ALIASES.get(text, text)


def parse_optical_rx_dbm(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        parsed = float(match.group(0))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def evaluate_optical_rx(
    rx_dbm: object,
    *,
    reported_status: object = "",
    data_freshness: object = "",
    threshold_dbm: float = OPTICAL_BUSINESS_RX_MIN_DBM,
) -> OpticalRxEvaluation:
    value = parse_optical_rx_dbm(rx_dbm)
    if str(data_freshness or "").strip().casefold() == "stale":
        return OpticalRxEvaluation("unknown", value, threshold_dbm)

    status = normalize_optical_rx_status(reported_status)
    if status in _FAULT_STATUSES or status in _PRESERVED_NO_DATA_STATUSES:
        return OpticalRxEvaluation(status, value, threshold_dbm)
    if value is not None and value < threshold_dbm:
        return OpticalRxEvaluation("abnormal", value, threshold_dbm)
    if classify_optical_health(status) in {"warning", "critical"}:
        return OpticalRxEvaluation(status, value, threshold_dbm)
    if value is not None:
        return OpticalRxEvaluation("normal", value, threshold_dbm)
    return OpticalRxEvaluation("unknown", None, threshold_dbm)


def combine_optical_rx_status(ap_status: object, switch_status: object) -> str:
    statuses = [
        normalize_optical_rx_status(ap_status),
        normalize_optical_rx_status(switch_status),
    ]
    abnormal = [
        status
        for status in statuses
        if classify_optical_health(status) in {"warning", "critical"}
    ]
    if abnormal:
        return max(abnormal, key=lambda status: _BUSINESS_STATUS_RANK.get(status, 0))
    if statuses == ["normal", "normal"]:
        return "normal"
    if statuses == ["not_applicable", "not_applicable"]:
        return "not_applicable"
    return "unknown"


def evaluate_dual_optical_rx(
    ap_rx_dbm: object,
    switch_rx_dbm: object,
    *,
    ap_reported_status: object = "",
    switch_reported_status: object = "",
    ap_data_freshness: object = "",
    switch_data_freshness: object = "",
) -> DualOpticalRxEvaluation:
    ap = evaluate_optical_rx(
        ap_rx_dbm,
        reported_status=ap_reported_status,
        data_freshness=ap_data_freshness,
    )
    switch = evaluate_optical_rx(
        switch_rx_dbm,
        reported_status=switch_reported_status,
        data_freshness=switch_data_freshness,
    )
    return DualOpticalRxEvaluation(
        ap=ap,
        switch=switch,
        status=combine_optical_rx_status(ap.status, switch.status),
        threshold_dbm=OPTICAL_BUSINESS_RX_MIN_DBM,
    )


__all__ = [
    "DualOpticalRxEvaluation",
    "OPTICAL_BUSINESS_RX_MIN_DBM",
    "OpticalRxEvaluation",
    "combine_optical_rx_status",
    "evaluate_dual_optical_rx",
    "evaluate_optical_rx",
    "normalize_optical_rx_status",
    "parse_optical_rx_dbm",
]
