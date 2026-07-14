from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.file_management import (
    FileDownloadResultDTO,
    FileDownloadTaskDTO,
    FileManagementCapabilityDTO,
    FileManagementStatusDTO,
    ManagedFileDTO,
    ManagedFilePageDTO,
)
from netconsole.models.task_state import TaskState
from netconsole.services.background_job import BackgroundJob

if TYPE_CHECKING:
    from netconsole.services.job_center.job_context import JobContext
    from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
    from netconsole.services.job_center.task_application_service import TaskApplicationService


FILE_REF_RE = re.compile(r"^fm1_[0-9a-f]{32}$")
FILE_CATEGORIES = {"session", "raw", "package", "artifact"}
ARTIFACT_SUFFIXES = {".csv", ".diff", ".html", ".json", ".md", ".pdf", ".png", ".txt", ".xls", ".xlsx"}
SESSION_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".pcap", ".pcapng", ".txt", ".yaml", ".yml"}
REMOTE_FILES_UNAVAILABLE = "Web 首版不连接设备，仅提供局点本地文件浏览与下载。"


class FileManagementError(ValueError):
    pass


class FileReferenceNotFound(FileManagementError):
    pass


@dataclass(frozen=True)
class ResolvedManagedFile:
    file_ref: str
    site_id: str
    path: Path
    relative_path: str
    category: str


