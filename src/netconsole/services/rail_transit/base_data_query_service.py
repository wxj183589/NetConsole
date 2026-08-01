from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import sqlite3
import time
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, TypeVar
from uuid import NAMESPACE_URL, uuid5

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import (
    DataQualityEntityGroupDTO,
    DataQualityEntityGroupPageDTO,
    DataQualityIssueDTO,
    DataQualityIssuePageDTO,
    MileageDTO,
    MeshRadioDTO,
    RailTransitRelationDTO,
    RailTransitRelationPageDTO,
    RailTransitSummaryDTO,
    RelatedRuntimeStatusDTO,
    SectionDTO,
    SectionPageDTO,
    StationDTO,
    StationPageDTO,
    TracksideApDTO,
    TracksideApDetailDTO,
    TracksideApPageDTO,
    TrainDTO,
    TrainDetailDTO,
    TrainPageDTO,
    VehicleMrDTO,
    VehicleMrDetailDTO,
    VehicleMrPageDTO,
)
from netconsole.models.device import Device
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac, normalize_mac_key
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.ap_line_side_service import (
    derive_ap_line_side,
    line_side_metadata,
)
from netconsole.services.rail_transit.source_policy import is_blocking_issue
from netconsole.services.rail_transit.mr_end_role_service import mr_position
from netconsole.services.rail_transit.station_source_utils import (
    DEFAULT_MAIN_PATH_CODE,
    DEFAULT_STATION_SOURCE_GROUP,
    STATION_SOURCE_FIELD,
    normalize_track_facilities,
    normalize_station_source_value,
    parse_station_source_value,
)
from netconsole.services.rail_transit.trackside_ap_location import (
    NON_MAINLINE_LOCATION_CLASSES,
    resolve_trackside_ap_location,
)
from netconsole.utils.mileage import parse_track_mileage


T = TypeVar("T")
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "": 3}
_LOGGER = logging.getLogger(__name__)
_AP_FIELDS = (
    "id",
    "belong_type",
    "line_name",
    "system_type",
    "network_domain",
    "station_name",
    "section_name",
    "line_side",
    "direction",
    "location_class",
    "participates_in_mainline",
    "location_class_source",
    "mileage_text",
    "mileage_m",
    "distance_to_prev_m",
    "ap_point_code",
    "ap_name",
    "ap_vendor",
    "ap_mac_norm",
    "ap_mac_display",
    "yard_name",
    "area_name",
    "curve_radius_m",
    "curve_start_text",
    "curve_end_text",
    "install_scene",
    "location_desc",
    "power_station",
    "power_distribution",
    "fiber_access_station",
    "fiber_distribution",
    "uplink_switch",
    "uplink_port",
    "optical_port",
    "remark",
    "source_file",
    "source_sheet",
    "source_row",
    "updated_at",
    "section_start_station",
    "section_end_station",
    "raw_payload_json",
)
_DEVICE_FIELDS = (
    "id",
    "device_uuid",
    "name",
    "system_name",
    "mac_address",
    "station",
    "location",
    "group_id",
    "device_vendor",
    "device_type",
    "primary_address",
    "backup_address",
    "protocol",
    "port",
    "remark",
    "created_at",
    "updated_at",
)


def _parse_train_identity_from_device(device: Device):
    from netconsole.services.vehicle_mr_online import parse_train_identity_from_device

    return parse_train_identity_from_device(device)


