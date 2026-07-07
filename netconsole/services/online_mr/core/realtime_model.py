from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from netconsole.services.online_mr.core.event_model import OnlineMrEvent


@dataclass(frozen=True)
class PingConfig:
    source_device_id: int
    target_ip: str


@dataclass
class RealtimeMRState:
    device_id: int
    device_name: str
    status: str
    peer_name: str | None = None
    peer_mac: str | None = None
    peer_station: str | None = None
    peer_site: str | None = None
    peer_section: str | None = None
    belong_type: str | None = None
    belonging_source: str | None = None
    peer_serial_number: str | None = None
    mr_rssi: int | None = None
    link_state: str | None = None
    ctl_busy: float | None = None
    tx_busy: float | None = None
    rx_busy: float | None = None
    loss: float | None = None
    rtt: float | None = None
    retry_count: int | None = None
    retry: int | None = None
    iperf_mbps: float | None = None
    retrans: int | None = None
    sample_count: int = 0
    fail_count: int = 0
    reconnect_count: int = 0
    last_time: datetime | None = None


class RealtimeAggregator:
    def __init__(
        self,
        *,
        device_id: int,
        device_name: str,
        status: str,
        sample_count: int = 0,
        fail_count: int = 0,
        reconnect_count: int = 0,
        resolve_peer: Callable[[str], dict[str, object] | None] | None = None,
    ) -> None:
        self.state = RealtimeMRState(
            device_id=device_id,
            device_name=device_name,
            status=status,
            sample_count=sample_count,
            fail_count=fail_count,
            reconnect_count=reconnect_count,
        )
        self.resolve_peer = resolve_peer

    def update(self, event: OnlineMrEvent) -> RealtimeMRState:
        _apply_event(self.state, event, self.resolve_peer)
        return self.state


def build_realtime_state(
    *,
    device_id: int,
    device_name: str,
    status: str,
    events: list[OnlineMrEvent],
    sample_count: int = 0,
    fail_count: int = 0,
    reconnect_count: int = 0,
    resolve_peer: Callable[[str], dict[str, object] | None] | None = None,
) -> RealtimeMRState:
    aggregator = RealtimeAggregator(
        device_id=device_id,
        device_name=device_name,
        status=status,
        sample_count=sample_count,
        fail_count=fail_count,
        reconnect_count=reconnect_count,
        resolve_peer=resolve_peer,
    )
    for event in events:
        aggregator.update(event)
    return aggregator.state


def _apply_event(state: RealtimeMRState, event: OnlineMrEvent, resolve_peer: Callable[[str], dict[str, object] | None] | None) -> None:
    if state.last_time is None or event.timestamp > state.last_time:
        state.last_time = event.timestamp
    payload = event.payload
    if event.module == "mesh":
        link_state = _text(payload.get("link_state")) or state.link_state
        state.link_state = link_state
        if (link_state or "").upper() != "ACTIVE":
            return
        peer_mac = _text(payload.get("peer_mac") or payload.get("active_peer") or payload.get("peer_mac_normalized"))
        peer_name = _text(payload.get("peer_name") or payload.get("peer_ap_name"))
        state.peer_mac = peer_mac or state.peer_mac
        state.peer_name = peer_name or state.peer_name
        peer_site = _text(payload.get("peer_station") or payload.get("peer_site") or payload.get("site"))
        state.peer_station = peer_site or state.peer_station
        state.peer_site = peer_site or state.peer_site
        peer_section = _text(payload.get("peer_section") or payload.get("belong_section"))
        state.peer_section = peer_section or state.peer_section
        state.belong_type = _text(payload.get("belong_type")) or state.belong_type
        state.belonging_source = _text(payload.get("belonging_source")) or state.belonging_source
        mr_rssi = _int_or_none(payload.get("mr_rssi"), payload.get("local_rssi"), payload.get("local_rssi_db"), payload.get("rssi"))
        state.mr_rssi = mr_rssi if mr_rssi is not None else state.mr_rssi
        retry = _int_or_none(payload.get("retry_count"), payload.get("retry"), payload.get("local_retry"))
        state.retry_count = retry if retry is not None else state.retry_count
        state.retry = retry if retry is not None else state.retry
        if resolve_peer and (not state.peer_name or not state.peer_station or not state.peer_serial_number):
            resolved: dict[str, object] = {}
            for lookup_key in (state.peer_name, state.peer_mac, payload.get("peer_mac_normalized"), payload.get("bssid")):
                if not lookup_key:
                    continue
                candidate = resolve_peer(str(lookup_key)) or {}
                if _is_resolved_peer(candidate):
                    resolved = candidate
                    break
            state.peer_name = _text(resolved.get("peer_ap_name") or resolved.get("ap_name")) or state.peer_name
            resolved_site = _text(resolved.get("peer_site") or resolved.get("site"))
            state.peer_station = resolved_site or state.peer_station
            state.peer_site = resolved_site or state.peer_site
            state.peer_section = _text(resolved.get("peer_section") or resolved.get("belong_section")) or state.peer_section
            state.belong_type = _text(resolved.get("belong_type")) or state.belong_type
            state.belonging_source = _text(resolved.get("belonging_source")) or state.belonging_source
            state.peer_serial_number = _text(resolved.get("peer_serial_number") or resolved.get("serial_number")) or state.peer_serial_number
    elif event.module == "busy":
        state.ctl_busy = _float_or_none(payload.get("ctl_busy")) if payload.get("ctl_busy") is not None else state.ctl_busy
        state.tx_busy = _float_or_none(payload.get("tx_busy")) if payload.get("tx_busy") is not None else state.tx_busy
        state.rx_busy = _float_or_none(payload.get("rx_busy")) if payload.get("rx_busy") is not None else state.rx_busy
    elif event.module == "stats":
        retry = _int_or_none(payload.get("retry_count"), payload.get("retry"), payload.get("local_retry"))
        state.retry_count = retry if retry is not None else state.retry_count
        state.retry = retry if retry is not None else state.retry
    elif event.module == "fping":
        state.loss = _float_or_none(payload.get("loss_rate_percent"), payload.get("loss_percent")) if _has_any(payload, "loss_rate_percent", "loss_percent") else state.loss
        state.rtt = _float_or_none(payload.get("avg_rtt_ms"), payload.get("rtt_ms"), payload.get("last_rtt_ms")) if _has_any(payload, "avg_rtt_ms", "rtt_ms", "last_rtt_ms") else state.rtt
    elif event.module == "iperf":
        state.iperf_mbps = _float_or_none(payload.get("bitrate_mbps"), payload.get("throughput_mbps")) if _has_any(payload, "bitrate_mbps", "throughput_mbps") else state.iperf_mbps
        state.retrans = _int_or_none(payload.get("retransmits"), payload.get("retrans")) if _has_any(payload, "retransmits", "retrans") else state.retrans


def _has_any(payload: dict[str, object], *keys: str) -> bool:
    return any(payload.get(key) is not None for key in keys)


def _text(value: object) -> str:
    return str(value or "").strip()


def _is_resolved_peer(value: dict[str, object]) -> bool:
    if not value:
        return False
    if _text(value.get("match_rule")).lower() == "unresolved":
        return False
    return any(_text(value.get(key)) for key in ("peer_ap_name", "peer_site", "peer_section", "site", "serial_number", "peer_serial_number", "radio_mac", "peer_radio_mac"))


def _int_or_none(*values: object) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _float_or_none(*values: object) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
