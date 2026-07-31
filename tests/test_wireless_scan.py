from __future__ import annotations

import subprocess

from openpyxl import load_workbook

from netconsole.core.paths import PathResolver
from netconsole.models.wireless_scan_models import (
    TracksideBssidMatch,
    WirelessAdapter,
    WirelessNetwork,
    WirelessScanResult,
)
from netconsole.repositories.wireless_scan_repository import WirelessScanRepository
from netconsole.services.network_tools.netsh_wireless_scanner import NetshWirelessScanner, parse_netsh_networks
from netconsole.services.network_tools.trackside_bssid_resolver import TracksideApBssidResolver
from netconsole.services.network_tools.hybrid_wireless_scanner import HybridWirelessScanner, merge_wireless_networks
from netconsole.services.network_tools.wireless_channel_analyzer import band_from_frequency, frequency_to_channel, normalize_mac, rssi_level
from netconsole.services.network_tools.wireless_ie_parser import WirelessInformationElementParser
from netconsole.services.network_tools.wireless_mimo_parser import parse_channel_width_from_ie_blob, parse_mimo_from_ie_blob
from netconsole.services.network_tools.wireless_scan_service import WIRELESS_SCAN_EXPORT_COLUMNS, WIRELESS_SCAN_DISPLAY_COLUMNS, WirelessScanService, export_wireless_scan_xlsx, result_to_row


EXPECTED_DISPLAY_KEYS = [
    "wireless_scan.ssid",
    "wireless_scan.mac_address",
    "wireless_scan.ap_mac",
    "wireless_scan.ap_name",
    "wireless_scan.radio_id",
    "wireless_scan.station",
    "wireless_scan.section",
    "wireless_scan.belong_type",
    "wireless_scan.belonging_source",
    "wireless_scan.location_mileage",
    "wireless_scan.rssi",
    "wireless_scan.signal_quality",
    "wireless_scan.channel",
    "wireless_scan.frequency",
    "wireless_scan.band",
    "wireless_scan.channel_width",
    "wireless_scan.mimo",
    "wireless_scan.encryption_method",
    "wireless_scan.encryption",
    "wireless_scan.auth_method",
]


NETSH_SAMPLE = """
SSID 1 : TracksideMesh
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : 30:f5:27:7a:5a:2f
         Signal             : 90%
         Radio type         : 802.11ac
         Channel            : 149

SSID 2 :
    Network type            : Infrastructure
    Authentication          : Open
    Encryption              : None
    BSSID 1                 : 30:f5:27:7a:5a:2d
         Signal             : 60%
         Radio type         : 802.11n
         Channel            : 6
"""


def test_wireless_frequency_channel_band_and_rssi_level():
    assert frequency_to_channel(2412) == 1
    assert frequency_to_channel(2437) == 6
    assert frequency_to_channel(2462) == 11
    assert frequency_to_channel(5180) == 36
    assert frequency_to_channel(5200) == 40
    assert frequency_to_channel(5745) == 149
    assert frequency_to_channel(5825) == 165
    assert band_from_frequency(2412) == "2.4G"
    assert band_from_frequency(5180) == "5G"
    assert band_from_frequency(5955) == "6G"
    assert rssi_level(-45) == "strong"
    assert rssi_level(-60) == "good"
    assert rssi_level(-70) == "fair"
    assert rssi_level(-82) == "weak"


def test_wireless_mac_normalization():
    assert normalize_mac("30f5-277a-5a2f") == "30f5277a5a2f"
    assert normalize_mac("30:f5:27:7a:5a:2f") == "30f5277a5a2f"
    assert normalize_mac("30F5277A5A2F") == "30f5277a5a2f"
    assert normalize_mac("bad") is None


