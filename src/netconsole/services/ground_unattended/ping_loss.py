from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4


def enqueue_loss_event(pending: Any, event: dict[str, Any], *, capacity: int = 4096) -> None:
    """Coalesce cumulative updates while retaining episode boundaries."""
    if event.get("action") == "UPDATE":
        for index in range(len(pending) - 1, -1, -1):
            previous = pending[index]
            if previous.get("event_key") != event.get("event_key"):
                continue
            if previous.get("action") in {"OPEN", "UPDATE"}:
                pending[index] = {**event, "action": previous["action"]}
                return
            break
    if len(pending) >= capacity:
        raise RuntimeError("PING_LOSS_EVENT_BACKLOG_FULL")
    pending.append(event)


def acknowledge_loss_events(pending: Any, batch: list[dict[str, Any]]) -> None:
    # A producer may replace a cumulative update while the batch is being saved.
    # Retain that newer command so it is not lost when acknowledging the old one.
    committed = {id(event) for event in batch}
    remaining = [event for event in pending if id(event) not in committed]
    pending.clear()
    pending.extend(remaining)


@dataclass
class PingLossTracker:
    """Track one target's loss episode without coupling it to a sampler."""

    event_key: str
    state: dict[str, Any] | None = None
    last_success: dict[str, str] | None = None

    def enqueue_observation(
        self, pending: Any, *, success: bool, at: datetime,
        metadata: Mapping[str, Any] | None = None,
        fields: Mapping[str, Any] | None = None, capacity: int = 4096,
    ) -> None:
        previous = dict(self.state) if self.state is not None else None
        last_success = self.last_success
        event = self.observe(success=success, at=at, metadata=metadata)
        if event is None:
            return
        event.update(fields or {})
        try:
            enqueue_loss_event(pending, event, capacity=capacity)
        except RuntimeError:
            # A rejected recovery must leave its episode open for a retry.
            self.state, self.last_success = previous, last_success
            raise

    def observe(
        self,
        *,
        success: bool,
        at: datetime,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        context = {
            "ap_name": str((metadata or {}).get("ap_name") or ""),
            "station": str((metadata or {}).get("station") or ""),
            "section": str((metadata or {}).get("section") or ""),
        }
        timestamp = at.isoformat(timespec="milliseconds")
        if success:
            self.last_success = context
            if self.state is None:
                return None
            event = dict(self.state)
            event.update(
                action="RECOVER",
                ended_at=timestamp,
                recovered_at=timestamp,
                duration_seconds=max(
                    0.0,
                    (at - self.state["_started_at"]).total_seconds(),
                ),
                last_success_ap_name=context["ap_name"],
                last_success_station=context["station"],
                last_success_section=context["section"],
                sent_count=int(self.state.get("sent_count") or 0) + 1,
                success_count=int(self.state.get("success_count") or 0) + 1,
            )
            event.pop("_started_at", None)
            self.state = None
            return event

        opened = self.state is None
        if opened:
            self.state = {
                # A target can have many independent outages. The episode key
                # stays stable across retries and recovery, never across episodes.
                "event_key": f"{self.event_key}:{uuid4().hex}",
                "action": "OPEN",
                "started_at": timestamp,
                "ended_at": "",
                "recovered_at": "",
                "duration_seconds": 0.0,
                "loss_count": 1,
                "sent_count": 1,
                "success_count": 0,
                "last_success_ap_name": (self.last_success or {}).get("ap_name", ""),
                "last_success_station": (self.last_success or {}).get("station", ""),
                "last_success_section": (self.last_success or {}).get("section", ""),
                "ap_name": context["ap_name"],
                "station": context["station"],
                "section": context["section"],
                "_started_at": at,
            }
        else:
            self.state["loss_count"] = int(self.state.get("loss_count") or 0) + 1
            self.state["sent_count"] = int(self.state.get("sent_count") or 0) + 1
            self.state["duration_seconds"] = max(
                0.0, (at - self.state["_started_at"]).total_seconds()
            )
        event = dict(self.state)
        event.update(action="OPEN" if opened else "UPDATE", observed_at=timestamp)
        event.pop("_started_at", None)
        return event

    def restore(self, row: Mapping[str, Any]) -> None:
        started = str(row.get("started_at") or "")
        if not started:
            return
        try:
            parsed = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError:
            return
        self.state = dict(row)
        self.state["_started_at"] = parsed
