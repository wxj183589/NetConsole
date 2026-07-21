from __future__ import annotations

import ipaddress
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_base_data import (
    BaseDataChangeDTO,
    BaseDataEditSessionDTO,
    BaseDataSaveResultDTO,
    BaseDataValidationIssueDTO,
    BaseDataValidationResultDTO,
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
from netconsole.services.trackside_ap_plan_io import normalize_trackside_plan_rows
from netconsole.services.vehicle_mr_online import parse_train_identity
from netconsole.utils.mileage import parse_track_mileage


_SENSITIVE_KEYS = {
    "password", "username", "token", "secret", "community", "credential",
    "ssh_password", "telnet_password", "tunnel1_password", "tunnel2_password",
}


class RailTransitBaseDataApplicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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

    def validate_changes(
        self,
        site_id: str,
        base_revision: str,
        changes: Iterable[BaseDataChangeDTO],
    ) -> tuple[BaseDataValidationResultDTO, list[dict[str, Any]]]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        issues: list[BaseDataValidationIssueDTO] = []
        if self.repository.base_data_revision(site_id) != base_revision:
            issues.append(self._issue(0, "BASE_DATA_REVISION_CONFLICT", "基础资料已被其他操作更新，请重新加载"))
        normalized: list[dict[str, Any]] = []
        for index, change in enumerate(changes):
            try:
                normalized.append(self._normalize_change(change))
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
            validation_issues=validation.issues,
        )

    def _normalize_change(self, change: BaseDataChangeDTO) -> dict[str, Any]:
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
            values = self._station_values(raw, action)
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
        return {
            "line_name": line_name[:200],
            "system_type": system_type[:100],
            "network_domain": str(raw.get("network_domain") or "default").strip()[:100],
            "remark": str(raw.get("remark") or "").strip()[:1000],
        }

    @staticmethod
    def _station_values(raw: Mapping[str, Any], action: str) -> dict[str, Any]:
        name = str(raw.get("name") or "").strip()
        old_name = str(raw.get("old_name") or name).strip()
        if not (old_name if action == "delete" else name):
            raise ValueError("站点名称不能为空")
        return {
            "name": name,
            "old_name": old_name,
            "code": str(raw.get("code") or "").strip(),
            "line_name": str(raw.get("line_name") or "").strip(),
            "sort_order": int(raw.get("sort_order") or 0),
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
        return {
            "name": name,
            "old_name": str(raw.get("old_name") or name).strip(),
            "start_station": start,
            "old_start_station": str(raw.get("old_start_station") or start).strip(),
            "end_station": end,
            "old_end_station": str(raw.get("old_end_station") or end).strip(),
            "line_side": str(raw.get("line_side") or "").strip(),
            "old_line_side": str(raw.get("old_line_side") or raw.get("line_side") or "").strip(),
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
        station_names = {item.name for item in self.query_service.list_stations(site_id, page_size=200).items}
        station_codes = {
            item.code.casefold(): item.id
            for item in self.query_service.list_stations(site_id, page_size=200).items
            if item.code
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
                if change["action"] == "delete":
                    station_names.discard(old_name)
                    continue
                name = values["name"]
                if name in station_names and change["action"] == "create":
                    issues.append(self._issue(index, "STATION_DUPLICATE", "站点名称已存在", "name"))
                station_names.discard(old_name)
                station_names.add(name)
                code = str(values.get("code") or "").casefold()
                if code and code in station_codes and station_codes[code] != change.get("entity_id"):
                    issues.append(self._issue(index, "STATION_CODE_DUPLICATE", "站点编码已存在", "code"))
            elif change["entity_type"] == "section" and change["action"] != "delete":
                for field in ("start_station", "end_station"):
                    if values[field] not in station_names:
                        issues.append(self._issue(index, "SECTION_STATION_UNKNOWN", "区间引用的站点不存在", field))
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
    def _issue(index: int, code: str, message: str, field_name: str = "") -> BaseDataValidationIssueDTO:
        return BaseDataValidationIssueDTO(
            change_index=index,
            code=code,
            message=message,
            field_name=field_name,
            blocking=True,
        )


__all__ = ["RailTransitBaseDataApplicationError", "RailTransitBaseDataApplicationService"]