class FileManagementApplicationService:
    """局点本地文件的只读索引与受控下载任务入口。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        task_service: TaskApplicationService | None = None,
        process_adapter: LocalProcessAdapter | None = None,
        site_name: str = "demo",
    ) -> None:
        self.paths = paths
        self.site_name = str(site_name or "demo")
        self.task_service = task_service
        self.process_adapter = process_adapter
        self._owns_process_adapter = False
        if self.task_service is not None and self.process_adapter is None:
            from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter

            self.process_adapter = LocalProcessAdapter(self.task_service)
            self._owns_process_adapter = True

    def close(self) -> None:
        if self._owns_process_adapter and self.process_adapter is not None:
            self.process_adapter.shutdown()

    def current_site_id(self) -> str:
        try:
            return SiteManager(self.paths).get_current_site()
        except (OSError, ValueError, KeyError):
            return self.site_name

    def status(self, site_id: str = "") -> FileManagementStatusDTO:
        site = self._site_id(site_id)
        return FileManagementStatusDTO(
            site_id=site,
            local_files=FileManagementCapabilityDTO(
                available=self._files_root(site).is_dir(),
                message="" if self._files_root(site).is_dir() else "当前局点尚未创建本地文件目录。",
            ),
            device_files=FileManagementCapabilityDTO(available=False, message=REMOTE_FILES_UNAVAILABLE),
        )

    def list_files(
        self,
        site_id: str = "",
        *,
        category: str = "",
        search: str = "",
        limit: int = 200,
    ) -> ManagedFilePageDTO:
        site = self._site_id(site_id)
        selected_category = str(category or "").strip().casefold()
        if selected_category and selected_category not in FILE_CATEGORIES:
            raise FileManagementError("文件分类无效")
        query = str(search or "").strip().casefold()
        rows: list[ManagedFileDTO] = []
        for path in self._iter_files(site):
            resolved = self._resolve_candidate(site, path)
            if resolved is None or (selected_category and resolved.category != selected_category):
                continue
            if query and query not in f"{path.name} {resolved.relative_path}".casefold():
                continue
            try:
                stat_result = path.stat()
            except OSError:
                continue
            rows.append(
                ManagedFileDTO(
                    file_ref=resolved.file_ref,
                    site_id=site,
                    category=resolved.category,
                    name=path.name,
                    relative_path=resolved.relative_path,
                    size_bytes=int(stat_result.st_size),
                    modified_at=datetime.fromtimestamp(stat_result.st_mtime).isoformat(timespec="seconds"),
                )
            )
        rows.sort(key=lambda item: (item.modified_at or "", item.relative_path.casefold()), reverse=True)
        return ManagedFilePageDTO(site_id=site, category=selected_category, items=rows[: max(1, min(int(limit), 500))], total=len(rows))

    def resolve_ref(self, site_id: str, file_ref: str) -> ResolvedManagedFile:
        site = self._site_id(site_id)
        value = str(file_ref or "").strip()
        if not FILE_REF_RE.fullmatch(value):
            raise FileReferenceNotFound("文件引用不存在")
        for path in self._iter_files(site):
            resolved = self._resolve_candidate(site, path)
            if resolved is not None and resolved.file_ref == value:
                return resolved
        raise FileReferenceNotFound("文件不存在或已不可用")

    def submit_download(self, site_id: str, file_ref: str) -> FileDownloadTaskDTO:
        if self.task_service is None or self.process_adapter is None:
            raise RuntimeError("文件下载任务宿主未接线")
        resolved = self.resolve_ref(site_id, file_ref)
        task_id = uuid4().hex
        job = BackgroundJob(
            job_id=task_id,
            task_type="file_management_download",
            params={
                "site_name": resolved.site_id,
                "file_ref": resolved.file_ref,
                "task_name": f"文件下载 - {resolved.path.name}",
                "task_source": "local",
                "owner": "web_file_management",
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
            },
        )
        try:
            self.process_adapter.start_job(job)
        except Exception as exc:
            raise RuntimeError("文件下载任务启动失败") from exc
        return self.download_task(resolved.site_id, task_id) or FileDownloadTaskDTO(
            task_id=task_id,
            site_id=resolved.site_id,
            status=TaskState.PENDING.value,
            progress=0,
            message="已创建文件下载任务",
        )

    def download_task(self, site_id: str, task_id: str) -> FileDownloadTaskDTO | None:
        if self.task_service is None:
            return None
        site = self._site_id(site_id)
        snapshot = self.task_service.repository(site).get(str(task_id or ""))
        if (
            snapshot is None
            or snapshot.task_type != "file_management_download"
            or snapshot.source != "local"
            or snapshot.owner != "web_file_management"
        ):
            return None
        result = dict(snapshot.result or {})
        result_dto = None
        if snapshot.status is TaskState.COMPLETED and result.get("download_ref") and result.get("name"):
            result_dto = FileDownloadResultDTO(
                file_ref=str(result["download_ref"]),
                name=str(result["name"]),
                size_bytes=max(0, int(result.get("size_bytes") or 0)),
            )
        message = str(snapshot.message or "")
        if snapshot.status is TaskState.FAILED:
            message = "文件下载失败"
        elif snapshot.status is TaskState.CANCELLED:
            message = "文件下载已取消"
        return FileDownloadTaskDTO(
            task_id=snapshot.task_id,
            site_id=site,
            status=snapshot.status.value,
            progress=max(0, min(int(snapshot.progress or 0), 100)),
            stage=str(snapshot.stage or ""),
            message=message,
            result=result_dto,
        )

    def open_download(self, site_id: str, task_id: str) -> tuple[Path, str]:
        task = self.download_task(site_id, task_id)
        if task is None:
            raise FileReferenceNotFound("下载任务不存在")
        if task.status != TaskState.COMPLETED.value or task.result is None:
            raise FileManagementError("文件下载任务尚未完成")
        resolved = self.resolve_ref(task.site_id, task.result.file_ref)
        return resolved.path, task.result.name

    def validate_for_download(self, context: JobContext) -> dict[str, object]:
        site = self._site_id(str(context.params.get("site_name") or ""))
        source = self.resolve_ref(site, str(context.params.get("file_ref") or ""))
        context.check_cancelled()
        context.progress("file_validate", 1, 1, f"已校验 {source.path.name}")
        return {
            "download_ref": source.file_ref,
            "name": source.path.name,
            "size_bytes": source.path.stat().st_size,
        }

    def _site_id(self, site_id: str) -> str:
        value = str(site_id or self.current_site_id()).strip()
        try:
            value = SiteManager(self.paths).validate_site_name(value)
        except ValueError as exc:
            raise FileManagementError("局点标识无效") from exc
        if not self.paths.site_dir(value).is_dir():
            raise FileManagementError("局点不存在")
        return value

    def _files_root(self, site_id: str) -> Path:
        return self.paths.site_files_dir(site_id).resolve()

    def _iter_files(self, site_id: str):
        root = self._files_root(site_id)
        if not root.is_dir():
            return
        pending = [root]
        while pending:
            current = pending.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        path = Path(entry.path)
                        if self._resolve_candidate(site_id, path) is not None:
                            yield path
                except OSError:
                    continue

    def _resolve_candidate(self, site_id: str, path: Path) -> ResolvedManagedFile | None:
        root = self._files_root(site_id)
        try:
            candidate = path.resolve(strict=True)
            relative = candidate.relative_to(root).as_posix()
        except (OSError, ValueError):
            return None
        if path.is_symlink() or not candidate.is_file():
            return None
        category = classify_file(relative)
        if category is None:
            return None
        return ResolvedManagedFile(self._file_ref(site_id, relative), site_id, candidate, relative, category)

    def _file_ref(self, site_id: str, relative_path: str) -> str:
        digest = hashlib.sha256(f"{site_id}\0{relative_path}".encode("utf-8")).hexdigest()[:32]
        return f"fm1_{digest}"


def classify_file(relative_path: str) -> str | None:
    parts = {part.casefold() for part in Path(relative_path).parts}
    name = Path(relative_path).name.casefold()
    if parts & {"parsed", "cache", "tmp", "runtime"}:
        return None
    if name.endswith((".sqlite", ".sqlite3", ".db", "-wal", "-shm", "-journal")):
        return None
    if "raw" in parts:
        return "raw"
    if name.endswith((".zip", ".tar.gz", ".zip.gz")) or ("imports" in parts and "online_mr" in parts):
        return "package"
    suffix = Path(relative_path).suffix.casefold()
    if parts & {"outputs", "reports", "artifacts", "view"} and suffix in ARTIFACT_SUFFIXES:
        return "artifact"
    if "online_mr" in parts and "sessions" in parts and suffix in SESSION_SUFFIXES:
        return "session"
    return None


def run_file_management_download(context: JobContext) -> dict[str, object]:
    service = FileManagementApplicationService(context.paths)
    return service.validate_for_download(context)


__all__ = [
    "FILE_CATEGORIES",
    "FileManagementApplicationService",
    "FileManagementError",
    "FileReferenceNotFound",
    "ResolvedManagedFile",
    "REMOTE_FILES_UNAVAILABLE",
    "classify_file",
    "run_file_management_download",
]
