from __future__ import annotations

from pathlib import Path

from netconsole.core.feature_registry import FEATURE_BY_ID
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_management import AcApDTO, AcApPageDTO, AcManagementSummaryDTO
from netconsole.models.api.ac_mesh_link import AcMeshLinkPageDTO, AcMeshLinkSummaryDTO
from netconsole.models.api.job_center import JobCenterSummaryDTO, JobCenterTaskDTO
from netconsole.models.api.mesh_analysis import MeshAnalysisSessionPageDTO, MeshAnalysisSummaryDTO
from netconsole.models.api.online_mr import OnlineMrSessionSummaryDTO
from netconsole.models.api.rail_transit_base_data import RailTransitSummaryDTO
from netconsole.models.api.train_communication import (
    MrCommunicationStatusDTO,
    TrainCommunicationPageDTO,
    TrainCommunicationRowDTO,
)
from netconsole.services.rail_transit.wireless_dashboard_query_service import WirelessDashboardQueryService


class _BaseQuery:
    @staticmethod
    def current_site_id() -> str:
        return "demo"

    @staticmethod
    def get_summary(site_id: str) -> RailTransitSummaryDTO:
        return RailTransitSummaryDTO(site_id=site_id, site_name="测试局点", train_count=1, mr_count=1, issue_count=2, updated_at="2026-07-14T10:00:00")


class _AcQuery:
    @staticmethod
    def get_summary(site_id: str) -> AcManagementSummaryDTO:
        return AcManagementSummaryDTO(site_id=site_id, ap_total=10, online_aps=8, offline_aps=2, unauthenticated_aps=1, optical_anomalies=1, updated_at="2026-07-14T10:01:00")

    @staticmethod
    def list_optical_anomalies(_site_id: str, **_kwargs) -> AcApPageDTO:
        return AcApPageDTO(items=[AcApDTO(id="ap-1", ac_id="ac-1", name="AP-01", optical_status="critical")], total=1)


class _MeshQuery:
    @staticmethod
    def get_summary(site_id: str) -> AcMeshLinkSummaryDTO:
        return AcMeshLinkSummaryDTO(site_id=site_id, stale_mrs=1, data_status="stale", updated_at="2026-07-14T10:02:00")

    @staticmethod
    def list_current_links(_site_id: str, **_kwargs) -> AcMeshLinkPageDTO:
        return AcMeshLinkPageDTO()


class _TrainQuery:
    @staticmethod
    def list_trains(_site_id: str, **_kwargs) -> TrainCommunicationPageDTO:
        mr = MrCommunicationStatusDTO(train_id="12", train_name="12车", mr_id="mr-ct", mr_name="12车-MR-CT", mr_role="CT", communication_status="warning")
        row = TrainCommunicationRowDTO(train_id="12", train_no="12", train_name="12车", communication_status="warning", mrs=[mr], active_sessions=1, warning_count=1, last_updated_at="2026-07-14T10:03:00")
        return TrainCommunicationPageDTO(items=[row], total=1)


class _JobQuery:
    @staticmethod
    def list_tasks(_site_id: str, **_kwargs) -> list[JobCenterTaskDTO]:
        return [JobCenterTaskDTO(id="task-1", type="mr", name="MR 采集", status="FAILED", updated_time="2026-07-14T10:04:00", error_summary="连接失败")]

    @staticmethod
    def get_summary(_site_id: str) -> JobCenterSummaryDTO:
        return JobCenterSummaryDTO(total=1, failed=1)


class _OnlineQuery:
    @staticmethod
    def list_sessions(site_id: str, **_kwargs) -> list[OnlineMrSessionSummaryDTO]:
        return [OnlineMrSessionSummaryDTO(session_id="session-1", site_id=site_id, status="COMPLETED", started_at="2026-07-14T10:05:00")]


class _AnalysisQuery:
    @staticmethod
    def get_summary(site_id: str) -> MeshAnalysisSummaryDTO:
        return MeshAnalysisSummaryDTO(site_id=site_id, session_count=1, warning_session_count=1, latest_analysis_time="2026-07-14T10:06:00")

    @staticmethod
    def list_analysis_sessions(_site_id: str, **_kwargs) -> MeshAnalysisSessionPageDTO:
        return MeshAnalysisSessionPageDTO()


class _AgentService:
    calls = 0

    @classmethod
    def list_agents(cls):
        cls.calls += 1
        return [{"agent_id": "agent-1", "name": "本机 Agent", "base_url": "http://127.0.0.1:18080", "enabled": True, "authentication_type": "none", "has_credential": False, "status": "ONLINE", "last_checked_at": "2026-07-14T10:07:00"}]


def _service(tmp_path: Path) -> WirelessDashboardQueryService:
    return WirelessDashboardQueryService(
        PathResolver(app_root=tmp_path, data_root=tmp_path),
        base_query=_BaseQuery(),
        ac_query=_AcQuery(),
        mesh_query=_MeshQuery(),
        train_query=_TrainQuery(),
        online_mr_query=_OnlineQuery(),
        job_query=_JobQuery(),
        mesh_analysis_query=_AnalysisQuery(),
        agent_service=_AgentService(),
        cache_ttl_seconds=60,
    )


def test_dashboard_aggregates_existing_statuses_and_reuses_site_version_cache(tmp_path: Path) -> None:
    _AgentService.calls = 0
    service = _service(tmp_path)

    first = service.get_dashboard("demo")
    second = service.get_dashboard("demo")

    assert first.summary.ap_total == 10
    assert first.summary.registered_trains == 1
    assert first.summary.active_online_mr_sessions == 1
    assert first.summary.agent_total == 1
    assert first.summary.data_version
    assert first.summary.cached is False
    assert second.summary.cached is True
    assert second.summary.data_version == first.summary.data_version
    assert _AgentService.calls == 1
    assert {item.id for item in first.alerts.items} >= {"ac-offline", "ac-unauthenticated", "optical-ap-1", "mesh-stale", "train-12", "task-task-1", "base-data-quality", "mesh-analysis-warning"}
    assert all(item.severity in {"critical", "warning"} for item in first.alerts.items)
    assert FEATURE_BY_ID["capability.rail_transit.wireless_dashboard"].parent_id == "module.rail_transit"


def test_dashboard_agent_section_never_calls_remote_probe(tmp_path: Path) -> None:
    class _NoRemoteAgent(_AgentService):
        @staticmethod
        def probe_agent(*_args, **_kwargs):
            raise AssertionError("dashboard must not probe Agent")

    service = WirelessDashboardQueryService(
        PathResolver(app_root=tmp_path, data_root=tmp_path),
        base_query=_BaseQuery(), ac_query=_AcQuery(), mesh_query=_MeshQuery(), train_query=_TrainQuery(),
        online_mr_query=_OnlineQuery(), job_query=_JobQuery(), mesh_analysis_query=_AnalysisQuery(), agent_service=_NoRemoteAgent(),
    )

    assert service.get_dashboard("demo").agents.online == 1
