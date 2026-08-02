from __future__ import annotations

import hashlib
import gzip
import json
import logging
import math
import re
import sqlite3
from bisect import bisect_right
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.mesh_analysis import (
    MeshAnalysisSessionDTO,
    MeshAnalysisSessionDetailDTO,
    MeshAnalysisSessionPageDTO,
    MeshAnalysisParamsDTO,
    MeshAnalysisSummaryDTO,
    MeshAnalysisWarningDTO,
    MeshActiveBuildOrderDTO,
    MeshActiveBuildOrderPageDTO,
    MeshAnomalyDTO,
    MeshAnomalyPageDTO,
    MeshApStatisticsDTO,
    MeshApStatisticsPageDTO,
    MeshChannelBusyDTO,
    MeshChannelBusyPageDTO,
    MeshChartBackupLinkDTO,
    MeshChartEventDTO,
    MeshChartLocationSegmentDTO,
    MeshChartPointDTO,
    MeshCounterDeltaPageDTO,
    MeshCounterDeltaPointDTO,
    MeshDataSourceDTO,
    MeshLinkDetailDTO,
    MeshLinkPageDTO,
    MeshProfileDTO,
    MeshLinkTimelineDTO,
    MeshPathChartDTO,
    MeshPathChartSummaryDTO,
    MeshRawTailDTO,
    MeshRatePageDTO,
    MeshRatePointDTO,
    MeshReportArtifactDTO,
    MeshRssiDTO,
    MeshRssiPointDTO,
    MeshRssiStatisticsDTO,
    MeshSwitchEventDTO,
    MeshSwitchEventPageDTO,
    MeshTracksideSignalChartDTO,
    MeshTracksideSignalPointDTO,
    MeshTracksideSignalRangeDTO,
    MeshTracksideSignalSeriesDTO,
    MeshTimelineDTO,
)
from netconsole.models.mesh_analysis_params import mesh_analysis_params_from_json, mesh_analysis_params_to_json
from netconsole.models.mesh_log_models import LINK_STATE_ACTIVE, LINK_STATE_STANDBY
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, MeshSchemaRebuildRequired, SCHEMA_VERSION
from netconsole.services.mesh_analysis_params_service import load_site_mesh_analysis_params
from netconsole.services.mesh_chart_payload import build_chart_payload, render_indices
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.mesh_ap_location_service import (
    MeshApLocation,
    MeshApLocationService,
    MeshApLocationSnapshot,
)
from netconsole.services.mesh_source_locator import MeshSourceLocator


_SESSION_ID_RE = re.compile(r"^(?P<mr_id>[0-9a-fA-F-]{8,64}):(?P<source_id>[1-9][0-9]*)$")
_MR_IDENTITY_RE = re.compile(r"^(?P<train>.+?)[-_ ]*MR[-_ ]*(?P<role>CT|TC|CW)$", re.IGNORECASE)
_ALLOWED_OUTPUT_SUFFIXES = {".xlsx", ".zip", ".csv", ".json", ".md"}
_MAX_PAGE_SIZE = 1_000
_MAX_CHART_RENDER_POINTS = 2_000
LOGGER = logging.getLogger(__name__)
_DETAIL_CAPABILITY_TABLES = {
    "links": frozenset({"mesh_links"}),
    "timeline": frozenset({"active_segments"}),
    "switches": frozenset({"switch_events"}),
    "diagnosis": frozenset({"diagnosis_events"}),
    "parse_issues": frozenset({"parse_issues"}),
    "active_points": frozenset({"active_points"}),
}


class MeshAnalysisQueryError(RuntimeError):
    pass


class MeshAnalysisTimeRangeError(ValueError):
    pass


@dataclass(frozen=True)
class _SessionContext:
    site_id: str
    session_id: str
    mr_id: str
    mr_name: str
    safe_folder_name: str
    linked_device_id: int | None
    source_id: int
    detail_source_id: int
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
    manifest_path: Path | None = None


@dataclass(frozen=True)
class _BoundReportArtifact:
    artifact_id: str
    artifact_type: str
    display_name: str
    path: Path
    manifest_path: Path
    completed: bool


