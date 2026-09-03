from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Callable, Iterator

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.device_credential_store import (
    repair_device_credential_states,
    sanitize_device_credentials_for_package,
)
from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import persistent_storage
from netconsole.core.sites import DEFAULT_SITE, SiteManager
from netconsole.core.version import APP_VERSION
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)
from netconsole.services.job_center.job_context import BackgroundTaskCancelled
from netconsole.services.site_sync import (
    COLLECTION_RETURN,
    FIELD_COLLECTION,
    FULL_MIGRATION,
    LIGHTWEIGHT,
    PACKAGE_FORMAT,
    PACKAGE_FORMAT_VERSION,
    PACKAGE_TYPES,
    SANITIZED_SHARE,
    SiteSyncService,
    is_sqlite_database_path,
    package_profile_for_type,
)
from netconsole.services.site_package_staging import (
    SitePackageStagingLifecycle,
    SitePackageStagingRecovery,
)


class SiteStorageError(RuntimeError):
    """可安全返回给 Desktop API 的局点/数据存储错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True)
class SiteRecord:
    site_id: str
    display_name: str
    root_path: Path
    created_at: str = ""
    updated_at: str = ""
    remark: str = ""
    line_name: str | None = None
    project_type: str | None = None

    def to_public(self, *, include_path: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "site_id": self.site_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "remark": self.remark,
            "line_name": self.line_name,
            "project_type": self.project_type,
        }
        if include_path:
            value["path"] = str(self.root_path)
        return value


@dataclass(frozen=True)
class DataRootSnapshot:
    data_root: Path
    default_data_root: Path
    site_count: int
    active_site_id: str
    storage_mode: str
    data_root_kind: str
    persistent: bool

    def to_public(self) -> dict[str, object]:
        return {
            "data_root": str(self.data_root) if self.persistent else "<temporary>",
            "default_data_root": str(self.default_data_root)
            if self.persistent
            else "<unavailable>",
            "site_count": self.site_count,
            "active_site_id": self.active_site_id,
            "storage_mode": self.storage_mode,
            "data_root_kind": self.data_root_kind,
            "persistent": self.persistent,
        }


_REGISTRY_NAME = "site_registry.json"
_BOOTSTRAP_NAME = "bootstrap.json"
_INVALID_NAME_RE = re.compile(r'[<>:"/\\|?*]')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_SITE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
_SENSITIVE_PARTS = {
    "token",
    "password",
    "passwd",
    "secret",
    "credentials",
    "bootstrap",
    "locks",
    "cache",
    "sync",
    "temp",
}
_MAX_PACKAGE_FILES = 50_000
_MAX_PACKAGE_BYTES = 20 * 1024 * 1024 * 1024
_MAX_SINGLE_FILE_BYTES = 4 * 1024 * 1024 * 1024
_LIGHTWEIGHT_COMPONENTS = (
    "device_management",
    "ac_management",
    "trackside_ap_business",
    "rail_transit_base_data",
)
_LIGHTWEIGHT_COMPONENT_PREFIXES = {
    "device_management": "device-management/",
    "ac_management": "ac-management/",
    "trackside_ap_business": "trackside-ap-business/",
    "rail_transit_base_data": "rail-transit-base-data/",
}
_LIGHTWEIGHT_FORBIDDEN_PARTS = {
    "logs",
    "history",
    "raw",
    "artifact",
    "artifacts",
    "backup",
    "backups",
    "cache",
    "runtime",
    "staging",
    "temp",
    "temporary",
    "credentials",
    "token",
}
_LIGHTWEIGHT_REQUIRED_FILES = (
    "site/site_meta.json",
    "site/db/devices.db",
)
_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lightweight_should_cancel(
    check_cancel: Callable[[], None] | None,
) -> Callable[[], bool] | None:
    if check_cancel is None:
        return None

    def callback() -> bool:
        result = check_cancel()
        return bool(result)

    return callback


def _atomic_json(path: Path, value: object) -> None:
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


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _relative_inside(root: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_site_id(value: str) -> str:
    site_id = str(value or "").strip().casefold()
    if not _SITE_ID_RE.fullmatch(site_id) or site_id in {".", ".."}:
        raise SiteStorageError(
            "SITE_ID_INVALID", "局点标识只能包含小写字母、数字、短横线和下划线"
        )
    return site_id


def validate_display_name(value: str) -> str:
    raw = str(value or "")
    if raw != raw.strip() or raw.endswith((".", " ")):
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能以空格或点结尾")
    name = raw.strip()
    if (
        not name
        or name in {".", ".."}
        or _INVALID_NAME_RE.search(name)
        or any(ord(c) < 32 for c in name)
    ):
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称包含 Windows 不允许的字符")
    if name.split(".", 1)[0].upper() in _RESERVED_NAMES:
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能使用 Windows 保留名称")
    if len(name) > 128:
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能超过 128 个字符")
    return name


def normalize_site_display_name(value: str) -> str:
    name = validate_display_name(str(value or "").strip())
    if len(name) > 64:
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能超过 64 个字符")
    return name


def normalize_optional_site_info(
    value: object,
    *,
    field_name: str,
    max_length: int = 128,
) -> str | None:
    normalized = str(value or "").strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise SiteStorageError("SITE_INFO_INVALID", f"{field_name}不能包含控制字符")
    if len(normalized) > max_length:
        raise SiteStorageError(
            "SITE_INFO_INVALID", f"{field_name}不能超过 {max_length} 个字符"
        )
    return normalized or None


def _read_optional_site_info(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _lock_for(paths: PathResolver, name: str) -> RLock:
    key = f"{paths.data_root.resolve()}:{name}"
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, RLock())


@contextmanager
def storage_lock(paths: PathResolver, name: str) -> Iterator[None]:
    lock = _lock_for(paths, name)
    with lock:
        lock_dir = paths.runtime_dir / "locks"
        with interprocess_file_lock(lock_dir / f"{name}.lock"):
            yield


def _with_site_package_operation_lease(
    method: Callable[..., dict[str, object]],
) -> Callable[..., dict[str, object]]:
    @wraps(method)
    def wrapped(self, *args: object, **kwargs: object) -> dict[str, object]:
        with self.staging_lifecycle.operation_lease():
            return method(self, *args, **kwargs)

    return wrapped


class SiteRegistryRepository:
    """全局唯一的局点 Registry；历史目录会被惰性补录。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.path = paths.config_dir / _REGISTRY_NAME

    def list(self) -> list[SiteRecord]:
        raw = self._load()
        records: dict[str, SiteRecord] = {}
        manager = SiteManager(self.paths)
        for item in raw.get("sites", []):
            if not isinstance(item, dict):
                continue
            try:
                site_id = validate_site_id(str(item.get("site_id") or ""))
                root = self._resolve_root(
                    str(item.get("relative_path") or f"sites/{site_id}")
                )
                if root.is_dir():
                    metadata = manager.load_site_metadata(root.name)
                    records[site_id] = SiteRecord(
                        site_id=site_id,
                        display_name=validate_display_name(
                            str(item.get("display_name") or site_id)
                        ),
                        root_path=root,
                        created_at=str(item.get("created_at") or ""),
                        updated_at=str(item.get("updated_at") or ""),
                        remark=str(item.get("remark") or ""),
                        line_name=_read_optional_site_info(
                            item.get("line_name")
                            if "line_name" in item
                            else metadata.get("line_name")
                        ),
                        project_type=_read_optional_site_info(
                            item.get("project_type")
                            if "project_type" in item
                            else metadata.get("system_type")
                        ),
                    )
            except SiteStorageError:
                continue
        discovered = False
        self.paths.sites_dir.mkdir(parents=True, exist_ok=True)
        used_names = {item.display_name.casefold() for item in records.values()}
        for root in self.paths.sites_dir.iterdir():
            if not root.is_dir() or root.is_symlink() or root.name.startswith("."):
                continue
            resolved_root = root.resolve()
            if resolved_root.parent != self.paths.sites_dir.resolve():
                continue
            database = resolved_root / "db" / "devices.db"
            if not database.is_file() or database.is_symlink():
                continue
            try:
                site_id = self._legacy_site_id(root.name, records)
                metadata = manager.load_site_metadata(root.name)
                display_name = self._legacy_display_name(
                    root.name, metadata, used_names
                )
            except SiteStorageError:
                continue
            if any(
                item.root_path.resolve() == resolved_root for item in records.values()
            ):
                continue
            records[site_id] = SiteRecord(
                site_id=site_id,
                display_name=display_name,
                root_path=resolved_root,
                created_at=str(metadata.get("created_at") or ""),
                updated_at=str(metadata.get("updated_at") or ""),
                remark=str(metadata.get("remark") or ""),
                line_name=_read_optional_site_info(metadata.get("line_name")),
                project_type=_read_optional_site_info(metadata.get("system_type")),
            )
            used_names.add(display_name.casefold())
            discovered = True
        if discovered and self._can_persist_discovery():
            now = _now()
            _atomic_json(
                self.path,
                {
                    "schema_version": 2,
                    "updated_at": now,
                    "sites": [self._serialize(item) for item in records.values()],
                },
            )
        return sorted(
            records.values(),
            key=lambda item: (
                item.site_id != DEFAULT_SITE,
                item.display_name.casefold(),
            ),
        )

    def refresh(self) -> list[SiteRecord]:
        """重新扫描 Registry 与受控局点目录，避免依赖进程级列表缓存。"""

        return self.list()

    def revision(self) -> str:
        """返回当前 Registry 内容版本，供 API/Renderer 判断缓存是否过期。"""

        self.refresh()
        try:
            payload = self.path.read_bytes()
        except OSError:
            payload = b"{}"
        return hashlib.sha256(payload).hexdigest()

    def get(self, site_id: str) -> SiteRecord:
        wanted = validate_site_id(site_id)
        for record in self.list():
            if record.site_id == wanted:
                return record
        raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")

    def get_by_directory_name(self, directory_name: str) -> SiteRecord:
        wanted = str(directory_name or "").strip().casefold()
        for record in self.list():
            if record.root_path.name.casefold() == wanted:
                return record
        raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")

    def directory_name(self, site_id: str) -> str:
        return self.get(site_id).root_path.name

    def resolve_directory_name(self, site_ref: str) -> str:
        try:
            return self.directory_name(site_ref)
        except SiteStorageError:
            return self.get_by_directory_name(site_ref).root_path.name

    def register(self, record: SiteRecord) -> SiteRecord:
        site_id = validate_site_id(record.site_id)
        display_name = validate_display_name(record.display_name)
        records = {item.site_id: item for item in self.list()}
        if (
            site_id in records
            and records[site_id].root_path.resolve() != record.root_path.resolve()
        ):
            raise SiteStorageError("SITE_ALREADY_EXISTS", "局点标识已存在")
        for item in records.values():
            if (
                item.site_id != site_id
                and item.display_name.casefold() == display_name.casefold()
            ):
                raise SiteStorageError("SITE_ALREADY_EXISTS", "局点名称已存在")
        now = _now()
        value = SiteRecord(
            site_id,
            display_name,
            record.root_path.resolve(),
            record.created_at or now,
            now,
            record.remark,
            record.line_name,
            record.project_type,
        )
        records[site_id] = value
        _atomic_json(
            self.path,
            {
                "schema_version": 2,
                "updated_at": now,
                "sites": [self._serialize(item) for item in records.values()],
            },
        )
        return value

    def update_metadata(
        self,
        site_id: str,
        *,
        display_name: str,
        line_name: str | None,
        project_type: str | None,
    ) -> SiteRecord:
        wanted = validate_site_id(site_id)
        name = normalize_site_display_name(display_name)
        records = {item.site_id: item for item in self.list()}
        current = records.get(wanted)
        if current is None:
            raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")
        if any(
            item.site_id != wanted
            and item.display_name.casefold() == name.casefold()
            for item in records.values()
        ):
            raise SiteStorageError("SITE_NAME_CONFLICT", "局点名称已存在")
        updated = SiteRecord(
            site_id=current.site_id,
            display_name=name,
            root_path=current.root_path,
            created_at=current.created_at,
            updated_at=_now(),
            remark=current.remark,
            line_name=line_name,
            project_type=project_type,
        )
        records[wanted] = updated
        _atomic_json(
            self.path,
            {
                "schema_version": 2,
                "updated_at": updated.updated_at,
                "sites": [self._serialize(item) for item in records.values()],
            },
        )
        return updated

    def unregister(self, site_id: str, expected_root: Path) -> None:
        """Remove one exact registry record without discovering or touching other sites."""
        wanted = validate_site_id(site_id)
        expected = Path(expected_root).resolve()
        raw = self._load()
        retained: list[dict[str, object]] = []
        removed = False
        for item in raw.get("sites", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("site_id") or "").casefold() != wanted:
                retained.append(item)
                continue
            resolved = self._resolve_root(
                str(item.get("relative_path") or f"sites/{wanted}")
            )
            if resolved != expected:
                raise SiteStorageError(
                    "SITE_REGISTRY_CONFLICT", "Registry 局点路径与清理目标不一致"
                )
            removed = True
        if not removed:
            raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")
        _atomic_json(
            self.path, {"schema_version": 2, "updated_at": _now(), "sites": retained}
        )

    def registered_root_path(self, site_id: str) -> Path:
        """Return the Registry path without resolving links for mutation checks."""
        wanted = validate_site_id(site_id)
        for item in self._load().get("sites", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("site_id") or "").casefold() != wanted:
                continue
            relative = str(item.get("relative_path") or f"sites/{wanted}")
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise SiteStorageError(
                    "SITE_REGISTRY_CONFLICT", "Registry 局点路径必须是受控相对路径"
                )
            return self.paths.data_root / relative_path
        raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")

    def raw_record(self, site_id: str) -> dict[str, object] | None:
        """Return one exact persisted record without lazy site discovery."""
        wanted = validate_site_id(site_id)
        matches = [
            dict(item)
            for item in self._load().get("sites", [])
            if isinstance(item, dict)
            and str(item.get("site_id") or "").casefold() == wanted
        ]
        if len(matches) > 1:
            raise SiteStorageError(
                "SITE_REGISTRY_CONFLICT", "Registry 存在重复局点记录"
            )
        return matches[0] if matches else None

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": 1, "sites": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "sites": []}
        return value if isinstance(value, dict) else {"schema_version": 1, "sites": []}

    def _can_persist_discovery(self) -> bool:
        if not self.path.exists():
            return True
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(value, dict)

    def _legacy_site_id(
        self, directory_name: str, records: dict[str, SiteRecord]
    ) -> str:
        try:
            candidate = validate_site_id(directory_name.casefold())
        except SiteStorageError:
            digest = hashlib.sha256(directory_name.encode("utf-8")).hexdigest()
            candidate = f"legacy-{digest[:12]}"
        if candidate not in records:
            return candidate
        digest = hashlib.sha256(directory_name.encode("utf-8")).hexdigest()
        for length in (16, 24, 32, 40, 64):
            candidate = f"legacy-{digest[:length]}"
            if candidate not in records:
                return candidate
        raise SiteStorageError("SITE_REGISTRY_CONFLICT", "历史局点标识发生冲突")

    @staticmethod
    def _legacy_display_name(
        directory_name: str, metadata: dict[str, object], used_names: set[str]
    ) -> str:
        candidate = str(metadata.get("display_name") or directory_name)
        try:
            display_name = validate_display_name(candidate)
        except SiteStorageError:
            display_name = validate_display_name(directory_name)
        if display_name.casefold() not in used_names:
            return display_name
        suffix = f"（{directory_name}）"
        return validate_display_name(
            f"{display_name[: max(1, 128 - len(suffix))]}{suffix}"
        )

    def _serialize(self, item: SiteRecord) -> dict[str, object]:
        try:
            relative = (
                item.root_path.resolve()
                .relative_to(self.paths.data_root.resolve())
                .as_posix()
            )
        except ValueError as exc:
            raise SiteStorageError(
                "SITE_REGISTRY_CONFLICT", "局点必须位于当前数据根内"
            ) from exc
        value: dict[str, object] = {
            "site_id": item.site_id,
            "display_name": item.display_name,
            "relative_path": relative,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "remark": item.remark,
        }
        if item.line_name is not None:
            value["line_name"] = item.line_name
        if item.project_type is not None:
            value["project_type"] = item.project_type
        return value

    def _resolve_root(self, relative: str) -> Path:
        candidate = (self.paths.data_root / relative).resolve()
        if (
            not _relative_inside(self.paths.data_root, candidate)
            or candidate == self.paths.data_root
        ):
            raise SiteStorageError("SITE_REGISTRY_CONFLICT", "Registry 局点路径越界")
        return candidate


