from __future__ import annotations

import json
import hashlib
from threading import RLock
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade.backup_lifecycle import BackupLifecycleService
from netconsole.services.database_upgrade.backup_store import (
    DatabaseBackupDeleteError,
    DatabaseBackupStore,
)
from netconsole.services.database_upgrade.coordinator import DatabaseUpgradeCoordinator
from netconsole.services.database_upgrade.history import LegacyDatabaseArchiveService
from netconsole.services.database_upgrade.journal import list_upgrade_journals
from netconsole.services.database_upgrade.models import DatabaseDescriptor, DatabaseUpgradeStrategy
from netconsole.services.database_upgrade.sqlite_consistency import sqlite_backup, validate_sqlite
from netconsole.services.job_center.job_context import BackgroundTaskCancelled


_DATABASE_BATCH_LOCK = RLock()


class DatabaseUpgradeManagementService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.backups = DatabaseBackupStore(paths)
        self.backup_lifecycle = BackupLifecycleService(paths)
        self.history = LegacyDatabaseArchiveService(paths, backup_store=self.backups)

    def batch_backup(
        self,
        site_id: str,
        profile_ids: list[str] | tuple[str, ...],
        *,
        task_id: str,
        progress: Callable[[str, int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Create checked backups serially and retain a result for every Profile."""

        selected = _unique_profile_ids(profile_ids)
        inspection = self._mesh_inspection(site_id)
        profiles = {
            str(item.get("mr_id") or ""): dict(item)
            for item in inspection.get("profiles", [])
            if isinstance(item, dict)
        }
        results: list[dict[str, Any]] = []
        cancel_check = _batch_cancel_check(should_cancel)
        with _DATABASE_BATCH_LOCK:
            for index, profile_id in enumerate(selected, start=1):
                cancel_check()
                profile = profiles.get(profile_id)
                if profile is None:
                    results.append({"profile_id": profile_id, "status": "failed", "message": "MESH Profile 不存在"})
                else:
                    safe_name = str(profile.get("safe_folder_name") or profile_id)
                    scope_id = f"{site_id}:{safe_name}"
                    try:
                        backup = self.backups.create(
                            source_path=self.paths.mesh_mr_db_path(site_id, safe_name),
                            database_kind="mesh_derived",
                            scope_type="site_profile",
                            scope_id=scope_id,
                            task_id=task_id,
                            old_version=str(profile.get("current_version") or "unknown"),
                            target_version=str(profile.get("required_version") or "unknown"),
                            strategy="BATCH_BACKUP",
                            reason="用户批量备份数据库",
                            metadata={"profile_id": profile_id, "profile_name": str(profile.get("display_name") or "")},
                        )
                        results.append({
                            "profile_id": profile_id,
                            "profile_name": str(profile.get("display_name") or ""),
                            "status": "success",
                            "backup_id": str(backup.get("backup_id") or ""),
                            "result_status": str(backup.get("result_status") or ""),
                            "message": "数据库备份完成",
                        })
                    except Exception as exc:
                        results.append({
                            "profile_id": profile_id,
                            "profile_name": str(profile.get("display_name") or ""),
                            "status": "failed",
                            "message": str(exc),
                        })
                if progress:
                    progress("database_batch_backup", index, len(selected), f"已处理 {index}/{len(selected)} 个数据库")
        summary = _batch_summary(site_id, "backup", results)
        self._audit("database_batch_backup", {"site_id": site_id, "task_id": task_id, **summary})
        return summary

    def batch_upgrade(
        self,
        site_id: str,
        profile_ids: list[str] | tuple[str, ...],
        *,
        task_id: str,
        progress: Callable[[str, int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Preflight then repair each incompatible Profile one at a time."""

        selected = _unique_profile_ids(profile_ids)
        inspection = self._mesh_inspection(site_id)
        profiles = {
            str(item.get("mr_id") or ""): dict(item)
            for item in inspection.get("profiles", [])
            if isinstance(item, dict)
        }
        results: list[dict[str, Any]] = []
        from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceService

        cancel_check = _batch_cancel_check(should_cancel)
        with _DATABASE_BATCH_LOCK:
            for index, profile_id in enumerate(selected, start=1):
                cancel_check()
                profile = profiles.get(profile_id)
                if profile is None:
                    results.append({"profile_id": profile_id, "status": "failed", "message": "MESH Profile 不存在"})
                elif str(profile.get("status") or "") != "incompatible":
                    results.append({
                        "profile_id": profile_id,
                        "profile_name": str(profile.get("display_name") or ""),
                        "status": "skipped",
                        "message": "数据库版本兼容，无需升级",
                    })
                else:
                    try:
                        result = MeshDerivedDataMaintenanceService(self.paths).repair(
                            site_id,
                            profile_ids=[profile_id],
                            progress=_batch_progress(progress, index, len(selected), profile_id),
                            should_cancel=cancel_check,
                        )
                        repaired = list(result.get("repaired_profiles") or [])
                        detail = dict(repaired[0]) if repaired else {}
                        results.append({
                            "profile_id": profile_id,
                            "profile_name": str(profile.get("display_name") or ""),
                            "status": "success",
                            "backup_id": str(detail.get("backup_id") or ""),
                            "message": "数据库升级完成",
                        })
                    except BackgroundTaskCancelled:
                        raise
                    except Exception as exc:
                        results.append({
                            "profile_id": profile_id,
                            "profile_name": str(profile.get("display_name") or ""),
                            "status": "failed",
                            "message": str(exc),
                        })
                if progress:
                    progress("database_batch_upgrade", index, len(selected), f"已处理 {index}/{len(selected)} 个数据库")
        summary = _batch_summary(site_id, "upgrade", results)
        self._audit("database_batch_upgrade", {"site_id": site_id, "task_id": task_id, **summary})
        return summary

    def list_status(self, site_id: str) -> dict[str, Any]:
        inspection = self._mesh_inspection(site_id)
        backups = [
            item
            for item in self.backups.list()
            if str(item.get("scope_id") or "") == str(site_id)
            or str(item.get("scope_id") or "").startswith(f"{site_id}:")
        ]
        databases: list[dict[str, Any]] = []
        for value in inspection.get("profiles", []):
            item = dict(value)
            scope_id = f"{site_id}:{item.get('safe_folder_name') or item.get('mr_id') or 'unknown'}"
            related = [backup for backup in backups if str(backup.get("scope_id") or "") == scope_id]
            latest = related[0] if related else {}
            status = str(item.get("status") or "unknown")
            databases.append(
                {
                    **item,
                    "database_kind": "mesh_derived",
                    "scope_type": "site_profile",
                    "scope_id": scope_id,
                    "health_status": "healthy" if status == "compatible" else "upgrade_required" if status == "incompatible" else "not_created",
                    "needs_upgrade": status == "incompatible",
                    "backup_count": len(related),
                    "latest_backup_id": str(latest.get("backup_id") or ""),
                    "last_upgrade_time": str(latest.get("created_at") or ""),
                    "last_upgrade_task": str(latest.get("task_id") or ""),
                }
            )
        return {
            "site_id": str(site_id),
            "databases": databases,
            "backups": backups,
            "backup_count": len(backups),
            "backup_size_bytes": sum(int(item.get("database_size") or 0) for item in backups),
        }

    def preview_backup_retirement(
        self,
        *,
        keep_revisions: int = 2,
        protected_backup_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Return a manifest-driven plan; production retirement is never applied here."""

        return self.backup_lifecycle.preview_retirement(
            keep_revisions=keep_revisions,
            protected_backup_ids=protected_backup_ids,
        )

    def read_backup(self, backup_id: str, *, site_id: str | None = None) -> dict[str, Any]:
        item = self.backups.read(backup_id)
        self._ensure_site_scope(item, site_id)
        return item

    def validate_backup(self, backup_id: str, *, site_id: str | None = None) -> dict[str, Any]:
        with self._backup_action_lock(backup_id):
            item = self.read_backup(backup_id, site_id=site_id)
            result = self.backups.validate(str(item["backup_id"]))
            self._audit("database_backup_validation", {
                "backup_id": backup_id,
                "result_status": result.get("result_status"),
                "validation": result.get("validation") or {},
            })
            return result

    def organize_legacy(self, site_id: str) -> dict[str, Any]:
        result = self.history.organize_mesh_archives(site_id)
        self._audit("legacy_database_archive_migration", result)
        return result

    def delete_backup(self, backup_id: str, *, confirmed: bool = False, site_id: str | None = None) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("删除数据库备份前必须明确确认")
        with self.backups.lifecycle_lock():
            _, result = self._delete_backup_item(backup_id, site_id=site_id)
        self._audit("database_backup_delete", {"backup_id": backup_id, **result})
        return result

    def delete_backups(
        self,
        backup_ids: list[str] | tuple[str, ...],
        *,
        confirmed: bool = False,
        site_id: str | None = None,
        task_id: str = "",
        progress: Callable[[str, int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        """Delete selected backups item-by-item while retaining partial results."""

        if not confirmed:
            raise ValueError("批量删除数据库备份前必须明确确认")
        selected = _unique_backup_ids(backup_ids)
        results: list[dict[str, Any]] = []
        with _DATABASE_BATCH_LOCK:
            with self.backups.lifecycle_lock():
                for index, backup_id in enumerate(selected, start=1):
                    try:
                        item, deleted = self._delete_backup_item(backup_id, site_id=site_id)
                        released_bytes = int(
                            deleted.get("released_bytes")
                            or item.get("database_size")
                            or item.get("size_bytes")
                            or 0
                        )
                        outcome = {
                            "backup_id": backup_id,
                            "status": "deleted",
                            "code": "DELETED",
                            "message": "数据库备份已删除",
                            "released_bytes": released_bytes,
                        }
                    except FileNotFoundError as exc:
                        outcome = _backup_delete_outcome(
                            backup_id,
                            status="failed",
                            code="BACKUP_NOT_FOUND",
                            message=str(exc) or "数据库备份不存在",
                        )
                    except DatabaseBackupDeleteError as exc:
                        outcome = _backup_delete_outcome(
                            backup_id,
                            status="skipped" if exc.code == "BACKUP_IN_USE" else "failed",
                            code=exc.code,
                            message=str(exc),
                        )
                    except ValueError as exc:
                        outcome = _backup_delete_outcome(
                            backup_id,
                            status="skipped",
                            code="BACKUP_IN_USE",
                            message=str(exc) or "数据库备份正在使用中",
                        )
                    except OSError as exc:
                        outcome = _backup_delete_outcome(
                            backup_id,
                            status="failed",
                            code="BACKUP_DELETE_FAILED",
                            message=str(exc) or "数据库备份目录删除失败",
                        )
                    except Exception:
                        outcome = _backup_delete_outcome(
                            backup_id,
                            status="failed",
                            code="BACKUP_DELETE_FAILED",
                            message="数据库备份删除失败",
                        )
                    results.append(outcome)
                    self._audit(
                        "database_backup_batch_delete_item",
                        {"task_id": task_id, "site_id": site_id or "", **outcome},
                    )
                    if progress:
                        progress(
                            "database_backup_batch_delete",
                            index,
                            len(selected),
                            f"已处理 {index}/{len(selected)} 个数据库备份",
                        )
        summary = _backup_delete_summary(site_id or "", results)
        self._audit(
            "database_backup_batch_delete",
            {"task_id": task_id, **summary},
        )
        return summary

    def restore_backup(
        self,
        backup_id: str,
        *,
        confirmed: bool = False,
        site_id: str | None = None,
        progress: Callable[[str, int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("恢复数据库备份前必须明确确认")
        with self._backup_action_lock(backup_id):
            item = self.read_backup(backup_id, site_id=site_id)
            item = self.backups.validate(backup_id)
            validation = dict(item.get("validation") or {})
            if not validation.get("valid"):
                raise ValueError("数据库备份完整性校验未通过，不能恢复")
            original = self._restore_target(item, site_id=site_id)
            restore_id = f"restore-{uuid4().hex}"
            source = (Path(str(item["path"])) / "database.sqlite").resolve()
            current = validate_sqlite(original)
            descriptor = DatabaseDescriptor(
                database_kind=str(item.get("database_kind") or "unknown"),
                scope_type=str(item.get("scope_type") or "unknown"),
                scope_id=str(item.get("scope_id") or "unknown"),
                database_path=original,
                current_version=str(current.get("schema_version") or "unknown"),
                target_version=str(validation.get("schema_version") or item.get("old_schema_version") or "unknown"),
                strategy=DatabaseUpgradeStrategy.SCHEMA_MIGRATION,
                adapter=_BackupRestoreAdapter(source),
                task_id=restore_id,
                maintenance_lock=f"database-upgrade:{item.get('scope_type')}:{item.get('scope_id')}",
                reason=f"用户恢复数据库备份 {backup_id}",
                metadata={"restored_from_backup_id": backup_id},
                smoke_test=validate_sqlite,
            )
            result = DatabaseUpgradeCoordinator(self.paths).upgrade(
                descriptor,
                task_id=restore_id,
                progress=progress,
                should_cancel=should_cancel,
            )
            payload = {
                "backup_id": backup_id,
                "database_path": str(original),
                "validation": result.new_validation,
                "safety_backup_id": result.backup_id,
                "safety_backup_path": result.backup_path,
                "restored": True,
            }
            self._audit("database_backup_restore", payload)
            return payload

    def open_backup_directory(self, backup_id: str, *, site_id: str | None = None) -> Path:
        self.read_backup(backup_id, site_id=site_id)
        return self.backups.open_directory(backup_id)

    def _mesh_inspection(self, site_id: str) -> dict[str, Any]:
        from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceService

        return MeshDerivedDataMaintenanceService(self.paths).inspect(site_id)

    def _active_mesh_paths(self, scope_id: str) -> tuple[Path, ...]:
        site_id = scope_id.split(":", 1)[0]
        safe_profile = scope_id.split(":", 1)[1] if ":" in scope_id else ""
        if not site_id or not safe_profile:
            return ()
        return (self.paths.mesh_mr_db_path(site_id, safe_profile),)

    def _restore_target(self, item: dict[str, Any], *, site_id: str | None) -> Path:
        scope_type = str(item.get("scope_type") or "")
        scope_id = str(item.get("scope_id") or "")
        if str(item.get("database_kind") or "") == "mesh_derived" and scope_type == "site_profile" and ":" in scope_id:
            target_site, safe_profile = scope_id.split(":", 1)
            self._ensure_site_scope(item, site_id)
            return self.paths.mesh_mr_db_path(target_site, safe_profile).resolve()
        original = Path(str(item.get("original_database_path") or "")).resolve()
        root = self.paths.data_root.resolve()
        if not str(item.get("original_database_path") or "").strip() or (original != root and not original.is_relative_to(root)):
            raise ValueError("备份原始路径不在当前数据根内")
        return original

    def _ensure_site_scope(self, item: dict[str, Any], site_id: str | None) -> None:
        if not site_id:
            return
        scope_id = str(item.get("scope_id") or "")
        site = str(site_id)
        if scope_id != site and not scope_id.startswith(f"{site}:"):
            raise FileNotFoundError("数据库备份不属于当前局点")

    @contextmanager
    def _backup_action_lock(self, backup_id: str):
        digest = hashlib.sha256(str(backup_id).encode("utf-8")).hexdigest()[:32]
        lock_path = self.paths.database_upgrade_locks_dir / f"backup-{digest}.lock"
        try:
            with interprocess_file_lock(lock_path, timeout_seconds=1):
                yield
        except TimeoutError as exc:
            raise ValueError("数据库备份正在被其他维护任务使用") from exc

    def _audit(self, action: str, value: dict[str, Any]) -> None:
        path = self.paths.logs_dir / "database_upgrade_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps({"action": action, "at": datetime.now(UTC).isoformat(), **value}, ensure_ascii=False) + "\n")

    def _ensure_not_in_use(self, backup_id: str) -> None:
        terminal_stages = {
            "completed",
            "failed_before_switch",
            "failed_rolled_back",
            "diagnostic_retention_failed",
            "recovered_no_switch",
            "recovered_rollback",
            "recovered_from_backup",
            "recovered_new_database",
            "recovered_no_existing_database",
        }
        for journal in list_upgrade_journals(self.paths):
            if str(journal.get("backup_id") or "") == str(backup_id) and str(journal.get("stage") or "") not in terminal_stages:
                raise DatabaseBackupDeleteError("BACKUP_IN_USE", "数据库备份正在用于升级或回滚，不能删除")

    def _delete_backup_item(
        self,
        backup_id: str,
        *,
        site_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._backup_action_lock(backup_id):
            item = self.read_backup(backup_id, site_id=site_id)
            result_status = str(item.get("result_status") or "").strip().upper()
            authority_status = str(item.get("authority_status") or "").strip().upper()
            if result_status in {"CREATING", "RESTORING", "RESTORE_IN_PROGRESS", "MIGRATION_IN_PROGRESS"} or (
                authority_status in {"PREPARING", "RESTORING", "IN_USE"}
                and result_status != "CREATION_FAILED"
            ):
                raise DatabaseBackupDeleteError("BACKUP_IN_USE", "数据库备份正在创建或恢复，不能删除")
            self._ensure_not_in_use(backup_id)
            active_paths = self._active_mesh_paths(str(item.get("scope_id") or ""))
            return item, self.backups.delete(backup_id, active_paths=active_paths)


class _BackupRestoreAdapter:
    def __init__(self, source: Path) -> None:
        self.source = source

    def build_shadow(self, descriptor, shadow_path, *, progress, should_cancel):
        if should_cancel and should_cancel():
            raise RuntimeError("数据库恢复任务已取消")
        sqlite_backup(self.source, shadow_path)
        return {"restored_from": str(self.source)}

    def validate(self, path: Path) -> dict[str, Any]:
        return validate_sqlite(path)

    def switch(self, descriptor, shadow_path, rollback_path) -> None:
        active = descriptor.database_path.resolve()
        if rollback_path.exists():
            raise RuntimeError(f"检测到未完成的 rollback 文件：{rollback_path.name}")
        if active.exists():
            active.replace(rollback_path)
        shadow_path.replace(active)

    def rollback(self, descriptor, rollback_path, failed_shadow_path, failure_dir) -> None:
        active = descriptor.database_path.resolve()
        failure_dir.mkdir(parents=True, exist_ok=True)
        failed = failure_dir / "failed_restored_database.sqlite"
        if active.exists():
            active.replace(failed)
        elif failed_shadow_path.exists():
            failed_shadow_path.replace(failed)
        retained_rollback = rollback_path if rollback_path.exists() else failure_dir / "rollback.sqlite"
        if retained_rollback.exists():
            retained_rollback.replace(active)

    def discard_shadow(self, shadow_path: Path, failure_dir: Path) -> None:
        if shadow_path.exists():
            failure_dir.mkdir(parents=True, exist_ok=True)
            shadow_path.replace(failure_dir / "failed_restored_database.sqlite")

    def finalize_success(self, descriptor, rollback_path, backup_dir) -> dict[str, Any]:
        if not rollback_path.exists():
            return {}
        target = backup_dir / "rollback.sqlite"
        if target.exists():
            raise RuntimeError("备份目录中的 rollback 文件已存在")
        rollback_path.replace(target)
        return {"rollback_path": str(target)}


def _unique_profile_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _unique_backup_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _backup_delete_outcome(
    backup_id: str,
    *,
    status: str,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "backup_id": backup_id,
        "status": status,
        "code": code,
        "message": message,
        "released_bytes": 0,
    }


def _backup_delete_summary(site_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    deleted = sum(item.get("status") == "deleted" for item in results)
    failed = sum(item.get("status") == "failed" for item in results)
    skipped = sum(item.get("status") == "skipped" for item in results)
    partial = bool(failed or skipped)
    business_status = "SUCCESS" if not partial else "PARTIAL_SUCCESS" if deleted else "FAILED" if failed else "SKIPPED"
    return {
        "site_id": str(site_id),
        "action": "batch_delete",
        "requested": len(results),
        "deleted": deleted,
        "failed": failed,
        "skipped": skipped,
        "released_bytes": sum(int(item.get("released_bytes") or 0) for item in results if item.get("status") == "deleted"),
        "success_count": deleted,
        "failed_count": failed,
        "skipped_count": skipped,
        "partial_success": partial,
        "business_status": business_status,
        "business_outcome": f"批量删除完成：成功 {deleted} 个，失败 {failed} 个，跳过 {skipped} 个",
        "items": results,
    }


def _batch_cancel_check(
    should_cancel: Callable[[], bool] | None,
) -> Callable[[], bool]:
    def check() -> bool:
        if should_cancel and should_cancel():
            raise BackgroundTaskCancelled("批量数据库维护任务已取消")
        return False

    return check


def _batch_progress(
    progress: Callable[[str, int, int, str], None] | None,
    index: int,
    total: int,
    profile_id: str,
) -> Callable[[str, int, int, str], None] | None:
    if progress is None:
        return None

    def emit(stage: str, current: int, stage_total: int, message: str) -> None:
        progress(stage, index - 1, total, f"{profile_id}：{message}")

    return emit


def _batch_summary(site_id: str, action: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "site_id": str(site_id),
        "action": action,
        "total": len(results),
        "success": sum(item.get("status") == "success" for item in results),
        "skipped": sum(item.get("status") == "skipped" for item in results),
        "failed": sum(item.get("status") == "failed" for item in results),
        "partial": any(item.get("status") == "failed" for item in results)
        and any(item.get("status") == "success" for item in results),
        "results": results,
    }


__all__ = ["DatabaseUpgradeManagementService"]
