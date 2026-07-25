from __future__ import annotations

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
from pathlib import Path
from threading import RLock
from typing import BinaryIO, Callable, Iterator

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.device_credential_store import (
    DEVICE_SECRET_FIELDS,
    DEVICE_SECRET_STORAGE_FIELDS,
    ensure_device_credential_schema,
    read_device_credential_states,
    replace_device_credential_state,
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
from netconsole.services.site_sync import (
    COLLECTION_RETURN,
    FIELD_COLLECTION,
    FULL_MIGRATION,
    PACKAGE_FORMAT_VERSION,
    PACKAGE_TYPES,
    SANITIZED_SHARE,
    SiteSyncService,
)
from netconsole.services.site_package_crypto import (
    SitePackageCryptoError,
    decrypt_stream,
    encrypt_file,
    new_encryption_metadata,
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

    def to_public(self, *, include_path: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "site_id": self.site_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "remark": self.remark,
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
            "default_data_root": str(self.default_data_root) if self.persistent else "<unavailable>",
            "site_count": self.site_count,
            "active_site_id": self.active_site_id,
            "storage_mode": self.storage_mode,
            "data_root_kind": self.data_root_kind,
            "persistent": self.persistent,
        }


_REGISTRY_NAME = "site_registry.json"
_BOOTSTRAP_NAME = "bootstrap.json"
_INVALID_NAME_RE = re.compile(r'[<>:"/\\|?*]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_SITE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
_SENSITIVE_PARTS = {"token", "password", "passwd", "secret", "credentials", "bootstrap", "locks", "cache", "sync", "temp"}
_MAX_PACKAGE_FILES = 50_000
_MAX_PACKAGE_BYTES = 20 * 1024 * 1024 * 1024
_MAX_SINGLE_FILE_BYTES = 4 * 1024 * 1024 * 1024
_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
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
        raise SiteStorageError("SITE_ID_INVALID", "局点标识只能包含小写字母、数字、短横线和下划线")
    return site_id


def validate_display_name(value: str) -> str:
    raw = str(value or "")
    if raw != raw.strip() or raw.endswith((".", " ")):
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能以空格或点结尾")
    name = raw.strip()
    if not name or name in {".", ".."} or _INVALID_NAME_RE.search(name) or any(ord(c) < 32 for c in name):
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称包含 Windows 不允许的字符")
    if name.split(".", 1)[0].upper() in _RESERVED_NAMES:
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能使用 Windows 保留名称")
    if len(name) > 128:
        raise SiteStorageError("SITE_NAME_INVALID", "局点名称不能超过 128 个字符")
    return name


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


class SiteRegistryRepository:
    """全局唯一的局点 Registry；历史目录会被惰性补录。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.path = paths.config_dir / _REGISTRY_NAME

    def list(self) -> list[SiteRecord]:
        raw = self._load()
        records: dict[str, SiteRecord] = {}
        for item in raw.get("sites", []):
            if not isinstance(item, dict):
                continue
            try:
                site_id = validate_site_id(str(item.get("site_id") or ""))
                root = self._resolve_root(str(item.get("relative_path") or f"sites/{site_id}"))
                if root.is_dir():
                    records[site_id] = SiteRecord(
                        site_id=site_id,
                        display_name=validate_display_name(str(item.get("display_name") or site_id)),
                        root_path=root,
                        created_at=str(item.get("created_at") or ""),
                        updated_at=str(item.get("updated_at") or ""),
                        remark=str(item.get("remark") or ""),
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
                metadata = SiteManager(self.paths).load_site_metadata(root.name)
                display_name = self._legacy_display_name(root.name, metadata, used_names)
            except SiteStorageError:
                continue
            if any(item.root_path.resolve() == resolved_root for item in records.values()):
                continue
            records[site_id] = SiteRecord(
                site_id=site_id,
                display_name=display_name,
                root_path=resolved_root,
                created_at=str(metadata.get("created_at") or ""),
                updated_at=str(metadata.get("updated_at") or ""),
                remark=str(metadata.get("remark") or ""),
            )
            used_names.add(display_name.casefold())
            discovered = True
        if discovered and self._can_persist_discovery():
            now = _now()
            _atomic_json(self.path, {
                "schema_version": 1,
                "updated_at": now,
                "sites": [self._serialize(item) for item in records.values()],
            })
        return sorted(records.values(), key=lambda item: (item.site_id != DEFAULT_SITE, item.display_name.casefold()))

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
        if site_id in records and records[site_id].root_path.resolve() != record.root_path.resolve():
            raise SiteStorageError("SITE_ALREADY_EXISTS", "局点标识已存在")
        for item in records.values():
            if item.site_id != site_id and item.display_name.casefold() == display_name.casefold():
                raise SiteStorageError("SITE_ALREADY_EXISTS", "局点名称已存在")
        now = _now()
        value = SiteRecord(site_id, display_name, record.root_path.resolve(), record.created_at or now, now, record.remark)
        records[site_id] = value
        _atomic_json(self.path, {"schema_version": 1, "updated_at": now, "sites": [self._serialize(item) for item in records.values()]})
        return value

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
            resolved = self._resolve_root(str(item.get("relative_path") or f"sites/{wanted}"))
            if resolved != expected:
                raise SiteStorageError("SITE_REGISTRY_CONFLICT", "Registry 局点路径与清理目标不一致")
            removed = True
        if not removed:
            raise SiteStorageError("SITE_NOT_FOUND", "局点不存在")
        _atomic_json(self.path, {"schema_version": 1, "updated_at": _now(), "sites": retained})

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

    def _legacy_site_id(self, directory_name: str, records: dict[str, SiteRecord]) -> str:
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
    def _legacy_display_name(directory_name: str, metadata: dict[str, object], used_names: set[str]) -> str:
        candidate = str(metadata.get("display_name") or directory_name)
        try:
            display_name = validate_display_name(candidate)
        except SiteStorageError:
            display_name = validate_display_name(directory_name)
        if display_name.casefold() not in used_names:
            return display_name
        suffix = f"（{directory_name}）"
        return validate_display_name(f"{display_name[: max(1, 128 - len(suffix))]}{suffix}")

    def _serialize(self, item: SiteRecord) -> dict[str, object]:
        try:
            relative = item.root_path.resolve().relative_to(self.paths.data_root.resolve()).as_posix()
        except ValueError as exc:
            raise SiteStorageError("SITE_REGISTRY_CONFLICT", "局点必须位于当前数据根内") from exc
        return {
            "site_id": item.site_id,
            "display_name": item.display_name,
            "relative_path": relative,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "remark": item.remark,
        }

    def _resolve_root(self, relative: str) -> Path:
        candidate = (self.paths.data_root / relative).resolve()
        if not _relative_inside(self.paths.data_root, candidate) or candidate == self.paths.data_root:
            raise SiteStorageError("SITE_REGISTRY_CONFLICT", "Registry 局点路径越界")
        return candidate


class SiteApplicationService:
    def __init__(self, paths: PathResolver, task_service: object | None = None) -> None:
        self.paths = paths
        self.registry = SiteRegistryRepository(paths)
        self.manager = SiteManager(paths)
        self.task_service = task_service

    def list_sites(self) -> list[dict[str, object]]:
        active = self.active_site_id()
        from netconsole.services.site_lifecycle import SiteAuditService

        latest = SiteAuditService(self.paths).latest() or {}
        audits = {str(item.get("site_id") or ""): item for item in latest.get("sites", []) if isinstance(item, dict)}
        return [
            {
                **item.to_public(include_path=persistent_storage()),
                "active": item.site_id == active,
                "size_bytes": _directory_size(item.root_path),
                **self._lifecycle_summary(item, audits.get(item.site_id), str(latest.get("generated_at") or "")),
            }
            for item in self.registry.list()
        ]

    def get_site(self, site_id: str) -> dict[str, object]:
        item = self.registry.get(site_id)
        from netconsole.services.site_lifecycle import SiteAuditService

        latest = SiteAuditService(self.paths).latest() or {}
        audit = next((value for value in latest.get("sites", []) if isinstance(value, dict) and value.get("site_id") == item.site_id), None)
        return {
            **item.to_public(include_path=persistent_storage()),
            "active": item.site_id == self.active_site_id(),
            "size_bytes": _directory_size(item.root_path),
            **self._lifecycle_summary(item, audit, str(latest.get("generated_at") or "")),
        }

    def _lifecycle_summary(self, item: SiteRecord, audit: dict[str, object] | None, audited_at: str) -> dict[str, object]:
        metadata = self.manager.load_site_metadata(item.root_path.name)
        managed_demo = bool(metadata.get("managed_demo") is True)
        if audit:
            database_files = audit.get("database_files") or []
            integrity = "ok" if database_files and all(value.get("quick_check") == "ok" for value in database_files if isinstance(value, dict)) else "unknown"
            classification = str(audit.get("classification") or "unknown")
            migration_status = str(audit.get("migration_status") or "unknown")
            recommended_action = str(audit.get("recommended_action") or "keep_and_review")
        else:
            integrity = "unknown"
            classification = "managed_demo" if managed_demo else "legacy_demo" if item.site_id == DEFAULT_SITE else "legacy_valid" if item.site_id.startswith("legacy-") else "normal_site"
            migration_status = str(metadata.get("migration_status") or ("managed" if managed_demo else "not_audited"))
            recommended_action = "audit_required"
        return {
            "site_kind": "demo" if item.site_id == DEFAULT_SITE else "legacy" if item.site_id.startswith("legacy-") else "formal",
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

    def create_site(self, site_id: str, display_name: str, *, remark: str = "", activate: bool = False) -> dict[str, object]:
        site_id = validate_site_id(site_id)
        display_name = validate_display_name(display_name)
        with storage_lock(self.paths, "site-mutation"):
            if any(item.site_id == site_id for item in self.registry.list()):
                raise SiteStorageError("SITE_ALREADY_EXISTS", "局点标识已存在")
            if any(item.display_name.casefold() == display_name.casefold() for item in self.registry.list()):
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
                record = self.registry.register(SiteRecord(site_id, display_name, final, remark=remark))
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
                return {**record.to_public(), "active": True, "previous_site_id": previous, "restart_required": True}
            except Exception as exc:
                try:
                    self.manager.switch_site(previous_directory)
                except Exception:
                    pass
                app_logger.log_error(
                    "SITE_SWITCH_FAILED",
                    f"stage=activate previous_site_id={previous} target_site_id={site_id} error_type={exc.__class__.__name__}",
                )
                raise SiteStorageError("SITE_SWITCH_BLOCKED", "局点切换失败，已恢复原局点") from exc

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
        }

    def migrate_site(self, site_id: str, destination_root: Path, *, check_cancel: Callable[[], None] | None = None) -> dict[str, object]:
        """把单个局点复制到另一个受控数据根；源目录始终保留。"""
        record = self.registry.get(site_id)
        destination_root = Path(destination_root).expanduser().resolve()
        if destination_root == self.paths.data_root.resolve():
            raise SiteStorageError("SITE_MIGRATION_CONFLICT", "目标数据根与当前数据根相同")
        if _relative_inside(self.paths.data_root, destination_root) or _relative_inside(destination_root, self.paths.data_root):
            raise SiteStorageError("DATA_ROOT_NESTED_PATH", "单局点迁移目标不能与当前数据根嵌套")
        destination = destination_root / "data" / "sites" / record.site_id
        staging = destination_root / "temp" / "site-migration" / uuid.uuid4().hex
        with storage_lock(self.paths, "site-migration"):
            try:
                if self.task_service is not None:
                    self._ensure_no_active_tasks(record.site_id)
                staging.mkdir(parents=True, exist_ok=True)
                if check_cancel:
                    check_cancel()
                _copy_tree_snapshot(record.root_path, staging, check_cancel=check_cancel)
                _quick_check_site(staging)
                if destination.exists():
                    raise SiteStorageError("SITE_MIGRATION_CONFLICT", "目标局点已存在")
                destination.parent.mkdir(parents=True, exist_ok=True)
                _publish_directory(staging, destination)
                return {"site_id": record.site_id, "destination_root": str(destination_root), "old_data_retained": True, "restart_required": True}
            except SiteStorageError:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise SiteStorageError("SITE_MIGRATION_FAILED", "单局点迁移失败，源数据未改变") from exc

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
        list_blocking = getattr(service, "list_site_blocking_tasks", None)
        if callable(list_blocking):
            snapshots, reconciled = list_blocking(directory_name)
        else:
            repository = getattr(service, "repository", lambda _site: None)(directory_name)
            if repository is None:
                return []
            snapshots = repository.list(
                statuses={TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING},
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
    def __init__(self, paths: PathResolver, sites: SiteApplicationService | None = None) -> None:
        self.paths = paths
        self.sites = sites or SiteApplicationService(paths)

    def snapshot(self) -> DataRootSnapshot:
        from netconsole.core.runtime_environment import desktop_storage_mode, persistent_storage

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
        return {"valid": True, "path": str(candidate), "free_bytes": shutil.disk_usage(candidate if candidate.exists() else candidate.parent).free}

    def migrate(self, target: Path, *, check_cancel: Callable[[], None] | None = None) -> dict[str, object]:
        destination = self._validate_target(target)
        if destination == self.paths.data_root.resolve():
            raise SiteStorageError("DATA_ROOT_INVALID", "目标数据根与当前路径相同")
        with storage_lock(self.paths, "global-data-migration"):
            operation_id = uuid.uuid4().hex
            staging = destination.with_name(f"{destination.name}.staging-{operation_id}")
            payload = staging / "payload"
            published = False
            try:
                if staging.exists():
                    raise SiteStorageError("DATA_ROOT_INVALID", "数据根迁移暂存目录已存在")
                occupied = list(destination.iterdir())
                if occupied:
                    raise SiteStorageError("DATA_ROOT_INVALID", "目标数据根必须为空")
                _write_migration_operation(staging, "created", self.paths.data_root, destination)
                for source in self.paths.data_root.iterdir():
                    if source.name in {"runtime", "staging"}:
                        continue
                    if check_cancel:
                        check_cancel()
                    _write_migration_operation(staging, "copying", self.paths.data_root, destination)
                    target_path = payload / source.name
                    if source.is_dir():
                        _copy_tree_snapshot(source, target_path, check_cancel=check_cancel)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target_path)
                _write_migration_operation(staging, "verifying", self.paths.data_root, destination)
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
                _atomic_json(payload / "migrations" / f"migration-{operation_id}.json", manifest)
                _write_migration_operation(staging, "committing", self.paths.data_root, destination)
                destination.rmdir()
                _publish_data_root(payload, destination)
                published = True
                _write_migration_operation(staging, "completed", self.paths.data_root, destination)
                shutil.rmtree(staging, ignore_errors=True)
                return {"data_root": str(destination), "restart_required": True, "old_data_root_retained": True}
            except SiteStorageError:
                _write_migration_operation(staging, "failed", self.paths.data_root, destination)
                raise
            except Exception as exc:
                _write_migration_operation(staging, "failed", self.paths.data_root, destination)
                raise SiteStorageError("DATA_ROOT_MIGRATION_FAILED", "数据根迁移失败，旧数据未改变") from exc
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
            _relative_inside(temporary, candidate) and not _relative_inside(temporary, current)
        ):
            raise SiteStorageError("DATA_ROOT_UNSAFE_LOCATION", "不能使用源码、安装目录或系统临时目录")
        if _relative_inside(current, candidate) or _relative_inside(candidate, current):
            raise SiteStorageError("DATA_ROOT_NESTED_PATH", "目标数据根不能与当前数据根嵌套")
        candidate.mkdir(parents=True, exist_ok=True)
        marker = candidate / f".write-test-{uuid.uuid4().hex}"
        try:
            marker.write_text("ok", encoding="ascii")
        except OSError as exc:
            raise SiteStorageError("DATA_ROOT_NOT_WRITABLE", "目标数据根不可写") from exc
        finally:
            marker.unlink(missing_ok=True)
        return candidate


class SitePackageService:
    def __init__(self, paths: PathResolver, sites: SiteApplicationService | None = None) -> None:
        self.paths = paths
        self.sites = sites or SiteApplicationService(paths)

    def export_site(
        self,
        site_id: str,
        destination: Path,
        *,
        package_type: str = FULL_MIGRATION,
        migration_password: str | None = None,
        check_cancel: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        normalized_type = str(package_type or FULL_MIGRATION).strip().casefold()
        if normalized_type not in PACKAGE_TYPES:
            raise SiteStorageError("SITE_EXPORT_TYPE_INVALID", "不支持的局点数据包类型")
        sync = SiteSyncService(self.paths, self.sites)
        if normalized_type == FIELD_COLLECTION:
            return sync.export_field_package(site_id, destination, check_cancel=check_cancel)
        if normalized_type == COLLECTION_RETURN:
            return sync.export_return_package(site_id, destination, check_cancel=check_cancel)
        if normalized_type == FULL_MIGRATION:
            if not migration_password:
                raise SiteStorageError(
                    "SITE_EXPORT_PASSWORD_REQUIRED",
                    "完整迁移包必须设置至少 8 个字符的迁移密码",
                )
            return self._export_encrypted_site(
                site_id,
                destination,
                migration_password=migration_password,
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
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
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
                    if source.name.endswith(".db"):
                        reentry_count = max(
                            reentry_count,
                            _copy_sanitized_database(source, target),
                        )
                    else:
                        shutil.copy2(source, target)
                    manifest_files[f"site/{relative}"] = _sha256(target)
                manifest = {
                    "format": "netconsole-site-package",
                    "format_version": PACKAGE_FORMAT_VERSION,
                    "package_id": str(uuid.uuid4()),
                    "package_type": SANITIZED_SHARE,
                    "app_version": APP_VERSION.removeprefix("v"),
                    "site_id": site.site_id,
                    "site_uuid": identity["site_uuid"],
                    "site_name": site.display_name,
                    "site_revision": identity["revision"],
                    "base_revision": identity["revision"],
                    "created_at": _now(),
                    "source_platform": "windows" if os.name == "nt" else os.name,
                    "databases": [name for name in manifest_files if name.endswith(".db")],
                    "artifacts": [],
                    "checksums": manifest_files,
                    "contains_credentials": False,
                    "credential_reentry_count": reentry_count,
                }
                (Path(temp) / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                (Path(temp) / "checksums.json").write_text(json.dumps(manifest_files, ensure_ascii=False, indent=2), encoding="utf-8")
                (Path(temp) / "README.txt").write_text(
                    "NetConsole 脱敏分享包；导入后需要重新录入设备凭据。\n",
                    encoding="utf-8",
                )
                with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
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
            staging.unlink(missing_ok=True)

    def _export_encrypted_site(
        self,
        site_id: str,
        destination: Path,
        *,
        migration_password: str,
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
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        package_id = str(uuid.uuid4())
        try:
            self.paths.temp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="netconsole-site-export-", dir=self.paths.temp_dir
            ) as temp:
                temp_root = Path(temp)
                payload_root = temp_root / "payload"
                site_root = payload_root / "site"
                manifest_files: dict[str, str] = {}
                for source in _safe_site_files(site.root_path):
                    if check_cancel:
                        check_cancel()
                    relative = source.relative_to(site.root_path).as_posix()
                    target = site_root / relative
                    if source.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
                        _copy_database_snapshot(source, target)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                    manifest_files[f"site/{relative}"] = _sha256(target)
                payload_manifest = {
                    "format": "netconsole-site-package-payload",
                    "format_version": 1,
                    "package_id": package_id,
                    "checksums": manifest_files,
                }
                _atomic_json(payload_root / "payload-manifest.json", payload_manifest)
                _atomic_json(payload_root / "checksums.json", manifest_files)
                (payload_root / "README.txt").write_text(
                    "NetConsole 完整迁移包加密载荷。\n", encoding="utf-8"
                )
                payload_zip = temp_root / "payload.zip"
                _write_zip_tree(payload_root, payload_zip)

                encryption = new_encryption_metadata()
                manifest: dict[str, object] = {
                    "format": "netconsole-site-package",
                    "format_version": PACKAGE_FORMAT_VERSION,
                    "package_id": package_id,
                    "package_type": FULL_MIGRATION,
                    "app_version": APP_VERSION.removeprefix("v"),
                    "site_id": site.site_id,
                    "site_uuid": identity["site_uuid"],
                    "site_name": site.display_name,
                    "site_revision": identity["revision"],
                    "base_revision": identity["revision"],
                    "created_at": _now(),
                    "source_platform": "windows" if os.name == "nt" else os.name,
                    "contains_credentials": True,
                    "credential_reentry_count": 0,
                    "encrypted": True,
                    "encryption": encryption,
                }
                encrypted_payload = temp_root / "payload.enc"
                try:
                    encrypt_file(
                        payload_zip,
                        encrypted_payload,
                        password=migration_password,
                        metadata=encryption,
                        aad=_package_aad(manifest),
                    )
                except SitePackageCryptoError as exc:
                    raise SiteStorageError("SITE_EXPORT_ENCRYPTION_FAILED", str(exc)) from exc
                manifest["payload_ciphertext_sha256"] = _sha256(encrypted_payload)
                manifest["payload_size_bytes"] = encrypted_payload.stat().st_size
                _write_encrypted_package(staging, manifest, encrypted_payload)
            self.inspect_package(
                staging,
                migration_password=migration_password,
                validate_extension=False,
            )
            os.replace(staging, destination)
            return {
                "package_name": destination.name,
                "package_type": FULL_MIGRATION,
                "site_uuid": identity["site_uuid"],
                "base_revision": identity["revision"],
                "size_bytes": destination.stat().st_size,
                "contains_credentials": True,
                "credential_reentry_count": 0,
                "encrypted": True,
            }
        finally:
            staging.unlink(missing_ok=True)

    def inspect_package(
        self,
        package: Path,
        *,
        target_site_id: str | None = None,
        migration_password: str | None = None,
        validate_extension: bool = True,
    ) -> dict[str, object]:
        package = Path(package).resolve()
        try:
            with zipfile.ZipFile(package) as archive:
                infos = archive.infolist()
                if len(infos) > _MAX_PACKAGE_FILES:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包文件数量超限")
                total = 0
                for info in infos:
                    _validate_archive_name(info.filename)
                    if _is_symlink(info):
                        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包不允许符号链接")
                    single_limit = (
                        _MAX_PACKAGE_BYTES
                        if info.filename == "payload.enc"
                        else _MAX_SINGLE_FILE_BYTES
                    )
                    if info.file_size > single_limit:
                        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包单文件过大")
                    total += info.file_size
                    if total > _MAX_PACKAGE_BYTES:
                        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包解压总大小超限")
                try:
                    manifest = json.loads(archive.read("manifest.json"))
                except (KeyError, json.JSONDecodeError) as exc:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包缺少有效 manifest") from exc
                if not isinstance(manifest, dict):
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包 manifest 格式无效")
                try:
                    version = int(manifest.get("format_version") or 0)
                except (TypeError, ValueError) as exc:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE", "局点包版本格式无效"
                    ) from exc
                if manifest.get("format") != "netconsole-site-package" or version not in {1, 2, PACKAGE_FORMAT_VERSION}:
                    raise SiteStorageError("SITE_IMPORT_VERSION_UNSUPPORTED", "不支持的局点包版本")
                package_type = (
                    FULL_MIGRATION
                    if version == 1
                    else str(manifest.get("package_type") or "")
                )
                if package_type not in PACKAGE_TYPES:
                    raise SiteStorageError("SITE_IMPORT_VERSION_UNSUPPORTED", "数据包类型不受支持")
                expected_suffix = ".ncresult" if package_type == COLLECTION_RETURN else ".ncsite"
                if validate_extension and package.suffix.casefold() != expected_suffix:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", f"{package_type} 数据包扩展名应为 {expected_suffix}")
                encrypted_full = (
                    package_type == FULL_MIGRATION
                    and version >= 3
                    and manifest.get("encrypted") is True
                    and manifest.get("contains_credentials") is True
                )
                if version >= 3 and package_type == FULL_MIGRATION and not encrypted_full:
                    raise SiteStorageError(
                        "SITE_IMPORT_INVALID_PACKAGE",
                        "v3 完整迁移包必须使用认证加密",
                    )
                if encrypted_full:
                    if not migration_password:
                        raise SiteStorageError(
                            "SITE_IMPORT_PASSWORD_REQUIRED",
                            "该完整迁移包已加密，请输入迁移密码",
                            details={
                                "package_type": FULL_MIGRATION,
                                "site_name": str(manifest.get("site_name") or ""),
                                "encrypted": True,
                            },
                        )
                    payload_summary = self._inspect_encrypted_payload(
                        archive, manifest, migration_password
                    )
                    checksums: object = {"payload.enc": manifest.get("payload_ciphertext_sha256")}
                else:
                    if manifest.get("contains_credentials") is not False:
                        raise SiteStorageError(
                            "SITE_IMPORT_INVALID_PACKAGE",
                            "未加密的局点包不能包含凭据",
                        )
                    payload_summary = {
                        "file_count": len(infos),
                        "total_bytes": total,
                    }
                    checksums = manifest.get("checksums")
                if not isinstance(checksums, dict):
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包缺少 checksum")
                for name, expected in checksums.items():
                    _validate_archive_name(str(name))
                    try:
                        actual = hashlib.sha256(archive.read(str(name))).hexdigest()
                    except KeyError as exc:
                        raise SiteStorageError("SITE_IMPORT_CHECKSUM_FAILED", "局点包文件缺失") from exc
                    if actual != str(expected):
                        raise SiteStorageError("SITE_IMPORT_CHECKSUM_FAILED", "局点包完整性校验失败")
                public = {
                    "site_id": str(manifest.get("site_id") or ""),
                    "site_uuid": str(manifest.get("site_uuid") or ""),
                    "site_name": str(manifest.get("site_name") or ""),
                    "package_type": package_type,
                    "package_id": str(manifest.get("package_id") or ""),
                    "base_revision": int(manifest.get("base_revision") or manifest.get("site_revision") or 1),
                    "file_count": int(payload_summary["file_count"]),
                    "contains_credentials": bool(encrypted_full),
                    "encrypted": bool(encrypted_full),
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
                        **SiteSyncService(self.paths, self.sites).inspect_return_package(
                            package,
                            manifest,
                            target_site_id=target_site_id,
                        ),
                    }
                return public
        except zipfile.BadZipFile as exc:
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包不是有效 ZIP") from exc

    def _inspect_encrypted_payload(
        self,
        archive: zipfile.ZipFile,
        manifest: dict[str, object],
        migration_password: str,
    ) -> dict[str, int]:
        encryption = manifest.get("encryption")
        if not isinstance(encryption, dict):
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "完整迁移包缺少加密参数")
        try:
            expected = str(manifest.get("payload_ciphertext_sha256") or "")
            with archive.open("payload.enc") as encrypted:
                if _sha256_stream(encrypted) != expected:
                    raise SiteStorageError(
                        "SITE_IMPORT_AUTHENTICATION_FAILED",
                        "迁移密码错误、数据包已损坏或被修改",
                    )
            self.paths.temp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="netconsole-site-inspect-", dir=self.paths.temp_dir
            ) as temporary:
                payload_zip = Path(temporary) / "payload.zip"
                with archive.open("payload.enc") as encrypted:
                    decrypt_stream(
                        encrypted,
                        payload_zip,
                        password=migration_password,
                        metadata=encryption,
                        aad=_package_aad(manifest),
                    )
                return _inspect_payload_zip(payload_zip, str(manifest.get("package_id") or ""))
        except KeyError as exc:
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "完整迁移包缺少加密载荷") from exc
        except SitePackageCryptoError as exc:
            raise SiteStorageError(
                "SITE_IMPORT_AUTHENTICATION_FAILED",
                "迁移密码错误、数据包已损坏或被修改",
            ) from exc

    def import_site(
        self,
        package: Path,
        *,
        site_id: str | None = None,
        display_name: str | None = None,
        replace_site_id: str | None = None,
        raw_only: bool = False,
        conflict_resolutions: list[dict[str, object]] | None = None,
        migration_password: str | None = None,
        credential_policy: str = "preserve_local",
    ) -> dict[str, object]:
        if credential_policy not in {"preserve_local", "use_package"}:
            raise SiteStorageError("SITE_IMPORT_CREDENTIAL_POLICY_INVALID", "凭据冲突策略无效")
        info = self.inspect_package(
            package,
            target_site_id=site_id or replace_site_id,
            migration_password=migration_password,
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
        name = validate_display_name(display_name or str(info["site_name"]) or wanted_id)
        replacement = self.sites.registry.get(replace_site_id) if replace_site_id else None
        target = replacement.root_path if replacement is not None else self.paths.sites_dir / wanted_id
        backup: Path | None = None
        published = False
        staging = self.paths.temp_dir / "site-import-staging" / uuid.uuid4().hex
        with storage_lock(self.paths, "site-import"):
            try:
                staging.mkdir(parents=True)
                if bool(info.get("encrypted")):
                    self._extract_encrypted_payload(
                        Path(package).resolve(),
                        staging,
                        manifest,
                        migration_password or "",
                    )
                else:
                    _extract_outer_package(Path(package).resolve(), staging)
                imported_root = staging / "site"
                imported_database = imported_root / "db" / "devices.db"
                reentry_count = 0
                if imported_database.is_file():
                    with sqlite3.connect(imported_database) as connection:
                        if bool(info.get("contains_credentials")):
                            repair_device_credential_states(connection)
                        else:
                            reentry_count = sanitize_device_credentials_for_package(
                                connection,
                                infer_missing=(
                                    "credential_reentry_count" not in manifest
                                    or int(manifest.get("credential_reentry_count") or 0) > 0
                                ),
                            )
                        connection.commit()
                if (
                    replacement is not None
                    and bool(info.get("contains_credentials"))
                    and credential_policy == "preserve_local"
                ):
                    _preserve_local_device_credentials(
                        replacement.root_path / "db" / "devices.db",
                        imported_database,
                    )
                _quick_check_site(imported_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if replace_site_id is None:
                        raise SiteStorageError("SITE_IMPORT_CONFLICT", "目标局点已存在")
                    backup = self.paths.archive_dir / f"site-import-{wanted_id}-{uuid.uuid4().hex}"
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    _finalize_site_databases(target)
                    _publish_directory(target, backup)
                    _remove_directory_after_backup(target)
                _publish_directory(imported_root, target)
                published = True
                self.sites.registry.register(SiteRecord(wanted_id, name, target, remark="imported"))
                if package_type == FIELD_COLLECTION:
                    SiteSyncService(self.paths, self.sites).record_field_baseline(target, manifest)
                return {
                    "site_id": wanted_id,
                    "display_name": name,
                    "package_type": package_type,
                    "backup_created": backup is not None,
                    "requires_credentials": reentry_count > 0,
                    "credential_reentry_count": reentry_count,
                    "credential_policy": (
                        credential_policy if bool(info.get("contains_credentials")) else "not_applicable"
                    ),
                }
            except SiteStorageError:
                if published and backup and target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup and not target.exists():
                    _publish_directory(backup, target)
                shutil.rmtree(staging, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(staging, ignore_errors=True)
                if published and backup and target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                if backup and not target.exists():
                    _publish_directory(backup, target)
                raise SiteStorageError("SITE_IMPORT_FAILED", "局点导入失败，已保留原数据") from exc
            finally:
                shutil.rmtree(staging, ignore_errors=True)

    def _extract_encrypted_payload(
        self,
        package: Path,
        staging: Path,
        manifest: dict[str, object],
        migration_password: str,
    ) -> None:
        encryption = manifest.get("encryption")
        if not isinstance(encryption, dict):
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "完整迁移包缺少加密参数")
        payload_zip = staging / ".decrypted-payload.zip"
        try:
            with zipfile.ZipFile(package) as archive, archive.open("payload.enc") as source:
                decrypt_stream(
                    source,
                    payload_zip,
                    password=migration_password,
                    metadata=encryption,
                    aad=_package_aad(manifest),
                )
            _inspect_payload_zip(payload_zip, str(manifest.get("package_id") or ""))
            _extract_outer_package(payload_zip, staging)
        except (SitePackageCryptoError, KeyError) as exc:
            raise SiteStorageError(
                "SITE_IMPORT_AUTHENTICATION_FAILED",
                "迁移密码错误、数据包已损坏或被修改",
            ) from exc
        finally:
            payload_zip.unlink(missing_ok=True)

    @staticmethod
    def _read_manifest(package: Path) -> dict[str, object]:
        try:
            with zipfile.ZipFile(Path(package).resolve()) as archive:
                value = json.loads(archive.read("manifest.json"))
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "数据包缺少有效 manifest") from exc
        if not isinstance(value, dict):
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "数据包 manifest 格式无效")
        return value


def _default_data_root(paths: PathResolver) -> Path:
    from netconsole.core.runtime_environment import data_root

    return data_root()


def _write_migration_operation(staging: Path, status: str, source: Path, destination: Path) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    common = {"schema_version": 1, "updated_at": _now()}
    _atomic_json(staging / "manifest.json", {**common, "operation_id": staging.name, "status": status})
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
    raise SiteStorageError("DATA_ROOT_MIGRATION_FAILED", "无法原子发布新的数据根") from last_error


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
        raise SiteStorageError("DATA_ROOT_MIGRATION_FAILED", "storage-manifest.json 无效，无法迁移") from exc
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
    for db in root.rglob("*.db"):
        connection = sqlite3.connect(db)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
        if not result or str(result[0]).lower() != "ok":
            raise SiteStorageError("SITE_MIGRATION_FAILED", "SQLite 完整性检查失败")


def _quick_check_site_tree(root: Path) -> None:
    if root.exists():
        _quick_check_site(root)


def _finalize_site_databases(root: Path) -> None:
    """Checkpoint WAL files before a Windows directory publish."""
    for db in root.rglob("*.db"):
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(db, timeout=5)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.DatabaseError:
            continue
        finally:
            if connection is not None:
                connection.close()
        for suffix in ("-wal", "-shm"):
            try:
                (db.parent / f"{db.name}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass
    time.sleep(0.02)


def _safe_site_files(root: Path) -> Iterator[Path]:
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        relative_parts = {part.casefold() for part in item.relative_to(root).parts}
        if relative_parts & _SENSITIVE_PARTS or item.name.endswith((".tmp", ".lock", ".part", "-wal", "-shm")) or ".db-" in item.name:
            continue
        yield item


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


def _preserve_local_device_credentials(source: Path, target: Path) -> None:
    if not source.is_file() or not target.is_file():
        return
    source_connection = sqlite3.connect(source)
    source_connection.row_factory = sqlite3.Row
    target_connection = sqlite3.connect(target)
    target_connection.row_factory = sqlite3.Row
    try:
        source_columns = _table_columns(source_connection, "devices")
        target_columns = _table_columns(target_connection, "devices")
        credential_columns = [
            field
            for field in (
                "username",
                "ssh_username",
                "telnet_username",
                "tunnel1_username",
                "tunnel2_username",
                *DEVICE_SECRET_STORAGE_FIELDS,
            )
            if field in source_columns and field in target_columns
        ]
        if "device_uuid" not in source_columns or "device_uuid" not in target_columns:
            return
        source_states = read_device_credential_states(source_connection)
        ensure_device_credential_schema(target_connection)
        selected = ", ".join(
            ["device_uuid", *(f'"{field}"' for field in credential_columns)]
        )
        for row in source_connection.execute(f"SELECT {selected} FROM devices"):
            device_uuid = str(row["device_uuid"] or "")
            if not device_uuid:
                continue
            exists = target_connection.execute(
                "SELECT 1 FROM devices WHERE device_uuid = ? LIMIT 1",
                (device_uuid,),
            ).fetchone()
            if exists is None:
                continue
            if credential_columns:
                assignments = ", ".join(f'"{field}" = ?' for field in credential_columns)
                target_connection.execute(
                    f"UPDATE devices SET {assignments} WHERE device_uuid = ?",
                    [*(row[field] for field in credential_columns), device_uuid],
                )
            target_connection.execute(
                "DELETE FROM device_credential_states WHERE device_uuid = ?",
                (device_uuid,),
            )
            for field in DEVICE_SECRET_FIELDS:
                replace_device_credential_state(
                    target_connection,
                    device_uuid,
                    field,
                    source_states.get(device_uuid, {}).get(field),
                )
        repair_device_credential_states(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _package_aad(manifest: dict[str, object]) -> bytes:
    encryption = manifest.get("encryption")
    encryption_values = dict(encryption) if isinstance(encryption, dict) else {}
    aad_value = {
        "format": manifest.get("format"),
        "format_version": manifest.get("format_version"),
        "package_id": manifest.get("package_id"),
        "package_type": manifest.get("package_type"),
        "app_version": manifest.get("app_version"),
        "site_id": manifest.get("site_id"),
        "site_uuid": manifest.get("site_uuid"),
        "site_name": manifest.get("site_name"),
        "site_revision": manifest.get("site_revision"),
        "base_revision": manifest.get("base_revision"),
        "created_at": manifest.get("created_at"),
        "source_platform": manifest.get("source_platform"),
        "contains_credentials": manifest.get("contains_credentials"),
        "encrypted": manifest.get("encrypted"),
        "encryption": {
            key: encryption_values.get(key)
            for key in (
                "algorithm",
                "kdf",
                "n",
                "r",
                "p",
                "salt_b64",
                "nonce_b64",
                "aad_version",
                "payload",
            )
        },
    }
    return json.dumps(
        aad_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_zip_tree(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        for item in root.rglob("*"):
            if item.is_file():
                archive.write(item, item.relative_to(root).as_posix())


def _write_encrypted_package(
    destination: Path,
    manifest: dict[str, object],
    encrypted_payload: Path,
) -> None:
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        archive.writestr(
            "README.txt",
            "NetConsole 完整迁移包；设备凭据位于认证加密载荷中。\n".encode(
                "utf-8"
            ),
        )
        archive.write(
            encrypted_payload,
            "payload.enc",
            compress_type=zipfile.ZIP_STORED,
        )


def _inspect_payload_zip(payload: Path, package_id: str) -> dict[str, int]:
    try:
        with zipfile.ZipFile(payload) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_PACKAGE_FILES:
                raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包文件数量超限")
            total = 0
            for info in infos:
                _validate_archive_name(info.filename)
                if _is_symlink(info):
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包不允许符号链接")
                if info.file_size > _MAX_SINGLE_FILE_BYTES:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包单文件过大")
                total += info.file_size
                if total > _MAX_PACKAGE_BYTES:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包解压总大小超限")
            try:
                payload_manifest = json.loads(archive.read("payload-manifest.json"))
            except (KeyError, json.JSONDecodeError) as exc:
                raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "加密载荷缺少有效 manifest") from exc
            if (
                not isinstance(payload_manifest, dict)
                or payload_manifest.get("format") != "netconsole-site-package-payload"
            ):
                raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "加密载荷与外层 manifest 不匹配")
            try:
                payload_version = int(payload_manifest.get("format_version") or 0)
            except (TypeError, ValueError) as exc:
                raise SiteStorageError(
                    "SITE_IMPORT_INVALID_PACKAGE", "加密载荷版本格式无效"
                ) from exc
            if (
                payload_version != 1
                or str(payload_manifest.get("package_id") or "") != package_id
            ):
                raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "加密载荷与外层 manifest 不匹配")
            checksums = payload_manifest.get("checksums")
            if not isinstance(checksums, dict):
                raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "加密载荷缺少 checksum")
            for name, expected in checksums.items():
                _validate_archive_name(str(name))
                try:
                    actual = hashlib.sha256(archive.read(str(name))).hexdigest()
                except KeyError as exc:
                    raise SiteStorageError("SITE_IMPORT_CHECKSUM_FAILED", "加密载荷文件缺失") from exc
                if actual != str(expected):
                    raise SiteStorageError("SITE_IMPORT_CHECKSUM_FAILED", "加密载荷完整性校验失败")
            return {"file_count": len(infos), "total_bytes": total}
    except zipfile.BadZipFile as exc:
        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "解密后的载荷不是有效 ZIP") from exc


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


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _copy_tree_snapshot(source: Path, destination: Path, *, check_cancel: Callable[[], None] | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if check_cancel:
            check_cancel()
        relative = item.relative_to(source)
        if any(part.casefold() in {"cache", "locks", "temp"} for part in relative.parts):
            continue
        if item.name.endswith((".tmp", ".lock", ".part", "-wal", "-shm")) or ".db-" in item.name:
            continue
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}:
            target.parent.mkdir(parents=True, exist_ok=True)
            source_connection = sqlite3.connect(f"{item.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
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
    if not logical_name or logical_name.startswith("/") or re.match(r"^[A-Za-z]:", logical_name) or logical_name.startswith("//") or any(part in {"", ".", ".."} for part in logical_name.split("/")) or path.is_absolute():
        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包包含不安全路径")
    return f"{logical_name}/" if directory_entry else logical_name


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


__all__ = [
    "DataRootApplicationService", "DataRootSnapshot", "SiteApplicationService", "SitePackageService",
    "SiteRecord", "SiteRegistryRepository", "SiteStorageError", "storage_lock", "validate_display_name", "validate_site_id",
]
