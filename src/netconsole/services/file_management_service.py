from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.models.api.file_management import (
    FileConnectionDTO,
    FileDesktopActionDTO,
    FileDownloadResultDTO,
    FileDownloadTaskDTO,
    FileManagementCapabilityDTO,
    FileManagementStatusDTO,
    ManagedFileDTO,
    ManagedFilePageDTO,
    RemoteFileEntryDTO,
    RemoteFilePageDTO,
)
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.file_transfer_service import (
    FileTransferService,
    RemoteDeviceFile,
    file_sha256,
    is_within_remote_root,
    normalize_remote_path,
    parent_remote_path,
)

if TYPE_CHECKING:
    from netconsole.models.task_snapshot import TaskSnapshot
    from netconsole.services.job_center.job_context import JobContext
    from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
    from netconsole.services.job_center.task_application_service import TaskApplicationService


FILE_REF_RE = re.compile(r"^fm1_[0-9a-f]{32}$")
CONNECTION_ID_RE = re.compile(r"^fc1_[0-9a-f]{32}$")
REMOTE_ENTRY_ID_RE = re.compile(r"^fe1_[0-9a-f]{32}$")
ARTIFACT_ID_RE = re.compile(r"^fa1_[0-9a-f]{32}$")
FILE_CATEGORIES = {"session", "raw", "package", "artifact"}
ARTIFACT_SUFFIXES = {".csv", ".diff", ".html", ".json", ".md", ".pdf", ".png", ".txt", ".xls", ".xlsx"}
PACKAGE_SUFFIXES = (".tar.gz", ".tgz", ".zip", ".zip.gz")
RAW_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".pcap", ".pcapng", ".txt", ".yaml", ".yml"}
SESSION_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".pcap", ".pcapng", ".txt", ".yaml", ".yml"}
REMOTE_FILES_UNAVAILABLE = "当前局点没有可用的设备资料库。"
REMOTE_FILES_AVAILABLE = "设备文件通过受控 SFTP 会话读取。"
WINSCP_INTEGRATION_MESSAGE = "WinSCP 需要 Desktop Action Service；当前 Web 宿主未提供桥接。"
ACTIVE_DOWNLOAD_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}


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


@dataclass(frozen=True)
class _RemoteEntry:
    device_id: str
    remote_file: RemoteDeviceFile


@dataclass
class _RemoteSession:
    connection_id: str
    site_id: str
    device_id: str
    device: Device
    transfer: FileTransferService
    root_path: str
    root_entry_id: str
    current_entry_id: str
    entries: dict[str, _RemoteEntry]
    lock: threading.RLock


DeviceResolver = Callable[[str, str], Device | None]
TransferServiceFactory = Callable[..., FileTransferService]


