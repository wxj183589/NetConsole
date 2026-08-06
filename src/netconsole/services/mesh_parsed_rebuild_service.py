from __future__ import annotations

import gc
import hashlib
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION
from netconsole.services.mesh_import_service import MeshImportResult, MeshImportService
from netconsole.services.mesh_storage_service import MeshStorageService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class MeshParsedRebuildService:
    """从受保护 raw 日志原子重建一个 MESH MR 的派生数据库。"""

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
        raw_files = self._raw_files(raw_root) if raw_files is None else [path.resolve() for path in raw_files]
        for raw_file in raw_files:
            self._require_inside(raw_file, raw_root, "MESH raw 文件")
        if not raw_files and not allow_empty_raw:
            raise ValueError("没有可用于重建的原始 MESH 日志")
        # 维护服务可能只恢复实际登记过的来源。未登记的历史副本和本次等待
        # 导入的候选都不属于该次重建输入，也不能让它们的变化中断重建。
        raw_snapshot = {
            path.relative_to(raw_root).as_posix(): self._sha256(path)
            for path in raw_files
        }
        self._check_cancel(should_cancel)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        archived_index = index_path.with_name(f"{index_path.name}.schema_archive_{stamp}")
        archived_parsed = parsed_dir.with_name(f"{parsed_dir.name}.schema_archive_{stamp}")
        moved_index = False
        moved_parsed = False
        rebuild_started = False
        try:
            if progress:
                progress("mesh_schema_rebuild_backup", 0, len(raw_files) + 2, "正在归档旧 MESH 派生结果")
            gc.collect()
            if index_path.exists():
                index_path.replace(archived_index)
                moved_index = True
                self._move_sidecars(index_path, archived_index)
            if parsed_dir.exists():
                if parsed_dir.is_symlink():
                    raise ValueError("parsed 目录不能是符号链接")
                parsed_dir.replace(archived_parsed)
                moved_parsed = True
            self._check_cancel(should_cancel)
            rebuild_started = True

            def import_progress(file_index: int, total: int, lines: int, parsed: int, skipped: int) -> None:
                if progress:
                    progress(
                        "mesh_schema_rebuild_parse",
                        file_index,
                        total + 2,
                        f"正在重建 MESH 日志 {file_index}/{total}，已解析 {parsed} 行，跳过 {skipped} 行",
                    )

            if raw_files:
                result = MeshImportService(site_id, self.paths).import_files(
                    profile,
                    raw_files,
                    should_cancel=should_cancel,
                    progress=import_progress,
                )
            else:
                from netconsole.repositories.mesh_mr_repository import MeshMrRepository

                MeshMrRepository(index_path)
                result = MeshImportResult()
            self._check_cancel(should_cancel)
            current = {
                path.relative_to(raw_root).as_posix(): self._sha256(path)
                for path in raw_files
            }
            if current != raw_snapshot:
                raise RuntimeError("重建期间原始 MESH 日志发生变化")
            if self._schema_version(index_path) != SCHEMA_VERSION:
                raise RuntimeError("MESH 派生数据库版本校验失败")
            if progress:
                progress("mesh_schema_rebuild_done", len(raw_files) + 2, len(raw_files) + 2, "MESH 派生数据库重建完成")
            return {
                "mr_id": profile.mr_id,
                "mr_name": profile.display_name,
                "schema_version": SCHEMA_VERSION,
                "raw_file_count": len(raw_files),
                "parsed_record_count": result.parsed_record_count,
                "issue_count": len(result.issues),
                "archive_created": moved_index or moved_parsed,
                "archived_index_path": str(archived_index) if moved_index else "",
                "archived_parsed_path": str(archived_parsed) if moved_parsed else "",
            }
        except Exception:
            gc.collect()
            if rebuild_started:
                self._remove_derived(index_path, parsed_dir, profile_root)
            if moved_index:
                archived_index.replace(index_path)
                self._move_sidecars(archived_index, index_path)
            if moved_parsed:
                archived_parsed.replace(parsed_dir)
            raise

    @staticmethod
    def _check_cancel(should_cancel: CancelCallback | None) -> None:
        if should_cancel and should_cancel():
            raise RuntimeError("MESH 重建任务已取消")

    @classmethod
    def _raw_files(cls, raw_root: Path) -> list[Path]:
        if not raw_root.is_dir() or raw_root.is_symlink():
            return []
        files: list[Path] = []
        for path in raw_root.rglob("*"):
            if path.is_symlink() or not path.is_file():
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
    def _schema_version(path: Path) -> str:
        if not path.is_file():
            return "missing"
        try:
            with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as conn:
                for table in ("schema_meta", "meta"):
                    row = conn.execute(
                        f"SELECT value FROM {table} WHERE key IN ('schema_version', 'schema_' || 'version') LIMIT 1"
                    ).fetchone()
                    if row:
                        return str(row[0] or "unknown")
        except sqlite3.Error:
            return "unknown"
        return "unknown"

    @classmethod
    def _remove_derived(cls, index_path: Path, parsed_dir: Path, profile_root: Path) -> None:
        for path in (index_path, index_path.with_name(index_path.name + "-wal"), index_path.with_name(index_path.name + "-shm")):
            cls._require_inside(path.resolve(), profile_root, "MESH 派生数据库")
            path.unlink(missing_ok=True)
        if parsed_dir.exists():
            cls._require_inside(parsed_dir.resolve(), profile_root, "MESH parsed 目录")
            if parsed_dir.is_symlink():
                raise ValueError("parsed 目录不能是符号链接")
            shutil.rmtree(parsed_dir)

    @staticmethod
    def _move_sidecars(source: Path, target: Path) -> None:
        for suffix in ("-wal", "-shm"):
            source_sidecar = source.with_name(source.name + suffix)
            if source_sidecar.exists():
                source_sidecar.replace(target.with_name(target.name + suffix))

    @staticmethod
    def _require_inside(candidate: Path, root: Path, label: str) -> None:
        if candidate != root and not candidate.is_relative_to(root):
            raise ValueError(f"{label}越过允许目录")


__all__ = ["MeshParsedRebuildService"]
