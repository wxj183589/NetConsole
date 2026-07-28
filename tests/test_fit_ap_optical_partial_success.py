from __future__ import annotations

from netconsole.services.ac.fit_ap_optical_partial_success import (
    has_valid_ap_optical_measurement,
    preserve_valid_ap_optical_result,
)


def test_failed_row_with_valid_ap_optical_measurement_is_promoted() -> None:
    row = {
        "ap_uuid": "ap-ok",
        "ap_name": "AP-OK",
        "status": "failed",
        "rx_power": "-7.34",
        "tx_power": "-2.10",
        "error_message": "connect_timeout: display lldp neighbor-information list",
    }

    result = preserve_valid_ap_optical_result(row)

    assert result["status"] == "success"
    assert result["rx_power"] == "-7.34"
    assert result["error_message"] == row["error_message"]
    assert row["status"] == "failed"


def test_failed_row_without_ap_optical_measurement_stays_failed() -> None:
    row = {
        "ap_uuid": "ap-timeout",
        "ap_name": "AP-TIMEOUT",
        "status": "failed",
        "rx_power": None,
        "tx_power": None,
        "error_message": "connect_timeout: timed out",
    }

    result = preserve_valid_ap_optical_result(row)

    assert result["status"] == "failed"
    assert not has_valid_ap_optical_measurement(result)


def test_lldp_only_data_does_not_fake_an_optical_success() -> None:
    row = {
        "ap_uuid": "ap-lldp-only",
        "ap_name": "AP-LLDP",
        "status": "failed",
        "neighbor_device_name": "SW01",
        "neighbor_interface": "GE1/0/1",
        "error_message": "connect_timeout: display transceiver diagnosis interface",
    }

    result = preserve_valid_ap_optical_result(row)

    assert result["status"] == "failed"
    assert not has_valid_ap_optical_measurement(result)