class RailTransitBaseDataQueryService:
    """轨道交通基础资料 GET-only 查询边界，不初始化或修改数据库。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        ac_query: AcManagementQueryService | None = None,
        mesh_query: AcMeshLinkQueryService | None = None,
        online_mr_query: OnlineMrQueryService | None = None,
    ) -> None:
        self.paths = paths
        self.ac_query = ac_query or AcManagementQueryService(paths)
        self.mesh_query = mesh_query or AcMeshLinkQueryService(paths)
        self.online_mr_query = online_mr_query or OnlineMrQueryService(paths)

    def current_site_id(self) -> str:
        return self.ac_query.current_site_id()

    def get_summary(self, site_id: str) -> RailTransitSummaryDTO:
        meta = self._site_meta(site_id)
        increasing_direction_leading_end = str(meta.get("increasing_direction_leading_end") or "unknown")
        if increasing_direction_leading_end not in {"car_1_end", "car_6_end", "unknown"}:
            increasing_direction_leading_end = "unknown"
        points = self._all_points(site_id, include_runtime=False)
        aps = [item for item in points if self._is_ap_record(item)]
        stations = self._stations(points, site_id=site_id)
        sections = self._sections(points)
        mrs = self._all_mrs(site_id, include_runtime=False)
        trains = self._trains(mrs, self._issues(site_id, aps=aps, mrs=mrs))
        issues = self._issues(site_id, aps=aps, mrs=mrs)
        codes = Counter(issue.code for issue in issues)
        has_formal_stations = any(station.source_kind != "legacy_ap_derived" for station in stations)
        if has_formal_stations:
            message = "已维护正式线路与站点基础资料，可从设备管理站点字段生成初稿并人工确认。"
        elif stations:
            message = "当前站点包含 AP 旧资料派生结果，可从设备管理站点字段生成初稿后再确认保存。"
        else:
            message = "当前暂无正式站点资料，可从设备管理中分组为“车站”的设备 station 字段生成初稿。"
        return RailTransitSummaryDTO(
            site_id=site_id,
            site_name=str(meta.get("display_name") or site_id),
            line_name=str(meta.get("line_name") or self._first(aps, "line_name") or ""),
            project_type=str(meta.get("system_type") or ""),
            network_type=str(meta.get("network_domain") or ""),
            main_path_code=str(meta.get("main_path_code") or DEFAULT_MAIN_PATH_CODE),
            increasing_direction_name=str(meta.get("increasing_direction_name") or "上行"),
            decreasing_direction_name=str(meta.get("decreasing_direction_name") or "下行"),
            increasing_direction_line_side=str(meta.get("increasing_direction_line_side") or "右线"),
            decreasing_direction_line_side=str(meta.get("decreasing_direction_line_side") or "左线"),
            increasing_direction_leading_end=increasing_direction_leading_end,
            station_source_group_name=str(meta.get("station_source_group_name") or DEFAULT_STATION_SOURCE_GROUP),
            station_source_field=STATION_SOURCE_FIELD,
            remark=str(meta.get("remark") or ""),
            created_at=str(meta.get("created_at") or ""),
            updated_at=max(
                [str(meta.get("updated_at") or ""), *(item.updated_at for item in aps)],
                default="",
            ),
            station_count=len(stations),
            normal_station_count=sum(station.node_type == "station" for station in stations),
            special_node_count=sum(station.node_type != "station" for station in stations),
            source_pending_count=sum(station.source_sync_status in {"manual", "legacy", "unavailable"} for station in stations),
            source_conflict_count=sum(station.source_sync_status == "conflict" for station in stations),
            source_stale_count=sum(station.source_sync_status == "stale" for station in stations),
            section_count=len(sections),
            ap_count=len(aps),
            train_count=len(trains),
            mr_count=len(mrs),
            missing_location_ap_count=codes["ap_location_missing"],
            invalid_mileage_count=codes["ap_mileage_invalid"],
            duplicate_ap_mac_count=codes["ap_mac_duplicate"],
            duplicate_static_ip_count=codes["static_ip_duplicate"],
            unbound_mr_count=codes["mr_train_unbound"],
            issue_count=len(issues),
            message=message,
        )

    def list_stations(
        self, site_id: str, *, query: str = "", page: int = 1, page_size: int = 50, sort_order: str = "asc"
    ) -> StationPageDTO:
        items = self._stations(self._all_points(site_id, include_runtime=False), site_id=site_id)
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.code} {item.source_station_value}".casefold()]
        items.sort(key=lambda item: (item.sort_order is None, item.sort_order or 0, item.name), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return StationPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_sections(
        self,
        site_id: str,
        *,
        station: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_order: str = "asc",
    ) -> SectionPageDTO:
        items = self._sections(self._all_points(site_id, include_runtime=False))
        if station:
            needle = station.casefold()
            items = [
                item
                for item in items
                if needle in f"{item.start_station} {item.end_station} {item.name}".casefold()
            ]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.start_station} {item.end_station}".casefold()]
        items.sort(key=lambda item: (item.mileage_min is None, item.mileage_min or 0, item.name), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return SectionPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_aps(
        self,
        site_id: str,
        *,
        station: str = "",
        section: str = "",
        line_side: str = "",
        query: str = "",
        has_issue: bool | None = None,
        issue_severity: str = "",
        fit_ap_status: str = "",
        optical_status: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> TracksideApPageDTO:
        # The list view only needs the current page. Keep detail/export paths on
        # the existing complete projection, but avoid loading every AP, AC
        # detail, MESH link, and quality issue before slicing the page.
        fast_page = self._list_aps_sql_first(
            site_id,
            station=station,
            section=section,
            line_side=line_side,
            query=query,
            has_issue=has_issue,
            issue_severity=issue_severity,
            fit_ap_status=fit_ap_status,
            optical_status=optical_status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        if fast_page is not None:
            return fast_page
        items = self._all_aps(site_id, include_runtime=True)
        issues = self._issues(site_id, aps=self._all_aps(site_id, include_runtime=False), mrs=self._all_mrs(site_id, include_runtime=False))
        issues.extend(self._runtime_ap_issues(items))
        issue_map = self._issue_map(issues, "ap")
        items = [self._with_ap_issues(item, issue_map.get(item.id, [])) for item in items]
        for field, value in (("station", station), ("section", section), ("line_side", line_side)):
            if value:
                needle = value.casefold()
                items = [item for item in items if needle in str(getattr(item, field)).casefold()]
        if fit_ap_status:
            items = [item for item in items if item.runtime.fit_ap_status == fit_ap_status]
        if optical_status:
            items = [item for item in items if item.runtime.optical_status == optical_status]
        if query:
            if normalize_mac_key(query):
                identity_rows = ApIdentityQueryService(
                    Database(self.paths.site_db_path(site_id))
                ).search_aps(query)
                base_ids = {
                    str(row.get("base_record_id") or "")
                    for row in identity_rows
                    if row.get("base_record_id")
                }
                items = [item for item in items if str(item.id) in base_ids]
            else:
                needle = query.casefold()
                items = [
                    item
                    for item in items
                    if needle
                    in f"{item.name} {item.point_code} {item.mac} {item.management_ip}".casefold()
                ]
        if has_issue is not None:
            items = [item for item in items if (item.issue_count > 0) is has_issue]
        if issue_severity:
            items = [item for item in items if item.highest_issue_severity == issue_severity]
        items.sort(key=lambda item: self._ap_sort_key(item, sort_by), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return TracksideApPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def _list_aps_sql_first(
        self,
        site_id: str,
        *,
        station: str,
        section: str,
        line_side: str,
        query: str,
        has_issue: bool | None,
        issue_severity: str,
        fit_ap_status: str,
        optical_status: str,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
    ) -> TracksideApPageDTO | None:
        started = time.perf_counter()
        path = self.paths.site_db_path(site_id)
        if not path.is_file():
            return TracksideApPageDTO(items=[], total=0, page=max(1, int(page)), page_size=max(1, min(int(page_size), 200)))
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        post_filter = bool(
            fit_ap_status
            or optical_status
            or has_issue is not None
            or issue_severity
        )
        clauses = [
            "COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')",
            (
                "(trim(COALESCE(ap_name, '')) <> '' "
                "OR trim(COALESCE(ap_mac_norm, '')) <> '' "
                "OR trim(COALESCE(ap_mac_display, '')) <> '' "
                "OR trim(COALESCE(ap_point_code, '')) NOT IN ('', '-'))"
            ),
        ]
        params: list[object] = []
        for field, value in (("station_name", station), ("section_name", section), ("line_side", line_side)):
            text = str(value or "").strip()
            if text:
                clauses.append(f"COALESCE({field}, '') LIKE ? COLLATE NOCASE")
                params.append(f"%{text}%")
        keyword = str(query or "").strip()
        if keyword and not normalize_mac_key(keyword):
            clauses.append(
                "(COALESCE(ap_name, '') LIKE ? COLLATE NOCASE OR "
                "COALESCE(ap_point_code, '') LIKE ? COLLATE NOCASE OR "
                "COALESCE(ap_mac_display, '') LIKE ? COLLATE NOCASE)"
            )
            params.extend([f"%{keyword}%"] * 3)
        elif keyword:
            normalized = normalize_mac_key(keyword)
            identity_rows = ApIdentityQueryService(Database(path)).search_aps(keyword)
            base_ids = sorted(
                {
                    str(row.get("base_record_id") or "").removeprefix("ap:")
                    for row in identity_rows
                    if str(row.get("base_record_id") or "").removeprefix("ap:")
                }
            )
            physical_clause = (
                "replace(replace(replace(lower(COALESCE(ap_mac_norm, ap_mac_display, '')), "
                "':', ''), '-', ''), ' ', '') = ?"
            )
            if base_ids:
                placeholders = ", ".join("?" for _ in base_ids)
                clauses.append(
                    f"({physical_clause} OR CAST(id AS TEXT) IN ({placeholders}))"
                )
                params.extend([normalized, *base_ids])
            else:
                clauses.append(physical_clause)
                params.append(normalized)
        where = " AND ".join(clauses)
        sort_map = {
            "name": "COALESCE(ap_name, '')",
            "station": "COALESCE(station_name, '')",
            "section": "COALESCE(section_name, '')",
            "mileage": "mileage_m",
            "updated_at": "COALESCE(updated_at, '')",
        }
        sort_column = sort_map.get(sort_by, sort_map["name"])
        direction = "DESC" if sort_order == "desc" else "ASC"
        selected_fields = [field for field in _AP_FIELDS]
        base_query_started = time.perf_counter()
        with closing(self._connect(path)) as conn:
            wal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(ap_extension_points)")}
            selected = [field for field in selected_fields if field in columns]
            if "id" not in selected:
                return None
            sql_fields = ", ".join(f'"{field}"' for field in selected)
        base_query_ms = (time.perf_counter() - base_query_started) * 1000
        count_started = time.perf_counter()
        with closing(self._connect(path)) as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM ap_extension_points WHERE {where}",
                params,
            ).fetchone()
            total = int(total_row[0] if total_row else 0)
        count_ms = (time.perf_counter() - count_started) * 1000
        page_sql_ms = 0.0
        dto_ms = 0.0
        runtime_join_ms = 0.0
        issue_join_ms = 0.0

        def project_rows(raw_rows: list[sqlite3.Row]) -> list[TracksideApDTO]:
            nonlocal dto_ms, runtime_join_ms, issue_join_ms
            dto_started = time.perf_counter()
            base_items = self._points_from_rows(site_id, [dict(row) for row in raw_rows])
            dto_ms += (time.perf_counter() - dto_started) * 1000
            runtime_started = time.perf_counter()
            enriched = self._attach_runtime_for_page(site_id, base_items)
            runtime_join_ms += (time.perf_counter() - runtime_started) * 1000
            issue_started = time.perf_counter()
            issues = self._issues_for_page(site_id, enriched)
            issue_map = self._issue_map(issues, "ap")
            enriched = [
                self._with_ap_issues(item, issue_map.get(item.id, []))
                for item in enriched
            ]
            issue_join_ms += (time.perf_counter() - issue_started) * 1000
            return enriched

        filtered_items: list[TracksideApDTO] = []
        if post_filter:
            batch_size = 200
            offset = 0
            while offset < total:
                page_sql_started = time.perf_counter()
                with closing(self._connect(path)) as conn:
                    rows = conn.execute(
                        f"SELECT {sql_fields} FROM ap_extension_points WHERE {where} "
                        f"ORDER BY {sort_column} {direction}, id ASC LIMIT ? OFFSET ?",
                        [*params, batch_size, offset],
                    ).fetchall()
                page_sql_ms += (time.perf_counter() - page_sql_started) * 1000
                if not rows:
                    break
                batch = project_rows(rows)
                if fit_ap_status:
                    batch = [
                        item
                        for item in batch
                        if item.runtime.fit_ap_status == fit_ap_status
                    ]
                if optical_status:
                    batch = [
                        item
                        for item in batch
                        if item.runtime.optical_status == optical_status
                    ]
                if has_issue is not None:
                    batch = [
                        item
                        for item in batch
                        if (item.issue_count > 0) is has_issue
                    ]
                if issue_severity:
                    batch = [
                        item
                        for item in batch
                        if item.highest_issue_severity == issue_severity
                    ]
                filtered_items.extend(batch)
                offset += len(rows)
            total = len(filtered_items)
            start = (current_page - 1) * size
            result_items = filtered_items[start : start + size]
        else:
            page_sql_started = time.perf_counter()
            with closing(self._connect(path)) as conn:
                rows = conn.execute(
                    f"SELECT {sql_fields} FROM ap_extension_points WHERE {where} "
                    f"ORDER BY {sort_column} {direction}, id ASC LIMIT ? OFFSET ?",
                    [*params, size, (current_page - 1) * size],
                ).fetchall()
            page_sql_ms = (time.perf_counter() - page_sql_started) * 1000
            result_items = project_rows(rows)

        total_ms = (time.perf_counter() - started) * 1000
        if total_ms > 2000:
            _LOGGER.warning(
                "base-data/aps slow query base_query_ms=%.1f count_ms=%.1f "
                "page_sql_ms=%.1f runtime_join_ms=%.1f issue_join_ms=%.1f "
                "dto_ms=%.1f total_ms=%.1f returned_rows=%s total_rows=%s "
                "wal_mode=%s lock_wait_ms=%.1f",
                base_query_ms,
                count_ms,
                page_sql_ms,
                runtime_join_ms,
                issue_join_ms,
                dto_ms,
                total_ms,
                len(result_items),
                total,
                wal_mode,
                0.0,
            )
        return TracksideApPageDTO(
            items=result_items,
            total=total,
            page=current_page,
            page_size=size,
        )

    def _points_from_rows(self, site_id: str, rows: list[dict[str, Any]]) -> list[TracksideApDTO]:
        # Reuse the canonical DTO construction and line-side derivation with no
        # runtime readers. This keeps SQL paging separate from identity logic.
        formal_sections: list[dict[str, Any]] = []
        path = self.paths.site_db_path(site_id)
        if path.is_file():
            with closing(self._connect(path)) as conn:
                columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(ap_extension_points)")}
                selected = [field for field in _AP_FIELDS if field in columns]
                if selected:
                    sql_fields = ", ".join(f'"{field}"' for field in selected)
                    formal_sections = [
                        dict(row)
                        for row in conn.execute(
                            f"""
                            SELECT {sql_fields}
                            FROM ap_extension_points
                            WHERE belong_type = '__base_section__'
                            """
                        )
                    ]
        return [
            item
            for item in self._all_points(
                site_id,
                include_runtime=False,
                rows=[*rows, *formal_sections],
            )
            if self._is_ap_record(item)
        ]

    def _attach_runtime_for_page(
        self,
        site_id: str,
        items: list[TracksideApDTO],
    ) -> list[TracksideApDTO]:
        macs = [item.mac for item in items if self._mac_key(item.mac)]
        ac_by_mac: dict[str, list[Any]] = defaultdict(list)
        try:
            loader = getattr(self.ac_query, "list_ap_details_for_macs", None)
            details = loader(site_id, macs) if callable(loader) else []
            for detail in details:
                mac_key = self._mac_key(detail.ap.mac)
                if mac_key:
                    ac_by_mac[mac_key].append(detail)
        except (OSError, ValueError, sqlite3.Error):
            pass
        mesh_by_mac: dict[str, dict[str, object]] = {}
        try:
            loader = getattr(self.mesh_query, "current_link_summaries_for_ap_macs", None)
            if callable(loader):
                mesh_by_mac = loader(site_id, macs)
        except (OSError, ValueError, sqlite3.Error):
            pass
        result: list[TracksideApDTO] = []
        for item in items:
            mac_key = self._mac_key(item.mac)
            matches = ac_by_mac.get(mac_key, []) if mac_key else []
            ac = matches[0] if len(matches) == 1 else None
            mesh = mesh_by_mac.get(mac_key, {}) if mac_key else {}
            names_value = mesh.get("mr_names")
            names = sorted(str(value) for value in names_value) if isinstance(names_value, (set, list, tuple)) else []
            runtime = RelatedRuntimeStatusDTO(
                fit_ap_id=ac.ap.id if ac else "",
                fit_ap_ac_id=ac.ap.ac_id if ac else "",
                fit_ap_name=ac.ap.name if ac else "",
                fit_ap_match_status="matched" if ac else "conflict" if len(matches) > 1 else "unmatched",
                fit_ap_status=ac.ap.status if ac else "unknown",
                optical_status=ac.optical.optical_status if ac else "no_data",
                mesh_status="online" if mesh else "unknown",
                mesh_related_name="、".join(names),
                updated_at=max(
                    str(mesh.get("updated_at") or ""),
                    ac.ap.updated_at if ac else "",
                ),
            )
            result.append(
                item.model_copy(
                    update={
                        "management_ip": ac.ap.ip if ac else "",
                        "model": ac.ap.model if ac else "",
                        "radios": [],
                        "runtime": runtime,
                    },
                    deep=True,
                )
            )
        return result

    def _issues_for_page(
        self,
        site_id: str,
        aps: list[TracksideApDTO],
    ) -> list[DataQualityIssueDTO]:
        page_macs = {self._mac_key(ap.mac) for ap in aps if self._mac_key(ap.mac)}
        mac_counts: Counter[str] = Counter()
        db_path = self.paths.site_db_path(site_id)
        if page_macs and db_path.is_file():
            placeholders = ", ".join("?" for _ in page_macs)
            expression = (
                "replace(replace(replace(lower(COALESCE(ap_mac_norm, ap_mac_display, '')), "
                "':', ''), '-', ''), ' ', '')"
            )
            with closing(self._connect(db_path)) as conn:
                rows = conn.execute(
                    f"""
                    SELECT {expression} AS mac_key, COUNT(*) AS row_count
                    FROM ap_extension_points
                    WHERE COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__')
                      AND {expression} IN ({placeholders})
                    GROUP BY {expression}
                    """,
                    sorted(page_macs),
                ).fetchall()
            mac_counts.update(
                {
                    str(row["mac_key"] or ""): int(row["row_count"] or 0)
                    for row in rows
                    if row["mac_key"]
                }
            )
        issues = self._ap_record_issues(aps, mac_counts=mac_counts)
        page_record_ids = {
            ap.id.removeprefix("ap:")
            for ap in aps
            if ap.id
        }
        issues.extend(
            issue
            for issue in self._identity_conflict_issues(site_id)
            if issue.entity_id.removeprefix("ap:") in page_record_ids
        )
        issues.extend(self._runtime_ap_issues(aps))
        return issues

    def list_ap_location_items(self, site_id: str) -> list[TracksideApDTO]:
        """一次返回 AP 位置基础字段，不拼接运行态、质量问题或分页结果。"""
        return self._all_aps(site_id, include_runtime=False)

    def list_ap_status_items(self, site_id: str) -> list[TracksideApDTO]:
        """返回轨旁 AP 基础资料及统一 AC/FIT-AP 运行态，不附加质量扫描。"""
        return self._all_aps(site_id, include_runtime=True)

    def list_ap_export_items(self, site_id: str) -> list[TracksideApDTO]:
        """一次返回导出所需的 AP 基础资料、运行态和质量摘要。"""
        items = self._all_aps(site_id, include_runtime=True)
        issues = self._issues(
            site_id,
            aps=self._all_aps(site_id, include_runtime=False),
            mrs=self._all_mrs(site_id, include_runtime=False),
        )
        issues.extend(self._runtime_ap_issues(items))
        issue_map = self._issue_map(issues, "ap")
        return [self._with_ap_issues(item, issue_map.get(item.id, [])) for item in items]

    def get_ap(self, site_id: str, ap_id: str) -> TracksideApDetailDTO | None:
        item = next((row for row in self._all_aps(site_id, include_runtime=True) if row.id == ap_id), None)
        if item is None:
            return None
        issues = [
            issue
            for issue in [*self._issues(site_id), *self._runtime_ap_issues([item])]
            if issue.entity_type == "ap" and issue.entity_id == ap_id
        ]
        return TracksideApDetailDTO(ap=self._with_ap_issues(item, issues), issues=issues)

    def list_mrs(
        self,
        site_id: str,
        *,
        train: str = "",
        mr_role: str = "",
        query: str = "",
        has_issue: bool | None = None,
        issue_severity: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "train_no",
        sort_order: str = "asc",
    ) -> VehicleMrPageDTO:
        items = self._all_mrs(site_id, include_runtime=True)
        issues = self._issues(site_id, aps=self._all_aps(site_id, include_runtime=False), mrs=self._all_mrs(site_id, include_runtime=False))
        issue_map = self._issue_map(issues, "mr")
        items = [self._with_mr_issues(item, issue_map.get(item.id, [])) for item in items]
        if train:
            needle = train.casefold()
            items = [item for item in items if needle in f"{item.train_id} {item.train_no}".casefold()]
        if mr_role:
            items = [item for item in items if item.mr_position_code.casefold() == mr_role.casefold()]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.management_ip} {item.mac} {item.device_id}".casefold()]
        if has_issue is not None:
            items = [item for item in items if (item.issue_count > 0) is has_issue]
        if issue_severity:
            items = [item for item in items if item.highest_issue_severity == issue_severity]
        items.sort(key=lambda item: self._mr_sort_key(item, sort_by), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return VehicleMrPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_mesh_import_context_mrs(self, site_id: str) -> list[VehicleMrDTO]:
        """导入弹窗只需身份字段，不拼接 MESH/Online MR 运行态与质量汇总。"""
        return self._all_mrs(site_id, include_runtime=False)

    def get_mr(self, site_id: str, mr_id: str) -> VehicleMrDetailDTO | None:
        item = next((row for row in self._all_mrs(site_id, include_runtime=True) if row.id == mr_id), None)
        if item is None:
            return None
        issues = [issue for issue in self._issues(site_id) if issue.entity_type == "mr" and issue.entity_id == mr_id]
        return VehicleMrDetailDTO(mr=self._with_mr_issues(item, issues), issues=issues)

    def list_trains(
        self,
        site_id: str,
        *,
        query: str = "",
        has_issue: bool | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_order: str = "asc",
    ) -> TrainPageDTO:
        mrs = self._all_mrs(site_id, include_runtime=True)
        items = self._trains(mrs, self._issues(site_id))
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.train_no}".casefold()]
        if has_issue is not None:
            items = [item for item in items if (item.issue_count > 0) is has_issue]
        items.sort(key=lambda item: self._natural_key(item.train_no), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return TrainPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def get_train(self, site_id: str, train_id: str) -> TrainDetailDTO | None:
        mrs = [item for item in self._all_mrs(site_id, include_runtime=True) if item.train_id == train_id]
        if not mrs:
            return None
        issues = [issue for issue in self._issues(site_id) if issue.entity_id in {train_id, *(item.id for item in mrs)}]
        train = self._trains(mrs, issues)[0]
        return TrainDetailDTO(train=train, mrs=mrs, issues=issues)

    def list_issues(
        self,
        site_id: str,
        *,
        severity: str = "",
        entity_type: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DataQualityIssuePageDTO:
        items = self._issues(site_id)
        if severity:
            items = [item for item in items if item.severity == severity]
        if entity_type:
            items = [item for item in items if item.entity_type == entity_type]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.entity_name} {item.code} {item.message} {item.original_value}".casefold()]
        items.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], item.entity_type, item.entity_name, item.code))
        selected, current, size = self._page(items, page, page_size)
        return DataQualityIssuePageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_issue_groups(
        self,
        site_id: str,
        *,
        blocking_only: bool | None = None,
        needs_confirmation_only: bool | None = None,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DataQualityEntityGroupPageDTO:
        issues = self._issues(site_id)
        grouped: dict[tuple[str, str], list[DataQualityIssueDTO]] = defaultdict(list)
        for issue in issues:
            grouped[(issue.entity_type, issue.entity_id)].append(issue)
        items = []
        for (entity_type, entity_id), rows in grouped.items():
            blocking = any(row.blocking for row in rows)
            needs_confirmation = not blocking and any(row.severity == "warning" for row in rows)
            actions = list(dict.fromkeys(row.suggested_action for row in rows if row.suggested_action))
            items.append(
                DataQualityEntityGroupDTO(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    display_name=next((row.entity_name for row in rows if row.entity_name), entity_id),
                    issue_count=len(rows),
                    error_count=sum(row.severity == "error" for row in rows),
                    warning_count=sum(row.severity == "warning" for row in rows),
                    info_count=sum(row.severity == "info" for row in rows),
                    blocking=blocking,
                    needs_confirmation=needs_confirmation,
                    issues=rows,
                    suggested_action="；".join(actions),
                )
            )
        if blocking_only is not None:
            items = [item for item in items if item.blocking is blocking_only]
        if needs_confirmation_only is not None:
            items = [item for item in items if item.needs_confirmation is needs_confirmation_only]
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle
                in f"{item.entity_type} {item.display_name} {item.suggested_action} {' '.join(row.code for row in item.issues)}".casefold()
            ]
        items.sort(key=lambda item: (not item.blocking, -item.error_count, -item.warning_count, item.display_name))
        selected, current, size = self._page(items, page, page_size)
        return DataQualityEntityGroupPageDTO(
            items=selected,
            total=len(items),
            issue_total=len(issues),
            blocking_total=sum(item.blocking for item in items),
            warning_total=sum(issue.severity == "warning" for issue in issues),
            info_total=sum(issue.severity == "info" for issue in issues),
            code_counts=dict(Counter(issue.code for issue in issues)),
            page=current,
            page_size=size,
        )

    def list_relations(
        self, site_id: str, *, query: str = "", page: int = 1, page_size: int = 50
    ) -> RailTransitRelationPageDTO:
        try:
            links = self.mesh_query.list_current_links(site_id, page=1, page_size=200).items
        except (OSError, ValueError, sqlite3.Error):
            links = []
        items = [
            RailTransitRelationDTO(
                mr_id=item.mr_device_id or item.mr_id,
                mr_name=item.mr_name,
                train_no=item.train_no,
                ap_id=item.peer_ap_id,
                ap_name=item.peer_ap_name,
                station=item.station,
                section=item.section,
                status=item.mr_online_status,
                updated_at=item.last_seen_at,
            )
            for item in links
        ]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.mr_name} {item.ap_name} {item.station} {item.section}".casefold()]
        selected, current, size = self._page(items, page, page_size)
        return RailTransitRelationPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def known_locations(self, site_id: str) -> tuple[set[str], set[str]]:
        points = self._all_points(site_id, include_runtime=False)
        return ({item.name for item in self._stations(points, site_id=site_id)}, {item.name for item in self._sections(points)})

    def _all_aps(self, site_id: str, *, include_runtime: bool) -> list[TracksideApDTO]:
        return [item for item in self._all_points(site_id, include_runtime=include_runtime) if self._is_ap_record(item)]

    def _all_points(
        self,
        site_id: str,
        *,
        include_runtime: bool,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[TracksideApDTO]:
        rows = rows if rows is not None else self._read_rows(site_id, "ap_extension_points", _AP_FIELDS)
        ac_by_mac: dict[str, list[Any]] = defaultdict(list)
        links_by_ap: dict[str, list[Any]] = defaultdict(list)
        if include_runtime:
            try:
                for detail in self.ac_query.list_all_ap_details(site_id):
                    mac_key = self._mac_key(detail.ap.mac)
                    if mac_key:
                        ac_by_mac[mac_key].append(detail)
            except (OSError, ValueError, sqlite3.Error):
                pass
            try:
                for link in self.mesh_query.list_current_links(site_id, page=1, page_size=200).items:
                    for key in (self._mac_key(link.peer_ap_mac), link.peer_ap_name.casefold()):
                        if key:
                            links_by_ap[key].append(link)
            except (OSError, ValueError, sqlite3.Error):
                pass
        result: list[TracksideApDTO] = []
        for row in rows:
            name = str(row.get("ap_name") or "")
            mac_key = self._mac_key(row.get("ap_mac_norm") or row.get("ap_mac_display"))
            ac_matches = ac_by_mac.get(mac_key, []) if mac_key else []
            ac = ac_matches[0] if len(ac_matches) == 1 else None
            links = links_by_ap.get(mac_key) or links_by_ap.get(name.casefold()) or []
            parsed = self._mileage(row.get("mileage_text"), row.get("mileage_m"))
            record_kind = str(row.get("belong_type") or "")
            (
                location_class,
                participates_in_mainline,
                location_class_source,
            ) = resolve_trackside_ap_location(row)
            location_class_conflict = bool(
                location_class in NON_MAINLINE_LOCATION_CLASSES
                and participates_in_mainline
            )
            base_metadata = self._base_metadata(row.get("raw_payload_json"))
            for field_name in (
                "belong_type", "system_type", "network_domain", "ap_vendor", "yard_name", "area_name",
                "distance_to_prev_m", "curve_radius_m", "curve_start_text", "curve_end_text",
                "install_scene", "location_desc", "power_station", "power_distribution",
                "fiber_access_station", "fiber_distribution", "uplink_switch", "uplink_port",
                "optical_port",
            ):
                value = row.get(field_name)
                if value not in (None, ""):
                    base_metadata[field_name] = value
            base_metadata.update(
                {
                    "location_class": location_class,
                    "participates_in_mainline": participates_in_mainline,
                    "location_class_source": location_class_source,
                }
            )
            radios = []
            if ac:
                radios = [
                    MeshRadioDTO(
                        radio_id=radio.radio_id,
                        channel=radio.channel,
                        bandwidth=radio.bandwidth,
                        power=radio.tx_power,
                        bssid=radio.bssid,
                    )
                    for radio in ac.radios
                    if radio.radio_id <= 2
                ]
            related_names = sorted({link.mr_name for link in links if link.mr_name})
            runtime = RelatedRuntimeStatusDTO(
                fit_ap_id=ac.ap.id if ac else "",
                fit_ap_ac_id=ac.ap.ac_id if ac else "",
                fit_ap_name=ac.ap.name if ac else "",
                fit_ap_match_status="matched" if ac else "conflict" if len(ac_matches) > 1 else "unmatched",
                fit_ap_status=ac.ap.status if ac else "unknown",
                optical_status=ac.optical.optical_status if ac else "no_data",
                mesh_status="online" if links else "unknown",
                mesh_related_name="、".join(related_names),
                updated_at=max([*(link.last_seen_at for link in links), ac.ap.updated_at if ac else ""], default=""),
            )
            result.append(
                TracksideApDTO(
                    id=f"ap:{row.get('id')}",
                    site_id=site_id,
                    line_name=str(row.get("line_name") or ""),
                    name=name,
                    point_code=str(row.get("ap_point_code") or ""),
                    vendor=str(row.get("ap_vendor") or ""),
                    mac=self._display_mac(row.get("ap_mac_norm") or row.get("ap_mac_display")),
                    management_ip=ac.ap.ip if ac else "",
                    model=ac.ap.model if ac else "",
                    station=str(row.get("station_name") or ""),
                    section=str(row.get("section_name") or ""),
                    section_start_station=str(row.get("section_start_station") or ""),
                    section_end_station=str(row.get("section_end_station") or ""),
                    mileage=parsed,
                    line_side=str(row.get("line_side") or ""),
                    direction=str(row.get("direction") or ""),
                    location_class=location_class,
                    participates_in_mainline=participates_in_mainline,
                    location_class_source=location_class_source,
                    location_class_conflict=location_class_conflict,
                    radios=radios,
                    remark=str(row.get("remark") or ""),
                    source_file=Path(str(row.get("source_file") or "")).name,
                    source_sheet=str(row.get("source_sheet") or ""),
                    source_row=self._int_or_none(row.get("source_row")),
                    updated_at=str(row.get("updated_at") or ""),
                    runtime=runtime,
                    record_kind=record_kind,
                    base_metadata=base_metadata,
                )
            )
        formal_sections = [
            section
            for section in self._sections(result)
            if section.source_kind != "legacy_ap_derived"
        ]
        site_metadata = self._site_meta(site_id)
        derived_result: list[TracksideApDTO] = []
        for item in result:
            if not self._is_ap_record(item):
                derived_result.append(item)
                continue
            derivation = derive_ap_line_side(
                item.model_dump(),
                formal_sections,
                site_metadata,
            )
            derived_result.append(
                item.model_copy(
                    update={
                        "line_side": derivation.line_side,
                        "line_side_source": derivation.source,
                        "line_side_derivation_issue_code": derivation.issue_code,
                        "line_side_derivation_issue_message": derivation.issue_message,
                        "base_metadata": line_side_metadata(item.base_metadata, derivation),
                    },
                    deep=True,
                )
            )
        return derived_result

    def _all_mrs(self, site_id: str, *, include_runtime: bool) -> list[VehicleMrDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            rows = self._select_rows(conn, "devices", _DEVICE_FIELDS)
            groups = {
                int(row["id"]): str(row["name"] or "")
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if row.get("id") is not None
            }
        has_mr_group = any("车载-MR" in name for name in groups.values())
        mesh_by_id: dict[str, Any] = {}
        mesh_by_name: dict[str, Any] = {}
        session_by_name: dict[str, Any] = {}
        if include_runtime:
            try:
                for item in self.mesh_query.list_mrs(site_id, page=1, page_size=200).items:
                    if item.mr_device_id:
                        mesh_by_id[item.mr_device_id] = item
                    mesh_by_name[item.mr_name.casefold()] = item
            except (OSError, ValueError, sqlite3.Error):
                pass
            try:
                for item in self.online_mr_query.list_sessions(site_id, limit=1000):
                    session_by_name.setdefault(item.mr_name.casefold(), item)
            except (OSError, ValueError, sqlite3.Error):
                pass
        result: list[VehicleMrDTO] = []
        for row in rows:
            group_name = groups.get(int(row.get("group_id") or 0), "")
            device = Device.from_mapping(row)
            identity = _parse_train_identity_from_device(device)
            if identity is None:
                continue
            if has_mr_group and "车载-MR" not in group_name:
                continue
            if not has_mr_group and "MR" not in f"{row.get('name')} {row.get('device_type')}".upper():
                continue
            item_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
            position_code, physical_end, car_number = mr_position(identity.car_end)
            mesh = mesh_by_id.get(item_id) or mesh_by_name.get(str(row.get("name") or "").casefold())
            session = session_by_name.get(str(row.get("name") or "").casefold())
            runtime = RelatedRuntimeStatusDTO(
                mesh_status=mesh.online_status if mesh else "unknown",
                mesh_related_name=mesh.peer_ap_name if mesh else "",
                latest_session_id=session.session_id if session else "",
                latest_session_status=session.status if session else "",
                updated_at=max(mesh.last_seen_at if mesh else "", session.started_at if session else ""),
            )
            result.append(
                VehicleMrDTO(
                    id=item_id,
                    device_id=self._int_or_none(row.get("id")),
                    name=str(row.get("name") or ""),
                    train_id=identity.train_id,
                    train_no=identity.train_no,
                    role=identity.car_end,
                    mr_position_code=position_code,
                    physical_end=physical_end,
                    car_number=car_number,
                    management_ip=str(row.get("primary_address") or ""),
                    station=str(row.get("station") or ""),
                    mac=self._display_mac(row.get("mac_address")),
                    protocol=str(row.get("protocol") or ""),
                    port=self._int_or_none(row.get("port")),
                    remark=str(row.get("remark") or ""),
                    runtime=runtime,
                )
            )
        return result

    def _issues(
        self,
        site_id: str,
        *,
        aps: list[TracksideApDTO] | None = None,
        mrs: list[VehicleMrDTO] | None = None,
    ) -> list[DataQualityIssueDTO]:
        aps = aps if aps is not None else self._all_aps(site_id, include_runtime=False)
        mrs = mrs if mrs is not None else self._all_mrs(site_id, include_runtime=False)
        ap_macs = Counter(self._mac_key(ap.mac) for ap in aps if self._mac_key(ap.mac))
        issues = self._ap_record_issues(aps, mac_counts=ap_macs)
        mr_macs = Counter(self._mac_key(mr.mac) for mr in mrs if self._mac_key(mr.mac))
        role_counts = Counter((mr.train_id, mr.role) for mr in mrs if mr.train_id and mr.role)
        for mr in mrs:
            if not mr.train_id:
                issues.append(self._issue("error", "mr_train_unbound", "mr", mr.id, mr.name, "train", "", "MR 未关联列车", "核对正式 MR 命名或设备分组"))
            mac_key = self._mac_key(mr.mac)
            if not mac_key:
                issues.append(self._issue("warning", "mr_mac_missing", "mr", mr.id, mr.name, "mac", mr.mac, "MR MAC 为空或格式无效", "补充有效 MR MAC"))
            elif mr_macs[mac_key] > 1:
                issues.append(self._issue("error", "mr_mac_duplicate", "mr", mr.id, mr.name, "mac", mr.mac, "同一局点存在重复 MR MAC", "核对车载 MR 资料"))
            if mr.train_id and mr.role and role_counts[(mr.train_id, mr.role)] > 1:
                issues.append(self._issue("error", "mr_role_duplicate", "mr", mr.id, mr.name, "role", mr.role, "同一列车存在重复 MR 角色", "核对列车 MR 配置"))
        issues.extend(self._unbound_mr_issues(site_id))
        issues.extend(self._static_ip_issues(site_id))
        points = self._all_points(site_id, include_runtime=False)
        stations = self._stations(points, site_id=site_id)
        sections = self._sections(points)
        issues.extend(self._station_issues(stations))
        issues.extend(self._section_issues(sections, stations))
        issues.extend(self._identity_conflict_issues(site_id))
        return issues

    def _ap_record_issues(
        self,
        aps: list[TracksideApDTO],
        *,
        mac_counts: Counter[str],
    ) -> list[DataQualityIssueDTO]:
        issues: list[DataQualityIssueDTO] = []
        for ap in aps:
            if not ap.name:
                issues.append(self._issue("warning", "ap_name_missing", "ap", ap.id, ap.name, "name", "", "AP 正式名称为空", "补充正式 AP 名称"))
            mac_key = self._mac_key(ap.mac)
            if not ap.mac:
                issues.append(self._issue("warning", "ap_mac_missing", "ap", ap.id, ap.name, "mac", "", "AP MAC 为空", "补充有效 AP MAC"))
            elif not mac_key:
                issues.append(self._issue("error", "ap_mac_invalid", "ap", ap.id, ap.name, "mac", ap.mac, "AP MAC 格式无效", "补充有效 AP MAC"))
            elif mac_counts[mac_key] > 1:
                issues.append(self._issue("error", "ap_mac_duplicate", "ap", ap.id, ap.name, "mac", ap.mac, "同一局点存在重复 AP MAC", "核对 AP 点表"))
            if not ap.station and not ap.section:
                issues.append(self._issue("warning", "ap_location_missing", "ap", ap.id, ap.name, "station/section", "", "AP 未填写站点或区间", "补充位置归属"))
            if ap.line_side_derivation_issue_code:
                issues.append(
                    self._issue(
                        "warning",
                        ap.line_side_derivation_issue_code,
                        "ap",
                        ap.id,
                        ap.name or ap.point_code,
                        "line_side",
                        ap.line_side,
                        ap.line_side_derivation_issue_message,
                        "核对归属区间、区间方向和线路方向来源",
                    )
                )
            if not ap.mileage.raw:
                issues.append(self._issue("warning", "ap_mileage_missing", "ap", ap.id, ap.name, "mileage", "", "AP 里程为空", "补充正式里程"))
            elif not ap.mileage.valid:
                issues.append(self._issue("error", "ap_mileage_invalid", "ap", ap.id, ap.name, "mileage", ap.mileage.raw, ap.mileage.error or "里程格式无效", "按现有 ZDK/YDK/CDK/RDK 格式修正"))
            expected = self._expected_prefix(ap.line_side, ap.direction)
            if ap.mileage.valid and expected and ap.mileage.line_type and expected != ap.mileage.line_type:
                issues.append(self._issue("warning", "ap_mileage_direction_mismatch", "ap", ap.id, ap.name, "mileage", ap.mileage.raw, "里程前缀与线路方向不一致", "核对线别和里程前缀"))
        return issues

    def _identity_conflict_issues(
        self,
        site_id: str,
    ) -> list[DataQualityIssueDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        try:
            rows = ApIdentityQueryService(Database(db_path)).list_conflicts()
        except sqlite3.Error:
            return []
        result: list[DataQualityIssueDTO] = []
        for row in rows:
            conflict_type = str(row.get("conflict_type") or "")
            field_name = (
                "mac" if conflict_type == "ap_mac_mismatch" else "name"
            )
            ac_value = str(row.get("ac_value") or "")
            base_value = str(row.get("base_value") or "")
            base_record_id = str(row.get("base_record_id") or "")
            entity_id = (
                base_record_id
                if base_record_id.startswith("ap:")
                else f"ap:{base_record_id}"
                if base_record_id
                else str(row.get("entity_id") or "")
            )
            result.append(
                self._issue(
                    "warning",
                    "AP_IDENTITY_AC_BASE_CONFLICT",
                    "ap",
                    entity_id,
                    str(row.get("effective_ap_name") or ""),
                    field_name,
                    base_value,
                    (
                        f"AC 与基础资料 AP {field_name.upper()} 不一致；"
                        f"当前使用 AC 值 {ac_value}"
                    ),
                    "核对基础资料并按 AC 现场事实更新；该问题不阻断 MESH 分析",
                )
            )
        return result

    def _runtime_ap_issues(self, aps: list[TracksideApDTO]) -> list[DataQualityIssueDTO]:
        return [
            self._issue(
                "error",
                "fit_ap_mac_ambiguous",
                "ap",
                ap.id,
                ap.runtime.fit_ap_name or ap.name or ap.point_code,
                "mac",
                ap.mac,
                "同一 AP MAC 匹配到多个 AC FIT-AP，未自动关联",
                "核对 AC FIT-AP 资源中的重复 MAC",
            )
            for ap in aps
            if ap.runtime.fit_ap_match_status == "conflict"
        ]

    def _unbound_mr_issues(self, site_id: str) -> list[DataQualityIssueDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            rows = self._select_rows(conn, "devices", _DEVICE_FIELDS)
            groups = {
                int(row["id"]): str(row["name"] or "")
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if row.get("id") is not None
            }
        result = []
        for row in rows:
            if "车载-MR" not in groups.get(int(row.get("group_id") or 0), ""):
                continue
            if _parse_train_identity_from_device(Device.from_mapping(row)) is not None:
                continue
            entity_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
            result.append(
                self._issue(
                    "error",
                    "mr_train_unbound",
                    "mr",
                    entity_id,
                    str(row.get("name") or ""),
                    "train",
                    "",
                    "MR 名称无法关联正式列车",
                    "核对正式 MR 命名；Agent 临时名称不得自动转为正式资产",
                )
            )
        return result

    def _static_ip_issues(self, site_id: str) -> list[DataQualityIssueDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            rows = self._select_rows(conn, "devices", _DEVICE_FIELDS)
            groups = {
                int(row["id"]): str(row["name"] or "")
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if row.get("id") is not None
            }
        candidates: list[tuple[dict[str, Any], str]] = []
        issues: list[DataQualityIssueDTO] = []
        for row in rows:
            ip = str(row.get("primary_address") or "").strip()
            device_type = str(row.get("device_type") or "").upper()
            group = groups.get(int(row.get("group_id") or 0), "")
            is_vehicle_mr = "车载-MR" in group
            is_dynamic_ap = device_type in {"FIT-AP", "CLOUD-AP"} and not is_vehicle_mr
            if is_dynamic_ap or not ip:
                continue
            entity_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
            try:
                normalized = str(ipaddress.ip_address(ip))
            except ValueError:
                issues.append(self._issue("error", "static_ip_invalid", "device", entity_id, str(row.get("name") or ""), "primary_address", ip, "静态设备 IP 格式无效", "修正设备管理 IP"))
                continue
            candidates.append((row, normalized))
        counts = Counter(ip for _, ip in candidates)
        for row, ip in candidates:
            if counts[ip] > 1:
                entity_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
                issues.append(self._issue("error", "static_ip_duplicate", "device", entity_id, str(row.get("name") or ""), "primary_address", ip, "同一局点静态设备 IP 重复", "核对设备点表；FIT-AP DHCP 地址不参与此规则"))
        return issues

    def _station_source_counts(self, site_id: str, group_name: str) -> dict[str, tuple[int, str]]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return {}
        with closing(self._connect(db_path)) as conn:
            target_key = normalize_station_source_value(group_name)[1]
            groups = [
                row
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if normalize_station_source_value(row.get("name"))[1] == target_key
            ]
            if not groups:
                return {}
            ids = [int(row["id"]) for row in groups if row.get("id") is not None]
            if not ids:
                return {}
            columns = {str(row[1]) for row in conn.execute('PRAGMA table_info("devices")')}
            selected = [field for field in ("station", "group_id", "updated_at") if field in columns]
            if "station" not in selected or "group_id" not in selected:
                return {}
            placeholders = ", ".join("?" for _ in ids)
            rows = [
                dict(row)
                for row in conn.execute(
                    f'SELECT {", ".join(selected)} FROM devices WHERE group_id IN ({placeholders})',
                    ids,
                )
            ]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = parse_station_source_value(row.get("station")).source_station_key
            if key:
                grouped[key].append(row)
        return {
            key: (len(items), max(str(item.get("updated_at") or "") for item in items))
            for key, items in grouped.items()
        }

    def _station_issues(self, stations: list[StationDTO]) -> list[DataQualityIssueDTO]:
        issues: list[DataQualityIssueDTO] = []
        names = Counter(station.name.casefold() for station in stations if station.name)
        codes = Counter(station.code.casefold() for station in stations if station.code)
        source_keys = Counter(station.source_station_key.casefold() for station in stations if station.source_station_key)
        order_keys = Counter(
            (station.path_code.casefold(), station.sort_order)
            for station in stations
            if station.participates_in_direction and station.sort_order is not None
        )
        for station in stations:
            if not station.name:
                issues.append(self._issue("error", "station_name_required", "station", station.id, station.name, "name", "", "节点名称不能为空", "补充节点名称"))
            if station.name and names[station.name.casefold()] > 1:
                issues.append(self._issue("error", "station_name_duplicate", "station", station.id, station.name, "name", station.name, "同一局点正式节点名称重复", "合并或更正重复节点"))
            if station.code and codes[station.code.casefold()] > 1:
                issues.append(self._issue("error", "station_code_duplicate", "station", station.id, station.name, "code", station.code, "同一局点节点编码重复", "核对节点编码"))
            if station.participates_in_direction:
                if not station.path_code:
                    issues.append(self._issue("error", "station_order_missing", "station", station.id, station.name, "path_code", "", "参与方向判断的节点必须填写所属路径", "补充所属路径"))
                if station.sort_order is None:
                    issues.append(self._issue("error", "station_order_missing", "station", station.id, station.name, "sort_order", "", "参与方向判断的节点必须填写主线顺序", "补充主线顺序或关闭参与方向判断"))
            elif station.node_type == "station" and station.sort_order is None:
                issues.append(self._issue("warning", "station_order_missing", "station", station.id, station.name, "sort_order", "", "普通车站没有主线顺序", "确认是否需要参与方向判断"))
            if station.participates_in_direction and station.sort_order is not None and order_keys[(station.path_code.casefold(), station.sort_order)] > 1:
                issues.append(self._issue("error", "station_order_duplicate", "station", station.id, station.name, "sort_order", str(station.sort_order), "同一路径内参与方向判断的主线顺序重复", "调整主线顺序"))
            if station.node_type in {"parking_lot", "depot"} and station.participates_in_direction:
                issues.append(self._issue("warning", "station_special_node_in_direction", "station", station.id, station.name, "participates_in_direction", "true", "特殊节点不应默认参与主线方向判断", "关闭参与方向判断或补充拓扑资料"))
            if station.node_type in {"parking_lot", "depot"} and station.path_code.casefold() == DEFAULT_MAIN_PATH_CODE.casefold() and station.sort_order is not None:
                issues.append(self._issue("warning", "station_special_node_in_direction", "station", station.id, station.name, "sort_order", str(station.sort_order), "特殊节点设置了 MAIN 顺序但没有拓扑资料", "确认接轨拓扑后再纳入方向判断"))
            if not station.center_mileage_text:
                issues.append(self._issue("warning", "station_center_mileage_missing", "station", station.id, station.name, "center_mileage_text", "", "中心里程为空", "按正式线路资料补充中心里程"))
            elif parse_track_mileage(station.center_mileage_text).error:
                issues.append(self._issue("error", "station_center_mileage_invalid", "station", station.id, station.name, "center_mileage_text", station.center_mileage_text, "中心里程格式无效", "使用 K12+345、12+345 或米数格式"))
            turnback_facilities = {"turnback_track", "crossover", "storage_track", "tail_track", "loop"}
            if not station.turnback_capable and set(station.track_facilities) & turnback_facilities:
                issues.append(self._issue("warning", "station_turnback_facility_mismatch", "station", station.id, station.name, "track_facilities", "、".join(station.track_facilities), "已配置折返相关轨道设施，但未标记具备折返能力", "核对实际折返能力"))
            if station.turnback_capable and not (set(station.track_facilities) & turnback_facilities):
                issues.append(self._issue("warning", "station_turnback_facility_mismatch", "station", station.id, station.name, "track_facilities", "、".join(station.track_facilities), "已标记具备折返能力，但未配置相关轨道设施", "补充轨道设施或取消折返能力"))
            if station.turnback_capable and set(station.track_facilities) == {"depot_connection"}:
                issues.append(self._issue("warning", "station_turnback_facility_mismatch", "station", station.id, station.name, "track_facilities", "depot_connection", "仅有出入段线不等同于正常运营折返", "核对折返能力"))
            if station.is_service_terminal and not station.track_facilities:
                issues.append(self._issue("warning", "station_turnback_facility_mismatch", "station", station.id, station.name, "track_facilities", "", "运营终到/折返站未配置轨道设施", "补充实际轨道设施"))
            if station.turnback_capable and station.turnback_direction == "unknown":
                issues.append(self._issue("warning", "station_turnback_direction_unknown", "station", station.id, station.name, "turnback_direction", "unknown", "可折返但折返方向未知", "补充折返方向"))
            if station.terminal_extension_enabled and not station.is_line_terminal:
                issues.append(self._issue("warning", "station_terminal_extension_without_terminal", "station", station.id, station.name, "terminal_extension_enabled", "true", "非线路端点不能启用端点延伸区间", "先确认线路端点"))
            if station.terminal_extension_distance_m is not None and station.terminal_extension_distance_m < 0:
                issues.append(self._issue("error", "station_terminal_extension_distance_invalid", "station", station.id, station.name, "terminal_extension_distance_m", str(station.terminal_extension_distance_m), "端点距离不能为负数", "修正端点距离"))
            if station.terminal_endpoint_mileage_text and parse_track_mileage(station.terminal_endpoint_mileage_text).error:
                issues.append(self._issue("warning", "station_terminal_endpoint_mileage_invalid", "station", station.id, station.name, "terminal_endpoint_mileage_text", station.terminal_endpoint_mileage_text, "端点里程格式无效", "使用 K12+345、12+345 或米数格式"))
            if station.source_sync_status == "stale":
                issues.append(self._issue("warning", "station_source_stale", "station", station.id, station.name, "source_station_value", station.source_station_value, "来源站点已不存在", "核对设备管理 station 字段或保留人工资料"))
            if station.source_kind == "legacy_ap_derived":
                issues.append(self._issue("warning", "station_legacy_source_unconfirmed", "station", station.id, station.name, "source_kind", station.source_kind, "旧 AP 派生站点尚未确认来源", "从设备管理来源或模板确认后保存"))
            if station.source_station_key and source_keys[station.source_station_key.casefold()] > 1:
                issues.append(self._issue("error", "station_source_ambiguous_match", "station", station.id, station.name, "source_station_key", station.source_station_value, "同一来源键指向多个正式站点", "人工合并重复来源"))
        main_stations = [
            station
            for station in stations
            if station.enabled
            and station.node_type == "station"
            and station.path_code.casefold() == DEFAULT_MAIN_PATH_CODE.casefold()
        ]
        if main_stations and not any(station.is_line_terminal for station in main_stations):
            issues.append(self._issue("warning", "section_generation_endpoint_ambiguous", "station", "", "MAIN", "is_line_terminal", "", "MAIN 路径没有标记线路端点", "标记主线低序和高序线路端点"))
        for station in main_stations:
            if station.is_line_terminal and not station.terminal_extension_enabled:
                issues.append(self._issue("warning", "station_terminal_extension_disabled", "station", station.id, station.name, "terminal_extension_enabled", "false", "线路端点未配置端点延伸区间", "确认终点站外侧是否仍有轨道"))
        return issues

    def _section_issues(
        self,
        sections: list[SectionDTO],
        stations: list[StationDTO],
    ) -> list[DataQualityIssueDTO]:
        issues: list[DataQualityIssueDTO] = []
        station_uids = {station.node_uid for station in stations if station.node_uid}
        generation_keys = Counter(section.generation_key for section in sections if section.generation_key)
        names = Counter(section.name.casefold() for section in sections if section.name)
        for section in sections:
            if section.name and names[section.name.casefold()] > 1:
                issues.append(self._issue("error", "section_generation_conflict", "section", section.id, section.name, "name", section.name, "区间名称重复", "核对人工区间和自动生成区间"))
            if section.generation_key and generation_keys[section.generation_key] > 1:
                issues.append(self._issue("error", "section_duplicate_generation_key", "section", section.id, section.name, "generation_key", section.generation_key, "自动区间生成标识重复", "删除或修正重复自动区间"))
            if (
                section.start_node_uid
                and section.end_node_uid
                and section.start_node_uid == section.end_node_uid
            ) or (
                not section.start_node_uid
                and not section.end_node_uid
                and section.start_station
                and section.start_station == section.end_station
            ):
                issues.append(self._issue("error", "section_direction_mismatch", "section", section.id, section.name, "start_node_uid", section.start_station, "区间起始节点和终到节点不能相同", "修正区间节点"))
            if section.direction_role not in {"increasing", "decreasing", "none", "unknown"}:
                issues.append(self._issue("error", "section_direction_mismatch", "section", section.id, section.name, "direction_role", section.direction_role, "区间方向角色无效", "修正方向角色"))
            if section.auto_generated:
                for field, node_type, node_uid in (
                    ("start_node_uid", section.start_node_type, section.start_node_uid),
                    ("end_node_uid", section.end_node_type, section.end_node_uid),
                ):
                    valid = (
                        node_type == "station" and node_uid in station_uids
                    ) or (
                        node_type == "terminal_endpoint" and node_uid.startswith("endpoint:")
                    )
                    if not valid:
                        issues.append(self._issue("error", "section_generation_node_identity_missing", "section", section.id, section.name, field, node_uid, "自动区间引用的稳定节点不存在", "重新生成区间并核对站点"))
            elif not section.start_node_uid or not section.end_node_uid:
                issues.append(self._issue("warning", "section_legacy_node_unresolved", "section", section.id, section.name, "start_node_uid/end_node_uid", "", "旧区间尚未关联正式节点", "在区间维护中关联正式站点或端点"))
            if section.section_mileage_source == "unavailable":
                if (
                    section.section_mileage_start_m is not None
                    or section.section_mileage_end_m is not None
                    or section.section_mileage_open_end
                ):
                    issues.append(self._issue("error", "section_mileage_range_invalid", "section", section.id, section.name, "section_mileage_source", section.section_mileage_source, "区间里程来源为未生成，但仍保存了范围值", "清空范围或重新生成区间"))
                else:
                    issues.append(self._issue("warning", "section_mileage_unavailable", "section", section.id, section.name, "section_mileage_start_m", "", "区间物理里程范围未生成", "补充站台中心里程后重新生成区间，或人工填写范围"))
            elif section.section_mileage_open_end:
                if (
                    section.section_kind != "terminal_extension"
                    or section.section_mileage_start_m is None
                    or section.section_mileage_end_m is not None
                ):
                    issues.append(self._issue("error", "section_mileage_range_invalid", "section", section.id, section.name, "section_mileage_open_end", "true", "区间开放终点范围无效", "仅在端点延伸区间保留起点并清空终点"))
            elif (
                section.section_mileage_start_m is None
                or section.section_mileage_end_m is None
                or section.section_mileage_start_m < 0
                or section.section_mileage_end_m <= section.section_mileage_start_m
            ):
                issues.append(self._issue("error", "section_mileage_range_invalid", "section", section.id, section.name, "section_mileage_start_m/section_mileage_end_m", "", "区间物理里程范围无效", "填写非负起点，并确保终点大于起点"))
            if section.ap_count == 0:
                issues.append(self._issue("warning", "section_ap_reference_unresolved", "section", section.id, section.name, "ap_count", "0", "区间没有关联轨旁 AP", "核对轨旁 AP 正式区间归属"))
        return issues

    def _stations(self, aps: list[TracksideApDTO], *, site_id: str = "") -> list[StationDTO]:
        endpoint_names: set[str] = set()
        for ap in aps:
            if ap.record_kind != "__base_section__":
                continue
            if ap.base_metadata.get("start_node_type") == "terminal_endpoint" and ap.section_start_station:
                endpoint_names.add(ap.section_start_station)
            if ap.base_metadata.get("end_node_type") == "terminal_endpoint" and ap.section_end_station:
                endpoint_names.add(ap.section_end_station)
        names = {ap.station for ap in aps if ap.station}
        names.update(
            ap.section_start_station
            for ap in aps
            if ap.section_start_station and ap.section_start_station not in endpoint_names
        )
        names.update(
            ap.section_end_station
            for ap in aps
            if ap.section_end_station and ap.section_end_station not in endpoint_names
        )
        site_meta = self._site_meta(site_id) if site_id else {}
        main_path_code = str(site_meta.get("main_path_code") or DEFAULT_MAIN_PATH_CODE)
        source_group = str(site_meta.get("station_source_group_name") or DEFAULT_STATION_SOURCE_GROUP)
        source_counts = self._station_source_counts(site_id, source_group) if site_id else {}
        result = []
        for index, name in enumerate(sorted(names, key=self._natural_key), 1):
            metadata_row = next(
                (ap for ap in aps if ap.record_kind == "__base_station__" and ap.station == name),
                None,
            )
            metadata = metadata_row.base_metadata if metadata_row else {}
            node_uid = str(metadata.get("node_uid") or "")
            if not node_uid:
                identity = metadata_row.id if metadata_row else f"legacy:{name}"
                node_uid = str(uuid5(NAMESPACE_URL, f"netconsole:{site_id}:station:{identity}"))
            source_value = str(metadata.get("source_station_value") or "")
            parsed_source = parse_station_source_value(source_value)
            parsed_name = parse_station_source_value(name)
            source_key = str(
                metadata.get("source_station_key")
                or parsed_source.source_station_key
                or parsed_name.source_station_key
                or ""
            )
            canonical_station_name = str(
                metadata.get("canonical_station_name")
                or parsed_name.canonical_station_name
            )
            node_type = str(metadata.get("node_type") or "station")
            source_kind = str(metadata.get("source_kind") or ("manual" if metadata_row else "legacy_ap_derived"))
            special = node_type in {"parking_lot", "depot"}
            path_code = str(metadata.get("path_code") or (DEFAULT_MAIN_PATH_CODE if not special else "UNASSIGNED"))
            participates = bool(metadata.get("participates_in_direction", not special))
            raw_sort_order = metadata.get("sort_order")
            sort_order = self._int_or_none(raw_sort_order) if raw_sort_order not in (None, "") else (index if source_kind == "legacy_ap_derived" else None)
            turnback_type = str(metadata.get("turnback_type") or "none")
            try:
                track_facilities = normalize_track_facilities(
                    metadata.get("track_facilities"),
                    legacy_turnback_type=turnback_type,
                )
            except ValueError:
                track_facilities = normalize_track_facilities(None, legacy_turnback_type=turnback_type)
            center_mileage_text = str(metadata.get("center_mileage_text") or "")
            center_mileage = parse_track_mileage(center_mileage_text)
            if source_value and source_key and source_key in source_counts:
                source_device_count, source_last_seen_at = source_counts[source_key]
                sync_status = "matched"
            else:
                source_device_count, source_last_seen_at = 0, ""
                if source_kind == "device_station_field":
                    sync_status = "stale"
                elif source_kind == "legacy_ap_derived":
                    sync_status = "legacy"
                elif source_kind == "manual":
                    sync_status = "manual"
                else:
                    sync_status = "unavailable"
            related = [ap for ap in aps if ap.station == name and self._is_ap_record(ap)]
            section_names = {
                ap.section
                for ap in aps
                if ap.section and name in {ap.station, ap.section_start_station, ap.section_end_station}
            }
            mileages = [ap.mileage.meters for ap in related if ap.mileage.meters is not None]
            result.append(
                StationDTO(
                    id=self._derived_id("station", node_uid),
                    node_uid=node_uid,
                    name=name,
                    code=str(metadata.get("code") or ""),
                    line_name=(metadata_row.line_name if metadata_row else "") or next((ap.line_name for ap in related if ap.line_name), ""),
                    sort_order=sort_order,
                    ap_count=len(related),
                    section_count=len(section_names),
                    mileage_min=min(mileages, default=None),
                    mileage_max=max(mileages, default=None),
                    remark=str(metadata.get("remark") or (metadata_row.remark if metadata_row else "")),
                    source_station_value=source_value,
                    source_station_key=source_key,
                    source_order_text=str(metadata.get("source_order_text") or parsed_source.source_order_text),
                    source_order=self._int_or_none(
                        metadata.get("source_order")
                        if metadata.get("source_order") not in (None, "")
                        else parsed_source.source_order
                    ),
                    canonical_station_name=canonical_station_name,
                    node_type=node_type,  # type: ignore[arg-type]
                    path_code=path_code or main_path_code,
                    participates_in_direction=participates,
                    structure_type=str(metadata.get("structure_type") or "unknown"),  # type: ignore[arg-type]
                    platform_layout=str(metadata.get("platform_layout") or "unknown"),  # type: ignore[arg-type]
                    center_mileage_text=center_mileage_text,
                    center_mileage_m=center_mileage.meters,
                    is_line_terminal=bool(metadata.get("is_line_terminal", False)),
                    is_service_terminal=bool(metadata.get("is_service_terminal", False)),
                    turnback_capable=bool(metadata.get("turnback_capable", False)),
                    turnback_type=turnback_type,  # type: ignore[arg-type]
                    track_facilities=track_facilities,  # type: ignore[arg-type]
                    turnback_direction=str(metadata.get("turnback_direction") or "none"),  # type: ignore[arg-type]
                    terminal_extension_enabled=bool(metadata.get("terminal_extension_enabled", False)),
                    terminal_endpoint_label=str(metadata.get("terminal_endpoint_label") or "端点"),
                    terminal_extension_distance_m=self._float_or_none(metadata.get("terminal_extension_distance_m")),
                    terminal_endpoint_mileage_text=str(metadata.get("terminal_endpoint_mileage_text") or ""),
                    enabled=bool(metadata.get("enabled", True)),
                    source_kind=source_kind,  # type: ignore[arg-type]
                    source_device_count=source_device_count,
                    source_sync_status=sync_status,  # type: ignore[arg-type]
                    source_last_seen_at=source_last_seen_at,
                )
            )
        source_key_counts = Counter(station.source_station_key for station in result if station.source_station_key)
        return [
            station.model_copy(update={"source_sync_status": "conflict"})
            if station.source_station_key and source_key_counts[station.source_station_key] > 1
            else station
            for station in result
        ]

    def _sections(self, aps: list[TracksideApDTO]) -> list[SectionDTO]:
        result: list[SectionDTO] = []
        actual_aps = [ap for ap in aps if self._is_ap_record(ap)]
        formal_rows = [ap for ap in aps if ap.record_kind == "__base_section__" and ap.section]
        formal_names = {row.section for row in formal_rows}
        for metadata_row in formal_rows:
            metadata = metadata_row.base_metadata
            ap_rows = [ap for ap in actual_aps if ap.section == metadata_row.section]
            mileages = [ap.mileage.meters for ap in ap_rows if ap.mileage.meters is not None]
            generation_key = str(metadata.get("generation_key") or "")
            identity = generation_key or metadata_row.id
            line_direction = str(metadata.get("line_direction") or metadata_row.line_side)
            result.append(
                SectionDTO(
                    id=self._derived_id("section", identity),
                    name=metadata_row.section,
                    section_code=str(metadata.get("section_code") or ""),
                    section_kind=str(metadata.get("section_kind") or "manual"),  # type: ignore[arg-type]
                    path_code=str(metadata.get("path_code") or DEFAULT_MAIN_PATH_CODE),
                    direction_role=str(metadata.get("direction_role") or "unknown"),  # type: ignore[arg-type]
                    line_direction=line_direction,
                    start_node_type=str(metadata.get("start_node_type") or "legacy"),  # type: ignore[arg-type]
                    start_node_uid=str(metadata.get("start_node_uid") or ""),
                    start_station=metadata_row.section_start_station,
                    end_node_type=str(metadata.get("end_node_type") or "legacy"),  # type: ignore[arg-type]
                    end_node_uid=str(metadata.get("end_node_uid") or ""),
                    end_station=metadata_row.section_end_station,
                    line_side=metadata_row.line_side,
                    auto_generated=bool(metadata.get("auto_generated", False)),
                    generation_key=generation_key,
                    manual_override_fields=[
                        str(field)
                        for field in metadata.get("manual_override_fields", [])
                        if isinstance(field, str) and field
                    ] if isinstance(metadata.get("manual_override_fields"), list) else [],
                    section_mileage_start_m=self._float_or_none(metadata.get("section_mileage_start_m")),
                    section_mileage_end_m=self._float_or_none(metadata.get("section_mileage_end_m")),
                    section_mileage_open_end=bool(metadata.get("section_mileage_open_end", False)),
                    section_mileage_source=(
                        str(metadata.get("section_mileage_source"))
                        if str(metadata.get("section_mileage_source") or "") in {"generated", "manual", "unavailable"}
                        else "unavailable"
                    ),  # type: ignore[arg-type]
                    enabled=bool(metadata.get("enabled", True)),
                    source_kind=str(metadata.get("source_kind") or "manual"),  # type: ignore[arg-type]
                    ap_count=len(ap_rows),
                    mileage_min=min(mileages, default=None),
                    mileage_max=max(mileages, default=None),
                    remark=str(metadata.get("remark") or metadata_row.remark),
                )
            )
        grouped: dict[tuple[str, str, str, str], list[TracksideApDTO]] = defaultdict(list)
        for ap in actual_aps:
            if ap.section and ap.section not in formal_names:
                grouped[(ap.section, ap.section_start_station, ap.section_end_station, ap.line_side)].append(ap)
        for key, rows in grouped.items():
            name, start, end, line_side = key
            mileages = [ap.mileage.meters for ap in rows if ap.mileage.meters is not None]
            result.append(
                SectionDTO(
                    id=self._derived_id("section", *key),
                    name=name,
                    section_kind="legacy",
                    direction_role="unknown",
                    line_direction=line_side,
                    start_node_type="legacy",
                    start_station=start,
                    end_node_type="legacy",
                    end_station=end,
                    line_side=line_side,
                    source_kind="legacy_ap_derived",
                    ap_count=len(rows),
                    mileage_min=min(mileages, default=None),
                    mileage_max=max(mileages, default=None),
                )
            )
        return result

    def _trains(self, mrs: list[VehicleMrDTO], issues: list[DataQualityIssueDTO]) -> list[TrainDTO]:
        grouped: dict[str, list[VehicleMrDTO]] = defaultdict(list)
        for mr in mrs:
            grouped[mr.train_id].append(mr)
        result = []
        for train_id, rows in grouped.items():
            issue_rows = [issue for issue in issues if issue.entity_id in {train_id, *(row.id for row in rows)}]
            sessions = [row.runtime.latest_session_id for row in rows if row.runtime.latest_session_id]
            statuses = [row.runtime.mesh_status for row in rows]
            result.append(
                TrainDTO(
                    id=train_id,
                    train_no=rows[0].train_no,
                    name=train_id,
                    mr_count=len(rows),
                    roles=sorted({row.role for row in rows if row.role}),
                    mr_position_codes=sorted({row.mr_position_code for row in rows if row.mr_position_code != "unknown"}),
                    latest_mesh_status="online" if "online" in statuses else statuses[0] if statuses else "unknown",
                    latest_session_id=sessions[0] if sessions else "",
                    issue_count=len(issue_rows),
                    highest_issue_severity=self._highest(issue_rows),
                )
            )
        return result

    def _read_rows(self, site_id: str, table: str, fields: Iterable[str]) -> list[dict[str, Any]]:
        path = self.paths.site_db_path(site_id)
        if not path.is_file():
            return []
        with closing(self._connect(path)) as conn:
            return self._select_rows(conn, table, fields)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    @staticmethod
    def _select_rows(conn: sqlite3.Connection, table: str, fields: Iterable[str]) -> list[dict[str, Any]]:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            return []
        columns = {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
        selected = [field for field in fields if field in columns]
        if not selected:
            return []
        sql = ", ".join(f'"{field}"' for field in selected)
        return [dict(row) for row in conn.execute(f'SELECT {sql} FROM "{table}"')]

    def _site_meta(self, site_id: str) -> dict[str, Any]:
        path = self.paths.site_dir(site_id) / "site_meta.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _mileage(raw: Any, meters: Any) -> MileageDTO:
        parsed = parse_track_mileage(raw if str(raw or "").strip() else meters)
        return MileageDTO(
            raw=str(raw or ""),
            normalized=parsed.display if parsed.meters is not None else "",
            meters=parsed.meters,
            line_type=parsed.prefix or "",
            valid=parsed.meters is not None and not parsed.error,
            error=parsed.error or "",
        )

    @staticmethod
    def _expected_prefix(line_side: str, direction: str) -> str:
        text = f"{line_side} {direction}"
        if "左" in text or "下行" in text:
            return "ZDK"
        if "右" in text or "上行" in text:
            return "YDK"
        if "出" in text:
            return "CDK"
        if "入" in text:
            return "RDK"
        return ""

    @staticmethod
    def _issue(severity: str, code: str, entity_type: str, entity_id: str, entity_name: str, field: str, original: str, message: str, action: str) -> DataQualityIssueDTO:
        return DataQualityIssueDTO(
            severity=severity,  # type: ignore[arg-type]
            code=code,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            field_name=field,
            original_value=str(original or ""),
            message=message,
            suggested_action=action,
            blocking=is_blocking_issue(code, severity),
        )

    @staticmethod
    def _issue_map(issues: list[DataQualityIssueDTO], entity_type: str) -> dict[str, list[DataQualityIssueDTO]]:
        result: dict[str, list[DataQualityIssueDTO]] = defaultdict(list)
        for issue in issues:
            if issue.entity_type == entity_type:
                result[issue.entity_id].append(issue)
        return result

    def _with_ap_issues(self, item: TracksideApDTO, issues: list[DataQualityIssueDTO]) -> TracksideApDTO:
        return item.model_copy(update={"issue_count": len(issues), "highest_issue_severity": self._highest(issues)})

    def _with_mr_issues(self, item: VehicleMrDTO, issues: list[DataQualityIssueDTO]) -> VehicleMrDTO:
        return item.model_copy(update={"issue_count": len(issues), "highest_issue_severity": self._highest(issues)})

    @staticmethod
    def _highest(issues: list[DataQualityIssueDTO]) -> str:
        return min((issue.severity for issue in issues), key=lambda value: _SEVERITY_ORDER[value], default="")

    @staticmethod
    def _mac_key(value: Any) -> str:
        normalized = normalize_mac(value)
        if normalized:
            return normalized.replace(":", "")
        return normalize_ap_mac(value).normalized

    @classmethod
    def _display_mac(cls, value: Any) -> str:
        key = cls._mac_key(value)
        return ":".join(key[index : index + 2] for index in range(0, 12, 2)) if key else str(value or "")

    @classmethod
    def _is_ap_record(cls, item: TracksideApDTO) -> bool:
        if item.record_kind in {"__base_station__", "__base_section__"}:
            return False
        return bool(item.name or item.mac or item.point_code.strip() not in {"", "-"})

    @staticmethod
    def _base_metadata(value: Any) -> dict[str, Any]:
        try:
            payload = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _derived_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:12]
        return f"{prefix}:{digest}"

    @staticmethod
    def _page(items: list[T], page: int, page_size: int) -> tuple[list[T], int, int]:
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        return items[start : start + size], current, size

    @staticmethod
    def _natural_key(value: str) -> tuple[Any, ...]:
        import re

        return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value or "")))

    @staticmethod
    def _ap_sort_key(item: TracksideApDTO, sort_by: str) -> Any:
        mapping = {
            "name": item.name.casefold(),
            "station": item.station.casefold(),
            "section": item.section.casefold(),
            "mileage": (item.mileage.meters is None, item.mileage.meters or 0),
            "updated_at": item.updated_at,
        }
        return mapping.get(sort_by, mapping["name"])

    @classmethod
    def _mr_sort_key(cls, item: VehicleMrDTO, sort_by: str) -> Any:
        return {
            "train_no": cls._natural_key(item.train_no),
            "name": item.name.casefold(),
            "role": item.role.casefold(),
            "ip": item.management_ip,
        }.get(sort_by, cls._natural_key(item.train_no))

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first(items: list[Any], field: str) -> str:
        return next((str(getattr(item, field)) for item in items if getattr(item, field, "")), "")


__all__ = ["RailTransitBaseDataQueryService"]
