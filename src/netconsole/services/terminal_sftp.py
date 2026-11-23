from __future__ import annotations

import shutil
import threading
import time
import uuid
import hashlib
import json
import stat
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from netconsole.core.paths import PathResolver
from netconsole.services.file_transfer_service import (
    FileTransferService,
    TransferCancelled,
    is_within_remote_root,
    join_remote_path,
    normalize_remote_path,
)
from netconsole.services.site_manager import SiteManager
from netconsole.services.site_ssh_relay import active_site_id
from netconsole.services.sftp_connection import SftpConnectionService
from netconsole.services.sftp_tree import check_cancel, copy_directory, download_directory
from netconsole.services.sftp_resume import download_checkpoint


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
    workspace_id: str = ""


@dataclass(slots=True)
class TerminalSftpTransferSnapshot:
    task_id: str
    session_id: str
    kind: TransferKind
    source: str
    target: str
    status: str = "WAITING"
    transferred_bytes: int = 0
    total_bytes: int = 0
    bytes_per_second: int = 0
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    started_at_ms: int | None = None
    ended_at_ms: int | None = None
    error_code: str = ""
    error_message: str = ""
    result_name: str = ""
    result_size: int = 0
    result_sha256: str = ""
    save_status: str = ""
    remaining_seconds: int | None = None
    site_name: str = ""
    device_uuid: str = ""
    resumable: bool = False
    files_completed: int = 0
    files_total: int = 0


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
    last_progress_at: float = 0.0
    pause_requested: bool = False
    sampled_bytes: int = 0
    sampled_at: float = 0.0


class _TaskCancellation:
    def __init__(self, event, path: Path) -> None:
        self.event, self.path = event, path

    def is_set(self) -> bool:
        return self.event.is_set() or self.path.is_file()


