from __future__ import annotations

import ipaddress
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any

from netconsole.models.api.ground_unattended import HeartbeatConfigDTO, HeartbeatRuntimeDTO
from netconsole.services.ground_unattended.fleet_ping import FleetPingSupervisor, FleetPingTarget
from netconsole.services.ground_unattended.heartbeat_state import (
    HeartbeatIpObservation, HeartbeatStateEngine, HeartbeatTarget,
    HeartbeatTransition, TrainConnectivityAggregator,
)
from netconsole.services.ground_unattended.inventory import TrainInventorySyncService
from netconsole.services.ground_unattended.ping_loss import PingLossTracker, acknowledge_loss_events

LOGGER = logging.getLogger(__name__)
HEARTBEAT_STREAM_ID = "heartbeat-resident"
_HEARTBEAT_PERSIST_BATCH_SIZE = 256
_HEARTBEAT_EVENT_CAPACITY = 4096

def _fair_persist_batch(items: list[str], *, after: str, limit: int) -> list[str]:
    """Select a bounded rotating slice so a busy prefix cannot starve later IDs."""
    if len(items) <= limit:
        return items
    start = 0
    if after:
        for index, item in enumerate(items):
            if item > after:
                start = index
                break
        else:
            start = 0
    return items[start : start + limit]


def _valid_heartbeat_ip(value: object) -> bool:
    try:
        parsed = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return (
        parsed.version == 4
        and not parsed.is_unspecified
        and not parsed.is_multicast
        and str(parsed) != "255.255.255.255"
    )



