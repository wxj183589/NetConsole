from __future__ import annotations

import json
import os
import re
import threading
import uuid
import weakref
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from netconsole.core.paths import PathResolver
from netconsole.models.traffic_test import TrafficEvent
from netconsole.repositories.traffic_run_repository import TrafficRunRepository


_STATE_GUARD = threading.Lock()
_PATH_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = weakref.WeakValueDictionary()
_PATH_WATERMARKS: OrderedDict[Path, tuple[int, int]] = OrderedDict()
_MAX_WATERMARKS = 4_096
_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)"
)


class TrafficEventStore:
    def __init__(
        self,
        paths: PathResolver,
        repository: TrafficRunRepository,
        site_name: str = "demo",
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.site_name = str(site_name or "demo")
        self._offset_guard = threading.Lock()
        self._offsets: OrderedDict[str, OrderedDict[int, int]] = OrderedDict()

    def append(self, event: TrafficEvent) -> TrafficEvent | None:
        accepted = self.append_many([event])
        return accepted[0] if accepted else None

    def append_many(self, events: Iterable[TrafficEvent]) -> list[TrafficEvent]:
        pending = [replace(event, payload=_sanitize_payload(event.payload)) for event in events]
        if not pending:
            return []
        traffic_run_id = pending[0].traffic_run_id
        if not traffic_run_id or any(event.traffic_run_id != traffic_run_id for event in pending):
            raise ValueError("traffic event batch must contain one non-empty traffic_run_id")
        lock = self._lock_for(traffic_run_id)
        with lock:
            controller_sequence, remote_sequence = self._watermark(traffic_run_id)
            accepted: list[TrafficEvent] = []
            for event in pending:
                if event.remote_sequence is not None:
                    candidate = int(event.remote_sequence)
                    if candidate <= 0:
                        raise ValueError("remote_sequence must be positive")
                    if candidate <= remote_sequence:
                        continue
                    remote_sequence = candidate
                controller_sequence += 1
                accepted.append(replace(event, sequence=controller_sequence))
            if not accepted:
                return []

            path = self.paths.traffic_run_events_path(self.site_name, traffic_run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            separator = "\n" if _needs_line_separator(path) else ""
            text = separator + "".join(
                json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
                for event in accepted
            )
            with path.open("a", encoding="utf-8", newline="") as file:
                file.write(text)
                file.flush()
            _set_watermark(path.resolve(), (controller_sequence, remote_sequence))
            self.repository.update_last_event_sequence(
                traffic_run_id,
                controller_sequence,
                accepted[-1].timestamp,
            )
            return accepted

    def list_events(
        self,
        traffic_run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[TrafficEvent]:
        if int(after_sequence) < 0:
            raise ValueError("after_sequence must be non-negative")
        max_events = max(1, min(int(limit), 2_000))
        path = self.paths.traffic_run_events_path(self.site_name, traffic_run_id)
        if not path.exists():
            return []
        events: list[TrafficEvent] = []
        start_offset = self._start_offset(traffic_run_id, int(after_sequence), path.stat().st_size)
        with path.open("rb") as file:
            file.seek(start_offset)
            while True:
                line = file.readline()
                if not line:
                    break
                next_offset = file.tell()
                try:
                    raw = json.loads(line.decode("utf-8", errors="replace"))
                    event = TrafficEvent.from_dict(raw) if isinstance(raw, dict) else None
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if event is None or event.traffic_run_id != traffic_run_id:
                    continue
                self._remember_offset(traffic_run_id, event.sequence, next_offset)
                if event.sequence <= int(after_sequence):
                    continue
                events.append(event)
                if len(events) >= max_events:
                    break
        return events

    def write_summary(self, traffic_run_id: str, value: dict[str, Any]) -> Path:
        value = _sanitize_payload(value)
        path = self.paths.traffic_run_summary_path(self.site_name, traffic_run_id)
        _write_json_atomic(path, value)
        return path

    def read_summary(self, traffic_run_id: str) -> dict[str, Any]:
        return _read_json_object(self.paths.traffic_run_summary_path(self.site_name, traffic_run_id))

    def write_remote_result(self, traffic_run_id: str, value: dict[str, Any]) -> Path:
        value = _sanitize_payload(value)
        path = self.paths.traffic_run_remote_result_path(self.site_name, traffic_run_id)
        _write_json_atomic(path, value)
        return path

    def read_remote_result(self, traffic_run_id: str) -> dict[str, Any]:
        return _read_json_object(self.paths.traffic_run_remote_result_path(self.site_name, traffic_run_id))

    def _lock_for(self, traffic_run_id: str) -> threading.RLock:
        path = self.paths.traffic_run_events_path(self.site_name, traffic_run_id).resolve()
        with _STATE_GUARD:
            lock = _PATH_LOCKS.get(path)
            if lock is None:
                lock = threading.RLock()
                _PATH_LOCKS[path] = lock
            return lock

    def _watermark(self, traffic_run_id: str) -> tuple[int, int]:
        path = self.paths.traffic_run_events_path(self.site_name, traffic_run_id).resolve()
        cached = _get_watermark(path)
        if cached is not None:
            return cached
        controller_sequence = 0
        remote_sequence = 0
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace") as file:
                for line in file:
                    try:
                        raw = json.loads(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if not isinstance(raw, dict) or str(raw.get("traffic_run_id") or "") != traffic_run_id:
                        continue
                    controller_sequence = max(controller_sequence, int(raw.get("sequence") or 0))
                    value = raw.get("remote_sequence")
                    if value is not None:
                        remote_sequence = max(remote_sequence, int(value))
        run = self.repository.get(traffic_run_id)
        if run is not None:
            controller_sequence = max(controller_sequence, run.last_event_sequence)
        result = (controller_sequence, remote_sequence)
        _set_watermark(path, result)
        return result

    def _start_offset(self, traffic_run_id: str, after_sequence: int, file_size: int) -> int:
        with self._offset_guard:
            offsets = self._offset_bucket(traffic_run_id)
            candidates = [(sequence, offset) for sequence, offset in offsets.items() if sequence <= after_sequence and offset <= file_size]
        return max(candidates, default=(0, 0), key=lambda item: item[0])[1]

    def _remember_offset(self, traffic_run_id: str, sequence: int, offset: int) -> None:
        with self._offset_guard:
            offsets = self._offset_bucket(traffic_run_id)
            offsets[int(sequence)] = int(offset)
            offsets.move_to_end(int(sequence))
            while len(offsets) > 4_096:
                offsets.popitem(last=False)

    def _offset_bucket(self, traffic_run_id: str) -> OrderedDict[int, int]:
        offsets = self._offsets.get(traffic_run_id)
        if offsets is None:
            offsets = OrderedDict()
            self._offsets[traffic_run_id] = offsets
        self._offsets.move_to_end(traffic_run_id)
        while len(self._offsets) > 256:
            self._offsets.popitem(last=False)
        return offsets


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _needs_line_separator(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    with path.open("rb") as file:
        file.seek(-1, os.SEEK_END)
        return file.read(1) not in {b"\n", b"\r"}


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("_", "-")
            if any(part in normalized for part in ("authorization", "credential", "password", "secret", "token")):
                raise ValueError(f"sensitive field is not allowed in traffic event storage: {key}")
            result[str(key)] = _sanitize_payload(item)
        return result
    elif isinstance(value, (list, tuple)):
        return [_sanitize_payload(item) for item in value]
    elif isinstance(value, os.PathLike):
        path = Path(value)
        return "<redacted-path>" if path.is_absolute() else str(path)
    elif isinstance(value, str):
        return _ABSOLUTE_PATH_RE.sub("<redacted-path>", value)
    return value


def _get_watermark(path: Path) -> tuple[int, int] | None:
    with _STATE_GUARD:
        value = _PATH_WATERMARKS.get(path)
        if value is not None:
            _PATH_WATERMARKS.move_to_end(path)
        return value


def _set_watermark(path: Path, value: tuple[int, int]) -> None:
    with _STATE_GUARD:
        _PATH_WATERMARKS[path] = value
        _PATH_WATERMARKS.move_to_end(path)
        while len(_PATH_WATERMARKS) > _MAX_WATERMARKS:
            _PATH_WATERMARKS.popitem(last=False)
