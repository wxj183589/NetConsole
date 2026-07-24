from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Iterable

from netconsole.models.api.rail_transit_base_data import (
    SectionDTO,
    SectionGenerationLineMetadataDTO,
    SectionGenerationPreviewDTO,
    SectionGenerationPreviewItemDTO,
    StationDTO,
    StationSourceIssueDTO,
)
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataRepository,
)
from netconsole.utils.mileage import parse_track_mileage


class SectionGenerationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SectionGenerationService:
    """根据当前编辑草稿计算区间预览，不执行任何持久化。"""

    def __init__(self, repository: RailTransitBaseDataRepository) -> None:
        self.repository = repository

    def preview(
        self,
        *,
        site_id: str,
        base_revision: str,
        line_metadata: SectionGenerationLineMetadataDTO,
        stations: Iterable[StationDTO],
        current_sections: Iterable[SectionDTO],
    ) -> SectionGenerationPreviewDTO:
        if self.repository.base_data_revision(site_id) != base_revision:
            raise SectionGenerationError(
                "BASE_DATA_REVISION_CONFLICT",
                "基础资料已被其他操作更新，请重新加载后再生成区间",
            )
        station_rows = list(stations)
        current_rows = list(current_sections)
        generated, issues = self._generate(line_metadata, station_rows)
        valid_node_uids = {station.node_uid for station in station_rows if station.node_uid}
        valid_node_uids.update(
            uid
            for section in generated
            for uid in (section.start_node_uid, section.end_node_uid)
            if uid
        )
        items, compare_issues = self._compare(generated, current_rows, valid_node_uids)
        issues.extend(compare_issues)
        return SectionGenerationPreviewDTO(
            site_id=site_id,
            base_revision=base_revision,
            generated_sections=items,
            create_count=sum(item.result == "CREATE" for item in items),
            update_count=sum(item.result == "UPDATE" for item in items),
            unchanged_count=sum(item.result == "UNCHANGED" for item in items),
            conflict_count=sum(item.result == "CONFLICT" for item in items),
            stale_count=sum(item.result == "STALE" for item in items),
            blocking_count=sum(issue.blocking for issue in issues),
            issues=issues,
        )

    def _generate(
        self,
        metadata: SectionGenerationLineMetadataDTO,
        stations: list[StationDTO],
    ) -> tuple[list[SectionDTO], list[StationSourceIssueDTO]]:
        issues: list[StationSourceIssueDTO] = []
        grouped: dict[str, list[StationDTO]] = defaultdict(list)
        for station in stations:
            if not station.enabled or not station.participates_in_direction or station.node_type != "station":
                continue
            if station.sort_order is None:
                issues.append(
                    self._issue(
                        "warning",
                        "section_generation_station_order_missing",
                        f"{station.name} 缺少主线顺序，未参与区间生成",
                        "sort_order",
                        entity_id=station.id,
                    )
                )
                continue
            if not station.node_uid:
                issues.append(
                    self._issue(
                        "error",
                        "section_generation_node_identity_missing",
                        f"{station.name} 缺少稳定节点标识",
                        "node_uid",
                        blocking=True,
                        entity_id=station.id,
                    )
                )
                continue
            grouped[station.path_code or metadata.main_path_code].append(station)

        generated: list[SectionDTO] = []
        for path_code, path_stations in grouped.items():
            order_counts = Counter(station.sort_order for station in path_stations)
            duplicates = {order for order, count in order_counts.items() if count > 1}
            if duplicates:
                issues.append(
                    self._issue(
                        "error",
                        "section_generation_station_order_duplicate",
                        f"{path_code} 路径存在重复顺序：{', '.join(str(item) for item in sorted(duplicates))}",
                        "sort_order",
                        blocking=True,
                    )
                )
                continue
            uid_counts = Counter(station.node_uid for station in path_stations)
            if any(count > 1 for count in uid_counts.values()):
                issues.append(
                    self._issue(
                        "error",
                        "section_generation_node_identity_missing",
                        f"{path_code} 路径存在重复稳定节点标识",
                        "node_uid",
                        blocking=True,
                    )
                )
                continue
            ordered = sorted(path_stations, key=lambda station: (station.sort_order, station.node_uid))
            mileage_counts = Counter(
                station.center_mileage_m
                for station in ordered
                if station.center_mileage_m is not None
            )
            duplicate_mileages = {
                mileage for mileage, count in mileage_counts.items() if count > 1
            }
            if duplicate_mileages:
                issues.append(
                    self._issue(
                        "warning",
                        "section_generation_station_mileage_duplicate",
                        f"{path_code} 路径存在重复站台中心里程："
                        f"{', '.join(self._format_mileage(item) for item in sorted(duplicate_mileages))} m",
                        "center_mileage_m",
                    )
                )
            for lower, higher in zip(ordered, ordered[1:]):
                between_sections, between_issues = self._between_sections(
                    metadata,
                    path_code,
                    lower,
                    higher,
                )
                generated.extend(between_sections)
                issues.extend(between_issues)
            if path_code.casefold() == metadata.main_path_code.casefold():
                terminal_sections, terminal_issues = self._terminal_sections(
                    metadata,
                    path_code,
                    ordered,
                )
                generated.extend(terminal_sections)
                issues.extend(terminal_issues)

        keys = Counter(section.generation_key for section in generated)
        duplicate_keys = {key for key, count in keys.items() if key and count > 1}
        if duplicate_keys:
            generated = [section for section in generated if section.generation_key not in duplicate_keys]
            issues.append(
                self._issue(
                    "error",
                    "section_duplicate_generation_key",
                    "区间生成结果包含重复生成标识",
                    "generation_key",
                    blocking=True,
                )
            )
        return generated, issues

    def _between_sections(
        self,
        metadata: SectionGenerationLineMetadataDTO,
        path_code: str,
        lower: StationDTO,
        higher: StationDTO,
    ) -> tuple[list[SectionDTO], list[StationSourceIssueDTO]]:
        physical_name = f"{lower.name}-{higher.name}"
        mileage_start, mileage_end, mileage_source = self._closed_mileage_range(
            lower.center_mileage_m,
            higher.center_mileage_m,
        )
        issues: list[StationSourceIssueDTO] = []
        if mileage_source == "unavailable":
            if lower.center_mileage_m is None or higher.center_mileage_m is None:
                missing_names = "、".join(
                    station.name
                    for station in (lower, higher)
                    if station.center_mileage_m is None
                )
                message = f"{physical_name} 缺少站台中心里程（{missing_names}），无法生成区间里程范围"
            else:
                message = f"{physical_name} 的站台中心里程相同，无法生成零长度区间里程范围"
            issues.append(
                self._issue(
                    "warning",
                    "section_generation_mileage_unavailable",
                    message,
                    "center_mileage_m",
                )
            )
        elif lower.center_mileage_m > higher.center_mileage_m:
            issues.append(
                self._issue(
                    "warning",
                    "section_generation_station_mileage_reversed",
                    f"{physical_name} 的站点顺序与站台中心里程方向相反，已按物理里程从小到大生成范围",
                    "center_mileage_m",
                )
            )
        sections = [
            self._section(
                name=f"{physical_name}-{metadata.increasing_direction_name}",
                section_kind="between_stations",
                path_code=path_code,
                direction_role="increasing",
                line_direction=metadata.increasing_direction_name,
                line_side=metadata.increasing_direction_line_side,
                start_node_type="station",
                start_node_uid=lower.node_uid,
                start_station=lower.name,
                end_node_type="station",
                end_node_uid=higher.node_uid,
                end_station=higher.name,
                generation_key=f"{path_code}|between|{lower.node_uid}|{higher.node_uid}|increasing",
                section_mileage_start_m=mileage_start,
                section_mileage_end_m=mileage_end,
                section_mileage_source=mileage_source,
            ),
            self._section(
                name=f"{physical_name}-{metadata.decreasing_direction_name}",
                section_kind="between_stations",
                path_code=path_code,
                direction_role="decreasing",
                line_direction=metadata.decreasing_direction_name,
                line_side=metadata.decreasing_direction_line_side,
                start_node_type="station",
                start_node_uid=higher.node_uid,
                start_station=higher.name,
                end_node_type="station",
                end_node_uid=lower.node_uid,
                end_station=lower.name,
                generation_key=f"{path_code}|between|{lower.node_uid}|{higher.node_uid}|decreasing",
                section_mileage_start_m=mileage_start,
                section_mileage_end_m=mileage_end,
                section_mileage_source=mileage_source,
            ),
        ]
        return sections, issues

    def _terminal_sections(
        self,
        metadata: SectionGenerationLineMetadataDTO,
        path_code: str,
        ordered: list[StationDTO],
    ) -> tuple[list[SectionDTO], list[StationSourceIssueDTO]]:
        if not ordered:
            return [], []
        issues: list[StationSourceIssueDTO] = []
        configured = [
            station
            for station in ordered
            if station.is_line_terminal and station.terminal_extension_enabled
        ]
        if len(configured) > 2:
            return [], [
                self._issue(
                    "error",
                    "section_generation_endpoint_ambiguous",
                    f"{path_code} 路径配置了超过两个端点延伸站，无法区分低序端和高序端",
                    "is_line_terminal",
                    blocking=True,
                )
            ]
        low_station = ordered[0]
        high_station = ordered[-1]
        if low_station.node_uid == high_station.node_uid and configured:
            return [], [
                self._issue(
                    "error",
                    "section_generation_endpoint_ambiguous",
                    f"{path_code} 路径只有一个可生成站点，无法区分两端",
                    "is_line_terminal",
                    blocking=True,
                )
            ]
        sections: list[SectionDTO] = []
        for station in configured:
            if station.node_uid not in {low_station.node_uid, high_station.node_uid}:
                issues.append(
                    self._issue(
                        "warning",
                        "section_generation_endpoint_ambiguous",
                        f"{station.name} 不是 {path_code} 路径最低序或最高序站，未生成端点延伸区间",
                        "is_line_terminal",
                        entity_id=station.id,
                    )
                )
                continue
            side = "low" if station.node_uid == low_station.node_uid else "high"
            mileage_start, mileage_end, mileage_open_end, mileage_source, mileage_issue = (
                self._terminal_mileage_range(path_code, station, side)
            )
            if mileage_issue:
                issues.append(mileage_issue)
            endpoint_uid = f"endpoint:{path_code}:{side}"
            endpoint_label = station.terminal_endpoint_label.strip() or "端点"
            if side == "low":
                start_node_type, start_node_uid, start_station = "terminal_endpoint", endpoint_uid, endpoint_label
                end_node_type, end_node_uid, end_station = "station", station.node_uid, station.name
                physical_name = f"{endpoint_label}-{station.name}"
            else:
                start_node_type, start_node_uid, start_station = "station", station.node_uid, station.name
                end_node_type, end_node_uid, end_station = "terminal_endpoint", endpoint_uid, endpoint_label
                physical_name = f"{station.name}-{endpoint_label}"
            for direction_role, line_direction in (
                ("increasing", metadata.increasing_direction_name),
                ("decreasing", metadata.decreasing_direction_name),
            ):
                line_side = (
                    metadata.increasing_direction_line_side
                    if direction_role == "increasing"
                    else metadata.decreasing_direction_line_side
                )
                sections.append(
                    self._section(
                        name=f"{physical_name}-{line_direction}",
                        section_kind="terminal_extension",
                        path_code=path_code,
                        direction_role=direction_role,
                        line_direction=line_direction,
                        line_side=line_side,
                        start_node_type=start_node_type,
                        start_node_uid=start_node_uid,
                        start_station=start_station,
                        end_node_type=end_node_type,
                        end_node_uid=end_node_uid,
                        end_station=end_station,
                        generation_key=f"{path_code}|terminal|{endpoint_uid}|{station.node_uid}|{direction_role}",
                        section_mileage_start_m=mileage_start,
                        section_mileage_end_m=mileage_end,
                        section_mileage_open_end=mileage_open_end,
                        section_mileage_source=mileage_source,
                    )
                )
        return sections, issues

    def _terminal_mileage_range(
        self,
        path_code: str,
        station: StationDTO,
        side: str,
    ) -> tuple[float | None, float | None, bool, str, StationSourceIssueDTO | None]:
        center = station.center_mileage_m
        if center is None:
            return (
                None,
                None,
                False,
                "unavailable",
                self._issue(
                    "warning",
                    "section_generation_mileage_unavailable",
                    f"{station.name} 缺少站台中心里程，无法生成端点区间里程范围",
                    "center_mileage_m",
                    entity_id=station.id,
                ),
            )

        endpoint: float | None = None
        endpoint_text = station.terminal_endpoint_mileage_text.strip()
        if endpoint_text:
            parsed = parse_track_mileage(endpoint_text)
            if parsed.meters is not None and not parsed.error:
                endpoint = float(parsed.meters)
            else:
                return (
                    None,
                    None,
                    False,
                    "unavailable",
                    self._issue(
                        "warning",
                        "section_generation_terminal_mileage_invalid",
                        f"{station.name} 的端点里程无法解析，无法生成端点区间里程范围",
                        "terminal_endpoint_mileage_text",
                        entity_id=station.id,
                    ),
                )
        elif station.terminal_extension_distance_m is not None:
            distance = station.terminal_extension_distance_m
            endpoint = center - distance if side == "low" else center + distance
        elif side == "low":
            endpoint = 0.0
        else:
            return center, None, True, "generated", None

        mileage_start, mileage_end, mileage_source = self._closed_mileage_range(center, endpoint)
        if mileage_source == "generated":
            return mileage_start, mileage_end, False, mileage_source, None
        reason = "计算结果小于 0" if endpoint is not None and endpoint < 0 else "端点里程与站台中心里程相同"
        return (
            None,
            None,
            False,
            "unavailable",
            self._issue(
                "warning",
                "section_generation_mileage_unavailable",
                f"{path_code} 路径 {station.name} 的{reason}，无法生成端点区间里程范围",
                "terminal_endpoint_mileage_text",
                entity_id=station.id,
            ),
        )

    @staticmethod
    def _closed_mileage_range(
        first: float | None,
        second: float | None,
    ) -> tuple[float | None, float | None, str]:
        if first is None or second is None or first < 0 or second < 0 or first == second:
            return None, None, "unavailable"
        return min(first, second), max(first, second), "generated"

    def _compare(
        self,
        generated: list[SectionDTO],
        current: list[SectionDTO],
        valid_node_uids: set[str],
    ) -> tuple[list[SectionGenerationPreviewItemDTO], list[StationSourceIssueDTO]]:
        items: list[SectionGenerationPreviewItemDTO] = []
        issues: list[StationSourceIssueDTO] = []
        current_by_key: dict[str, list[SectionDTO]] = defaultdict(list)
        current_by_name: dict[str, list[SectionDTO]] = defaultdict(list)
        for section in current:
            if section.generation_key:
                current_by_key[section.generation_key].append(section)
            if section.name:
                current_by_name[section.name.casefold()].append(section)
        generated_keys = {section.generation_key for section in generated}
        for proposed in generated:
            key_matches = current_by_key.get(proposed.generation_key, [])
            name_matches = current_by_name.get(proposed.name.casefold(), [])
            conflict_issue: StationSourceIssueDTO | None = None
            current_section: SectionDTO | None = None
            if len(key_matches) > 1:
                conflict_issue = self._issue(
                    "error",
                    "section_generation_conflict",
                    "同一生成标识对应多个现有区间",
                    "generation_key",
                    blocking=True,
                )
            elif key_matches:
                current_section = key_matches[0]
                if not current_section.auto_generated:
                    conflict_issue = self._issue(
                        "error",
                        "section_generation_conflict",
                        "生成标识已被人工区间占用",
                        "generation_key",
                        blocking=True,
                    )
            elif any(not section.auto_generated for section in name_matches):
                current_section = next(section for section in name_matches if not section.auto_generated)
                conflict_issue = self._issue(
                    "error",
                    "section_generation_conflict",
                    "自动生成结果与人工区间同名，未覆盖人工数据",
                    "name",
                    blocking=True,
                )
            if conflict_issue:
                issues.append(conflict_issue)
                items.append(
                    SectionGenerationPreviewItemDTO(
                        item_id=self._item_id("conflict", proposed.generation_key),
                        result="CONFLICT",
                        proposed_section=proposed,
                        current_section=current_section,
                        selectable=False,
                        issues=[conflict_issue],
                    )
                )
                continue
            if current_section:
                override_fields = set(current_section.manual_override_fields)
                missing_node_field = next(
                    (
                        field
                        for field in ("start_node_uid", "end_node_uid")
                        if field in override_fields and getattr(current_section, field) not in valid_node_uids
                    ),
                    "",
                )
                if missing_node_field:
                    missing_issue = self._issue(
                        "error",
                        "section_generation_manual_node_missing",
                        f"人工调整的节点已不存在：{getattr(current_section, missing_node_field) or '未设置'}",
                        missing_node_field,
                        blocking=True,
                        entity_id=current_section.id,
                    )
                    issues.append(missing_issue)
                    items.append(
                        SectionGenerationPreviewItemDTO(
                            item_id=self._item_id("conflict", proposed.generation_key),
                            result="CONFLICT",
                            proposed_section=proposed,
                            current_section=current_section,
                            selectable=False,
                            issues=[missing_issue],
                        )
                    )
                    continue
                merged_values = {
                    "id": current_section.id,
                    "remark": current_section.remark,
                    "ap_count": current_section.ap_count,
                    "mileage_min": current_section.mileage_min,
                    "mileage_max": current_section.mileage_max,
                    "manual_override_fields": current_section.manual_override_fields,
                }
                managed_fields = {
                    "name", "section_kind", "path_code", "start_node_type", "start_node_uid",
                    "start_station", "end_node_type", "end_node_uid", "end_station",
                    "direction_role", "line_direction", "line_side", "enabled",
                    "section_mileage_start_m", "section_mileage_end_m",
                    "section_mileage_open_end", "section_mileage_source",
                }
                for field in override_fields & managed_fields:
                    merged_values[field] = getattr(current_section, field)
                merged = proposed.model_copy(update=merged_values)
                unchanged = self._comparable(merged) == self._comparable(current_section)
                override_differences = [
                    field for field in override_fields & managed_fields
                    if getattr(proposed, field) != getattr(current_section, field)
                ]
                item_issues = []
                if override_differences:
                    item_issues.append(
                        self._issue(
                            "warning",
                            "section_generation_manual_override",
                            f"已保留人工调整字段：{'、'.join(sorted(override_differences))}",
                            "manual_override_fields",
                            entity_id=current_section.id,
                        )
                    )
                items.append(
                    SectionGenerationPreviewItemDTO(
                        item_id=self._item_id("current", proposed.generation_key),
                        result="UNCHANGED" if unchanged else "UPDATE",
                        proposed_section=merged,
                        current_section=current_section,
                        selected_by_default=not unchanged and not override_differences,
                        issues=item_issues,
                    )
                )
            else:
                items.append(
                    SectionGenerationPreviewItemDTO(
                        item_id=self._item_id("create", proposed.generation_key),
                        result="CREATE",
                        proposed_section=proposed,
                        selected_by_default=True,
                    )
                )
        for section in current:
            if not section.auto_generated or not section.generation_key:
                continue
            if section.generation_key in generated_keys:
                continue
            stale_message = "站点顺序已不再生成该区间，但该区间含人工修改" if section.manual_override_fields else "该自动区间已不在当前站点顺序的生成结果中，默认保留"
            stale_issue = self._issue(
                "warning",
                "section_generation_stale",
                stale_message,
                "generation_key",
                entity_id=section.id,
            )
            issues.append(stale_issue)
            items.append(
                SectionGenerationPreviewItemDTO(
                    item_id=self._item_id("stale", section.generation_key),
                    result="STALE",
                    current_section=section,
                    selected_by_default=False,
                    selectable=True,
                    issues=[stale_issue],
                )
            )
        order = {"CREATE": 0, "UPDATE": 1, "UNCHANGED": 2, "CONFLICT": 3, "STALE": 4}
        items.sort(
            key=lambda item: (
                order[item.result],
                (item.proposed_section or item.current_section or SectionDTO(id="", name="")).path_code,
                (item.proposed_section or item.current_section or SectionDTO(id="", name="")).name,
            )
        )
        return items, issues

    @classmethod
    def _section(
        cls,
        *,
        name: str,
        section_kind: str,
        path_code: str,
        direction_role: str,
        line_direction: str,
        line_side: str,
        start_node_type: str,
        start_node_uid: str,
        start_station: str,
        end_node_type: str,
        end_node_uid: str,
        end_station: str,
        generation_key: str,
        section_mileage_start_m: float | None = None,
        section_mileage_end_m: float | None = None,
        section_mileage_open_end: bool = False,
        section_mileage_source: str = "unavailable",
    ) -> SectionDTO:
        digest = hashlib.sha1(generation_key.encode("utf-8")).hexdigest()
        return SectionDTO(
            id=f"new:auto:{digest[:16]}",
            name=name,
            section_code=f"AUTO-{digest[:12].upper()}",
            section_kind=section_kind,  # type: ignore[arg-type]
            path_code=path_code,
            direction_role=direction_role,  # type: ignore[arg-type]
            line_direction=line_direction,
            start_node_type=start_node_type,  # type: ignore[arg-type]
            start_node_uid=start_node_uid,
            start_station=start_station,
            end_node_type=end_node_type,  # type: ignore[arg-type]
            end_node_uid=end_node_uid,
            end_station=end_station,
            line_side=line_side,
            auto_generated=True,
            generation_key=generation_key,
            section_mileage_start_m=section_mileage_start_m,
            section_mileage_end_m=section_mileage_end_m,
            section_mileage_open_end=section_mileage_open_end,
            section_mileage_source=section_mileage_source,  # type: ignore[arg-type]
            enabled=True,
            source_kind="generated",
        )

    @staticmethod
    def _comparable(section: SectionDTO) -> tuple[object, ...]:
        return (
            section.name,
            section.section_code,
            section.section_kind,
            section.path_code,
            section.direction_role,
            section.line_direction,
            section.start_node_type,
            section.start_node_uid,
            section.start_station,
            section.end_node_type,
            section.end_node_uid,
            section.end_station,
            section.line_side,
            section.auto_generated,
            section.generation_key,
            section.section_mileage_start_m,
            section.section_mileage_end_m,
            section.section_mileage_open_end,
            section.section_mileage_source,
            section.enabled,
            section.source_kind,
        )

    @staticmethod
    def _format_mileage(value: float) -> str:
        return f"{value:g}"

    @staticmethod
    def _item_id(prefix: str, value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]
        return f"section-generation:{prefix}:{digest}"

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


__all__ = ["SectionGenerationError", "SectionGenerationService"]
