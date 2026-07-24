from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.core.ping.fping_v5_runner import run_fping_v5_json
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.timeline import (
    GroundUnattendedTimelineCorrelator,
)


@dataclass(frozen=True)
class FleetPingTarget:
    target_ip: str
    train_id: str
    train_no: str
    mr_id: str
    mr_position_code: str
    ac_snapshot_id: int | None = None
    ac_received_at: str = ""
    current_ap_identity: str = ""
    current_ap_name: str = ""
    current_ap_mac: str = ""
    station: str = ""
    section: str = ""
    mileage: str = ""
    rssi: int | None = None
    same_ap_since: str = ""


@dataclass
class _Stats:
    sent: int = 0
    success: int = 0
    loss: int = 0
    rtt_sum: float = 0.0
    min_rtt: float | None = None
    max_rtt: float | None = None
    current_loss: int = 0
    max_loss: int = 0

    def add(self, sample: FpingV5Sample) -> None:
        self.sent += 1
        if sample.ok:
            self.success += 1
            self.current_loss = 0
            if sample.rtt_ms is not None:
                self.rtt_sum += sample.rtt_ms
                self.min_rtt = (
                    sample.rtt_ms
                    if self.min_rtt is None
                    else min(self.min_rtt, sample.rtt_ms)
                )
                self.max_rtt = (
                    sample.rtt_ms
                    if self.max_rtt is None
                    else max(self.max_rtt, sample.rtt_ms)
                )
        else:
            self.loss += 1
            self.current_loss += 1
            self.max_loss = max(self.max_loss, self.current_loss)


@dataclass
class _ShardWorker:
    shard_id: str
    generation: str
    targets: tuple[str, ...]
    stop_event: threading.Event
    started_event: threading.Event
    thread: threading.Thread