def test_trackside_bssid_resolver_does_not_treat_ap_base_mac_as_bssid():
    resolver = TracksideApBssidResolver([{"ap_name": "AP-1", "ap_mac": "083b-e9ec-da5f", "site_name": "S1", "location_note": "K1", "direction": "up"}])
    radio1 = resolver.resolve("083b-e9ec-da5f")
    assert radio1.match_status == "unmatched"
    radio2 = TracksideApBssidResolver([{"ap_name": "AP-2", "ap_mac": "083b-e9ec-da40", "site_name": "S2"}]).resolve("083b-e9ec-da5f")
    assert radio2.match_status == "unmatched"
    second_vendor_sample = TracksideApBssidResolver([{"ap_name": "AP-3", "ap_mac": "94a7-482c-1140", "site_name": "S3"}]).resolve("94a7-482c-115f")
    assert second_vendor_sample.match_status == "unmatched"
    no_wrap = TracksideApBssidResolver([{"ap_name": "AP-Zero", "ap_mac": "083b-e9ec-daff"}])
    assert no_wrap.resolve("083b-e9ec-da0f").match_status == "unmatched"


def test_trackside_bssid_resolver_prefers_exact_collected_radio_mac():
    resolver = TracksideApBssidResolver(
        [
            {"ap_name": "AP-1", "ap_mac": "083b-e9ec-da4f", "site_name": "S1", "radio2_mac": "083b-e9ec-da6f"},
        ]
    )
    match = resolver.resolve("083b.e9ec.da6f")
    assert match.matched
    assert match.radio_id == 2
    assert match.ap_name == "AP-1"
    assert match.ap_mac == "083b-e9ec-da4f"
    assert match.match_rule == "radio2_mac"


def test_trackside_bssid_resolver_does_not_use_peer_name_as_fallback():
    resolver = TracksideApBssidResolver([{"ap_name": "AP-Name-01", "ap_mac": "083b-e9ec-da4f", "site_name": "S1"}])

    match = resolver.resolve("1122-3344-5566", peer_name="AP-Name-01")

    assert not match.matched
    assert match.match_status == "unmatched"


def test_trackside_bssid_resolver_preserves_section_belonging():
    resolver = TracksideApBssidResolver(
        [
            {
                "ap_name": "ap0303_a",
                "ap_mac_display": "5866-bab3-0a40",
                "belong_type": "section",
                "station_name": "",
                "section_name": "联庄-中医药大学",
                "radio1_mac": "5866-bab3-0a4f",
                "_identity_source": "ap_metadata",
            }
        ]
    )

    match = resolver.resolve("5866-bab3-0a4f")

    assert match.matched
    assert match.section == "联庄-中医药大学"
    assert match.belong_type == "section"


def test_trackside_bssid_resolver_uses_point_code_for_offline_base_data():
    resolver = TracksideApBssidResolver(
        [
            {
                "ap_name": "",
                "ap_point_code": "AP0127",
                "ap_mac_display": "1c94-6876-8ee0",
                "station_name": "高桥西",
                "section_name": "高桥西-高桥",
                "section_start_station": "高桥西",
                "section_end_station": "高桥",
                "mileage_text": "ZDK12+300",
                "direction": "下行",
                "radio1_mac": "1c94-6876-8eef",
                "_identity_source": "ap_metadata",
            }
        ]
    )

    match = resolver.resolve("1c94-6876-8eef")

    assert match.matched
    assert match.ap_name == "AP0127"
    assert match.station == "高桥西"
    assert match.section == "高桥西-高桥"
    assert match.mileage == "ZDK12+300"


def test_trackside_bssid_resolver_rejects_unique_name_only_extension_section():
    resolver = TracksideApBssidResolver(
        [
            {
                "ap_name": "ap0303_a",
                "belong_type": "section",
                "section_name": "联庄-中医药大学",
                "_identity_source": "ap_metadata",
            }
        ]
    )

    match = resolver.resolve("4ce9-e4f1-b880", peer_name="ap0303_a")

    assert not match.matched
    assert match.match_status == "unmatched"


def test_trackside_bssid_resolver_multi_match_uses_status():
    resolver = TracksideApBssidResolver(
        [
            {"ap_name": "AP-1", "ap_mac": "30f5-277a-5a2f"},
            {"ap_name": "AP-2", "ap_mac": "30f5-277a-5a2a"},
        ]
    )
    match = resolver.resolve("30f5-277a-5a2b")
    assert match.match_status == "unmatched"
    assert len(match.candidates) == 0


