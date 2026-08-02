from pathlib import Path

from netconsole.parsers.h3c.ac.wlan_ap_verbose_parser import parse_wlan_ap_verbose
from netconsole.services.h3c_ac_collect_service import _select_verified_verbose_ap


FIXTURE = Path(__file__).parent / "fixtures" / "h3c" / "ac" / "real_display_wlan_ap_verbose.txt"


def test_verbose_parser_extracts_versions_radios_continuations_and_zero_power():
    rows = parse_wlan_ap_verbose(FIXTURE.read_text(encoding="utf-8"))

    assert [row["ap_name"] for row in rows] == ["AP-NB12-01", "AP-NB12-02"]
    assert rows[0]["hardware_version"] == "Ver.A"
    assert rows[0]["software_version"] == "Version 7.1.064, Release 2619P08"
    assert rows[0]["boot_version"] == "7.1.064"
    assert rows[0]["description"] == "宁波地铁12号线 一号站厅 AP"
    assert rows[0]["radio_details"][0]["radio_id"] == 1
    assert rows[0]["radio_details"][0]["max_power"] == "0"
    assert rows[0]["radio_details"][0]["max_power_unit"] == "dBm"
    assert rows[0]["radio_details"][1]["radio_id"] == 2
    assert rows[1]["serial_id"] == "219801A4588256E0002X"
    assert rows[1]["radio_details"][0]["channel"] == "149"


def test_verbose_parser_cross_checks_name_mac_and_serial_against_resource():
    row = parse_wlan_ap_verbose(FIXTURE.read_text(encoding="utf-8"))[0]
    resource = {
        "ap_name": "AP-NB12-01",
        "ap_mac": "28c9-7a3e-5da0",
        "serial_number": "219801A3L68257P005M3",
    }
    assert _select_verified_verbose_ap([row], resource) is row
    assert _select_verified_verbose_ap(
        [row], {**resource, "ap_mac": "30f5-277a-0ea0"}
    ) is None
    assert _select_verified_verbose_ap(
        [row], {**resource, "serial_number": "wrong"}
    ) is None
