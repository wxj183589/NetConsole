from __future__ import annotations

import json
import os
import sys
from typing import Any, TextIO

_FALLBACK_STDOUT: TextIO | None = None


def encode_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_event(event: dict[str, Any], stream: TextIO | None = None) -> None:
    target = stream or getattr(sys, "__stdout__", None) or sys.stdout or _fallback_stdout()
    target.write(encode_event(event))
    target.flush()


def _fallback_stdout() -> TextIO:
    global _FALLBACK_STDOUT
    if _FALLBACK_STDOUT is None:
        _FALLBACK_STDOUT = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    return _FALLBACK_STDOUT


def parse_event_line(line: str) -> dict[str, Any] | None:
    text = str(line or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    event = dict(value)
    event_type = str(event.get("type") or event.get("event") or "")
    if event_type == "started":
        event_type = "progress"
        event.setdefault("current", 0)
        event.setdefault("total", 0)
    elif event_type == "success":
        event_type = "finished"
        event.setdefault("ok", True)
    elif event_type == "failed":
        event_type = "error"
        event.setdefault("ok", False)
    elif event_type == "result":
        event_type = "finished" if bool(event.get("ok")) else "error"
    if event_type == "cancelled":
        event["cancelled"] = True
        event.setdefault("ok", False)
    event["type"] = event_type
    event.setdefault("job_id", "")
    event.setdefault("stage", "")
    event.setdefault("current", int(event.get("done") or 0))
    event.setdefault("total", 0)
    event.setdefault("message", event.get("error_message") or event.get("error") or "")
    event.setdefault("result", None)
    event.setdefault("error", event.get("error_message") or "")
    event.setdefault("traceback", "")
    event.setdefault("cancelled", False)
    return event


def feed_jsonl(buffer: str, chunk: bytes | str) -> tuple[list[dict[str, Any]], list[str], str]:
    text = chunk.decode("utf-8", errors="strict") if isinstance(chunk, bytes) else str(chunk)
    combined = buffer + text
    lines = combined.split("\n")
    remainder = lines.pop()
    events: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip("\r").strip()
        if not line:
            continue
        event = parse_event_line(line)
        if event is None:
            diagnostics.append(line)
        else:
            events.append(event)
    return events, diagnostics, remainder
