"""Canonical Ground Ping classification and statistics.

The Renderer receives these derived values as part of the API contract.  Keep
this module free of persistence and framework concerns so raw and Quick Ping
queries use exactly the same rules.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping

PING_STATUSES = ("SUCCESS", "TIMEOUT", "PACKET_LOSS", "UNKNOWN")
STATUS_ALIASES = {
    "SUCCESS": "SUCCESS",
    "OK": "SUCCESS",
    "CONNECTED": "SUCCESS",
    "TIMEOUT": "TIMEOUT",
    "TIMED_OUT": "TIMEOUT",
    "PACKET_LOSS": "PACKET_LOSS",
    "LOSS": "PACKET_LOSS",
    "LOST": "PACKET_LOSS",
    "UNKNOWN": "UNKNOWN",
}


def _js_truthy(value: object) -> bool:
    return value is not None and value is not False and value != "" and value != 0


def _numeric(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def normalize_status(value: object) -> str | None:
    key = re.sub(r"[ -]+", "_", str(value if value is not None else "").strip().upper())
    return STATUS_ALIASES.get(key)


def _explicit_status(sample: Mapping[str, Any]) -> str | None:
    # Match the legacy `status ?? state ?? result ?? outcome` contract: once
    # the first non-null field is selected, an unknown value must not fall
    # through to a later alias.
    value: object = None
    for key in ("status", "state", "result", "outcome"):
        if key in sample and sample[key] is not None:
            value = sample[key]
            break
    return normalize_status(value)


def classify_status(sample: Mapping[str, Any]) -> str:
    explicit = _explicit_status(sample)
    if explicit:
        return explicit
    if not isinstance(sample.get("ok"), bool):
        return "UNKNOWN"
    if sample.get("timeout") is True or sample.get("timed_out") is True:
        return "TIMEOUT"
    if not sample["ok"]:
        reason = str(
            sample.get("error_code")
            or sample.get("failure_code")
            or sample.get("reason")
            or sample.get("error")
            or ""
        ).upper()
        return "TIMEOUT" if "TIMEOUT" in reason or "TIMED_OUT" in reason else "PACKET_LOSS"
    loss = _numeric(
        sample.get("loss_percent")
        if sample.get("loss_percent") is not None
        else sample.get("loss_rate_percent")
        if sample.get("loss_rate_percent") is not None
        else sample.get("packet_loss_percent")
    )
    if loss is not None and loss > 0:
        return "PACKET_LOSS"
    if _numeric(sample.get("rtt_ms")) is None:
        return "UNKNOWN"
    return "SUCCESS"


def classify_heartbeat_status(sample: Mapping[str, Any]) -> str:
    """Heartbeat keeps persisted reachability semantics independent of RTT."""
    explicit = _explicit_status(sample)
    if explicit:
        return explicit
    if not isinstance(sample.get("ok"), bool):
        return "UNKNOWN"
    if sample["ok"]:
        return "SUCCESS"
    return "TIMEOUT" if sample.get("timeout") is True or sample.get("timed_out") is True else "PACKET_LOSS"


def point_values(sample: Mapping[str, Any]) -> dict[str, Any]:
    status = classify_status(sample)
    raw_loss = _numeric(
        sample.get("loss_percent")
        if sample.get("loss_percent") is not None
        else sample.get("loss_rate_percent")
        if sample.get("loss_rate_percent") is not None
        else sample.get("packet_loss_percent")
    )
    loss = (
        0.0
        if raw_loss is None and status == "SUCCESS"
        else 100.0
        if raw_loss is None and status in {"TIMEOUT", "PACKET_LOSS"}
        else None
        if raw_loss is None
        else max(0.0, min(100.0, raw_loss))
    )
    rtt = None if status in {"TIMEOUT", "UNKNOWN"} else _numeric(sample.get("rtt_ms"))
    return {
        "normalized_status": _explicit_status(sample),
        "error_reason": str(
            sample.get("error_reason")
            or sample.get("error_code")
            or sample.get("failure_code")
            or sample.get("reason")
            or sample.get("error")
            or ""
        ),
        "status": status,
        "heartbeat_status": classify_heartbeat_status(sample),
        "loss_percent": loss,
        "rtt_display_ms": rtt,
    }


def _timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sample_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = row.get("sample")
    return nested if isinstance(nested, Mapping) else row


def _sample_time(row: Mapping[str, Any]) -> datetime | None:
    sample = _sample_of(row)
    for key in ("received_at", "ts"):
        parsed = _timestamp(row.get(key))
        if parsed:
            return parsed
        parsed = _timestamp(sample.get(key))
        if parsed:
            return parsed
    return None


def _sample_key(row: Mapping[str, Any], stamp: datetime) -> str:
    sample = _sample_of(row)
    identity = row.get("sample_id") or sample.get("sample_id")
    if _js_truthy(identity):
        return f"id:{identity}"
    return "|".join(
        str(value or "")
        for value in (
            row.get("quick_run_id") or sample.get("quick_ping_run_id"),
            row.get("target_ip") or sample.get("target_ip"),
            sample.get("seq") if sample.get("seq") is not None else row.get("seq"),
            stamp.timestamp() * 1000,
        )
    )


def natural_second_loss_buckets(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    seen: set[str] = set()
    for row in rows:
        stamp = _sample_time(row)
        if stamp is None:
            continue
        key = _sample_key(row, stamp)
        if key in seen:
            continue
        seen.add(key)
        start_ms = math.floor(stamp.timestamp() * 1000 / 1000) * 1000
        bucket = buckets.setdefault(
            start_ms,
            {
                "start": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "end": datetime.fromtimestamp((start_ms + 1000) / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "ping_total": 0,
                "ping_success": 0,
                "ping_lost": 0,
                "ping_unknown": 0,
                "packet_loss_rate": None,
            },
        )
        status = point_values(_sample_of(row))["status"]
        bucket["ping_total"] += 1
        bucket["ping_success"] += int(status == "SUCCESS")
        bucket["ping_lost"] += int(status in {"TIMEOUT", "PACKET_LOSS"})
        bucket["ping_unknown"] += int(status == "UNKNOWN")
        bucket["packet_loss_rate"] = bucket["ping_lost"] / bucket["ping_total"] * 100
    return [buckets[key] for key in sorted(buckets)]


def selected_statistics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    total = success = lost = unknown = 0
    rtts: list[float] = []
    for row in rows:
        stamp = _sample_time(row)
        if stamp is None:
            continue
        key = _sample_key(row, stamp)
        if key in seen:
            continue
        seen.add(key)
        values = point_values(_sample_of(row))
        total += 1
        success += int(values["status"] == "SUCCESS")
        lost += int(values["status"] in {"TIMEOUT", "PACKET_LOSS"})
        unknown += int(values["status"] == "UNKNOWN")
        if values["status"] == "SUCCESS" and values["rtt_display_ms"] is not None:
            rtts.append(float(values["rtt_display_ms"]))
    return {
        "ping_total": total,
        "ping_success": success,
        "ping_lost": lost,
        "ping_unknown": unknown,
        "packet_loss_rate": lost / total * 100 if total else None,
        "min_rtt_ms": min(rtts) if rtts else None,
        "average_rtt_ms": sum(rtts) / len(rtts) if rtts else None,
        "max_rtt_ms": max(rtts) if rtts else None,
    }


def project_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    projected = dict(row)
    projected.update(point_values(projected))
    return projected


def project_quick_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    projected = dict(row)
    nested = row.get("sample")
    if isinstance(nested, Mapping):
        projected["sample"] = {**nested, **point_values(nested)}
        projected.update({key: value for key, value in point_values(nested).items() if key != "heartbeat_status"})
    else:
        projected.update(point_values(projected))
    return projected
