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
from typing import Callable, Iterator

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import persistent_storage
from netconsole.core.sites import DEFAULT_SITE, SiteManager
from netconsole.core.version import APP_VERSION
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.models.task_state import TaskState


class SiteStorageError(RuntimeError):
    """可安全返回给 Desktop API 的局点/数据存储错误。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
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
_SENSITIVE_PARTS = {"token", "password", "passwd", "secret", "credentials", "bootstrap", "locks", "cache", "temp"}
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
                root = self._resolve_root(str(item.get("relative_path") or f"data/sites/{site_id}"))
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
        return [
            {
                **item.to_public(include_path=persistent_storage()),
                "active": item.site_id == active,
                "size_bytes": _directory_size(item.root_path),
            }
            for item in self.registry.list()
        ]

    def get_site(self, site_id: str) -> dict[str, object]:
        item = self.registry.get(site_id)
        return {
            **item.to_public(include_path=persistent_storage()),
            "active": item.site_id == self.active_site_id(),
            "size_bytes": _directory_size(item.root_path),
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
                _atomic_json(staging / "site_meta.json", {"site_id": site_id, "display_name": display_name, "remark": remark, "schema_version": 1, "created_at": _now()})
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
            self._ensure_no_active_tasks(site_id)
            record = self.registry.get(site_id)
            previous = self.active_site_id()
            previous_directory = self.registry.resolve_directory_name(previous)
            try:
                self.manager.switch_site(record.root_path.name)
                return {**record.to_public(), "active": True, "previous_site_id": previous, "restart_required": True}
            except Exception as exc:
                try:
                    self.manager.switch_site(previous_directory)
                except Exception:
                    pass
                raise SiteStorageError("SITE_SWITCH_BLOCKED", "局点切换失败，已恢复原局点") from exc

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
        service = self.task_service
        if service is None:
            return
        repository = getattr(service, "repository", lambda _site: None)(self.registry.directory_name(site_id))
        if repository is None:
            return
        active = repository.list(statuses={TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING})
        if active:
            raise SiteStorageError("SITE_HAS_ACTIVE_TASKS", "局点存在未完成任务，无法切换")

    def ensure_no_active_tasks(self, site_id: str) -> None:
        self._ensure_no_active_tasks(validate_site_id(site_id))

    def ensure_no_active_tasks_anywhere(self) -> None:
        for site in self.registry.list():
            self._ensure_no_active_tasks(site.site_id)


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
            staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
            try:
                for source in self.paths.data_root.iterdir():
                    if source.name in {"runtime", "temp", "bootstrap"}:
                        continue
                    if check_cancel:
                        check_cancel()
                    target_path = staging / source.name
                    if source.is_dir():
                        _copy_tree_snapshot(source, target_path, check_cancel=check_cancel)
                    else:
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target_path)
                _quick_check_site_tree(staging / "data" / "sites")
                manifest = {"format": "netconsole-data-root-migration", "version": 1, "created_at": _now(), "source": str(self.paths.data_root), "destination": str(destination)}
                _atomic_json(staging / "migrations" / f"migration-{uuid.uuid4().hex}.json", manifest)
                if destination.exists():
                    if any(destination.iterdir()):
                        raise SiteStorageError("DATA_ROOT_INVALID", "目标数据根必须为空或不存在")
                    destination.rmdir()
                _publish_directory(staging, destination)
                return {"data_root": str(destination), "restart_required": True, "old_data_root_retained": True}
            except SiteStorageError:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            except Exception as exc:
                shutil.rmtree(staging, ignore_errors=True)
                raise SiteStorageError("DATA_ROOT_MIGRATION_FAILED", "数据根迁移失败，旧数据未改变") from exc

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

    def export_site(self, site_id: str, destination: Path, *, check_cancel: Callable[[], None] | None = None) -> dict[str, object]:
        site = self.sites.registry.get(site_id)
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.casefold() != ".ncsite":
            destination = destination.with_suffix(".ncsite")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            manifest_files: dict[str, str] = {}
            with tempfile.TemporaryDirectory(prefix="netconsole-site-export-") as temp:
                root = Path(temp) / "site"
                for source in _safe_site_files(site.root_path):
                    if check_cancel:
                        check_cancel()
                    relative = source.relative_to(site.root_path).as_posix()
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.name.endswith(".db"):
                        _copy_sanitized_database(source, target)
                    else:
                        shutil.copy2(source, target)
                    manifest_files[f"site/{relative}"] = _sha256(target)
                manifest = {"format": "netconsole-site-package", "format_version": 1, "app_version": APP_VERSION.removeprefix("v"), "site_id": site.site_id, "site_name": site.display_name, "created_at": _now(), "source_platform": "windows" if os.name == "nt" else os.name, "databases": [name for name in manifest_files if name.endswith(".db")], "artifacts": [], "checksums": manifest_files, "contains_credentials": False}
                (Path(temp) / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                (Path(temp) / "checksums.json").write_text(json.dumps(manifest_files, ensure_ascii=False, indent=2), encoding="utf-8")
                (Path(temp) / "README.txt").write_text("NetConsole 局点包；导入后需要重新录入设备凭据。\n", encoding="utf-8")
                with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for item in Path(temp).rglob("*"):
                        if item.is_file():
                            archive.write(item, item.relative_to(temp).as_posix())
            self.inspect_package(staging)
            os.replace(staging, destination)
            return {"package_name": destination.name, "size_bytes": destination.stat().st_size, "contains_credentials": False}
        finally:
            staging.unlink(missing_ok=True)

    def inspect_package(self, package: Path) -> dict[str, object]:
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
                    if info.file_size > _MAX_SINGLE_FILE_BYTES:
                        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包单文件过大")
                    total += info.file_size
                    if total > _MAX_PACKAGE_BYTES:
                        raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包解压总大小超限")
                try:
                    manifest = json.loads(archive.read("manifest.json"))
                except (KeyError, json.JSONDecodeError) as exc:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包缺少有效 manifest") from exc
                if manifest.get("format") != "netconsole-site-package" or manifest.get("format_version") != 1:
                    raise SiteStorageError("SITE_IMPORT_VERSION_UNSUPPORTED", "不支持的局点包版本")
                if manifest.get("contains_credentials") is not False:
                    raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包不能包含凭据")
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
                return {"site_id": str(manifest.get("site_id") or ""), "site_name": str(manifest.get("site_name") or ""), "file_count": len(infos), "contains_credentials": False}
        except zipfile.BadZipFile as exc:
            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包不是有效 ZIP") from exc

    def import_site(self, package: Path, *, site_id: str | None = None, display_name: str | None = None, replace_site_id: str | None = None) -> dict[str, object]:
        info = self.inspect_package(package)
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
                with zipfile.ZipFile(Path(package).resolve()) as archive:
                    for info_item in archive.infolist():
                        name_item = _validate_archive_name(info_item.filename)
                        destination = (staging / name_item).resolve()
                        if not _relative_inside(staging, destination):
                            raise SiteStorageError("SITE_IMPORT_INVALID_PACKAGE", "局点包路径越界")
                        if info_item.is_dir():
                            destination.mkdir(parents=True, exist_ok=True)
                        else:
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(info_item) as source, destination.open("wb") as target_file:
                                shutil.copyfileobj(source, target_file)
                imported_root = staging / "site"
                _quick_check_site(imported_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if replace_site_id is None:
                        raise SiteStorageError("SITE_IMPORT_CONFLICT", "目标局点已存在")
                    backup = self.paths.archive_dir / f"site-import-{wanted_id}-{uuid.uuid4().hex}"
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    _publish_directory(target, backup)
                _publish_directory(imported_root, target)
                published = True
                self.sites.registry.register(SiteRecord(wanted_id, name, target, remark="imported"))
                return {"site_id": wanted_id, "display_name": name, "backup_created": backup is not None, "requires_credentials": True}
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


def _default_data_root(paths: PathResolver) -> Path:
    from netconsole.core.runtime_environment import is_packaged_runtime

    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return (base / "NetConsole" / ("" if is_packaged_runtime() else "Development")).resolve()


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
        with sqlite3.connect(db) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise SiteStorageError("SITE_MIGRATION_FAILED", "SQLite 完整性检查失败")


def _quick_check_site_tree(root: Path) -> None:
    if root.exists():
        _quick_check_site(root)


def _finalize_site_databases(root: Path) -> None:
    """Checkpoint WAL files before a Windows directory publish."""
    for db in root.rglob("*.db"):
        try:
            with sqlite3.connect(db, timeout=5) as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA journal_mode=DELETE")
        except sqlite3.DatabaseError:
            continue
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


def _copy_sanitized_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        columns = {str(row[1]) for row in target_connection.execute("PRAGMA table_info(devices)")}
        credential_columns = {"password", "ssh_password", "telnet_password", "snmp_ro_community", "tunnel1_password", "tunnel2_password"}
        available = sorted(columns & credential_columns)
        if available:
            target_connection.execute(f"UPDATE devices SET {', '.join(f'{column} = NULL' for column in available)}")
            target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()


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