class _SegmentWriter:
    def __init__(
        self,
        *,
        root: Path,
        repository: GroundUnattendedRepository,
        site_id: str,
        run_id: str,
        shard_id: str,
        generation: str,
        target_count: int,
    ) -> None:
        self.root = root
        self.repository = repository
        self.site_id = site_id
        self.run_id = run_id
        self.shard_id = shard_id
        self.generation = generation
        self.target_count = target_count
        self._hour = ""
        self._path: Path | None = None
        self._file = None
        self._segment_id = ""
        self._started_at = ""
        self._sample_count = 0
        self._pending_flush_count = 0
        self._last_flush_monotonic = time.monotonic()

    def write(self, payload: dict[str, Any], ts: datetime) -> None:
        hour = ts.strftime("%Y%m%d_%H")
        if hour != self._hour:
            self._close_segment(ts.isoformat(timespec="milliseconds"))
            self._open_segment(hour, ts.isoformat(timespec="milliseconds"))
        self._file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._sample_count += 1
        self._pending_flush_count += 1
        if (
            self._pending_flush_count >= 64
            or time.monotonic() - self._last_flush_monotonic >= 1.0
        ):
            self._file.flush()
            self._pending_flush_count = 0
            self._last_flush_monotonic = time.monotonic()

    def close(self) -> None:
        self._close_segment(
            datetime.now().astimezone().isoformat(timespec="milliseconds")
        )

    def _open_segment(self, hour: str, started_at: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._hour = hour
        self._started_at = started_at
        self._segment_id = (
            f"pingseg_{self.run_id}_{self.shard_id}_{hour}_{self.generation}"
        )
        self._path = self.root / f"ping_{hour}_{self.shard_id}_{self.generation}.jsonl"
        self._file = self._path.open("a", encoding="utf-8", newline="\n")
        self._sample_count = 0
        self._pending_flush_count = 0
        self._last_flush_monotonic = time.monotonic()
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.repository.upsert_ping_segment(
            {
                "segment_id": self._segment_id,
                "site_id": self.site_id,
                "run_id": self.run_id,
                "shard_id": self.shard_id,
                "relative_path": self._relative_path(),
                "started_at": started_at,
                "ended_at": "",
                "target_count": self.target_count,
                "sample_count": 0,
                "size_bytes": self._path.stat().st_size,
                "sha256": "",
                "status": "OPEN",
                "created_at": now,
                "updated_at": now,
            }
        )

    def _close_segment(self, ended_at: str) -> None:
        if self._file is None or self._path is None:
            return
        self._file.flush()
        self._file.close()
        self._file = None
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.repository.upsert_ping_segment(
            {
                "segment_id": self._segment_id,
                "site_id": self.site_id,
                "run_id": self.run_id,
                "shard_id": self.shard_id,
                "relative_path": self._relative_path(),
                "started_at": self._started_at,
                "ended_at": ended_at,
                "target_count": self.target_count,
                "sample_count": self._sample_count,
                "size_bytes": self._path.stat().st_size,
                "sha256": _sha256(self._path),
                "status": "CLOSED",
                "created_at": self._started_at,
                "updated_at": now,
            }
        )
        self._path = None

    def _relative_path(self) -> str:
        return (
            self._path.relative_to(self.repository.db_path.parent).as_posix()
            if self._path
            else ""
        )


class FleetPingSupervisor:
    """为全车目标维护有界多目标 fping 分片，与深度采集生命周期完全分离。"""

    def __init__(
        self,
        *,
        repository: GroundUnattendedRepository,
        site_id: str,
        runner: Callable[..., Iterator[FpingV5Sample]] = run_fping_v5_json,
    ) -> None:
        self.repository = repository
        self.site_id = site_id
        self.runner = runner
        self._lock = threading.RLock()
        self._workers: dict[str, _ShardWorker] = {}
        self._targets: dict[str, FleetPingTarget] = {}
        self._stats: dict[str, _Stats] = {}
        self._buckets: dict[tuple[str, str, str, str], _Stats] = {}
        self._dirty_buckets: set[tuple[str, str, str, str]] = set()
        self._run_id = ""
        self._run_date = ""
        self._output_dir: Path | None = None
        self._period_ms = 1000
        self._timeout_ms = 4000
        self._packet_size = 64
        self._shard_size = 12
        self._correlator: GroundUnattendedTimelineCorrelator | None = None
        self._sample_count = 0
        self._started_at: dict[str, str] = {}
        self._backend_warnings: list[str] = []

    def start(
        self,
        *,
        run_id: str,
        run_date: str,
        active_dir: Path,
        period_ms: int,
        timeout_ms: int,
        packet_size: int,
        shard_size: int,
        correlation_tolerance_seconds: int,
        switch_before_seconds: int,
        switch_after_seconds: int,
    ) -> None:
        if self._run_id and self._run_id != run_id:
            self.stop()
        self._recover_open_segments(run_id)
        with self._lock:
            if self._run_id == run_id:
                return
            self._run_id = run_id
            self._run_date = run_date
            self._stats = {}
            self._buckets = {}
            self._dirty_buckets = set()
            self._sample_count = 0
            self._started_at = {}
            self._backend_warnings = []
            self._output_dir = Path(active_dir) / "fleet_ping"
            self._period_ms = int(period_ms)
            self._timeout_ms = int(timeout_ms)
            self._packet_size = int(packet_size)
            self._shard_size = int(shard_size)
            self._correlator = GroundUnattendedTimelineCorrelator(
                Path(active_dir) / "timeline",
                tolerance_seconds=correlation_tolerance_seconds,
                switch_before_seconds=switch_before_seconds,
                switch_after_seconds=switch_after_seconds,
                event_callback=lambda **values: self.repository.add_event(
                    run_id=run_id, **values
                ),
            )

    def update_targets(self, targets: list[FleetPingTarget]) -> None:
        with self._lock:
            self._flush_summaries_locked()
            desired = {item.target_ip: item for item in targets if item.target_ip}
            for address, current in desired.items():
                previous = self._targets.get(address)
                if (
                    previous
                    and previous.current_ap_identity != current.current_ap_identity
                ):
                    transition_at = (
                        datetime.now().astimezone().isoformat(timespec="milliseconds")
                    )
                    current = FleetPingTarget(
                        **{**current.__dict__, "same_ap_since": current.same_ap_since}
                    )
                    if self._correlator:
                        self._correlator.ap_transition(
                            target_ip=address,
                            train_id=current.train_id,
                            mr_id=current.mr_id,
                            transition_at=transition_at,
                            before_ap=previous.current_ap_name,
                            after_ap=current.current_ap_name,
                        )
                    desired[address] = current
            self._targets = desired
            addresses = tuple(sorted(desired))
        self._reconcile_shards(addresses)

    def flush_summaries(self) -> None:
        with self._lock:
            self._flush_summaries_locked()

    def _flush_summaries_locked(self) -> None:
        if not self._run_id or not self._dirty_buckets:
            return
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        flushed = set()
        for key in tuple(self._dirty_buckets):
            kind, bucket_start, target_ip, ap_identity = key
            target = self._targets.get(target_ip)
            stats = self._buckets.get(key)
            if target is None or stats is None:
                continue
            bucket_end = self._bucket_end(kind, bucket_start)
            self.repository.upsert_ping_summary(
                self._summary_payload(
                    kind, bucket_start, bucket_end, target, ap_identity, stats, now
                )
            )
            flushed.add(key)
        self._dirty_buckets.difference_update(flushed)

    def stop(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers = {}
        for worker in workers:
            worker.stop_event.set()
        for worker in workers:
            worker.thread.join(timeout=8)
        with self._lock:
            if self._run_id:
                self.flush_summaries()
            if self._correlator:
                self._correlator.close()
            self._correlator = None
            self._targets = {}
            self._run_id = ""

    def target_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            shard_by_target = {
                address: shard.shard_id
                for shard in self._workers.values()
                for address in shard.targets
            }
            for address, target in self._targets.items():
                stats = self._stats.get(address, _Stats())
                result.append(
                    {
                        "target_ip": address,
                        "train_id": target.train_id,
                        "train_no": target.train_no,
                        "mr_id": target.mr_id,
                        "mr_position_code": target.mr_position_code,
                        "started_at": self._started_at.get(address, ""),
                        "updated_at": datetime.now()
                        .astimezone()
                        .isoformat(timespec="milliseconds"),
                        "shard_id": shard_by_target.get(address, ""),
                        **self._stats_values(stats),
                        "current_ap_name": target.current_ap_name,
                        "station": target.station,
                        "section": target.section,
                    }
                )
            return result

    @property
    def sample_count(self) -> int:
        with self._lock:
            return self._sample_count

    @property
    def target_count(self) -> int:
        with self._lock:
            return len(self._targets)

    @property
    def process_count(self) -> int:
        with self._lock:
            return len(self._workers)

    def _reconcile_shards(self, addresses: tuple[str, ...]) -> None:
        with self._lock:
            planned = self._plan_shards(addresses)
            old = dict(self._workers)
            replacements: dict[str, _ShardWorker] = {}
            for shard_id, shard_targets in planned.items():
                current = old.get(shard_id)
                if (
                    current
                    and current.targets == shard_targets
                    and current.thread.is_alive()
                ):
                    replacements[shard_id] = current
                    continue
                worker = self._start_worker(shard_id, shard_targets)
                replacements[shard_id] = worker
            self._workers = replacements
        # 新分片先进入 runner，再关闭发生变化的旧分片，缩短时间轴空洞。
        for worker in replacements.values():
            if all(worker is not existing for existing in old.values()):
                worker.started_event.wait(timeout=2)
        for shard_id, worker in old.items():
            if replacements.get(shard_id) is not worker:
                worker.stop_event.set()
                worker.thread.join(timeout=8)
                self.repository.add_event(
                    run_id=self._run_id,
                    event_type="ping_shard_restarted",
                    title="长 Ping 分片已按目标变化重建",
                    details={"shard_id": shard_id, "targets": list(worker.targets)},
                )

    def _recover_open_segments(self, run_id: str) -> None:
        root = self.repository.db_path.parent.resolve()
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        for row in self.repository.list_open_ping_segments(run_id):
            path = (root / str(row.get("relative_path") or "")).resolve()
            try:
                path.relative_to(root)
                valid = path.is_file() and not path.is_symlink()
            except ValueError:
                valid = False
            self.repository.upsert_ping_segment(
                {
                    "segment_id": row["segment_id"],
                    "site_id": self.site_id,
                    "run_id": run_id,
                    "shard_id": row["shard_id"],
                    "relative_path": row.get("relative_path", ""),
                    "started_at": row.get("started_at", ""),
                    "ended_at": now,
                    "target_count": int(row.get("target_count") or 0),
                    "sample_count": int(row.get("sample_count") or 0),
                    "size_bytes": path.stat().st_size if valid else 0,
                    "sha256": _sha256(path) if valid else "",
                    "status": "RECOVERED" if valid else "MISSING",
                    "created_at": row.get("created_at", now),
                    "updated_at": now,
                }
            )

    def _plan_shards(self, addresses: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
        remaining = set(addresses)
        planned: dict[str, tuple[str, ...]] = {}
        new_addresses = [
            value
            for value in addresses
            if all(value not in shard.targets for shard in self._workers.values())
        ]
        for shard_id, worker in sorted(self._workers.items()):
            kept = [value for value in worker.targets if value in remaining]
            while len(kept) < self._shard_size and new_addresses:
                value = new_addresses.pop(0)
                if value in remaining and value not in kept:
                    kept.append(value)
            if kept:
                planned[shard_id] = tuple(kept)
                remaining.difference_update(kept)
        index = 1
        while remaining:
            shard_id = f"shard-{index:03d}"
            while shard_id in planned:
                index += 1
                shard_id = f"shard-{index:03d}"
            group = tuple(sorted(remaining)[: self._shard_size])
            planned[shard_id] = group
            remaining.difference_update(group)
            index += 1
        return planned

    def _start_worker(self, shard_id: str, targets: tuple[str, ...]) -> _ShardWorker:
        generation = uuid.uuid4().hex[:8]
        stop_event = threading.Event()
        started_event = threading.Event()
        thread = threading.Thread(
            target=self._worker_loop,
            args=(shard_id, generation, targets, stop_event, started_event),
            name=f"fleet-ping-{shard_id}-{generation}",
            daemon=True,
        )
        worker = _ShardWorker(
            shard_id, generation, targets, stop_event, started_event, thread
        )
        for address in targets:
            self._started_at.setdefault(
                address, datetime.now().astimezone().isoformat(timespec="milliseconds")
            )
        thread.start()
        return worker

    def _worker_loop(
        self,
        shard_id: str,
        generation: str,
        targets: tuple[str, ...],
        stop_event: threading.Event,
        started_event: threading.Event,
    ) -> None:
        writer = _SegmentWriter(
            root=self._output_dir or Path("."),
            repository=self.repository,
            site_id=self.site_id,
            run_id=self._run_id,
            shard_id=shard_id,
            generation=generation,
            target_count=len(targets),
        )
        started_event.set()
        parsed = 0
        try:
            for sample in self.runner(
                target="",
                targets=list(targets),
                period_ms=self._period_ms,
                timeout_ms=self._timeout_ms,
                packet_size=self._packet_size,
                count_json=None,
                stop_event=stop_event,
            ):
                parsed += 1
                self._record_sample(sample, shard_id, writer)
            if not stop_event.is_set() and parsed == 0 and len(targets) > 1:
                self._bounded_single_target_fallback(
                    targets, stop_event, shard_id, writer
                )
        except Exception as exc:
            self.repository.add_event(
                run_id=self._run_id,
                event_type="ping_shard_failed",
                severity="error",
                title="长 Ping 分片运行失败",
                message=f"{exc.__class__.__name__}: {exc}",
                details={"shard_id": shard_id, "target_count": len(targets)},
            )
            if not stop_event.is_set() and len(targets) > 1:
                self._bounded_single_target_fallback(
                    targets, stop_event, shard_id, writer
                )
        finally:
            writer.close()

    def _bounded_single_target_fallback(
        self, targets, stop_event, shard_id, writer
    ) -> None:
        warning = f"{shard_id}: multi-target JSON unavailable; bounded round-robin fallback active"
        with self._lock:
            if warning not in self._backend_warnings:
                self._backend_warnings.append(warning)
        self.repository.add_event(
            run_id=self._run_id,
            event_type="ping_fallback_enabled",
            severity="warning",
            title="长 Ping 已进入有界兼容模式",
            message="当前 fping 多目标 JSON 不可用；每个分片仅保留一个轮询进程，不会按 MR 无上限创建进程。",
            details={"shard_id": shard_id, "target_count": len(targets)},
        )
        while not stop_event.is_set():
            for address in targets:
                if stop_event.is_set():
                    return
                try:
                    for sample in self.runner(
                        target=address,
                        period_ms=self._period_ms,
                        timeout_ms=self._timeout_ms,
                        packet_size=self._packet_size,
                        count_json=1,
                        stop_event=stop_event,
                    ):
                        raw = dict(sample.raw)
                        raw["fallback"] = True
                        sample = FpingV5Sample(
                            **{
                                **sample.__dict__,
                                "backend": "fping_v5_json_single_target_fallback",
                                "raw": raw,
                            }
                        )
                        self._record_sample(sample, shard_id, writer)
                except Exception:
                    if stop_event.wait(min(1.0, self._period_ms / 1000)):
                        return

    def _record_sample(
        self, sample: FpingV5Sample, shard_id: str, writer: _SegmentWriter
    ) -> None:
        with self._lock:
            target = self._targets.get(sample.target)
            if target is None or not self._run_id:
                return
            ts = _parse_sample_ts(sample.ts)
            self._sample_count += 1
            sample_id = f"{self._run_id}:{sample.target}:{sample.seq or self._sample_count}:{sample.ts}"
            payload = {
                "sample_id": sample_id,
                "ts": ts.isoformat(timespec="milliseconds"),
                "site_id": self.site_id,
                "automation_run_id": self._run_id,
                "target_ip": sample.target,
                "train_id": target.train_id,
                "train_no": target.train_no,
                "mr_id": target.mr_id,
                "mr_position_code": target.mr_position_code,
                "seq": sample.seq,
                "ok": bool(sample.ok),
                "rtt_ms": sample.rtt_ms,
                "timeout_ms": sample.timeout_ms,
                "packet_size": sample.size or self._packet_size,
                "backend": sample.backend,
                "error": sample.error,
                "shard_id": shard_id,
            }
            writer.write(payload, ts)
            self._stats.setdefault(sample.target, _Stats()).add(sample)
            for kind, bucket_start, ap_identity in self._bucket_keys(ts, target):
                key = (kind, bucket_start, sample.target, ap_identity)
                self._buckets.setdefault(key, _Stats()).add(sample)
                self._dirty_buckets.add(key)
            if self._correlator:
                context = {**target.__dict__, "ap_transition_at": target.same_ap_since}
                self._correlator.correlate(payload, context)

    def _bucket_keys(self, ts: datetime, target: FleetPingTarget):
        minute = ts.replace(second=0, microsecond=0)
        five = minute.replace(minute=(minute.minute // 5) * 5)
        daily = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        ac_start = target.ac_received_at or minute.isoformat(timespec="seconds")
        ap_start = target.same_ap_since or minute.isoformat(timespec="seconds")
        return (
            ("1m", minute.isoformat(timespec="seconds"), ""),
            ("5m", five.isoformat(timespec="seconds"), ""),
            ("ac_poll", ac_start, str(target.ac_snapshot_id or "")),
            ("ap_segment", ap_start, target.current_ap_identity),
            ("daily", daily.isoformat(timespec="seconds"), ""),
        )

    def _summary_payload(self, kind, start, end, target, ap_identity, stats, now):
        values = self._stats_values(stats)
        return {
            "site_id": self.site_id,
            "run_id": self._run_id,
            "bucket_kind": kind,
            "bucket_start": start,
            "bucket_end": end,
            "target_ip": target.target_ip,
            "train_id": target.train_id,
            "train_no": target.train_no,
            "mr_id": target.mr_id,
            "mr_position_code": target.mr_position_code,
            "ac_snapshot_id": target.ac_snapshot_id,
            "ap_identity": ap_identity,
            "sent_count": values["sent_count"],
            "success_count": values["success_count"],
            "loss_count": values["loss_count"],
            "loss_rate_percent": values["loss_rate_percent"],
            "min_rtt_ms": values["min_rtt_ms"],
            "avg_rtt_ms": values["avg_rtt_ms"],
            "max_rtt_ms": values["max_rtt_ms"],
            "continuous_loss_max_count": values["continuous_loss_max_count"],
            "continuous_loss_max_seconds": values["continuous_loss_max_seconds"],
            "created_at": now,
        }

    def _stats_values(self, stats: _Stats) -> dict[str, Any]:
        return {
            "sent_count": stats.sent,
            "success_count": stats.success,
            "loss_count": stats.loss,
            "loss_rate_percent": round(stats.loss * 100 / stats.sent, 4)
            if stats.sent
            else 0.0,
            "min_rtt_ms": stats.min_rtt,
            "avg_rtt_ms": round(stats.rtt_sum / stats.success, 4)
            if stats.success
            else None,
            "max_rtt_ms": stats.max_rtt,
            "continuous_loss_max_count": stats.max_loss,
            "continuous_loss_max_seconds": round(
                stats.max_loss * self._period_ms / 1000, 3
            ),
        }

    @staticmethod
    def _bucket_end(kind: str, start: str) -> str:
        try:
            value = datetime.fromisoformat(start)
        except ValueError:
            return start
        delta = {
            "1m": timedelta(minutes=1),
            "5m": timedelta(minutes=5),
            "daily": timedelta(days=1),
        }.get(kind, timedelta(seconds=0))
        return (value + delta).isoformat(timespec="seconds") if delta else start


def _parse_sample_ts(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.astimezone()
    except ValueError:
        return datetime.now().astimezone()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["FleetPingSupervisor", "FleetPingTarget"]