class SiteApplicationService:
    def __init__(self, paths: PathResolver, task_service: object | None = None) -> None:
        self.paths = paths
        self.registry = SiteRegistryRepository(paths)
        self.manager = SiteManager(paths)
        self.task_service = task_service
        self._runtime_rebind_handler: Callable[[str], None] | None = None

    def set_runtime_rebind_handler(
        self, handler: Callable[[str], None] | None
    ) -> None:
        """绑定宿主运行时的 SiteContext 热重绑定回调。"""

        self._runtime_rebind_handler = handler

    def list_sites(self) -> list[dict[str, object]]:
        active = self.active_site_id()
        records = self.registry.refresh()
        registry_revision = self.registry.revision()
        from netconsole.services.site_lifecycle import SiteAuditService

        latest = SiteAuditService(self.paths).latest() or {}
        audits = {
            str(item.get("site_id") or ""): item
            for item in latest.get("sites", [])
            if isinstance(item, dict)
        }
        result = [
            {
                **item.to_public(include_path=persistent_storage()),
                "active": item.site_id == active,
                "size_bytes": _directory_size(item.root_path),
                "registry_revision": registry_revision,
                **self._lifecycle_summary(
                    item,
                    audits.get(item.site_id),
                    str(latest.get("generated_at") or ""),
                ),
            }
            for item in records
        ]
        return result

    def get_site(self, site_id: str) -> dict[str, object]:
        item = self.registry.get(site_id)
        from netconsole.services.site_lifecycle import SiteAuditService

        latest = SiteAuditService(self.paths).latest() or {}
        audit = next(
            (
                value
                for value in latest.get("sites", [])
                if isinstance(value, dict) and value.get("site_id") == item.site_id
            ),
            None,
        )
        return {
            **item.to_public(include_path=persistent_storage()),
            "active": item.site_id == self.active_site_id(),
            "size_bytes": _directory_size(item.root_path),
            "registry_revision": self.registry.revision(),
            **self._lifecycle_summary(
                item, audit, str(latest.get("generated_at") or "")
            ),
        }

    def task_result_storage_status(self, site_id: str) -> dict[str, object]:
        site = self.registry.get(site_id)
        return TaskResultRolloutService(site.root_path / "db" / "tasks.db").status()

    def _lifecycle_summary(
        self, item: SiteRecord, audit: dict[str, object] | None, audited_at: str
    ) -> dict[str, object]:
        metadata = self.manager.load_site_metadata(item.root_path.name)
        managed_demo = bool(metadata.get("managed_demo") is True)
        if audit:
            database_files = audit.get("database_files") or []
            integrity = (
                "ok"
                if database_files
                and all(
                    value.get("quick_check") == "ok"
                    for value in database_files
                    if isinstance(value, dict)
                )
                else "unknown"
            )
            classification = str(audit.get("classification") or "unknown")
            migration_status = str(audit.get("migration_status") or "unknown")
            recommended_action = str(
                audit.get("recommended_action") or "keep_and_review"
            )
        else:
            integrity = "unknown"
            classification = (
                "managed_demo"
                if managed_demo
                else "legacy_demo"
                if item.site_id == DEFAULT_SITE
                else "legacy_valid"
                if item.site_id.startswith("legacy-")
                else "normal_site"
            )
            migration_status = str(
                metadata.get("migration_status")
                or ("managed" if managed_demo else "not_audited")
            )
            recommended_action = "audit_required"
        return {
            "site_kind": "demo"
            if item.site_id == DEFAULT_SITE
            else "legacy"
            if item.site_id.startswith("legacy-")
            else "formal",
            "classification": classification,
            "managed_demo": managed_demo,
            "demo_seed_version": str(metadata.get("seed_version") or ""),
            "migration_status": migration_status,
            "data_integrity": integrity,
            "recommended_action": recommended_action,
            "audited_at": audited_at if audit else "",
        }

    def active_site_id(self) -> str:
        selected = self.manager.get_current_site()
        try:
            return self.registry.get_by_directory_name(selected).site_id
        except SiteStorageError:
            return selected

    def get_active_site(self) -> dict[str, object]:
        return self.get_site(self.active_site_id())

    def active_site_directory_name(self) -> str:
        return self.registry.directory_name(self.active_site_id())

    def update_site_info(
        self,
        site_id: str,
        *,
        display_name: str,
        line_name: object = None,
        project_type: object = None,
    ) -> dict[str, object]:
        wanted = validate_site_id(site_id)
        name = normalize_site_display_name(display_name)
        normalized_line = normalize_optional_site_info(
            line_name, field_name="线路名称"
        )
        normalized_project = normalize_optional_site_info(
            project_type, field_name="项目类型"
        )
        with storage_lock(self.paths, "site-mutation"):
            current = self.registry.get(wanted)
            metadata_path = current.root_path / "site_meta.json"
            metadata_existed = metadata_path.is_file()
            metadata_backup = metadata_path.read_bytes() if metadata_existed else b""
            try:
                self.manager.save_site_metadata(
                    current.root_path.name,
                    {
                        "display_name": name,
                        "line_name": normalized_line or "",
                        "system_type": normalized_project or "",
                    },
                )
                self.registry.update_metadata(
                    wanted,
                    display_name=name,
                    line_name=normalized_line,
                    project_type=normalized_project,
                )
            except Exception as exc:
                try:
                    if metadata_existed:
                        _atomic_bytes(metadata_path, metadata_backup)
                    else:
                        metadata_path.unlink(missing_ok=True)
                except OSError:
                    app_logger.log_error(
                        "SITE_INFO_ROLLBACK_FAILED",
                        f"site_id={wanted} stage=site_metadata",
                    )
                if isinstance(exc, SiteStorageError):
                    raise
                raise SiteStorageError(
                    "SITE_INFO_UPDATE_FAILED", "局点信息保存失败，原信息已恢复"
                ) from exc
        app_logger.log_info("SITE_INFO_UPDATED", f"site_id={wanted}")
        return self.get_site(wanted)

    def create_site(
        self,
        site_id: str,
        display_name: str,
        *,
        remark: str = "",
        activate: bool = False,
    ) -> dict[str, object]:
        site_id = validate_site_id(site_id)
        display_name = validate_display_name(display_name)
        with storage_lock(self.paths, "site-mutation"):
            if any(item.site_id == site_id for item in self.registry.list()):
                raise SiteStorageError("SITE_ALREADY_EXISTS", "局点标识已存在")
            if any(
                item.display_name.casefold() == display_name.casefold()
                for item in self.registry.list()
            ):
                raise SiteStorageError("SITE_ALREADY_EXISTS", "局点名称已存在")
            final = self.paths.sites_dir / site_id
            staging = self.paths.temp_dir / "site-staging" / uuid.uuid4().hex
            try:
                staging.mkdir(parents=True)
                db_path = staging / "db" / "devices.db"
                db_path.parent.mkdir(parents=True)
                database = Database(db_path)
                database.initialize()
                DeviceGroupRepository(database, site_id).ensure_default_groups()
                _atomic_json(
                    staging / "site_meta.json",
                    {
                        "site_id": site_id,
                        "site_uuid": f"site-{uuid.uuid4()}",
                        "display_name": display_name,
                        "remark": remark,
                        "schema_version": 1,
                        "sync_schema_version": 1,
                        "revision": 1,
                        "created_at": _now(),
                    },
                )
                _quick_check_site(staging)
                _finalize_site_databases(staging)
                if final.exists():
                    raise SiteStorageError("SITE_ALREADY_EXISTS", "局点目录已存在")
                final.parent.mkdir(parents=True, exist_ok=True)
                _publish_directory(staging, final)
                record = self.registry.register(
                    SiteRecord(site_id, display_name, final, remark=remark)
                )
                if activate:
                    self.switch_site(site_id)
                return self.get_site(record.site_id)
            except SiteStorageError:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise SiteStorageError("SITE_CREATE_FAILED", "局点创建失败") from exc

    def switch_site(self, site_id: str) -> dict[str, object]:
        site_id = validate_site_id(site_id)
        with storage_lock(self.paths, "site-switch"):
            record = self.registry.get(site_id)
            previous = self.active_site_id()
            previous_directory = self.registry.resolve_directory_name(previous)
            app_logger.log_info(
                "SITE_SWITCH_STARTED",
                f"previous_site_id={previous} target_site_id={site_id}",
            )
            self.ensure_no_active_tasks_anywhere()
            try:
                self.manager.switch_site(record.root_path.name)
                if self._runtime_rebind_handler is not None:
                    self._runtime_rebind_handler(record.root_path.name)
                return {
                    **record.to_public(),
                    "site_root": str(record.root_path),
                    "active": True,
                    "previous_site_id": previous,
                    "registry_revision": self.registry.revision(),
                    "switch_revision": uuid.uuid4().hex,
                    "runtime_revision": uuid.uuid4().hex,
                    "restart_required": False,
                }
            except Exception as exc:
                try:
                    self.manager.switch_site(previous_directory)
                    if self._runtime_rebind_handler is not None:
                        self._runtime_rebind_handler(previous_directory)
                except Exception:
                    pass
                app_logger.log_error(
                    "SITE_SWITCH_FAILED",
                    f"stage=activate previous_site_id={previous} target_site_id={site_id} error_type={exc.__class__.__name__}",
                )
                raise SiteStorageError(
                    "SITE_SWITCH_BLOCKED", "局点切换失败，已恢复原局点"
                ) from exc

    def preflight_site_switch(self, site_id: str) -> dict[str, object]:
        site_id = validate_site_id(site_id)
        record = self.registry.get(site_id)
        previous = self.active_site_id()
        if site_id == previous:
            raise SiteStorageError("SITE_ALREADY_ACTIVE", "目标局点已经是当前局点")
        self.ensure_no_active_tasks_anywhere()
        return {
            "ready": True,
            "target_site_id": record.site_id,
            "previous_site_id": previous,
            "registry_revision": self.registry.revision(),
        }

    def migrate_site(
        self,
        site_id: str,
        destination_root: Path,
        *,
        check_cancel: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        """把单个局点复制到另一个受控数据根；源目录始终保留。"""
        record = self.registry.get(site_id)
        destination_root = Path(destination_root).expanduser().resolve()
        if destination_root == self.paths.data_root.resolve():
            raise SiteStorageError(
                "SITE_MIGRATION_CONFLICT", "目标数据根与当前数据根相同"
            )
        if _relative_inside(self.paths.data_root, destination_root) or _relative_inside(
            destination_root, self.paths.data_root
        ):
            raise SiteStorageError(
                "DATA_ROOT_NESTED_PATH", "单局点迁移目标不能与当前数据根嵌套"
            )
        destination = destination_root / "data" / "sites" / record.site_id
        staging = destination_root / "temp" / "site-migration" / uuid.uuid4().hex
        with storage_lock(self.paths, "site-migration"):
            try:
                if self.task_service is not None:
                    self._ensure_no_active_tasks(record.site_id)
                staging.mkdir(parents=True, exist_ok=True)
                if check_cancel:
                    check_cancel()
                _copy_tree_snapshot(
                    record.root_path, staging, check_cancel=check_cancel
                )
                _quick_check_site(staging)
                if destination.exists():
                    raise SiteStorageError("SITE_MIGRATION_CONFLICT", "目标局点已存在")
                destination.parent.mkdir(parents=True, exist_ok=True)
                _publish_directory(staging, destination)
                return {
                    "site_id": record.site_id,
                    "destination_root": str(destination_root),
                    "old_data_retained": True,
                    "restart_required": True,
                }
            except SiteStorageError:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise SiteStorageError(
                    "SITE_MIGRATION_FAILED", "单局点迁移失败，源数据未改变"
                ) from exc

    def _ensure_no_active_tasks(self, site_id: str) -> None:
        active = self._list_blocking_tasks(site_id)
        if active:
            app_logger.log_warning(
                "SITE_SWITCH_BLOCKED_BY_ACTIVE_TASK",
                f"site_id={site_id} task_count={len(active)} task_ids={','.join(str(item['task_id']) for item in active)}",
            )
            raise SiteStorageError(
                "SITE_HAS_ACTIVE_TASKS",
                "局点存在仍在运行的任务，无法切换",
                details={"blocking_tasks": active},
            )

    def _list_blocking_tasks(self, site_id: str) -> list[dict[str, object]]:
        service = self.task_service
        if service is None:
            return []
        directory_name = self.registry.directory_name(site_id)
        # A pristine managed Demo does not ship a task database.  The global
        # site-mutation preflight is read-only and must not create one merely
        # to prove that no active tasks exist; doing so changes the Demo seed
        # manifest before the rebuild worker can consume it.
        if not self.paths.site_tasks_db_path(directory_name).is_file():
            return []
        list_blocking = getattr(service, "list_site_blocking_tasks", None)
        if callable(list_blocking):
            snapshots, reconciled = list_blocking(directory_name)
        else:
            repository = getattr(service, "repository", lambda _site: None)(
                directory_name
            )
            if repository is None:
                return []
            snapshots = repository.list(
                statuses={
                    TaskState.PENDING,
                    TaskState.STARTING,
                    TaskState.RUNNING,
                    TaskState.STOPPING,
                },
                limit=1000,
            )
            reconciled = []
        for task in reconciled:
            app_logger.log_warning(
                "SITE_SWITCH_STALE_TASK_RECONCILED",
                f"site_id={site_id} task_id={task.task_id} previous_status=active new_status={task.status.value}",
            )
        return [self._blocking_task_detail(snapshot) for snapshot in snapshots]

    @staticmethod
    def _blocking_task_detail(snapshot: TaskSnapshot) -> dict[str, object]:
        status = snapshot.status.value
        return {
            "task_id": snapshot.task_id,
            "task_type": snapshot.task_type,
            "task_name": snapshot.task_name,
            "status": status,
            "created_at": snapshot.created_time,
            "updated_at": snapshot.updated_time,
            "blocking_reason": f"任务状态为 {status}，任务宿主仍可能继续执行",
            "recoverable": False,
            "stale": False,
        }

    def ensure_no_active_tasks(self, site_id: str) -> None:
        self._ensure_no_active_tasks(validate_site_id(site_id))

    def ensure_no_active_tasks_anywhere(self) -> None:
        blocking: list[dict[str, object]] = []
        for site in self.registry.list():
            blocking.extend(self._list_blocking_tasks(site.site_id))
        if blocking:
            app_logger.log_warning(
                "SITE_SWITCH_BLOCKED_BY_ACTIVE_TASK",
                f"scope=all_sites task_count={len(blocking)} task_ids={','.join(str(item['task_id']) for item in blocking)}",
            )
            raise SiteStorageError(
                "SITE_HAS_ACTIVE_TASKS",
                "存在仍在运行的任务，无法切换局点",
                details={"blocking_tasks": blocking},
            )


class DataRootApplicationService:
    def __init__(
        self, paths: PathResolver, sites: SiteApplicationService | None = None
    ) -> None:
        self.paths = paths
        self.sites = sites or SiteApplicationService(paths)

    def snapshot(self) -> DataRootSnapshot:
        from netconsole.core.runtime_environment import (
            desktop_storage_mode,
            persistent_storage,
        )

        mode = desktop_storage_mode()
        return DataRootSnapshot(
            self.paths.data_root,
            _default_data_root(self.paths),
            len(self.sites.registry.list()),
            self.sites.active_site_id(),
            mode,
            "temporary" if mode == "isolated_test" else "persistent",
            persistent_storage(),
        )

    def validate(self, target: Path) -> dict[str, object]:
        candidate = self._validate_target(target)
        return {
            "valid": True,
            "path": str(candidate),
            "free_bytes": shutil.disk_usage(
                candidate if candidate.exists() else candidate.parent
            ).free,
        }

    def migrate(
        self, target: Path, *, check_cancel: Callable[[], None] | None = None
    ) -> dict[str, object]:
        destination = self._validate_target(target)
        if destination == self.paths.data_root.resolve():
            raise SiteStorageError("DATA_ROOT_INVALID", "目标数据根与当前路径相同")
        with storage_lock(self.paths, "global-data-migration"):
            operation_id = uuid.uuid4().hex
            staging = destination.with_name(
                f"{destination.name}.staging-{operation_id}"
            )
            payload = staging / "payload"
            published = False
            try:
                if staging.exists():
                    raise SiteStorageError(
                        "DATA_ROOT_INVALID", "数据根迁移暂存目录已存在"
                    )
                occupied = list(destination.iterdir())
                if occupied:
                    raise SiteStorageError("DATA_ROOT_INVALID", "目标数据根必须为空")
                _write_migration_operation(
                    staging, "created", self.paths.data_root, destination
                )
                for source in self.paths.data_root.iterdir():
                    if source.name in {"runtime", "staging"}:
                        continue
                    if check_cancel:
                        check_cancel()
                    _write_migration_operation(
                        staging, "copying", self.paths.data_root, destination
                    )
                    target_path = payload / source.name
                    if source.is_dir():
                        _copy_tree_snapshot(
                            source, target_path, check_cancel=check_cancel
                        )
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target_path)
                _write_migration_operation(
                    staging, "verifying", self.paths.data_root, destination
                )
                _quick_check_site_tree(payload / "sites")
                _rewrite_migrated_storage_manifest(payload, destination)
                manifest = {
                    "format": "netconsole-data-root-migration",
                    "version": 2,
                    "migration_id": operation_id,
                    "created_at": _now(),
                    "source": str(self.paths.data_root),
                    "destination": str(destination),
                }
                _atomic_json(
                    payload / "migrations" / f"migration-{operation_id}.json", manifest
                )
                _write_migration_operation(
                    staging, "committing", self.paths.data_root, destination
                )
                destination.rmdir()
                _publish_data_root(payload, destination)
                published = True
                _write_migration_operation(
                    staging, "completed", self.paths.data_root, destination
                )
                shutil.rmtree(staging, ignore_errors=True)
                return {
                    "data_root": str(destination),
                    "restart_required": True,
                    "old_data_root_retained": True,
                }
            except SiteStorageError:
                _write_migration_operation(
                    staging, "failed", self.paths.data_root, destination
                )
                raise
            except Exception as exc:
                _write_migration_operation(
                    staging, "failed", self.paths.data_root, destination
                )
                raise SiteStorageError(
                    "DATA_ROOT_MIGRATION_FAILED", "数据根迁移失败，旧数据未改变"
                ) from exc
            finally:
                if published:
                    shutil.rmtree(staging, ignore_errors=True)

    def _validate_target(self, target: Path) -> Path:
        candidate = Path(target).expanduser().resolve()
        if not candidate.is_absolute():
            raise SiteStorageError("DATA_ROOT_INVALID", "数据根必须是绝对路径")
        app_root = self.paths.app_root.resolve()
        current = self.paths.data_root.resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if _relative_inside(app_root, candidate) or (
            _relative_inside(temporary, candidate)
            and not _relative_inside(temporary, current)
        ):
            raise SiteStorageError(
                "DATA_ROOT_UNSAFE_LOCATION", "不能使用源码、安装目录或系统临时目录"
            )
        if _relative_inside(current, candidate) or _relative_inside(candidate, current):
            raise SiteStorageError(
                "DATA_ROOT_NESTED_PATH", "目标数据根不能与当前数据根嵌套"
            )
        candidate.mkdir(parents=True, exist_ok=True)
        marker = candidate / f".write-test-{uuid.uuid4().hex}"
        try:
            marker.write_text("ok", encoding="ascii")
        except OSError as exc:
            raise SiteStorageError(
                "DATA_ROOT_NOT_WRITABLE", "目标数据根不可写"
            ) from exc
        finally:
            marker.unlink(missing_ok=True)
        return candidate


