from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from netconsole.models.traffic_test import AgentTaskMapping, TrafficSyncState
from netconsole.repositories.traffic_run_repository import TrafficRunRepository
from netconsole.services.traffic.agent_adapter import AgentTrafficAdapter
from netconsole.services.traffic.errors import TrafficErrorCode, TrafficTestError


@dataclass(frozen=True)
class AgentTrafficSupervisorSettings:
    poll_interval_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    max_concurrency: int = 4
    event_page_size: int = 1_000
    max_event_pages_per_poll: int = 4
    result_retry_limit: int = 3

    def normalized(self) -> AgentTrafficSupervisorSettings:
        return AgentTrafficSupervisorSettings(
            poll_interval_seconds=max(0.01, float(self.poll_interval_seconds)),
            max_backoff_seconds=max(float(self.poll_interval_seconds), float(self.max_backoff_seconds)),
            max_concurrency=max(1, min(int(self.max_concurrency), 32)),
            event_page_size=max(1, min(int(self.event_page_size), 1_000)),
            max_event_pages_per_poll=max(1, min(int(self.max_event_pages_per_poll), 20)),
            result_retry_limit=max(1, int(self.result_retry_limit)),
        )


class AgentTrafficSupervisor:
    """单循环、有限并发的 Controller 侧远端任务监督器。"""

    def __init__(
        self,
        adapter: AgentTrafficAdapter,
        repository: TrafficRunRepository | None = None,
        *,
        settings: AgentTrafficSupervisorSettings | None = None,
    ) -> None:
        self.adapter = adapter
        self.repository = repository or adapter.repository
        self.settings = (settings or AgentTrafficSupervisorSettings()).normalized()
        self._attached: set[str] = set()
        self._next_poll: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._last_error_codes: dict[str, str] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    def attach(self, traffic_run_id: str) -> bool:
        run_id = str(traffic_run_id or "").strip()
        if not run_id or self.repository.get_agent_mapping(run_id) is None:
            return False
        created = run_id not in self._attached
        self._attached.add(run_id)
        self._next_poll[run_id] = 0.0
        self._wake.set()
        return created

    def detach(self, traffic_run_id: str) -> bool:
        run_id = str(traffic_run_id or "").strip()
        existed = run_id in self._attached
        self._attached.discard(run_id)
        self._next_poll.pop(run_id, None)
        self._failures.pop(run_id, None)
        self._last_error_codes.pop(run_id, None)
        return existed

    async def start(self) -> None:
        if self.running:
            return
        self._stopping = False
        await self.recover_active_runs()
        self._loop_task = asyncio.create_task(self._run_loop(), name="agent-traffic-supervisor")

    async def stop(self) -> None:
        task, self._loop_task = self._loop_task, None
        self._stopping = True
        self._wake.set()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for run_id in tuple(self._attached):
            mapping = await asyncio.to_thread(self.repository.get_agent_mapping, run_id)
            if mapping is not None:
                try:
                    await asyncio.to_thread(self.adapter.mark_sync_state, mapping, TrafficSyncState.STALE)
                except Exception:
                    pass
            self.detach(run_id)

    async def recover_active_runs(self) -> tuple[str, ...]:
        mappings = await asyncio.to_thread(self.repository.list_recoverable_agent_mappings)
        recovered: list[str] = []
        for mapping in mappings:
            try:
                await asyncio.to_thread(self.adapter.ensure_sync_ready, mapping)
            except TrafficTestError as exc:
                state = _sync_state_for_error(exc)
                await asyncio.to_thread(
                    self.adapter.mark_sync_state,
                    mapping,
                    state,
                    error_code=exc.code,
                    error_message=exc.message,
                )
                continue
            self.attach(mapping.traffic_run_id)
            recovered.append(mapping.traffic_run_id)
        return tuple(recovered)

    async def _run_loop(self) -> None:
        while not self._stopping:
            now = time.monotonic()
            due = sorted(
                (run_id for run_id in self._attached if self._next_poll.get(run_id, 0.0) <= now),
                key=lambda item: self._next_poll.get(item, 0.0),
            )[: self.settings.max_concurrency]
            if due:
                await asyncio.gather(*(self._poll_one(run_id) for run_id in due), return_exceptions=True)
                continue
            timeout = self._wait_timeout(now)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=timeout)
            except TimeoutError:
                pass

    async def _poll_one(self, run_id: str) -> None:
        mapping = await asyncio.to_thread(self.repository.get_agent_mapping, run_id)
        if mapping is None:
            self.detach(run_id)
            return
        try:
            outcome = await self.adapter.sync_once(
                mapping,
                event_limit=self.settings.event_page_size,
                max_event_pages=self.settings.max_event_pages_per_poll,
            )
        except TrafficTestError as exc:
            await self._handle_error(mapping, exc)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_error(
                mapping,
                TrafficTestError(TrafficErrorCode.REMOTE_SYNC_FAILED, str(exc) or "远端任务同步失败", retryable=True),
            )
            return

        self._failures.pop(run_id, None)
        self._last_error_codes.pop(run_id, None)
        if outcome.terminal:
            self.detach(run_id)
            return
        delay = 0.0 if outcome.has_more else self.settings.poll_interval_seconds
        self._next_poll[run_id] = time.monotonic() + delay

    async def _handle_error(self, mapping: AgentTaskMapping, error: TrafficTestError) -> None:
        run_id = mapping.traffic_run_id
        failures = self._failures.get(run_id, 0) + 1 if self._last_error_codes.get(run_id) == error.code else 1
        self._failures[run_id] = failures
        self._last_error_codes[run_id] = error.code
        state = _sync_state_for_error(error)
        try:
            await asyncio.to_thread(
                self.adapter.mark_sync_state,
                mapping,
                state,
                error_code=error.code,
                error_message=error.message,
            )
        except Exception:
            pass

        if error.code == TrafficErrorCode.RESULT_NOT_FOUND.value and failures >= self.settings.result_retry_limit:
            try:
                await asyncio.to_thread(self.adapter.fail_sync, mapping, error)
            finally:
                self.detach(run_id)
            return
        if state in {TrafficSyncState.CREDENTIAL_REQUIRED, TrafficSyncState.STALE}:
            self.detach(run_id)
            return
        if not error.retryable:
            if error.code == TrafficErrorCode.REMOTE_TASK_NOT_FOUND.value:
                try:
                    await asyncio.to_thread(self.adapter.fail_sync, mapping, error)
                finally:
                    self.detach(run_id)
            else:
                self.detach(run_id)
            return
        backoff = min(
            self.settings.max_backoff_seconds,
            self.settings.poll_interval_seconds * (2 ** min(failures - 1, 10)),
        )
        self._next_poll[run_id] = time.monotonic() + backoff

    def _wait_timeout(self, now: float) -> float:
        if not self._attached:
            return self.settings.poll_interval_seconds
        next_due = min(self._next_poll.get(run_id, now) for run_id in self._attached)
        return max(0.01, min(self.settings.poll_interval_seconds, next_due - now))


def _sync_state_for_error(error: TrafficTestError) -> TrafficSyncState:
    if error.code == TrafficErrorCode.AGENT_CREDENTIAL_REQUIRED.value:
        return TrafficSyncState.CREDENTIAL_REQUIRED
    if error.code in {TrafficErrorCode.AGENT_DISABLED.value, TrafficErrorCode.AGENT_NOT_FOUND.value}:
        return TrafficSyncState.STALE
    if error.code in {TrafficErrorCode.AGENT_OFFLINE.value, TrafficErrorCode.CONNECTION_TIMEOUT.value}:
        return TrafficSyncState.AGENT_OFFLINE
    return TrafficSyncState.ERROR


__all__ = ["AgentTrafficSupervisor", "AgentTrafficSupervisorSettings"]
