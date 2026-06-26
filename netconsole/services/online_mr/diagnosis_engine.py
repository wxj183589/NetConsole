from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from netconsole.services.online_mr.core.realtime_model import RealtimeMRState
from netconsole.services.online_mr.event_bus import EVENT_FPING_V5_SAMPLE, EVENT_IPERF3_SAMPLE, OnlineMrEvent


@dataclass(frozen=True)
class OnlineMrIssue:
    timestamp: datetime
    issue_type: str
    message: str
    payload: dict[str, object]


class OnlineMrDiagnosisEngine:
    def __init__(self, ping_loss_threshold_percent: float = 1.0, weak_signal_threshold: int = 20) -> None:
        self.ping_loss_threshold_percent = ping_loss_threshold_percent
        self.weak_signal_threshold = weak_signal_threshold
        self.issues: list[OnlineMrIssue] = []
        self.module_scores: dict[str, float] = {}
        self.score: float = 0.0

    def on_event(self, event: OnlineMrEvent) -> None:
        if event.event_type == EVENT_FPING_V5_SAMPLE:
            loss = float(event.payload.get("loss_rate_percent") or 0.0)
            self.module_scores["fping"] = max(0.0, min(100.0, 100.0 - loss))
            if loss > self.ping_loss_threshold_percent:
                self._issue(event, "PING_LOSS", f"Ping loss {loss:.2f}%")
        elif event.event_type == EVENT_IPERF3_SAMPLE or event.module == "iperf":
            self.module_scores["iperf"] = _iperf_score(event.payload)
        if event.module == "mesh":
            rssi = event.payload.get("mr_rssi") or event.payload.get("local_rssi")
            if rssi is not None and float(rssi) < self.weak_signal_threshold:
                self._issue(event, "WEAK_SIGNAL", f"MR RSSI {rssi}")
            self.module_scores["mesh"] = _bounded(float(rssi or 100))
        elif event.module == "busy":
            busy = float(event.payload.get("tx_busy") or event.payload.get("rx_busy") or 0)
            self.module_scores["busy"] = _bounded(100.0 - busy)
        elif event.module == "stats":
            self.module_scores["stats"] = _bounded(float(event.payload.get("score") or 100))
        self.score = self.current_score()

    def on_state(self, state: RealtimeMRState) -> None:
        if state.mr_rssi is not None:
            self.module_scores["mesh"] = _bounded(float(state.mr_rssi))
            self.module_scores["rssi"] = self.module_scores["mesh"]
        if state.tx_busy is not None or state.rx_busy is not None or state.ctl_busy is not None:
            busy = max(
                value
                for value in (state.ctl_busy, state.tx_busy, state.rx_busy)
                if value is not None
            )
            self.module_scores["busy"] = _bounded(100.0 - float(busy))
        if state.loss is not None or state.rtt is not None:
            loss = float(state.loss or 0.0)
            rtt = float(state.rtt or 0.0)
            self.module_scores["fping"] = _bounded((100.0 - loss) * 0.7 + (100.0 - min(rtt, 100.0)) * 0.3)
        if state.retry is not None:
            self.module_scores["stats"] = _bounded(100.0 - min(float(state.retry), 100.0))
        self.score = self.current_score()

    def _issue(self, event: OnlineMrEvent, issue_type: str, message: str) -> None:
        self.issues.append(OnlineMrIssue(event.timestamp, issue_type, message, dict(event.payload)))

    def current_score(self) -> float:
        weights = {"mesh": 0.3, "busy": 0.2, "stats": 0.2, "fping": 0.2, "iperf": 0.1}
        return sum(self.module_scores.get(module, 100.0) * weight for module, weight in weights.items())


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _iperf_score(payload: dict[str, object]) -> float:
    value = payload.get("throughput_score") or payload.get("throughput_mbps")
    if value is None:
        end = payload.get("end")
        if isinstance(end, dict):
            row = end.get("sum_received") or end.get("sum_sent") or end.get("sum")
            if isinstance(row, dict) and row.get("bits_per_second") is not None:
                value = float(row["bits_per_second"]) / 1_000_000.0
    try:
        return _bounded(float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0
