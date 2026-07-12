from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from netconsole.services.online_mr_chart_builder import ChartData, ChartEvent, OnlineMrChartBuilder


DATA_SOURCE_TYPE = "VEHICLE_MR_REALTIME_OFFLINE"


@dataclass(frozen=True)
class VehicleMrOfflineAnalysis:
    session_dir: Path
    data_source_type: str
    charts: dict[str, ChartData]
    summary: dict[str, object] | None = None
    switch_events: list[ChartEvent] | None = None


def build_vehicle_mr_analysis_chart_payload(session_dir: Path) -> dict[str, object]:
    session_dir = Path(session_dir)
    builder = OnlineMrChartBuilder(session_dir / "parsed" / "online_diagnosis.sqlite")
    summary = builder.build_session_summary()
    switch_events = builder.build_switch_events()
    charts = {
        "rssi": builder.build_active_rssi_series(),
        "ping_loss": builder.build_ping_loss_series(),
        "ping": builder.build_ping_latency_series(),
        "interface": builder.build_interface_rate_series(),
        "traffic": builder.build_traffic_rate_series(),
        "busy": builder.build_channel_busy_series(),
        "switch_rssi": builder.build_switch_rssi_series(),
        "switch_log_rssi": builder.build_switch_log_rssi_series(),
    }
    overlay_keys = {"rssi", "ping_loss", "ping", "traffic"}
    charts = {key: replace(chart, events=switch_events if key in overlay_keys else chart.events) for key, chart in charts.items()}
    return {"session_dir": session_dir, "summary": summary, "switch_events": switch_events, "charts": charts}


class VehicleMrOfflineAnalysisService:
    def analyze(self, session_dir: Path) -> VehicleMrOfflineAnalysis:
        session_dir = Path(session_dir)
        payload = build_vehicle_mr_analysis_chart_payload(session_dir)
        builder = OnlineMrChartBuilder(session_dir / "parsed" / "online_diagnosis.sqlite")
        return VehicleMrOfflineAnalysis(
            session_dir=session_dir,
            data_source_type=DATA_SOURCE_TYPE,
            summary=payload["summary"],
            switch_events=payload["switch_events"],
            charts={
                "active_rssi": payload["charts"]["rssi"],
                "channel_busy": payload["charts"]["busy"],
                "ping_loss": payload["charts"]["ping_loss"],
                "ping_latency": payload["charts"]["ping"],
                "interface_rate": payload["charts"]["interface"],
                "switch_rssi": payload["charts"]["switch_rssi"],
                "switch_log_rssi": payload["charts"]["switch_log_rssi"],
                "switch_reason": builder.build_switch_reason_summary(),
            },
        )
