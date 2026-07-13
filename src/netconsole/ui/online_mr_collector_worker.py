from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_application import OnlineMrPhase, OnlineMrStartRequest
from netconsole.models.online_mr_models import (
    STATE_COLLECTING,
    STATE_CONNECTING,
    STATE_CREATED,
    STATE_FAILED,
    STATE_FORCED_STOPPED,
    STATE_INITIALIZING,
    STATE_STOPPED,
    STATE_STOPPING,
    OnlineMrConnectionConfig,
    OnlineMrSnapshot,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.online_mr.collection_models import (
    collection_config_to_payload,
    session_meta_from_payload,
    snapshot_from_payload,
)
from netconsole.services.online_mr.collection_paths import OnlineMrCollectionPaths
from netconsole.services.online_mr.core.event_model import (
    EVENT_BUSY_SAMPLE,
    EVENT_INTERFACE_SAMPLE,
    EVENT_MESH_SAMPLE,
    EVENT_RAW_LINE,
    EVENT_STATS_SAMPLE,
    OnlineMrEvent,
)
from netconsole.services.online_mr_session_store import OnlineMrSession

if TYPE_CHECKING:
    from netconsole.models.api.online_mr import OnlineMrOperationSnapshotDTO
    from netconsole.services.online_mr.application_service import OnlineMrApplicationService


_COLLECTOR_RAW_PREFIX = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)"
    r"\s+\[collector=[^\]]+\]\s+(?:(?:RX|TX)\s*)?(?P<line>.*)$"
)


@dataclass
class _CollectorFacade:
    config: OnlineMrConnectionConfig
    session: OnlineMrSession | None = None
    cancelled: bool = False
    status: str = STATE_CREATED
    latest_snapshot: OnlineMrSnapshot | None = None

    def snapshot(self) -> OnlineMrSnapshot:
        if self.latest_snapshot is not None:
            return self.latest_snapshot
        return OnlineMrSnapshot(
            session_id=self.session.meta.session_id if self.session is not None else f"pending:{self.config.device_id or 0}",
            status=self.status,
            device_id=self.config.device_id,
            device_name=self.config.device_name,
            host=self.config.host,
        )


