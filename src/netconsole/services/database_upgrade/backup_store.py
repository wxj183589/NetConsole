from __future__ import annotations

import json
import shutil
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.version import APP_VERSION
from netconsole.core.atomic_file import atomic_write_bytes
from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.services.database_upgrade.sqlite_consistency import (
    sqlite_backup,
    validate_sqlite,
)


def _safe_component(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in text)
    return safe.strip(".") or "unknown"


_BACKUP_LIFECYCLE_LOCK = threading.RLock()


class DatabaseBackupStore:
    """统一数据库升级备份中心；只在明确的用户动作中删除。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.root = paths.database_upgrade_backups_dir.resolve()

    def create(
        self,
        *,
        source_path: Path,
        database_kind: str,
        scope_type: str,
        scope_id: str,
        task_id: str,
        old_version: str,
        target_version: str,
        strategy: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.lifecycle_lock():
            return self._create_locked(
                source_path=source_path,
                database_kind=database_kind,
                scope_type=scope_type,
                scope_id=scope_id,
                task_id=task_id,
                old_version=old_version,
                target_version=target_version,
                strategy=strategy,
                reason=reason,
                metadata=metadata,
                checkpoint=checkpoint,
            )

    def _create_locked(
        self,
        *,
        source_path: Path,
        database_kind: str,
        scope_type: str,
        scope_id: str,
        task_id: str,
        old_version: str,
        target_version: str,
        strategy: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        backup_id = f"dbu_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"
        destination = self.directory_path(scope_type, scope_id, database_kind, backup_id)
        destination.mkdir(parents=True, exist_ok=False)
        database_path = destination / "database.sqlite"
        validation_path = destination / "validation.json"
        manifest_path = destination / "manifest.json"
        migration_log = destination / "migration.log"
        created_at = datetime.now(UTC).isoformat()
        prepared = {
            "backup_id": backup_id,
            "task_id": task_id,
            "database_kind": database_kind,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "original_database_path": str(source_path),
            "backup_database_path": str(database_path),
            "created_at": created_at,
            "application_version": APP_VERSION,
            "old_schema_version": old_version,
            "target_schema_version": target_version,
            "migration_strategy": strategy,
            "upgrade_reason": reason,
            "checkpoint_result": checkpoint or {},
            "result_status": "CREATING",
            "authority_status": "PREPARING",
            "reuse_count": 0,
            **(metadata or {}),
        }
        _write_json(manifest_path, prepared)
        migration_log.write_text("数据库升级备份正在创建\n", encoding="utf-8")
        validation: dict[str, Any]
        try:
            if source_path.is_file() and source_path.stat().st_size > 0:
                sqlite_backup(source_path, database_path)
                validation = validate_sqlite(database_path)
                validation["restorable"] = bool(validation.get("valid"))
            elif source_path.is_file():
                validation = validate_sqlite(source_path)
                validation.update(
                    path=str(database_path),
                    status="ZERO_BYTE_ARCHIVE",
                    restorable=False,
                )
            else:
                validation = {
                    "path": str(database_path),
                    "exists": False,
                    "size_bytes": 0,
                    "sha256": "",
                    "quick_check": "not_present",
                    "integrity_check": "not_present",
                    "schema_version": old_version,
                    "valid": True,
                    "restorable": False,
                    "status": "NOT_PRESENT",
                }
        except Exception as exc:
            failed = {
                **prepared,
                "result_status": "CREATION_FAILED",
                "authority_status": "PREPARING",
                "error_message": f"{type(exc).__name__}: {exc}",
                "failed_at": datetime.now(UTC).isoformat(),
            }
            _write_json(manifest_path, failed)
            migration_log.write_text("数据库升级备份创建失败\n", encoding="utf-8")
            raise
        _write_json(validation_path, validation)
        result_status = (
            "NO_EXISTING_DATABASE"
            if not validation.get("exists")
            else "ZERO_BYTE_ARCHIVE"
            if int(validation.get("size_bytes") or 0) == 0
            else "VALID_BACKUP"
            if validation.get("valid")
            else "INVALID_DATABASE"
        )
        source_revision = str(validation.get("sha256") or "")
        if result_status == "VALID_BACKUP" and source_revision:
            reusable = self._find_reusable(
                scope_type=scope_type,
                scope_id=scope_id,
                database_kind=database_kind,
                source_revision=source_revision,
                database_size=int(validation.get("size_bytes") or 0),
                exclude_backup_id=backup_id,
            )
            if reusable is not None:
                reused = self._record_reuse(
                    reusable,
                    task_id=task_id,
                    target_version=target_version,
                    strategy=strategy,
                    reason=reason,
                )
                shutil.rmtree(destination)
                return {
                    **reused,
                    "reused": True,
                    "requested_backup_id": backup_id,
                    "source_revision": source_revision,
                }
        manifest = {
            **prepared,
            "database_size": validation.get("size_bytes", 0),
            "database_sha256": validation.get("sha256", ""),
            "source_revision": source_revision,
            "old_parser_version": validation.get("parser_version", "unknown"),
            "sqlite_page_count": validation.get("page_count", 0),
            "sqlite_page_size": validation.get("page_size", 0),
            "sqlite_freelist_count": validation.get("freelist_count", 0),
            "source_file_count": validation.get("source_file_count", 0),
            "session_count": validation.get("session_count", 0),
            "link_record_count": validation.get("link_record_count", 0),
            "switch_event_count": validation.get("switch_event_count", 0),
            "rssi_record_count": validation.get("rssi_record_count", 0),
            "integrity_check_result": validation,
            "result_status": result_status,
            "authority_status": (
                "VERIFIED" if result_status == "VALID_BACKUP" else "PROTECTED"
            ),
            "verified_at": (
                datetime.now(UTC).isoformat() if result_status == "VALID_BACKUP" else ""
            ),
        }
        _write_json(manifest_path, manifest)
        migration_log.write_text("数据库升级备份已创建\n", encoding="utf-8")
        return {
            **manifest,
            "path": str(destination),
            "validation": validation,
            "reused": False,
        }

    def list(self, *, scope_type: str | None = None, scope_id: str | None = None, database_kind: str | None = None) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        result: list[dict[str, Any]] = []
        for manifest_path in self.root.rglob("manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            if scope_type and str(manifest.get("scope_type")) != str(scope_type):
                continue
            if scope_id and str(manifest.get("scope_id")) != str(scope_id):
                continue
            if database_kind and str(manifest.get("database_kind")) != str(database_kind):
                continue
            result.append({**manifest, "path": str(manifest_path.parent)})
        return sorted(result, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def read(self, backup_id: str) -> dict[str, Any]:
        for item in self.list():
            if str(item.get("backup_id")) == str(backup_id):
                return item
        raise FileNotFoundError("数据库备份不存在")

    def validate(self, backup_id: str) -> dict[str, Any]:
        item = self.read(backup_id)
        database_path = self._database_path(item)
        result = validate_sqlite(database_path)
        expected_size = int(item.get("database_size") or 0)
        expected_sha256 = str(item.get("database_sha256") or "")
        result["expected_size_bytes"] = expected_size
        result["expected_sha256"] = expected_sha256
        result["size_matches"] = bool(expected_size > 0 and int(result.get("size_bytes") or 0) == expected_size)
        result["sha256_matches"] = bool(expected_sha256 and str(result.get("sha256") or "") == expected_sha256)
        result["restorable"] = bool(
            result.get("valid")
            and result["size_matches"]
            and result["sha256_matches"]
        )
        result["valid"] = result["restorable"]
        validation_path = Path(item["path"]) / "validation.json"
        _write_json(validation_path, result)
        manifest_path = Path(item["path"]) / "manifest.json"
        previous_status = str(item.get("result_status") or "")
        result_status = (
            "ZERO_BYTE_ARCHIVE"
            if int(result.get("size_bytes") or 0) == 0
            else "DUPLICATE_BACKUP"
            if previous_status == "DUPLICATE_BACKUP" and result["valid"]
            else "VALID_BACKUP"
            if result["valid"]
            else "INVALID_DATABASE"
        )
        updated = {
            **item,
            "integrity_check_result": result,
            "result_status": result_status,
            "validated_at": datetime.now(UTC).isoformat(),
        }
        updated.pop("path", None)
        _write_json(manifest_path, updated)
        return {**updated, "path": str(manifest_path.parent), "validation": result}

    def delete(self, backup_id: str, *, active_paths: Iterable[Path] = ()) -> dict[str, Any]:
        item = self.read(backup_id)
        path = Path(str(item["path"])).resolve()
        database_path = self._database_path(item)
        if any(database_path == active.resolve() for active in active_paths):
            raise ValueError("当前活动数据库或其备份不能删除")
        if self.root not in path.parents:
            raise ValueError("数据库备份路径越界")
        shutil.rmtree(path)
        return {"backup_id": backup_id, "deleted": True}

    def open_directory(self, backup_id: str) -> Path:
        path = Path(str(self.read(backup_id)["path"])).resolve()
        if self.root not in path.parents:
            raise ValueError("数据库备份路径越界")
        return path

    def directory_path(self, scope_type: str, scope_id: str, database_kind: str, backup_id: str) -> Path:
        return (
            self.root
            / _safe_component(scope_type)
            / _safe_component(scope_id)
            / _safe_component(database_kind)
            / _safe_component(backup_id)
        )

    def _database_path(self, item: dict[str, Any]) -> Path:
        directory = Path(str(item["path"])).resolve()
        if self.root not in directory.parents:
            raise ValueError("数据库备份路径越界")
        database_path = (directory / "database.sqlite").resolve()
        if database_path.parent != directory:
            raise ValueError("数据库备份文件路径越界")
        declared = str(item.get("backup_database_path") or "").strip()
        if declared and Path(declared).resolve() != database_path:
            raise ValueError("数据库备份 manifest 路径与受控目录不一致")
        return database_path

    def _find_reusable(
        self,
        *,
        scope_type: str,
        scope_id: str,
        database_kind: str,
        source_revision: str,
        database_size: int,
        exclude_backup_id: str,
    ) -> dict[str, Any] | None:
        for item in self.list(
            scope_type=scope_type,
            scope_id=scope_id,
            database_kind=database_kind,
        ):
            if str(item.get("backup_id") or "") == exclude_backup_id:
                continue
            if str(item.get("result_status") or "") != "VALID_BACKUP":
                continue
            if str(item.get("authority_status") or "VERIFIED") != "VERIFIED":
                continue
            if str(item.get("source_revision") or item.get("database_sha256") or "") != source_revision:
                continue
            if int(item.get("database_size") or 0) != database_size:
                continue
            database = self._database_path(item)
            validation = validate_sqlite(database)
            if (
                validation.get("valid")
                and int(validation.get("size_bytes") or 0) == database_size
                and str(validation.get("sha256") or "") == source_revision
            ):
                return {**item, "validation": validation}
        return None

    def _record_reuse(
        self,
        item: dict[str, Any],
        *,
        task_id: str,
        target_version: str,
        strategy: str,
        reason: str,
    ) -> dict[str, Any]:
        manifest_path = Path(str(item["path"])) / "manifest.json"
        updated = {
            **item,
            "reuse_count": int(item.get("reuse_count") or 0) + 1,
            "last_reused_at": datetime.now(UTC).isoformat(),
            "last_reuse_task_id": task_id,
            "last_requested_target_schema_version": target_version,
            "last_requested_strategy": strategy,
            "last_requested_reason": reason,
        }
        updated.pop("path", None)
        updated.pop("validation", None)
        _write_json(manifest_path, updated)
        return {
            **updated,
            "path": str(manifest_path.parent),
            "validation": dict(item["validation"]),
        }

    @contextmanager
    def lifecycle_lock(self):
        self.paths.database_upgrade_locks_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.paths.database_upgrade_locks_dir / "backup-lifecycle.lock"
        with _BACKUP_LIFECYCLE_LOCK:
            with interprocess_file_lock(lock_path, timeout_seconds=60):
                yield


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


__all__ = ["DatabaseBackupStore"]
