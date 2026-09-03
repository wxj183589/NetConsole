from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import OnlineMrOperationSnapshotDTO
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrStartRequest,
    OnlineMrTaskSessionMapping,
    calculate_duration_minutes,
)
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TERMINAL_TASK_STATES
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.online_mr_task_session_repository import OnlineMrTaskSessionRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.online_mr.collection_models import collection_config_to_payload
from netconsole.services.online_mr.errors import OnlineMrApplicationError, OnlineMrApplicationErrorCode
from netconsole.services.online_mr_session_store import OnlineMrSessionStore
from netconsole.services.device_scope import is_current_debug_device

if TYPE_CHECKING:
    from netconsole.services.agent.controller import AgentControllerService
    from netconsole.services.online_mr.agent_executor import OnlineMrAgentExecutor


DeviceValidator = Callable[[str, int | str], bool]
_ACTIVE_MAPPING_STATES = {OnlineMrMappingState.PENDING_SESSION, OnlineMrMappingState.LINKED}
_STALE_SESSION_STATES = {
    "CREATED",
    "PREPARING",
    "CONNECTING",
    "INITIALIZING",
    "STARTING",
    "RUNNING",
    "COLLECTING",
    "RECONNECTING",
    "STOPPING",
    "FINALIZING",
    "PARSING",
    "PACKAGING",
}
_STARTUP_PHASES = {
    OnlineMrPhase.VALIDATING,
    OnlineMrPhase.PREPARING_TASK,
    OnlineMrPhase.PREPARING_SESSION,
    OnlineMrPhase.CONNECTING,
    OnlineMrPhase.STARTING_COLLECTION,
}


