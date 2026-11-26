from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import threading
import time
import uuid
import shutil
from datetime import datetime
from zipfile import ZipFile, ZIP_DEFLATED
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.device_activity import device_write_resource_key
from netconsole.services.netmiko_connection import ConnectionTarget, connection_targets
from netconsole.services.site_manager import SiteManager
from netconsole.services.site_ssh_relay import active_site_id
from netconsole.services.terminal_profiles import TerminalProfileStore
from netconsole.services.terminal_settings import TerminalSettingsService
from netconsole.services.terminal_transports import create_terminal_transport
from netconsole.services.terminal_transcript import render_events


TERMINAL_STATES = frozenset(
    {
        "CREATED",
        "CONNECTING",
        "CONNECTED",
        "RUNNING",
        "DISCONNECTED",
        "RECONNECTING",
        "CLOSING",
        "CLOSED",
        "FAILED",
        "CANCELLED",
    }
)
TERMINAL_TRANSITIONS = {
    "CREATED": {"CONNECTING", "CANCELLED"},
    "CONNECTING": {"CONNECTED", "FAILED", "CLOSING", "CANCELLED"},
    "CONNECTED": {"RUNNING", "DISCONNECTED", "CLOSING", "FAILED"},
    "RUNNING": {"DISCONNECTED", "CLOSING", "FAILED"},
    "DISCONNECTED": {"RECONNECTING", "CLOSING", "CLOSED"},
    "RECONNECTING": {"CONNECTED", "FAILED", "CLOSING"},
    "CLOSING": {"CLOSED", "FAILED"},
    "CLOSED": set(),
    "FAILED": {"RECONNECTING", "CLOSING", "CLOSED"},
    "CANCELLED": {"CLOSED"},
}
TERMINAL_FINAL_STATES = frozenset({"CLOSED", "FAILED", "CANCELLED"})
TERMINAL_LIVE_STATES = frozenset(
    {"CREATED", "CONNECTING", "CONNECTED", "RUNNING", "RECONNECTING", "CLOSING"}
)


def _utc_ms() -> int:
    return int(time.time() * 1000)


def _sanitize_terminal_data(data: str, device: Device) -> str:
    """Redact credentials without changing terminal control sequences or line endings."""

    safe = str(data or "")
    secrets_to_redact = {
        str(value)
        for value in (
            device.ssh_password,
            device.telnet_password,
            device.snmp_ro_community,
            device.tunnel1_password,
            device.tunnel2_password,
        )
        if value
    }
    for secret in sorted(secrets_to_redact, key=len, reverse=True):
        safe = safe.replace(secret, "***")
    return re.sub(
        r"(?i)((?:password|passwd|secret|community|token)\s*[:=]\s*)[^\s,;|]+",
        r"\1***",
        safe,
    )


@dataclass(slots=True)
class TerminalSessionSnapshot:
    session_id: str
    device_uuid: str
    device_name: str
    site_id: str
    site_name: str
    protocol: str
    encoding: str
    mode: str
    state: str
    address: str
    port: int
    created_at_ms: int
    updated_at_ms: int
    address_role: str = "primary"
    connected_at_ms: int | None = None
    ended_at_ms: int | None = None
    username: str = ""
    backup_address: str = ""
    backup_port: int = 0
    disconnect_reason: str = ""
    error_code: str = ""
    error_message: str = ""
    detached_window: bool = False
    command_count: int = 0
    output_bytes: int = 0
    recording_status: str = "RECORDING"
    recording_sha256: str = ""
    recording_dropped_events: int = 0
    session_name: str = ""
    recording_log_name: str = ""
    recording_zip_name: str = ""
    recording_error: str = ""
    recording_projection: dict = field(default_factory=dict)
    manual_log_status: str = "STOPPED"
    manual_log_id: str = ""
    manual_log_format: str = ""
    manual_log_filename: str = ""
    manual_log_dropped_events: int = 0
    automation_write_active: bool = False
    automation_write_task_id: str = ""
    automation_write_task_name: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TerminalTicket:
    ticket: str
    session_id: str
    expires_at_ms: int
    consumed: bool = False


class TerminalTicketStore:
    def __init__(self, *, ttl_seconds: int = 30) -> None:
        self._ttl_ms = max(5, min(int(ttl_seconds), 120)) * 1000
        self._tickets: dict[str, TerminalTicket] = {}
        self._lock = threading.Lock()

    def issue(self, session_id: str) -> TerminalTicket:
        with self._lock:
            self._purge_locked()
            value = TerminalTicket(
                ticket=secrets.token_urlsafe(32),
                session_id=session_id,
                expires_at_ms=_utc_ms() + self._ttl_ms,
            )
            self._tickets[value.ticket] = value
            return value

    def consume(self, ticket: str, session_id: str) -> bool:
        with self._lock:
            self._purge_locked()
            value = self._tickets.get(str(ticket or ""))
            if value is None or value.consumed or value.session_id != session_id:
                return False
            value.consumed = True
            self._tickets.pop(value.ticket, None)
            return True

    def _purge_locked(self) -> None:
        now = _utc_ms()
        expired = [
            key for key, value in self._tickets.items() if value.expires_at_ms <= now
        ]
        for key in expired:
            self._tickets.pop(key, None)