class SitePackageService:
    def __init__(
        self, paths: PathResolver, sites: SiteApplicationService | None = None
    ) -> None:
        self.paths = paths
        self.sites = sites or SiteApplicationService(paths)
        self.staging_lifecycle = SitePackageStagingLifecycle(paths)

    def recover_orphaned_staging(self) -> SitePackageStagingRecovery:
        return self.staging_lifecycle.recover_orphans()

    @_with_site_package_operation_lease
    def export_site(
        self,
        site_id: str,
        destination: Path,
        *,
        package_type: str = FULL_MIGRATION,
        check_cancel: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        normalized_type = str(package_type or FULL_MIGRATION).strip().casefold()
        if normalized_type not in PACKAGE_TYPES:
            raise SiteStorageError("SITE_EXPORT_TYPE_INVALID", "不支持的局点数据包类型")
        sync = SiteSyncService(self.paths, self.sites)
        if normalized_type == FIELD_COLLECTION:
            return sync.export_field_package(
                site_id, destination, check_cancel=check_cancel
            )
        if normalized_type == COLLECTION_RETURN:
            return sync.export_return_package(
                site_id, destination, check_cancel=check_cancel
            )
        if normalized_type == FULL_MIGRATION:
            return self._export_full_site(
                site_id,
                destination,
                check_cancel=check_cancel,
            )
        if normalized_type == LIGHTWEIGHT:
            return self._export_lightweight_site(
                site_id,
                destination,
                check_cancel=check_cancel,
            )
        if normalized_type != SANITIZED_SHARE:
            raise SiteStorageError("SITE_EXPORT_TYPE_INVALID", "不支持的局点数据包类型")
        site = self.sites.registry.get(site_id)
        identity = sync.ensure_sync_identity(site, require_legacy_audit=False)
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.casefold() != ".ncsite":
            destination = destination.with_suffix(".ncsite")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging, staging_journal = self.staging_lifecycle.begin_publish_path(
            destination
        )
        try:
            manifest_files: dict[str, str] = {}
            reentry_count = 0
            self.paths.temp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="netconsole-site-export-", dir=self.paths.temp_dir
            ) as temp:
                root = Path(temp) / "site"
                for source in _safe_site_files(site.root_path):
                    if check_cancel:
                        check_cancel()
                    relative = source.relative_to(site.root_path).as_posix()
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if is_sqlite_database_path(source):
                        reentry_count = max(
                            reentry_count,
                            _copy_sanitized_database(source, target),
                        )
                    else:
                        shutil.copy2(source, target)
                    manifest_files[f"site/{relative}"] = _sha256(target)
                manifest = {
                    "format": PACKAGE_FORMAT,
                    "format_version": PACKAGE_FORMAT_VERSION,
                    "package_id": str(uuid.uuid4()),
                    "package_type": SANITIZED_SHARE,
                    "package_profile": package_profile_for_type(SANITIZED_SHARE),
                    "app_version": APP_VERSION.removeprefix("v"),
                    "site_id": site.site_id,
                    "site_uuid": identity["site_uuid"],
                    "site_name": site.display_name,
                    "line_name": site.line_name,
                    "project_type": site.project_type,
                    "site_revision": identity["revision"],
                    "base_revision": identity["revision"],
                    "created_at": _now(),
                    "source_platform": "windows" if os.name == "nt" else os.name,
                    "databases": [
                        name for name in manifest_files if is_sqlite_database_path(name)
                    ],
                    "artifacts": [],
                    "checksums": manifest_files,
                    "contains_credentials": False,
                    "credential_reentry_count": reentry_count,
                    "site_scope": {
                        "schema_version": 1,
                        "source_directory_name": site.root_path.name,
                    },
                    "relation_summary": {
                        "device_groups": _device_group_contract(
                            root / "db" / "devices.db"
                        )
                    },
                }
                (Path(temp) / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (Path(temp) / "checksums.json").write_text(
                    json.dumps(manifest_files, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (Path(temp) / "README.txt").write_text(
                    "NetConsole 脱敏分享包；导入后需要重新录入设备凭据。\n",
                    encoding="utf-8",
                )
                with zipfile.ZipFile(
                    staging, "w", compression=zipfile.ZIP_DEFLATED
                ) as archive:
                    for item in Path(temp).rglob("*"):
                        if item.is_file():
                            archive.write(item, item.relative_to(temp).as_posix())
            self.inspect_package(staging, validate_extension=False)
            os.replace(staging, destination)
            return {
                "package_name": destination.name,
                "package_type": SANITIZED_SHARE,
                "site_uuid": identity["site_uuid"],
                "base_revision": identity["revision"],
                "size_bytes": destination.stat().st_size,
                "contains_credentials": False,
                "credential_reentry_count": reentry_count,
            }
        finally:
            self.staging_lifecycle.finish_publish_path(staging, staging_journal)

    def _export_full_site(
        self,
        site_id: str,
        destination: Path,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> dict[str, object]:
        site = self.sites.registry.get(site_id)
        identity = SiteSyncService(self.paths, self.sites).ensure_sync_identity(
            site, require_legacy_audit=False
        )
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.casefold() != ".ncsite":
            destination = destination.with_suffix(".ncsite")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging, staging_journal = self.staging_lifecycle.begin_publish_path(
            destination
        )
        try:
            self.paths.temp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="netconsole-site-export-", dir=self.paths.temp_dir
            ) as temp:
                temp_root = Path(temp)
                site_root = temp_root / "site"
                manifest_files: dict[str, str] = {}
                for source in _safe_site_files(
                    site.root_path,
                    include_full_sync_authority=True,
                ):
                    if check_cancel:
                        check_cancel()
                    relative = source.relative_to(site.root_path).as_posix()
                    target = site_root / relative
                    if is_sqlite_database_path(source):
                        _copy_database_snapshot(source, target)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                    manifest_files[f"site/{relative}"] = _sha256(target)
                manifest: dict[str, object] = {
                    "format": PACKAGE_FORMAT,
                    "format_version": PACKAGE_FORMAT_VERSION,
                    "package_id": str(uuid.uuid4()),
                    "package_type": FULL_MIGRATION,
                    "package_profile": package_profile_for_type(FULL_MIGRATION),
                    "app_version": APP_VERSION.removeprefix("v"),
                    "site_id": site.site_id,
                    "site_uuid": identity["site_uuid"],
                    "site_name": site.display_name,
                    "line_name": site.line_name,
                    "project_type": site.project_type,
                    "site_revision": identity["revision"],
                    "base_revision": identity["revision"],
                    "created_at": _now(),
                    "source_platform": "windows" if os.name == "nt" else os.name,
                    "databases": [
                        name for name in manifest_files if is_sqlite_database_path(name)
                    ],
                    "artifacts": [],
                    "required_files": [
                        "site/site_meta.json",
                        "site/db/devices.db",
                    ],
                    "checksums": manifest_files,
                    "contains_credentials": True,
                    "credential_reentry_count": 0,
                    "encrypted": False,
                    "site_scope": {
                        "schema_version": 1,
                        "source_directory_name": site.root_path.name,
                    },
                    "relation_summary": {
                        "device_groups": _device_group_contract(
                            site_root / "db" / "devices.db"
                        )
                    },
                }
                _atomic_json(temp_root / "manifest.json", manifest)
                _atomic_json(temp_root / "checksums.json", manifest_files)
                (temp_root / "README.txt").write_text(
                    "NetConsole 完整迁移包包含设备用户名和密码，请妥善保管。\n",
                    encoding="utf-8",
                )
                with zipfile.ZipFile(
                    staging, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
                ) as archive:
                    for item in temp_root.rglob("*"):
                        if item.is_file():
                            archive.write(item, item.relative_to(temp_root).as_posix())
            self.inspect_package(staging, validate_extension=False)
            os.replace(staging, destination)
            return {
                "package_name": destination.name,
                "package_type": FULL_MIGRATION,
                "site_uuid": identity["site_uuid"],
                "base_revision": identity["revision"],
                "size_bytes": destination.stat().st_size,
                "contains_credentials": True,
                "credential_reentry_count": 0,
                "encrypted": False,
            }
        finally:
            self.staging_lifecycle.finish_publish_path(staging, staging_journal)

    def _export_lightweight_site(
        self,
        site_id: str,
        destination: Path,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> dict[str, object]:
        """Publish a small, directly restorable site package.

        The device CSV deliberately uses the existing sensitive exporter.  The
        other three files use their existing read-only exporters; if a module
        has no usable source data, a safe status file keeps the package
        inspectable while making the missing module explicit.  Only the
        current site metadata and devices database are retained as the
        restorable core; histories, raw files, artifacts and runtime state are
        intentionally not copied.
        """

        site = self.sites.registry.get(site_id)
        sync = SiteSyncService(self.paths, self.sites)
        identity = sync.ensure_sync_identity(site, require_legacy_audit=False)
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.casefold() != ".zip":
            destination = destination.with_suffix(".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging, staging_journal = self.staging_lifecycle.begin_publish_path(destination)
        try:
            self.paths.temp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="netconsole-lightweight-export-", dir=self.paths.temp_dir
            ) as temp:
                root = Path(temp)
                module_roots = {
                    "device_management": root / "device-management",
                    "ac_management": root / "ac-management",
                    "trackside_ap_business": root / "trackside-ap-business",
                    "rail_transit_base_data": root / "rail-transit-base-data",
                }
                for module_root in module_roots.values():
                    module_root.mkdir(parents=True, exist_ok=True)
                components: dict[str, str] = {}
                component_paths: dict[str, str] = {}

                site_root = root / "site"
                _atomic_json(
                    site_root / "site_meta.json",
                    self.sites.manager.load_site_metadata(site.site_id),
                )
                _copy_database_snapshot(
                    self.paths.site_db_path(site.site_id),
                    site_root / "db" / "devices.db",
                )

                self._lightweight_export_device_csv(
                    module_roots["device_management"] / "devices.csv",
                    site,
                    check_cancel=check_cancel,
                )
                component_paths["device_management"] = self._lightweight_component_path(
                    root,
                    module_roots["device_management"],
                    "devices.csv",
                )
                components["device_management"] = "devices.csv"

                self._lightweight_export_ac_csv(
                    module_roots["ac_management"] / "fit-ap-resources.csv",
                    site,
                    check_cancel=check_cancel,
                )
                component_paths["ac_management"] = self._lightweight_component_path(
                    root,
                    module_roots["ac_management"],
                    "fit-ap-resources.csv",
                )
                components["ac_management"] = "fit-ap-resources.csv"

                trackside_tmp = root / "trackside-ap-business.tmp.xlsx"
                self._lightweight_export_trackside(
                    module_roots["trackside_ap_business"] / "trackside-ap-business.xlsx",
                    site,
                    trackside_tmp,
                    check_cancel=check_cancel,
                )
                trackside_tmp.unlink(missing_ok=True)
                component_paths[
                    "trackside_ap_business"
                ] = self._lightweight_component_path(
                    root,
                    module_roots["trackside_ap_business"],
                    "trackside-ap-business.xlsx",
                )
                components["trackside_ap_business"] = "trackside-ap-business.xlsx"

                self._lightweight_export_base_data(
                    module_roots["rail_transit_base_data"] / "rail-transit-base-data.xlsx",
                    site,
                    check_cancel=check_cancel,
                )
                component_paths[
                    "rail_transit_base_data"
                ] = self._lightweight_component_path(
                    root,
                    module_roots["rail_transit_base_data"],
                    "rail-transit-base-data.xlsx",
                )
                components["rail_transit_base_data"] = "rail-transit-base-data.xlsx"

                manifest_files = {
                    item.relative_to(root).as_posix(): _sha256(item)
                    for item in root.rglob("*")
                    if item.is_file()
                }
                manifest = {
                    "format": PACKAGE_FORMAT,
                    "format_version": PACKAGE_FORMAT_VERSION,
                    "package_id": str(uuid.uuid4()),
                    "package_type": LIGHTWEIGHT,
                    "package_profile": package_profile_for_type(LIGHTWEIGHT),
                    "app_version": APP_VERSION.removeprefix("v"),
                    "site_id": site.site_id,
                    "site_uuid": identity["site_uuid"],
                    "site_name": site.display_name,
                    "line_name": site.line_name,
                    "project_type": site.project_type,
                    "base_revision": identity["revision"],
                    "created_at": _now(),
                    "source_platform": "windows" if os.name == "nt" else os.name,
                    "databases": ["site/db/devices.db"],
                    "artifacts": [],
                    "required_files": list(_LIGHTWEIGHT_REQUIRED_FILES),
                    "components": components,
                    "component_paths": component_paths,
                    "checksums": manifest_files,
                    "contains_credentials": True,
                    "contains_sensitive_credentials": True,
                    "device_passwords_included": True,
                    "encrypted": False,
                }
                _atomic_json(root / "manifest.json", manifest)
                _atomic_json(root / "checksums.json", manifest_files)
                (root / "README.txt").write_text(
                    "NetConsole 轻量可恢复包；包含当前局点基础数据和设备凭据，不包含历史、原始文件、报告或运行时缓存。请妥善保管。\n",
                    encoding="utf-8",
                )
                with zipfile.ZipFile(
                    staging, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
                ) as archive:
                    for item in root.rglob("*"):
                        if item.is_file():
                            archive.write(item, item.relative_to(root).as_posix())
            self.inspect_package(staging, validate_extension=False)
            os.replace(staging, destination)
            return {
                "package_name": destination.name,
                "package_type": LIGHTWEIGHT,
                "site_uuid": identity["site_uuid"],
                "base_revision": identity["revision"],
                "size_bytes": destination.stat().st_size,
                "contains_credentials": True,
                "device_passwords_included": True,
                "encrypted": False,
            }
        finally:
            self.staging_lifecycle.finish_publish_path(staging, staging_journal)

    @staticmethod
    def _lightweight_component_path(
        root: Path,
        module_root: Path,
        expected_name: str,
    ) -> str:
        expected = module_root / expected_name
        if expected.is_file():
            return expected.relative_to(root).as_posix()
        status = module_root / "export-status.json"
        if status.is_file():
            return status.relative_to(root).as_posix()
        raise SiteStorageError(
            "SITE_EXPORT_FAILED",
            f"轻量包缺少 {module_root.name} 模块导出结果",
        )

    def _lightweight_export_device_csv(
        self,
        target: Path,
        site: SiteRecord,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> None:
        if check_cancel:
            check_cancel()
        from netconsole.services.export.common_exporters import export_device_csv

        try:
            export_device_csv(
                target,
                {
                    "db_path": str(self.paths.site_db_path(site.site_id)),
                    "site_name": site.site_id,
                    "omit_credentials": False,
                },
                should_cancel=_lightweight_should_cancel(check_cancel),
            )
        except BackgroundTaskCancelled:
            raise
        except Exception:
            self._write_lightweight_unavailable(target.parent, "设备清单导出暂不可用")

    def _lightweight_export_ac_csv(
        self,
        target: Path,
        site: SiteRecord,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> None:
        if check_cancel:
            check_cancel()
        try:
            from netconsole.core.database import Database
            from netconsole.repositories.ac_repository import AcRepository
            from netconsole.services.fit_ap_import_export import FitApImportExportService

            database = Database(self.paths.site_db_path(site.site_id))
            rows = AcRepository(database).list_all_fit_ap_resources_with_metadata()
            FitApImportExportService(AcRepository(database)).export_ap_csv(target, rows)
        except BackgroundTaskCancelled:
            raise
        except Exception:
            self._write_lightweight_unavailable(target.parent, "AC 资源导出暂不可用")

    def _lightweight_export_trackside(
        self,
        target: Path,
        site: SiteRecord,
        tmp_path: Path,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> None:
        if check_cancel:
            check_cancel()
        try:
            from netconsole.services.trackside_ap_export_service import (
                export_trackside_ap_business_prepare_and_render,
            )

            export_trackside_ap_business_prepare_and_render(
                database_path=self.paths.site_db_path(site.site_id),
                site_name=site.site_id,
                task_id=f"lightweight-{uuid.uuid4().hex}",
                snapshot_staging_root=self.paths.staging_dir,
                output_path=target,
                tmp_path=tmp_path,
                scope_context={
                    "site_id": site.site_id,
                    "display_name": site.display_name,
                    "line_name": site.line_name or "",
                    "project_type": site.project_type or "",
                },
                should_cancel=_lightweight_should_cancel(check_cancel),
            )
        except BackgroundTaskCancelled:
            raise
        except Exception:
            self._write_lightweight_unavailable(target.parent, "轨旁 AP 业务导出暂不可用")

    def _lightweight_export_base_data(
        self,
        target: Path,
        site: SiteRecord,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> None:
        if check_cancel:
            check_cancel()
        try:
            from netconsole.services.trackside_ap_base_export import (
                export_trackside_ap_base_xlsx_task,
            )

            export_trackside_ap_base_xlsx_task(
                target,
                {
                    "site_id": site.site_id,
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                },
                should_cancel=_lightweight_should_cancel(check_cancel),
            )
        except BackgroundTaskCancelled:
            raise
        except Exception:
            self._write_lightweight_unavailable(target.parent, "轨道交通基础资料导出暂不可用")

    @staticmethod
    def _write_lightweight_unavailable(directory: Path, message: str) -> None:
        _atomic_json(
            directory / "export-status.json",
            {"status": "unavailable", "message": message},
        )

    def inspect_package(
        self,
        package: Path,
        *,
        target_site_id: str | None = None,
        validate_extension: bool = True,
    ) -> dict[str, object]:
        package = Path(package).resolve()
        try:
            with zipfile.ZipFile(package) as archive:
                infos = archive.infolist()
                if len(infos) > _MAX_PACKAGE_FILES:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包文件数量超限"
                    )
                total = 0
                for info in infos:
                    _validate_archive_name(info.filename)
                    if _is_symlink(info):
                        raise SiteStorageError(
                            "SITE_IMPORT_INVALID_PACKAGE", "局点包不允许符号链接"
                        )
                    if info.file_size > _MAX_SINGLE_FILE_BYTES:
                        raise SiteStorageError(
                            "SITE_IMPORT_INVALID_PACKAGE", "局点包单文件过大"
                        )
                    total += info.file_size
                    if total > _MAX_PACKAGE_BYTES:
                        raise SiteStorageError(
                            "SITE_IMPORT_INVALID_PACKAGE", "局点包解压总大小超限"
                        )
                try:
                    manifest = json.loads(archive.read("manifest.json"))
                except (KeyError, json.JSONDecodeError) as exc:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包缺少有效 manifest"
                    ) from exc
                if not isinstance(manifest, dict):
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包 manifest 格式无效"
                    )
                if manifest.get("format") == "netconsole-lightweight-package":
                    return self._inspect_lightweight_package(
                        archive,
                        manifest,
                        infos,
                        total,
                        package,
                        validate_extension=validate_extension,
                    )
                try:
                    version = int(manifest.get("format_version") or 0)
                except (TypeError, ValueError) as exc:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包版本格式无效"
                    ) from exc
                if manifest.get("format") != PACKAGE_FORMAT or version not in {
                    1,
                    2,
                    PACKAGE_FORMAT_VERSION,
                }:
                    raise SiteStorageError(
                        "SITE_IMPORT_VERSION_UNSUPPORTED", "不支持的局点包版本"
                    )
                package_type = (
                    FULL_MIGRATION
                    if version == 1
                    else str(manifest.get("package_type") or "")
                )
                if package_type not in PACKAGE_TYPES:
                    raise SiteStorageError(
                        "SITE_IMPORT_VERSION_UNSUPPORTED", "数据包类型不受支持"
                    )
                expected_profile = package_profile_for_type(package_type)
                declared_profile = manifest.get("package_profile")
                if declared_profile is not None and str(declared_profile) != expected_profile:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包 profile 与类型不一致"
                    )
                expected_suffix = (
                    ".ncresult"
                    if package_type == COLLECTION_RETURN
                    else ".zip"
                    if package_type == LIGHTWEIGHT
                    else ".ncsite"
                )
                if validate_extension and package.suffix.casefold() != expected_suffix:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE",
                        f"{package_type} 数据包扩展名应为 {expected_suffix}",
                    )
                plain_full = (
                    package_type == FULL_MIGRATION
                    and version == PACKAGE_FORMAT_VERSION
                    and manifest.get("encrypted") is False
                    and manifest.get("contains_credentials") is True
                )
                plain_lightweight = (
                    package_type == LIGHTWEIGHT
                    and version == PACKAGE_FORMAT_VERSION
                    and manifest.get("package_profile")
                    == package_profile_for_type(LIGHTWEIGHT)
                    and manifest.get("encrypted") is False
                    and manifest.get("contains_credentials") is True
                    and manifest.get("device_passwords_included") is True
                )
                if (
                    version == PACKAGE_FORMAT_VERSION
                    and package_type == FULL_MIGRATION
                    and not plain_full
                ):
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE",
                        "v4 完整迁移包必须原样包含凭据且不得加密",
                    )
                if package_type == LIGHTWEIGHT and not plain_lightweight:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE",
                        "当前轻量包必须使用 v4 lightweight profile 并明确包含设备凭据",
                    )
                if not plain_full and not plain_lightweight:
                    if manifest.get("contains_credentials") is not False:
                        raise SiteStorageError(
                            "SITE_IMPORT_INVALID_PACKAGE",
                            "只有 v4 完整迁移包可以包含凭据",
                        )
                payload_summary = {
                    "file_count": len(infos),
                    "total_bytes": total,
                }
                checksums = manifest.get("checksums")
                if not isinstance(checksums, dict):
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包缺少 checksum"
                    )
                if package_type == LIGHTWEIGHT:
                    self._validate_current_lightweight_package(
                        archive,
                        manifest,
                        infos,
                        checksums,
                    )
                for name, expected in checksums.items():
                    _validate_archive_name(str(name))
                    try:
                        actual = hashlib.sha256(archive.read(str(name))).hexdigest()
                    except KeyError as exc:
                        raise SiteStorageError(
                            "SITE_IMPORT_CHECKSUM_FAILED", "局点包文件缺失"
                        ) from exc
                    if actual != str(expected):
                        raise SiteStorageError(
                            "SITE_IMPORT_CHECKSUM_FAILED", "局点包完整性校验失败"
                        )
                public = {
                    "site_id": str(manifest.get("site_id") or ""),
                    "site_uuid": str(manifest.get("site_uuid") or ""),
                    "site_name": str(manifest.get("site_name") or ""),
                    "line_name": _read_optional_site_info(
                        manifest.get("line_name")
                    ),
                    "project_type": _read_optional_site_info(
                        manifest.get("project_type")
                    ),
                    "package_type": package_type,
                    "package_id": str(manifest.get("package_id") or ""),
                    "base_revision": int(
                        manifest.get("base_revision")
                        or manifest.get("site_revision")
                        or 1
                    ),
                    "package_profile": str(
                        manifest.get("package_profile")
                        or package_profile_for_type(package_type)
                    ),
                    "file_count": int(payload_summary["file_count"]),
                    "contains_credentials": bool(plain_full or plain_lightweight),
                    "encrypted": False,
                    "credential_reentry_count": max(
                        0, int(manifest.get("credential_reentry_count") or 0)
                    ),
                    "conflict_count": 0,
                    "conflicts": [],
                    "invalid_count": 0,
                    "estimated_additional_bytes": int(payload_summary["total_bytes"]),
                    "can_import": True,
                }
                if package_type == COLLECTION_RETURN:
                    return {
                        **public,
                        **SiteSyncService(
                            self.paths, self.sites
                        ).inspect_return_package(
                            package,
                            manifest,
                            target_site_id=target_site_id,
                        ),
                    }
                return public
        except zipfile.BadZipFile as exc:
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "局点包不是有效 ZIP"
            ) from exc

    @staticmethod
    def _validate_current_lightweight_package(
        archive: zipfile.ZipFile,
        manifest: dict[str, object],
        infos: list[zipfile.ZipInfo],
        checksums: dict[object, object],
    ) -> None:
        names = {
            info.filename
            for info in infos
            if not info.is_dir()
        }
        required_files = manifest.get("required_files")
        if not isinstance(required_files, list) or {
            str(value) for value in required_files
        } != set(_LIGHTWEIGHT_REQUIRED_FILES):
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包缺少可恢复核心文件声明"
            )
        for required in _LIGHTWEIGHT_REQUIRED_FILES:
            if required not in names:
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "轻量包缺少可恢复核心文件"
                )

        structural = {"manifest.json", "checksums.json", "README.txt"}
        payload_names = names - structural
        allowed_prefixes = ("site/", *(_LIGHTWEIGHT_COMPONENT_PREFIXES.values()))
        for name in payload_names:
            if _LIGHTWEIGHT_FORBIDDEN_PARTS.intersection(
                part.casefold() for part in name.split("/")
            ):
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE",
                    "轻量包包含禁止的日志、历史或运行时数据",
                )
            if not name.startswith(allowed_prefixes):
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "轻量包包含未声明的文件"
                )

        component_paths = manifest.get("component_paths")
        if not isinstance(component_paths, dict) or set(component_paths) != set(
            _LIGHTWEIGHT_COMPONENTS
        ):
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包缺少完整业务模块声明"
            )
        if len({str(path) for path in component_paths.values()}) != len(
            _LIGHTWEIGHT_COMPONENTS
        ):
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包业务模块不能共用同一文件"
            )
        for component in _LIGHTWEIGHT_COMPONENTS:
            path = component_paths.get(component)
            prefix = _LIGHTWEIGHT_COMPONENT_PREFIXES[component]
            if not isinstance(path, str) or not path.startswith(prefix):
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "轻量包业务模块路径无效"
                )
            _validate_archive_name(path)
            if path not in payload_names:
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "轻量包业务模块文件缺失"
                )

        expected_payload_names = set(_LIGHTWEIGHT_REQUIRED_FILES) | {
            str(path) for path in component_paths.values()
        }
        if payload_names != expected_payload_names:
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包包含未声明的文件"
            )

        if set(str(name) for name in checksums) != payload_names:
            raise SiteStorageError(
                "SITE_IMPORT_CHECKSUM_FAILED", "轻量包 checksum 清单与内容不一致"
            )
        try:
            checksum_file = json.loads(archive.read("checksums.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包缺少有效 checksum 清单"
            ) from exc
        if checksum_file != checksums:
            raise SiteStorageError(
                "SITE_IMPORT_CHECKSUM_FAILED", "轻量包 checksum 清单不一致"
            )

    @staticmethod
    def _inspect_lightweight_package(
        archive: zipfile.ZipFile,
        manifest: dict[str, object],
        infos: list[zipfile.ZipInfo],
        total: int,
        package: Path,
        *,
        validate_extension: bool,
    ) -> dict[str, object]:
        package_type = str(manifest.get("package_type") or "")
        if package_type != LIGHTWEIGHT or (
            validate_extension and package.suffix.casefold() != ".zip"
        ):
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包类型或扩展名无效"
            )
        required_prefixes = (
            "device-management/",
            "ac-management/",
            "trackside-ap-business/",
            "rail-transit-base-data/",
        )
        names = {info.filename.rstrip("/") for info in infos}
        for prefix in required_prefixes:
            if not any(name.startswith(prefix) for name in names):
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "轻量包缺少业务模块导出"
                )
        forbidden_parts = {
            "logs",
            "history",
            "raw",
            "backup",
            "backups",
            "cache",
            "runtime",
            "credentials",
            "token",
        }
        for name in names:
            if name == "manifest.json":
                continue
            if forbidden_parts.intersection(part.casefold() for part in name.split("/")):
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "轻量包包含禁止的日志、历史或运行时数据"
                )
        checksums = manifest.get("checksums")
        if not isinstance(checksums, dict) or not checksums:
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包缺少 checksum"
            )
        for name, expected in checksums.items():
            _validate_archive_name(str(name))
            try:
                actual = hashlib.sha256(archive.read(str(name))).hexdigest()
            except KeyError as exc:
                raise SiteStorageError(
                    "SITE_IMPORT_CHECKSUM_FAILED", "轻量包文件缺失"
                ) from exc
            if actual != str(expected):
                raise SiteStorageError(
                    "SITE_IMPORT_CHECKSUM_FAILED", "轻量包完整性校验失败"
                )
        if manifest.get("contains_credentials") is not True or manifest.get("device_passwords_included") is not True:
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "轻量包必须明确标记设备连接凭据"
            )
        return {
            "site_id": str(manifest.get("site_id") or ""),
            "site_uuid": str(manifest.get("site_uuid") or ""),
            "site_name": str(manifest.get("site_name") or ""),
            "line_name": _read_optional_site_info(manifest.get("line_name")),
            "project_type": _read_optional_site_info(manifest.get("project_type")),
            "package_type": LIGHTWEIGHT,
            "package_id": str(manifest.get("package_id") or ""),
            "base_revision": int(manifest.get("base_revision") or 1),
            "file_count": len(infos),
            "contains_credentials": True,
            "device_passwords_included": True,
            "encrypted": False,
            "credential_reentry_count": 0,
            "conflict_count": 0,
            "conflicts": [],
            "invalid_count": 0,
            "estimated_additional_bytes": total,
            "can_import": False,
        }

    @_with_site_package_operation_lease
    def import_site(
        self,
        package: Path,
        *,
        site_id: str | None = None,
        display_name: str | None = None,
        replace_site_id: str | None = None,
        raw_only: bool = False,
        conflict_resolutions: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        info = self.inspect_package(
            package,
            target_site_id=site_id or replace_site_id,
        )
        if not bool(info.get("can_import")):
            raise SiteStorageError(
                "SITE_IMPORT_UNSUPPORTED", "该数据包仅支持检查，不能直接恢复为局点"
            )
        manifest = self._read_manifest(package)
        package_type = str(info.get("package_type") or FULL_MIGRATION)
        if package_type == COLLECTION_RETURN:
            return SiteSyncService(self.paths, self.sites).import_return_package(
                Path(package).resolve(),
                manifest,
                target_site_id=site_id or replace_site_id,
                raw_only=raw_only,
                conflict_resolutions=conflict_resolutions or [],
            )
        original_id = validate_site_id(str(info["site_id"]))
        wanted_id = validate_site_id(site_id or replace_site_id or original_id)
        name = validate_display_name(
            display_name or str(info["site_name"]) or wanted_id
        )
        registry_preimage = self.sites.registry.raw_record(wanted_id)
        replacement = (
            self.sites.registry.get(replace_site_id) if replace_site_id else None
        )
        target = (
            replacement.root_path
            if replacement is not None
            else self.paths.sites_dir / wanted_id
        )
        backup: Path | None = None
        replacement_journal: Path | None = None
        staging = self.paths.temp_dir / "site-import-staging" / uuid.uuid4().hex
        with storage_lock(self.paths, "site-import"):
            try:
                staging.mkdir(parents=True)
                _extract_outer_package(Path(package).resolve(), staging)
                imported_root = staging / "site"
                imported_database = imported_root / "db" / "devices.db"
                reentry_count = 0
                if imported_database.is_file():
                    connection = sqlite3.connect(imported_database)
                    try:
                        if bool(info.get("contains_credentials")):
                            repair_device_credential_states(connection)
                        else:
                            reentry_count = sanitize_device_credentials_for_package(
                                connection,
                                infer_missing=(
                                    "credential_reentry_count" not in manifest
                                    or int(
                                        manifest.get("credential_reentry_count") or 0
                                    )
                                    > 0
                                ),
                            )
                        connection.commit()
                    finally:
                        connection.close()
                    Database(imported_database).initialize()
                    connection = sqlite3.connect(imported_database)
                    try:
                        _rebind_device_group_scope(
                            connection,
                            target_scope=target.name,
                            manifest=manifest,
                        )
                        connection.commit()
                    finally:
                        connection.close()
                    ApIdentityQueryService(Database(imported_database)).rebuild_index(
                        "site_package_import_staging"
                    )
                    # Legacy repository context managers finish transactions but
                    # can leave unreachable SQLite handles in a reference cycle.
                    # Release them before Windows atomically publishes staging.
                    gc.collect()
                _quick_check_site(imported_root)
                _finalize_site_databases(imported_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if replace_site_id is None:
                        raise SiteStorageError("SITE_IMPORT_CONFLICT", "目标局点已存在")
                    backup = (
                        self.paths.archive_dir
                        / f"site-import-{target.name}-{uuid.uuid4().hex}"
                    )
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    replacement_journal = (
                        self.staging_lifecycle.begin_site_replacement(
                            target, backup
                        )
                    )
                    _finalize_site_databases(target)
                    _publish_directory(target, backup)
                    self.staging_lifecycle.mark_site_replacement(
                        replacement_journal, "BACKUP_PUBLISHED"
                    )
                    _remove_directory_after_backup(target)
                else:
                    replacement_journal = (
                        self.staging_lifecycle.begin_site_replacement(target, None)
                    )
                _publish_directory(imported_root, target)
                if replacement_journal is not None:
                    self.staging_lifecycle.mark_site_replacement(
                        replacement_journal, "TARGET_PUBLISHED"
                    )
                imported_metadata = self.sites.manager.load_site_metadata(target.name)
                line_name = normalize_optional_site_info(
                    manifest.get("line_name")
                    if "line_name" in manifest
                    else imported_metadata.get("line_name"),
                    field_name="线路名称",
                )
                project_type = normalize_optional_site_info(
                    manifest.get("project_type")
                    if "project_type" in manifest
                    else imported_metadata.get("system_type"),
                    field_name="项目类型",
                )
                self.sites.manager.save_site_metadata(
                    target.name,
                    {
                        "display_name": name,
                        "line_name": line_name or "",
                        "system_type": project_type or "",
                    },
                )
                if package_type == FIELD_COLLECTION:
                    SiteSyncService(self.paths, self.sites).record_field_baseline(
                        target, manifest
                    )
                registry_expected: dict[str, object] = {
                    "site_id": wanted_id,
                    "display_name": name,
                    "relative_path": target.resolve()
                    .relative_to(self.paths.data_root.resolve())
                    .as_posix(),
                    "remark": "imported",
                }
                if line_name is not None:
                    registry_expected["line_name"] = line_name
                if project_type is not None:
                    registry_expected["project_type"] = project_type
                if replacement_journal is not None:
                    self.staging_lifecycle.bind_site_replacement_registry(
                        replacement_journal,
                        site_id=wanted_id,
                        preimage=registry_preimage,
                        expected=registry_expected,
                    )
                self.sites.registry.register(
                    SiteRecord(
                        wanted_id,
                        name,
                        target,
                        remark="imported",
                        line_name=line_name,
                        project_type=project_type,
                    )
                )
                if replacement_journal is not None:
                    self.staging_lifecycle.mark_site_replacement(
                        replacement_journal, "APPLICATION_COMMITTED"
                    )
                self.staging_lifecycle.finish_site_replacement(
                    replacement_journal
                )
                return self._site_import_result(
                    wanted_id,
                    name,
                    package_type,
                    backup is not None,
                    reentry_count,
                )
            except SiteStorageError:
                if replacement_journal is not None and replacement_journal.exists():
                    self.staging_lifecycle.promote_persisted_registry_commit(
                        replacement_journal
                    )
                    outcome = self.staging_lifecycle.reconcile_site_replacement(
                        replacement_journal
                    )
                    if outcome == "COMMITTED":
                        return self._site_import_result(
                            wanted_id,
                            name,
                            package_type,
                            backup is not None,
                            reentry_count,
                        )
                _remove_temporary_directory(staging)
                raise
            except Exception as exc:
                _remove_temporary_directory(staging)
                if replacement_journal is not None and replacement_journal.exists():
                    self.staging_lifecycle.promote_persisted_registry_commit(
                        replacement_journal
                    )
                    outcome = self.staging_lifecycle.reconcile_site_replacement(
                        replacement_journal
                    )
                    if outcome == "COMMITTED":
                        return self._site_import_result(
                            wanted_id,
                            name,
                            package_type,
                            backup is not None,
                            reentry_count,
                        )
                raise SiteStorageError(
                    "SITE_IMPORT_FAILED", "局点导入失败，已保留原数据"
                ) from exc
            finally:
                _remove_temporary_directory(staging)

    def _site_import_result(
        self,
        site_id: str,
        display_name: str,
        package_type: str,
        backup_created: bool,
        reentry_count: int,
    ) -> dict[str, object]:
        """在导入任务完成前确认 Registry 已刷新且目标可切换。"""

        self.sites.registry.refresh()
        record = self.sites.registry.get(site_id)
        switchable = record.root_path.is_dir() and (
            record.root_path / "db" / "devices.db"
        ).is_file()
        if not switchable:
            raise SiteStorageError(
                "SITE_IMPORT_RUNTIME_REFRESH_FAILED",
                "局点已写入，但运行时 Registry 刷新后目标不可切换",
            )
        return {
            "site_id": site_id,
            "display_name": display_name,
            "package_type": package_type,
            "backup_created": backup_created,
            "requires_credentials": reentry_count > 0,
            "credential_reentry_count": reentry_count,
            "site_registry_refreshed": True,
            "site_switchable": True,
            "registry_revision": self.sites.registry.revision(),
        }

    @staticmethod
    def _read_manifest(package: Path) -> dict[str, object]:
        try:
            with zipfile.ZipFile(Path(package).resolve()) as archive:
                value = json.loads(archive.read("manifest.json"))
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "数据包缺少有效 manifest"
            ) from exc
        if not isinstance(value, dict):
            raise SiteStorageError(
                "SITE_IMPORT_INVALID_PACKAGE", "数据包 manifest 格式无效"
            )
        return value


def _default_data_root(paths: PathResolver) -> Path:
    from netconsole.core.runtime_environment import data_root

    return data_root()


def _write_migration_operation(
    staging: Path, status: str, source: Path, destination: Path
) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    common = {"schema_version": 1, "updated_at": _now()}
    _atomic_json(
        staging / "manifest.json",
        {**common, "operation_id": staging.name, "status": status},
    )
    _atomic_json(staging / "source.json", {**common, "data_root": str(source)})
    _atomic_json(staging / "target.json", {**common, "data_root": str(destination)})
    _atomic_json(staging / "status.json", {**common, "status": status})
    lock_path = staging / "operation.lock"
    if not lock_path.exists():
        lock_path.write_text(str(os.getpid()), encoding="ascii")


def _publish_directory(source: Path, destination: Path) -> None:
    """Windows 不允许 os.replace 目录时，使用同卷 rename，再退回 move。"""
    try:
        os.replace(source, destination)
        return
    except (OSError, PermissionError):
        pass
    try:
        os.rename(source, destination)
        return
    except (OSError, PermissionError):
        pass
    if destination.exists():
        raise SiteStorageError("SITE_STORAGE_UNAVAILABLE", "目标目录无法原子发布")
    # Windows may keep a SQLite WAL handle open briefly. Registry publication
    # still happens only after the complete copy; the staging cleanup is best effort.
    shutil.copytree(source, destination, copy_function=shutil.copyfile)
    shutil.rmtree(source, ignore_errors=True)


def _remove_directory_after_backup(path: Path) -> None:
    for _attempt in range(20):
        if not path.exists():
            return
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.05)
    raise SiteStorageError(
        "SITE_STORAGE_UNAVAILABLE",
        "原局点已完成备份，但目录仍被占用，未发布导入数据",
    )


