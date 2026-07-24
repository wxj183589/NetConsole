from __future__ import annotations

import json
import os
import sys
from typing import Any, BinaryIO, TextIO

_FALLBACK_STDOUT: BinaryIO | None = None
WORKER_EVENT_TYPES = frozenset({"progress", "log", "finished", "error", "cancelled"})


def encode_event(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"


def encode_event_bytes(event: dict[str, Any]) -> bytes:
    return encode_event(event).encode("ascii", errors="strict")


def write_event(event: dict[str, Any], stream: BinaryIO | TextIO | None = None) -> None:
    payload = encode_event_bytes(event)
    if stream is None:
        target = _stdout_binary_stream()
        target.write(payload)
        target.flush()
        return
    binary_target = getattr(stream, "buffer", None)
    if binary_target is not None:
        binary_target.write(payload)
        binary_target.flush()
        return
    try:
        stream.write(payload)  # type: ignore[arg-type]
    except TypeError:
        stream.write(payload.decode("ascii"))  # type: ignore[arg-type]
    stream.flush()


def configure_standard_streams() -> None:
    _reconfigure_stream(sys.stdin, encoding="utf-8", errors="strict")
    _reconfigure_stream(sys.stdout, encoding="utf-8", errors="strict", newline="\n", write_through=True)
    _reconfigure_stream(
        sys.stderr,
        encoding="utf-8",
        errors="backslashreplace",
        newline="\n",
        write_through=True,
    )


def _reconfigure_stream(stream: object, **options: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(**options)
    except (OSError, TypeError, ValueError):
        return


def _stdout_binary_stream() -> BinaryIO:
    for stream in (getattr(sys, "__stdout__", None), sys.stdout):
        target = getattr(stream, "buffer", None)
        if target is not None:
            return target
    return _fallback_stdout()


def _fallback_stdout() -> BinaryIO:
    global _FALLBACK_STDOUT
    if _FALLBACK_STDOUT is None:
        _FALLBACK_STDOUT = os.fdopen(os.dup(1), "wb", buffering=0)
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


def parse_worker_event_line(line: str) -> tuple[dict[str, Any] | None, str]:
    """Parse one Worker frame and return a stable fatal reason on failure."""

    text = str(line or "").strip()
    if not text:
        return None, "worker_protocol_schema_invalid"
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None, "worker_protocol_json_invalid"
    if not isinstance(value, dict):
        return None, "worker_protocol_schema_invalid"
    try:
        event = parse_event_line(text)
    except (TypeError, ValueError):
        return None, "worker_protocol_schema_invalid"
    if event is None:
        return None, "worker_protocol_schema_invalid"
    event_type = str(event.get("type") or "")
    if event_type not in WORKER_EVENT_TYPES:
        return None, "worker_protocol_unexpected_message"
    if not str(event.get("job_id") or "").strip():
        return None, "worker_protocol_schema_invalid"
    for key in ("stage", "message", "error", "traceback"):
        if not isinstance(event.get(key), str):
            return None, "worker_protocol_schema_invalid"
    for key in ("current", "total"):
        value = event.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "worker_protocol_schema_invalid"
    if not isinstance(event.get("cancelled"), bool):
        return None, "worker_protocol_schema_invalid"
    result = event.get("result")
    if result is not None and not isinstance(result, dict):
        return None, "worker_protocol_schema_invalid"
    return event, ""


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
