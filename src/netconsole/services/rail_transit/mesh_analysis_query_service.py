from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.mesh_analysis import (
    MeshAlignmentDTO,
    MeshAlignmentPointDTO,
    MeshAnalysisSessionDTO,
    MeshAnalysisSessionDetailDTO,
    MeshAnalysisSessionPageDTO,
    MeshAnalysisSummaryDTO,
    MeshAnalysisWarningDTO,
    MeshAnomalyDTO,
    MeshAnomalyPageDTO,
    MeshApStatisticsDTO,
    MeshApStatisticsPageDTO,
    MeshChannelBusyDTO,
    MeshChannelBusyPageDTO,
    MeshDataSourceDTO,
    MeshLinkDetailDTO,
    MeshLinkPageDTO,
    MeshLinkTimelineDTO,
    MeshRawTailDTO,
    MeshReportArtifactDTO,
    MeshRssiDTO,
    MeshRssiPointDTO,
    MeshRssiStatisticsDTO,
    MeshSwitchEventDTO,
    MeshSwitchEventPageDTO,
    MeshTimelineDTO,
)
from netconsole.models.api.online_mr import OnlineMrDownsampleMode, OnlineMrMetricType
from netconsole.repositories.mesh_mr_repository import _active_build_order_rows_from_points
from netconsole.services.online_mr.errors import OnlineMrQueryError
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService


_SESSION_ID_RE = re.compile(r"^(?P<mr_id>[0-9a-fA-F-]{8,64}):(?P<source_id>[1-9][0-9]*)$")
_MR_IDENTITY_RE = re.compile(r"^(?P<train>.+?)[-_ ]*MR[-_ ]*(?P<role>CT|TC|CW)$", re.IGNORECASE)
_ALLOWED_OUTPUT_SUFFIXES = {".xlsx", ".zip", ".csv", ".json", ".md"}
_MAX_PAGE_SIZE = 500


class MeshAnalysisQueryError(RuntimeError):
    pass


@dataclass(frozen=True)
class _ApLocation:
    name: str = ""
    mac: str = ""
    station: str = ""
    section: str = ""
    mileage: str = ""
    line_side: str = ""


@dataclass(frozen=True)
class _SessionContext:
    site_id: str
    session_id: str
    mr_id: str
    mr_name: str
    safe_folder_name: str
    linked_device_id: int | None
    source_id: int
    source: dict[str, Any]
    mr_root: Path
    index_db: Path
    detail_db: Path | None
    raw_path: Path | None
    relocated_detail: bool = False


@dataclass(frozen=True)
class _ArtifactCandidate:
    dto: MeshReportArtifactDTO
    path: Path


