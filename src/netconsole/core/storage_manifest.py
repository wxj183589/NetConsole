from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.version import APP_VERSION


CURRENT_STORAGE_SCHEMA_VERSION = 1


class StorageCompatibilityError(RuntimeError):
    pass


class StorageMigrationConfirmationRequired(StorageCompatibilityError):
    pass


@dataclass(frozen=True)
class StorageManifest:
    schema_version: int
    minimum_app_version: str
    last_opened_app_version: str
    last_migration_time: str
    migration_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "minimum_app_version": self.minimum_app_version,
            "last_opened_app_version": self.last_opened_app_version,
            "last_migration_time": self.last_migration_time,
            "migration_id": self.migration_id,
        }


def prepare_storage_manifest(paths: PathResolver) -> StorageManifest:
    _reject_legacy_layout(paths)
    paths.ensure_project_dirs()
    path = paths.storage_manifest_path
    if not path.is_file():
        manifest = StorageManifest(
            schema_version=CURRENT_STORAGE_SCHEMA_VERSION,
            minimum_app_version=APP_VERSION,
            last_opened_app_version=APP_VERSION,
            last_migration_time="",
            migration_id="",
        )
        _atomic_json(path, manifest.to_dict())
        return manifest
    manifest = _load_manifest(path)
    if manifest.schema_version > CURRENT_STORAGE_SCHEMA_VERSION:
        raise StorageCompatibilityError(
            f"存储 schema {manifest.schema_version} 高于当前应用支持的 {CURRENT_STORAGE_SCHEMA_VERSION}"
        )
    if manifest.schema_version < CURRENT_STORAGE_SCHEMA_VERSION:
        raise StorageMigrationConfirmationRequired(
            "此次开发版本将升级真实数据结构，旧版本可能无法继续使用。"
        )
    if _version_key(APP_VERSION) < _version_key(manifest.minimum_app_version):
        raise StorageCompatibilityError(
            f"当前应用版本 {APP_VERSION} 低于数据要求的最低版本 {manifest.minimum_app_version}"
        )
    opened = StorageManifest(
        schema_version=manifest.schema_version,
        minimum_app_version=manifest.minimum_app_version,
        last_opened_app_version=APP_VERSION,
        last_migration_time=manifest.last_migration_time,
        migration_id=manifest.migration_id,
    )
    _atomic_json(path, opened.to_dict())
    return opened


def prepare_irreversible_storage_migration(
    paths: PathResolver,
    *,
    migration_id: str,
    target_schema_version: int,
    confirmed: bool,
) -> Path:
    if not confirmed:
        raise StorageMigrationConfirmationRequired(
            "此次开发版本将升级真实数据结构，旧版本可能无法继续使用。"
        )
    safe_id = str(migration_id or "").strip()
    if not safe_id or Path(safe_id).name != safe_id:
        raise ValueError("migration_id is invalid")
    backup_root = paths.migrations_dir / "backups" / f"{safe_id}-{uuid.uuid4().hex}"
    backup_root.mkdir(parents=True, exist_ok=False)
    try:
        for source in (paths.config_dir, paths.sites_dir, paths.agents_dir):
            if source.exists():
                shutil.copytree(source, backup_root / source.name, copy_function=shutil.copy2)
        _atomic_json(
            backup_root / "backup-manifest.json",
            {
                "schema_version": CURRENT_STORAGE_SCHEMA_VERSION,
                "migration_id": safe_id,
                "target_schema_version": int(target_schema_version),
                "created_at": _now(),
                "source_data_root": str(paths.data_root),
                "app_version": APP_VERSION,
            },
        )
    except Exception:
        shutil.rmtree(backup_root, ignore_errors=True)
        raise
    return backup_root


def record_storage_migration(
    paths: PathResolver,
    *,
    migration_id: str,
    minimum_app_version: str = APP_VERSION,
) -> StorageManifest:
    manifest = StorageManifest(
        schema_version=CURRENT_STORAGE_SCHEMA_VERSION,
        minimum_app_version=minimum_app_version,
        last_opened_app_version=APP_VERSION,
        last_migration_time=_now(),
        migration_id=str(migration_id),
    )
    _atomic_json(paths.storage_manifest_path, manifest.to_dict())
    return manifest


def _reject_legacy_layout(paths: PathResolver) -> None:
    legacy_sites = paths.data_root / "data" / "sites"
    if legacy_sites.is_dir() and not paths.sites_dir.is_dir():
        raise StorageMigrationConfirmationRequired(
            "检测到旧数据目录结构；必须先完成受控迁移，Backend 不会创建第二套空局点。"
        )


def _load_manifest(path: Path) -> StorageManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return StorageManifest(
            schema_version=int(value["schema_version"]),
            minimum_app_version=str(value["minimum_app_version"]),
            last_opened_app_version=str(value.get("last_opened_app_version") or ""),
            last_migration_time=str(value.get("last_migration_time") or ""),
            migration_id=str(value.get("migration_id") or ""),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StorageCompatibilityError("storage-manifest.json 无效，Backend 已停止启动") from exc


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _version_key(value: str) -> tuple[int, ...]:
    raw = str(value or "").strip().removeprefix("v")
    try:
        return tuple(int(part) for part in raw.split("."))
    except ValueError as exc:
        raise StorageCompatibilityError(f"应用版本格式无效：{value}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "CURRENT_STORAGE_SCHEMA_VERSION",
    "StorageCompatibilityError",
    "StorageManifest",
    "StorageMigrationConfirmationRequired",
    "prepare_irreversible_storage_migration",
    "prepare_storage_manifest",
    "record_storage_migration",
]
