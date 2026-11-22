from __future__ import annotations

import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.file_transfer_service import (
    FileTransferService,
    TransferCancelled,
    is_within_remote_root,
    join_remote_path,
    normalize_remote_path,
)
from netconsole.services.site_manager import SiteManager
from netconsole.services.site_ssh_relay import active_site_id


TransferKind = Literal["UPLOAD", "DOWNLOAD", "COPY"]


@dataclass(slots=True)
class TerminalSftpSessionSnapshot:
    session_id: str
    device_uuid: str
    device_name: str
    site_id: str
    site_name: str
    root_path: str
    current_path: str
    state: str
    created_at_ms: int
    error_code: str = ""


@dataclass(slots=True)
class TerminalSftpTransferSnapshot:
    task_id: str
    session_id: str
    kind: TransferKind
    source: str
    target: str
    status: str = "QUEUED"
    transferred_bytes: int = 0
    total_bytes: int = 0
    bytes_per_second: int = 0
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    error_code: str = ""
    error_message: str = ""
    result_name: str = ""


@dataclass(slots=True)
class _SftpSession:
    snapshot: TerminalSftpSessionSnapshot
    service: FileTransferService
    operation_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(slots=True)
class _TransferTask:
    snapshot: TerminalSftpTransferSnapshot
    cancel_event: threading.Event
    params: dict[str, Any]
    started_monotonic: float = 0.0


