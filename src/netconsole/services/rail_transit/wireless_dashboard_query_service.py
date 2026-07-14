from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.api.agent import AgentDTO
from netconsole.models.api.train_communication import TrainCommunicationRowDTO, TrainCommunicationSummaryDTO
from netconsole.models.api.wireless_dashboard import (
    WirelessDashboardAgentsDTO,
    WirelessDashboardAlertsDTO,
    WirelessDashboardAlertDTO,
    WirelessDashboardAnalysisDTO,
    WirelessDashboardDTO,
    WirelessDashboardFreshnessDTO,
    WirelessDashboardFreshnessItemDTO,
    WirelessDashboardInfrastructureDTO,
    WirelessDashboardRecentOperationsDTO,
    WirelessDashboardSummaryDTO,
    WirelessDashboardTrainsDTO,
)
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.agent.controller import AgentControllerService
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService
from netconsole.services.rail_transit.train_communication_query_service import TrainCommunicationQueryService


@dataclass(frozen=True)
class _CacheEntry:
    created_at: float
    value: WirelessDashboardDTO


class WirelessDashboardQueryService:
    """聚合既有只读查询结果，不连接设备、不创建任务、不写业务数据。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        base_query: RailTransitBaseDataQueryService | None = None,
        ac_query: AcManagementQueryService | None = None,
        mesh_query: AcMeshLinkQueryService | None = None,
        train_query: TrainCommunicationQueryService | None = None,
        online_mr_query: OnlineMrQueryService | None = None,
        job_query: JobCenterQueryService | None = None,
        mesh_analysis_query: MeshAnalysisQueryService | None = None,
        agent_service: AgentControllerService | None = None,
        cache_ttl_seconds: float = 2.0,
    ) -> None:
        self.paths = paths
        self.ac_query = ac_query or AcManagementQueryService(paths)
        self.mesh_query = mesh_query or AcMeshLinkQueryService(paths)
        self.online_mr_query = online_mr_query or OnlineMrQueryService(paths)
        self.job_query = job_query or JobCenterQueryService(paths)
        self.base_query = base_query or RailTransitBaseDataQueryService(
            paths,
            ac_query=self.ac_query,
            mesh_query=self.mesh_query,
            online_mr_query=self.online_mr_query,
        )
        self.train_query = train_query or TrainCommunicationQueryService(
            paths,
            base_query=self.base_query,
            mesh_query=self.mesh_query,
            online_mr_query=self.online_mr_query,
            job_query=self.job_query,
        )
        self.mesh_analysis_query = mesh_analysis_query or MeshAnalysisQueryService(
            paths,
            base_query=self.base_query,
            online_mr_query=self.online_mr_query,
        )
        self.agent_service = agent_service
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._latest_key: dict[str, tuple[str, str]] = {}
        self._base_summaries: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()

    def current_site_id(self) -> str:
        return self.base_query.current_site_id()

    def get_dashboard(self, site_id: str) -> WirelessDashboardDTO:
        cached = self._cached(site_id)
        if cached is not None:
            return cached.model_copy(update={"summary": cached.summary.model_copy(update={"cached": True})})
        with self._build_lock:
            cached = self._cached(site_id)
            if cached is not None:
                return cached.model_copy(update={"summary": cached.summary.model_copy(update={"cached": True})})
            return self._load_dashboard(site_id)

    def _load_dashboard(self, site_id: str) -> WirelessDashboardDTO:
        base = self.base_query.get_summary(site_id)
        ac = self.ac_query.get_summary(site_id)
        mesh = self.mesh_query.get_summary(site_id)
        optical = self.ac_query.list_optical_anomalies(site_id, page=1, page_size=20)
        links = self.mesh_query.list_current_links(site_id, page=1, page_size=20)
        trains = self.train_query.list_trains(site_id, page=1, page_size=200)
        train_summary = self._train_summary(site_id, trains.items)
        tasks = self.job_query.list_tasks(site_id, limit=20)
        task_summary = self.job_query.get_summary(site_id)
        sessions = self.online_mr_query.list_sessions(site_id, limit=20)
        analysis_summary = self.mesh_analysis_query.get_summary(site_id)
        analysis_sessions = self.mesh_analysis_query.list_analysis_sessions(site_id, page=1, page_size=8)
        agents = self._agents()

        infrastructure = WirelessDashboardInfrastructureDTO(
            ac=ac,
            mesh_link=mesh,
            optical_anomalies=optical.items,
            current_links=links.items,
        )
        train_section = WirelessDashboardTrainsDTO(summary=train_summary, items=trains.items, total=trains.total)
        recent = WirelessDashboardRecentOperationsDTO(tasks=tasks, sessions=sessions)
        analysis = WirelessDashboardAnalysisDTO(summary=analysis_summary, sessions=analysis_sessions.items)
        agent_section = self._agent_section(agents)
        alerts = self._alerts(base, infrastructure, train_section, recent, analysis, agent_section)
        freshness = self._freshness(base, ac, mesh, train_summary, tasks, sessions, analysis_summary, agents)
        data_version = self._data_version(base, ac, mesh, train_summary, tasks, sessions, analysis_summary, agents)
        updated_at = max((item.updated_at for item in freshness.items if item.updated_at), default="")
        summary = WirelessDashboardSummaryDTO(
            site_id=site_id,
            site_name=base.site_name,
            line_name=base.line_name,
            ap_total=ac.ap_total,
            online_aps=ac.online_aps,
            offline_aps=ac.offline_aps,
            unauthenticated_aps=ac.unauthenticated_aps,
            optical_anomalies=ac.optical_anomalies,
            registered_trains=train_summary.registered_trains,
            registered_mrs=train_summary.registered_mrs,
            online_mrs=mesh.online_mrs,
            offline_mrs=mesh.offline_mrs,
            stale_mrs=mesh.stale_mrs,
            active_online_mr_sessions=train_summary.active_online_mr_sessions,
            agent_total=agent_section.total,
            online_agents=agent_section.online,
            running_tasks=task_summary.active,
            mesh_analysis_sessions=analysis_summary.session_count,
            alert_total=alerts.total,
            critical_alerts=alerts.critical,
            warning_alerts=alerts.warning,
            updated_at=updated_at,
            data_version=data_version,
        )
        result = WirelessDashboardDTO(
            summary=summary,
            infrastructure=infrastructure,
            trains=train_section,
            alerts=alerts,
            freshness=freshness,
            recent_operations=recent,
            analysis=analysis,
            agents=agent_section,
        )
        key = (site_id, data_version)
        with self._lock:
            self._cache = {key: _CacheEntry(time.monotonic(), result)}
            self._latest_key[site_id] = key
            self._base_summaries[site_id] = base
        return result

    def get_summary_section(self, site_id: str) -> WirelessDashboardSummaryDTO:
        return self._current(site_id).summary.model_copy(update={"cached": True})

    def get_infrastructure_section(self, site_id: str) -> WirelessDashboardInfrastructureDTO:
        ac = self.ac_query.get_summary(site_id)
        mesh = self.mesh_query.get_summary(site_id)
        section = WirelessDashboardInfrastructureDTO(
            ac=ac,
            mesh_link=mesh,
            optical_anomalies=self.ac_query.list_optical_anomalies(site_id, page=1, page_size=20).items,
            current_links=self.mesh_query.list_current_links(site_id, page=1, page_size=20).items,
        )
        self._update_section(site_id, "infrastructure", section)
        return section

    def get_trains_section(self, site_id: str) -> WirelessDashboardTrainsDTO:
        page = self.train_query.list_trains(site_id, page=1, page_size=200)
        section = WirelessDashboardTrainsDTO(
            summary=self._train_summary(site_id, page.items),
            items=page.items,
            total=page.total,
        )
        self._update_section(site_id, "trains", section)
        return section

    def get_recent_operations_section(self, site_id: str) -> WirelessDashboardRecentOperationsDTO:
        section = WirelessDashboardRecentOperationsDTO(
            tasks=self.job_query.list_tasks(site_id, limit=20),
            sessions=self.online_mr_query.list_sessions(site_id, limit=20),
        )
        self._update_section(site_id, "recent_operations", section)
        return section

    def get_analysis_section(self, site_id: str) -> WirelessDashboardAnalysisDTO:
        summary = self.mesh_analysis_query.get_summary(site_id)
        section = WirelessDashboardAnalysisDTO(
            summary=summary,
            sessions=self.mesh_analysis_query.list_analysis_sessions(site_id, page=1, page_size=8).items,
        )
        self._update_section(site_id, "analysis", section)
        return section

    def get_agents_section(self, site_id: str) -> WirelessDashboardAgentsDTO:
        section = self._agent_section(self._agents())
        self._update_section(site_id, "agents", section)
        return section

    def get_alerts_section(self, site_id: str) -> WirelessDashboardAlertsDTO:
        dashboard = self._current(site_id)
        base = self._base_summaries[site_id]
        section = self._alerts(
            base,
            dashboard.infrastructure,
            dashboard.trains,
            dashboard.recent_operations,
            dashboard.analysis,
            dashboard.agents,
        )
        self._update_section(site_id, "alerts", section)
        return section

    def get_freshness_section(self, site_id: str) -> WirelessDashboardFreshnessDTO:
        return self._current(site_id).freshness

    def _current(self, site_id: str) -> WirelessDashboardDTO:
        with self._lock:
            key = self._latest_key.get(site_id)
            entry = self._cache.get(key) if key else None
        return entry.value if entry is not None else self.get_dashboard(site_id)

    def _update_section(self, site_id: str, name: str, value: Any) -> None:
        dashboard = self._current(site_id)
        with self._lock:
            setattr(dashboard, name, value)
            self._refresh_derived(dashboard)
            old_key = self._latest_key[site_id]
            entry = self._cache.pop(old_key)
            new_key = (site_id, dashboard.summary.data_version)
            self._cache[new_key] = _CacheEntry(entry.created_at, dashboard)
            self._latest_key[site_id] = new_key

    def _refresh_derived(self, dashboard: WirelessDashboardDTO) -> None:
        summary = dashboard.summary
        ac = dashboard.infrastructure.ac
        mesh = dashboard.infrastructure.mesh_link
        trains = dashboard.trains.summary
        analysis = dashboard.analysis.summary
        agents = dashboard.agents
        active_states = {"PENDING", "STARTING", "RUNNING", "STOPPING"}
        summary.ap_total = ac.ap_total
        summary.online_aps = ac.online_aps
        summary.offline_aps = ac.offline_aps
        summary.unauthenticated_aps = ac.unauthenticated_aps
        summary.optical_anomalies = ac.optical_anomalies
        summary.registered_trains = trains.registered_trains
        summary.registered_mrs = trains.registered_mrs
        summary.online_mrs = mesh.online_mrs
        summary.offline_mrs = mesh.offline_mrs
        summary.stale_mrs = mesh.stale_mrs
        summary.active_online_mr_sessions = trains.active_online_mr_sessions
        summary.agent_total = agents.total
        summary.online_agents = agents.online
        summary.running_tasks = sum(task.status.upper() in active_states for task in dashboard.recent_operations.tasks)
        summary.mesh_analysis_sessions = analysis.session_count
        summary.alert_total = dashboard.alerts.total
        summary.critical_alerts = dashboard.alerts.critical
        summary.warning_alerts = dashboard.alerts.warning
        self._update_freshness(dashboard)
        summary.updated_at = max((item.updated_at for item in dashboard.freshness.items if item.updated_at), default="")
        summary.data_version = self._dashboard_version(dashboard)
        summary.cached = True

    @staticmethod
    def _update_freshness(dashboard: WirelessDashboardDTO) -> None:
        rows = {item.source: item for item in dashboard.freshness.items}
        ac = dashboard.infrastructure.ac
        mesh = dashboard.infrastructure.mesh_link
        trains = dashboard.trains.summary
        analysis = dashboard.analysis.summary
        tasks = dashboard.recent_operations.tasks
        sessions = dashboard.recent_operations.sessions
        agents = dashboard.agents.items
        rows["ac_management"].status = "available" if ac.updated_at else "no_data"
        rows["ac_management"].updated_at = ac.updated_at
        rows["ac_mesh_link"].status = mesh.data_status
        rows["ac_mesh_link"].updated_at = mesh.updated_at
        rows["ac_mesh_link"].age_seconds = mesh.age_seconds
        rows["train_communication"].status = "available" if trains.latest_updated_at else "no_data"
        rows["train_communication"].updated_at = trains.latest_updated_at or ""
        rows["online_mr"].updated_at = max(((item.stopped_at or item.started_at or item.created_at or "") for item in sessions), default="")
        rows["online_mr"].status = "available" if rows["online_mr"].updated_at else "no_data"
        rows["job_center"].updated_at = max((item.updated_time for item in tasks), default="")
        rows["job_center"].status = "available" if rows["job_center"].updated_at else "no_data"
        rows["mesh_analysis"].updated_at = analysis.latest_analysis_time or ""
        rows["mesh_analysis"].status = "available" if rows["mesh_analysis"].updated_at else "no_data"
        rows["agents"].updated_at = max((item.last_checked_at for item in agents), default="")
        rows["agents"].status = "available" if agents else "no_data"

    @staticmethod
    def _dashboard_version(dashboard: WirelessDashboardDTO) -> str:
        payload = {
            "ac": [dashboard.infrastructure.ac.updated_at, dashboard.infrastructure.ac.ap_total],
            "mesh": [dashboard.infrastructure.mesh_link.updated_at, dashboard.infrastructure.mesh_link.link_total],
            "trains": [dashboard.trains.summary.latest_updated_at, dashboard.trains.total],
            "tasks": [[item.id, item.status, item.updated_time] for item in dashboard.recent_operations.tasks],
            "sessions": [[item.session_id, item.status] for item in dashboard.recent_operations.sessions],
            "analysis": [dashboard.analysis.summary.latest_analysis_time, dashboard.analysis.summary.session_count],
            "agents": [[item.agent_id, WirelessDashboardQueryService._text(item.status), item.last_checked_at] for item in dashboard.agents.items],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def _cached(self, site_id: str) -> WirelessDashboardDTO | None:
        with self._lock:
            key = self._latest_key.get(site_id)
            entry = self._cache.get(key) if key else None
        if entry is None or time.monotonic() - entry.created_at > self.cache_ttl_seconds:
            return None
        return entry.value

    def _agents(self) -> list[AgentDTO]:
        if self.agent_service is None:
            return []
        return [AgentDTO.model_validate(item) for item in self.agent_service.list_agents()]

    @staticmethod
    def _train_summary(site_id: str, rows: list[TrainCommunicationRowDTO]) -> TrainCommunicationSummaryDTO:
        counts = {
            status: sum(row.communication_status == status for row in rows)
            for status in ("normal", "warning", "critical", "stale", "unknown")
        }
        return TrainCommunicationSummaryDTO(
            site_id=site_id,
            registered_trains=len(rows),
            registered_mrs=sum(len(row.mrs) for row in rows),
            normal_trains=counts["normal"],
            warning_trains=counts["warning"],
            critical_trains=counts["critical"],
            stale_trains=counts["stale"],
            unknown_trains=counts["unknown"],
            current_mesh_links=sum(row.current_mesh_links for row in rows),
            active_online_mr_sessions=sum(row.active_sessions for row in rows),
            agent_imported_sessions=sum(
                str(mr.executor or "").upper() == "AGENT" and bool(mr.session_id)
                for row in rows
                for mr in row.mrs
            ),
            latest_updated_at=max((row.last_updated_at or "" for row in rows), default="") or None,
        )

    @staticmethod
    def _agent_section(items: list[AgentDTO]) -> WirelessDashboardAgentsDTO:
        statuses = [WirelessDashboardQueryService._text(item.status).casefold() for item in items]
        return WirelessDashboardAgentsDTO(
            items=items,
            total=len(items),
            online=sum(value == "online" for value in statuses),
            offline=sum(value == "offline" for value in statuses),
            unknown=sum(value not in {"online", "offline"} for value in statuses),
        )

    @classmethod
    def _alerts(cls, base, infrastructure, trains, recent, analysis, agents) -> WirelessDashboardAlertsDTO:
        items: list[WirelessDashboardAlertDTO] = []

        def add(alert_id: str, severity: str, category: str, title: str, message: str, path: str, *, entity_id: str = "", updated_at: str = "") -> None:
            items.append(WirelessDashboardAlertDTO(id=alert_id, severity=severity, category=category, title=title, message=message, entity_id=entity_id, detail_path=path, updated_at=updated_at))

        ac = infrastructure.ac
        mesh = infrastructure.mesh_link
        if ac.offline_aps:
            add("ac-offline", "warning", "infrastructure", "FIT-AP 离线", f"当前已有状态中存在 {ac.offline_aps} 台离线 FIT-AP。", "/ac-management")
        if ac.unauthenticated_aps:
            add("ac-unauthenticated", "warning", "infrastructure", "FIT-AP 未认证", f"当前已有状态中存在 {ac.unauthenticated_aps} 台未认证 FIT-AP。", "/ac-management")
        for ap in infrastructure.optical_anomalies:
            severity = "critical" if ap.optical_status == "critical" else "warning"
            add(f"optical-{ap.id}", severity, "optical", f"{ap.name} 光衰异常", f"光衰状态：{ap.optical_status}；接入端口：{ap.switch_interface or '无数据'}。", "/ac-management", entity_id=ap.id, updated_at=ap.updated_at)
        if mesh.stale_mrs:
            add("mesh-stale", "warning", "mesh_link", "Mesh-Link 快照过期", f"已有状态中 {mesh.stale_mrs} 台 MR 数据过期。", "/ac-management/mesh-links", updated_at=mesh.updated_at)
        if mesh.offline_mrs:
            add("mesh-offline", "warning", "mesh_link", "车载 MR 离线", f"已有状态中 {mesh.offline_mrs} 台 MR 离线。", "/ac-management/mesh-links", updated_at=mesh.updated_at)
        for train in trains.items:
            if train.communication_status in {"critical", "warning", "stale"}:
                severity = "critical" if train.communication_status == "critical" else "warning"
                add(f"train-{train.train_id}", severity, "train", f"{train.train_name} 通信状态异常", f"综合状态：{train.communication_status}；已有告警 {train.warning_count} 条。", f"/rail-transit/train-communication?train={train.train_id}", entity_id=train.train_id, updated_at=train.last_updated_at or "")
        for task in recent.tasks:
            if task.status.upper() == "FAILED" or task.has_warning:
                add(f"task-{task.id}", "critical" if task.status.upper() == "FAILED" else "warning", "task", f"任务：{task.name}", task.error_summary or task.message or task.status, f"/tasks?task={task.id}", entity_id=task.id, updated_at=task.updated_time)
        if base.issue_count:
            add("base-data-quality", "warning", "base_data", "基础资料存在待治理项", f"现有校验结果共 {base.issue_count} 条。", "/rail-transit/base-data", updated_at=base.updated_at)
        if analysis.summary.warning_session_count:
            add("mesh-analysis-warning", "warning", "analysis", "Mesh 分析会话存在告警", f"现有分析结果中 {analysis.summary.warning_session_count} 个会话带告警。", "/rail-transit/mesh-analysis", updated_at=analysis.summary.latest_analysis_time or "")
        for agent in agents.items:
            status = cls._text(agent.status).casefold()
            if agent.enabled and status in {"offline", "error"}:
                add(f"agent-{agent.agent_id}", "warning", "agent", f"Agent：{agent.name}", agent.last_error_message or f"当前状态：{status}", f"/agents?agent={agent.agent_id}", entity_id=agent.agent_id, updated_at=agent.last_checked_at)
        items.sort(key=lambda item: (item.severity != "critical", item.updated_at), reverse=False)
        return WirelessDashboardAlertsDTO(items=items[:100], total=len(items), critical=sum(item.severity == "critical" for item in items), warning=sum(item.severity == "warning" for item in items))

    @staticmethod
    def _freshness(base, ac, mesh, trains, tasks, sessions, analysis, agents) -> WirelessDashboardFreshnessDTO:
        latest_task = max((item.updated_time for item in tasks), default="")
        latest_session = max(((item.stopped_at or item.started_at or item.created_at or "") for item in sessions), default="")
        latest_agent = max((item.last_checked_at for item in agents), default="")
        items = [
            WirelessDashboardFreshnessItemDTO(source="base_data", label="轨道交通基础资料", status="available" if base.updated_at else "no_data", updated_at=base.updated_at, message=base.message),
            WirelessDashboardFreshnessItemDTO(source="ac_management", label="FIT-AP / 光衰", status="available" if ac.updated_at else "no_data", updated_at=ac.updated_at, message=ac.message),
            WirelessDashboardFreshnessItemDTO(source="ac_mesh_link", label="AC Mesh-Link", status=mesh.data_status, updated_at=mesh.updated_at, age_seconds=mesh.age_seconds, message=mesh.message),
            WirelessDashboardFreshnessItemDTO(source="train_communication", label="在线列车通信", status="available" if trains.latest_updated_at else "no_data", updated_at=trains.latest_updated_at or ""),
            WirelessDashboardFreshnessItemDTO(source="online_mr", label="Online MR 会话", status="available" if latest_session else "no_data", updated_at=latest_session),
            WirelessDashboardFreshnessItemDTO(source="job_center", label="任务中心", status="available" if latest_task else "no_data", updated_at=latest_task),
            WirelessDashboardFreshnessItemDTO(source="mesh_analysis", label="Mesh 离线分析", status="available" if analysis.latest_analysis_time else "no_data", updated_at=analysis.latest_analysis_time or ""),
            WirelessDashboardFreshnessItemDTO(source="agents", label="Agent Controller 缓存", status="available" if agents else "no_data", updated_at=latest_agent, message="仅展示 Controller 已缓存状态，不主动探测 Agent。"),
        ]
        return WirelessDashboardFreshnessDTO(items=items)

    @staticmethod
    def _data_version(base, ac, mesh, trains, tasks, sessions, analysis, agents) -> str:
        payload: dict[str, Any] = {
            "base": [base.updated_at, base.ap_count, base.mr_count, base.issue_count],
            "ac": [ac.updated_at, ac.ap_total, ac.optical_anomalies],
            "mesh": [mesh.updated_at, mesh.link_total, mesh.data_status],
            "trains": [trains.latest_updated_at, trains.registered_trains, trains.active_online_mr_sessions],
            "task": [tasks[0].updated_time, tasks[0].id] if tasks else [],
            "session": [sessions[0].session_id, sessions[0].status] if sessions else [],
            "analysis": [analysis.latest_analysis_time, analysis.session_count, analysis.link_record_count],
            "agents": [[item.agent_id, WirelessDashboardQueryService._text(item.status), item.last_checked_at] for item in agents],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def _text(value: Any) -> str:
        return str(getattr(value, "value", value) or "")


__all__ = ["WirelessDashboardQueryService"]
