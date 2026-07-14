from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_mesh_link import AcMeshMrStatusDTO
from netconsole.models.api.job_center import JobCenterTaskDTO
from netconsole.models.api.online_mr import OnlineMrRealtimePreviewDTO, OnlineMrSessionSummaryDTO
from netconsole.models.api.rail_transit_base_data import VehicleMrDTO
from netconsole.models.api.train_communication import (
    CommunicationDataSourceDTO,
    CommunicationMetricDTO,
    CommunicationPackageDTO,
    CommunicationRawSourceDTO,
    CommunicationTaskDTO,
    CommunicationWarningDTO,
    MrCommunicationDetailDTO,
    MrCommunicationStatusDTO,
    TrainCommunicationDetailDTO,
    TrainCommunicationPageDTO,
    TrainCommunicationRowDTO,
    TrainCommunicationSummaryDTO,
)
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.job_center.query_service import JobCenterQueryService
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.online_mr.errors import OnlineMrQueryError
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


ACTIVE_SESSION_STATES = {
    "CREATED",
    "CONNECTING",
    "INITIALIZING",
    "COLLECTING",
    "RECONNECTING",
    "RUNNING",
    "STOPPING",
}
RAW_LABELS = {
    "mesh_link": "Mesh-Link",
    "channel_busy": "最新空口",
    "fping_samples": "高频 Ping 样本",
    "fping_summary": "高频 Ping 汇总",
    "fping_raw": "高频 Ping 原始输出",
    "iperf_client": "iPerf Client",
    "switch_history": "主链路切换日志",
    "collector_output": "Collector 输出",
}


