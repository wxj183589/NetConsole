from __future__ import annotations

import pytest

from netconsole.services.ap_business_optical import (
    AP_BUSINESS_RX_MIN_DBM,
    evaluate_ap_business_rx,
    evaluate_ap_business_rx_detail,
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
