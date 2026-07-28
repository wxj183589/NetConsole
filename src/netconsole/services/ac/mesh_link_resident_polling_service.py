from __future__ import annotations

import hashlib
import json
import os
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TERMINAL_TASK_STATES
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkConnectionError,
    AcMeshLinkRefreshError,
    AcMeshLinkRefreshErrorCode,
    AcMeshLinkRefreshWorkerService,
    AcMeshLinkSnapshotCollector,
    ConnectionFactory,
    MESH_LINK_REFRESH_COMMANDS,
    MeshLinkConnection,
    load_mesh_link_controller,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_context import (
    BackgroundTaskCancelled,
    JobContext,
)
from netconsole.services.job_center.local_process_adapter import (
    LocalProcessAdapter,
    LocalProcessCompletion,
)
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)
from netconsole.services.online_mr_collector import NetmikoShellConnection


MESH_LINK_RESIDENT_TASK_TYPE = "ac_mesh_link_resident_poll"
MESH_LINK_RESIDENT_OWNER = "ground_unattended_ac_mesh_link"
MESH_LINK_RESIDENT_SOURCE_TYPE = "ac_resident_poll"
RESIDENT_CONNECTION_STATES = frozenset(
    {
        "CONNECTING",
        "CONNECTED",
        "POLLING",
        "WAITING",
        "RECONNECTING",
        "BACKOFF",
        "STOPPING",
        "STOPPED",
        "FAILED",
    }
)
_ACTIVE_TASK_STATES = frozenset({"PENDING", "STARTING", "RUNNING", "STOPPING"})
_DEFAULT_BACKOFF_SECONDS = (2.0, 5.0, 10.0, 30.0, 60.0)


@dataclass(frozen=True)
class AcMeshLinkResidentPollerStart:
    task: TaskSnapshot
    poll_session_id: str
    already_running: bool = False
    recovered: bool = False


@dataclass(frozen=True)
class AcMeshLinkResidentRefreshRequest:
    task: TaskSnapshot
    request_id: str


@dataclass(frozen=True)
class AcMeshLinkResidentStopResult:
    success: bool
    pollers: tuple[dict[str, object], ...]


def resident_poller_directory(
    paths: PathResolver,
    site_name: str,
    run_id: str,
    controller_id: str,
) -> Path:
    site = SiteManager(paths).validate_site_name(site_name)
    run_key = hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:24]
    controller_key = hashlib.sha256(
        str(controller_id).encode("utf-8")
    ).hexdigest()[:24]
    return (
        paths.ac_mesh_link_root(site)
        / "resident"
        / run_key
        / controller_key
    )


