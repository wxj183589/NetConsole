from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from netconsole.models.online_mr_agent import (
    OnlineMrAgentStartRequest,
    OnlineMrAgentStatus,
    OnlineMrAgentTaskStatusResponse,
    map_online_mr_agent_status,
)
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
    OnlineMrTaskSessionMapping,
    calculate_duration_minutes,
)
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.agent_controller_service import (
    OnlineMrAgentControllerService,
)
from netconsole.services.online_mr.agent_http_client import OnlineMrAgentClientError
from netconsole.services.online_mr.errors import (
    OnlineMrApplicationError,
    OnlineMrApplicationErrorCode,
)


RepositoryFactory = Callable[[str], OnlineMrTaskSessionRepository]
SiteIds = Callable[[], list[str]]
DeviceIdentityValidator = Callable[[OnlineMrStartRequest], bool]


@dataclass(frozen=True)
class OnlineMrAgentExecutorSettings:
    enabled: bool = False
    poll_interval_seconds: float = 3.0
    status_failure_threshold: int = 3

    @classmethod
    def from_environment(cls) -> OnlineMrAgentExecutorSettings:
        return cls(
            enabled=os.environ.get("ONLINE_MR_AGENT_EXECUTOR_ENABLED", "0").strip() == "1",
            poll_interval_seconds=max(
                0.2,
                float(os.environ.get("ONLINE_MR_AGENT_POLL_INTERVAL_SECONDS", "3")),
            ),
            status_failure_threshold=max(
                1,
                int(os.environ.get("ONLINE_MR_AGENT_STATUS_FAILURE_THRESHOLD", "3")),
            ),
        )


