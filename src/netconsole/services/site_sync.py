from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from netconsole.core.device_credential_store import (
    credential_reentry_count,
    sanitize_device_credentials_for_package,
)
from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.core.version import APP_VERSION


FULL_MIGRATION = "full_migration"
SANITIZED_SHARE = "sanitized_share"
FIELD_COLLECTION = "field_collection"
COLLECTION_RETURN = "collection_return"
PACKAGE_TYPES = frozenset(
    {FULL_MIGRATION, SANITIZED_SHARE, FIELD_COLLECTION, COLLECTION_RETURN}
)
PACKAGE_FORMAT = "netconsole-site-package"
PACKAGE_FORMAT_VERSION = 4

_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_EXCLUDED_PARTS = {
    "agents.db",
    "bootstrap",
    "cache",
    "credentials",
    "locks",
    "sync",
    "temp",
    "token",
}
_CREDENTIAL_COLUMNS = {
    "password",
    "ssh_password",
    "telnet_password",
    "snmp_ro_community",
    "tunnel1_password",
    "tunnel2_password",
}
_MERGE_TABLES = {
    "devices": ("device_uuid",),
    "collect_runs": ("collect_run_uuid",),
    "device_facts": ("device_uuid",),
    "ac_fit_ap_resources": ("ap_uuid",),
    "ac_fit_ap_metadata": ("ap_uuid",),
    "ap_entities": ("ap_uuid",),
    "ap_resource_snapshots": ("snapshot_uuid",),
    "ap_lldp_history": ("history_uuid",),
    "ap_optical_history": ("history_uuid",),
}
_TASK_STATUS_PRIORITY = {
    "COMPLETED": 50,
    "PARTIAL": 40,
    "FAILED": 30,
    "CANCELLED": 20,
    "STOPPED": 20,
    "STOPPING": 10,
    "RUNNING": 5,
    "STARTING": 4,
    "PENDING": 3,
}


@dataclass(frozen=True)
class MergeConflict:
    conflict_id: str
    entity_type: str
    entity_id: str
    field: str
    base_value: object
    local_value: object
    returned_value: object

    def to_public(self) -> dict[str, object]:
        return {
            "conflict_id": self.conflict_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "field": self.field,
            "base_value": self.base_value,
            "local_value": self.local_value,
            "returned_value": self.returned_value,
        }


@dataclass(frozen=True)
class MergeAction:
    table: str
    key_columns: tuple[str, ...]
    key_values: tuple[object, ...]
    insert_values: dict[str, object] | None
    update_values: dict[str, object]


@dataclass(frozen=True)
class DatabaseMergePlan:
    actions: tuple[MergeAction, ...]
    conflicts: tuple[MergeConflict, ...]
    new_records: int
    updated_records: int
    duplicate_records: int
    deletion_requests: int
    unsupported_records: int


