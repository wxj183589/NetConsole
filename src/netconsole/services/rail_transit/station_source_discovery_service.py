from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_base_data import (
    StationDTO,
    StationSourceCandidateDTO,
    StationSourceIssueDTO,
    StationSourcePreviewDTO,
)
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.station_source_utils import (
    DEFAULT_MAIN_PATH_CODE,
    DEFAULT_STATION_SOURCE_GROUP,
    STATION_SOURCE_FIELD,
    normalize_station_source_value,
    parse_station_source_value,
    station_structure_defaults,
)


class StationSourceDiscoveryService:
    """只读发现设备管理中“车站”分组的 station 字段候选。"""

    def __init__(
        self,
        paths: PathResolver,
        query_service: RailTransitBaseDataQueryService,
    ) -> None:
        self.paths = paths
        self.query_service = query_service

    def preview(self, site_id: str) -> StationSourcePreviewDTO:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        source_group = str(metadata.get("station_source_group_name") or DEFAULT_STATION_SOURCE_GROUP).strip() or DEFAULT_STATION_SOURCE_GROUP
        source_field = STATION_SOURCE_FIELD
        main_path_code = str(metadata.get("main_path_code") or DEFAULT_MAIN_PATH_CODE).strip() or DEFAULT_MAIN_PATH_CODE
        issues: list[StationSourceIssueDTO] = []
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return StationSourcePreviewDTO(
                site_id=site_id,
                source_group_name=source_group,
                source_field=source_field,
                group_found=False,
                issues=[self._issue("error", "station_source_group_missing", "基础资料数据库不存在", blocking=True)],
            )
        with closing(self._connect(db_path)) as conn:
            group_rows = self._select_rows(conn, "device_groups", ("id", "name"))
            target_group_key = normalize_station_source_value(source_group)[1]
            matched_groups = [
                row
                for row in group_rows
                if normalize_station_source_value(row.get("name"))[1] == target_group_key
            ]
            if not matched_groups:
                return StationSourcePreviewDTO(
                    site_id=site_id,
                    source_group_name=source_group,
                    source_field=source_field,
                    group_found=False,
                    issues=[
                        self._issue(
                            "warning",
                            "station_source_group_missing",
                            f"未找到设备分组“{source_group}”，无法从设备管理站点字段生成候选",
                        )
                    ],
                )
            if len(matched_groups) > 1:
                issues.append(
                    self._issue(
                        "warning",
                        "station_source_group_duplicate",
                        f"标准化名称为“{source_group}”的设备分组存在 {len(matched_groups)} 个，请核对设备分组",
                    )
                )
            devices = self._station_group_devices(conn, [int(row["id"]) for row in matched_groups])
        candidates, candidate_issues = self._build_candidates(site_id, devices, main_path_code=main_path_code)
        issues.extend(candidate_issues)
        unique_station_count = len(candidates)
        warning_count = sum(issue.severity == "warning" for issue in issues)
        warning_count += sum(issue.severity == "warning" for candidate in candidates for issue in candidate.issues)
        return StationSourcePreviewDTO(
            site_id=site_id,
            source_group_name=source_group,
            source_field=source_field,
            group_found=True,
            scanned_device_count=len(devices),
            empty_station_device_count=sum(1 for row in devices if not str(row.get("station") or "").strip()),
            unique_station_value_count=unique_station_count,
            normal_station_count=sum(candidate.node_type == "station" for candidate in candidates),
            special_node_count=sum(candidate.node_type != "station" for candidate in candidates),
            create_count=sum(candidate.match_status == "create" for candidate in candidates),
            match_count=sum(candidate.match_status == "matched" for candidate in candidates),
            conflict_count=sum(candidate.match_status == "conflict" for candidate in candidates),
            warning_count=warning_count,
            candidates=candidates,
            issues=issues,
        )

    def source_counts(self, site_id: str, *, group_name: str = DEFAULT_STATION_SOURCE_GROUP) -> dict[str, tuple[int, str]]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
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
            rows = self._station_group_devices(conn, [int(row["id"]) for row in groups])
        counts: dict[str, tuple[int, str]] = {}
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            parsed = parse_station_source_value(row.get("station"))
            value, key = parsed.source_station_value, parsed.source_station_key
            if key:
                grouped[key].append({**row, "source_station_value": value})
        for key, items in grouped.items():
            counts[key] = (len(items), max(str(item.get("updated_at") or "") for item in items))
        return counts

    def _build_candidates(
        self,
        site_id: str,
        devices: list[dict[str, Any]],
        *,
        main_path_code: str,
    ) -> tuple[list[StationSourceCandidateDTO], list[StationSourceIssueDTO]]:
        top_level_issues: list[StationSourceIssueDTO] = []
        empty_devices = [str(row.get("device_uuid") or row.get("id") or "") for row in devices if not str(row.get("station") or "").strip()]
        if empty_devices:
            shown = "、".join(empty_devices[:20])
            suffix = " 等" if len(empty_devices) > 20 else ""
            top_level_issues.append(
                self._issue(
                    "warning",
                    "station_source_value_empty",
                    f"{len(empty_devices)} 台分组为“车站”的设备 station 字段为空，已跳过；设备标识：{shown}{suffix}",
                    field_name="station",
                )
            )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in devices:
            source_value = str(row.get("station") or "")
            if not source_value.strip():
                continue
            parsed = parse_station_source_value(source_value, main_path_code=main_path_code)
            identity_key = (
                f"{parsed.node_type}\0{parsed.source_station_key}"
                if parsed.source_station_key
                else f"invalid\0{normalize_station_source_value(source_value)[1]}"
            )
            grouped[identity_key].append(
                {
                    **row,
                    "source_station_value": source_value,
                    "parsed_station_source": parsed,
                }
            )

        parsed_rows = {
            key: sorted(
                (row["parsed_station_source"] for row in rows),
                key=lambda item: (item.source_order is None, item.source_order or 0, item.source_station_value),
            )[0]
            for key, rows in grouped.items()
        }
        order_names: dict[tuple[str, int], set[str]] = defaultdict(set)
        name_orders: dict[str, set[int]] = defaultdict(set)
        for key, rows in grouped.items():
            for parsed in (row["parsed_station_source"] for row in rows):
                if parsed.participates_in_direction and parsed.sort_order is not None:
                    order_names[(parsed.path_code.casefold(), parsed.sort_order)].add(parsed.source_station_key)
                    name_orders[key].add(parsed.sort_order)

        existing = self._list_existing_stations(site_id)
        existing_by_id = {station.id: station for station in existing}
        existing_by_identity, existing_by_canonical_name = self._map_existing_canonical(existing)
        existing_by_order = {
            (station.path_code.casefold(), station.sort_order): station
            for station in existing
            if (
                station.source_kind != "legacy_ap_derived"
                and station.participates_in_direction
                and station.sort_order is not None
            )
        }
        candidates: list[StationSourceCandidateDTO] = []
        for key, rows in grouped.items():
            parsed = parsed_rows[key]
            row_issues: list[StationSourceIssueDTO] = []
            if parsed.parse_error:
                row_issues.append(
                    self._issue(
                        "error",
                        "station_source_parse_failed",
                        parsed.parse_error,
                        field_name="source_station_value",
                        blocking=True,
                    )
                )
            if len(name_orders[key]) > 1:
                row_issues.append(
                    self._issue(
                        "error",
                        "station_source_name_conflict",
                        "同一规范站名对应多个不同主线顺序",
                        "sort_order",
                        blocking=True,
                    )
                )
            if (
                parsed.participates_in_direction
                and parsed.sort_order is not None
                and len(order_names[(parsed.path_code.casefold(), parsed.sort_order)]) > 1
            ):
                row_issues.append(
                    self._issue(
                        "error",
                        "station_order_duplicate",
                        "同一主线顺序对应多个不同规范站名",
                        "sort_order",
                        blocking=True,
                    )
                )
            match_status, matched_station_id, match_issues = self._match_existing(
                parsed,
                existing_by_identity,
                existing_by_canonical_name,
                existing_by_order,
            )
            row_issues.extend(match_issues)
            if any(issue.blocking for issue in row_issues):
                match_status = "conflict"
            last_seen = max(str(row.get("updated_at") or "") for row in rows)
            structure_type, platform_layout = station_structure_defaults(
                parsed.node_type,
                parsed.path_code,
                main_path_code,
            )
            matched_station = existing_by_id.get(matched_station_id)
            proposed = StationDTO(
                id=matched_station_id or f"new:{self._candidate_digest(key)}",
                node_uid=(
                    matched_station.node_uid
                    if matched_station
                    else str(uuid5(NAMESPACE_URL, f"netconsole:{site_id}:station-source:{key}"))
                ),
                name=parsed.name,
                code=parsed.code,
                line_name="",
                sort_order=parsed.sort_order,
                remark="",
                source_station_value=parsed.source_station_value,
                source_station_key=parsed.source_station_key,
                source_order_text=parsed.source_order_text,
                source_order=parsed.source_order,
                canonical_station_name=parsed.canonical_station_name,
                node_type=parsed.node_type,  # type: ignore[arg-type]
                path_code=parsed.path_code,
                participates_in_direction=parsed.participates_in_direction,
                structure_type=structure_type,  # type: ignore[arg-type]
                platform_layout=platform_layout,  # type: ignore[arg-type]
                source_kind="device_station_field",
                source_device_count=len(rows),
                source_sync_status="conflict" if match_status == "conflict" else "matched",
                source_last_seen_at=last_seen,
            )
            candidates.append(
                StationSourceCandidateDTO(
                    candidate_id=f"station-source:{self._candidate_digest(key)}",
                    source_station_value=parsed.source_station_value,
                    source_station_key=parsed.source_station_key,
                    source_order_text=parsed.source_order_text,
                    source_order=parsed.source_order,
                    code=parsed.code,
                    name=parsed.name,
                    canonical_station_name=parsed.canonical_station_name,
                    node_type=parsed.node_type,  # type: ignore[arg-type]
                    path_code=parsed.path_code,
                    sort_order=parsed.sort_order,
                    participates_in_direction=parsed.participates_in_direction,
                    source_device_count=len(rows),
                    match_status=match_status,  # type: ignore[arg-type]
                    matched_station_id=matched_station_id,
                    matched_station_name=matched_station.name if matched_station else "",
                    suggested_action=(
                        "人工确认"
                        if match_status == "conflict"
                        else ("覆盖现有" if matched_station else "新增")
                    ),
                    proposed_station=proposed,
                    issues=row_issues,
                )
            )
        candidates.sort(key=lambda item: (item.sort_order is None, item.sort_order or 0, item.code, item.name))
        return candidates, top_level_issues

    def _match_existing(
        self,
        parsed: Any,
        by_identity: Mapping[tuple[str, str], list[StationDTO]],
        by_canonical_name: Mapping[str, list[StationDTO]],
        by_order: Mapping[tuple[str, int], StationDTO],
    ) -> tuple[str, str, list[StationSourceIssueDTO]]:
        issues: list[StationSourceIssueDTO] = []
        matches = by_identity.get((parsed.source_station_key, parsed.node_type), [])
        if len(matches) > 1:
            issues.append(
                self._issue(
                    "error",
                    "station_source_ambiguous_match",
                    "同一规范站名和节点类型匹配到多个正式站点，需要人工合并",
                    blocking=True,
                )
            )
            return "conflict", "", issues
        same_name = by_canonical_name.get(parsed.source_station_key, [])
        if same_name and not matches:
            issues.append(
                self._issue(
                    "error",
                    "station_source_node_type_conflict",
                    "同一规范站名存在不同节点类型，需要人工确认",
                    "node_type",
                    blocking=True,
                )
            )
            return "conflict", "", issues
        if matches:
            matched = matches[0]
            if (
                parsed.participates_in_direction
                and parsed.sort_order is not None
                and matched.participates_in_direction
                and matched.sort_order is not None
                and matched.source_kind != "legacy_ap_derived"
                and parsed.sort_order != matched.sort_order
            ):
                issues.append(
                    self._issue(
                        "error",
                        "station_source_name_conflict",
                        "同一规范站名对应多个不同主线顺序",
                        "sort_order",
                        blocking=True,
                    )
                )
                return "conflict", matched.id, issues
            if parsed.participates_in_direction and parsed.sort_order is not None:
                occupied = by_order.get((parsed.path_code.casefold(), parsed.sort_order))
                if occupied is not None and occupied.id != matched.id:
                    issues.append(
                        self._issue(
                            "error",
                            "station_order_duplicate",
                            f"主线顺序 {parsed.sort_order} 已由“{occupied.name}”使用",
                            "sort_order",
                            blocking=True,
                        )
                    )
                    return "conflict", matched.id, issues
            return "matched", matched.id, issues
        if parsed.participates_in_direction and parsed.sort_order is not None:
            occupied = by_order.get((parsed.path_code.casefold(), parsed.sort_order))
            if occupied is not None:
                issues.append(
                    self._issue(
                        "error",
                        "station_order_duplicate",
                        f"主线顺序 {parsed.sort_order} 已由“{occupied.name}”使用",
                        "sort_order",
                        blocking=True,
                    )
                )
                return "conflict", "", issues
        return "create", "", issues

    def _list_existing_stations(self, site_id: str) -> list[StationDTO]:
        result: list[StationDTO] = []
        page = 1
        while True:
            page_data = self.query_service.list_stations(site_id, page=page, page_size=200)
            result.extend(page_data.items)
            if len(result) >= page_data.total or not page_data.items:
                return result
            page += 1

    @staticmethod
    def _map_existing_canonical(
        rows: Iterable[StationDTO],
    ) -> tuple[dict[tuple[str, str], list[StationDTO]], dict[str, list[StationDTO]]]:
        by_identity: dict[tuple[str, str], list[StationDTO]] = defaultdict(list)
        by_name: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            parsed = parse_station_source_value(row.name)
            canonical_key = parsed.source_station_key
            if not canonical_key and row.canonical_station_name:
                canonical_key = normalize_station_source_value(row.canonical_station_name)[1]
            if not canonical_key and row.source_station_value:
                canonical_key = parse_station_source_value(row.source_station_value).source_station_key
            if not canonical_key:
                continue
            by_identity[(canonical_key, row.node_type)].append(row)
            by_name[canonical_key].append(row)
        return by_identity, by_name

    @staticmethod
    def _station_group_devices(conn: sqlite3.Connection, group_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(int(value) for value in group_ids))
        if not ids:
            return []
        columns = {str(row[1]) for row in conn.execute('PRAGMA table_info("devices")')}
        selected = [field for field in ("id", "device_uuid", "station", "group_id", "updated_at") if field in columns]
        if "station" not in selected or "group_id" not in selected:
            return []
        placeholders = ", ".join("?" for _ in ids)
        return [
            dict(row)
            for row in conn.execute(
                f'SELECT {", ".join(selected)} FROM devices WHERE group_id IN ({placeholders})',
                ids,
            )
        ]

    @staticmethod
    def _select_rows(conn: sqlite3.Connection, table: str, fields: Iterable[str]) -> list[dict[str, Any]]:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            return []
        columns = {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
        selected = [field for field in fields if field in columns]
        if not selected:
            return []
        return [dict(row) for row in conn.execute(f'SELECT {", ".join(selected)} FROM "{table}"')]

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    @staticmethod
    def _candidate_digest(value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _issue(
        severity: str,
        code: str,
        message: str,
        field_name: str = "",
        *,
        blocking: bool = False,
        entity_id: str = "",
    ) -> StationSourceIssueDTO:
        return StationSourceIssueDTO(
            severity=severity,  # type: ignore[arg-type]
            code=code,
            message=message,
            field_name=field_name,
            blocking=blocking,
            entity_id=entity_id,
        )


__all__ = ["StationSourceDiscoveryService"]
