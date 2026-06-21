from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from time import sleep

from netconsole.models.wireless_scan_models import WirelessAdapter, WirelessNetwork
from netconsole.services.network_tools.netsh_wireless_scanner import NetshWirelessScanner
from netconsole.services.network_tools.wireless_channel_analyzer import band_from_frequency, frequency_to_channel, normalize_mac
from netconsole.services.network_tools.wireless_ie_parser import parse_wireless_capabilities


SCAN_SOURCE_AUTO = "auto"
SCAN_SOURCE_HYBRID = "hybrid"
SCAN_SOURCE_WLAN_API = "wlan_api"
SCAN_SOURCE_NETSH = "netsh"

ERROR_SUCCESS = 0
WLAN_CLIENT_VERSION = 2


class WindowsWlanScanner:
    """Windows Native WiFi scanner with netsh fallback.

    The Native WiFi API exposes WLAN_BSS_ENTRY IE blobs. Those blobs carry the
    HT/VHT capability and operation IEs required for channel width and MIMO.
    netsh remains as a fallback because it usually returns only basic BSSID
    fields and does not promise full Beacon/Probe Response IE data.
    """

    def __init__(self, fallback: NetshWirelessScanner | None = None, scan_source: str = SCAN_SOURCE_AUTO) -> None:
        self.fallback = fallback or NetshWirelessScanner()
        self.scan_source = scan_source if scan_source in {SCAN_SOURCE_AUTO, SCAN_SOURCE_HYBRID, SCAN_SOURCE_WLAN_API, SCAN_SOURCE_NETSH} else SCAN_SOURCE_AUTO

    def list_adapters(self) -> list[WirelessAdapter]:
        if self.scan_source != SCAN_SOURCE_NETSH:
            try:
                adapters = self._list_adapters_wlan_api()
                if adapters:
                    return adapters
            except Exception:
                if self.scan_source == SCAN_SOURCE_WLAN_API:
                    raise
        return self.fallback.list_adapters()

    def scan(self, adapter: WirelessAdapter | None = None) -> tuple[list[WirelessNetwork], str]:
        if self.scan_source == SCAN_SOURCE_NETSH:
            return self.fallback.scan(adapter)
        try:
            return self._scan_wlan_api(adapter)
        except Exception:
            if self.scan_source == SCAN_SOURCE_WLAN_API:
                raise
            return self.fallback.scan(adapter)

    def _list_adapters_wlan_api(self) -> list[WirelessAdapter]:
        if sys.platform != "win32":
            raise RuntimeError("Windows WLAN API is only available on Windows")
        with _WlanClient() as client:
            interfaces = client.enum_interfaces()
        return [WirelessAdapter(name=item.description, guid=_guid_to_string(item.interface_guid), state=str(item.state)) for item in interfaces]

    def _scan_wlan_api(self, adapter: WirelessAdapter | None) -> tuple[list[WirelessNetwork], str]:
        if sys.platform != "win32":
            raise RuntimeError("Windows WLAN API is only available on Windows")
        lines: list[str] = []
        networks: list[WirelessNetwork] = []
        last_seen = datetime.now().isoformat(sep=" ", timespec="seconds")
        with _WlanClient() as client:
            interfaces = client.enum_interfaces()
            selected = _select_interfaces(interfaces, adapter)
            if not selected:
                raise RuntimeError("No matching wireless adapter was found")
            for interface in selected:
                client.scan(interface.interface_guid)
                sleep(1.2)
                for bss in client.get_bss_entries(interface.interface_guid):
                    try:
                        network = _network_from_bss_entry(bss.entry, interface.description, last_seen, bss.ie_blob)
                    except Exception as exc:
                        lines.append(f"skip bss parse error: {exc}")
                        continue
                    networks.append(network)
                    lines.append(_debug_line(network))
        if not networks:
            lines.append("Windows WLAN API scan returned no BSS entries")
        return networks, "\n".join(lines)


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _Dot11Ssid(ctypes.Structure):
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]


class _WlanRateSet(ctypes.Structure):
    _fields_ = [("uRateSetLength", wintypes.ULONG), ("usRateSet", wintypes.USHORT * 126)]


class _WlanInterfaceInfo(ctypes.Structure):
    _fields_ = [("interface_guid", _Guid), ("description", wintypes.WCHAR * 256), ("state", wintypes.DWORD)]


