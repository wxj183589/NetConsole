from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.services.vehicle_mr_offline_analysis import VehicleMrOfflineAnalysisService


@dataclass(frozen=True)
class VehicleMrOfflineReport:
    session_dir: Path
    title: str
    sheet_names: list[str]


class VehicleMrOfflineReportService:
    def build(self, session_dir: Path) -> VehicleMrOfflineReport:
        analysis = VehicleMrOfflineAnalysisService().analyze(session_dir)
        return VehicleMrOfflineReport(
            session_dir=analysis.session_dir,
            title="车载MR离线诊断报告",
            sheet_names=[
                "报告总览",
                "会话信息",
                "数据完整性",
                "质量评分",
                "时间轴质量概览",
                "fping业务质量",
                "Mesh主链路区段",
                "Peer质量排名",
                "切换影响分析",
                "丢包关联分析",
                "异常事件清单",
                "空口繁忙度分析",
                "射频统计分析",
                "接口速率分析",
                "链路重建与连接异常",
                "原始证据片段",
                "参数配置",
            ],
        )
