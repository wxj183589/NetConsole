from __future__ import annotations

from pydantic import Field

from netconsole.models.api.ac_management import AcApDTO, AcManagementSummaryDTO
from netconsole.models.api.ac_mesh_link import AcMeshLinkRecordDTO, AcMeshLinkSummaryDTO
from netconsole.models.api.agent import AgentDTO
from netconsole.models.api.common import ApiModel
from netconsole.models.api.job_center import JobCenterTaskDTO
from netconsole.models.api.mesh_analysis import MeshAnalysisSessionDTO, MeshAnalysisSummaryDTO
from netconsole.models.api.online_mr import OnlineMrSessionSummaryDTO
from netconsole.models.api.train_communication import TrainCommunicationRowDTO, TrainCommunicationSummaryDTO


class WirelessDashboardAlertDTO(ApiModel):
    id: str
    severity: str
    category: str
    title: str
    message: str
    entity_id: str = ""
    detail_path: str = ""
    updated_at: str = ""


class WirelessDashboardFreshnessItemDTO(ApiModel):
    source: str
    label: str
    status: str = "no_data"
    updated_at: str = ""
    age_seconds: int | None = None
    message: str = ""


class WirelessDashboardSummaryDTO(ApiModel):
    site_id: str
    site_name: str = ""
    line_name: str = ""
    ap_total: int = 0
    online_aps: int = 0
    offline_aps: int = 0
    unauthenticated_aps: int = 0
    optical_anomalies: int = 0
    registered_trains: int = 0
    registered_mrs: int = 0
    online_mrs: int = 0
    offline_mrs: int = 0
    stale_mrs: int = 0
    active_online_mr_sessions: int = 0
    agent_total: int = 0
    online_agents: int = 0
    running_tasks: int = 0
    mesh_analysis_sessions: int = 0
    alert_total: int = 0
    critical_alerts: int = 0
    warning_alerts: int = 0
    updated_at: str = ""
    data_version: str = ""
    cached: bool = False


class WirelessDashboardInfrastructureDTO(ApiModel):
    ac: AcManagementSummaryDTO
    mesh_link: AcMeshLinkSummaryDTO
    optical_anomalies: list[AcApDTO] = Field(default_factory=list)
    current_links: list[AcMeshLinkRecordDTO] = Field(default_factory=list)


class WirelessDashboardTrainsDTO(ApiModel):
    summary: TrainCommunicationSummaryDTO
    items: list[TrainCommunicationRowDTO] = Field(default_factory=list)
    total: int = 0


class WirelessDashboardAlertsDTO(ApiModel):
    items: list[WirelessDashboardAlertDTO] = Field(default_factory=list)
    total: int = 0
    critical: int = 0
    warning: int = 0


class WirelessDashboardFreshnessDTO(ApiModel):
    items: list[WirelessDashboardFreshnessItemDTO] = Field(default_factory=list)


class WirelessDashboardRecentOperationsDTO(ApiModel):
    tasks: list[JobCenterTaskDTO] = Field(default_factory=list)
    sessions: list[OnlineMrSessionSummaryDTO] = Field(default_factory=list)


class WirelessDashboardAnalysisDTO(ApiModel):
    summary: MeshAnalysisSummaryDTO
    sessions: list[MeshAnalysisSessionDTO] = Field(default_factory=list)


class WirelessDashboardAgentsDTO(ApiModel):
    items: list[AgentDTO] = Field(default_factory=list)
    total: int = 0
    online: int = 0
    offline: int = 0
    unknown: int = 0


class WirelessDashboardDTO(ApiModel):
    summary: WirelessDashboardSummaryDTO
    infrastructure: WirelessDashboardInfrastructureDTO
    trains: WirelessDashboardTrainsDTO
    alerts: WirelessDashboardAlertsDTO
    freshness: WirelessDashboardFreshnessDTO
    recent_operations: WirelessDashboardRecentOperationsDTO
    analysis: WirelessDashboardAnalysisDTO
    agents: WirelessDashboardAgentsDTO


__all__ = [name for name in globals() if name.startswith("WirelessDashboard")]
