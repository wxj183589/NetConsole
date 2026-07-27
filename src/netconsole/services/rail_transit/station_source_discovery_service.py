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
    canonical_station_name,
    normalize_station_source_value,
    parse_station_source_values,
    station_identity_key,
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
            match_count=sum(
                candidate.match_status
                in {
                    "exact_source_key",
                    "canonical_name",
                    "canonical_name_and_type",
                    "alias",
                }
                for candidate in candidates
            ),
            conflict_count=sum(candidate.match_status == "conflict" for candidate in candidates),
            manual_review_count=sum(
                candidate.match_status == "manual_review" for candidate in candidates
            ),
            canonical_match_count=sum(
                candidate.match_status
                in {"canonical_name", "canonical_name_and_type", "alias"}
                for candidate in candidates
            ),
            recommended_overwrite_count=sum(
                candidate.processing_strategy == "overwrite_existing"
                for candidate in candidates
            ),
            recommended_create_count=sum(
                candidate.processing_strategy == "create"
                for candidate in candidates
            ),
            recommended_merge_count=sum(
                candidate.processing_strategy == "merge_duplicates"
                for candidate in candidates
            ),
            remaining_manual_count=sum(
                candidate.processing_strategy == "manual_target"
                for candidate in candidates
            ),
            warning_count=warning_count,
            candidates=candidates,
            issues=issues,
        )

    def source_counts(self, site_id: str, *, group_name: str = DEFAULT_STATION_SOURCE_GROUP) -> dict[str, tuple[int, str]]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        main_path_code = (
            str(metadata.get("main_path_code") or DEFAULT_MAIN_PATH_CODE).strip()
            or DEFAULT_MAIN_PATH_CODE
        )
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
        parsed = parse_station_source_values(
            [items[0]["source_station_value"] for items in grouped.values()],
            main_path_code=main_path_code,
        )
        canonical_counts: dict[str, tuple[int, str]] = {}
        for key, items in grouped.items():
            count = len(items)
            updated_at = max(str(item.get("updated_at") or "") for item in items)
            counts[key] = (count, updated_at)
            candidate = parsed.get(key)
            if candidate is not None:
                previous_count, previous_updated_at = canonical_counts.get(
                    candidate.source_station_key, (0, "")
                )
                canonical_counts[candidate.source_station_key] = (
                    previous_count + count,
                    max(previous_updated_at, updated_at),
                )
        counts.update(canonical_counts)
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

        parsed_by_raw_key = parse_station_source_values(
            [rows[0]["source_station_value"] for rows in grouped.values()],
            main_path_code=main_path_code,
        )
        canonical_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        parsed_rows: dict[str, Any] = {}
        for raw_key, rows in grouped.items():
            parsed = parsed_by_raw_key[raw_key]
            normalized_code = _station_code_key(parsed.code)
            group_key = f"{parsed.source_station_key}|code:{normalized_code}"
            canonical_groups[group_key].extend(rows)
            parsed_rows.setdefault(group_key, parsed)
        grouped = canonical_groups
        code_names: dict[str, set[str]] = defaultdict(set)
        name_codes: dict[str, set[str]] = defaultdict(set)
        order_keys: dict[tuple[str, int], list[str]] = defaultdict(list)
        for key, parsed in parsed_rows.items():
            if parsed.code:
                code_names[_station_code_key(parsed.code)].add(
                    parsed.name.casefold()
                )
                name_codes[parsed.name.casefold()].add(
                    _station_code_key(parsed.code)
                )
            if parsed.participates_in_direction and parsed.sort_order is not None:
                order_keys[(parsed.path_code.casefold(), parsed.sort_order)].append(key)

        existing = self._list_existing_stations(site_id)
        existing_by_id = {station.id: station for station in existing}
        existing_source_key = self._map_existing_source_keys(existing)
        existing_canonical_name = self._map_existing_canonical_name(existing)
        existing_canonical_name_type = self._map_existing_canonical_name_type(
            existing
        )
        existing_alias = self._map_existing_alias(existing)
        existing_code_name = self._map_existing_code_name(existing)
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
            if (
                parsed.code
                and len(code_names[_station_code_key(parsed.code)]) > 1
            ):
                row_issues.append(self._issue("error", "station_source_code_conflict", "相同节点编码对应不同站名", "code", blocking=True))
            if parsed.code and len(name_codes[parsed.name.casefold()]) > 1:
                row_issues.append(self._issue("error", "station_source_name_conflict", "相同站名对应不同节点编码", "name", blocking=True))
            if parsed.participates_in_direction and parsed.sort_order is not None and len(order_keys[(parsed.path_code.casefold(), parsed.sort_order)]) > 1:
                row_issues.append(self._issue("error", "station_order_duplicate", "同一路径内候选主线顺序重复", "sort_order", blocking=True))
            (
                match_status,
                matched_station_id,
                match_basis,
                match_issues,
            ) = self._match_existing(
                parsed,
                existing_source_key,
                existing_canonical_name,
                existing_canonical_name_type,
                existing_alias,
                existing_code_name,
            )
            row_issues.extend(match_issues)
            possible_matches = self._candidate_matches(
                parsed,
                match_basis=match_basis,
                matched_station_id=matched_station_id,
                existing_by_id=existing_by_id,
                existing_source_key=existing_source_key,
                existing_canonical_name=existing_canonical_name,
                existing_canonical_name_type=existing_canonical_name_type,
                existing_alias=existing_alias,
            )
            candidate_code = parsed.code
            candidate_name = parsed.name
            candidate_source_order = parsed.source_order
            candidate_sort_order = parsed.sort_order
            candidate_order_method = parsed.order_parse_method
            candidate_confidence = parsed.parse_confidence
            candidate_warning = parsed.parse_warning
            normalized_source_name = canonical_station_name(
                parsed.source_station_value
            )
            inferred_prefix = (
                parsed.source_station_value[: -len(normalized_source_name)]
                if normalized_source_name
                and parsed.source_station_value.endswith(normalized_source_name)
                else ""
            ).strip()
            matched_identity_confirms_prefix = (
                not parsed.code
                and len(inferred_prefix) == 2
                and inferred_prefix.isdigit()
                and bool(possible_matches)
                and all(
                    station.node_type == parsed.node_type
                    and station.path_code.casefold() == parsed.path_code.casefold()
                    and canonical_station_name(station.name).casefold()
                    == normalized_source_name.casefold()
                    for station in possible_matches
                )
            )
            if matched_identity_confirms_prefix:
                candidate_code = inferred_prefix
                candidate_name = normalized_source_name
                candidate_source_order = int(inferred_prefix)
                candidate_sort_order = (
                    None
                    if parsed.node_type in {"parking_lot", "depot"}
                    else candidate_source_order
                )
                candidate_order_method = "existing_match_inferred"
                candidate_confidence = "matched_existing"
                candidate_warning = ""
                row_issues = [
                    issue
                    for issue in row_issues
                    if issue.code != "station_source_parse_failed"
                ]
            if any(issue.blocking for issue in row_issues):
                match_status = "conflict"
            elif (
                match_status == "create"
                and parsed.parse_confidence == "manual_review"
            ):
                match_status = "manual_review"
            last_seen = max(str(row.get("updated_at") or "") for row in rows)
            structure_type, platform_layout = station_structure_defaults(
                parsed.node_type,
                parsed.path_code,
                main_path_code,
            )
            matched_station = existing_by_id.get(matched_station_id)
            processing_strategy, processing_options = self._processing_strategy(
                match_status=match_status,
                matches=possible_matches,
                parsed=parsed,
            )
            proposed = StationDTO(
                id=matched_station_id or f"new:{self._candidate_digest(key)}",
                node_uid=(
                    matched_station.node_uid
                    if matched_station
                    else str(uuid5(NAMESPACE_URL, f"netconsole:{site_id}:station-source:{key}"))
                ),
                name=candidate_name,
                code=candidate_code,
                line_name="",
                sort_order=candidate_sort_order,
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
                    code=candidate_code,
                    name=candidate_name,
                    canonical_name=normalized_source_name,
                    source_order=candidate_source_order,
                    order_parse_method=candidate_order_method,
                    parse_confidence=candidate_confidence,
                    parse_warning=candidate_warning,
                    node_type=parsed.node_type,  # type: ignore[arg-type]
                    path_code=parsed.path_code,
                    sort_order=candidate_sort_order,
                    participates_in_direction=parsed.participates_in_direction,
                    source_device_count=len(rows),
                    match_status=match_status,  # type: ignore[arg-type]
                    matched_station_id=matched_station_id,
                    matched_station_name=(
                        existing_by_id[matched_station_id].name
                        if matched_station_id in existing_by_id
                        else ""
                    ),
                    matched_station_ids=[station.id for station in possible_matches],
                    matched_station_names=[station.name for station in possible_matches],
                    match_basis=match_basis,
                    suggested_action=(
                        "覆盖现有"
                        if processing_strategy == "overwrite_existing"
                        else "合并重复项"
                        if processing_strategy == "merge_duplicates"
                        else "处理来源冲突"
                        if match_status == "conflict"
                        else "人工确认"
                        if match_status == "manual_review"
                        else "新建规范站点"
                    ),
                    processing_strategy=processing_strategy,
                    processing_options=processing_options,
                    cleanup_name_prefix_recommended=bool(
                        matched_station
                        and canonical_station_name(matched_station.name)
                        != matched_station.name.strip()
                    ),
                    proposed_station=proposed,
                    issues=row_issues,
                )
            )
        candidates.sort(key=lambda item: (item.sort_order is None, item.sort_order or 0, item.code, item.name))
        return candidates, top_level_issues

    @staticmethod
    def _candidate_matches(
        parsed: Any,
        *,
        match_basis: str,
        matched_station_id: str,
        existing_by_id: Mapping[str, StationDTO],
        existing_source_key: Mapping[str, list[StationDTO]],
        existing_canonical_name: Mapping[str, list[StationDTO]],
        existing_canonical_name_type: Mapping[tuple[str, str], list[StationDTO]],
        existing_alias: Mapping[str, list[StationDTO]],
    ) -> list[StationDTO]:
        if matched_station_id and matched_station_id in existing_by_id:
            return [existing_by_id[matched_station_id]]
        matches_by_basis = {
            "exact_source_key": existing_source_key.get(
                parsed.source_station_key, []
            ),
            "canonical_name_and_type": existing_canonical_name_type.get(
                (parsed.canonical_name.casefold(), parsed.node_type), []
            ),
            "canonical_name": existing_canonical_name.get(
                parsed.canonical_name.casefold(), []
            ),
            "alias": existing_alias.get(parsed.canonical_name.casefold(), []),
        }
        return list(matches_by_basis.get(match_basis, []))

    @staticmethod
    def _processing_strategy(
        *,
        match_status: str,
        matches: list[StationDTO],
        parsed: Any,
    ) -> tuple[str, list[str]]:
        if len(matches) == 1 and match_status != "conflict":
            return "overwrite_existing", [
                "auto_match",
                "overwrite_existing",
                "ignore",
                "manual_target",
            ]
        if len(matches) > 1:
            normalized_source_name = canonical_station_name(
                parsed.source_station_value
            ).casefold()
            compatible = all(
                station.node_type == matches[0].node_type
                and station.path_code.casefold() == matches[0].path_code.casefold()
                and canonical_station_name(station.name).casefold()
                == normalized_source_name
                for station in matches
            )
            if compatible:
                return "merge_duplicates", [
                    "merge_duplicates",
                    "overwrite_existing",
                    "ignore",
                    "manual_target",
                ]
        if match_status == "create":
            return "create", ["create", "ignore", "manual_target"]
        return "manual_target", ["manual_target", "ignore"]

    def _match_existing(
        self,
        parsed: Any,
        by_source_key: Mapping[str, list[StationDTO]],
        by_canonical_name: Mapping[str, list[StationDTO]],
        by_canonical_name_type: Mapping[tuple[str, str], list[StationDTO]],
        by_alias: Mapping[str, list[StationDTO]],
        by_code_name: Mapping[tuple[str, str], list[StationDTO]],
    ) -> tuple[str, str, str, list[StationSourceIssueDTO]]:
        issues: list[StationSourceIssueDTO] = []
        code_key = _station_code_key(parsed.code)
        name_key = parsed.canonical_name.casefold()
        code_conflicts = [
            station
            for (code, _name), rows in by_code_name.items()
            for station in rows
            if code_key
            and code == code_key
            and canonical_station_name(station.name).casefold() != name_key
        ]
        if code_conflicts:
            issues.append(self._issue("error", "station_source_code_conflict", "候选节点编码已被其他正式站点使用", "code", blocking=True))
            return "conflict", "", "code_conflict", issues
        name_conflicts = [
            station
            for (_code, name), rows in by_code_name.items()
            for station in rows
            if code_key
            and name == name_key
            and _station_code_key(station.code) != code_key
        ]
        if name_conflicts:
            issues.append(self._issue("error", "station_source_name_conflict", "候选站名已被其他正式编码使用", "name", blocking=True))
            return "conflict", "", "name_conflict", issues
        selectors: Iterable[tuple[str, list[StationDTO]]] = (
            (
                "exact_source_key",
                by_source_key.get(parsed.source_station_key, []),
            ),
            (
                "canonical_name_and_type",
                by_canonical_name_type.get(
                    (parsed.canonical_name.casefold(), parsed.node_type), []
                ),
            ),
            (
                "canonical_name",
                by_canonical_name.get(parsed.canonical_name.casefold(), []),
            ),
            ("alias", by_alias.get(parsed.canonical_name.casefold(), [])),
        )
        for method, matches in selectors:
            if len(matches) == 1:
                return method, matches[0].id, method, issues
            if len(matches) > 1:
                issues.append(
                    self._issue(
                        "error",
                        "station_source_ambiguous_match",
                        f"来源候选通过 {method} 匹配到多个正式站点，需要人工确认",
                        blocking=True,
                    )
                )
                return "conflict", "", method, issues
        return "create", "", "", issues

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
    def _map_existing_source_keys(
        rows: Iterable[StationDTO],
    ) -> dict[str, list[StationDTO]]:
        result: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            keys = {
                str(row.source_station_key or "").casefold(),
                station_identity_key(row.name, row.node_type, row.path_code),
            }
            for key in keys:
                if key and row not in result[key]:
                    result[key].append(row)
        return result

    @staticmethod
    def _map_existing_canonical_name(
        rows: Iterable[StationDTO],
    ) -> dict[str, list[StationDTO]]:
        result: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            key = canonical_station_name(row.name).casefold()
            if key:
                result[key].append(row)
        return result

    @staticmethod
    def _map_existing_canonical_name_type(
        rows: Iterable[StationDTO],
    ) -> dict[tuple[str, str], list[StationDTO]]:
        result: dict[tuple[str, str], list[StationDTO]] = defaultdict(list)
        for row in rows:
            key = (canonical_station_name(row.name).casefold(), row.node_type)
            if key[0]:
                result[key].append(row)
        return result

    @staticmethod
    def _map_existing_alias(
        rows: Iterable[StationDTO],
    ) -> dict[str, list[StationDTO]]:
        result: dict[str, list[StationDTO]] = defaultdict(list)
        for row in rows:
            key = canonical_station_name(row.source_station_value).casefold()
            if key:
                result[key].append(row)
        return result

    @staticmethod
    def _map_existing_code_name(rows: Iterable[StationDTO]) -> dict[tuple[str, str], list[StationDTO]]:
        result: dict[tuple[str, str], list[StationDTO]] = defaultdict(list)
        for row in rows:
            if row.code:
                result[
                    (
                        _station_code_key(row.code),
                        canonical_station_name(row.name).casefold(),
                    )
                ].append(row)
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


def _station_code_key(value: object) -> str:
    text = str(value or "").strip().casefold()
    return str(int(text)) if text.isdigit() else text


__all__ = ["StationSourceDiscoveryService"]
