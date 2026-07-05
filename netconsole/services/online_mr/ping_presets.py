from __future__ import annotations

from dataclasses import dataclass


CUSTOM_PING_PRESET_KEY = ""
DEFAULT_PING_PRESET_KEY = "pis_high_ping_acceptance"


@dataclass(frozen=True)
class HighPingPreset:
    key: str
    name: str
    packet_size_bytes: int
    interval_ms: int
    timeout_ms: int
    loss_warn_percent: float
    latency_warn_ms: int
    description: str = ""


_PRESETS: tuple[HighPingPreset, ...] = (
    HighPingPreset(
        key="pis_high_ping_acceptance",
        name="PIS 高频 Ping / 验收",
        packet_size_bytes=64,
        interval_ms=10,
        timeout_ms=100,
        loss_warn_percent=0.7,
        latency_warn_ms=100,
        description="适用于 PIS 车地无线高频丢包和时延验收",
    ),
    HighPingPreset(
        key="pis_stability_observation",
        name="PIS 稳定性观察",
        packet_size_bytes=64,
        interval_ms=30,
        timeout_ms=100,
        loss_warn_percent=0.7,
        latency_warn_ms=100,
        description="适用于长时间稳定性观察，输出压力低于 10ms 高频模式",
    ),
    HighPingPreset(
        key="cbtc_dcs_high_ping",
        name="CBTC/DCS 高频 Ping",
        packet_size_bytes=64,
        interval_ms=10,
        timeout_ms=100,
        loss_warn_percent=5.0,
        latency_warn_ms=100,
        description="适用于 DCS 高频连通性观察",
    ),
    HighPingPreset(
        key="cbtc_dcs_attkping_64b",
        name="CBTC/DCS Attkping 等效 64B",
        packet_size_bytes=64,
        interval_ms=30,
        timeout_ms=100,
        loss_warn_percent=5.0,
        latency_warn_ms=100,
    ),
    HighPingPreset(
        key="cbtc_dcs_attkping_256b",
        name="CBTC/DCS Attkping 等效 256B",
        packet_size_bytes=256,
        interval_ms=30,
        timeout_ms=100,
        loss_warn_percent=5.0,
        latency_warn_ms=100,
    ),
    HighPingPreset(
        key="cbtc_dcs_attkping_1256b",
        name="CBTC/DCS Attkping 等效 1256B",
        packet_size_bytes=1256,
        interval_ms=30,
        timeout_ms=100,
        loss_warn_percent=5.0,
        latency_warn_ms=100,
    ),
)


def list_ping_presets() -> tuple[HighPingPreset, ...]:
    return _PRESETS


def get_ping_preset(key: str | None) -> HighPingPreset | None:
    if not key:
        return None
    for preset in _PRESETS:
        if preset.key == key:
            return preset
    return None
