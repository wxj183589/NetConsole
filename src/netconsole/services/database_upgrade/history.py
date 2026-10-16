from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from netconsole.core.atomic_file import atomic_write_bytes
from netconsole.core.paths import PathResolver
from netconsole.core.version import APP_VERSION
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.coordinator import database_maintenance_lock
from netconsole.services.database_upgrade.sqlite_consistency import sha256_file, validate_sqlite


_LEGACY_ARCHIVE_PATTERNS = (
    "mesh.sqlite.legacy_*",
    "mesh.sqlite.schema_archive_*",
    "mesh.sqlite.rollback_*",
)


def legacy_archive_candidates(paths: PathResolver, site_id: str) -> list[Path]:
    root = paths.site_mesh_root(site_id).resolve()
    if not root.is_dir() or root.is_symlink():
        return []
    candidates: list[Path] = []
    seen: set[str] = set()
    for pattern in _LEGACY_ARCHIVE_PATTERNS:
        for source in root.rglob(pattern):
            if not source.is_file() or source.is_symlink():
                continue
            key = str(source.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(source)
    return sorted(candidates, key=lambda item: str(item).casefold())


def legacy_archive_binding(
    paths: PathResolver,
    site_id: str,
    source: Path,
    *,
    include_content_identity: bool = True,
) -> dict[str, Any]:
    root = paths.site_mesh_root(site_id).resolve()
    if source.is_symlink() or not source.is_file():
        raise FileNotFoundError(str(source))
    resolved = source.resolve()
    relative_path = resolved.relative_to(root).as_posix()
    stat = resolved.stat()
    size_bytes = stat.st_size
    return {
        "source_relative_path": relative_path,
        "profile_name": resolved.parent.name,
        "size_bytes": size_bytes,
        "modified_ns": int(stat.st_mtime_ns),
        "sha256": sha256_file(resolved) if include_content_identity and size_bytes else "",
    }


def legacy_archive_bindings(
    paths: PathResolver,
    site_id: str,
    *,
    include_content_identity: bool = True,
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for source in legacy_archive_candidates(paths, site_id):
        try:
            bindings.append(
                legacy_archive_binding(
                    paths,
                    site_id,
                    source,
                    include_content_identity=include_content_identity,
                )
            )
        except (FileNotFoundError, OSError, ValueError):
            continue
    return bindings


class LegacyDatabaseArchiveService:
    """一次性整理历史 MESH 归档；有效和无效文件都保留，不自动删除。"""

    _PATTERNS = _LEGACY_ARCHIVE_PATTERNS

    def __init__(self, paths: PathResolver, *, backup_store: DatabaseBackupStore | None = None) -> None:
        self.paths = paths
        self.backups = backup_store or DatabaseBackupStore(paths)

    def organize_mesh_archives(
        self,
        site_id: str,
        *,
        profile_id: str = "",
        authorized_archives: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        root = self.paths.site_mesh_root(site_id).resolve()
        if not root.is_dir() or root.is_symlink():
            return {"site_id": str(site_id), "found_count": 0, "moved_count": 0, "invalid_count": 0, "items": []}
        recovered_count = self._recover_in_progress(site_id)
        authorized_by_path = (
            {
                str(item.get("source_relative_path") or ""): dict(item)
                for item in authorized_archives
                if isinstance(item, Mapping) and str(item.get("source_relative_path") or "")
            }
            if authorized_archives is not None
            else None
        )
        candidates = legacy_archive_candidates(self.paths, site_id)
        items: list[dict[str, Any]] = []
        existing_by_digest = {
            str(item.get("database_sha256") or ""): str(item.get("backup_id") or "")
            for item in self.backups.list(database_kind="mesh_derived")
            if str(item.get("database_sha256") or "")
            and str(item.get("result_status") or "") in {"VALID_BACKUP", "DUPLICATE_BACKUP"}
        }
        for source in candidates:
            profile_scope = str(profile_id or source.parent.name or "unknown")
            scope_id = f"{site_id}:{profile_scope}"
            lock_key = f"database-upgrade:site_profile:{scope_id}"
            with database_maintenance_lock(self.paths, lock_key):
                if not source.is_file() or source.is_symlink():
                    continue
                if authorized_by_path is not None:
                    relative_path = source.resolve().relative_to(root).as_posix()
                    expected = authorized_by_path.get(relative_path)
                    if expected is None:
                        items.append(
                            {
                                "original_database_path": str(source),
                                "source_relative_path": relative_path,
                                "result_status": "UNAUTHORIZED_ARCHIVE",
                                "error_message": "该历史归档未包含在提交时的 authority 快照中",
                                "moved": False,
                            }
                        )
                        continue
                    try:
                        actual = legacy_archive_binding(self.paths, site_id, source)
                    except (FileNotFoundError, OSError, ValueError):
                        continue
                    if actual != expected:
                        items.append(
                            {
                                "original_database_path": str(source),
                                **actual,
                                "result_status": "LEGACY_ARCHIVE_STALE",
                                "error_message": "历史归档在 authority 快照后发生变化",
                                "moved": False,
                            }
                        )
                        continue
                item = self._organize_one(
                    source,
                    scope_id=scope_id,
                    profile_id=str(profile_id or ""),
                    profile_name=profile_scope,
                    existing_by_digest=existing_by_digest,
                )
                items.append(item)
                if item["result_status"] in {"VALID_BACKUP", "DUPLICATE_BACKUP"}:
                    digest = str(item.get("database_sha256") or "")
                    if digest:
                        existing_by_digest.setdefault(digest, str(item["backup_id"]))
        return {
            "site_id": str(site_id),
            "found_count": len(candidates),
            "moved_count": sum(bool(item.get("moved")) for item in items),
            "valid_count": sum(item["result_status"] == "VALID_BACKUP" for item in items),
            "duplicate_count": sum(item["result_status"] == "DUPLICATE_BACKUP" for item in items),
            "invalid_count": sum(
                item["result_status"] not in {"VALID_BACKUP", "DUPLICATE_BACKUP"}
                for item in items
            ),
            "recovered_count": recovered_count,
            "items": items,
        }

    def _recover_in_progress(self, site_id: str) -> int:
        recovered = 0
        for manifest_path in self.paths.database_upgrade_backups_dir.rglob("manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(manifest, dict):
                continue
            if str(manifest.get("task_id") or "") != "legacy_database_archive_migration":
                continue
            if not str(manifest.get("scope_id") or "").startswith(f"{site_id}:"):
                continue
            if str(manifest.get("migration_state") or "") != "PREPARED":
                continue
            target_dir = manifest_path.parent.resolve()
            database_path = target_dir / "database.sqlite"
            if database_path.is_file():
                validation = validate_sqlite(database_path)
                expected_size = int(manifest.get("database_size") or 0)
                expected_sha256 = str(manifest.get("database_sha256") or "")
                validation["size_matches"] = int(validation.get("size_bytes") or 0) == expected_size
                validation["sha256_matches"] = str(validation.get("sha256") or "") == expected_sha256
                validation["restorable"] = bool(
                    validation.get("valid")
                    and validation["size_matches"]
                    and validation["sha256_matches"]
                )
                status = (
                    "ZERO_BYTE_ARCHIVE"
                    if int(validation.get("size_bytes") or 0) == 0
                    else "VALID_BACKUP"
                    if validation["restorable"]
                    else "INVALID_DATABASE"
                )
                manifest.update(
                    integrity_check_result=validation,
                    result_status=status,
                    migration_state="COMPLETED",
                    completed_at=datetime.now(UTC).isoformat(),
                )
                _write_json(target_dir / "validation.json", validation)
                _write_json(manifest_path, manifest)
                (target_dir / "migration.log").write_text(f"历史归档整理恢复：{status}\n", encoding="utf-8")
                recovered += 1
                continue
            manifest.update(
                result_status="UNREADABLE_DATABASE",
                migration_state="ABANDONED",
                error_message="整理任务中断，备份文件尚未生成；原始文件保留并等待重新整理",
                completed_at=datetime.now(UTC).isoformat(),
            )
            _write_json(manifest_path, manifest)
            (target_dir / "migration.log").write_text("历史归档整理中断，原始文件仍保留\n", encoding="utf-8")
            recovered += 1
        return recovered

    def _organize_one(
        self,
        source: Path,
        *,
        scope_id: str,
        profile_id: str,
        profile_name: str,
        existing_by_digest: dict[str, str],
    ) -> dict[str, Any]:
        size = source.stat().st_size
        digest = sha256_file(source) if size else ""
        validation = validate_sqlite(source)
        valid = bool(validation.get("valid")) and size > 0
        duplicate_of = existing_by_digest.get(digest, "") if valid else ""
        status = (
            "ZERO_BYTE_ARCHIVE"
            if size == 0
            else "DUPLICATE_BACKUP"
            if duplicate_of
            else "VALID_BACKUP"
            if valid
            else "INVALID_DATABASE"
        )
        archive_id = f"legacy_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:10]}"
        target_dir = (
            self.paths.database_upgrade_backups_dir / "_invalid" / archive_id
            if not valid
            else self.backups.directory_path("site_profile", scope_id, "mesh_derived", archive_id)
        )
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / "database.sqlite"
        created_at = datetime.now(UTC).isoformat()
        manifest = {
            "backup_id": archive_id,
            "task_id": "legacy_database_archive_migration",
            "database_kind": "mesh_derived",
            "scope_type": "site_profile",
            "scope_id": scope_id,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "original_database_path": str(source),
            "backup_database_path": str(target),
            "created_at": created_at,
            "application_version": APP_VERSION,
            "database_size": size,
            "database_sha256": digest,
            "old_schema_version": validation.get("schema_version", "unknown"),
            "target_schema_version": "unknown",
            "migration_strategy": "LEGACY_ARCHIVE_MIGRATION",
            "integrity_check_result": validation,
            "result_status": "MIGRATION_IN_PROGRESS",
            "duplicate_of_backup_id": duplicate_of,
            "migration_state": "PREPARED",
        }
        _write_json(target_dir / "manifest.json", manifest)
        _write_json(target_dir / "validation.json", validation)
        (target_dir / "migration.log").write_text("历史归档整理已准备\n", encoding="utf-8")
        try:
            shutil.move(str(source), str(target))
            retained_validation = validate_sqlite(target)
            retained_validation["size_matches"] = int(retained_validation.get("size_bytes") or 0) == size
            retained_validation["sha256_matches"] = str(retained_validation.get("sha256") or "") == digest
            retained_validation["restorable"] = bool(
                retained_validation.get("valid")
                and retained_validation["size_matches"]
                and retained_validation["sha256_matches"]
            )
            if valid and not retained_validation["restorable"]:
                status = "INVALID_DATABASE"
            manifest.update(
                old_schema_version=retained_validation.get("schema_version", "unknown"),
                integrity_check_result=retained_validation,
                result_status=status,
                migration_state="COMPLETED",
                completed_at=datetime.now(UTC).isoformat(),
            )
            _write_json(target_dir / "validation.json", retained_validation)
            _write_json(target_dir / "manifest.json", manifest)
            (target_dir / "migration.log").write_text(f"历史归档整理：{status}\n", encoding="utf-8")
            return {**manifest, "path": str(target_dir), "moved": True}
        except Exception as exc:
            manifest.update(
                result_status="UNREADABLE_DATABASE",
                migration_state="FAILED",
                error_message=str(exc),
                completed_at=datetime.now(UTC).isoformat(),
            )
            _write_json(target_dir / "manifest.json", manifest)
            (target_dir / "migration.log").write_text(
                f"历史归档整理失败：{type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )
            return {**manifest, "path": str(target_dir), "moved": target.is_file()}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write_bytes(path, payload)


__all__ = [
    "LegacyDatabaseArchiveService",
    "legacy_archive_binding",
    "legacy_archive_bindings",
    "legacy_archive_candidates",
]