def test_netsh_wireless_parser_extracts_hidden_ssid_and_bssid_fields():
    networks = parse_netsh_networks(NETSH_SAMPLE)
    assert len(networks) == 2
    first = networks[0]
    assert first.ssid == "TracksideMesh"
    assert first.bssid == "30:f5:27:7a:5a:2f"
    assert first.rssi_dbm == -55
    assert first.channel == 149
    assert first.frequency_mhz == 5745
    assert first.band == "5G"
    assert first.auth == "WPA2-Personal"
    assert first.encryption == "CCMP"
    hidden = networks[1]
    assert hidden.is_hidden
    assert hidden.ssid == ""
    assert hidden.channel == 6
    assert hidden.scan_source == "netsh"
    assert hidden.mimo is None
    assert hidden.mimo_source == "unavailable"
    assert hidden.channel_width_text == "-"
    assert "netsh_no_ie_blob" in hidden.parse_warnings


def test_netsh_wireless_scanner_decodes_gbk_output(monkeypatch):
    raw = """
SSID 1 : 车地无线
    身份验证          : WPA2-个人
    加密              : CCMP
    BSSID 1           : 30:f5:27:7a:5a:2f
         信号         : 90%
         无线电类型   : 802.11ac
         频道         : 149
""".encode("gbk")

    def fake_run(cmd, **kwargs):
        assert kwargs == {"capture_output": True, "check": False}
        return subprocess.CompletedProcess(cmd, 0, stdout=raw, stderr=b"")

    monkeypatch.setattr("netconsole.services.network_tools.netsh_wireless_scanner.subprocess.run", fake_run)

    networks, text = NetshWirelessScanner().scan()

    assert "车地无线" in text
    assert networks[0].ssid == "车地无线"
    assert networks[0].channel == 149


def test_wireless_mimo_parser_vht_ht_and_unavailable():
    vht_payload = bytes([0, 0, 0, 0, 0xAA, 0xFF, 0, 0])
    vht_ie = bytes([191, len(vht_payload)]) + vht_payload
    vht = parse_mimo_from_ie_blob(vht_ie)
    assert vht.mimo == "4x4"
    assert vht.mimo_source == "vht_mcs_map"

    ht_mcs = bytearray(16)
    ht_mcs[0] = 0xFF
    ht_mcs[1] = 0xFF
    ht_payload = bytes([0, 0, 0]) + bytes(ht_mcs) + bytes(7)
    ht_ie = bytes([45, len(ht_payload)]) + ht_payload
    ht = parse_mimo_from_ie_blob(ht_ie)
    assert ht.mimo == "2x2"
    assert ht.mimo_source == "ht_mcs_set"
    assert parse_mimo_from_ie_blob(b"").mimo == "-"


def test_wireless_channel_width_parser_uses_vht_and_ht_operation():
    vht_80_payload = bytes([1, 149, 155])
    vht_160_payload = bytes([2, 149, 163])
    assert parse_channel_width_from_ie_blob(bytes([192, len(vht_80_payload)]) + vht_80_payload) == 80
    assert parse_channel_width_from_ie_blob(bytes([192, len(vht_160_payload)]) + vht_160_payload) == 160

    ht_40_payload = bytes([6, 1]) + bytes(20)
    ht_20_payload = bytes([6, 0]) + bytes(20)
    assert parse_channel_width_from_ie_blob(bytes([61, len(ht_40_payload)]) + ht_40_payload) == 40
    assert parse_channel_width_from_ie_blob(bytes([61, len(ht_20_payload)]) + ht_20_payload) == 20
    assert parse_channel_width_from_ie_blob(b"") is None


def test_wireless_ie_parser_reports_sources_and_no_ie_unavailable():
    parser = WirelessInformationElementParser()
    vht_payload = bytes([0, 0, 0, 0, 0xAA, 0xFF, 0, 0])
    vht_operation = bytes([1, 149, 155])
    info = parser.parse(bytes([191, len(vht_payload)]) + vht_payload + bytes([192, len(vht_operation)]) + vht_operation)
    assert info.channel_width_mhz == 80
    assert info.channel_width_source == "vht_operation"
    assert info.mimo == "4x4"
    assert info.mimo_source == "vht_mcs_map"

    empty = parser.parse(b"")
    assert empty.channel_width_text == "-"
    assert empty.mimo == "-"
    assert "ie_blob_unavailable" in empty.parse_warnings


