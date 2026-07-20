from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import ImportedLogFile, MeshMrProfile, MeshSwitchEvent, ParseIssue
from netconsole.parsers.mesh_log_parser import MeshLogParser, make_imported_file, sha256_file
from netconsole.models.mesh_analysis_params import mesh_analysis_params_to_json
from netconsole.services.mesh_log_analysis_service import (
    PARSER_VERSION,
)
from netconsole.services.mesh_analysis_params_service import load_site_mesh_analysis_params
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.file_contract import ImportValidationError


@dataclass
class MeshImportResult:
    files: list[ImportedLogFile] = field(default_factory=list)
    events: list[MeshSwitchEvent] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    imported_count: int = 0
    duplicate_count: int = 0
    parsed_record_count: int = 0


class MeshImportService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self.storage = MeshStorageService(site_name, paths)
        self.parser = MeshLogParser()

    def import_files(
        self,
        profile: MeshMrProfile,
        files: list[Path],
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[int, int, int, int, int], None] | None = None,
    ) -> MeshImportResult:
        self._validate_files(files)
        repo = self.storage.mr_repository(profile)
        analysis_params = load_site_mesh_analysis_params(self.paths, self.site_name)
        analysis_params_json = mesh_analysis_params_to_json(analysis_params)
        app_logger.log_info("MESH_IMPORT_ANALYSIS_PARAMS_SNAPSHOT", f"site={self.site_name} params={analysis_params_json}")
        result = MeshImportResult()
        total = len(files)
        next_record_seq = 1
        for index, path in enumerate(files, start=1):
            if should_cancel and should_cancel():
                break
            digest = sha256_file(path)
            if repo.has_sha256(digest):
                info = make_imported_file(path, source_label=profile.display_name, precomputed_hash=digest)
                info.status = "duplicate"
                result.files.append(info)
                result.duplicate_count += 1
                app_logger.log_info("MESH_FILE_DUPLICATE", path.name)
                continue

            def on_file_progress(lines: int, parsed: int, skipped: int, file_index=index) -> None:
                if progress:
                    progress(file_index, total, lines, parsed, skipped)

            info, records, issues = self.parser.parse_file(path, source_label=profile.display_name, precomputed_hash=digest, should_cancel=should_cancel, progress=on_file_progress)
            if not records:
                raise ImportValidationError(f"不是 NetConsole 支持的导入文件：{path.name} 未识别到 MESH 记录")
            info.file_hash = digest
            first_sample = min((record.sample_time for record in records), default=None)
            archived_path = self.storage.archive_raw_file(profile, path, first_sample)
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
            repo.insert_file_result(
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
            )
            result.imported_count += 1
            result.parsed_record_count += len(records)
            if progress:
                progress(index, total, info.lines_read, result.parsed_record_count, info.skipped_count)
        try:
            mapped_count = MeshPeerMappingService(self.site_name, self.paths).refresh_repository(repo)
            if mapped_count:
                app_logger.log_info("MESH_PEER_MAPPING_REFRESHED", f"{profile.display_name}:{mapped_count}")
        except Exception as exc:
            app_logger.log_error("MESH_PEER_MAPPING_REFRESH_FAILED", str(exc))
        repo.rebuild_derived_analysis(should_cancel=should_cancel)
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
            if not self.parser.is_supported_file(path):
                raise ImportValidationError(f"不是 NetConsole 支持的导入文件：{path.name} 未识别到 MESH 记录")

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
