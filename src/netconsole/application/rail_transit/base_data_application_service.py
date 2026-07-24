from __future__ import annotations

import ipaddress
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_base_data import (
    BaseDataChangeDTO,
    BaseDataEditSessionDTO,
    BaseDataSaveResultDTO,
    BaseDataValidationIssueDTO,
    BaseDataValidationResultDTO,
    SectionGenerationPreviewDTO,
    SectionGenerationPreviewRequestDTO,
)
from netconsole.repositories.rail_transit_base_data_repository import (
    RailTransitBaseDataCompensationError,
    RailTransitBaseDataConstraintError,
    RailTransitBaseDataRepository,
    RailTransitBaseDataRevisionConflict,
)
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard, BaseDataWriteGuardError
from netconsole.services.rail_transit.section_generation_service import SectionGenerationService
from netconsole.services.rail_transit.station_source_utils import (
    DEFAULT_MAIN_PATH_CODE,
    DEFAULT_STATION_SOURCE_GROUP,
    STATION_SOURCE_FIELD,
    legacy_turnback_type_for_facilities,
    normalize_track_facilities,
    station_structure_defaults,
)
from netconsole.services.trackside_ap_plan_io import normalize_trackside_plan_rows
from netconsole.services.vehicle_mr_online import parse_train_identity
from netconsole.utils.mileage import parse_track_mileage


_SENSITIVE_KEYS = {
    "password", "username", "token", "secret", "community", "credential",
    "ssh_password", "telnet_password", "tunnel1_password", "tunnel2_password",
}
_NODE_TYPES = {"station", "parking_lot", "depot", "connection_point", "other", "unknown"}
_STRUCTURE_TYPES = {"underground", "elevated", "at_grade", "cutting", "mixed", "unknown"}
_PLATFORM_LAYOUTS = {"island", "side", "mixed", "stacked_island", "stacked_side", "separated", "unknown"}
_TURNBACK_TYPES = {"none", "crossover", "pocket_track", "tail_track", "loop", "depot_connection", "other", "unknown"}
_TURNBACK_DIRECTIONS = {"none", "both", "increasing_to_decreasing", "decreasing_to_increasing", "unknown"}
_INCREASING_DIRECTION_LEADING_ENDS = {"car_1_end", "car_6_end", "unknown"}
_SOURCE_KINDS = {"device_station_field", "template", "manual", "legacy_ap_derived"}
_SECTION_KINDS = {"between_stations", "terminal_extension", "depot_connection", "manual", "legacy"}
_SECTION_DIRECTIONS = {"increasing", "decreasing", "none", "unknown"}
_SECTION_NODE_TYPES = {"station", "terminal_endpoint", "legacy", "unknown"}
_SECTION_SOURCE_KINDS = {"generated", "manual", "template", "legacy_ap_derived"}


class RailTransitBaseDataApplicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BaseDataFieldValidationError(ValueError):
    def __init__(self, code: str, message: str, field_name: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field_name = field_name


class RailTransitBaseDataApplicationService:
    """统一编排基础资料编辑会话、校验和单库事务保存。"""

    def __init__(
        self,
        paths: PathResolver,
        query_service: RailTransitBaseDataQueryService,
        guard: BaseDataWriteGuard,
        repository: RailTransitBaseDataRepository | None = None,
    ) -> None:
        self.paths = paths
        self.query_service = query_service
        self.guard = guard
        self.repository = repository or RailTransitBaseDataRepository(paths)
        self.section_generation_service = SectionGenerationService(self.repository)

    def get_edit_session(self, site_id: str) -> BaseDataEditSessionDTO:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        status = self.guard.status(site_id)
        can_write = status.copy_write_authorized if status.scope == "copy_validation" else status.real_write_authorized
        denial_code, denial_reason = self.guard.write_denial(status)
        return BaseDataEditSessionDTO(
            site_id=site_id,
            base_revision=self.repository.base_data_revision(site_id),
            loaded_at=datetime.now(timezone.utc).isoformat(),
            can_write=can_write,
            write_scope=status.scope,
            storage_mode=status.storage_mode,
            write_denial_code=denial_code,
            write_denial_reason=denial_reason,
        )

    def preview_section_generation(
        self,
        payload: SectionGenerationPreviewRequestDTO,
    ) -> SectionGenerationPreviewDTO:
        site_id = SiteManager(self.paths).validate_site_name(payload.site_id)
        return self.section_generation_service.preview(
            site_id=site_id,
            base_revision=payload.base_revision,
            line_metadata=payload.line_metadata,
            stations=payload.stations,
            current_sections=payload.current_sections,
        )

    def validate_changes(
        self,
        site_id: str,
        base_revision: str,
        changes: Iterable[BaseDataChangeDTO],
    ) -> tuple[BaseDataValidationResultDTO, list[dict[str, Any]]]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        change_rows = list(changes)
        metadata = SiteManager(self.paths).load_site_metadata(site_id)
        main_path_code = str(
            metadata.get("main_path_code") or DEFAULT_MAIN_PATH_CODE
        ).strip() or DEFAULT_MAIN_PATH_CODE
        for change in change_rows:
            if change.entity_type != "site_metadata" or change.action != "update":
                continue
            requested_main_path = str(
                change.values.get("main_path_code") or ""
            ).strip()
            if requested_main_path:
                main_path_code = requested_main_path
        issues: list[BaseDataValidationIssueDTO] = []
        if self.repository.base_data_revision(site_id) != base_revision:
            issues.append(self._issue(0, "BASE_DATA_REVISION_CONFLICT", "基础资料已被其他操作更新，请重新加载"))
        normalized: list[dict[str, Any]] = []
        for index, change in enumerate(change_rows):
            try:
                normalized.append(
                    self._normalize_change(change, main_path_code=main_path_code)
                )
            except BaseDataFieldValidationError as exc:
                issues.append(self._issue(index, exc.code, str(exc), exc.field_name))
            except ValueError as exc:
                issues.append(self._issue(index, "BASE_DATA_VALIDATION_FAILED", str(exc)))
        if not issues:
            issues.extend(self._cross_validate(site_id, normalized))
        return BaseDataValidationResultDTO(valid=not any(issue.blocking for issue in issues), issues=issues), normalized

    def save_changes(
        self,
        site_id: str,
        base_revision: str,
        changes: Iterable[BaseDataChangeDTO],
        *,
        explicit_confirmation: bool,
    ) -> BaseDataSaveResultDTO:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        try:
            self.guard.authorize_apply(site_id, explicit_confirmation=explicit_confirmation)
        except BaseDataWriteGuardError as exc:
            raise RailTransitBaseDataApplicationError(exc.code, str(exc)) from exc
        validation, normalized = self.validate_changes(site_id, base_revision, changes)
        if not validation.valid:
            conflict = next((item for item in validation.issues if item.code == "BASE_DATA_REVISION_CONFLICT"), None)
            if conflict:
                raise RailTransitBaseDataApplicationError(conflict.code, conflict.message)
            raise RailTransitBaseDataApplicationError("BASE_DATA_VALIDATION_FAILED", "基础资料校验失败")
        try:
            result = self.repository.apply_base_data_changes(site_id, base_revision, normalized)
        except RailTransitBaseDataRevisionConflict as exc:
            raise RailTransitBaseDataApplicationError(
                "BASE_DATA_REVISION_CONFLICT",
                "基础资料已被其他操作更新，请重新加载",
            ) from exc
        except RailTransitBaseDataCompensationError as exc:
            raise RailTransitBaseDataApplicationError(
                "BASE_DATA_COMPENSATION_FAILED",
                "基础资料保存失败，metadata 补偿恢复也未完成；请停止继续编辑并从备份核对数据",
            ) from exc
        except RailTransitBaseDataConstraintError as exc:
            raise RailTransitBaseDataApplicationError("BASE_DATA_REFERENCE_CONFLICT", str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise RailTransitBaseDataApplicationError("BASE_DATA_REFERENCE_CONFLICT", "基础资料唯一性或引用关系冲突") from exc
        except (sqlite3.Error, OSError) as exc:
            raise RailTransitBaseDataApplicationError("BASE_DATA_TRANSACTION_FAILED", "基础资料事务保存失败并已回滚") from exc
        return BaseDataSaveResultDTO(
            revision=str(result["revision"]),
            created_count=int(result["created_count"]),
            updated_count=int(result["updated_count"]),
            deleted_count=int(result["deleted_count"]),
            warnings=[issue.message for issue in validation.issues if not issue.blocking],
            validation_issues=validation.issues,
        )

    def _normalize_change(
        self,
        change: BaseDataChangeDTO,
        *,
        main_path_code: str = DEFAULT_MAIN_PATH_CODE,
    ) -> dict[str, Any]:
        raw = dict(change.values)
        self._reject_sensitive(raw)
        entity_type = change.entity_type
        action = change.action
        allowed_actions = {
            "site_metadata": {"update"},
            "station": {"create", "update", "delete"},
            "section": {"create", "update", "delete"},
            "trackside_ap": {"create", "update", "delete"},
            "vehicle_mr": {"create", "update", "delete"},
            "trackside_ap_plan": {"replace"},
        }
        if action not in allowed_actions[entity_type]:
            raise ValueError("基础资料动作不受支持")
        if entity_type == "site_metadata":
            values = self._site_metadata_values(raw)
        elif entity_type == "station":
            values = self._station_values(
                raw,
                action,
                main_path_code=main_path_code,
            )
        elif entity_type == "section":
            values = self._section_values(raw, action)
        elif entity_type == "trackside_ap":
            values = self._ap_values(raw, action)
        elif entity_type == "vehicle_mr":
            values = self._mr_values(raw, action)
        else:
            rows = raw.get("rows")
            if not isinstance(rows, list):
                raise ValueError("轨旁 AP 规划数据格式无效")
            raw_rows = [dict(row) for row in rows if isinstance(row, Mapping)]
            station_keys = [str(row.get("station_name") or "").strip().casefold() for row in raw_rows]
            if len(station_keys) != len(set(station_keys)):
                raise ValueError("轨旁 AP 规划存在重复站点")
            normalized_rows = normalize_trackside_plan_rows(raw_rows)
            self._validate_plan_networks(normalized_rows)
            values = {"rows": normalized_rows}
        return {
            "entity_type": entity_type,
            "action": action,
            "entity_id": change.entity_id,
            "values": values,
        }

    @staticmethod
    def _site_metadata_values(raw: Mapping[str, Any]) -> dict[str, Any]:
        line_name = str(raw.get("line_name") or "").strip()
        system_type = str(raw.get("system_type") or "").strip()
        if not line_name:
            raise ValueError("线路名称不能为空")
        if not system_type:
            raise ValueError("项目类型不能为空")
        station_source_field = str(raw.get("station_source_field") or STATION_SOURCE_FIELD).strip()
        if station_source_field != STATION_SOURCE_FIELD:
            raise ValueError("站点来源字段只能为 station")
        return {
            "line_name": line_name[:200],
            "system_type": system_type[:100],
            "network_domain": str(raw.get("network_domain") or "default").strip()[:100],
            "main_path_code": str(raw.get("main_path_code") or DEFAULT_MAIN_PATH_CODE).strip()[:50] or DEFAULT_MAIN_PATH_CODE,
            "increasing_direction_name": str(raw.get("increasing_direction_name") or "上行").strip()[:50] or "上行",
            "decreasing_direction_name": str(raw.get("decreasing_direction_name") or "下行").strip()[:50] or "下行",
            "increasing_direction_leading_end": _enum(
                raw.get("increasing_direction_leading_end"),
                _INCREASING_DIRECTION_LEADING_ENDS,
                "unknown",
                "站序递增方向行驶头端无效",
            ),
            "station_source_group_name": str(raw.get("station_source_group_name") or DEFAULT_STATION_SOURCE_GROUP).strip()[:100] or DEFAULT_STATION_SOURCE_GROUP,
            "station_source_field": STATION_SOURCE_FIELD,
            "remark": str(raw.get("remark") or "").strip()[:1000],
        }

    @staticmethod
    def _station_values(
        raw: Mapping[str, Any],
        action: str,
        *,
        main_path_code: str = DEFAULT_MAIN_PATH_CODE,
    ) -> dict[str, Any]:
        name = str(raw.get("name") or "").strip()
        old_name = str(raw.get("old_name") or name).strip()
        if not (old_name if action == "delete" else name):
            raise ValueError("站点名称不能为空")
        node_type = _enum(raw.get("node_type"), _NODE_TYPES, "station", "节点类型无效")
        special = node_type in {"parking_lot", "depot"}
        path_code = str(raw.get("path_code") or ("UNASSIGNED" if special else DEFAULT_MAIN_PATH_CODE)).strip()
        participates = _bool(raw.get("participates_in_direction"), default=not special)
        sort_order = _int_or_none(raw.get("sort_order"))
        turnback_capable = _bool(raw.get("turnback_capable"), default=False)
        legacy_turnback_type = _enum(
            raw.get("turnback_type"),
            _TURNBACK_TYPES,
            "unknown" if turnback_capable else "none",
            "折返类型无效",
        )
        try:
            track_facilities = normalize_track_facilities(
                raw.get("track_facilities") if "track_facilities" in raw else None,
                legacy_turnback_type=legacy_turnback_type,
            )
        except ValueError as exc:
            raise BaseDataFieldValidationError(
                "station_facility_invalid",
                str(exc),
                "track_facilities",
            ) from exc
        turnback_type = legacy_turnback_type_for_facilities(track_facilities)
        structure_default, platform_default = station_structure_defaults(
            node_type,
            path_code,
            main_path_code,
        )
        center_mileage_text = str(raw.get("center_mileage_text") or "").strip()
        center_mileage = parse_track_mileage(center_mileage_text)
        if center_mileage_text and center_mileage.error:
            raise BaseDataFieldValidationError(
                "station_center_mileage_invalid",
                "中心里程格式无效",
                "center_mileage_text",
            )
        terminal_distance = _float_or_none(raw.get("terminal_extension_distance_m"))
        if terminal_distance is not None and terminal_distance < 0:
            raise BaseDataFieldValidationError(
                "station_terminal_extension_distance_invalid",
                "端点距离不能为负数",
                "terminal_extension_distance_m",
            )
        terminal_mileage_text = str(raw.get("terminal_endpoint_mileage_text") or "").strip()
        return {
            "node_uid": str(raw.get("node_uid") or (uuid4() if action == "create" else "")).strip(),
            "name": name,
            "old_name": old_name,
            "code": str(raw.get("code") or "").strip(),
            "line_name": str(raw.get("line_name") or "").strip(),
            "sort_order": sort_order,
            "source_station_value": str(raw.get("source_station_value") or "").strip(),
            "source_station_key": str(raw.get("source_station_key") or "").strip(),
            "node_type": node_type,
            "path_code": path_code,
            "participates_in_direction": participates,
            "structure_type": _enum(raw.get("structure_type"), _STRUCTURE_TYPES, structure_default, "车站结构无效"),
            "platform_layout": _enum(raw.get("platform_layout"), _PLATFORM_LAYOUTS, platform_default, "站台形式无效"),
            "center_mileage_text": center_mileage_text,
            "center_mileage_m": center_mileage.meters,
            "is_line_terminal": _bool(raw.get("is_line_terminal"), default=False),
            "is_service_terminal": _bool(raw.get("is_service_terminal"), default=False),
            "turnback_capable": turnback_capable,
            "turnback_type": turnback_type,
            "track_facilities": track_facilities,
            "turnback_direction": _enum(raw.get("turnback_direction"), _TURNBACK_DIRECTIONS, "none", "折返方向无效"),
            "terminal_extension_enabled": _bool(raw.get("terminal_extension_enabled"), default=False),
            "terminal_endpoint_label": str(raw.get("terminal_endpoint_label") or "端点").strip()[:100] or "端点",
            "terminal_extension_distance_m": terminal_distance,
            "terminal_endpoint_mileage_text": terminal_mileage_text,
            "enabled": _bool(raw.get("enabled"), default=True),
            "source_kind": _enum(raw.get("source_kind"), _SOURCE_KINDS, "manual", "站点来源类型无效"),
            "remark": str(raw.get("remark") or "").strip(),
        }

    @staticmethod
    def _section_values(raw: Mapping[str, Any], action: str) -> dict[str, Any]:
        name = str(raw.get("name") or "").strip()
        start = str(raw.get("start_station") or "").strip()
        end = str(raw.get("end_station") or "").strip()
        if action != "delete" and not name:
            raise ValueError("区间名称不能为空")
        if action != "delete" and (not start or not end or start == end):
            raise ValueError("区间起止站必须填写且不能相同")
        direction_role = _enum(
            raw.get("direction_role"),
            _SECTION_DIRECTIONS,
            "none",
            "方向角色无效",
        )
        auto_generated = _bool(raw.get("auto_generated"), default=False)
        generation_key = str(raw.get("generation_key") or "").strip()
        if auto_generated and not generation_key:
            raise BaseDataFieldValidationError(
                "section_duplicate_generation_key",
                "自动区间必须包含稳定生成标识",
                "generation_key",
            )
        manual_override_fields = raw.get("manual_override_fields") or []
        if not isinstance(manual_override_fields, list):
            raise ValueError("区间人工覆盖字段格式无效")
        return {
            "name": name,
            "old_name": str(raw.get("old_name") or name).strip(),
            "section_code": str(raw.get("section_code") or "").strip(),
            "section_kind": _enum(raw.get("section_kind"), _SECTION_KINDS, "manual", "区间类型无效"),
            "path_code": str(raw.get("path_code") or DEFAULT_MAIN_PATH_CODE).strip() or DEFAULT_MAIN_PATH_CODE,
            "direction_role": direction_role,
            "line_direction": str(raw.get("line_direction") or raw.get("line_side") or "").strip(),
            "start_node_type": _enum(raw.get("start_node_type"), _SECTION_NODE_TYPES, "legacy", "起始节点类型无效"),
            "start_node_uid": str(raw.get("start_node_uid") or "").strip(),
            "start_station": start,
            "old_start_station": str(raw.get("old_start_station") or start).strip(),
            "end_node_type": _enum(raw.get("end_node_type"), _SECTION_NODE_TYPES, "legacy", "终到节点类型无效"),
            "end_node_uid": str(raw.get("end_node_uid") or "").strip(),
            "end_station": end,
            "old_end_station": str(raw.get("old_end_station") or end).strip(),
            "line_side": str(raw.get("line_side") or "").strip(),
            "old_line_side": str(raw.get("old_line_side") or raw.get("line_side") or "").strip(),
            "auto_generated": auto_generated,
            "generation_key": generation_key,
            "manual_override_fields": sorted({str(field).strip() for field in manual_override_fields if str(field).strip()}),
            "enabled": _bool(raw.get("enabled"), default=True),
            "source_kind": _enum(raw.get("source_kind"), _SECTION_SOURCE_KINDS, "manual", "区间来源类型无效"),
            "remark": str(raw.get("remark") or "").strip(),
        }

    @staticmethod
    def _ap_values(raw: Mapping[str, Any], action: str) -> dict[str, Any]:
        if action == "delete":
            return {}
        name = str(raw.get("name") or raw.get("ap_name") or "").strip()
        point_code = str(raw.get("point_code") or raw.get("ap_point_code") or "").strip()
        mac = normalize_ap_mac(raw.get("mac") or raw.get("ap_mac_display"))
        if not name and not point_code:
            raise ValueError("轨旁 AP 名称或点位编号至少填写一项")
        if (raw.get("mac") or raw.get("ap_mac_display")) and not mac.normalized:
            raise ValueError("AP MAC 格式无效")
        mileage_raw = raw.get("mileage")
        if isinstance(mileage_raw, Mapping):
            mileage_raw = mileage_raw.get("raw") or mileage_raw.get("normalized")
        mileage = parse_track_mileage(mileage_raw)
        if mileage_raw not in (None, "") and mileage.error:
            raise ValueError(mileage.error)
        station = str(raw.get("station") or raw.get("station_name") or "").strip()
        section = str(raw.get("section") or raw.get("section_name") or "").strip()
        if not station and not section:
            raise ValueError("轨旁 AP 必须填写归属站点或归属区间")
        return {
            "line_name": str(raw.get("line_name") or "").strip(),
            "station_name": station,
            "section_name": section,
            "section_start_station": str(raw.get("section_start_station") or "").strip(),
            "section_end_station": str(raw.get("section_end_station") or "").strip(),
            "line_side": str(raw.get("line_side") or "").strip(),
            "direction": str(raw.get("direction") or "").strip(),
            "mileage_text": str(mileage_raw or "").strip(),
            "mileage_m": mileage.meters,
            "ap_point_code": point_code,
            "ap_name": name,
            "ap_mac_norm": mac.normalized,
            "ap_mac_display": mac.display or mac.raw,
            "remark": str(raw.get("remark") or "").strip(),
        }

    @staticmethod
    def _mr_values(raw: Mapping[str, Any], action: str) -> dict[str, Any]:
        if action == "delete":
            return {"name": str(raw.get("name") or "").strip()}
        name = str(raw.get("name") or "").strip()
        address = str(raw.get("management_ip") or raw.get("primary_address") or "").strip()
        protocol = str(raw.get("protocol") or "SSH").upper()
        try:
            ipaddress.ip_address(address)
        except ValueError:
            raise ValueError("车载 MR 管理地址格式无效") from None
        station = str(raw.get("station") or "").strip()
        if parse_train_identity(name) is None and parse_train_identity(station) is None:
            raise ValueError("车载 MR 名称无法识别列车和 CT/TC 角色")
        if protocol not in {"SSH", "TELNET"}:
            raise ValueError("车载 MR 协议只允许 SSH 或 TELNET")
        port = int(raw.get("port") or (22 if protocol == "SSH" else 23))
        if not 1 <= port <= 65535:
            raise ValueError("车载 MR 端口必须在 1-65535 范围内")
        mac = normalize_ap_mac(raw.get("mac") or raw.get("mac_address"))
        if (raw.get("mac") or raw.get("mac_address")) and not mac.normalized:
            raise ValueError("车载 MR MAC 格式无效")
        return {
            "name": name,
            "station": station,
            "primary_address": address,
            "mac_address": mac.display or mac.raw,
            "protocol": protocol,
            "port": port,
            "remark": str(raw.get("remark") or "").strip(),
        }

    def _cross_validate(self, site_id: str, changes: list[dict[str, Any]]) -> list[BaseDataValidationIssueDTO]:
        issues: list[BaseDataValidationIssueDTO] = []
        existing_stations = self._all_stations(site_id)
        station_names = {item.name for item in existing_stations}
        station_by_name = {item.name: item.node_uid for item in existing_stations}
        station_uids = {item.node_uid: item.id for item in existing_stations if item.node_uid}
        station_codes = {
            item.code.casefold(): item.id
            for item in existing_stations
            if item.code
        }
        station_source_keys = {
            item.source_station_key.casefold(): item.id
            for item in existing_stations
            if item.source_station_key
        }
        station_orders = {
            (item.path_code.casefold(), item.sort_order): item.id
            for item in existing_stations
            if item.participates_in_direction and item.sort_order is not None
        }
        existing_sections = self._all_sections(site_id)
        section_names = {item.name.casefold(): item.id for item in existing_sections if item.name}
        generation_keys = {
            item.generation_key: item.id
            for item in existing_sections
            if item.generation_key
        }
        ap_macs = {
            normalize_ap_mac(row.get("ap_mac_norm") or row.get("ap_mac_display")).normalized: f"ap:{row.get('id')}"
            for row in self.repository.list_ap_records(site_id)
            if normalize_ap_mac(row.get("ap_mac_norm") or row.get("ap_mac_display")).normalized
        }
        for index, change in enumerate(changes):
            values = change["values"]
            if change["entity_type"] == "site_metadata":
                continue
            if change["entity_type"] == "station":
                old_name = values.get("old_name")
                old_station = next((item for item in existing_stations if item.name == old_name), None)
                if change["action"] == "delete":
                    station_names.discard(old_name)
                    if old_station:
                        station_by_name.pop(old_station.name, None)
                        if old_station.node_uid:
                            station_uids.pop(old_station.node_uid, None)
                        if old_station.code:
                            station_codes.pop(old_station.code.casefold(), None)
                        if old_station.source_station_key:
                            station_source_keys.pop(old_station.source_station_key.casefold(), None)
                        if old_station.participates_in_direction and old_station.sort_order is not None:
                            station_orders.pop((old_station.path_code.casefold(), old_station.sort_order), None)
                    continue
                name = values["name"]
                if old_station:
                    if not values.get("node_uid"):
                        values["node_uid"] = old_station.node_uid
                    station_by_name.pop(old_station.name, None)
                    if old_station.node_uid:
                        station_uids.pop(old_station.node_uid, None)
                    if old_station.code:
                        station_codes.pop(old_station.code.casefold(), None)
                    if old_station.source_station_key:
                        station_source_keys.pop(old_station.source_station_key.casefold(), None)
                    if old_station.participates_in_direction and old_station.sort_order is not None:
                        station_orders.pop((old_station.path_code.casefold(), old_station.sort_order), None)
                if name in station_names and (change["action"] == "create" or name != old_name):
                    issues.append(self._issue(index, "STATION_DUPLICATE", "站点名称已存在", "name"))
                station_names.discard(old_name)
                station_names.add(name)
                node_uid = str(values.get("node_uid") or "")
                if not node_uid:
                    issues.append(self._issue(index, "section_generation_node_identity_missing", "站点缺少稳定节点标识", "node_uid"))
                elif node_uid in station_uids and station_uids[node_uid] != change.get("entity_id"):
                    issues.append(self._issue(index, "section_generation_node_identity_missing", "站点稳定节点标识重复", "node_uid"))
                else:
                    station_uids[node_uid] = str(change.get("entity_id") or f"new:{index}")
                    station_by_name[name] = node_uid
                code = str(values.get("code") or "").casefold()
                if code and code in station_codes and station_codes[code] != change.get("entity_id"):
                    issues.append(self._issue(index, "STATION_CODE_DUPLICATE", "站点编码已存在", "code"))
                if code:
                    station_codes[code] = str(change.get("entity_id") or f"new:{index}")
                source_key = str(values.get("source_station_key") or "").casefold()
                if source_key and source_key in station_source_keys and station_source_keys[source_key] != change.get("entity_id"):
                    issues.append(self._issue(index, "station_source_ambiguous_match", "来源键不能指向多个正式站点", "source_station_key"))
                if source_key:
                    station_source_keys[source_key] = str(change.get("entity_id") or f"new:{index}")
                participates = bool(values.get("participates_in_direction"))
                path_code = str(values.get("path_code") or "").strip()
                sort_order = values.get("sort_order")
                if participates and not path_code:
                    issues.append(self._issue(index, "station_order_missing", "参与方向判断的节点必须填写所属路径", "path_code"))
                if participates and sort_order is None:
                    issues.append(self._issue(index, "station_order_missing", "参与方向判断的节点必须填写主线顺序", "sort_order"))
                if participates and sort_order is not None:
                    order_key = (path_code.casefold(), int(sort_order))
                    if order_key in station_orders and station_orders[order_key] != change.get("entity_id"):
                        issues.append(self._issue(index, "station_order_duplicate", "同一路径内参与方向判断的主线顺序重复", "sort_order"))
                    station_orders[order_key] = str(change.get("entity_id") or f"new:{index}")
                facilities = set(values.get("track_facilities") or [])
                turnback_facilities = {"turnback_track", "crossover", "storage_track", "tail_track", "loop"}
                if not values.get("turnback_capable") and facilities & turnback_facilities:
                    issues.append(self._issue(index, "station_turnback_facility_mismatch", "已配置折返相关轨道设施，但未标记具备折返能力", "track_facilities", blocking=False))
                if values.get("turnback_capable") and not facilities & turnback_facilities:
                    issues.append(self._issue(index, "station_turnback_facility_mismatch", "已标记具备折返能力，但未配置相关轨道设施", "track_facilities", blocking=False))
                if values.get("turnback_capable") and facilities == {"depot_connection"}:
                    issues.append(self._issue(index, "station_turnback_facility_mismatch", "仅有出入段线不等同于正常运营折返", "track_facilities", blocking=False))
                if values.get("is_service_terminal") and not facilities:
                    issues.append(self._issue(index, "station_turnback_facility_mismatch", "运营终到/折返站未配置轨道设施", "track_facilities", blocking=False))
                if values.get("turnback_capable") and values.get("turnback_direction") == "unknown":
                    issues.append(self._issue(index, "station_turnback_direction_unknown", "具备折返能力但折返方向未知", "turnback_direction", blocking=False))
                if values.get("terminal_extension_enabled") and not values.get("is_line_terminal"):
                    issues.append(self._issue(index, "station_terminal_extension_without_terminal", "非线路端点不能启用端点延伸区间", "terminal_extension_enabled", blocking=False))
                terminal_mileage = str(values.get("terminal_endpoint_mileage_text") or "")
                if terminal_mileage and parse_track_mileage(terminal_mileage).error:
                    issues.append(self._issue(index, "station_terminal_endpoint_mileage_invalid", "端点里程格式无效", "terminal_endpoint_mileage_text", blocking=False))
            elif change["entity_type"] == "section":
                old_name = str(values.get("old_name") or "")
                old_section = next((item for item in existing_sections if item.name == old_name), None)
                if old_section:
                    section_names.pop(old_section.name.casefold(), None)
                    if old_section.generation_key:
                        generation_keys.pop(old_section.generation_key, None)
                if change["action"] == "delete":
                    continue
                name_key = str(values.get("name") or "").casefold()
                if name_key in section_names and section_names[name_key] != change.get("entity_id"):
                    issues.append(self._issue(index, "section_generation_conflict", "区间名称已存在", "name"))
                section_names[name_key] = str(change.get("entity_id") or f"new:{index}")
                generation_key = str(values.get("generation_key") or "")
                if generation_key:
                    if generation_key in generation_keys and generation_keys[generation_key] != change.get("entity_id"):
                        issues.append(self._issue(index, "section_duplicate_generation_key", "自动区间生成标识重复", "generation_key"))
                    generation_keys[generation_key] = str(change.get("entity_id") or f"new:{index}")
                for prefix in ("start", "end"):
                    node_type = str(values.get(f"{prefix}_node_type") or "legacy")
                    node_uid = str(values.get(f"{prefix}_node_uid") or "")
                    station_name = str(values.get(f"{prefix}_station") or "")
                    if node_type == "station" and not node_uid and station_name in station_by_name:
                        node_uid = station_by_name[station_name]
                        values[f"{prefix}_node_uid"] = node_uid
                    if node_type == "station" and node_uid not in station_uids:
                        code = "section_generation_node_identity_missing" if values.get("auto_generated") else "SECTION_STATION_UNKNOWN"
                        issues.append(self._issue(index, code, "区间引用的正式站点不存在", f"{prefix}_node_uid"))
                    elif node_type == "terminal_endpoint" and not node_uid.startswith("endpoint:"):
                        issues.append(self._issue(index, "section_generation_node_identity_missing", "区间端点稳定标识无效", f"{prefix}_node_uid"))
                    elif node_type in {"legacy", "unknown"} and not node_uid:
                        issues.append(self._issue(index, "section_legacy_node_unresolved", "区间尚未关联正式节点", f"{prefix}_node_uid", blocking=False))
                if (
                    values.get("start_node_uid")
                    and values.get("start_node_uid") == values.get("end_node_uid")
                ):
                    issues.append(self._issue(index, "section_direction_mismatch", "区间起始节点和终到节点不能相同", "start_node_uid"))
            elif change["entity_type"] == "trackside_ap":
                if change["action"] in {"update", "delete"}:
                    ap_macs = {mac: entity for mac, entity in ap_macs.items() if entity != change.get("entity_id")}
                if change["action"] != "delete":
                    mac = str(values.get("ap_mac_norm") or "")
                    if mac and mac in ap_macs:
                        issues.append(self._issue(index, "AP_MAC_DUPLICATE", "同一局点存在重复 AP MAC", "mac"))
                    if mac:
                        ap_macs[mac] = str(change.get("entity_id") or f"new:{index}")
            elif change["entity_type"] == "vehicle_mr" and change["action"] == "delete":
                mr = self.query_service.get_mr(site_id, str(change.get("entity_id") or ""))
                if mr and self._mr_has_history(site_id, mr.mr.name):
                    issues.append(self._issue(index, "MR_HISTORY_EXISTS", "车载 MR 已有关联历史，禁止直接删除", "name"))
        return issues

    def _all_stations(self, site_id: str):
        items = []
        page = 1
        while True:
            page_data = self.query_service.list_stations(site_id, page=page, page_size=200)
            items.extend(page_data.items)
            if len(items) >= page_data.total or not page_data.items:
                return items
            page += 1

    def _all_sections(self, site_id: str):
        items = []
        page = 1
        while True:
            page_data = self.query_service.list_sections(site_id, page=page, page_size=200)
            items.extend(page_data.items)
            if len(items) >= page_data.total or not page_data.items:
                return items
            page += 1

    def _mr_has_history(self, site_id: str, name: str) -> bool:
        try:
            return any(item.mr_name == name for item in self.query_service.online_mr_query.list_sessions(site_id, limit=1000))
        except (OSError, ValueError):
            return True

    @staticmethod
    def _validate_plan_networks(rows: list[dict[str, object | None]]) -> None:
        networks: list[tuple[str, ipaddress.IPv4Network]] = []
        for row in rows:
            station = str(row.get("station_name") or "")
            start_text = str(row.get("ap_start_address") or "").strip()
            gateway_text = str(row.get("ap_gateway") or "").strip()
            count = int(row.get("ap_count") or 0)
            mask = row.get("mask_length")
            if not start_text or "X" in start_text.upper():
                continue
            if mask is None:
                raise ValueError(f"{station}：填写 AP 起始地址时必须填写掩码")
            start = ipaddress.IPv4Address(start_text)
            network = ipaddress.IPv4Network(f"{start}/{int(mask)}", strict=False)
            if gateway_text and ipaddress.IPv4Address(gateway_text) not in network:
                raise ValueError(f"{station}：AP 网关不在规划网段内")
            if count and int(start) + count - 1 > int(network.broadcast_address):
                raise ValueError(f"{station}：规划地址段容量不足")
            for other_station, other in networks:
                if network.overlaps(other):
                    raise ValueError(f"{station} 与 {other_station} 的规划网段冲突")
            networks.append((station, network))

    @classmethod
    def _reject_sensitive(cls, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).casefold() in _SENSITIVE_KEYS:
                    raise ValueError("基础资料请求不得包含凭据或敏感字段")
                cls._reject_sensitive(item)
        elif isinstance(value, list):
            for item in value:
                cls._reject_sensitive(item)

    @staticmethod
    def _issue(
        index: int,
        code: str,
        message: str,
        field_name: str = "",
        *,
        blocking: bool = True,
    ) -> BaseDataValidationIssueDTO:
        return BaseDataValidationIssueDTO(
            change_index=index,
            code=code,
            message=message,
            field_name=field_name,
            blocking=blocking,
        )


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _bool(value: Any, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "y", "是"}:
        return True
    if text in {"false", "0", "no", "n", "否"}:
        return False
    return bool(value)


def _enum(value: Any, allowed: set[str], default: str, message: str) -> str:
    text = str(value or default).strip() or default
    if text not in allowed:
        raise ValueError(message)
    return text


__all__ = ["RailTransitBaseDataApplicationError", "RailTransitBaseDataApplicationService"]
