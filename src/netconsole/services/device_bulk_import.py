from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.core.device_credential_store import (
    CredentialFieldResolution,
    DEVICE_SECRET_FIELDS,
    ensure_device_credential_schema,
    replace_device_credential_state,
)
from netconsole.models.device import Device
from netconsole.models.device_address import (
    DeviceAddressError,
    normalize_ip_address,
)
from netconsole.services.device_import_export import (
    ImportPreviewError,
    ImportPreviewResult,
    ImportPreviewRowResult,
    ImportResult,
)
from netconsole.services.file_contract import read_validated_csv_rows


MATCH_STRATEGIES = {"DEVICE_ID", "SITE_PRIMARY_IP", "DEVICE_NAME"}
WRITE_MODES = {"UPDATE_ONLY", "UPSERT"}
CLEAR_MARKER = "__CLEAR__"
_MATCH_FIELDS = {"device_id", "original_primary_address"}
_SECRET_FIELDS = {
    "password",
    "ssh_password",
    "telnet_password",
    "tunnel1_password",
    "tunnel2_password",
    "snmp_ro_community",
}


@dataclass
class _PlanRow:
    line: int
    source: dict[str, object | None]
    action: str
    match_strategy: str
    match_basis: str = ""
    target: Device | None = None
    prepared: Device | None = None
    group_name: str | None = None
    error_code: str = ""
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def hard_error(self) -> bool:
        return bool(self.error_code)