def _remove_temporary_directory(path: Path) -> None:
    for _attempt in range(20):
        if not path.exists():
            return
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.05)


def _publish_data_root(source: Path, destination: Path) -> None:
    """Publish a complete data root by same-volume rename only.

    The caller creates `<data-root>.staging-<id>` beside the selected root, so
    no partially copied tree can become the configured root.  A fallback copy
    would violate that invariant and is intentionally refused.
    """

    last_error: OSError | None = None
    for _attempt in range(20):
        for publish in (os.replace, os.rename):
            try:
                publish(source, destination)
                return
            except (OSError, PermissionError) as exc:
                last_error = exc
        # SQLite connections opened for the final integrity check can retain a
        # Windows directory handle briefly after close.  Retrying preserves the
        # atomic same-volume publish invariant without falling back to copying.
        time.sleep(0.05)
    raise SiteStorageError(
        "DATA_ROOT_MIGRATION_FAILED", "无法原子发布新的数据根"
    ) from last_error


def _rewrite_migrated_storage_manifest(payload: Path, destination: Path) -> None:
    """Keep the copied manifest bound to the root that will be published.

    Updating the manifest while it is still in sibling staging prevents a
    successfully published migration from being rejected on its first startup
    because it still names the source root.
    """

    manifest_path = payload / "config" / "storage-manifest.json"
    if not manifest_path.is_file():
        return
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("manifest must be an object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SiteStorageError(
            "DATA_ROOT_MIGRATION_FAILED", "storage-manifest.json 无效，无法迁移"
        ) from exc
    value["data_root"] = str(destination)
    _atomic_json(manifest_path, value)