class OnlineMrApplicationService:
    """Online MR LOCAL 生命周期与尚未启用的 Agent executor 分派边界。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_name: str = "demo",
        task_service: TaskApplicationService | None = None,
        process_adapter: LocalProcessAdapter | None = None,
        device_validator: DeviceValidator | None = None,
        agent_executor: OnlineMrAgentExecutor | None = None,
        agent_profile_controller: AgentControllerService | None = None,
    ) -> None:
        self.paths = paths
        self.site_name = str(site_name or "demo")
        self.task_service = task_service or TaskApplicationService(paths, site_name=self.site_name)
        self.process_adapter = process_adapter or LocalProcessAdapter(self.task_service)
        self.device_validator = device_validator or self._device_exists
        self._repositories: dict[str, OnlineMrTaskSessionRepository] = {}
        self._operation_sites: dict[str, str] = {}
        self._session_sites: dict[str, str] = {}
        self._mapping_index_lock = threading.RLock()
        self.agent_executor = agent_executor
        if self.agent_executor is None and os.environ.get("ONLINE_MR_AGENT_EXECUTOR_ENABLED", "0") == "1":
            from netconsole.services.agent.controller import AgentControllerService
            from netconsole.services.online_mr.agent_controller_service import OnlineMrAgentControllerService
            from netconsole.services.online_mr.agent_executor import OnlineMrAgentExecutor

            profiles = agent_profile_controller or AgentControllerService(paths=paths, site_name=self.site_name)
            self.agent_executor = OnlineMrAgentExecutor(
                OnlineMrAgentControllerService(paths, profile_controller=profiles),
                self.task_service,
                self.repository,
                self._site_ids,
                self._device_identity_matches,
            )
        task_events = getattr(self.task_service, "events", None)
        subscribe = getattr(task_events, "subscribe", None)
        self._unsubscribe = (
            subscribe(self.reconcile_task_event)
            if callable(subscribe)
            else lambda: None
        )

    def rebind_site(self, site_name: str) -> None:
        """切换当前局点并丢弃旧局点的惰性 Repository 缓存。"""

        self.site_name = str(site_name or "demo")
        self._repositories.clear()

    def prepare_start(self, request: OnlineMrStartRequest) -> OnlineMrStartRequest:
        site_id = self._safe_component(request.site_id)
        if not site_id or not self.paths.site_dir(site_id).is_dir():
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.SITE_NOT_FOUND, "Online MR 局点不存在")
        if request.executor_kind is OnlineMrExecutorKind.LOCAL and request.agent_id:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.INVALID_START_REQUEST, "本地执行不能指定 Agent")
        if request.executor_kind is OnlineMrExecutorKind.AGENT and not request.agent_id:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.INVALID_START_REQUEST, "Agent 执行必须指定 Agent Profile")
        if request.device_id in (None, "") or not request.device_name.strip() or not request.mr_name.strip():
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.INVALID_START_REQUEST, "Online MR 设备和 MR 信息不完整")
        if not self.device_validator(site_id, request.device_id):
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.DEVICE_NOT_FOUND, "Online MR 设备不存在")
        config = request.config
        if (
            config.site != site_id
            or str(config.device_id or "") != str(request.device_id)
            or config.device_name != request.device_name
            or config.mr_name != request.mr_name
        ):
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.INVALID_START_REQUEST, "Online MR 启动配置与任务归属不一致")
        active = self.repository(site_id).list_active(limit=1000)
        if any(mapping.device_id == str(request.device_id) for mapping in active):
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.MAPPING_CONFLICT,
                "当前设备已有 Online MR 采集任务",
            )
        return request

    def start_collection(self, request: OnlineMrStartRequest) -> OnlineMrOperationSnapshotDTO:
        """统一 LOCAL/AGENT executor 入口。"""
        request = self.prepare_start(request)
        if request.executor_kind is OnlineMrExecutorKind.LOCAL:
            return self.start_local_collection(request)
        if self.agent_executor is None:
            raise OnlineMrApplicationError(
                OnlineMrApplicationErrorCode.AGENT_EXECUTOR_DISABLED,
                "Online MR Agent 执行器未启用",
            )
        mapping = self.agent_executor.start(request)
        return self._to_operation(mapping)

    def start_local_collection(self, request: OnlineMrStartRequest) -> OnlineMrOperationSnapshotDTO:
        request = self.prepare_start(request)
        task_id = f"online_mr_collection_{uuid.uuid4().hex}"
        now = utc_now_iso()
        mapping = OnlineMrTaskSessionMapping(
            controller_task_id=task_id,
            site_id=request.site_id,
            device_id=str(request.device_id),
            device_name=request.device_name,
            mr_id=request.config.mr_id,
            mr_name=request.mr_name,
            executor_kind=request.executor_kind,
            agent_id=request.agent_id,
            phase=OnlineMrPhase.PREPARING_TASK,
            mapping_state=OnlineMrMappingState.PENDING_SESSION,
            created_at=now,
            updated_at=now,
        )
        repository = self.repository(request.site_id)
        try:
            repository.create(mapping)
            self._remember_mapping(mapping)
        except sqlite3.IntegrityError as exc:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.MAPPING_CONFLICT, "Online MR 任务映射冲突") from exc

        grace_ms = min(60_000, max(30_000, int(request.config.command_timeout or 15) * 1_000 + 5_000))
        params = {
            "site_name": request.site_id,
            "device": request.device_name,
            "device_id": str(request.device_id),
            "owner": request.owner,
            "task_name": f"Online MR - {request.device_name}",
            "task_source": "local",
            "config": collection_config_to_payload(request.config),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "package_on_stop": True,
            "manage_traffic": True,
            "_cancel_grace_ms": grace_ms,
        }
        try:
            self.process_adapter.start_job(
                BackgroundJob(job_id=task_id, task_type="online_mr_collection_start", params=params),
                on_complete=self._process_completed,
            )
        except Exception as exc:
            snapshot = self.task_service.repository(request.site_id).get(task_id)
            code = (
                OnlineMrApplicationErrorCode.TASK_SUBMIT_FAILED
                if snapshot is not None
                else OnlineMrApplicationErrorCode.TASK_CREATE_FAILED
            )
            failed = replace(
                repository.get_by_task(task_id) or mapping,
                phase=OnlineMrPhase.TERMINAL,
                mapping_state=OnlineMrMappingState.TASK_ONLY_FAILED,
                updated_at=utc_now_iso(),
                terminal_at=utc_now_iso(),
                ended_at=utc_now_iso(),
                duration_minutes=0.0,
                stop_reason="task_start_failed",
                error_code=code.value,
                error_summary=self._safe_error(exc, request.config.password),
                error_message=self._safe_error(exc, request.config.password),
            )
            repository.save(failed)
            raise OnlineMrApplicationError(code, "Online MR 本地采集任务启动失败") from exc

        current = repository.get_by_task(task_id) or mapping
        if current.phase is OnlineMrPhase.PREPARING_TASK:
            repository.save(replace(current, phase=OnlineMrPhase.PREPARING_SESSION, updated_at=utc_now_iso()))
        return self.get_operation(task_id, site_id=request.site_id)

    def get_operation(self, controller_task_id: str, *, site_id: str | None = None) -> OnlineMrOperationSnapshotDTO:
        mapping = self._find_by_task(controller_task_id, site_id=site_id)
        if mapping is None:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.OPERATION_NOT_FOUND, "Online MR 操作不存在")
        return self._to_operation(mapping)

    def get_operation_by_session(self, session_id: str, *, site_id: str | None = None) -> OnlineMrOperationSnapshotDTO:
        mapping = self._find_by_session(session_id, site_id=site_id)
        if mapping is None:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.OPERATION_NOT_FOUND, "Online MR 会话操作不存在")
        return self._to_operation(mapping)

    def list_operations(
        self,
        *,
        site_id: str | None = None,
        states: set[OnlineMrMappingState] | None = None,
        device_id: str | int | None = None,
        limit: int = 200,
    ) -> list[OnlineMrOperationSnapshotDTO]:
        sites = [site_id] if site_id else self._site_ids()
        rows = [
            self._to_operation(mapping)
            for selected_site in sites
            for mapping in self.repository(selected_site).list(states=states, device_id=device_id, limit=limit)
        ]
        rows.sort(key=lambda row: (row.updated_at, row.controller_task_id), reverse=True)
        return rows[: max(1, min(int(limit), 1000))]

    def stop_operation(
        self,
        controller_task_id: str,
        *,
        site_id: str | None = None,
        timeout_seconds: float = 65.0,
        stop_reason: str = "user_stop",
    ) -> OnlineMrOperationSnapshotDTO:
        mapping = self._required_mapping(controller_task_id, site_id=site_id)
        if mapping.phase is OnlineMrPhase.TERMINAL:
            return self._to_operation(mapping)
        if mapping.executor_kind is not OnlineMrExecutorKind.LOCAL:
            if self.agent_executor is None:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.AGENT_EXECUTOR_DISABLED,
                    "Online MR Agent 执行器未启用",
                )
            updated = self.agent_executor.stop(mapping, stop_reason=stop_reason)
            return self._to_operation(updated)
        repository = self.repository(mapping.site_id)
        repository.mark_stopping(
            controller_task_id,
            phase=OnlineMrPhase.STOPPING_TRAFFIC,
            stop_reason=stop_reason,
            updated_at=utc_now_iso(),
        )
        requested = self.process_adapter.cancel_job(controller_task_id)
        if requested and self.process_adapter.wait(controller_task_id, timeout=max(0.0, float(timeout_seconds))):
            return self.finalize_operation(controller_task_id, site_id=mapping.site_id, stop_reason=stop_reason)
        return self.get_operation(controller_task_id, site_id=mapping.site_id)

    def force_stop_operation(
        self,
        controller_task_id: str,
        *,
        site_id: str | None = None,
        cooperative_timeout_seconds: float = 2.0,
        force_timeout_seconds: float = 1.0,
        stop_reason: str = "force_stop",
    ) -> OnlineMrOperationSnapshotDTO:
        mapping = self._required_mapping(controller_task_id, site_id=site_id)
        if mapping.phase is OnlineMrPhase.TERMINAL:
            return self._to_operation(mapping)
        if mapping.executor_kind is not OnlineMrExecutorKind.LOCAL:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.EXECUTOR_UNSUPPORTED, "Agent 执行端不支持强制停止")
        repository = self.repository(mapping.site_id)
        repository.mark_stopping(
            controller_task_id,
            phase=OnlineMrPhase.STOPPING_TRAFFIC,
            stop_reason=stop_reason,
            force_stopped=True,
            updated_at=utc_now_iso(),
        )
        self.process_adapter.cancel_job(controller_task_id)
        cooperative = self.process_adapter.wait(
            controller_task_id,
            timeout=max(0.0, float(cooperative_timeout_seconds)),
        )
        forced_process = False
        if not cooperative:
            forced_process = self.process_adapter.force_stop_job(
                controller_task_id,
                timeout_seconds=max(0.0, float(force_timeout_seconds)),
            )
            self.process_adapter.wait(controller_task_id, timeout=max(0.0, float(force_timeout_seconds)))
        warning = "强制终止后无法确认全部 writer flush，已保留原始会话目录" if forced_process else ""
        return self.finalize_operation(
            controller_task_id,
            site_id=mapping.site_id,
            status="FORCED_STOPPED",
            stop_reason=stop_reason,
            force_stopped=True,
            error_summary=warning,
            finalization_complete=False if forced_process else None,
        )

    def finalize_operation(
        self,
        controller_task_id: str,
        *,
        site_id: str | None = None,
        status: str | None = None,
        stop_reason: str = "",
        force_stopped: bool = False,
        error_summary: str = "",
        error_code: str = "",
        finalization_complete: bool | None = None,
        mapping_state: OnlineMrMappingState | None = None,
    ) -> OnlineMrOperationSnapshotDTO:
        mapping = self._required_mapping(controller_task_id, site_id=site_id)
        repository = self.repository(mapping.site_id)
        now = utc_now_iso()
        session_dir = self._session_dir(mapping)
        meta = self._read_metadata(session_dir) if session_dir is not None else None
        task = self.task_service.repository(mapping.site_id).get(mapping.controller_task_id)
        started_at = self._text((meta or {}).get("started_at")) or mapping.started_at
        if not started_at and task is not None:
            started_at = task.started_time
        started_at = started_at or mapping.created_at
        ended_at = self._text((meta or {}).get("ended_at")) or now
        duration = calculate_duration_minutes(started_at, ended_at)
        forced = bool(force_stopped or mapping.force_stopped)
        summary = str(error_summary or mapping.error_summary or mapping.error_message)
        reason = str(stop_reason or mapping.stop_reason or ("force_stop" if forced else "task_terminal"))

        if meta is not None and session_dir is not None:
            current_status = self._text(meta.get("status")).upper()
            selected_status = str(status or current_status or ("FORCED_STOPPED" if forced else "STOPPED")).upper()
            if current_status not in {"STOPPED", "FORCED_STOPPED", "FAILED", "ABORTED"} or status:
                meta["status"] = selected_status
            meta["ended_at"] = self._text(meta.get("ended_at")) or datetime.now().isoformat(sep=" ", timespec="seconds")
            meta["duration_minutes"] = duration
            meta["stop_reason"] = reason
            meta["force_stopped"] = forced
            if finalization_complete is not None:
                meta["finalization_complete"] = bool(finalization_complete)
                if not finalization_complete:
                    meta["package_available"] = False
                    meta["data_integrity"] = "partial"
            if summary:
                warnings = [str(item) for item in list(meta.get("finalization_warnings") or []) if str(item)]
                if summary not in warnings:
                    warnings.append(summary)
                meta["finalization_warnings"] = warnings
                meta["error_message"] = summary
            if error_code:
                meta["error_code"] = error_code
            self._write_metadata(session_dir, meta)

        final_state = mapping_state or (
            OnlineMrMappingState.TASK_ONLY_FAILED
            if mapping.session_id is None and (status == "FAILED" or summary)
            else OnlineMrMappingState.TERMINAL
        )
        updated = repository.mark_terminal(
            controller_task_id,
            started_at=started_at,
            ended_at=ended_at,
            updated_at=now,
            duration_minutes=duration,
            stop_reason=reason,
            force_stopped=forced,
            error_summary=summary,
            error_code=error_code or mapping.error_code,
            mapping_state=final_state,
        )
        return self._to_operation(updated)

    def finalize_by_session(
        self,
        session_id: str,
        *,
        site_id: str | None = None,
        **kwargs: object,
    ) -> OnlineMrOperationSnapshotDTO:
        mapping = self._find_by_session(session_id, site_id=site_id)
        if mapping is None:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.OPERATION_NOT_FOUND, "Online MR 会话操作不存在")
        return self.finalize_operation(mapping.controller_task_id, site_id=mapping.site_id, **kwargs)

    def reconcile_task_event(self, event: dict[str, object]) -> None:
        task_id = str(event.get("task_id") or event.get("job_id") or "")
        if not task_id:
            return
        payload = dict(event.get("payload") or event)
        mapping = self._find_by_task(task_id, site_id=self._text(payload.get("site_id")) or None)
        if (
            mapping is None
            or mapping.phase is OnlineMrPhase.TERMINAL
            or mapping.executor_kind is not OnlineMrExecutorKind.LOCAL
        ):
            return
        repository = self.repository(mapping.site_id)
        event_type = str(event.get("type") or payload.get("type") or "")
        stage = str(payload.get("stage") or "")
        now = str(event.get("time") or utc_now_iso())

        if event_type == "progress" and stage in {"online_mr_session_created", "online_mr_started", "online_mr_status"}:
            details = self._structured_message(payload.get("message"))
            mapping = self._reconcile_progress(repository, mapping, stage, details, now)
            return
        if event_type not in {"finished", "error", "cancelled"}:
            return

        error_message = self._sanitize_error_text(payload.get("error") or payload.get("message"))
        startup_failure = event_type == "error" and mapping.phase in _STARTUP_PHASES
        state = OnlineMrMappingState.TASK_ONLY_FAILED if event_type == "error" and not mapping.session_id else OnlineMrMappingState.TERMINAL
        error_code = OnlineMrApplicationErrorCode.STARTUP_CONNECTION_FAILED.value if startup_failure else mapping.error_code
        result = dict(event.get("result") or payload.get("result") or {})
        result_warnings = [str(item) for item in list(result.get("warnings") or []) if str(item)]
        cancelled_with_session = event_type == "cancelled" and bool(mapping.session_id)
        # A bare cancellation event without an explicit stop request means the
        # worker disappeared before finalization; an acknowledged user stop is
        # already marked with stop_reason and remains a normal STOPPED result.
        forced = bool(mapping.force_stopped or (cancelled_with_session and not mapping.stop_reason))
        terminal_summary = (
            error_message
            if event_type == "error"
            else "Worker 在完成最终化前退出，原始会话目录已保留"
            if cancelled_with_session and forced
            else "; ".join(result_warnings) or mapping.error_summary
        )
        self.finalize_operation(
            task_id,
            site_id=mapping.site_id,
            status=(
                "FAILED"
                if event_type == "error"
                else "FORCED_STOPPED"
                if forced
                else self._text(result.get("status")) or "STOPPED"
            ),
            stop_reason=mapping.stop_reason
            or self._text(result.get("stop_reason"))
            or ("task_failed" if event_type == "error" else "worker_cancelled" if event_type == "cancelled" else "task_terminal"),
            force_stopped=forced,
            error_summary=terminal_summary,
            error_code=error_code,
            finalization_complete=False if cancelled_with_session and forced else None,
            mapping_state=state,
        )

    def recover_mappings(self, *, site_id: str | None = None) -> list[OnlineMrOperationSnapshotDTO]:
        changed: list[OnlineMrTaskSessionMapping] = []
        if self.agent_executor is not None:
            changed.extend(self.agent_executor.recover(site_id))
        for selected_site in ([site_id] if site_id else self._site_ids()):
            repository = self.repository(selected_site)
            task_repository = self.task_service.repository(selected_site)
            for mapping in repository.list(limit=1000):
                self._remember_mapping(mapping)
                if mapping.mapping_state not in _ACTIVE_MAPPING_STATES:
                    continue
                if mapping.executor_kind is not OnlineMrExecutorKind.LOCAL:
                    continue
                task = task_repository.get(mapping.controller_task_id)
                if task is not None and task.status not in TERMINAL_TASK_STATES:
                    continue
                now = utc_now_iso()
                if task is None:
                    state = OnlineMrMappingState.STALE
                    error = "未找到对应 Controller Task"
                elif mapping.session_id:
                    state = OnlineMrMappingState.TERMINAL
                    error = task.error_message
                else:
                    state = OnlineMrMappingState.TASK_ONLY_FAILED
                    error = task.error_message
                updated = replace(
                    mapping,
                    phase=OnlineMrPhase.TERMINAL,
                    mapping_state=state,
                    updated_at=now,
                    terminal_at=now,
                    ended_at=now,
                    duration_minutes=calculate_duration_minutes(mapping.started_at or mapping.created_at, now),
                    stop_reason="recovered_aborted",
                    error_code=mapping.error_code or OnlineMrApplicationErrorCode.STALE_OPERATION.value,
                    error_summary=mapping.error_summary or error,
                    error_message=mapping.error_message or error,
                )
                repository.save(updated)
                changed.append(updated)

            store = OnlineMrSessionStore(self.paths)
            for session_dir in store.list_session_dirs(selected_site):
                meta = self._read_metadata(session_dir)
                if meta is None or str(meta.get("status") or "").upper() not in _STALE_SESSION_STATES:
                    continue
                existing = repository.get_by_session(str(meta.get("session_id") or session_dir.name))
                if existing:
                    task = task_repository.get(existing.controller_task_id)
                    if task is not None and task.status not in TERMINAL_TASK_STATES:
                        continue
                self._abort_stale_session(session_dir, meta)
                now = utc_now_iso()
                if existing and existing.mapping_state in _ACTIVE_MAPPING_STATES:
                    updated = replace(
                        existing,
                        phase=OnlineMrPhase.TERMINAL,
                        mapping_state=OnlineMrMappingState.STALE,
                        updated_at=now,
                        terminal_at=now,
                        started_at=self._text(meta.get("started_at")) or existing.started_at,
                        ended_at=self._text(meta.get("ended_at")) or now,
                        duration_minutes=float(meta.get("duration_minutes") or 0.0),
                        stop_reason="recovered_aborted",
                        error_summary="Controller 重启后未发现仍存活的本地 Online MR Worker",
                        error_code=OnlineMrApplicationErrorCode.STALE_OPERATION.value,
                        error_message="Controller 重启后未发现仍存活的本地 Online MR Worker",
                    )
                    repository.save(updated)
                elif existing:
                    if existing.duration_minutes is None:
                        repository.save(
                            replace(
                                existing,
                                started_at=self._text(meta.get("started_at")) or existing.started_at,
                                ended_at=self._text(meta.get("ended_at")) or existing.ended_at or now,
                                duration_minutes=float(meta.get("duration_minutes") or 0.0),
                            )
                        )
                    continue
                else:
                    session_id_value = str(meta.get("session_id") or session_dir.name)
                    updated = OnlineMrTaskSessionMapping(
                        controller_task_id=f"recovered_{uuid.uuid5(uuid.NAMESPACE_URL, f'{selected_site}:{session_id_value}').hex}",
                        session_id=session_id_value,
                        site_id=selected_site,
                        device_id=str(meta.get("device_id") or ""),
                        device_name=str(meta.get("device_name") or ""),
                        mr_id=str(meta.get("mr_id") or ""),
                        mr_name=str(meta.get("mr_name") or session_dir.parent.parent.name),
                        executor_kind=OnlineMrExecutorKind.LOCAL,
                        phase=OnlineMrPhase.TERMINAL,
                        mapping_state=OnlineMrMappingState.SESSION_ONLY_RECOVERED,
                        created_at=now,
                        updated_at=now,
                        started_at=self._text(meta.get("started_at")) or None,
                        ended_at=self._text(meta.get("ended_at")) or now,
                        duration_minutes=calculate_duration_minutes(
                            self._text(meta.get("started_at")) or now,
                            self._text(meta.get("ended_at")) or now,
                        ),
                        stop_reason="recovered_aborted",
                        error_summary="恢复到无 Controller Task 的遗留 Online MR 会话",
                        terminal_at=now,
                        error_code=OnlineMrApplicationErrorCode.STALE_OPERATION.value,
                        error_message="恢复到无 Controller Task 的遗留 Online MR 会话",
                    )
                    try:
                        repository.create(updated)
                    except sqlite3.IntegrityError:
                        continue
                changed.append(updated)
        return [self._to_operation(mapping) for mapping in changed]

    def repository(self, site_id: str) -> OnlineMrTaskSessionRepository:
        selected_site = self._safe_component(site_id)
        if not selected_site or not self.paths.site_dir(selected_site).is_dir():
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.SITE_NOT_FOUND, "Online MR 局点不存在")
        repository = self._repositories.get(selected_site)
        if repository is None:
            repository = OnlineMrTaskSessionRepository(self.paths.site_tasks_db_path(selected_site), site_id=selected_site)
            self._repositories[selected_site] = repository
        return repository

    def close(self) -> None:
        self._unsubscribe()
        if self.agent_executor is not None:
            self.agent_executor.close()

    def _reconcile_progress(
        self,
        repository: OnlineMrTaskSessionRepository,
        mapping: OnlineMrTaskSessionMapping,
        stage: str,
        details: dict[str, object],
        now: str,
    ) -> OnlineMrTaskSessionMapping:
        if details:
            if self._text(details.get("controller_task_id")) not in {"", mapping.controller_task_id}:
                return mapping
            if self._text(details.get("site_id") or details.get("site")) not in {"", mapping.site_id}:
                return mapping
            if self._text(details.get("device_id")) not in {"", mapping.device_id}:
                return mapping
        session_id = self._text(details.get("session_id"))
        if session_id and mapping.session_id not in {None, session_id}:
            self._terminal_mapping_error(repository, mapping, OnlineMrApplicationErrorCode.SESSION_LINK_FAILED, "Online MR session_id 映射冲突")
            return mapping
        if stage == "online_mr_session_created":
            phase = OnlineMrPhase.CONNECTING
        elif stage == "online_mr_started":
            phase = OnlineMrPhase.COLLECTING
        else:
            status = self._text(details.get("status")).upper()
            phase = {
                "CONNECTING": OnlineMrPhase.CONNECTING,
                "INITIALIZING": OnlineMrPhase.STARTING_COLLECTION,
                "COLLECTING": OnlineMrPhase.COLLECTING,
                "RECONNECTING": OnlineMrPhase.COLLECTING,
            }.get(status, mapping.phase)
        updated = replace(
            mapping,
            session_id=session_id or mapping.session_id,
            phase=phase,
            mapping_state=OnlineMrMappingState.LINKED if session_id or mapping.session_id else mapping.mapping_state,
            updated_at=now,
            started_at=(
                self._text(details.get("started_at")) or mapping.started_at
                if stage == "online_mr_started"
                else mapping.started_at
            ),
        )
        try:
            return self._remember_mapping(repository.save(updated))
        except sqlite3.IntegrityError:
            self._terminal_mapping_error(repository, mapping, OnlineMrApplicationErrorCode.MAPPING_CONFLICT, "Online MR session_id 已关联其他任务")
            return mapping

    def _terminal_mapping_error(
        self,
        repository: OnlineMrTaskSessionRepository,
        mapping: OnlineMrTaskSessionMapping,
        code: OnlineMrApplicationErrorCode,
        message: str,
    ) -> None:
        now = utc_now_iso()
        repository.save(
            replace(
                mapping,
                phase=OnlineMrPhase.TERMINAL,
                mapping_state=OnlineMrMappingState.TERMINAL,
                updated_at=now,
                terminal_at=now,
                ended_at=now,
                duration_minutes=calculate_duration_minutes(mapping.started_at or mapping.created_at, now),
                stop_reason="mapping_error",
                error_code=code.value,
                error_summary=message,
                error_message=message,
            )
        )

    def _to_operation(self, mapping: OnlineMrTaskSessionMapping) -> OnlineMrOperationSnapshotDTO:
        self._remember_mapping(mapping)
        task = self.task_service.repository(mapping.site_id).get(mapping.controller_task_id)
        return OnlineMrOperationSnapshotDTO(
            controller_task_id=mapping.controller_task_id,
            session_id=mapping.session_id,
            site_id=mapping.site_id,
            device_id=mapping.device_id or None,
            device_name=mapping.device_name,
            mr_id=mapping.mr_id,
            mr_name=mapping.mr_name,
            executor_kind=mapping.executor_kind,
            agent_id=mapping.agent_id,
            agent_profile_id=mapping.agent_profile_id,
            agent_task_id=mapping.agent_task_id,
            remote_session_id=mapping.remote_session_id,
            remote_package_id=mapping.remote_package_id,
            last_remote_status=mapping.last_remote_status,
            last_remote_seen_at=mapping.last_remote_seen_at,
            consecutive_status_failures=mapping.consecutive_status_failures,
            deadline_at=mapping.deadline_at,
            task_status=task.status if task else None,
            phase=mapping.phase,
            created_at=mapping.created_at,
            started_at=mapping.started_at or (task.started_time if task and task.started_time else None),
            updated_at=mapping.updated_at,
            terminal_at=mapping.terminal_at,
            ended_at=mapping.ended_at,
            duration_minutes=mapping.duration_minutes,
            stop_reason=mapping.stop_reason,
            force_stopped=mapping.force_stopped,
            error_summary=mapping.error_summary,
            error_code=mapping.error_code,
            error_message=mapping.error_message,
            mapping_state=mapping.mapping_state,
        )

    def _find_by_task(self, task_id: str, *, site_id: str | None = None) -> OnlineMrTaskSessionMapping | None:
        bound_site = self._operation_sites.get(task_id)
        if site_id and bound_site and site_id != bound_site:
            return None
        selected_site = site_id or bound_site
        if not selected_site:
            return None
        mapping = self.repository(selected_site).get_by_task(task_id)
        return self._remember_mapping(mapping) if mapping is not None else None

    def _find_by_session(self, session_id: str, *, site_id: str | None = None) -> OnlineMrTaskSessionMapping | None:
        bound_site = self._session_sites.get(session_id)
        if site_id and bound_site and site_id != bound_site:
            return None
        selected_site = site_id or bound_site
        if not selected_site:
            return None
        mapping = self.repository(selected_site).get_by_session(session_id)
        return self._remember_mapping(mapping) if mapping is not None else None

    def _remember_mapping(self, mapping: OnlineMrTaskSessionMapping) -> OnlineMrTaskSessionMapping:
        with self._mapping_index_lock:
            bound_site = self._operation_sites.get(mapping.controller_task_id)
            session_site = self._session_sites.get(mapping.session_id) if mapping.session_id else None
            if bound_site not in {None, mapping.site_id}:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.MAPPING_CONFLICT,
                    "Online MR operation 局点绑定冲突",
                )
            if session_site not in {None, mapping.site_id}:
                raise OnlineMrApplicationError(
                    OnlineMrApplicationErrorCode.MAPPING_CONFLICT,
                    "Online MR session 局点绑定冲突",
                )
            self._operation_sites[mapping.controller_task_id] = mapping.site_id
            if mapping.session_id:
                self._session_sites[mapping.session_id] = mapping.site_id
        return mapping

    def _required_mapping(self, task_id: str, *, site_id: str | None = None) -> OnlineMrTaskSessionMapping:
        mapping = self._find_by_task(task_id, site_id=site_id)
        if mapping is None:
            raise OnlineMrApplicationError(OnlineMrApplicationErrorCode.OPERATION_NOT_FOUND, "Online MR 操作不存在")
        return mapping

    def _process_completed(self, completion: LocalProcessCompletion) -> None:
        if not completion.forced:
            return
        mapping = self._find_by_task(completion.job_id)
        if mapping is None:
            return
        self.finalize_operation(
            completion.job_id,
            site_id=mapping.site_id,
            status="FORCED_STOPPED",
            stop_reason=mapping.stop_reason or "worker_forced_stop",
            force_stopped=True,
            error_summary="Worker 进程被强制终止，原始会话目录已保留",
            finalization_complete=False,
        )

    def _session_dir(self, mapping: OnlineMrTaskSessionMapping) -> Path | None:
        if not mapping.session_id:
            return None
        store = OnlineMrSessionStore(self.paths)
        for session_dir in store.list_session_dirs(mapping.site_id):
            if session_dir.name == mapping.session_id:
                return session_dir
        return None

    def _site_ids(self) -> list[str]:
        values: set[str] = set()
        if self.paths.sites_dir.is_dir():
            values.update(path.name for path in self.paths.sites_dir.iterdir() if path.is_dir())
        if self.paths.site_dir(self.site_name).is_dir():
            values.add(self.site_name)
        return sorted(values)

    def _device_exists(self, site_id: str, device_id: int | str) -> bool:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return False
        try:
            device = DeviceRepository(Database(db_path)).get(int(device_id))
            return is_current_debug_device(device)
        except (KeyError, TypeError, ValueError):
            return False

    def _device_identity_matches(self, request: OnlineMrStartRequest) -> bool:
        try:
            device = DeviceRepository(Database(self.paths.site_db_path(request.site_id))).get(
                int(request.device_id)
            )
        except (KeyError, OSError, sqlite3.Error, TypeError, ValueError):
            return False
        if not is_current_debug_device(device):
            return False
        hosts = {str(device.primary_address or "").strip(), str(device.backup_address or "").strip()}
        return (
            request.device_name == device.name
            and request.config.device_name == device.name
            and request.config.host.strip() in hosts
        )

    def _abort_stale_session(self, session_dir: Path, meta: dict[str, object]) -> None:
        previous_status = str(meta.get("status") or "")
        meta["status"] = "ABORTED"
        meta["ended_at"] = meta.get("ended_at") or datetime.now().isoformat(sep=" ", timespec="seconds")
        meta["recovery_previous_status"] = previous_status
        meta["error_code"] = meta.get("error_code") or OnlineMrApplicationErrorCode.STALE_OPERATION.value
        meta["error_message"] = meta.get("error_message") or "Controller 重启后未发现仍存活的本地 Online MR Worker"
        meta["stop_reason"] = meta.get("stop_reason") or "recovered_aborted"
        meta["force_stopped"] = bool(meta.get("force_stopped", False))
        meta["finalization_complete"] = False
        meta["duration_minutes"] = calculate_duration_minutes(
            self._text(meta.get("started_at")) or str(meta["ended_at"]),
            str(meta["ended_at"]),
        )
        self._write_metadata(session_dir, meta)

    @staticmethod
    def _read_metadata(session_dir: Path) -> dict[str, object] | None:
        try:
            value = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def _write_metadata(session_dir: Path, meta: dict[str, object]) -> None:
        path = session_dir / "session_meta.json"
        temporary = path.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _structured_message(value: object) -> dict[str, object]:
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @staticmethod
    def _safe_component(value: object) -> str:
        text = str(value or "").strip()
        return text if text and Path(text).name == text and text not in {".", ".."} else ""

    @staticmethod
    def _text(value: object) -> str:
        return str(value or "").strip()

    @staticmethod
    def _safe_error(exc: BaseException, *sensitive_values: str) -> str:
        text = OnlineMrApplicationService._sanitize_error_text(exc or exc.__class__.__name__)
        for sensitive in sorted({str(value) for value in sensitive_values if str(value)}, key=len, reverse=True):
            text = text.replace(sensitive, "<redacted>")
        return text

    @staticmethod
    def _sanitize_error_text(value: object) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        return re.sub(r"(?i)(?:[a-z]:\\|/)[^ ]+", "<path>", text)[:500]


__all__ = ["OnlineMrApplicationService"]
