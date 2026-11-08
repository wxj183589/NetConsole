from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping


MR_OFFLINE_THRESHOLD_SECONDS = 10.0
MR_RECOVERY_SUCCESSES = 2
TRAIN_OFFLINE_THRESHOLD_SECONDS = 120.0


@dataclass(frozen=True)
class HeartbeatTarget:
    """A base-data MR identity and the management IPs explicitly eligible for monitoring."""

    mr_uuid: str
    train_id: str
    role: str
    management_ips: tuple[str, ...]


@dataclass(frozen=True)
class HeartbeatIpObservation:
    ip: str
    success: bool
    rtt_ms: float | None = None


@dataclass(frozen=True)
class HeartbeatTransition:
    entity_type: str
    entity_id: str
    previous_state: str
    current_state: str
    event_type: str
    occurred_at: datetime

    def to_payload(self) -> dict[str, str]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "previous_state": self.previous_state,
            "current_state": self.current_state,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(timespec="milliseconds"),
        }


@dataclass(frozen=True)
class HeartbeatIpSnapshot:
    ip: str
    sent_count: int
    received_count: int
    lost_count: int
    min_rtt_ms: float | None
    avg_rtt_ms: float | None
    max_rtt_ms: float | None
    last_probe_at: datetime | None
    last_success_at: datetime | None
    unreachable_since: datetime | None

    def to_payload(self) -> dict[str, object]:
        return {
            "ip": self.ip,
            "sent_count": self.sent_count,
            "received_count": self.received_count,
            "lost_count": self.lost_count,
            "min_rtt_ms": self.min_rtt_ms,
            "avg_rtt_ms": self.avg_rtt_ms,
            "max_rtt_ms": self.max_rtt_ms,
            "last_probe_at": _iso(self.last_probe_at),
            "last_success_at": _iso(self.last_success_at),
            "unreachable_since": _iso(self.unreachable_since),
        }


@dataclass(frozen=True)
class HeartbeatMrSnapshot:
    mr_uuid: str
    train_id: str
    role: str
    status: str
    unreachable_since: datetime | None
    last_success_at: datetime | None
    last_recovery_at: datetime | None
    consecutive_recovery_successes: int
    engine_state: str
    ip_states: tuple[HeartbeatIpSnapshot, ...]
    offline_event_open: bool = False
    previously_confirmed_offline: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "mr_uuid": self.mr_uuid,
            "train_id": self.train_id,
            "role": self.role,
            "status": self.status,
            "unreachable_since": _iso(self.unreachable_since),
            "last_success_at": _iso(self.last_success_at),
            "last_recovery_at": _iso(self.last_recovery_at),
            "consecutive_recovery_successes": self.consecutive_recovery_successes,
            "engine_state": self.engine_state,
            "offline_event_open": self.offline_event_open,
            "previously_confirmed_offline": self.previously_confirmed_offline,
            "ip_states": [value.to_payload() for value in self.ip_states],
        }


@dataclass(frozen=True)
class TrainConnectivitySnapshot:
    train_id: str
    status: str
    both_unreachable_since: datetime | None
    mr_states: Mapping[str, str]

    def to_payload(self) -> dict[str, object]:
        return {
            "train_id": self.train_id,
            "status": self.status,
            "both_unreachable_since": _iso(self.both_unreachable_since),
            "mr_states": dict(self.mr_states),
        }