class TerminalSftpManager:
    MAX_SESSIONS = 8
    MAX_TRANSFERS = 100
    MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.root = paths.runtime_dir / "terminal-sftp"
        self.upload_root = self.root / "uploads"
        self.download_root = self.root / "downloads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, _SftpSession] = {}
        self._tasks: dict[str, _TransferTask] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="terminal-sftp")

    def connect(self, device_uuid: str) -> dict[str, Any]:
        with self._lock:
            active = [item for item in self._sessions.values() if item.snapshot.state == "CONNECTED"]
            if len(active) >= self.MAX_SESSIONS:
                raise RuntimeError("SFTP 活动会话已达到上限")
        site_name = SiteManager(self.paths).get_current_site()
        site_id = active_site_id(self.paths)
        device = DeviceRepository(Database(self.paths.site_db_path(site_name))).get_by_uuid(
            str(device_uuid or "").strip()
        )
        if device is None:
            raise KeyError("设备不存在或不属于当前局点")
        service = FileTransferService(
            site_name,
            self.paths,
            relay_site_id=site_id,
            route_source="terminal_console",
            allow_device_writes=True,
        )
        root_path = service.connect(device)
        session_id = uuid.uuid4().hex
        snapshot = TerminalSftpSessionSnapshot(
            session_id=session_id,
            device_uuid=str(device.device_uuid),
            device_name=str(device.name or device.system_name or device.primary_address),
            site_id=site_id,
            site_name=site_name,
            root_path=root_path,
            current_path=root_path,
            state="CONNECTED",
            created_at_ms=int(time.time() * 1000),
        )
        with self._lock:
            self._sessions[session_id] = _SftpSession(snapshot, service)
        return asdict(snapshot)

    def close_session(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        for task in self._tasks_for_session(session_id):
            if task.snapshot.status in {"QUEUED", "RUNNING"}:
                task.cancel_event.set()
        with session.operation_lock:
            session.service.disconnect()
            session.snapshot.state = "CLOSED"
        return asdict(session.snapshot)

    def list_directory(self, session_id: str, path: str = "") -> dict[str, Any]:
        session = self._connected_session(session_id)
        target = self._remote_path(session, path or session.snapshot.current_path)
        with session.operation_lock:
            items = [asdict(item) for item in session.service.list_directory(target)]
            session.snapshot.current_path = session.service.current_path
        return {"session": asdict(session.snapshot), "path": target, "items": items}

    def mkdir(self, session_id: str, path: str) -> dict[str, Any]:
        session = self._connected_session(session_id)
        target = self._remote_path(session, path)
        with session.operation_lock:
            created = session.service.mkdir(target)
        return {"path": created}

    def rename(
        self,
        session_id: str,
        source: str,
        target: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        session = self._connected_session(session_id)
        source_path = self._remote_path(session, source)
        target_path = self._remote_path(session, target)
        with session.operation_lock:
            renamed = session.service.rename(source_path, target_path, overwrite=overwrite)
        return {"path": renamed}

    def move(
        self,
        session_id: str,
        source: str,
        target: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        return self.rename(session_id, source, target, overwrite=overwrite)

    def delete(
        self,
        session_id: str,
        paths: list[str],
        *,
        recursive: bool = False,
    ) -> dict[str, Any]:
        session = self._connected_session(session_id)
        normalized = [self._remote_path(session, value) for value in paths]
        if session.snapshot.root_path in normalized:
            raise ValueError("不能删除 SFTP 根目录")
        with session.operation_lock:
            for path in normalized:
                session.service.delete_path(path, recursive=recursive)
        return {"deleted": normalized, "count": len(normalized)}

    def stage_upload(self, filename: str, source) -> tuple[Path, int]:
        safe_name = self._safe_filename(filename)
        staging_id = uuid.uuid4().hex
        target = self.upload_root / staging_id / safe_name
        target.parent.mkdir(parents=True, exist_ok=False)
        total = 0
        with target.open("wb") as stream:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.MAX_UPLOAD_BYTES:
                    stream.close()
                    shutil.rmtree(target.parent, ignore_errors=True)
                    raise ValueError("上传文件超过 2 GiB 限制")
                stream.write(chunk)
        return target, total

    def submit_upload(
        self,
        session_id: str,
        staged_path: Path,
        remote_path: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        session = self._connected_session(session_id)
        source = self._staged_upload_path(staged_path)
        target = self._remote_path(session, remote_path)
        return self._submit(
            session,
            "UPLOAD",
            str(source),
            target,
            {"source": source, "target": target, "overwrite": overwrite},
        )

    def submit_download(self, session_id: str, remote_path: str) -> dict[str, Any]:
        session = self._connected_session(session_id)
        source = self._remote_path(session, remote_path)
        name = self._safe_filename(Path(source).name or "download.bin")
        return self._submit(
            session,
            "DOWNLOAD",
            source,
            name,
            {"source": source, "name": name},
        )

    def submit_copy(
        self,
        session_id: str,
        source: str,
        target: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        session = self._connected_session(session_id)
        source_path = self._remote_path(session, source)
        target_path = self._remote_path(session, target)
        return self._submit(
            session,
            "COPY",
            source_path,
            target_path,
            {"source": source_path, "target": target_path, "overwrite": overwrite},
        )

    def list_tasks(self, session_id: str = "") -> list[dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
        if session_id:
            tasks = [item for item in tasks if item.snapshot.session_id == session_id]
        tasks.sort(key=lambda item: item.snapshot.created_at_ms, reverse=True)
        return [asdict(item.snapshot) for item in tasks[: self.MAX_TRANSFERS]]

    def task(self, task_id: str) -> dict[str, Any]:
        return asdict(self._task(task_id).snapshot)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        if task.snapshot.status in {"QUEUED", "RUNNING"}:
            task.cancel_event.set()
        return asdict(task.snapshot)

    def retry_task(self, task_id: str) -> dict[str, Any]:
        previous = self._task(task_id)
        if previous.snapshot.status not in {"FAILED", "CANCELLED"}:
            raise ValueError("只有失败或已取消的传输可以重试")
        session = self._connected_session(previous.snapshot.session_id)
        return self._submit(
            session,
            previous.snapshot.kind,
            previous.snapshot.source,
            previous.snapshot.target,
            dict(previous.params),
        )

    def download_result(self, task_id: str) -> tuple[Path, str]:
        task = self._task(task_id)
        if task.snapshot.kind != "DOWNLOAD" or task.snapshot.status != "COMPLETED":
            raise ValueError("SFTP 下载尚未完成")
        path = (self.download_root / task.snapshot.task_id / task.snapshot.result_name).resolve()
        if path.parent != (self.download_root / task.snapshot.task_id).resolve() or not path.is_file():
            raise KeyError("SFTP 下载结果不存在")
        return path, task.snapshot.result_name

    def close(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
            tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel_event.set()
        for session in sessions:
            with session.operation_lock:
                session.service.disconnect()
                session.snapshot.state = "CLOSED"
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _submit(
        self,
        session: _SftpSession,
        kind: TransferKind,
        source: str,
        target: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        task = _TransferTask(
            TerminalSftpTransferSnapshot(task_id, session.snapshot.session_id, kind, source, target),
            threading.Event(),
            params,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._trim_tasks_locked()
        self._executor.submit(self._run_transfer, task)
        return asdict(task.snapshot)

    def _run_transfer(self, task: _TransferTask) -> None:
        session = self._connected_session(task.snapshot.session_id)
        task.snapshot.status = "RUNNING"
        task.snapshot.started_at_ms = int(time.time() * 1000)
        task.started_monotonic = time.monotonic()

        def progress(transferred: int, total: int) -> None:
            task.snapshot.transferred_bytes = int(transferred)
            task.snapshot.total_bytes = int(total)
            elapsed = max(0.001, time.monotonic() - task.started_monotonic)
            task.snapshot.bytes_per_second = int(transferred / elapsed)

        try:
            with session.operation_lock:
                if task.cancel_event.is_set():
                    raise TransferCancelled("Transfer cancelled.")
                if task.snapshot.kind == "UPLOAD":
                    session.service.upload(
                        Path(task.params["source"]),
                        str(task.params["target"]),
                        overwrite=bool(task.params.get("overwrite")),
                        progress_callback=progress,
                        cancel_token=task.cancel_event,
                    )
                elif task.snapshot.kind == "DOWNLOAD":
                    name = str(task.params["name"])
                    destination = self.download_root / task.snapshot.task_id / name
                    session.service.download(
                        str(task.params["source"]),
                        destination,
                        progress_callback=progress,
                        cancel_token=task.cancel_event,
                    )
                    task.snapshot.result_name = name
                else:
                    session.service.copy(
                        str(task.params["source"]),
                        str(task.params["target"]),
                        overwrite=bool(task.params.get("overwrite")),
                        progress_callback=progress,
                        cancel_token=task.cancel_event,
                    )
            task.snapshot.status = "COMPLETED"
        except TransferCancelled:
            task.snapshot.status = "CANCELLED"
        except BaseException as exc:
            task.snapshot.status = "FAILED"
            task.snapshot.error_code = exc.__class__.__name__.upper()[:64]
            task.snapshot.error_message = str(exc)[:500]
        finally:
            task.snapshot.ended_at_ms = int(time.time() * 1000)
            if task.snapshot.kind == "UPLOAD" and task.snapshot.status == "COMPLETED":
                shutil.rmtree(Path(task.params["source"]).parent, ignore_errors=True)

    def _remote_path(self, session: _SftpSession, value: str) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if any(part == ".." for part in raw.split("/")):
            raise ValueError("远程路径不能包含上级目录跳转")
        candidate = normalize_remote_path(
            raw or session.snapshot.current_path,
            current_path=session.snapshot.current_path,
        )
        if not is_within_remote_root(candidate, session.snapshot.root_path):
            raise ValueError("远程路径超出当前 SFTP 根目录")
        return candidate

    def child_path(self, session_id: str, directory: str, name: str) -> str:
        session = self._connected_session(session_id)
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError("远程文件名无效")
        return self._remote_path(session, join_remote_path(directory, name))

    def _session(self, session_id: str) -> _SftpSession:
        with self._lock:
            session = self._sessions.get(str(session_id or ""))
        if session is None:
            raise KeyError("SFTP 会话不存在")
        return session

    def _connected_session(self, session_id: str) -> _SftpSession:
        session = self._session(session_id)
        if session.snapshot.state != "CONNECTED":
            raise ValueError("SFTP 会话未连接")
        return session

    def _task(self, task_id: str) -> _TransferTask:
        with self._lock:
            task = self._tasks.get(str(task_id or ""))
        if task is None:
            raise KeyError("SFTP 传输任务不存在")
        return task

    def _tasks_for_session(self, session_id: str) -> list[_TransferTask]:
        with self._lock:
            return [item for item in self._tasks.values() if item.snapshot.session_id == session_id]

    def _staged_upload_path(self, path: Path) -> Path:
        candidate = Path(path).resolve(strict=True)
        root = self.upload_root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("上传暂存文件路径越界") from exc
        return candidate

    def _trim_tasks_locked(self) -> None:
        completed = sorted(
            (
                item
                for item in self._tasks.values()
                if item.snapshot.status in {"COMPLETED", "FAILED", "CANCELLED"}
            ),
            key=lambda item: item.snapshot.created_at_ms,
        )
        while len(self._tasks) > self.MAX_TRANSFERS and completed:
            removed = completed.pop(0)
            self._tasks.pop(removed.snapshot.task_id, None)

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = Path(str(value or "")).name.strip()
        if not name or name in {".", ".."} or any(char in name for char in '\\/:*?"<>|'):
            raise ValueError("文件名无效")
        return name[:240]


__all__ = ["TerminalSftpManager", "TerminalSftpSessionSnapshot", "TerminalSftpTransferSnapshot"]
