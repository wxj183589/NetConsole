from __future__ import annotations

import os

from openpyxl import load_workbook

from netconsole.core.paths import PathResolver
from netconsole.models.wireless_scan_models import TracksideBssidMatch, WirelessNetwork, WirelessScanResult
from netconsole.repositories.wireless_scan_repository import WirelessScanRepository
from netconsole.services.network_tools.netsh_wireless_scanner import parse_netsh_networks
from netconsole.services.network_tools.trackside_bssid_resolver import TracksideApBssidResolver
from netconsole.services.network_tools.hybrid_wireless_scanner import HybridWirelessScanner, merge_wireless_networks
from netconsole.services.network_tools.wireless_channel_analyzer import band_from_frequency, frequency_to_channel, normalize_mac, rssi_level
from netconsole.services.network_tools.wireless_ie_parser import WirelessInformationElementParser
from netconsole.services.network_tools.wireless_mimo_parser import parse_channel_width_from_ie_blob, parse_mimo_from_ie_blob
from netconsole.services.network_tools.wireless_scan_service import WIRELESS_SCAN_EXPORT_COLUMNS, WIRELESS_SCAN_DISPLAY_COLUMNS, WirelessScanService, export_wireless_scan_xlsx, result_to_row, wireless_scanner_external_path


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


def test_h3c_trackside_bssid_resolver_radio_rules_and_no_wrap():
    resolver = TracksideApBssidResolver([{"ap_name": "AP-1", "ap_mac": "083b-e9ec-da5f", "site_name": "S1", "location_note": "K1", "direction": "up"}])
    radio1 = resolver.resolve("083b-e9ec-da5f")
    assert radio1.radio_id == 1
    assert radio1.ap_mac == "083b-e9ec-da5f"
    assert radio1.match_rule == "h3c_radio_1_ap_mac_prefix11"
    radio2 = TracksideApBssidResolver([{"ap_name": "AP-2", "ap_mac": "083b-e9ec-da40", "site_name": "S2"}]).resolve("083b-e9ec-da5f")
    assert radio2.radio_id == 2
    assert radio2.ap_mac == "083b-e9ec-da40"
    assert radio2.match_rule == "h3c_radio_2_ap_mac_nibble_plus_1"
    second_vendor_sample = TracksideApBssidResolver([{"ap_name": "AP-3", "ap_mac": "94a7-482c-1140", "site_name": "S3"}]).resolve("94a7-482c-115f")
    assert second_vendor_sample.radio_id == 2
    assert second_vendor_sample.ap_mac == "94a7-482c-1140"
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


def test_trackside_bssid_resolver_can_match_peer_name_to_ap_name():
    resolver = TracksideApBssidResolver([{"ap_name": "AP-Name-01", "ap_mac": "083b-e9ec-da4f", "site_name": "S1"}])

    match = resolver.resolve("1122-3344-5566", peer_name="AP-Name-01")

    assert match.matched
    assert match.ap_name == "AP-Name-01"
    assert match.ap_mac == "083b-e9ec-da4f"
    assert match.radio_id is None
    assert match.match_rule == "mesh_peer_name_ap_name_exact"


def test_trackside_bssid_resolver_preserves_section_belonging():
    resolver = TracksideApBssidResolver(
        [
            {
                "ap_name": "ap0303_a",
                "ap_mac_display": "5866-bab3-0a40",
                "belong_type": "section",
                "station_name": "",
                "section_name": "联庄-中医药大学",
                "_identity_source": "ap_metadata",
            }
        ]
    )

    match = resolver.resolve("5866-bab3-0a40")

    assert match.matched
    assert match.ap_name == "ap0303_a"
    assert match.station == ""
    assert match.section == "联庄-中医药大学"
    assert match.belong_type == "section"
    assert match.belonging_source == "ap_metadata"


def test_trackside_bssid_resolver_matches_name_only_extension_section():
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

    assert match.matched
    assert match.ap_name == "ap0303_a"
    assert match.ap_mac == ""
    assert match.section == "联庄-中医药大学"
    assert match.match_rule == "mesh_peer_name_ap_name_exact"


def test_trackside_bssid_resolver_multi_match_uses_status():
    resolver = TracksideApBssidResolver(
        [
            {"ap_name": "AP-1", "ap_mac": "30f5-277a-5a2f"},
            {"ap_name": "AP-2", "ap_mac": "30f5-277a-5a2a"},
        ]
    )
    match = resolver.resolve("30f5-277a-5a2b")
    assert match.match_status == "multi_match"
    assert len(match.candidates) == 2


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