class HeartbeatSupervisor:
    """Site 心跳资源的唯一所有者，由 Backend lifespan 管理。"""

    def __init__(self, paths, *, site_id, repository, base_query, now_provider=None, tick_seconds=1.0):
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())
        self.tick_seconds = max(0.05, float(tick_seconds))
        self._heartbeat_engine = HeartbeatStateEngine(
            event_sink=self._on_heartbeat_transition,
        )
        self._train_connectivity = TrainConnectivityAggregator(
            event_sink=self._on_heartbeat_transition,
        )
        self._heartbeat_run_id = ""
        # fping callbacks run on shard threads while the Supervisor tick and
        # stop/finalize paths run on the scheduler thread. Keep the state
        # engine and its bounded persistence queue behind one lock.
        self._heartbeat_lock = threading.RLock()
        self._heartbeat_dirty_mrs: set[str] = set()
        self._heartbeat_dirty_trains: set[str] = set()
        self._heartbeat_persist_after_mr = ""
        self._heartbeat_persist_after_train = ""
        self._heartbeat_target_signature: tuple[tuple[Any, ...], ...] = ()
        self._heartbeat_force_persist = False
        self._heartbeat_pending_events: deque[dict[str, Any]] = deque()
        self._heartbeat_pending_loss_events: deque[dict[str, Any]] = deque()
        self._heartbeat_loss_trackers: dict[str, PingLossTracker] = {}
        self._heartbeat_event_flush_lock = threading.Lock()
        self._heartbeat_event_error = ""
        self.fleet_ping = FleetPingSupervisor(
            repository=repository,
            site_id=site_id,
            sample_callback=self._on_fleet_ping_sample,
        )
        self.inventory_sync = TrainInventorySyncService(
            paths, site_id=site_id, repository=repository, base_query=base_query,
        )
        self._lifecycle_lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self._config = HeartbeatConfigDTO()
        self._config_initialized = False
        self._applied_config = None
        self._inventory_refresh_at = 0.0
        self._restored = False
        self._fleet_started = False
        self._runtime_state = "STOPPED"
        self._last_error = ""
        self._last_success_at = ""
        self._enrichment = {}
        self._failure_count = 0
        self._inventory_error = ""

    def _now(self):
        return self.now_provider()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lifecycle_lock:
            if self.running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name=f"heartbeat-{self.site_id}", daemon=True)
            self._thread.start()

    def close(self, timeout_seconds=30.0):
        with self._lifecycle_lock:
            self._stop_event.set()
            self._wake_event.set()
            if self._thread is not None:
                self._thread.join(timeout=max(0.1, timeout_seconds))
                if self._thread.is_alive():
                    raise RuntimeError("Heartbeat supervisor did not stop within budget")
                self._thread = None
            result = self.fleet_ping.stop()
            if not result.get("success"):
                raise RuntimeError(f"Heartbeat workers did not stop: {result}")
            self._fleet_started = False
            self._applied_config = None
            self._quiesce_heartbeat()
            self._runtime_state = "STOPPED"

    def config_updated(self):
        self._inventory_refresh_at = 0.0
        self._wake_event.set()

    def apply_inventory_action(self, action, *, expected_revision):
        # Serialize with start/close and the tick. A saved enabled=false alone
        # is insufficient: old workers and dirty buffers must already be drained.
        with self._lifecycle_lock, self._operation_lock:
            if self._runtime_state not in {"DISABLED", "STOPPED"} or self.repository.get_heartbeat_config().enabled:
                raise ValueError("HEARTBEAT_MONITORING_ACTIVE")
            self.repository.apply_heartbeat_inventory_action(action, expected_revision=expected_revision)
            self._restored = False
            self._last_success_at = ""

    def enrich_targets(self, targets):
        # Ground can supplement locations, never create/remove probe identities.
        with self._heartbeat_lock:
            self._enrichment = {target.target_ip: target for target in targets}

    def status(self):
        # Fleet invokes the callback while holding its own lock; always read
        # Fleet before taking the state lock to preserve that lock order.
        target_count = self.fleet_ping.target_count
        process_count = self.fleet_ping.process_count
        last_sample_at = self.fleet_ping.last_sample_at
        fleet_error = self.fleet_ping.last_error
        with self._heartbeat_lock:
            return HeartbeatRuntimeDTO(
                state=("HEARTBEAT_DEGRADED" if self._runtime_state == "RUNNING" and
                       (fleet_error or self._heartbeat_event_error or self._inventory_error) else self._runtime_state), enabled=self._config.enabled,
                target_count=target_count,
                process_count=process_count,
                last_sample_at=last_sample_at,
                last_success_at=self._last_success_at,
                last_error=self._last_error or fleet_error or self._heartbeat_event_error or self._inventory_error,
                pending_events=len(self._heartbeat_pending_events),
                pending_loss_events=len(self._heartbeat_pending_loss_events),
            )

    def _run(self):
        while not self._stop_event.is_set():
            delay = self.tick_seconds
            try:
                with self._operation_lock:
                    if self._stop_event.is_set():
                        break
                    self._tick()
                self._failure_count = 0
                self._last_error = ""
            except Exception as exc:
                self._failure_count += 1
                self._runtime_state = "HEARTBEAT_DEGRADED"
                self._last_error = f"{type(exc).__name__}: {exc}"
                LOGGER.exception("Heartbeat tick failed: site=%s", self.site_id)
                delay = min(30.0, 2 ** min(self._failure_count, 5))
            self._wake_event.wait(delay)
            self._wake_event.clear()

    def _refresh_inventory(self):
        if time.monotonic() >= self._inventory_refresh_at:
            self._inventory_refresh_at = time.monotonic() + 5.0
            # Explicit CLEAR_DEVICES suppresses automatic regeneration.
            if self.repository.heartbeat_inventory_state()["enabled"]:
                preview = self.inventory_sync.preview()
                if preview["conflicts"]:
                    raise ValueError(f"Heartbeat inventory conflict: {preview['conflicts']}")
                if any(preview[key] for key in ("added_count", "updated_count", "disabled_count")):
                    self.inventory_sync.synchronize()

    def _tick(self):
        if not self._config_initialized:
            self._config = self.repository.initialize_heartbeat_config()
            self._config_initialized = True
        else:
            self._config = self.repository.get_heartbeat_config()
        self._heartbeat_engine.sample_stale_seconds = max(
            5.0, (3 * self._config.interval_ms + self._config.timeout_ms) / 1000,
        )
        now = self._now()
        try:
            self._refresh_inventory()
            self._inventory_error = ""
        except Exception as exc:
            # Keep monitoring the last verified inventory during source faults.
            self._inventory_error = f"INVENTORY_REFRESH_FAILED: {type(exc).__name__}: {exc}"
        if not self._config.enabled:
            if self._fleet_started:
                result = self.fleet_ping.stop()
                if not result.get("success"):
                    raise RuntimeError(f"Heartbeat disable pending: {result}")
                self._fleet_started = False
                self._applied_config = None
                self._quiesce_heartbeat()
            self._runtime_state = "DISABLED"
            return
        if not self._restored:
            self.repository.migrate_resident_heartbeat(HEARTBEAT_STREAM_ID)
        self._configure_heartbeat_targets(HEARTBEAT_STREAM_ID)
        if not self._restored:
            rows = self.repository.list_heartbeat_snapshots(HEARTBEAT_STREAM_ID, entity_type="MR")
            self._heartbeat_engine.restore_snapshots(rows)
            self._last_success_at = max((str(ip.get("last_success_at") or "")
                for row in rows for ip in row["snapshot"].get("ip_states", [])), default="")
            self._restored = True
        if self._applied_config != self._config:
            if self._fleet_started:
                result = self.fleet_ping.stop()
                if not result.get("success"):
                    raise RuntimeError(f"Heartbeat reconfigure pending: {result}")
                self._fleet_started = False
            self.fleet_ping.start(
                run_id=HEARTBEAT_STREAM_ID, run_date="resident",
                active_dir=self.paths.ground_unattended_root(self.site_id) / "heartbeat",
                period_ms=self._config.interval_ms, timeout_ms=self._config.timeout_ms,
                packet_size=self._config.packet_size, shard_size=self._config.shard_size,
                warmup_seconds=self._config.warmup_seconds,
                correlation_tolerance_seconds=15, switch_before_seconds=5, switch_after_seconds=5,
            )
            self._fleet_started = True
            self._applied_config = self._config.model_copy(deep=True)
        desired = self._refresh_inventory_heartbeat({"run_id": HEARTBEAT_STREAM_ID}, now)
        with self._heartbeat_lock:
            enrichment = dict(self._enrichment)
        targets = []
        for ip, target in desired.items():
            candidate = enrichment.get(ip, target)
            if (candidate.mr_id, candidate.train_id, candidate.mr_position_code) != (
                target.mr_id, target.train_id, target.mr_position_code,
            ):
                candidate = target
            targets.append(candidate)
        self.fleet_ping.update_targets(targets)
        self.fleet_ping.flush_summaries()
        self._runtime_state = "HEARTBEAT_DEGRADED" if self.fleet_ping.last_error else "RUNNING"

    def _configure_heartbeat_targets(self, run_id: str) -> list[HeartbeatTarget]:
        """Build heartbeat identities from the persisted rail inventory.

        This path intentionally does not inspect AC rows or credentials.  The
        inventory is the monitoring authority; AC and SSH are supplemental
        capabilities used by the other workers.
        """
        grouped: dict[str, dict[str, Any]] = {}
        inventory_state = self.repository.heartbeat_inventory_state()
        inventory = (self.repository.list_inventory(include_removed=False)
                     if inventory_state["enabled"] else [])
        for train in inventory:
            train_id = str(train.get("train_id") or "").strip()
            if not train_id:
                continue
            for endpoint in train.get("endpoints") or []:
                if not isinstance(endpoint, dict):
                    continue
                mr_id = str(endpoint.get("device_uuid") or "").strip()
                role = str(endpoint.get("mr_role") or "").strip().upper()
                if not mr_id or role not in {"CT", "CW"}:
                    continue
                addresses: list[str] = []
                primary = str(endpoint.get("management_ip") or "").strip()
                if _valid_heartbeat_ip(primary):
                    addresses.append(primary)
                backup = str(endpoint.get("backup_management_ip") or "").strip()
                strategy = str(
                    endpoint.get("backup_monitoring_strategy") or "MONITOR"
                ).strip().upper()
                if _valid_heartbeat_ip(backup) and strategy == "MONITOR" and self._config.backup_policy == "MONITOR":
                    addresses.append(backup)
                if not addresses:
                    continue
                row = grouped.setdefault(
                    mr_id,
                    {"mr_uuid": mr_id, "train_id": train_id, "role": role, "ips": []},
                )
                row["ips"].extend(addresses)
        targets = [
            HeartbeatTarget(
                mr_uuid=str(row["mr_uuid"]),
                train_id=str(row["train_id"]),
                role=str(row["role"]),
                management_ips=tuple(dict.fromkeys(str(ip) for ip in row["ips"])),
            )
            for row in grouped.values()
        ]
        normalized_run_id = str(run_id)
        with self._heartbeat_lock:
            # An explicit clear must not reuse old in-memory counters.
            cleared_at = str(inventory_state.get("data_cleared_at") or "")
            if self._heartbeat_run_id and (
                self._heartbeat_run_id != normalized_run_id
                or getattr(self, "_heartbeat_cleared_at", "") != cleared_at
            ):
                self._heartbeat_engine = HeartbeatStateEngine(
                    event_sink=self._on_heartbeat_transition,
                )
                self._train_connectivity = TrainConnectivityAggregator(
                    event_sink=self._on_heartbeat_transition,
                )
                self._heartbeat_target_signature = ()
                self._heartbeat_dirty_mrs.clear()
                self._heartbeat_dirty_trains.clear()
                self._heartbeat_persist_after_mr = ""
                self._heartbeat_persist_after_train = ""
                self._heartbeat_pending_loss_events.clear()
                self._heartbeat_pending_events.clear()
                self._heartbeat_loss_trackers.clear()
            self._heartbeat_cleared_at = cleared_at
            self._heartbeat_run_id = normalized_run_id
            self._heartbeat_engine.configure_targets(targets)
            self._restore_heartbeat_loss_trackers(normalized_run_id, targets)
            signature = tuple(
                sorted(
                    (
                        target.mr_uuid,
                        target.train_id,
                        target.role,
                        target.management_ips,
                    )
                    for target in targets
                )
            )
            if signature != self._heartbeat_target_signature:
                self._train_connectivity.reconcile_targets(targets)
                if self._heartbeat_engine.ip_conflicts:
                    self.repository.add_health_event(
                        run_id=normalized_run_id, component="heartbeat",
                        severity="error", code="HEARTBEAT_IP_IDENTITY_CONFLICT",
                        message="管理 IP 被多个 MR 认领，冲突地址已停止监测",
                        details={"conflicts": self._heartbeat_engine.ip_conflicts},
                    )
                previous = {
                    item[0]: item for item in self._heartbeat_target_signature
                }
                for target in targets:
                    current = (
                        target.mr_uuid,
                        target.train_id,
                        target.role,
                        target.management_ips,
                    )
                    if previous.get(target.mr_uuid) != current:
                        self._heartbeat_dirty_mrs.add(target.mr_uuid)
                        self._heartbeat_dirty_trains.add(target.train_id)
                self._heartbeat_target_signature = signature
            self._heartbeat_engine.set_engine_state("RUNNING", at=self._now())
        return targets


    def _restore_heartbeat_loss_trackers(
        self, run_id: str, targets: list[HeartbeatTarget]
    ) -> None:
        by_mr = {target.mr_uuid: target for target in targets}
        valid_keys = {
            f"heartbeat:{target.mr_uuid}:{address}"
            for target in targets for address in target.management_ips
        }
        restored = {
            key: tracker for key, tracker in self._heartbeat_loss_trackers.items()
            if key in valid_keys
        }
        missing = valid_keys - restored.keys()
        if not missing:
            self._heartbeat_loss_trackers = restored
            return
        for row in self.repository.list_open_ping_loss_intervals(
            run_id, started_after=getattr(self, "_heartbeat_cleared_at", "")
        ):
            mr_id = str(row.get("mr_id") or "")
            target_ip = str(row.get("target_ip") or "")
            target = by_mr.get(mr_id)
            if not target_ip or target is None or target_ip not in target.management_ips:
                continue
            key = f"heartbeat:{mr_id}:{target_ip}"
            if key not in missing:
                continue
            tracker = PingLossTracker(key)
            tracker.restore(row)
            restored[key] = tracker
        for key in missing - restored.keys():
            restored[key] = PingLossTracker(key)
        self._heartbeat_loss_trackers = restored


    def _queue_heartbeat_loss_sample(
        self, target: FleetPingTarget, sample: Any, timestamp: datetime
    ) -> None:
        key = f"heartbeat:{target.mr_id}:{target.target_ip}"
        trackers = getattr(self, "_heartbeat_loss_trackers", None)
        if trackers is None:
            trackers = self._heartbeat_loss_trackers = {}
        tracker = trackers.setdefault(key, PingLossTracker(key))
        pending = getattr(self, "_heartbeat_pending_loss_events", None)
        if pending is None:
            pending = self._heartbeat_pending_loss_events = deque()
        try:
            tracker.enqueue_observation(
                pending,
                success=bool(sample.ok),
                at=timestamp,
                metadata={
                    "ap_name": target.current_ap_name,
                    "station": target.station,
                    "section": target.section,
                },
                fields=dict(run_id=self._heartbeat_run_id, target_ip=target.target_ip,
                            train_id=target.train_id, mr_id=target.mr_id, mr_role=target.mr_position_code),
            )
        except RuntimeError as exc:
            self._heartbeat_event_error = f"HEARTBEAT_EVENT_BACKLOG_FULL: {exc}"
            raise


    def _heartbeat_fleet_targets(self) -> dict[str, FleetPingTarget]:
        result: dict[str, FleetPingTarget] = {}
        conflicts: set[str] = set()
        if not self.repository.heartbeat_inventory_state()["enabled"]:
            return result
        for train in self.repository.list_inventory(include_removed=False):
            train_id = str(train.get("train_id") or "").strip()
            train_no = str(train.get("train_no") or train_id).strip()
            for endpoint in train.get("endpoints") or []:
                if not isinstance(endpoint, dict):
                    continue
                mr_id = str(endpoint.get("device_uuid") or "").strip()
                role = str(endpoint.get("mr_role") or "").strip().upper()
                if not train_id or not mr_id or role not in {"CT", "CW"}:
                    continue
                primary = str(endpoint.get("management_ip") or "").strip()
                backup = str(endpoint.get("backup_management_ip") or "").strip()
                strategy = str(endpoint.get("backup_monitoring_strategy") or "MONITOR").strip().upper()
                addresses = [primary]
                if _valid_heartbeat_ip(backup) and strategy == "MONITOR" and self._config.backup_policy == "MONITOR":
                    addresses.append(backup)
                for address in addresses:
                    if not _valid_heartbeat_ip(address) or address in conflicts:
                        continue
                    if address in result:
                        if result[address].mr_id != mr_id:
                            conflicts.add(address)
                            result.pop(address)
                        continue
                    result[address] = FleetPingTarget(
                        target_ip=address,
                        train_id=train_id,
                        train_no=train_no,
                        mr_id=mr_id,
                        mr_position_code=role,
                        mr_name=str(endpoint.get("device_name") or ""),
                        device_id=endpoint.get("device_id"),
                    )
        return result


    def _refresh_inventory_heartbeat(self, run: dict[str, Any], now: datetime) -> dict[str, FleetPingTarget]:
        self._configure_heartbeat_targets(str(run["run_id"]))
        desired = self._heartbeat_fleet_targets()
        with self._heartbeat_lock:
            transitions = self._heartbeat_engine.evaluate(at=now)
            self._mark_heartbeat_transitions_dirty(transitions)
            self._refresh_train_heartbeat_snapshots_locked(
                self._heartbeat_engine.snapshots(), at=now
            )
        self._persist_heartbeat_state(at=now)
        return desired


    def _on_fleet_ping_sample(self, target: FleetPingTarget, sample) -> None:
        with self._heartbeat_lock:
            run_id = self._heartbeat_run_id
        if not run_id or not target.mr_id:
            return
        try:
            timestamp = datetime.fromisoformat(str(sample.ts))
            if timestamp.tzinfo is None:
                timestamp = timestamp.astimezone()
            with self._heartbeat_lock:
                # A worker can finish a sample after stop() has been requested,
                # or a previous run's callback can arrive after a new run has
                # taken over.  Never let either callback mutate the new/final
                # heartbeat state.
                if self._heartbeat_run_id != run_id:
                    return
                transitions = self._heartbeat_engine.record_observation(
                    target.mr_id,
                    HeartbeatIpObservation(
                        ip=target.target_ip,
                        success=bool(sample.ok),
                        rtt_ms=sample.rtt_ms,
                    ),
                    at=timestamp,
                )
                snapshot = self._heartbeat_engine.snapshot(str(target.mr_id))
                if snapshot.engine_state != "RUNNING":
                    return
                if sample.ok:
                    self._last_success_at = timestamp.isoformat(timespec="milliseconds")
                self._queue_heartbeat_loss_sample(target, sample, timestamp)
                self._heartbeat_dirty_mrs.add(str(target.mr_id))
                self._mark_heartbeat_transitions_dirty(transitions)
                self._refresh_train_heartbeat_snapshots_locked(
                    (snapshot,), at=timestamp, advance_timers=False
                )
        except (KeyError, ValueError, TypeError) as exc:
            self.repository.add_health_event(
                run_id=run_id,
                component="heartbeat",
                severity="warning",
                code="HEARTBEAT_SAMPLE_IGNORED",
                message=f"{exc.__class__.__name__}: {exc}",
                details={"target_ip": target.target_ip, "mr_id": target.mr_id},
            )


    def _persist_heartbeat_state(self, *, at: datetime) -> None:
        # SQLite IO belongs to the scheduler, outside the probe/state lock.
        # Failed batches remain queued with stable dedup keys for the next tick.
        self._persist_heartbeat_events()
        updated_at = at.isoformat(timespec="milliseconds")
        with self._heartbeat_lock:
            run_id = self._heartbeat_run_id
            if not run_id:
                return
            force = self._heartbeat_force_persist
            mr_ids = sorted(self._heartbeat_dirty_mrs)
            train_ids = sorted(self._heartbeat_dirty_trains)
            if not force and not mr_ids and not train_ids:
                return
            if not force:
                mr_ids = _fair_persist_batch(
                    mr_ids,
                    after=self._heartbeat_persist_after_mr,
                    limit=_HEARTBEAT_PERSIST_BATCH_SIZE,
                )
                train_ids = _fair_persist_batch(
                    train_ids,
                    after=self._heartbeat_persist_after_train,
                    limit=_HEARTBEAT_PERSIST_BATCH_SIZE,
                )
                if mr_ids:
                    self._heartbeat_persist_after_mr = mr_ids[-1]
                if train_ids:
                    self._heartbeat_persist_after_train = train_ids[-1]
            records: list[dict[str, Any]] = []
            for mr_id in mr_ids:
                try:
                    snapshot = self._heartbeat_engine.snapshot(mr_id)
                except KeyError:
                    continue
                records.append(
                    {
                        "snapshot": snapshot.to_payload(),
                        "entity_type": "MR",
                        "entity_id": snapshot.mr_uuid,
                    }
                )
            for train_id in train_ids:
                train_snapshot = self._train_connectivity.snapshot(train_id)
                if train_snapshot is None:
                    continue
                records.append(
                    {
                        "snapshot": train_snapshot.to_payload(),
                        "entity_type": "TRAIN",
                        "entity_id": train_snapshot.train_id,
                    }
                )
            if not records:
                self._heartbeat_dirty_mrs.difference_update(mr_ids)
                self._heartbeat_dirty_trains.difference_update(train_ids)
                return
            self._heartbeat_dirty_mrs.difference_update(mr_ids)
            self._heartbeat_dirty_trains.difference_update(train_ids)
            self._heartbeat_force_persist = False
        try:
            batch = getattr(self.repository, "upsert_heartbeat_snapshots", None)
            if callable(batch):
                for offset in range(0, len(records), _HEARTBEAT_PERSIST_BATCH_SIZE):
                    batch(
                        run_id,
                        records[offset : offset + _HEARTBEAT_PERSIST_BATCH_SIZE],
                        updated_at=updated_at,
                    )
            else:
                for record in records:
                    self.repository.upsert_heartbeat_snapshot(
                        run_id,
                        record["snapshot"],
                        entity_type=record["entity_type"],
                        entity_id=record["entity_id"],
                        updated_at=updated_at,
                    )
        except Exception:
            with self._heartbeat_lock:
                if self._heartbeat_run_id == run_id:
                    self._heartbeat_dirty_mrs.update(mr_ids)
                    self._heartbeat_dirty_trains.update(train_ids)
            raise


    def _refresh_train_heartbeat_snapshots_locked(
        self,
        snapshots,
        *,
        at: datetime,
        advance_timers: bool = True,
    ) -> None:
        for snapshot in snapshots:
            try:
                previous = self._train_connectivity.snapshot(snapshot.train_id)
                current, _ = self._train_connectivity.update(snapshot, at=at)
            except ValueError:
                continue
            if current != previous:
                self._heartbeat_dirty_trains.add(current.train_id)
        if not advance_timers:
            return
        train_ids = {
            snapshot.train_id
            for snapshot in self._heartbeat_engine.snapshots()
            if snapshot.train_id
        }
        previous_by_train = {
            train_id: self._train_connectivity.snapshot(train_id)
            for train_id in train_ids
        }
        for current in self._train_connectivity.evaluate(at=at):
            if current != previous_by_train.get(current.train_id):
                self._heartbeat_dirty_trains.add(current.train_id)


    def _mark_heartbeat_transitions_dirty(
        self, transitions: list[HeartbeatTransition] | tuple[HeartbeatTransition, ...]
    ) -> None:
        for transition in transitions:
            if transition.entity_type == "MR":
                self._heartbeat_dirty_mrs.add(transition.entity_id)
            elif transition.entity_type == "TRAIN":
                self._heartbeat_dirty_trains.add(transition.entity_id)


    def _on_heartbeat_transition(self, transition: HeartbeatTransition) -> None:
        with self._heartbeat_lock:
            run_id = self._heartbeat_run_id
            if not run_id:
                return
            if len(self._heartbeat_pending_events) >= _HEARTBEAT_EVENT_CAPACITY:
                self._heartbeat_event_error = "HEARTBEAT_EVENT_BACKLOG_FULL: 心跳事件队列已满"
                LOGGER.error(self._heartbeat_event_error)
                raise RuntimeError(self._heartbeat_event_error)
            self._heartbeat_pending_events.append({
                "run_id": run_id, "event_type": transition.event_type,
                "severity": "warning" if "offline" in transition.event_type else "info",
                "train_id": transition.entity_id if transition.entity_type == "TRAIN" else "",
                "mr_id": transition.entity_id if transition.entity_type == "MR" else "",
                "title": "心跳状态变化",
                "message": f"{transition.previous_state} -> {transition.current_state}",
                "details": transition.to_payload(),
                "ts": transition.occurred_at.isoformat(timespec="milliseconds"),
                "dedup_key": "heartbeat:" + uuid.uuid4().hex,
            })


    def _persist_heartbeat_events(self) -> None:
        with self._heartbeat_event_flush_lock:
            with self._heartbeat_lock:
                batch = list(self._heartbeat_pending_events)
                loss_batch = list(getattr(self, "_heartbeat_pending_loss_events", ()))
            if loss_batch:
                try:
                    self.repository.apply_ping_loss_events(loss_batch)
                except Exception:
                    raise
                with self._heartbeat_lock:
                    acknowledge_loss_events(self._heartbeat_pending_loss_events, loss_batch)
            if not batch:
                return
            for offset in range(0, len(batch), _HEARTBEAT_PERSIST_BATCH_SIZE):
                records = batch[offset:offset + _HEARTBEAT_PERSIST_BATCH_SIZE]
                try:
                    self.repository.add_events_batch(records)
                except Exception as exc:
                    if not self._heartbeat_event_error.startswith("HEARTBEAT_EVENT_BACKLOG_FULL"):
                        self._heartbeat_event_error = f"HEARTBEAT_EVENT_WRITE_FAILED: {exc}"
                    raise
                with self._heartbeat_lock:
                    for _ in records:
                        self._heartbeat_pending_events.popleft()
            # A saturation incident needs an operator-visible health record even
            # after draining. Ordinary temporary write failures recover here.
            if not self._heartbeat_event_error.startswith("HEARTBEAT_EVENT_BACKLOG_FULL"):
                self._heartbeat_event_error = ""


    def _quiesce_heartbeat(self) -> None:
        """Reject late samples and persist the terminal heartbeat state."""
        with self._heartbeat_lock:
            if not self._heartbeat_run_id:
                return
            now = self._now()
            transitions = self._heartbeat_engine.set_engine_state("STOPPED", at=now)
            self._mark_heartbeat_transitions_dirty(transitions)
            snapshots = self._heartbeat_engine.snapshots()
            self._heartbeat_dirty_mrs.update(snapshot.mr_uuid for snapshot in snapshots)
            self._refresh_train_heartbeat_snapshots_locked(
                snapshots, at=now, advance_timers=False
            )
            self._heartbeat_force_persist = True
        self._persist_heartbeat_state(at=now)