def _directory_size(root: Path) -> int:
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _quick_check_site(root: Path) -> None:
    for database in _site_database_paths(root):
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database)
            result = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise SiteStorageError(
                "SITE_MIGRATION_FAILED", "SQLite 完整性检查失败"
            ) from exc
        finally:
            if connection is not None:
                connection.close()
        if not result or str(result[0]).lower() != "ok":
            raise SiteStorageError("SITE_MIGRATION_FAILED", "SQLite 完整性检查失败")


def _quick_check_site_tree(root: Path) -> None:
    if root.exists():
        _quick_check_site(root)


def _finalize_site_databases(root: Path) -> None:
    """Checkpoint WAL files before a Windows directory publish."""
    for database in _site_database_paths(root):
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database, timeout=5)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.DatabaseError:
            continue
        finally:
            if connection is not None:
                connection.close()
        for suffix in ("-wal", "-shm"):
            try:
                (database.parent / f"{database.name}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
    time.sleep(0.02)


def _site_database_paths(root: Path) -> Iterator[Path]:
    for item in root.rglob("*"):
        if item.is_file() and is_sqlite_database_path(item):
            yield item


def _safe_site_files(
    root: Path,
    *,
    include_full_sync_authority: bool = False,
) -> Iterator[Path]:
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        relative_path = item.relative_to(root)
        relative_parts = {part.casefold() for part in relative_path.parts}
        sensitive_parts = relative_parts & _SENSITIVE_PARTS
        if include_full_sync_authority and _is_full_migration_sync_authority(
            relative_path
        ):
            sensitive_parts.discard("sync")
        if (
            sensitive_parts
            or item.name.endswith((".tmp", ".lock", ".part", "-wal", "-shm"))
            or ".db-" in item.name
            or _is_excluded_online_mr_package_file(relative_path)
        ):
            continue
        yield item


def _is_full_migration_sync_authority(relative_path: Path) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    return parts == ("sync", "wps_sync.sqlite") or (
        len(parts) >= 3
        and parts[:2] in {
            ("sync", "baselines"),
            ("sync", "imports"),
        }
    )


def _is_excluded_online_mr_package_file(relative_path: Path) -> bool:
    parts = tuple(part.casefold() for part in relative_path.parts)
    if (
        len(parts) < 7
        or parts[:3] != ("files", "rail_transit", "online_mr")
        or parts[4] != "sessions"
    ):
        return False
    session_relative = parts[6:]
    return (
        session_relative[:1] == ("view",)
        or session_relative == ("parsed", "online_diagnosis.sqlite.upgrading")
        or session_relative == ("parsed", "online_diagnosis.upgrade.json")
        or session_relative
        == ("parsed", "retired", "online_diagnosis.previous.sqlite")
    )


def _copy_sanitized_database(source: Path, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        count = sanitize_device_credentials_for_package(target_connection)
        target_connection.commit()
        return count
    finally:
        target_connection.close()
        source_connection.close()


def _device_group_contract(database: Path) -> dict[str, object]:
    if not database.is_file():
        return {
            "schema_version": 1,
            "scope_ids": [],
            "group_count": 0,
            "grouped_device_count": 0,
            "orphan_group_reference_count": 0,
            "definitions_sha256": _relation_digest([]),
            "membership_sha256": _relation_digest([]),
        }
    connection = sqlite3.connect(database)
    try:
        connection.row_factory = sqlite3.Row
        return _device_group_contract_from_connection(connection)
    finally:
        connection.close()


def _device_group_contract_from_connection(
    connection: sqlite3.Connection,
) -> dict[str, object]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if not {"devices", "device_groups"} <= tables:
        return {
            "schema_version": 1,
            "scope_ids": [],
            "group_count": 0,
            "grouped_device_count": 0,
            "orphan_group_reference_count": 0,
            "definitions_sha256": _relation_digest([]),
            "membership_sha256": _relation_digest([]),
        }
    group_rows = connection.execute(
        "SELECT id, site_id, name, sort_order, created_at, updated_at "
        "FROM device_groups ORDER BY id"
    ).fetchall()
    membership_rows = connection.execute(
        "SELECT device_uuid, group_id FROM devices "
        "WHERE group_id IS NOT NULL ORDER BY device_uuid"
    ).fetchall()
    orphan_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM devices d LEFT JOIN device_groups g ON g.id=d.group_id "
            "WHERE d.group_id IS NOT NULL AND g.id IS NULL"
        ).fetchone()[0]
    )
    definitions = [
        [
            int(row["id"]),
            str(row["name"] or ""),
            int(row["sort_order"] or 0),
            str(row["created_at"] or ""),
            str(row["updated_at"] or ""),
        ]
        for row in group_rows
    ]
    memberships = [
        [str(row["device_uuid"] or ""), int(row["group_id"])]
        for row in membership_rows
    ]
    return {
        "schema_version": 1,
        "scope_ids": sorted(
            {
                str(row["site_id"] or "")
                for row in group_rows
            }
        ),
        "group_count": len(group_rows),
        "grouped_device_count": len(membership_rows),
        "orphan_group_reference_count": orphan_count,
        "definitions_sha256": _relation_digest(definitions),
        "membership_sha256": _relation_digest(memberships),
    }


