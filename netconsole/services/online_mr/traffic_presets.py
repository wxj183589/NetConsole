from __future__ import annotations

from dataclasses import dataclass

from netconsole.services.network_tools.iperf_runner import FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS


ONLINE_MR_IPERF_DURATION_MODE = "follow_collection"


@dataclass(frozen=True)
class TrafficPreset:
    key: str
    name: str
    protocol: str
    test_type: str
    deployment_mode: str
    business_direction: str
    report_threshold_mbps: float
    udp_bitrate_mbps: float | None
    packet_length: int | None
    parallel: int
    reverse: bool
    duration_sec: int
    interval_sec: int
    duration_mode: str = ONLINE_MR_IPERF_DURATION_MODE


DEFAULT_TRAFFIC_PRESET_KEY = "pis_tcp_downlink_single"

_TRAFFIC_PRESETS: tuple[TrafficPreset, ...] = (
    TrafficPreset(
        key="pis_tcp_downlink_single",
        name="PIS TCP 下行单流最大吞吐",
        protocol="TCP",
        test_type="tcp_single_throughput",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=600.0,
        udp_bitrate_mbps=None,
        packet_length=None,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="pis_tcp_downlink_parallel",
        name="PIS TCP 下行多流聚合吞吐",
        protocol="TCP",
        test_type="tcp_parallel_throughput",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=600.0,
        udp_bitrate_mbps=None,
        packet_length=None,
        parallel=4,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="pis_udp_downlink_carrier",
        name="PIS UDP 下行指定码率承载",
        protocol="UDP",
        test_type="udp_carrier",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=600.0,
        udp_bitrate_mbps=600.0,
        packet_length=1400,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="cbtc_dcs_udp_1m_64b",
        name="CBTC/DCS UDP 1.0M 64B 小包基准",
        protocol="UDP",
        test_type="udp_carrier",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=1.0,
        udp_bitrate_mbps=1.0,
        packet_length=64,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="cbtc_dcs_udp_1_3m_64b",
        name="CBTC/DCS UDP 1.3M 64B 背景流",
        protocol="UDP",
        test_type="udp_carrier",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=1.3,
        udp_bitrate_mbps=1.3,
        packet_length=64,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="cbtc_dcs_udp_1m_256b",
        name="CBTC/DCS UDP 1.0M 256B 小包",
        protocol="UDP",
        test_type="udp_carrier",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=1.0,
        udp_bitrate_mbps=1.0,
        packet_length=256,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="cbtc_dcs_udp_1m_1256b",
        name="CBTC/DCS UDP 1.0M 1256B 小包",
        protocol="UDP",
        test_type="udp_carrier",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=1.0,
        udp_bitrate_mbps=1.0,
        packet_length=1256,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
    TrafficPreset(
        key="cbtc_dcs_tcp_observation",
        name="CBTC/DCS TCP 连通吞吐观察",
        protocol="TCP",
        test_type="tcp_single_throughput",
        deployment_mode="ground_server_train_client",
        business_direction="ground_to_train",
        report_threshold_mbps=1.0,
        udp_bitrate_mbps=None,
        packet_length=None,
        parallel=1,
        reverse=True,
        duration_sec=FOLLOW_COLLECTION_PROTECTION_DURATION_SECONDS,
        interval_sec=1,
    ),
)


def list_traffic_presets() -> tuple[TrafficPreset, ...]:
    return _TRAFFIC_PRESETS


def get_traffic_preset(key: str | None) -> TrafficPreset | None:
    normalized = str(key or "").strip()
    for preset in _TRAFFIC_PRESETS:
        if preset.key == normalized:
            return preset
    return None