class TerminalSftpManager:
    MAX_TRANSFERS = 100
    MAX_UPLOAD_BYTES = 64 * 1024 * 1024 * 1024

    def __init__(self, paths: PathResolver, task_service=None) -> None:
        self.paths = paths
        self.task_service = task_service
        self.journal_path = paths.config_dir / "terminal" / "sftp-transfers.json"
        self._journal_lock = threading.RLock()
        self.root = paths.runtime_dir / "terminal-sftp"
        self.upload_root = self.root / "uploads"
        self.download_root = self.root / "downloads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, _SftpSession] = {}
        self._tasks: dict[str, _TransferTask] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="terminal-sftp")
        self._closed = False
        self._journal_error = False
        try:
            self._load_journal()
        except (OSError, ValueError, TypeError, KeyError):
            # A broken transfer journal must not prevent the terminal/backend startup.
            # Preserve it, refuse mutation and let the SFTP area report the issue.
            self._journal_error = True

    def connect(self, device_uuid: str, workspace_id: str = "") -> dict[str, Any]:
        self._require_journal()
        site_name = SiteManager(self.paths).get_current_site()
        site_id = active_site_id(self.paths)
        connections = SftpConnectionService(self.paths, FileTransferService)
        device = connections.device(site_name, str(device_uuid or "").strip())
        service = connections.create(site_name, relay_site_id=site_id, source="terminal_console", writable=True)
        try:
            root_path = service.connect(device)
        except BaseException:
            service.disconnect()
            raise
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
            workspace_id=workspace_id,
        )
        with self._lock:
            self._sessions[session_id] = _SftpSession(snapshot, service)
        return asdict(snapshot)

    def list_sessions(self) -> list[dict[str, Any]]:
        site = SiteManager(self.paths).get_current_site()
        with self._lock:
            return [asdict(value.snapshot) for value in self._sessions.values()
                    if value.snapshot.site_name == site and value.snapshot.state == "CONNECTED"]

    def close_session(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        for task in self._tasks_for_session(session_id):
            if task.snapshot.status in {"WAITING", "RUNNING"}:
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
                    raise ValueError("上传文件超过 64 GiB 限制")
                stream.write(chunk)
        return target, total

    def submit_upload(
        self,
        session_id: str,
        staged_path: Path,
        remote_path: str,
        *,
        overwrite: bool = False,
        conflict: str = "error",
    ) -> dict[str, Any]:
        session = self._connected_session(session_id)
        source = self._staged_upload_path(staged_path)
        target = self._remote_path(session, remote_path)
        return self._submit(
            session,
            "UPLOAD",
            str(source),
            target,
            {"source": source, "target": target, "overwrite": overwrite, "conflict": conflict},
        )

    def discard_unsubmitted_upload(self, staged_path: Path) -> None:
        candidate = self._staged_upload_path(staged_path)
        with self._lock:
            if any(str(item.params.get("source")) == str(candidate) for item in self._tasks.values()):
                return
            if candidate.parent.parent.resolve() == self.upload_root.resolve():
                shutil.rmtree(candidate.parent, ignore_errors=True)

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
        conflict: str = "error",
    ) -> dict[str, Any]:
        session = self._connected_session(session_id)
        source_path = self._remote_path(session, source)
        target_path = self._remote_path(session, target)
        return self._submit(
            session,
            "COPY",
            source_path,
            target_path,
            {"source": source_path, "target": target_path, "overwrite": overwrite, "conflict": conflict},
        )

    def list_tasks(self, session_id: str = "") -> list[dict[str, Any]]:
        self._require_journal()
        with self._lock:
            tasks = list(self._tasks.values())
        site = SiteManager(self.paths).get_current_site()
        tasks = [item for item in tasks if item.snapshot.site_name == site]
        if session_id:
            tasks = [item for item in tasks if item.snapshot.session_id == session_id]
        tasks.sort(key=lambda item: item.snapshot.created_at_ms, reverse=True)
        return [self._public_task(item) for item in tasks[: self.MAX_TRANSFERS]]

    def task(self, task_id: str) -> dict[str, Any]:
        return self._public_task(self._task(task_id))

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        if task.snapshot.status in {"WAITING", "RUNNING"}:
            task.cancel_event.set()
        elif task.snapshot.status in {"PAUSED", "FAILED", "READY"}:
            task.snapshot.status = "CANCELLED"
            task.snapshot.resumable = False
            self._discard_task_files(task)
            task.snapshot.result_name = ""
            task.snapshot.save_status = ""
            self._persist()
            self._publish(task, "cancelled")
        return self._public_task(task)

    def retry_task(self, task_id: str) -> dict[str, Any]:
        previous = self._task(task_id)
        if previous.snapshot.status not in {"FAILED", "CANCELLED", "PAUSED"}:
            raise ValueError("只有失败或已取消的传输可以重试")
        if previous.snapshot.result_name:
            previous.snapshot.status = "READY"
            previous.snapshot.save_status = "PENDING"
            previous.snapshot.error_code = previous.snapshot.error_message = ""
            self._persist()
            return self._public_task(previous)
        if previous.snapshot.kind == "UPLOAD" and not Path(previous.params["source"]).is_file():
            raise ValueError("上传暂存已清理，请重新选择本地文件")
        session = self._retry_session(previous)
        replacement = self._submit(
            session,
            previous.snapshot.kind,
            previous.snapshot.source,
            previous.snapshot.target,
            dict(previous.params),
        )
        if previous.snapshot.status == "PAUSED":
            previous.snapshot.status = "CANCELLED"
            previous.snapshot.resumable = False
            self._publish(previous, "cancelled")
            self._persist()
        return replacement

    def _retry_session(self, task):
        current = self._sessions.get(task.snapshot.session_id)
        if current is not None and current.snapshot.state == "CONNECTED":
            service = current.service
            client = getattr(service, "_client", None)
            sftp = getattr(service, "_sftp", None)
            healthy = not hasattr(service, "is_connected") or service.is_connected()
            if client is not None:
                healthy = healthy and FileTransferService._transport_is_active(client)
            if sftp is not None:
                healthy = healthy and not sftp.get_channel().closed
            if healthy:
                return current
            with current.operation_lock:
                service.disconnect()
                current.snapshot.state = "CLOSED"
        snapshot = self.connect(task.snapshot.device_uuid)
        return self._connected_session(snapshot["session_id"])

    def pause_task(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        if not task.snapshot.resumable:
            raise ValueError("此任务未验证续传能力，不支持暂停")
        if task.snapshot.status in {"WAITING", "RUNNING"}:
            task.pause_requested = True
            task.cancel_event.set()
        return self._public_task(task)

    def download_result(self, task_id: str) -> tuple[Path, str]:
        task = self._task(task_id)
        if task.snapshot.kind != "DOWNLOAD" or not task.snapshot.result_name:
            raise ValueError("SFTP 下载尚未完成")
        path = (self.download_root / task.snapshot.task_id / task.snapshot.result_name).resolve()
        if path.parent != (self.download_root / task.snapshot.task_id).resolve() or not path.is_file():
            raise KeyError("SFTP 下载结果不存在")
        return path, task.snapshot.result_name

    def record_save(self, task_id: str, *, saved: bool, size: int = 0, sha256: str = "") -> dict[str, Any]:
        task = self._task(task_id)
        self.download_result(task_id)
        if saved and (size != task.snapshot.result_size or sha256 != task.snapshot.result_sha256):
            raise ValueError("本地保存校验结果与下载文件不一致")
        if task.snapshot.status == "COMPLETED":
            return self._public_task(task)
        if self.task_service is not None:
            # Task Center terminal history is immutable. A save after restart gets
            # a new attempt rather than silently rewriting an orphaned old task.
            previous_id = str(task.params.get("task_center_id", task.snapshot.task_id))
            previous = self.task_service.repository(task.snapshot.site_name).get(previous_id)
            if previous is None or previous.status.value in {"COMPLETED", "FAILED", "CANCELLED"}:
                attempt_id = uuid.uuid4().hex
                self.task_service.create_external_task(
                    task_id=attempt_id, task_type="terminal_sftp_transfer",
                    task_name=f"SFTP SAVE: {task.snapshot.result_name}", source="local",
                    site_name=task.snapshot.site_name, owner="terminal_sftp",
                    device=task.snapshot.device_uuid, trigger_source="ui",
                    retry_of_task_id=previous_id,
                )
                task.params["task_center_id"] = attempt_id
        task.snapshot.status = "COMPLETED" if saved else "FAILED"
        task.snapshot.save_status = "SAVED" if saved else "FAILED"
        task.snapshot.error_code = "" if saved else "LOCAL_SAVE_FAILED"
        task.snapshot.error_message = "" if saved else "本地保存失败，可重试保存已有结果"
        self._persist()
        self._publish(task, "finished" if saved else "progress")
        return self._public_task(task)

    def clear_completed(self, device_uuid: str = "") -> int:
        with self._lock:
            site = SiteManager(self.paths).get_current_site()
            ids = [key for key, value in self._tasks.items() if value.snapshot.site_name == site and (not device_uuid or value.snapshot.device_uuid == device_uuid) and value.snapshot.status in {"COMPLETED", "CANCELLED", "SKIPPED"}]
            removed = [self._tasks.pop(key) for key in ids]
        for task in removed:
            self._discard_task_files(task)
        self._persist()
        return len(ids)

    def export_log(self) -> Path:
        path = self.root / "transfer-log.jsonl"
        temporary = path.with_suffix(".part")
        with temporary.open("w", encoding="utf-8") as stream:
            for task in self.list_tasks():
                # Only operational fields, no local staging paths or credentials.
                value = {key: task[key] for key in ("task_id", "kind", "status", "result_name", "transferred_bytes", "total_bytes", "error_code", "created_at_ms", "ended_at_ms")}
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        temporary.replace(path)
        return path

    def close(self) -> None:
        with self._lock:
            self._closed = True
            sessions = tuple(self._sessions.values())
            tasks = tuple(self._tasks.values())
        for task in tasks:
            if task.snapshot.kind == "DOWNLOAD" and task.snapshot.status in {"WAITING", "RUNNING"}:
                task.pause_requested = True
            task.cancel_event.set()
        for session in sessions:
            with session.operation_lock:
                session.service.disconnect()
                session.snapshot.state = "CLOSED"
        self._executor.shutdown(wait=True, cancel_futures=True)
        if not self._journal_error:
            self._persist()

    def _submit(
        self,
        session: _SftpSession,
        kind: TransferKind,
        source: str,
        target: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        params.pop("task_center_id", None)
        if kind == "DOWNLOAD":
            params.setdefault("checkpoint_id", task_id)
        task = _TransferTask(
            TerminalSftpTransferSnapshot(task_id, session.snapshot.session_id, kind, source, target,
                                         site_name=session.snapshot.site_name, device_uuid=session.snapshot.device_uuid),
            threading.Event(),
            params,
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("SFTP 服务正在退出")
            checkpoint = params.get("checkpoint_id")
            if checkpoint and any(item.params.get("checkpoint_id") == checkpoint and item.snapshot.status in {"WAITING", "RUNNING"} for item in self._tasks.values()):
                raise RuntimeError("此断点已有传输正在执行")
            active = sum(item.snapshot.status in {"WAITING", "RUNNING"} for item in self._tasks.values())
            if active >= self.MAX_TRANSFERS:
                raise RuntimeError("SFTP 等待队列已满")
            self._trim_tasks_locked()
            if len(self._tasks) >= self.MAX_TRANSFERS:
                raise RuntimeError("传输记录已满，请清除已完成记录")
            self._tasks[task_id] = task
        self._persist()
        if self.task_service is not None:
            self.task_service.create_external_task(task_id=task_id, task_type="terminal_sftp_transfer",
                task_name=f"SFTP {kind}: {Path(target).name}", source="local", site_name=task.snapshot.site_name,
                owner="terminal_sftp", device=task.snapshot.device_uuid, trigger_source="ui")
        self._executor.submit(self._run_transfer, task)
        return self._public_task(task)

    def _run_transfer(self, task: _TransferTask) -> None:
        cancel = _TaskCancellation(task.cancel_event, self.paths.runtime_cache_dir / "background_jobs" / f"{task.snapshot.task_id}.cancel")
        def progress(transferred: int, total: int) -> None:
            check_cancel(cancel)
            task.snapshot.transferred_bytes = int(transferred)
            task.snapshot.total_bytes = int(total)
            now = time.monotonic()
            elapsed = max(0.001, now - task.sampled_at)
            if elapsed >= 0.2:
                task.snapshot.bytes_per_second = int(max(0, transferred - task.sampled_bytes) / elapsed)
                task.sampled_at = now
                task.sampled_bytes = transferred
            task.snapshot.remaining_seconds = int(max(0, total - transferred) / task.snapshot.bytes_per_second) if task.snapshot.bytes_per_second else None
            if time.monotonic() - task.last_progress_at >= 0.5:
                task.last_progress_at = time.monotonic()
                self._publish(task, "progress")

        try:
            with self._lock:
                session = self._sessions[task.snapshot.session_id]
            with session.operation_lock:
                check_cancel(cancel)
                if session.snapshot.state != "CONNECTED":
                    raise ValueError("SFTP 会话已断开，请重新连接")
                task.snapshot.status = "RUNNING"
                task.snapshot.started_at_ms = int(time.time() * 1000)
                task.started_monotonic = time.monotonic()
                task.sampled_at = task.started_monotonic
                self._publish(task, "state")
                if task.snapshot.kind != "DOWNLOAD":
                    target = self._conflict_target(session, task)
                    if target is None:
                        task.snapshot.status = "SKIPPED"
                        return
                    task.params["target"] = target
                    task.snapshot.target = target
                if task.snapshot.kind == "UPLOAD":
                    self._ensure_parent_directories(session, str(task.params["target"]))
                    session.service.upload(
                        Path(task.params["source"]),
                        str(task.params["target"]),
                        overwrite=bool(task.params.get("overwrite")),
                        progress_callback=progress,
                        cancel_token=cancel,
                    )
                elif task.snapshot.kind == "DOWNLOAD":
                    name = str(task.params["name"])
                    attrs = session.service.stat(str(task.params["source"]))
                    directory = stat.S_ISDIR(int(attrs.st_mode))
                    task.snapshot.resumable = not directory and hasattr(session.service, "_require_sftp")
                    if directory:
                        name += ".zip"
                    destination = self.download_root / task.snapshot.task_id / name
                    if directory:
                        work = self.download_root / str(task.params["checkpoint_id"]) / "directory-manifest"
                        if not work.resolve().is_relative_to(self.download_root.resolve()):
                            raise ValueError("目录断点路径越界")
                        def manifest_progress(done, total):
                            task.snapshot.files_completed = done
                            task.snapshot.files_total = total
                            self._persist()
                        task.snapshot.resumable = hasattr(session.service, "_require_sftp")
                        download_directory(session.service, str(task.params["source"]), destination, cancel, progress,
                                           work_root=work, manifest_progress=manifest_progress)
                    elif task.snapshot.resumable:
                        checkpoint = self.download_root / str(task.params["checkpoint_id"]) / "checkpoint.part"
                        if not checkpoint.resolve().is_relative_to(self.download_root.resolve()):
                            raise ValueError("断点路径越界")
                        download_checkpoint(session.service, str(task.params["source"]), destination, checkpoint, cancel, progress)
                    else:
                        session.service.download(
                        str(task.params["source"]),
                        destination,
                        progress_callback=progress,
                        cancel_token=cancel,
                    )
                    if not destination.is_file():
                        raise IOError("下载结果未实际落盘")
                    task.snapshot.result_name = name
                    task.snapshot.result_size = destination.stat().st_size
                    with destination.open("rb") as stream:
                        task.snapshot.result_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
                    task.snapshot.save_status = "PENDING"
                else:
                    source = str(task.params["source"])
                    if stat.S_ISDIR(int(session.service.stat(source).st_mode)):
                        copy_directory(session.service, source, str(task.params["target"]), cancel, progress)
                    else:
                        session.service.copy(
                        str(task.params["source"]),
                        str(task.params["target"]),
                        overwrite=bool(task.params.get("overwrite")),
                        progress_callback=progress,
                        cancel_token=cancel,
                    )
            task.snapshot.status = "READY" if task.snapshot.kind == "DOWNLOAD" else "COMPLETED"
            task.snapshot.resumable = False
        except TransferCancelled:
            task.snapshot.status = "PAUSED" if task.pause_requested else "CANCELLED"
        except Exception as exc:
            task.snapshot.status = "FAILED"
            task.snapshot.error_code = exc.__class__.__name__.upper()[:64]
            task.snapshot.error_message = "远程文件已存在" if isinstance(exc, FileExistsError) else (str(exc) if isinstance(exc, ValueError) else "SFTP 传输失败，请检查连接、路径与访问权限")
        finally:
            task.snapshot.ended_at_ms = int(time.time() * 1000)
            task.snapshot.bytes_per_second = 0
            task.snapshot.remaining_seconds = None
            self._persist()
            event = {"COMPLETED": "finished", "SKIPPED": "finished", "FAILED": "error", "CANCELLED": "cancelled"}.get(task.snapshot.status, "progress")
            self._publish(task, event)
            if task.snapshot.status in {"CANCELLED", "SKIPPED"} or (task.snapshot.kind == "UPLOAD" and task.snapshot.status == "COMPLETED"):
                self._discard_task_files(task)

    def _discard_task_files(self, task) -> None:
        """Only remove this manager's exact staging directories, never a live retry."""
        checkpoint_id = str(task.params.get("checkpoint_id", task.snapshot.task_id))
        with self._lock:
            retained = [item for item in self._tasks.values() if item is not task and
                        item.snapshot.status not in {"COMPLETED", "CANCELLED", "SKIPPED"}]
            protected = {item.snapshot.task_id for item in retained}
            protected.update(str(item.params.get("checkpoint_id", "")) for item in retained)
            for identifier in {task.snapshot.task_id, checkpoint_id} - protected:
                if re.fullmatch(r"[a-f0-9]{32}", identifier):
                    directory = self.download_root / identifier
                    if directory.resolve().parent == self.download_root.resolve():
                        shutil.rmtree(directory, ignore_errors=True)
            if task.snapshot.kind == "UPLOAD":
                source = Path(task.params["source"])
                if not any(str(item.params.get("source")) == str(source) for item in retained):
                    directory = source.parent
                    if directory.resolve().parent == self.upload_root.resolve() and re.fullmatch(r"[a-f0-9]{32}", directory.name):
                        shutil.rmtree(directory, ignore_errors=True)

    @staticmethod
    def _public_task(task) -> dict[str, Any]:
        value = asdict(task.snapshot)
        if task.snapshot.kind == "UPLOAD":
            value["source"] = Path(value["source"]).name
        return value

    def _publish(self, task, event: str) -> None:
        if self.task_service is None:
            return
        value = self._public_task(task)
        payload = {"state": "RUNNING", "stage": task.snapshot.status,
                   "current": task.snapshot.transferred_bytes, "total": task.snapshot.total_bytes,
                   "details": {"prevent_running_100": True}, "result": value,
                   "message": task.snapshot.error_message or task.snapshot.status}
        self.task_service.record_external_event(str(task.params.get("task_center_id", task.snapshot.task_id)), event, payload,
                                               site_name=task.snapshot.site_name, source="terminal_sftp")

    def _persist(self) -> None:
        self._require_journal()
        with self._journal_lock:
            with self._lock:
                rows = [{"snapshot": asdict(item.snapshot), "params": {key: str(value) if isinstance(value, Path) else value for key, value in item.params.items()}}
                        for item in self._tasks.values()]
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.journal_path.with_suffix(".part")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump({"version": 1, "tasks": rows}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.journal_path)

    def _load_journal(self) -> None:
        if not self.journal_path.is_file():
            return
        document = json.loads(self.journal_path.read_text(encoding="utf-8"))
        if document.get("version") != 1:
            raise ValueError("SFTP 传输日志版本不受支持，原文件保留")
        for row in document.get("tasks", [])[-self.MAX_TRANSFERS:]:
            snapshot = TerminalSftpTransferSnapshot(**row["snapshot"])
            if snapshot.status in {"WAITING", "RUNNING"}:
                snapshot.status = "PAUSED"
                snapshot.error_message = "应用退出前传输中断；下载恢复前会重新验证断点，上传需要重新执行"
            self._tasks[snapshot.task_id] = _TransferTask(snapshot, threading.Event(), row["params"])

    def _require_journal(self) -> None:
        if self._journal_error:
            raise ValueError("SFTP 传输日志损坏或版本不受支持，原文件已保留；终端和后台设备下载仍可独立使用")

    def _conflict_target(self, session, task) -> str | None:
        target = str(task.params["target"])
        policy = str(task.params.get("conflict", "error"))
        if policy not in {"error", "skip", "rename", "overwrite"}:
            raise ValueError("文件冲突策略无效")
        try:
            session.service.stat(target)
        except FileNotFoundError:
            return target
        if policy == "skip":
            return None
        if policy == "rename":
            name = Path(target)
            for index in range(1, 1001):
                candidate = str(name.with_name(f"{name.stem} ({index}){name.suffix}")).replace("\\", "/")
                try:
                    session.service.stat(candidate)
                except FileNotFoundError:
                    return candidate
            raise FileExistsError("未找到可用文件名")
        if policy == "overwrite" or task.params.get("overwrite"):
            task.params["overwrite"] = True
            return target
        raise FileExistsError(target)

    def _ensure_parent_directories(self, session, target: str) -> None:
        parent = target.rsplit("/", 1)[0]
        if parent == session.snapshot.root_path.rstrip("/"):
            return
        parts = parent.strip("/").split("/")
        path = "/" if parent.startswith("/") else ""
        for part in parts:
            path = join_remote_path(path, part)
            if not is_within_remote_root(path, session.snapshot.root_path):
                continue
            try:
                attrs = session.service.stat(path)
                if not stat.S_ISDIR(int(attrs.st_mode)):
                    raise NotADirectoryError(path)
            except FileNotFoundError:
                session.service.mkdir(path)

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
        if session.snapshot.site_name != SiteManager(self.paths).get_current_site():
            raise KeyError("SFTP 会话不属于当前局点")
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
        if task.snapshot.site_name != SiteManager(self.paths).get_current_site():
            raise KeyError("SFTP 传输任务不属于当前局点")
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
                if item.snapshot.status in {"COMPLETED", "CANCELLED", "SKIPPED"}
            ),
            key=lambda item: item.snapshot.created_at_ms,
        )
        while len(self._tasks) >= self.MAX_TRANSFERS and completed:
            removed = completed.pop(0)
            self._tasks.pop(removed.snapshot.task_id, None)
            self._discard_task_files(removed)

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = str(value or "").strip()
        if not name or name in {".", ".."} or len(name) > 240 or any(char in name for char in '\\/:*?"<>|') or any(ord(char) < 32 for char in name) or re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I):
            raise ValueError("文件名无效")
        return name


__all__ = ["TerminalSftpManager", "TerminalSftpSessionSnapshot", "TerminalSftpTransferSnapshot"]