class MeshAnalysisQueryService:
    """只读展示既有 Mesh 分析结果；不初始化 schema，也不触发解析或报告。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        base_query: RailTransitBaseDataQueryService | None = None,
        online_mr_query: OnlineMrQueryService | None = None,
    ) -> None:
        self.paths = paths
        self.base_query = base_query or RailTransitBaseDataQueryService(paths)
        self.online_mr_query = online_mr_query or OnlineMrQueryService(paths)

    def current_site_id(self) -> str:
        try:
            return str(SiteManager(self.paths).get_current_site() or "demo")
        except (OSError, ValueError, KeyError):
            return "demo"

    def get_summary(self, site_id: str) -> MeshAnalysisSummaryDTO:
        sessions = self._session_rows(site_id)
        summary = MeshAnalysisSummaryDTO(site_id=site_id, session_count=len(sessions))
        trains: set[str] = set()
        mrs: set[str] = set()
        latest = ""
        for context in sessions:
            stats = self._stats(context)
            train_name, _role = self._mr_identity(context.mr_name)
            if train_name:
                trains.add(train_name)
            mrs.add(context.mr_name)
            summary.link_record_count += stats["links"]
            summary.active_link_count += stats["active"]
            summary.standby_link_count += stats["standby"]
            summary.link_up_event_count += stats["link_up"]
            summary.link_down_event_count += stats["link_down"]
            summary.switch_event_count += stats["switches"]
            summary.short_link_count += stats["short"]
            summary.pingpong_count += stats["pingpong"]
            summary.rssi_anomaly_count += stats["rssi_anomalies"]
            summary.channel_busy_anomaly_count += stats["busy_anomalies"]
            summary.unmatched_ap_count += stats["unmatched"]
            summary.warning_session_count += int(stats["warnings"] > 0)
            latest = max(latest, str(context.source.get("imported_at") or ""))
        summary.train_count = len(trains)
        summary.mr_count = len(mrs)
        summary.latest_analysis_time = latest or None
        return summary

    def list_analysis_sessions(
        self,
        site_id: str,
        *,
        train: str = "",
        mr_name: str = "",
        mr_role: str = "",
        source_type: str = "",
        analysis_status: str = "",
        has_warning: bool | None = None,
        time_from: str = "",
        time_to: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "analysis_time",
        sort_order: str = "desc",
    ) -> MeshAnalysisSessionPageDTO:
        rows = [self._session_dto(context) for context in self._session_rows(site_id)]
        filters = {
            "train_name": train,
            "mr_name": mr_name,
            "mr_role": mr_role,
            "source_type": source_type,
            "analysis_status": analysis_status,
        }
        for field, value in filters.items():
            if value:
                needle = value.casefold()
                rows = [row for row in rows if needle in str(getattr(row, field)).casefold()]
        if has_warning is not None:
            rows = [row for row in rows if (row.warning_count > 0) is has_warning]
        if time_from:
            rows = [row for row in rows if (row.last_sample_time or row.analysis_time or "") >= time_from]
        if time_to:
            rows = [row for row in rows if (row.first_sample_time or row.analysis_time or "") <= time_to]
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in f"{row.train_name} {row.mr_name} {row.original_filename}".casefold()]
        sort_keys = {
            "analysis_time": lambda row: (row.analysis_time or "", row.session_id),
            "mr_name": lambda row: (row.mr_name.casefold(), row.analysis_time or ""),
            "link_record_count": lambda row: (row.link_record_count, row.analysis_time or ""),
        }
        rows.sort(key=sort_keys.get(sort_by, sort_keys["analysis_time"]), reverse=sort_order != "asc")
        current, size = self._page(page, page_size)
        start = (current - 1) * size
        return MeshAnalysisSessionPageDTO(items=rows[start : start + size], total=len(rows), page=current, page_size=size)

    def get_analysis_session(self, site_id: str, session_id: str) -> MeshAnalysisSessionDetailDTO:
        context = self._context(site_id, session_id)
        warnings: list[MeshAnalysisWarningDTO] = []
        if context.detail_db is None:
            warnings.append(MeshAnalysisWarningDTO(code="parsed_result_missing", message="结构化分析结果不存在，Web 不会自动重解析。", severity="error"))
        if context.raw_path is None:
            warnings.append(MeshAnalysisWarningDTO(code="raw_source_missing", message="原始 Mesh 日志当前不可用；既有结构化结果仍按只读方式展示。"))
        if context.relocated_detail:
            warnings.append(MeshAnalysisWarningDTO(code="parsed_path_relocated", message="索引中的旧数据根路径不可用，已只读使用当前 MR parsed 目录的同名结果。"))
        if int(context.source.get("issue_count") or 0):
            warnings.append(MeshAnalysisWarningDTO(code="parse_issues", message="该来源存在既有解析告警，请查看异常摘要。"))
        return MeshAnalysisSessionDetailDTO(session=self._session_dto(context), warnings=warnings, sources=self.get_raw_source_summary(site_id, session_id))

    def list_link_details(
        self,
        site_id: str,
        session_id: str,
        *,
        peer_ap_name: str = "",
        peer_ap_mac: str = "",
        station: str = "",
        section: str = "",
        line_side: str = "",
        link_role: str = "",
        event_type: str = "",
        time_from: str = "",
        time_to: str = "",
        has_warning: bool | None = None,
        query: str = "",
        page: int = 1,
        page_size: int = 100,
        sort_by: str = "timestamp",
        sort_order: str = "asc",
    ) -> MeshLinkPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshLinkPageDTO(page=page, page_size=page_size)
        clauses: list[str] = []
        values: list[Any] = []
        ap_map = self._ap_map(site_id)
        for column, value in (
            ("ml.peer_ap_name", peer_ap_name),
            ("COALESCE(NULLIF(ml.peer_ap_mac, ''), ml.peer_mac_normalized)", self._mac_key(peer_ap_mac)),
            ("ml.link_state", link_role.upper()),
        ):
            if value:
                clauses.append(f"LOWER(COALESCE({column}, '')) LIKE ?")
                values.append(f"%{str(value).casefold()}%")
        for field, value in (("station", station), ("section", section), ("line_side", line_side)):
            if not value:
                continue
            matching_macs = sorted(
                {
                    self._mac_key(location.mac)
                    for location in ap_map.values()
                    if self._mac_key(location.mac) and value.casefold() in str(getattr(location, field)).casefold()
                }
            )
            location_clause = "LOWER(COALESCE(ml.peer_site, '')) LIKE ?" if field in {"station", "section"} else "0"
            location_values: list[Any] = [f"%{value.casefold()}%"] if field in {"station", "section"} else []
            if matching_macs:
                placeholders = ",".join("?" for _ in matching_macs)
                location_clause = f"({location_clause} OR LOWER(COALESCE(NULLIF(ml.peer_ap_mac, ''), ml.peer_mac_normalized, '')) IN ({placeholders}))"
                location_values.extend(matching_macs)
            clauses.append(location_clause)
            values.extend(location_values)
        if event_type:
            clauses.append("EXISTS (SELECT 1 FROM switch_events se WHERE se.event_time = ml.sample_time AND se.event_type = ?)")
            values.append(event_type)
        if time_from:
            clauses.append("ml.sample_time >= ?")
            values.append(time_from)
        if time_to:
            clauses.append("ml.sample_time <= ?")
            values.append(time_to)
        if has_warning is not None:
            clauses.append("(COALESCE(ml.peer_ap_name, '') = '') = ?")
            values.append(1 if has_warning else 0)
        if query:
            clauses.append("LOWER(COALESCE(ml.peer_ap_name, '') || ' ' || COALESCE(ml.peer_mac_raw, '') || ' ' || COALESCE(ml.peer_site, '')) LIKE ?")
            values.append(f"%{query.casefold()}%")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        current, size = self._page(page, page_size)
        offset = (current - 1) * size
        direction = "DESC" if sort_order == "desc" else "ASC"
        sort_column = {"timestamp": "ml.sample_time", "rssi": "ml.local_rssi_db", "peer_ap_name": "ml.peer_ap_name"}.get(sort_by, "ml.sample_time")
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM mesh_links ml {where}", values).fetchone()[0] or 0)
            rows = conn.execute(
                f"""
                SELECT ml.id, ml.sample_time, ml.radio, ml.link_state, ml.peer_mac_raw,
                       ml.peer_mac_normalized, ml.peer_ap_name, ml.peer_ap_mac, ml.peer_site,
                       ml.peer_radio_label, ml.local_rssi_db, ml.duration_seconds,
                       ml.record_seq, ml.peer_match_rule, ml.peer_resolve_source,
                       (SELECT event_type FROM switch_events se WHERE se.event_time = ml.sample_time ORDER BY se.id LIMIT 1) AS event_type
                FROM mesh_links ml
                {where}
                ORDER BY {sort_column} {direction}, ml.id {direction}
                LIMIT ? OFFSET ?
                """,
                (*values, size, offset),
            ).fetchall()
        train_name, role = self._mr_identity(context.mr_name)
        items: list[MeshLinkDetailDTO] = []
        for row in rows:
            data = dict(row)
            location = self._locate_ap(ap_map, data)
            peer_mac = str(data.get("peer_ap_mac") or data.get("peer_mac_normalized") or data.get("peer_mac_raw") or "") or None
            peer_name = str(data.get("peer_ap_name") or location.name or "") or None
            items.append(
                MeshLinkDetailDTO(
                    record_id=int(data["id"]),
                    timestamp=str(data["sample_time"]),
                    train_name=train_name,
                    mr_name=context.mr_name,
                    mr_role=role,
                    local_radio=data.get("radio"),
                    peer_ap_name=peer_name,
                    peer_ap_mac=peer_mac,
                    peer_radio=str(data.get("peer_radio_label") or "") or None,
                    link_role=str(data.get("link_state") or ""),
                    link_status=str(data.get("link_state") or ""),
                    rssi=self._number(data.get("local_rssi_db")),
                    station=location.station or str(data.get("peer_site") or "") or None,
                    section=location.section or None,
                    mileage=location.mileage or None,
                    line_side=location.line_side or None,
                    event_type=str(data.get("event_type") or "") or None,
                    duration_ms=self._milliseconds(data.get("duration_seconds")),
                    source_file=str(context.source.get("original_filename") or context.source.get("archived_filename") or ""),
                    source_record_index=data.get("record_seq"),
                    match_method=str(data.get("peer_match_rule") or data.get("peer_resolve_source") or "") or None,
                    warning=None if peer_name else "Peer AP 未匹配",
                )
            )
        return MeshLinkPageDTO(items=items, total=total, page=current, page_size=size)

    def get_link_timeline(self, site_id: str, session_id: str, *, time_from: str = "", time_to: str = "", limit: int = 2_000) -> MeshTimelineDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshTimelineDTO()
        clauses, values = self._time_clauses("start_time", "end_time", time_from, time_to)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM active_segments {where}", values).fetchone()[0] or 0)
            rows = conn.execute(f"SELECT * FROM active_segments {where} ORDER BY start_time, id LIMIT ?", (*values, min(max(limit, 1), 5_000))).fetchall()
        ap_map = self._ap_map(site_id)
        items = []
        for row in rows:
            data = dict(row)
            location = self._locate_ap(ap_map, data)
            items.append(
                MeshLinkTimelineDTO(
                    segment_id=int(data["id"]),
                    start_time=str(data.get("start_time") or ""),
                    end_time=str(data.get("end_time") or ""),
                    duration_seconds=self._number(data.get("duration_sec")),
                    peer_ap_name=str(data.get("peer_ap_name") or location.name or "") or None,
                    peer_ap_mac=str(data.get("peer_mac_normalized") or data.get("peer_mac") or location.mac or "") or None,
                    local_radio=data.get("radio"),
                    rssi_min=self._number(data.get("min_rssi")),
                    rssi_avg=self._number(data.get("avg_rssi")),
                    rssi_max=self._number(data.get("max_rssi")),
                    station=location.station or str(data.get("belong_station") or "") or None,
                    section=location.section or str(data.get("belong_section") or "") or None,
                    mileage=location.mileage or None,
                    line_side=location.line_side or None,
                    event_type=str(data.get("event_type") or "") or None,
                )
            )
        return MeshTimelineDTO(items=items, total=total)

    def list_switch_events(
        self,
        site_id: str,
        session_id: str,
        *,
        event_type: str = "",
        time_from: str = "",
        time_to: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> MeshSwitchEventPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshSwitchEventPageDTO(page=page, page_size=page_size)
        clauses: list[str] = []
        values: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            values.append(event_type)
        if time_from:
            clauses.append("event_time >= ?")
            values.append(time_from)
        if time_to:
            clauses.append("event_time <= ?")
            values.append(time_to)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        current, size = self._page(page, page_size)
        offset = (current - 1) * size
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM switch_events {where}", values).fetchone()[0] or 0)
            rows = conn.execute(f"SELECT * FROM switch_events {where} ORDER BY event_time, id LIMIT ? OFFSET ?", (*values, size, offset)).fetchall()
            peer_rows = conn.execute(
                """
                SELECT peer_mac_normalized, MAX(peer_ap_name) AS peer_ap_name, MAX(peer_ap_mac) AS peer_ap_mac,
                       MAX(peer_site) AS peer_site
                FROM mesh_links WHERE COALESCE(peer_mac_normalized, '') != '' GROUP BY peer_mac_normalized
                """
            ).fetchall()
        ap_map = self._ap_map(site_id)
        peer_map = {self._mac_key(row["peer_mac_normalized"]): dict(row) for row in peer_rows}
        builds = self._build_rows(context)
        build_by_start = {str(row.get("build_start_time") or ""): row for row in builds}
        items: list[MeshSwitchEventDTO] = []
        for row in rows:
            data = dict(row)
            details = self._json_object(data.get("details_json"))
            build = build_by_start.get(str(data.get("current_sample_time") or data.get("event_time") or ""), {})
            from_peer = peer_map.get(self._mac_key(data.get("from_peer_mac")), {"peer_ap_mac": data.get("from_peer_mac")})
            to_peer = peer_map.get(self._mac_key(data.get("to_peer_mac")), {"peer_ap_mac": data.get("to_peer_mac")})
            from_location = self._locate_ap(ap_map, from_peer)
            to_location = self._locate_ap(ap_map, to_peer)
            items.append(
                MeshSwitchEventDTO(
                    event_id=int(data["id"]),
                    timestamp=str(data.get("event_time") or "") or None,
                    event_type=str(data.get("event_type") or ""),
                    mr_name=context.mr_name,
                    local_radio=data.get("radio"),
                    from_peer_mac=str(data.get("from_peer_mac") or "") or None,
                    to_peer_mac=str(data.get("to_peer_mac") or "") or None,
                    from_ap_name=from_location.name or str(from_peer.get("peer_ap_name") or "") or None,
                    to_ap_name=to_location.name or str(to_peer.get("peer_ap_name") or build.get("peer_ap_name") or "") or None,
                    before_rssi=self._number(details.get("from_local_rssi")),
                    after_rssi=self._number(details.get("to_local_rssi")),
                    duration_ms=data.get("observed_window_ms"),
                    is_short_link=build.get("build_result") == "short",
                    is_pingpong=bool(build.get("is_pingpong_abnormal")),
                    station=to_location.station or str(build.get("peer_site") or "") or None,
                    section=to_location.section or None,
                )
            )
        return MeshSwitchEventPageDTO(items=items, total=total, page=current, page_size=size)

    def get_rssi_statistics(
        self,
        site_id: str,
        session_id: str,
        *,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
    ) -> MeshRssiDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshRssiDTO(statistics=MeshRssiStatisticsDTO())
        max_points = min(max(int(max_points), 10), 2_000)
        clauses: list[str] = []
        values: list[Any] = []
        if time_from:
            clauses.append("sample_time >= ?")
            values.append(time_from)
        if time_to:
            clauses.append("sample_time <= ?")
            values.append(time_to)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM active_points {where}", values).fetchone()[0] or 0)
            missing = int(conn.execute(f"SELECT COUNT(*) FROM active_points {where} {'AND' if where else 'WHERE'} local_rssi_db IS NULL", values).fetchone()[0] or 0)
            latest = conn.execute(f"SELECT local_rssi_db FROM active_points {where} ORDER BY sample_time DESC, id DESC LIMIT 1", values).fetchone()
            stat_row = conn.execute("SELECT * FROM rssi_stats WHERE scope_type = 'all' ORDER BY id DESC LIMIT 1").fetchone()
            step = max(1, (total + max_points - 1) // max_points)
            point_rows = conn.execute(
                f"""
                WITH ordered AS (
                    SELECT sample_time, local_rssi_db, peer_ap_name, peer_mac_normalized, radio,
                           ROW_NUMBER() OVER (ORDER BY sample_time, id) AS rn
                    FROM active_points {where}
                )
                SELECT * FROM ordered WHERE ((rn - 1) % ?) = 0 ORDER BY sample_time LIMIT ?
                """,
                (*values, step, max_points),
            ).fetchall()
        data = dict(stat_row) if stat_row else {}
        statistics = MeshRssiStatisticsDTO(
            min_rssi=self._number(data.get("min_rssi")),
            max_rssi=self._number(data.get("max_rssi")),
            avg_rssi=self._number(data.get("avg_rssi")),
            latest_rssi=self._number(latest[0]) if latest else None,
            sample_count=int(data.get("sample_count") or max(total - missing, 0)),
            missing_sample_count=missing,
            low_rssi_count=int(data.get("low_rssi_count") or 0),
            severe_low_rssi_count=int(data.get("severe_low_rssi_count") or 0),
        )
        points = [
            MeshRssiPointDTO(
                timestamp=str(row["sample_time"]),
                value=self._number(row["local_rssi_db"]),
                peer_ap_name=str(row["peer_ap_name"] or "") or None,
                peer_ap_mac=str(row["peer_mac_normalized"] or "") or None,
                local_radio=row["radio"],
            )
            for row in point_rows
        ]
        return MeshRssiDTO(statistics=statistics, points=points, downsampled=step > 1, total_points=total)

    def get_channel_busy(
        self,
        site_id: str,
        session_id: str,
        *,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
    ) -> MeshChannelBusyPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshChannelBusyPageDTO()
        max_points = min(max(int(max_points), 10), 2_000)
        clauses = ["(local_tx_busy IS NOT NULL OR local_rx_busy IS NOT NULL)"]
        values: list[Any] = []
        if time_from:
            clauses.append("sample_time >= ?")
            values.append(time_from)
        if time_to:
            clauses.append("sample_time <= ?")
            values.append(time_to)
        where = "WHERE " + " AND ".join(clauses)
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM active_points {where}", values).fetchone()[0] or 0)
            step = max(1, (total + max_points - 1) // max_points)
            rows = conn.execute(
                f"""
                WITH ordered AS (
                    SELECT sample_time, radio, local_tx_busy, local_rx_busy, peer_ap_name, peer_site,
                           ROW_NUMBER() OVER (ORDER BY sample_time, id) AS rn
                    FROM active_points {where}
                )
                SELECT * FROM ordered WHERE ((rn - 1) % ?) = 0 ORDER BY sample_time LIMIT ?
                """,
                (*values, step, max_points),
            ).fetchall()
        items = [
            MeshChannelBusyDTO(
                timestamp=str(row["sample_time"]),
                local_radio=row["radio"],
                tx_busy=self._number(row["local_tx_busy"]),
                rx_busy=self._number(row["local_rx_busy"]),
                peer_ap_name=str(row["peer_ap_name"] or "") or None,
                station=str(row["peer_site"] or "") or None,
            )
            for row in rows
        ]
        return MeshChannelBusyPageDTO(items=items, total=total, downsampled=step > 1)

    def list_anomalies(
        self,
        site_id: str,
        session_id: str,
        *,
        anomaly_type: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> MeshAnomalyPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshAnomalyPageDTO(page=page, page_size=page_size)
        train_name, _role = self._mr_identity(context.mr_name)
        rows: list[MeshAnomalyDTO] = []
        with closing(self._connect_readonly(context.detail_db)) as conn:
            if self._table_exists(conn, "diagnosis_events"):
                for row in conn.execute("SELECT * FROM diagnosis_events ORDER BY event_time, id"):
                    data = dict(row)
                    rows.append(
                        MeshAnomalyDTO(
                            anomaly_id=f"diagnosis:{data['id']}",
                            severity=str(data.get("severity") or "warning"),
                            anomaly_type=str(data.get("category") or data.get("title") or "diagnosis"),
                            start_time=str(data.get("event_time") or "") or None,
                            train_name=train_name,
                            mr_name=context.mr_name,
                            peer_ap_mac=str(data.get("related_peer_mac") or "") or None,
                            description=str(data.get("detail") or data.get("title") or ""),
                            evidence_reference=str(data.get("evidence") or "") or None,
                        )
                    )
            if self._table_exists(conn, "parse_issues"):
                for row in conn.execute("SELECT * FROM parse_issues ORDER BY id"):
                    data = dict(row)
                    rows.append(
                        MeshAnomalyDTO(
                            anomaly_id=f"parse:{data['id']}",
                            severity=str(data.get("severity") or "warning").lower(),
                            anomaly_type=str(data.get("issue_type") or "parse_issue"),
                            train_name=train_name,
                            mr_name=context.mr_name,
                            description=str(data.get("message") or ""),
                            evidence_reference=f"line:{data.get('line_number')}",
                        )
                    )
        for build in self._build_rows(context):
            common = {
                "train_name": train_name,
                "mr_name": context.mr_name,
                "peer_ap_name": str(build.get("peer_ap_name") or "") or None,
                "peer_ap_mac": str(build.get("active_peer_mac") or "") or None,
                "station": str(build.get("peer_site") or "") or None,
                "start_time": str(build.get("build_start_time") or "") or None,
                "end_time": str(build.get("build_end_time") or "") or None,
                "rule_version": "existing_mesh_analysis_params",
            }
            if build.get("build_result") == "short":
                rows.append(
                    MeshAnomalyDTO(
                        anomaly_id=f"short:{build.get('sequence')}",
                        severity="warning",
                        anomaly_type="short_link",
                        description=str(build.get("judge_reason") or "短时建链"),
                        evidence_reference=f"segment:{build.get('sequence')}",
                        **common,
                    )
                )
            if build.get("is_pingpong_abnormal"):
                rows.append(
                    MeshAnomalyDTO(
                        anomaly_id=f"pingpong:{build.get('sequence')}",
                        severity="warning",
                        anomaly_type="pingpong",
                        description=str(build.get("pingpong_judgment_reason") or "乒乓切换"),
                        evidence_reference=f"group:{build.get('pingpong_group_id')}",
                        **common,
                    )
                )
        if anomaly_type:
            rows = [row for row in rows if row.anomaly_type == anomaly_type]
        current, size = self._page(page, page_size)
        start = (current - 1) * size
        return MeshAnomalyPageDTO(items=rows[start : start + size], total=len(rows), page=current, page_size=size)

    def list_ap_statistics(
        self,
        site_id: str,
        session_id: str,
        *,
        query: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> MeshApStatisticsPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshApStatisticsPageDTO(page=page, page_size=page_size)
        with closing(self._connect_readonly(context.detail_db)) as conn:
            grouped = conn.execute(
                """
                SELECT COALESCE(NULLIF(peer_ap_mac, ''), peer_mac_normalized, peer_mac_raw) AS ap_mac,
                       MAX(peer_ap_name) AS ap_name, MAX(peer_site) AS peer_site,
                       AVG(local_rssi_db) AS avg_rssi, MIN(local_rssi_db) AS min_rssi
                FROM mesh_links
                GROUP BY COALESCE(NULLIF(peer_ap_mac, ''), peer_mac_normalized, peer_mac_raw)
                ORDER BY ap_name, ap_mac
                """
            ).fetchall()
            switches = [dict(row) for row in conn.execute("SELECT from_peer_mac, to_peer_mac FROM switch_events WHERE event_type = 'ACTIVE_SWITCH'")]
            anomalies = [str(row[0] or "") for row in conn.execute("SELECT related_peer_mac FROM diagnosis_events WHERE COALESCE(related_peer_mac, '') != ''")]
            segment_peers = [str(row[0] or "") for row in conn.execute("SELECT peer_mac_normalized FROM active_segments")]
            peer_to_ap = {
                self._mac_key(row["peer_mac_normalized"]): self._mac_key(row["peer_ap_mac"] or row["peer_mac_normalized"])
                for row in conn.execute(
                    """
                    SELECT peer_mac_normalized, MAX(peer_ap_mac) AS peer_ap_mac
                    FROM mesh_links WHERE COALESCE(peer_mac_normalized, '') != '' GROUP BY peer_mac_normalized
                    """
                )
            }
        switch_in: dict[str, int] = {}
        switch_out: dict[str, int] = {}
        for row in switches:
            source_key = self._mac_key(row.get("from_peer_mac"))
            target_key = self._mac_key(row.get("to_peer_mac"))
            source = peer_to_ap.get(source_key, source_key)
            target = peer_to_ap.get(target_key, target_key)
            switch_out[source] = switch_out.get(source, 0) + 1
            switch_in[target] = switch_in.get(target, 0) + 1
        anomaly_counts: dict[str, int] = {}
        for value in anomalies:
            peer_key = self._mac_key(value)
            key = peer_to_ap.get(peer_key, peer_key)
            anomaly_counts[key] = anomaly_counts.get(key, 0) + 1
        build_counts: dict[str, int] = {}
        for value in segment_peers:
            peer_key = self._mac_key(value)
            key = peer_to_ap.get(peer_key, peer_key)
            build_counts[key] = build_counts.get(key, 0) + 1
        ap_map = self._ap_map(site_id)
        items: list[MeshApStatisticsDTO] = []
        for row in grouped:
            data = dict(row)
            location = self._locate_ap(ap_map, {"peer_ap_mac": data.get("ap_mac"), "peer_ap_name": data.get("ap_name"), "peer_site": data.get("peer_site")})
            key = self._mac_key(data.get("ap_mac"))
            item = MeshApStatisticsDTO(
                peer_ap_name=str(data.get("ap_name") or location.name or "") or None,
                peer_ap_mac=str(data.get("ap_mac") or location.mac or "") or None,
                station=location.station or str(data.get("peer_site") or "") or None,
                section=location.section or None,
                mileage=location.mileage or None,
                line_side=location.line_side or None,
                link_up_count=build_counts.get(key, 0),
                link_down_count=switch_out.get(key, 0),
                switch_in_count=switch_in.get(key, 0),
                switch_out_count=switch_out.get(key, 0),
                avg_rssi=self._number(data.get("avg_rssi")),
                min_rssi=self._number(data.get("min_rssi")),
                anomaly_count=anomaly_counts.get(key, 0),
                match_status="matched" if location.name else "unresolved",
            )
            if not query or query.casefold() in f"{item.peer_ap_name} {item.peer_ap_mac} {item.station} {item.section}".casefold():
                items.append(item)
        current, size = self._page(page, page_size)
        start = (current - 1) * size
        return MeshApStatisticsPageDTO(items=items[start : start + size], total=len(items), page=current, page_size=size)

    def get_alignment(self, site_id: str, session_id: str, *, max_points: int = 1_000) -> MeshAlignmentDTO:
        context = self._context(site_id, session_id)
        associated = self._associated_online_session(context)
        if associated is None:
            return MeshAlignmentDTO(message="没有与该离线来源时间重叠的 Online MR 结构化会话。")
        try:
            series = self.online_mr_query.query_metrics(
                site_id,
                associated.session_id,
                [OnlineMrMetricType.PING_RTT, OnlineMrMetricType.PING_LOSS, OnlineMrMetricType.IPERF_BITRATE],
                start_time=str(context.source.get("first_sample_time") or "") or None,
                end_time=str(context.source.get("last_sample_time") or "") or None,
                limit=min(max(int(max_points), 10), 2_000),
                downsample=OnlineMrDownsampleMode.LATEST_PER_BUCKET,
                bucket_seconds=1,
            )
        except (OnlineMrQueryError, OSError, ValueError, sqlite3.Error):
            return MeshAlignmentDTO(associated_online_mr_session_id=associated.session_id, message="关联会话存在，但结构化流量指标不可读取。")
        buckets: dict[str, dict[str, Any]] = {}
        for item in series:
            for point in item.points:
                if not point.timestamp:
                    continue
                key = point.timestamp[:19]
                bucket = buckets.setdefault(key, {"timestamp": point.timestamp})
                if item.metric_type == OnlineMrMetricType.PING_RTT:
                    bucket["fping_rtt_ms"] = point.value
                elif item.metric_type == OnlineMrMetricType.PING_LOSS:
                    bucket["fping_loss_percent"] = point.value
                elif item.metric_type == OnlineMrMetricType.IPERF_BITRATE:
                    bucket["iperf_mbps"] = point.value
        if context.detail_db is not None and buckets:
            first, last = min(buckets), max(buckets)
            with closing(self._connect_readonly(context.detail_db)) as conn:
                rows = conn.execute(
                    """
                    SELECT sample_time, peer_ap_name, peer_mac_normalized, local_rssi_db, peer_site
                    FROM active_points WHERE sample_time >= ? AND sample_time <= ?
                    ORDER BY sample_time LIMIT 5000
                    """,
                    (first, last + "\uffff"),
                ).fetchall()
            for row in rows:
                key = str(row["sample_time"])[:19]
                if key in buckets:
                    buckets[key].update(
                        peer_ap_name=str(row["peer_ap_name"] or "") or None,
                        peer_ap_mac=str(row["peer_mac_normalized"] or "") or None,
                        rssi=self._number(row["local_rssi_db"]),
                        station=str(row["peer_site"] or "") or None,
                    )
        return MeshAlignmentDTO(
            associated_online_mr_session_id=associated.session_id,
            transient=True,
            items=[MeshAlignmentPointDTO(**buckets[key]) for key in sorted(buckets)],
            message="只读对齐结果，不保存为正式分析结果。",
        )

    def list_report_artifacts(self, site_id: str, session_id: str) -> list[MeshReportArtifactDTO]:
        return [item.dto for item in self._artifact_candidates(self._context(site_id, session_id))]

    def open_artifact(self, site_id: str, session_id: str, artifact_id: str) -> tuple[Path, str]:
        for candidate in self._artifact_candidates(self._context(site_id, session_id)):
            if candidate.dto.artifact_id == artifact_id:
                return candidate.path, candidate.dto.name
        raise MeshAnalysisQueryError("文件不存在或不属于当前分析会话")

    def get_raw_source_summary(self, site_id: str, session_id: str) -> list[MeshDataSourceDTO]:
        context = self._context(site_id, session_id)
        if context.raw_path is None:
            return [
                MeshDataSourceDTO(
                    source_id=self._artifact_id(session_id, "raw", str(context.source.get("archived_filename") or "missing")),
                    source_type="raw_mesh_log",
                    name=str(context.source.get("original_filename") or context.source.get("archived_filename") or "原始日志"),
                )
            ]
        path = context.raw_path
        stat = path.stat()
        return [
            MeshDataSourceDTO(
                source_id=self._artifact_id(session_id, "raw", path.name),
                source_type="raw_mesh_log",
                name=str(context.source.get("original_filename") or path.name),
                exists=True,
                size_bytes=stat.st_size,
                modified_at=self._mtime(stat.st_mtime),
                compressed=path.suffix.lower() == ".gz",
                tail_available=path.suffix.lower() != ".gz",
            )
        ]

    def read_raw_tail(self, site_id: str, session_id: str, source_id: str, *, lines: int = 100) -> MeshRawTailDTO:
        context = self._context(site_id, session_id)
        if context.raw_path is None or source_id != self._artifact_id(session_id, "raw", context.raw_path.name):
            raise MeshAnalysisQueryError("原始来源不存在")
        if context.raw_path.suffix.lower() == ".gz":
            return MeshRawTailDTO(source_id=source_id, message="压缩原始日志只展示 metadata，不在线解压 tail。")
        limit = min(max(int(lines), 1), 200)
        with context.raw_path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - 256 * 1024))
            raw = handle.read()
        text = self._decode_text(raw)
        return MeshRawTailDTO(source_id=source_id, available=True, lines=text.splitlines()[-limit:])

    def _session_rows(self, site_id: str) -> list[_SessionContext]:
        catalog = self.paths.mesh_catalog_path(site_id)
        if not catalog.is_file():
            return []
        with closing(self._connect_readonly(catalog)) as conn:
            profiles = [dict(row) for row in conn.execute("SELECT * FROM mr_profiles ORDER BY display_name")]
        contexts: list[_SessionContext] = []
        for profile in profiles:
            mr_root = self._validated_mr_root(site_id, str(profile["safe_folder_name"]))
            index_db = mr_root / "mesh.sqlite"
            if not index_db.is_file():
                continue
            with closing(self._connect_readonly(index_db)) as conn:
                if not self._table_exists(conn, "source_files"):
                    continue
                sources = [dict(row) for row in conn.execute("SELECT * FROM source_files WHERE COALESCE(parsed_deleted_at, '') = '' ORDER BY id")]
            contexts.extend(self._context_from_rows(site_id, profile, source, index_db) for source in sources)
        return contexts

    def _context(self, site_id: str, session_id: str) -> _SessionContext:
        match = _SESSION_ID_RE.fullmatch(session_id)
        if not match:
            raise MeshAnalysisQueryError("分析会话标识无效")
        catalog = self.paths.mesh_catalog_path(site_id)
        if not catalog.is_file():
            raise MeshAnalysisQueryError("分析会话不存在")
        with closing(self._connect_readonly(catalog)) as conn:
            profile_row = conn.execute("SELECT * FROM mr_profiles WHERE mr_id = ?", (match.group("mr_id"),)).fetchone()
        if profile_row is None:
            raise MeshAnalysisQueryError("分析会话不存在")
        profile = dict(profile_row)
        index_db = self._validated_mr_root(site_id, str(profile["safe_folder_name"])) / "mesh.sqlite"
        if not index_db.is_file():
            raise MeshAnalysisQueryError("分析会话不存在")
        with closing(self._connect_readonly(index_db)) as conn:
            source_row = conn.execute("SELECT * FROM source_files WHERE id = ?", (int(match.group("source_id")),)).fetchone()
        if source_row is None:
            raise MeshAnalysisQueryError("分析会话不存在")
        return self._context_from_rows(site_id, profile, dict(source_row), index_db)

    def _context_from_rows(self, site_id: str, profile: dict[str, Any], source: dict[str, Any], index_db: Path) -> _SessionContext:
        mr_name = str(profile["display_name"])
        safe_name = str(profile["safe_folder_name"])
        mr_root = self._validated_mr_root(site_id, safe_name)
        parsed_root = self.paths.mesh_mr_parsed_dir(site_id, safe_name).resolve()
        recorded = Path(str(source.get("parsed_db_path") or "").strip().strip("'\"")) if source.get("parsed_db_path") else None
        detail: Path | None = None
        relocated = False
        if recorded is not None and recorded.is_file() and self._within(recorded, parsed_root):
            detail = recorded.resolve()
        elif recorded is not None and recorded.name:
            fallback = (parsed_root / recorded.name).resolve()
            if fallback.is_file() and self._within(fallback, parsed_root):
                detail = fallback
                relocated = True
        raw_root = self.paths.mesh_mr_raw_dir(site_id, safe_name).resolve()
        raw_path: Path | None = None
        for value in (source.get("archived_path"), source.get("archived_filename"), source.get("original_filename")):
            if not value:
                continue
            candidate = Path(str(value))
            if not candidate.is_file() or not self._within(candidate, raw_root):
                candidate = raw_root / candidate.name
            if candidate.is_file() and self._within(candidate, raw_root):
                raw_path = candidate.resolve()
                break
        return _SessionContext(
            site_id=site_id,
            session_id=f"{profile['mr_id']}:{source['id']}",
            mr_id=str(profile["mr_id"]),
            mr_name=mr_name,
            safe_folder_name=safe_name,
            linked_device_id=profile.get("linked_device_id"),
            source_id=int(source["id"]),
            source=source,
            mr_root=mr_root.resolve(),
            index_db=index_db.resolve(),
            detail_db=detail,
            raw_path=raw_path,
            relocated_detail=relocated,
        )

    def _session_dto(self, context: _SessionContext) -> MeshAnalysisSessionDTO:
        stats = self._stats(context)
        train_name, role = self._mr_identity(context.mr_name)
        associated = self._associated_online_session(context)
        return MeshAnalysisSessionDTO(
            session_id=context.session_id,
            site_id=context.site_id,
            analysis_time=str(context.source.get("imported_at") or "") or None,
            train_name=train_name,
            mr_name=context.mr_name,
            mr_role=role,
            original_filename=str(context.source.get("original_filename") or context.source.get("archived_filename") or ""),
            link_record_count=stats["links"],
            active_link_count=stats["active"],
            standby_link_count=stats["standby"],
            event_count=stats["events"],
            data_integrity="complete" if context.detail_db and stats["warnings"] == 0 else "partial",
            analysis_status=str(context.source.get("parse_status") or "unknown"),
            warning_count=stats["warnings"],
            associated_online_mr_session_id=associated.session_id if associated else None,
            task_id=associated.controller_task_id if associated else None,
            report_count=len([item for item in self._artifact_candidates(context) if item.dto.artifact_type != "raw_mesh_log"]),
            first_sample_time=str(context.source.get("first_sample_time") or "") or None,
            last_sample_time=str(context.source.get("last_sample_time") or "") or None,
        )

    def _stats(self, context: _SessionContext) -> dict[str, int]:
        empty = {key: 0 for key in ("links", "active", "standby", "events", "link_up", "link_down", "switches", "short", "pingpong", "rssi_anomalies", "busy_anomalies", "unmatched", "warnings")}
        if context.detail_db is None:
            empty["warnings"] = 1
            return empty
        with closing(self._connect_readonly(context.detail_db)) as conn:
            link = conn.execute(
                """
                SELECT COUNT(*) AS links,
                       SUM(CASE WHEN link_state = 'ACTIVE' THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN link_state = 'STANDBY' THEN 1 ELSE 0 END) AS standby,
                       COUNT(DISTINCT CASE WHEN COALESCE(peer_ap_name, '') = '' THEN COALESCE(peer_mac_normalized, peer_mac_raw) END) AS unmatched
                FROM mesh_links
                """
            ).fetchone()
            events = conn.execute(
                """
                SELECT COUNT(*) AS events,
                       SUM(CASE WHEN event_type IN ('LINK_UP', 'ACTIVE_UP') THEN 1 ELSE 0 END) AS link_up,
                       SUM(CASE WHEN event_type IN ('LINK_DOWN', 'NO_ACTIVE') THEN 1 ELSE 0 END) AS link_down,
                       SUM(CASE WHEN event_type = 'ACTIVE_SWITCH' THEN 1 ELSE 0 END) AS switches
                FROM switch_events
                """
            ).fetchone()
            segment_count = int(conn.execute("SELECT COUNT(*) FROM active_segments").fetchone()[0] or 0)
            issues = int(conn.execute("SELECT COUNT(*) FROM parse_issues").fetchone()[0] or 0)
            diagnoses = conn.execute(
                """
                SELECT SUM(CASE WHEN LOWER(category) LIKE '%rssi%' THEN 1 ELSE 0 END) AS rssi_anomalies,
                       SUM(CASE WHEN LOWER(category) LIKE '%busy%' THEN 1 ELSE 0 END) AS busy_anomalies
                FROM diagnosis_events
                """
            ).fetchone()
        builds = self._build_rows(context)
        result = dict(empty)
        result.update({key: int(link[key] or 0) for key in ("links", "active", "standby", "unmatched")})
        result.update({key: int(events[key] or 0) for key in ("events", "link_up", "link_down", "switches")})
        result["link_up"] = segment_count
        result["link_down"] = result["switches"]
        result["short"] = sum(row.get("build_result") == "short" for row in builds)
        result["pingpong"] = sum(bool(row.get("is_pingpong_abnormal")) for row in builds)
        result["rssi_anomalies"] = int(diagnoses["rssi_anomalies"] or 0) if diagnoses else 0
        result["busy_anomalies"] = int(diagnoses["busy_anomalies"] or 0) if diagnoses else 0
        result["warnings"] = issues + result["unmatched"] + int(context.raw_path is None)
        return result

    def _build_rows(self, context: _SessionContext) -> list[dict[str, Any]]:
        if context.detail_db is None:
            return []
        stat = context.detail_db.stat()
        params = str(context.source.get("analysis_params_json") or "")
        return [dict(row) for row in self._build_rows_cached(str(context.detail_db), stat.st_mtime_ns, stat.st_size, params)]

    @lru_cache(maxsize=16)
    def _build_rows_cached(self, path: str, _mtime_ns: int, _size: int, analysis_params_json: str) -> tuple[dict[str, Any], ...]:
        with closing(self._connect_readonly(Path(path))) as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT ap.id, ap.link_id, ap.source_file_id, ap.radio, ap.sample_time,
                           ap.peer_mac_raw, ap.peer_mac_normalized, ap.peer_mac,
                           ap.peer_ap_name, ap.peer_site, ap.peer_radio, ap.peer_radio_label,
                           ml.peer_ap_mac, ml.peer_radio_mac,
                           ap.duration_text, ap.duration_seconds,
                           ap.local_rssi_db, ap.peer_rssi_db,
                           ap.local_tx_busy, ap.peer_tx_busy, ap.local_rx_busy, ap.peer_rx_busy,
                           sf.archived_filename AS source_file,
                           COALESCE(NULLIF(?, ''), sf.analysis_params_json) AS analysis_params_json
                    FROM active_points ap
                    LEFT JOIN source_files sf ON sf.id = ap.source_file_id
                    LEFT JOIN mesh_links ml ON ml.id = ap.link_id
                    ORDER BY ap.source_file_id, ap.radio, ap.sample_time, ap.id
                    """,
                    (analysis_params_json,),
                )
            ]
        return tuple(_active_build_order_rows_from_points(rows))

    def _associated_online_session(self, context: _SessionContext):
        first = self._parse_time(context.source.get("first_sample_time"))
        last = self._parse_time(context.source.get("last_sample_time"))
        if first is None or last is None:
            return None
        for row in self.online_mr_query.list_sessions(context.site_id, mr_name=context.mr_name, limit=500):
            started = self._parse_time(row.started_at)
            if started and first <= started <= last:
                return row
        return None

    def _artifact_candidates(self, context: _SessionContext) -> list[_ArtifactCandidate]:
        rows: list[tuple[str, Path]] = []
        if context.raw_path is not None:
            rows.append(("raw_mesh_log", context.raw_path))
        output_root = self.paths.mesh_mr_export_dir(context.site_id, context.safe_folder_name).resolve()
        if output_root.is_dir():
            for path in output_root.iterdir():
                if path.is_file() and not path.is_symlink() and path.suffix.lower() in _ALLOWED_OUTPUT_SUFFIXES and self._within(path, output_root):
                    rows.append(("analysis_report" if path.suffix.lower() == ".xlsx" else "package", path.resolve()))
        result: list[_ArtifactCandidate] = []
        for kind, path in rows:
            stat = path.stat()
            relative = path.relative_to(context.mr_root).as_posix()
            dto = MeshReportArtifactDTO(
                artifact_id=self._artifact_id(context.session_id, kind, relative),
                artifact_type=kind,
                name=path.name,
                size_bytes=stat.st_size,
                modified_at=self._mtime(stat.st_mtime),
            )
            result.append(_ArtifactCandidate(dto=dto, path=path))
        return sorted(result, key=lambda item: (item.dto.artifact_type, item.dto.name))

    def _ap_map(self, site_id: str) -> dict[str, _ApLocation]:
        result: dict[str, _ApLocation] = {}
        try:
            first = self.base_query.list_aps(site_id, page=1, page_size=500)
            items = list(first.items)
            page = 2
            while len(items) < first.total:
                part = self.base_query.list_aps(site_id, page=page, page_size=500)
                if not part.items:
                    break
                items.extend(part.items)
                page += 1
        except (OSError, ValueError, sqlite3.Error):
            return result
        for item in items:
            mileage = getattr(getattr(item, "mileage", None), "raw", "")
            location = _ApLocation(
                name=str(item.name or ""),
                mac=str(item.mac or ""),
                station=str(item.station or ""),
                section=str(item.section or ""),
                mileage=str(mileage or ""),
                line_side=str(item.line_side or ""),
            )
            mac_key = self._mac_key(item.mac)
            if mac_key:
                result[f"mac:{mac_key}"] = location
            if item.name:
                result[f"name:{str(item.name).casefold()}"] = location
        return result

    def _locate_ap(self, ap_map: dict[str, _ApLocation], row: dict[str, Any]) -> _ApLocation:
        mac = self._mac_key(row.get("peer_ap_mac") or row.get("peer_mac_normalized") or row.get("peer_mac") or row.get("ap_mac"))
        name = str(row.get("peer_ap_name") or row.get("ap_name") or "")
        location = ap_map.get(f"mac:{mac}") if mac else None
        if location is None and name:
            location = ap_map.get(f"name:{name.casefold()}")
        if location is not None:
            return location
        return _ApLocation(name=name, mac=mac, station=str(row.get("peer_site") or ""))

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    @staticmethod
    def _page(page: int, page_size: int) -> tuple[int, int]:
        return max(int(page), 1), min(max(int(page_size), 1), _MAX_PAGE_SIZE)

    @staticmethod
    def _mr_identity(value: str) -> tuple[str, str]:
        match = _MR_IDENTITY_RE.match(value.strip())
        return (match.group("train"), match.group("role").upper()) if match else ("", "")

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _milliseconds(cls, value: Any) -> int | None:
        number = cls._number(value)
        return int(round(number * 1_000)) if number is not None else None

    @staticmethod
    def _mac_key(value: Any) -> str:
        return "".join(character for character in str(value or "").lower() if character in "0123456789abcdef")

    @staticmethod
    def _artifact_id(session_id: str, kind: str, relative: str) -> str:
        return hashlib.sha256(f"{session_id}|{kind}|{relative}".encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _validated_mr_root(self, site_id: str, safe_name: str) -> Path:
        mesh_root = self.paths.mesh_catalog_path(site_id).parent.resolve()
        candidate = self.paths.mesh_mr_root(site_id, safe_name).resolve()
        if candidate == mesh_root or not self._within(candidate, mesh_root):
            raise MeshAnalysisQueryError("MR 数据目录标识无效")
        return candidate

    @staticmethod
    def _mtime(value: float) -> str:
        return datetime.fromtimestamp(value).isoformat(sep=" ", timespec="seconds")

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value)) if value else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _time_clauses(start_column: str, end_column: str, time_from: str, time_to: str) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if time_from:
            clauses.append(f"{end_column} >= ?")
            values.append(time_from)
        if time_to:
            clauses.append(f"{start_column} <= ?")
            values.append(time_to)
        return clauses, values

    @staticmethod
    def _decode_text(raw: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


__all__ = ["MeshAnalysisQueryError", "MeshAnalysisQueryService"]