class OnlineMrAgentExecutor:
    """单 Agent、单 MR 的远端执行与采集包收敛器。"""

    def __init__(
        self,
        controller: OnlineMrAgentControllerService,
        task_service: TaskApplicationService,
        repository_factory: RepositoryFactory,
        site_ids: SiteIds,
        device_identity_validator: DeviceIdentityValidator,
        *,
        settings: OnlineMrAgentExecutorSettings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.controller = controller
        self.task_service = task_service
        self.repository = repository_factory
        self.site_ids = site_ids
        self.device_identity_validator = device_identity_validator
        self.settings = settings or OnlineMrAgentExecutorSettings.from_environment()
        self.clock = clock or (lambda: datetime.now(UTC))
        self._monitored: set[tuple[str, str]] = set()
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, request: OnlineMrStartRequest) -> OnlineMrTaskSessionMapping:
        self._require_enabled()
        if request.executor_kind is not OnlineMrExecutorKind.AGENT or not request.agent_id:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.INVALID_START_REQUEST,
                "Agent 执行必须指定一个 Agent Profile",
            )
        if not self.device_identity_validator(request):
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.INVALID_START_REQUEST,
                "Online MR 启动配置与当前局点设备静态身份不一致",
            )
        self._ensure_no_active_operation(request.site_id, request.device_id)

        profile_id = request.agent_id
        try:
            asyncio.run(self.controller.ping_agent(profile_id))
            agent_status = asyncio.run(self.controller.get_agent_status(profile_id))
            self._check_version(agent_status.version)
            tools = asyncio.run(self.controller.get_agent_tools(profile_id))
            if not tools.mr_collector.ready:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_MR_COLLECTOR_MISSING,
                    "Agent MR 采集器不可用",
                )
            if request.config.fping.normalized().enabled and not tools.fping.ready:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_TOOL_MISSING,
                    "Agent fping 不可用",
                )
            if request.config.iperf.normalized().enabled and not tools.iperf3.ready:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_TOOL_MISSING,
                    "Agent iPerf3 不可用",
                )
            agent_request = OnlineMrAgentStartRequest.from_application_request(request).model_copy(
                update={"agent_id": agent_status.agent_id}
            )
            remote = asyncio.run(self.controller.start_collection(profile_id, agent_request))
        except OnlineMrApplicationError:
            raise
        except OnlineMrAgentClientError as exc:
            preflight_codes = {
                code.value
                for code in (
                    OnlineMrApplicationErrorCode.AGENT_UNREACHABLE,
                    OnlineMrApplicationErrorCode.AGENT_AUTH_FAILED,
                    OnlineMrApplicationErrorCode.AGENT_VERSION_UNSUPPORTED,
                    OnlineMrApplicationErrorCode.AGENT_TOOL_MISSING,
                    OnlineMrApplicationErrorCode.AGENT_MR_COLLECTOR_MISSING,
                    OnlineMrApplicationErrorCode.AGENT_TIMEOUT,
                )
            }
            code = exc.code if exc.code in preflight_codes else OnlineMrApplicationErrorCode.AGENT_START_FAILED.value
            raise OnlineMrApplicationError(code, exc.message) from exc
        except Exception as exc:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_START_FAILED,
                self._safe_error(exc, request.config.password),
            ) from exc

        now = self._now_iso()
        task_id = f"online_mr_agent_{uuid.uuid4().hex}"
        deadline = self._deadline(now, request.config.duration_minutes)
        state = map_online_mr_agent_status(remote.status)
        mapping = OnlineMrTaskSessionMapping(
            controller_task_id=task_id,
            site_id=request.site_id,
            device_id=str(request.device_id),
            device_name=request.device_name,
            mr_id=request.config.mr_id,
            mr_name=request.mr_name,
            executor_kind=OnlineMrExecutorKind.AGENT,
            agent_id=agent_status.agent_id,
            agent_profile_id=profile_id,
            agent_task_id=remote.task_id,
            remote_package_id=remote.package_id,
            last_remote_status=remote.status.value,
            last_remote_seen_at=now,
            deadline_at=deadline,
            phase=state.phase,
            mapping_state=state.mapping_state,
            created_at=now,
            updated_at=now,
            started_at=remote.start_time or now,
        )
        repository = self.repository(request.site_id)
        try:
            self.task_service.create_external_task(
                task_id=task_id,
                task_type="online_mr_collection_start",
                task_name=f"Online MR - {request.device_name}",
                source="agent",
                site_name=request.site_id,
                owner=request.owner,
                agent=agent_status.agent_id,
                device=request.device_name,
            )
            repository.create(mapping)
            self._record_state(mapping, state.task_state, "Agent Online MR 已启动")
        except (sqlite3.Error, OSError, ValueError, KeyError) as exc:
            try:
                asyncio.run(self.controller.stop_collection(profile_id, remote.task_id))
            except Exception:
                pass
            if self.task_service.repository(request.site_id).get(task_id) is not None:
                self.task_service.record_external_event(
                    task_id,
                    "error",
                    {"error": "Controller 任务映射创建失败，已请求 Agent 正常停止"},
                    source="agent_executor",
                    site_name=request.site_id,
                )
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.MAPPING_CONFLICT,
                "Agent 已启动但 Controller 任务映射创建失败，已请求正常停止",
            ) from exc
        self.monitor(mapping)
        return repository.get_by_task(task_id) or mapping

    def stop(
        self, mapping: OnlineMrTaskSessionMapping, *, stop_reason: str
    ) -> OnlineMrTaskSessionMapping:
        self._require_enabled()
        if mapping.mapping_state is OnlineMrMappingState.TERMINAL:
            return mapping
        if not mapping.agent_profile_id or not mapping.agent_task_id:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_STOP_FAILED,
                "Agent Task 映射不完整",
            )
        repository = self.repository(mapping.site_id)
        current = repository.get_by_task(mapping.controller_task_id) or mapping
        now = self._now_iso()
        current = repository.save(
            replace(
                current,
                phase=OnlineMrPhase.STOPPING_COLLECTION,
                stop_reason=stop_reason or current.stop_reason or "user_stop",
                updated_at=now,
            )
        )
        self._record_state(current, TaskState.STOPPING, "正在停止 Agent Online MR")
        try:
            remote = asyncio.run(
                self.controller.stop_collection(current.agent_profile_id, current.agent_task_id)
            )
        except OnlineMrAgentClientError as exc:
            if exc.code != str(OnlineMrApplicationErrorCode.AGENT_TASK_NOT_FOUND):
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_STOP_FAILED, exc.message
                ) from exc
            return self._terminal_failure(current, exc.code, exc.message)
        self._apply_remote(current, remote)
        self.monitor(current)
        return repository.get_by_task(current.controller_task_id) or current

    def sync_once(self, mapping: OnlineMrTaskSessionMapping) -> OnlineMrTaskSessionMapping:
        repository = self.repository(mapping.site_id)
        current = repository.get_by_task(mapping.controller_task_id) or mapping
        if current.mapping_state is OnlineMrMappingState.TERMINAL:
            self._unmonitor(current)
            return current
        if self._deadline_due(current) and current.last_remote_status not in {
            OnlineMrAgentStatus.STOPPING.value,
        }:
            return self.stop(current, stop_reason="duration_reached")
        try:
            remote = asyncio.run(
                self.controller.get_task(current.agent_profile_id, current.agent_task_id)
            )
        except OnlineMrAgentClientError as exc:
            if exc.code == str(OnlineMrApplicationErrorCode.AGENT_TASK_NOT_FOUND):
                return self._terminal_failure(current, exc.code, exc.message)
            return self._status_failure(current, exc.code, exc.message)
        except Exception as exc:
            return self._status_failure(
                current,
                OnlineMrApplicationErrorCode.AGENT_STATUS_FAILED.value,
                self._safe_error(exc),
            )
        return self._apply_remote(current, remote)

    def recover(self, site_id: str | None = None) -> list[OnlineMrTaskSessionMapping]:
        self._require_enabled()
        recovered: list[OnlineMrTaskSessionMapping] = []
        for selected_site in ([site_id] if site_id else self.site_ids()):
            for mapping in self.repository(selected_site).list_active(limit=1000):
                if mapping.executor_kind is not OnlineMrExecutorKind.AGENT:
                    continue
                if not mapping.agent_profile_id or not mapping.agent_task_id:
                    recovered.append(
                        self._terminal_failure(
                            mapping,
                            OnlineMrApplicationErrorCode.AGENT_STATUS_FAILED.value,
                            "Agent Task 恢复映射不完整",
                        )
                    )
                    continue
                recovered.append(self.sync_once(mapping))
                current = self.repository(selected_site).get_by_task(mapping.controller_task_id)
                if current is not None and current.mapping_state is not OnlineMrMappingState.TERMINAL:
                    self.monitor(current)
        return recovered

    def monitor(self, mapping: OnlineMrTaskSessionMapping) -> None:
        with self._lock:
            self._monitored.add((mapping.site_id, mapping.controller_task_id))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._poll_loop,
                    name="online-mr-agent-supervisor",
                    daemon=True,
                )
                self._thread.start()

    def close(self) -> None:
        self._closed.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=min(2.0, self.settings.poll_interval_seconds + 0.2))

    def _poll_loop(self) -> None:
        while not self._closed.wait(self.settings.poll_interval_seconds):
            with self._lock:
                selected = tuple(self._monitored)
            for site_id, task_id in selected:
                mapping = self.repository(site_id).get_by_task(task_id)
                if mapping is None or mapping.mapping_state is OnlineMrMappingState.TERMINAL:
                    if mapping is not None:
                        self._unmonitor(mapping)
                    continue
                try:
                    self.sync_once(mapping)
                except Exception:
                    continue

    def _apply_remote(
        self,
        mapping: OnlineMrTaskSessionMapping,
        remote: OnlineMrAgentTaskStatusResponse,
    ) -> OnlineMrTaskSessionMapping:
        if remote.task_id != mapping.agent_task_id:
            return self._terminal_failure(
                mapping,
                OnlineMrApplicationErrorCode.AGENT_STATUS_FAILED.value,
                "Agent 返回了错误的 Task ID",
            )
        state = map_online_mr_agent_status(remote.status)
        now = self._now_iso()
        repository = self.repository(mapping.site_id)
        current = repository.get_by_task(mapping.controller_task_id) or mapping
        if current.mapping_state is OnlineMrMappingState.TERMINAL:
            return current
        pending_import = state.remote_terminal
        updated = repository.save(
            replace(
                current,
                phase=OnlineMrPhase.FINALIZING if pending_import else state.phase,
                mapping_state=OnlineMrMappingState.LINKED if pending_import else state.mapping_state,
                updated_at=now,
                started_at=remote.start_time or current.started_at,
                remote_session_id=self._remote_session(remote) or current.remote_session_id,
                remote_package_id=remote.package_id or current.remote_package_id,
                last_remote_status=remote.status.value,
                last_remote_seen_at=now,
                consecutive_status_failures=(
                    current.consecutive_status_failures if pending_import else 0
                ),
                error_code="",
                error_message="",
            )
        )
        self._record_state(
            updated,
            TaskState.RUNNING if pending_import else state.task_state,
            "Agent Online MR 已结束，正在导入采集包"
            if pending_import
            else self._state_message(state.task_state),
        )
        if not state.remote_terminal:
            return updated
        package_id = remote.package_id or updated.remote_package_id
        remote_session_id = updated.remote_session_id
        if not package_id or not remote_session_id:
            discovered_package, discovered_session = self._find_package(updated)
            package_id = package_id or discovered_package
            remote_session_id = remote_session_id or discovered_session
        if not package_id:
            waiting = self._status_failure(
                updated,
                OnlineMrApplicationErrorCode.AGENT_PACKAGE_NOT_READY.value,
                "Agent 任务已结束，但采集包尚未就绪",
            )
            if waiting.consecutive_status_failures >= self.settings.status_failure_threshold:
                return self._terminal_failure(
                    waiting,
                    OnlineMrApplicationErrorCode.AGENT_PACKAGE_NOT_READY.value,
                    "Agent 任务已结束，但采集包在限定重试后仍未就绪",
                )
            return waiting
        updated = repository.save(
            replace(
                updated,
                phase=OnlineMrPhase.FINALIZING,
                remote_package_id=package_id,
                remote_session_id=remote_session_id,
                updated_at=self._now_iso(),
            )
        )
        try:
            result = asyncio.run(
                self.controller.download_import_package(
                    package_id,
                    site_id=updated.site_id,
                    site_name=updated.site_id,
                    profile_id=updated.agent_profile_id,
                    device_id=updated.device_id,
                    device_name=updated.device_name,
                    mr_id=updated.mr_id,
                    mr_name=updated.mr_name,
                    owner="agent_executor",
                    expected_session_id=updated.remote_session_id or None,
                    controller_task_id=updated.controller_task_id,
                    agent_task_id=updated.agent_task_id,
                    agent_id=updated.agent_id,
                    expected_host=self._remote_host(remote),
                    source_package_id=package_id,
                )
            )
        except Exception as exc:
            return self._terminal_failure(
                updated,
                OnlineMrApplicationErrorCode.AGENT_IMPORT_FAILED.value,
                self._safe_error(exc),
            )
        if not result.success:
            code = result.error_code or OnlineMrApplicationErrorCode.AGENT_IMPORT_FAILED.value
            message = "；".join(result.errors or result.warnings) or "Agent 采集包导入失败"
            if code == str(OnlineMrApplicationErrorCode.AGENT_PACKAGE_NOT_READY):
                return self._status_failure(updated, code, message)
            return self._terminal_failure(updated, code, message)
        final = repository.get_by_task(updated.controller_task_id) or updated
        final_updates: dict[str, object] = {}
        if result.session_id and not final.remote_session_id:
            final_updates["remote_session_id"] = result.session_id
        if updated.stop_reason and final.stop_reason != updated.stop_reason:
            final_updates["stop_reason"] = updated.stop_reason
        if final_updates:
            final = repository.save(replace(final, **final_updates))
        self._unmonitor(final)
        return final

    def _find_package(self, mapping: OnlineMrTaskSessionMapping) -> tuple[str, str]:
        try:
            packages = asyncio.run(
                self.controller.list_agent_packages(mapping.agent_profile_id)
            )
        except Exception:
            return "", ""
        for package in packages:
            if package.task_id == mapping.agent_task_id:
                return package.package_id, package.session_id
        return "", ""

    def _status_failure(
        self, mapping: OnlineMrTaskSessionMapping, code: str, message: str
    ) -> OnlineMrTaskSessionMapping:
        repository = self.repository(mapping.site_id)
        current = repository.get_by_task(mapping.controller_task_id) or mapping
        if current.mapping_state is OnlineMrMappingState.TERMINAL:
            return current
        failures = current.consecutive_status_failures + 1
        selected_code = (
            OnlineMrApplicationErrorCode.AGENT_REMOTE_STATUS_UNKNOWN.value
            if failures >= self.settings.status_failure_threshold
            else str(code)
        )
        return repository.save(
            replace(
                current,
                updated_at=self._now_iso(),
                consecutive_status_failures=failures,
                error_code=selected_code,
                error_message=message,
                error_summary=message if failures >= self.settings.status_failure_threshold else current.error_summary,
            )
        )

    def _terminal_failure(
        self, mapping: OnlineMrTaskSessionMapping, code: str, message: str
    ) -> OnlineMrTaskSessionMapping:
        repository = self.repository(mapping.site_id)
        current = repository.get_by_task(mapping.controller_task_id) or mapping
        if current.mapping_state is OnlineMrMappingState.TERMINAL:
            return current
        now = self._now_iso()
        updated = repository.save(
            replace(
                current,
                phase=OnlineMrPhase.TERMINAL,
                mapping_state=OnlineMrMappingState.TERMINAL,
                updated_at=now,
                terminal_at=now,
                ended_at=now,
                duration_minutes=calculate_duration_minutes(
                    current.started_at or current.created_at, now
                ),
                error_code=str(code),
                error_summary=message,
                error_message=message,
            )
        )
        if self.task_service.repository(updated.site_id).get(updated.controller_task_id) is None:
            self.task_service.create_external_task(
                task_id=updated.controller_task_id,
                task_type="online_mr_collection_start",
                task_name=f"Online MR - {updated.device_name}",
                source="agent",
                site_name=updated.site_id,
                owner="agent_recovery",
                agent=updated.agent_id,
                device=updated.device_name,
            )
        self.task_service.record_external_event(
            updated.controller_task_id,
            "error",
            {"error": message, "stage": OnlineMrPhase.TERMINAL.value},
            source="agent_executor",
            site_name=updated.site_id,
        )
        self._unmonitor(updated)
        return updated

    def _record_state(
        self, mapping: OnlineMrTaskSessionMapping, state: TaskState, message: str
    ) -> None:
        current = self.task_service.repository(mapping.site_id).get(mapping.controller_task_id)
        if current is None or current.status is state or current.status in TERMINAL_TASK_STATES:
            return
        self.task_service.record_external_event(
            mapping.controller_task_id,
            "state",
            {"state": state.value, "stage": mapping.phase.value, "message": message},
            source="agent_executor",
            site_name=mapping.site_id,
        )

    def _ensure_no_active_operation(self, site_id: str, device_id: str | int) -> None:
        for selected_site in self.site_ids():
            for mapping in self.repository(selected_site).list_active(limit=1000):
                if mapping.executor_kind is OnlineMrExecutorKind.AGENT or (
                    selected_site == site_id and mapping.device_id == str(device_id)
                ):
                    raise OnlineMrApplicationError(
                        OnlineMrApplicationErrorCode.MAPPING_CONFLICT,
                        "当前已有 Online MR 采集任务，单 Agent 执行器不允许并发",
                    )

    def _require_enabled(self) -> None:
        if not self.settings.enabled:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_EXECUTOR_DISABLED,
                "Online MR Agent 执行器未启用",
            )

    @staticmethod
    def _check_version(version: str) -> None:
        value = str(version or "").strip().lower().lstrip("v")
        parts = value.split("-", 1)[0].split(".")
        try:
            major, minor = int(parts[0]), int(parts[1])
        except (IndexError, ValueError) as exc:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_VERSION_UNSUPPORTED,
                "Agent 版本格式不受支持",
            ) from exc
        if major < 1 and (major, minor) < (0, 2):
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_VERSION_UNSUPPORTED,
                "Agent 版本不支持 Online MR 远端执行",
            )

    @staticmethod
    def _deadline(started_at: str, duration_minutes: int | None) -> str | None:
        if not duration_minutes:
            return None
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (started + timedelta(minutes=duration_minutes)).isoformat()

    def _deadline_due(self, mapping: OnlineMrTaskSessionMapping) -> bool:
        if not mapping.deadline_at:
            return False
        try:
            deadline = datetime.fromisoformat(mapping.deadline_at.replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            return self._now() >= deadline
        except ValueError:
            return False

    def _now(self) -> datetime:
        value = self.clock()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _now_iso(self) -> str:
        return self._now().isoformat(timespec="milliseconds")

    @staticmethod
    def _remote_host(remote: OnlineMrAgentTaskStatusResponse) -> str:
        target = remote.params.get("target")
        return str(target.get("host") or "") if isinstance(target, dict) else ""

    @staticmethod
    def _remote_session(remote: OnlineMrAgentTaskStatusResponse) -> str:
        session = remote.params.get("session")
        return str(session.get("session_id") or "") if isinstance(session, dict) else ""

    @staticmethod
    def _state_message(state: TaskState) -> str:
        return {
            TaskState.STARTING: "Agent Online MR 正在启动",
            TaskState.RUNNING: "Agent Online MR 正在采集",
            TaskState.STOPPING: "Agent Online MR 正在停止",
        }.get(state, "Agent Online MR 状态已更新")

    def _unmonitor(self, mapping: OnlineMrTaskSessionMapping) -> None:
        with self._lock:
            self._monitored.discard((mapping.site_id, mapping.controller_task_id))

    @staticmethod
    def _safe_error(exc: BaseException, *secrets: str) -> str:
        text = str(exc or exc.__class__.__name__).replace("\r", " ").replace("\n", " ")[:500]
        for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
            text = text.replace(secret, "<redacted>")
        return text


__all__ = ["OnlineMrAgentExecutor", "OnlineMrAgentExecutorSettings"]