def _relation_digest(rows: list[object]) -> str:
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rebind_device_group_scope(
    connection: sqlite3.Connection,
    *,
    target_scope: str,
    manifest: dict[str, object],
) -> dict[str, object]:
    connection.row_factory = sqlite3.Row
    before = _device_group_contract_from_connection(connection)
    relation_summary = manifest.get("relation_summary")
    has_site_scope = "site_scope" in manifest
    has_relation_summary = "relation_summary" in manifest
    if has_site_scope != has_relation_summary:
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_MANIFEST_INVALID",
            "局点包中的来源作用域与关系摘要必须同时存在",
            details={"relation": "device_groups"},
        )
    if relation_summary is not None and not isinstance(relation_summary, dict):
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_MANIFEST_INVALID",
            "局点包中的关系摘要格式无效",
            details={"relation": "device_groups", "field": "relation_summary"},
        )
    expected_value = (
        relation_summary.get("device_groups")
        if isinstance(relation_summary, dict)
        else None
    )
    if has_relation_summary and expected_value is None:
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_MANIFEST_INVALID",
            "局点包缺少设备分组关系摘要",
            details={"relation": "device_groups", "field": "device_groups"},
        )
    if expected_value is not None and not isinstance(expected_value, dict):
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_MANIFEST_INVALID",
            "局点包中的设备分组关系摘要格式无效",
            details={"relation": "device_groups", "field": "device_groups"},
        )
    expected = dict(expected_value or {})
    if expected:
        if not (
            type(expected.get("schema_version")) is int
            and expected["schema_version"] == 1
        ):
            raise SiteStorageError(
                "SITE_IMPORT_RELATION_SCHEMA_UNSUPPORTED",
                "局点包中的设备分组关系版本不受支持",
                details={
                    "relation": "device_groups",
                    "schema_version": expected.get("schema_version"),
                },
            )
        if not (
            isinstance(expected.get("scope_ids"), list)
            and all(isinstance(value, str) for value in expected["scope_ids"])
            and all(
                type(expected.get(field)) is int
                and int(expected[field]) >= 0
                for field in (
                    "group_count",
                    "grouped_device_count",
                    "orphan_group_reference_count",
                )
            )
            and all(
                isinstance(expected.get(field), str)
                and re.fullmatch(r"[0-9a-f]{64}", str(expected[field])) is not None
                for field in ("definitions_sha256", "membership_sha256")
            )
        ):
            raise SiteStorageError(
                "SITE_IMPORT_RELATION_MANIFEST_INVALID",
                "局点包中的设备分组关系摘要字段无效",
                details={"relation": "device_groups"},
            )
        for field in (
            "scope_ids",
            "group_count",
            "grouped_device_count",
            "orphan_group_reference_count",
            "definitions_sha256",
            "membership_sha256",
        ):
            if before.get(field) != expected.get(field):
                raise SiteStorageError(
                    "SITE_IMPORT_RELATION_MISMATCH",
                    "局点包中的设备分组关系与 manifest 不一致",
                    details={"relation": "device_groups", "field": field},
                )
    site_scope = manifest.get("site_scope")
    if site_scope is not None:
        if not (
            isinstance(site_scope, dict)
            and type(site_scope.get("schema_version")) is int
            and site_scope["schema_version"] == 1
        ):
            raise SiteStorageError(
                "SITE_IMPORT_SITE_SCOPE_UNSUPPORTED",
                "局点包中的来源作用域版本不受支持",
                details={"field": "site_scope"},
            )
        source_scope = site_scope.get("source_directory_name")
        if not isinstance(source_scope, str) or not source_scope:
            raise SiteStorageError(
                "SITE_IMPORT_SITE_SCOPE_INVALID",
                "局点包中的来源物理目录名无效",
                details={"field": "source_directory_name"},
            )
        before_scope_ids = [str(value) for value in before["scope_ids"]]
        if (
            len(before_scope_ids) == 1
            and before_scope_ids[0]
            and before_scope_ids[0] != source_scope
        ):
            raise SiteStorageError(
                "SITE_IMPORT_SITE_SCOPE_MISMATCH",
                "设备分组作用域与局点包来源物理目录不一致",
                details={
                    "source_directory_name": source_scope,
                    "group_scope": before_scope_ids[0],
                },
            )
    if int(before["orphan_group_reference_count"]) > 0:
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_INVALID",
            "局点包存在找不到分组定义的设备关系，已停止导入",
            details={
                "relation": "device_groups",
                "orphan_count": int(before["orphan_group_reference_count"]),
            },
        )
    scope_ids = [str(value) for value in before["scope_ids"]]
    if len(scope_ids) > 1:
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_SCOPE_CONFLICT",
            "局点包包含多个设备分组作用域，无法安全重绑定",
            details={"relation": "device_groups", "scope_ids": scope_ids},
        )
    if scope_ids and scope_ids[0] != target_scope:
        connection.execute(
            "UPDATE device_groups SET site_id=? WHERE COALESCE(site_id, '')=?",
            (target_scope, scope_ids[0]),
        )
    after = _device_group_contract_from_connection(connection)
    for field in (
        "group_count",
        "grouped_device_count",
        "orphan_group_reference_count",
        "definitions_sha256",
        "membership_sha256",
    ):
        if before[field] != after[field]:
            raise SiteStorageError(
                "SITE_IMPORT_RELATION_REBIND_FAILED",
                "设备分组作用域重绑定未通过无损校验",
                details={"relation": "device_groups", "field": field},
            )
    if int(after["group_count"]) and after["scope_ids"] != [target_scope]:
        raise SiteStorageError(
            "SITE_IMPORT_RELATION_REBIND_FAILED",
            "设备分组作用域未绑定到目标局点",
            details={"relation": "device_groups"},
        )
    return after