class _WlanInterfaceInfoList(ctypes.Structure):
    _fields_ = [("number_of_items", wintypes.DWORD), ("index", wintypes.DWORD), ("interface_info", _WlanInterfaceInfo * 1)]


class _WlanBssEntry(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", _Dot11Ssid),
        ("uPhyId", wintypes.ULONG),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11BssType", wintypes.DWORD),
        ("dot11BssPhyType", wintypes.DWORD),
        ("lRssi", wintypes.LONG),
        ("uLinkQuality", wintypes.ULONG),
        ("bInRegDomain", wintypes.BOOL),
        ("usBeaconPeriod", wintypes.USHORT),
        ("ullTimestamp", ctypes.c_ulonglong),
        ("ullHostTimestamp", ctypes.c_ulonglong),
        ("usCapabilityInformation", wintypes.USHORT),
        ("ulChCenterFrequency", wintypes.ULONG),
        ("wlanRateSet", _WlanRateSet),
        ("ulIeOffset", wintypes.ULONG),
        ("ulIeSize", wintypes.ULONG),
    ]


class _WlanBssList(ctypes.Structure):
    _fields_ = [("total_size", wintypes.DWORD), ("number_of_items", wintypes.DWORD), ("bss_entry", _WlanBssEntry * 1)]


@dataclass(frozen=True)
class _BssEntryData:
    entry: _WlanBssEntry
    ie_blob: bytes


class _WlanClient:
    def __init__(self) -> None:
        self.wlanapi = ctypes.WinDLL("wlanapi")
        self.handle = wintypes.HANDLE()
        negotiated_version = wintypes.DWORD()
        code = self.wlanapi.WlanOpenHandle(WLAN_CLIENT_VERSION, None, ctypes.byref(negotiated_version), ctypes.byref(self.handle))
        _raise_if_error(code, "WlanOpenHandle")

    def __enter__(self) -> _WlanClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self.handle:
            self.wlanapi.WlanCloseHandle(self.handle, None)
            self.handle = wintypes.HANDLE()

    def enum_interfaces(self) -> list[_WlanInterfaceInfo]:
        pointer = ctypes.c_void_p()
        code = self.wlanapi.WlanEnumInterfaces(self.handle, None, ctypes.byref(pointer))
        _raise_if_error(code, "WlanEnumInterfaces")
        try:
            header = ctypes.cast(pointer, ctypes.POINTER(_WlanInterfaceInfoList)).contents
            array_type = _WlanInterfaceInfo * header.number_of_items
            array = ctypes.cast(ctypes.addressof(header.interface_info), ctypes.POINTER(array_type)).contents
            return [array[index] for index in range(header.number_of_items)]
        finally:
            self.wlanapi.WlanFreeMemory(pointer)

    def scan(self, guid: _Guid) -> None:
        code = self.wlanapi.WlanScan(self.handle, ctypes.byref(guid), None, None, None)
        _raise_if_error(code, "WlanScan")

    def get_bss_entries(self, guid: _Guid) -> list[_BssEntryData]:
        pointer = ctypes.c_void_p()
        code = self.wlanapi.WlanGetNetworkBssList(self.handle, ctypes.byref(guid), None, 1, False, None, ctypes.byref(pointer))
        _raise_if_error(code, "WlanGetNetworkBssList")
        try:
            header = ctypes.cast(pointer, ctypes.POINTER(_WlanBssList)).contents
            array_type = _WlanBssEntry * header.number_of_items
            array = ctypes.cast(ctypes.addressof(header.bss_entry), ctypes.POINTER(array_type)).contents
            entries: list[_BssEntryData] = []
            for index in range(header.number_of_items):
                entry = array[index]
                entry_address = ctypes.addressof(array[index])
                entries.append(_BssEntryData(entry=entry, ie_blob=_ie_blob_from_entry_address(entry, entry_address)))
            return entries
        finally:
            self.wlanapi.WlanFreeMemory(pointer)


