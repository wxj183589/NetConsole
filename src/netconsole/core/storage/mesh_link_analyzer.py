from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from netconsole.models.mesh_analysis_params import MeshAnalysisParams, normalize_mesh_analysis_params


@dataclass(frozen=True)
class MeshLinkEstablishmentDecision:
    accepted: bool
    signal: float | None
    threshold: int
    reason: str


class MeshLinkAnalyzer:
    """Shared link grouping and establishment rules for MESH queries and exports."""

    def __init__(self, params: MeshAnalysisParams | Mapping[str, object] | str | None = None) -> None:
        self.params = normalize_mesh_analysis_params(params)

    def group_active_points(
        self,
        rows: Sequence[dict[str, object]],
        gap_seconds_by_scope: Mapping[tuple[object, object], float],
        time_window_seconds_by_scope: Mapping[tuple[object, object], float] | None = None,
    ) -> list[list[dict[str, object]]]:
        segments: list[list[dict[str, object]]] = []
        current: list[dict[str, object]] = []
        last_key: tuple[object, object, str] | None = None
        last_time = ""
        for row in rows:
            sample_time = str(row.get("sample_time") or "")
            key = (
                row.get("source_file_id"),
                row.get("radio"),
                self._canonical_mac(row.get("peer_mac_normalized") or row.get("peer_mac_raw") or row.get("peer_mac")),
            )
            scope = (row.get("source_file_id"), row.get("radio"))
            configured_window = max(
                float((time_window_seconds_by_scope or {}).get(scope, self.params.link_time_window / 1000.0)),
                0.001,
            )
            gap_seconds = min(
                float(gap_seconds_by_scope.get(scope, configured_window)),
                configured_window,
            )
            if current and (key != last_key or self._seconds_between(last_time, sample_time) > gap_seconds):
                segments.append(current)
                current = []
            current.append(row)
            last_key = key
            last_time = sample_time
        if current:
            segments.append(current)
        return segments

    def evaluate_establishment(
        self,
        row: Mapping[str, object],
        *,
        first_link: bool,
        previous_signal: float | None = None,
    ) -> MeshLinkEstablishmentDecision:
        threshold = self.params.link_establish_rssi
        signal = self._signal(row)
        if first_link:
            return MeshLinkEstablishmentDecision(True, signal, threshold, "第一个主链路忽略信号阈值")
        if signal is None:
            return MeshLinkEstablishmentDecision(False, None, threshold, "缺少有效 RSSI，无法通过建链信号阈值")
        threshold_accepted = signal >= threshold
        switch_accepted = previous_signal is None or signal >= previous_signal + self.params.link_switch_threshold
        accepted = threshold_accepted and switch_accepted
        operator = ">=" if threshold_accepted else "<"
        switch_reason = ""
        if previous_signal is not None:
            switch_operator = ">=" if switch_accepted else "<"
            switch_target = previous_signal + self.params.link_switch_threshold
            switch_reason = f"；切换信号 {signal:g} {switch_operator} 前链路 {previous_signal:g} + 切换阈值 {self.params.link_switch_threshold} = {switch_target:g}"
        return MeshLinkEstablishmentDecision(
            accepted,
            signal,
            threshold,
            f"实际信号 {signal:g} {operator} 维持阈值 {self.params.link_hold_rssi} + 发现阈值 {self.params.link_establish_threshold} = {threshold}{switch_reason}",
        )

    @staticmethod
    def _signal(row: Mapping[str, object]) -> float | None:
        for key in ("avg_mr_rssi", "local_rssi_db", "peer_rssi_db"):
            try:
                value = float(row.get(key))
            except (TypeError, ValueError):
                continue
            return value
        return None

    @staticmethod
    def _canonical_mac(value: object) -> str:
        return "".join(character for character in str(value or "").lower() if character in "0123456789abcdef")

    @staticmethod
    def _seconds_between(previous: str, current: str) -> float:
        try:
            return (datetime.fromisoformat(current) - datetime.fromisoformat(previous)).total_seconds()
        except (TypeError, ValueError):
            return 0.0