class FileManagementApplicationService:
    """文件管理 Web 用例：受控本地文件、设备会话和下载任务。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        task_service: TaskApplicationService | None = None,
        process_adapter: LocalProcessAdapter | None = None,
        site_name: str = "demo",
        device_resolver: DeviceResolver | None = None,
        transfer_factory: TransferServiceFactory = FileTransferService,
    ) -> None:
        self.paths = paths
        self.site_name = str(site_name or "demo")
        self.task_service = task_service
        self.process_adapter = process_adapter
        self._device_resolver = device_resolver
        self._transfer_factory = transfer_factory
        self._sessions: dict[str, _RemoteSession] = {}
        self._sessions_lock = threading.RLock()
        self._owns_process_adapter = False
        if self.task_service is not None and self.process_adapter is None:
            from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter

            self.process_adapter = LocalProcessAdapter(self.task_service)
            self._owns_process_adapter = True

    def close(self) -> None:
        """幂等关闭全部 Web 会话；FastAPI lifespan 必须在 shutdown 调用。"""
        with self._sessions_lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.transfer.disconnect()
            except Exception:
                pass
        if self._owns_process_adapter and self.process_adapter is not None:
            self.process_adapter.shutdown()

    def current_site_id(self) -> str:
        try:
            return SiteManager(self.paths).get_current_site()
        except (OSError, ValueError, KeyError):
            return self.site_name

    def status(self, site_id: str = "") -> FileManagementStatusDTO:
        site = self._site_id(site_id)
        device_db_exists = self.paths.site_db_path(site).is_file()
        return FileManagementStatusDTO(
            site_id=site,
            local_files=FileManagementCapabilityDTO(
                available=self._files_root(site).is_dir(),
                message="" if self._files_root(site).is_dir() else "当前局点尚未创建本地文件目录。",
            ),
            device_files=FileManagementCapabilityDTO(
                available=device_db_exists,
                message=REMOTE_FILES_AVAILABLE if device_db_exists else REMOTE_FILES_UNAVAILABLE,
            ),
            winscp=FileManagementCapabilityDTO(available=False, message=WINSCP_INTEGRATION_MESSAGE),
        )

    def connect_device(self, site_id: str, device_id: str) -> FileConnectionDTO:
        site = self._site_id(site_id)
        device = self._resolve_device(site, device_id)
        device_key = str(device.device_uuid or device_id)
        self._close_device_sessions(site, device_key)
        transfer = self._transfer_factory(site, self.paths, allow_remote_setup=False)
        try:
            root_path = normalize_remote_path(transfer.connect(device))
        except Exception as exc:
            try:
                transfer.disconnect()
            except Exception:
                pass
            raise RuntimeError(f"设备文件连接失败：{exc}") from exc
        connection_id = f"fc1_{uuid4().hex}"
        root_file = RemoteDeviceFile("根目录", root_path, None, None, "dir", is_dir=True, file_type="directory")
        root_entry_id = self._remote_entry_id(device_key, root_path)
        session = _RemoteSession(
            connection_id=connection_id,
            site_id=site,
            device_id=device_key,
            device=device,
            transfer=transfer,
            root_path=root_path,
            root_entry_id=root_entry_id,
            current_entry_id=root_entry_id,
            entries={root_entry_id: _RemoteEntry(device_key, root_file)},
            lock=threading.RLock(),
        )
        self._register_session(session)
        return self._connection_dto(session, "已连接")

    def disconnect_device(self, site_id: str, connection_id: str) -> FileConnectionDTO:
        session = self._session(site_id, connection_id)
        self._close_session(session)
        return self._connection_dto(session, "已断开", status="DISCONNECTED")

    def list_remote_files(self, site_id: str, connection_id: str, entry_id: str = "") -> RemoteFilePageDTO:
        session = self._session(site_id, connection_id)
        with session.lock:
            selected_id = str(entry_id or session.current_entry_id)
            selected = session.entries.get(selected_id)
            if selected is None:
                raise FileReferenceNotFound("远程目录引用不存在或不属于当前设备会话")
            if not selected.remote_file.is_dir:
                raise FileManagementError("只能浏览远程目录")
            try:
                files = session.transfer.list_directory(selected.remote_file.remote_path)
            except Exception as exc:
                raise RuntimeError(f"远程目录读取失败：{exc}") from exc
            items: list[RemoteFileEntryDTO] = []
            for remote_file in files:
                normalized = normalize_remote_path(
                    remote_file.remote_path,
                    current_path=selected.remote_file.remote_path,
                    root_path=session.root_path,
                )
                controlled = RemoteDeviceFile(
                    name=Path(remote_file.name).name,
                    remote_path=normalized,
                    size=remote_file.size,
                    modified_time=remote_file.modified_time,
                    category=remote_file.category,
                    is_dir=remote_file.is_dir,
                    file_type=remote_file.file_type,
                )
                child_id = self._remote_entry_id(session.device_id, normalized)
                session.entries[child_id] = _RemoteEntry(session.device_id, controlled)
                items.append(
                    RemoteFileEntryDTO(
                        entry_id=child_id,
                        name=controlled.name,
                        is_dir=controlled.is_dir,
                        size_bytes=None if controlled.is_dir else max(0, int(controlled.size or 0)),
                        modified_at=controlled.modified_time,
                        category=controlled.category,
                        file_type=controlled.file_type,
                        downloadable=not controlled.is_dir,
                    )
                )
            parent_path = parent_remote_path(selected.remote_file.remote_path, session.root_path)
            parent_id = self._remote_entry_id(session.device_id, parent_path)
            if parent_id not in session.entries:
                parent_name = Path(parent_path.rstrip("/")).name or "根目录"
                session.entries[parent_id] = _RemoteEntry(
                    session.device_id,
                    RemoteDeviceFile(parent_name, parent_path, None, None, "dir", is_dir=True, file_type="directory"),
                )
            session.current_entry_id = selected_id
            return RemoteFilePageDTO(
                connection_id=session.connection_id,
                current_entry_id=selected_id,
                parent_entry_id=parent_id,
                current_label="根目录" if selected_id == session.root_entry_id else selected.remote_file.name,
                items=sorted(items, key=lambda item: (not item.is_dir, item.name.casefold())),
            )

    def list_download_tasks(self, site_id: str, limit: int = 100) -> list[FileDownloadTaskDTO]:
        if self.task_service is None:
            return []
        site = self._site_id(site_id)
        requested = max(1, min(int(limit), 200))
        page_size = min(200, max(50, requested))
        tasks: list[FileDownloadTaskDTO] = []
        task_ids: set[str] = set()
        repository = self.task_service.repository(site)

        offset = 0
        while True:
            snapshots = repository.list(statuses=ACTIVE_DOWNLOAD_STATES, limit=page_size, offset=offset)
            if not snapshots:
                break
            offset += len(snapshots)
            for snapshot in snapshots:
                if self._is_download_snapshot(snapshot):
                    tasks.append(self._download_task_from_snapshot(site, snapshot))
                    task_ids.add(snapshot.task_id)
            if len(snapshots) < page_size:
                break

        if len(tasks) >= requested:
            return tasks

        offset = 0
        while len(tasks) < requested:
            snapshots = repository.list(limit=page_size, offset=offset)
            if not snapshots:
                break
            offset += len(snapshots)
            for snapshot in snapshots:
                if snapshot.task_id not in task_ids and self._is_download_snapshot(snapshot):
                    tasks.append(self._download_task_from_snapshot(site, snapshot))
                    task_ids.add(snapshot.task_id)
                    if len(tasks) >= requested:
                        break
            if len(snapshots) < page_size:
                break
        return tasks

    def cancel_download(self, site_id: str, task_id: str) -> FileDownloadTaskDTO:
        task = self.download_task(site_id, task_id)
        if task is None:
            raise FileReferenceNotFound("下载任务不存在")
        if task.status not in {TaskState.PENDING.value, TaskState.STARTING.value, TaskState.RUNNING.value, TaskState.STOPPING.value}:
            raise FileManagementError("下载任务当前不可停止")
        if self.process_adapter is None or not self.process_adapter.cancel_job(task.task_id):
            raise FileManagementError("下载任务当前不可停止")
        return self.download_task(site_id, task.task_id) or task

    def desktop_action(self, action: str, *, site_id: str = "", device_id: str = "", artifact_id: str = "") -> FileDesktopActionDTO:
        selected = str(action or "").strip()
        if selected == "winscp":
            if not str(device_id or "").strip():
                raise FileManagementError("WinSCP 操作缺少设备标识")
            self._resolve_device(self._site_id(site_id), device_id)
            return FileDesktopActionDTO(action=selected, message=WINSCP_INTEGRATION_MESSAGE)
        if selected == "open_result_dir":
            if not ARTIFACT_ID_RE.fullmatch(str(artifact_id or "")):
                raise FileReferenceNotFound("Artifact 引用不存在")
            return FileDesktopActionDTO(action=selected, message="打开结果目录需要 Desktop Action Service；当前 Web 宿主未提供桥接。")
        raise FileManagementError("不支持的桌面动作")

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

    def submit_download(
        self,
        site_id: str,
        file_ref: str = "",
        *,
        connection_id: str = "",
        remote_entry_id: str = "",
    ) -> FileDownloadTaskDTO:
        if self.task_service is None or self.process_adapter is None:
            raise RuntimeError("文件下载任务宿主未接线")
        site = self._site_id(site_id)
        if file_ref and (connection_id or remote_entry_id):
            raise FileManagementError("本地文件引用与远程文件引用不能同时提交")
        task_id = uuid4().hex
        params: dict[str, object]
        if str(file_ref or "").strip():
            resolved = self.resolve_ref(site, file_ref)
            params = {
                "site_name": resolved.site_id,
                "file_ref": resolved.file_ref,
                "task_name": f"文件下载 - {resolved.path.name}",
                "task_source": "local",
            }
        else:
            session = self._session(site, connection_id)
            with session.lock:
                entry = session.entries.get(str(remote_entry_id or ""))
                if entry is None or not REMOTE_ENTRY_ID_RE.fullmatch(str(remote_entry_id or "")):
                    raise FileReferenceNotFound("远程文件引用不存在或不属于当前设备会话")
                if entry.remote_file.is_dir:
                    raise FileManagementError("不能下载远程目录")
                candidate = session.transfer.local_path_for(session.device, entry.remote_file)
                target = candidate.with_name(f"{task_id}_{candidate.name}")
                relative_target = target.resolve().relative_to(self.paths.site_dir(site).resolve()).as_posix()
                params = {
                    "site_name": site,
                    "task_name": f"设备文件下载 - {entry.remote_file.name}",
                    "task_source": "local",
                    "file_source": "remote",
                    "device_id": session.device_id,
                    "remote_entry_id": str(remote_entry_id),
                    "remote_path": entry.remote_file.remote_path,
                    "remote_name": entry.remote_file.name,
                    "remote_size": int(entry.remote_file.size or 0),
                    "remote_modified_at": entry.remote_file.modified_time or "",
                    "remote_category": entry.remote_file.category,
                    "target_relative_path": relative_target,
                }
        params.update(
            {
                "owner": "web_file_management",
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
            }
        )
        job = BackgroundJob(
            job_id=task_id,
            task_type="file_management_download",
            params=params,
        )
        try:
            self.process_adapter.start_job(job)
        except Exception as exc:
            raise RuntimeError("文件下载任务启动失败") from exc
        return self.download_task(site, task_id) or FileDownloadTaskDTO(
            task_id=task_id,
            site_id=site,
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
            or snapshot.owner != "web_file_management"
            or snapshot.source != "local"
        ):
            return None
        return self._download_task_from_snapshot(site, snapshot)

    def _download_task_from_snapshot(self, site: str, snapshot) -> FileDownloadTaskDTO:
        result = dict(snapshot.result or {})
        result_dto = None
        if snapshot.status is TaskState.COMPLETED and result.get("name"):
            file_ref = str(result.get("download_ref") or "")
            artifact_id = str(result.get("artifact_id") or "")
            if FILE_REF_RE.fullmatch(file_ref) or ARTIFACT_ID_RE.fullmatch(artifact_id):
                try:
                    result_dto = FileDownloadResultDTO(
                        file_ref=file_ref,
                        name=str(result["name"]),
                        size_bytes=max(0, int(result.get("size_bytes") or 0)),
                        artifact_id=artifact_id,
                        relative_path=str(result.get("relative_path") or ""),
                        sha256=str(result.get("sha256") or ""),
                        device_id=str(result.get("device_id") or ""),
                        remote_entry_id=str(result.get("remote_entry_id") or ""),
                    )
                except (TypeError, ValueError):
                    result_dto = None
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
        if task.result.file_ref:
            resolved = self.resolve_ref(task.site_id, task.result.file_ref)
            return resolved.path, task.result.name
        if not ARTIFACT_ID_RE.fullmatch(task.result.artifact_id) or not task.result.relative_path:
            raise FileReferenceNotFound("下载结果 Artifact 不存在")
        path = self._safe_site_relative_path(task.site_id, task.result.relative_path, under_downloads=True)
        if not path.is_file():
            raise FileReferenceNotFound("下载结果文件不存在")
        if task.result.sha256 and file_sha256(path) != task.result.sha256:
            raise FileManagementError("下载结果校验失败")
        expected_artifact = self._artifact_id(task.task_id, task.result.relative_path, task.result.sha256)
        if task.result.artifact_id != expected_artifact:
            raise FileReferenceNotFound("下载结果 Artifact 引用无效")
        return path, task.result.name

    def validate_for_download(self, context: JobContext) -> dict[str, object]:
        site = self._site_id(str(context.params.get("site_name") or ""))
        file_ref = str(context.params.get("file_ref") or "")
        if file_ref:
            source = self.resolve_ref(site, file_ref)
            context.check_cancelled()
            context.progress("file_validate", 1, 1, f"已校验 {source.path.name}")
            return {
                "download_ref": source.file_ref,
                "name": source.path.name,
                "size_bytes": source.path.stat().st_size,
            }
        return self._download_remote(context, site)

    def _download_remote(self, context: JobContext, site: str) -> dict[str, object]:
        device_id = str(context.params.get("device_id") or "").strip()
        remote_entry_id = str(context.params.get("remote_entry_id") or "").strip()
        remote_path = str(context.params.get("remote_path") or "").strip()
        remote_name = str(context.params.get("remote_name") or "").strip()
        if not device_id or not REMOTE_ENTRY_ID_RE.fullmatch(remote_entry_id):
            raise FileReferenceNotFound("远程文件引用不存在")
        if (
            not remote_path
            or not remote_name
            or remote_name in {".", ".."}
            or Path(remote_name).name != remote_name
            or any(char in remote_name for char in "/\\")
        ):
            raise FileReferenceNotFound("远程文件名或路径无效")
        normalized_path = normalize_remote_path(remote_path)
        if self._remote_entry_id(device_id, normalized_path) != remote_entry_id:
            raise FileReferenceNotFound("远程文件引用校验失败")
        category = str(context.params.get("remote_category") or "file").strip().casefold()
        if category in {"", "dir"}:
            category = "file"
        if category not in {"bin", "zip", "diag", "meshlog", "file"}:
            raise FileManagementError("远程文件分类无效")
        target = self._safe_site_relative_path(
            site,
            str(context.params.get("target_relative_path") or ""),
            under_downloads=True,
        )
        device = self._resolve_device(site, device_id)
        remote_file = RemoteDeviceFile(
            name=remote_name,
            remote_path=normalized_path,
            size=max(0, int(context.params.get("remote_size") or 0)),
            modified_time=str(context.params.get("remote_modified_at") or "") or None,
            category=category,
        )
        transfer = FileTransferService(site, context.paths, allow_remote_setup=False)

        class _JobCancelToken:
            def is_cancelled(self) -> bool:
                context.check_cancelled()
                return False

        try:
            root_path = normalize_remote_path(transfer.connect(device))
            if not is_within_remote_root(normalized_path, root_path):
                raise FileReferenceNotFound("远程文件不属于当前设备根目录")
            context.check_cancelled()
            context.progress("file_transfer", 0, remote_file.size or 0, f"正在下载 {remote_file.name}")
            downloaded = transfer.download(
                normalized_path,
                target,
                progress_callback=lambda current, total: context.progress(
                    "file_transfer",
                    current,
                    total,
                    f"正在下载 {remote_file.name}：{current} / {total}",
                ),
                cancel_token=_JobCancelToken(),
            )
            context.check_cancelled()
        finally:
            transfer.disconnect()
        output = Path(downloaded).resolve()
        if output != target.resolve():
            raise FileManagementError("下载器返回了非受控结果路径")
        relative = output.relative_to(context.paths.site_dir(site).resolve()).as_posix()
        size = output.stat().st_size
        digest = file_sha256(output)
        context.progress("file_verify", 1, 1, f"已校验 {remote_file.name}")
        return {
            "name": remote_file.name,
            "size_bytes": size,
            "relative_path": relative,
            "sha256": digest,
            "artifact_id": self._artifact_id(context.job_id, relative, digest),
            "device_id": device_id,
            "remote_entry_id": remote_entry_id,
        }

    def _resolve_device(self, site: str, device_id: str) -> Device:
        value = str(device_id or "").strip()
        if self._device_resolver is not None:
            device = self._device_resolver(site, value)
            if device is None:
                raise FileReferenceNotFound("设备不存在")
            return device
        if not self.paths.site_db_path(site).is_file():
            raise FileReferenceNotFound("设备不存在")
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        device = repository.get_by_uuid(value)
        if device is None and value.isdigit():
            try:
                device = repository.get(int(value))
            except KeyError:
                device = None
        if device is None:
            raise FileReferenceNotFound("设备不存在")
        return device

    def _session(self, site_id: str, connection_id: str) -> _RemoteSession:
        site = self._site_id(site_id)
        value = str(connection_id or "").strip()
        if not CONNECTION_ID_RE.fullmatch(value):
            raise FileReferenceNotFound("设备文件连接不存在")
        with self._sessions_lock:
            session = self._sessions.get(value)
        if session is None or session.site_id != site:
            raise FileReferenceNotFound("设备文件连接不存在或不属于当前局点")
        return session

    def _close_device_sessions(self, site: str, device_id: str) -> None:
        with self._sessions_lock:
            sessions = tuple(
                session
                for session in self._sessions.values()
                if session.site_id == site and session.device_id == device_id
            )
            for session in sessions:
                self._sessions.pop(session.connection_id, None)
        for session in sessions:
            self._close_session(session, remove=False)

    def _register_session(self, session: _RemoteSession) -> None:
        with self._sessions_lock:
            stale = tuple(
                existing
                for existing in self._sessions.values()
                if existing.site_id == session.site_id and existing.device_id == session.device_id
            )
            for existing in stale:
                self._sessions.pop(existing.connection_id, None)
            self._sessions[session.connection_id] = session
        for existing in stale:
            self._close_session(existing, remove=False)

    def _close_session(self, session: _RemoteSession, *, remove: bool = True) -> None:
        if remove:
            with self._sessions_lock:
                self._sessions.pop(session.connection_id, None)
        try:
            session.transfer.disconnect()
        except Exception:
            pass

    @staticmethod
    def _connection_dto(session: _RemoteSession, message: str, *, status: str = "CONNECTED") -> FileConnectionDTO:
        current = session.entries.get(session.current_entry_id)
        return FileConnectionDTO(
            connection_id=session.connection_id,
            device_id=session.device_id,
            device_name=str(session.device.name or session.device.system_name or ""),
            status=status,
            root_entry_id=session.root_entry_id,
            current_entry_id=session.current_entry_id,
            current_label="根目录" if current is None or session.current_entry_id == session.root_entry_id else current.remote_file.name,
            message=message,
        )

    @staticmethod
    def _remote_entry_id(device_id: str, remote_path: str) -> str:
        digest = hashlib.sha256(f"fe1\0{device_id}\0{normalize_remote_path(remote_path)}".encode("utf-8")).hexdigest()[:32]
        return f"fe1_{digest}"

    def _safe_site_relative_path(self, site: str, relative_path: str, *, under_downloads: bool = False) -> Path:
        value = str(relative_path or "").strip()
        candidate = Path(value)
        if not value or candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise FileReferenceNotFound("文件路径无效")
        site_root = self.paths.site_dir(site).resolve()
        resolved = (site_root / candidate).resolve()
        try:
            resolved.relative_to(site_root)
        except ValueError as exc:
            raise FileReferenceNotFound("文件路径超出局点目录") from exc
        if under_downloads:
            downloads_root = self.paths.file_downloads_root(site).resolve()
            try:
                resolved.relative_to(downloads_root)
            except ValueError as exc:
                raise FileReferenceNotFound("文件路径不属于受控下载目录") from exc
        return resolved

    @staticmethod
    def _artifact_id(task_id: str, relative_path: str, sha256: str) -> str:
        digest = hashlib.sha256(f"fa1\0{task_id}\0{relative_path}\0{sha256}".encode("utf-8")).hexdigest()[:32]
        return f"fa1_{digest}"

    @staticmethod
    def _is_download_snapshot(snapshot: TaskSnapshot) -> bool:
        return (
            snapshot.task_type == "file_management_download"
            and snapshot.owner == "web_file_management"
            and snapshot.source == "local"
        )

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
    if name.endswith(PACKAGE_SUFFIXES):
        return "package"
    suffix = Path(relative_path).suffix.casefold()
    if "raw" in parts and suffix in RAW_SUFFIXES:
        return "raw"
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