class DeviceBulkImportService:
    def __init__(self, base_service) -> None:
        self.base = base_service
        self.repository = base_service.repository
        self.group_repository = base_service.group_repository

    def preview_csv(
        self,
        path: Path,
        *,
        match_strategy: str,
        write_mode: str,
    ) -> ImportPreviewResult:
        strategy, mode = self._validate_options(match_strategy, write_mode)
        rows, _metadata, detected_encoding = read_validated_csv_rows(Path(path))
        if not rows:
            raise ValueError("文件为空")
        columns = tuple(str(value).strip() for value in rows[0])
        template_mode = self.base._detect_mode(list(columns))
        mapped_rows = [
            (line, self.base._map_row(list(columns), values, template_mode))
            for line, values in enumerate(rows[1:], start=2)
            if any(str(value).strip() for value in values)
        ]
        with self.repository.database.connect() as conn:
            plan = self._build_plan(conn, mapped_rows, strategy, mode)
        return self._preview_result(
            plan,
            columns=columns,
            detected_encoding=detected_encoding,
        )

    def apply_csv_atomic(
        self,
        path: Path,
        *,
        match_strategy: str,
        write_mode: str,
        check_cancelled: Callable[[], None] | None = None,
    ) -> ImportResult:
        strategy, mode = self._validate_options(match_strategy, write_mode)
        rows, _metadata, _detected_encoding = read_validated_csv_rows(Path(path))
        if not rows:
            return ImportResult(created=0, updated=0, skipped=0, errors=[])
        columns = [str(value).strip() for value in rows[0]]
        template_mode = self.base._detect_mode(columns)
        mapped_rows = [
            (line, self.base._map_row(columns, values, template_mode))
            for line, values in enumerate(rows[1:], start=2)
            if any(str(value).strip() for value in values)
        ]
        if check_cancelled is not None:
            check_cancelled()
        created = 0
        updated = 0
        unchanged = 0
        groups_created = 0
        with self.repository.database.connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                plan = self._build_plan(conn, mapped_rows, strategy, mode)
                errors = [row for row in plan if row.hard_error]
                if errors:
                    summary = "；".join(
                        f"第 {row.line} 行 {row.message}" for row in errors
                    )
                    raise ValueError(f"批量预检未通过，未写入任何设备：{summary}")
                ensure_device_credential_schema(conn)
                changed_ids = [
                    int(row.target.id)
                    for row in plan
                    if row.action == "UPDATE"
                    and row.target is not None
                    and row.target.id is not None
                ]
                if changed_ids:
                    placeholders = ", ".join("?" for _ in changed_ids)
                    conn.execute(
                        f"""
                        UPDATE devices
                        SET normalized_primary_address = NULL
                        WHERE id IN ({placeholders})
                        """,
                        changed_ids,
                    )
                for row in plan:
                    if check_cancelled is not None:
                        check_cancelled()
                    if row.action == "UNCHANGED":
                        unchanged += 1
                        continue
                    if row.prepared is None:
                        continue
                    group_id, was_created = self._resolve_group(
                        conn, row.group_name
                    )
                    groups_created += was_created
                    if row.group_name is not None:
                        row.prepared.group_id = group_id
                    if row.action == "CREATE":
                        self._insert_device(conn, row)
                        created += 1
                    elif row.action == "UPDATE":
                        self._update_device(conn, row)
                        updated += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return ImportResult(
            created=created,
            updated=updated,
            unchanged=unchanged,
            skipped=0,
            errors=[],
            groups_created=groups_created,
        )

    def _build_plan(
        self,
        conn: sqlite3.Connection,
        mapped_rows: list[tuple[int, dict[str, object | None]]],
        match_strategy: str,
        write_mode: str,
    ) -> list[_PlanRow]:
        existing = [
            Device.from_mapping(dict(row))
            for row in conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        ]
        by_id = {int(device.id): device for device in existing if device.id is not None}
        by_address: dict[str, list[Device]] = {}
        by_name: dict[str, list[Device]] = {}
        for device in existing:
            normalized = normalize_ip_address(device.primary_address)
            if normalized:
                by_address.setdefault(normalized, []).append(device)
            by_name.setdefault(str(device.name or "").strip().casefold(), []).append(
                device
            )
        group_names = {
            int(row["id"]): str(row["name"])
            for row in conn.execute("SELECT id, name FROM device_groups").fetchall()
        }
        plan: list[_PlanRow] = []
        targeted: dict[int, _PlanRow] = {}
        for line, source in mapped_rows:
            row = self._plan_row(
                line,
                dict(source),
                match_strategy,
                write_mode,
                by_id,
                by_address,
                by_name,
                group_names,
            )
            if (
                not row.hard_error
                and row.target is not None
                and row.target.id is not None
            ):
                target_id = int(row.target.id)
                previous = targeted.get(target_id)
                if previous is not None:
                    row.action = "CONFLICT"
                    row.error_code = "MULTIPLE_ROWS_TARGET_SAME_DEVICE"
                    row.message = (
                        f"与第 {previous.line} 行匹配到同一设备 ID {target_id}"
                    )
                else:
                    targeted[target_id] = row
            plan.append(row)
        self._validate_final_addresses(plan, existing)
        self._add_backup_address_warnings(plan, existing)
        return plan

    def _plan_row(
        self,
        line: int,
        source: dict[str, object | None],
        match_strategy: str,
        write_mode: str,
        by_id: dict[int, Device],
        by_address: dict[str, list[Device]],
        by_name: dict[str, list[Device]],
        group_names: dict[int, str],
    ) -> _PlanRow:
        device_name = str(source.get("name") or "").strip()
        target: Device | None = None
        basis = ""
        try:
            target, basis = self._match_device(
                source, match_strategy, by_id, by_address, by_name
            )
        except DeviceAddressError as exc:
            return _PlanRow(
                line,
                source,
                "INVALID",
                match_strategy,
                error_code=exc.code,
                message=exc.message,
            )
        except ValueError as exc:
            code = str(exc.args[1]) if len(exc.args) > 1 else "DEVICE_NOT_FOUND"
            return _PlanRow(
                line,
                source,
                "CONFLICT" if "CONFLICT" in code else "INVALID",
                match_strategy,
                error_code=code,
                message=str(exc.args[0]),
            )
        if target is None and write_mode == "UPDATE_ONLY":
            return _PlanRow(
                line,
                source,
                "NOT_FOUND",
                match_strategy,
                match_basis=basis,
                error_code="DEVICE_NOT_FOUND",
                message=f"当前局点内未匹配到设备：{basis or device_name or '无匹配依据'}",
            )
        try:
            prepared, group_name = self._prepare_device(source, target)
        except DeviceAddressError as exc:
            return _PlanRow(
                line,
                source,
                "INVALID",
                match_strategy,
                match_basis=basis,
                target=target,
                error_code=exc.code,
                message=exc.message,
            )
        except (TypeError, ValueError) as exc:
            return _PlanRow(
                line,
                source,
                "INVALID",
                match_strategy,
                match_basis=basis,
                target=target,
                error_code="INVALID_DEVICE_ROW",
                message=str(exc) or "设备字段校验失败",
            )
        if target is None:
            action = "CREATE"
        elif self._device_changed(target, prepared, group_name, group_names):
            action = "UPDATE"
        else:
            action = "UNCHANGED"
        return _PlanRow(
            line,
            source,
            action,
            match_strategy,
            match_basis=basis,
            target=target,
            prepared=prepared,
            group_name=group_name,
            message=(
                "当前局点未找到匹配设备，将新增"
                if action == "CREATE"
                else "设备资料将更新"
                if action == "UPDATE"
                else "设备资料无变化"
            ),
        )

    def _match_device(
        self,
        source: dict[str, object | None],
        match_strategy: str,
        by_id: dict[int, Device],
        by_address: dict[str, list[Device]],
        by_name: dict[str, list[Device]],
    ) -> tuple[Device | None, str]:
        raw_id = source.get("device_id")
        if match_strategy in {"DEVICE_ID", "SITE_PRIMARY_IP"} and raw_id is not None:
            try:
                device_id = int(str(raw_id).strip())
            except ValueError as exc:
                raise ValueError("设备 ID 必须是整数", "INVALID_DEVICE_ID") from exc
            target = by_id.get(device_id)
            if target is None:
                raise ValueError(
                    f"当前局点不存在设备 ID {device_id}", "DEVICE_NOT_FOUND"
                )
            return target, f"设备 ID {device_id}"
        if match_strategy == "DEVICE_ID":
            raise ValueError("按设备 ID 更新时设备ID必填", "DEVICE_ID_REQUIRED")
        if match_strategy == "DEVICE_NAME":
            name = str(source.get("name") or "").strip()
            if not name:
                raise ValueError("按设备名称更新时设备名称必填", "DEVICE_NAME_REQUIRED")
            matches = by_name.get(name.casefold(), [])
            if len(matches) > 1:
                raise ValueError(
                    f"设备名称“{name}”在当前局点匹配到多台设备",
                    "DEVICE_NAME_CONFLICT",
                )
            return (matches[0] if matches else None), f"设备名称 {name}"
        raw_original = source.get("original_primary_address")
        raw_current = source.get("primary_address")
        raw_basis = raw_original if raw_original is not None else raw_current
        normalized = normalize_ip_address(raw_basis, allow_empty=False)
        matches = by_address.get(str(normalized), [])
        if len(matches) > 1:
            raise ValueError(
                f"主地址 {normalized} 在当前局点匹配到多台设备",
                "DATABASE_PRIMARY_IP_CONFLICT",
            )
        label = "原主地址" if raw_original is not None else "当前局点主地址"
        return (matches[0] if matches else None), f"{label} {normalized}"

    def _prepare_device(
        self, source: dict[str, object | None], target: Device | None
    ) -> tuple[Device, str | None]:
        record = target.to_record() if target is not None else {}
        group_value = source.get("group_name")
        group_name: str | None = None
        if group_value is not None:
            group_name = (
                ""
                if str(group_value).strip() == CLEAR_MARKER
                else str(group_value).strip()
            )
        explicit_clears: set[str] = set()
        for key, value in source.items():
            if key in _MATCH_FIELDS or key == "group_name" or value is None:
                continue
            if str(value).strip() == CLEAR_MARKER:
                record[key] = None
                explicit_clears.add(key)
            else:
                record[key] = value
        if target is None:
            if not str(record.get("name") or "").strip():
                raise ValueError("新增设备时设备名称必填")
            if not str(record.get("primary_address") or "").strip():
                raise ValueError("新增设备时主用地址必填")
        primary = normalize_ip_address(record.get("primary_address"))
        backup = normalize_ip_address(record.get("backup_address"), field="备用地址")
        record["primary_address"] = primary or ""
        record["normalized_primary_address"] = primary
        record["backup_address"] = backup
        validation = dict(record)
        validation.pop("device_uuid", None)
        validation.pop("id", None)
        validation.pop("created_at", None)
        validation.pop("updated_at", None)
        self.base._apply_defaults(validation)
        if "password" in explicit_clears:
            if str(validation.get("protocol") or "").casefold() == "telnet":
                validation["telnet_password"] = None
            else:
                validation["ssh_password"] = None
        self.base._validate_payload(validation)
        record.update(validation)
        if not str(record.get("name") or "").strip():
            raise ValueError("设备名称不能为空")
        if not record.get("primary_address") and not record.get("backup_address"):
            raise ValueError("主用地址和备用地址不能同时为空")
        if target is None:
            record.pop("id", None)
            record.pop("device_uuid", None)
            record.pop("created_at", None)
            record.pop("updated_at", None)
        return Device.from_mapping(record), group_name

    @staticmethod
    def _device_changed(
        target: Device,
        prepared: Device,
        group_name: str | None,
        group_names: dict[int, str],
    ) -> bool:
        ignored = {"id", "device_uuid", "created_at", "updated_at"}
        for field_name in Device.field_names():
            if field_name in ignored or field_name == "group_id":
                continue
            if getattr(target, field_name) != getattr(prepared, field_name):
                return True
        if group_name is not None:
            current = group_names.get(int(target.group_id or 0), "")
            return current.casefold() != group_name.casefold()
        return False

    def _validate_final_addresses(
        self, plan: list[_PlanRow], existing: list[Device]
    ) -> None:
        final: dict[object, str] = {}
        for device in existing:
            if device.id is None:
                continue
            normalized = normalize_ip_address(device.primary_address)
            if normalized:
                final[int(device.id)] = normalized
        for row in plan:
            if row.hard_error or row.prepared is None:
                continue
            key: object = (
                int(row.target.id)
                if row.target is not None and row.target.id is not None
                else f"line:{row.line}"
            )
            normalized = row.prepared.normalized_primary_address
            if normalized:
                final[key] = normalized
            else:
                final.pop(key, None)
        addresses: dict[str, list[object]] = {}
        for key, normalized in final.items():
            addresses.setdefault(normalized, []).append(key)
        for normalized, keys in addresses.items():
            if len(keys) < 2:
                continue
            for row in plan:
                if row.hard_error or row.prepared is None:
                    continue
                key = (
                    int(row.target.id)
                    if row.target is not None and row.target.id is not None
                    else f"line:{row.line}"
                )
                if key not in keys:
                    continue
                row.action = "CONFLICT"
                row.error_code = "DUPLICATE_PRIMARY_IP_IN_FILE"
                row.message = (
                    f"批量变更后的主地址 {normalized} 与当前局点其他设备冲突"
                )

    @staticmethod
    def _add_backup_address_warnings(
        plan: list[_PlanRow], existing: list[Device]
    ) -> None:
        existing_primary = {
            DeviceBulkImportService._safe_normalize(device.primary_address)
            for device in existing
            if DeviceBulkImportService._safe_normalize(device.primary_address)
        }
        existing_backup = {
            DeviceBulkImportService._safe_normalize(device.backup_address)
            for device in existing
            if DeviceBulkImportService._safe_normalize(device.backup_address)
        }
        for row in plan:
            if row.prepared is None:
                continue
            primary = row.prepared.normalized_primary_address
            backup = normalize_ip_address(
                row.prepared.backup_address, field="备用地址"
            )
            if primary and backup and primary == backup:
                row.warnings.append("同一设备的主地址与备用地址相同")
            if backup and backup in existing_primary:
                row.warnings.append("备用地址与当前局点设备主地址重复")
            if primary and primary in existing_backup:
                row.warnings.append("主地址与当前局点设备备用地址重复")

    @staticmethod
    def _safe_normalize(value: object) -> str | None:
        try:
            return normalize_ip_address(value)
        except DeviceAddressError:
            return None

    def _preview_result(
        self,
        plan: list[_PlanRow],
        *,
        columns: tuple[str, ...],
        detected_encoding: str,
    ) -> ImportPreviewResult:
        errors = tuple(
            ImportPreviewError(
                line=row.line,
                device_name=str(
                    (row.prepared or row.target).name
                    if (row.prepared or row.target)
                    else row.source.get("name") or ""
                ),
                field="",
                raw_value="",
                message=row.message,
                code=row.error_code,
            )
            for row in plan
            if row.hard_error
        )
        row_results = tuple(
            ImportPreviewRowResult(
                line=row.line,
                action=row.action,
                match_strategy=row.match_strategy,
                match_basis=row.match_basis,
                device_id=(
                    int(row.target.id)
                    if row.target is not None and row.target.id is not None
                    else None
                ),
                device_name=str(
                    (row.prepared or row.target).name
                    if (row.prepared or row.target)
                    else row.source.get("name") or ""
                ),
                original_primary_address=str(
                    row.target.primary_address if row.target is not None else ""
                ),
                new_primary_address=str(
                    row.prepared.primary_address if row.prepared is not None else ""
                ),
                message=row.message,
                error_code=row.error_code,
                warnings=tuple(dict.fromkeys(row.warnings)),
            )
            for row in plan
        )
        counts = {
            action: sum(1 for row in plan if row.action == action)
            for action in {
                "CREATE",
                "UPDATE",
                "UNCHANGED",
                "NOT_FOUND",
                "CONFLICT",
                "INVALID",
            }
        }
        vendor_summary: dict[str, int] = {}
        type_summary: dict[str, int] = {}
        for row in plan:
            device = row.prepared or row.target
            if device is None:
                continue
            vendor = str(device.device_vendor or "")
            device_type = str(device.device_type or "")
            vendor_summary[vendor] = vendor_summary.get(vendor, 0) + 1
            type_summary[device_type] = type_summary.get(device_type, 0) + 1
        return ImportPreviewResult(
            total_rows=len(plan),
            valid_rows=len(plan) - len(errors),
            invalid_rows=len(errors),
            vendor_summary=vendor_summary,
            device_type_summary=type_summary,
            create_count=counts["CREATE"],
            update_count=counts["UPDATE"],
            conflict_count=counts["CONFLICT"],
            errors=errors,
            columns=columns,
            duplicate_rows=tuple(
                row.line
                for row in plan
                if row.error_code == "DUPLICATE_PRIMARY_IP_IN_FILE"
            ),
            detected_encoding=detected_encoding,
            unchanged_count=counts["UNCHANGED"],
            not_found_count=counts["NOT_FOUND"],
            row_results=row_results,
            has_hard_errors=bool(errors),
        )

    def _resolve_group(
        self, conn: sqlite3.Connection, group_name: str | None
    ) -> tuple[int | None, int]:
        if group_name is None:
            return None, 0
        if not group_name:
            return None, 0
        if self.group_repository is None:
            return None, 0
        row = conn.execute(
            """
            SELECT id
            FROM device_groups
            WHERE site_id = ? AND name = ? COLLATE NOCASE
            """,
            (self.group_repository.site_id, group_name),
        ).fetchone()
        if row is not None:
            return int(row["id"]), 0
        now = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            """
            INSERT INTO device_groups
                (site_id, name, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self.group_repository.site_id, group_name, 100, now, now),
        )
        return int(cursor.lastrowid), 1

    def _insert_device(self, conn: sqlite3.Connection, row: _PlanRow) -> None:
        device = row.prepared
        assert device is not None
        device.ensure_device_uuid()
        now = datetime.now().isoformat(timespec="seconds")
        record = device.to_record()
        record.update({"created_at": now, "updated_at": now})
        record.pop("id", None)
        columns = list(record)
        conn.execute(
            f"""
            INSERT INTO devices ({', '.join(columns)})
            VALUES ({', '.join('?' for _ in columns)})
            """,
            [record[column] for column in columns],
        )
        for secret_field in DEVICE_SECRET_FIELDS:
            state = (
                CredentialFieldResolution("available", "local_database")
                if record.get(secret_field)
                else None
            )
            replace_device_credential_state(
                conn, str(device.device_uuid), secret_field, state
            )

    def _update_device(self, conn: sqlite3.Connection, row: _PlanRow) -> None:
        device = row.prepared
        target = row.target
        assert device is not None and target is not None and target.id is not None
        record = device.to_record()
        record["updated_at"] = datetime.now().isoformat(timespec="seconds")
        record.pop("id", None)
        record.pop("device_uuid", None)
        record.pop("created_at", None)
        columns = list(record)
        conn.execute(
            f"""
            UPDATE devices
            SET {', '.join(f'{column} = ?' for column in columns)}
            WHERE id = ?
            """,
            [record[column] for column in columns] + [int(target.id)],
        )
        explicit_fields = {
            key
            for key, value in row.source.items()
            if value is not None and (key in _SECRET_FIELDS or key == "protocol")
        }
        if explicit_fields:
            for secret_field in DEVICE_SECRET_FIELDS:
                state = (
                    CredentialFieldResolution("available", "local_database")
                    if record.get(secret_field)
                    else None
                )
                replace_device_credential_state(
                    conn, str(target.device_uuid or ""), secret_field, state
                )

    @staticmethod
    def _validate_options(
        match_strategy: str, write_mode: str
    ) -> tuple[str, str]:
        strategy = str(match_strategy or "").strip().upper()
        mode = str(write_mode or "").strip().upper()
        if strategy not in MATCH_STRATEGIES:
            raise ValueError("不支持的设备匹配方式")
        if mode not in WRITE_MODES:
            raise ValueError("不支持的批量写入模式")
        return strategy, mode
