from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import ImportedLogFile, MeshMrProfile, MeshSwitchEvent, ParseIssue
from netconsole.parsers.mesh_log_parser import MeshLogParser, inspect_mesh_log_path, make_imported_file
from netconsole.models.mesh_analysis_params import mesh_analysis_params_to_json
from netconsole.repositories.mesh_mr_repository import PARSER_VERSION, MeshMrRepository
from netconsole.services.mesh_analysis_params_service import load_site_mesh_analysis_params
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_import_preflight_service import MeshImportPreflightService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.file_contract import ImportValidationError


MESH_SOURCE_TYPES = frozenset(
    {"manual_upload", "device_download", "local_scan", "unattended_collection"}
)


@dataclass
class MeshImportResult:
    files: list[ImportedLogFile] = field(default_factory=list)
    events: list[MeshSwitchEvent] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    imported_count: int = 0
    duplicate_count: int = 0
    parsed_record_count: int = 0
    source_results: list[dict[str, object]] = field(default_factory=list)


class MeshImportService:
    def __init__(
        self,
        site_name: str,
        paths: PathResolver,
        *,
        database_path: Path | None = None,
        parsed_dir: Path | None = None,
        refresh_catalog: bool = True,
    ) -> None:
        self.site_name = site_name
        self.paths = paths
        self.storage = MeshStorageService(site_name, paths)
        self.parser = MeshLogParser()
        self.database_path = database_path
        self.parsed_dir = parsed_dir
        self.refresh_catalog = refresh_catalog

    def import_files(
        self,
        profile: MeshMrProfile,
        files: list[Path],
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[int, int, int, int, int], None] | None = None,
        *,
        source_type: str = "manual_upload",
        source_device_id: str = "",
        parse_task_id: str = "",
    ) -> MeshImportResult:
        source_type = str(source_type or "manual_upload").strip().casefold()
        if source_type not in MESH_SOURCE_TYPES:
            raise ImportValidationError(f"不支持的 MESH 来源类型：{source_type}")
        self._validate_files(files)
        repo = (
            MeshMrRepository(
                self.database_path,
                parsed_dir=self.parsed_dir,
                index_database=True,
            )
            if self.database_path is not None
            else self.storage.mr_repository(profile)
        )
        analysis_params = load_site_mesh_analysis_params(self.paths, self.site_name)
        analysis_params_json = mesh_analysis_params_to_json(analysis_params)
        app_logger.log_info("MESH_IMPORT_ANALYSIS_PARAMS_SNAPSHOT", f"site={self.site_name} params={analysis_params_json}")
        result = MeshImportResult()
        preflight = (
            MeshImportPreflightService(self.site_name, self.paths)
            if self.database_path is None
            else None
        )
        total = len(files)
        next_record_seq = 1
        for index, path in enumerate(files, start=1):
            if should_cancel and should_cancel():
                break
            metadata = inspect_mesh_log_path(path)
            if preflight is not None:
                preflight.inspect_import(
                    profile,
                    content_sha256=metadata.content_sha256,
                    raw_sha256=metadata.raw_sha256,
                )
            duplicate = repo.find_by_content_sha256(
                metadata.content_sha256,
                raw_sha256=metadata.raw_sha256,
            )
            if duplicate is not None:
                if preflight is not None:
                    assessment = preflight.inspect_source(profile, duplicate)
                    if assessment.broken:
                        recovered = preflight.prepare_broken_duplicate(
                            profile,
                            duplicate,
                            selected_file=path,
                            metadata=metadata,
                        )
                        info = make_imported_file(
                            path,
                            source_label=profile.display_name,
                            precomputed_hash=metadata.raw_sha256,
                        )
                        info.status = "recovered"
                        result.files.append(info)
                        result.imported_count += 1
                        result.parsed_record_count += int(
                            recovered.get("parsed_record_count") or 0
                        )
                        result.source_results.append(
                            {
                                "result": "recovered_existing",
                                "duplicate_status": "broken_same_mr_recovered",
                                "original_filename": path.name,
                                "raw_sha256": metadata.raw_sha256,
                                "content_sha256": metadata.content_sha256,
                                "source_id": int(duplicate["id"]),
                                "session_id": str(recovered["session_id"]),
                                "profile_id": profile.mr_id,
                                "source_type": str(
                                    duplicate.get("source_type") or source_type
                                ),
                            }
                        )
                        continue
                info = make_imported_file(path, source_label=profile.display_name, precomputed_hash=metadata.raw_sha256)
                info.status = "duplicate"
                result.files.append(info)
                result.duplicate_count += 1
                result.source_results.append(
                    {
                        "result": "duplicate_skipped",
                        "duplicate_status": "duplicate_same_mr",
                        "original_filename": path.name,
                        "raw_sha256": metadata.raw_sha256,
                        "content_sha256": metadata.content_sha256,
                        "existing_source_id": int(duplicate["id"]),
                        "existing_stored_filename": str(
                            duplicate.get("stored_filename")
                            or duplicate.get("archived_filename")
                            or ""
                        ),
                        "existing_session_id": f"{profile.mr_id}:{int(duplicate['id'])}",
                        "existing_profile_id": profile.mr_id,
                        "source_type": str(duplicate.get("source_type") or source_type),
                    }
                )
                app_logger.log_info("MESH_FILE_DUPLICATE", path.name)
                continue

            def on_file_progress(lines: int, parsed: int, skipped: int, file_index=index) -> None:
                if progress:
                    progress(file_index, total, lines, parsed, skipped)

            info, records, issues = self.parser.parse_file(
                path,
                source_label=profile.display_name,
                precomputed_hash=metadata.raw_sha256,
                should_cancel=should_cancel,
                progress=on_file_progress,
            )
            timestamp_missing = metadata.first_log_timestamp is None
            if not records and not timestamp_missing:
                raise ImportValidationError(f"不是 NetConsole 支持的导入文件：{path.name} 未识别到 MESH 记录")
            if not records:
                info.status = "timestamp_not_found"
                info.error_message = "未识别到首个有效日志时间，无法生成日期归档名称。"
                issues.append(
                    ParseIssue(
                        str(path),
                        0,
                        "未识别日志时间",
                        info.error_message,
                        "",
                    )
                )
            info.file_hash = metadata.raw_sha256
            first_sample = min((record.sample_time for record in records), default=None)
            archive = self.storage.archive_raw_file_with_metadata(
                profile,
                path,
                metadata.first_log_timestamp or first_sample,
            )
            archived_path = archive.path
            info.archived_path = archived_path
            info.imported_at = datetime.now()
            for record in records:
                record.source_label = profile.display_name
                record.source_file = str(archived_path)
                record.source_file_order = index
                record.record_seq = next_record_seq
                next_record_seq += 1
            for issue in issues:
                issue.source_file = str(archived_path)
            result.files.append(info)
            result.issues.extend(issues)
            app_logger.log_info("MESH_FILE_IMPORTED", archived_path.name)
            if should_cancel and should_cancel():
                info.status = "cancelled"
            source_file_id = repo.insert_file_result(
                profile.mr_id,
                path,
                archived_path,
                info.file_hash,
                info.size,
                info.modified_time,
                PARSER_VERSION,
                info.status,
                info.start_time,
                info.end_time,
                info.lines_read,
                len(records),
                info.skipped_count,
                0,
                len(issues),
                info.error_message,
                records,
                [],
                issues,
                analysis_params_json=analysis_params_json,
                raw_sha256=metadata.raw_sha256,
                content_sha256=metadata.content_sha256,
                profile_id=profile.mr_id,
                linked_mr_id=profile.linked_device_uuid or str(profile.linked_device_id or ""),
                first_log_timestamp=metadata.first_log_timestamp,
                last_log_timestamp=metadata.last_log_timestamp,
                log_date=archive.log_date.isoformat() if archive.log_date else "",
                daily_sequence=archive.daily_sequence,
                rename_status=archive.rename_status,
                rename_warning=archive.rename_warning,
                source_status="imported" if records else "timestamp_not_found",
                source_type=source_type,
                source_device_id=str(source_device_id or ""),
                parse_task_id=str(parse_task_id or ""),
            )
            result.source_results.append(
                {
                    "result": "imported" if records else "archived_without_analysis",
                    "duplicate_status": "new",
                    "source_id": source_file_id,
                    "session_id": f"{profile.mr_id}:{source_file_id}",
                    "profile_id": profile.mr_id,
                    "original_filename": path.name,
                    "stored_filename": archive.stored_filename,
                    "raw_sha256": metadata.raw_sha256,
                    "content_sha256": metadata.content_sha256,
                    "first_log_timestamp": metadata.first_log_timestamp.isoformat() if metadata.first_log_timestamp else None,
                    "last_log_timestamp": metadata.last_log_timestamp.isoformat() if metadata.last_log_timestamp else None,
                    "log_date": archive.log_date.isoformat() if archive.log_date else None,
                    "daily_sequence": archive.daily_sequence,
                    "rename_status": archive.rename_status,
                    "rename_warning": archive.rename_warning,
                    "source_type": source_type,
                    "source_device_id": str(source_device_id or ""),
                    "parse_task_id": str(parse_task_id or ""),
                }
            )
            if preflight is not None:
                imported_source = repo.get_source_file(source_file_id)
                if imported_source is not None:
                    preflight.inspect_source(profile, imported_source)
            result.imported_count += 1
            result.parsed_record_count += len(records)
            if progress:
                progress(index, total, info.lines_read, result.parsed_record_count, info.skipped_count)
        if result.imported_count:
            try:
                mapped_count = MeshPeerMappingService(self.site_name, self.paths).refresh_repository(repo)
                if mapped_count:
                    app_logger.log_info("MESH_PEER_MAPPING_REFRESHED", f"{profile.display_name}:{mapped_count}")
            except Exception as exc:
                app_logger.log_error("MESH_PEER_MAPPING_REFRESH_FAILED", str(exc))
            repo.rebuild_derived_analysis(should_cancel=should_cancel)
            if self.refresh_catalog:
                self.storage.refresh_catalog_summary(profile)
        return result

    def _validate_files(self, files: list[Path]) -> None:
        if not files:
            raise ImportValidationError("未选择导入文件")
        for path in files:
            name = path.name.casefold()
            if not (name.endswith(".log") or name.endswith(".txt") or name.endswith(".log.gz") or name.endswith(".txt.gz")):
                raise ImportValidationError(f"文件类型不匹配：{path.name}")
            if not path.is_file():
                raise ImportValidationError(f"文件不存在或无法读取：{path}")
            if path.stat().st_size <= 0:
                raise ImportValidationError(f"文件为空：{path.name}")

    def discover_mesh_logs(self, folder: Path, include_txt: bool = False) -> list[Path]:
        if not folder.exists():
            return []
        paths: list[Path] = []
        for path in folder.iterdir():
            if not path.is_file():
                continue
            name = path.name.lower()
            if name == "meshlog.log" or name.endswith("meshlog.log") or name.endswith("meshlog.log.gz"):
                paths.append(path)
            elif include_txt and name.endswith(".txt"):
                paths.append(path)
        return sorted(paths, key=lambda item: item.name.casefold())
