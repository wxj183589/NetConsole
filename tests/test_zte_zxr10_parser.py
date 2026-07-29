from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.parsers.zte.zxr10 import (
    merge_optical_modules,
    merge_optical_snapshot,
    normalize_zte_cli_text,
    parse_device_identity,
    parse_interface_detail,
    parse_interface_switchport_config,
    parse_interfaces,
    parse_lldp,
    parse_lldp_brief,
    parse_lldp_entries,
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
    assert parsed.value["verification_status"] == "DOCUMENT_SAMPLE_ONLY"
    assert parsed.value["parser_version"]
    assert parsed.value["parse_status"] == "PARSED"
    assert parsed.value["warnings"] == []
    assert parsed.value["raw_output_ref"] == ""


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

    assert parsed.status == "UNSUPPORTED_MODEL"
    assert parsed.value["model"] == "UNKNOWN"


def test_real_c89e_version_fixture_is_parsed_as_supported_central_switch() -> None:
    parsed = parse_device_identity(
        _fixture("real_c89e4_show_version_redacted.txt")
    )

    assert parsed.status == "OK"
    assert parsed.value["vendor"] == "ZTE"
    assert parsed.value["platform"] == "ZXR10"
    assert parsed.value["product_family"] == "C89E"
    assert parsed.value["model"] == "C89E-4"
    assert parsed.value["software_version"] == "V1.9.0"
    assert parsed.value["uptime_seconds"] == 1_038_420
    assert parsed.value["system_name"] == "DEVICE-REDACTED"
    assert parsed.value["parse_status"] == "PARSED"


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


def test_parse_real_c89e_interface_brief_redacts_description_but_keeps_shape() -> None:
    parsed = parse_interfaces(
        _fixture("real_c89e4_show_interface_brief_redacted.txt")
    )
    by_name = {str(row["interface_name"]): row for row in parsed.value}

    assert parsed.status == "OK"
    assert parsed.warnings == ()
    assert by_name["sci-0/1/0/1"]["oper_status"] == "UP"
    assert by_name["gei-0/3/0/1"]["oper_status"] == "PHYSICAL_DOWN"
    assert by_name["gei-0/3/0/1"]["admin_status"] == "up"
    assert by_name["gei-0/3/0/1"]["physical_status"] == "down"
    assert by_name["gei-0/3/0/1"]["protocol_status"] == "down"
    assert by_name["gei-0/3/0/1"]["media_attribute"] == "optical"
    assert by_name["gei-0/3/0/1"]["media_type"] == "optical"
    assert by_name["gei-0/3/0/1"]["category"] == "physical"
    assert by_name["gei-0/3/0/1"]["interface_type"] is None
    assert by_name["gei-0/3/0/1"]["port_status"] is None
    assert by_name["xgeis-0/4/0/5"]["description"] == "DESCRIPTION-REDACTED"


def test_parse_hzdt10_interface_fixture_preserves_complete_names_and_semantics() -> None:
    parsed = parse_interfaces(_fixture("hzdt10_show_interface_brief.txt"))
    by_name = {str(row["interface_name"]): row for row in parsed.value}

    assert parsed.status == "OK"
    assert set(by_name) == {
        "gei-0/3/0/2",
        "gei-0/3/0/6",
        "sci-0/1/0/1",
        "xgei-0/4/0/1",
    }
    assert by_name["gei-0/3/0/2"]["link_status"] == "UP"
    assert by_name["gei-0/3/0/6"]["link_status"] == "PHYSICAL_DOWN"
    assert by_name["sci-0/1/0/1"]["link_status"] == "PHYSICAL_DOWN"
    assert by_name["xgei-0/4/0/1"]["link_status"] == "PROTOCOL_DOWN"
    assert by_name["xgei-0/4/0/1"]["media_type"] == "electric"
    assert all(row["port_status"] is None for row in by_name.values())


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

    assert by_name["xgei-0/1/1/1"]["status"] == "no_module"
    unknown = by_name["xgei-0/1/1/2"]
    assert unknown["status"] == "no_light"
    assert unknown["rx_power"] == -11.9
    assert unknown["rx_low_alarm"] == -11.1
    assert unknown["rx_high_alarm"] == 0.5
    assert unknown["tx_power"] == -2.8
    assert unknown["tx_low_alarm"] == -7.3
    assert by_name["xgei-0/1/1/3"]["status"] == "normal"
    assert by_name["xgei-0/1/1/4"]["status"] == "abnormal"
    assert by_name["xgei-0/1/1/5"]["status"] == "no_light"
    assert by_name["xgei-0/1/1/5"]["rx_power"] is None


def test_parse_real_c89e_optical_summary_with_mode_column() -> None:
    parsed = parse_optical_summary(
        _fixture("real_c89e4_show_opticalinfo_brief_redacted.txt")
    )
    by_name = {str(row["interface_name"]): row for row in parsed.value}

    assert parsed.status == "OK"
    assert parsed.warnings == ()
    assert by_name["sci-0/1/0/1"]["rx_power"] == -7.2
    assert by_name["sci-0/1/0/1"]["tx_power"] == -5.1
    assert by_name["sci-0/1/0/1"]["transceiver_mode"] == "SingleMode"
    assert by_name["gei-0/3/0/1"]["status"] == "no_module"
    assert by_name["xgeis-0/4/0/5"]["tx_power"] is None
    assert by_name["xgeis-0/4/0/5"]["status"] == "no_light"


def test_parse_switchport_config_uses_observed_vlan_values_without_site_defaults() -> None:
    parsed = parse_interface_switchport_config(
        _fixture("zte_running_config_interface_redacted.txt")
    )
    item = parsed.value[0]

    assert parsed.status == "OK"
    assert item["interface_name"] == "gei-0/3/0/16"
    assert item["description"] == "Synthetic AP uplink"
    assert item["switchport_mode"] == "hybrid"
    assert item["tagged_vlans"] == [1201]
    assert item["untagged_vlans"] == [1701, 1703, 1704]
    assert item["native_vlan"] == 1701


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


def test_parse_c89e_optical_summary_preserves_native_thresholds_and_status() -> None:
    parsed = parse_optical_summary(
        _fixture("zte_c89e_show_opticalinfo_brief_thresholds.txt")
    )
    by_name = {str(row["interface_name"]): row for row in parsed.value}

    assert parsed.status == "OK"
    assert by_name["sci-0/1/0/1"]["module_online"] is False
    assert by_name["sci-0/1/0/1"]["device_reported_status"] == "offline"
    missing_rx = by_name["gei-0/3/0/1"]
    assert missing_rx["rx_power_dbm"] is None
    assert missing_rx["rx_low_alarm_dbm"] == -28.2
    assert missing_rx["rx_high_alarm_dbm"] == 0
    assert missing_rx["tx_power_dbm"] == -5.4
    assert missing_rx["tx_low_alarm_dbm"] == -10
    assert missing_rx["tx_high_alarm_dbm"] == -0.5
    assert missing_rx["device_reported_status"] == "Unknown"
    assert missing_rx["status"] == "no_light"
    assert missing_rx["transceiver_mode"] == "SingleMode"
    assert by_name["gei-0/3/0/4"]["rx_power_dbm"] == -28.2
    assert by_name["gei-0/3/0/5"]["rx_power_dbm"] == -25.4
    assert by_name["gei-0/3/0/6"]["rx_power_dbm"] == -15.1


def test_parse_c89e_optical_detail_maps_vendor_and_dom_fields() -> None:
    parsed = parse_optical_detail(
        _fixture("zte_c89e_show_opticalinfo_gei_0_3_0_6.txt")
    )
    item = parsed.value

    assert item["interface_name"] == "gei-0/3/0/6"
    assert item["transceiver_type"] == "SFP"
    assert item["connector_type"] == "LC"
    assert item["transceiver_mode"] == "smf"
    assert item["ethernet_compliance"] == "1000BASE-LX"
    assert item["transfer_distance_smf_m"] == 10000
    assert item["tx_wavelength_nm"] == 1310
    assert item["rx_wavelength_nm"] == 1310
    assert item["rx_power_dbm"] == -15.2
    assert item["tx_power_dbm"] == -5.5
    assert item["tx_bias_current_ma"] == 17.2
    assert item["temperature_celsius"] == 31
    assert item["supply_voltage_1_v"] == 3.3
    assert item["supply_voltage_2_v"] is None
    assert item["rx_low_alarm_dbm"] == -28.2
    assert item["rx_high_alarm_dbm"] == 0
    assert item["tx_low_alarm_dbm"] == -10
    assert item["tx_high_alarm_dbm"] == -0.5
    assert item["module_vendor"] == "ZTRS"
    assert item["vendor_part_number"] == "SFP-GE"
    assert item["vendor_revision"] == "A"
    assert item["vendor_serial_number"] == "UHD507000163"
    assert item["authentication"] is None
    assert item["authentication_code"] is None
    assert item["product_serial_number"] is None


def test_merge_zte_optical_detail_by_interface_skips_empty_values() -> None:
    brief = [
        {
            "interface_name": "gei-0/3/0/6",
            "rx_power": -15.1,
            "rx_low_alarm": -28.2,
            "status": "normal",
            "device_reported_status": "Normal",
        },
        {"interface_name": "gei-0/3/0/5", "rx_power": -25.4},
    ]
    details = [
        {
            "interface_name": "GEI-0/3/0/6",
            "rx_power": -15.2,
            "rx_low_alarm": None,
            "vendor_serial_number": "UHD507000163",
            "status": "unverified",
        }
    ]

    merged = merge_optical_modules(brief, details)

    assert merged[0]["interface_name"] == "gei-0/3/0/6"
    assert merged[0]["rx_power"] == -15.2
    assert merged[0]["rx_low_alarm"] == -28.2
    assert merged[0]["status"] == "normal"
    assert merged[0]["device_reported_status"] == "Normal"
    assert merged[0]["vendor_serial_number"] == "UHD507000163"
    assert merged[1]["interface_name"] == "gei-0/3/0/5"
    assert "vendor_serial_number" not in merged[1]


def test_zte_brief_refresh_preserves_detail_until_module_is_removed() -> None:
    existing = [
        {
            "interface_name": "gei-0/3/0/6",
            "device_vendor": "ZTE",
            "device_reported_status": "Normal",
            "status": "normal",
            "rx_power": -15.2,
            "module_model": "SFP-GE",
            "module_serial_number": "SN-OLD",
            "module_vendor": "ZTRS",
        }
    ]
    online = merge_optical_snapshot(
        existing,
        [
            {
                "interface_name": "gei-0/3/0/6",
                "device_vendor": "ZTE",
                "device_reported_status": "Normal",
                "status": "normal",
                "rx_power": -15.1,
            }
        ],
    )

    assert online[0]["module_serial_number"] == "SN-OLD"
    removed = merge_optical_snapshot(
        online,
        [
            {
                "interface_name": "gei-0/3/0/6",
                "device_vendor": "ZTE",
                "device_reported_status": "offline",
                "status": "no_module",
            }
        ],
    )
    assert removed[0]["status"] == "no_module"
    assert removed[0]["module_serial_number"] is None

    reinserted = merge_optical_snapshot(
        removed,
        [
            {
                "interface_name": "gei-0/3/0/6",
                "device_vendor": "ZTE",
                "device_reported_status": "Normal",
                "status": "normal",
                "rx_power": -14.8,
            }
        ],
    )
    assert reinserted[0]["module_serial_number"] is None


def test_normalize_zte_cli_text_removes_ansi_pager_and_backspace_overwrite() -> None:
    raw = "\x1b[31mline\x1b[0m\r\n--More--\x08\x08        \r\nabcX\b"

    normalized = normalize_zte_cli_text(raw)

    assert "\x1b" not in normalized
    assert "More" not in normalized
    assert "\b" not in normalized
    assert "abc" in normalized


def test_lldp_parser_rejects_unrecognized_text_without_fabricating_rows() -> None:
    parsed = parse_lldp("LLDP local interface xgei-0/1/1/2\nRemote System Name: AP-01")

    assert parsed.status == "PARSE_FAILED"
    assert parsed.value == []
    assert parsed.warnings
    assert parse_lldp("No neighbor").status == "NO_NEIGHBOR"
    assert (
        parse_lldp("LLDP is disabled\nNo neighbor").status
        == "LLDP_DISABLED"
    )
    assert parse_lldp("Invalid command").status == "COMMAND_UNSUPPORTED"


def test_parse_lldp_brief_merges_wrapped_port_id() -> None:
    parsed = parse_lldp_brief(_fixture("hzdt10_show_lldp_neighbor_brief.txt"))

    assert parsed.status == "OK"
    assert len(parsed.value) == 36
    neighbor = parsed.value[0]
    assert neighbor["local_interface"] == "gei-0/3/0/1"
    assert neighbor["scope"] == "NB"
    assert neighbor["neighbor_mac"] == "02:aa:bb:cc:00:01"
    assert neighbor["neighbor_interface"] == "Ten-GigabitEthernet1/0/1"
    assert neighbor["holdtime"] == 228
    assert neighbor["neighbor_sysname"] == "HZDT-TEST-01"


def test_parse_lldp_entry_unfolds_description_and_extracts_details() -> None:
    parsed = parse_lldp_entries(_fixture("hzdt10_show_lldp_entry.txt"))

    assert parsed.status == "OK"
    assert len(parsed.value) == 2
    neighbor = parsed.value[0]
    assert neighbor["neighbor_mac"] == "02:aa:bb:cc:00:02"
    assert neighbor["neighbor_ip"] == "192.0.2.26"
    assert neighbor["pvid"] == 71
    assert neighbor["ttl"] == 228
    assert neighbor["system_description"] == (
        "H3C Comware Platform Software, Software Version 7.1.064, "
        "Release 2493P01 HZDT-TEST-AP"
    )
    assert neighbor["operational_mau"] == "1000BaseLXFD"
    assert neighbor["max_frame_size"] == 9216
    assert parsed.value[1]["chassis_id"] == "192.0.2.27"
    assert parsed.value[1]["neighbor_mac"] is None