@dataclass
class _IpState:
    sent_count: int = 0
    received_count: int = 0
    lost_count: int = 0
    rtt_total_ms: float = 0.0
    rtt_count: int = 0
    min_rtt_ms: float | None = None
    max_rtt_ms: float | None = None
    last_probe_at: datetime | None = None
    last_success_at: datetime | None = None
    unreachable_since: datetime | None = None
    has_live_success: bool = False

    def observe(self, value: HeartbeatIpObservation, at: datetime) -> None:
        self.sent_count += 1
        self.last_probe_at = at
        if value.success:
            self.received_count += 1
            self.last_success_at = at
            self.unreachable_since = None
            self.has_live_success = True
            if value.rtt_ms is not None:
                self.rtt_count += 1
                self.rtt_total_ms += value.rtt_ms
                self.min_rtt_ms = (
                    value.rtt_ms
                    if self.min_rtt_ms is None
                    else min(self.min_rtt_ms, value.rtt_ms)
                )
                self.max_rtt_ms = (
                    value.rtt_ms
                    if self.max_rtt_ms is None
                    else max(self.max_rtt_ms, value.rtt_ms)
                )
        else:
            self.lost_count += 1
            if self.unreachable_since is None:
                # A success before a sampler gap or Backend restart is historical
                # data, not evidence that the target was observed continuously.
                self.unreachable_since = (
                    self.last_success_at if self.has_live_success else at
                )

    def snapshot(self, ip: str) -> HeartbeatIpSnapshot:
        return HeartbeatIpSnapshot(
            ip=ip,
            sent_count=self.sent_count,
            received_count=self.received_count,
            lost_count=self.lost_count,
            min_rtt_ms=self.min_rtt_ms,
            avg_rtt_ms=(
                self.rtt_total_ms / self.rtt_count
                if self.rtt_count
                else None
            ),
            max_rtt_ms=self.max_rtt_ms,
            last_probe_at=self.last_probe_at,
            last_success_at=self.last_success_at,
            unreachable_since=self.unreachable_since,
        )


@dataclass
class _MrState:
    target: HeartbeatTarget
    ip_states: dict[str, _IpState]
    status: str = "UNKNOWN"
    unreachable_since: datetime | None = None
    last_success_at: datetime | None = None
    last_recovery_at: datetime | None = None
    recovery_successes: int = 0
    offline_event_open: bool = False
    previously_confirmed_offline: bool = False
    engine_state: str = "STOPPED"
    last_recovery_sample_bucket: int | None = None


