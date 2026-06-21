from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WirelessCapabilityInfo:
    channel_width_mhz: int | None = None
    channel_width_text: str = "-"
    channel_width_source: str = "unavailable"
    mimo: str = "-"
    mimo_source: str = "unavailable"
    mimo_note: str = ""
    ht_supported: bool = False
    vht_supported: bool = False
    he_supported: bool = False
    parse_warnings: list[str] = field(default_factory=list)


class WirelessInformationElementParser:
    """Parse AP Beacon/Probe Response Information Elements.

    netsh wlan show networks mode=bssid normally exposes only basic network
    fields. Channel width and MIMO require 802.11 IE data from lower-level BSS
    scan sources such as the Windows Native WiFi API.
    """

    def parse(self, ie_blob: bytes | bytearray | memoryview | None) -> WirelessCapabilityInfo:
        warnings: list[str] = []
        if not ie_blob:
            return WirelessCapabilityInfo(mimo_note="scan_source_unavailable", parse_warnings=["ie_blob_unavailable"])
        elements = _iter_information_elements(bytes(ie_blob), warnings)
        ht_supported = 45 in elements
        vht_supported = 191 in elements
        he_supported = _has_he_elements(elements)
        if he_supported:
            warnings.append("he_parser_not_implemented")

        width_mhz, width_text, width_source = self._parse_channel_width(elements)
        mimo, mimo_source, mimo_note = self._parse_mimo(elements)
        return WirelessCapabilityInfo(
            channel_width_mhz=width_mhz,
            channel_width_text=width_text,
            channel_width_source=width_source,
            mimo=mimo,
            mimo_source=mimo_source,
            mimo_note=mimo_note,
            ht_supported=ht_supported,
            vht_supported=vht_supported,
            he_supported=he_supported,
            parse_warnings=warnings,
        )

    def _parse_channel_width(self, elements: dict[int, list[bytes]]) -> tuple[int | None, str, str]:
        vht_width = _parse_vht_channel_width(_first(elements, 192))
        if vht_width:
            return vht_width[0], vht_width[1], "vht_operation"
        ht_width = _parse_ht_channel_width(_first(elements, 61))
        if ht_width:
            return ht_width, f"{ht_width} MHz", "ht_operation"
        return None, "-", "unavailable"

    def _parse_mimo(self, elements: dict[int, list[bytes]]) -> tuple[str, str, str]:
        vht_streams = _parse_vht_mimo_streams(_first(elements, 191))
        if vht_streams:
            return f"{vht_streams}x{vht_streams}", "vht_mcs_map", "mimo_capability_note"
        ht_streams = _parse_ht_mimo_streams(_first(elements, 45))
        if ht_streams:
            return f"{ht_streams}x{ht_streams}", "ht_mcs_set", "mimo_capability_note"
        return "-", "unavailable", "scan_source_unavailable"


def parse_wireless_capabilities(ie_blob: bytes | bytearray | memoryview | None) -> WirelessCapabilityInfo:
    return WirelessInformationElementParser().parse(ie_blob)


def _parse_vht_channel_width(payload: bytes | None) -> tuple[int | None, str] | None:
    if not payload:
        return None
    channel_width = payload[0]
    if channel_width == 1:
        return 80, "80 MHz"
    if channel_width == 2:
        return 160, "160 MHz"
    if channel_width == 3:
        return None, "80+80 MHz"
    return None


def _parse_ht_channel_width(payload: bytes | None) -> int | None:
    if not payload or len(payload) < 2:
        return None
    secondary_channel_offset = payload[1] & 0b11
    return 40 if secondary_channel_offset in {1, 3} else 20


def _parse_vht_mimo_streams(payload: bytes | None) -> int:
    if not payload or len(payload) < 8:
        return 0
    rx_mcs_map = int.from_bytes(payload[4:6], "little")
    stream_count = 0
    for index in range(8):
        bits = (rx_mcs_map >> (index * 2)) & 0b11
        if bits != 0b11:
            stream_count = index + 1
    return min(stream_count, 8)


def _parse_ht_mimo_streams(payload: bytes | None) -> int:
    if not payload or len(payload) < 19:
        return 0
    mcs_set = payload[3:19]
    stream_count = 0
    for index in range(4):
        if mcs_set[index] != 0:
            stream_count = index + 1
    return stream_count


def _iter_information_elements(blob: bytes, warnings: list[str]) -> dict[int, list[bytes]]:
    elements: dict[int, list[bytes]] = {}
    offset = 0
    while offset + 2 <= len(blob):
        element_id = blob[offset]
        length = blob[offset + 1]
        offset += 2
        if offset + length > len(blob):
            warnings.append(f"truncated_ie_{element_id}")
            break
        elements.setdefault(element_id, []).append(blob[offset : offset + length])
        offset += length
    if offset != len(blob):
        warnings.append("trailing_ie_bytes")
    return elements


def _first(elements: dict[int, list[bytes]], element_id: int) -> bytes | None:
    values = elements.get(element_id)
    return values[0] if values else None


def _has_he_elements(elements: dict[int, list[bytes]]) -> bool:
    for payload in elements.get(255, []):
        if payload and payload[0] in {35, 36}:
            return True
    return False