def test_windows_wlan_bss_entry_binds_ie_capabilities():
    from netconsole.services.network_tools.windows_wlan_scanner import _WlanBssEntry, _network_from_bss_entry

    entry = _WlanBssEntry()
    ssid = b"TracksideMesh"
    entry.dot11Ssid.uSSIDLength = len(ssid)
    for index, value in enumerate(ssid):
        entry.dot11Ssid.ucSSID[index] = value
    for index, value in enumerate(bytes.fromhex("30f5277a5a2d")):
        entry.dot11Bssid[index] = value
    entry.lRssi = -51
    entry.uLinkQuality = 88
    entry.ulChCenterFrequency = 5745000
    entry.dot11BssPhyType = 8
    vht_payload = bytes([0, 0, 0, 0, 0xAA, 0xFF, 0, 0])
    vht_operation = bytes([1, 149, 155])
    network = _network_from_bss_entry(entry, "wlan0", "2026-06-22 10:00:00", bytes([191, len(vht_payload)]) + vht_payload + bytes([192, len(vht_operation)]) + vht_operation)
    assert network.scan_source == "wlan_api"
    assert network.bssid == "30f5277a5a2d"
    assert network.frequency_mhz == 5745
    assert network.channel == 149
    assert network.channel_width_mhz == 80
    assert network.channel_width_source == "vht_operation"
    assert network.mimo == "4x4"
    assert network.mimo_source == "vht_mcs_map"
    assert network.raw_ie_available is True

    no_ie = _network_from_bss_entry(entry, "wlan0", "2026-06-22 10:00:00", b"")
    assert no_ie.channel_width_text == "-"
    assert no_ie.mimo is None
    assert no_ie.raw_ie_available is False


def test_windows_wlan_bss_entry_decodes_non_utf8_ssid_with_fallback():
    from netconsole.services.network_tools.windows_wlan_scanner import _WlanBssEntry, _network_from_bss_entry

    entry = _WlanBssEntry()
    ssid = "车地无线".encode("gbk")
    entry.dot11Ssid.uSSIDLength = len(ssid)
    for index, value in enumerate(ssid):
        entry.dot11Ssid.ucSSID[index] = value
    for index, value in enumerate(bytes.fromhex("30f5277a5a2d")):
        entry.dot11Bssid[index] = value
    entry.lRssi = -51
    entry.uLinkQuality = 88
    entry.ulChCenterFrequency = 2412000
    entry.dot11BssPhyType = 7

    network = _network_from_bss_entry(entry, "wlan0", "2026-06-22 10:00:00", b"")

    assert network.ssid == "车地无线"
    assert network.raw["ssid_encoding"] in {"gb18030", "gbk"}
    assert network.raw["ssid_used_replacement"] is False
    assert any(str(warning).startswith("ssid_encoding_") for warning in network.parse_warnings)


def test_windows_wlan_bss_entry_marks_unrecoverable_ssid_decode_replacement():
    from netconsole.services.network_tools.windows_wlan_scanner import _WlanBssEntry, _network_from_bss_entry

    entry = _WlanBssEntry()
    ssid = b"\xff\xff\xff"
    entry.dot11Ssid.uSSIDLength = len(ssid)
    for index, value in enumerate(ssid):
        entry.dot11Ssid.ucSSID[index] = value
    for index, value in enumerate(bytes.fromhex("30f5277a5a2d")):
        entry.dot11Bssid[index] = value
    entry.lRssi = -51
    entry.uLinkQuality = 88
    entry.ulChCenterFrequency = 2412000
    entry.dot11BssPhyType = 7

    network = _network_from_bss_entry(entry, "wlan0", "2026-06-22 10:00:00", b"")

    assert network.raw["ssid_encoding"] == "utf-8-replace"
    assert network.raw["ssid_used_replacement"] is True
    assert "ssid_decode_replacement" in network.parse_warnings