class OnlineMrCollectorWorker(QObject):
    """兼容旧页面信号的 Job Center 句柄；本对象不执行 SSH 或采集循环。"""

    snapshot = Signal(object)
    raw_stream_event = Signal(object)
    started_session = Signal(object)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        config: OnlineMrConnectionConfig,
        paths: PathResolver,
        connection_factory=None,
        realtime_cache=None,
        config_only: bool = False,
        application_service: OnlineMrApplicationService | None = None,
        application_request: OnlineMrStartRequest | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if connection_factory is not None:
            raise ValueError("Job Center 在线 MR 采集不接受 UI 进程连接工厂")
        if config_only:
            raise ValueError("配置单独采集请使用对应 Job Center 任务")
        self.config = config
        self.paths = paths
        self.realtime_cache = realtime_cache
        self.collector = _CollectorFacade(config)
        self.job_id = f"online_mr_collection_{uuid4().hex}"
        if (application_service is None) != (application_request is None):
            raise ValueError("Online MR Application Service 与启动请求必须同时提供")
        self.application_service = application_service
        self.application_request = application_request
        self.operation_snapshot: OnlineMrOperationSnapshotDTO | None = None
        self.manages_traffic = application_service is not None
        self._application_events: deque[dict[str, object]] = deque(maxlen=2000)
        self._application_unsubscribe = None
        self._terminal_emitted = False
        self._manager: BackgroundProcessManager | None = None
        if application_service is None:
            self._manager = BackgroundProcessManager(self, paths=paths)
            self._manager.progress.connect(self._handle_progress)
            self._manager.finished.connect(self._handle_finished)
            self._manager.failed.connect(self._handle_failed)
            self._manager.cancelled.connect(self._handle_cancelled)
        self._application_timer = QTimer(self)
        self._application_timer.setInterval(500)
        self._application_timer.timeout.connect(self._poll_application_events)
        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(250)
        self._tail_timer.timeout.connect(self._poll_raw_files)
        self._raw_offsets: dict[Path, int] = {}
        self._raw_buffers: dict[Path, str] = {}

    def start(self) -> OnlineMrOperationSnapshotDTO | None:
        if self.application_service is not None and self.application_request is not None:
            self._application_unsubscribe = self.application_service.task_service.events.subscribe(
                self._enqueue_application_event
            )
            try:
                operation = self.application_service.start_local_collection(self.application_request)
            except Exception:
                self._stop_application_monitor()
                raise
            self.job_id = operation.controller_task_id
            self.operation_snapshot = operation
            self.collector.status = self._operation_status(operation)
            self._application_timer.start()
            self._poll_application_events()
            return operation
        if self._manager is None:
            raise RuntimeError("Online MR Job Manager 未初始化")
        grace_ms = min(60000, max(30000, int(self.config.command_timeout or 15) * 1000 + 5000))
        self._manager.start_job(
            BackgroundJob(
                job_id=self.job_id,
                task_type="online_mr_collection_start",
                params={
                    "config": collection_config_to_payload(self.config),
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "package_on_stop": True,
                    "_cancel_grace_ms": grace_ms,
                },
            )
        )
        return None

    def cancel(self) -> None:
        self.collector.cancelled = True
        self.collector.status = STATE_STOPPING
        if self.application_service is not None:
            self.operation_snapshot = self.application_service.stop_operation(
                self.job_id,
                site_id=self.config.site,
                timeout_seconds=0.0,
                stop_reason="user_stop",
            )
            return
        if self._manager is not None:
            self._manager.cancel_job(self.job_id)

    def force_stop(self, reason: str = "force_stop") -> None:
        self.collector.cancelled = True
        self.collector.status = STATE_FORCED_STOPPED
        if self.application_service is not None:
            self.operation_snapshot = self.application_service.force_stop_operation(
                self.job_id,
                site_id=self.config.site,
                cooperative_timeout_seconds=0.0,
                force_timeout_seconds=0.1,
                stop_reason=reason,
            )
            self._poll_raw_files()
            self._stop_application_monitor()
            return
        if self._manager is not None:
            self._manager.force_stop_job(self.job_id)

    def isRunning(self) -> bool:
        if self.application_service is not None:
            try:
                operation = self.application_service.get_operation(self.job_id, site_id=self.config.site)
            except Exception:
                return False
            self.operation_snapshot = operation
            return operation.phase is not OnlineMrPhase.TERMINAL
        return self._manager is not None and self._manager.is_running(self.job_id)

    def _enqueue_application_event(self, event: dict[str, object]) -> None:
        self._application_events.append(dict(event))

    def _poll_application_events(self) -> None:
        while self._application_events:
            envelope = self._application_events.popleft()
            if str(envelope.get("task_id") or "") != self.job_id:
                continue
            payload = dict(envelope.get("payload") or {})
            event = {**payload, "job_id": self.job_id}
            event_type = str(envelope.get("type") or payload.get("type") or "")
            if event_type == "progress":
                self._handle_progress(event)
            elif event_type == "finished":
                self._handle_finished(event)
            elif event_type == "error":
                self._handle_failed(event)
            elif event_type == "cancelled":
                self._handle_cancelled(event)
        self._refresh_application_operation()

    def _refresh_application_operation(self) -> None:
        if self.application_service is None or not self.job_id or self._terminal_emitted:
            return
        try:
            operation = self.application_service.get_operation(self.job_id, site_id=self.config.site)
        except Exception:
            return
        self.operation_snapshot = operation
        self.collector.status = self._operation_status(operation)
        if operation.session_id and self.collector.session is None:
            self._attach_application_session(operation.session_id)
        if operation.phase is not OnlineMrPhase.TERMINAL:
            return
        if self.collector.status == STATE_FAILED:
            self._handle_failed(
                {
                    "job_id": self.job_id,
                    "message": operation.error_summary or operation.error_message or "在线 MR 采集失败",
                }
            )
        else:
            self._handle_finished(
                {
                    "job_id": self.job_id,
                    "result": {
                        "session_id": operation.session_id or "",
                        "status": self.collector.status,
                    },
                }
            )

    def _attach_application_session(self, session_id: str) -> None:
        if self.application_request is None:
            return
        session_dir = self.paths.online_mr_session_dir(
            self.application_request.site_id,
            self.application_request.config.safe_mr_name,
            session_id,
        )
        meta_path = session_dir / "session_meta.json"
        if not meta_path.is_file():
            return
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            meta = session_meta_from_payload(payload)
        except (OSError, ValueError, TypeError):
            return
        meta.session_dir = session_dir
        self.collector.session = OnlineMrSession(session_dir, meta)
        self._tail_timer.start()
        self.started_session.emit(meta)

    @staticmethod
    def _operation_status(operation: OnlineMrOperationSnapshotDTO) -> str:
        phase = operation.phase
        if phase is OnlineMrPhase.TERMINAL:
            if operation.force_stopped:
                return STATE_FORCED_STOPPED
            if str(operation.task_status or "").upper() == "FAILED" or operation.error_code:
                return STATE_FAILED
            return STATE_STOPPED
        if phase is OnlineMrPhase.COLLECTING:
            return STATE_COLLECTING
        if phase in {
            OnlineMrPhase.STOPPING_TRAFFIC,
            OnlineMrPhase.STOPPING_COLLECTION,
            OnlineMrPhase.FINALIZING,
            OnlineMrPhase.PARSING,
            OnlineMrPhase.PACKAGING,
        }:
            return STATE_STOPPING
        if phase is OnlineMrPhase.CONNECTING:
            return STATE_CONNECTING
        if phase in {OnlineMrPhase.STARTING_COLLECTION, OnlineMrPhase.PREPARING_SESSION}:
            return STATE_INITIALIZING
        return STATE_CONNECTING

    def _handle_progress(self, event: dict[str, object]) -> None:
        if str(event.get("job_id") or "") != self.job_id:
            return
        stage = str(event.get("stage") or "")
        message = str(event.get("message") or "")
        if stage == "online_mr_started":
            payload = self._json_message(message)
            meta = session_meta_from_payload(payload)
            if meta.session_dir is None and payload.get("session_dir"):
                meta.session_dir = Path(str(payload["session_dir"]))
            existing_session_id = self.collector.session.meta.session_id if self.collector.session is not None else ""
            if meta.session_dir is not None:
                self.collector.session = OnlineMrSession(meta.session_dir, meta)
                self._tail_timer.start()
            self.collector.status = meta.status
            if existing_session_id != meta.session_id:
                self.started_session.emit(meta)
            return
        if stage == "online_mr_status":
            snapshot = snapshot_from_payload(self._json_message(message))
            self.collector.latest_snapshot = snapshot
            self.collector.status = snapshot.status
            self.snapshot.emit(snapshot)

    def _handle_finished(self, event: dict[str, object]) -> None:
        if str(event.get("job_id") or "") != self.job_id:
            return
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        result = dict(event.get("result") or {})
        self.collector.status = str(result.get("status") or STATE_STOPPED)
        self._stop_application_monitor()
        self._stop_tail()
        self._cleanup_package_tmp()
        self.completed.emit(str(result.get("session_id") or self._session_id()))

    def _handle_failed(self, event: dict[str, object]) -> None:
        if str(event.get("job_id") or "") != self.job_id:
            return
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        self.collector.status = STATE_FAILED
        self._stop_application_monitor()
        self._stop_tail()
        self._cleanup_package_tmp()
        self.failed.emit(str(event.get("message") or event.get("error") or "在线 MR 采集失败"))

    def _handle_cancelled(self, event: dict[str, object]) -> None:
        if str(event.get("job_id") or "") != self.job_id:
            return
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        if self.operation_snapshot is not None and self.operation_snapshot.force_stopped:
            self.collector.status = STATE_FORCED_STOPPED
        else:
            self.collector.status = STATE_STOPPED
        self._stop_application_monitor()
        self._stop_tail()
        self._cleanup_package_tmp()
        self.completed.emit(self._session_id())

    def _poll_raw_files(self) -> None:
        session = self.collector.session
        if session is None:
            return
        paths = OnlineMrCollectionPaths.from_session_dir(session.session_dir)
        sources = {
            paths.mesh_link_raw: ("mesh", EVENT_MESH_SAMPLE, "mesh_link"),
            paths.channel_busy_raw: ("busy", EVENT_BUSY_SAMPLE, "channel_busy"),
            paths.ap_radio_statistics_raw: ("stats", EVENT_STATS_SAMPLE, "ap_radio_statistics"),
            paths.interface_rate_raw: ("interface_rate", EVENT_INTERFACE_SAMPLE, "interface_rate"),
            paths.wireless_status_raw: ("wireless_status", EVENT_RAW_LINE, "wireless_status"),
        }
        for path, (module, event_type, task_type) in sources.items():
            self._poll_raw_file(path, module, event_type, task_type)

    def _poll_raw_file(self, path: Path, module: str, event_type: str, task_type: str) -> None:
        if not path.is_file():
            return
        offset = self._raw_offsets.get(path, 0)
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
                self._raw_offsets[path] = handle.tell()
        except OSError:
            return
        if not chunk:
            return
        text = self._raw_buffers.get(path, "") + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._raw_buffers[path] = lines.pop()
        session = self.collector.session
        if session is None:
            return
        for line in lines:
            if not line:
                continue
            raw_line = line.rstrip("\r")
            timestamp, parser_line = self._split_collector_raw_line(raw_line)
            self.raw_stream_event.emit(
                OnlineMrEvent(
                    timestamp=timestamp,
                    session_id=session.meta.session_id,
                    device_id=self.config.device_id,
                    source="ssh_raw_tail",
                    module=module,
                    event_type=event_type,
                    payload={"task_type": task_type, "line": parser_line, "raw_line": raw_line},
                    raw=raw_line,
                )
            )

    @staticmethod
    def _split_collector_raw_line(raw_line: str) -> tuple[datetime, str]:
        match = _COLLECTOR_RAW_PREFIX.match(raw_line)
        if match is None:
            return datetime.now(), raw_line
        try:
            timestamp = datetime.fromisoformat(match.group("timestamp").replace("T", " "))
        except ValueError:
            timestamp = datetime.now()
        return timestamp, match.group("line")

    def _stop_tail(self) -> None:
        self._poll_raw_files()
        self._tail_timer.stop()

    def _stop_application_monitor(self) -> None:
        self._application_timer.stop()
        unsubscribe = self._application_unsubscribe
        self._application_unsubscribe = None
        if unsubscribe is not None:
            unsubscribe()

    def _cleanup_package_tmp(self) -> None:
        if self.collector.session is None:
            return
        try:
            OnlineMrCollectionPaths.from_session_dir(self.collector.session.session_dir).package_tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _session_id(self) -> str:
        return self.collector.session.meta.session_id if self.collector.session is not None else ""

    @staticmethod
    def _json_message(message: str) -> dict[str, object]:
        payload = json.loads(message or "{}")
        if not isinstance(payload, dict):
            raise ValueError("在线 MR Job 状态不是 JSON 对象")
        return payload
