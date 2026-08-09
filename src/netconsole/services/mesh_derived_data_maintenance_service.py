from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable, Mapping
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import MeshSchemaRebuildRequired, SCHEMA_VERSION
from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]

_JOURNAL_SCHEMA_VERSION = 1
_OPERATION_KINDS = frozenset(
    {
        "mesh_log_import",
        "mesh_bundle_import",
        "mesh_local_scan_import",
    }
)
_PENDING_OPERATION_STATES = frozenset({"waiting_repair", "repairing"})


class MeshDerivedDataMaintenanceError(RuntimeError):
    """派生数据自动维护无法安全完成。"""


class MeshRepairMode(StrEnum):
    SCHEMA_MIGRATION = "SCHEMA_MIGRATION"
    EMPTY_DATABASE_RECREATE = "EMPTY_DATABASE_RECREATE"
    PARTIAL_SOURCE_REBUILD = "PARTIAL_SOURCE_REBUILD"


class MeshDerivedDatabaseIncompatible(MeshSchemaRebuildRequired):
    """携带局点和 schema 版本信息的兼容性错误。"""

    def __init__(
        self,
        *,
        site_id: str,
        current_version: str,
        required_version: str = SCHEMA_VERSION,
        repair_mode: str = "rebuild",
        recoverable: bool = True,
    ) -> None:
        self.site_id = str(site_id)
        self.current_version = str(current_version or "unknown")
        self.required_version = str(required_version)
        self.repair_mode = str(repair_mode)
        self.recoverable = bool(recoverable)
        super().__init__("当前局点的 MESH 分析数据库版本不兼容，系统将自动修复。")


@dataclass(frozen=True)
class MeshDerivedProfileInspection:
    mr_id: str
    display_name: str
    safe_folder_name: str
    current_version: str
    required_version: str
    status: str
    raw_file_count: int
    repair_mode: str = ""
    detail: str = ""
    registered_source_count: int = 0
    missing_source_count: int = 0
    registered_raw_file_count: int = 0
    missing_sources: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "mr_id": self.mr_id,
            "display_name": self.display_name,
            "safe_folder_name": self.safe_folder_name,
            "current_version": self.current_version,
            "required_version": self.required_version,
            "status": self.status,
            "raw_file_count": self.raw_file_count,
            "repair_mode": self.repair_mode,
            "detail": self.detail,
            "registered_source_count": self.registered_source_count,
            "missing_source_count": self.missing_source_count,
            "registered_raw_file_count": self.registered_raw_file_count,
            "missing_sources": [dict(item) for item in self.missing_sources],
        }