def test_hybrid_wireless_merge_combines_wlan_width_mimo_and_netsh_security():
    wlan = WirelessNetwork(
        ssid="",
        bssid="DA:DA:21:EE:8E:54",
        rssi_dbm=-45,
        quality=80,
        channel=149,
        frequency_mhz=5745,
        band="5G",
        channel_width_mhz=80,
        channel_width_text="80 MHz",
        channel_width_source="vht_operation",
        mimo="4x4",
        mimo_source="vht_mcs_map",
        scan_source="wlan_api",
        raw_ie_available=True,
    )
    netsh = WirelessNetwork(
        ssid="TracksideMesh",
        bssid="dada-21ee-8e54",
        rssi_dbm=-52,
        quality=67,
        channel=149,
        frequency_mhz=5745,
        band="5G",
        auth="WPA3-Personal",
        encryption="CCMP",
        phy_type="802.11ax",
        scan_source="netsh",
    )
    rows = merge_wireless_networks([wlan], [netsh])
    assert len(rows) == 1
    merged = rows[0]
    assert merged.bssid == "dada21ee8e54"
    assert merged.ssid == "TracksideMesh"
    assert merged.rssi_dbm == -45
    assert merged.quality == 67
    assert merged.channel_width_text == "80 MHz"
    assert merged.mimo == "4x4"
    assert merged.auth == "WPA3-Personal"
    assert merged.encryption == "CCMP"
    assert merged.phy_type == "802.11ax"
    assert merged.scan_source == "hybrid"
    assert merged.has_wlan_api_data is True
    assert merged.has_netsh_data is True


def test_hybrid_wireless_merge_keeps_single_source_records_and_deduplicates_bssid():
    wlan_only = WirelessNetwork(
        ssid="",
        bssid="aa:bb:cc:dd:ee:ff",
        channel_width_mhz=160,
        channel_width_text="160 MHz",
        channel_width_source="vht_operation",
        mimo="2x2",
        scan_source="wlan_api",
    )
    netsh_hidden = WirelessNetwork(ssid="", bssid="11:22:33:44:55:66", auth="WPA2-Personal", encryption="CCMP", scan_source="netsh")
    netsh_named = WirelessNetwork(ssid="VisibleMesh", bssid="1122-3344-5566", auth="WPA3-Personal", encryption="GCMP", scan_source="netsh")
    rows = merge_wireless_networks([wlan_only], [netsh_hidden, netsh_named])
    assert len(rows) == 2
    wlan_row = next(row for row in rows if row.bssid == "aabbccddeeff")
    netsh_row = next(row for row in rows if row.bssid == "112233445566")
    assert wlan_row.scan_source == "wlan_api"
    assert wlan_row.channel_width_text == "160 MHz"
    assert wlan_row.auth == ""
    assert netsh_row.scan_source == "netsh"
    assert netsh_row.ssid == "VisibleMesh"
    assert netsh_row.auth == "WPA3-Personal"
    assert netsh_row.channel_width_text == "-"


class _FakeScanner:
    def __init__(self, networks=None, raw="raw", error: Exception | None = None):
        self.networks = networks or []
        self.raw = raw
        self.error = error

    def list_adapters(self):
        return [WirelessAdapter("fake")]

    def scan(self, _adapter=None):
        if self.error:
            raise self.error
        return self.networks, self.raw


def test_hybrid_wireless_scanner_auto_merge_and_fallbacks():
    wlan = WirelessNetwork(bssid="aa:bb:cc:00:00:01", channel_width_text="80 MHz", mimo="4x4", scan_source="wlan_api")
    netsh = WirelessNetwork(bssid="aabb-cc00-0001", ssid="Mesh", auth="WPA2-Personal", encryption="CCMP", scan_source="netsh")
    scanner = HybridWirelessScanner(_FakeScanner([wlan], "wlan raw"), _FakeScanner([netsh], "netsh raw"))
    rows, raw = scanner.scan()
    assert len(rows) == 1
    assert rows[0].scan_source == "hybrid"
    assert rows[0].ssid == "Mesh"
    assert "===== Windows WLAN API =====" in raw
    assert "===== netsh =====" in raw

    wlan_only = HybridWirelessScanner(_FakeScanner([wlan], "wlan raw"), _FakeScanner(error=RuntimeError("netsh down"))).scan()[0]
    assert len(wlan_only) == 1
    assert wlan_only[0].scan_source == "wlan_api"
    netsh_only = HybridWirelessScanner(_FakeScanner(error=RuntimeError("wlan down")), _FakeScanner([netsh], "netsh raw")).scan()[0]
    assert len(netsh_only) == 1
    assert netsh_only[0].scan_source == "netsh"