class SiteSyncService:
    """增量局点包的基准、预检和受控合并实现。"""

    def __init__(self, paths: PathResolver, sites: object) -> None:
        self.paths = paths
        self.sites = sites

    def export_field_package(
        self,
        site_id: str,
        destination: Path,
        *,
        check_cancel: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        record = self.sites.registry.get(site_id)
        identity = self.ensure_sync_identity(record, require_legacy_audit=True)
        baseline_id = str(uuid.uuid4())
        destination = _with_suffix(destination, ".ncsite")
        files = list(self._field_collection_files(record.root_path))
        with tempfile.TemporaryDirectory(
            prefix="netconsole-field-package-"
        ) as temporary:
            temp_root = Path(temporary)
            checksums = self._copy_package_files(
                files,
                record.root_path,
                temp_root / "site",
                check_cancel=check_cancel,
            )
            reentry_count = _database_credential_reentry_count(
                temp_root / "site" / "db" / "devices.db"
            )
            manifest = self._manifest(
                record=record,
                identity=identity,
                package_type=FIELD_COLLECTION,
                checksums=checksums,
                extra={
                    "baseline_id": baseline_id,
                    "base_revision": identity["revision"],
                    "credential_reentry_count": reentry_count,
                    "baseline_files": {
                        name.removeprefix("site/"): digest
                        for name, digest in checksums.items()
                        if not name.endswith((".db", ".sqlite", ".sqlite3"))
                        and name != "site/site_meta.json"
                    },
                    "changes": {
                        "new_files": 0,
                        "new_tasks": 0,
                        "modified_base_records": 0,
                        "deletion_requests": 0,
                    },
                },
            )
            self._write_package(temp_root, destination, manifest)
        return {
            "package_name": destination.name,
            "package_type": FIELD_COLLECTION,
            "baseline_id": baseline_id,
            "base_revision": identity["revision"],
            "size_bytes": destination.stat().st_size,
            "contains_credentials": False,
            "credential_reentry_count": reentry_count,
        }

    def export_return_package(
        self,
        site_id: str,
        destination: Path,
        *,
        check_cancel: Callable[[], None] | None = None,
    ) -> dict[str, object]:
        record = self.sites.registry.get(site_id)
        metadata = self._read_metadata(record.root_path)
        origin = metadata.get("sync_origin")
        if not isinstance(origin, dict) or not str(origin.get("baseline_id") or ""):
            _raise(
                "SITE_SYNC_BASELINE_REQUIRED",
                "当前局点不是由现场采集包建立，不能导出采集回传包",
            )
        baseline_id = str(origin["baseline_id"])
        baseline_root = self._baseline_root(record.root_path, baseline_id)
        baseline_manifest = _read_json(baseline_root / "manifest.json")
        if baseline_manifest.get("site_uuid") != metadata.get("site_uuid"):
            _raise("SITE_SYNC_BASELINE_INVALID", "现场采集基准与当前局点不匹配")
        identity = self.ensure_sync_identity(record, require_legacy_audit=True)
        destination = _with_suffix(destination, ".ncresult")
        source_machine_id = self._installation_id()
        baseline_files = {
            str(name): str(value)
            for name, value in dict(
                baseline_manifest.get("baseline_files") or {}
            ).items()
        }

        with tempfile.TemporaryDirectory(
            prefix="netconsole-return-package-"
        ) as temporary:
            temp_root = Path(temporary)
            payload_root = temp_root / "return"
            file_entries: list[dict[str, object]] = []
            deletion_entries: list[dict[str, object]] = []
            current_paths: set[str] = set()
            content_paths: dict[str, str] = {}

            for source in self._sync_candidate_files(record.root_path):
                if check_cancel:
                    check_cancel()
                relative = source.relative_to(record.root_path).as_posix()
                if relative == "site_meta.json":
                    continue
                current_paths.add(relative)
                if source.suffix.casefold() in _DATABASE_SUFFIXES:
                    continue
                digest = _sha256(source)
                if baseline_files.get(relative) == digest:
                    continue
                payload_name = content_paths.get(digest)
                if payload_name is None:
                    payload_name = f"return/files/{digest}"
                    target = temp_root / payload_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    content_paths[digest] = payload_name
                file_entries.append(
                    {
                        "data_id": f"file-{digest}",
                        "relative_path": relative,
                        "sha256": digest,
                        "size_bytes": source.stat().st_size,
                        "collected_at": datetime.fromtimestamp(
                            source.stat().st_mtime,
                            timezone.utc,
                        ).isoformat(timespec="seconds"),
                        "payload": payload_name,
                        "source_task_id": _task_id_from_path(relative),
                    }
                )

            for relative, digest in baseline_files.items():
                if relative not in current_paths:
                    deletion_entries.append(
                        {
                            "entity_type": "file",
                            "entity_id": relative,
                            "sha256": digest,
                            "base_revision": int(origin.get("base_revision") or 1),
                        }
                    )

            current_devices = record.root_path / "db" / "devices.db"
            base_devices = baseline_root / "devices.db"
            if not current_devices.is_file() or not base_devices.is_file():
                _raise("SITE_SYNC_BASELINE_INVALID", "现场采集基准缺少主数据库副本")
            _copy_sanitized_database(
                base_devices, payload_root / "databases" / "base" / "devices.db"
            )
            _copy_sanitized_database(
                current_devices, payload_root / "databases" / "current" / "devices.db"
            )
            tasks = record.root_path / "db" / "tasks.db"
            if tasks.is_file():
                _copy_database(
                    tasks, payload_root / "databases" / "current" / "tasks.db"
                )

            checksums = {
                item.relative_to(temp_root).as_posix(): _sha256(item)
                for item in temp_root.rglob("*")
                if item.is_file()
            }
            manifest = self._manifest(
                record=record,
                identity=identity,
                package_type=COLLECTION_RETURN,
                checksums=checksums,
                extra={
                    "baseline_id": baseline_id,
                    "base_revision": int(origin.get("base_revision") or 1),
                    "source_machine_id": source_machine_id,
                    "source_package_id": str(origin.get("source_package_id") or ""),
                    "file_entries": file_entries,
                    "deletions": deletion_entries,
                    "changes": {
                        "new_or_changed_files": len(file_entries),
                        "deletion_requests": len(deletion_entries),
                    },
                },
            )
            self._write_package(temp_root, destination, manifest)
        return {
            "package_name": destination.name,
            "package_type": COLLECTION_RETURN,
            "baseline_id": baseline_id,
            "base_revision": int(origin.get("base_revision") or 1),
            "new_or_changed_files": len(file_entries),
            "deletion_requests": len(deletion_entries),
            "size_bytes": destination.stat().st_size,
            "contains_credentials": False,
        }

    def inspect_return_package(
        self,
        package: Path,
        manifest: dict[str, object],
        *,
        target_site_id: str | None = None,
    ) -> dict[str, object]:
        target = self._resolve_target(
            str(manifest.get("site_uuid") or ""), target_site_id
        )
        with tempfile.TemporaryDirectory(
            prefix="netconsole-return-inspect-"
        ) as temporary:
            extracted = Path(temporary)
            _extract_selected(
                package,
                extracted,
                {
                    "return/databases/base/devices.db",
                    "return/databases/current/devices.db",
                    "return/databases/current/tasks.db",
                },
            )
            database_plan = _plan_database_merge(
                target.root_path / "db" / "devices.db",
                extracted / "return" / "databases" / "base" / "devices.db",
                extracted / "return" / "databases" / "current" / "devices.db",
            )
            task_preview = _preview_task_merge(
                target.root_path / "db" / "tasks.db",
                extracted / "return" / "databases" / "current" / "tasks.db",
                site_id=target.site_id,
            )

        file_hashes = {
            _sha256(item)
            for item in self._sync_candidate_files(target.root_path)
            if item.suffix.casefold() not in _DATABASE_SUFFIXES
        }
        entries = [
            item for item in manifest.get("file_entries", []) if isinstance(item, dict)
        ]
        duplicate_files = sum(
            1 for item in entries if str(item.get("sha256") or "") in file_hashes
        )
        new_files = len(entries) - duplicate_files
        conflicts = [item.to_public() for item in database_plan.conflicts]
        conflicts.extend(task_preview["conflicts"])
        local_metadata = self._read_metadata(target.root_path)
        base_revision = int(manifest.get("base_revision") or 1)
        local_revision = int(local_metadata.get("revision") or 1)
        estimated_bytes = sum(
            int(item.get("size_bytes") or 0)
            for item in entries
            if str(item.get("sha256") or "") not in file_hashes
        )
        return {
            "package_type": COLLECTION_RETURN,
            "site_id": target.site_id,
            "target_site_id": target.site_id,
            "site_name": target.display_name,
            "site_uuid": str(manifest.get("site_uuid") or ""),
            "site_identity_match": True,
            "base_revision": base_revision,
            "local_revision": local_revision,
            "new_files": new_files,
            "duplicate_files": duplicate_files,
            "new_tasks": task_preview["new_tasks"],
            "updated_tasks": task_preview["updated_tasks"],
            "new_records": database_plan.new_records,
            "updated_records": database_plan.updated_records,
            "duplicate_records": database_plan.duplicate_records,
            "unsupported_records": database_plan.unsupported_records,
            "deletion_requests": database_plan.deletion_requests
            + int(task_preview["deletion_requests"])
            + len(
                [
                    item
                    for item in manifest.get("deletions", [])
                    if isinstance(item, dict)
                ]
            ),
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "invalid_count": 0,
            "estimated_additional_bytes": estimated_bytes,
            "create_snapshot": True,
            "can_import": True,
        }

    def import_return_package(
        self,
        package: Path,
        manifest: dict[str, object],
        *,
        target_site_id: str | None,
        raw_only: bool,
        conflict_resolutions: Iterable[dict[str, object]],
    ) -> dict[str, object]:
        target = self._resolve_target(
            str(manifest.get("site_uuid") or ""), target_site_id
        )
        import_id = str(uuid.uuid4())
        resolution_map = {
            str(item.get("conflict_id") or ""): item
            for item in conflict_resolutions
            if isinstance(item, dict)
        }
        recovery = (
            self.paths.site_backups_dir(target.root_path.name)
            / f"sync-import-{import_id}"
        )
        created_files: list[Path] = []
        archived_files: list[Path] = []
        recovery.mkdir(parents=True, exist_ok=False)

        with tempfile.TemporaryDirectory(
            prefix="netconsole-return-import-"
        ) as temporary:
            extracted = Path(temporary)
            _extract_all(package, extracted)
            devices_base = extracted / "return" / "databases" / "base" / "devices.db"
            devices_returned = (
                extracted / "return" / "databases" / "current" / "devices.db"
            )
            tasks_returned = extracted / "return" / "databases" / "current" / "tasks.db"
            devices_local = target.root_path / "db" / "devices.db"
            tasks_local = target.root_path / "db" / "tasks.db"
            database_plan = _plan_database_merge(
                devices_local, devices_base, devices_returned
            )
            task_preview = _preview_task_merge(
                tasks_local, tasks_returned, site_id=target.site_id
            )
            unresolved = [
                conflict
                for conflict in [
                    *database_plan.conflicts,
                    *_task_conflicts(task_preview),
                ]
                if str(resolution_map.get(conflict.conflict_id, {}).get("choice") or "")
                not in {
                    "local",
                    "returned",
                    "manual",
                }
            ]
            if unresolved and not raw_only:
                shutil.rmtree(recovery, ignore_errors=True)
                _raise(
                    "SITE_IMPORT_CONFLICT",
                    "回传包仍有未处理冲突，请先在预检页面选择处理方式",
                )

            try:
                _copy_database(devices_local, recovery / "db" / "devices.db")
                if tasks_local.is_file():
                    _copy_database(tasks_local, recovery / "db" / "tasks.db")
                metadata_path = target.root_path / "site_meta.json"
                if metadata_path.is_file():
                    recovery.joinpath("site_meta.json").write_bytes(
                        metadata_path.read_bytes()
                    )

                file_result = self._merge_return_files(
                    target.root_path,
                    extracted,
                    manifest,
                    import_id,
                    created_files,
                    archived_files,
                )
                database_result = {
                    "new_records": 0,
                    "updated_records": 0,
                    "duplicate_records": 0,
                }
                task_result = {"new_tasks": 0, "updated_tasks": 0, "duplicate_tasks": 0}
                if not raw_only:
                    database_result = _apply_database_plan(
                        devices_local,
                        database_plan,
                        resolution_map,
                    )
                    task_result = _apply_task_merge(
                        tasks_local,
                        tasks_returned,
                        resolution_map,
                        site_id=target.site_id,
                    )

                metadata = self._read_metadata(target.root_path)
                metadata["revision"] = int(metadata.get("revision") or 1) + 1
                metadata["updated_at"] = _now()
                _atomic_json(metadata_path, metadata)
                audit = {
                    "format": "netconsole-site-sync-import",
                    "version": 1,
                    "import_id": import_id,
                    "package_id": str(manifest.get("package_id") or ""),
                    "site_uuid": str(manifest.get("site_uuid") or ""),
                    "base_revision": int(manifest.get("base_revision") or 1),
                    "applied_revision": metadata["revision"],
                    "source_machine_id": str(manifest.get("source_machine_id") or ""),
                    "created_at": _now(),
                    "raw_only": raw_only,
                    "files": file_result,
                    "database": database_result,
                    "tasks": task_result,
                    "deletion_requests_ignored": len(
                        [
                            item
                            for item in manifest.get("deletions", [])
                            if isinstance(item, dict)
                        ]
                    )
                    + database_plan.deletion_requests
                    + int(task_preview["deletion_requests"]),
                    "recovery_snapshot": recovery.relative_to(
                        target.root_path
                    ).as_posix(),
                }
                _atomic_json(
                    self.paths.site_sync_dir(target.root_path.name)
                    / "imports"
                    / f"{import_id}.json",
                    audit,
                )
                return {
                    "site_id": target.site_id,
                    "display_name": target.display_name,
                    "package_type": COLLECTION_RETURN,
                    "import_id": import_id,
                    "backup_created": True,
                    "requires_credentials": False,
                    **file_result,
                    **database_result,
                    **task_result,
                    "deletion_requests_ignored": audit["deletion_requests_ignored"],
                }
            except Exception:
                _restore_database(recovery / "db" / "devices.db", devices_local)
                if (recovery / "db" / "tasks.db").is_file():
                    _restore_database(recovery / "db" / "tasks.db", tasks_local)
                for path in reversed(created_files):
                    path.unlink(missing_ok=True)
                for path in reversed(archived_files):
                    path.unlink(missing_ok=True)
                if (recovery / "site_meta.json").is_file():
                    shutil.copy2(
                        recovery / "site_meta.json", target.root_path / "site_meta.json"
                    )
                raise

    def record_field_baseline(
        self,
        site_root: Path,
        manifest: dict[str, object],
    ) -> None:
        baseline_id = str(manifest.get("baseline_id") or "")
        if not baseline_id:
            _raise("SITE_SYNC_BASELINE_INVALID", "现场采集包缺少基准标识")
        baseline_root = self._baseline_root(site_root, baseline_id)
        baseline_root.mkdir(parents=True, exist_ok=False)
        devices = site_root / "db" / "devices.db"
        _copy_sanitized_database(devices, baseline_root / "devices.db")
        _atomic_json(
            baseline_root / "manifest.json",
            {
                "baseline_id": baseline_id,
                "site_uuid": str(manifest.get("site_uuid") or ""),
                "base_revision": int(manifest.get("base_revision") or 1),
                "baseline_files": dict(manifest.get("baseline_files") or {}),
                "source_package_id": str(manifest.get("package_id") or ""),
                "created_at": _now(),
            },
        )
        metadata = self._read_metadata(site_root)
        metadata["site_uuid"] = str(
            manifest.get("site_uuid") or metadata.get("site_uuid") or ""
        )
        metadata["revision"] = int(
            manifest.get("base_revision") or metadata.get("revision") or 1
        )
        metadata["sync_origin"] = {
            "baseline_id": baseline_id,
            "base_revision": int(manifest.get("base_revision") or 1),
            "source_package_id": str(manifest.get("package_id") or ""),
            "imported_at": _now(),
        }
        _atomic_json(site_root / "site_meta.json", metadata)

    def ensure_sync_identity(
        self,
        record: object,
        *,
        require_legacy_audit: bool,
    ) -> dict[str, object]:
        metadata = self._read_metadata(record.root_path)
        site_uuid = str(metadata.get("site_uuid") or "")
        if site_uuid:
            return {
                "site_uuid": site_uuid,
                "revision": int(metadata.get("revision") or 1),
            }
        if require_legacy_audit and str(record.site_id).startswith("legacy-"):
            from netconsole.services.site_lifecycle import SiteAuditService

            if not SiteAuditService(self.paths).latest(record.site_id):
                _raise(
                    "SITE_SYNC_AUDIT_REQUIRED",
                    "Legacy 局点必须先完成只读审计，才能建立跨电脑同步标识",
                )
        metadata["site_uuid"] = f"site-{uuid.uuid4()}"
        metadata["revision"] = max(1, int(metadata.get("revision") or 1))
        metadata["sync_schema_version"] = 1
        metadata["updated_at"] = _now()
        _atomic_json(record.root_path / "site_meta.json", metadata)
        return {
            "site_uuid": metadata["site_uuid"],
            "revision": metadata["revision"],
        }

    def _resolve_target(self, site_uuid: str, target_site_id: str | None) -> object:
        if not site_uuid:
            _raise("SITE_IMPORT_INVALID_PACKAGE", "数据包缺少稳定局点 UUID")
        if target_site_id:
            record = self.sites.registry.get(target_site_id)
            metadata = self._read_metadata(record.root_path)
            if str(metadata.get("site_uuid") or "") != site_uuid:
                _raise("SITE_IMPORT_SITE_MISMATCH", "数据包与所选局点 UUID 不一致")
            return record
        for record in self.sites.registry.list():
            metadata = self._read_metadata(record.root_path)
            if str(metadata.get("site_uuid") or "") == site_uuid:
                return record
        _raise("SITE_IMPORT_SITE_MISMATCH", "本机没有与回传包 UUID 匹配的局点")

    def _merge_return_files(
        self,
        site_root: Path,
        extracted: Path,
        manifest: dict[str, object],
        import_id: str,
        created_files: list[Path],
        archived_files: list[Path],
    ) -> dict[str, int]:
        existing_by_hash = {
            _sha256(item): item
            for item in self._sync_candidate_files(site_root)
            if item.suffix.casefold() not in _DATABASE_SUFFIXES
        }
        source_machine = _safe_component(
            str(manifest.get("source_machine_id") or "unknown")
        )
        imported = 0
        duplicates = 0
        renamed = 0
        for entry in manifest.get("file_entries", []):
            if not isinstance(entry, dict):
                continue
            digest = str(entry.get("sha256") or "")
            if digest in existing_by_hash:
                duplicates += 1
                continue
            relative = _safe_relative(str(entry.get("relative_path") or ""))
            payload = _safe_relative(str(entry.get("payload") or ""))
            source = (extracted / payload).resolve()
            if not source.is_file() or _sha256(source) != digest:
                _raise("SITE_IMPORT_CHECKSUM_FAILED", "回传文件完整性校验失败")
            desired = (site_root / relative).resolve()
            _require_inside(site_root, desired)
            target = desired
            if target.exists():
                target = (
                    site_root
                    / "files"
                    / "sync-imports"
                    / datetime.now().strftime("%Y-%m-%d")
                    / source_machine
                    / import_id
                    / relative
                ).resolve()
                _require_inside(site_root, target)
                renamed += 1
                archived_files.append(target)
            else:
                created_files.append(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            existing_by_hash[digest] = target
            imported += 1
        return {
            "new_files": imported,
            "duplicate_files": duplicates,
            "renamed_files": renamed,
        }

    def _manifest(
        self,
        *,
        record: object,
        identity: dict[str, object],
        package_type: str,
        checksums: dict[str, str],
        extra: dict[str, object],
    ) -> dict[str, object]:
        return {
            "format": PACKAGE_FORMAT,
            "format_version": PACKAGE_FORMAT_VERSION,
            "package_id": str(uuid.uuid4()),
            "package_type": package_type,
            "app_version": APP_VERSION.removeprefix("v"),
            "database_schema_version": _database_schema_version(
                record.root_path / "db" / "devices.db"
            ),
            "site_id": record.site_id,
            "site_uuid": identity["site_uuid"],
            "site_name": record.display_name,
            "site_revision": identity["revision"],
            "created_at": _now(),
            "source_platform": "windows" if os.name == "nt" else os.name,
            "source_machine_id": self._installation_id(),
            "checksums": checksums,
            "contains_credentials": False,
            **extra,
        }

    def _write_package(
        self,
        temp_root: Path,
        destination: Path,
        manifest: dict[str, object],
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            _atomic_json(temp_root / "manifest.json", manifest)
            _atomic_json(temp_root / "checksums.json", manifest["checksums"])
            (temp_root / "README.txt").write_text(
                "NetConsole 局点数据包；不包含本机设置、Token、密码或设备凭据。\n",
                encoding="utf-8",
            )
            with zipfile.ZipFile(
                staging, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for item in temp_root.rglob("*"):
                    if item.is_file():
                        archive.write(item, item.relative_to(temp_root).as_posix())
            os.replace(staging, destination)
        finally:
            staging.unlink(missing_ok=True)

    def _copy_package_files(
        self,
        files: Iterable[Path],
        root: Path,
        target_root: Path,
        *,
        check_cancel: Callable[[], None] | None,
    ) -> dict[str, str]:
        checksums: dict[str, str] = {}
        for source in files:
            if check_cancel:
                check_cancel()
            relative = source.relative_to(root)
            target = target_root / relative
            if source.suffix.casefold() in _DATABASE_SUFFIXES:
                _copy_sanitized_database(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            checksums[f"site/{relative.as_posix()}"] = _sha256(target)
        return checksums

    def _field_collection_files(self, site_root: Path) -> Iterable[Path]:
        allowed_exact = {
            "site_meta.json",
            "db/devices.db",
            "files/rail_transit/car_network/parsed/point_table.json",
        }
        for item in self._sync_candidate_files(site_root):
            relative = item.relative_to(site_root).as_posix()
            if (
                relative in allowed_exact
                or relative.startswith("config_center/")
                or relative.startswith("files/config_center/")
            ):
                yield item

    def _sync_candidate_files(self, site_root: Path) -> Iterable[Path]:
        for item in site_root.rglob("*"):
            if not item.is_file() or item.is_symlink():
                continue
            relative = item.relative_to(site_root)
            parts = {part.casefold() for part in relative.parts}
            if parts & _EXCLUDED_PARTS:
                continue
            if (
                item.name.endswith((".tmp", ".lock", ".part", "-wal", "-shm"))
                or ".db-" in item.name
            ):
                continue
            yield item

    def _baseline_root(self, site_root: Path, baseline_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(baseline_id))
        except ValueError:
            _raise("SITE_SYNC_BASELINE_INVALID", "现场采集基准标识无效")
        root = (
            self.paths.site_sync_dir(site_root.name) / "baselines" / normalized
        ).resolve()
        _require_inside(site_root, root)
        return root

    def _read_metadata(self, site_root: Path) -> dict[str, object]:
        path = site_root / "site_meta.json"
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _raise("SITE_SYNC_METADATA_INVALID", "局点同步元数据无效，不能覆盖原文件")
            raise AssertionError("unreachable") from exc
        if not isinstance(value, dict):
            _raise("SITE_SYNC_METADATA_INVALID", "局点同步元数据无效，不能覆盖原文件")
        return value

    def _installation_id(self) -> str:
        path = self.paths.config_dir / "installation_identity.json"
        value = _read_json(path)
        installation_id = str(value.get("installation_id") or "")
        try:
            return str(uuid.UUID(installation_id))
        except ValueError:
            installation_id = str(uuid.uuid4())
            _atomic_json(
                path,
                {
                    "installation_id": installation_id,
                    "created_at": _now(),
                },
            )
            return installation_id


def _plan_database_merge(local: Path, base: Path, returned: Path) -> DatabaseMergePlan:
    if not local.is_file() or not base.is_file() or not returned.is_file():
        _raise("SITE_SYNC_DATABASE_INVALID", "回传包主数据库副本不完整")
    actions: list[MergeAction] = []
    conflicts: list[MergeConflict] = []
    new_records = 0
    updated_records = 0
    duplicate_records = 0
    deletion_requests = 0
    unsupported_records = 0
    with (
        closing(connect_sqlite(local)) as local_db,
        closing(connect_sqlite(base)) as base_db,
        closing(connect_sqlite(returned)) as returned_db,
    ):
        local_db.row_factory = sqlite3.Row
        base_db.row_factory = sqlite3.Row
        returned_db.row_factory = sqlite3.Row
        tables = _table_names(returned_db)
        for table in sorted(tables):
            key_columns = _MERGE_TABLES.get(table)
            if not key_columns:
                if table not in {"schema_metadata", "sqlite_sequence"}:
                    unsupported_records += _table_count(returned_db, table)
                continue
            if table not in _table_names(local_db) or table not in _table_names(
                base_db
            ):
                unsupported_records += _table_count(returned_db, table)
                continue
            base_rows = _rows_by_key(base_db, table, key_columns)
            local_rows = _rows_by_key(local_db, table, key_columns)
            returned_rows = _rows_by_key(returned_db, table, key_columns)
            for key in sorted(
                set(base_rows) | set(returned_rows), key=lambda value: repr(value)
            ):
                base_row = base_rows.get(key)
                local_row = local_rows.get(key)
                returned_row = returned_rows.get(key)
                entity_id = "|".join(str(value) for value in key)
                if returned_row is None:
                    if base_row is not None:
                        deletion_requests += 1
                    continue
                if base_row is None:
                    if local_row is None:
                        insert_values = _writable_row(returned_row)
                        actions.append(
                            MergeAction(table, key_columns, key, insert_values, {})
                        )
                        new_records += 1
                    elif _comparable_row(local_row) == _comparable_row(returned_row):
                        duplicate_records += 1
                    else:
                        conflicts.extend(
                            _row_conflicts(
                                table, entity_id, {}, local_row, returned_row
                            )
                        )
                    continue
                if local_row is None:
                    conflicts.append(
                        _conflict(
                            table, entity_id, "__entity__", base_row, None, returned_row
                        )
                    )
                    continue
                updates: dict[str, object] = {}
                row_conflicts: list[MergeConflict] = []
                fields = sorted(set(base_row) | set(local_row) | set(returned_row))
                for field in fields:
                    if field in {"id", *key_columns, *_CREDENTIAL_COLUMNS}:
                        continue
                    base_value = base_row.get(field)
                    local_value = local_row.get(field)
                    returned_value = returned_row.get(field)
                    if returned_value == base_value:
                        continue
                    if local_value == returned_value:
                        continue
                    if local_value == base_value:
                        updates[field] = returned_value
                    else:
                        row_conflicts.append(
                            _conflict(
                                table,
                                entity_id,
                                field,
                                base_value,
                                local_value,
                                returned_value,
                            )
                        )
                if updates:
                    actions.append(MergeAction(table, key_columns, key, None, updates))
                    updated_records += 1
                elif not row_conflicts:
                    duplicate_records += 1
                conflicts.extend(row_conflicts)
    return DatabaseMergePlan(
        tuple(actions),
        tuple(conflicts),
        new_records,
        updated_records,
        duplicate_records,
        deletion_requests,
        unsupported_records,
    )


def _apply_database_plan(
    local: Path,
    plan: DatabaseMergePlan,
    resolutions: dict[str, dict[str, object]],
) -> dict[str, int]:
    actions_by_entity: dict[tuple[str, str], dict[str, object]] = {}
    for conflict in plan.conflicts:
        resolution = resolutions.get(conflict.conflict_id, {})
        choice = str(resolution.get("choice") or "")
        if choice == "local":
            continue
        value = (
            resolution.get("manual_value")
            if choice == "manual"
            else conflict.returned_value
        )
        actions_by_entity.setdefault((conflict.entity_type, conflict.entity_id), {})[
            conflict.field
        ] = value

    inserted = 0
    updated = 0
    with closing(connect_sqlite(local)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        try:
            for action in plan.actions:
                if action.insert_values is not None:
                    values = dict(action.insert_values)
                    columns = sorted(values)
                    connection.execute(
                        f"INSERT INTO {_quote(action.table)} ({', '.join(_quote(column) for column in columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})",
                        [values[column] for column in columns],
                    )
                    inserted += 1
                if action.update_values:
                    _update_row(connection, action, action.update_values)
                    updated += 1
            for (table, entity_id), values in actions_by_entity.items():
                if "__entity__" in values:
                    continue
                spec = _MERGE_TABLES.get(table)
                if not spec:
                    continue
                key = tuple(entity_id.split("|"))
                action = MergeAction(table, spec, key, None, values)
                _update_row(connection, action, values)
                updated += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "new_records": inserted,
        "updated_records": updated,
        "duplicate_records": plan.duplicate_records,
    }


def _preview_task_merge(
    local: Path,
    returned: Path,
    *,
    site_id: str = "",
) -> dict[str, object]:
    if not returned.is_file():
        return {
            "new_tasks": 0,
            "updated_tasks": 0,
            "duplicate_tasks": 0,
            "deletion_requests": 0,
            "conflicts": [],
        }
    local_rows = _task_rows(local) if local.is_file() else {}
    returned_rows = _task_rows(returned)
    new_tasks = 0
    updated_tasks = 0
    duplicates = 0
    conflicts: list[dict[str, object]] = []
    for task_id, returned_row in returned_rows.items():
        local_row = local_rows.get(task_id)
        if local_row is None:
            new_tasks += 1
        elif _comparable_row(local_row) == _comparable_row(returned_row):
            duplicates += 1
        elif _prefer_returned_task(local_row, returned_row):
            updated_tasks += 1
        else:
            conflicts.append(
                _conflict(
                    "task",
                    task_id,
                    "result",
                    None,
                    _task_summary(local_row),
                    _task_summary(returned_row),
                ).to_public()
            )
    with closing(connect_sqlite(returned)) as returned_db:
        returned_db.row_factory = sqlite3.Row
        local_context = (
            closing(connect_sqlite(local))
            if local.is_file()
            else closing(sqlite3.connect(":memory:"))
        )
        with local_context as local_db:
            local_db.row_factory = sqlite3.Row
            task_ids = set(local_rows) | set(returned_rows)
            _validate_task_merge_references(
                local_db,
                returned_db,
                task_ids=task_ids,
                site_id=site_id,
            )
            conflicts.extend(
                item.to_public()
                for item in _immutable_task_conflicts(local_db, returned_db)
            )
    return {
        "new_tasks": new_tasks,
        "updated_tasks": updated_tasks,
        "duplicate_tasks": duplicates,
        "deletion_requests": 0,
        "conflicts": conflicts,
    }


def _apply_task_merge(
    local: Path,
    returned: Path,
    resolutions: dict[str, dict[str, object]],
    *,
    site_id: str = "",
) -> dict[str, int]:
    if not returned.is_file():
        return {"new_tasks": 0, "updated_tasks": 0, "duplicate_tasks": 0}
    from netconsole.repositories.online_mr_task_session_repository import (
        OnlineMrTaskSessionRepository,
    )
    from netconsole.repositories.task_repository import TaskRepository

    TaskRepository(local).initialize()
    OnlineMrTaskSessionRepository(local, site_id=site_id or "demo").initialize()
    inserted = 0
    updated = 0
    duplicates = 0
    with (
        closing(connect_sqlite(local, foreign_keys=True)) as local_db,
        closing(connect_sqlite(returned)) as returned_db,
    ):
        local_db.row_factory = sqlite3.Row
        returned_db.row_factory = sqlite3.Row
        local_db.execute("PRAGMA foreign_keys = ON")
        local_db.execute("BEGIN IMMEDIATE")
        try:
            local_rows = _task_rows_from_connection(local_db)
            returned_rows = _task_rows_from_connection(returned_db)
            task_ids = set(local_rows) | set(returned_rows)
            _validate_task_merge_references(
                local_db,
                returned_db,
                task_ids=task_ids,
                site_id=site_id,
            )
            immutable_conflicts = _immutable_task_conflicts(local_db, returned_db)
            if immutable_conflicts:
                conflict = immutable_conflicts[0]
                _raise(
                    "SITE_IMPORT_TASK_CONFLICT",
                    f"回传任务数据存在不可覆盖冲突：{conflict.entity_type}/{conflict.entity_id}",
                )

            for returned_result in _rows_for_table(
                returned_db, "task_results", order_by="result_id"
            ):
                result_id = str(returned_result.get("result_id") or "")
                existing = _row_by_key(local_db, "task_results", "result_id", result_id)
                if existing is not None:
                    continue
                _insert_compatible_row(
                    local_db,
                    "task_results",
                    returned_result,
                    skip=set(),
                )

            for task_id, returned_row in returned_rows.items():
                local_row = local_rows.get(task_id)
                if local_row is None:
                    _insert_compatible_row(
                        local_db, "task_snapshots", returned_row, skip={"sequence"}
                    )
                    inserted += 1
                    continue
                if _comparable_row(local_row) == _comparable_row(returned_row):
                    duplicates += 1
                    continue
                conflict = _conflict(
                    "task",
                    task_id,
                    "result",
                    None,
                    _task_summary(local_row),
                    _task_summary(returned_row),
                )
                resolution = resolutions.get(conflict.conflict_id, {})
                if (
                    _prefer_returned_task(local_row, returned_row)
                    or resolution.get("choice") == "returned"
                ):
                    _replace_row(local_db, "task_snapshots", returned_row, ("task_id",))
                    updated += 1
            for event in _rows_for_table(
                returned_db, "task_events", order_by="sequence"
            ):
                event_id = str(event.get("event_id") or "")
                existing = _row_by_key(local_db, "task_events", "event_id", event_id)
                if existing is not None:
                    continue
                _insert_compatible_row(
                    local_db, "task_events", event, skip={"sequence"}
                )

            for mapping in _rows_for_table(
                returned_db,
                "online_mr_task_sessions",
                order_by="controller_task_id",
            ):
                controller_task_id = str(mapping.get("controller_task_id") or "")
                existing = _row_by_key(
                    local_db,
                    "online_mr_task_sessions",
                    "controller_task_id",
                    controller_task_id,
                )
                if existing is not None:
                    continue
                _insert_compatible_row(
                    local_db,
                    "online_mr_task_sessions",
                    mapping,
                    skip=set(),
                )
            local_db.commit()
        except Exception:
            local_db.rollback()
            raise
    return {
        "new_tasks": inserted,
        "updated_tasks": updated,
        "duplicate_tasks": duplicates,
    }


def _immutable_task_conflicts(
    local_db: sqlite3.Connection,
    returned_db: sqlite3.Connection,
) -> list[MergeConflict]:
    conflicts: list[MergeConflict] = []
    for returned_result in _rows_for_table(returned_db, "task_results"):
        result_id = str(returned_result.get("result_id") or "")
        local_result = _row_by_key(local_db, "task_results", "result_id", result_id)
        if local_result is not None and _result_semantics(
            local_result
        ) != _result_semantics(returned_result):
            conflicts.append(
                _conflict(
                    "task_result",
                    result_id,
                    "immutable_content",
                    None,
                    _result_summary(local_result),
                    _result_summary(returned_result),
                )
            )

    for returned_event in _rows_for_table(returned_db, "task_events"):
        event_id = str(returned_event.get("event_id") or "")
        local_event = _row_by_key(local_db, "task_events", "event_id", event_id)
        if local_event is not None and _event_semantics(
            local_event
        ) != _event_semantics(returned_event):
            conflicts.append(
                _conflict(
                    "task_event",
                    event_id,
                    "immutable_content",
                    None,
                    _event_semantics(local_event),
                    _event_semantics(returned_event),
                )
            )

    local_mappings = {
        str(row.get("controller_task_id") or ""): row
        for row in _rows_for_table(local_db, "online_mr_task_sessions")
    }
    returned_mappings = _rows_for_table(returned_db, "online_mr_task_sessions")
    for returned_mapping in returned_mappings:
        controller_task_id = str(returned_mapping.get("controller_task_id") or "")
        local_mapping = local_mappings.get(controller_task_id)
        if local_mapping is not None and _mapping_semantics(
            local_mapping
        ) != _mapping_semantics(returned_mapping):
            conflicts.append(
                _conflict(
                    "online_mr_task_session",
                    controller_task_id,
                    "immutable_mapping",
                    None,
                    _mapping_summary(local_mapping),
                    _mapping_summary(returned_mapping),
                )
            )

    combined_mappings = [*local_mappings.values(), *returned_mappings]
    conflicts.extend(_mapping_identity_conflicts(combined_mappings))
    unique: dict[str, MergeConflict] = {}
    for conflict in conflicts:
        unique.setdefault(conflict.conflict_id, conflict)
    return list(unique.values())


def _validate_task_merge_references(
    local_db: sqlite3.Connection,
    returned_db: sqlite3.Connection,
    *,
    task_ids: set[str],
    site_id: str,
) -> None:
    from netconsole.repositories.task_repository import TaskRepository

    local_results = {
        str(row.get("result_id") or ""): row
        for row in _rows_for_table(local_db, "task_results")
    }
    returned_results = {
        str(row.get("result_id") or ""): row
        for row in _rows_for_table(returned_db, "task_results")
    }
    for result_id, row in returned_results.items():
        if not result_id:
            _raise(
                "SITE_IMPORT_TASK_RESULT_INVALID", "回传 task_results 缺少 result_id"
            )
        try:
            TaskRepository._verified_result_row(row)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            _raise(
                "SITE_IMPORT_TASK_RESULT_INVALID",
                f"回传 task_results 身份校验失败：{result_id} ({exc})",
            )
        if str(row.get("task_id") or "") not in task_ids:
            _raise(
                "SITE_IMPORT_TASK_REFERENCE_INVALID",
                f"task_results 引用了不存在的任务：{row.get('task_id')}",
            )

    available_results = {**local_results, **returned_results}
    for snapshot in _rows_for_table(returned_db, "task_snapshots"):
        _validate_result_reference(snapshot, available_results, owner="task_snapshots")
    for event in _rows_for_table(returned_db, "task_events"):
        task_id = str(event.get("task_id") or "")
        if task_id not in task_ids:
            _raise(
                "SITE_IMPORT_TASK_REFERENCE_INVALID",
                f"task_events 引用了不存在的任务：{task_id}",
            )
        payload = _json_object_strict(event.get("payload_json"), owner="task_events")
        _validate_result_reference(payload, available_results, owner="task_events")

    mappings = _rows_for_table(returned_db, "online_mr_task_sessions")
    for mapping in mappings:
        controller_task_id = str(mapping.get("controller_task_id") or "")
        if controller_task_id not in task_ids:
            _raise(
                "SITE_IMPORT_TASK_REFERENCE_INVALID",
                f"Online MR mapping 引用了不存在的 Controller task：{controller_task_id}",
            )
        mapping_site = str(mapping.get("site_id") or "")
        if site_id and mapping_site != site_id:
            _raise(
                "SITE_IMPORT_TASK_REFERENCE_INVALID",
                f"Online MR mapping 局点不匹配：{mapping_site}",
            )
        agent_id = str(mapping.get("agent_id") or "")
        agent_task_id = str(mapping.get("agent_task_id") or "")
        if bool(agent_id) != bool(agent_task_id):
            _raise(
                "SITE_IMPORT_TASK_REFERENCE_INVALID",
                f"Online MR Agent task 引用不完整：{controller_task_id}",
            )


def _validate_result_reference(
    values: dict[str, object],
    results: dict[str, dict[str, object]],
    *,
    owner: str,
) -> None:
    result_id = str(values.get("result_id") or "")
    result_hash = str(values.get("result_hash") or "")
    if not result_id and not result_hash:
        return
    if not result_id or not result_hash:
        _raise(
            "SITE_IMPORT_TASK_REFERENCE_INVALID",
            f"{owner} 的 result_id/result_hash 引用不完整",
        )
    result = results.get(result_id)
    if result is None or str(result.get("sha256") or "") != result_hash:
        _raise(
            "SITE_IMPORT_TASK_REFERENCE_INVALID",
            f"{owner} 引用了不存在或 hash 不匹配的 task_result：{result_id}",
        )
    owner_task_id = str(values.get("task_id") or "")
    if owner_task_id and str(result.get("task_id") or "") != owner_task_id:
        _raise(
            "SITE_IMPORT_TASK_REFERENCE_INVALID",
            f"{owner} 的 task_result 不属于当前任务：{result_id}",
        )


def _mapping_identity_conflicts(
    mappings: list[dict[str, object]],
) -> list[MergeConflict]:
    conflicts: list[MergeConflict] = []
    seen_sessions: dict[str, str] = {}
    seen_agent_tasks: dict[tuple[str, str], str] = {}
    for mapping in mappings:
        controller_task_id = str(mapping.get("controller_task_id") or "")
        session_id = str(mapping.get("session_id") or "")
        if session_id:
            previous = seen_sessions.setdefault(session_id, controller_task_id)
            if previous != controller_task_id:
                conflicts.append(
                    _conflict(
                        "online_mr_task_session",
                        session_id,
                        "session_id",
                        None,
                        previous,
                        controller_task_id,
                    )
                )
        agent_id = str(mapping.get("agent_id") or "")
        agent_task_id = str(mapping.get("agent_task_id") or "")
        if agent_id and agent_task_id:
            identity = (agent_id, agent_task_id)
            previous = seen_agent_tasks.setdefault(identity, controller_task_id)
            if previous != controller_task_id:
                conflicts.append(
                    _conflict(
                        "online_mr_task_session",
                        f"{agent_id}/{agent_task_id}",
                        "agent_task_id",
                        None,
                        previous,
                        controller_task_id,
                    )
                )
    return conflicts


def _rows_for_table(
    connection: sqlite3.Connection,
    table: str,
    *,
    order_by: str = "",
) -> list[dict[str, object]]:
    if table not in _table_names(connection):
        return []
    order = f" ORDER BY {_quote(order_by)}" if order_by else ""
    return [
        dict(row) for row in connection.execute(f"SELECT * FROM {_quote(table)}{order}")
    ]


def _row_by_key(
    connection: sqlite3.Connection,
    table: str,
    key: str,
    value: object,
) -> dict[str, object] | None:
    if table not in _table_names(connection):
        return None
    row = connection.execute(
        f"SELECT * FROM {_quote(table)} WHERE {_quote(key)} = ? LIMIT 1",
        (value,),
    ).fetchone()
    return dict(row) if row is not None else None


def _insert_compatible_row(
    connection: sqlite3.Connection,
    table: str,
    row: dict[str, object],
    *,
    skip: set[str],
) -> None:
    writable_columns = {
        str(item[1])
        for item in connection.execute(f"PRAGMA table_info({_quote(table)})")
    }
    values = {
        key: value
        for key, value in row.items()
        if key not in skip and key in writable_columns
    }
    columns = sorted(values)
    connection.execute(
        f"INSERT INTO {_quote(table)} ({', '.join(_quote(column) for column in columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        [values[column] for column in columns],
    )


def _result_semantics(row: dict[str, object]) -> dict[str, object]:
    return {
        key: row.get(key)
        for key in (
            "result_id",
            "task_id",
            "terminal_event_type",
            "canonical_json",
            "sha256",
            "byte_size",
            "schema_version",
        )
    }


def _result_summary(row: dict[str, object]) -> dict[str, object]:
    return {
        "result_id": row.get("result_id"),
        "task_id": row.get("task_id"),
        "terminal_event_type": row.get("terminal_event_type"),
        "sha256": row.get("sha256"),
        "byte_size": row.get("byte_size"),
        "schema_version": row.get("schema_version"),
    }


def _event_semantics(row: dict[str, object]) -> dict[str, object]:
    return {
        "event_id": row.get("event_id"),
        "task_id": row.get("task_id"),
        "event_type": row.get("event_type"),
        "event_time": row.get("event_time"),
        "source": row.get("source"),
        "payload": _json_object_strict(row.get("payload_json"), owner="task_events"),
    }


def _mapping_semantics(row: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items()}


def _mapping_summary(row: dict[str, object]) -> dict[str, object]:
    return {
        "controller_task_id": row.get("controller_task_id"),
        "session_id": row.get("session_id"),
        "site_id": row.get("site_id"),
        "executor_kind": row.get("executor_kind"),
        "agent_id": row.get("agent_id"),
        "agent_task_id": row.get("agent_task_id"),
        "phase": row.get("phase"),
        "mapping_state": row.get("mapping_state"),
        "updated_at": row.get("updated_at"),
    }


def _json_object_strict(value: object, *, owner: str) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        _raise("SITE_IMPORT_TASK_REFERENCE_INVALID", f"{owner} JSON 无效：{exc}")
    if not isinstance(parsed, dict):
        _raise("SITE_IMPORT_TASK_REFERENCE_INVALID", f"{owner} JSON 必须是对象")
    return dict(parsed)


def _task_conflicts(preview: dict[str, object]) -> list[MergeConflict]:
    values: list[MergeConflict] = []
    for item in preview.get("conflicts", []):
        if not isinstance(item, dict):
            continue
        values.append(
            MergeConflict(
                conflict_id=str(item.get("conflict_id") or ""),
                entity_type=str(item.get("entity_type") or "task"),
                entity_id=str(item.get("entity_id") or ""),
                field=str(item.get("field") or "result"),
                base_value=item.get("base_value"),
                local_value=item.get("local_value"),
                returned_value=item.get("returned_value"),
            )
        )
    return values


def _task_rows(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    with closing(connect_sqlite(path)) as connection:
        connection.row_factory = sqlite3.Row
        return _task_rows_from_connection(connection)


def _task_rows_from_connection(
    connection: sqlite3.Connection,
) -> dict[str, dict[str, object]]:
    if "task_snapshots" not in _table_names(connection):
        return {}
    return {
        str(row["task_id"]): dict(row)
        for row in connection.execute("SELECT * FROM task_snapshots")
    }


def _prefer_returned_task(
    local: dict[str, object], returned: dict[str, object]
) -> bool:
    local_priority = _TASK_STATUS_PRIORITY.get(
        str(local.get("status") or "").upper(), 0
    )
    returned_priority = _TASK_STATUS_PRIORITY.get(
        str(returned.get("status") or "").upper(), 0
    )
    if returned_priority != local_priority:
        return returned_priority > local_priority
    return _nonempty_score(returned) > _nonempty_score(local)


def _task_summary(row: dict[str, object]) -> dict[str, object]:
    return {
        "status": row.get("status"),
        "progress": row.get("progress"),
        "finished_time": row.get("finished_time"),
        "result_json": row.get("result_json"),
        "error_message": row.get("error_message"),
    }


def _nonempty_score(row: dict[str, object]) -> int:
    return sum(value not in (None, "", "{}", "[]", 0) for value in row.values())


def _row_conflicts(
    table: str,
    entity_id: str,
    base: dict[str, object],
    local: dict[str, object],
    returned: dict[str, object],
) -> list[MergeConflict]:
    return [
        _conflict(
            table,
            entity_id,
            field,
            base.get(field),
            local.get(field),
            returned.get(field),
        )
        for field in sorted(set(local) | set(returned))
        if field not in {"id", *_CREDENTIAL_COLUMNS}
        and local.get(field) != returned.get(field)
    ]


def _conflict(
    entity_type: str,
    entity_id: str,
    field: str,
    base_value: object,
    local_value: object,
    returned_value: object,
) -> MergeConflict:
    digest = hashlib.sha256(
        f"{entity_type}\0{entity_id}\0{field}".encode("utf-8")
    ).hexdigest()[:20]
    return MergeConflict(
        conflict_id=f"conflict-{digest}",
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        base_value=base_value,
        local_value=local_value,
        returned_value=returned_value,
    )


def _rows_by_key(
    connection: sqlite3.Connection,
    table: str,
    key_columns: tuple[str, ...],
) -> dict[tuple[object, ...], dict[str, object]]:
    rows: dict[tuple[object, ...], dict[str, object]] = {}
    for row in connection.execute(f"SELECT * FROM {_quote(table)}"):
        value = dict(row)
        key = tuple(value.get(column) for column in key_columns)
        if any(item in (None, "") for item in key):
            continue
        rows[key] = value
    return rows


def _writable_row(row: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in row.items()
        if key != "id" and key not in _CREDENTIAL_COLUMNS
    }


def _comparable_row(row: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in row.items()
        if key != "id" and key not in _CREDENTIAL_COLUMNS
    }


def _update_row(
    connection: sqlite3.Connection,
    action: MergeAction,
    values: dict[str, object],
) -> None:
    clean = {
        key: value
        for key, value in values.items()
        if key not in {"id", *action.key_columns}
    }
    if not clean:
        return
    columns = sorted(clean)
    connection.execute(
        f"UPDATE {_quote(action.table)} SET "
        f"{', '.join(f'{_quote(column)} = ?' for column in columns)} "
        f"WHERE {' AND '.join(f'{_quote(column)} = ?' for column in action.key_columns)}",
        [clean[column] for column in columns] + list(action.key_values),
    )


def _insert_row(
    connection: sqlite3.Connection,
    table: str,
    row: dict[str, object],
    *,
    skip: set[str],
) -> None:
    values = {key: value for key, value in row.items() if key not in skip}
    columns = sorted(values)
    connection.execute(
        f"INSERT INTO {_quote(table)} ({', '.join(_quote(column) for column in columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})",
        [values[column] for column in columns],
    )


def _replace_row(
    connection: sqlite3.Connection,
    table: str,
    row: dict[str, object],
    key_columns: tuple[str, ...],
) -> None:
    values = {key: value for key, value in row.items() if key not in key_columns}
    columns = sorted(values)
    connection.execute(
        f"UPDATE {_quote(table)} SET {', '.join(f'{_quote(column)} = ?' for column in columns)} "
        f"WHERE {' AND '.join(f'{_quote(column)} = ?' for column in key_columns)}",
        [values[column] for column in columns]
        + [row[column] for column in key_columns],
    )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(
        connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
    )


def _quote(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError("invalid SQLite identifier")
    return f'"{identifier}"'


def _database_schema_version(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        with closing(connect_sqlite(path)) as connection:
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
        return str(row[0]) if row else ""
    except sqlite3.DatabaseError:
        return ""


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = connect_sqlite(source, row_factory=False)
    target_connection = connect_sqlite(target, row_factory=False)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _copy_sanitized_database(source: Path, target: Path) -> int:
    _copy_database(source, target)
    with closing(connect_sqlite(target)) as connection:
        if "devices" not in _table_names(connection):
            return 0
        count = sanitize_device_credentials_for_package(connection)
        connection.commit()
        return count


def _database_credential_reentry_count(database: Path) -> int:
    if not database.is_file():
        return 0
    with closing(connect_sqlite(database)) as connection:
        return credential_reentry_count(connection)


def _restore_database(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(connect_sqlite(source, row_factory=False)) as source_connection,
        closing(connect_sqlite(target, row_factory=False)) as target_connection,
    ):
        source_connection.backup(target_connection)


def _extract_selected(package: Path, target: Path, selected: set[str]) -> None:
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        for name in selected & names:
            destination = (target / _safe_relative(name)).resolve()
            _require_inside(target, destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _extract_all(package: Path, target: Path) -> None:
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            relative = _safe_relative(info.filename.rstrip("/"))
            destination = (target / relative).resolve()
            _require_inside(target, destination)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> Path:
    normalized = str(value or "").replace("\\", "/").strip("/")
    if (
        not normalized
        or normalized.startswith("/")
        or normalized.startswith("//")
        or len(normalized) >= 2
        and normalized[1] == ":"
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        _raise("SITE_IMPORT_INVALID_PACKAGE", "数据包包含不安全路径")
    return Path(normalized)


def _require_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        _raise("SITE_IMPORT_INVALID_PACKAGE", "数据包路径越界")


def _safe_component(value: str) -> str:
    normalized = "".join(
        character
        for character in value
        if character.isalnum() or character in {"-", "_"}
    )
    return normalized[:80] or "unknown"


def _task_id_from_path(relative: str) -> str:
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        if part.casefold() in {"sessions", "runs"} and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _with_suffix(destination: Path, suffix: str) -> Path:
    value = Path(destination).expanduser().resolve()
    return value if value.suffix.casefold() == suffix else value.with_suffix(suffix)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _raise(code: str, message: str) -> None:
    from netconsole.services.site_storage import SiteStorageError

    raise SiteStorageError(code, message)


__all__ = [
    "COLLECTION_RETURN",
    "FIELD_COLLECTION",
    "FULL_MIGRATION",
    "SANITIZED_SHARE",
    "PACKAGE_FORMAT",
    "PACKAGE_FORMAT_VERSION",
    "PACKAGE_TYPES",
    "SiteSyncService",
]