class MeshDerivedDataMaintenanceService:
    """局点级 MESH 派生库检查、重建和等待操作持久化。

    当前没有可证明安全的跨 compact schema 增量迁移规则，因此只对不兼容
    的 MR 采用已有的可回滚重建服务。新建 MR 尚未生成 index 时不触发维护。
    """

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def inspect(
        self,
        site_id: str,
        *,
        profile_ids: Iterable[str] | None = None,
    ) -> dict[str, object]:
        site = str(site_id)
        selected = None if profile_ids is None else {str(value) for value in profile_ids if str(value)}
        entries: list[MeshDerivedProfileInspection] = []
        catalog_path = self.paths.mesh_catalog_path(site)
        profiles = MeshCatalogRepository(catalog_path).list_profiles() if catalog_path.is_file() else []
        for profile in profiles:
            if selected is not None and profile.mr_id not in selected:
                continue
            index_path = self.paths.mesh_mr_db_path(site, profile.safe_folder_name).resolve()
            raw_root = self.paths.mesh_mr_raw_dir(site, profile.safe_folder_name).resolve()
            raw_files = self._raw_files(raw_root)
            current_version = self._schema_version(index_path)
            registered_source_count = self._registered_source_count(index_path)
            registered_sources = self._registered_sources(index_path, raw_root)
            registered_raw_files = [
                raw_path
                for item in registered_sources
                if isinstance((raw_path := item.get("raw_path")), Path)
            ]
            missing_sources = tuple(
                {
                    key: value
                    for key, value in item.items()
                    if key != "raw_path"
                }
                for item in registered_sources
                if not isinstance(item.get("raw_path"), Path)
            )
            missing_source_count = max(0, registered_source_count - len(registered_raw_files))
            if current_version == "missing":
                status = "missing"
                mode = ""
                detail = "尚未生成派生数据库"
            elif current_version == SCHEMA_VERSION:
                status = "compatible"
                mode = ""
                detail = ""
            elif registered_source_count == 0:
                status = "incompatible"
                mode = MeshRepairMode.EMPTY_DATABASE_RECREATE.value
                detail = "当前派生库没有已登记的分析来源，将创建最新结构的空派生库。"
            else:
                status = "incompatible"
                mode = MeshRepairMode.PARTIAL_SOURCE_REBUILD.value
                detail = "仅重建仍有 raw 文件的历史来源，缺失文件记录为警告。"
            entries.append(
                MeshDerivedProfileInspection(
                    mr_id=profile.mr_id,
                    display_name=profile.display_name,
                    safe_folder_name=profile.safe_folder_name,
                    current_version=current_version,
                    required_version=SCHEMA_VERSION,
                    status=status,
                    raw_file_count=len(raw_files),
                    repair_mode=mode,
                    detail=detail,
                    registered_source_count=registered_source_count,
                    missing_source_count=missing_source_count,
                    registered_raw_file_count=len(registered_raw_files),
                    missing_sources=missing_sources,
                )
            )
        incompatible = [entry for entry in entries if entry.status == "incompatible"]
        repair_mode = ""
        if incompatible:
            repair_mode = (
                MeshRepairMode.PARTIAL_SOURCE_REBUILD.value
                if any(entry.repair_mode == MeshRepairMode.PARTIAL_SOURCE_REBUILD.value for entry in incompatible)
                else MeshRepairMode.EMPTY_DATABASE_RECREATE.value
            )
        return {
            "site_id": site,
            "compatible": not incompatible,
            "required_version": SCHEMA_VERSION,
            "repair_mode": repair_mode,
            "profiles": [entry.to_dict() for entry in entries],
            "incompatible_profiles": [entry.to_dict() for entry in incompatible],
            "recoverable": True,
        }

    def require_compatible(self, site_id: str) -> dict[str, object]:
        inspection = self.inspect(site_id)
        if inspection["compatible"]:
            return inspection
        incompatible = list(inspection["incompatible_profiles"])
        first = dict(incompatible[0]) if incompatible else {}
        raise MeshDerivedDatabaseIncompatible(
            site_id=str(inspection["site_id"]),
            current_version=str(first.get("current_version") or "unknown"),
            required_version=str(inspection["required_version"]),
            repair_mode=str(inspection["repair_mode"] or "rebuild"),
            recoverable=bool(inspection["recoverable"]),
        )

    def repair(
        self,
        site_id: str,
        *,
        profile_ids: Iterable[str] | None = None,
        include_missing: bool = False,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> dict[str, object]:
        normalized_profile_ids = (
            None
            if profile_ids is None
            else tuple(str(value) for value in profile_ids if str(value))
        )
        inspection = self.inspect(site_id, profile_ids=normalized_profile_ids)
        entries = [dict(item) for item in inspection["incompatible_profiles"]]
        if include_missing:
            entries.extend(
                dict(item)
                for item in inspection["profiles"]
                if item.get("status") == "missing" and int(item.get("raw_file_count") or 0) > 0
            )
        if not entries:
            self._set_journal_stage(site_id, "ready")
            return {
                "site_id": str(site_id),
                "compatible": True,
                "repair_mode": "",
                "repaired_profiles": [],
                "validation": self.validate(site_id, profile_ids=normalized_profile_ids),
            }
        self._set_journal_stage(site_id, "repairing")
        total = len(entries)
        repaired: list[dict[str, object]] = []
        if progress:
            progress("mesh_derived_repair_inspect", 5, 100, "正在检查 MESH 分析数据库版本")
            progress("mesh_derived_repair_prepare", 15, 100, "正在释放当前局点的 MESH 数据库资源")
        for index, entry in enumerate(entries, start=1):
            self._check_cancel(should_cancel)
            mr_id = str(entry["mr_id"])
            display_name = str(entry["display_name"])
            profile_root = self.paths.mesh_mr_raw_dir(site_id, str(entry["safe_folder_name"])).resolve()
            registered_sources = self._registered_sources(
                self.paths.mesh_mr_db_path(site_id, str(entry["safe_folder_name"])).resolve(),
                profile_root,
            )
            registered_raw_files = [
                raw_path
                for source in registered_sources
                if isinstance((raw_path := source.get("raw_path")), Path)
            ]
            if include_missing and entry.get("status") == "missing":
                registered_raw_files = self._raw_files(profile_root)

            def rebuild_progress(_stage: str, current: int, total_files: int, message: str) -> None:
                if progress:
                    fraction = current / max(total_files, 1)
                    base = 25 + int((index - 1) * 60 / total)
                    span = max(1, int(60 / total))
                    progress(
                        "mesh_derived_repair_rebuild",
                        min(85, base + int(span * fraction)),
                        100,
                        f"{display_name}：{message}",
                    )

            result = MeshParsedRebuildService(self.paths).rebuild(
                str(site_id),
                mr_id,
                progress=rebuild_progress,
                should_cancel=should_cancel,
                allow_empty_raw=True,
                raw_files=registered_raw_files,
                source_metadata=registered_sources,
            )
            missing_sources = [
                dict(item)
                for item in entry.get("missing_sources") or ()
                if isinstance(item, dict)
            ]
            result["skipped_missing_source_count"] = max(
                int(entry.get("missing_source_count") or 0),
                int(result.get("preserved_missing_count") or 0),
            )
            result["skipped_missing_sources"] = missing_sources[:50]
            repaired.append(result)
        if progress:
            progress("mesh_derived_repair_validate", 90, 100, "正在校验升级后的 MESH 分析数据库")
        validation = self.validate(site_id, profile_ids=(str(item["mr_id"]) for item in entries))
        catalog_path = self.paths.mesh_catalog_path(str(site_id))
        if catalog_path.is_file():
            MeshCatalogRepository(catalog_path).mark_index_pending()
        self._set_journal_stage(site_id, "ready")
        if progress:
            progress("mesh_derived_repair_reopen", 95, 100, "MESH 分析数据库已重新打开")
        return {
            "site_id": str(site_id),
            "compatible": True,
            "repair_mode": str(inspection["repair_mode"] or MeshRepairMode.PARTIAL_SOURCE_REBUILD.value),
            "repaired_profiles": repaired,
            "rebuilt_source_count": sum(int(item.get("raw_file_count") or 0) for item in repaired),
            "skipped_missing_source_count": sum(
                int(item.get("skipped_missing_source_count") or 0) for item in repaired
            ),
            "pending_import_count": len(self.pending_operations(site_id)),
            "warning_count": sum(
                int(item.get("skipped_missing_source_count") or 0) for item in repaired
            ),
            "validation": validation,
        }

    def validate(
        self,
        site_id: str,
        *,
        profile_ids: Iterable[str] | None = None,
    ) -> dict[str, object]:
        inspection = self.inspect(site_id, profile_ids=profile_ids)
        incompatible = list(inspection["incompatible_profiles"])
        if incompatible:
            first = dict(incompatible[0])
            raise MeshDerivedDatabaseIncompatible(
                site_id=str(site_id),
                current_version=str(first.get("current_version") or "unknown"),
                required_version=SCHEMA_VERSION,
                repair_mode=str(first.get("repair_mode") or "rebuild"),
                recoverable=bool(inspection["recoverable"]),
            )
        return inspection

    def enqueue_operation(
        self,
        site_id: str,
        *,
        kind: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        normalized_kind = str(kind)
        if normalized_kind not in _OPERATION_KINDS:
            raise MeshDerivedDataMaintenanceError("不支持的 MESH 等待导入操作")
        normalized_payload = json.loads(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True))
        journal = self._read_journal(site_id)
        for operation in journal["operations"]:
            if (
                operation.get("kind") == normalized_kind
                and operation.get("payload") == normalized_payload
                and operation.get("state") in {"waiting_repair", "repairing", "repair_failed"}
            ):
                operation["state"] = "waiting_repair"
                operation["error_message"] = ""
                operation["updated_at"] = self._now()
                self._write_journal(site_id, journal)
                return dict(operation)
        operation = {
            "operation_id": f"mdo1_{uuid4().hex}",
            "kind": normalized_kind,
            "payload": normalized_payload,
            "state": "waiting_repair",
            "repair_task_id": "",
            "created_at": self._now(),
            "updated_at": self._now(),
            "error_message": "",
            "result": {},
        }
        journal["operations"].append(operation)
        journal["stage"] = "pending"
        self._write_journal(site_id, journal)
        return dict(operation)

    def pending_operations(self, site_id: str) -> list[dict[str, object]]:
        journal = self._read_journal(site_id)
        return [
            dict(operation)
            for operation in journal["operations"]
            if str(operation.get("state") or "") in _PENDING_OPERATION_STATES
        ]

    def set_repair_task(self, site_id: str, task_id: str) -> None:
        journal = self._read_journal(site_id)
        for operation in journal["operations"]:
            if str(operation.get("state") or "") in _PENDING_OPERATION_STATES:
                operation["repair_task_id"] = str(task_id)
                operation["updated_at"] = self._now()
        journal["repair_task_id"] = str(task_id)
        self._write_journal(site_id, journal)

    def mark_operations_repairing(self, site_id: str, operation_ids: Iterable[str]) -> None:
        selected = {str(value) for value in operation_ids}
        journal = self._read_journal(site_id)
        for operation in journal["operations"]:
            if str(operation.get("operation_id") or "") in selected:
                operation["state"] = "repairing"
                operation["updated_at"] = self._now()
        journal["stage"] = "repairing"
        self._write_journal(site_id, journal)

    def complete_operation(self, site_id: str, operation_id: str, result: Mapping[str, object]) -> None:
        self._finish_operation(site_id, operation_id, "completed", result=result)

    def fail_operation(self, site_id: str, operation_id: str, message: str, *, repair_failed: bool) -> None:
        self._finish_operation(
            site_id,
            operation_id,
            "repair_failed" if repair_failed else "parse_failed",
            error_message=message,
        )

    def cleanup_manual_staging(self, site_id: str, files: Iterable[object]) -> None:
        """清理 Web 手工导入完成后的受管暂存目录。"""

        root = (self.paths.runtime_cache_dir / "rail_web_uploads" / str(site_id)).resolve()
        directories: set[Path] = set()
        for value in files:
            try:
                candidate = Path(str(value)).resolve()
            except (OSError, ValueError):
                continue
            if candidate.parent.parent == root:
                directories.add(candidate.parent)
        for directory in directories:
            if directory.is_dir() and not directory.is_symlink():
                shutil.rmtree(directory)

    def _finish_operation(
        self,
        site_id: str,
        operation_id: str,
        state: str,
        *,
        result: Mapping[str, object] | None = None,
        error_message: str = "",
    ) -> None:
        journal = self._read_journal(site_id)
        for operation in journal["operations"]:
            if str(operation.get("operation_id") or "") != str(operation_id):
                continue
            operation["state"] = state
            operation["error_message"] = str(error_message)
            operation["result"] = dict(result or {})
            operation["updated_at"] = self._now()
            break
        journal["stage"] = "ready" if not any(
            str(item.get("state") or "") in _PENDING_OPERATION_STATES
            for item in journal["operations"]
        ) else journal.get("stage") or "pending"
        self._write_journal(site_id, journal)

    def _set_journal_stage(self, site_id: str, stage: str) -> None:
        journal = self._read_journal(site_id)
        journal["stage"] = str(stage)
        journal["updated_at"] = self._now()
        self._write_journal(site_id, journal)

    def _read_journal(self, site_id: str) -> dict[str, object]:
        path = self._journal_path(site_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._new_journal(site_id)
        except (OSError, json.JSONDecodeError):
            # Keep a malformed journal for diagnostics and start a fresh safe record.
            return self._new_journal(site_id)
        if not isinstance(value, dict) or value.get("site_id") != str(site_id):
            return self._new_journal(site_id)
        operations = value.get("operations")
        value["operations"] = [dict(item) for item in operations if isinstance(item, dict)] if isinstance(operations, list) else []
        return value

    def _write_journal(self, site_id: str, journal: Mapping[str, object]) -> None:
        path = self._journal_path(site_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **dict(journal),
            "schema_version": _JOURNAL_SCHEMA_VERSION,
            "site_id": str(site_id),
            "updated_at": self._now(),
        }
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _new_journal(self, site_id: str) -> dict[str, object]:
        return {
            "schema_version": _JOURNAL_SCHEMA_VERSION,
            "site_id": str(site_id),
            "stage": "ready",
            "repair_task_id": "",
            "created_at": self._now(),
            "updated_at": self._now(),
            "operations": [],
        }

    def _journal_path(self, site_id: str) -> Path:
        site_cache = self.paths.site_cache_dir(str(site_id)).resolve()
        path = (site_cache / "mesh_derived_maintenance" / "repair_journal.json").resolve()
        if not path.is_relative_to(site_cache):
            raise MeshDerivedDataMaintenanceError("MESH 维护记录路径无效")
        return path

    @staticmethod
    def _schema_version(path: Path) -> str:
        if not path.is_file():
            return "missing"
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
            for table in ("schema_meta", "meta"):
                try:
                    row = connection.execute(
                        f"SELECT value FROM {table} WHERE key IN (?, ?) LIMIT 1",
                        ("schema_version", "schema_" + "version"),
                    ).fetchone()
                except sqlite3.Error:
                    continue
                if row is not None:
                    return str(row[0] or "unknown")
            return "unknown"
        except sqlite3.Error:
            return "unknown"
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _registered_source_count(path: Path) -> int:
        if not path.is_file():
            return 0
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
            row = connection.execute("SELECT COUNT(*) FROM source_files").fetchone()
            return max(0, int(row[0] if row else 0))
        except (sqlite3.Error, TypeError, ValueError):
            return 0
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _registered_raw_files(index_path: Path, raw_root: Path) -> list[Path]:
        """仅解析旧 index 中真实登记的 raw source，不从 Profile 推导日志。"""

        return [
            raw_path
            for item in MeshDerivedDataMaintenanceService._registered_sources(index_path, raw_root)
            if isinstance((raw_path := item.get("raw_path")), Path)
        ]

    @staticmethod
    def _registered_sources(index_path: Path, raw_root: Path) -> list[dict[str, object]]:
        """返回旧 index 的真实来源及可验证的 raw 路径。

        这里有意不遍历 raw 目录：Profile 与 raw source 并不等价，未登记的文件只能由
        当前导入请求或用户显式扫描进入后续流程。
        """

        if not index_path.is_file() or not raw_root.is_dir() or raw_root.is_symlink():
            return []
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"{index_path.as_uri()}?mode=ro", uri=True, timeout=5)
            connection.row_factory = sqlite3.Row
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(source_files)").fetchall()
            }
            if not columns:
                return []
            names = [
                name
                for name in (
                    "id",
                    "mr_id",
                    "raw_relative_path",
                    "archived_path",
                    "original_path",
                    "stored_filename",
                    "archived_filename",
                    "original_filename",
                    "sha256",
                    "raw_sha256",
                    "content_sha256",
                    "profile_id",
                    "linked_mr_id",
                    "file_size",
                    "file_mtime",
                    "imported_at",
                    "parser_version",
                    "source_type",
                    "source_device_id",
                    "parse_task_id",
                    "encoding",
                    "is_gzip",
                    "first_sample_time",
                    "last_sample_time",
                    "first_log_timestamp",
                    "last_log_timestamp",
                    "log_date",
                    "daily_sequence",
                    "rename_status",
                    "rename_warning",
                    "source_file_order",
                    "analysis_params_json",
                    "archive_sha256",
                    "bundle_member_id",
                    "bundle_member_sha256",
                )
                if name in columns
            ]
            if "id" not in names:
                return []
            rows = connection.execute(f"SELECT {', '.join(names)} FROM source_files").fetchall()
        except sqlite3.Error:
            return []
        finally:
            if connection is not None:
                connection.close()

        sources: list[dict[str, object]] = []
        for row in rows:
            source = dict(row)
            raw_path: Path | None = None
            for name in names:
                if name not in {
                    "raw_relative_path",
                    "archived_path",
                    "original_path",
                    "stored_filename",
                    "archived_filename",
                    "original_filename",
                }:
                    continue
                value = str(row[name] or "").strip().strip("'\"")
                if not value:
                    continue
                candidate = Path(value)
                if candidate.is_absolute():
                    candidates = [candidate]
                elif name == "raw_relative_path":
                    parts = candidate.parts
                    if parts and parts[0].casefold() == "raw":
                        candidate = Path(*parts[1:])
                    candidates = [raw_root / candidate]
                elif len(candidate.parts) == 1:
                    candidates = [raw_root / candidate.name]
                else:
                    candidates = []
                for candidate in candidates:
                    try:
                        if candidate.is_symlink() or not candidate.is_file():
                            continue
                        resolved = candidate.resolve()
                        if not resolved.is_relative_to(raw_root):
                            continue
                    except OSError:
                        continue
                    raw_path = resolved
                    break
                if raw_path is not None:
                    break
            source["raw_path"] = raw_path
            source["source_file_id"] = str(source.get("id") or "")
            source["file_name"] = str(
                source.get("original_filename")
                or source.get("stored_filename")
                or source.get("archived_filename")
                or source.get("source_file_id")
                or "历史来源"
            )
            sources.append(source)
        return sources

    @staticmethod
    def _raw_files(raw_root: Path) -> list[Path]:
        if not raw_root.is_dir() or raw_root.is_symlink():
            return []
        files: list[Path] = []
        for candidate in raw_root.rglob("*"):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(raw_root):
                continue
            if candidate.name.casefold().endswith((".log", ".txt", ".log.gz", ".txt.gz")):
                files.append(resolved)
        return sorted(files, key=lambda item: item.relative_to(raw_root).as_posix().casefold())

    @staticmethod
    def _check_cancel(should_cancel: CancelCallback | None) -> None:
        if should_cancel and should_cancel():
            raise MeshDerivedDataMaintenanceError("MESH 派生数据库自动修复已取消")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()


__all__ = [
    "MeshDerivedDataMaintenanceError",
    "MeshDerivedDataMaintenanceService",
    "MeshDerivedDatabaseIncompatible",
    "MeshDerivedProfileInspection",
    "MeshRepairMode",
]