class TrainCommunicationQueryService:
    """在线列车通信页的只读聚合边界。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        base_query: RailTransitBaseDataQueryService | None = None,
        mesh_query: AcMeshLinkQueryService | None = None,
        online_mr_query: OnlineMrQueryService | None = None,
        job_query: JobCenterQueryService | None = None,
        now_provider=None,
    ) -> None:
        self.paths = paths
        self.base_query = base_query or RailTransitBaseDataQueryService(paths)
        self.mesh_query = mesh_query or AcMeshLinkQueryService(paths)
        self.online_mr_query = online_mr_query or OnlineMrQueryService(paths)
        self.job_query = job_query or JobCenterQueryService(paths)
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    def current_site_id(self) -> str:
        return self.base_query.current_site_id()

    def get_summary(self, site_id: str) -> TrainCommunicationSummaryDTO:
        rows, sessions = self._rows(site_id)
        counts = {name: sum(row.communication_status == name for row in rows) for name in _STATUS_ORDER}
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
            active_online_mr_sessions=sum(self._is_active(item.status) for item in sessions),
            agent_imported_sessions=sum(str(item.executor_kind or "").upper() == "AGENT" for item in sessions),
            latest_updated_at=self._latest_text(*(row.last_updated_at for row in rows)),
        )

    def list_trains(
        self,
        site_id: str,
        *,
        train: str = "",
        mr_role: str = "",
        communication_status: str = "",
        mesh_link_status: str = "",
        station: str = "",
        section: str = "",
        line_side: str = "",
        executor: str = "",
        data_source: str = "",
        has_warning: bool | None = None,
        query: str = "",
        active_only: bool = False,
        agent_only: bool = False,
        optical_anomaly_only: bool = False,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "train_no",
        sort_order: str = "asc",
    ) -> TrainCommunicationPageDTO:
        rows, _ = self._rows(site_id)
        if train:
            needle = train.casefold()
            rows = [row for row in rows if needle in f"{row.train_no} {row.train_name}".casefold()]
        if mr_role:
            rows = [row for row in rows if any(item.mr_role.casefold() == mr_role.casefold() for item in row.mrs)]
        if communication_status:
            rows = [row for row in rows if row.communication_status == communication_status]
        if mesh_link_status:
            needle = mesh_link_status.casefold()
            rows = [row for row in rows if any(needle in item.mesh_link_status.casefold() for item in row.mrs)]
        for value, field in ((station, "station"), (section, "section"), (line_side, "line_side")):
            if value:
                needle = value.casefold()
                rows = [row for row in rows if any(needle in str(getattr(item, field)).casefold() for item in row.mrs)]
        if executor:
            rows = [row for row in rows if any(str(item.executor or "").upper() == executor.upper() for item in row.mrs)]
        if data_source:
            rows = [row for row in rows if any(any(source.source == data_source for source in item.data_sources) for item in row.mrs)]
        if has_warning is not None:
            rows = [row for row in rows if (row.warning_count > 0) is has_warning]
        if active_only:
            rows = [row for row in rows if row.active_sessions > 0]
        if agent_only:
            rows = [row for row in rows if any(str(item.executor or "").upper() == "AGENT" for item in row.mrs)]
        if optical_anomaly_only:
            rows = [row for row in rows if any(item.optical_status in {"warning", "critical"} for item in row.mrs)]
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in self._search_text(row)]
        reverse = sort_order == "desc"
        if sort_by == "status":
            rows.sort(key=lambda row: (_STATUS_ORDER[row.communication_status], self._natural_key(row.train_no)), reverse=reverse)
        elif sort_by == "updated_at":
            rows.sort(key=lambda row: row.last_updated_at or "", reverse=reverse)
        else:
            rows.sort(key=lambda row: self._natural_key(row.train_no), reverse=reverse)
        size = max(1, min(int(page_size), 200))
        current = max(1, int(page))
        start = (current - 1) * size
        return TrainCommunicationPageDTO(items=rows[start : start + size], total=len(rows), page=current, page_size=size)

    def get_train_detail(self, site_id: str, train_id: str) -> TrainCommunicationDetailDTO | None:
        rows, _ = self._rows(site_id)
        row = next((item for item in rows if item.train_id == train_id), None)
        if row is None:
            return None
        return TrainCommunicationDetailDTO(
            train=row,
            site_id=site_id,
            sources=self._unique_sources(source for mr in row.mrs for source in mr.data_sources),
            warnings=[warning for mr in row.mrs for warning in mr.warnings],
        )

    def get_mr_detail(self, site_id: str, mr_id: str) -> MrCommunicationDetailDTO | None:
        mr = self._find_mr(site_id, mr_id)
        if mr is None:
            return None
        collectors = []
        if mr.session_id:
            collectors = [item.model_dump() for item in self.online_mr_query.list_collectors(site_id, mr.session_id)]
        return MrCommunicationDetailDTO(
            mr=mr,
            collectors=collectors,
            raw_sources=self._raw_sources_for(site_id, mr),
            tasks=self._related_tasks_for(site_id, mr),
            packages=self._related_packages_for(site_id, mr),
        )

    def get_communication_preview(self, site_id: str, mr_id: str) -> MrCommunicationStatusDTO | None:
        return self._find_mr(site_id, mr_id)

    def get_raw_sources(self, site_id: str, mr_id: str) -> list[CommunicationRawSourceDTO]:
        mr = self._find_mr(site_id, mr_id)
        if mr is None or not mr.session_id:
            return []
        return self._raw_sources_for(site_id, mr)

    def _raw_sources_for(self, site_id: str, mr: MrCommunicationStatusDTO) -> list[CommunicationRawSourceDTO]:
        if not mr.session_id:
            return []
        return [
            CommunicationRawSourceDTO(
                name=item.name,
                label=RAW_LABELS.get(item.name, item.name),
                session_id=mr.session_id,
                exists=item.exists,
                size_bytes=item.size_bytes,
                modified_at=item.modified_at,
                message="" if item.exists else "文件不存在或尚未生成",
            )
            for item in self.online_mr_query.get_raw_summary(site_id, mr.session_id)
            if item.name in RAW_LABELS
        ]

    def get_related_tasks(self, site_id: str, mr_id: str) -> list[CommunicationTaskDTO]:
        mr = self._find_mr(site_id, mr_id)
        if mr is None:
            return []
        return self._related_tasks_for(site_id, mr)

    def _related_tasks_for(self, site_id: str, mr: MrCommunicationStatusDTO) -> list[CommunicationTaskDTO]:
        device_keys = {str(mr.device_id or ""), mr.mr_id}
        matches = [
            item
            for item in self.job_query.list_tasks(site_id, limit=1000)
            if (mr.session_id and item.session_id == mr.session_id)
            or (item.device_id and item.device_id in device_keys)
            or (item.mr_name and item.mr_name.casefold() == mr.mr_name.casefold())
        ][:50]
        return [
            CommunicationTaskDTO(
                id=item.id,
                type=item.type,
                name=item.name,
                status=item.status,
                progress=item.progress,
                executor=item.executor,
                source=item.source,
                started_at=item.started_time,
                ended_at=item.finished_time,
                updated_at=item.updated_time,
                error_summary=item.error_summary,
            )
            for item in matches
        ]

    def get_related_packages(self, site_id: str, mr_id: str) -> list[CommunicationPackageDTO]:
        mr = self._find_mr(site_id, mr_id)
        if mr is None:
            return []
        return self._related_packages_for(site_id, mr)

    def _related_packages_for(self, site_id: str, mr: MrCommunicationStatusDTO) -> list[CommunicationPackageDTO]:
        rows = [
            item
            for item in self.online_mr_query.list_sessions(site_id, limit=1000)
            if self._session_matches_status(item, mr)
        ]
        return [
            CommunicationPackageDTO(
                session_id=item.session_id,
                package_name=str(item.package_name or ""),
                package_reference=str(item.package_reference or ""),
                executor=str(item.executor_kind or ""),
                agent_id=item.agent_id,
                import_status="imported" if str(item.executor_kind or "").upper() == "AGENT" else "not_applicable",
                data_integrity=self._integrity(item),
                collected_at=item.stopped_at or item.started_at,
            )
            for item in rows
            if item.has_package and item.package_name and item.package_reference
        ]

    def read_raw_tail(self, site_id: str, mr_id: str, name: str, *, tail: int = 200):
        mr = self._find_mr(site_id, mr_id)
        if mr is None or not mr.session_id:
            return None
        return self.online_mr_query.read_raw_tail(site_id, mr.session_id, name, tail=tail)

    def _find_mr(self, site_id: str, mr_id: str) -> MrCommunicationStatusDTO | None:
        rows, _ = self._rows(site_id)
        return next((mr for row in rows for mr in row.mrs if mr.mr_id == mr_id), None)

    def _rows(self, site_id: str) -> tuple[list[TrainCommunicationRowDTO], list[OnlineMrSessionSummaryDTO]]:
        base_mrs = self.base_query.list_mrs(site_id, page=1, page_size=200).items
        mesh_page = self.mesh_query.list_mrs(site_id, page=1, page_size=200)
        mesh_summary = self.mesh_query.get_summary(site_id)
        sessions = self.online_mr_query.list_sessions(site_id, limit=1000)
        tasks = self.job_query.list_tasks(site_id, limit=1000)
        mesh_by_device, mesh_by_name = self._mesh_indexes(mesh_page.items)
        sessions_by_device, sessions_by_name = self._session_indexes(sessions)
        task_by_session = {item.session_id: item for item in tasks if item.session_id}
        tasks_by_device, tasks_by_name = self._task_indexes(tasks)
        grouped: dict[str, list[MrCommunicationStatusDTO]] = defaultdict(list)
        for base in base_mrs:
            mesh = mesh_by_device.get(str(base.id)) or mesh_by_name.get(base.name.casefold())
            session = sessions_by_device.get(str(base.device_id or "")) or sessions_by_name.get(base.name.casefold())
            task = task_by_session.get(session.session_id) if session else None
            task = task or tasks_by_device.get(str(base.device_id or "")) or tasks_by_device.get(base.id)
            task = task or tasks_by_name.get(base.name.casefold())
            grouped[base.train_id].append(self._mr_status(base, mesh, session, task, mesh_summary.age_seconds))
        rows = [self._train_row(train_id, mrs) for train_id, mrs in grouped.items()]
        return rows, sessions

    def _mr_status(
        self,
        base: VehicleMrDTO,
        mesh: AcMeshMrStatusDTO | None,
        session: OnlineMrSessionSummaryDTO | None,
        task: JobCenterTaskDTO | None,
        mesh_age_seconds: int | None,
    ) -> MrCommunicationStatusDTO:
        preview = self._preview(session)
        link = preview.link if preview else {}
        fping_payload, iperf_payload = self._traffic_payloads(session, preview)
        fping = self._metric(fping_payload, "fping")
        iperf = self._metric(iperf_payload, "iperf")
        peer_name = str(mesh.peer_ap_name if mesh else "")
        peer_mac = str(mesh.peer_ap_mac if mesh else "")
        warnings: list[CommunicationWarningDTO] = []
        live_name = self._text(link, "peer_ap_name", "peer_name", "ap_name")
        live_mac = self._text(link, "peer_ap_mac", "peer_mac", "ap_mac")
        if not peer_name:
            peer_name = live_name
        elif live_name and peer_name.casefold() != live_name.casefold():
            warnings.append(self._warning("source_conflict", "AC 快照与 Online MR 的 Peer AP 名称不一致", "mesh_link"))
        if not peer_mac:
            peer_mac = live_mac
        elif live_mac and self._mac_key(peer_mac) != self._mac_key(live_mac):
            warnings.append(self._warning("source_conflict", "AC 快照与 Online MR 的 Peer MAC 不一致", "mesh_link"))
        if mesh and mesh.match_warning:
            warnings.append(self._warning("mesh_match_warning", mesh.match_warning, "ac_mesh_link"))
        if base.issue_count:
            warnings.append(self._warning("base_data_issue", f"基础资料存在 {base.issue_count} 项待核验问题", "base_data"))
        if mesh and mesh.online_status == "offline":
            warnings.append(self._warning("mr_offline", "当前 Mesh-Link 快照显示 MR 离线", "ac_mesh_link"))
        if mesh and mesh.ap_online_status == "offline":
            warnings.append(self._warning("peer_ap_offline", "当前关联轨旁 AP 离线", "ac_mesh_link", "critical"))
        if mesh and mesh.optical_status in {"warning", "critical"}:
            warnings.append(self._warning("optical_anomaly", "当前关联轨旁 AP 存在光衰异常", "ac_mesh_link", mesh.optical_status))
        if mesh and mesh.data_status == "stale":
            warnings.append(self._warning("stale_mesh_snapshot", "Mesh-Link 数据已过期", "ac_mesh_link"))
        if session and str(session.status).upper() == "FAILED":
            warnings.append(self._warning("collection_failed", session.error_message or "最近 Online MR 采集失败", "online_mr", "critical"))
        elif task and task.status == "FAILED":
            warnings.append(self._warning("collection_failed", task.error_summary or "最近 Online MR 任务失败", "job_center", "critical"))
        integrity = self._integrity(session)
        if integrity == "partial":
            warnings.append(self._warning("partial_data", "采集数据仅部分完整", "online_mr"))
        for metric, source in ((fping, "fping"), (iperf, "iperf")):
            if metric.status.casefold() in {"warning", "failed", "error", "critical", "timeout"}:
                severity = "critical" if metric.status.casefold() in {"failed", "error", "critical", "timeout"} else "warning"
                warnings.append(self._warning(f"{source}_status", f"{source} 状态为 {metric.status}", source, severity))
        data_sources = [CommunicationDataSourceDTO(source="base_data", status="formal", reference=base.id)]
        if mesh:
            data_sources.append(CommunicationDataSourceDTO(source="ac_mesh_link", status=mesh.data_status, updated_at=mesh.last_seen_at or None, age_seconds=mesh_age_seconds, reference=mesh.mr_id))
        if session:
            data_sources.append(CommunicationDataSourceDTO(source="online_mr", status="active" if self._is_active(session.status) else "recent", updated_at=session.started_at, reference=session.session_id))
        if task:
            data_sources.append(CommunicationDataSourceDTO(source="job_center", status="active" if self._is_active(task.status) else "recent", updated_at=task.updated_time or None, reference=task.id))
        if preview and preview.available:
            data_sources.append(CommunicationDataSourceDTO(source="online_mr_preview", status="fresh", updated_at=preview.updated_at, age_seconds=self._age_seconds(preview.updated_at), reference=preview.session_id))
        mesh_link_status = str(mesh.link_status if mesh and mesh.link_status else mesh.online_status if mesh else self._text(link, "status", "link_status") or "unknown")
        status = self._mr_communication_status(mesh, session, warnings)
        collected_at = self._latest_text(
            mesh.last_seen_at if mesh else None,
            preview.updated_at if preview else None,
            session.started_at if session else None,
        )
        return MrCommunicationStatusDTO(
            train_id=base.train_id,
            train_name=f"{base.train_no}车" if base.train_no else base.train_id,
            mr_id=base.id,
            mr_name=base.name,
            mr_role=base.role,
            device_id=base.device_id,
            management_ip=base.management_ip,
            mac=base.mac,
            executor=str(session.executor_kind or "") if session else task.executor if task else None,
            agent_id=session.agent_id if session else task.agent if task else None,
            collection_status=str(session.status if session else task.status if task else "no_data"),
            session_id=session.session_id if session else None,
            task_id=(task.id if task else session.controller_task_id if session else None),
            mesh_link_status=mesh_link_status,
            peer_ap_id=mesh.peer_ap_id if mesh else "",
            peer_ap_name=peer_name,
            peer_ap_mac=peer_mac,
            mesh_radio=mesh.mesh_radio if mesh else self._text(link, "mesh_radio", "radio", "interface"),
            rssi=float(mesh.rssi) if mesh and mesh.rssi is not None else self._number(link, "rssi", "signal"),
            station=(mesh.station if mesh else "") or self._text(preview.display_context if preview else {}, "station"),
            section=(mesh.section if mesh else "") or self._text(preview.display_context if preview else {}, "section"),
            mileage=(mesh.mileage if mesh else "") or self._text(preview.display_context if preview else {}, "mileage"),
            line_side=(mesh.line_side if mesh else "") or self._text(preview.display_context if preview else {}, "line_side"),
            ap_online_status=mesh.ap_online_status if mesh else "unknown",
            optical_status=mesh.optical_status if mesh else "no_data",
            fping_status=fping.status,
            fping_latest_rtt_ms=fping.latest_value,
            fping_avg_rtt_ms=fping.average_value,
            fping_loss_percent=fping.loss_percent,
            iperf_status=iperf.status,
            iperf_latest_mbps=iperf.latest_value,
            iperf_avg_mbps=iperf.average_value,
            iperf_threshold_mbps=iperf.threshold_value,
            data_integrity=integrity,
            collected_at=collected_at,
            data_age_seconds=min((source.age_seconds for source in data_sources if source.age_seconds is not None), default=None),
            communication_status=status,
            is_active=bool((session and self._is_active(session.status)) or (task and self._is_active(task.status))),
            warnings=warnings,
            data_sources=data_sources,
            fping=fping,
            iperf=iperf,
        )

    def _train_row(self, train_id: str, mrs: list[MrCommunicationStatusDTO]) -> TrainCommunicationRowDTO:
        statuses = [item.communication_status for item in mrs]
        all_offline = bool(mrs) and all(item.mesh_link_status.casefold() in {"offline", "down", "disconnected"} for item in mrs)
        if all_offline or "critical" in statuses:
            status = "critical"
        elif "warning" in statuses:
            status = "warning"
        elif statuses and all(item == "stale" for item in statuses):
            status = "stale"
        elif "normal" in statuses:
            status = "normal"
        elif "stale" in statuses:
            status = "stale"
        else:
            status = "unknown"
        train_no = mrs[0].train_id if mrs else train_id
        return TrainCommunicationRowDTO(
            train_id=train_id,
            train_no=train_no,
            train_name=mrs[0].train_name if mrs else train_id,
            communication_status=status,
            mrs=sorted(mrs, key=lambda item: (item.mr_role, item.mr_name)),
            current_mesh_links=sum(
                item.mesh_link_status.casefold() in {"forwarding", "online", "up", "connected"}
                and any(source.source == "ac_mesh_link" and source.status == "fresh" for source in item.data_sources)
                for item in mrs
            ),
            active_sessions=sum(item.is_active for item in mrs),
            warning_count=sum(len(item.warnings) for item in mrs),
            last_updated_at=self._latest_text(*(item.collected_at for item in mrs)),
        )

    def _preview(self, session: OnlineMrSessionSummaryDTO | None) -> OnlineMrRealtimePreviewDTO | None:
        if session is None:
            return None
        try:
            return self.online_mr_query.get_realtime_preview(session.site_id, session.session_id)
        except (OSError, ValueError, OnlineMrQueryError):
            return None

    def _traffic_payloads(
        self,
        session: OnlineMrSessionSummaryDTO | None,
        preview: OnlineMrRealtimePreviewDTO | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        live_fping = dict(preview.fping) if preview and preview.fping else {}
        live_iperf = dict(preview.iperf) if preview and preview.iperf else {}
        if session is None or self._is_active(session.status):
            return live_fping, live_iperf
        fping: dict[str, Any] = {}
        iperf: dict[str, Any] = {}
        try:
            traffic = self.online_mr_query.get_session(session.site_id, session.session_id).traffic_summary
            if isinstance(traffic.get("fping"), dict):
                fping = dict(traffic["fping"])
            if isinstance(traffic.get("iperf"), dict):
                iperf = dict(traffic["iperf"])
            final = self.online_mr_query.read_raw_tail(session.site_id, session.session_id, "fping_summary", tail=200)
            if final.summary:
                fping.update(final.summary)
        except (OSError, ValueError, OnlineMrQueryError):
            pass
        return fping or live_fping, iperf or live_iperf

    @classmethod
    def _metric(cls, payload: dict[str, Any], kind: str) -> CommunicationMetricDTO:
        dicts = list(cls._nested_dicts(payload))
        status = cls._first_text(dicts, "status", "Status", "state") or ("available" if payload else "no_data")
        if kind == "fping":
            return CommunicationMetricDTO(
                status=status,
                target=cls._first_text(dicts, "target", "target_ip", "host", "name") or None,
                sent=cls._first_int(dicts, "sent", "sent_count", "packets_sent"),
                received=cls._first_int(dicts, "received", "received_count", "packets_received"),
                loss_percent=cls._first_number(dicts, "loss_percent", "loss_rate_percent", "packet_loss_percent"),
                latest_value=cls._first_number(dicts, "latest_rtt_ms", "latest_latency_ms", "latency_ms", "rtt_ms"),
                average_value=cls._first_number(dicts, "avg_rtt_ms", "average_rtt_ms", "avg_latency_ms"),
                maximum_value=cls._first_number(dicts, "max_rtt_ms", "max_latency_ms"),
                updated_at=cls._first_text(dicts, "updated_at", "timestamp") or None,
            )
        return CommunicationMetricDTO(
            status=status,
            target=cls._first_text(dicts, "server_host", "server", "host") or None,
            protocol=cls._first_text(dicts, "protocol") or None,
            direction=cls._first_text(dicts, "direction") or None,
            latest_value=cls._first_number(dicts, "bitrate_mbps", "throughput_mbps", "latest_mbps"),
            average_value=cls._first_number(dicts, "average_bitrate_mbps", "avg_mbps", "average_mbps"),
            maximum_value=cls._first_number(dicts, "max_bitrate_mbps", "max_mbps"),
            threshold_value=cls._first_number(dicts, "threshold_mbps", "min_bitrate_mbps"),
            updated_at=cls._first_text(dicts, "updated_at", "timestamp") or None,
        )

    @staticmethod
    def _mr_communication_status(
        mesh: AcMeshMrStatusDTO | None,
        session: OnlineMrSessionSummaryDTO | None,
        warnings: list[CommunicationWarningDTO],
    ) -> str:
        if any(item.severity == "critical" for item in warnings):
            return "critical"
        if warnings and not (mesh and mesh.data_status == "stale" and len(warnings) == 1):
            return "warning"
        if mesh and mesh.data_status in {"recent", "stale"}:
            return "stale"
        if mesh and mesh.data_status in {"fresh", "recent"} and mesh.online_status == "online":
            return "normal"
        if session and str(session.status).upper() in ACTIVE_SESSION_STATES:
            return "warning"
        return "unknown"

    @staticmethod
    def _mesh_indexes(items: list[AcMeshMrStatusDTO]) -> tuple[dict[str, AcMeshMrStatusDTO], dict[str, AcMeshMrStatusDTO]]:
        return (
            {str(item.mr_device_id): item for item in items if item.mr_device_id},
            {item.mr_name.casefold(): item for item in items if item.mr_name},
        )

    def _session_indexes(
        self, items: list[OnlineMrSessionSummaryDTO]
    ) -> tuple[dict[str, OnlineMrSessionSummaryDTO], dict[str, OnlineMrSessionSummaryDTO]]:
        ordered = sorted(items, key=lambda item: (not self._is_active(item.status), -(self._timestamp(item.started_at))))
        by_device: dict[str, OnlineMrSessionSummaryDTO] = {}
        by_name: dict[str, OnlineMrSessionSummaryDTO] = {}
        for item in ordered:
            if item.device_id not in (None, ""):
                by_device.setdefault(str(item.device_id), item)
            for name in (item.mr_name, item.device_name):
                if name:
                    by_name.setdefault(name.casefold(), item)
        return by_device, by_name

    def _task_indexes(
        self, items: list[JobCenterTaskDTO]
    ) -> tuple[dict[str, JobCenterTaskDTO], dict[str, JobCenterTaskDTO]]:
        ordered = sorted(items, key=lambda item: not self._is_active(item.status))
        by_device: dict[str, JobCenterTaskDTO] = {}
        by_name: dict[str, JobCenterTaskDTO] = {}
        for item in ordered:
            if item.device_id:
                by_device.setdefault(item.device_id, item)
            for name in (item.mr_name, item.device_name):
                if name:
                    by_name.setdefault(name.casefold(), item)
        return by_device, by_name

    @staticmethod
    def _session_matches_status(item: OnlineMrSessionSummaryDTO, mr: MrCommunicationStatusDTO) -> bool:
        return (
            item.device_id not in (None, "")
            and mr.device_id not in (None, "")
            and str(item.device_id) == str(mr.device_id)
        ) or any(name and name.casefold() == mr.mr_name.casefold() for name in (item.mr_name, item.device_name))

    @staticmethod
    def _integrity(session: OnlineMrSessionSummaryDTO | None) -> str:
        if session is None:
            return "unknown"
        if session.finalization_complete is True and not session.force_stopped:
            return "complete"
        if session.finalization_complete is False or session.force_stopped:
            return "partial"
        return "unknown"

    @staticmethod
    def _is_active(status: str) -> bool:
        return str(status or "").upper() in ACTIVE_SESSION_STATES

    @staticmethod
    def _warning(code: str, message: str, source: str, severity: str = "warning") -> CommunicationWarningDTO:
        return CommunicationWarningDTO(code=code, message=message, source=source, severity=severity)

    @staticmethod
    def _unique_sources(items: Iterable[CommunicationDataSourceDTO]) -> list[CommunicationDataSourceDTO]:
        result: dict[tuple[str, str], CommunicationDataSourceDTO] = {}
        for item in items:
            result[(item.source, item.reference)] = item
        return list(result.values())

    @staticmethod
    def _search_text(row: TrainCommunicationRowDTO) -> str:
        return " ".join(
            [row.train_no, row.train_name]
            + [f"{item.mr_name} {item.management_ip} {item.peer_ap_name} {item.station} {item.section}" for item in row.mrs]
        ).casefold()

    @staticmethod
    def _natural_key(value: str) -> tuple[Any, ...]:
        import re

        return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value or ""))

    def _age_seconds(self, value: str | None) -> int | None:
        parsed = self._parse_datetime(value)
        if parsed is None:
            return None
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return max(0, int((now - parsed).total_seconds()))

    @classmethod
    def _timestamp(cls, value: str | None) -> float:
        parsed = cls._parse_datetime(value)
        return parsed.timestamp() if parsed else 0.0

    @classmethod
    def _latest_text(cls, *values: str | None) -> str | None:
        present = [value for value in values if value]
        return max(present, key=cls._timestamp) if present else None

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _nested_dicts(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        pending: list[Any] = [payload]
        while pending:
            item = pending.pop(0)
            if isinstance(item, dict):
                yield item
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)

    @classmethod
    def _first_text(cls, items: list[dict[str, Any]], *keys: str) -> str:
        for item in items:
            value = cls._text(item, *keys)
            if value:
                return value
        return ""

    @classmethod
    def _first_number(cls, items: list[dict[str, Any]], *keys: str) -> float | None:
        for item in items:
            value = cls._number(item, *keys)
            if value is not None:
                return value
        return None

    @classmethod
    def _first_int(cls, items: list[dict[str, Any]], *keys: str) -> int | None:
        value = cls._first_number(items, *keys)
        return int(value) if value is not None else None

    @staticmethod
    def _text(item: dict[str, Any], *keys: str) -> str:
        return next((str(item[key]) for key in keys if item.get(key) not in (None, "")), "")

    @staticmethod
    def _number(item: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            try:
                if item.get(key) not in (None, ""):
                    return float(item[key])
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _mac_key(value: str) -> str:
        return "".join(character for character in str(value).casefold() if character in "0123456789abcdef")


_STATUS_ORDER = {"critical": 0, "warning": 1, "stale": 2, "unknown": 3, "normal": 4}


__all__ = ["TrainCommunicationQueryService"]