class TerminalRecordingWriter:
    """Bounded asynchronous JSONL recorder; transport output never waits on disk."""

    def __init__(
        self,
        root: Path,
        snapshot: TerminalSessionSnapshot,
        *,
        queue_size: int = 2048,
    ) -> None:
        self.session_dir = root / snapshot.session_id
        self.session_dir.mkdir(parents=True, exist_ok=False)
        self.events_path = self.session_dir / "events.jsonl"
        self.metadata_path = self.session_dir / "metadata.json"
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=queue_size
        )
        self._thread = threading.Thread(
            target=self._run,
            name=f"terminal-recorder-{snapshot.session_id[:8]}",
            daemon=True,
        )
        self._closed = threading.Event()
        self._dropped = 0
        self._error = ""
        self._metadata_lock = threading.Lock()
        self._write_metadata(snapshot)
        self._thread.start()

    @property
    def dropped_events(self) -> int:
        return self._dropped

    def append(self, event_type: str, **detail: Any) -> bool:
        if self._closed.is_set():
            return False
        event = {"at_ms": _utc_ms(), "event_type": event_type, **detail}
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            self._dropped += 1
            return False

    def update_metadata(self, snapshot: TerminalSessionSnapshot) -> None:
        snapshot.recording_dropped_events = self._dropped
        self._write_metadata(snapshot)

    def close(self, snapshot: TerminalSessionSnapshot) -> None:
        if self._closed.is_set():
            return
        self.append("SESSION_END", state=snapshot.state)
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._dropped += 1
                self._queue.put_nowait(None)
            except (queue.Empty, queue.Full):
                self._dropped += 1
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            self._dropped += 1
            snapshot.recording_status = "INCOMPLETE"
        elif self._dropped:
            snapshot.recording_status = "INCOMPLETE"
        elif self._error:
            snapshot.recording_status = "FAILED"
            snapshot.recording_error = self._error
        else:
            snapshot.recording_status = "FINALIZING"
        if self.events_path.is_file():
            with self.events_path.open("rb") as stream:
                snapshot.recording_sha256 = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
        snapshot.recording_dropped_events = self._dropped
        incomplete = snapshot.recording_status == "INCOMPLETE" or snapshot.state in {
            "FAILED",
            "DISCONNECTED",
            "CANCELLED",
        }
        self._write_metadata(snapshot)
        try:
            if self._thread.is_alive() or self._error:
                raise IOError("录制事件尚未完整写入")
            stamp = datetime.fromtimestamp(
                (snapshot.connected_at_ms or snapshot.created_at_ms) / 1000
            ).strftime("%Y%m%d%H%M%S")
            stem = re.sub(
                r'[\\/:*?"<>|\x00-\x1f]',
                "_",
                f"{snapshot.device_name}_{snapshot.address}_{snapshot.port}_{stamp}",
            ).rstrip(". ")[:200]
            # Session-scoped storage and suffix avoid same-second exported collisions.
            stem += f"_{snapshot.session_id[:8]}"
            snapshot.recording_log_name, snapshot.recording_zip_name = (
                stem + ".log",
                stem + ".zip",
            )
            log_path = self.session_dir / snapshot.recording_log_name
            temporary = log_path.with_suffix(".log.part")
            with (
                self.events_path.open("r", encoding="utf-8") as source,
                temporary.open("w", encoding="utf-8", newline="\n") as output,
            ):
                snapshot.recording_projection = render_events(
                    (json.loads(line) for line in source), output
                )
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(log_path)
            snapshot.recording_status = "COMPRESSING"
            self._write_metadata(snapshot)
            archive = self.session_dir / snapshot.recording_zip_name
            temporary_zip = archive.with_suffix(".zip.part")
            with ZipFile(temporary_zip, "w", ZIP_DEFLATED) as zipped:
                zipped.write(log_path, log_path.name)
            with ZipFile(temporary_zip) as zipped:
                if zipped.namelist() != [log_path.name] or zipped.testzip() is not None:
                    raise IOError("ZIP 文件名或 CRC 校验失败")
                with zipped.open(log_path.name) as stream, log_path.open("rb") as local:
                    if (
                        hashlib.file_digest(stream, "sha256").digest()
                        != hashlib.file_digest(local, "sha256").digest()
                    ):
                        raise IOError("ZIP 内容校验失败")
            temporary_zip.replace(archive)
            snapshot.recording_status = "INCOMPLETE" if incomplete else "COMPLETED"
        except Exception as exc:
            snapshot.recording_status = "INCOMPLETE" if incomplete else "FAILED"
            snapshot.recording_error = (
                f"录制整理失败 ({type(exc).__name__})；原始事件及已生成 LOG 已保留"
            )
        self._write_metadata(snapshot)
        self._closed.set()

    def _run(self) -> None:
        try:
            self._write_events()
        except Exception as exc:
            self._error = type(exc).__name__

    def _write_events(self) -> None:
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            while True:
                event = self._queue.get()
                if event is None:
                    stream.flush()
                    os.fsync(stream.fileno())
                    return
                stream.write(
                    json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                stream.flush()

    def _write_metadata(self, snapshot: TerminalSessionSnapshot) -> None:
        with self._metadata_lock:
            temporary = self.metadata_path.with_suffix(".json.tmp")
            metadata = snapshot.to_public_dict()
            metadata.pop("username", None)
            temporary.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.metadata_path)


class TerminalManualLogWriter:
    """Independent bounded writer for a user-controlled session log."""

    def __init__(
        self,
        root: Path,
        snapshot: TerminalSessionSnapshot,
        *,
        filename: str,
        log_format: str,
        queue_size: int = 2048,
    ) -> None:
        self.log_id = uuid.uuid4().hex
        self.log_format = log_format
        suffix = ".jsonl" if log_format == "jsonl" else ".log"
        safe_stem = re.sub(
            r"[^\w.-]+", "-", Path(filename).stem, flags=re.UNICODE
        ).strip(".-")
        self.filename = f"{safe_stem or f'session-{snapshot.session_id[:8]}'}{suffix}"
        self.directory = root / snapshot.session_id / self.log_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / self.filename
        self.metadata_path = self.directory / "metadata.json"
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=queue_size
        )
        self._thread = threading.Thread(
            target=self._run,
            args=(snapshot.to_public_dict(),),
            name=f"terminal-manual-log-{snapshot.session_id[:8]}",
            daemon=True,
        )
        self._closed = threading.Event()
        self._dropped = 0
        self._status = "RECORDING"
        self._write_metadata(snapshot, "RECORDING")
        self._thread.start()

    @property
    def dropped_events(self) -> int:
        return self._dropped

    @property
    def status(self) -> str:
        return self._status

    def append(self, event_type: str, **detail: Any) -> bool:
        if self._closed.is_set():
            return False
        try:
            self._queue.put_nowait(
                {"at_ms": _utc_ms(), "event_type": event_type, **detail}
            )
            return True
        except queue.Full:
            self._dropped += 1
            return False

    def close(self, snapshot: TerminalSessionSnapshot) -> None:
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._dropped += 1
                self._queue.put_nowait(None)
            except (queue.Empty, queue.Full):
                self._dropped += 1
        self._thread.join(timeout=5)
        status = (
            "INCOMPLETE" if self._thread.is_alive() or self._dropped else "COMPLETE"
        )
        self._status = status
        self._write_metadata(snapshot, status)
        self._closed.set()

    def _run(self, session: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            if self.log_format == "txt":
                stream.write(
                    "# NetConsole Session Log\n"
                    f"# Session: {session['session_id']}\n"
                    f"# Device: {session['device_name']} ({session['address']})\n"
                    f"# Protocol: {session['protocol']}\n\n"
                )
            while True:
                event = self._queue.get()
                if event is None:
                    stream.flush()
                    os.fsync(stream.fileno())
                    return
                if self.log_format == "jsonl":
                    stream.write(
                        json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                else:
                    self._write_text_event(stream, event)
                stream.flush()

    @staticmethod
    def _write_text_event(stream, event: dict[str, Any]) -> None:
        timestamp = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(int(event["at_ms"]) / 1000),
        )
        event_type = str(event.get("event_type") or "")
        if event_type == "OUTPUT":
            stream.write(str(event.get("data") or ""))
        elif event_type == "INPUT":
            stream.write(f"\n[{timestamp}] INPUT {event.get('data') or ''}\n")
        elif event_type == "RISK":
            stream.write(f"\n[{timestamp}] WARNING {event.get('command') or ''}\n")
        elif event_type == "STATE":
            stream.write(f"\n[{timestamp}] STATE {event.get('state') or ''}\n")

    def _write_metadata(self, snapshot: TerminalSessionSnapshot, status: str) -> None:
        temporary = self.metadata_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "log_id": self.log_id,
                    "session_id": snapshot.session_id,
                    "device_uuid": snapshot.device_uuid,
                    "device_name": snapshot.device_name,
                    "address": snapshot.address,
                    "protocol": snapshot.protocol,
                    "filename": self.filename,
                    "format": self.log_format,
                    "status": status,
                    "dropped_events": self._dropped,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.metadata_path)