def _network_from_bss_entry(entry: _WlanBssEntry, adapter_name: str, last_seen: str, ie_blob: bytes | None = None) -> WirelessNetwork:
    ssid = bytes(entry.dot11Ssid.ucSSID[: min(entry.dot11Ssid.uSSIDLength, 32)]).decode("utf-8", errors="replace")
    bssid = "".join(f"{byte:02x}" for byte in entry.dot11Bssid)
    frequency_mhz = int(entry.ulChCenterFrequency / 1000) if entry.ulChCenterFrequency else None
    channel = frequency_to_channel(frequency_mhz)
    ie_blob = ie_blob if ie_blob is not None else _ie_blob_from_entry(entry)
    capability = parse_wireless_capabilities(ie_blob)
    return WirelessNetwork(
        ssid=ssid,
        bssid=bssid,
        rssi_dbm=int(entry.lRssi),
        quality=int(entry.uLinkQuality),
        band=band_from_frequency(frequency_mhz),
        channel=channel,
        frequency_mhz=frequency_mhz,
        channel_width_mhz=capability.channel_width_mhz,
        channel_width_text=capability.channel_width_text,
        channel_width_source=capability.channel_width_source,
        channel_width=capability.channel_width_text,
        phy_type=_phy_type_name(int(entry.dot11BssPhyType)),
        auth="",
        encryption="",
        is_hidden=not bool(ssid),
        last_seen=last_seen,
        mimo=None if capability.mimo == "-" else capability.mimo,
        mimo_source=capability.mimo_source,
        mimo_note=capability.mimo_note,
        scan_source="wlan_api",
        raw_ie_hex=ie_blob.hex(),
        raw_ie_available=bool(ie_blob),
        parse_warnings=capability.parse_warnings,
        raw={
            "adapter": adapter_name,
            "raw_ie_available": bool(ie_blob),
            "raw_ie_size": len(ie_blob),
            "channel_width_source": capability.channel_width_source,
            "mimo_source": capability.mimo_source,
            "parse_warnings": capability.parse_warnings,
        },
    )


def _ie_blob_from_entry(entry: _WlanBssEntry) -> bytes:
    if not entry.ulIeOffset or not entry.ulIeSize:
        return b""
    address = ctypes.addressof(entry) + int(entry.ulIeOffset)
    return ctypes.string_at(address, int(entry.ulIeSize))


def _ie_blob_from_entry_address(entry: _WlanBssEntry, entry_address: int) -> bytes:
    if not entry.ulIeOffset or not entry.ulIeSize:
        return b""
    return ctypes.string_at(entry_address + int(entry.ulIeOffset), int(entry.ulIeSize))


def _select_interfaces(interfaces: list[_WlanInterfaceInfo], adapter: WirelessAdapter | None) -> list[_WlanInterfaceInfo]:
    if adapter is None:
        return interfaces
    wanted = {adapter.guid.casefold(), adapter.name.casefold()}
    selected = []
    for interface in interfaces:
        if _guid_to_string(interface.interface_guid).casefold() in wanted or str(interface.description).casefold() in wanted:
            selected.append(interface)
    return selected


def _guid_to_string(guid: _Guid) -> str:
    data4 = bytes(guid.Data4)
    return f"{guid.Data1:08x}-{guid.Data2:04x}-{guid.Data3:04x}-{data4[0]:02x}{data4[1]:02x}-{data4[2:].hex()}"


def _phy_type_name(value: int) -> str:
    return {
        4: "802.11b",
        5: "802.11a",
        6: "802.11g",
        7: "802.11n",
        8: "802.11ac",
        9: "802.11ad",
        10: "802.11ax",
    }.get(value, str(value) if value else "")


def _debug_line(network: WirelessNetwork) -> str:
    return (
        f"BSSID={normalize_mac(network.bssid) or network.bssid} "
        f"scan_source={network.scan_source} frequency={network.frequency_mhz or '-'} "
        f"channel={network.channel or '-'} channel_width={network.channel_width_text or '-'} "
        f"channel_width_source={network.channel_width_source or 'unavailable'} "
        f"mimo={network.mimo or '-'} mimo_source={network.mimo_source or 'unavailable'} "
        f"ie_blob_size={len(network.raw_ie_hex) // 2} "
        f"parse_warnings={','.join(network.parse_warnings) or '-'}"
    )


def _raise_if_error(code: int, operation: str) -> None:
    if code != ERROR_SUCCESS:
        raise RuntimeError(f"{operation} failed: {code}")
