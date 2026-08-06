from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository, MeshSchemaRebuildRequired
from netconsole.services.mesh_bundle_import_service import MeshBundleImportError, MeshBundleImportService
from netconsole.services.mesh_catalog_index_service import MeshCatalogIndexService
from netconsole.services.mesh_import_service import MeshImportService


SCAN_ID_RE = re.compile(r"^mls1_[0-9a-f]{32}$")
CANDIDATE_ID_RE = re.compile(r"^mlc1_[0-9a-f]{32}$")
_IDENTITY_RE = re.compile(
    r"(?:列车\s*)?(?P<train>\d{1,3}).*?MR[-_\s]?(?P<role>CT|CW|TC)(?:\b|[_-])?",
    re.IGNORECASE,
)
_SUPPORTED_SUFFIXES = (".log", ".log.gz", ".zip")
_SCAN_TTL = timedelta(hours=24)
_MAX_SCANS = 64
_MAX_GZIP_EXPANDED_BYTES = 512 * 1024 * 1024


class MeshLocalScanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MeshLocalScanService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = str(site_name)
        self.paths = paths
        self.mesh_root = paths.site_mesh_root(self.site_name).resolve()
        self.cache_root = paths.site_cache_dir(self.site_name).resolve() / "mesh_local_scans"

    def create_scan_id(self) -> str:
        return f"mls1_{uuid4().hex}"

    def scan(
        self,
        scan_id: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str, int, int, str], None] | None = None,
    ) -> dict[str, object]:
        self._validate_scan_id(scan_id)
        self._cleanup_expired()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        cache = self._read_fingerprint_cache()
        profiles = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name)).list_profiles()
        profile_by_folder = {item.safe_folder_name.casefold(): item for item in profiles}
        profiles_by_identity = self._profiles_by_identity(profiles)
        registered_paths, registered_hashes = self._registered_sources(profiles)
        discovered = list(self._iter_candidates())
        candidates: list[dict[str, object]] = []
        next_cache: dict[str, dict[str, object]] = {}
        seen_scan_hashes: dict[str, str] = {}
        total = len(discovered)
        bundle_service = MeshBundleImportService(self.site_name, self.paths)
        for index, path in enumerate(discovered, start=1):
            self._raise_if_cancelled(should_cancel)
            relative = path.relative_to(self.mesh_root).as_posix()
            before = path.stat()
            cached = cache.get(relative, {})
            unchanged = (
                int(cached.get("size") or -1) == int(before.st_size)
                and int(cached.get("mtime_ns") or -1) == int(before.st_mtime_ns)
                and bool(re.fullmatch(r"[0-9a-f]{64}", str(cached.get("sha256") or "")))
            )
            if unchanged:
                digest = str(cached["sha256"])
                validation_error = str(cached.get("validation_error") or "")
            else:
                digest = self._sha256(path, should_cancel)
                validation_error = self._validate_candidate(path, bundle_service)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                validation_error = "文件扫描期间仍在写入，请稍后重试"
            next_cache[relative] = {
                "size": int(after.st_size),
                "mtime_ns": int(after.st_mtime_ns),
                "sha256": digest,
                "validation_error": validation_error,
                "last_scanned_at": self._now(),
            }
            profile, train_no, role, match_status = self._match_profile(
                path,
                profile_by_folder,
                profiles_by_identity,
            )
            registered = registered_paths.get(str(path.resolve()).casefold())
            duplicate = registered_hashes.get(digest)
            candidate_id = f"mlc1_{uuid4().hex}"
            duplicate_of_candidate_id = seen_scan_hashes.get(digest, "")
            if validation_error:
                status = "invalid"
                existing = None
            elif registered is not None:
                status = "imported"
                existing = registered
            elif duplicate is not None or duplicate_of_candidate_id or (
                path.name.casefold().endswith(".zip") and bundle_service.is_archived(digest)
            ):
                status = "duplicate"
                existing = duplicate
            elif profile is None:
                status = "needs_metadata"
                existing = None
            else:
                status = "unregistered"
                existing = None
            if not validation_error:
                seen_scan_hashes.setdefault(digest, candidate_id)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "relative_path": relative,
                    "file_name": path.name,
                    "file_type": self._file_type(path),
                    "file_size": int(after.st_size),
                    "modified_at": datetime.fromtimestamp(after.st_mtime, UTC).isoformat(),
                    "mtime_ns": int(after.st_mtime_ns),
                    "sha256": digest,
                    "profile_id": profile.mr_id if profile else "",
                    "profile_name": (
                        profile.display_name
                        if profile
                        else path.relative_to(self.mesh_root).parts[0]
                    ),
                    "train_no": train_no,
                    "mr_role": role,
                    "match_status": match_status,
                    "scan_status": status,
                    "error_message": validation_error,
                    "existing_session_id": self._session_id(existing),
                    "existing_profile_name": str((existing or {}).get("profile_name") or ""),
                    "duplicate_of_candidate_id": duplicate_of_candidate_id,
                }
            )
            if progress:
                progress("mesh_local_scan", index, total, f"正在扫描本地 MESH 日志：{index} / {total}")
        manifest = {
            "scan_id": scan_id,
            "site_id": self.site_name,
            "created_at": self._now(),
            "updated_at": self._now(),
            "status": "ready",
            "stats": self._stats(candidates),
            "profiles": [
                {"profile_id": item.mr_id, "display_name": item.display_name}
                for item in profiles
            ],
            "candidates": candidates,
        }
        self._write_manifest(manifest)
        self._write_fingerprint_cache(next_cache)
        return {
            "scan_id": scan_id,
            "stats": manifest["stats"],
            "candidate_count": len(candidates),
        }

    def get_scan(self, scan_id: str) -> dict[str, object]:
        manifest = self._read_manifest(scan_id)
        return {
            "scan_id": manifest["scan_id"],
            "site_id": manifest["site_id"],
            "created_at": manifest["created_at"],
            "updated_at": manifest.get("updated_at") or manifest["created_at"],
            "status": manifest.get("status") or "ready",
            "stats": dict(manifest.get("stats") or {}),
            "profiles": list(manifest.get("profiles") or []),
            "candidates": list(manifest.get("candidates") or []),
        }

    def ignore_candidates(self, scan_id: str, candidate_ids: Iterable[str]) -> dict[str, object]:
        manifest = self._read_manifest(scan_id)
        selected = {str(value or "") for value in candidate_ids}
        if not selected:
            raise MeshLocalScanError("CANDIDATE_SELECTION_INVALID", "请至少选择一个本地日志")
        candidates = [item for item in manifest.get("candidates") or [] if isinstance(item, dict)]
        known = {str(item.get("candidate_id") or "") for item in candidates}
        if not selected.issubset(known):
            raise MeshLocalScanError("CANDIDATE_NOT_FOUND", "本地日志候选不存在或不属于当前扫描")
        for candidate in candidates:
            if str(candidate.get("candidate_id") or "") not in selected:
                continue
            if str(candidate.get("scan_status") or "") in {
                "unregistered",
                "needs_metadata",
                "failed",
                "parse_failed",
                "repair_failed",
            }:
                candidate["scan_status"] = "ignored"
                candidate["error_message"] = "已忽略"
        manifest["updated_at"] = self._now()
        manifest["stats"] = self._stats(candidates)
        self._write_manifest(manifest)
        return self.get_scan(scan_id)

    def import_candidates(
        self,
        scan_id: str,
        mappings: Iterable[Mapping[str, object]],
        *,
        job_id: str,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[str, int, int, str], None] | None = None,
    ) -> dict[str, object]:
        manifest = self._read_manifest(scan_id)
        candidates = {
            str(item.get("candidate_id") or ""): item
            for item in manifest.get("candidates") or []
            if isinstance(item, dict)
        }
        requested = [dict(item) for item in mappings]
        if not requested or len(requested) > 200:
            raise MeshLocalScanError("CANDIDATE_SELECTION_INVALID", "每次必须选择 1 到 200 个本地日志")
        profiles = {
            item.mr_id: item
            for item in MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name)).list_profiles()
        }
        imported_count = 0
        duplicate_count = 0
        parsed_record_count = 0
        source_results: list[dict[str, object]] = []
        created_session_ids: list[str] = []
        failed_files: list[dict[str, str]] = []
        total = len(requested)
        for index, mapping in enumerate(requested, start=1):
            self._raise_if_cancelled(should_cancel)
            candidate_id = str(mapping.get("candidate_id") or "")
            if not CANDIDATE_ID_RE.fullmatch(candidate_id) or candidate_id not in candidates:
                raise MeshLocalScanError("CANDIDATE_NOT_FOUND", "本地日志候选不存在或不属于当前扫描")
            candidate = candidates[candidate_id]
            profile_id = str(mapping.get("profile_id") or candidate.get("profile_id") or "")
            profile = profiles.get(profile_id)
            try:
                if profile is None:
                    raise MeshLocalScanError("PROFILE_REQUIRED", "请先为该日志选择列车与 MR")
                candidate_status = str(candidate.get("scan_status") or "")
                if candidate_status in {"imported", "duplicate"}:
                    duplicate_count += 1
                    existing = str(candidate.get("existing_session_id") or "")
                    if existing:
                        created_session_ids.append(existing)
                    continue
                if candidate_status == "invalid":
                    raise MeshLocalScanError(
                        "SOURCE_INVALID",
                        str(candidate.get("error_message") or "本地日志无效"),
                    )
                if candidate_status not in {
                    "unregistered",
                    "needs_metadata",
                    "failed",  # 兼容升级前的扫描记录
                    "parse_failed",
                    "repair_failed",
                    "repairing",
                    "queued",
                }:
                    raise MeshLocalScanError("SOURCE_NOT_IMPORTABLE", "当前本地日志状态不可导入")
                path = self._resolve_candidate(candidate)
                if self._sha256(path, should_cancel) != str(candidate.get("sha256") or ""):
                    raise MeshLocalScanError("SOURCE_CHANGED", "本地日志在扫描后发生变化，请重新扫描")
                candidate["scan_status"] = "parsing"
                candidate["error_message"] = "正在解析"
                manifest["updated_at"] = self._now()
                manifest["stats"] = self._stats(list(candidates.values()))
                self._write_manifest(manifest)
                if path.name.casefold().endswith(".zip"):
                    result = self._import_zip(
                        path,
                        profile,
                        job_id=job_id,
                        should_cancel=should_cancel,
                        progress=progress,
                    )
                    imported_count += int(result.get("imported_count") or 0)
                    duplicate_count += int(result.get("duplicate_count") or 0)
                    parsed_record_count += int(result.get("parsed_record_count") or 0)
                    created = [str(value) for value in result.get("created_session_ids") or []]
                    created_session_ids.extend(created)
                    candidate["scan_status"] = "imported" if int(result.get("imported_count") or 0) else "duplicate"
                    candidate["existing_session_id"] = created[0] if created else ""
                else:
                    result = MeshImportService(self.site_name, self.paths).import_files(
                        profile,
                        [path],
                        should_cancel=should_cancel,
                        source_type="local_scan",
                        parse_task_id=job_id,
                    )
                    imported_count += result.imported_count
                    duplicate_count += result.duplicate_count
                    parsed_record_count += result.parsed_record_count
                    source_results.extend(result.source_results)
                    sessions = [
                        str(item.get("session_id") or item.get("existing_session_id") or "")
                        for item in result.source_results
                    ]
                    sessions = [value for value in sessions if value]
                    created_session_ids.extend(sessions)
                    candidate["scan_status"] = "imported" if result.imported_count else "duplicate"
                    candidate["existing_session_id"] = sessions[0] if sessions else ""
                candidate["profile_id"] = profile.mr_id
                candidate["profile_name"] = profile.display_name
                candidate["match_status"] = "matched"
                candidate["error_message"] = ""
            except MeshSchemaRebuildRequired:
                raise
            except Exception as exc:
                if exc.__class__.__name__ == "BackgroundTaskCancelled":
                    raise
                message = self._safe_error(exc)
                candidate["scan_status"] = "failed"
                candidate["error_message"] = message
                failed_files.append(
                    {"candidate_id": candidate_id, "file_name": str(candidate.get("file_name") or ""), "error": message}
                )
            finally:
                manifest["updated_at"] = self._now()
                manifest["stats"] = self._stats(list(candidates.values()))
                self._write_manifest(manifest)
            if progress:
                progress("mesh_local_scan_import", index, total, f"正在补录本地 MESH 日志：{index} / {total}")
        self._publish_source_results(source_results)
        if imported_count or duplicate_count:
            catalog = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name))
            catalog.mark_index_pending()
            MeshCatalogIndexService(self.paths).rebuild_now(self.site_name)
        unique_sessions = list(dict.fromkeys(created_session_ids))
        return {
            "scan_id": scan_id,
            "business_status": "PARTIAL_SUCCESS" if failed_files else "SUCCESS",
            "imported_count": imported_count,
            "duplicate_count": duplicate_count,
            "parsed_record_count": parsed_record_count,
            "failed_count": len(failed_files),
            "failed_files": failed_files,
            "created_session_ids": unique_sessions,
        }

    def set_repair_status(
        self,
        scan_id: str,
        candidate_ids: Iterable[str],
        status: str,
        message: str = "",
    ) -> dict[str, object]:
        if status not in {"waiting_repair", "repairing", "queued", "parsing", "repair_failed", "parse_failed"}:
            raise MeshLocalScanError("REPAIR_STATUS_INVALID", "本地日志维护状态无效")
        selected = {str(value or "") for value in candidate_ids if str(value or "")}
        if not selected:
            return self.get_scan(scan_id)
        manifest = self._read_manifest(scan_id)
        changed = False
        for candidate in manifest.get("candidates") or []:
            if not isinstance(candidate, dict) or str(candidate.get("candidate_id") or "") not in selected:
                continue
            candidate["scan_status"] = status
            candidate["error_message"] = str(message)
            changed = True
        if changed:
            manifest["updated_at"] = self._now()
            manifest["stats"] = self._stats(
                [item for item in manifest.get("candidates") or [] if isinstance(item, dict)]
            )
            self._write_manifest(manifest)
        return self.get_scan(scan_id)

    def candidate_directory(self, scan_id: str, candidate_id: str) -> Path:
        manifest = self._read_manifest(scan_id)
        candidate = next(
            (
                item
                for item in manifest.get("candidates") or []
                if isinstance(item, dict) and item.get("candidate_id") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise MeshLocalScanError("CANDIDATE_NOT_FOUND", "本地日志候选不存在或不属于当前扫描")
        return self._resolve_candidate(candidate).parent

    def _import_zip(
        self,
        path: Path,
        profile: MeshMrProfile,
        *,
        job_id: str,
        should_cancel: Callable[[], bool] | None,
        progress: Callable[[str, int, int, str], None] | None,
    ) -> dict[str, object]:
        service = MeshBundleImportService(self.site_name, self.paths)
        profiles = MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name)).list_profiles()
        with path.open("rb") as source:
            preview = service.create_preview(path.name, source, profiles)
        train_no, role = self._identity(profile.display_name)
        if role not in {"CT", "CW"}:
            raise MeshLocalScanError("PROFILE_IDENTITY_INVALID", "所选 MR 缺少可识别的 CT/CW 角色")
        mappings = [
            {
                "member_id": str(item["member_id"]),
                "profile_id": profile.mr_id,
                "train_number": train_no,
                "role": role,
            }
            for item in preview.get("items") or []
        ]
        _manifest, approved = service.approve_preview(
            str(preview["preview_id"]),
            mappings,
            (item.mr_id for item in profiles),
        )
        return service.import_approved_preview(
            str(preview["preview_id"]),
            approved,
            job_id=job_id,
            source_type="local_scan",
            should_cancel=should_cancel,
            progress=progress,
        )

    def _registered_sources(
        self,
        profiles: Iterable[MeshMrProfile],
    ) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
        by_path: dict[str, dict[str, object]] = {}
        by_hash: dict[str, dict[str, object]] = {}
        for profile in profiles:
            index_path = self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name)
            if not index_path.is_file():
                continue
            try:
                rows = MeshMrRepository(index_path).list_source_files()
            except (OSError, sqlite3.Error, MeshSchemaRebuildRequired):
                continue
            for row in rows:
                value = {
                    **row,
                    "profile_name": profile.display_name,
                    "session_id": f"{profile.mr_id}:{int(row['id'])}",
                }
                digest = str(row.get("raw_sha256") or row.get("sha256") or "").casefold()
                if digest:
                    by_hash.setdefault(digest, value)
                raw_path = str(row.get("archived_path") or "").strip().strip("'\"")
                if raw_path:
                    try:
                        resolved = Path(raw_path).resolve()
                        resolved.relative_to(self.mesh_root)
                        by_path[str(resolved).casefold()] = value
                    except (OSError, ValueError):
                        pass
        return by_path, by_hash

    def _iter_candidates(self) -> Iterable[Path]:
        if not self.mesh_root.is_dir() or self.mesh_root.is_symlink():
            return ()
        result: list[Path] = []
        for profile_root in sorted(self.mesh_root.iterdir(), key=lambda item: item.name.casefold()):
            if profile_root.is_symlink() or not profile_root.is_dir():
                continue
            raw_root = profile_root / "raw"
            if not raw_root.is_dir() or raw_root.is_symlink():
                continue
            for current, directories, files in os.walk(raw_root, followlinks=False):
                current_path = Path(current)
                directories[:] = [
                    name
                    for name in directories
                    if not (current_path / name).is_symlink()
                ]
                for name in files:
                    path = current_path / name
                    lowered = name.casefold()
                    if path.is_symlink() or lowered.endswith((".part", ".tmp", ".partial")):
                        continue
                    if not lowered.endswith(_SUPPORTED_SUFFIXES):
                        continue
                    try:
                        resolved = path.resolve(strict=True)
                        resolved.relative_to(self.mesh_root)
                    except (OSError, ValueError):
                        continue
                    if resolved.is_file():
                        result.append(resolved)
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    len(item.relative_to(self.mesh_root).parts),
                    item.relative_to(self.mesh_root).as_posix().casefold(),
                ),
            )
        )

    def _match_profile(
        self,
        path: Path,
        profile_by_folder: Mapping[str, MeshMrProfile],
        profiles_by_identity: Mapping[tuple[str, str], list[MeshMrProfile]],
    ) -> tuple[MeshMrProfile | None, str, str, str]:
        folder_name = path.relative_to(self.mesh_root).parts[0]
        direct = profile_by_folder.get(folder_name.casefold())
        train_no, role = self._identity(folder_name)
        if direct is not None:
            profile_train, profile_role = self._identity(direct.display_name)
            return direct, train_no or profile_train, role or profile_role, "matched"
        matches = profiles_by_identity.get((train_no, role), []) if train_no and role else []
        if len(matches) == 1:
            return matches[0], train_no, role, "matched"
        file_train, file_role = self._identity(path.name)
        matches = profiles_by_identity.get((file_train, file_role), []) if file_train and file_role else []
        if len(matches) == 1:
            return matches[0], file_train, file_role, "matched"
        return None, train_no or file_train, role or file_role, "ambiguous" if len(matches) > 1 else "unmatched"

    @staticmethod
    def _profiles_by_identity(
        profiles: Iterable[MeshMrProfile],
    ) -> dict[tuple[str, str], list[MeshMrProfile]]:
        result: dict[tuple[str, str], list[MeshMrProfile]] = {}
        for profile in profiles:
            identity = MeshLocalScanService._identity(profile.display_name)
            if all(identity):
                result.setdefault(identity, []).append(profile)
        return result

    @staticmethod
    def _identity(value: str) -> tuple[str, str]:
        match = _IDENTITY_RE.search(str(value or ""))
        if not match:
            return "", ""
        role = match.group("role").upper()
        if role == "TC":
            role = "CT"
        return match.group("train").zfill(2), role

    @staticmethod
    def _session_id(source: Mapping[str, object] | None) -> str:
        return str((source or {}).get("session_id") or "")

    @staticmethod
    def _file_type(path: Path) -> str:
        lowered = path.name.casefold()
        if lowered.endswith(".zip"):
            return "zip"
        if lowered.endswith(".log.gz"):
            return "log_gz"
        return "log"

    def _validate_candidate(self, path: Path, bundle_service: MeshBundleImportService) -> str:
        try:
            if path.stat().st_size <= 0:
                return "文件为空，不能导入"
            if path.name.casefold().endswith(".log.gz"):
                expanded = 0
                with gzip.open(path, "rb") as source:
                    while chunk := source.read(1024 * 1024):
                        expanded += len(chunk)
                        if expanded > _MAX_GZIP_EXPANDED_BYTES:
                            return "GZIP 解压后超过 512 MiB，拒绝导入"
            elif path.name.casefold().endswith(".zip"):
                bundle_service.inspect(path)
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            return f"GZIP 文件损坏：{exc}"
        except (MeshBundleImportError, zipfile.BadZipFile) as exc:
            return f"ZIP 文件无效：{exc}"
        return ""

    @staticmethod
    def _sha256(path: Path, should_cancel: Callable[[], bool] | None) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                MeshLocalScanService._raise_if_cancelled(should_cancel)
                digest.update(chunk)
        return digest.hexdigest()

    def _resolve_candidate(self, candidate: Mapping[str, object]) -> Path:
        relative = Path(str(candidate.get("relative_path") or ""))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise MeshLocalScanError("CANDIDATE_PATH_INVALID", "本地日志候选路径无效")
        unresolved = self.mesh_root / relative
        if unresolved.is_symlink() or any(parent.is_symlink() for parent in unresolved.parents if parent != self.mesh_root.parent):
            raise MeshLocalScanError("CANDIDATE_PATH_INVALID", "本地日志候选不允许使用符号链接")
        path = unresolved.resolve()
        try:
            path.relative_to(self.mesh_root)
        except ValueError as exc:
            raise MeshLocalScanError("CANDIDATE_PATH_INVALID", "本地日志候选超出当前局点") from exc
        if not path.is_file():
            raise MeshLocalScanError("CANDIDATE_NOT_FOUND", "本地日志候选已不存在")
        return path

    def _publish_source_results(self, rows: Iterable[Mapping[str, object]]) -> None:
        prepared = [
            {
                "content_sha256": item.get("content_sha256"),
                "raw_sha256": item.get("raw_sha256"),
                "mr_id": item.get("profile_id"),
                "source_file_id": item.get("source_id"),
                "stored_filename": item.get("stored_filename"),
            }
            for item in rows
            if item.get("profile_id") and item.get("source_id")
        ]
        if prepared:
            MeshCatalogRepository(self.paths.mesh_catalog_path(self.site_name)).upsert_source_fingerprints(prepared)

    @staticmethod
    def _stats(candidates: list[Mapping[str, object]]) -> dict[str, int]:
        statuses = [str(item.get("scan_status") or "") for item in candidates]
        return {
            "found_count": len(candidates),
            "unregistered_count": sum(
                value in {"unregistered", "needs_metadata", "failed", "parse_failed", "repair_failed"}
                for value in statuses
            ),
            "imported_count": statuses.count("imported"),
            "duplicate_count": statuses.count("duplicate"),
            "invalid_count": statuses.count("invalid"),
            "needs_metadata_count": statuses.count("needs_metadata"),
            "failed_count": sum(value in {"failed", "parse_failed", "repair_failed"} for value in statuses),
            "waiting_repair_count": statuses.count("waiting_repair"),
            "repairing_count": statuses.count("repairing"),
            "queued_count": statuses.count("queued"),
            "parsing_count": statuses.count("parsing"),
            "repair_failed_count": statuses.count("repair_failed"),
            "parse_failed_count": statuses.count("parse_failed"),
            "ignored_count": statuses.count("ignored"),
        }

    def _manifest_path(self, scan_id: str) -> Path:
        self._validate_scan_id(scan_id)
        path = (self.cache_root / scan_id / "manifest.json").resolve()
        try:
            path.relative_to(self.cache_root)
        except ValueError as exc:
            raise MeshLocalScanError("SCAN_NOT_FOUND", "本地扫描结果不存在") from exc
        return path

    def _read_manifest(self, scan_id: str) -> dict[str, object]:
        path = self._manifest_path(scan_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MeshLocalScanError("SCAN_NOT_FOUND", "本地扫描结果不存在或已过期") from exc
        if not isinstance(value, dict) or value.get("site_id") != self.site_name:
            raise MeshLocalScanError("SCAN_NOT_FOUND", "本地扫描结果不存在或不属于当前局点")
        return value

    def _write_manifest(self, manifest: Mapping[str, object]) -> None:
        path = self._manifest_path(str(manifest.get("scan_id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, manifest)

    def _fingerprint_cache_path(self) -> Path:
        return self.cache_root / "fingerprints.json"

    def _read_fingerprint_cache(self) -> dict[str, dict[str, object]]:
        try:
            value = json.loads(self._fingerprint_cache_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(key): dict(item)
            for key, item in value.items()
            if isinstance(item, dict)
        }

    def _write_fingerprint_cache(self, value: Mapping[str, object]) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(self._fingerprint_cache_path(), value)

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                json.dump(value, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _cleanup_expired(self) -> None:
        if not self.cache_root.is_dir():
            return
        now = datetime.now(UTC)
        directories = [
            item
            for item in self.cache_root.iterdir()
            if item.is_dir() and not item.is_symlink() and SCAN_ID_RE.fullmatch(item.name)
        ]
        directories.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for index, directory in enumerate(directories):
            modified = datetime.fromtimestamp(directory.stat().st_mtime, UTC)
            if index < _MAX_SCANS and now - modified <= _SCAN_TTL:
                continue
            try:
                directory.resolve().relative_to(self.cache_root)
                shutil.rmtree(directory)
            except (OSError, ValueError):
                app_logger.log_warning("MESH_LOCAL_SCAN_CACHE_CLEANUP_FAILED", directory.name)

    @staticmethod
    def _validate_scan_id(scan_id: str) -> None:
        if not SCAN_ID_RE.fullmatch(str(scan_id or "")):
            raise MeshLocalScanError("SCAN_NOT_FOUND", "本地扫描结果不存在")

    @staticmethod
    def _raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
        if should_cancel and should_cancel():
            from netconsole.services.job_center.job_context import BackgroundTaskCancelled

            raise BackgroundTaskCancelled("本地 MESH 日志任务已取消")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, MeshLocalScanError):
            return str(exc)
        if isinstance(exc, MeshBundleImportError):
            return str(exc)
        if isinstance(exc, (gzip.BadGzipFile, EOFError)):
            return f"GZIP 文件损坏：{exc}"
        return str(exc) or exc.__class__.__name__

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()


__all__ = ["MeshLocalScanError", "MeshLocalScanService"]