@dataclass(slots=True)
class _TerminalSession:
    snapshot: TerminalSessionSnapshot
    device: Device
    paths: PathResolver
    recording: TerminalRecordingWriter
    requested_protocol: str
    target: ConnectionTarget
    managed_device: bool
    input_queue: queue.Queue[tuple[str, Any]] = field(
        default_factory=lambda: queue.Queue(maxsize=256)
    )
    listeners: set[queue.Queue[dict[str, Any]]] = field(default_factory=set)
    listener_lock: threading.Lock = field(default_factory=threading.Lock)
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    dispatch_lock: threading.Lock = field(default_factory=threading.Lock)
    close_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    replacement_session_id: str = ""
    display_backlog: list[str] = field(default_factory=list)
    display_backlog_chars: int = 0
    terminal_cols: int = 120
    terminal_rows: int = 32
    risk_input_buffer: str = ""
    risk_escape_state: str = ""
    risk_last_was_cr: bool = False
    manual_log: TerminalManualLogWriter | None = None

    MAX_DISPLAY_BACKLOG_CHARS = 1_000_000

    def publish(self, message: dict[str, Any]) -> None:
        with self.listener_lock:
            if message.get("type") in {"output", "local_echo"}:
                data = str(message.get("data") or "")
                if data:
                    self.display_backlog.append(data)
                    self.display_backlog_chars += len(data)
                    while (
                        self.display_backlog
                        and self.display_backlog_chars > self.MAX_DISPLAY_BACKLOG_CHARS
                    ):
                        self.display_backlog_chars -= len(self.display_backlog.pop(0))
            listeners = tuple(self.listeners)
        for listener in listeners:
            try:
                listener.put_nowait(message)
            except queue.Full:
                try:
                    listener.get_nowait()
                    listener.put_nowait(message)
                except (queue.Empty, queue.Full):
                    pass

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        listener: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=512)
        with self.listener_lock:
            if self.listeners:
                raise RuntimeError("此 Session 已有终端显示，请克隆为独立会话")
            self.listeners.add(listener)
            backlog = "".join(self.display_backlog)
        listener.put_nowait(
            {"type": "snapshot", "session": self.snapshot.to_public_dict()}
        )
        if backlog:
            listener.put_nowait({"type": "backlog", "data": backlog})
        return listener

    def unsubscribe(self, listener: queue.Queue[dict[str, Any]]) -> None:
        with self.listener_lock:
            self.listeners.discard(listener)


