from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.parsers.zte.zxr10 import (
    normalize_zte_cli_text,
    parse_device_identity,
    parse_interface_detail,
    parse_interfaces,
    parse_lldp,
    parse_optical_detail,
    parse_optical_summary,
)


FIXTURES = Path(__file__).parent / "fixtures" / "zte"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_zte_5960x_identity_from_manual_fixture() -> None:
    parsed = parse_device_identity(_fixture("zte_5960x_show_version.txt"))

    assert parsed.status == "OK"
    assert parsed.value["vendor"] == "ZTE"
    assert parsed.value["platform"] == "ZXR10"
    assert parsed.value["product_family"] == "5960X-ES"
    assert parsed.value["model"] == "5960X-32U-ES"
    assert parsed.value["software_version"] == "V2.00.20.03B07"
    assert parsed.value["base_version"] == "V2.00.20.03"
    assert parsed.value["build_time"] == "2024/08/06 01:38:11"
    assert parsed.value["image_file"] == "sysdisk0: verset/59X-ES-V2.00.20.03B07.set"
    assert parsed.value["uptime_seconds"] == 6600
    assert parsed.value["board_name"] == "5960X-32U-ES"


@pytest.mark.parametrize(
    "model_text",
    ("59X-ES", "5960X-ES", "ZXR10 5960X-ES", "  59x-es  "),
)
def test_parse_zte_identity_accepts_model_variants(model_text: str) -> None:
    raw = (
        f"ZTE ZXR10 Software, Version: {model_text} V2.00.20.03B07, Release software\n"
        "System uptime is 1 day(s), 0 hour(s), 0 minute(s)\n"
    )

    parsed = parse_device_identity(raw)

    assert parsed.value["product_family"] == "5960X-ES"
    assert parsed.value["software_version"] == "V2.00.20.03B07"


def test_non_zte_output_is_not_misidentified() -> None:
    parsed = parse_device_identity("H3C Comware Software, Version 7.1.070")

    assert parsed.status == "NOT_RECOGNIZED"
    assert parsed.value == {}


def test_other_zxr10_model_is_not_misidentified_as_5960x_es() -> None:
    parsed = parse_device_identity(
        "ZTE ZXR10 Software, Version: ZXR10 5950 V2.00.20.03B07, Release software"
    )

    assert parsed.status == "NOT_RECOGNIZED"
    assert parsed.value == {}


def test_parse_zte_interface_brief_handles_types_descriptions_and_pager() -> None:
    parsed = parse_interfaces(_fixture("zte_5960x_show_interface_brief.txt"))
    by_name = {str(row["interface_name"]): row for row in parsed.value}

    assert set(by_name) == {
        "cgei-1/1/0/49:1",
        "cgei-1/1/0/50",
        "cgei-1/1/0/52",
        "xxvgei-1/1/0/1",
        "xlgei-0/1/0/1",
        "xgei-0/1/1/2",
        "mgmt_eth",
    }
    assert by_name["xxvgei-1/1/0/1"]["oper_status"] == "UP"
    assert by_name["cgei-1/1/0/52"]["oper_status"] == "PHYSICAL_DOWN"
    assert by_name["xlgei-0/1/0/1"]["oper_status"] == "PROTOCOL_DOWN"
    assert by_name["cgei-1/1/0/50"]["oper_status"] == "ADMIN_DOWN"
    assert by_name["xxvgei-1/1/0/1"]["description"] == "Trackside AP 01"
    assert by_name["mgmt_eth"]["trackside_candidate"] is False


def test_parse_zte_interface_detail_from_manual_fixture() -> None:
    parsed = parse_interface_detail(_fixture("zte_5960x_show_interface_detail.txt"))

    assert parsed.value["interface_name"] == "mgmt_eth"
    assert parsed.value["ifindex"] == 262146
    assert parsed.value["physical_status"] == "up"
    assert parsed.value["protocol_status"] == "up"
    assert parsed.value["ipv4_protocol_status"] == "up"
    assert parsed.value["ipv6_protocol_status"] == "down"
    assert parsed.value["detected_status"] == "RX-OK/TX-OK"
    assert parsed.value["last_physical_up_time"] == "2024-06-25 10:54:06"
    assert parsed.value["mac_address"] == "22:33:44:55:66:78"
    assert parsed.value["drop_events"] == 168
    assert parsed.value["crc_error"] is None


def test_parse_zte_optical_summary_keeps_unknown_and_na_rows() -> None:
    parsed = parse_optical_summary(_fixture("zte_5960x_show_opticalinfo_brief.txt"))
    by_name = {str(row["interface_name"]): row for row in parsed.value}

    assert by_name["xgei-0/1/1/1"]["status"] == "offline"
    unknown = by_name["xgei-0/1/1/2"]
    assert unknown["status"] == "unverified"
    assert unknown["rx_power"] == -11.9
    assert unknown["rx_low_alarm"] == -11.1
    assert unknown["rx_high_alarm"] == 0.5
    assert unknown["tx_power"] == -2.8
    assert unknown["tx_low_alarm"] == -7.3
    assert by_name["xgei-0/1/1/3"]["status"] == "normal"
    assert by_name["xgei-0/1/1/4"]["status"] == "abnormal"
    assert by_name["xgei-0/1/1/5"]["status"] == "dom_unavailable"
    assert by_name["xgei-0/1/1/5"]["rx_power"] is None


def test_parse_zte_optical_detail_from_manual_fixture() -> None:
    parsed = parse_optical_detail(_fixture("zte_5960x_show_opticalinfo_detail.txt"))
    item = parsed.value

    assert item["interface_name"] == "xgei-0/1/1/2"
    assert item["module_present"] is True
    assert item["dom_supported"] is True
    assert item["module_type"] == "SFP+"
    assert item["connector"] == "LC"
    assert item["ethernet_compliance"] == "10GBase-SR"
    assert item["wavelength_nm"] == 850
    assert item["rx_power"] == -11.904
    assert item["tx_power"] == -2.779
    assert item["bias_current"] == 6.074
    assert item["temperature"] == 20.117
    assert item["voltage"] == 3.27
    assert item["receiver_sensitivity_dbm"] == -9.9
    assert item["receiver_overload_dbm"] == 0.5
    assert item["rx_low_alarm"] == -11.101
    assert item["rx_high_alarm"] == 0.5
    assert item["tx_low_alarm"] == -7.3
    assert item["tx_high_alarm"] == -1
    assert item["module_vendor"] == "HG GENUINE"
    assert item["module_model"] == "MTRS-01X11-G"
    assert item["module_serial_number"] == "HA20140052592"


def test_normalize_zte_cli_text_removes_ansi_pager_and_backspace_overwrite() -> None:
    raw = "\x1b[31mline\x1b[0m\r\n--More--\x08\x08        \r\nabcX\b"

    normalized = normalize_zte_cli_text(raw)

    assert "\x1b" not in normalized
    assert "More" not in normalized
    assert "\b" not in normalized
    assert "abc" in normalized


def test_lldp_parser_remains_sample_required_without_real_fixture() -> None:
    parsed = parse_lldp("LLDP local interface xgei-0/1/1/2\nRemote System Name: AP-01")

    assert parsed.status == "SAMPLE_REQUIRED"
    assert parsed.value == []
    assert parsed.warnings
    assert parse_lldp("No neighbor").status == "NO_NEIGHBOR"
    assert (
        parse_lldp("LLDP is disabled\nNo neighbor").status
        == "LLDP_DISABLED"
    )
    assert parse_lldp("Invalid command").status == "COMMAND_UNSUPPORTED"
