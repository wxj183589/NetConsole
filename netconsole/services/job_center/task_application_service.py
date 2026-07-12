from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from typing import Any

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.runtime.task_event_hub import TaskEventHub
from netconsole.services.job_center.runtime.task_runtime import TaskLaunch, TaskRuntime


class TaskApplicationService:
    """Qt、FastAPI 等宿主共享的任务应用层与持久化入口。"""

    def __init__(
        self,
        paths: PathResolver | None = None,
        event_hub: TaskEventHub | None = None,
        *,
        site_name: str = "demo",
    ) -> None:
        self.paths = paths or PathResolver()
        self.site_name = str(site_name or "demo")
        self.runtime = TaskRuntime(paths=self.paths, event_bus=event_hub or TaskEventHub())
        self._repositories: dict[str, TaskRepository] = {}
        self._reconciled_sites: set[str] = set()
        self._job_sites: dict[str, str] = {}
        self.events.subscribe(self._persist_event)
        self.reconcile_orphaned_local_tasks()

    @property
    def events(self) -> TaskEventHub:
        return self.runtime.events

    def repository(self, site_name: str | None = None) -> TaskRepository:
        site = str(site_name or self.site_name or "demo")
        repository = self._repositories.get(site)
        if repository is None:
            repository = TaskRepository(self.paths.site_tasks_db_path(site))
            self._repositories[site] = repository
        if site not in self._reconciled_sites:
            self._reconciled_sites.add(site)
            repository.reconcile_orphaned_local_tasks(self._is_process_alive)
        return repository

    def prepare(self, job: BackgroundJob) -> TaskLaunch:
        job_id = job.job_id or uuid.uuid4().hex
        runtime_job = BackgroundJob.from_dict({**job.to_dict(), "job_id": job_id})
        params = dict(runtime_job.params or {})
        site_name = str(params.get("site_name") or self.site_name or "demo")
        now = utc_now_iso()
        snapshot = TaskSnapshot(
            task_id=job_id,
            task_type=runtime_job.task_type,
            task_name=str(params.get("task_name") or params.get("name") or runtime_job.task_type),
            status=TaskState.PENDING,
            created_time=now,
            updated_time=now,
            owner=str(params.get("owner") or "local"),
            device=self._first_text(params, "device", "device_name", "device_uuid", "device_id"),
            agent=self._first_text(params, "agent", "agent_name", "agent_id"),
            result_path=str(params.get("result_path") or ""),
            source=str(params.get("task_source") or "local"),
            site_name=site_name,
            owner_pid=os.getpid(),
        )
        self.repository(site_name).save(snapshot)
        self._job_sites[job_id] = site_name
        try:
            return self.runtime.prepare(runtime_job)
        except Exception as exc:
            self._record_prepare_failure(snapshot, str(exc))
            self._job_sites.pop(job_id, None)
            raise

    def create_external_task(
        self,
        *,
        task_id: str,
        task_type: str,
        task_name: str,
        source: str,
        site_name: str | None = None,
        owner: str = "controller",
        agent: str = "",
        device: str = "",
    ) -> TaskSnapshot:
        """创建不由本地 Worker 承载、但仍进入统一任务中心的任务。"""

        selected_site = str(site_name or self.site_name or "demo")
        repository = self.repository(selected_site)
        if repository.get(task_id) is not None:
            raise ValueError(f"任务已存在：{task_id}")
        now = utc_now_iso()
        snapshot = TaskSnapshot(
            task_id=task_id,
            task_type=task_type,
            task_name=task_name,
            status=TaskState.PENDING,
            created_time=now,
            updated_time=now,
            owner=owner,
            device=device,
            agent=agent,
            source=str(source or "external"),
            site_name=selected_site,
            owner_pid=0,
        )
        event = TaskEvent(
            event_id=uuid.uuid4().hex,
            task_id=task_id,
            type="state",
            time=now,
            source="service",
            payload={"state": TaskState.PENDING.value, "task_type": task_type},
        )
        repository.record(snapshot, event)
        self._job_sites[task_id] = selected_site
        self.events.publish(event.to_dict())
        return snapshot

    def record_external_event(
        self,
        task_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        source: str = "service",
        site_name: str | None = None,
        event_id: str = "",
        event_time: str = "",
    ) -> TaskSnapshot:
        """先持久化外部任务事件，再广播同一事件；持久化失败会直接上抛。"""

        selected_site = str(site_name or self._job_sites.get(task_id) or self.site_name or "demo")
        repository = self.repository(selected_site)
        snapshot = repository.get(task_id)
        if snapshot is None:
            raise KeyError(task_id)
        selected_time = event_time or utc_now_iso()
        event = TaskEvent(
            event_id=event_id or uuid.uuid4().hex,
            task_id=task_id,
            type=str(event_type or "log"),
            time=selected_time,
            source=source,
            payload=dict(payload or {}),
        )
        updated = self._apply_event(snapshot, event.type, event.payload, selected_time)
        repository.record(updated, event)
        self._job_sites[task_id] = selected_site
        self.events.publish(event.to_dict())
        if updated.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            self._job_sites.pop(task_id, None)
        return updated

    def mark_running(self, job_id: str) -> None:
        self.runtime.mark_running(job_id)

    def feed_stdout(self, job_id: str, chunk: bytes) -> None:
        self.runtime.feed_stdout(job_id, chunk)

    def feed_stderr(self, job_id: str, chunk: bytes) -> None:
        self.runtime.feed_stderr(job_id, chunk)

    def request_cancel(self, job_id: str) -> int:
        return self.runtime.request_cancel(job_id)

    def cancel_task(self, job_id: str) -> bool:
        snapshot = self.get_task(job_id)
        if snapshot is None or snapshot.status in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            return False
        if snapshot.source != "local":
            return False
        if self.runtime.is_running(job_id):
            self.runtime.request_cancel(job_id)
        else:
            cancel_path = self.paths.runtime_cache_dir / "background_jobs" / f"{job_id}.cancel"
            cancel_path.parent.mkdir(parents=True, exist_ok=True)
            cancel_path.write_text("cancelled", encoding="utf-8")
            self.events.publish(
                {
                    "type": "state",
                    "job_id": job_id,
                    "task_type": snapshot.task_type,
                    "state": TaskState.STOPPING.value,
                    "message": "已请求停止任务",
                },
                source="api",
            )
        return True

    def complete(self, job_id: str, exit_code: int) -> dict[str, object] | None:
        try:
            return self.runtime.complete(job_id, exit_code)
        finally:
            self._job_sites.pop(job_id, None)

    def fail_start(self, job_id: str, message: str) -> dict[str, object] | None:
        try:
            return self.runtime.fail_start(job_id, message)
        finally:
            self._job_sites.pop(job_id, None)

    def abandon(self, job_id: str) -> None:
        try:
            self.runtime.abandon(job_id)
        finally:
            self._job_sites.pop(job_id, None)

    def is_running(self, job_id: str) -> bool:
        return self.runtime.is_running(job_id)

    def list_tasks(self, *, statuses: set[TaskState] | None = None, limit: int = 200) -> list[TaskSnapshot]:
        return self.repository().list(statuses=statuses, limit=limit)

    def get_task(self, task_id: str) -> TaskSnapshot | None:
        return self.repository().get(task_id)

    def list_events(self, task_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self.repository().list_events(task_id, after_sequence=after_sequence, limit=limit)

    def list_all_events(self, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self.repository().list_all_events(after_sequence=after_sequence, limit=limit)

    def last_event_sequence(self) -> int:
        return self.repository().last_event_sequence()

    def reconcile_orphaned_local_tasks(self) -> list[TaskSnapshot]:
        return self.repository().reconcile_orphaned_local_tasks(self._is_process_alive)

    def _persist_event(self, envelope: dict[str, object]) -> None:
        try:
            task_id = str(envelope.get("task_id") or "")
            if not task_id:
                return
            payload = dict(envelope.get("payload") or {})
            site_name = self._job_sites.get(task_id, self.site_name)
            repository = self.repository(site_name)
            snapshot = repository.get(task_id)
            if snapshot is None:
                return
            updated = self._apply_event(snapshot, str(envelope.get("type") or ""), payload, str(envelope.get("time") or utc_now_iso()))
            repository.record(
                updated,
                TaskEvent(
                    event_id=str(envelope.get("id") or uuid.uuid4().hex),
                    task_id=task_id,
                    type=str(envelope.get("type") or "log"),
                    time=str(envelope.get("time") or utc_now_iso()),
                    source=str(envelope.get("source") or "service"),
                    payload=payload,
                ),
            )
        except Exception as exc:
            app_logger.log_error("TASK_EVENT_PERSIST_FAILED", f"task_id={envelope.get('task_id', '')} error={exc}")

    def _apply_event(self, snapshot: TaskSnapshot, event_type: str, payload: dict[str, Any], event_time: str) -> TaskSnapshot:
        values = asdict(snapshot)
        values["updated_time"] = event_time
        values["stage"] = str(payload.get("stage") or values["stage"])
        values["message"] = str(payload.get("message") or values["message"])
        current = int(payload.get("current") or values["current"] or 0)
        total = int(payload.get("total") or values["total"] or 0)
        values["current"] = current
        values["total"] = total
        if event_type == "state":
            state_text = str(payload.get("state") or snapshot.status.value)
            values["status"] = TaskState(state_text)
            if values["status"] is TaskState.RUNNING and not values["started_time"]:
                values["started_time"] = event_time
            if values["status"] in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
                values["finished_time"] = event_time
        elif event_type == "progress":
            if total > 0:
                values["progress"] = max(0, min(round(current * 100 / total), 100))
        elif event_type == "finished":
            result = dict(payload.get("result") or {})
            values.update(
                {
                    "status": TaskState.COMPLETED,
                    "finished_time": event_time,
                    "progress": 100,
                    "result": result,
                    "result_path": self._result_path(result) or values["result_path"],
                }
            )
        elif event_type == "error":
            values.update(
                {
                    "status": TaskState.FAILED,
                    "finished_time": event_time,
                    "error_message": str(payload.get("error") or payload.get("message") or "任务失败"),
                }
            )
        elif event_type == "cancelled":
            values.update(
                {
                    "status": TaskState.CANCELLED,
                    "finished_time": event_time,
                    "error_message": str(payload.get("error") or payload.get("message") or "任务已取消"),
                }
            )
        return TaskSnapshot(**values)

    def _record_prepare_failure(self, snapshot: TaskSnapshot, message: str) -> None:
        now = utc_now_iso()
        failed = TaskSnapshot(
            **{
                **asdict(snapshot),
                "status": TaskState.FAILED,
                "finished_time": now,
                "updated_time": now,
                "message": "任务启动失败",
                "error_message": message,
            }
        )
        self.repository(snapshot.site_name).record(
            failed,
            TaskEvent(
                event_id=uuid.uuid4().hex,
                task_id=snapshot.task_id,
                type="error",
                time=now,
                source="service",
                payload={"message": "任务启动失败", "error": message, "cancelled": False},
            ),
        )

    @staticmethod
    def _first_text(values: dict[str, Any], *keys: str) -> str:
        return next((str(values[key]) for key in keys if values.get(key) not in {None, ""}), "")

    @staticmethod
    def _result_path(result: dict[str, Any]) -> str:
        return next(
            (
                str(result[key])
                for key in ("result_path", "output_path", "report_path", "package_path", "path")
                if result.get(key)
            ),
            "",
        )

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
