from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.services.online_mr_chart_builder import OnlineMrChartBuilder, ChartData


DATA_SOURCE_TYPE = "VEHICLE_MR_REALTIME_OFFLINE"


@dataclass(frozen=True)
class VehicleMrOfflineAnalysis:
    session_dir: Path
    data_source_type: str
    charts: dict[str, ChartData]


class VehicleMrOfflineAnalysisService:
    def analyze(self, session_dir: Path) -> VehicleMrOfflineAnalysis:
        session_dir = Path(session_dir)
        builder = OnlineMrChartBuilder(session_dir / "parsed" / "online_diagnosis.sqlite")
        return VehicleMrOfflineAnalysis(
            session_dir=session_dir,
            data_source_type=DATA_SOURCE_TYPE,
            charts={
                "active_rssi": builder.build_active_rssi_series(),
                "channel_busy": builder.build_channel_busy_series(),
                "ping_loss": builder.build_ping_loss_series(),
                "ping_latency": builder.build_ping_latency_series(),
                "interface_rate": builder.build_interface_rate_series(),
                "switch_rssi": builder.build_switch_rssi_series(),
                "switch_reason": builder.build_switch_reason_summary(),
            },
        )
