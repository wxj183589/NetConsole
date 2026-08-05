from __future__ import annotations

import pytest

from netconsole.services.ap_business_optical import (
    AP_BUSINESS_RX_MIN_DBM,
    evaluate_ap_business_rx,
    evaluate_ap_business_rx_detail,
    evaluate_dual_rx_business_detail,
)


@pytest.mark.parametrize(
    ("rx_power", "expected"),
    [
        (-13.89, "normal"),
        (-13.90, "normal"),
        (-13.91, "abnormal"),
        (-17.80, "abnormal"),
        (None, "unknown"),
        ("", "unknown"),
        ("invalid", "unknown"),
    ],
)
def test_ap_business_rx_fixed_boundary(rx_power: object, expected: str) -> None:
    assert AP_BUSINESS_RX_MIN_DBM == -13.90
    assert evaluate_ap_business_rx(rx_power) == expected


def test_ap_business_rx_accepts_device_text_and_explains_abnormal() -> None:
    result = evaluate_ap_business_rx_detail("-17.80 dBm")

    assert result.status == "abnormal"
    assert result.rx_dbm == -17.80
    assert result.threshold_dbm == -13.90
    assert result.reason == "AP接收光功率 -17.80 dBm 低于业务门限 -13.90 dBm"


def test_ap_business_rx_stale_measurement_is_unknown() -> None:
    result = evaluate_ap_business_rx_detail(-17.80, data_freshness="stale")

    assert result.status == "unknown"
    assert "已过期" in result.reason


@pytest.mark.parametrize(
    ("ap_rx", "switch_rx", "expected"),
    [
        (-7.72, -19.10, "abnormal"),
        (-19.10, -7.72, "abnormal"),
        (-13.90, -13.90, "normal"),
        (-13.91, -13.90, "abnormal"),
        (-13.90, -13.91, "abnormal"),
        (-13.89, -13.89, "normal"),
        (-13.89, None, "unknown"),
    ],
)
def test_dual_rx_business_requires_both_sides_to_pass(
    ap_rx: object,
    switch_rx: object,
    expected: str,
) -> None:
    result = evaluate_dual_rx_business_detail(
        ap_rx,
        switch_rx,
        ap_reported_status="normal",
        switch_reported_status="normal",
    )

    assert result.status == expected


def test_dual_rx_business_overrides_stale_switch_normal_status() -> None:
    result = evaluate_dual_rx_business_detail(
        -7.72,
        -19.10,
        ap_reported_status="normal",
        switch_reported_status="normal",
    )

    assert result.ap_status == "normal"
    assert result.switch_status == "abnormal"
    assert result.status == "abnormal"
    assert "交换机侧收光 -19.10 dBm 低于业务门限 -13.90 dBm" in result.reason
