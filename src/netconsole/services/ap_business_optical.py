from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from netconsole.core.optical_rx_threshold import (
    OPTICAL_BUSINESS_RX_MIN_DBM,
    DualOpticalRxEvaluation,
    evaluate_dual_optical_rx,
    evaluate_optical_rx,
    parse_optical_rx_dbm,
)
from netconsole.core.optical_severity_engine import display_optical_status

AP_BUSINESS_RX_MIN_DBM = OPTICAL_BUSINESS_RX_MIN_DBM
ApBusinessOpticalStatus = Literal["normal", "abnormal", "unknown"]


@dataclass(frozen=True)
class ApBusinessRxEvaluation:
    status: ApBusinessOpticalStatus
    rx_dbm: float | None
    threshold_dbm: float
    reason: str


@dataclass(frozen=True)
class DualRxBusinessEvaluation:
    status: str
    ap_status: str
    switch_status: str
    ap_rx_dbm: float | None
    switch_rx_dbm: float | None
    threshold_dbm: float
    reason: str


parse_ap_rx_dbm = parse_optical_rx_dbm


def evaluate_ap_business_rx(
    rx_dbm: object,
    *,
    data_freshness: object = "",
) -> ApBusinessOpticalStatus:
    if str(data_freshness or "").strip().casefold() == "stale":
        return "unknown"
    return evaluate_optical_rx(
        rx_dbm,
        data_freshness=data_freshness,
    ).status  # type: ignore[return-value]


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


def evaluate_dual_rx_business_detail(
    ap_rx_dbm: object,
    switch_rx_dbm: object,
    *,
    ap_reported_status: object = "",
    switch_reported_status: object = "",
    ap_data_freshness: object = "",
    switch_data_freshness: object = "",
) -> DualRxBusinessEvaluation:
    evaluation = evaluate_dual_optical_rx(
        ap_rx_dbm,
        switch_rx_dbm,
        ap_reported_status=ap_reported_status,
        switch_reported_status=switch_reported_status,
        ap_data_freshness=ap_data_freshness,
        switch_data_freshness=switch_data_freshness,
    )
    reason = _dual_rx_reason(evaluation)
    return DualRxBusinessEvaluation(
        status=evaluation.status,
        ap_status=evaluation.ap.status,
        switch_status=evaluation.switch.status,
        ap_rx_dbm=evaluation.ap.rx_dbm,
        switch_rx_dbm=evaluation.switch.rx_dbm,
        threshold_dbm=evaluation.threshold_dbm,
        reason=reason,
    )


def _dual_rx_reason(evaluation: DualOpticalRxEvaluation) -> str:
    sides = [
        _side_reason("AP 侧收光", evaluation.ap),
        _side_reason("交换机侧收光", evaluation.switch),
    ]
    if evaluation.status == "normal":
        conclusion = "综合判定：正常"
    elif evaluation.status == "unknown":
        conclusion = "综合判定：数据不完整"
    else:
        conclusion = f"综合判定：{display_optical_status(evaluation.status)}"
    return "；".join([*sides, conclusion])


def _side_reason(label: str, evaluation) -> str:
    if evaluation.rx_dbm is None:
        if evaluation.status not in {"", "unknown", "not_collected"}:
            return f"{label}{display_optical_status(evaluation.status)}"
        return f"{label}无有效值"
    if evaluation.status == "abnormal":
        return (
            f"{label} {evaluation.rx_dbm:.2f} dBm 低于业务门限 "
            f"{evaluation.threshold_dbm:.2f} dBm"
        )
    if evaluation.status == "normal":
        return (
            f"{label} {evaluation.rx_dbm:.2f} dBm 达到业务门限 "
            f"{evaluation.threshold_dbm:.2f} dBm"
        )
    return (
        f"{label}{display_optical_status(evaluation.status)}："
        f"{evaluation.rx_dbm:.2f} dBm"
    )


__all__ = [
    "AP_BUSINESS_RX_MIN_DBM",
    "ApBusinessOpticalStatus",
    "ApBusinessRxEvaluation",
    "DualRxBusinessEvaluation",
    "evaluate_ap_business_rx",
    "evaluate_ap_business_rx_detail",
    "evaluate_dual_rx_business_detail",
    "parse_ap_rx_dbm",
]
