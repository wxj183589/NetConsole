from __future__ import annotations

from dataclasses import dataclass

from netconsole.services.network_tools.wireless_ie_parser import parse_wireless_capabilities


@dataclass(frozen=True)
class WirelessMimoParseResult:
    mimo: str
    mimo_source: str
    mimo_note: str = ""


def parse_mimo_from_ie_blob(ie_blob: bytes | bytearray | memoryview | None) -> WirelessMimoParseResult:
    info = parse_wireless_capabilities(ie_blob)
    return WirelessMimoParseResult(info.mimo, info.mimo_source, info.mimo_note)


def parse_channel_width_from_ie_blob(ie_blob: bytes | bytearray | memoryview | None) -> int | None:
    return parse_wireless_capabilities(ie_blob).channel_width_mhz


def unavailable_mimo() -> WirelessMimoParseResult:
    return WirelessMimoParseResult("-", "unavailable", "scan_source_unavailable")


def parse_he_mimo(_elements: dict[int, bytes]) -> WirelessMimoParseResult:
    return unavailable_mimo()


def _parse_vht_mimo(payload: bytes | None) -> WirelessMimoParseResult:
    if not payload or len(payload) < 8:
        return unavailable_mimo()
    rx_mcs_map = int.from_bytes(payload[4:6], "little")
    stream_count = 0
    for index in range(8):
        bits = (rx_mcs_map >> (index * 2)) & 0b11
        if bits != 0b11:
            stream_count = index + 1
    if stream_count <= 0:
        return unavailable_mimo()
    return WirelessMimoParseResult(f"{stream_count}x{stream_count}", "vht_mcs_map", "mimo_capability_note")


def _parse_ht_mimo(payload: bytes | None) -> WirelessMimoParseResult:
    if not payload or len(payload) < 19:
        return unavailable_mimo()
    mcs_set = payload[3:19]
    stream_count = 0
    for index in range(4):
        if mcs_set[index] != 0:
            stream_count = index + 1
    if stream_count <= 0:
        return unavailable_mimo()
    return WirelessMimoParseResult(f"{stream_count}x{stream_count}", "ht_mcs_set", "mimo_capability_note")


def _parse_vht_channel_width(payload: bytes | None) -> int | None:
    if not payload:
        return None
    channel_width = payload[0]
    if channel_width == 1:
        return 80
    if channel_width in {2, 3}:
        return 160
    return None


def _parse_ht_channel_width(payload: bytes | None) -> int | None:
    if not payload or len(payload) < 2:
        return None
    secondary_channel_offset = payload[1] & 0b11
    return 40 if secondary_channel_offset in {1, 3} else 20


def _iter_information_elements(blob: bytes) -> dict[int, bytes]:
    elements: dict[int, bytes] = {}
    offset = 0
    while offset + 2 <= len(blob):
        element_id = blob[offset]
        length = blob[offset + 1]
        offset += 2
        if offset + length > len(blob):
            break
        elements[element_id] = blob[offset : offset + length]
        offset += length
    return elements
