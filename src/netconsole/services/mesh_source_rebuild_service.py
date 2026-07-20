from __future__ import annotations

import gc
import hashlib
import json
import re
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_analysis_params import mesh_analysis_params_to_json
from netconsole.parsers.mesh_log_parser import MeshLogParser, sha256_file
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import PARSER_VERSION, SCHEMA_VERSION, MeshMrRepository
from netconsole.repositories.mesh_source_index_repository import MeshSourceIndexRepository
from netconsole.services.mesh_analysis_params_service import load_site_mesh_analysis_params
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_source_locator import MeshSourceLocation, MeshSourceLocator


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]
_SESSION_RE = re.compile(r"^(?P<mr_id>[0-9a-fA-F-]{8,64}):(?P<source_id>[1-9][0-9]*)$")
_MAX_RECOVERY_BYTES = 20 * 1024 * 1024


class MeshSourceRebuildService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.locator = MeshSourceLocator(paths)

    def rebuild_source(
        self,
        site_id: str,
        session_id: str,
        *,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> dict[str, object]:
        profile, source, repository = self._source(site_id, session_id)
        profile_root = self.paths.mesh_mr_root(site_id, profile.safe_folder_name).resolve()
        raw_root = self.paths.mesh_mr_raw_dir(site_id, profile.safe_folder_name).resolve()
        parsed_root = self.paths.mesh_mr_parsed_dir(site_id, profile.safe_folder_name).resolve()
        for path in (raw_root, parsed_root):
            self._require_inside(path, profile_root)
            path.mkdir(parents=True, exist_ok=True)
        location = self.locator.locate(site_id, profile, source)
        self._check_cancel(should_cancel)
        recovered = False
        raw_path = location.raw_path
        if raw_path is None and location.recoverable:
            if progress:
                progress("mesh_source_restore", 0, 3, "正在从受保护 ZIP 归档恢复原始 MESH 日志")
            raw_path = self._restore_from_bundle(site_id, profile.mr_id, profile_root, raw_root, source, location)
            recovered = True
        if raw_path is None:
            raise ValueError(location.missing_reason or "未找到原始日志或归档 ZIP，请重新导入该日志")
        self._require_inside(raw_path, raw_root)
        expected_sha = str(source.get("sha256") or "").strip().casefold()
        actual_sha = sha256_file(raw_path)
        if expected_sha and actual_sha != expected_sha:
            raise ValueError("恢复后的 MESH 原始日志 SHA-256 与来源记录不一致")
        self._check_cancel(should_cancel)
        if progress:
            progress("mesh_source_parse", 1, 3, "正在解析当前 MESH 原始日志")
        info, records, issues = MeshLogParser().parse_file(
            raw_path,
            source_label=profile.display_name,
            precomputed_hash=actual_sha,
            should_cancel=should_cancel,
        )
        if not records:
            raise ValueError("当前原始日志未解析到合法 MESH 记录")
        source_order = int(source.get("source_file_order") or source["id"])
        for index, record in enumerate(records, start=1):
            record.source_label = profile.display_name
            record.source_file = str(raw_path)
            record.source_file_order = source_order
            record.record_seq = index
        for issue in issues:
            issue.source_file = str(raw_path)
        target = self._target_detail_path(parsed_root, source)
        temporary = parsed_root / f".{target.name}.{uuid4().hex}.rebuild.sqlite"
        backup = parsed_root / f".{target.name}.{uuid4().hex}.backup.sqlite"
        detail = MeshMrRepository(temporary)
        detail.insert_file_result(
            profile.mr_id,
            Path(str(source.get("original_filename") or raw_path.name)),
            raw_path,
            actual_sha,
            raw_path.stat().st_size,
            datetime.fromtimestamp(raw_path.stat().st_mtime),
            PARSER_VERSION,
            "imported",
            min((record.sample_time for record in records), default=None),
            max((record.sample_time for record in records), default=None),
            info.lines_read,
            len(records),
            info.skipped_count,
            0,
            len(issues),
            "",
            records,
            [],
            issues,
            mesh_analysis_params_to_json(load_site_mesh_analysis_params(self.paths, site_id)),
        )
        MeshPeerMappingService(site_id, self.paths).refresh_repository(detail)
        detail.rebuild_derived_analysis(should_cancel=should_cancel)
        self._checkpoint(temporary)
        self._check_cancel(should_cancel)
        if detail.summary()["link_record_count"] < 1 or self._schema_version(temporary) != SCHEMA_VERSION:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("当前来源重建结果校验失败")
        replaced = False
        try:
            gc.collect()
            if target.exists():
                try:
                    self._checkpoint(target)
                except sqlite3.Error:
                    pass
                target.replace(backup)
                self._move_sidecars(target, backup)
            temporary.replace(target)
            self._move_sidecars(temporary, target)
            replaced = True
            repository.update_rebuilt_source(
                int(source["id"]),
                raw_path=raw_path,
                raw_relative_path=raw_path.relative_to(profile_root).as_posix(),
                parsed_path=target,
                parsed_relative_path=target.relative_to(profile_root).as_posix(),
                parser_version=PARSER_VERSION,
                first_sample_time=min((record.sample_time for record in records), default=None),
                last_sample_time=max((record.sample_time for record in records), default=None),
                lines_read=info.lines_read,
                records_parsed=len(records),
                records_skipped=info.skipped_count,
                issue_count=len(issues),
            )
            repository.update_source_provenance(
                int(source["id"]),
                raw_relative_path=raw_path.relative_to(profile_root).as_posix(),
                parsed_relative_path=target.relative_to(profile_root).as_posix(),
                archive_sha256=location.archive_sha256,
                bundle_member_id=location.bundle_member_id,
                bundle_member_sha256=location.bundle_member_sha256,
            )
            MeshCatalogRepository(self.paths.mesh_catalog_path(site_id)).update_summary(
                profile.mr_id,
                repository.aggregate_summary(),
            )
        except Exception:
            repository.restore_source_metadata(int(source["id"]), source)
            if replaced:
                target.unlink(missing_ok=True)
                self._remove_sidecars(target)
            if backup.exists():
                backup.replace(target)
                self._move_sidecars(backup, target)
            raise
        finally:
            temporary.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
            self._remove_sidecars(temporary)
            self._remove_sidecars(backup)
        if progress:
            progress("mesh_source_done", 3, 3, "当前 MESH 来源恢复并重新解析完成")
        return {
            "archive_sha256": location.archive_sha256,
            "raw_archived_count": 1 if recovered else 0,
            "parsed_source_count": 1,
            "parsed_record_count": len(records),
            "issue_count": len(issues),
            "created_session_ids": [session_id],
            "recovery_source": "bundle_archive" if recovered else location.recovery_source,
        }

    def _source(self, site_id: str, session_id: str):
        match = _SESSION_RE.fullmatch(session_id)
        if not match:
            raise ValueError("MESH 来源标识无效")
        profile = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id)).get_profile(match.group("mr_id"))
        if profile is None:
            raise ValueError("MESH Profile 不存在")
        repository = MeshSourceIndexRepository(self.paths.mesh_mr_db_path(site_id, profile.safe_folder_name))
        source = repository.get_source_file(int(match.group("source_id")))
        if source is None:
            raise ValueError("MESH 来源不存在")
        return profile, source, repository

    def _restore_from_bundle(
        self,
        site_id: str,
        profile_id: str,
        profile_root: Path,
        raw_root: Path,
        source: Mapping[str, object],
        location: MeshSourceLocation,
    ) -> Path:
        bundle = self.locator.find_bundle(site_id, profile_id, source)
        if bundle is None:
            raise ValueError("受保护 ZIP 归档不存在")
        directory = (self.paths.site_mesh_root(site_id) / "bundles" / bundle["archive_sha256"]).resolve()
        archive = directory / "source.zip"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        members = {
            str(item.get("member_id") or ""): str(item.get("original_name") or "")
            for item in manifest.get("members") or ()
            if isinstance(item, Mapping)
        }
        original_name = members.get(bundle["bundle_member_id"], "")
        if not original_name:
            raise ValueError("ZIP 归档缺少对应成员")
        target_name = Path(str(source.get("archived_filename") or bundle["bundle_member_id"])).name
        target_dir = raw_root / "recovered"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = (target_dir / target_name).resolve()
        self._require_inside(target, raw_root)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with zipfile.ZipFile(archive) as bundle_zip:
                info = bundle_zip.getinfo(original_name)
                if info.file_size > _MAX_RECOVERY_BYTES:
                    raise ValueError("ZIP 中的 MESH 日志超过恢复大小上限")
                digest = hashlib.sha256()
                total = 0
                with bundle_zip.open(info) as source_file, temporary.open("xb") as output:
                    while chunk := source_file.read(1024 * 1024):
                        total += len(chunk)
                        if total > _MAX_RECOVERY_BYTES:
                            raise ValueError("ZIP 中的 MESH 日志超过恢复大小上限")
                        digest.update(chunk)
                        output.write(chunk)
            if digest.hexdigest() != bundle["bundle_member_sha256"]:
                raise ValueError("ZIP 恢复成员 SHA-256 校验失败")
            if target.exists() and sha256_file(target) != digest.hexdigest():
                target = target.with_name(f"{target.stem}_{digest.hexdigest()[:8]}{target.suffix}")
            temporary.replace(target)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _target_detail_path(parsed_root: Path, source: Mapping[str, object]) -> Path:
        recorded = Path(str(source.get("parsed_relative_path") or source.get("parsed_db_path") or ""))
        name = recorded.name
        if not name:
            stem = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(str(source.get("archived_filename") or "mesh")).stem)
            name = f"{stem}.mesh.sqlite"
        target = (parsed_root / name).resolve()
        MeshSourceRebuildService._require_inside(target, parsed_root)
        return target

    @staticmethod
    def _checkpoint(path: Path) -> None:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    @staticmethod
    def _schema_version(path: Path) -> str:
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return str(row[0] or "") if row else ""

    @staticmethod
    def _remove_sidecars(path: Path) -> None:
        for suffix in ("-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)

    @staticmethod
    def _move_sidecars(source: Path, target: Path) -> None:
        for suffix in ("-wal", "-shm"):
            source_sidecar = source.with_name(source.name + suffix)
            if source_sidecar.exists():
                source_sidecar.replace(target.with_name(target.name + suffix))

    @staticmethod
    def _check_cancel(callback: CancelCallback | None) -> None:
        if callback and callback():
            raise RuntimeError("MESH 来源重建任务已取消")

    @staticmethod
    def _require_inside(candidate: Path, root: Path) -> None:
        if candidate != root and not candidate.is_relative_to(root):
            raise ValueError("MESH 来源路径越过允许目录")


__all__ = ["MeshSourceRebuildService"]
