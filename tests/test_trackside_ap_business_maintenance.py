from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from netconsole.core.optical_severity_engine import compute_zte_optical_severity
from netconsole.services.ap_business_optical import evaluate_ap_business_rx
from netconsole.services.trackside_ap_business import (
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    TRACKSIDE_RX_NORMAL_MIN_DBM,
    export_trackside_ap_business_xlsx,
    is_current_optical_abnormal_row,
    normalize_trackside_ap_business_row,
    normalize_trackside_vlan_display,
    trackside_row_status,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Native/PVID 71; Tagged 201", "Tagged 201"),
        ("Native/PVID 71 ; Tagged 201", "Tagged 201"),
        ("native / pvid 71; tagged 201", "tagged 201"),
        ("Tagged 201; Native/PVID 71", "Tagged 201"),
        ("Native/PVID 71", "—"),
        ("Native / PVID 4094；Untagged 202", "Untagged 202"),
        ("Tagged 201,202", "Tagged 201,202"),
        ("Tagged 201", "Tagged 201"),
        ("", "—"),
        (None, "—"),
    ],
)
def test_trackside_vlan_display_removes_native_pvid_fragment(
    value: object,
    expected: str,
) -> None:
    assert normalize_trackside_vlan_display(value) == expected


@pytest.mark.parametrize(
    ("rx_power", "expected"),
    [
        (-13.89, "normal"),
        (-13.90, "normal"),
        (-13.91, "abnormal"),
        (-24.7, "abnormal"),
        (-26.8, "abnormal"),
    ],
)
def test_trackside_rx_maintenance_boundary(
    rx_power: float,
    expected: str,
) -> None:
    assert TRACKSIDE_RX_NORMAL_MIN_DBM == -13.90
    assert evaluate_ap_business_rx(rx_power) == expected


def test_trackside_switch_keeps_native_tx_alarm() -> None:
    native = compute_zte_optical_severity(
        {
            "status": "normal",
            "rx_power": -10,
            "rx_low_alarm": -28.2,
            "rx_high_alarm": 0,
            "tx_power": -11,
            "tx_low_alarm": -10,
            "tx_high_alarm": -0.5,
        }
    )

    assert native.severity == "abnormal"


def test_trackside_row_status_preserves_critical_native_alarm() -> None:
    assert trackside_row_status(
        {
            "switch_rx_power": -10,
            "switch_optical_status": "critical",
            "ap_rx_power": -10,
            "ap_optical_status": "normal",
            "ap_side_has_data": True,
        }
    ) == "critical"


def test_trackside_switch_keeps_zte_native_threshold_result() -> None:
    native = compute_zte_optical_severity(
        {
            "status": "normal",
            "rx_power": -24.7,
            "rx_low_alarm": -28.2,
            "rx_high_alarm": 0,
            "tx_power": -5.2,
            "tx_low_alarm": -10,
            "tx_high_alarm": -0.5,
        }
    )

    assert native.severity == "normal"


def test_trackside_row_normalization_applies_business_threshold_only_to_ap() -> None:
    row = normalize_trackside_ap_business_row(
        {
            "pvid": 71,
            "vlan": "Native/PVID 71;; Tagged 201",
            "switch_rx_power": -24.7,
            "switch_optical_status": "normal",
            "ap_uuid": "ap-1",
            "ap_name": "AP-1",
            "ap_mac": "0011-2233-4455",
            "ap_rx_power": -26.8,
            "ap_optical_status": "normal",
            "ap_side_has_data": True,
        }
    )

    assert row["pvid"] == 71
    assert row["vlan"] == "Tagged 201"
    assert row["switch_optical_status"] == "normal"
    assert row["ap_device_optical_status"] == "normal"
    assert row["ap_business_optical_status"] == "abnormal"
    assert row["ap_optical_status"] == "abnormal"
    assert row["ap_business_threshold_dbm"] == -13.90
    assert "-26.80 dBm 低于业务门限 -13.90 dBm" in row["ap_business_reason"]
    assert row["optical_severity"] == "abnormal"
    assert trackside_row_status(row) == "abnormal"
    assert is_current_optical_abnormal_row(row) is True


def test_trackside_export_has_no_bidirectional_column_and_uses_normalized_vlan(
    tmp_path: Path,
) -> None:
    exported_fields = {
        field for _label_key, field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS
    }
    assert {
        "calculation_status",
        "forward_loss_db",
        "reverse_loss_db",
    }.isdisjoint(exported_fields)

    output = tmp_path / "trackside.xlsx"
    columns = (
        ("PVID", "pvid"),
        ("VLAN", "vlan"),
        ("交换机模块状态", "switch_optical_status"),
        ("业务综合状态", "optical_severity"),
        ("更新时间", "updated_at"),
    )
    row = normalize_trackside_ap_business_row(
        {
            "pvid": 71,
            "vlan": "Native/PVID 71; Tagged 201",
            "switch_rx_power": -24.7,
            "switch_optical_status": "normal",
            "ap_side_has_data": False,
            "updated_at": "2026-07-29T12:00:00+08:00",
        }
    )

    export_trackside_ap_business_xlsx(
        output,
        [row],
        columns,
        [header for header, _field in columns],
    )

    sheet = load_workbook(output)["轨旁AP业务"]
    headers = [cell.value for cell in sheet[1]]
    values = [cell.value for cell in sheet[2]]
    assert "双向光衰" not in headers
    assert "calculation_status" not in headers
    assert headers == ["PVID", "VLAN", "交换机模块状态", "业务综合状态", "更新时间"]
    assert values[:4] == ["71", "Tagged 201", "正常", "normal"]