def test_wireless_external_tool_path_and_network_tools_tab(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tool = tmp_path / "tools" / "wifi_scanner" / "WiFiScannerPortable.exe"
    tool.parent.mkdir(parents=True)
    tool.write_text("", encoding="utf-8")
    assert wireless_scanner_external_path(PathResolver(tmp_path)) == tool

    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages.wireless_scan_page import WirelessScanPage
    from netconsole.ui.pages.network_tools_page import NetworkToolsPage

    monkeypatch.setattr(WirelessScanPage, "load_adapters", lambda self: None)
    app = QApplication.instance() or QApplication([])
    assert app is not None
    page = NetworkToolsPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    assert page.tabs.count() == 4
    assert page.tabs.tabText(3) == "Toolbox"
    assert page.tabs.tabText(1) == "Wireless Scan"
    assert page.tabs.tabText(2) == "Local Adapter Config"


def test_wireless_scan_page_headers_hidden_fields_search_sort_and_width(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages.wireless_scan_page import WirelessScanPage

    monkeypatch.setattr(WirelessScanPage, "load_adapters", lambda self: None)
    app = QApplication.instance() or QApplication([])
    assert app is not None
    page = WirelessScanPage(I18n("zh_CN"), "demo", PathResolver(tmp_path))
    tab_titles = [page.tabs.tabText(index) for index in range(page.tabs.count())]
    assert page.tabs.count() == 3
    assert tab_titles == ["扫描结果", "扫描历史", "原始输出"]
    assert "2.4G信道图" not in tab_titles
    assert "5G信道图" not in tab_titles
    assert page.tabs.currentIndex() == 0
    headers = [page.result_table.horizontalHeaderItem(index).text() for index in range(page.result_table.columnCount())]
    assert headers == ["SSID", "MAC地址", "AP_MAC", "AP名称", "射频口", "归属站点", "归属区间", "归属类型", "归属来源", "位置/里程", "RSSI", "信号质量", "信道", "频率", "频段", "频宽", "MIMO", "加密方式", "加密", "认证方式"]
    for hidden in {"匹配状态", "匹配规则", "是否隐藏SSID", "最后扫描时间", "安全类型", "PHY模式", "厂商"}:
        assert hidden not in headers
    assert page.result_table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert page.result_table.wordWrap() is False
    assert page.result_table.columnWidth(1) >= 130
    assert page.result_table.columnWidth(2) >= 130
    assert page.result_table.columnWidth(3) >= 140
    assert page.scan_source_combo.currentData() == "auto"

    matched_weak = result_to_row(
        WirelessScanResult(
            network=WirelessNetwork(ssid="mesh-a", bssid="30:f5:27:7a:5a:2d", is_hidden=False, rssi_dbm=-97, quality=20, channel=48, frequency_mhz=5240, band="5G", encryption="CCMP", auth="WPA2-Personal"),
            match=TracksideBssidMatch(matched=True, match_status="matched", ap_name="AP-B", ap_mac="30f5-277a-5a2f", station="S2", location="K2", radio_id=3),
        )
    )
    matched_strong = result_to_row(
        WirelessScanResult(
            network=WirelessNetwork(ssid="", bssid="30:f5:27:7a:5a:1f", is_hidden=True, rssi_dbm=-50, quality=100, channel=157, frequency_mhz=5785, band="5G", encryption="CCMP", auth="WPA3-Personal"),
            match=TracksideBssidMatch(matched=True, match_status="matched", ap_name="AP-A", ap_mac="30f5-277a-5a2f", station="S1", mileage="K1", radio_id=2),
        )
    )
    unmatched = result_to_row(
        WirelessScanResult(
            network=WirelessNetwork(ssid="guest", bssid="40:f5:27:7a:5a:2f", is_hidden=False, rssi_dbm=-40, quality=100, channel=6, frequency_mhz=2437, band="2.4G", encryption="Open", auth="Open"),
            match=TracksideBssidMatch(matched=False, match_status="unmatched"),
        )
    )
    page.current_rows = [unmatched, matched_weak, matched_strong]
    page.apply_filters()
    assert page.result_table.item(0, 3).text() == "AP-A"
    assert page.result_table.item(1, 3).text() == "AP-B"
    assert page.result_table.item(2, 3).text() == "-"
    assert page.result_table.item(0, 0).text() == "隐藏"
    assert page.result_table.item(2, 2).text() == "-"

    netsh_row = result_to_row(
        WirelessScanResult(
            network=WirelessNetwork(ssid="netsh-only", bssid="50:f5:27:7a:5a:2f", is_hidden=False, rssi_dbm=-70, channel=44, frequency_mhz=5220, band="5G", scan_source="netsh"),
            match=TracksideBssidMatch(matched=False, match_status="unmatched"),
        )
    )
    page.current_rows = [netsh_row]
    page.apply_filters()
    assert page.result_table.item(0, 15).text() == "-"

    page.current_rows = [unmatched, matched_weak, matched_strong]
    page.apply_filters()
    page.search_edit.setText("K2")
    assert page.result_table.rowCount() == 1
    assert page.result_table.item(0, 3).text() == "AP-B"
    page.search_edit.setText("40f5")
    assert page.result_table.rowCount() == 1
    assert page.result_table.item(0, 0).text() == "guest"

    page.search_edit.clear()
    page.sort_column = [field for _key, field in WIRELESS_SCAN_DISPLAY_COLUMNS].index("display_rssi")
    page.sort_order = Qt.AscendingOrder
    page.apply_filters()
    assert [page.result_table.item(index, 10).text() for index in range(page.result_table.rowCount())] == ["-97", "-50", "-40"]
    page.sort_order = Qt.DescendingOrder
    page.apply_filters()
    assert [page.result_table.item(index, 10).text() for index in range(page.result_table.rowCount())] == ["-40", "-50", "-97"]

    page.current_rows = [
        {**matched_strong, "display_mimo": "-"},
        {**matched_strong, "display_mimo": "4x4", "bssid": "a"},
        {**matched_strong, "display_mimo": "2x2", "bssid": "b"},
        {**matched_strong, "display_mimo": "1x1", "bssid": "c"},
    ]
    page.sort_column = [field for _key, field in WIRELESS_SCAN_DISPLAY_COLUMNS].index("display_mimo")
    page.sort_order = Qt.AscendingOrder
    page.apply_filters()
    assert [page.result_table.item(index, 16).text() for index in range(page.result_table.rowCount())] == ["1x1", "2x2", "4x4", "-"]

    page.result_table.setColumnWidth(3, 260)
    page.column_state.save_now()
    page.current_rows = [matched_strong]
    page.apply_filters()
    page.column_state.restore()
    assert page.result_table.columnWidth(3) == 260


def test_wireless_scan_page_restores_page_settings_and_field_widths(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.models.wireless_scan_models import WirelessAdapter
    from netconsole.ui.pages.wireless_scan_page import WirelessScanPage

    monkeypatch.setattr(WirelessScanPage, "load_adapters", lambda self: None)
    app = QApplication.instance() or QApplication([])
    assert app is not None

    page = WirelessScanPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    page.adapter_combo.addItem("Adapter A", WirelessAdapter(name="Adapter A", guid="guid-a"))
    page.scan_source_combo.setCurrentIndex(page.scan_source_combo.findData("hybrid"))
    page.auto_refresh_check.setChecked(True)
    page.interval_spin.setValue(9)
    page.only_trackside_check.setChecked(True)
    page.band_filter.setCurrentIndex(page.band_filter.findData("5G"))
    page.radio_filter.setCurrentIndex(page.radio_filter.findData(2))
    page.tabs.setCurrentIndex(2)
    page.sort_column = [field for _key, field in WIRELESS_SCAN_DISPLAY_COLUMNS].index("display_signal_quality")
    page.sort_order = Qt.DescendingOrder
    page.result_table.setColumnWidth(3, 260)
    page.column_state.save_now()
    page.save_settings()

    restored = WirelessScanPage(I18n("en_US"), "demo", PathResolver(tmp_path))
    assert restored.auto_refresh_check.isChecked()
    assert restored.scan_source_combo.currentData() == "hybrid"
    assert restored.interval_spin.value() == 9
    assert restored.only_trackside_check.isChecked()
    assert restored.band_filter.currentData() == "5G"
    assert restored.radio_filter.currentData() == 2
    assert restored.tabs.currentIndex() == 2
    assert restored.sort_column == [field for _key, field in WIRELESS_SCAN_DISPLAY_COLUMNS].index("display_signal_quality")
    assert restored.sort_order == Qt.DescendingOrder
    assert restored.result_table.columnWidth(3) == 260

    restored._adapters_loaded([WirelessAdapter(name="Adapter A", guid="guid-a"), WirelessAdapter(name="Adapter B", guid="guid-b")])
    assert restored.adapter_combo.currentData().guid == "guid-a"


def test_wireless_scan_page_ignores_removed_channel_tab_cache(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.core.settings import SettingsStore
    from netconsole.ui.pages.wireless_scan_page import WirelessScanPage

    monkeypatch.setattr(WirelessScanPage, "load_adapters", lambda self: None)
    settings = SettingsStore(PathResolver(tmp_path))
    settings.values["network_tools/wireless_scan/current_tab"] = 2
    settings.save()

    app = QApplication.instance() or QApplication([])
    assert app is not None
    page = WirelessScanPage(I18n("en_US"), "demo", PathResolver(tmp_path))

    assert page.tabs.count() == 3
    assert page.tabs.currentIndex() == 0
    assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == ["Scan Results", "Scan History", "Raw Output"]