class HeartbeatStateEngine:
    """Aggregate per-IP heartbeat cycles into persisted-ready MR transitions.

    The caller supplies complete cycles: each configured, monitor-eligible IP is
    represented once, and the MR is reachable when any observation succeeds.
    Cycles received while the engine is unavailable do not constitute device
    evidence. A scheduler should call ``evaluate`` to advance timeout states.
    """

    def __init__(
        self,
        *,
        offline_threshold_seconds: float = MR_OFFLINE_THRESHOLD_SECONDS,
        recovery_successes: int = MR_RECOVERY_SUCCESSES,
        sample_stale_seconds: float = 5.0,
        clock: Callable[[], datetime] | None = None,
        event_sink: Callable[[HeartbeatTransition], None] | None = None,
    ) -> None:
        if offline_threshold_seconds <= 0:
            raise ValueError("offline_threshold_seconds must be positive")
        if recovery_successes < 1:
            raise ValueError("recovery_successes must be at least one")
        if sample_stale_seconds <= 0:
            raise ValueError("sample_stale_seconds must be positive")
        self.offline_threshold_seconds = float(offline_threshold_seconds)
        self.recovery_successes = int(recovery_successes)
        self.sample_stale_seconds = float(sample_stale_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.event_sink = event_sink
        self._mrs: dict[str, _MrState] = {}

    def configure_targets(self, targets: Iterable[HeartbeatTarget]) -> None:
        """Replace the active target set while retaining matching MR runtime state."""
        targets = tuple(targets)
        owners: dict[str, set[str]] = {}
        for target in targets:
            for ip in target.management_ips:
                owners.setdefault(str(ip).strip(), set()).add(target.mr_uuid)
        self.ip_conflicts = {ip: tuple(sorted(ids)) for ip, ids in owners.items() if len(ids) > 1}
        incoming: dict[str, _MrState] = {}
        for target in targets:
            mr_uuid = str(target.mr_uuid).strip()
            ips = tuple(dict.fromkeys(str(ip).strip() for ip in target.management_ips if str(ip).strip() and str(ip).strip() not in self.ip_conflicts))
            if not mr_uuid:
                continue
            normalized = HeartbeatTarget(
                mr_uuid=mr_uuid,
                train_id=str(target.train_id).strip(),
                role=str(target.role).strip().upper(),
                management_ips=ips,
            )
            previous = self._mrs.get(mr_uuid)
            if previous is not None and previous.target != normalized:
                previous = None
            retained = previous.ip_states if previous else {}
            incoming[mr_uuid] = _MrState(
                target=normalized,
                ip_states={ip: retained.get(ip, _IpState()) for ip in ips},
                status=previous.status if previous else "UNKNOWN",
                unreachable_since=previous.unreachable_since if previous else None,
                last_success_at=previous.last_success_at if previous else None,
                last_recovery_at=previous.last_recovery_at if previous else None,
                recovery_successes=previous.recovery_successes if previous else 0,
                offline_event_open=previous.offline_event_open if previous else False,
                previously_confirmed_offline=(
                    previous.previously_confirmed_offline if previous else False
                ),
                engine_state=previous.engine_state if previous else "STOPPED",
                last_recovery_sample_bucket=(
                    previous.last_recovery_sample_bucket if previous else None
                ),
            )
        self._mrs = incoming

    def restore_snapshots(self, rows: Iterable[Mapping[str, object]]) -> list[HeartbeatTransition]:
        """Restore durable counters and last-success timestamps without carrying an outage across restart."""
        restored_at = _as_utc(self.clock())
        by_id: dict[str, Mapping[str, object]] = {}
        for row in rows:
            entity_id = str(row.get("entity_id") or "").strip()
            snapshot = row.get("snapshot")
            if entity_id and isinstance(snapshot, Mapping):
                by_id[entity_id] = snapshot
        transitions: list[HeartbeatTransition] = []
        for mr_uuid, mr in self._mrs.items():
            payload = by_id.get(mr_uuid)
            if payload is None:
                continue
            previous = str(payload.get("status") or "UNKNOWN").upper()
            ip_payloads = payload.get("ip_states")
            if isinstance(ip_payloads, list):
                restored: dict[str, _IpState] = {}
                for raw_ip_state in ip_payloads:
                    if not isinstance(raw_ip_state, Mapping):
                        continue
                    ip = str(raw_ip_state.get("ip") or "").strip()
                    if ip not in mr.ip_states:
                        continue
                    restored[ip] = _restore_ip_state(raw_ip_state)
                for ip in mr.target.management_ips:
                    if ip in restored:
                        mr.ip_states[ip] = restored[ip]
            mr.last_success_at = _parse_iso_datetime(payload.get("last_success_at"))
            mr.last_recovery_at = _parse_iso_datetime(payload.get("last_recovery_at"))
            mr.unreachable_since = None
            mr.recovery_successes = 0
            mr.offline_event_open = bool(payload.get("offline_event_open"))
            mr.previously_confirmed_offline = bool(
                payload.get("previously_confirmed_offline")
                or previous == "OFFLINE"
            )
            mr.last_recovery_sample_bucket = None
            mr.status = "UNKNOWN"
            mr.engine_state = "DEGRADED"
            # The old probe time remains historical data in SQLite but is not
            # live evidence after a backend restart.
            for ip_state in mr.ip_states.values():
                ip_state.last_probe_at = None
                ip_state.unreachable_since = None
                ip_state.has_live_success = False
            transitions.append(
                HeartbeatTransition(
                    "MR", mr_uuid, previous, "UNKNOWN",
                    "heartbeat_sampling_interrupted", restored_at,
                )
            )
        return self._emit(transitions)

    def set_engine_state(self, state: str, *, at: datetime | None = None) -> list[HeartbeatTransition]:
        """Mark the sampling engine state without translating an outage to device loss."""
        timestamp = _as_utc(at or self.clock())
        normalized = str(state).strip().upper()
        if normalized not in {"RUNNING", "DEGRADED", "STOPPED"}:
            raise ValueError("engine state must be RUNNING, DEGRADED, or STOPPED")
        transitions: list[HeartbeatTransition] = []
        for mr in self._mrs.values():
            previous = mr.status
            mr.engine_state = normalized
            if normalized != "RUNNING":
                # A sampler gap breaks continuous-unreachable evidence. Preserve a
                # confirmed alarm episode for recovery confirmation, but require a
                # fresh ten-second failure interval before any new offline event.
                mr.unreachable_since = None
                mr.recovery_successes = 0
                self._reset_ip_outage_baselines(mr)
                if mr.status != "UNKNOWN":
                    mr.status = "UNKNOWN"
                    transitions.append(
                        HeartbeatTransition(
                            "MR", mr.target.mr_uuid, previous, "UNKNOWN",
                            "heartbeat_engine_unavailable", timestamp,
                        )
                    )
            elif mr.status == "UNKNOWN":
                # A running process alone is not evidence of device reachability.
                mr.unreachable_since = None
        return self._emit(transitions)

    def record_cycle(
        self,
        mr_uuid: str,
        observations: Mapping[str, HeartbeatIpObservation | bool | tuple[bool, float | None]],
        *,
        at: datetime | None = None,
    ) -> list[HeartbeatTransition]:
        """Record one complete probe cycle for the MR's eligible management IPs."""
        mr = self._mrs.get(str(mr_uuid))
        if mr is None:
            raise KeyError(f"unknown heartbeat target: {mr_uuid}")
        timestamp = _as_utc(at or self.clock())
        if mr.engine_state != "RUNNING":
            return []
        transitions = self._check_arriving_probe_gap(mr, timestamp, observations)
        mr.engine_state = "RUNNING"
        values: list[HeartbeatIpObservation] = []
        for ip, raw in observations.items():
            if ip not in mr.ip_states:
                continue
            observation = _coerce_observation(ip, raw)
            mr.ip_states[ip].observe(observation, timestamp)
            values.append(observation)
        if not values:
            return []
        if set(observations).intersection(mr.ip_states) != set(mr.ip_states):
            # Partial sampling cannot prove that every eligible route was checked.
            # Mark the engine degraded for this MR and discard outage continuity.
            return self.mark_mr_sampling_gap(mr_uuid, at=timestamp)

        if any(value.success for value in values):
            return transitions + self._record_success(mr, timestamp)
        return transitions + self._record_failure(mr, timestamp)

    def record_observation(
        self,
        mr_uuid: str,
        observation: HeartbeatIpObservation | bool | tuple[bool, float | None],
        *,
        at: datetime | None = None,
    ) -> list[HeartbeatTransition]:
        """Ingest one per-IP fping result while requiring fresh evidence for every configured IP."""
        mr = self._mrs.get(str(mr_uuid))
        if mr is None:
            raise KeyError(f"unknown heartbeat target: {mr_uuid}")
        timestamp = _as_utc(at or self.clock())
        ip = observation.ip if isinstance(observation, HeartbeatIpObservation) else ""
        if isinstance(observation, tuple):
            raise ValueError("record_observation requires an IP-bearing observation")
        if not ip or ip not in mr.ip_states:
            raise ValueError(f"unknown heartbeat IP for target: {ip}")
        value = _coerce_observation(ip, observation)
        if mr.engine_state == "STOPPED":
            return []
        transitions = self._check_arriving_probe_gap(mr, timestamp, (ip,))
        # A new complete per-IP fping result is fresh engine evidence, including
        # after a previous sampler gap. It never bridges the outage timer.
        mr.engine_state = "RUNNING"
        mr.ip_states[ip].observe(value, timestamp)
        if value.success:
            bucket = int(timestamp.timestamp())
            return transitions + self._record_success(mr, timestamp, recovery_bucket=bucket)
        if not self._all_ip_samples_fresh(mr, timestamp):
            if mr.status != "UNKNOWN":
                return self.mark_mr_sampling_gap(mr_uuid, at=timestamp)
            return []
        unreachable = [state.unreachable_since for state in mr.ip_states.values()]
        if all(value is not None for value in unreachable):
            mr.unreachable_since = max(value for value in unreachable if value is not None)
            return transitions + self._record_failure(mr, timestamp)
        return transitions

    def _check_arriving_probe_gap(
        self, mr: _MrState, at: datetime, ips: Iterable[str],
    ) -> list[HeartbeatTransition]:
        # Check the previous timestamp before replacing it with the new sample.
        if any(
            state.last_probe_at is not None
            and (at - state.last_probe_at).total_seconds() > self.sample_stale_seconds
            for ip in ips if (state := mr.ip_states.get(ip)) is not None
        ):
            transitions = self.mark_mr_sampling_gap(mr.target.mr_uuid, at=at)
            for state in mr.ip_states.values():
                state.last_probe_at = None
            return transitions
        return []

    def mark_mr_sampling_gap(
        self, mr_uuid: str, *, at: datetime | None = None
    ) -> list[HeartbeatTransition]:
        mr = self._mrs.get(str(mr_uuid))
        if mr is None:
            raise KeyError(f"unknown heartbeat target: {mr_uuid}")
        timestamp = _as_utc(at or self.clock())
        previous = mr.status
        mr.engine_state = "DEGRADED"
        mr.unreachable_since = None
        mr.recovery_successes = 0
        self._reset_ip_outage_baselines(mr)
        if previous == "UNKNOWN":
            return []
        mr.status = "UNKNOWN"
        return self._emit(
            [HeartbeatTransition(
                "MR", mr.target.mr_uuid, previous, "UNKNOWN",
                "heartbeat_sampling_interrupted", timestamp,
            )]
        )

    def evaluate(self, *, at: datetime | None = None) -> list[HeartbeatTransition]:
        """Advance loss/offline states, but only while fresh sampler evidence exists."""
        timestamp = _as_utc(at or self.clock())
        transitions: list[HeartbeatTransition] = []
        for mr in self._mrs.values():
            if mr.engine_state != "RUNNING":
                continue
            last_probes = [value.last_probe_at for value in mr.ip_states.values()]
            if any(
                last_probe is None
                or (timestamp - last_probe).total_seconds() > self.sample_stale_seconds
                for last_probe in last_probes
            ):
                previous = mr.status
                mr.engine_state = "DEGRADED"
                mr.unreachable_since = None
                mr.recovery_successes = 0
                self._reset_ip_outage_baselines(mr)
                if previous != "UNKNOWN":
                    mr.status = "UNKNOWN"
                    transitions.append(
                        HeartbeatTransition(
                            "MR", mr.target.mr_uuid, previous, "UNKNOWN",
                            "heartbeat_sampling_interrupted", timestamp,
                        )
                    )
                continue
            unreachable = [value.unreachable_since for value in mr.ip_states.values()]
            if not all(value is not None for value in unreachable):
                mr.unreachable_since = None
                continue
            mr.unreachable_since = max(value for value in unreachable if value is not None)
            outage_seconds = (timestamp - mr.unreachable_since).total_seconds()
            if outage_seconds >= self.offline_threshold_seconds:
                if mr.status != "OFFLINE":
                    previous = mr.status
                    mr.status = "OFFLINE"
                    mr.previously_confirmed_offline = True
                    if not mr.offline_event_open:
                        mr.offline_event_open = True
                        transitions.append(
                            HeartbeatTransition(
                                "MR", mr.target.mr_uuid, previous, "OFFLINE",
                                "mr_offline", timestamp,
                            )
                        )
            elif mr.status not in {"OFFLINE_PENDING", "RECOVERING"}:
                previous = mr.status
                mr.status = "OFFLINE_PENDING"
                transitions.append(
                    HeartbeatTransition(
                        "MR", mr.target.mr_uuid, previous, "OFFLINE_PENDING",
                        "mr_loss_pending", timestamp,
                    )
                )
        return self._emit(transitions)

    def snapshot(self, mr_uuid: str) -> HeartbeatMrSnapshot:
        mr = self._mrs[str(mr_uuid)]
        return HeartbeatMrSnapshot(
            mr_uuid=mr.target.mr_uuid,
            train_id=mr.target.train_id,
            role=mr.target.role,
            status=mr.status,
            unreachable_since=mr.unreachable_since,
            last_success_at=mr.last_success_at,
            last_recovery_at=mr.last_recovery_at,
            consecutive_recovery_successes=mr.recovery_successes,
            engine_state=mr.engine_state,
            ip_states=tuple(
                mr.ip_states[ip].snapshot(ip) for ip in mr.target.management_ips
            ),
            offline_event_open=mr.offline_event_open,
            previously_confirmed_offline=mr.previously_confirmed_offline,
        )

    def snapshots(self) -> tuple[HeartbeatMrSnapshot, ...]:
        return tuple(self.snapshot(mr_uuid) for mr_uuid in sorted(self._mrs))

    def _record_success(
        self,
        mr: _MrState,
        at: datetime,
        *,
        recovery_bucket: int | None = None,
    ) -> list[HeartbeatTransition]:
        mr.last_success_at = at
        mr.unreachable_since = None
        if recovery_bucket is not None:
            if mr.last_recovery_sample_bucket == recovery_bucket and (
                mr.previously_confirmed_offline
                or mr.offline_event_open
                or mr.status == "RECOVERING"
            ):
                return []
            mr.last_recovery_sample_bucket = recovery_bucket
        if mr.previously_confirmed_offline or mr.offline_event_open or mr.status == "RECOVERING":
            previous = mr.status
            mr.recovery_successes += 1
            if mr.recovery_successes < self.recovery_successes:
                mr.status = "RECOVERING"
                if previous != "RECOVERING":
                    return self._emit(
                        [HeartbeatTransition(
                            "MR", mr.target.mr_uuid, previous, "RECOVERING",
                            "mr_recovering", at,
                        )]
                    )
                return []
            mr.status = "ONLINE"
            mr.last_recovery_at = at
            mr.offline_event_open = False
            mr.previously_confirmed_offline = False
            mr.recovery_successes = 0
            return self._emit(
                [HeartbeatTransition(
                    "MR", mr.target.mr_uuid, previous, "ONLINE", "mr_recovered", at
                )]
            )
        previous = mr.status
        mr.status = "ONLINE"
        mr.recovery_successes = 0
        if previous == "ONLINE":
            return []
        return self._emit(
            [HeartbeatTransition(
                "MR", mr.target.mr_uuid, previous, "ONLINE", "mr_online", at
            )]
        )

    def _record_failure(self, mr: _MrState, at: datetime) -> list[HeartbeatTransition]:
        previous = mr.status
        if mr.unreachable_since is None:
            # Each eligible management address must have fresh failed evidence.
            # The latest first-failure timestamp starts the MR-wide outage.
            starts = [state.unreachable_since for state in mr.ip_states.values()]
            mr.unreachable_since = (
                max(value for value in starts if value is not None)
                if starts and all(value is not None for value in starts)
                else at
            )
        if mr.status == "RECOVERING":
            mr.recovery_successes = 0
            mr.last_recovery_sample_bucket = None
        elapsed = (at - mr.unreachable_since).total_seconds()
        if elapsed >= self.offline_threshold_seconds:
            mr.status = "OFFLINE"
            mr.previously_confirmed_offline = True
            if not mr.offline_event_open:
                mr.offline_event_open = True
                return self._emit(
                    [HeartbeatTransition(
                        "MR", mr.target.mr_uuid, previous, "OFFLINE", "mr_offline", at
                    )]
                )
        else:
            mr.status = "OFFLINE_PENDING"
        if mr.status == previous:
            return []
        event_type = "mr_loss_pending" if mr.status == "OFFLINE_PENDING" else "mr_offline"
        return self._emit(
            [HeartbeatTransition(
                "MR", mr.target.mr_uuid, previous, mr.status, event_type, at
            )]
        )

    def _all_ip_samples_fresh(self, mr: _MrState, at: datetime) -> bool:
        return bool(mr.ip_states) and all(
            state.last_probe_at is not None
            and (at - state.last_probe_at).total_seconds() <= self.sample_stale_seconds
            for state in mr.ip_states.values()
        )

    @staticmethod
    def _reset_ip_outage_baselines(mr: _MrState) -> None:
        for state in mr.ip_states.values():
            state.unreachable_since = None
            state.has_live_success = False

    def _emit(self, transitions: list[HeartbeatTransition]) -> list[HeartbeatTransition]:
        if self.event_sink:
            for transition in transitions:
                self.event_sink(transition)
        return transitions


class TrainConnectivityAggregator:
    """Apply the train-level two-endpoint outage intersection rule."""

    def __init__(
        self,
        *,
        offline_threshold_seconds: float = TRAIN_OFFLINE_THRESHOLD_SECONDS,
        event_sink: Callable[[HeartbeatTransition], None] | None = None,
    ) -> None:
        if offline_threshold_seconds <= 0:
            raise ValueError("offline_threshold_seconds must be positive")
        self.offline_threshold_seconds = float(offline_threshold_seconds)
        self.event_sink = event_sink
        self._states: dict[str, TrainConnectivitySnapshot] = {}
        self._members: dict[str, dict[str, HeartbeatMrSnapshot]] = {}
        self._offline_events_open: set[str] = set()

    def reconcile_targets(self, targets: Iterable[HeartbeatTarget]) -> None:
        """Discard members and alarm episodes whose inventory identity changed."""
        expected = {(target.train_id, target.role): target.mr_uuid for target in targets}
        for train_id, members in tuple(self._members.items()):
            retained = {
                role: member for role, member in members.items()
                if expected.get((train_id, role)) == member.mr_uuid
            }
            if len(retained) != len(members):
                self._states.pop(train_id, None)
                self._offline_events_open.discard(train_id)
            if retained:
                self._members[train_id] = retained
            else:
                self._members.pop(train_id, None)

    def update(
        self,
        mr: HeartbeatMrSnapshot,
        *,
        at: datetime | None = None,
    ) -> tuple[TrainConnectivitySnapshot, list[HeartbeatTransition]]:
        timestamp = _as_utc(at or datetime.now(timezone.utc))
        train_id = mr.train_id
        if not train_id:
            raise ValueError("train_id is required for train aggregation")
        role = mr.role.upper()
        if role not in {"CT", "CW"}:
            raise ValueError("train endpoint role must be CT or CW")
        members = self._members.setdefault(train_id, {})
        members[role] = mr
        return self._evaluate_and_emit(train_id, members, timestamp)

    def evaluate(
        self, *, at: datetime | None = None
    ) -> tuple[TrainConnectivitySnapshot, ...]:
        """Advance train offline timers even when no MR state changed this cycle."""
        timestamp = _as_utc(at or datetime.now(timezone.utc))
        snapshots: list[TrainConnectivitySnapshot] = []
        for train_id, members in self._members.items():
            snapshot, _ = self._evaluate_and_emit(train_id, members, timestamp)
            snapshots.append(snapshot)
        return tuple(snapshots)

    def _evaluate_and_emit(
        self,
        train_id: str,
        members: Mapping[str, HeartbeatMrSnapshot],
        timestamp: datetime,
    ) -> tuple[TrainConnectivitySnapshot, list[HeartbeatTransition]]:
        previous = self._states.get(train_id)
        snapshot = self._evaluate(train_id, members, timestamp)
        self._states[train_id] = snapshot
        transitions: list[HeartbeatTransition] = []
        prior_status = previous.status if previous else "UNKNOWN"
        if snapshot.status != prior_status:
            if snapshot.status == "TRAIN_OFFLINE" and train_id not in self._offline_events_open:
                self._offline_events_open.add(train_id)
                event_type = "train_offline"
            elif train_id in self._offline_events_open and snapshot.status in {
                "BOTH_ONLINE", "CT_ONLY", "CW_ONLY",
            }:
                self._offline_events_open.discard(train_id)
                event_type = "train_recovered"
            else:
                event_type = "train_connectivity_changed"
            transitions.append(
                HeartbeatTransition(
                    "TRAIN", train_id, prior_status, snapshot.status,
                    event_type, timestamp,
                )
            )
        if self.event_sink:
            for transition in transitions:
                self.event_sink(transition)
        return snapshot, transitions

    def snapshot(self, train_id: str) -> TrainConnectivitySnapshot | None:
        return self._states.get(str(train_id))

    def _evaluate(
        self,
        train_id: str,
        members: Mapping[str, HeartbeatMrSnapshot],
        now: datetime,
    ) -> TrainConnectivitySnapshot:
        if set(members) not in ({"CT"}, {"CW"}, {"CT", "CW"}):
            return TrainConnectivitySnapshot(train_id, "UNKNOWN", None, {})
        role_states = {role: member.status for role, member in members.items()}
        if len(members) == 1:
            role, member = next(iter(members.items()))
            if member.status == "UNKNOWN":
                status = "UNKNOWN"
            elif member.status == "OFFLINE":
                status = "SINGLE_OFFLINE"
            elif member.status == "OFFLINE_PENDING":
                status = "SINGLE_UNREACHABLE_PENDING"
            elif member.status == "RECOVERING":
                status = "SINGLE_RECOVERING"
            else:
                status = "SINGLE_ONLINE"
            return TrainConnectivitySnapshot(
                train_id, status, member.unreachable_since if status == "SINGLE_UNREACHABLE_PENDING" else None,
                role_states,
            )
        ct = members.get("CT")
        cw = members.get("CW")
        if ct is None or cw is None or "UNKNOWN" in {ct.status, cw.status}:
            return TrainConnectivitySnapshot(train_id, "UNKNOWN", None, role_states)
        ct_reachable = ct.status in {"ONLINE", "RECOVERING"}
        cw_reachable = cw.status in {"ONLINE", "RECOVERING"}
        if ct_reachable and cw_reachable:
            return TrainConnectivitySnapshot(train_id, "BOTH_ONLINE", None, role_states)
        if ct_reachable:
            return TrainConnectivitySnapshot(train_id, "CT_ONLY", None, role_states)
        if cw_reachable:
            return TrainConnectivitySnapshot(train_id, "CW_ONLY", None, role_states)
        if ct.status not in {"OFFLINE_PENDING", "OFFLINE"} or cw.status not in {"OFFLINE_PENDING", "OFFLINE"}:
            return TrainConnectivitySnapshot(train_id, "UNKNOWN", None, role_states)
        starts = [ct.unreachable_since, cw.unreachable_since]
        if any(value is None for value in starts):
            return TrainConnectivitySnapshot(train_id, "UNKNOWN", None, role_states)
        both_unreachable_since = max(value for value in starts if value is not None)
        elapsed = (now - both_unreachable_since).total_seconds()
        status = (
            "TRAIN_OFFLINE"
            if elapsed >= self.offline_threshold_seconds
            else "BOTH_UNREACHABLE_PENDING"
        )
        return TrainConnectivitySnapshot(train_id, status, both_unreachable_since, role_states)


def _coerce_observation(
    ip: str,
    value: HeartbeatIpObservation | bool | tuple[bool, float | None],
) -> HeartbeatIpObservation:
    if isinstance(value, HeartbeatIpObservation):
        return HeartbeatIpObservation(ip=ip, success=value.success, rtt_ms=value.rtt_ms)
    if isinstance(value, tuple):
        success, rtt = value
        return HeartbeatIpObservation(ip=ip, success=bool(success), rtt_ms=rtt)
    return HeartbeatIpObservation(ip=ip, success=bool(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return _as_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def _nonnegative_int(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _restore_ip_state(payload: Mapping[str, object]) -> _IpState:
    received_count = _nonnegative_int(payload.get("received_count"))
    average = _finite_float(payload.get("avg_rtt_ms"))
    rtt_count = received_count if average is not None else 0
    return _IpState(
        sent_count=_nonnegative_int(payload.get("sent_count")),
        received_count=received_count,
        lost_count=_nonnegative_int(payload.get("lost_count")),
        rtt_total_ms=(average or 0.0) * rtt_count,
        rtt_count=rtt_count,
        min_rtt_ms=_finite_float(payload.get("min_rtt_ms")),
        max_rtt_ms=_finite_float(payload.get("max_rtt_ms")),
        last_probe_at=_parse_iso_datetime(payload.get("last_probe_at")),
        last_success_at=_parse_iso_datetime(payload.get("last_success_at")),
        unreachable_since=_parse_iso_datetime(payload.get("unreachable_since")),
    )


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="milliseconds") if value else ""


__all__ = [
    "HeartbeatIpObservation",
    "HeartbeatIpSnapshot",
    "HeartbeatMrSnapshot",
    "HeartbeatStateEngine",
    "HeartbeatTarget",
    "HeartbeatTransition",
    "TrainConnectivityAggregator",
    "TrainConnectivitySnapshot",
]
