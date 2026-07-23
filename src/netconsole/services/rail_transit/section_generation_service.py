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
        items, compare_issues = self._compare(generated, current_rows)
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
            for lower, higher in zip(ordered, ordered[1:]):
                generated.extend(self._between_sections(metadata, path_code, lower, higher))
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
    ) -> list[SectionDTO]:
        physical_name = f"{lower.name}-{higher.name}"
        return [
            self._section(
                name=f"{physical_name}-{metadata.increasing_direction_name}",
                section_kind="between_stations",
                path_code=path_code,
                direction_role="increasing",
                line_direction=metadata.increasing_direction_name,
                start_node_type="station",
                start_node_uid=lower.node_uid,
                start_station=lower.name,
                end_node_type="station",
                end_node_uid=higher.node_uid,
                end_station=higher.name,
                generation_key=f"{path_code}|between|{lower.node_uid}|{higher.node_uid}|increasing",
            ),
            self._section(
                name=f"{physical_name}-{metadata.decreasing_direction_name}",
                section_kind="between_stations",
                path_code=path_code,
                direction_role="decreasing",
                line_direction=metadata.decreasing_direction_name,
                start_node_type="station",
                start_node_uid=higher.node_uid,
                start_station=higher.name,
                end_node_type="station",
                end_node_uid=lower.node_uid,
                end_station=lower.name,
                generation_key=f"{path_code}|between|{lower.node_uid}|{higher.node_uid}|decreasing",
            ),
        ]

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
            endpoint_uid = f"endpoint:{path_code}:{side}"
            endpoint_label = station.terminal_endpoint_label.strip() or "端点"
            endpoint_display = f"{endpoint_label}（{station.name}端）"
            if side == "low":
                sections.extend(
                    [
                        self._section(
                            name=f"{endpoint_label}-{station.name}-{metadata.increasing_direction_name}",
                            section_kind="terminal_extension",
                            path_code=path_code,
                            direction_role="increasing",
                            line_direction=metadata.increasing_direction_name,
                            start_node_type="terminal_endpoint",
                            start_node_uid=endpoint_uid,
                            start_station=endpoint_display,
                            end_node_type="station",
                            end_node_uid=station.node_uid,
                            end_station=station.name,
                            generation_key=f"{path_code}|terminal|{endpoint_uid}|{station.node_uid}|increasing",
                        ),
                        self._section(
                            name=f"{station.name}-{endpoint_label}-{metadata.decreasing_direction_name}",
                            section_kind="terminal_extension",
                            path_code=path_code,
                            direction_role="decreasing",
                            line_direction=metadata.decreasing_direction_name,
                            start_node_type="station",
                            start_node_uid=station.node_uid,
                            start_station=station.name,
                            end_node_type="terminal_endpoint",
                            end_node_uid=endpoint_uid,
                            end_station=endpoint_display,
                            generation_key=f"{path_code}|terminal|{endpoint_uid}|{station.node_uid}|decreasing",
                        ),
                    ]
                )
            else:
                sections.extend(
                    [
                        self._section(
                            name=f"{station.name}-{endpoint_label}-{metadata.increasing_direction_name}",
                            section_kind="terminal_extension",
                            path_code=path_code,
                            direction_role="increasing",
                            line_direction=metadata.increasing_direction_name,
                            start_node_type="station",
                            start_node_uid=station.node_uid,
                            start_station=station.name,
                            end_node_type="terminal_endpoint",
                            end_node_uid=endpoint_uid,
                            end_station=endpoint_display,
                            generation_key=f"{path_code}|terminal|{endpoint_uid}|{station.node_uid}|increasing",
                        ),
                        self._section(
                            name=f"{endpoint_label}-{station.name}-{metadata.decreasing_direction_name}",
                            section_kind="terminal_extension",
                            path_code=path_code,
                            direction_role="decreasing",
                            line_direction=metadata.decreasing_direction_name,
                            start_node_type="terminal_endpoint",
                            start_node_uid=endpoint_uid,
                            start_station=endpoint_display,
                            end_node_type="station",
                            end_node_uid=station.node_uid,
                            end_station=station.name,
                            generation_key=f"{path_code}|terminal|{endpoint_uid}|{station.node_uid}|decreasing",
                        ),
                    ]
                )
        return sections, issues

    def _compare(
        self,
        generated: list[SectionDTO],
        current: list[SectionDTO],
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
                merged = proposed.model_copy(
                    update={
                        "id": current_section.id,
                        "remark": current_section.remark,
                        "ap_count": current_section.ap_count,
                        "mileage_min": current_section.mileage_min,
                        "mileage_max": current_section.mileage_max,
                    }
                )
                unchanged = self._comparable(merged) == self._comparable(current_section)
                items.append(
                    SectionGenerationPreviewItemDTO(
                        item_id=self._item_id("current", proposed.generation_key),
                        result="UNCHANGED" if unchanged else "UPDATE",
                        proposed_section=merged,
                        current_section=current_section,
                        selected_by_default=not unchanged,
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
            stale_issue = self._issue(
                "warning",
                "section_generation_stale",
                "该自动区间已不在当前站点顺序的生成结果中，默认保留",
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
        start_node_type: str,
        start_node_uid: str,
        start_station: str,
        end_node_type: str,
        end_node_uid: str,
        end_station: str,
        generation_key: str,
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
            line_side=line_direction,
            auto_generated=True,
            generation_key=generation_key,
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
            section.enabled,
            section.source_kind,
        )

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
