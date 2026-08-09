from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileLogPolicy:
    max_file_bytes: int
    retention_days: int


@dataclass(frozen=True)
class ElectronLogPolicy(FileLogPolicy):
    queue_soft_limit_bytes: int
    queue_hard_limit_bytes: int
    flush_timeout_ms: int
    fallback_max_bytes: int
    rotation_retry_seconds: tuple[int, ...]


@dataclass(frozen=True)
class ApplicationLogPolicy:
    max_event_bytes: int
    max_context_bytes: int
    max_traceback_bytes: int
    production_level: str
    development_level: str


@dataclass(frozen=True)
class RetentionPolicy:
    retention_days: int


@dataclass(frozen=True)
class DuplicateSuppressionPolicy:
    window_seconds: int
    summary_interval_seconds: int


@dataclass(frozen=True)
class HousekeeperPolicy:
    max_total_bytes: int
    target_total_bytes: int
    interval_seconds: int


@dataclass(frozen=True)
class RuntimeCleanupPolicy:
    cache_retention_days: int
    temporary_retention_days: int


@dataclass(frozen=True)
class LogPolicy:
    application_log: ApplicationLogPolicy
    electron: ElectronLogPolicy
    backend: FileLogPolicy
    wps: FileLogPolicy
    startup_error: RetentionPolicy
    faulthandler: RetentionPolicy
    duplicate_suppression: DuplicateSuppressionPolicy
    housekeeper: HousekeeperPolicy
    runtime_cleanup: RuntimeCleanupPolicy
    raw_collection_truncate: bool


@lru_cache(maxsize=1)
def load_log_policy() -> LogPolicy:
    path = Path(__file__).resolve().parents[1] / "resources" / "log_policy.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported log policy schema")
    application = _mapping(payload, "application_log")
    electron = _mapping(payload, "electron")
    backend = _mapping(payload, "backend")
    wps = _mapping(payload, "wps")
    startup_error = _mapping(payload, "startup_error")
    faulthandler = _mapping(payload, "faulthandler")
    duplicate = _mapping(payload, "duplicate_suppression")
    housekeeper = _mapping(payload, "housekeeper")
    runtime_cleanup = _mapping(payload, "runtime_cleanup")
    raw_collection = _mapping(payload, "raw_collection")
    policy = LogPolicy(
        application_log=ApplicationLogPolicy(
            max_event_bytes=_positive_int(application, "max_event_bytes"),
            max_context_bytes=_positive_int(application, "max_context_bytes"),
            max_traceback_bytes=_positive_int(application, "max_traceback_bytes"),
            production_level=str(application["production_level"]).upper(),
            development_level=str(application["development_level"]).upper(),
        ),
        electron=ElectronLogPolicy(
            max_file_bytes=_positive_int(electron, "max_file_bytes"),
            retention_days=_positive_int(electron, "retention_days"),
            queue_soft_limit_bytes=_positive_int(
                electron, "queue_soft_limit_bytes"
            ),
            queue_hard_limit_bytes=_positive_int(
                electron, "queue_hard_limit_bytes"
            ),
            flush_timeout_ms=_positive_int(electron, "flush_timeout_ms"),
            fallback_max_bytes=_positive_int(electron, "fallback_max_bytes"),
            rotation_retry_seconds=tuple(
                _positive_int_value(value, "rotation_retry_seconds")
                for value in electron.get("rotation_retry_seconds", ())
            ),
        ),
        backend=FileLogPolicy(
            max_file_bytes=_positive_int(backend, "max_file_bytes"),
            retention_days=_positive_int(backend, "retention_days"),
        ),
        wps=FileLogPolicy(
            max_file_bytes=_positive_int(wps, "max_file_bytes"),
            retention_days=_positive_int(wps, "retention_days"),
        ),
        startup_error=RetentionPolicy(_positive_int(startup_error, "retention_days")),
        faulthandler=RetentionPolicy(_positive_int(faulthandler, "retention_days")),
        duplicate_suppression=DuplicateSuppressionPolicy(
            window_seconds=_positive_int(duplicate, "window_seconds"),
            summary_interval_seconds=_positive_int(duplicate, "summary_interval_seconds"),
        ),
        housekeeper=HousekeeperPolicy(
            max_total_bytes=_positive_int(housekeeper, "max_total_bytes"),
            target_total_bytes=_positive_int(housekeeper, "target_total_bytes"),
            interval_seconds=_positive_int(housekeeper, "interval_seconds"),
        ),
        runtime_cleanup=RuntimeCleanupPolicy(
            cache_retention_days=_positive_int(
                runtime_cleanup, "cache_retention_days"
            ),
            temporary_retention_days=_positive_int(
                runtime_cleanup, "temporary_retention_days"
            ),
        ),
        raw_collection_truncate=bool(raw_collection.get("truncate", True)),
    )
    if policy.housekeeper.target_total_bytes >= policy.housekeeper.max_total_bytes:
        raise ValueError("log housekeeper target must be below its maximum")
    if policy.electron.queue_soft_limit_bytes >= policy.electron.queue_hard_limit_bytes:
        raise ValueError("electron log queue soft limit must be below its hard limit")
    if not policy.electron.rotation_retry_seconds:
        raise ValueError("electron log rotation retry policy must not be empty")
    if not (
        policy.application_log.max_event_bytes
        <= policy.application_log.max_context_bytes
        <= policy.application_log.max_traceback_bytes
    ):
        raise ValueError("application log limits must be ordered")
    if policy.raw_collection_truncate:
        raise ValueError("raw collection data must never use application log truncation")
    return policy


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"invalid log policy section: {key}")
    return value


def _positive_int(payload: dict[str, Any], key: str) -> int:
    value = int(payload.get(key, 0))
    if value <= 0:
        raise ValueError(f"invalid log policy value: {key}")
    return value


def _positive_int_value(value: Any, key: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid log policy value: {key}") from exc
    if result <= 0:
        raise ValueError(f"invalid log policy value: {key}")
    return result


LOG_POLICY = load_log_policy()
