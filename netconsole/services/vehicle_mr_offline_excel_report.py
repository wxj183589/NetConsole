from __future__ import annotations

from pathlib import Path

from netconsole.services.online_mr_analysis_report_exporter import OnlineMrAnalysisReportExporter


class VehicleMrOfflineExcelReportExporter:
    def export(self, session_dir: Path, output_path: Path) -> Path:
        return OnlineMrAnalysisReportExporter().export(session_dir, output_path)