class AcMeshLinkResidentPollingApplicationService:
    """管理每个无人值守 run/controller 唯一的常驻 Worker Task。"""

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self._lock = RLock()
        self._active: dict[tuple[str, str, str], str] = {}

    def ensure_poller(
        self,
        *,
        site_name: str,
        run_id: str,
        controller_id: str,
        controller_name: str,
        poll_interval_seconds: float,
        include_switch_history: bool = False,
    ) -> AcMeshLinkResidentPollerStart:
        site = SiteManager(self.paths).validate_site_name(site_name)
        controller = load_mesh_link_controller(
            self.paths, site, controller_id, require_credentials=False
        )
        canonical_controller_id = str(controller.device_uuid or controller_id)
        display_name = str(
            controller.name
            or controller.system_name
            or controller_name
            or controller_id
        )
        key = (site, str(run_id), canonical_controller_id)
        poll_session_id = self._poll_session_id(*key)
        with self._lock:
            active = self._active_snapshot(key)
            if active is not None:
                self._update_control(
                    key,
                    poll_interval_seconds=poll_interval_seconds,
                    stop_requested=False,
                )
                return AcMeshLinkResidentPollerStart(
                    active,
                    poll_session_id,
                    already_running=True,
                )

            runtime_dir = resident_poller_directory(
                self.paths, site, run_id, canonical_controller_id
            )
            previous_status = self._read_json(runtime_dir / "status.json")
            previous_control = self._read_json(runtime_dir / "control.json")
            recovered = bool(
                previous_status.get("task_id")
                or previous_control.get("task_id")
            )
            task_id = f"ac-mesh-resident-{uuid.uuid4().hex}"
            task_name = f"AC Mesh-Link 常驻轮询 · {display_name}"
            self._write_json_atomic(
                runtime_dir / "control.json",
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "site_name": site,
                    "run_id": str(run_id),
                    "controller_id": canonical_controller_id,
                    "poll_session_id": poll_session_id,
                    "poll_interval_seconds": self._interval(
                        poll_interval_seconds
                    ),
                    "include_switch_history": bool(include_switch_history),
                    "immediate_request_id": "",
                    "stop_requested": False,
                    "updated_at": self._now_iso(),
                },
            )
            self._write_json_atomic(
                runtime_dir / "status.json",
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "task_mode": "resident",
                    "progress_mode": "indeterminate",
                    "site_name": site,
                    "run_id": str(run_id),
                    "poll_session_id": poll_session_id,
                    "controller_id": canonical_controller_id,
                    "controller_name": display_name,
                    "connection_state": "CONNECTING",
                    "poll_interval_seconds": self._interval(
                        poll_interval_seconds
                    ),
                    "poll_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "reconnect_count": 0,
                    "consecutive_failures": 0,
                    "heartbeat_at": self._now_iso(),
                },
            )
            job = BackgroundJob(
                job_id=task_id,
                task_type=MESH_LINK_RESIDENT_TASK_TYPE,
                params={
                    "site_name": site,
                    "controller_id": canonical_controller_id,
                    "controller_name": display_name,
                    "run_id": str(run_id),
                    "poll_session_id": poll_session_id,
                    "poll_interval_seconds": self._interval(
                        poll_interval_seconds
                    ),
                    "include_switch_history": bool(include_switch_history),
                    "task_mode": "resident",
                    "progress_mode": "indeterminate",
                    "task_name": task_name,
                    "owner": MESH_LINK_RESIDENT_OWNER,
                    "device": canonical_controller_id,
                    "resource_key": (
                        f"ac-mesh-resident:{site}:{run_id}:"
                        f"{canonical_controller_id}"
                    ),
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "_emit_log_events": True,
                    "_cancel_grace_ms": 3000,
                },
            )
            self._active[key] = task_id
            try:
                self.process_adapter.start_job(
                    job,
                    on_complete=lambda value: self._complete(key, value),
                )
            except Exception:
                self._active.pop(key, None)
                failed_status = self._read_json(
                    runtime_dir / "status.json"
                )
                failed_status.update(
                    {
                        "connection_state": "FAILED",
                        "last_error_code": "AC_POLLER_START_FAILED",
                        "last_error_message": (
                            "AC 常驻轮询 Worker 启动失败。"
                        ),
                        "heartbeat_at": self._now_iso(),
                    }
                )
                self._write_json_atomic(
                    runtime_dir / "status.json", failed_status
                )
                raise
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is None:
                self._active.pop(key, None)
                raise RuntimeError("AC 常驻轮询任务创建后未写入任务中心")
            return AcMeshLinkResidentPollerStart(
                snapshot,
                poll_session_id,
                recovered=recovered,
            )

    def request_immediate_if_active(
        self,
        *,
        site_name: str,
        controller_id: str,
    ) -> AcMeshLinkResidentRefreshRequest | None:
        site = SiteManager(self.paths).validate_site_name(site_name)
        with self._lock:
            for key in tuple(self._active):
                if key[0] != site or key[2] != str(controller_id):
                    continue
                snapshot = self._active_snapshot(key)
                if snapshot is None:
                    continue
                request_id = f"acpollreq_{uuid.uuid4().hex}"
                self._update_control(key, immediate_request_id=request_id)
                return AcMeshLinkResidentRefreshRequest(snapshot, request_id)
        return None

    def request_stop_run(
        self,
        *,
        site_name: str,
        run_id: str,
        timeout_seconds: float = 25.0,
    ) -> AcMeshLinkResidentStopResult:
        site = SiteManager(self.paths).validate_site_name(site_name)
        with self._lock:
            keys = [
                key
                for key in self._active
                if key[0] == site and key[1] == str(run_id)
            ]
            for key in keys:
                self._update_control(key, stop_requested=True)
            task_ids = [(key, self._active[key]) for key in keys]
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        rows: list[dict[str, object]] = []
        success = True
        for key, task_id in task_ids:
            remaining = max(0.0, deadline - time.monotonic())
            stopped = self._wait(task_id, remaining)
            forced = False
            if not stopped:
                forced = self._force_stop(task_id)
                stopped = self._wait(task_id, 1.0)
            status = self.read_status(
                site_name=site,
                run_id=run_id,
                controller_id=key[2],
            )
            row = {
                "controller_id": key[2],
                "task_id": task_id,
                "connection_state": str(
                    status.get("connection_state") or "UNKNOWN"
                ),
                "stopped": bool(stopped),
                "forced": bool(forced),
            }
            rows.append(row)
            success = success and bool(stopped)
        return AcMeshLinkResidentStopResult(success, tuple(rows))

    def cancel_task(self, task_id: str) -> bool:
        cancel = getattr(self.process_adapter, "cancel_job", None)
        return bool(cancel(task_id) if callable(cancel) else False)

    def read_status(
        self,
        *,
        site_name: str,
        run_id: str,
        controller_id: str,
    ) -> dict[str, object]:
        return self._read_json(
            resident_poller_directory(
                self.paths, site_name, run_id, controller_id
            )
            / "status.json"
        )

    def list_statuses(
        self,
        *,
        site_name: str,
        run_id: str,
    ) -> list[dict[str, object]]:
        site = SiteManager(self.paths).validate_site_name(site_name)
        statuses: dict[str, dict[str, object]] = {}
        root = self.paths.ac_mesh_link_root(site) / "resident"
        if root.is_dir():
            for status_path in root.glob("*/*/status.json"):
                row = self._read_json(status_path)
                if (
                    str(row.get("site_name") or "") == site
                    and str(row.get("run_id") or "") == str(run_id)
                ):
                    statuses[str(row.get("controller_id") or status_path)] = row
        with self._lock:
            keys = [
                key
                for key in self._active
                if key[0] == site and key[1] == str(run_id)
            ]
        for key in keys:
            row = self.read_status(
                site_name=site,
                run_id=run_id,
                controller_id=key[2],
            )
            statuses[key[2]] = row
        return list(statuses.values())

    async def stop(self) -> None:
        import asyncio

        await asyncio.to_thread(self.process_adapter.shutdown)

    def _active_snapshot(
        self, key: tuple[str, str, str]
    ) -> TaskSnapshot | None:
        site, _run_id, _controller_id = key
        task_id = self._active.get(key)
        if not task_id:
            return None
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None or snapshot.status in TERMINAL_TASK_STATES:
            self._active.pop(key, None)
            return None
        checker = getattr(self.process_adapter, "is_running", None)
        if callable(checker) and not checker(task_id):
            self._active.pop(key, None)
            return None
        return snapshot

    def _update_control(
        self,
        key: tuple[str, str, str],
        **values: object,
    ) -> None:
        path = (
            resident_poller_directory(self.paths, key[0], key[1], key[2])
            / "control.json"
        )
        payload = self._read_json(path)
        payload.update(values)
        payload["updated_at"] = self._now_iso()
        self._write_json_atomic(path, payload)

    def _complete(
        self,
        key: tuple[str, str, str],
        completion: LocalProcessCompletion,
    ) -> None:
        with self._lock:
            if self._active.get(key) == completion.job_id:
                self._active.pop(key, None)

    def _wait(self, task_id: str, timeout: float) -> bool:
        waiter = getattr(self.process_adapter, "wait", None)
        if callable(waiter):
            return bool(waiter(task_id, timeout=max(0.0, timeout)))
        snapshot = self.task_service.repository().get(task_id)
        return snapshot is None or snapshot.status in TERMINAL_TASK_STATES

    def _force_stop(self, task_id: str) -> bool:
        stopper = getattr(self.process_adapter, "force_stop_job", None)
        return bool(
            stopper(task_id, timeout_seconds=1.0)
            if callable(stopper)
            else False
        )

    @staticmethod
    def _poll_session_id(site: str, run_id: str, controller_id: str) -> str:
        digest = hashlib.sha256(
            f"{site}\0{run_id}\0{controller_id}".encode("utf-8")
        ).hexdigest()[:24]
        return f"acpoll_{digest}"

    @staticmethod
    def _interval(value: object) -> float:
        try:
            return max(0.05, float(value))
        except (TypeError, ValueError):
            return 10.0

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt >= 5:
                    raise
                time.sleep(0.01)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="milliseconds")


