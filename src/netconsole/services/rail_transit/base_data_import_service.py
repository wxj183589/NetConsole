from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import (
    FieldProvenanceDTO,
    ImportPreviewRowDTO,
    MergeFieldDiffDTO,
    MergePlanDTO,
    MergePlanItemDTO,
    MergePlanSummaryDTO,
)
from netconsole.repositories.rail_transit_base_data_repository import (
    AP_MERGE_FIELDS,
    RailTransitBaseDataRepository,
)
from netconsole.services.rail_transit.source_policy import (
    BASE_DATA_WRITE_ENV,
    SOURCE_PRIORITIES,
    field_action,
    is_blocking_issue,
    match_trackside_ap,
)


PREVIEW_TTL_MINUTES = 15


class BaseDataImportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RailTransitBaseDataImportService:
    """合并计划与受控写入；生产默认关闭，Web 本阶段不暴露 apply。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        repository: RailTransitBaseDataRepository | None = None,
        write_enabled: bool | None = None,
    ) -> None:
        self.paths = paths
        self.repository = repository or RailTransitBaseDataRepository(paths)
        self.write_enabled = (
            os.getenv(BASE_DATA_WRITE_ENV, "0").strip() == "1" if write_enabled is None else bool(write_enabled)
        )

    def inspect_import(self, **kwargs: Any) -> MergePlanDTO:
        return self.build_merge_plan(**kwargs)

    def build_merge_plan(
        self,
        *,
        site_id: str,
        rows: Iterable[ImportPreviewRowDTO],
        source_file_name: str,
        source_file_sha256: str,
        source_type: str = "official_point_table",
    ) -> MergePlanDTO:
        now = datetime.now(timezone.utc)
        safe_file_name = Path(source_file_name).name
        existing = self.repository.list_ap_records(site_id)
        by_id = {f"ap:{row['id']}": row for row in existing}
        items = [
            self._plan_item(row, existing, by_id, safe_file_name, source_type, now)
            for row in rows
        ]
        counts = Counter(item.result for item in items)
        return MergePlanDTO(
            plan_id=str(uuid4()),
            site_id=site_id,
            source_file_name=safe_file_name,
            source_file_sha256=source_file_sha256,
            source_type=source_type,
            database_hash=self.repository.database_hash(site_id),
            created_at=now.isoformat(),
            preview_expires_at=(now + timedelta(minutes=PREVIEW_TTL_MINUTES)).isoformat(),
            write_enabled=self.write_enabled,
            items=items,
            summary=MergePlanSummaryDTO(
                create_count=counts["CREATE"],
                update_count=counts["UPDATE"],
                unchanged_count=counts["UNCHANGED"],
                skip_count=counts["SKIP"],
                conflict_count=counts["CONFLICT"],
                needs_confirmation_count=counts["NEEDS_CONFIRMATION"],
                blocking_count=sum(item.blocking for item in items),
            ),
        )

    def validate_merge_plan(self, plan: MergePlanDTO) -> None:
        try:
            expires_at = datetime.fromisoformat(plan.preview_expires_at)
            if expires_at.tzinfo is None:
                raise ValueError("timezone missing")
        except (TypeError, ValueError) as exc:
            raise BaseDataImportError("BASE_DATA_PREVIEW_EXPIRED", "合并预览时间无效") from exc
        if expires_at <= datetime.now(timezone.utc):
            raise BaseDataImportError("BASE_DATA_PREVIEW_EXPIRED", "合并预览已过期，请重新预览")
        if self.repository.database_hash(plan.site_id) != plan.database_hash:
            raise BaseDataImportError("BASE_DATA_DATABASE_CHANGED", "基础资料数据库已变化，请重新预览")
        if any(item.blocking or item.result == "CONFLICT" for item in plan.items):
            raise BaseDataImportError("BASE_DATA_BLOCKING_ISSUES", "合并计划包含阻断问题")
        if any(item.result == "NEEDS_CONFIRMATION" for item in plan.items):
            raise BaseDataImportError("BASE_DATA_IMPORT_CONFLICT", "合并计划仍有待人工确认字段")

    def apply_merge_plan(self, plan: MergePlanDTO, *, confirmed: bool, owner: str = "") -> dict[str, Any]:
        if not self.write_enabled:
            raise BaseDataImportError("BASE_DATA_WRITE_DISABLED", "轨道交通基础资料正式写入未启用")
        if not confirmed:
            raise BaseDataImportError("BASE_DATA_IMPORT_CONFLICT", "正式写入需要明确确认")
        self.validate_merge_plan(plan)
        operation_id = self._operation_id(plan.plan_id)
        audit_path = self._audit_path(plan.site_id, operation_id)
        if audit_path.exists():
            raise BaseDataImportError("BASE_DATA_IMPORT_CONFLICT", "该合并计划已经处理")
        backup_path = self._backup_path(plan.site_id, operation_id)
        database_hash_before = self.repository.database_hash(plan.site_id)
        try:
            self.repository.backup_database(plan.site_id, backup_path)
        except Exception as exc:
            raise BaseDataImportError("BASE_DATA_BACKUP_FAILED", "基础资料数据库备份失败") from exc
        audit = self._audit_payload(plan, operation_id, owner, backup_path, database_hash_before)
        self._write_audit(audit_path, audit)
        operations = self._operations(plan)
        try:
            changes = self.repository.apply_operations(plan.site_id, operation_id, operations)
            database_hash_after = self.repository.database_hash(plan.site_id)
            audit.update(
                status="APPLIED",
                applied_at=datetime.now(timezone.utc).isoformat(),
                database_hash_after=database_hash_after,
                changes=changes,
            )
            self._write_audit(audit_path, audit)
            return dict(audit)
        except Exception as exc:
            audit.update(status="FAILED", error_summary="事务已回滚，数据库未产生部分写入")
            self._write_audit(audit_path, audit)
            raise BaseDataImportError("BASE_DATA_TRANSACTION_FAILED", "基础资料事务写入失败并已回滚") from exc

    def rollback_import(self, *, site_id: str, operation_id: str) -> dict[str, Any]:
        if not self.write_enabled:
            raise BaseDataImportError("BASE_DATA_WRITE_DISABLED", "轨道交通基础资料正式写入未启用")
        operation_id = self._operation_id(operation_id)
        path = self._audit_path(site_id, operation_id)
        audit = self._read_audit(path)
        if audit.get("status") != "APPLIED":
            raise BaseDataImportError("BASE_DATA_ROLLBACK_CONFLICT", "只有已应用且未回滚的操作可以回滚")
        if self.repository.database_hash(site_id) != audit.get("database_hash_after"):
            raise BaseDataImportError("BASE_DATA_ROLLBACK_CONFLICT", "数据库在导入后已变化，禁止覆盖后续合法修改")
        try:
            self.repository.rollback_changes(site_id, audit.get("changes") or [])
            audit.update(
                status="ROLLED_BACK",
                rolled_back_at=datetime.now(timezone.utc).isoformat(),
                database_hash_rollback=self.repository.database_hash(site_id),
            )
            self._write_audit(path, audit)
            return audit
        except BaseDataImportError:
            raise
        except Exception as exc:
            raise BaseDataImportError("BASE_DATA_TRANSACTION_FAILED", "基础资料回滚事务失败") from exc

    def _plan_item(
        self,
        row: ImportPreviewRowDTO,
        existing: list[dict[str, Any]],
        by_id: Mapping[str, dict[str, Any]],
        source_file_name: str,
        source_type: str,
        now: datetime,
    ) -> MergePlanItemDTO:
        values = {field: row.values.get(field) for field in AP_MERGE_FIELDS if field in row.values}
        values["source_file"] = source_file_name
        match = match_trackside_ap(values, existing)
        issues = [
            issue.model_copy(update={"blocking": issue.blocking or is_blocking_issue(issue.code, issue.severity)})
            for issue in row.issues
        ]
        blocking = any(issue.blocking for issue in issues) or match.status == "conflict"
        current = by_id.get(match.entity_id, {})
        diffs: list[MergeFieldDiffDTO] = []
        for field in (item for item in AP_MERGE_FIELDS if item not in {"source_file", "source_sheet", "source_row"}):
            proposed = values.get(field)
            if proposed is None or proposed == "":
                continue
            current_value = current.get(field)
            action = "use_imported" if match.status == "create" else field_action(
                current_value,
                proposed,
                source_type=source_type,
            )
            if action == "keep_existing" and str(current_value or "") == str(proposed or ""):
                continue
            diffs.append(
                MergeFieldDiffDTO(
                    field_name=field,
                    current_value=current_value,
                    proposed_value=proposed,
                    source=FieldProvenanceDTO(
                        field_name=field,
                        value=proposed,
                        source_type=source_type,
                        source_reference=source_file_name,
                        source_row=row.row_number,
                        imported_at=now.isoformat(),
                        confirmed=False,
                        priority=SOURCE_PRIORITIES.get(source_type, 0),
                        warning="现有正式值不会被自动覆盖" if action == "manual_review" else "",
                    ),
                    action=action,  # type: ignore[arg-type]
                    warning="现有正式值与导入值不同" if action == "manual_review" else "",
                )
            )
        has_business_value = any(
            str(values.get(field) or "").strip()
            for field in AP_MERGE_FIELDS
            if field not in {"source_file", "source_sheet", "source_row"}
        )
        if not has_business_value:
            result = "SKIP"
        elif blocking:
            result = "CONFLICT"
        elif not any(str(values.get(field) or "").strip() for field in ("ap_name", "ap_mac_norm", "ap_mac_display")):
            result = "NEEDS_CONFIRMATION"
        elif match.status == "create":
            result = "NEEDS_CONFIRMATION" if not values.get("ap_name") or not values.get("ap_mac_norm") else "CREATE"
        elif any(diff.action == "manual_review" for diff in diffs):
            result = "NEEDS_CONFIRMATION"
        elif diffs:
            result = "UPDATE"
        else:
            result = "UNCHANGED"
        return MergePlanItemDTO(
            row_number=row.row_number,
            source_identity={
                "ap_name": values.get("ap_name") or "",
                "ap_mac": values.get("ap_mac_display") or values.get("ap_mac_norm") or "",
                "ap_point_code": values.get("ap_point_code") or "",
            },
            matched_entity_id=match.entity_id,
            matched_entity_name=str(current.get("ap_name") or ""),
            match_method=match.method,
            result=result,  # type: ignore[arg-type]
            conflict_summary=match.warning,
            field_diffs=diffs,
            source_values=values,
            blocking=blocking,
            issues=issues,
        )

    @staticmethod
    def _operations(plan: MergePlanDTO) -> list[dict[str, Any]]:
        operations = []
        for item in plan.items:
            if item.result == "CREATE":
                operations.append({"kind": "create", "values": item.source_values})
            elif item.result == "UPDATE":
                fields = {
                    diff.field_name: diff.proposed_value
                    for diff in item.field_diffs
                    if diff.action in {"fill_missing", "use_imported"}
                }
                fields["source_file"] = plan.source_file_name
                operations.append({"kind": "update", "entity_id": item.matched_entity_id, "values": fields})
        return operations

    def _audit_payload(
        self,
        plan: MergePlanDTO,
        operation_id: str,
        owner: str,
        backup_path: Path,
        database_hash_before: str,
    ) -> dict[str, Any]:
        root = self.paths.rail_transit_base_data_import_root(plan.site_id).resolve()
        return {
            "operation_id": operation_id,
            "site_id": plan.site_id,
            "source_file_name": Path(plan.source_file_name).name,
            "source_file_sha256": plan.source_file_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "applied_at": "",
            "status": "STARTING",
            "created_count": plan.summary.create_count,
            "updated_count": plan.summary.update_count,
            "skipped_count": plan.summary.skip_count + plan.summary.unchanged_count,
            "conflict_count": plan.summary.conflict_count,
            "backup_reference": backup_path.resolve().relative_to(root).as_posix(),
            "database_hash_before": database_hash_before,
            "database_hash_after": "",
            "warnings": ["NEEDS_CONFIRMATION"] if plan.summary.needs_confirmation_count else [],
            "error_summary": "",
            "owner": self._safe_owner(owner),
            "changes": [],
        }

    def _audit_path(self, site_id: str, operation_id: str) -> Path:
        return self.paths.rail_transit_base_data_import_operations_dir(site_id) / f"{operation_id}.json"

    def _backup_path(self, site_id: str, operation_id: str) -> Path:
        return self.paths.rail_transit_base_data_import_backups_dir(site_id) / f"{operation_id}.sqlite"

    @staticmethod
    def _operation_id(value: str) -> str:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "导入操作标识无效") from exc

    @staticmethod
    def _safe_owner(value: str) -> str:
        owner = str(value or "").strip()[:100]
        lowered = owner.casefold()
        sensitive_words = ("password", "token", "secret", "community", "credential", "密码", "口令")
        if any(word in lowered for word in sensitive_words) or "/" in owner or "\\" in owner:
            return ""
        return owner

    @staticmethod
    def _write_audit(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _read_audit(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "导入审计记录不可读") from exc
        if not isinstance(payload, dict):
            raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "导入审计记录格式无效")
        return payload


__all__ = ["BaseDataImportError", "RailTransitBaseDataImportService"]
