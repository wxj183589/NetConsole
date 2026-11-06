"""独立的人工快速 Ping 运行时。

快速 Ping 是诊断任务，不能复用 Fleet Ping 的 supervisor、统计或 raw writer。
本模块只依赖已有的 fping v5 runner 和 PathResolver 提供的受管目录；每个 run
拥有自己的停止事件、统计状态和 NDJSON 分片。
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import ipaddress
import json
import os
import queue
import threading
import time
import uuid
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.core.ping.fping_v5_runner import run_fping_v5_json
from netconsole.services.ground_unattended.quick_ping_ownership import matching_process, orphan_fping_children, process_identity

try:
    from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
except ImportError:  # pragma: no cover - import cycle protection for type checkers
    GroundUnattendedRepository = Any  # type: ignore[misc,assignment]


QUICK_PING_STATES = (
    "RUNNING",
    "STOPPING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIME_LIMIT",
    "INTERRUPTED",
)
MAX_QUICK_PING_TARGETS = 32
MAX_QUICK_PING_ACTIVE_RUNS = 4
MAX_RETAINED_QUICK_PING_RUNS = 500
QUICK_PING_SEGMENT_BYTES = 10 * 1024 * 1024


class QuickPingError(ValueError):
    """快速 Ping 输入或运行态错误。"""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class QuickPingConfig:
    interval_ms: int = 200
    timeout_ms: int = 1000
    packet_size: int = 64
    duration_seconds: float | None = None
    max_in_flight: int = 32

    def __post_init__(self) -> None:
        if not 1 <= int(self.interval_ms) <= 60_000:
            raise QuickPingError("QUICK_PING_INTERVAL_INVALID", "Ping 间隔必须为 1-60000ms")
        if not 1 <= int(self.timeout_ms) <= 60_000:
            raise QuickPingError("QUICK_PING_TIMEOUT_INVALID", "Ping 超时必须为 1-60000ms")
        if not 1 <= int(self.packet_size) <= 65_507:
            raise QuickPingError("QUICK_PING_PACKET_SIZE_INVALID", "ICMP 包大小必须为 1-65507 Bytes")
        if self.duration_seconds is not None and not 0 < float(self.duration_seconds) <= 7 * 24 * 3600:
            raise QuickPingError("QUICK_PING_DURATION_INVALID", "测试时长必须大于 0 且不超过 7 天")
        if not 1 <= int(self.max_in_flight) <= 32:
            raise QuickPingError("QUICK_PING_CONCURRENCY_INVALID", "快速 Ping 并发上限必须为 1-32")


@dataclass(frozen=True)
class QuickPingTarget:
    target_ip: str
    train_id: str = ""
    mr_id: str = ""
    mr_role: str = ""
    address_role: str = "PRIMARY"
    train_no: str = ""
    mr_name: str = ""

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(str(self.target_ip).strip())
        except ValueError as exc:
            raise QuickPingError("QUICK_PING_TARGET_INVALID", f"目标 IP 无效: {self.target_ip}") from exc
        if address.version != 4:
            raise QuickPingError("QUICK_PING_TARGET_INVALID", "快速 Ping 只接受 IPv4 目标")
        object.__setattr__(self, "target_ip", str(address))
        if self.address_role not in {"PRIMARY", "BACKUP"}:
            raise QuickPingError("QUICK_PING_ADDRESS_ROLE_INVALID", "地址角色必须为 PRIMARY 或 BACKUP")
        if not str(self.mr_id).strip():
            raise QuickPingError("QUICK_PING_MR_ID_REQUIRED", "快速 Ping 目标必须带 MR UUID")


@dataclass
class QuickPingStats:
    raw_samples: int = 0
    sent: int = 0
    received: int = 0
    lost: int = 0
    rtt_sum_ms: float = 0.0
    min_rtt_ms: float | None = None
    max_rtt_ms: float | None = None
    jitter_sum_ms: float = 0.0
    jitter_count: int = 0
    current_consecutive_loss: int = 0
    max_consecutive_loss: int = 0
    last_sample_at: str = ""
    last_success_at: str = ""
    _previous_success_rtt: float | None = field(default=None, repr=False)
    current_rtt_ms: float | None = None

    def add(self, sample: FpingV5Sample) -> None:
        if sample.ok is None:
            return
        self.raw_samples += 1
        self.last_sample_at = sample.ts
        self.sent += 1
        self.current_rtt_ms = sample.rtt_ms if sample.ok else None
        if sample.ok:
            self.received += 1
            self.current_consecutive_loss = 0
            self.last_success_at = sample.ts
            if sample.rtt_ms is not None:
                rtt = float(sample.rtt_ms)
                self.rtt_sum_ms += rtt
                self.min_rtt_ms = rtt if self.min_rtt_ms is None else min(self.min_rtt_ms, rtt)
                self.max_rtt_ms = rtt if self.max_rtt_ms is None else max(self.max_rtt_ms, rtt)
                if self._previous_success_rtt is not None:
                    self.jitter_sum_ms += abs(rtt - self._previous_success_rtt)
                    self.jitter_count += 1
                self._previous_success_rtt = rtt
        else:
            self.lost += 1
            self.current_consecutive_loss += 1
            self.max_consecutive_loss = max(self.max_consecutive_loss, self.current_consecutive_loss)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_samples": self.raw_samples,
            "sent": self.sent,
            "received": self.received,
            "lost": self.lost,
            "loss_rate_percent": (self.lost * 100.0 / self.sent) if self.sent else 0.0,
            "min_rtt_ms": self.min_rtt_ms,
            "avg_rtt_ms": (self.rtt_sum_ms / self.received) if self.received else None,
            "max_rtt_ms": self.max_rtt_ms,
            "jitter_ms": (self.jitter_sum_ms / self.jitter_count) if self.jitter_count else None,
            "current_consecutive_loss": self.current_consecutive_loss,
            "max_consecutive_loss": self.max_consecutive_loss,
            "last_sample_at": self.last_sample_at,
            "last_success_at": self.last_success_at,
            "current_rtt_ms": self.current_rtt_ms,
        }


class _QuickPingSegmentWriter:
    def __init__(self, root: Path, *, max_bytes: int = QUICK_PING_SEGMENT_BYTES, on_closed: Callable[[Path], None] | None = None) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self._file: Any = None
        self._path: Path | None = None
        self._hour = ""
        self._index = 0
        self.paths: list[str] = []
        self.on_closed = on_closed

    def write(self, payload: dict[str, Any], timestamp: str) -> None:
        hour = _timestamp_hour(timestamp)
        encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if self._file is None or hour != self._hour or self._path is None or self._path.stat().st_size + len(encoded) > self.max_bytes:
            self._close()
            self._open(hour)
        self._file.write(encoded.decode("utf-8"))
        self._file.flush()

    def close(self) -> None:
        self._close()

    def _open(self, hour: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._hour = hour
        suffix = "" if self._index == 0 else f"_{self._index}"
        self._path = self.root / f"quick_ping_{hour}{suffix}.ndjson"
        self._file = self._path.open("a", encoding="utf-8", newline="\n")
        if self._path.as_posix() not in self.paths:
            self.paths.append(self._path.as_posix())
        self._index += 1

    def _close(self) -> None:
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None
            closed_path = self._path
            self._path = None
            if closed_path is not None and self.on_closed is not None:
                self.on_closed(closed_path)


class _QuickPingCompressionWorker:
    """One bounded queue per active run; collection never compresses a file."""

    def __init__(self, service: QuickPingService, run: QuickPingRun) -> None:
        self.service, self.run = service, run
        self.queue: queue.Queue[Path] = queue.Queue(maxsize=64)
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._work, name="quick-ping-compressor", daemon=True)
        self.thread.start()

    def submit(self, path: Path) -> None:
        try:
            self.queue.put_nowait(path)
        except queue.Full:
            self.service._storage_error(self.run.run_id, "QUICK_PING_COMPRESSION_QUEUE_FULL", "压缩队列已满，保留原始文件")

    def stop(self) -> None:
        self.stopping.set()
        # Called only by the collection thread, never the API or UI thread.
        self.thread.join()

    def _work(self) -> None:
        while not self.stopping.is_set() or not self.queue.empty():
            try:
                path = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.service._compress_segment(self.run.run_id, path)
            except Exception as exc:
                self.service._storage_error(self.run.run_id, "QUICK_PING_COMPRESSION_FAILED", f"{type(exc).__name__}: {exc}")
            finally:
                self.queue.task_done()


@dataclass
class QuickPingRun:
    run_id: str
    site_id: str
    run_date: str
    targets: tuple[QuickPingTarget, ...]
    config: QuickPingConfig
    state: str = "RUNNING"
    started_at: str = ""
    ended_at: str = ""
    error: str = ""
    segment_paths: list[str] = field(default_factory=list)
    stats: QuickPingStats = field(default_factory=QuickPingStats)
    target_stats: dict[str, QuickPingStats] = field(default_factory=dict)
    recent_samples: list[dict[str, Any]] = field(default_factory=list)
    target_runtime: dict[str, dict[str, Any]] = field(default_factory=dict)
    _target_stops: dict[str, threading.Event] = field(default_factory=dict, repr=False)
    _target_threads: dict[str, threading.Thread] = field(default_factory=dict, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _persistence_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _last_persist_monotonic: float = field(default=0.0, repr=False)
    _active_segment_paths: dict[str, str] = field(default_factory=dict, repr=False)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "site_id": self.site_id,
                "run_date": self.run_date,
                "targets": [target.__dict__.copy() for target in self.targets],
                "config": self.config.__dict__.copy(),
                "state": self.state,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "error": self.error,
                "segment_paths": list(self.segment_paths),
                "stats": self.stats.as_dict(),
                "target_stats": {key: value.as_dict() for key, value in self.target_stats.items()},
                "recent_samples": list(self.recent_samples[-256:]),
                "target_runtime": {ip: dict(value) for ip, value in self.target_runtime.items()},
            }


def _maintain_quick_ping_storage(service_ref: Any, stopping: threading.Event) -> None:
    """Run at startup and hourly without retaining an unused Site service."""
    while not stopping.is_set():
        service = service_ref()
        if service is None:
            return
        service.apply_retention()
        del service
        if stopping.wait(3600):
            return


class QuickPingService:
    """受管的快速 Ping 任务集合，运行状态与 Fleet Ping 完全隔离。"""
    _reservation_guard = threading.RLock()
    _memory_reservations: dict[tuple[str, str], str] = {}
    _worker_slots = threading.BoundedSemaphore(4)

    def __init__(
        self,
        *,
        site_id: str,
        output_root: Path,
        runner: Callable[..., Iterator[FpingV5Sample]] = run_fping_v5_json,
        max_active_runs: int = 4,
        repository: GroundUnattendedRepository | None = None,
        persist_interval_seconds: float = 1.0,
    ) -> None:
        if not site_id or Path(site_id).name != site_id or "/" in site_id or "\\" in site_id:
            raise ValueError("invalid quick ping site id")
        if not 1 <= int(max_active_runs) <= MAX_QUICK_PING_ACTIVE_RUNS:
            raise ValueError(f"max_active_runs must be between 1 and {MAX_QUICK_PING_ACTIVE_RUNS}")
        self.site_id = site_id
        self.output_root = Path(output_root)
        self.runner = runner
        self.max_active_runs = int(max_active_runs)
        self.repository = repository
        self.persist_interval_seconds = max(0.25, float(persist_interval_seconds))
        self._lock = threading.RLock()
        self._retention_lock = threading.Lock()
        self._runs: dict[str, QuickPingRun] = {}
        self._restore_runs()
        self._maintenance_stop = threading.Event()
        self._maintenance_thread: threading.Thread | None = None
        if self.repository is not None:
            self._maintenance_thread = threading.Thread(
                target=_maintain_quick_ping_storage,
                args=(weakref.ref(self), self._maintenance_stop),
                name="quick-ping-retention", daemon=True,
            )
            self._maintenance_thread.start()

    def start(
        self,
        *,
        targets: list[QuickPingTarget] | tuple[QuickPingTarget, ...],
        run_date: str | None = None,
        config: QuickPingConfig | None = None,
    ) -> str:
        config = config or QuickPingConfig()
        if len(targets) > MAX_QUICK_PING_TARGETS:
            raise QuickPingError(
                "QUICK_PING_TARGET_LIMIT",
                f"快速 Ping 每个任务最多选择 {MAX_QUICK_PING_TARGETS} 个目标",
            )
        normalized = _dedupe_targets(targets)
        if not normalized:
            raise QuickPingError("QUICK_PING_TARGETS_REQUIRED", "至少选择一个快速 Ping 目标")
        interval_ms = max(1, (config.timeout_ms + config.max_in_flight - 1) // config.max_in_flight)
        if interval_ms > config.interval_ms:
            raise QuickPingError(
                "QUICK_PING_CONCURRENCY_LIMIT",
                "目标数、超时和并发上限无法同时满足配置的每目标 Ping 间隔",
                status_code=409,
            )
        date_value = str(run_date or date.today().isoformat())
        try:
            datetime.strptime(date_value, "%Y-%m-%d")
        except ValueError as exc:
            raise QuickPingError("QUICK_PING_RUN_DATE_INVALID", "run_date 必须为 YYYY-MM-DD") from exc
        with self._lock:
            self._recover_reservations()
            for cached_id in list(self._runs):
                self.status(cached_id)
            active_runs = [run for run in self._runs.values() if run.state in {"RUNNING", "STOPPING"} or (run._thread is not None and run._thread.is_alive())]
            active = len(active_runs)
            if active >= self.max_active_runs:
                raise QuickPingError("QUICK_PING_ACTIVE_LIMIT", "快速 Ping 活动任务数已达到上限", status_code=409)
            run_id = f"quick-ping-{uuid.uuid4().hex}"
            self._reserve_ips(run_id, [target.target_ip for target in normalized])
            run = QuickPingRun(
                run_id=run_id,
                site_id=self.site_id,
                run_date=date_value,
                targets=tuple(normalized),
                config=config,
                started_at=_now(),
                target_stats={target.target_ip: QuickPingStats() for target in normalized},
                target_runtime={target.target_ip: {"state": "QUEUED", "started_at": "", "ended_at": "", "error": ""} for target in normalized},
                _target_stops={target.target_ip: threading.Event() for target in normalized},
            )
            self._runs[run_id] = run
            try:
                self._write_manifest(run)
                self._persist_run(run, event_type="STARTED", force=True)
            except Exception as exc:
                run.state = "FAILED"
                run.error = f"initial persistence failed: {exc.__class__.__name__}: {exc}"
                run.ended_at = _now()
                try:
                    self._persist_run(run, event_type="FAILED", force=True)
                except Exception:
                    pass
                self._trim_runs_locked()
                for target in run.targets:
                    self._release_ip(run.run_id, target.target_ip)
                raise QuickPingError(
                    "QUICK_PING_MANIFEST_WRITE_FAILED",
                    "快速 Ping 任务记录无法写入",
                    status_code=503,
                ) from exc
            run._thread = threading.Thread(target=self._run, args=(run,), name=f"quick-ping-{run_id[-8:]}", daemon=True)
            try:
                run._thread.start()
            except Exception as exc:
                run.state = "FAILED"
                run.error = f"{exc.__class__.__name__}: {exc}"
                run.ended_at = _now()
                try:
                    self._write_manifest(run)
                except Exception:
                    pass
                try:
                    self._persist_run(run, event_type="FAILED_TO_START", force=True)
                except Exception:
                    pass
                self._trim_runs_locked()
                for target in run.targets:
                    self._release_ip(run.run_id, target.target_ip)
                raise QuickPingError(
                    "QUICK_PING_START_FAILED",
                    "快速 Ping 任务无法启动",
                    status_code=503,
                ) from exc
            self._trim_runs_locked()
            return run_id

    def stop(self, run_id: str, *, wait_seconds: float = 5.0) -> QuickPingRun:
        changed = False
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise QuickPingError("QUICK_PING_NOT_FOUND", "快速 Ping 任务不存在", status_code=404)
            with run._lock:
                if run.state == "RUNNING":
                    if not run._target_stops:
                        raise QuickPingError("QUICK_PING_OWNER_UNAVAILABLE", "任务由另一 Backend 实例运行，请从原实例停止", status_code=409)
                    run.state = "STOPPING"
                    run._stop_event.set()
                    for event in run._target_stops.values():
                        event.set()
                    changed = True
            thread = run._thread
        if changed:
            self._persist_run(run, event_type="STOPPING", force=True)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(wait_seconds)))
        return self.status(run_id)  # type: ignore[return-value]

    def stop_target(self, run_id: str, target_ip: str, *, wait_seconds: float = 5.0) -> QuickPingRun:
        run = self.status(run_id)
        if run is None:
            raise QuickPingError("QUICK_PING_NOT_FOUND", "快速 Ping 任务不存在", status_code=404)
        try:
            target_ip = str(ipaddress.ip_address(target_ip.strip()))
        except ValueError as exc:
            raise QuickPingError("QUICK_PING_TARGET_INVALID", "目标 IP 无效") from exc
        with run._lock:
            runtime = run.target_runtime.get(target_ip)
            if runtime is None:
                raise QuickPingError("QUICK_PING_TARGET_INVALID", "目标 IP 不属于该任务", status_code=404)
            if runtime["state"] in {"QUEUED", "STARTING", "RUNNING", "STOPPING"}:
                if target_ip not in run._target_stops:
                    raise QuickPingError("QUICK_PING_OWNER_UNAVAILABLE", "任务由另一 Backend 实例运行，请从原实例停止", status_code=409)
                runtime["state"] = "STOPPING"
                run._target_stops[target_ip].set()
        self._persist_run(run, event_type="TARGET_STOPPING", force=True)
        thread = run._target_threads.get(target_ip)
        if thread is not None:
            thread.join(timeout=max(0, wait_seconds))
        return run

    def status(self, run_id: str) -> QuickPingRun | None:
        with self._lock:
            run = self._runs.get(run_id)
        if self.repository is None or (run is not None and (run._thread is not None or run.state not in {"RUNNING", "STOPPING"})):
            return run
        try:
            value = self.repository.get_quick_ping_run(run_id)
            if value is None:
                return None
            run = _run_from_manifest(value, self.site_id)
        except (KeyError, TypeError, ValueError, OSError):
            return None
        with self._lock:
            self._runs[run.run_id] = run
            self._trim_runs_locked()
        return run

    def list_runs(self, *, limit: int = 100) -> list[QuickPingRun]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            return list(reversed(list(self._runs.values())))[:limit]

    def active_ips(self) -> dict[str, str]:
        if self.repository is not None:
            return {row["target_ip"]: row["run_id"] for row in self.repository.quick_ping_reservations()}
        with self._reservation_guard:
            return {ip: owner for (root, ip), owner in self._memory_reservations.items() if root == str(self.output_root.resolve())}

    def query_runs(
        self, *, limit: int = 50, offset: int = 0, start_time: str = "", end_time: str = "",
        query: str = "", state: str = "", train_id: str = "", mr_id: str = "", mr_role: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        start, end = _query_time_range(start_time, end_time)
        if state and state not in QUICK_PING_STATES:
            raise QuickPingError("QUICK_PING_FILTER_INVALID", "快速 Ping 状态筛选无效")
        if self.repository is not None:
            values, total = self.repository.query_quick_ping_runs(
                limit=limit, offset=offset, start_time=start_time, end_time=end_time,
                query=query, state=state, train_id=train_id, mr_id=mr_id, mr_role=mr_role,
            )
            with self._lock:
                live = {run_id: run for run_id, run in self._runs.items() if run._thread is not None}
            return [live[value["run_id"]].as_dict() if value["run_id"] in live else value for value in values], total
        with self._lock:
            values = [run.as_dict() for run in self._runs.values()]
        def matches(value: dict[str, Any]) -> bool:
            stamp = _query_timestamp(str(value["started_at"]))
            return (
                (start is None or stamp >= start) and (end is None or stamp <= end)
                and (not state or value["state"] == state)
                and (not query or query.casefold() in (
                    value["run_id"] + " " + value["started_at"] + " "
                    + json.dumps(value["targets"], ensure_ascii=False)
                ).casefold())
                and any(
                    (not train_id or target["train_id"] == train_id)
                    and (not mr_id or target["mr_id"] == mr_id)
                    and (not mr_role or target["mr_role"] == mr_role)
                    for target in value["targets"]
                )
            )
        values = sorted((value for value in values if matches(value)), key=lambda value: (_query_timestamp(value["started_at"]), value["run_id"]), reverse=True)
        offset, limit = max(0, int(offset)), max(1, min(500, int(limit)))
        return values[offset:offset + limit], len(values)

    def query_samples(
        self, run_id: str, *, target_ip: str = "", start_time: str = "", end_time: str = "",
        limit: int = 1000, cursor: str = "", scan_budget_bytes: int = 4 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Page through NDJSON with bounded IO/memory; samples stay outside SQLite."""
        run = self.status(run_id)
        if run is None:
            raise QuickPingError("QUICK_PING_NOT_FOUND", "快速 Ping 任务不存在", status_code=404)
        start, end = _query_time_range(start_time, end_time)
        with run._lock:
            snapshot = run.as_dict()
            active_paths = set(run._active_segment_paths.values())
        if target_ip and target_ip not in {target["target_ip"] for target in snapshot["targets"]}:
            raise QuickPingError("QUICK_PING_TARGET_INVALID", "目标地址不属于该快速 Ping 任务")
        fingerprint = hashlib.sha256(json.dumps(
            [self.site_id, run_id, target_ip, start_time, end_time], ensure_ascii=False,
        ).encode("utf-8")).hexdigest()[:24]
        index, offset, checkpoints, turn = _decode_sample_cursor(cursor, fingerprint) if cursor else (0, 0, {}, 0)
        paths = snapshot["segment_paths"]
        if index > len(paths) or any(saved >= index for saved in checkpoints):
            raise QuickPingError("QUICK_PING_CURSOR_INVALID", "快速 Ping 样本游标已失效")
        items: list[dict[str, Any]] = []
        scanned = 0
        limit = max(1, min(2000, int(limit)))
        budget = max(1, min(int(scan_budget_bytes), 4 * 1024 * 1024))
        root = self.output_root.resolve()
        visited: set[int] = set()
        while len(items) < limit and scanned < budget:
            candidates = sorted(saved for saved in checkpoints if saved not in visited)
            if index < len(paths) and index not in visited:
                candidates.append(index)
            if not candidates:
                break
            selected = next((saved for saved in candidates if saved >= turn), candidates[0])
            visited.add(selected)
            turn = selected + 1
            position = checkpoints[selected] if selected in checkpoints else offset
            path = self.output_root / paths[selected]
            if not path.resolve().is_relative_to(root / "quick_ping") or path.suffix != ".ndjson":
                raise QuickPingError("QUICK_PING_RAW_PATH_INVALID", "快速 Ping 原始文件路径无效", status_code=503)
            try:
                with self._open_segment(run_id, path) as (handle, size):
                    if position > size:
                        raise QuickPingError("QUICK_PING_CURSOR_INVALID", "快速 Ping 原始文件已改变")
                    handle.seek(position)
                    while handle.tell() < size and len(items) < limit and scanned < budget:
                        line_start = handle.tell()
                        line = handle.readline(min(65537, size - line_start))
                        if len(line) >= 65537:
                            raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 原始记录超过大小限制", status_code=503)
                        if not line.endswith(b"\n"):
                            if is_active_quick_ping(snapshot) and handle.tell() == size:
                                break
                            raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 原始记录不完整或超过大小限制", status_code=503)
                        position = handle.tell()
                        scanned += len(line)
                        value = json.loads(line)
                        if not isinstance(value, dict) or value.get("quick_ping_run_id") != run_id or value.get("site_id") != self.site_id:
                            raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 原始记录身份校验失败", status_code=503)
                        if target_ip and value.get("target_ip") != target_ip:
                            continue
                        try:
                            stamp = _query_timestamp(str(value.get("received_at") or ""))
                        except QuickPingError as exc:
                            raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 原始记录时间无效", status_code=503) from exc
                        if (start is None or stamp >= start) and (end is None or stamp <= end):
                            items.append(value)
                    active = paths[selected] in active_paths
                    if selected in checkpoints:
                        if position >= size and not active:
                            del checkpoints[selected]
                        else:
                            checkpoints[selected] = position
                    elif active and len(checkpoints) < MAX_QUICK_PING_TARGETS:
                        # Keep each live file's logical offset while visiting other MRs.
                        # Retired checkpoints disappear at EOF, regardless of gzip rotation.
                        checkpoints[selected] = position
                        index, offset = index + 1, 0
                    elif position >= size and not active:
                        index, offset = index + 1, 0
                    else:
                        offset = position
            except (OSError, EOFError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                if isinstance(exc, QuickPingError):
                    raise
                raise QuickPingError("QUICK_PING_RAW_UNREADABLE", "快速 Ping 原始文件无法读取", status_code=503) from exc
        has_more = bool(checkpoints) or index < len(paths) or is_active_quick_ping(snapshot)
        return {
            "run_id": run_id, "items": items, "has_more": has_more,
            "next_cursor": _encode_sample_cursor(index, offset, fingerprint, checkpoints, turn) if has_more else "",
            "scanned_bytes": scanned, "scan_budget_exhausted": has_more and scanned >= budget,
        }

    def close(self) -> None:
        self._maintenance_stop.set()
        if self._maintenance_thread is not None:
            self._maintenance_thread.join(timeout=5)
        with self._lock:
            active_runs = [run for run in self._runs.values() if run._thread is not None and run._thread.is_alive()]
        for run in active_runs:
            if run.state in {"RUNNING", "STOPPING"}:
                try:
                    self.stop(run.run_id)
                except QuickPingError:
                    continue

    def _reserve_ips(self, run_id: str, ips: list[str]) -> None:
        with self._reservation_guard:
            root = "backend" if self.repository is not None else str(self.output_root.resolve())
            conflict = next(({"target_ip": ip, "run_id": self._memory_reservations[(root, ip)]} for ip in ips if (root, ip) in self._memory_reservations), None)
            if conflict is None and self.repository is not None:
                conflict = self.repository.reserve_quick_ping_ips(run_id, ips, owner_pid=os.getpid(), owner_identity=process_identity(os.getpid()), max_active_runs=self.max_active_runs)
            if conflict is None:
                self._memory_reservations.update(((root, ip), run_id) for ip in ips)
        if conflict:
            if conflict.get("limit"):
                raise QuickPingError("QUICK_PING_ACTIVE_LIMIT", "快速 Ping 活动任务数已达到上限", status_code=409)
            raise QuickPingError("QUICK_PING_DUPLICATE_ACTIVE", f"IP {conflict['target_ip']} 已由活动任务 {conflict['run_id']} 占用", status_code=409)

    def _release_ip(self, run_id: str, ip: str) -> None:
        if self.repository is not None:
            self.repository.release_quick_ping_ip(run_id, ip)
        with self._reservation_guard:
            key = ("backend" if self.repository is not None else str(self.output_root.resolve()), ip)
            if self._memory_reservations.get(key) == run_id:
                del self._memory_reservations[key]

    def _recover_reservations(self) -> None:
        if self.repository is None:
            return
        # A previous local disk failure may have retained a confirmed-exited
        # target. Retry its final result before allowing a replacement probe.
        for local in list(self._runs.values()):
            if local._thread is not None and not local._thread.is_alive():
                confirmed = [ip for ip, runtime in local.target_runtime.items() if runtime.get("_close_confirmed")]
                if confirmed:
                    self._write_manifest(local)
                    self._persist_run(local, event_type="FINALIZE_RETRIED", force=True)
                    for ip in confirmed:
                        self._release_ip(local.run_id, ip)
                        local.target_runtime[ip].pop("_close_confirmed", None)
        rows = self.repository.quick_ping_reservations()
        interrupted: dict[str, list[str]] = {}
        for row in rows:
            if row["site_id"] != self.site_id or matching_process(row["owner_pid"], row["owner_identity"]):
                continue
            if matching_process(row["child_pid"], row["child_identity"]) or orphan_fping_children(row["owner_pid"]):
                continue
            interrupted.setdefault(row["run_id"], []).append(row["target_ip"])
        for run_id, ips in interrupted.items():
            value = self.repository.get_quick_ping_run(run_id)
            if value is not None:
                run = _run_from_manifest(value, self.site_id)
                for ip in ips:
                    run.target_runtime.setdefault(ip, {}).update(state="INTERRUPTED", ended_at=_now(), error="Backend interrupted; previous fping exit confirmed")
                surviving = [row for row in rows if row["run_id"] == run_id and row["target_ip"] not in ips]
                if not surviving:
                    run.state, run.ended_at = "INTERRUPTED", _now()
                self._write_manifest(run)
                self._persist_run(run, event_type="INTERRUPTED", force=True)
                self._runs[run_id] = run
            for ip in ips:
                self._release_ip(run_id, ip)

    def _run(self, run: QuickPingRun) -> None:
        timer: threading.Timer | None = None
        compressor = _QuickPingCompressionWorker(self, run)
        if run.config.duration_seconds is not None:
            timer = threading.Timer(float(run.config.duration_seconds), self._time_limit, args=(run,))
            timer.daemon = True
            timer.start()
        pending = list(run.targets)
        try:
            while pending or any(thread.is_alive() for thread in run._target_threads.values()):
                for target in list(pending):
                    ip = target.target_ip
                    if run._target_stops[ip].is_set():
                        with run._lock:
                            run.target_runtime[ip].update(state="CANCELLED", ended_at=_now())
                        self._persist_run(run, event_type="TARGET_CANCELLED", force=True)
                        self._release_ip(run.run_id, ip)
                        pending.remove(target)
                        continue
                    if not self._worker_slots.acquire(blocking=False):
                        break
                    if self.repository is not None and not self.repository.claim_quick_ping_ip(run.run_id, ip):
                        self._worker_slots.release()
                        break
                    with run._lock:
                        run.target_runtime[ip].update(state="STARTING", started_at=_now())
                    worker = threading.Thread(target=self._run_target, args=(run, target, compressor), name=f"quick-ip-{ip}", daemon=True)
                    run._target_threads[ip] = worker
                    try:
                        worker.start()
                    except Exception:
                        self._worker_slots.release()
                        raise
                    pending.remove(target)
                run._stop_event.wait(0.025) if not run._stop_event.is_set() else time.sleep(0.025)
            with run._lock:
                states = {value["state"] for value in run.target_runtime.values()}
                if run.state != "TIME_LIMIT":
                    run.state = "FAILED" if "FAILED" in states else "CANCELLED" if "CANCELLED" in states else "COMPLETED"
        except Exception as exc:
            run._stop_event.set()
            for event in run._target_stops.values():
                event.set()
            for thread in run._target_threads.values():
                if thread.ident is not None:
                    thread.join()
            run.state, run.error = "FAILED", f"{type(exc).__name__}: {exc}"
            for target in pending:
                run.target_runtime[target.target_ip].update(state="FAILED", ended_at=_now(), error=run.error, _close_confirmed=True)
        finally:
            if timer is not None:
                timer.cancel()
            compressor.stop()
            with run._lock:
                run.ended_at = _now()
            try:
                self._write_manifest(run)
                self._persist_run(run, event_type=run.state, force=True)
                # Pending targets never spawned a child. Worker targets release only
                # after their own generator close and final persistence succeed.
                for target in pending:
                    self._release_ip(run.run_id, target.target_ip)
                for ip, runtime in run.target_runtime.items():
                    if runtime.get("_close_confirmed"):
                        self._release_ip(run.run_id, ip)
                        runtime.pop("_close_confirmed", None)
            except Exception as exc:
                run.error = _append_error(run.error, f"final persistence failed: {exc}")
                self._storage_error(run.run_id, "QUICK_PING_PERSISTENCE_FAILED", run.error)
            self.apply_retention()

    def _run_target(self, run: QuickPingRun, target: QuickPingTarget, compressor: _QuickPingCompressionWorker) -> None:
        ip = target.target_ip
        stream: Iterator[FpingV5Sample] | None = None
        writer = _QuickPingSegmentWriter(self._run_output_root(run, target), on_closed=compressor.submit)
        runtime = run.target_runtime[ip]
        terminal, error = "COMPLETED", ""
        closed = True
        try:
            kwargs: dict[str, Any] = dict(target=ip, targets=[ip], period_ms=run.config.interval_ms, timeout_ms=run.config.timeout_ms, packet_size=run.config.packet_size,
                                          interval_ms=max(1, (run.config.timeout_ms + run.config.max_in_flight - 1) // run.config.max_in_flight), count_json=None, stop_event=run._target_stops[ip])
            if self.runner is run_fping_v5_json:
                def observe(process: Any) -> None:
                    identity = process_identity(process.pid)
                    if not identity:
                        raise RuntimeError("Cannot establish fping process identity")
                    if self.repository is not None:
                        self.repository.record_quick_ping_child(run.run_id, ip, process.pid, identity)
                kwargs["process_observer"] = observe
            with run._lock:
                runtime["state"] = "RUNNING"
            self._persist_run(run, event_type="TARGET_RUNNING", force=True)
            stream = self.runner(**kwargs)
            for raw_sample in stream:
                if run._target_stops[ip].is_set():
                    break
                sample = _coerce_sample(raw_sample, run.config.timeout_ms)
                if sample.target != ip:
                    raise ValueError(f"unexpected quick Ping sample target: {sample.target}")
                self._record_sample(run, writer, sample)
            if run._target_stops[ip].is_set():
                terminal = "CANCELLED"
        except Exception as exc:
            terminal = "CANCELLED" if run._target_stops[ip].is_set() else "FAILED"
            error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
                writer.close()
            except Exception as exc:
                closed, terminal, error = False, "FAILED", f"runner/writer close failed: {exc}"
            with run._lock:
                runtime.update(state=terminal, ended_at=_now(), error=error)
                runtime["_close_confirmed"] = closed
                if error:
                    run.error = _append_error(run.error, f"{ip}: {error}")
                run._active_segment_paths.pop(ip, None)
            try:
                self._write_manifest(run)
                self._persist_run(run, event_type=f"TARGET_{terminal}", force=True)
                if closed:
                    self._release_ip(run.run_id, ip)
                    runtime.pop("_close_confirmed", None)
            except Exception as exc:
                with run._lock:
                    runtime["state"] = "FAILED"
                    runtime["error"] = f"final persistence failed: {exc}"
                    run.error = _append_error(run.error, runtime["error"])
                self._storage_error(run.run_id, "QUICK_PING_TARGET_FINALIZE_FAILED", f"{ip}: {exc}")
            finally:
                self._worker_slots.release()

    def _storage_error(self, run_id: str, code: str, message: str) -> None:
        if self.repository is not None:
            try:
                self.repository.add_health_event(run_id=run_id, component="quick_ping_storage", severity="error", code=code, message=message)
            except Exception:
                pass

    def _managed_segment(self, path: Path) -> Path:
        resolved = self._managed_path(path)
        if resolved.suffix != ".ndjson":
            raise QuickPingError("QUICK_PING_RAW_PATH_INVALID", "快速 Ping 原始文件路径无效", status_code=503)
        return resolved

    def _managed_path(self, path: Path) -> Path:
        root = self.output_root.resolve() / "quick_ping"
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise QuickPingError("QUICK_PING_RAW_PATH_INVALID", "快速 Ping 原始文件路径无效", status_code=503)
        for candidate in (path, *path.parents):
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                raise QuickPingError("QUICK_PING_RAW_PATH_INVALID", "快速 Ping 原始文件不能经过链接目录", status_code=503)
            if candidate == self.output_root:
                break
        return resolved

    def _compress_segment(self, run_id: str, path: Path) -> None:
        path = self._managed_segment(path)
        target = path.with_name(path.name + ".gz")
        metadata_path = target.with_name(target.name + ".json")
        temporary = target.with_name(target.name + ".part")
        metadata_temp = metadata_path.with_name(metadata_path.name + ".part")
        for candidate in (target, metadata_path, temporary, metadata_temp):
            self._managed_path(candidate)
        try:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as source, temporary.open("wb") as output:
                with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                        compressed.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            verified = hashlib.sha256()
            verified_size = 0
            with gzip.open(temporary, "rb") as compressed:
                for chunk in iter(lambda: compressed.read(1024 * 1024), b""):
                    verified_size += len(chunk)
                    verified.update(chunk)
            if verified_size != size or verified.digest() != digest.digest():
                raise ValueError("compressed Quick Ping segment failed SHA-256 verification")
            metadata = {"site_id": self.site_id, "run_id": run_id, "size_bytes": size, "sha256": digest.hexdigest(), "gzip_sha256": _file_sha256(temporary)}
            metadata_temp.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
            temporary.replace(target)
            metadata_temp.replace(metadata_path)
            path.unlink()
        finally:
            temporary.unlink(missing_ok=True)
            metadata_temp.unlink(missing_ok=True)

    @contextmanager
    def _open_segment(self, run_id: str, path: Path) -> Iterator[tuple[Any, int]]:
        path = self._managed_segment(path)
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            target = path.with_name(path.name + ".gz")
            metadata_path = target.with_name(target.name + ".json")
            self._managed_path(target)
            self._managed_path(metadata_path)
            # Publication retains the raw file until both verified files exist.
            # Logical cursor offsets refer to uncompressed bytes and survive rotation.
            if metadata_path.stat().st_size > 65536 or target.stat().st_size > QUICK_PING_SEGMENT_BYTES + 131072:
                raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 压缩分段超过大小限制", status_code=503)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            size = int(metadata["size_bytes"])
            if metadata.get("site_id") != self.site_id or metadata.get("run_id") != run_id or not 0 <= size <= QUICK_PING_SEGMENT_BYTES + 65536:
                raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 压缩分段身份或大小无效", status_code=503)
            if target.is_symlink() or metadata_path.is_symlink() or _file_sha256(target) != metadata.get("gzip_sha256"):
                raise QuickPingError("QUICK_PING_RAW_CORRUPT", "快速 Ping 压缩分段校验失败", status_code=503)
            with gzip.open(target, "rb") as compressed:
                yield compressed, size
        else:
            with handle:
                yield handle, os.fstat(handle.fileno()).st_size

    def apply_retention(self, *, now: datetime | None = None) -> None:
        """Background maintenance of registered terminal runs; no directory guessing.

        The live Site profile supplies ping_raw_retention_days and
        summary_retention_days on every pass. Run events remain durable.
        """
        if self.repository is None or not self._retention_lock.acquire(blocking=False):
            return
        try:
            profile = self.repository.get_profile()
            current = now or datetime.now(timezone.utc)
            raw_cutoff = current - timedelta(days=profile.ping_raw_retention_days)
            summary_cutoff = current - timedelta(days=profile.summary_retention_days)
            offset = 0
            while True:
                records, total = self.repository.query_quick_ping_runs(limit=500, offset=offset)
                deleted = 0
                for record in records:
                    if record["state"] not in {"COMPLETED", "FAILED", "CANCELLED", "TIME_LIMIT", "INTERRUPTED"} or not record.get("ended_at"):
                        continue
                    try:
                        ended = datetime.fromisoformat(record["ended_at"].replace("Z", "+00:00"))
                        if ended.tzinfo is None or ended >= raw_cutoff:
                            continue
                        # Validate the complete registered set before deleting any file.
                        paths = [self._managed_segment(self.output_root / value) for value in record["segment_paths"]]
                        manifest = self._managed_path(self.output_root / "quick_ping" / record["run_date"] / "runs" / f"{_safe_segment(record['run_id'])}.json")
                        if manifest.exists():
                            identity = json.loads(manifest.read_text(encoding="utf-8"))
                            if identity.get("site_id") != self.site_id or identity.get("run_id") != record["run_id"]:
                                raise ValueError("retention manifest identity mismatch")
                        for path in paths:
                            gzip_path = path.with_name(path.name + ".gz")
                            sidecar = gzip_path.with_name(gzip_path.name + ".json")
                            for candidate in (gzip_path, sidecar):
                                self._managed_path(candidate)
                            if sidecar.exists():
                                identity = json.loads(sidecar.read_text(encoding="utf-8"))
                                if identity.get("site_id") != self.site_id or identity.get("run_id") != record["run_id"]:
                                    raise ValueError("retention compressed segment identity mismatch")
                            elif gzip_path.exists():
                                raise ValueError("retention compressed segment has no identity metadata")
                            if path.exists():
                                with path.open("rb") as source:
                                    identity = json.loads(source.readline(65537))
                                if identity.get("site_id") != self.site_id or identity.get("quick_ping_run_id") != record["run_id"]:
                                    raise ValueError("retention raw segment identity mismatch")
                        for path in paths:
                            path.unlink(missing_ok=True)
                            path.with_name(path.name + ".gz").unlink(missing_ok=True)
                            path.with_name(path.name + ".gz.json").unlink(missing_ok=True)
                        if ended < summary_cutoff:
                            manifest.unlink(missing_ok=True)
                            if self.repository.delete_terminal_quick_ping_summary(record["run_id"], ended_at=record["ended_at"], cutoff=summary_cutoff.isoformat()):
                                deleted += 1
                                with self._lock:
                                    self._runs.pop(record["run_id"], None)
                    except Exception as exc:
                        self._storage_error(record["run_id"], "QUICK_PING_RETENTION_FAILED", f"{type(exc).__name__}: {exc}")
                offset += len(records) - deleted
                if not records or offset >= total - deleted:
                    break
        except Exception as exc:
            self._storage_error("", "QUICK_PING_RETENTION_FAILED", f"{type(exc).__name__}: {exc}")
        finally:
            self._retention_lock.release()

    def _record_sample(self, run: QuickPingRun, writer: _QuickPingSegmentWriter, sample: FpingV5Sample) -> None:
        target = next(item for item in run.targets if item.target_ip == sample.target)
        payload = {
            "quick_ping_run_id": run.run_id,
            "site_id": run.site_id,
            "target_ip": target.target_ip,
            "train_id": target.train_id,
            "train_no": target.train_no,
            "mr_id": target.mr_id,
            "mr_name": target.mr_name,
            "mr_role": target.mr_role,
            "address_role": target.address_role,
            "received_at": sample.ts,
            "sample": sample.as_dict(),
        }
        with run._lock:
            run.stats.add(sample)
            run.target_stats[target.target_ip].add(sample)
            if target.target_ip in run.target_runtime:
                run.target_runtime[target.target_ip]["current_rtt_ms"] = run.target_stats[target.target_ip].current_rtt_ms
            run.recent_samples.append(payload)
            if len(run.recent_samples) > 256:
                del run.recent_samples[:-256]
            writer.write(payload, sample.ts)
            current = Path(writer.paths[-1])
            relative = current.relative_to(self.output_root).as_posix()
            if relative != run._active_segment_paths.get(target.target_ip):
                run.segment_paths.append(relative)
                run._active_segment_paths[target.target_ip] = relative
        self._persist_run(run)

    def _persist_run(self, run: QuickPingRun, *, event_type: str = "", force: bool = False) -> None:
        with run._persistence_lock:
            self._persist_run_locked(run, event_type=event_type, force=force)

    def _persist_run_locked(
        self,
        run: QuickPingRun,
        *,
        event_type: str = "",
        force: bool = False,
    ) -> None:
        repository = self.repository
        if repository is None:
            return
        now_mono = time.monotonic()
        with run._lock:
            if not force and now_mono - run._last_persist_monotonic < self.persist_interval_seconds:
                return
            payload = run.as_dict()
            stats = {"": payload["stats"], **payload["target_stats"]}
            accumulators = {
                "": _stats_accumulator(run.stats),
                **{
                    target_ip: _stats_accumulator(value)
                    for target_ip, value in run.target_stats.items()
                },
            }
            run._last_persist_monotonic = now_mono
        repository.save_quick_ping_state(
            payload,
            stats,
            accumulators,
            event=(
                {
                    "event_type": event_type,
                    "state": payload["state"],
                    "ts": _now(),
                    "details": {"error": payload.get("error", "")},
                }
                if event_type
                else None
            ),
        )

    def _write_manifest(self, run: QuickPingRun) -> None:
        with run._persistence_lock:
            self._write_manifest_locked(run)

    def _write_manifest_locked(self, run: QuickPingRun) -> None:
        manifest = self.output_root / "quick_ping" / run.run_date / "runs" / f"{_safe_segment(run.run_id)}.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temp = manifest.with_suffix(".json.part")
        with run._lock:
            payload = run.as_dict()
            payload["_stats_accumulators"] = {
                "overall": _stats_accumulator(run.stats),
                "targets": {
                    target_ip: _stats_accumulator(stats)
                    for target_ip, stats in run.target_stats.items()
                },
            }
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(manifest)

    def _restore_runs(self) -> None:
        reservations = self.repository.quick_ping_reservations() if self.repository is not None else []
        protected = {row["run_id"] for row in reservations if matching_process(row["owner_pid"], row["owner_identity"]) or matching_process(row["child_pid"], row["child_identity"]) or orphan_fping_children(row["owner_pid"])}
        restored: list[QuickPingRun] = []
        restored_ids: set[str] = set()
        sqlite_ids: set[str] = set()
        if self.repository is not None:
            try:
                for value in self.repository.list_quick_ping_runs(limit=MAX_RETAINED_QUICK_PING_RUNS):
                    run = _run_from_manifest(value, self.site_id)
                    restored.append(run)
                    restored_ids.add(run.run_id)
                    sqlite_ids.add(run.run_id)
            except Exception:
                restored = []
                restored_ids = set()
        manifest_root = self.output_root / "quick_ping"
        if not manifest_root.is_dir() and not restored:
            return
        for manifest in manifest_root.glob("*/runs/*.json"):
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
                run = _run_from_manifest(value, self.site_id)
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError):
                continue
            if run.run_date != manifest.parent.parent.name:
                continue
            if run.run_id in restored_ids:
                continue
            interrupted = run.state in {"RUNNING", "STOPPING"}
            if interrupted and run.run_id not in protected:
                run.state = "FAILED"
                run.error = "INTERRUPTED: backend restart stopped sample stream"
                run.ended_at = _now()
            elif not run.ended_at:
                run.ended_at = _now()
            restored.append(run)
            restored_ids.add(run.run_id)
            if interrupted or not value.get("ended_at"):
                self._write_manifest(run)
        restored.sort(key=lambda run: (run.started_at, run.run_id))
        with self._lock:
            self._runs.update((run.run_id, run) for run in restored)
            self._trim_runs_locked()
        if self.repository is not None:
            for run in restored:
                if run.run_id not in sqlite_ids and not run.error.startswith("INTERRUPTED:"):
                    try:
                        self._persist_run(run, event_type="RESTORED_FROM_MANIFEST", force=True)
                    except Exception:
                        continue
                if run.state in {"RUNNING", "STOPPING"} and run.run_id not in protected:
                    run.state = "FAILED"
                    run.error = "INTERRUPTED: backend restart stopped sample stream"
                    run.ended_at = _now()
                    try:
                        self._write_manifest(run)
                    except OSError:
                        pass
                if run.state == "FAILED" and run.error.startswith("INTERRUPTED:"):
                    try:
                        self._persist_run(run, event_type="INTERRUPTED", force=True)
                    except Exception:
                        continue
        self._recover_reservations()

    def _trim_runs_locked(self) -> None:
        excess = len(self._runs) - MAX_RETAINED_QUICK_PING_RUNS
        if excess <= 0:
            return
        terminal = sorted(
            (run for run in self._runs.values() if run.state not in {"RUNNING", "STOPPING"}),
            key=lambda run: (run.started_at, run.run_id),
        )
        for run in terminal[:excess]:
            self._runs.pop(run.run_id, None)

    def _time_limit(self, run: QuickPingRun) -> None:
        changed = False
        with run._lock:
            if run.state == "RUNNING":
                run.state = "TIME_LIMIT"
                run._stop_event.set()
                for event in run._target_stops.values():
                    event.set()
                changed = True
        if changed:
            self._persist_run(run, event_type="TIME_LIMIT", force=True)

    def _run_output_root(self, run: QuickPingRun, target: QuickPingTarget) -> Path:
        return (
            self.output_root
            / "quick_ping"
            / run.run_date
            / "trains"
            / _safe_segment(target.train_id or "unknown-train")
            / _safe_segment(target.mr_role or "unknown-role")
            / _safe_segment(target.mr_id)
            / "quick_ping"
            / _safe_segment(run.run_id)
            / _safe_segment(target.target_ip)
        )


def _run_from_manifest(value: Any, site_id: str) -> QuickPingRun:
    if not isinstance(value, dict):
        raise TypeError("quick ping manifest must be an object")
    manifest_site_id = str(value.get("site_id") or "")
    if manifest_site_id != site_id:
        raise ValueError("quick ping manifest belongs to another site")
    run_id = str(value.get("run_id") or "").strip()
    run_date = str(value.get("run_date") or "").strip()
    if not run_id or not run_date:
        raise ValueError("quick ping manifest is missing run identity")
    datetime.strptime(run_date, "%Y-%m-%d")
    state = str(value.get("state") or "").strip()
    if state not in QUICK_PING_STATES:
        raise ValueError("quick ping manifest has an unknown state")
    raw_targets = value.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("quick ping manifest has no targets")
    targets = tuple(_target_from_manifest(raw_target) for raw_target in raw_targets)
    config_value = value.get("config")
    if not isinstance(config_value, dict):
        raise ValueError("quick ping manifest has no config")
    config = QuickPingConfig(
        interval_ms=int(config_value.get("interval_ms", 200)),
        timeout_ms=int(config_value.get("timeout_ms", 1000)),
        packet_size=int(config_value.get("packet_size", 64)),
        duration_seconds=(
            None
            if config_value.get("duration_seconds") is None
            else float(config_value["duration_seconds"])
        ),
        max_in_flight=int(config_value.get("max_in_flight", 32)),
    )
    accumulator_value = value.get("_stats_accumulators")
    overall_accumulator = accumulator_value.get("overall") if isinstance(accumulator_value, dict) else None
    target_accumulators = accumulator_value.get("targets") if isinstance(accumulator_value, dict) else None
    raw_target_stats = value.get("target_stats")
    if not isinstance(raw_target_stats, dict):
        raw_target_stats = {}
    target_stats = {
        target.target_ip: _stats_from_manifest(
            raw_target_stats.get(target.target_ip),
            target_accumulators.get(target.target_ip) if isinstance(target_accumulators, dict) else None,
        )
        for target in targets
    }
    raw_segment_paths = value.get("segment_paths")
    segment_paths = [str(path) for path in raw_segment_paths] if isinstance(raw_segment_paths, list) else []
    return QuickPingRun(
        run_id=run_id,
        site_id=manifest_site_id,
        run_date=run_date,
        targets=targets,
        config=config,
        state=state,
        started_at=str(value.get("started_at") or ""),
        ended_at=str(value.get("ended_at") or ""),
        error=str(value.get("error") or ""),
        segment_paths=segment_paths,
        stats=_stats_from_manifest(value.get("stats"), overall_accumulator),
        target_stats=target_stats,
        recent_samples=_recent_samples_from_manifest(value.get("recent_samples")),
        target_runtime={str(ip): dict(runtime) for ip, runtime in (value.get("target_runtime") or {}).items()},
    )


def _target_from_manifest(value: Any) -> QuickPingTarget:
    if not isinstance(value, dict):
        raise TypeError("quick ping target must be an object")
    return QuickPingTarget(
        target_ip=str(value.get("target_ip") or ""),
        train_id=str(value.get("train_id") or ""),
        mr_id=str(value.get("mr_id") or ""),
        mr_role=str(value.get("mr_role") or ""),
        address_role=str(value.get("address_role") or "PRIMARY"),
        train_no=str(value.get("train_no") or ""),
        mr_name=str(value.get("mr_name") or ""),
    )


def _stats_accumulator(stats: QuickPingStats) -> dict[str, Any]:
    return {
        "rtt_sum_ms": stats.rtt_sum_ms,
        "jitter_sum_ms": stats.jitter_sum_ms,
        "jitter_count": stats.jitter_count,
        "previous_success_rtt": stats._previous_success_rtt,
    }


def _stats_from_manifest(value: Any, accumulator: Any = None) -> QuickPingStats:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise TypeError("quick ping stats must be an object")
    received = int(value.get("received") or 0)
    avg_rtt = value.get("avg_rtt_ms")
    jitter = value.get("jitter_ms")
    accumulator = accumulator if isinstance(accumulator, dict) else {}
    rtt_sum = accumulator.get("rtt_sum_ms")
    jitter_sum = accumulator.get("jitter_sum_ms")
    jitter_count = accumulator.get("jitter_count")
    return QuickPingStats(
        raw_samples=int(value.get("raw_samples") or 0),
        sent=int(value.get("sent") or 0),
        received=received,
        lost=int(value.get("lost") or 0),
        rtt_sum_ms=(
            float(rtt_sum)
            if rtt_sum is not None
            else (float(avg_rtt) * received if avg_rtt is not None else 0.0)
        ),
        min_rtt_ms=(None if value.get("min_rtt_ms") is None else float(value["min_rtt_ms"])),
        max_rtt_ms=(None if value.get("max_rtt_ms") is None else float(value["max_rtt_ms"])),
        jitter_sum_ms=(
            float(jitter_sum)
            if jitter_sum is not None
            else (float(jitter) if jitter is not None else 0.0)
        ),
        jitter_count=(int(jitter_count) if jitter_count is not None else (1 if jitter is not None else 0)),
        current_consecutive_loss=int(value.get("current_consecutive_loss") or 0),
        max_consecutive_loss=int(value.get("max_consecutive_loss") or 0),
        last_sample_at=str(value.get("last_sample_at") or ""),
        last_success_at=str(value.get("last_success_at") or ""),
        current_rtt_ms=value.get("current_rtt_ms"),
        _previous_success_rtt=(
            None
            if accumulator.get("previous_success_rtt") is None
            else float(accumulator["previous_success_rtt"])
        ),
    )


def _recent_samples_from_manifest(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(sample) for sample in value[-256:] if isinstance(sample, dict)]


def _dedupe_targets(targets: list[QuickPingTarget] | tuple[QuickPingTarget, ...]) -> list[QuickPingTarget]:
    result: list[QuickPingTarget] = []
    by_ip: dict[str, QuickPingTarget] = {}
    for target in targets:
        if not isinstance(target, QuickPingTarget):
            target = QuickPingTarget(**dict(target))  # type: ignore[arg-type]
        existing = by_ip.get(target.target_ip)
        if existing is not None:
            if existing.mr_id != target.mr_id:
                raise QuickPingError(
                    "QUICK_PING_TARGET_AMBIGUOUS",
                    f"目标 IP {target.target_ip} 对应多个 MR，无法安全关联采样",
                    status_code=409,
                )
            raise QuickPingError("QUICK_PING_TARGET_DUPLICATE", f"批次中存在重复 IP: {target.target_ip}", status_code=409)
        by_ip[target.target_ip] = target
        result.append(target)
    return result


def _safe_segment(value: str) -> str:
    value = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value))
    return value[:160] or "unknown"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp_hour(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y%m%d_%H")
    except (TypeError, ValueError):
        return datetime.now().strftime("%Y%m%d_%H")


def _coerce_sample(value: Any, timeout_ms: int) -> FpingV5Sample:
    if isinstance(value, FpingV5Sample):
        return value
    if not isinstance(value, dict):
        raise TypeError("fping runner yielded an unsupported sample")
    return FpingV5Sample(
        ts=str(value.get("ts") or _now()),
        target=str(value.get("target") or ""),
        seq=value.get("seq"),
        ok=value.get("ok"),
        rtt_ms=value.get("rtt_ms"),
        timeout_ms=int(value.get("timeout_ms") or timeout_ms),
        size=value.get("size"),
        error=str(value.get("error") or ""),
        backend=str(value.get("backend") or "fping_v5_json"),
        raw_type=str(value.get("raw_type") or "unknown"),
        raw=value.get("raw") if isinstance(value.get("raw"), dict) else value,
    )


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _append_error(existing: str, addition: str) -> str:
    return f"{existing}; {addition}" if existing else addition


__all__ = [
    "QUICK_PING_STATES",
    "QuickPingConfig",
    "QuickPingError",
    "QuickPingRun",
    "QuickPingService",
    "QuickPingStats",
    "QuickPingTarget",
]


def _query_timestamp(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timezone required")
        return stamp.astimezone(timezone.utc)
    except ValueError as exc:
        raise QuickPingError("QUICK_PING_TIME_INVALID", "时间必须为带时区的 ISO 8601 格式") from exc


def _query_time_range(start_time: str, end_time: str) -> tuple[datetime | None, datetime | None]:
    start = _query_timestamp(start_time) if start_time else None
    end = _query_timestamp(end_time) if end_time else None
    if start is not None and end is not None and start > end:
        raise QuickPingError("QUICK_PING_TIME_RANGE_INVALID", "开始时间不能晚于结束时间")
    return start, end


def is_active_quick_ping(value: dict[str, Any]) -> bool:
    return value["state"] in {"RUNNING", "STOPPING"} and not value.get("ended_at")


def _encode_sample_cursor(index: int, offset: int, fingerprint: str, checkpoints: dict[int, int], turn: int) -> str:
    return base64.urlsafe_b64encode(json.dumps([index, offset, fingerprint, sorted(checkpoints.items()), turn]).encode("utf-8")).decode("ascii")


def _decode_sample_cursor(cursor: str, fingerprint: str) -> tuple[int, int, dict[int, int], int]:
    try:
        if len(cursor) > 8192:
            raise ValueError("cursor too long")
        value = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        index, offset, saved_fingerprint = value[:3]
        saved, turn = ([], 0) if len(value) == 3 else value[3:]
        if type(saved) is not list or len(saved) > MAX_QUICK_PING_TARGETS:
            raise ValueError("too many checkpoints")
        checkpoints = dict(saved)
        integers = [index, offset, turn, *checkpoints, *checkpoints.values()]
        if any(type(number) is not int or not 0 <= number <= 2**63 - 1 for number in integers) or saved_fingerprint != fingerprint or len(checkpoints) != len(saved):
            raise ValueError("cursor mismatch")
        return index, offset, checkpoints, turn
    except (ValueError, TypeError, UnicodeError) as exc:
        raise QuickPingError("QUICK_PING_CURSOR_INVALID", "快速 Ping 样本游标无效或与筛选条件不符") from exc