class MeshAnalysisQueryService:
    """只读展示既有 Mesh 分析结果；不初始化 schema，也不触发解析或报告。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        base_query: RailTransitBaseDataQueryService | None = None,
        schedule_catalog_index: bool = True,
    ) -> None:
        self.paths = paths
        self.base_query = base_query or RailTransitBaseDataQueryService(paths)
        self.location_service = MeshApLocationService(self.base_query)
        self.schedule_catalog_index = schedule_catalog_index

    def current_site_id(self) -> str:
        try:
            return str(SiteManager(self.paths).get_current_site() or "demo")
        except (OSError, ValueError, KeyError):
            return "demo"

    def list_profiles(self, site_id: str) -> list[MeshProfileDTO]:
        catalog = self.paths.mesh_catalog_path(site_id)
        if not catalog.is_file():
            return []
        with closing(self._connect_readonly(catalog)) as conn:
            columns = self._table_columns(conn, "mr_profiles")
            rows = conn.execute("SELECT * FROM mr_profiles ORDER BY display_name COLLATE NOCASE").fetchall()
        return [
            MeshProfileDTO(
                mr_id=str(row["mr_id"]),
                display_name=str(row["display_name"]),
                safe_folder_name=str(row["safe_folder_name"]),
                linked_device_id=row["linked_device_id"],
                linked_device_uuid=str(row["linked_device_uuid"] or "") if "linked_device_uuid" in columns else None,
                source_file_count=int(row["source_file_count"] or 0),
                sample_count=int(row["sample_count"] or 0),
                link_record_count=int(row["link_record_count"] or 0),
                session_count=int(row["session_count"] or 0),
                event_count=int(row["event_count"] or 0),
                notes=str(row["notes"] or ""),
            )
            for row in rows
        ]

    def get_summary(self, site_id: str) -> MeshAnalysisSummaryDTO:
        catalog = self.paths.mesh_catalog_path(site_id)
        if not catalog.is_file():
            return MeshAnalysisSummaryDTO(site_id=site_id)
        self._schedule_catalog_backfill(site_id)
        try:
            with closing(self._connect_readonly(catalog)) as conn:
                if not self._table_exists(conn, "mesh_session_index"):
                    return MeshAnalysisSummaryDTO(site_id=site_id)
                state = self._catalog_index_state(conn)
                valid_session_ids = self._valid_catalog_session_ids(conn, site_id)
                storage_clause = ""
                if valid_session_ids is not None:
                    conn.create_function(
                        "mesh_storage_available",
                        1,
                        lambda value: int(str(value or "") in valid_session_ids),
                        deterministic=True,
                    )
                    storage_clause = "WHERE mesh_storage_available(session_id) = 1"
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) AS session_count,
                           COUNT(DISTINCT NULLIF(train_name, '')) AS train_count,
                           COUNT(DISTINCT mr_id) AS mr_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(link_record_count) END
                               AS link_record_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(active_link_count) END
                               AS active_link_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(standby_link_count) END
                               AS standby_link_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(link_up_event_count) END
                               AS link_up_event_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(link_down_event_count) END
                               AS link_down_event_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(switch_event_count) END
                               AS switch_event_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(short_link_count) END
                               AS short_link_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(pingpong_count) END
                               AS pingpong_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(rssi_anomaly_count) END
                               AS rssi_anomaly_count,
                           CASE WHEN COUNT(*) = 0 THEN 0
                                ELSE SUM(channel_busy_anomaly_count) END
                               AS channel_busy_anomaly_count,
                           CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(unmatched_ap_count) END
                               AS unmatched_ap_count,
                           COALESCE(SUM(CASE WHEN warning_count > 0 THEN 1 ELSE 0 END), 0)
                               AS warning_session_count,
                           MAX(analysis_time) AS latest_analysis_time
                    FROM mesh_session_index
                    {storage_clause}
                    """,
                ).fetchone()
        except sqlite3.Error:
            LOGGER.warning("MESH 目录摘要读取失败", exc_info=True)
            return MeshAnalysisSummaryDTO(site_id=site_id, index_status="failed")
        values = dict(row) if row else {}
        return MeshAnalysisSummaryDTO(
            site_id=site_id,
            index_status=str(state.get("status") or "pending"),
            indexed_session_count=int(state.get("indexed_session_count") or 0),
            pending_session_count=max(
                0,
                int(state.get("discovered_session_count") or 0)
                - int(state.get("detail_indexed_session_count") or 0),
            ),
            index_updated_at=str(state.get("updated_at") or "") or None,
            **values,
        )

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
        current, size = self._page(page, page_size)
        catalog = self.paths.mesh_catalog_path(site_id)
        if not catalog.is_file():
            return MeshAnalysisSessionPageDTO(page=current, page_size=size)
        self._schedule_catalog_backfill(site_id)
        where: list[str] = []
        values: list[Any] = []
        for field, value in (
            ("train_name", train),
            ("mr_name", mr_name),
            ("mr_role", mr_role),
            ("source_type", source_type),
            ("analysis_status", analysis_status),
        ):
            if value:
                where.append(f"{field} LIKE ? ESCAPE '\\' COLLATE NOCASE")
                values.append(f"%{self._like_value(value)}%")
        if has_warning is not None:
            where.append("warning_count > 0" if has_warning else "warning_count = 0")
        if time_from:
            where.append("COALESCE(last_sample_time, analysis_time, '') >= ?")
            values.append(time_from)
        if time_to:
            where.append("COALESCE(first_sample_time, analysis_time, '') <= ?")
            values.append(time_to)
        if query:
            where.append(
                "(train_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR mr_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR original_filename LIKE ? ESCAPE '\\' COLLATE NOCASE)"
            )
            needle = f"%{self._like_value(query)}%"
            values.extend((needle, needle, needle))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sort_columns = {
            "analysis_time": "analysis_time",
            "mr_name": "mr_name COLLATE NOCASE",
            "link_record_count": "link_record_count",
        }
        sort_column = sort_columns.get(sort_by, sort_columns["analysis_time"])
        direction = "ASC" if sort_order == "asc" else "DESC"
        offset = (current - 1) * size
        try:
            with closing(self._connect_readonly(catalog)) as conn:
                if not self._table_exists(conn, "mesh_session_index"):
                    return MeshAnalysisSessionPageDTO(page=current, page_size=size)
                state = self._catalog_index_state(conn)
                valid_session_ids = self._valid_catalog_session_ids(conn, site_id)
                if valid_session_ids is not None:
                    conn.create_function(
                        "mesh_storage_available",
                        1,
                        lambda value: int(str(value or "") in valid_session_ids),
                        deterministic=True,
                    )
                    where.append("mesh_storage_available(session_id) = 1")
                clause = f"WHERE {' AND '.join(where)}" if where else ""
                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM mesh_session_index {clause}",
                        values,
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    f"""
                    SELECT * FROM mesh_session_index {clause}
                    ORDER BY {sort_column} {direction}, session_id {direction}
                    LIMIT ? OFFSET ?
                    """,
                    [*values, size, offset],
                ).fetchall()
        except sqlite3.Error:
            LOGGER.warning("MESH 会话目录读取失败", exc_info=True)
            return MeshAnalysisSessionPageDTO(
                page=current, page_size=size, index_status="failed"
            )
        return MeshAnalysisSessionPageDTO(
            items=[self._indexed_session_dto(dict(row), site_id) for row in rows],
            total=total,
            page=current,
            page_size=size,
            index_status=str(state.get("status") or "pending"),
            indexed_session_count=int(state.get("indexed_session_count") or 0),
            pending_session_count=max(
                0,
                int(state.get("discovered_session_count") or 0)
                - int(state.get("detail_indexed_session_count") or 0),
            ),
        )

    def _schedule_catalog_backfill(self, site_id: str) -> None:
        if not self.schedule_catalog_index:
            return
        from netconsole.core.runtime_environment import runtime_mode
        from netconsole.core.runtime_mode import RuntimeMode
        from netconsole.services.mesh_catalog_index_service import MeshCatalogIndexService

        index_service = MeshCatalogIndexService(self.paths)
        if runtime_mode() is RuntimeMode.TEST:
            index_service.rebuild_now(site_id)
        else:
            index_service.schedule(site_id)

    @classmethod
    def _indexed_session_dto(
        cls, row: dict[str, Any], site_id: str
    ) -> MeshAnalysisSessionDTO:
        return MeshAnalysisSessionDTO(
            **{
                field: row.get(field)
                for field in MeshAnalysisSessionDTO.model_fields
                if field in row
                and field not in {"site_id", "available_capabilities", "missing_capabilities"}
            },
            site_id=site_id,
            available_capabilities=cls._json_array(
                row.get("available_capabilities_json")
            ),
            missing_capabilities=cls._json_array(
                row.get("missing_capabilities_json")
            ),
        )

    @staticmethod
    def _catalog_index_state(conn: sqlite3.Connection) -> dict[str, Any]:
        if not MeshAnalysisQueryService._table_exists(
            conn, "mesh_catalog_index_state"
        ):
            return {}
        row = conn.execute(
            "SELECT * FROM mesh_catalog_index_state WHERE singleton = 1"
        ).fetchone()
        return dict(row) if row else {}

    def _valid_catalog_session_ids(
        self,
        conn: sqlite3.Connection,
        site_id: str,
    ) -> set[str] | None:
        """Return sessions whose registered storage is still usable."""

        if not self._table_exists(conn, "mr_profiles"):
            return None
        result: set[str] = set()
        for row in conn.execute("SELECT mr_id, safe_folder_name FROM mr_profiles"):
            mr_id = str(row["mr_id"] or "")
            try:
                safe_name = str(row["safe_folder_name"] or "")
                root = self._validated_mr_root(site_id, safe_name)
                index_db = root / "mesh.sqlite"
                if not index_db.is_file():
                    continue
                with closing(self._connect_readonly(index_db)) as index_conn:
                    if not self._table_exists(index_conn, "source_files"):
                        continue
                    columns = self._table_columns(index_conn, "source_files")
                    selected = ["id"]
                    selected.extend(
                        field
                        for field in (
                            "parsed_db_path",
                            "parsed_relative_path",
                            "parsed_deleted_at",
                        )
                        if field in columns
                    )
                    sources = [
                        dict(source)
                        for source in index_conn.execute(
                            f"SELECT {', '.join(selected)} FROM source_files"
                        )
                    ]
                for source in sources:
                    if self._registered_source_storage_available(
                        site_id,
                        safe_name,
                        source,
                    ):
                        result.add(f"{mr_id}:{int(source['id'])}")
            except (
                MeshAnalysisQueryError,
                OSError,
                sqlite3.Error,
                TypeError,
                ValueError,
            ):
                LOGGER.warning(
                    "跳过存储失效的 MESH MR 来源索引：site=%s mr_id=%s",
                    site_id,
                    mr_id,
                    exc_info=True,
                )
        return result

    def _registered_source_storage_available(
        self,
        site_id: str,
        safe_name: str,
        source: dict[str, Any],
    ) -> bool:
        if str(source.get("parsed_deleted_at") or "").strip():
            return True
        recorded_value = str(source.get("parsed_db_path") or "").strip().strip("'\"")
        relative_value = str(source.get("parsed_relative_path") or "").strip().strip("'\"")
        if not recorded_value and not relative_value:
            return True
        parsed_root = self.paths.mesh_mr_parsed_dir(site_id, safe_name).resolve()
        candidates: list[Path] = []
        if recorded_value:
            recorded = Path(recorded_value)
            candidates.append(recorded)
            if recorded.name:
                candidates.append(parsed_root / recorded.name)
        if relative_value:
            relative = Path(relative_value)
            candidates.append(parsed_root / relative.name)
        for candidate in dict.fromkeys(candidates):
            try:
                resolved = candidate.resolve()
                if self._within(resolved, parsed_root) and resolved.is_file():
                    return True
            except OSError:
                continue
        return False

    def _current_identity_revision(self, site_id: str) -> int:
        """Read the AP Identity index revision without mutating the site database."""
        path = Path(self.paths.site_db_path(site_id))
        if not path.is_file():
            return 0
        try:
            with closing(self._connect_readonly(path)) as conn:
                if not self._table_exists(conn, "ap_identity_index_state"):
                    return 0
                columns = self._table_columns(conn, "ap_identity_index_state")
                if "revision" not in columns:
                    return 0
                if "site_id" in columns:
                    row = conn.execute(
                        """
                        SELECT revision
                        FROM ap_identity_index_state
                        WHERE site_id IN (?, 'current')
                        ORDER BY CASE WHEN site_id = 'current' THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (str(site_id),),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT revision FROM ap_identity_index_state LIMIT 1"
                    ).fetchone()
            return max(0, self._int(row[0]) or 0) if row is not None else 0
        except (OSError, sqlite3.Error, TypeError, ValueError):
            LOGGER.debug("读取 AP Identity revision 失败：%s", site_id, exc_info=True)
            return 0

    def _identity_mapping_state(self, context: _SessionContext) -> dict[str, Any]:
        saved_revision = self._int(context.source.get("identity_index_revision")) or 0
        current_revision = self._current_identity_revision(context.site_id)
        status = str(context.source.get("identity_mapping_status") or "unknown").strip() or "unknown"
        if current_revision > 0 and saved_revision != current_revision:
            status = "identity_stale"
        return {
            "identity_index_revision": saved_revision,
            "identity_current_revision": current_revision,
            "identity_mapped_at": str(context.source.get("identity_mapped_at") or ""),
            "identity_mapping_status": status,
        }

    @staticmethod
    def _json_array(value: Any) -> list[str]:
        try:
            parsed = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @staticmethod
    def _like_value(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def get_analysis_session(self, site_id: str, session_id: str) -> MeshAnalysisSessionDetailDTO:
        context = self._context(site_id, session_id)
        stats = self._stats(context)
        identity_state = self._identity_mapping_state(context)
        warnings: list[MeshAnalysisWarningDTO] = []
        if stats["parsed_status"] == "missing":
            warnings.append(MeshAnalysisWarningDTO(code="parsed_result_missing", message="结构化分析结果不存在，Web 不会自动重解析。", severity="error"))
        elif stats["parsed_status"] == "unreadable":
            warnings.append(MeshAnalysisWarningDTO(code="parsed_result_unreadable", message=stats["parsed_message"], severity="error"))
        elif stats["parsed_status"] == "legacy":
            warnings.append(MeshAnalysisWarningDTO(code="parsed_result_legacy", message=stats["parsed_message"], severity="warning"))
        if context.raw_path is None:
            warnings.append(MeshAnalysisWarningDTO(code="raw_source_missing", message="原始 Mesh 日志当前不可用；既有结构化结果仍按只读方式展示。"))
        if context.relocated_detail:
            warnings.append(MeshAnalysisWarningDTO(code="parsed_path_relocated", message="索引中的旧数据根路径不可用，已只读使用当前 MR parsed 目录的同名结果。"))
        if int(context.source.get("issue_count") or 0):
            warnings.append(MeshAnalysisWarningDTO(code="parse_issues", message="该来源存在既有解析告警，请查看异常摘要。"))
        if identity_state["identity_mapping_status"] == "identity_stale":
            warnings.append(
                MeshAnalysisWarningDTO(
                    code="identity_mapping_stale",
                    message="AP 身份索引已更新；打开健康来源后将通过任务中心轻量刷新身份映射。",
                    severity="warning",
                )
            )
        return MeshAnalysisSessionDetailDTO(
            session=self._session_dto(context, stats),
            analysis_params=self._effective_analysis_params(context),
            available_radios=self._available_radios(context),
            warnings=warnings,
            sources=self.get_raw_source_summary(site_id, session_id),
        )

    def _available_radios(self, context: _SessionContext) -> list[int]:
        """Return the real Radio dimensions without depending on the visible build-order page."""
        if context.detail_db is None:
            return []
        try:
            with closing(self._connect_readonly(context.detail_db)) as conn:
                table = "active_points" if self._table_exists(conn, "active_points") else "mesh_links"
                if not self._table_exists(conn, table):
                    return []
                rows = conn.execute(
                    f"SELECT DISTINCT radio FROM {table} WHERE radio IS NOT NULL ORDER BY radio"
                ).fetchall()
            return [int(row[0]) for row in rows if row[0] is not None]
        except (OSError, sqlite3.Error, TypeError, ValueError):
            LOGGER.debug("读取 MESH Radio 维度失败：%s", context.session_id, exc_info=True)
            return []

    def _effective_analysis_params(self, context: _SessionContext) -> MeshAnalysisParamsDTO:
        source_params = str(context.source.get("analysis_params_json") or "").strip()
        try:
            params = (
                mesh_analysis_params_from_json(source_params)
                if source_params
                else load_site_mesh_analysis_params(self.paths, context.site_id)
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            params = mesh_analysis_params_from_json(None)
        return MeshAnalysisParamsDTO(**params.to_dict())

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
            ("ml.peer_ap_mac", self._mac_key(peer_ap_mac)),
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
                location_clause = f"({location_clause} OR LOWER(COALESCE(ml.peer_ap_mac, '')) IN ({placeholders}))"
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
            link_columns = self._table_columns(conn, "mesh_links")
            identity_select = ", ".join(
                (
                    f"ml.{column}"
                    if column in link_columns
                    else f"NULL AS {column}"
                )
                for column in (
                    "peer_match_confidence",
                    "peer_identity_status",
                    "peer_identity_source",
                    "peer_identity_reason",
                )
            )
            total = int(conn.execute(f"SELECT COUNT(*) FROM mesh_links ml {where}", values).fetchone()[0] or 0)
            rows = conn.execute(
                f"""
                SELECT ml.id, ml.sample_id, ml.source_file_id, ml.sample_time, s.timestamp_tag,
                       DENSE_RANK() OVER (
                           ORDER BY ml.source_file_id, ml.sample_time, s.timestamp_tag
                       ) - 1 AS sample_group_index,
                       ml.radio, ml.link_state, ml.peer_mac_raw, ml.peer_mac_normalized,
                       ml.peer_ap_name, ml.peer_ap_mac, ml.peer_site, ml.peer_radio_mac,
                       ml.peer_radio_label, ml.establish_time, ml.duration_text, ml.duration_seconds,
                       ml.link_count, ml.local_rssi_db, ml.peer_rssi_db,
                       ml.local_noise_dbm, ml.peer_noise_dbm, ml.local_signal_dbm, ml.peer_signal_dbm,
                       ml.local_rate_raw, ml.peer_rate_raw,
                       ml.local_tx_busy, ml.peer_tx_busy, ml.local_rx_busy, ml.peer_rx_busy,
                       ml.local_cpu_percent, ml.peer_cpu_percent, ml.local_mem_percent, ml.peer_mem_percent,
                       ml.local_tx_des_free_cnt, ml.peer_tx_des_free_cnt,
                       ml.local_tx, ml.peer_tx, ml.local_rx, ml.peer_rx,
                       ml.local_retry, ml.peer_retry, ml.local_err, ml.peer_err,
                       ml.local_tx_garp, ml.peer_rx_garp, ml.local_tx_mul_join, ml.peer_rx_mul_join,
                       ml.source_line_number, ml.record_seq, ml.raw_line_start, ml.raw_line_end,
                       ml.raw_offset_start, ml.raw_offset_end,
                       ml.peer_match_rule, ml.peer_resolve_source, {identity_select},
                       sf.archived_filename AS source_file,
                       (SELECT event_type FROM switch_events se
                        WHERE se.source_file_id = ml.source_file_id
                          AND se.radio = ml.radio
                          AND se.event_time = ml.sample_time
                        ORDER BY se.id LIMIT 1) AS event_type
                FROM mesh_links ml
                LEFT JOIN samples s ON s.id = ml.sample_id
                LEFT JOIN source_files sf ON sf.id = ml.source_file_id
                {where}
                ORDER BY {sort_column} {direction}, s.timestamp_tag {direction}, ml.record_seq {direction}, ml.id {direction}
                LIMIT ? OFFSET ?
                """,
                (*values, size, offset),
            ).fetchall()
        train_name, role = self._mr_identity(context.mr_name)
        items: list[MeshLinkDetailDTO] = []
        for row in rows:
            data = dict(row)
            location = self._locate_ap(ap_map, data)
            peer_name = self._resolved_ap_name(data, location)
            items.append(
                MeshLinkDetailDTO(
                    record_id=int(data["id"]),
                    timestamp=str(data["sample_time"]),
                    train_name=train_name,
                    mr_name=context.mr_name,
                    mr_role=role,
                    timestamp_tag=str(data.get("timestamp_tag") or ""),
                    sample_group_index=data.get("sample_group_index"),
                    local_radio=data.get("radio"),
                    peer_mac_raw=str(data.get("peer_mac_raw") or "") or None,
                    peer_mac=str(data.get("peer_mac_normalized") or data.get("peer_mac_raw") or "") or None,
                    peer_ap_name=peer_name,
                    peer_ap_mac=self._resolved_ap_mac(data, location),
                    peer_radio_mac=str(data.get("peer_radio_mac") or "") or None,
                    peer_radio=str(data.get("peer_radio_label") or "") or None,
                    link_role=str(data.get("link_state") or ""),
                    link_status=str(data.get("link_state") or ""),
                    rssi=self._number(data.get("local_rssi_db")),
                    peer_rssi=self._number(data.get("peer_rssi_db")),
                    local_noise=self._number(data.get("local_noise_dbm")),
                    peer_noise=self._number(data.get("peer_noise_dbm")),
                    local_signal=self._number(data.get("local_signal_dbm")),
                    peer_signal=self._number(data.get("peer_signal_dbm")),
                    local_rssi_db=self._number(data.get("local_rssi_db")),
                    peer_rssi_db=self._number(data.get("peer_rssi_db")),
                    local_noise_dbm=self._number(data.get("local_noise_dbm")),
                    peer_noise_dbm=self._number(data.get("peer_noise_dbm")),
                    local_signal_dbm=self._number(data.get("local_signal_dbm")),
                    peer_signal_dbm=self._number(data.get("peer_signal_dbm")),
                    local_rate_raw=self._number(data.get("local_rate_raw")),
                    peer_rate_raw=self._number(data.get("peer_rate_raw")),
                    local_tx_busy=self._number(data.get("local_tx_busy")),
                    peer_tx_busy=self._number(data.get("peer_tx_busy")),
                    local_rx_busy=self._number(data.get("local_rx_busy")),
                    peer_rx_busy=self._number(data.get("peer_rx_busy")),
                    establish_time=str(data.get("establish_time") or "") or None,
                    duration_text=str(data.get("duration_text") or "") or None,
                    duration_seconds=self._number(data.get("duration_seconds")),
                    link_count=data.get("link_count"),
                    station=self._resolved_location_value(data, location, "station"),
                    section=self._resolved_location_value(data, location, "section"),
                    mileage=self._resolved_location_value(data, location, "mileage"),
                    line_side=self._resolved_location_value(data, location, "line_side"),
                    event_type=str(data.get("event_type") or "") or None,
                    duration_ms=self._milliseconds(data.get("duration_seconds")),
                    source_file=str(data.get("source_file") or context.source.get("original_filename") or context.source.get("archived_filename") or ""),
                    source_record_index=data.get("record_seq"),
                    source_line_number=data.get("source_line_number"),
                    raw_line_start=data.get("raw_line_start"),
                    raw_line_end=data.get("raw_line_end"),
                    raw_offset_start=data.get("raw_offset_start"),
                    raw_offset_end=data.get("raw_offset_end"),
                    local_cpu_percent=self._number(data.get("local_cpu_percent")),
                    peer_cpu_percent=self._number(data.get("peer_cpu_percent")),
                    local_mem_percent=self._number(data.get("local_mem_percent")),
                    peer_mem_percent=self._number(data.get("peer_mem_percent")),
                    local_tx_des_free_cnt=data.get("local_tx_des_free_cnt"),
                    peer_tx_des_free_cnt=data.get("peer_tx_des_free_cnt"),
                    local_tx=data.get("local_tx"),
                    peer_tx=data.get("peer_tx"),
                    local_rx=data.get("local_rx"),
                    peer_rx=data.get("peer_rx"),
                    local_retry=data.get("local_retry"),
                    peer_retry=data.get("peer_retry"),
                    local_err=data.get("local_err"),
                    peer_err=data.get("peer_err"),
                    local_tx_garp=data.get("local_tx_garp"),
                    peer_rx_garp=data.get("peer_rx_garp"),
                    local_tx_mul_join=data.get("local_tx_mul_join"),
                    peer_rx_mul_join=data.get("peer_rx_mul_join"),
                    match_method=str(data.get("peer_match_rule") or data.get("peer_resolve_source") or "") or None,
                    **self._identity_payload(data, location),
                    warning=None if peer_name else "Peer AP 未匹配",
                )
            )
        return MeshLinkPageDTO(items=items, total=total, page=current, page_size=size)

    def list_active_build_order(
        self,
        site_id: str,
        session_id: str,
        *,
        radio: int | None = None,
        peer: str = "",
        station: str = "",
        build_result: str = "",
        pingpong_only: bool = False,
        time_from: str = "",
        time_to: str = "",
        page: int = 1,
        page_size: int = 100,
        sort_order: str = "desc",
    ) -> MeshActiveBuildOrderPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshActiveBuildOrderPageDTO(page=page, page_size=page_size)
        rows = self._build_rows(context)
        ap_map = self._ap_map(site_id)
        items: list[MeshActiveBuildOrderDTO] = []
        peer_needle = peer.casefold().strip()
        station_needle = station.casefold().strip()
        result_needle = build_result.casefold().strip()
        for row in rows:
            location = self._locate_ap(ap_map, row)
            peer_text = " ".join(
                str(row.get(key) or "")
                for key in ("active_peer_mac", "peer_ap_name", "peer_ap_mac", "peer_radio", "peer_radio_mac")
            ).casefold()
            resolved_station = self._resolved_location_value(row, location, "station") or ""
            start_time = str(row.get("build_start_time") or "")
            end_time = str(row.get("build_end_time") or "")
            if radio is not None and self._int(row.get("radio")) != int(radio):
                continue
            if peer_needle and peer_needle not in peer_text:
                continue
            if station_needle and station_needle not in f"{resolved_station} {location.section}".casefold():
                continue
            if result_needle and result_needle != str(row.get("build_result") or "").casefold():
                continue
            if pingpong_only and not bool(row.get("is_ap_return_event") or row.get("is_pingpong_abnormal")):
                continue
            if time_from and end_time < time_from:
                continue
            if time_to and start_time > time_to:
                continue
            items.append(
                MeshActiveBuildOrderDTO(
                    sequence=int(row.get("sequence") or 0),
                    source_file_id=context.source_id,
                    anchor_link_id=self._int(row.get("anchor_link_id")),
                    local_radio=self._int(row.get("radio")),
                    peer_mac_raw=str(row.get("peer_mac_raw") or ""),
                    active_peer_mac=str(row.get("active_peer_mac") or ""),
                    peer_ap_name=self._resolved_ap_name(row, location),
                    peer_ap_mac=self._resolved_ap_mac(row, location),
                    peer_radio=str(row.get("peer_radio") or "") or None,
                    peer_radio_mac=str(row.get("peer_radio_mac") or "") or None,
                    **self._identity_payload(row, location),
                    station=resolved_station or None,
                    section=self._resolved_location_value(row, location, "section"),
                    mileage=self._resolved_location_value(row, location, "mileage"),
                    line_side=self._resolved_location_value(row, location, "line_side"),
                    build_start_time=start_time,
                    build_end_time=end_time,
                    main_link_duration_seconds=self._number(row.get("main_link_duration_seconds")),
                    reported_duration_seconds=self._number(row.get("reported_duration_seconds")),
                    sample_count=int(row.get("sample_count") or 0),
                    avg_mr_rssi=self._number(row.get("avg_mr_rssi")),
                    min_mr_rssi=self._number(row.get("min_mr_rssi")),
                    max_mr_rssi=self._number(row.get("max_mr_rssi")),
                    p10_mr_rssi=self._number(row.get("p10_mr_rssi")),
                    avg_tx_busy=self._number(row.get("avg_tx_busy")),
                    avg_rx_busy=self._number(row.get("avg_rx_busy")),
                    avg_peer_tx_busy=self._number(row.get("avg_peer_tx_busy")),
                    avg_peer_rx_busy=self._number(row.get("avg_peer_rx_busy")),
                    link_time_window=self._int(row.get("link_time_window")),
                    link_switch_threshold=self._int(row.get("link_switch_threshold")),
                    link_hold_rssi=self._int(row.get("link_hold_rssi")),
                    link_establish_threshold=self._int(row.get("link_establish_threshold")),
                    link_establish_rssi=self._int(row.get("link_establish_rssi")),
                    link_establishment_accepted=bool(row.get("link_establishment_accepted")),
                    link_establishment_signal=self._number(row.get("link_establishment_signal")),
                    link_establishment_reason=str(row.get("link_establishment_reason") or ""),
                    main_link_switch_time_ms=self._int(row.get("main_link_switch_time_ms")),
                    short_link_tolerance_ms=self._int(row.get("short_link_tolerance_ms")),
                    pingpong_tolerance_ms=self._int(row.get("pingpong_tolerance_ms")),
                    pingpong_return_window_ms=self._int(row.get("pingpong_return_window_ms")),
                    short_threshold_seconds=self._number(row.get("short_threshold_seconds")),
                    min_normal_sample_count=self._int(row.get("min_normal_sample_count")),
                    build_result=str(row.get("build_result") or ""),
                    judge_reason=str(row.get("judge_reason") or ""),
                    is_same_physical_ap_radio_switch=bool(row.get("is_same_physical_ap_radio_switch")),
                    physical_ap_key=str(row.get("physical_ap_key") or ""),
                    is_ap_return_event=bool(row.get("is_ap_return_event")),
                    is_pingpong_abnormal=bool(row.get("is_pingpong_abnormal")),
                    pingpong_type=str(row.get("pingpong_type") or ""),
                    pingpong_group_id=str(row.get("pingpong_group_id") or ""),
                    pingpong_return_duration_ms=self._int(row.get("pingpong_return_duration_ms")),
                    middle_ap_dwell_ms=self._int(row.get("middle_ap_dwell_ms")),
                    previous_ap=str(row.get("previous_ap") or ""),
                    middle_ap=str(row.get("middle_ap") or ""),
                    return_ap=str(row.get("return_ap") or ""),
                    pingpong_judgment_reason=str(row.get("pingpong_judgment_reason") or ""),
                    source_file=str(row.get("source_file") or context.source.get("archived_filename") or ""),
                )
            )
        items.sort(
            key=lambda item: (item.build_start_time, item.sequence),
            reverse=sort_order.lower() != "asc",
        )
        current, size = self._page(page, page_size)
        start = (current - 1) * size
        return MeshActiveBuildOrderPageDTO(
            items=items[start : start + size],
            total=len(items),
            page=current,
            page_size=size,
        )

    def get_link_timeline(self, site_id: str, session_id: str, *, time_from: str = "", time_to: str = "", limit: int = 2_000) -> MeshTimelineDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshTimelineDTO()
        clauses, values = self._time_clauses("start_time", "end_time", time_from, time_to)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM active_segments {where}", values).fetchone()[0] or 0)
            rows = conn.execute(f"SELECT * FROM active_segments {where} ORDER BY start_time, id LIMIT ?", (*values, min(max(limit, 1), 5_000))).fetchall()
            link_columns = self._table_columns(conn, "mesh_links")
            optional_aggregates = ", ".join(
                (
                    f"MAX({column}) AS {column}"
                    if column in link_columns
                    else f"NULL AS {column}"
                )
                for column in (
                    "peer_match_confidence",
                    "peer_identity_status",
                    "peer_identity_source",
                    "peer_identity_reason",
                )
            )
            peer_rows = conn.execute(
                f"""
                SELECT peer_mac_normalized,
                       MAX(peer_ap_name) AS peer_ap_name,
                       MAX(peer_ap_mac) AS peer_ap_mac,
                       MAX(peer_site) AS peer_site,
                       MAX(peer_match_rule) AS peer_match_rule,
                       MAX(peer_resolve_source) AS peer_resolve_source,
                       {optional_aggregates}
                FROM mesh_links
                WHERE COALESCE(peer_mac_normalized, '') != ''
                GROUP BY peer_mac_normalized
                """
            ).fetchall()
        ap_map = self._ap_map(site_id)
        peer_map = {
            self._mac_key(row["peer_mac_normalized"]): dict(row)
            for row in peer_rows
        }
        items = []
        for row in rows:
            data = dict(row)
            mapped = peer_map.get(
                self._mac_key(
                    data.get("peer_mac_normalized") or data.get("peer_mac")
                ),
                {},
            )
            identity_data = {**data, **mapped}
            location = self._locate_ap(ap_map, identity_data)
            items.append(
                MeshLinkTimelineDTO(
                    segment_id=int(data["id"]),
                    start_time=str(data.get("start_time") or ""),
                    end_time=str(data.get("end_time") or ""),
                    duration_seconds=self._number(data.get("duration_sec")),
                    peer_ap_name=self._resolved_ap_name(identity_data, location),
                    peer_ap_mac=self._resolved_ap_mac(identity_data, location),
                    **self._identity_payload(identity_data, location),
                    local_radio=data.get("radio"),
                    rssi_min=self._number(data.get("min_rssi")),
                    rssi_avg=self._number(data.get("avg_rssi")),
                    rssi_max=self._number(data.get("max_rssi")),
                    station=self._resolved_location_value(identity_data, location, "station"),
                    section=self._resolved_location_value(identity_data, location, "section"),
                    mileage=self._resolved_location_value(identity_data, location, "mileage"),
                    line_side=self._resolved_location_value(identity_data, location, "line_side"),
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
            from_peer = peer_map.get(self._mac_key(data.get("from_peer_mac")), {})
            to_peer = peer_map.get(self._mac_key(data.get("to_peer_mac")), {})
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
            link_columns = self._table_columns(conn, "mesh_links")
            identity_select = ", ".join(
                (
                    f"(SELECT {column} FROM mesh_links ml WHERE ml.id = ap.link_id) AS {column}"
                    if column in link_columns
                    else f"NULL AS {column}"
                )
                for column in (
                    "peer_match_rule",
                    "peer_match_confidence",
                    "peer_resolve_source",
                    "peer_identity_status",
                    "peer_identity_source",
                    "peer_identity_reason",
                )
            )
            point_rows = conn.execute(
                f"""
                WITH ordered AS (
                    SELECT ap.sample_time, ap.local_rssi_db, ap.peer_ap_name,
                           (SELECT peer_ap_mac FROM mesh_links ml WHERE ml.id = ap.link_id) AS peer_ap_mac,
                           ap.radio, {identity_select},
                           ROW_NUMBER() OVER (ORDER BY sample_time, id) AS rn
                    FROM active_points ap {where}
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
                peer_ap_name=self._resolved_ap_name(dict(row)),
                peer_ap_mac=self._resolved_ap_mac(dict(row)),
                local_radio=row["radio"],
                **self._identity_payload(dict(row)),
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

    def get_active_path_chart(
        self,
        site_id: str,
        session_id: str,
        *,
        radio: int | None = None,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
    ) -> MeshPathChartDTO:
        self._validate_chart_time_range(time_from, time_to)
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshPathChartDTO(
                mode="active_path",
                requested_time_from=time_from or None,
                requested_time_to=time_to or None,
            )
        repository = self._chart_repository(context)
        payload = repository.query_active_link_chart_segments(
            source_file_id=context.detail_source_id,
            radio=radio,
            time_from=time_from,
            time_to=time_to,
        )
        return self._chart_dto(
            site_id,
            context,
            payload,
            mode="active_path",
            max_points=max_points,
            time_from=time_from,
            time_to=time_to,
        )

    def get_trackside_signal_chart(
        self,
        site_id: str,
        session_id: str,
        *,
        radio: int | None = None,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
        include_standby: bool = True,
        top_n: int = 0,
    ) -> MeshTracksideSignalChartDTO:
        # 兼容保留旧查询参数；新轨旁链路语义始终包含主备链路，也不按 top N 截断。
        _ = include_standby, top_n
        self._validate_chart_time_range(time_from, time_to)
        context = self._context(site_id, session_id)
        max_points = max(int(max_points), 10)
        if context.detail_db is None:
            return MeshTracksideSignalChartDTO(
                source_id=context.session_id,
                radio=radio,
                time_range=MeshTracksideSignalRangeDTO(
                    start=time_from or None,
                    end=time_to or None,
                ),
                requested_max_points=max_points,
                effective_max_points=max_points,
                top_n=0,
                include_standby=True,
            )
        repository = self._chart_repository(context)
        payload = repository.query_trackside_link_chart_segment(
            source_file_id=context.detail_source_id,
            radio=radio,
            time_from=time_from,
            time_to=time_to,
        )
        return self._trackside_signal_chart_dto(
            context,
            payload,
            radio=radio,
            time_from=time_from,
            time_to=time_to,
            max_points=max_points,
        )

    def get_peer_segment_chart(
        self,
        site_id: str,
        session_id: str,
        *,
        anchor_link_id: int,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
        all_visits: bool = False,
    ) -> MeshPathChartDTO:
        self._validate_chart_time_range(time_from, time_to)
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshPathChartDTO(
                mode="peer_segment",
                requested_time_from=time_from or None,
                requested_time_to=time_to or None,
            )
        repository = self._chart_repository(context)
        if all_visits:
            payload = self._all_peer_visit_payload(
                context,
                repository,
                anchor_link_id,
                time_from=time_from,
                time_to=time_to,
            )
        elif time_from and time_to:
            payload = repository.query_peer_chart_segments_in_range(
                anchor_link_id,
                time_from,
                time_to,
                source_file_id=context.detail_source_id,
            )
        elif time_from or time_to:
            payload = repository.query_peer_chart_segments(
                anchor_link_id,
                source_file_id=context.detail_source_id,
            )
        else:
            payload = repository.query_peer_chart_initial_segments(
                anchor_link_id,
                visible_samples=min(max(int(max_points), 10), 2_000),
                margin_samples=60,
                source_file_id=context.detail_source_id,
            )
        return self._chart_dto(
            site_id,
            context,
            payload,
            mode="peer_segment",
            max_points=max_points,
            time_from=time_from,
            time_to=time_to,
        )

    def _all_peer_visit_payload(
        self,
        context: _SessionContext,
        repository: MeshMrRepository,
        anchor_link_id: int,
        *,
        time_from: str = "",
        time_to: str = "",
    ) -> dict[str, object]:
        builds = self._build_rows(context)
        anchor_build = next(
            (row for row in builds if self._int(row.get("anchor_link_id")) == int(anchor_link_id)),
            None,
        )
        if anchor_build is None:
            if time_from and time_to:
                return repository.query_peer_chart_segments_in_range(
                    anchor_link_id,
                    time_from,
                    time_to,
                    source_file_id=context.detail_source_id,
                )
            return repository.query_peer_chart_segments(
                anchor_link_id,
                source_file_id=context.detail_source_id,
            )
        identity = self._build_ap_identity(anchor_build)
        radio = self._int(anchor_build.get("radio"))
        visits = [
            row
            for row in builds
            if self._build_ap_identity(row) == identity and self._int(row.get("radio")) == radio
        ]
        payloads: list[dict[str, object]] = []
        for row in visits:
            visit_anchor = self._int(row.get("anchor_link_id"))
            visit_start = str(row.get("build_start_time") or "")
            visit_end = str(row.get("build_end_time") or "")
            if visit_anchor is None or not visit_start or not visit_end:
                continue
            query_start = max(visit_start, time_from) if time_from else visit_start
            query_end = min(visit_end, time_to) if time_to else visit_end
            if query_start > query_end:
                continue
            payloads.append(
                repository.query_peer_chart_segments_in_range(
                    visit_anchor,
                    query_start,
                    query_end,
                    source_file_id=context.detail_source_id,
                )
            )
        return self._merge_peer_visit_payloads(payloads)

    @classmethod
    def _merge_peer_visit_payloads(cls, payloads: list[dict[str, object]]) -> dict[str, object]:
        peer_rows: list[dict[str, object]] = []
        run_rows: list[dict[str, object]] = []
        events: list[dict[str, object]] = []
        anchors: list[dict[str, object]] = []
        intervals: list[float] = []
        gaps: list[float] = []
        for payload in payloads:
            peer_segment = dict(payload.get("peer_segment") or {})
            run_segment = dict(payload.get("run_segment") or {})
            peer_rows.extend(dict(row) for row in peer_segment.get("rows") or [])
            run_rows.extend(dict(row) for row in run_segment.get("rows") or [])
            events.extend(dict(row) for row in run_segment.get("events") or [])
            anchor = dict(payload.get("anchor") or peer_segment.get("anchor") or {})
            if anchor:
                anchors.append(anchor)
            for segment in (peer_segment, run_segment):
                interval = cls._number(segment.get("estimated_interval_seconds"))
                gap = cls._number(segment.get("continuity_gap_seconds"))
                if interval is not None:
                    intervals.append(interval)
                if gap is not None:
                    gaps.append(gap)
        peer_rows.sort(key=lambda row: (str(row.get("sample_time") or ""), str(row.get("timestamp_tag") or ""), int(row.get("id") or 0)))
        run_rows.sort(key=lambda row: (str(row.get("sample_time") or ""), str(row.get("timestamp_tag") or ""), int(row.get("id") or 0)))
        anchor = anchors[0] if anchors else None
        interval = min(intervals) if intervals else None
        gap = max(gaps) if gaps else None
        peer_segment = {
            "anchor": anchor,
            "rows": peer_rows,
            "estimated_interval_seconds": interval,
            "continuity_gap_seconds": gap,
        }
        run_segment = {
            "anchor": anchor,
            "rows": run_rows,
            "events": events,
            "estimated_interval_seconds": interval,
            "continuity_gap_seconds": gap,
        }
        return {"anchor": anchor, "peer_segment": peer_segment, "run_segment": run_segment}

    @classmethod
    def _build_ap_identity(cls, row: dict[str, Any]) -> str:
        physical = str(row.get("physical_ap_key") or "").strip().casefold()
        if physical and not physical.startswith("ap_name:"):
            return f"physical:{physical}"
        mac = cls._mac_key(row.get("peer_ap_mac"))
        if mac:
            return f"physical:ap_mac:{mac}"
        peer = cls._mac_key(
            row.get("active_peer_mac") or row.get("peer_radio_mac")
        )
        return f"observed_peer:{peer}" if peer else ""

    def get_rate_series(
        self,
        site_id: str,
        session_id: str,
        *,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
    ) -> MeshRatePageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshRatePageDTO()
        max_points = min(max(int(max_points), 10), 2_000)
        clauses = ["(local_rate_raw IS NOT NULL OR peer_rate_raw IS NOT NULL)"]
        values: list[Any] = []
        time_clauses, time_values = self._time_clauses("sample_time", "sample_time", time_from, time_to)
        clauses.extend(time_clauses)
        values.extend(time_values)
        where = "WHERE " + " AND ".join(clauses)
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM mesh_links {where}", values).fetchone()[0] or 0)
            step = max(1, (total + max_points - 1) // max_points)
            link_columns = self._table_columns(conn, "mesh_links")
            identity_select = ", ".join(
                (
                    column
                    if column in link_columns
                    else f"NULL AS {column}"
                )
                for column in (
                    "peer_match_rule",
                    "peer_match_confidence",
                    "peer_resolve_source",
                    "peer_identity_status",
                    "peer_identity_source",
                    "peer_identity_reason",
                )
            )
            rows = conn.execute(
                f"""
                WITH ordered AS (
                    SELECT sample_time, radio, peer_ap_name,
                           peer_ap_mac, {identity_select},
                           local_rate_raw, peer_rate_raw,
                           ROW_NUMBER() OVER (ORDER BY sample_time, timestamp_tag, id) AS rn
                    FROM mesh_links {where}
                )
                SELECT * FROM ordered
                WHERE ((rn - 1) % ?) = 0
                ORDER BY sample_time, rn
                LIMIT ?
                """,
                (*values, step, max_points),
            ).fetchall()
        items = [
            MeshRatePointDTO(
                timestamp=str(row["sample_time"]),
                local_radio=row["radio"],
                peer_ap_name=self._resolved_ap_name(dict(row)),
                peer_ap_mac=self._resolved_ap_mac(dict(row)),
                **self._identity_payload(dict(row)),
                local_rate_raw=self._number(row["local_rate_raw"]),
                peer_rate_raw=self._number(row["peer_rate_raw"]),
            )
            for row in rows
        ]
        return MeshRatePageDTO(items=items, total=total, downsampled=step > 1)

    def get_counter_deltas(
        self,
        site_id: str,
        session_id: str,
        *,
        time_from: str = "",
        time_to: str = "",
        max_points: int = 1_000,
    ) -> MeshCounterDeltaPageDTO:
        context = self._context(site_id, session_id)
        if context.detail_db is None:
            return MeshCounterDeltaPageDTO()
        max_points = min(max(int(max_points), 10), 2_000)
        time_clauses, time_values = self._time_clauses("sample_time", "sample_time", time_from, time_to)
        time_where = " AND ".join(time_clauses) if time_clauses else "1"
        with closing(self._connect_readonly(context.detail_db)) as conn:
            link_columns = self._table_columns(conn, "mesh_links")
        identity_select = ", ".join(
            (
                column
                if column in link_columns
                else f"NULL AS {column}"
            )
            for column in (
                "peer_match_rule",
                "peer_match_confidence",
                "peer_resolve_source",
                "peer_identity_status",
                "peer_identity_source",
                "peer_identity_reason",
            )
        )
        counter_cte = f"""
            WITH ordered AS (
                SELECT id, source_file_id, sample_time, timestamp_tag, radio, peer_ap_name,
                       peer_ap_mac, {identity_select},
                       local_retry, peer_retry, local_err, peer_err,
                       LAG(local_retry) OVER sample_partition AS previous_local_retry,
                       LAG(peer_retry) OVER sample_partition AS previous_peer_retry,
                       LAG(local_err) OVER sample_partition AS previous_local_err,
                       LAG(peer_err) OVER sample_partition AS previous_peer_err
                FROM mesh_links
                WINDOW sample_partition AS (
                    PARTITION BY source_file_id, radio,
                        COALESCE(NULLIF(session_id, ''), NULLIF(peer_mac_normalized, ''), peer_mac_raw, '')
                    ORDER BY sample_time, timestamp_tag, id
                )
            ), deltas AS (
                SELECT *,
                       CASE WHEN local_retry IS NULL OR previous_local_retry IS NULL
                                      OR local_retry < previous_local_retry
                            THEN NULL ELSE local_retry - previous_local_retry END AS local_retry_delta,
                       CASE WHEN peer_retry IS NULL OR previous_peer_retry IS NULL
                                      OR peer_retry < previous_peer_retry
                            THEN NULL ELSE peer_retry - previous_peer_retry END AS peer_retry_delta,
                       CASE WHEN local_err IS NULL OR previous_local_err IS NULL
                                      OR local_err < previous_local_err
                            THEN NULL ELSE local_err - previous_local_err END AS local_error_delta,
                       CASE WHEN peer_err IS NULL OR previous_peer_err IS NULL
                                      OR peer_err < previous_peer_err
                            THEN NULL ELSE peer_err - previous_peer_err END AS peer_error_delta
                FROM ordered
            ), filtered AS (
                SELECT * FROM deltas
                WHERE {time_where}
                  AND (local_retry_delta IS NOT NULL OR peer_retry_delta IS NOT NULL
                       OR local_error_delta IS NOT NULL OR peer_error_delta IS NOT NULL)
            )
        """
        with closing(self._connect_readonly(context.detail_db)) as conn:
            total = int(conn.execute(counter_cte + " SELECT COUNT(*) FROM filtered", time_values).fetchone()[0] or 0)
            step = max(1, (total + max_points - 1) // max_points)
            rows = conn.execute(
                counter_cte
                + """
                , numbered AS (
                    SELECT *, ROW_NUMBER() OVER (ORDER BY sample_time, timestamp_tag, id) AS rn
                    FROM filtered
                )
                SELECT * FROM numbered
                WHERE ((rn - 1) % ?) = 0
                ORDER BY sample_time, rn
                LIMIT ?
                """,
                (*time_values, step, max_points),
            ).fetchall()
        items = [
            MeshCounterDeltaPointDTO(
                timestamp=str(row["sample_time"]),
                local_radio=row["radio"],
                peer_ap_name=self._resolved_ap_name(dict(row)),
                peer_ap_mac=self._resolved_ap_mac(dict(row)),
                **self._identity_payload(dict(row)),
                local_retry_delta=int(row["local_retry_delta"]) if row["local_retry_delta"] is not None else None,
                peer_retry_delta=int(row["peer_retry_delta"]) if row["peer_retry_delta"] is not None else None,
                local_error_delta=int(row["local_error_delta"]) if row["local_error_delta"] is not None else None,
                peer_error_delta=int(row["peer_error_delta"]) if row["peer_error_delta"] is not None else None,
            )
            for row in rows
        ]
        return MeshCounterDeltaPageDTO(items=items, total=total, downsampled=step > 1)

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
                "peer_ap_mac": str(build.get("peer_ap_mac") or "") or None,
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
            link_columns = self._table_columns(conn, "mesh_links")
            identity_aggregates = ", ".join(
                (
                    f"MAX({column}) AS {alias}"
                    if column in link_columns
                    else f"NULL AS {alias}"
                )
                for column, alias in (
                    ("peer_match_rule", "identity_rule"),
                    ("peer_match_confidence", "identity_confidence"),
                    ("peer_identity_status", "identity_status"),
                    ("peer_identity_source", "identity_source"),
                    ("peer_identity_reason", "identity_reason"),
                )
            )
            grouped = conn.execute(
                f"""
                SELECT peer_ap_mac AS ap_mac,
                       MAX(peer_ap_name) AS ap_name, MAX(peer_site) AS peer_site,
                       {identity_aggregates},
                       AVG(local_rssi_db) AS avg_rssi, MIN(local_rssi_db) AS min_rssi
                FROM mesh_links
                WHERE COALESCE(peer_ap_mac, '') != ''
                GROUP BY peer_ap_mac
                ORDER BY ap_name, ap_mac
                """
            ).fetchall()
            switches = [dict(row) for row in conn.execute("SELECT from_peer_mac, to_peer_mac FROM switch_events WHERE event_type = 'ACTIVE_SWITCH'")]
            anomalies = [str(row[0] or "") for row in conn.execute("SELECT related_peer_mac FROM diagnosis_events WHERE COALESCE(related_peer_mac, '') != ''")]
            segment_peers = [str(row[0] or "") for row in conn.execute("SELECT peer_mac_normalized FROM active_segments")]
            peer_to_ap = {
                self._mac_key(row["peer_mac_normalized"]): self._mac_key(row["peer_ap_mac"])
                for row in conn.execute(
                    """
                    SELECT peer_mac_normalized, MAX(peer_ap_mac) AS peer_ap_mac
                    FROM mesh_links
                    WHERE COALESCE(peer_mac_normalized, '') != ''
                      AND COALESCE(peer_ap_mac, '') != ''
                    GROUP BY peer_mac_normalized
                    """
                )
            }
        switch_in: dict[str, int] = {}
        switch_out: dict[str, int] = {}
        for row in switches:
            source_key = self._mac_key(row.get("from_peer_mac"))
            target_key = self._mac_key(row.get("to_peer_mac"))
            source = peer_to_ap.get(source_key)
            target = peer_to_ap.get(target_key)
            if not source or not target:
                continue
            switch_out[source] = switch_out.get(source, 0) + 1
            switch_in[target] = switch_in.get(target, 0) + 1
        anomaly_counts: dict[str, int] = {}
        for value in anomalies:
            peer_key = self._mac_key(value)
            key = peer_to_ap.get(peer_key)
            if not key:
                continue
            anomaly_counts[key] = anomaly_counts.get(key, 0) + 1
        build_counts: dict[str, int] = {}
        for value in segment_peers:
            peer_key = self._mac_key(value)
            key = peer_to_ap.get(peer_key)
            if not key:
                continue
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
                match_status=str(data.get("identity_status") or location.identity_status),
                identity_source=str(data.get("identity_source") or location.identity_source or "") or None,
                identity_rule=str(data.get("identity_rule") or "") or None,
                identity_confidence=int(data.get("identity_confidence") or 0),
                identity_reason=str(data.get("identity_reason") or location.identity_reason or "") or None,
            )
            if not query or query.casefold() in f"{item.peer_ap_name} {item.peer_ap_mac} {item.station} {item.section}".casefold():
                items.append(item)
        current, size = self._page(page, page_size)
        start = (current - 1) * size
        return MeshApStatisticsPageDTO(items=items[start : start + size], total=len(items), page=current, page_size=size)

    def list_report_artifacts(self, site_id: str, session_id: str) -> list[MeshReportArtifactDTO]:
        return [item.dto for item in self._artifact_candidates(self._context(site_id, session_id))]

    def open_artifact(self, site_id: str, session_id: str, artifact_id: str) -> tuple[Path, str]:
        for candidate in self._artifact_candidates(self._context(site_id, session_id)):
            if candidate.dto.artifact_id == artifact_id:
                return candidate.path, candidate.dto.name
        raise MeshAnalysisQueryError("文件不存在或不属于当前分析会话")

    def artifact_delete_targets(self, site_id: str, session_id: str, artifact_id: str) -> tuple[str, list[Path]]:
        context = self._context(site_id, session_id)
        output_root = self.paths.mesh_mr_export_dir(context.site_id, context.safe_folder_name).resolve()
        for candidate in self._artifact_candidates(context):
            if candidate.dto.artifact_id != artifact_id:
                continue
            if not candidate.dto.deletable or not self._within(candidate.path, output_root):
                raise MeshAnalysisQueryError("原始导入日志不允许从报告列表删除")
            targets = [candidate.path.resolve()]
            if (
                candidate.manifest_path is not None
                and candidate.manifest_path.is_file()
                and not candidate.manifest_path.is_symlink()
            ):
                targets.append(candidate.manifest_path.resolve())
            return candidate.dto.name, targets
        raise MeshAnalysisQueryError("文件不存在或不属于当前分析会话")

    def get_raw_source_summary(self, site_id: str, session_id: str) -> list[MeshDataSourceDTO]:
        context = self._context(site_id, session_id)
        identity_state = self._identity_mapping_state(context)
        location = MeshSourceLocator(self.paths).locate(site_id, context.source | {"safe_folder_name": context.safe_folder_name, "mr_id": context.mr_id}, context.source)
        if context.raw_path is None:
            source_action_id = self._artifact_id(session_id, "raw", str(context.source.get("archived_filename") or "missing"))
            return [
                MeshDataSourceDTO(
                    source_file_id=context.source_id,
                    source_action_id=source_action_id,
                    source_id=source_action_id,
                    source_type="raw_mesh_log",
                    name=str(context.source.get("original_filename") or context.source.get("archived_filename") or "原始日志"),
                    recoverable=location.recoverable,
                    recovery_source=location.recovery_source,
                    missing_reason=location.missing_reason,
                    rebuild_capability=location.rebuild_capability,
                    package_name="source.zip" if location.recoverable else "",
                    package_sha256=location.archive_sha256,
                    bundle_member_id=location.bundle_member_id,
                    **identity_state,
                )
            ]
        path = context.raw_path
        stat = path.stat()
        source_action_id = self._artifact_id(session_id, "raw", path.name)
        return [
            MeshDataSourceDTO(
                source_file_id=context.source_id,
                source_action_id=source_action_id,
                source_id=source_action_id,
                source_type="raw_mesh_log",
                name=str(context.source.get("original_filename") or path.name),
                exists=True,
                size_bytes=stat.st_size,
                modified_at=self._mtime(stat.st_mtime),
                compressed=path.suffix.lower() == ".gz",
                tail_available=True,
                rebuild_capability="ready",
                recovery_source=location.recovery_source,
                package_name="source.zip" if location.archive_sha256 else "",
                package_sha256=location.archive_sha256,
                bundle_member_id=location.bundle_member_id,
                **identity_state,
            )
        ]

    def read_raw_tail(self, site_id: str, session_id: str, source_action_id: str, *, lines: int = 100) -> MeshRawTailDTO:
        context = self._context(site_id, session_id)
        if context.raw_path is None or source_action_id != self._artifact_id(session_id, "raw", context.raw_path.name):
            raise MeshAnalysisQueryError("原始来源不存在")
        limit = min(max(int(lines), 1), 200)
        if context.raw_path.suffix.lower() == ".gz":
            raw = self._gzip_tail(context.raw_path, 256 * 1024)
        else:
            with context.raw_path.open("rb") as handle:
                size = handle.seek(0, 2)
                handle.seek(max(0, size - 256 * 1024))
                raw = handle.read()
        text = self._decode_text(raw)
        return MeshRawTailDTO(source_action_id=source_action_id, source_id=source_action_id, available=True, lines=text.splitlines()[-limit:])

    @staticmethod
    def _gzip_tail(path: Path, maximum: int) -> bytes:
        buffer = bytearray()
        expanded = 0
        with gzip.open(path, "rb") as handle:
            while chunk := handle.read(64 * 1024):
                expanded += len(chunk)
                if expanded > 64 * 1024 * 1024:
                    raise MeshAnalysisQueryError("压缩原始日志解压后超过 64 MiB，拒绝在线读取 tail")
                buffer.extend(chunk)
                if len(buffer) > maximum:
                    del buffer[:-maximum]
        return bytes(buffer)

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
            try:
                with closing(self._connect_readonly(index_db)) as conn:
                    if not self._table_exists(conn, "source_files"):
                        continue
                    sources = [
                        dict(row)
                        for row in conn.execute("SELECT * FROM source_files ORDER BY id")
                    ]
            except sqlite3.Error:
                LOGGER.warning("跳过不可读取的 MESH MR 索引：%s", profile.get("display_name"), exc_info=True)
                continue
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
        raw_path = MeshSourceLocator(self.paths).locate(site_id, profile, source).raw_path
        return _SessionContext(
            site_id=site_id,
            session_id=f"{profile['mr_id']}:{source['id']}",
            mr_id=str(profile["mr_id"]),
            mr_name=mr_name,
            safe_folder_name=safe_name,
            linked_device_id=profile.get("linked_device_id"),
            source_id=int(source["id"]),
            detail_source_id=self._resolve_detail_source_id(detail, source),
            source=source,
            mr_root=mr_root.resolve(),
            index_db=index_db.resolve(),
            detail_db=detail,
            raw_path=raw_path,
            relocated_detail=relocated,
        )

    def _session_dto(self, context: _SessionContext, stats: dict[str, Any] | None = None) -> MeshAnalysisSessionDTO:
        stats = stats or self._stats(context)
        train_name, role = self._mr_identity(context.mr_name)
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
            data_integrity="complete" if stats["parsed_status"] == "ready" and stats["warnings"] == 0 else "partial",
            analysis_status=str(context.source.get("parse_status") or "unknown"),
            parsed_status=stats["parsed_status"],
            parsed_message=stats["parsed_message"],
            schema_version=stats["schema_version"],
            available_capabilities=stats["available_capabilities"],
            missing_capabilities=stats["missing_capabilities"],
            warning_count=stats["warnings"],
            report_count=len([item for item in self._artifact_candidates(context) if item.dto.artifact_type != "raw_mesh_log"]),
            first_sample_time=str(context.source.get("first_sample_time") or "") or None,
            last_sample_time=str(context.source.get("last_sample_time") or "") or None,
        )

    def _stats(self, context: _SessionContext) -> dict[str, Any]:
        count_keys = ("links", "active", "standby", "events", "link_up", "link_down", "switches", "short", "pingpong", "rssi_anomalies", "busy_anomalies", "unmatched")
        empty: dict[str, Any] = {key: None for key in count_keys}
        empty.update(
            warnings=1,
            parsed_status="missing",
            parsed_message="结构化分析结果不存在，可继续查看原始日志并重新解析。",
            schema_version=None,
            available_capabilities=[],
            missing_capabilities=sorted(_DETAIL_CAPABILITY_TABLES),
        )
        if context.detail_db is None:
            return empty
        result = dict(empty)
        try:
            with closing(self._connect_readonly(context.detail_db)) as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                }
                available = sorted(name for name, required in _DETAIL_CAPABILITY_TABLES.items() if required.issubset(tables))
                missing = sorted(set(_DETAIL_CAPABILITY_TABLES) - set(available))
                schema_version = self._mesh_schema_version(conn) or str(context.source.get("db_schema_version") or "") or None
                result.update(
                    parsed_status="ready" if schema_version == SCHEMA_VERSION and not missing else "legacy",
                    parsed_message="结构化分析结果可用。" if schema_version == SCHEMA_VERSION and not missing else "旧版结构化结果缺少部分能力；可用区域继续只读展示。",
                    schema_version=schema_version,
                    available_capabilities=available,
                    missing_capabilities=missing,
                )
                if "mesh_links" in tables:
                    columns = self._table_columns(conn, "mesh_links")
                    if "link_state" in columns:
                        unmatched_expr = "0"
                        if "peer_ap_name" in columns and {"peer_mac_normalized", "peer_mac_raw"}.intersection(columns):
                            peer_parts = [name for name in ("peer_mac_normalized", "peer_mac_raw") if name in columns]
                            peer_expr = peer_parts[0] if len(peer_parts) == 1 else f"COALESCE({', '.join(peer_parts)})"
                            unmatched_expr = f"COUNT(DISTINCT CASE WHEN COALESCE(peer_ap_name, '') = '' THEN {peer_expr} END)"
                        link = conn.execute(
                            f"SELECT COUNT(*) AS links, SUM(CASE WHEN link_state = 'ACTIVE' THEN 1 ELSE 0 END) AS active, "
                            f"SUM(CASE WHEN link_state = 'STANDBY' THEN 1 ELSE 0 END) AS standby, {unmatched_expr} AS unmatched FROM mesh_links"
                        ).fetchone()
                        result.update({key: int(link[key] or 0) for key in ("links", "active", "standby", "unmatched")})
                if "switch_events" in tables and "event_type" in self._table_columns(conn, "switch_events"):
                    events = conn.execute(
                        "SELECT COUNT(*) AS events, "
                        "SUM(CASE WHEN event_type IN ('LINK_UP', 'ACTIVE_UP') THEN 1 ELSE 0 END) AS link_up, "
                        "SUM(CASE WHEN event_type IN ('LINK_DOWN', 'NO_ACTIVE') THEN 1 ELSE 0 END) AS link_down, "
                        "SUM(CASE WHEN event_type = 'ACTIVE_SWITCH' THEN 1 ELSE 0 END) AS switches FROM switch_events"
                    ).fetchone()
                    result.update({key: int(events[key] or 0) for key in ("events", "link_up", "link_down", "switches")})
                if "active_segments" in tables:
                    result["link_up"] = int(conn.execute("SELECT COUNT(*) FROM active_segments").fetchone()[0] or 0)
                if result["switches"] is not None:
                    result["link_down"] = result["switches"]
                issues = int(conn.execute("SELECT COUNT(*) FROM parse_issues").fetchone()[0] or 0) if "parse_issues" in tables else 0
                if "diagnosis_events" in tables and "category" in self._table_columns(conn, "diagnosis_events"):
                    diagnoses = conn.execute(
                        "SELECT SUM(CASE WHEN LOWER(category) LIKE '%rssi%' THEN 1 ELSE 0 END) AS rssi_anomalies, "
                        "SUM(CASE WHEN LOWER(category) LIKE '%busy%' THEN 1 ELSE 0 END) AS busy_anomalies FROM diagnosis_events"
                    ).fetchone()
                    result["rssi_anomalies"] = int(diagnoses["rssi_anomalies"] or 0)
                    result["busy_anomalies"] = int(diagnoses["busy_anomalies"] or 0)
                builds: list[dict[str, Any]] = []
                if "active_points" in tables:
                    try:
                        builds = self._build_rows(context)
                    except (sqlite3.Error, MeshAnalysisQueryError):
                        LOGGER.debug("旧 MESH active_points 不支持派生建链统计", exc_info=True)
                result["short"] = sum(row.get("build_result") == "short" for row in builds) if builds else None
                result["pingpong"] = sum(bool(row.get("is_pingpong_abnormal")) for row in builds) if builds else None
                result["warnings"] = issues + int(result["unmatched"] or 0) + int(context.raw_path is None) + int(result["parsed_status"] != "ready")
        except sqlite3.Error:
            LOGGER.warning("MESH 结构化结果不可读取：%s", context.session_id, exc_info=True)
            result.update(
                parsed_status="unreadable",
                parsed_message="该会话的结构化数据库无法打开；其他会话与原始日志不受影响。",
                available_capabilities=[],
                missing_capabilities=sorted(_DETAIL_CAPABILITY_TABLES),
                warnings=1 + int(context.raw_path is None),
            )
        return result

    def _build_rows(self, context: _SessionContext) -> list[dict[str, Any]]:
        if context.detail_db is None:
            return []
        stat = context.detail_db.stat()
        source_params = str(context.source.get("analysis_params_json") or "")
        try:
            fallback_params = mesh_analysis_params_to_json(
                load_site_mesh_analysis_params(self.paths, context.site_id)
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            fallback_params = "{}"
        return [
            dict(row)
            for row in self._build_rows_cached(
                str(context.detail_db),
                stat.st_mtime_ns,
                stat.st_size,
                context.detail_source_id,
                source_params,
                fallback_params,
            )
        ]

    def _resolve_detail_source_id(self, detail_db: Path | None, source: dict[str, Any]) -> int:
        index_source_id = int(source["id"])
        if detail_db is None:
            return index_source_id
        try:
            with closing(self._connect_readonly(detail_db)) as conn:
                if not self._table_exists(conn, "source_files"):
                    return index_source_id
                columns = self._table_columns(conn, "source_files")
                selected = [
                    column
                    for column in ("id", "sha256", "original_filename", "archived_filename")
                    if column in columns
                ]
                if "id" not in selected:
                    return index_source_id
                rows = [dict(row) for row in conn.execute(f"SELECT {', '.join(selected)} FROM source_files ORDER BY id")]
        except sqlite3.Error:
            return index_source_id
        if not rows:
            return index_source_id
        source_sha = str(source.get("sha256") or "").strip().casefold()
        if source_sha:
            matched = [row for row in rows if str(row.get("sha256") or "").strip().casefold() == source_sha]
            if len(matched) == 1:
                return int(matched[0]["id"])
        source_names = {
            str(source.get(field) or "").strip().casefold()
            for field in ("original_filename", "archived_filename")
            if str(source.get(field) or "").strip()
        }
        if source_names:
            matched = [
                row
                for row in rows
                if source_names
                & {
                    str(row.get(field) or "").strip().casefold()
                    for field in ("original_filename", "archived_filename")
                }
            ]
            if len(matched) == 1:
                return int(matched[0]["id"])
        if len(rows) == 1:
            return int(rows[0]["id"])
        same_id = next((row for row in rows if int(row["id"]) == index_source_id), None)
        return int(same_id["id"]) if same_id is not None else index_source_id

    @lru_cache(maxsize=16)
    def _build_rows_cached(
        self,
        path: str,
        _mtime_ns: int,
        _size: int,
        source_file_id: int,
        analysis_params_json: str,
        fallback_params_json: str,
    ) -> tuple[dict[str, Any], ...]:
        try:
            repository = MeshMrRepository(Path(path), read_only=True)
            return tuple(
                repository.query_active_link_build_order(
                    source_file_id=source_file_id,
                    analysis_params=analysis_params_json or None,
                    fallback_analysis_params=fallback_params_json,
                )
            )
        except MeshSchemaRebuildRequired as exc:
            raise MeshAnalysisQueryError(str(exc)) from exc

    @staticmethod
    def _chart_repository(context: _SessionContext) -> MeshMrRepository:
        if context.detail_db is None:
            raise MeshAnalysisQueryError("结构化分析结果不存在")
        try:
            return MeshMrRepository(context.detail_db, read_only=True)
        except MeshSchemaRebuildRequired as exc:
            raise MeshAnalysisQueryError(str(exc)) from exc

    def _chart_dto(
        self,
        site_id: str,
        context: _SessionContext,
        payload: dict[str, object],
        *,
        mode: str,
        max_points: int,
        time_from: str,
        time_to: str,
    ) -> MeshPathChartDTO:
        return self._chart_payload_dto(
            site_id,
            context,
            payload,
            mode=mode,
            max_points=max_points,
            time_from=time_from,
            time_to=time_to,
        )

    def _chart_payload_dto(
        self,
        site_id: str,
        context: _SessionContext,
        payload: dict[str, object],
        *,
        mode: str,
        max_points: int,
        time_from: str,
        time_to: str,
    ) -> MeshPathChartDTO:
        run_segment = dict(payload.get("run_segment") or {})
        peer_segment = dict(payload.get("peer_segment") or {})
        run_segment["rows"] = self._chart_rows_in_window(run_segment.get("rows"), time_from, time_to)
        peer_segment["rows"] = self._chart_rows_in_window(peer_segment.get("rows"), time_from, time_to)
        run_segment["events"] = self._chart_events_in_window(run_segment.get("events"), time_from, time_to)
        chart = build_chart_payload(peer_segment, run_segment)
        timestamps = list(chart.get("timestamp_labels") or [])
        tags = list(chart.get("timestamp_tags") or [])
        sources = list(chart.get("sample_source_file_ids") or [])
        radios = list(chart.get("sample_radios") or [])
        backups = list(chart.get("standby_links_by_index") or [])
        contexts = list(
            chart.get("main_links_by_index") if mode == "active_path" else chart.get("peer_links_by_index") or []
        )
        active_series = dict(chart.get("active_series") or {})
        peer_series = dict(chart.get("peer_series") or {})
        active_peer_rssi = chart.get("active_peer_rssi")
        no_active_values = chart.get("no_active_indices")
        multi_active_values = chart.get("multi_active_indices")
        switch_values = chart.get("switch_indices")
        no_active = {int(value) for value in (no_active_values if no_active_values is not None else [])}
        multi_active = {int(value) for value in (multi_active_values if multi_active_values is not None else [])}
        switch_indices = {int(value) for value in (switch_values if switch_values is not None else [])}
        events_by_index = dict(chart.get("events_by_index") or {})
        segment_index = self._chart_segment_index(self._build_rows(context))
        ap_map = self._ap_map(site_id)
        continuity_gap = self._number(dict(chart.get("metadata") or {}).get("continuity_gap_seconds"))
        point_rows: list[dict[str, Any]] = []
        previous_time: datetime | None = None
        previous_source = ""
        previous_segment_sequence: int | None = None
        for index, timestamp in enumerate(timestamps):
            item = dict(contexts[index] or {}) if index < len(contexts) else {}
            source = str(sources[index] if index < len(sources) else item.get("source_file_id") or "")
            radio = self._int(radios[index] if index < len(radios) else item.get("radio"))
            current_time = self._parse_time(timestamp)
            gap_before = bool(previous_source and source != previous_source)
            if previous_time is not None and current_time is not None and continuity_gap is not None:
                gap_before = gap_before or (current_time - previous_time).total_seconds() > continuity_gap
            row_for_segment = {
                "source_file_id": source,
                "sample_time": timestamp,
                "radio": radio,
                "peer_mac_normalized": item.get("peer_mac"),
            }
            segment = self._chart_segment(segment_index, row_for_segment)
            segment_sequence = self._int((segment or {}).get("sequence"))
            if mode == "peer_segment" and previous_segment_sequence is not None and segment_sequence != previous_segment_sequence:
                gap_before = True
            if mode == "active_path":
                local_rssi = self._chart_array_number(active_series.get("active_local_rssi"), index)
                peer_rssi = self._chart_array_number(active_peer_rssi, index)
                local_tx_busy = self._chart_array_number(active_series.get("active_local_tx_busy"), index)
                local_rx_busy = self._chart_array_number(active_series.get("active_local_rx_busy"), index)
                peer_tx_busy = self._chart_array_number(chart.get("active_peer_tx_busy"), index)
                peer_rx_busy = self._chart_array_number(chart.get("active_peer_rx_busy"), index)
                local_signal = self._chart_array_number(chart.get("active_local_signal"), index)
                peer_signal = self._chart_array_number(chart.get("active_peer_signal"), index)
            else:
                local_rssi = self._chart_array_number(peer_series.get("local_rssi"), index)
                peer_rssi = self._chart_array_number(peer_series.get("peer_rssi"), index)
                local_tx_busy = self._chart_array_number(peer_series.get("local_tx_busy"), index)
                local_rx_busy = self._chart_array_number(peer_series.get("local_rx_busy"), index)
                peer_tx_busy = self._chart_array_number(peer_series.get("peer_tx_busy"), index)
                peer_rx_busy = self._chart_array_number(peer_series.get("peer_rx_busy"), index)
                local_signal = self._chart_array_number(peer_series.get("local_signal"), index)
                peer_signal = self._chart_array_number(peer_series.get("peer_signal"), index)
            point_rows.append(
                {
                    "index": index,
                    "item": item,
                    "source": source,
                    "timestamp": str(timestamp),
                    "timestamp_tag": str(tags[index] if index < len(tags) else item.get("timestamp_tag") or ""),
                    "radio": radio,
                    "segment": segment,
                    "segment_sequence": segment_sequence,
                    "local_rssi": local_rssi,
                    "peer_rssi": peer_rssi,
                    "local_signal": local_signal,
                    "peer_signal": peer_signal,
                    "local_tx_busy": local_tx_busy,
                    "peer_tx_busy": peer_tx_busy,
                    "local_rx_busy": local_rx_busy,
                    "peer_rx_busy": peer_rx_busy,
                    "is_switch": index in switch_indices,
                    "is_anomaly": index in no_active or index in multi_active,
                    "gap_before": gap_before,
                    "backups": backups[index] if index < len(backups) else [],
                }
            )
            previous_source = source
            previous_time = current_time or previous_time
            previous_segment_sequence = segment_sequence
        total_points = len(point_rows)
        prepared_events = self._prepare_chart_events(point_rows, events_by_index)
        valid_switch_indices = {
            int(index)
            for row in prepared_events
            for index in (row.get("point_index"), row.get("busy_point_index"))
            if str(row["event"].get("event_type") or "") == "ACTIVE_SWITCH"
            and index is not None
        }
        requested_max_points, effective_max_points, rendered_switch_indices, downsample_warning = (
            self._chart_render_budget(total_points, max_points, valid_switch_indices)
        )
        important_values = chart.get("important_indices")
        important = {int(value) for value in (important_values if important_values is not None else [])}
        important.update(self._important_chart_row_indices(point_rows))
        indices = [
            int(index)
            for index in render_indices(
                total_points,
                0,
                0,
                important,
                effective_max_points,
                pinned_indices=rendered_switch_indices,
            )
        ]
        returned_indices = set(indices)
        returned = [self._materialize_chart_point(ap_map, context, point_rows[index]) for index in indices]
        location_segments = self._chart_location_segments(ap_map, point_rows)
        anchor_index = self._int(dict(chart.get("metadata") or {}).get("anchor_index"))
        anchor = (
            self._materialize_chart_point(ap_map, context, point_rows[anchor_index])
            if anchor_index is not None and 0 <= anchor_index < total_points
            else None
        )
        events: list[MeshChartEventDTO] = []
        for prepared in prepared_events:
            event = prepared["event"]
            event_id = int(event.get("id") or 0)
            timestamp = str(event.get("event_time") or event.get("current_sample_time") or "")
            event_segment = self._chart_segment(
                segment_index,
                {
                    "source_file_id": event.get("source_file_id") or context.detail_source_id,
                    "sample_time": timestamp,
                    "radio": event.get("radio"),
                    "peer_mac_normalized": event.get("to_peer_mac"),
                },
            )
            from_location = self._locate_ap(
                ap_map,
                {"peer_ap_name": event.get("from_peer_ap_name")},
            )
            to_location = self._locate_ap(
                ap_map,
                {"peer_ap_name": event.get("to_peer_ap_name")},
            )
            before_point = prepared.get("before_point")
            after_point = prepared.get("after_point")
            event_point = prepared.get("event_point")
            point_index = self._int(prepared.get("point_index"))
            render_aligned = point_index is not None and point_index in returned_indices
            render_point = event_point if render_aligned else None
            busy_point = prepared.get("busy_event_point")
            busy_point_index = self._int(prepared.get("busy_point_index"))
            busy_render_aligned = busy_point_index is not None and busy_point_index in returned_indices
            busy_render_point = busy_point if busy_render_aligned else None
            event_location = self._locate_ap(ap_map, dict((event_point or busy_point or {}).get("item") or {}))
            events.append(
                MeshChartEventDTO(
                    event_id=event_id,
                    timestamp=timestamp,
                    event_type=str(event.get("event_type") or ""),
                    local_radio=self._int(event.get("radio")),
                    from_peer_mac=str(event.get("from_peer_mac") or "") or None,
                    to_peer_mac=str(event.get("to_peer_mac") or "") or None,
                    from_ap_name=str(event.get("from_peer_ap_name") or from_location.name or "") or None,
                    to_ap_name=str(event.get("to_peer_ap_name") or to_location.name or "") or None,
                    segment_sequence=self._int((event_segment or {}).get("sequence")),
                    duration_ms=self._int(event.get("observed_window_ms")),
                    point_timestamp=str((render_point or {}).get("timestamp") or "") or None,
                    point_rssi=self._number((render_point or {}).get("local_rssi")),
                    point_context=(
                        self._materialize_chart_point(ap_map, context, render_point)
                        if render_point is not None
                        else None
                    ),
                    render_point_timestamp=str((render_point or {}).get("timestamp") or "") or None,
                    render_point_rssi=self._number((render_point or {}).get("local_rssi")),
                    render_aligned=render_aligned,
                    render_busy_point_timestamp=str((busy_render_point or {}).get("timestamp") or "") or None,
                    render_busy_point_index=busy_point_index if busy_render_aligned else None,
                    render_busy_tx_busy=self._number((busy_render_point or {}).get("local_tx_busy")),
                    render_busy_rx_busy=self._number((busy_render_point or {}).get("local_rx_busy")),
                    render_busy_aligned=busy_render_aligned,
                    busy_point_context=(
                        self._materialize_chart_point(ap_map, context, busy_render_point)
                        if busy_render_point is not None
                        else None
                    ),
                    before_rssi=self._number((before_point or {}).get("local_rssi")),
                    after_rssi=self._number((after_point or {}).get("local_rssi")),
                    station=event_location.station or None,
                    section=event_location.section or None,
                )
            )
        current_row = next(
            (row for row in reversed(point_rows) if str(dict(row.get("item") or {}).get("status") or "") == "ACTIVE"),
            None,
        )
        current = self._materialize_chart_point(ap_map, context, current_row) if current_row else None
        first_time = str(point_rows[0]["timestamp"]) if point_rows else None
        last_time = str(point_rows[-1]["timestamp"]) if point_rows else None
        metadata = dict(chart.get("metadata") or {})
        return MeshPathChartDTO(
            mode="active_path" if mode == "active_path" else "peer_segment",
            anchor=anchor,
            points=returned,
            events=events,
            location_segments=location_segments,
            summary=MeshPathChartSummaryDTO(
                current_peer_mac=current.peer_mac if current else None,
                current_peer_ap_name=current.peer_ap_name if current else None,
                current_radio=current.local_radio if current else None,
                sample_count=total_points,
                active_count=sum(str(dict(row.get("item") or {}).get("status") or "") == "ACTIVE" for row in point_rows),
                standby_context_count=sum(len(row.get("backups") or []) for row in point_rows),
                switch_count=sum(event.event_type == "ACTIVE_SWITCH" for event in events),
                earliest_sample_time=first_time,
                latest_sample_time=last_time,
                first_sample_time=first_time,
                last_sample_time=last_time,
                estimated_interval_seconds=self._number(metadata.get("estimated_interval_seconds")),
                continuity_gap_seconds=continuity_gap,
            ),
            total_points=total_points,
            returned_points=len(returned),
            downsampled=len(returned) < total_points,
            requested_max_points=requested_max_points,
            effective_max_points=effective_max_points,
            downsample_warning=downsample_warning,
            time_from=time_from or first_time,
            time_to=time_to or last_time,
            requested_time_from=time_from or None,
            requested_time_to=time_to or None,
            effective_time_from=first_time,
            effective_time_to=last_time,
            first_sample_time=first_time,
            last_sample_time=last_time,
            total_points_in_range=total_points,
        )

    def _trackside_signal_chart_dto(
        self,
        context: _SessionContext,
        payload: dict[str, object],
        *,
        radio: int | None,
        time_from: str,
        time_to: str,
        max_points: int,
    ) -> MeshTracksideSignalChartDTO:
        run_segment = dict(payload.get("run_segment") or {})
        rows = self._chart_rows_in_window(run_segment.get("rows"), time_from, time_to)
        rows, fallback_standby_points = self._trackside_rows_with_standby_fallback(
            payload,
            rows,
            public_source_id=context.source_id,
        )
        rows.sort(
            key=lambda row: (
                str(row.get("sample_time") or ""),
                str(row.get("timestamp_tag") or ""),
                self._int(row.get("source_file_id")) or context.source_id,
                self._int(row.get("radio")) or 0,
                int(row.get("id") or 0),
            )
        )
        estimated_interval = self._number(run_segment.get("estimated_interval_seconds"))
        continuity_gap = self._number(run_segment.get("continuity_gap_seconds"))
        ap_map = self._ap_map(context.site_id)
        segment_index = self._chart_segment_index(self._build_rows(context))
        groups: dict[tuple[str, int | None], dict[str, Any]] = {}
        frame_items: dict[tuple[int, str, str, int | None], list[dict[str, Any]]] = defaultdict(list)
        observed_frame_keys: set[tuple[int, str, str, int | None]] = set()
        seen_samples: set[tuple[tuple[int, str, str, int | None], tuple[str, int | None], int | None, str]] = set()
        skipped_missing_signal = 0
        skipped_missing_identity = 0

        for row in rows:
            role = str(row.get("link_state") or "").upper()
            timestamp = str(row.get("sample_time") or "")
            if not timestamp:
                continue
            timestamp_tag = str(row.get("timestamp_tag") or "")
            source_file_id = self._int(row.get("source_file_id")) or context.source_id
            local_radio = self._int(row.get("radio"))
            frame_key = (source_file_id, timestamp, timestamp_tag, local_radio)
            observed_frame_keys.add(frame_key)
            if role not in {LINK_STATE_ACTIVE, LINK_STATE_STANDBY}:
                continue
            peer_mac = (
                str(
                    row.get("peer_mac_normalized")
                    or row.get("peer_mac")
                    or row.get("peer_mac_raw")
                    or ""
                ).strip()
                or None
            )
            peer_radio_mac = str(row.get("peer_radio_mac") or "").strip() or None
            location = self._locate_ap(
                ap_map,
                {
                    **row,
                    "peer_ap_mac": row.get("peer_ap_mac"),
                    "peer_ap_name": row.get("peer_ap_name"),
                    "peer_mac_normalized": peer_mac,
                    "peer_site": row.get("peer_site"),
                },
            )
            identity_payload = self._identity_payload(row, location)
            ap_mac = self._resolved_ap_mac(row, location)
            peer_name = self._resolved_ap_name(row, location)
            identity = self._trackside_link_identity(
                peer_radio_mac=peer_radio_mac,
                ap_mac=ap_mac,
                peer_mac=peer_mac,
                peer_name=peer_name,
            )
            if not identity:
                skipped_missing_identity += 1
                continue
            station = self._resolved_location_value(row, location, "station")
            section = self._resolved_location_value(row, location, "section")
            series_key = (identity, local_radio)
            peer_rssi = self._number(row.get("peer_rssi_db"))
            peer_signal = self._number(row.get("peer_signal_dbm"))
            data_source = self._trackside_signal_data_source(peer_rssi, peer_signal)
            link_id = self._int(row.get("id") or row.get("link_id"))
            sample_key = (frame_key, series_key, link_id, role)
            if sample_key in seen_samples:
                continue
            seen_samples.add(sample_key)
            if not data_source:
                skipped_missing_signal += 1
                continue

            segment = self._chart_segment(segment_index, row) if role == LINK_STATE_ACTIVE else None
            item = {
                "series_key": series_key,
                "frame_key": frame_key,
                "row": row,
                "role": role,
                "value": peer_rssi if peer_rssi is not None else peer_signal,
                "point_values": {
                    "timestamp": timestamp,
                    "timestamp_tag": timestamp_tag,
                    "source_file_id": source_file_id,
                    "link_id": link_id,
                    "sample_id": link_id,
                    "local_radio": local_radio,
                    "role": role,
                    "peer_mac": peer_mac,
                    "peer_ap_name": peer_name,
                    "peer_ap_mac": ap_mac,
                    "peer_radio": str(
                        row.get("peer_radio") or row.get("peer_radio_label") or ""
                    )
                    or None,
                    "peer_radio_mac": peer_radio_mac,
                    **identity_payload,
                    "station": station,
                    "section": section,
                    "peer_rssi": peer_rssi,
                    "local_rssi": self._number(row.get("local_rssi_db")),
                    "peer_signal": peer_signal,
                    "local_signal": self._number(row.get("local_signal_dbm")),
                    "segment_sequence": self._int((segment or {}).get("sequence")),
                    "segment_start": str((segment or {}).get("build_start_time") or "") or None,
                    "segment_end": str((segment or {}).get("build_end_time") or "") or None,
                    "segment_duration_seconds": self._number(
                        (segment or {}).get("main_link_duration_seconds")
                    ),
                    "data_source": data_source,
                },
            }
            group = groups.setdefault(
                series_key,
                {
                    "series_key": series_key,
                    "series_id": f"{identity}:radio:{local_radio if local_radio is not None else 'all'}",
                    "peer_name": peer_name or peer_radio_mac or ap_mac or peer_mac,
                    "peer_mac": peer_mac,
                    "ap_mac": ap_mac,
                    "peer_radio_mac": peer_radio_mac,
                    "radio": local_radio,
                    "station": station,
                    "section": section,
                    "items": [],
                },
            )
            for field, value_text in {
                "peer_name": peer_name,
                "peer_mac": peer_mac,
                "ap_mac": ap_mac,
                "peer_radio_mac": peer_radio_mac,
                "station": station,
                "section": section,
            }.items():
                if value_text and not group.get(field):
                    group[field] = value_text
            group["items"].append(item)
            frame_items[frame_key].append(item)

        warnings: list[str] = []
        if fallback_standby_points:
            warnings.append(
                f"旧结构化数据缺少部分 STANDBY 行，已从真实备链上下文补充 "
                f"{fallback_standby_points} 个备用链路点。"
            )
        if skipped_missing_signal:
            warnings.append(
                f"已跳过 {skipped_missing_signal} 个缺少 peer_rssi / peer_signal 的轨旁链路采样点。"
            )
        if skipped_missing_identity:
            warnings.append(
                f"已跳过 {skipped_missing_identity} 个无法确定 Peer/AP/Radio 物理身份的轨旁链路采样点。"
            )

        observed_frames = [
            {
                "key": key,
                "source_file_id": key[0],
                "timestamp": key[1],
                "timestamp_tag": key[2],
                "radio": key[3],
                "items": frame_items.get(key, []),
            }
            for key in sorted(
                observed_frame_keys,
                key=lambda frame_key: (
                    frame_key[1],
                    frame_key[2],
                    frame_key[0],
                    frame_key[3] or 0,
                ),
            )
        ]
        ordered_frames = [frame for frame in observed_frames if frame["items"]]
        materialized: list[dict[str, Any]] = []
        for frame_index, frame in enumerate(ordered_frames):
            frame["index"] = frame_index
            frame["time"] = self._parse_time(str(frame["timestamp"]))
            frame["items"].sort(
                key=lambda item: (
                    0 if item["role"] == LINK_STATE_ACTIVE else 1,
                    str(item["point_values"].get("peer_ap_name") or "").casefold(),
                    str(item["point_values"].get("peer_mac") or ""),
                )
            )
            for item in frame["items"]:
                item["frame_index"] = frame_index
                item["index"] = len(materialized)
                materialized.append(item)

        runs: dict[str, dict[str, Any]] = {}
        last_frame_by_axis: dict[tuple[int, int | None], dict[str, Any]] = {}
        last_by_series: dict[tuple[str, int | None], dict[str, Any]] = {}
        transition_frames: set[int] = set()
        active_switch_frames: set[int] = set()
        anomaly_frames: set[int] = set()
        last_active_by_axis: dict[tuple[int, int | None], dict[str, Any]] = {}
        run_sequence = 0
        role_switch_count = 0

        for frame in observed_frames:
            axis_key = (int(frame["source_file_id"]), frame["radio"])
            previous_frame = last_frame_by_axis.get(axis_key)
            previous_series = set(previous_frame.get("series_keys") or []) if previous_frame else set()
            frame_time = frame.get("time")
            previous_time = previous_frame.get("time") if previous_frame else None
            gap_break = bool(
                continuity_gap is not None
                and previous_time is not None
                and frame_time is not None
                and (frame_time - previous_time).total_seconds() > continuity_gap
            )
            by_series: dict[tuple[str, int | None], list[dict[str, Any]]] = defaultdict(list)
            for item in frame["items"]:
                by_series[item["series_key"]].append(item)
            current_series = set(by_series)
            render_frame_index = frame.get("index")

            for series_key, items in by_series.items():
                previous = last_by_series.get(series_key)
                starts_new_run = bool(
                    previous is None
                    or previous.get("source_file_id") != frame["source_file_id"]
                    or series_key not in previous_series
                    or gap_break
                )
                if starts_new_run:
                    run_sequence += 1
                current_run_sequence = (
                    run_sequence if starts_new_run else int(previous["run_sequence"])
                )
                run_id = (
                    f"{frame['source_file_id']}:"
                    f"{frame['radio'] if frame['radio'] is not None else 'all'}:"
                    f"{series_key[0]}:{current_run_sequence}"
                )
                current_role = (
                    LINK_STATE_ACTIVE
                    if any(item["role"] == LINK_STATE_ACTIVE for item in items)
                    else LINK_STATE_STANDBY
                )
                if (
                    previous is not None
                    and not starts_new_run
                    and previous.get("role") != current_role
                ):
                    role_switch_count += 1
                    transition_frames.update(
                        {int(previous["frame_index"]), int(render_frame_index)}
                    )

                run = runs.setdefault(
                    run_id,
                    {
                        "run_id": run_id,
                        "run_sequence": current_run_sequence,
                        "series_key": series_key,
                        "items": [],
                    },
                )
                for item_index, item in enumerate(items):
                    point = MeshTracksideSignalPointDTO(
                        **item["point_values"],
                        run_id=run_id,
                        run_sequence=current_run_sequence,
                        break_before=starts_new_run and item_index == 0,
                    )
                    item["run_id"] = run_id
                    item["run_sequence"] = current_run_sequence
                    item["point"] = point
                    run["items"].append(item)
                last_by_series[series_key] = {
                    "source_file_id": frame["source_file_id"],
                    "frame_index": render_frame_index,
                    "run_sequence": current_run_sequence,
                    "run_id": run_id,
                    "role": current_role,
                }

            active_series = {
                item["series_key"]
                for item in frame["items"]
                if item["role"] == LINK_STATE_ACTIVE
            }
            if render_frame_index is not None and len(active_series) != 1:
                anomaly_frames.add(int(render_frame_index))
            if len(active_series) == 1:
                active_series_key = next(iter(active_series))
                previous_active = last_active_by_axis.get(axis_key)
                if previous_active and previous_active.get("series_key") != active_series_key:
                    active_switch_frames.update(
                        {int(previous_active["frame_index"]), int(render_frame_index)}
                    )
                last_active_by_axis[axis_key] = {
                    "series_key": active_series_key,
                    "frame_index": render_frame_index,
                }
            else:
                last_active_by_axis.pop(axis_key, None)
            last_frame_by_axis[axis_key] = {
                "series_keys": current_series,
                "time": frame_time,
            }

        total_frames = len(ordered_frames)
        total_link_points = len(materialized)
        requested_max_frames = max(int(max_points), 10)
        effective_max_frames = requested_max_frames
        required_frames: set[int] = set(
            transition_frames | active_switch_frames | anomaly_frames
        )
        if total_frames:
            required_frames.update({0, total_frames - 1})
        for group in groups.values():
            items = list(group["items"])
            if items:
                required_frames.update(
                    {int(items[0]["frame_index"]), int(items[-1]["frame_index"])}
                )
        for run in runs.values():
            items = list(run["items"])
            if not items:
                continue
            required_frames.update(
                {int(items[0]["frame_index"]), int(items[-1]["frame_index"])}
            )
            valued = [item for item in items if item.get("value") is not None]
            if valued:
                required_frames.add(
                    int(min(valued, key=lambda item: item["value"])["frame_index"])
                )
                required_frames.add(
                    int(max(valued, key=lambda item: item["value"])["frame_index"])
                )

        if len(required_frames) > effective_max_frames:
            effective_max_frames = len(required_frames)
            warnings.append(
                "为保留链路出现、消失、角色切换和 RSSI 极值，"
                f"轨旁图目标采样时刻已从 {requested_max_frames} 提升到 "
                f"{effective_max_frames}。"
            )
        if total_frames == 0:
            warnings.append("当前日志没有任何有效 peer_rssi / peer_signal。")
            selected_frame_indices: set[int] = set()
        else:
            selected_frame_indices = set(
                int(index)
                for index in render_indices(
                    total_frames,
                    0,
                    0,
                    required_frames,
                    effective_max_frames,
                    pinned_indices=required_frames,
                )
            )
        selected_items = [
            item
            for item in materialized
            if int(item["frame_index"]) in selected_frame_indices
        ]
        returned_frames = len(
            {int(item["frame_index"]) for item in selected_items}
        )
        if returned_frames < total_frames:
            warnings.append(
                f"轨旁链路 RSSI 共 {total_link_points} 个有效链路采样点，"
                f"覆盖 {total_frames} 个采样时刻和 {len(groups)} 条 AP/Radio 序列；"
                f"最终返回 {returned_frames} 个采样时刻、{len(selected_items)} 个链路点。"
            )

        selected_by_series: dict[tuple[str, int | None], list[MeshTracksideSignalPointDTO]] = defaultdict(list)
        last_selected_by_series: dict[tuple[str, int | None], dict[str, Any]] = {}
        for item in selected_items:
            series_key = item["series_key"]
            previous = last_selected_by_series.get(series_key)
            point = item["point"]
            break_before = False if previous is None else bool(
                previous.get("run_id") != item.get("run_id")
            )
            selected_by_series[series_key].append(point.model_copy(update={"break_before": break_before}))
            last_selected_by_series[series_key] = item

        series: list[MeshTracksideSignalSeriesDTO] = []
        for group in sorted(
            groups.values(),
            key=lambda group: int((group.get("items") or [{"index": 0}])[0]["index"]),
        ):
            points = selected_by_series.get(group["series_key"], [])
            if not points:
                continue
            data_sources = {
                item["point"].data_source
                for item in group["items"]
                if item.get("point") and item["point"].data_source
            }
            roles_present = [
                role
                for role in (LINK_STATE_ACTIVE, LINK_STATE_STANDBY)
                if any(
                    item.get("point") and item["point"].role == role
                    for item in group["items"]
                )
            ]
            series.append(
                MeshTracksideSignalSeriesDTO(
                    series_id=group["series_id"],
                    peer_name=group.get("peer_name"),
                    peer_mac=group.get("peer_mac"),
                    ap_mac=group.get("ap_mac"),
                    peer_radio_mac=group.get("peer_radio_mac"),
                    radio=group.get("radio"),
                    station=group.get("station"),
                    section=group.get("section"),
                    roles_present=roles_present,
                    data_source=next(iter(data_sources)) if len(data_sources) == 1 else "mixed" if data_sources else "",
                    total_points=len(group["items"]),
                    returned_points=len(points),
                    points=points,
                )
            )
        returned_link_points = sum(item.returned_points for item in series)
        active_link_points = sum(
            item["role"] == LINK_STATE_ACTIVE for item in materialized
        )
        standby_link_points = sum(
            item["role"] == LINK_STATE_STANDBY for item in materialized
        )
        returned_active_link_points = sum(
            item["role"] == LINK_STATE_ACTIVE for item in selected_items
        )
        returned_standby_link_points = sum(
            item["role"] == LINK_STATE_STANDBY for item in selected_items
        )
        downsampled = returned_frames < total_frames

        return MeshTracksideSignalChartDTO(
            source_id=context.session_id,
            radio=radio,
            time_range=MeshTracksideSignalRangeDTO(
                start=time_from or str(run_segment.get("segment_start") or "") or None,
                end=time_to or str(run_segment.get("segment_end") or "") or None,
            ),
            series=series,
            events=[],
            warnings=warnings,
            estimated_interval_seconds=estimated_interval,
            continuity_gap_seconds=continuity_gap,
            total_series=len(groups),
            returned_series=len(series),
            total_frames=total_frames,
            returned_frames=returned_frames,
            total_link_points=total_link_points,
            returned_link_points=returned_link_points,
            total_link_runs=len(runs),
            active_link_points=active_link_points,
            standby_link_points=standby_link_points,
            returned_active_link_points=returned_active_link_points,
            returned_standby_link_points=returned_standby_link_points,
            role_switch_count=role_switch_count,
            skipped_missing_signal_points=skipped_missing_signal,
            skipped_missing_identity_points=skipped_missing_identity,
            total_points=total_link_points,
            returned_points=returned_link_points,
            downsampled=downsampled,
            requested_max_frames=requested_max_frames,
            effective_max_frames=effective_max_frames,
            requested_max_points=requested_max_frames,
            effective_max_points=effective_max_frames,
            top_n=0,
            included_roles=[LINK_STATE_ACTIVE, LINK_STATE_STANDBY],
            include_standby=True,
        )

    def _trackside_rows_with_standby_fallback(
        self,
        payload: dict[str, object],
        rows: list[dict[str, Any]],
        *,
        public_source_id: int,
    ) -> tuple[list[dict[str, Any]], int]:
        result = list(rows)
        existing = {
            self._trackside_fallback_identity(row, public_source_id)
            for row in result
            if str(row.get("link_state") or "").upper() == LINK_STATE_STANDBY
        }
        existing_link_ids = {
            (
                self._int(row.get("source_file_id")) or public_source_id,
                str(row.get("sample_time") or ""),
                str(row.get("timestamp_tag") or ""),
                self._int(row.get("radio") or row.get("local_radio")),
                link_id,
            )
            for row in result
            if str(row.get("link_state") or "").upper() == LINK_STATE_STANDBY
            and (link_id := self._int(row.get("id") or row.get("link_id"))) is not None
        }
        fallback_rows: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for row in rows:
            for backup in row.get("backups") or []:
                if isinstance(backup, dict):
                    fallback_rows.append((dict(backup), row))

        standby_by_index = payload.get("standby_links_by_index")
        if not isinstance(standby_by_index, list):
            standby_by_index = payload.get("backup_links_by_index")
        if isinstance(standby_by_index, list):
            timestamp_labels = payload.get("timestamp_labels")
            timestamp_tags = payload.get("timestamp_tags")
            source_ids = payload.get("sample_source_file_ids")
            radios = payload.get("sample_radios")
            for index, backups in enumerate(standby_by_index):
                defaults = {
                    "sample_time": self._trackside_sequence_value(timestamp_labels, index),
                    "timestamp_tag": self._trackside_sequence_value(timestamp_tags, index),
                    "source_file_id": self._trackside_sequence_value(source_ids, index)
                    or public_source_id,
                    "radio": self._trackside_sequence_value(radios, index),
                }
                for backup in backups if isinstance(backups, list) else []:
                    if isinstance(backup, dict):
                        fallback_rows.append((dict(backup), defaults))

        added = 0
        for backup, defaults in fallback_rows:
            default_values = defaults or {}
            row = {
                "id": backup.get("link_id"),
                "link_id": backup.get("link_id"),
                "source_file_id": backup.get("source_file_id")
                or default_values.get("source_file_id")
                or public_source_id,
                "sample_time": backup.get("sample_time")
                or backup.get("timestamp")
                or default_values.get("sample_time"),
                "timestamp_tag": backup.get("timestamp_tag")
                or default_values.get("timestamp_tag")
                or "",
                "radio": backup.get("radio")
                or backup.get("local_radio")
                or default_values.get("radio"),
                "link_state": LINK_STATE_STANDBY,
                "peer_mac_normalized": backup.get("peer_mac"),
                "peer_mac_raw": backup.get("peer_mac"),
                "peer_ap_name": backup.get("ap_name") or backup.get("peer_ap_name"),
                "peer_ap_mac": backup.get("ap_mac") or backup.get("peer_ap_mac"),
                "peer_site": backup.get("site") or backup.get("station"),
                "peer_radio": backup.get("peer_radio"),
                "peer_radio_label": backup.get("peer_radio"),
                "peer_radio_mac": backup.get("peer_radio_mac"),
                "local_rssi_db": backup.get("mr_rssi")
                if backup.get("mr_rssi") is not None
                else backup.get("local_rssi"),
                "peer_rssi_db": backup.get("ap_rssi")
                if backup.get("ap_rssi") is not None
                else backup.get("peer_rssi"),
                "local_signal_dbm": backup.get("local_signal"),
                "peer_signal_dbm": backup.get("peer_signal"),
            }
            if not row["sample_time"]:
                continue
            identity = self._trackside_fallback_identity(row, public_source_id)
            link_id = self._int(row.get("id") or row.get("link_id"))
            link_identity = (*identity[:4], link_id) if link_id is not None else None
            if identity in existing or (
                link_identity is not None and link_identity in existing_link_ids
            ):
                continue
            existing.add(identity)
            if link_identity is not None:
                existing_link_ids.add(link_identity)
            result.append(row)
            added += 1
        return result, added

    def _trackside_fallback_identity(
        self,
        row: dict[str, Any],
        public_source_id: int,
    ) -> tuple[int, str, str, int | None, str]:
        return (
            self._int(row.get("source_file_id")) or public_source_id,
            str(row.get("sample_time") or ""),
            str(row.get("timestamp_tag") or ""),
            self._int(row.get("radio") or row.get("local_radio")),
            self._trackside_link_identity(
                peer_radio_mac=str(row.get("peer_radio_mac") or "") or None,
                ap_mac=str(row.get("peer_ap_mac") or row.get("ap_mac") or "") or None,
                peer_mac=str(
                    row.get("peer_mac_normalized")
                    or row.get("peer_mac")
                    or row.get("peer_mac_raw")
                    or ""
                )
                or None,
                peer_name=str(
                    row.get("peer_ap_name") or row.get("ap_name") or ""
                )
                or None,
            )
            or "",
        )

    def _trackside_link_identity(
        self,
        *,
        peer_radio_mac: str | None,
        ap_mac: str | None,
        peer_mac: str | None,
        peer_name: str | None,
    ) -> str | None:
        for prefix, value in (
            ("peer-radio", peer_radio_mac),
            ("ap", ap_mac),
            ("peer", peer_mac),
        ):
            normalized = self._mac_key(value)
            if normalized:
                return f"{prefix}:{normalized}"
        normalized_name = re.sub(r"\s+", " ", str(peer_name or "").strip()).casefold()
        return f"name:{normalized_name}" if normalized_name else None

    @staticmethod
    def _trackside_sequence_value(value: object, index: int) -> object | None:
        if not isinstance(value, (list, tuple)) or index >= len(value):
            return None
        return value[index]

    @staticmethod
    def _trackside_signal_data_source(peer_rssi: float | None, peer_signal: float | None) -> str:
        if peer_rssi is not None:
            return "peer_rssi_db"
        if peer_signal is not None:
            return "peer_signal_dbm"
        return ""

    def _prepare_chart_events(
        self,
        point_rows: list[dict[str, Any]],
        events_by_index: dict[object, object],
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        seen_events: set[int] = set()
        for event_index_value, values in events_by_index.items():
            event_index = self._int(event_index_value)
            for value in values if isinstance(values, list) else []:
                event = dict(value) if isinstance(value, dict) else {}
                event_id = int(event.get("id") or 0)
                if event_id in seen_events:
                    continue
                seen_events.add(event_id)
                before_point = self._chart_event_point(
                    point_rows,
                    event_index,
                    step=-1,
                    expected_peer_mac=str(event.get("from_peer_mac") or ""),
                )
                after_point = self._chart_event_point(
                    point_rows,
                    event_index,
                    step=1,
                    expected_peer_mac=str(event.get("to_peer_mac") or ""),
                )
                event_point = after_point or before_point
                busy_before_point = self._chart_busy_event_point(
                    point_rows,
                    event_index,
                    step=-1,
                    expected_peer_mac=str(event.get("from_peer_mac") or ""),
                )
                busy_after_point = self._chart_busy_event_point(
                    point_rows,
                    event_index,
                    step=1,
                    expected_peer_mac=str(event.get("to_peer_mac") or ""),
                )
                busy_event_point = busy_after_point or busy_before_point
                prepared.append(
                    {
                        "event": event,
                        "before_point": before_point,
                        "after_point": after_point,
                        "event_point": event_point,
                        "point_index": self._int((event_point or {}).get("index")),
                        "busy_event_point": busy_event_point,
                        "busy_point_index": self._int((busy_event_point or {}).get("index")),
                    }
                )
        return prepared

    @classmethod
    def _chart_render_budget(
        cls,
        total_points: int,
        requested_max_points: int,
        switch_indices: set[int],
    ) -> tuple[int, int, set[int], str | None]:
        requested = min(max(int(requested_max_points), 10), _MAX_CHART_RENDER_POINTS)
        valid_switches = {index for index in switch_indices if 0 <= index < total_points}
        if total_points <= requested:
            return requested, requested, valid_switches, None
        endpoints = {index for index in (0, total_points - 1) if 0 <= index < total_points}
        required_count = len(valid_switches | endpoints)
        if required_count <= _MAX_CHART_RENDER_POINTS:
            effective = max(requested, required_count)
            warning = None
            if effective > requested:
                warning = (
                    f"为保留全部 {len(valid_switches)} 个有效切换节点，"
                    f"图表目标点数已从 {requested} 提升到 {effective}。"
                )
            return requested, effective, valid_switches, warning
        available = max(_MAX_CHART_RENDER_POINTS - len(endpoints), 0)
        sampled_switches = cls._evenly_spread_indices(valid_switches - endpoints, available)
        rendered = (valid_switches & endpoints) | sampled_switches
        warning = (
            f"切换事件过多，已按时间均匀抽样显示 "
            f"{len(rendered)}/{len(valid_switches)} 个有效切换节点。"
        )
        return requested, _MAX_CHART_RENDER_POINTS, rendered, warning

    @staticmethod
    def _evenly_spread_indices(values: set[int], limit: int) -> set[int]:
        ordered = sorted(values)
        if limit <= 0 or not ordered:
            return set()
        if len(ordered) <= limit:
            return set(ordered)
        if limit == 1:
            return {ordered[len(ordered) // 2]}
        return {
            ordered[round(position * (len(ordered) - 1) / (limit - 1))]
            for position in range(limit)
        }

    @classmethod
    def _validate_chart_time_range(cls, time_from: str, time_to: str) -> None:
        start = cls._parse_time(time_from) if time_from else None
        end = cls._parse_time(time_to) if time_to else None
        if time_from and start is None:
            raise MeshAnalysisTimeRangeError("time_from 必须是包含毫秒的有效日志时间")
        if time_to and end is None:
            raise MeshAnalysisTimeRangeError("time_to 必须是包含毫秒的有效日志时间")
        if start is not None and end is not None and start >= end:
            raise MeshAnalysisTimeRangeError("time_from 必须早于 time_to")

    def _chart_location_segments(
        self,
        ap_map: MeshApLocationSnapshot,
        point_rows: list[dict[str, Any]],
    ) -> list[MeshChartLocationSegmentDTO]:
        segments: list[MeshChartLocationSegmentDTO] = []
        current: dict[str, Any] | None = None
        for row in point_rows:
            item = dict(row.get("item") or {})
            if str(item.get("status") or "") != "ACTIVE":
                current = None
                continue
            location = self._locate_ap(
                ap_map,
                {
                    "peer_ap_mac": item.get("ap_mac"),
                    "peer_ap_name": item.get("ap_name"),
                    "peer_mac_normalized": item.get("peer_mac"),
                    "peer_site": item.get("site"),
                },
            )
            station = location.station.strip()
            section = location.section.strip()
            if not station and not section:
                current = None
                continue
            key = (str(row.get("source") or ""), self._int(row.get("radio")), station, section)
            timestamp = str(row.get("timestamp") or "")
            if current is not None and not bool(row.get("gap_before")) and current["key"] == key:
                current["dto"].end_time = timestamp
                current["dto"].mileage_end = location.mileage or current["dto"].mileage_end
                continue
            label = " / ".join(value for value in (station, section) if value)
            dto = MeshChartLocationSegmentDTO(
                start_time=timestamp,
                end_time=timestamp,
                station=station or None,
                section=section or None,
                label=label,
                direction=location.line_side or None,
                mileage_start=location.mileage or None,
                mileage_end=location.mileage or None,
            )
            segments.append(dto)
            current = {"key": key, "dto": dto}
        return segments

    def _chart_event_point(
        self,
        point_rows: list[dict[str, Any]],
        event_index: int | None,
        *,
        step: int,
        expected_peer_mac: str,
    ) -> dict[str, Any] | None:
        if event_index is None or not point_rows:
            return None
        start = event_index if step > 0 else event_index - 1
        reference = point_rows[event_index] if 0 <= event_index < len(point_rows) else None
        reference_source = str((reference or {}).get("source") or "")
        reference_radio = (reference or {}).get("radio")
        index = start
        while 0 <= index < len(point_rows):
            row = point_rows[index]
            if str(row.get("source") or "") != reference_source or row.get("radio") != reference_radio:
                break
            item = dict(row.get("item") or {})
            peer_matches = not expected_peer_mac or self._mac_key(item.get("peer_mac")) == self._mac_key(expected_peer_mac)
            rssi = self._number(row.get("local_rssi"))
            if peer_matches and str(item.get("status") or "") == "ACTIVE" and rssi not in {None, 0}:
                return row
            index += step
        return None

    def _chart_busy_event_point(
        self,
        point_rows: list[dict[str, Any]],
        event_index: int | None,
        *,
        step: int,
        expected_peer_mac: str,
    ) -> dict[str, Any] | None:
        if event_index is None or not point_rows:
            return None
        start = event_index if step > 0 else event_index - 1
        reference = point_rows[event_index] if 0 <= event_index < len(point_rows) else None
        reference_source = str((reference or {}).get("source") or "")
        reference_radio = (reference or {}).get("radio")
        index = start
        while 0 <= index < len(point_rows):
            row = point_rows[index]
            if str(row.get("source") or "") != reference_source or row.get("radio") != reference_radio:
                break
            item = dict(row.get("item") or {})
            peer_matches = not expected_peer_mac or self._mac_key(item.get("peer_mac")) == self._mac_key(expected_peer_mac)
            has_busy = row.get("local_tx_busy") is not None or row.get("local_rx_busy") is not None
            if peer_matches and str(item.get("status") or "") == "ACTIVE" and has_busy:
                return row
            index += step
        return None

    @staticmethod
    def _chart_rows_in_window(value: object, time_from: str, time_to: str) -> list[dict[str, Any]]:
        rows = [dict(row) for row in (value or []) if isinstance(row, dict)]
        if time_from:
            rows = [row for row in rows if str(row.get("sample_time") or "") >= time_from]
        if time_to:
            rows = [row for row in rows if str(row.get("sample_time") or "") <= time_to]
        return rows

    @staticmethod
    def _chart_events_in_window(value: object, time_from: str, time_to: str) -> list[dict[str, Any]]:
        events = [dict(row) for row in (value or []) if isinstance(row, dict)]
        if time_from:
            events = [row for row in events if str(row.get("event_time") or "") >= time_from]
        if time_to:
            events = [row for row in events if str(row.get("event_time") or "") <= time_to]
        return events

    def _chart_backup_from_summary(
        self,
        ap_map: MeshApLocationSnapshot,
        row: dict[str, Any],
        public_source_id: int,
    ) -> MeshChartBackupLinkDTO:
        location = self._locate_ap(
            ap_map,
            {
                "peer_ap_mac": row.get("ap_mac"),
                "peer_ap_name": row.get("ap_name"),
                "peer_mac_normalized": row.get("peer_mac"),
                "peer_site": row.get("site"),
            },
        )
        return MeshChartBackupLinkDTO(
            link_id=self._int(row.get("link_id")),
            source_file_id=public_source_id,
            timestamp=str(row.get("sample_time") or ""),
            timestamp_tag=str(row.get("timestamp_tag") or ""),
            local_radio=self._int(row.get("radio")),
            peer_mac=str(row.get("peer_mac") or ""),
            peer_ap_name=self._resolved_ap_name(row, location),
            peer_ap_mac=self._resolved_ap_mac(row, location),
            peer_radio=str(row.get("peer_radio") or "") or None,
            peer_radio_mac=str(row.get("peer_radio_mac") or "") or None,
            **self._identity_payload(row, location),
            station=self._resolved_location_value(row, location, "station"),
            section=self._resolved_location_value(row, location, "section"),
            local_rssi=self._number(row.get("mr_rssi")),
            peer_rssi=self._number(row.get("ap_rssi")),
            local_signal=self._number(row.get("local_signal")),
            peer_signal=self._number(row.get("peer_signal")),
            local_tx_busy=self._number(row.get("local_tx_busy")),
            peer_tx_busy=self._number(row.get("peer_tx_busy")),
            local_rx_busy=self._number(row.get("local_rx_busy")),
            peer_rx_busy=self._number(row.get("peer_rx_busy")),
        )

    def _materialize_chart_point(
        self,
        ap_map: MeshApLocationSnapshot,
        context: _SessionContext,
        row: dict[str, Any],
    ) -> MeshChartPointDTO:
        item = dict(row.get("item") or {})
        segment = dict(row.get("segment") or {})
        location = self._locate_ap(
            ap_map,
            {
                "peer_ap_mac": item.get("ap_mac"),
                "peer_ap_name": item.get("ap_name"),
                "peer_mac_normalized": item.get("peer_mac"),
                "peer_site": item.get("site"),
            },
        )
        return MeshChartPointDTO(
            link_id=self._int(item.get("link_id")),
            source_file_id=context.source_id,
            timestamp=str(row.get("timestamp") or ""),
            timestamp_tag=str(row.get("timestamp_tag") or ""),
            local_radio=self._int(row.get("radio")),
            link_state=str(item.get("status") or ""),
            peer_mac=str(item.get("peer_mac") or ""),
            peer_ap_name=self._resolved_ap_name(item, location),
            peer_ap_mac=self._resolved_ap_mac(item, location),
            peer_radio=str(item.get("peer_radio") or "") or None,
            peer_radio_mac=str(item.get("peer_radio_mac") or "") or None,
            **self._identity_payload(item, location),
            station=self._resolved_location_value(item, location, "station"),
            section=self._resolved_location_value(item, location, "section"),
            local_rssi=self._number(row.get("local_rssi")),
            peer_rssi=self._number(row.get("peer_rssi")),
            local_signal=self._number(row.get("local_signal")),
            peer_signal=self._number(row.get("peer_signal")),
            local_tx_busy=self._number(row.get("local_tx_busy")),
            peer_tx_busy=self._number(row.get("peer_tx_busy")),
            local_rx_busy=self._number(row.get("local_rx_busy")),
            peer_rx_busy=self._number(row.get("peer_rx_busy")),
            establish_time=str(item.get("establish_time") or "") or None,
            segment_sequence=self._int(row.get("segment_sequence")),
            segment_start=str(segment.get("build_start_time") or "") or None,
            segment_end=str(segment.get("build_end_time") or "") or None,
            segment_duration_seconds=self._number(segment.get("main_link_duration_seconds")),
            is_switch=bool(row.get("is_switch")),
            is_anomaly=bool(row.get("is_anomaly")),
            gap_before=bool(row.get("gap_before")),
            backups=[
                self._chart_backup_from_summary(ap_map, dict(backup), context.source_id)
                for backup in row.get("backups") or []
            ],
        )

    def _chart_segment(
        self,
        segment_index: dict[
            tuple[int | None, int | None, str],
            tuple[list[str], list[dict[str, Any]]],
        ],
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        timestamp = str(row.get("sample_time") or "")
        source = self._int(row.get("source_file_id"))
        radio = self._int(row.get("radio"))
        peer = self._mac_key(row.get("peer_mac_normalized") or row.get("peer_mac_raw"))
        starts, segments = segment_index.get((source, radio, peer), ([], []))
        position = bisect_right(starts, timestamp) - 1
        if position < 0:
            return None
        segment = segments[position]
        return segment if timestamp <= str(segment.get("build_end_time") or "") else None

    def _chart_segment_index(
        self,
        segments: list[dict[str, Any]],
    ) -> dict[
        tuple[int | None, int | None, str],
        tuple[list[str], list[dict[str, Any]]],
    ]:
        grouped: dict[tuple[int | None, int | None, str], list[dict[str, Any]]] = defaultdict(list)
        for segment in segments:
            key = (
                self._int(segment.get("source_file_id")),
                self._int(segment.get("radio")),
                self._mac_key(segment.get("active_peer_mac")),
            )
            grouped[key].append(segment)
        result: dict[
            tuple[int | None, int | None, str],
            tuple[list[str], list[dict[str, Any]]],
        ] = {}
        for key, rows in grouped.items():
            ordered = sorted(rows, key=lambda item: str(item.get("build_start_time") or ""))
            result[key] = (
                [str(item.get("build_start_time") or "") for item in ordered],
                ordered,
            )
        return result

    @staticmethod
    def _important_chart_row_indices(points: list[dict[str, Any]]) -> set[int]:
        important = {
            index
            for index, point in enumerate(points)
            if point.get("is_switch") or point.get("is_anomaly") or point.get("gap_before")
        }
        for index in range(1, len(points)):
            if points[index].get("segment_sequence") != points[index - 1].get("segment_sequence"):
                important.update((index - 1, index))
        for field in ("local_rssi", "peer_rssi", "local_tx_busy", "local_rx_busy", "peer_tx_busy", "peer_rx_busy"):
            values = [(index, point.get(field)) for index, point in enumerate(points) if point.get(field) is not None]
            if values:
                important.add(min(values, key=lambda item: item[1])[0])
                important.add(max(values, key=lambda item: item[1])[0])
        return important

    @classmethod
    def _chart_array_number(cls, values: object, index: int) -> float | None:
        if values is None:
            return None
        try:
            number = cls._number(values[index])
        except (IndexError, KeyError, TypeError):
            return None
        return number if number is not None and math.isfinite(number) else None

    def _artifact_candidates(self, context: _SessionContext) -> list[_ArtifactCandidate]:
        result: list[_ArtifactCandidate] = []
        if context.raw_path is not None:
            path = context.raw_path
            stat = path.stat()
            relative = path.relative_to(context.mr_root).as_posix()
            dto = MeshReportArtifactDTO(
                artifact_id=self._artifact_id(
                    context.session_id,
                    "raw_mesh_log",
                    relative,
                ),
                artifact_type="raw_mesh_log",
                name=path.name,
                size_bytes=stat.st_size,
                modified_at=self._mtime(stat.st_mtime),
                deletable=False,
            )
            result.append(_ArtifactCandidate(dto=dto, path=path))
        for artifact in self._bound_report_artifacts(context):
            if (
                not artifact.completed
                or not artifact.path.is_file()
                or artifact.path.is_symlink()
            ):
                continue
            stat = artifact.path.stat()
            kind = (
                "analysis_report"
                if artifact.path.suffix.casefold() == ".xlsx"
                else "package"
            )
            result.append(
                _ArtifactCandidate(
                    dto=MeshReportArtifactDTO(
                        artifact_id=artifact.artifact_id,
                        artifact_type=kind,
                        name=artifact.display_name,
                        size_bytes=stat.st_size,
                        modified_at=self._mtime(stat.st_mtime),
                        deletable=True,
                    ),
                    path=artifact.path,
                    manifest_path=artifact.manifest_path,
                )
            )
        return sorted(result, key=lambda item: (item.dto.artifact_type, item.dto.name))

    def session_report_delete_targets(
        self,
        site_id: str,
        session_id: str,
    ) -> tuple[list[Path], int]:
        context = self._context(site_id, session_id)
        targets: list[Path] = []
        report_count = 0
        for artifact in self._bound_report_artifacts(context):
            report_count += int(artifact.path.is_file())
            targets.append(artifact.path)
            targets.append(artifact.manifest_path)
        return list(dict.fromkeys(targets)), report_count

    def _bound_report_artifacts(
        self,
        context: _SessionContext,
    ) -> list[_BoundReportArtifact]:
        manifest_root = (
            self.paths.rail_transit_root(context.site_id)
            / "web_artifacts"
            / "manifests"
        ).resolve()
        if not manifest_root.is_dir():
            return []
        site_root = self.paths.site_dir(context.site_id).resolve()
        output_root = self.paths.mesh_mr_export_dir(
            context.site_id,
            context.safe_folder_name,
        ).resolve()
        expected_types = {
            "mesh_analysis_report": "web_export_mesh_analysis_report",
            "mesh_link_detail_export": "web_export_mesh_link_detail_export",
        }
        artifacts: list[_BoundReportArtifact] = []
        for manifest_path in manifest_root.glob("*.json"):
            if manifest_path.is_symlink():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                artifact_id = str(UUID(str(data.get("artifact_id") or "")))
                if manifest_path.resolve() != (manifest_root / f"{artifact_id}.json").resolve():
                    continue
                source = str(data.get("source") or "")
                context_data = data.get("context")
                if (
                    data.get("site_id") != context.site_id
                    or data.get("owner") != "web_rail_transit"
                    or data.get("task_source") != "local"
                    or expected_types.get(source) != data.get("task_type")
                    or not isinstance(context_data, dict)
                    or context_data.get("kind") != "mesh_analysis_session"
                    or context_data.get("session_id") != context.session_id
                ):
                    continue
                relative = Path(str(data.get("relative_path") or ""))
                if relative.is_absolute():
                    continue
                output = (site_root / relative).resolve()
                if (
                    not self._within(output, output_root)
                    or output.suffix.casefold() not in _ALLOWED_OUTPUT_SUFFIXES
                    or output.name != str(data.get("file_name") or "")
                ):
                    continue
                artifacts.append(
                    _BoundReportArtifact(
                        artifact_id=artifact_id,
                        artifact_type=str(data.get("artifact_type") or ""),
                        display_name=str(
                            data.get("display_name")
                            or data.get("file_name")
                            or output.name
                        ),
                        path=output,
                        manifest_path=manifest_path.resolve(),
                        completed=data.get("completed") is True,
                    )
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return artifacts

    def ap_location_snapshot(self, site_id: str) -> MeshApLocationSnapshot:
        try:
            return self.location_service.snapshot(site_id)
        except (OSError, ValueError, sqlite3.Error):
            return MeshApLocationSnapshot()

    def _ap_map(self, site_id: str) -> MeshApLocationSnapshot:
        return self.ap_location_snapshot(site_id)

    @staticmethod
    def _locate_ap(ap_map: MeshApLocationSnapshot, row: dict[str, Any]) -> MeshApLocation:
        return ap_map.resolve(row)

    @classmethod
    def _identity_payload(
        cls,
        row: dict[str, Any],
        location: MeshApLocation | None = None,
    ) -> dict[str, Any]:
        physical_mac = str(
            row.get("canonical_ap_mac")
            or row.get("peer_ap_mac")
            or row.get("ap_mac")
            or (location.mac if location is not None else "")
            or ""
        ).strip()
        explicit_status = str(
            row.get("peer_identity_status")
            or row.get("identity_status")
            or ""
        ).strip().casefold()
        if explicit_status in {"matched", "unresolved", "ambiguous"}:
            status = explicit_status
        elif (
            location is not None
            and location.identity_status == "ambiguous"
        ):
            status = "ambiguous"
        else:
            status = "unresolved"
        if status == "matched" and not physical_mac:
            status = "unresolved"
        source = str(
            row.get("peer_identity_source")
            or row.get("identity_source")
            or row.get("peer_resolve_source")
            or (location.identity_source if location is not None else "")
            or ""
        ).strip()
        rule = str(
            row.get("peer_match_rule")
            or row.get("identity_rule")
            or row.get("match_rule")
            or ""
        ).strip()
        reason = str(
            row.get("peer_identity_reason")
            or row.get("identity_reason")
            or (location.identity_reason if location is not None else "")
            or ""
        ).strip()
        confidence = cls._int(
            row.get("peer_match_confidence")
            if row.get("peer_match_confidence") is not None
            else row.get("identity_confidence")
        ) or 0
        return {
            "identity_status": status,
            "identity_source": source or None,
            "identity_rule": rule or None,
            "identity_confidence": confidence,
            "identity_reason": reason or None,
        }

    @classmethod
    def _resolved_ap_mac(
        cls,
        row: dict[str, Any],
        location: MeshApLocation | None = None,
    ) -> str | None:
        if cls._identity_payload(row, location)["identity_status"] != "matched":
            return None
        return (
            str(
                row.get("canonical_ap_mac")
                or row.get("peer_ap_mac")
                or row.get("ap_mac")
                or (location.mac if location is not None else "")
                or ""
            ).strip()
            or None
        )

    @classmethod
    def _resolved_ap_name(
        cls,
        row: dict[str, Any],
        location: MeshApLocation | None = None,
    ) -> str | None:
        if cls._resolved_ap_mac(row, location) is None:
            return None
        return (
            str(
                row.get("resolved_ap_name")
                or row.get("peer_ap_name")
                or row.get("ap_name")
                or (location.name if location is not None else "")
                or ""
            ).strip()
            or None
        )

    @classmethod
    def _resolved_location_value(
        cls,
        row: dict[str, Any],
        location: MeshApLocation | None,
        field: str,
    ) -> str | None:
        if cls._resolved_ap_mac(row, location) is None:
            return None
        fallback_fields = {
            "station": ("peer_site", "station", "belong_station"),
            "section": ("peer_section", "section", "belong_section"),
            "mileage": ("mileage",),
            "line_side": ("line_side",),
        }
        location_value = str(getattr(location, field, "") if location is not None else "").strip()
        if location_value:
            return location_value
        return next(
            (
                str(row.get(key) or "").strip()
                for key in fallback_fields.get(field, ())
                if str(row.get(key) or "").strip()
            ),
            None,
        )

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
    def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
        escaped = table.replace('"', '""')
        return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{escaped}")')}

    @classmethod
    def _mesh_schema_version(cls, conn: sqlite3.Connection) -> str | None:
        for table in ("schema_meta", "meta"):
            if not cls._table_exists(conn, table) or not {"key", "value"}.issubset(cls._table_columns(conn, table)):
                continue
            for key in ("schema_version", "schema_" + "version"):
                row = conn.execute(f"SELECT value FROM {table} WHERE key = ? LIMIT 1", (key,)).fetchone()
                if row and row[0] not in (None, ""):
                    return str(row[0])
        return None

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

    @staticmethod
    def _int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
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
    def _temporary_artifact_name(name: str) -> bool:
        lowered = str(name or "").casefold()
        return lowered.startswith(".") or lowered.endswith((".part", ".partial")) or ".tmp." in lowered

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