def test_wireless_scan_service_resolves_trackside_after_hybrid_merge(tmp_path, monkeypatch):
    wlan = WirelessNetwork(bssid="aa:bb:cc:00:00:02", channel_width_text="80 MHz", mimo="4x4", scan_source="wlan_api")
    netsh = WirelessNetwork(bssid="aabb-cc00-0002", ssid="Mesh", auth="WPA2-Personal", encryption="CCMP", scan_source="netsh")
    scanner = HybridWirelessScanner(_FakeScanner([wlan], "wlan raw"), _FakeScanner([netsh], "netsh raw"))
    service = WirelessScanService("demo", PathResolver(tmp_path), scanner=scanner)
    resolved: list[str] = []

    class Resolver:
        def resolve(self, bssid):
            resolved.append(bssid)
            return TracksideBssidMatch(matched=False, match_status="unmatched")

    monkeypatch.setattr(service, "_trackside_resolver", lambda: Resolver())
    result = service.scan()
    assert len(result.results) == 1
    assert resolved == ["aabbcc000002"]
    assert result.results[0].network.scan_source == "hybrid"


def test_wireless_scan_repository_persists_trackside_match_fields(tmp_path):
    repo = WirelessScanRepository(tmp_path / "wireless_scan.sqlite")
    result = WirelessScanResult(
        network=WirelessNetwork(ssid="", bssid="30:f5:27:7a:5a:2d", is_hidden=True, rssi_dbm=-60, channel=6, band="2.4G", last_seen="2026-06-22 10:00:00"),
        match=TracksideBssidMatch(matched=True, match_status="matched", ap_name="AP-1", ap_mac="30f5-277a-5a2f", station="S1", radio_id=3, match_rule="h3c_radio_3_nibble_minus_2"),
    )
    repo.save_scan("scan1", "demo", "wlan0", "guid", "start", "end", "success", "raw.txt", [result])
    runs = repo.list_runs()
    rows = repo.list_results("scan1")
    assert runs[0]["network_count"] == 1
    assert rows[0]["matched_trackside_ap"] == 1
    assert rows[0]["matched_ap_name"] == "AP-1"
    assert rows[0]["matched_radio_id"] == 3


def test_wireless_scan_export_contains_trackside_columns(tmp_path):
    row = result_to_row(
        WirelessScanResult(
            network=WirelessNetwork(ssid="", bssid="30:f5:27:7a:5a:2d", is_hidden=True, rssi_dbm=-60, channel=6, band="2.4G", channel_width_mhz=40, last_seen="2026-06-22 10:00:00"),
            match=TracksideBssidMatch(matched=True, match_status="matched", ap_name="AP-1", ap_mac="30f5-277a-5a2f", station="S1", radio_id=3, match_rule="h3c_radio_3_nibble_minus_2"),
        )
    )
    headers = [key for key, _field in WIRELESS_SCAN_EXPORT_COLUMNS]
    path = tmp_path / "wireless_trackside_scan.xlsx"
    export_wireless_scan_xlsx(path, [row], headers)
    sheet = load_workbook(path).active
    assert [cell.value for cell in sheet[1]] == EXPECTED_DISPLAY_KEYS
    assert "wireless_scan.match_status" not in [cell.value for cell in sheet[1]]
    assert "wireless_scan.match_rule" not in [cell.value for cell in sheet[1]]
    assert sheet["A2"].value == "Hidden"
    assert sheet["B2"].value == "30f5-277a-5a2d"
    assert sheet["D2"].value == "AP-1"
    assert sheet["P2"].value == "40 MHz"


def test_wireless_display_columns_have_required_order():
    assert [key for key, _field in WIRELESS_SCAN_DISPLAY_COLUMNS] == EXPECTED_DISPLAY_KEYS
    assert WIRELESS_SCAN_EXPORT_COLUMNS == WIRELESS_SCAN_DISPLAY_COLUMNS