class AcMeshLinkResidentPollingWorkerService:
    """在单个受控 Worker 内维持一台 AC 的连接、轮询和重连生命周期。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        connection_factory: ConnectionFactory = NetmikoShellConnection,
        monotonic_provider: Callable[[], float] = time.monotonic,
        now_provider: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        sleep_provider: Callable[[float], None] = time.sleep,
        backoff_seconds: tuple[float, ...] = _DEFAULT_BACKOFF_SECONDS,
        jitter_ratio: float = 0.1,
        wait_slice_seconds: float = 0.25,
    ) -> None:
        self.paths = paths
        self.connection_factory = connection_factory
        self.monotonic_provider = monotonic_provider
        self.now_provider = now_provider
        self.sleep_provider = sleep_provider
        self.backoff_seconds = tuple(
            max(0.0, float(value)) for value in backoff_seconds
        ) or (0.0,)
        self.jitter_ratio = max(0.0, min(float(jitter_ratio), 0.5))
        self.wait_slice_seconds = max(0.01, min(float(wait_slice_seconds), 0.5))
        self.collector = AcMeshLinkSnapshotCollector(
            paths, now_provider=now_provider
        )

    def execute(self, context: JobContext) -> dict[str, object]:
        params = dict(context.params)
        site = SiteManager(self.paths).validate_site_name(
            str(params.get("site_name") or "")
        )
        run_id = str(params.get("run_id") or "")
        controller_id = str(params.get("controller_id") or "")
        controller_name = str(params.get("controller_name") or controller_id)
        poll_session_id = str(params.get("poll_session_id") or "")
        runtime_dir = resident_poller_directory(
            self.paths, site, run_id, controller_id
        )
        control_path = runtime_dir / "control.json"
        status_path = runtime_dir / "status.json"
        state: dict[str, object] = {
            "schema_version": 1,
            "task_id": context.job_id,
            "task_mode": "resident",
            "progress_mode": "indeterminate",
            "site_name": site,
            "run_id": run_id,
            "poll_session_id": poll_session_id,
            "controller_id": controller_id,
            "controller_name": controller_name,
            "connection_state": "CONNECTING",
            "connected_at": "",
            "connection_method": "",
            "last_poll_started_at": "",
            "last_poll_completed_at": "",
            "last_success_at": "",
            "next_poll_at": "",
            "poll_interval_seconds": self._interval(
                params.get("poll_interval_seconds")
            ),
            "poll_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "reconnect_count": 0,
            "consecutive_failures": 0,
            "latest_snapshot_id": None,
            "latest_snapshot_record_count": 0,
            "last_error_code": "",
            "last_error_message": "",
            "heartbeat_at": self._now_iso(),
            "completed_request_id": "",
            "poll_overrun": False,
        }
        connection: MeshLinkConnection | None = None
        next_due = self.monotonic_provider()
        last_scheduled = next_due
        last_interval = float(state["poll_interval_seconds"])
        backoff_index = 0
        ever_connected = False
        stopped_normally = False
        self._publish(context, status_path, state, "正在连接 AC")
        try:
            while True:
                context.check_cancelled()
                control = self._read_json(control_path)
                if bool(control.get("stop_requested")):
                    stopped_normally = True
                    state["connection_state"] = "STOPPING"
                    self._publish(
                        context,
                        status_path,
                        state,
                        "无人值守运行结束，正在关闭 AC 常驻会话",
                    )
                    break
                interval = self._interval(
                    control.get(
                        "poll_interval_seconds",
                        state["poll_interval_seconds"],
                    )
                )
                state["poll_interval_seconds"] = interval
                if interval != last_interval:
                    next_due = last_scheduled + interval
                    last_interval = interval
                immediate_request_id = str(
                    control.get("immediate_request_id") or ""
                )
                immediate_due = bool(
                    immediate_request_id
                    and immediate_request_id
                    != str(state.get("completed_request_id") or "")
                )

                if connection is None:
                    reconnecting = ever_connected or int(
                        state["reconnect_count"]
                    ) > 0
                    state["connection_state"] = (
                        "RECONNECTING" if reconnecting else "CONNECTING"
                    )
                    self._publish(
                        context,
                        status_path,
                        state,
                        "SSH 会话中断，正在重连"
                        if reconnecting
                        else "正在连接 AC",
                    )
                    try:
                        controller = load_mesh_link_controller(
                            self.paths,
                            site,
                            controller_id,
                            require_credentials=True,
                        )
                        config = AcMeshLinkRefreshWorkerService._connection_config(
                            site, controller
                        )
                        connection = self.connection_factory(config)
                        connection.send_command(
                            MESH_LINK_REFRESH_COMMANDS[0],
                            config.command_timeout,
                        )
                    except AcMeshLinkRefreshError:
                        state["connection_state"] = "FAILED"
                        state["last_error_code"] = (
                            AcMeshLinkRefreshErrorCode.PROFILE_INVALID
                        )
                        state["last_error_message"] = (
                            "AC 配置或受控凭据不可用，常驻轮询已停止。"
                        )
                        self._publish(
                            context,
                            status_path,
                            state,
                            str(state["last_error_message"]),
                        )
                        raise
                    except Exception:
                        connection = self._close(connection)
                        state["failure_count"] = int(
                            state["failure_count"]
                        ) + 1
                        state["consecutive_failures"] = int(
                            state["consecutive_failures"]
                        ) + 1
                        state["last_error_code"] = (
                            AcMeshLinkRefreshErrorCode.CONNECT_FAILED
                        )
                        state["last_error_message"] = (
                            "连接 AC 失败，正在按退避策略重连。"
                        )
                        state["reconnect_count"] = int(
                            state["reconnect_count"]
                        ) + 1
                        delay = self._backoff(backoff_index)
                        backoff_index += 1
                        state["connection_state"] = "BACKOFF"
                        state["next_poll_at"] = self._future_iso(delay)
                        self._publish(
                            context,
                            status_path,
                            state,
                            (
                                "SSH 会话连接失败，"
                                f"{delay:.1f} 秒后重连"
                            ),
                        )
                        if self._interruptible_wait(
                            context, control_path, status_path, state, delay
                        ):
                            stopped_normally = True
                            break
                        continue
                    ever_connected = True
                    backoff_index = 0
                    state["connection_state"] = "CONNECTED"
                    state["connected_at"] = self._now_iso()
                    state["connection_method"] = str(
                        getattr(config, "connection_method", "")
                        or getattr(config, "protocol", "")
                    )
                    state["last_error_code"] = ""
                    state["last_error_message"] = ""
                    next_due = self.monotonic_provider()
                    last_scheduled = next_due
                    self._publish(
                        context,
                        status_path,
                        state,
                        "AC 连接成功",
                    )

                if not self._connection_alive(connection):
                    connection = self._close(connection)
                    state["reconnect_count"] = int(
                        state["reconnect_count"]
                    ) + 1
                    state["connection_state"] = "RECONNECTING"
                    state["last_error_code"] = (
                        AcMeshLinkRefreshErrorCode.CONNECT_FAILED
                    )
                    state["last_error_message"] = "SSH channel 已关闭。"
                    self._publish(
                        context,
                        status_path,
                        state,
                        "SSH 会话中断，正在重连",
                    )
                    continue

                now_monotonic = self.monotonic_provider()
                if immediate_due or now_monotonic >= next_due:
                    scheduled_poll = now_monotonic >= next_due
                    state["connection_state"] = "POLLING"
                    state["poll_count"] = int(state["poll_count"]) + 1
                    poll_number = int(state["poll_count"])
                    state["last_poll_started_at"] = self._now_iso()
                    state["next_poll_at"] = ""
                    self._publish(
                        context,
                        status_path,
                        state,
                        "正在获取 Mesh-Link",
                    )
                    try:
                        result = self.collector.collect(
                            context,
                            site=site,
                            controller=controller,
                            connection=connection,
                            command_timeout=config.command_timeout,
                            include_switch_history=bool(
                                control.get(
                                    "include_switch_history",
                                    params.get("include_switch_history"),
                                )
                            ),
                            artifact_key=(
                                f"{context.job_id}-poll-{poll_number}"
                            ),
                            source_type=MESH_LINK_RESIDENT_SOURCE_TYPE,
                        )
                    except AcMeshLinkConnectionError as exc:
                        state["failure_count"] = int(
                            state["failure_count"]
                        ) + 1
                        state["consecutive_failures"] = int(
                            state["consecutive_failures"]
                        ) + 1
                        state["last_error_code"] = exc.code
                        state["last_error_message"] = exc.message
                        state["last_poll_completed_at"] = self._now_iso()
                        state["reconnect_count"] = int(
                            state["reconnect_count"]
                        ) + 1
                        state["connection_state"] = "RECONNECTING"
                        connection = self._close(connection)
                        self._publish(
                            context,
                            status_path,
                            state,
                            (
                                "SSH 会话中断，正在重连"
                                f"（第 {state['reconnect_count']} 次）"
                            ),
                        )
                        continue
                    except AcMeshLinkRefreshError as exc:
                        state["failure_count"] = int(
                            state["failure_count"]
                        ) + 1
                        state["consecutive_failures"] = int(
                            state["consecutive_failures"]
                        ) + 1
                        state["last_error_code"] = exc.code
                        state["last_error_message"] = exc.message
                        state["last_poll_completed_at"] = self._now_iso()
                    else:
                        state["success_count"] = int(
                            state["success_count"]
                        ) + 1
                        state["consecutive_failures"] = 0
                        state["last_error_code"] = ""
                        state["last_error_message"] = ""
                        state["last_success_at"] = self._now_iso()
                        state["last_poll_completed_at"] = (
                            state["last_success_at"]
                        )
                        state["latest_snapshot_id"] = result.get(
                            "snapshot_id"
                        )
                        state["latest_snapshot_record_count"] = int(
                            result.get("records_count") or 0
                        )
                    control_after = self._read_json(control_path)
                    request_after = str(
                        control_after.get("immediate_request_id") or ""
                    )
                    if (
                        immediate_request_id
                        and request_after == immediate_request_id
                    ):
                        state["completed_request_id"] = immediate_request_id
                    finished = self.monotonic_provider()
                    if scheduled_poll:
                        last_scheduled = next_due
                        next_due += interval
                    overrun = next_due <= finished
                    state["poll_overrun"] = overrun
                    if overrun:
                        next_due = finished
                    delay = max(0.0, next_due - finished)
                    state["next_poll_at"] = self._future_iso(delay)
                    state["connection_state"] = "WAITING"
                    message = (
                        f"连接正常，下一轮 {max(0, round(delay))} 秒后"
                        if not state["last_error_message"]
                        else "本轮采集失败，连接仍可用，将在下一轮继续"
                    )
                    self._publish(
                        context, status_path, state, message
                    )
                    continue

                delay = max(0.0, next_due - now_monotonic)
                state["connection_state"] = "WAITING"
                state["next_poll_at"] = self._future_iso(delay)
                if self._interruptible_wait(
                    context,
                    control_path,
                    status_path,
                    state,
                    min(delay, self.wait_slice_seconds),
                ):
                    stopped_normally = True
                    break
        except BackgroundTaskCancelled:
            state["connection_state"] = "STOPPING"
            state["last_error_code"] = AcMeshLinkRefreshErrorCode.CANCELLED
            state["last_error_message"] = "用户取消常驻轮询。"
            self._publish(
                context,
                status_path,
                state,
                "用户取消常驻 AC 轮询",
            )
            raise
        except AcMeshLinkRefreshError as exc:
            state["connection_state"] = "FAILED"
            state["last_error_code"] = exc.code
            state["last_error_message"] = exc.message
            self._publish(
                context, status_path, state, exc.message
            )
            raise RuntimeError(str(exc)) from None
        finally:
            connection = self._close(connection)
            if stopped_normally:
                state["connection_state"] = "STOPPED"
                state["next_poll_at"] = ""
                state["last_error_code"] = ""
                state["last_error_message"] = ""
                self._publish(
                    context,
                    status_path,
                    state,
                    "无人值守运行结束，AC 常驻轮询已正常停止",
                )
        return {
            **state,
            "completion_message": (
                "无人值守运行结束，AC 常驻轮询已正常停止"
            ),
        }

    def _interruptible_wait(
        self,
        context: JobContext,
        control_path: Path,
        status_path: Path,
        state: dict[str, object],
        seconds: float,
    ) -> bool:
        deadline = self.monotonic_provider() + max(0.0, float(seconds))
        while self.monotonic_provider() < deadline:
            context.check_cancelled()
            control = self._read_json(control_path)
            if bool(control.get("stop_requested")):
                state["connection_state"] = "STOPPING"
                self._publish(
                    context,
                    status_path,
                    state,
                    "无人值守运行结束，正在关闭 AC 常驻会话",
                )
                return True
            request_id = str(control.get("immediate_request_id") or "")
            if (
                request_id
                and request_id
                != str(state.get("completed_request_id") or "")
            ):
                return False
            remaining = deadline - self.monotonic_provider()
            if remaining <= 0:
                break
            self.sleep_provider(
                min(self.wait_slice_seconds, max(0.0, remaining))
            )
            state["heartbeat_at"] = self._now_iso()
            self._write_json_atomic(status_path, state)
        return False

    def _publish(
        self,
        context: JobContext,
        status_path: Path,
        state: dict[str, object],
        message: str,
    ) -> None:
        state["heartbeat_at"] = self._now_iso()
        self._write_json_atomic(status_path, state)
        context.structured_progress(
            str(state.get("connection_state") or "UNKNOWN").casefold(),
            int(state.get("poll_count") or 0),
            0,
            message,
            **{
                key: value
                for key, value in state.items()
                if key not in {"schema_version"}
            },
        )

    def _backoff(self, index: int) -> float:
        base = self.backoff_seconds[min(index, len(self.backoff_seconds) - 1)]
        if not base or not self.jitter_ratio:
            return base
        return max(
            0.0,
            base
            + random.uniform(
                -base * self.jitter_ratio, base * self.jitter_ratio
            ),
        )

    @staticmethod
    def _connection_alive(connection: MeshLinkConnection | None) -> bool:
        if connection is None:
            return False
        checker = getattr(connection, "is_alive", None)
        if not callable(checker):
            return True
        try:
            value = checker()
        except Exception:
            return False
        if isinstance(value, dict):
            return bool(value.get("is_alive"))
        return bool(value)

    @staticmethod
    def _close(
        connection: MeshLinkConnection | None,
    ) -> None:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        return None

    @staticmethod
    def _interval(value: object) -> float:
        return AcMeshLinkResidentPollingApplicationService._interval(value)

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        return AcMeshLinkResidentPollingApplicationService._read_json(path)

    @staticmethod
    def _write_json_atomic(
        path: Path, payload: dict[str, object]
    ) -> None:
        AcMeshLinkResidentPollingApplicationService._write_json_atomic(
            path, payload
        )

    def _now_iso(self) -> str:
        return self.now_provider().isoformat(timespec="milliseconds")

    def _future_iso(self, seconds: float) -> str:
        return (
            self.now_provider() + timedelta(seconds=max(0.0, seconds))
        ).isoformat(timespec="milliseconds")


def run_ac_mesh_link_resident_poll(
    context: JobContext,
) -> dict[str, object]:
    return AcMeshLinkResidentPollingWorkerService(context.paths).execute(
        context
    )


__all__ = [
    "AcMeshLinkResidentPollerStart",
    "AcMeshLinkResidentPollingApplicationService",
    "AcMeshLinkResidentPollingWorkerService",
    "AcMeshLinkResidentRefreshRequest",
    "AcMeshLinkResidentStopResult",
    "MESH_LINK_RESIDENT_OWNER",
    "MESH_LINK_RESIDENT_SOURCE_TYPE",
    "MESH_LINK_RESIDENT_TASK_TYPE",
    "RESIDENT_CONNECTION_STATES",
    "resident_poller_directory",
    "run_ac_mesh_link_resident_poll",
]
