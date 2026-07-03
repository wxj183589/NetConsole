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
            title="车载MR收集离线分析报告",
            sheet_names=[
                "综合结论",
                "会话信息",
                "质量总览",
                "时间轴质量分析",
                "fping业务质量",
                "Mesh主链路质量",
                "Peer稳定性分析",
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
