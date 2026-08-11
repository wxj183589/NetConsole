from __future__ import annotations

import hashlib
import gc
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_mr_repository import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    MeshMrRepository,
)
from netconsole.services.database_upgrade.coordinator import DatabaseUpgradeCoordinator
from netconsole.services.database_upgrade.models import (
    DatabaseDescriptor,
    DatabaseUpgradeStrategy,
    ProgressCallback,
)
from netconsole.services.database_upgrade.sqlite_consistency import checkpoint_wal, validate_sqlite
from netconsole.services.mesh_import_service import MeshImportResult, MeshImportService
from netconsole.services.mesh_storage_service import MeshStorageService


CancelCallback = Callable[[], bool]


class MeshParsedRebuildService:
    """从受保护 raw 日志影子重建 MESH 派生数据库。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def rebuild(
        self,
        site_id: str,
        mr_id: str,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
        allow_empty_raw: bool = False,
        raw_files: list[Path] | None = None,
        source_metadata: Iterable[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        storage = MeshStorageService(site_id, self.paths)
        profile = storage.catalog.get_profile(mr_id)
        if profile is None:
            raise ValueError("MESH MR profile 不存在")
        profile_root = self.paths.mesh_mr_root(site_id, profile.safe_folder_name).resolve()
        site_mesh_root = self.paths.site_mesh_root(site_id).resolve()
        self._require_inside(profile_root, site_mesh_root, "MESH MR 目录")
        raw_root = self.paths.mesh_mr_raw_dir(site_id, profile.safe_folder_name).resolve()
        index_path = self.paths.mesh_mr_db_path(site_id, profile.safe_folder_name).resolve()
        parsed_dir = self.paths.mesh_mr_parsed_dir(site_id, profile.safe_folder_name).resolve()
        for path, label in ((raw_root, "raw 目录"), (index_path, "索引数据库"), (parsed_dir, "parsed 目录")):
            self._require_inside(path, profile_root, label)
        selected_raw = self._raw_files(raw_root) if raw_files is None else [path.resolve() for path in raw_files]
        for raw_file in selected_raw:
            self._require_inside(raw_file, raw_root, "MESH raw 文件")
        if not selected_raw and not allow_empty_raw:
            raise ValueError("没有可用于重建的原始 MESH 日志")
        raw_snapshot = {path.relative_to(raw_root).as_posix(): self._sha256(path) for path in self._raw_files(raw_root)}
        current_version = self._schema_version(index_path)
        strategy = DatabaseUpgradeStrategy.REBUILD_FROM_SOURCE if selected_raw else DatabaseUpgradeStrategy.EMPTY_DATABASE_RECREATE
        adapter = _MeshUpgradeAdapter(
            service=self,
            site_id=str(site_id),
            mr_id=str(mr_id),
            profile=profile,
            raw_root=raw_root,
            parsed_dir=parsed_dir,
            raw_files=selected_raw,
            raw_snapshot=raw_snapshot,
            profile_root=profile_root,
            source_metadata=tuple(dict(item) for item in source_metadata or ()),
        )
        descriptor = DatabaseDescriptor(
            database_kind="mesh_derived",
            scope_type="site_profile",
            scope_id=f"{site_id}:{profile.safe_folder_name}",
            database_path=index_path,
            target_version=SCHEMA_VERSION,
            current_version=current_version,
            strategy=strategy,
            adapter=adapter,
            profile_id=profile.mr_id,
            profile_name=profile.display_name,
            task_id="",
            maintenance_lock=f"database-upgrade:site_profile:{site_id}:{profile.safe_folder_name}",
            reason="MESH 派生数据库版本不兼容或需要重建",
            source_count=len(selected_raw),
            version_reader=self._schema_version,
            reopen_hook=lambda: None,
            smoke_test=lambda path: self._smoke_test(path),
        )
        result = DatabaseUpgradeCoordinator(self.paths).upgrade(
            descriptor,
            progress=progress,
            should_cancel=should_cancel,
        )
        return {
            "mr_id": profile.mr_id,
            "mr_name": profile.display_name,
            "schema_version": SCHEMA_VERSION,
            "raw_file_count": len(selected_raw),
            "parsed_record_count": int(result.diagnostics.get("build", {}).get("parsed_record_count") or 0),
            "issue_count": int(result.diagnostics.get("build", {}).get("issue_count") or 0),
            "restored_source_count": int(result.diagnostics.get("build", {}).get("restored_source_count") or 0),
            "preserved_missing_count": int(result.diagnostics.get("build", {}).get("preserved_missing_count") or 0),
            "archive_created": True,
            "backup_id": result.backup_id,
            "backup_path": result.backup_path,
            "backup_sha256": result.backup_validation.get("sha256", ""),
            "backup_size": result.backup_validation.get("size_bytes", 0),
            "old_schema_version": current_version,
            "target_schema_version": SCHEMA_VERSION,
            "checkpoint_status": result.checkpoint_status,
            "backup_integrity_status": result.backup_validation.get("integrity_check", ""),
            "new_database_integrity_status": result.new_validation.get("integrity_check", ""),
            "rollback_available": result.rollback_available,
            "rollback_performed": result.rollback_performed,
            "retained_backup_count": result.retained_backup_count,
        }

    @staticmethod
    def _smoke_test(path: Path) -> dict[str, object]:
        validation = validate_sqlite(path)
        if not validation.get("valid"):
            return validation
        try:
            MeshMrRepository(path, read_only=True).summary()
        except Exception as exc:
            return {**validation, "valid": False, "error": str(exc)}
        return validation

    @staticmethod
    def _schema_version(path: Path) -> str:
        if not path.is_file():
            return "missing"
        try:
            with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
                for table in ("schema_meta", "meta"):
                    try:
                        row = conn.execute(
                            f"SELECT value FROM {table} WHERE key IN ('schema_version', 'schema_' || 'version') LIMIT 1"
                        ).fetchone()
                    except sqlite3.Error:
                        continue
                    if row:
                        return str(row[0] or "unknown")
        except sqlite3.Error:
            return "unknown"
        return "unknown"

    @classmethod
    def _raw_files(cls, raw_root: Path) -> list[Path]:
        if not raw_root.is_dir() or raw_root.is_symlink():
            return []
        files: list[Path] = []
        for path in raw_root.rglob("*"):
            if path.is_symlink() or not path.is_file() or path.name.casefold().endswith((".part", ".tmp", ".partial")):
                continue
            resolved = path.resolve()
            cls._require_inside(resolved, raw_root, "MESH raw 文件")
            if path.name.casefold().endswith((".log", ".txt", ".log.gz", ".txt.gz")):
                files.append(resolved)
        return sorted(files, key=lambda path: path.relative_to(raw_root).as_posix().casefold())

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _restore_source_metadata(
        index_path: Path,
        sources: Iterable[Mapping[str, object]],
    ) -> int:
        records = [dict(item) for item in sources if isinstance(item.get("raw_path"), Path)]
        if not records or not index_path.is_file():
            return 0
        restored = 0
        with closing(sqlite3.connect(index_path)) as connection:
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_files)").fetchall()}
            for source in records:
                raw_sha = str(source.get("raw_sha256") or source.get("sha256") or "").strip().casefold()
                content_sha = str(source.get("content_sha256") or "").strip().casefold()
                if not raw_sha and not content_sha:
                    continue
                row = connection.execute(
                    "SELECT id FROM source_files WHERE "
                    "(raw_sha256 = ? AND ? != '') OR (sha256 = ? AND ? != '') OR "
                    "(content_sha256 = ? AND ? != '') ORDER BY id LIMIT 1",
                    (raw_sha, raw_sha, raw_sha, raw_sha, content_sha, content_sha),
                ).fetchone()
                if row is None:
                    continue
                values: dict[str, object] = {
                    "mr_id": str(source.get("mr_id") or ""),
                    "original_path": str(source.get("original_path") or ""),
                    "original_filename": str(source.get("original_filename") or source.get("file_name") or ""),
                    "archived_filename": str(source.get("archived_filename") or source.get("stored_filename") or ""),
                    "stored_filename": str(source.get("stored_filename") or ""),
                    "profile_id": str(source.get("profile_id") or ""),
                    "linked_mr_id": str(source.get("linked_mr_id") or ""),
                    "file_mtime": source.get("file_mtime"),
                    "imported_at": str(source.get("imported_at") or ""),
                    "parser_version": str(source.get("parser_version") or ""),
                    "source_type": str(source.get("source_type") or "manual_upload"),
                    "source_device_id": str(source.get("source_device_id") or ""),
                    "parse_task_id": str(source.get("parse_task_id") or ""),
                    "encoding": str(source.get("encoding") or ""),
                    "is_gzip": int(source.get("is_gzip") or 0),
                    "source_file_order": int(source.get("source_file_order") or 0),
                    "analysis_params_json": str(source.get("analysis_params_json") or ""),
                    "raw_relative_path": str(source.get("raw_relative_path") or ""),
                    "archive_sha256": str(source.get("archive_sha256") or ""),
                    "bundle_member_id": str(source.get("bundle_member_id") or ""),
                    "bundle_member_sha256": str(source.get("bundle_member_sha256") or ""),
                }
                assignments = [name for name in values if name in columns]
                if not assignments:
                    continue
                connection.execute(
                    f"UPDATE source_files SET {', '.join(f'{name} = ?' for name in assignments)} WHERE id = ?",
                    [values[name] for name in assignments] + [int(row[0])],
                )
                restored += 1
            connection.commit()
        return restored

    @staticmethod
    def _preserve_missing_source_metadata(
        index_path: Path,
        *,
        mr_id: str,
        missing_sources: Iterable[Mapping[str, object]],
    ) -> int:
        records = [dict(item) for item in missing_sources]
        if not records or not index_path.is_file():
            return 0
        now = datetime.now(UTC).isoformat()
        inserted = 0
        with closing(sqlite3.connect(index_path)) as connection:
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_files)").fetchall()}
            for source in records:
                source_id = str(source.get("source_file_id") or source.get("id") or "")
                file_name = str(source.get("file_name") or source.get("original_filename") or "历史来源")
                digest = str(source.get("sha256") or "").strip().casefold()
                if not digest:
                    digest = hashlib.sha256(
                        f"mesh-missing-source\0{mr_id}\0{source_id}\0{file_name}".encode("utf-8")
                    ).hexdigest()
                values: dict[str, object] = {
                    "mr_id": str(source.get("mr_id") or mr_id),
                    "original_path": str(source.get("original_path") or source.get("archived_path") or file_name),
                    "archived_path": str(source.get("archived_path") or source.get("original_path") or file_name),
                    "parsed_db_path": "",
                    "parsed_db_size": 0,
                    "db_schema_version": SCHEMA_VERSION,
                    "original_filename": str(source.get("original_filename") or file_name),
                    "archived_filename": str(source.get("archived_filename") or source.get("stored_filename") or file_name),
                    "stored_filename": str(source.get("stored_filename") or ""),
                    "sha256": digest,
                    "raw_sha256": str(source.get("raw_sha256") or digest),
                    "content_sha256": str(source.get("content_sha256") or ""),
                    "profile_id": str(source.get("profile_id") or mr_id),
                    "linked_mr_id": str(source.get("linked_mr_id") or ""),
                    "file_size": int(source.get("file_size") or 0),
                    "file_mtime": source.get("file_mtime"),
                    "imported_at": str(source.get("imported_at") or now),
                    "parser_version": str(source.get("parser_version") or "legacy"),
                    "parse_status": "missing",
                    "encoding": str(source.get("encoding") or ""),
                    "is_gzip": int(source.get("is_gzip") or 0),
                    "first_sample_time": source.get("first_sample_time"),
                    "last_sample_time": source.get("last_sample_time"),
                    "first_log_timestamp": source.get("first_log_timestamp"),
                    "last_log_timestamp": source.get("last_log_timestamp"),
                    "log_date": source.get("log_date"),
                    "daily_sequence": source.get("daily_sequence"),
                    "rename_status": str(source.get("rename_status") or ""),
                    "rename_warning": str(source.get("rename_warning") or ""),
                    "source_status": "RAW_FILE_MISSING",
                    "source_type": str(source.get("source_type") or "manual_upload"),
                    "source_device_id": str(source.get("source_device_id") or ""),
                    "parse_task_id": str(source.get("parse_task_id") or ""),
                    "lines_read": 0,
                    "records_parsed": 0,
                    "records_skipped": 0,
                    "duplicate_records": 0,
                    "issue_count": 0,
                    "error_message": "原始日志缺失，数据库升级时未恢复明细。",
                    "file_exists": 0,
                    "file_status": "raw_file_missing",
                    "parsed_deleted_at": "",
                    "parsed_delete_error": "",
                    "source_file_order": int(source.get("source_file_order") or 0),
                    "analysis_params_json": str(source.get("analysis_params_json") or ""),
                    "raw_relative_path": str(source.get("raw_relative_path") or ""),
                    "parsed_relative_path": "",
                    "archive_sha256": str(source.get("archive_sha256") or ""),
                    "bundle_member_id": str(source.get("bundle_member_id") or ""),
                    "bundle_member_sha256": str(source.get("bundle_member_sha256") or ""),
                }
                names = [name for name in values if name in columns]
                placeholders = ", ".join("?" for _ in names)
                cursor = connection.execute(
                    f"INSERT OR IGNORE INTO source_files ({', '.join(names)}) VALUES ({placeholders})",
                    [values[name] for name in names],
                )
                inserted += int(cursor.rowcount > 0)
            connection.commit()
        return inserted

    @staticmethod
    def _require_inside(candidate: Path, root: Path, label: str) -> None:
        if candidate != root and not candidate.is_relative_to(root):
            raise ValueError(f"{label}超出允许目录")


class _MeshUpgradeAdapter:
    def __init__(
        self,
        *,
        service: MeshParsedRebuildService,
        site_id: str,
        mr_id: str,
        profile: Any,
        raw_root: Path,
        parsed_dir: Path,
        raw_files: list[Path],
        raw_snapshot: dict[str, str],
        profile_root: Path,
        source_metadata: tuple[dict[str, object], ...],
    ) -> None:
        self.service = service
        self.site_id = site_id
        self.mr_id = mr_id
        self.profile = profile
        self.raw_root = raw_root
        self.parsed_dir = parsed_dir
        self.raw_files = raw_files
        self.raw_snapshot = raw_snapshot
        self.profile_root = profile_root
        self.source_metadata = source_metadata
        self.shadow_parsed: Path | None = None
        self.rollback_parsed: Path | None = None

    def build_shadow(self, descriptor: DatabaseDescriptor, shadow_path: Path, *, progress: ProgressCallback | None, should_cancel: CancelCallback | None) -> dict[str, Any]:
        self._check_cancel(should_cancel)
        self.shadow_parsed = self.parsed_dir.with_name(f"{self.parsed_dir.name}.new.{shadow_path.name.rsplit('.', 1)[-1]}")
        if shadow_path.exists() or any(shadow_path.with_name(shadow_path.name + suffix).exists() for suffix in ("-wal", "-shm")):
            raise RuntimeError(f"影子数据库路径已被占用：{shadow_path}")
        if self.shadow_parsed.exists():
            raise RuntimeError(f"影子 parsed 目录已被占用：{self.shadow_parsed}")
        self.shadow_parsed.mkdir(parents=True, exist_ok=True)
        repo = MeshMrRepository(shadow_path, parsed_dir=self.shadow_parsed, index_database=True)
        result = MeshImportResult()
        if self.raw_files:
            def import_progress(file_index: int, total: int, lines: int, parsed: int, skipped: int) -> None:
                if progress:
                    progress("mesh_schema_rebuild_parse", file_index, max(total, 1), f"正在重建 MESH 日志 {file_index}/{total}")

            result = MeshImportService(
                self.site_id,
                self.service.paths,
                database_path=shadow_path,
                parsed_dir=self.shadow_parsed,
                refresh_catalog=False,
            ).import_files(
                self.profile,
                self.raw_files,
                should_cancel=should_cancel,
                progress=import_progress,
                source_type="local_scan",
            )
        else:
            repo.summary()
        restored_source_count = self.service._restore_source_metadata(shadow_path, self.source_metadata)
        preserved_missing_count = self.service._preserve_missing_source_metadata(
            shadow_path,
            mr_id=self.mr_id,
            missing_sources=(
                source for source in self.source_metadata
                if not isinstance(source.get("raw_path"), Path)
            ),
        )
        current = {path.relative_to(self.raw_root).as_posix(): self.service._sha256(path) for path in self.service._raw_files(self.raw_root)}
        if current != self.raw_snapshot:
            raise RuntimeError("重建期间原始 MESH 日志发生变化")
        return {
            "parsed_record_count": result.parsed_record_count,
            "issue_count": len(result.issues),
            "imported_count": result.imported_count,
            "duplicate_count": result.duplicate_count,
            "restored_source_count": restored_source_count,
            "preserved_missing_count": preserved_missing_count,
        }

    def validate(self, path: Path) -> dict[str, Any]:
        checkpoint_wal(path)
        result = validate_sqlite(path)
        if result.get("valid") and result.get("schema_version") != SCHEMA_VERSION:
            result["valid"] = False
            result["error"] = "MESH schema_version 不匹配"
        required_tables = {"schema_meta", "meta", "source_files", "samples", "mesh_links", "switch_events"}
        missing_tables = sorted(required_tables - set(result.get("table_names") or ()))
        if result.get("valid") and missing_tables:
            result["valid"] = False
            result["error"] = f"MESH 必要表缺失：{', '.join(missing_tables)}"
        if result.get("valid") and result.get("parser_version") != PARSER_VERSION:
            result["valid"] = False
            result["error"] = "MESH parser_version 不匹配"
        return result

    def switch(self, descriptor: DatabaseDescriptor, shadow_path: Path, rollback_path: Path) -> None:
        active = descriptor.database_path.resolve()
        if rollback_path.exists():
            raise RuntimeError(f"检测到未完成的 rollback 文件：{rollback_path.name}")
        self._move_sidecars(active, rollback_path)
        if active.exists():
            active.replace(rollback_path)
        if self.parsed_dir.exists():
            self.rollback_parsed = self.parsed_dir.with_name(f"{self.parsed_dir.name}.rollback.{rollback_path.name.rsplit('.', 1)[-1]}")
            if self.rollback_parsed.exists():
                raise RuntimeError(f"检测到未完成的 parsed rollback：{self.rollback_parsed.name}")
            self.parsed_dir.replace(self.rollback_parsed)
        self._move_sidecars(shadow_path, active)
        shadow_path.replace(active)
        if self.shadow_parsed and self.shadow_parsed.exists():
            shadow_parsed = self.shadow_parsed
            self.shadow_parsed.replace(self.parsed_dir)
            self._rewrite_parsed_paths(active, shadow_parsed, self.parsed_dir)

    def rollback(self, descriptor: DatabaseDescriptor, rollback_path: Path, failed_shadow_path: Path, failure_dir: Path) -> None:
        failure_dir.mkdir(parents=True, exist_ok=True)
        active = descriptor.database_path.resolve()
        failed_target = self._unique_path(failure_dir / "failed_new_database.sqlite")
        if active.exists():
            active.replace(failed_target)
            self._move_sidecars(active, failed_target)
        if failed_shadow_path.exists():
            failed_shadow_path.replace(self._unique_path(failed_target))
        if self.parsed_dir.exists():
            failed_parsed = self._unique_path(failure_dir / "failed_new_parsed")
            self.parsed_dir.replace(failed_parsed)
        retained_rollback = rollback_path if rollback_path.exists() else failure_dir / "rollback.sqlite"
        if retained_rollback.exists():
            retained_rollback.replace(active)
            self._move_sidecars(retained_rollback, active)
        retained_parsed = (
            self.rollback_parsed
            if self.rollback_parsed and self.rollback_parsed.exists()
            else failure_dir / "rollback_parsed"
        )
        if retained_parsed.exists():
            retained_parsed.replace(self.parsed_dir)

    def discard_shadow(self, shadow_path: Path, failure_dir: Path) -> None:
        """影子库尚未切换时只隔离失败产物，正式库保持不动。"""

        failure_dir.mkdir(parents=True, exist_ok=True)
        if shadow_path.exists():
            shadow_path.replace(self._unique_path(failure_dir / "failed_new_database.sqlite"))
        if self.shadow_parsed and self.shadow_parsed.exists():
            target = self._unique_path(failure_dir / "failed_new_parsed")
            self.shadow_parsed.replace(target)

    def finalize_success(self, descriptor: DatabaseDescriptor, rollback_path: Path, backup_dir: Path) -> dict[str, Any]:
        retained: dict[str, Any] = {}
        if rollback_path.exists():
            target = backup_dir / "rollback.sqlite"
            if target.exists():
                raise RuntimeError("备份目录中的 rollback 文件已存在")
            rollback_path.replace(target)
            retained["rollback_path"] = str(target)
        if self.rollback_parsed and self.rollback_parsed.exists():
            target = backup_dir / "rollback_parsed"
            if target.exists():
                raise RuntimeError("备份目录中的 rollback parsed 已存在")
            self.rollback_parsed.replace(target)
            retained["rollback_parsed_path"] = str(target)
        return retained

    def journal_state(self, rollback_path: Path) -> dict[str, str]:
        suffix = rollback_path.name.rsplit(".", 1)[-1]
        rollback_parsed = self.parsed_dir.with_name(f"{self.parsed_dir.name}.rollback.{suffix}")
        return {
            "active_parsed_path": str(self.parsed_dir),
            "shadow_parsed_path": str(self.shadow_parsed or ""),
            "rollback_parsed_path": str(rollback_parsed),
        }

    @staticmethod
    def _check_cancel(should_cancel: CancelCallback | None) -> None:
        if should_cancel and should_cancel():
            raise RuntimeError("MESH 重建任务已取消")

    @staticmethod
    def _move_sidecars(source: Path, target: Path) -> None:
        gc.collect()
        for suffix in ("-wal", "-shm"):
            source_sidecar = source.with_name(source.name + suffix)
            target_sidecar = target.with_name(target.name + suffix)
            if source_sidecar.exists():
                source_sidecar.replace(target_sidecar)

    @staticmethod
    def _rewrite_parsed_paths(index_path: Path, old_root: Path, new_root: Path) -> None:
        """影子 parsed 目录切换后，修正索引中的绝对路径引用。"""

        if not index_path.is_file():
            return
        old_root = old_root.resolve()
        new_root = new_root.resolve()
        with closing(sqlite3.connect(index_path)) as connection:
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(source_files)").fetchall()
            }
            if "parsed_db_path" not in columns:
                return
            rows = connection.execute(
                "SELECT id, parsed_db_path FROM source_files WHERE COALESCE(parsed_db_path, '') != ''"
            ).fetchall()
            for row in rows:
                current = Path(str(row[1]).strip().strip("'\""))
                try:
                    relative = current.resolve().relative_to(old_root)
                except (OSError, ValueError):
                    continue
                connection.execute(
                    "UPDATE source_files SET parsed_db_path = ? WHERE id = ?",
                    (str(new_root / relative), int(row[0])),
                )
            connection.commit()

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        return path.with_name(f"{path.name}.{uuid4().hex[:10]}")


__all__ = ["MeshParsedRebuildService"]
