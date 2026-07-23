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
            value, key = normalize_station_source_value(row.get("station"))
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
            source_value, source_key = normalize_station_source_value(row.get("station"))
            if not source_key:
                continue
            grouped[source_key].append({**row, "source_station_value": source_value, "source_station_key": source_key})

        parsed_rows = {key: parse_station_source_value(rows[0]["source_station_value"], main_path_code=main_path_code) for key, rows in grouped.items()}
        code_names: dict[str, set[str]] = defaultdict(set)
        name_codes: dict[str, set[str]] = defaultdict(set)
        order_keys: dict[tuple[str, int], list[str]] = defaultdict(list)
        for key, parsed in parsed_rows.items():
            if parsed.code:
                code_names[parsed.code.casefold()].add(parsed.name.casefold())
                name_codes[parsed.name.casefold()].add(parsed.code.casefold())
            if parsed.participates_in_direction and parsed.sort_order is not None:
                order_keys[(parsed.path_code.casefold(), parsed.sort_order)].append(key)

        existing = self._list_existing_stations(site_id)
        existing_by_id = {station.id: station for station in existing}
        existing_source_key = self._map_existing(existing, "source_station_key")
        existing_source_value = self._map_existing_by_source_value(existing)
        existing_code_name = self._map_existing_code_name(existing)
        existing_name_empty_code = self._map_existing_name_without_code(existing)
        candidates: list[StationSourceCandidateDTO] = []
        for key, rows in grouped.items():
            parsed = parsed_rows[key]
            row_issues: list[StationSourceIssueDTO] = []
            raw_values = sorted({str(row.get("station") or "") for row in rows if str(row.get("station") or "").strip()})
            if len(raw_values) > 1:
                row_issues.append(
                    self._issue(
                        "warning",
                        "station_source_ambiguous_match",
                        "多个原始 station 值归一化为同一来源键，已按标准化值合并，请人工核对",
                        field_name="source_station_value",
                    )
                )
            if parsed.parse_warning:
                row_issues.append(
                    self._issue(
                        "warning",
                        "station_source_parse_failed",
                        "station 字段无法解析数字前缀，需要人工确认顺序",
                        field_name="source_station_value",
                    )
                )
            if parsed.code and len(code_names[parsed.code.casefold()]) > 1:
                row_issues.append(self._issue("error", "station_source_code_conflict", "相同节点编码对应不同站名", "code", blocking=True))
            if parsed.code and len(name_codes[parsed.name.casefold()]) > 1:
                row_issues.append(self._issue("error", "station_source_name_conflict", "相同站名对应不同节点编码", "name", blocking=True))
            if parsed.participates_in_direction and parsed.sort_order is not None and len(order_keys[(parsed.path_code.casefold(), parsed.sort_order)]) > 1:
                row_issues.append(self._issue("error", "station_order_duplicate", "同一路径内候选主线顺序重复", "sort_order", blocking=True))
            match_status, matched_station_id, match_issues = self._match_existing(
                parsed,
                existing_source_key,
                existing_source_value,
                existing_code_name,
                existing_name_empty_code,
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
                    code=parsed.code,
                    name=parsed.name,
                    node_type=parsed.node_type,  # type: ignore[arg-type]
                    path_code=parsed.path_code,
                    sort_order=parsed.sort_order,
                    participates_in_direction=parsed.participates_in_direction,
                    source_device_count=len(rows),
                    match_status=match_status,  # type: ignore[arg-type]
                    matched_station_id=matched_station_id,
                    proposed_station=proposed,
                    issues=row_issues,
                )
            )
        candidates.sort(key=lambda item: (item.sort_order is None, item.sort_order or 0, item.code, item.name))
        return candidates, top_level_issues

    def _match_existing(
        self,
        parsed: Any,
        by_source_key: Mapping[str, list[StationDTO]],
        by_source_value: Mapping[str, list[StationDTO]],
        by_code_name: Mapping[tuple[str, str], list[StationDTO]],
        by_name_empty_code: Mapping[str, list[StationDTO]],
    ) -> tuple[str, str, list[StationSourceIssueDTO]]:
        issues: list[StationSourceIssueDTO] = []
        selectors: Iterable[tuple[str, list[StationDTO]]] = (
            ("source_station_key", by_source_key.get(parsed.source_station_key, [])),
            ("source_station_value", by_source_value.get(parsed.source_station_key, [])),
            ("code_name", by_code_name.get((parsed.code.casefold(), parsed.name.casefold()), []) if parsed.code else []),
            ("name_without_code", by_name_empty_code.get(parsed.name.casefold(), []) if not parsed.code else []),
        )
        for method, matches in selectors:
            if len(matches) == 1:
                return "matched", matches[0].id, issues
            if len(matches) > 1:
                issues.append(
                    self._issue(
                        "error",
                        "station_source_ambiguous_match",
                        f"来源候选通过 {method} 匹配到多个正式站点，需要人工确认",
                        blocking=True,
                    )
                )
                return "conflict", "", issues
        code_conflicts = [
            station
            for (code, _name), rows in by_code_name.items()
            for station in rows
            if parsed.code and code == parsed.code.casefold() and station.name.casefold() != parsed.name.casefold()
        ]
        if code_conflicts:
            issues.append(self._issue("error", "station_source_code_conflict", "候选节点编码已被其他正式站点使用", "code", blocking=True))
            return "conflict", "", issues
        name_conflicts = [
            station
            for (_code, name), rows in by_code_name.items()
            for station in rows
            if parsed.code and name == parsed.name.casefold() and station.code.casefold() != parsed.code.casefold()
        ]
        if name_conflicts:
            issues.append(self._issue("error", "station_source_name_conflict", "候选站名已被其他正式编码使用", "name", blocking=True))
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
    def _map_existing(rows: Iterable[StationDTO], field_name: str) -> dict[str, list[StationDTO]]:
        result: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            key = str(getattr(row, field_name) or "").casefold()
            if key:
                result[key].append(row)
        return result

    @staticmethod
    def _map_existing_by_source_value(rows: Iterable[StationDTO]) -> dict[str, list[StationDTO]]:
        result: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            _value, key = normalize_station_source_value(row.source_station_value)
            if key:
                result[key].append(row)
        return result

    @staticmethod
    def _map_existing_code_name(rows: Iterable[StationDTO]) -> dict[tuple[str, str], list[StationDTO]]:
        result: dict[tuple[str, str], list[StationDTO]] = defaultdict(list)
        for row in rows:
            if row.code:
                result[(row.code.casefold(), row.name.casefold())].append(row)
        return result

    @staticmethod
    def _map_existing_name_without_code(rows: Iterable[StationDTO]) -> dict[str, list[StationDTO]]:
        result: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            if not row.code:
                result[row.name.casefold()].append(row)
        return result

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