class TerminalSessionManager:
    MAX_MESSAGE_CHARS = 65536

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.recording_root = paths.runtime_dir / "terminal-recordings"
        self.export_root = paths.runtime_dir / "terminal-exports"
        self.manual_log_root = paths.runtime_dir / "terminal-manual-logs"
        self.recording_root.mkdir(parents=True, exist_ok=True)
        self.export_root.mkdir(parents=True, exist_ok=True)
        self.manual_log_root.mkdir(parents=True, exist_ok=True)
        self.settings = TerminalSettingsService(paths)
        self.profiles = TerminalProfileStore(paths)
        self.tickets = TerminalTicketStore()
        self._sessions: dict[str, _TerminalSession] = {}
        self._lock = threading.RLock()
        self._recover_recordings()
        from netconsole.services.terminal_controls import BatchCommandDispatcher

        self.dispatcher = BatchCommandDispatcher(self)

    def create_session(
        self,
        device_uuid: str,
        *,
        protocol: str = "AUTO",
        address_role: str | None = None,
        cols: int = 120,
        rows: int = 32,
    ) -> tuple[dict[str, Any], TerminalTicket]:
        requested = str(protocol or "AUTO").strip().upper()
        if requested not in {"AUTO", "SSH", "TELNET"}:
            raise ValueError("终端协议只支持 AUTO、SSH 或 TELNET")
        if address_role not in {None, "primary", "backup"}:
            raise ValueError("终端地址只支持主地址或备用地址")
        site_name = SiteManager(self.paths).get_current_site()
        repository = DeviceRepository(Database(self.paths.site_db_path(site_name)))
        device = repository.get_by_uuid(str(device_uuid or "").strip())
        if device is None:
            raise KeyError("设备不存在或不属于当前局点")
        targets = connection_targets(device)
        if requested != "AUTO":
            targets = [item for item in targets if item.protocol.upper() == requested]
        if address_role is not None:
            targets = [item for item in targets if item.target_role == address_role]
            if not targets:
                address_name = "备用" if address_role == "backup" else "主"
                raise ValueError(f"设备未配置可用的{address_name}地址连接")
        if not targets:
            raise ValueError("设备未配置可用的 SSH/Telnet 凭据或连接方式")
        return self._create_runtime(
            device,
            targets[0],
            requested_protocol=requested,
            cols=cols,
            rows=rows,
            managed_device=True,
            encoding=str(self.settings.settings()["encoding"]),
        )

    def create_quick_session(
        self,
        values: dict[str, Any],
        *,
        password: str,
        cols: int = 120,
        rows: int = 32,
        address_role: str = "primary",
    ) -> tuple[dict[str, Any], TerminalTicket]:
        connection = self.profiles.connection_values(values)
        secret = str(password or "")
        if not secret:
            raise ValueError("快速连接密码不能为空")
        site_id = active_site_id(self.paths)
        identity = hashlib.sha256(
            f"{site_id}|{connection['protocol']}|{connection['host']}|{connection['port']}|{connection['username']}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        device_uuid = f"terminal-quick-{identity}"
        protocol = str(connection["protocol"])
        device = Device(
            device_uuid=device_uuid,
            name=str(connection["name"]),
            primary_address=str(connection["host"]),
            device_vendor=str(connection["vendor"]),
            device_type=str(connection["device_type"]),
            ssh_enabled=1 if protocol == "SSH" else 0,
            ssh_port=int(connection["port"]) if protocol == "SSH" else 22,
            ssh_username=str(connection["username"]) if protocol == "SSH" else None,
            ssh_password=secret if protocol == "SSH" else None,
            telnet_enabled=1 if protocol == "TELNET" else 0,
            telnet_port=int(connection["port"]) if protocol == "TELNET" else 23,
            telnet_username=str(connection["username"])
            if protocol == "TELNET"
            else None,
            telnet_password=secret if protocol == "TELNET" else None,
        )
        target = ConnectionTarget(
            protocol=protocol.casefold(),
            device_type="autodetect",
            host=str(connection["host"]),
            port=int(connection["port"]),
            username=str(connection["username"]),
            password=secret,
            encoding="mbcs"
            if connection["encoding"] == "ansi"
            else str(connection["encoding"]),
            method="terminal_quick_connect",
            target_role=address_role,
        )
        return self._create_runtime(
            device,
            target,
            requested_protocol=protocol,
            cols=cols,
            rows=rows,
            managed_device=False,
            encoding=str(connection["encoding"]),
        )

    def create_profile_session(
        self,
        profile_id: str,
        *,
        password_override: str = "",
        cols: int = 120,
        rows: int = 32,
        address_role: str = "primary",
    ) -> tuple[dict[str, Any], TerminalTicket]:
        profile, password = self.profiles.resolve(profile_id, password_override)
        if address_role not in {"primary", "backup"}:
            raise ValueError("连接地址角色无效")
        if address_role == "backup":
            if not profile["backup_host"]:
                raise ValueError("保存会话未配置备用地址")
            profile = {
                **profile,
                "host": profile["backup_host"],
                "port": profile["backup_port"],
            }
        return self.create_quick_session(
            profile, password=password, cols=cols, rows=rows,
            address_role=address_role,
        )

    def _create_runtime(
        self,
        device: Device,
        target: ConnectionTarget,
        *,
        requested_protocol: str,
        cols: int,
        rows: int,
        managed_device: bool,
        encoding: str,
    ) -> tuple[dict[str, Any], TerminalTicket]:
        site_id = active_site_id(self.paths)
        site_name = SiteManager(self.paths).get_current_site()
        with self._lock:
            same_device = [
                item
                for item in self._sessions.values()
                if item.snapshot.device_uuid == device.device_uuid
            ]
            session_id = uuid.uuid4().hex
            now = _utc_ms()
            backup_target = next(
                (candidate for candidate in connection_targets(device)
                 if candidate.target_role == "backup"),
                None,
            )
            snapshot = TerminalSessionSnapshot(
                session_id=session_id,
                device_uuid=str(device.device_uuid),
                device_name=str(
                    device.name or device.system_name or device.primary_address
                ),
                site_id=site_id,
                site_name=site_name,
                protocol=target.protocol.upper(),
                encoding=str(encoding or "utf-8"),
                mode="INTERACTIVE",
                state="CREATED",
                address=str(target.host),
                port=int(target.port),
                created_at_ms=now,
                updated_at_ms=now,
                address_role=target.target_role,
                username=target.username,
                backup_address=backup_target.host if backup_target else "",
                backup_port=backup_target.port if backup_target else 0,
                session_name=f"{device.name or device.system_name or device.primary_address}-{len(same_device) + 1:02}",
            )
            recording = TerminalRecordingWriter(self.recording_root, snapshot)
            terminal_cols = self._clamp(cols, 20, 400)
            terminal_rows = self._clamp(rows, 5, 200)
            session = _TerminalSession(
                snapshot,
                device,
                self.paths,
                recording,
                requested_protocol,
                target,
                managed_device,
                terminal_cols=terminal_cols,
                terminal_rows=terminal_rows,
            )
            self._sessions[session_id] = session
            session.thread = threading.Thread(
                target=self._run_session,
                args=(session,),
                name=f"terminal-{session_id[:8]}",
                daemon=True,
            )
            session.thread.start()
            ticket = self.tickets.issue(session_id)
            return snapshot.to_public_dict(), ticket

    def clone_session(self, session_id: str):
        previous = self.get_runtime(session_id)
        if previous.snapshot.site_name != SiteManager(self.paths).get_current_site():
            raise ValueError("会话不属于当前局点")
        return self._create_runtime(
            previous.device,
            previous.target,
            requested_protocol=previous.requested_protocol,
            cols=previous.terminal_cols,
            rows=previous.terminal_rows,
            managed_device=previous.managed_device,
            encoding=previous.snapshot.encoding,
        )

    def claim_detached_window(self, session_id: str):
        runtime = self.get_runtime(session_id)
        with runtime.listener_lock:
            if runtime.listeners or runtime.snapshot.detached_window:
                raise ValueError("此 Session 已有终端显示，请先克隆")
            runtime.snapshot.detached_window = True
            runtime.recording.update_metadata(runtime.snapshot)
        return {"claimed": True}

    def rename_session(self, session_id: str, name: str):
        session = self.get_runtime(session_id)
        value = str(name).strip()
        if not value or len(value) > 160:
            raise ValueError("会话名称无效")
        session.snapshot.session_name = value
        session.recording.update_metadata(session.snapshot)
        return session.snapshot.to_public_dict()

    def _recover_recordings(self):
        for metadata in self.recording_root.glob("*/metadata.json"):
            if metadata.parent.name.startswith("."):
                continue
            try:
                value = json.loads(metadata.read_text(encoding="utf-8"))
                if value.get("recording_status") in {
                    "RECORDING",
                    "FINALIZING",
                    "COMPRESSING",
                }:
                    value.update(
                        recording_status="INCOMPLETE",
                        recording_error="上次录制异常中断，原始事件已保留",
                    )
                    temporary = metadata.with_suffix(".recovery")
                    temporary.write_text(
                        json.dumps(value, ensure_ascii=False), encoding="utf-8"
                    )
                    temporary.replace(metadata)
            except (OSError, ValueError):
                continue

    def delete_recording(self, session_id: str):
        directory = self._session_directory(session_id)
        tombstone = self.recording_root / f".deleting-{session_id}"
        marker = self.recording_root / f".deleting-{session_id}.json"
        with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None and (
                (runtime.thread and runtime.thread.is_alive())
                or runtime.snapshot.recording_status
                in {"RECORDING", "FINALIZING", "COMPRESSING"}
            ):
                raise ValueError("活动或正在整理的录制不能删除")
            if directory.exists():
                metadata = self.session_detail(session_id)
                if metadata.get("recording_status") in {
                    "RECORDING",
                    "FINALIZING",
                    "COMPRESSING",
                }:
                    raise ValueError("录制仍在使用中")
                if tombstone.exists():
                    raise ValueError("删除暂存冲突，请重试")
                metadata.update(
                    deletion_pending=True, recording_error="删除未完成，可重试"
                )
                temporary = marker.with_suffix(".part")
                temporary.write_text(
                    json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
                )
                temporary.replace(marker)
                directory.rename(tombstone)
            if tombstone.exists():
                try:
                    for suffix in (".txt", ".txt.tmp"):
                        legacy = self.export_root / f"terminal-{session_id}{suffix}"
                        if legacy.is_file():
                            legacy.replace(tombstone / f"legacy-export{suffix}")
                    shutil.rmtree(tombstone)
                except OSError as exc:
                    metadata_path = tombstone / "metadata.json"
                    if metadata_path.exists():
                        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                        metadata.update(
                            deletion_pending=True, recording_error="删除未完成，可重试"
                        )
                        metadata_path.write_text(
                            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
                        )
                    raise ValueError(
                        f"删除未完成 ({type(exc).__name__})，记录已隔离，可重试"
                    ) from exc
            marker.unlink(missing_ok=True)
            self._sessions.pop(session_id, None)
        return {"deleted": True, "session_id": session_id}

    def reconnect(self, session_id: str) -> tuple[dict[str, Any], TerminalTicket]:
        with self._lock:
            previous = self.get_runtime(session_id)
            if previous.snapshot.state not in {"DISCONNECTED", "FAILED", "CLOSED"}:
                raise ValueError("只有已断开或失败的会话可以重连")
            replacement = self._sessions.get(previous.replacement_session_id)
            if replacement is not None and replacement.snapshot.state in TERMINAL_LIVE_STATES:
                raise ValueError("会话已有正在连接或使用中的重连")
            snapshot, ticket = self._create_runtime(
                previous.device,
                previous.target,
                requested_protocol=previous.requested_protocol,
                cols=previous.terminal_cols,
                rows=previous.terminal_rows,
                managed_device=previous.managed_device,
                encoding=previous.snapshot.encoding,
            )
            previous.replacement_session_id = ticket.session_id
            return snapshot, ticket

    def issue_ticket(self, session_id: str) -> TerminalTicket:
        session = self.get_runtime(session_id)
        with session.state_lock:
            if session.close_event.is_set() or session.snapshot.state in TERMINAL_FINAL_STATES:
                raise ValueError("已关闭或正在关闭的会话不能创建新的连接票据")
            return self.tickets.issue(session_id)

    def get_runtime(self, session_id: str) -> _TerminalSession:
        with self._lock:
            session = self._sessions.get(str(session_id or ""))
        if session is None:
            raise KeyError("终端会话不存在")
        return session

    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = [
                item
                for item in self._sessions.values()
                if item.snapshot.state not in TERMINAL_FINAL_STATES
            ]
        for session in sessions:
            self._refresh_automation_write_status(session)
        values = [item.snapshot.to_public_dict() for item in sessions]
        return sorted(values, key=lambda item: int(item["created_at_ms"]), reverse=True)

    def refresh_activity(self, session_id: str) -> dict[str, Any]:
        session = self.get_runtime(session_id)
        self._refresh_automation_write_status(session)
        return session.snapshot.to_public_dict()

    def _refresh_automation_write_status(self, session: _TerminalSession) -> None:
        snapshot = session.snapshot
        snapshot.automation_write_active = False
        snapshot.automation_write_task_id = ""
        snapshot.automation_write_task_name = ""
        try:
            resource_key = device_write_resource_key(
                snapshot.site_id, snapshot.device_uuid
            )
            repository = TaskRepository(
                self.paths.site_tasks_db_path(snapshot.site_name)
            )
            active = repository.list_filtered(
                statuses={
                    TaskState.PENDING,
                    TaskState.STARTING,
                    TaskState.RUNNING,
                    TaskState.STOPPING,
                },
                limit=1000,
            )
        except (OSError, RuntimeError, ValueError):
            return
        task = next(
            (item for item in active if resource_key in item.resource_keys),
            None,
        )
        if task is not None:
            snapshot.automation_write_active = True
            snapshot.automation_write_task_id = task.task_id
            snapshot.automation_write_task_name = task.task_name

    def history(self, *, keyword: str = "", limit: int = 100) -> list[dict[str, Any]]:
        needle = str(keyword or "").strip().casefold()
        result: list[dict[str, Any]] = []
        for metadata in self.recording_root.glob("*/metadata.json"):
            if metadata.parent.name.startswith("."):
                continue
            try:
                value = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            haystack = " ".join(
                str(value.get(key) or "")
                for key in (
                    "session_id",
                    "device_name",
                    "device_uuid",
                    "address",
                    "protocol",
                    "state",
                    "site_name",
                )
            ).casefold()
            if needle and needle not in haystack:
                continue
            result.append(value)
        for marker in self.recording_root.glob(".deleting-*.json"):
            try:
                value = json.loads(marker.read_text(encoding="utf-8"))
                if (
                    not needle
                    or needle in json.dumps(value, ensure_ascii=False).casefold()
                ):
                    result.append(value)
            except (OSError, ValueError):
                continue
        result.sort(key=lambda item: int(item.get("created_at_ms") or 0), reverse=True)
        return result[: self._clamp(limit, 1, 500)]

    def session_detail(self, session_id: str) -> dict[str, Any]:
        metadata = self._session_directory(session_id) / "metadata.json"
        if not metadata.is_file():
            raise KeyError("终端历史不存在")
        return json.loads(metadata.read_text(encoding="utf-8"))

    def close_session(self, session_id: str) -> dict[str, Any]:
        session = self.get_runtime(session_id)
        with session.state_lock:
            if session.snapshot.state == "DISCONNECTED":
                self._transition(session, "CLOSED", reason="USER_REQUEST")
            elif session.snapshot.state not in TERMINAL_FINAL_STATES and not session.close_event.is_set():
                session.close_event.set()
                target_state = (
                    "CANCELLED" if session.snapshot.state == "CREATED" else "CLOSING"
                )
                self._transition(session, target_state, reason="USER_REQUEST")
                try:
                    session.input_queue.put_nowait(("close", None))
                except queue.Full:
                    pass
            return session.snapshot.to_public_dict()

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        session = self.get_runtime(session_id)
        if session.snapshot.state in TERMINAL_FINAL_STATES:
            raise ValueError("终态会话不能调整窗口")
        dimensions = (self._clamp(cols, 20, 400), self._clamp(rows, 5, 200))
        session.terminal_cols, session.terminal_rows = dimensions
        session.input_queue.put_nowait(("resize", dimensions))

    def input(self, session_id: str, data: str, *, receipt=None) -> None:
        session = self.get_runtime(session_id)
        if len(data) > self.MAX_MESSAGE_CHARS:
            raise ValueError("终端输入消息超过大小限制")
        with session.state_lock:
            if session.close_event.is_set() or session.snapshot.state not in {"CONNECTED", "RUNNING"}:
                raise ValueError("终端会话当前不可输入")
            for command in self._risk_commands(session, data):
                matches = self.settings.match_dangerous_command(command, session.device)
                if not matches:
                    continue
                safe_command = _sanitize_terminal_data(command, session.device)
                rule_ids = [str(item["id"]) for item in matches]
                self._record(
                    session,
                    "RISK",
                    command=safe_command,
                    rule_ids=rule_ids,
                    severity="WARNING",
                )
                if self.settings.settings()["dangerous_command_warning"]:
                    session.publish(
                        {
                            "type": "risk_warning",
                            "command": safe_command,
                            "rule_ids": rule_ids,
                            "message": "检测到高危命令，请确认当前设备和操作意图。",
                        }
                    )
            session.input_queue.put_nowait(
                ("write", {"data": data, "receipt": receipt} if receipt else data)
            )
            session.snapshot.command_count += data.count("\r") + data.count("\n")

    def send_confirmed(self, session_id, data, *, scope, cancel_event=None):
        receipt = {
            "done": threading.Event(),
            "error": "",
            "cancel": cancel_event,
            "scope": scope,
        }
        self.input(session_id, data, receipt=receipt)
        if not receipt["done"].wait(15):
            raise TimeoutError("终端写入尚未确认，不能视为执行成功；请核对终端后重试")
        if receipt["error"]:
            raise TimeoutError(
                f"写入结果无法确认（可能已部分发送），请先核对终端：{receipt['error']}"
            )

    def recording_events(
        self, session_id: str, *, offset: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        path = self._session_directory(session_id) / "events.jsonl"
        if not path.is_file():
            return []
        result: list[dict[str, Any]] = []
        start = max(0, int(offset))
        maximum = self._clamp(limit, 1, 2000)
        with path.open("r", encoding="utf-8") as stream:
            for index, line in enumerate(stream):
                if index < start:
                    continue
                try:
                    result.append(json.loads(line))
                except ValueError:
                    result.append({"at_ms": 0, "event_type": "CORRUPTED_RECORD"})
                if len(result) >= maximum:
                    break
        return result

    def start_manual_log(
        self,
        session_id: str,
        *,
        filename: str,
        log_format: str = "txt",
    ) -> dict[str, Any]:
        session = self.get_runtime(session_id)
        if session.snapshot.state not in {"CONNECTED", "RUNNING"}:
            raise ValueError("只有已连接会话可以开始会话日志")
        if session.manual_log is not None:
            raise RuntimeError("当前会话日志已经开始")
        fmt = str(log_format or "txt").strip().casefold()
        if fmt not in {"txt", "jsonl"}:
            raise ValueError("会话日志只支持 TXT 或 JSONL")
        writer = TerminalManualLogWriter(
            self.manual_log_root,
            session.snapshot,
            filename=str(filename or ""),
            log_format=fmt,
        )
        session.manual_log = writer
        session.snapshot.manual_log_status = "RECORDING"
        session.snapshot.manual_log_id = writer.log_id
        session.snapshot.manual_log_format = fmt
        session.snapshot.manual_log_filename = writer.filename
        session.snapshot.manual_log_dropped_events = 0
        self._transition(session, session.snapshot.state)
        return session.snapshot.to_public_dict()

    def pause_manual_log(self, session_id: str) -> dict[str, Any]:
        session = self.get_runtime(session_id)
        if (
            session.manual_log is None
            or session.snapshot.manual_log_status != "RECORDING"
        ):
            raise ValueError("当前会话日志未在记录")
        session.snapshot.manual_log_status = "PAUSED"
        self._transition(session, session.snapshot.state)
        return session.snapshot.to_public_dict()

    def resume_manual_log(self, session_id: str) -> dict[str, Any]:
        session = self.get_runtime(session_id)
        if session.manual_log is None or session.snapshot.manual_log_status != "PAUSED":
            raise ValueError("当前会话日志未暂停")
        session.snapshot.manual_log_status = "RECORDING"
        self._transition(session, session.snapshot.state)
        return session.snapshot.to_public_dict()

    def stop_manual_log(self, session_id: str) -> dict[str, Any]:
        session = self.get_runtime(session_id)
        writer = session.manual_log
        if writer is None:
            raise ValueError("当前会话日志未开始")
        writer.close(session.snapshot)
        session.snapshot.manual_log_dropped_events = writer.dropped_events
        session.snapshot.manual_log_status = writer.status
        session.manual_log = None
        self._transition(session, session.snapshot.state)
        return session.snapshot.to_public_dict()

    def manual_log_export_path(self, session_id: str, log_id: str) -> tuple[Path, str]:
        session_directory = self._manual_log_directory(session_id, log_id)
        metadata_path = session_directory / "metadata.json"
        if not metadata_path.is_file():
            raise KeyError("会话日志不存在")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        filename = str(metadata.get("filename") or "")
        path = (session_directory / filename).resolve()
        if path.parent != session_directory or not path.is_file():
            raise KeyError("会话日志文件不存在")
        return path, filename

    def export_path(self, session_id: str, export_format: str) -> tuple[Path, str]:
        fmt = str(export_format or "").strip().casefold()
        session_dir = self._session_directory(session_id)
        events = session_dir / "events.jsonl"
        if not events.is_file():
            raise KeyError("终端录制不存在")
        if fmt == "jsonl":
            return events, f"terminal-{session_id}.jsonl"
        metadata = self.session_detail(session_id)
        if fmt in {"log", "zip"}:
            name = str(metadata.get(f"recording_{fmt}_name") or "")
            result = (session_dir / name).resolve()
            if result.parent != session_dir or not result.is_file():
                raise ValueError("录制文件尚未生成或处理失败")
            return result, name
        if fmt != "txt":
            raise ValueError("终端历史支持 LOG、ZIP、TXT 或 JSONL 导出")
        target = session_dir / "preview.txt"
        temporary = target.with_suffix(".txt.tmp")
        with (
            events.open("r", encoding="utf-8") as source,
            temporary.open("w", encoding="utf-8", newline="\n") as destination,
        ):
            render_events((json.loads(line) for line in source), destination)
        os.replace(temporary, target)
        return target, target.name

    def close(self) -> None:
        self.dispatcher.close()
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            if session.snapshot.state not in TERMINAL_FINAL_STATES:
                self.close_session(session.snapshot.session_id)
        deadline = time.monotonic() + 5
        for session in sessions:
            remaining = max(0.0, deadline - time.monotonic())
            if session.thread is not None:
                session.thread.join(timeout=remaining)

    def _run_session(self, session: _TerminalSession) -> None:
        transport = None
        try:
            with session.state_lock:
                if session.snapshot.state == "CANCELLED":
                    self._transition(session, "CLOSED", reason="USER_REQUEST")
                    return
                self._transition(session, "CONNECTING")
            target = session.target
            encoding = session.snapshot.encoding
            target = replace(
                target, encoding="mbcs" if encoding == "ansi" else encoding
            )
            transport = create_terminal_transport(
                self.paths,
                session.device,
                target,
                site_name=session.snapshot.site_name,
                site_id=session.snapshot.site_id,
                managed_device=session.managed_device,
            )
            transport.connect(session.terminal_cols, session.terminal_rows)
            if session.close_event.is_set() or session.snapshot.state in {
                "CANCELLED",
                "CLOSING",
            }:
                self._transition(session, "CLOSED", reason="USER_REQUEST")
                return
            session.snapshot.connected_at_ms = _utc_ms()
            self._record(
                session,
                "SESSION_START",
                address=session.target.host,
                port=session.target.port,
            )
            self._transition(session, "CONNECTED")
            self._transition(session, "RUNNING")
            while not session.close_event.is_set():
                try:
                    action, value = session.input_queue.get(timeout=0.05)
                except queue.Empty:
                    action, value = "", None
                if action == "write":
                    receipt = value.get("receipt") if isinstance(value, dict) else None
                    data = value["data"] if isinstance(value, dict) else str(value)
                    try:
                        if (
                            session.close_event.is_set()
                            or (receipt and receipt.get("cancel") and receipt["cancel"].is_set())
                        ):
                            if not receipt:
                                continue
                            receipt["error"] = "发送前已取消"
                            self._record(
                                session,
                                "BATCH_SEND",
                                session_id=session.snapshot.session_id,
                                data=data,
                                scope=receipt["scope"],
                                result="CANCELLED_PENDING",
                                sent_at_ms=_utc_ms(),
                            )
                            receipt["done"].set()
                            continue
                        transport.write(data)
                        self._record(session, "INPUT", data=data)
                        if receipt:
                            self._record(
                                session,
                                "BATCH_SEND",
                                session_id=session.snapshot.session_id,
                                data=data,
                                scope=receipt["scope"],
                                result="WRITTEN",
                                sent_at_ms=_utc_ms(),
                            )
                    except Exception as exc:
                        if receipt:
                            receipt["error"] = str(exc)
                            self._record(
                                session,
                                "BATCH_SEND",
                                session_id=session.snapshot.session_id,
                                data=data,
                                scope=receipt["scope"],
                                result="UNCONFIRMED",
                                sent_at_ms=_utc_ms(),
                            )
                        raise
                    finally:
                        if receipt:
                            receipt["done"].set()
                elif action == "resize" and not session.close_event.is_set():
                    transport.resize(*value)
                elif action == "close":
                    break
                output = str(transport.read() or "")
                if output and not session.close_event.is_set():
                    session.snapshot.output_bytes += len(
                        output.encode("utf-8", errors="replace")
                    )
                    self._record(session, "OUTPUT", data=output)
                    session.publish({"type": "output", "data": output})
            if session.snapshot.state != "CLOSING":
                self._transition(session, "CLOSING", reason="TRANSPORT_STOPPED")
            self._transition(
                session,
                "CLOSED",
                reason=session.snapshot.disconnect_reason or "USER_REQUEST",
            )
        except BaseException as exc:
            if (
                session.snapshot.state in {"CANCELLED", "CLOSING"}
                or session.close_event.is_set()
            ):
                self._transition(session, "CLOSED", reason="USER_REQUEST", force=True)
                return
            error_code = self._safe_error_code(exc)
            session.snapshot.error_message = _sanitize_terminal_data(
                str(exc), session.device
            )[:2000]
            app_logger.log_error(
                "TERMINAL_SESSION_FAILED",
                f"session_id={session.snapshot.session_id} device_uuid={session.snapshot.device_uuid} error={error_code}",
            )
            if session.snapshot.state in {"CONNECTED", "RUNNING"}:
                self._transition(
                    session,
                    "DISCONNECTED",
                    reason="TRANSPORT_ERROR",
                    error_code=error_code,
                    force=True,
                )
                message = "终端连接已断开"
            else:
                self._transition(
                    session,
                    "FAILED",
                    reason="TRANSPORT_ERROR",
                    error_code=error_code,
                    force=True,
                )
                message = "终端连接失败"
            session.publish(
                {
                    "type": "error",
                    "code": error_code,
                    "message": f"{message}：{session.snapshot.error_message}",
                }
            )
        finally:
            while True:
                try:
                    action, value = session.input_queue.get_nowait()
                except queue.Empty:
                    break
                if action == "write" and isinstance(value, dict) and (receipt := value.get("receipt")):
                    receipt["error"] = "会话已结束，命令未发送"
                    receipt["done"].set()
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            session.snapshot.ended_at_ms = session.snapshot.ended_at_ms or _utc_ms()
            if session.manual_log is not None:
                writer = session.manual_log
                writer.close(session.snapshot)
                session.snapshot.manual_log_dropped_events = writer.dropped_events
                session.snapshot.manual_log_status = writer.status
                session.manual_log = None
            session.recording.close(session.snapshot)
            session.publish(
                {"type": "state", "session": session.snapshot.to_public_dict()}
            )

    def _transition(
        self,
        session: _TerminalSession,
        state: str,
        *,
        reason: str = "",
        error_code: str = "",
        force: bool = False,
    ) -> None:
        if state not in TERMINAL_STATES:
            raise ValueError(f"未知终端状态: {state}")
        with session.state_lock:
            current = session.snapshot.state
            if (
                not force
                and state != current
                and state not in TERMINAL_TRANSITIONS[current]
            ):
                raise RuntimeError(f"非法终端状态迁移: {current} -> {state}")
            session.snapshot.state = state
            session.snapshot.updated_at_ms = _utc_ms()
            if reason:
                session.snapshot.disconnect_reason = reason
            if error_code:
                session.snapshot.error_code = error_code
            if state in TERMINAL_FINAL_STATES:
                session.snapshot.ended_at_ms = _utc_ms()
            self._record(
                session,
                "STATE",
                previous=current,
                state=state,
                reason=reason,
                error_code=error_code,
            )
            session.recording.update_metadata(session.snapshot)
            session.publish(
                {"type": "state", "session": session.snapshot.to_public_dict()}
            )

    @staticmethod
    def _record(session: _TerminalSession, event_type: str, **detail: Any) -> None:
        if not session.recording.append(event_type, **detail):
            session.snapshot.recording_status = "INCOMPLETE"
        if (
            session.manual_log is not None
            and session.snapshot.manual_log_status == "RECORDING"
        ):
            if not session.manual_log.append(event_type, **detail):
                session.snapshot.manual_log_dropped_events = (
                    session.manual_log.dropped_events
                )

    @staticmethod
    def _risk_commands(session: _TerminalSession, data: str) -> list[str]:
        commands: list[str] = []
        for char in str(data or ""):
            if session.risk_escape_state == "ESC":
                session.risk_escape_state = "CSI" if char == "[" else ""
                continue
            if session.risk_escape_state == "CSI":
                if "@" <= char <= "~":
                    session.risk_escape_state = ""
                continue
            if char == "\x1b":
                session.risk_escape_state = "ESC"
                continue
            if char == "\n" and session.risk_last_was_cr:
                session.risk_last_was_cr = False
                continue
            if char in {"\r", "\n"}:
                command = session.risk_input_buffer.strip()
                if command:
                    commands.append(command)
                session.risk_input_buffer = ""
                session.risk_last_was_cr = char == "\r"
                continue
            session.risk_last_was_cr = False
            if char in {"\b", "\x7f"}:
                session.risk_input_buffer = session.risk_input_buffer[:-1]
            elif char in {"\x03", "\x04", "\x15"}:
                session.risk_input_buffer = ""
            elif char == "\t" or char >= " ":
                session.risk_input_buffer += char
        return commands

    def _session_directory(self, session_id: str) -> Path:
        value = str(session_id or "").strip().casefold()
        if len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("终端会话 ID 无效")
        candidate = (self.recording_root / value).resolve()
        if candidate.parent != self.recording_root.resolve():
            raise ValueError("终端会话路径越界")
        return candidate

    def _manual_log_directory(self, session_id: str, log_id: str) -> Path:
        session_value = str(session_id or "").strip().casefold()
        log_value = str(log_id or "").strip().casefold()
        for value, label in ((session_value, "终端会话"), (log_value, "会话日志")):
            if len(value) != 32 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"{label} ID 无效")
        root = self.manual_log_root.resolve()
        candidate = (root / session_value / log_value).resolve()
        if candidate.parent.parent != root:
            raise ValueError("会话日志路径越界")
        return candidate

    @staticmethod
    def _safe_error_code(exc: BaseException) -> str:
        name = exc.__class__.__name__.upper()
        text = str(exc).casefold()
        if "auth" in text or "password" in text:
            return "AUTHENTICATION_FAILED"
        if "timeout" in text or "timed out" in text:
            return "CONNECTION_TIMEOUT"
        if "no_connection_target" in text:
            return "NO_CONNECTION_TARGET"
        return name[:64] or "TERMINAL_FAILED"

    @staticmethod
    def _clamp(value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(int(value), maximum))


__all__ = [
    "TERMINAL_FINAL_STATES",
    "TERMINAL_STATES",
    "TerminalSessionManager",
    "TerminalSessionSnapshot",
    "TerminalTicket",
    "TerminalTicketStore",
]
