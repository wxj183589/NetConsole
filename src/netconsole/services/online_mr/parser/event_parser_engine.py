from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from netconsole.services.online_mr.event_bus import EVENT_FPING_V5_SAMPLE, EVENT_IPERF3_ERROR, EVENT_IPERF3_SAMPLE, OnlineMrEvent
from netconsole.services.online_mr_parser import (
    parse_ap_radio_statistics_text,
    parse_channel_busy_text,
    parse_interface_rate_text,
    parse_mesh_link_row,
    parse_mesh_link_text,
    summarize_active,
)


class EventParserEngine:
    def __init__(self, maxlen: int = 3000) -> None:
        self.samples: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=maxlen))

    def on_event(self, event: OnlineMrEvent) -> None:
        if event.module == "fping" and event.event_type == EVENT_FPING_V5_SAMPLE:
            self.samples["fping"].append(self.parse_fping_v5(event))
        elif event.module == "iperf" and event.event_type == EVENT_IPERF3_SAMPLE:
            self.samples["iperf"].append(self.parse_iperf3(event))
        elif event.module == "iperf" and event.event_type == EVENT_IPERF3_ERROR:
            self.samples["iperf"].append(self.parse_iperf_error(event))
        elif event.module == "mesh":
            self.samples["mesh"].append(self.parse_mesh(event))
        elif event.module == "busy":
            self.samples["busy"].append(self.parse_busy(event))
        elif event.module == "stats":
            self.samples["stats"].append(self.parse_stats(event))
        elif event.module == "interface_rate":
            self.samples["interface_rate"].append(self.parse_interface_rate(event))

    def parse_mesh(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = {"timestamp": event.timestamp, "raw": event.raw, **event.payload}
        if event.raw:
            records, _status, _error = parse_mesh_link_text(event.raw, event.timestamp)
            active = summarize_active(records)
            if active is not None:
                peer_fields = _extract_mesh_peer_fields(active.raw_line)
                payload.update(
                    {
                        "link_state": active.link_state,
                        "peer_name": active.metrics.get("peer_name") or peer_fields.get("peer_name"),
                        "peer_mac": active.peer_mac_h3c(),
                        "peer_mac_normalized": active.peer_mac_normalized,
                        "bssid": active.metrics.get("bssid") or peer_fields.get("bssid"),
                        "interface": active.metrics.get("interface") or peer_fields.get("interface"),
                        "online_time": active.metrics.get("online_time") or peer_fields.get("online_time"),
                        "mr_rssi": active.metrics.get("local_rssi_db"),
                        "local_rssi": active.metrics.get("local_rssi_db"),
                        "peer_rssi": active.metrics.get("peer_rssi_db"),
                        "retry": active.metrics.get("local_retry"),
                    }
                )
            else:
                payload.update(_extract_mesh_peer_fields(event.raw))
        return payload

    def parse_mesh_line_stream(self, event: OnlineMrEvent) -> dict[str, Any]:
        return self.parse_mesh(event)

    def parse_busy(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = {"timestamp": event.timestamp, "raw": event.raw, **event.payload}
        if event.raw:
            rows = parse_channel_busy_text(event.raw, collected_at=event.timestamp)
            if rows:
                payload.update(_latest_channel_busy_row(rows))
        return payload

    def parse_stats(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = {"timestamp": event.timestamp, "raw": event.raw, **event.payload}
        if event.raw:
            payload.update(parse_ap_radio_statistics_text(event.raw))
        return payload

    def parse_interface_rate(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = {"timestamp": event.timestamp, "raw": event.raw, **event.payload}
        if event.raw:
            payload["rows"] = parse_interface_rate_text(event.raw)
        return payload

    def parse_fping_v5(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = dict(event.payload)
        loss = _float(payload.get("loss_rate_percent"), 0.0)
        avg = _float(payload.get("avg_rtt_ms"), payload.get("rtt_ms"), 0.0)
        payload["link_quality"] = max(0.0, min(100.0, 100.0 - loss))
        payload["latency_score"] = max(0.0, min(100.0, 100.0 - avg))
        payload["timestamp"] = event.timestamp
        return payload

    def parse_iperf3(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = dict(event.payload)
        throughput = _extract_iperf_mbps(payload)
        payload["throughput_mbps"] = throughput
        if payload.get("zero_sample_type") == "isolated_report_gap":
            payload["throughput_score"] = 100.0
        else:
            payload["throughput_score"] = max(0.0, min(100.0, throughput)) if throughput is not None else 0.0
        payload["timestamp"] = event.timestamp
        return payload

    def parse_iperf_error(self, event: OnlineMrEvent) -> dict[str, Any]:
        payload = dict(event.payload)
        payload["timestamp"] = event.timestamp
        payload["throughput_mbps"] = None
        payload["throughput_score"] = 0.0
        payload["iperf_error"] = True
        return payload

    def latest(self, module: str) -> dict[str, Any] | None:
        rows = self.samples.get(module)
        return rows[-1] if rows else None


def _float(*values: object) -> float:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _latest_channel_busy_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        row
        for row in rows
        if any(row.get(key) is not None for key in ("channel_busy_total", "ctl_busy", "tx_busy", "rx_busy"))
    ]
    if not valid:
        return rows[-1] if rows else {}

    def sort_key(row: dict[str, Any]) -> tuple[int, str]:
        sample_time = str(row.get("channel_busy_sample_time") or row.get("sample_time") or "")
        try:
            return (1, sample_time if sample_time else "")
        except (TypeError, ValueError):
            return (0, "")

    return max(valid, key=sort_key)


def _extract_iperf_mbps(payload: dict[str, Any]) -> float | None:
    end = payload.get("end")
    if isinstance(end, dict):
        for key in ("sum_received", "sum_sent", "sum"):
            row = end.get(key)
            if isinstance(row, dict) and row.get("bits_per_second") is not None:
                return float(row["bits_per_second"]) / 1_000_000.0
    if payload.get("bits_per_second") is not None:
        return float(payload["bits_per_second"]) / 1_000_000.0
    if payload.get("throughput_mbps") is not None:
        return float(payload["throughput_mbps"])
    if payload.get("bitrate_mbps") is not None:
        return float(payload["bitrate_mbps"])
    return None


def _extract_mesh_peer_fields(raw_text: str) -> dict[str, Any]:
    for line in raw_text.splitlines():
        parsed = parse_mesh_link_row(line)
        if parsed is None:
            continue
        return {
            "peer_name": parsed.get("peer_name") or "",
            "peer_mac": parsed.get("peer_mac") or "",
            "peer_mac_normalized": parsed.get("peer_mac_normalized") or "",
            "mr_rssi": int(parsed["rssi"]),
            "local_rssi": int(parsed["rssi"]),
            "peer_rssi": None,
            "bssid": parsed.get("bssid") or "",
            "interface": parsed.get("interface") or "",
            "link_state": parsed.get("link_state") or "UNKNOWN",
            "radio_mode": parsed.get("radio_mode") or "",
            "online_time": parsed.get("online_time") or "",
        }
    return {}


def _normalize_mesh_link_state(value: str) -> str:
    lowered = (value or "").casefold()
    if "active" in lowered:
        return "ACTIVE"
    if "standby" in lowered:
        return "STANDBY"
    return "UNKNOWN"