def _copy_database_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()


def _extract_outer_package(package: Path, target: Path) -> None:
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            name = _validate_archive_name(info.filename)
            destination = (target / name).resolve()
            if not _relative_inside(target, destination):
                raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包路径越界")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)


def _copy_tree_snapshot(
    source: Path, destination: Path, *, check_cancel: Callable[[], None] | None = None
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if check_cancel:
            check_cancel()
        relative = item.relative_to(source)
        if any(
            part.casefold() in {"cache", "locks", "temp"} for part in relative.parts
        ):
            continue
        if (
            item.name.endswith((".tmp", ".lock", ".part", "-wal", "-shm"))
            or ".db-" in item.name
        ):
            continue
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            target.parent.mkdir(parents=True, exist_ok=True)
            source_connection = sqlite3.connect(
                f"{item.resolve().as_uri()}?mode=ro", uri=True, timeout=30
            )
            target_connection = sqlite3.connect(target)
            try:
                source_connection.backup(target_connection)
            finally:
                target_connection.close()
                source_connection.close()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_archive_name(value: str) -> str:
    name = str(value or "")
    normalized = name.replace("\\", "/")
    directory_entry = normalized.endswith("/")
    logical_name = normalized.rstrip("/") if directory_entry else normalized
    path = Path(logical_name)
    if (
        not logical_name
        or logical_name.startswith("/")
        or re.match(r"^[A-Za-z]:", logical_name)
        or logical_name.startswith("//")
        or any(part in {"", ".", ".."} for part in logical_name.split("/"))
        or path.is_absolute()
    ):
        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包包含不安全路径")
    return f"{logical_name}/" if directory_entry else logical_name


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


__all__ = [
    "DataRootApplicationService",
    "DataRootSnapshot",
    "SiteApplicationService",
    "SitePackageService",
    "SiteRecord",
    "SiteRegistryRepository",
    "SiteStorageError",
    "storage_lock",
    "validate_display_name",
    "validate_site_id",
]
