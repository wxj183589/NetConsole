from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal


AP_BUSINESS_RX_MIN_DBM = -13.90
ApBusinessOpticalStatus = Literal["normal", "abnormal", "unknown"]


@dataclass(frozen=True)
class ApBusinessRxEvaluation:
    status: ApBusinessOpticalStatus
    rx_dbm: float | None
    threshold_dbm: float
    reason: str


def parse_ap_rx_dbm(value: object) -> float | None:
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


def evaluate_ap_business_rx(
    rx_dbm: object,
    *,
    data_freshness: object = "",
) -> ApBusinessOpticalStatus:
    if str(data_freshness or "").strip().casefold() == "stale":
        return "unknown"
    value = parse_ap_rx_dbm(rx_dbm)
    if value is None:
        return "unknown"
    return "abnormal" if value < AP_BUSINESS_RX_MIN_DBM else "normal"


def evaluate_ap_business_rx_detail(
    rx_dbm: object,
    *,
    data_freshness: object = "",
) -> ApBusinessRxEvaluation:
    value = parse_ap_rx_dbm(rx_dbm)
    status = evaluate_ap_business_rx(rx_dbm, data_freshness=data_freshness)
    if str(data_freshness or "").strip().casefold() == "stale":
        reason = "AP接收光功率数据已过期，业务状态未知"
    elif value is None:
        reason = "AP接收光功率无有效值，业务状态未知"
    elif status == "abnormal":
        reason = (
            f"AP接收光功率 {value:.2f} dBm 低于业务门限 "
            f"{AP_BUSINESS_RX_MIN_DBM:.2f} dBm"
        )
    else:
        reason = (
            f"AP接收光功率 {value:.2f} dBm 达到业务门限 "
            f"{AP_BUSINESS_RX_MIN_DBM:.2f} dBm"
        )
    return ApBusinessRxEvaluation(
        status=status,
        rx_dbm=value,
        threshold_dbm=AP_BUSINESS_RX_MIN_DBM,
        reason=reason,
    )


__all__ = [
    "AP_BUSINESS_RX_MIN_DBM",
    "ApBusinessOpticalStatus",
    "ApBusinessRxEvaluation",
    "evaluate_ap_business_rx",
    "evaluate_ap_business_rx_detail",
    "parse_ap_rx_dbm",
]
