from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.journal import DatabaseUpgradeJournal
from netconsole.services.database_upgrade.models import (
    CancelCallback,
    DatabaseDescriptor,
    DatabaseUpgradeResult,
    ProgressCallback,
)
from netconsole.services.database_upgrade.registry import DatabaseUpgradeRegistry, database_upgrade_registry_for
from netconsole.services.database_upgrade.sqlite_consistency import (
    checkpoint_wal,
    sqlite_backup,
    validate_sqlite,
)


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def database_maintenance_lock(paths: PathResolver, key: str) -> Iterator[None]:
    normalized = str(key or "database-upgrade:global")
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(normalized, threading.RLock())
    with lock:
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
        lock_path = paths.database_upgrade_locks_dir / f"{digest}.lock"
        with interprocess_file_lock(lock_path, timeout_seconds=60):
            yield


class DatabaseUpgradeCoordinator:
    """共用数据库升级生命周期；具体表结构由 adapter 实现。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        backup_store: DatabaseBackupStore | None = None,
        registry: DatabaseUpgradeRegistry | None = None,
    ) -> None:
        self.paths = paths
        self.backups = backup_store or DatabaseBackupStore(paths)
        self.registry = registry or database_upgrade_registry_for(paths.data_root)

    def upgrade(
        self,
        descriptor: DatabaseDescriptor,
        *,
        task_id: str | None = None,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> DatabaseUpgradeResult:
        operation_id = str(task_id or descriptor.task_id or f"dbu-op-{uuid4().hex}")
        self.registry.register(descriptor)
        active_path = descriptor.database_path.resolve()
        active_path.parent.mkdir(parents=True, exist_ok=True)
        journal = DatabaseUpgradeJournal(self.paths, operation_id)
        lock_key = descriptor.maintenance_lock or f"database-upgrade:{descriptor.scope_type}:{descriptor.scope_id}"
        self._progress(progress, "database_upgrade_lock", 5, "正在获取数据库维护锁")
        with database_maintenance_lock(self.paths, lock_key):
            return self._upgrade_locked(
                descriptor,
                operation_id=operation_id,
                active_path=active_path,
                journal=journal,
                progress=progress,
                should_cancel=should_cancel,
            )

    def _upgrade_locked(
        self,
        descriptor: DatabaseDescriptor,
        *,
        operation_id: str,
        active_path: Path,
        journal: DatabaseUpgradeJournal,
        progress: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> DatabaseUpgradeResult:
        checkpoint: dict[str, Any] = {}
        backup: dict[str, Any] | None = None
        backup_validation: dict[str, Any] = {}
        shadow_path = active_path.with_name(f"{active_path.name}.new.{operation_id}")
        rollback_path = active_path.with_name(f"{active_path.name}.rollback.{operation_id}")
        switched = False
        switch_started = False
        reopened = False
        closed = False
        close_hook = descriptor.close_hook
        reopen_hook = descriptor.reopen_hook
        journal.update(
            "created",
            active_path=str(active_path),
            shadow_path=str(shadow_path),
            rollback_path=str(rollback_path),
            database_kind=descriptor.database_kind,
            scope_type=descriptor.scope_type,
            scope_id=descriptor.scope_id,
            maintenance_lock=descriptor.maintenance_lock,
        )
        try:
            self._check_cancel(should_cancel)
            if descriptor.strategy.value == "MANUAL_INTERVENTION_REQUIRED":
                raise RuntimeError("数据库升级需要人工介入，自动升级已停止")
            if close_hook:
                closed = True
                close_hook()
            self._progress(progress, "database_upgrade_pause_writes", 10, "正在暂停数据库写入")
            journal.update("pause_writes")
            checkpoint = checkpoint_wal(active_path)
            self._progress(progress, "database_upgrade_checkpoint", 15, "WAL checkpoint 已完成")
            journal.update("checkpoint", checkpoint_result=checkpoint)
            backup = self.backups.create(
                source_path=active_path,
                database_kind=descriptor.database_kind,
                scope_type=descriptor.scope_type,
                scope_id=descriptor.scope_id,
                task_id=operation_id,
                old_version=descriptor.current_version,
                target_version=descriptor.target_version,
                strategy=descriptor.strategy.value,
                reason=descriptor.reason,
                metadata={
                    "profile_id": descriptor.profile_id,
                    "profile_name": descriptor.profile_name,
                    "source_count": descriptor.source_count,
                    **descriptor.metadata,
                },
                checkpoint=checkpoint,
            )
            backup_validation = dict(backup.get("validation") or {})
            if active_path.is_file() and not bool(backup_validation.get("valid")):
                journal.update("backup_failed", backup_id=backup["backup_id"], backup_path=backup["path"], error=backup_validation)
                raise RuntimeError("旧数据库备份完整性校验失败，升级已停止")
            self._progress(progress, "database_upgrade_backup", 25, "旧数据库备份已创建并通过校验")
            journal.update("backup_validated", backup_id=backup["backup_id"], backup_path=backup["path"], backup_sha256=backup.get("database_sha256", ""), backup_validation=backup_validation)
            self._safe_prepare_shadow(shadow_path)
            if rollback_path.exists():
                raise RuntimeError(f"检测到未完成的 rollback 文件：{rollback_path.name}")
            self._check_cancel(should_cancel)
            self._progress(progress, "database_upgrade_shadow", 35, "正在创建影子数据库")
            journal.update("shadow_building")
            build_result = descriptor.adapter.build_shadow(
                descriptor,
                shadow_path,
                progress=progress,
                should_cancel=should_cancel,
            )
            self._check_cancel(should_cancel)
            new_validation = descriptor.adapter.validate(shadow_path)
            if not bool(new_validation.get("valid")):
                raise RuntimeError("新数据库完整性校验失败")
            if descriptor.version_reader and descriptor.version_reader(shadow_path) != descriptor.target_version:
                raise RuntimeError("新数据库 schema_version 校验失败")
            self._progress(progress, "database_upgrade_validate_shadow", 85, "影子数据库校验通过")
            adapter_state = {}
            journal_state = getattr(descriptor.adapter, "journal_state", None)
            if callable(journal_state):
                adapter_state = dict(journal_state(rollback_path) or {})
            journal.update(
                "shadow_validated",
                new_validation=new_validation,
                build_result=build_result or {},
                adapter_state=adapter_state,
            )
            self._check_cancel(should_cancel)
            self._progress(progress, "database_upgrade_switch", 90, "正在原子切换数据库")
            switch_started = True
            descriptor.adapter.switch(descriptor, shadow_path, rollback_path)
            switched = True
            journal.update("switched", active_path=str(active_path), rollback_path=str(rollback_path), switched=True)
            if reopen_hook:
                reopen_hook()
            reopened = True
            smoke = descriptor.smoke_test(active_path) if descriptor.smoke_test else {"valid": True}
            if smoke is not None and smoke.get("valid") is False:
                journal.update("smoke_failed", smoke_test=smoke)
                raise RuntimeError("新数据库业务 smoke test 失败")
            journal.update("smoke_validated", smoke_test=smoke or {})
            finalized = descriptor.adapter.finalize_success(descriptor, rollback_path, Path(str(backup["path"])))
            retained_backup_count = len(
                self.backups.list(
                    scope_type=descriptor.scope_type,
                    scope_id=descriptor.scope_id,
                    database_kind=descriptor.database_kind,
                )
            )
            rollback_available = bool(backup_validation.get("exists") and backup_validation.get("valid"))
            journal.update("completed", smoke_test=smoke or {}, finalized=finalized or {}, rollback_available=rollback_available)
            self._progress(progress, "database_upgrade_complete", 100, "数据库升级完成，旧数据库已保留")
            return DatabaseUpgradeResult(
                operation_id=operation_id,
                backup_id=str(backup["backup_id"]),
                backup_path=str(backup["path"]),
                database_path=str(active_path),
                strategy=descriptor.strategy.value,
                old_version=descriptor.current_version,
                target_version=descriptor.target_version,
                checkpoint_status=str(checkpoint.get("status") or ""),
                backup_validation=backup_validation,
                new_validation=new_validation,
                rollback_available=rollback_available,
                rollback_performed=False,
                retained_backup_count=retained_backup_count,
                diagnostics={"build": build_result or {}, "smoke": smoke or {}, "finalized": finalized or {}},
            )
        except Exception as exc:
            failure_dir = Path(str(backup["path"])) if backup else self.paths.database_upgrade_backups_dir / "_failed" / operation_id
            journal.update("failed", error=str(exc), failure_dir=str(failure_dir))
            try:
                # A switch is not necessarily complete when adapter.switch raises:
                # the active file may already have been moved to rollback. Treat
                # any retained rollback artifact as a switched state so the old
                # database is restored instead of merely discarding the shadow.
                switch_artifact_exists = rollback_path.exists() or self._adapter_rollback_artifact_exists(descriptor.adapter)
                if switch_started or switched or switch_artifact_exists:
                    if close_hook:
                        close_hook()
                    rollback_error: Exception | None = None
                    try:
                        descriptor.adapter.rollback(descriptor, rollback_path, shadow_path, failure_dir)
                    except Exception as rollback_exc:
                        rollback_error = rollback_exc
                    if not self._restore_active_from_backup_if_needed(
                        active_path,
                        failure_dir,
                        old_database_existed=bool(backup_validation.get("exists")),
                    ):
                        if rollback_error is not None:
                            raise rollback_error
                        raise RuntimeError("数据库升级回滚后正式数据库不可用，安全备份也无法恢复")
                    journal.update(
                        "failed_rolled_back",
                        error=str(exc),
                        adapter_rollback_error=str(rollback_error or ""),
                        rollback_performed=True,
                    )
                elif hasattr(descriptor.adapter, "discard_shadow") and (shadow_path.exists() or getattr(descriptor.adapter, "shadow_parsed", None)):
                    try:
                        descriptor.adapter.discard_shadow(shadow_path, failure_dir)  # type: ignore[attr-defined]
                        journal.update("failed_before_switch", error=str(exc), rollback_performed=False)
                    except Exception as discard_exc:
                        # The original parser/validation error is the useful
                        # business failure. Keep an audit trail for a locked
                        # diagnostic artifact without masking that error.
                        journal.update(
                            "diagnostic_retention_failed",
                            error=str(exc),
                            diagnostic_error=str(discard_exc),
                            rollback_performed=False,
                        )
                else:
                    journal.update("failed_before_switch", error=str(exc), rollback_performed=False)
            except Exception as rollback_exc:
                journal.update("rollback_failed", error=str(exc), rollback_error=str(rollback_exc))
                raise RuntimeError(f"数据库升级失败且回滚失败：{rollback_exc}") from exc
            finally:
                if reopen_hook and closed and (not reopened or switched):
                    reopen_hook()
            raise

    @staticmethod
    def _adapter_rollback_artifact_exists(adapter: object) -> bool:
        rollback_parsed = getattr(adapter, "rollback_parsed", None)
        return isinstance(rollback_parsed, Path) and rollback_parsed.exists()

    @staticmethod
    def _restore_active_from_backup_if_needed(
        active_path: Path,
        failure_dir: Path,
        *,
        old_database_existed: bool,
    ) -> bool:
        """Keep the active SQLite usable even if adapter rollback partially failed."""

        if not old_database_existed:
            return not active_path.exists()
        if active_path.is_file():
            validation = validate_sqlite(active_path)
            if validation.get("valid"):
                return True
        backup_database = failure_dir / "database.sqlite"
        if not backup_database.is_file():
            return False
        try:
            sqlite_backup(backup_database, active_path)
        except Exception:
            return False
        return bool(validate_sqlite(active_path).get("valid"))

    @staticmethod
    def _safe_prepare_shadow(path: Path) -> None:
        if path.is_symlink():
            raise ValueError("影子数据库不能是符号链接")
        if path.exists() or any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm")):
            raise RuntimeError(f"影子数据库路径已被占用：{path}")

    @staticmethod
    def _check_cancel(should_cancel: CancelCallback | None) -> None:
        if should_cancel and should_cancel():
            raise RuntimeError("数据库升级任务已取消")

    @staticmethod
    def _progress(progress: ProgressCallback | None, stage: str, current: int, message: str) -> None:
        if progress:
            progress(stage, current, 100, message)


__all__ = ["DatabaseUpgradeCoordinator", "database_maintenance_lock"]
