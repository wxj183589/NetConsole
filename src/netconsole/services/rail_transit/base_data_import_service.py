from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.rail_transit_base_data import (
    FieldProvenanceDTO,
    ImportChangeDTO,
    ImportOperationDTO,
    ImportPreviewRowDTO,
    MergeFieldDecisionDTO,
    MergeFieldDiffDTO,
    MergePlanDTO,
    MergePlanItemDTO,
    MergePlanSummaryDTO,
)
from netconsole.repositories.rail_transit_base_data_repository import (
    AP_MERGE_FIELDS,
    RailTransitBaseDataRepository,
    RailTransitBaseDataRollbackConflict,
)
from netconsole.services.rail_transit.source_policy import (
    SOURCE_PRIORITIES,
    field_action,
    is_blocking_issue,
    is_runtime_field,
    match_trackside_ap,
)
from netconsole.services.rail_transit.base_data_preview_store import (
    BaseDataPreviewStore,
    BaseDataPreviewStoreError,
)
from netconsole.services.rail_transit.base_data_write_guard import (
    BaseDataWriteGuard,
    BaseDataWriteGuardError,
)


PREVIEW_TTL_MINUTES = 15


class BaseDataImportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RailTransitBaseDataImportService:
    """合并计划与受控写入；生产默认关闭，所有 apply 都经过 Guard。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        repository: RailTransitBaseDataRepository | None = None,
        preview_store: BaseDataPreviewStore | None = None,
        guard: BaseDataWriteGuard | None = None,
        write_enabled: bool | None = None,
    ) -> None:
        self.paths = paths
        self.repository = repository or RailTransitBaseDataRepository(paths)
        self.preview_store = preview_store or BaseDataPreviewStore(paths)
        self.guard = guard or BaseDataWriteGuard(paths, write_enabled=write_enabled)
        self.write_enabled = self.guard.write_enabled

    def inspect_import(self, **kwargs: Any) -> MergePlanDTO:
        return self.build_merge_plan(**kwargs)

    def save_preview(self, plan: MergePlanDTO) -> str:
        try:
            return self.preview_store.save(plan)
        except BaseDataPreviewStoreError as exc:
            raise BaseDataImportError(exc.code, str(exc)) from exc

    def apply_preview(
        self,
        *,
        preview_id: str,
        site_id: str,
        expected_database_sha256: str,
        explicit_confirmation: bool,
        decisions: Iterable[MergeFieldDecisionDTO] = (),
        owner: str = "",
    ) -> dict[str, Any]:
        try:
            plan = self.preview_store.load(preview_id)
        except BaseDataPreviewStoreError as exc:
            raise BaseDataImportError(exc.code, str(exc)) from exc
        preview_id = self._operation_id(preview_id)
        if plan.plan_id != preview_id or plan.site_id != site_id:
            raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "导入预览与局点不一致")
        if plan.database_hash != expected_database_sha256:
            raise BaseDataImportError("BASE_DATA_DATABASE_CHANGED", "请求中的数据库哈希与预览不一致")
        resolved = self.resolve_decisions(plan, list(decisions))
        return self.apply_merge_plan(
            resolved,
            confirmed=explicit_confirmation,
            owner=owner,
            decisions=list(decisions),
        )

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

    def resolve_decisions(
        self,
        plan: MergePlanDTO,
        decisions: list[MergeFieldDecisionDTO],
    ) -> MergePlanDTO:
        by_row = {item.row_number: item for item in plan.items}
        selected: dict[tuple[int, str], MergeFieldDecisionDTO] = {}
        skipped_rows: set[int] = set()
        for decision in decisions:
            item = by_row.get(decision.row_number)
            if item is None:
                raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "人工决策引用了不存在的导入行")
            if item.blocking or item.result == "CONFLICT":
                raise BaseDataImportError("BASE_DATA_BLOCKING_ISSUES", "阻断冲突不能通过人工决策绕过")
            if decision.action == "skip_entity":
                if decision.field_name not in {"", "*"}:
                    raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "跳过实体决策不能指定字段")
                skipped_rows.add(decision.row_number)
                continue
            key = (decision.row_number, decision.field_name)
            if not decision.field_name or key in selected:
                raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "人工字段决策无效或重复")
            selected[key] = decision

        resolved_items: list[MergePlanItemDTO] = []
        consumed: set[tuple[int, str]] = set()
        for item in plan.items:
            if item.row_number in skipped_rows:
                if any(key[0] == item.row_number for key in selected):
                    raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "同一实体不能同时跳过并修改字段")
                resolved_items.append(item.model_copy(update={"result": "SKIP"}, deep=True))
                continue
            diffs: list[MergeFieldDiffDTO] = []
            for diff in item.field_diffs:
                key = (item.row_number, diff.field_name)
                decision = selected.get(key)
                if decision is None:
                    diffs.append(diff.model_copy(deep=True))
                    continue
                consumed.add(key)
                self._validate_field_decision(diff, decision)
                diffs.append(
                    diff.model_copy(
                        update={
                            "action": decision.action,
                            "source": diff.source.model_copy(update={"confirmed": True}),
                            "warning": "",
                        },
                        deep=True,
                    )
                )
            if item.result == "CREATE":
                result = "CREATE"
            elif any(diff.action == "manual_review" for diff in diffs):
                result = "NEEDS_CONFIRMATION"
            elif any(diff.action in {"use_imported", "fill_missing"} for diff in diffs):
                result = "UPDATE"
            else:
                result = "UNCHANGED"
            resolved_items.append(item.model_copy(update={"field_diffs": diffs, "result": result}, deep=True))

        if consumed != set(selected):
            raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "人工决策引用了不可修改字段")
        counts = Counter(item.result for item in resolved_items)
        return plan.model_copy(
            update={
                "items": resolved_items,
                "summary": MergePlanSummaryDTO(
                    create_count=counts["CREATE"],
                    update_count=counts["UPDATE"],
                    unchanged_count=counts["UNCHANGED"],
                    skip_count=counts["SKIP"],
                    conflict_count=counts["CONFLICT"],
                    needs_confirmation_count=counts["NEEDS_CONFIRMATION"],
                    blocking_count=sum(item.blocking for item in resolved_items),
                ),
            },
            deep=True,
        )

    @staticmethod
    def _validate_field_decision(diff: MergeFieldDiffDTO, decision: MergeFieldDecisionDTO) -> None:
        if is_runtime_field(diff.field_name):
            raise BaseDataImportError("BASE_DATA_SOURCE_INVALID", "运行态字段不能进入正式资料写入计划")
        if decision.action == "fill_missing" and diff.current_value is not None and diff.current_value != "":
            raise BaseDataImportError("BASE_DATA_IMPORT_CONFLICT", "非空正式字段不能使用 fill_missing")
        if decision.action in {"fill_missing", "use_imported"} and (
            diff.proposed_value is None or diff.proposed_value == ""
        ):
            raise BaseDataImportError("BASE_DATA_IMPORT_CONFLICT", "不允许用空值覆盖或补齐正式字段")

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

    def apply_merge_plan(
        self,
        plan: MergePlanDTO,
        *,
        confirmed: bool,
        owner: str = "",
        decisions: list[MergeFieldDecisionDTO] | None = None,
    ) -> dict[str, Any]:
        try:
            self.guard.authorize_apply(plan.site_id, explicit_confirmation=confirmed)
        except BaseDataWriteGuardError as exc:
            raise BaseDataImportError(exc.code, str(exc)) from exc
        operation_id = self._operation_id(plan.plan_id)
        audit_path = self._audit_path(plan.site_id, operation_id)
        if audit_path.exists():
            raise BaseDataImportError("ALREADY_APPLIED", "该导入预览已经处理，请查询操作状态")
        self.validate_merge_plan(plan)
        backup_path = self._backup_path(plan.site_id, operation_id)
        database_hash_before = self.repository.database_hash(plan.site_id)
        try:
            self.repository.backup_database(plan.site_id, backup_path)
        except Exception as exc:
            failed_audit = self._audit_payload(
                plan,
                operation_id,
                owner,
                backup_path,
                database_hash_before,
                decisions or [],
            )
            failed_audit.update(
                status="FAILED",
                ended_at=datetime.now(timezone.utc).isoformat(),
                error_code="BASE_DATA_BACKUP_FAILED",
                error_summary="基础资料数据库备份失败，未执行业务写入",
            )
            try:
                self._write_audit(audit_path, failed_audit)
            except OSError:
                pass
            raise BaseDataImportError("BASE_DATA_BACKUP_FAILED", "基础资料数据库备份失败") from exc
        audit = self._audit_payload(
            plan,
            operation_id,
            owner,
            backup_path,
            database_hash_before,
            decisions or [],
        )
        try:
            self._write_audit(audit_path, audit)
        except OSError as exc:
            raise BaseDataImportError("BASE_DATA_AUDIT_FAILED", "基础资料审计初始化失败，未执行业务写入") from exc
        operations = self._operations(plan)
        try:
            changes = self.repository.apply_operations(plan.site_id, operation_id, operations)
            self.repository.assert_integrity(plan.site_id)
            database_hash_after = self.repository.database_hash(plan.site_id)
            audit.update(
                status="APPLIED",
                applied_at=datetime.now(timezone.utc).isoformat(),
                ended_at=datetime.now(timezone.utc).isoformat(),
                database_hash_after=database_hash_after,
                changes=changes,
                import_changes=self._flatten_changes(plan, changes, decisions or []),
            )
            self._write_audit(audit_path, audit)
            return dict(audit)
        except Exception as exc:
            if "changes" in locals() and changes:
                try:
                    self.repository.rollback_changes(plan.site_id, changes)
                except Exception:
                    pass
            audit.update(
                status="FAILED",
                ended_at=datetime.now(timezone.utc).isoformat(),
                error_code="BASE_DATA_TRANSACTION_FAILED",
                error_summary="写入失败，事务或已提交变更已回滚；备份保留",
            )
            try:
                self._write_audit(audit_path, audit)
            except OSError:
                pass
            raise BaseDataImportError("BASE_DATA_TRANSACTION_FAILED", "基础资料事务写入失败并已回滚") from exc

    def rollback_import(
        self,
        *,
        site_id: str,
        operation_id: str,
        explicit_confirmation: bool = False,
    ) -> dict[str, Any]:
        try:
            self.guard.authorize_rollback(site_id, explicit_confirmation=explicit_confirmation)
        except BaseDataWriteGuardError as exc:
            raise BaseDataImportError(exc.code, str(exc)) from exc
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
        except RailTransitBaseDataRollbackConflict as exc:
            raise BaseDataImportError(
                "BASE_DATA_ROLLBACK_CONFLICT",
                "基础资料字段已被后续修改，禁止覆盖合法变更",
            ) from exc
        except Exception as exc:
            raise BaseDataImportError("BASE_DATA_TRANSACTION_FAILED", "基础资料回滚事务失败") from exc

    def list_operations(self, site_id: str) -> list[ImportOperationDTO]:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        directory = self.paths.rail_transit_base_data_import_operations_dir(site_id)
        if not directory.is_dir():
            return []
        items = []
        for path in directory.glob("*.json"):
            try:
                items.append(self._operation_dto(self._read_audit(path)))
            except BaseDataImportError:
                continue
        return sorted(items, key=lambda item: item.started_at, reverse=True)

    def get_operation(self, site_id: str, operation_id: str) -> ImportOperationDTO:
        operation_id = self._operation_id(operation_id)
        return self._operation_dto(self._read_audit(self._audit_path(site_id, operation_id)))

    def list_operation_changes(self, site_id: str, operation_id: str) -> list[ImportChangeDTO]:
        operation_id = self._operation_id(operation_id)
        audit = self._read_audit(self._audit_path(site_id, operation_id))
        return [ImportChangeDTO.model_validate(item) for item in audit.get("import_changes") or []]

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
        decisions: list[MergeFieldDecisionDTO],
    ) -> dict[str, Any]:
        root = self.paths.rail_transit_base_data_import_root(plan.site_id).resolve()
        started_at = datetime.now(timezone.utc).isoformat()
        return {
            "operation_id": operation_id,
            "preview_id": plan.plan_id,
            "site_id": plan.site_id,
            "source_file_name": Path(plan.source_file_name).name,
            "source_file_sha256": plan.source_file_sha256,
            "created_at": started_at,
            "started_at": started_at,
            "ended_at": "",
            "applied_at": "",
            "status": "STARTING",
            "created_count": plan.summary.create_count,
            "updated_count": plan.summary.update_count,
            "skipped_count": plan.summary.skip_count + plan.summary.unchanged_count,
            "conflict_count": plan.summary.conflict_count,
            "warning_count": sum(issue.severity == "warning" for item in plan.items for issue in item.issues),
            "backup_reference": backup_path.resolve().relative_to(root).as_posix(),
            "database_hash_before": database_hash_before,
            "database_hash_after": "",
            "warnings": ["NEEDS_CONFIRMATION"] if plan.summary.needs_confirmation_count else [],
            "error_code": "",
            "error_summary": "",
            "owner": self._safe_owner(owner),
            "changes": [],
            "import_changes": [],
            "decisions": [decision.model_dump(mode="json") for decision in decisions],
        }

    def _audit_path(self, site_id: str, operation_id: str) -> Path:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        return self.paths.rail_transit_base_data_import_operations_dir(site_id) / f"{operation_id}.json"

    def _backup_path(self, site_id: str, operation_id: str) -> Path:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        return self.paths.rail_transit_base_data_import_backups_dir(site_id) / f"{operation_id}.sqlite"

    @staticmethod
    def _flatten_changes(
        plan: MergePlanDTO,
        changes: list[dict[str, Any]],
        decisions: list[MergeFieldDecisionDTO],
    ) -> list[dict[str, Any]]:
        actionable = [item for item in plan.items if item.result in {"CREATE", "UPDATE"}]
        explicit = {(item.row_number, item.field_name) for item in decisions if item.action != "skip_entity"}
        allowed = [
            field
            for field in AP_MERGE_FIELDS
            if field not in {"source_file", "source_sheet", "source_row"}
        ]
        output = []
        for item, change in zip(actionable, changes, strict=True):
            old_values = change.get("old_values") or {}
            new_values = change.get("new_values") or {}
            for field in allowed:
                old_value = old_values.get(field)
                new_value = new_values.get(field)
                if old_value == new_value or field not in new_values:
                    continue
                diff = next((row for row in item.field_diffs if row.field_name == field), None)
                output.append(
                    ImportChangeDTO(
                        operation_id=plan.plan_id,
                        entity_id=str(change.get("entity_id") or item.matched_entity_id),
                        action=str(change.get("kind") or item.result).upper(),
                        field_name=field,
                        old_value=old_value,
                        new_value=new_value,
                        source_type=diff.source.source_type if diff else plan.source_type,
                        source_reference=Path(plan.source_file_name).name,
                        confirmation_method="explicit" if (item.row_number, field) in explicit else "policy",
                    ).model_dump(mode="json")
                )
        return output

    @staticmethod
    def _operation_dto(audit: Mapping[str, Any]) -> ImportOperationDTO:
        operation_id = str(audit.get("operation_id") or "")
        return ImportOperationDTO(
            operation_id=operation_id,
            preview_id=str(audit.get("preview_id") or operation_id),
            site_id=str(audit.get("site_id") or ""),
            source_file_name=Path(str(audit.get("source_file_name") or "")).name,
            source_file_sha256=str(audit.get("source_file_sha256") or ""),
            owner=str(audit.get("owner") or ""),
            started_at=str(audit.get("started_at") or audit.get("created_at") or ""),
            ended_at=str(audit.get("ended_at") or audit.get("applied_at") or ""),
            status=str(audit.get("status") or "UNKNOWN"),
            created_count=int(audit.get("created_count") or 0),
            updated_count=int(audit.get("updated_count") or 0),
            skipped_count=int(audit.get("skipped_count") or 0),
            warning_count=int(audit.get("warning_count") or 0),
            backup_reference=str(audit.get("backup_reference") or ""),
            database_hash_before=str(audit.get("database_hash_before") or ""),
            database_hash_after=str(audit.get("database_hash_after") or ""),
            error_code=str(audit.get("error_code") or ""),
            error_summary=str(audit.get("error_summary") or ""),
            rolled_back_at=str(audit.get("rolled_back_at") or ""),
        )

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
