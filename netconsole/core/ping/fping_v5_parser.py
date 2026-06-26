from __future__ import annotations

import json
from typing import Any

from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample


KNOWN_META_TYPES = {"summary", "stats", "intSum", "vSum"}


def parse_fping_v5_json_line(raw_line: str, received_ts: str, timeout_ms: int) -> FpingV5Sample | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return FpingV5Sample(received_ts, "", None, None, None, timeout_ms, None, "", BACKEND, "unknown", {"value": payload})

    if isinstance(payload.get("resp"), dict):
        resp = payload["resp"]
        return FpingV5Sample(
            ts=received_ts,
            target=str(resp.get("host") or ""),
            seq=_int_or_none(resp.get("seq")),
            ok=True,
            rtt_ms=_float_or_none(resp.get("rtt")),
            timeout_ms=timeout_ms,
            size=_int_or_none(resp.get("size")),
            error="",
            backend=BACKEND,
            raw_type="resp",
            raw=payload,
        )
    if isinstance(payload.get("timeout"), dict):
        timeout = payload["timeout"]
        return FpingV5Sample(
            ts=received_ts,
            target=str(timeout.get("host") or ""),
            seq=_int_or_none(timeout.get("seq")),
            ok=False,
            rtt_ms=None,
            timeout_ms=timeout_ms,
            size=None,
            error="timeout",
            backend=BACKEND,
            raw_type="timeout",
            raw=payload,
        )
    for raw_type in KNOWN_META_TYPES:
        if raw_type in payload:
            body = payload.get(raw_type)
            target = ""
            if isinstance(body, dict):
                target = str(body.get("host") or body.get("target") or "")
            return FpingV5Sample(received_ts, target, None, None, None, timeout_ms, None, "", BACKEND, raw_type, payload)
    return FpingV5Sample(received_ts, "", None, None, None, timeout_ms, None, "", BACKEND, "unknown", payload)


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None

