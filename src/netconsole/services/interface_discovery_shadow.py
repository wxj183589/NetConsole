"""Read-only shadow execution for the interface discovery migration candidate.

This module deliberately accepts the capability as a callable.  The callable owns
device/profile/parser concerns; the runner only receives an already normalized
result, compares interface facts, and emits in-memory diagnostics.  It has no
repository, database, transport, or production collector dependency.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CAPABILITY_NAME = "interface.discovery"

SHADOW_SUCCESS = "SUCCESS"
SHADOW_EMPTY = "EMPTY"
SHADOW_FAILED = "FAILED"
SHADOW_TIMEOUT = "TIMEOUT"

COMPARE_MATCH = "MATCH"
COMPARE_DIFFERENT = "DIFFERENT"
COMPARE_SHADOW_FAILED = "SHADOW_FAILED"

_IGNORED_FIELDS = frozenset(
    {
        "raw",
        "raw_output",
        "raw_output_ref",
        "collected_at",
        "observed_at",
        "timestamp",
        "started_at",
        "ended_at",
        "duration_ms",
        "execution_duration_ms",
        "session_id",
        "collect_run_uuid",
        "task_id",
        "machine_path",
        "runtime_metadata",
    }
)
_SAFE_DEVICE_IDENTITY_FIELDS = frozenset(
    {
        "device_uuid",
        "device_id",
        "vendor",
        "role",
        "platform",
        "software_version",
        "profile_id",
        "profile_version",
        "system_name",
        "serial_number",
        "mac_address",
    }
)
_SENSITIVE_ERROR_VALUE = re.compile(
    r"(?i)(\b(?:password|passwd|secret|token|community|username)\b\s*[=:]\s*)"
    r"([^\s,;]+)"
)
_MISSING = object()

ShadowCapability = Callable[[], Mapping[str, Any]]
AuditSink = Callable[["InterfaceDiscoveryShadowAudit"], None]


@dataclass(frozen=True)
class InterfaceDiscoveryShadowAudit:
    """Safe, non-persistent audit fields for one shadow invocation."""

    execution_time: str
    execution_id: str
    device_identity: dict[str, Any]
    legacy_status: str
    shadow_status: str
    compare_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_time": self.execution_time,
            "execution_id": self.execution_id,
            "device_identity": dict(self.device_identity),
            "legacy_status": self.legacy_status,
            "shadow_status": self.shadow_status,
            "compare_status": self.compare_status,
        }


@dataclass(frozen=True)
class InterfaceDiscoveryShadowReport:
    """Machine-readable diagnostic result; Legacy remains authoritative."""

    execution_id: str
    device_identity: dict[str, Any]
    legacy_status: str
    shadow_status: str
    compare_status: str
    added: tuple[dict[str, Any], ...] = ()
    removed: tuple[dict[str, Any], ...] = ()
    changed: tuple[dict[str, Any], ...] = ()
    error: str | None = None
    audit: InterfaceDiscoveryShadowAudit | None = None

    @property
    def status(self) -> str:
        """Return the authoritative Legacy status, never the shadow outcome."""

        return self.legacy_status

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": CAPABILITY_NAME,
            "execution_id": self.execution_id,
            "device_identity": dict(self.device_identity),
            "status": self.status,
            "legacy_status": self.legacy_status,
            "shadow_status": self.shadow_status,
            "compare_status": self.compare_status,
            "authoritative_result": "LEGACY",
            "repository_write": "FORBIDDEN",
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
            "error": self.error,
        }
        if self.audit is not None:
            payload["audit"] = self.audit.to_dict()
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass
class ShadowAuditRecorder:
    """In-memory audit sink; it intentionally has no database/file writer."""

    records: list[InterfaceDiscoveryShadowAudit] = field(default_factory=list)

    def record(self, audit: InterfaceDiscoveryShadowAudit) -> None:
        self.records.append(audit)


class InterfaceDiscoveryShadowRunner:
    """Run a capability callback and compare only normalized interface facts."""

    def __init__(
        self,
        *,
        audit_sink: AuditSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit_sink = audit_sink
        self._clock = clock or _utc_now

    def run(
        self,
        *,
        execution_id: str,
        device_identity: Mapping[str, Any],
        legacy_status: str,
        legacy_result: Mapping[str, Any],
        shadow_capability: ShadowCapability,
    ) -> InterfaceDiscoveryShadowReport:
        safe_identity = _safe_device_identity(device_identity)
        shadow_result: Mapping[str, Any] | None = None
        shadow_status = SHADOW_SUCCESS
        error: str | None = None

        try:
            shadow_result = shadow_capability()
            _validate_shadow_result(shadow_result)
            if not shadow_result["interfaces"]:
                shadow_status = SHADOW_EMPTY
        except TimeoutError as exc:
            shadow_status = SHADOW_TIMEOUT
            error = _safe_error(exc)
        except Exception as exc:  # Shadow diagnostics cannot fail the Legacy task.
            shadow_status = SHADOW_FAILED
            error = _safe_error(exc)

        added: tuple[dict[str, Any], ...] = ()
        removed: tuple[dict[str, Any], ...] = ()
        changed: tuple[dict[str, Any], ...] = ()
        if shadow_result is None or shadow_status in {
            SHADOW_FAILED,
            SHADOW_TIMEOUT,
        }:
            compare_status = COMPARE_SHADOW_FAILED
        else:
            try:
                added, removed, changed = interface_discovery_differences(
                    legacy_result,
                    shadow_result,
                )
            except Exception as exc:  # Invalid shadow input remains diagnostic-only.
                shadow_status = SHADOW_FAILED
                compare_status = COMPARE_SHADOW_FAILED
                error = _safe_error(exc)
            else:
                compare_status = (
                    COMPARE_MATCH
                    if not added and not removed and not changed
                    else COMPARE_DIFFERENT
                )

        audit = InterfaceDiscoveryShadowAudit(
            execution_time=_format_execution_time(self._clock()),
            execution_id=str(execution_id),
            device_identity=safe_identity,
            legacy_status=_safe_status(legacy_status),
            shadow_status=shadow_status,
            compare_status=compare_status,
        )
        report = InterfaceDiscoveryShadowReport(
            execution_id=str(execution_id),
            device_identity=safe_identity,
            legacy_status=_safe_status(legacy_status),
            shadow_status=shadow_status,
            compare_status=compare_status,
            added=added,
            removed=removed,
            changed=changed,
            error=error,
            audit=audit,
        )
        if self._audit_sink is not None:
            self._audit_sink(audit)
        return report


def interface_discovery_normalized_projection(
    snapshot: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Project the existing normalized result to the interface section only."""

    rows = _normalized_interfaces(snapshot, "snapshot")
    return {"interfaces": [dict(row) for row in rows]}


def compare_interface_discovery_normalized(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    """Compare normalized interface facts while ignoring only runtime metadata."""

    return not any(interface_discovery_differences(left, right))


def interface_discovery_differences(
    legacy: Mapping[str, Any],
    shadow: Mapping[str, Any],
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    """Return added, removed, and changed interface records without mutating inputs."""

    legacy_rows = _normalized_interfaces(legacy, "legacy")
    shadow_rows = _normalized_interfaces(shadow, "shadow")
    legacy_by_identity = _index_interfaces(legacy_rows, "legacy")
    shadow_by_identity = _index_interfaces(shadow_rows, "shadow")

    added = tuple(
        {
            "identity": identity,
            "interface": dict(shadow_by_identity[identity]),
        }
        for identity in sorted(shadow_by_identity.keys() - legacy_by_identity.keys())
    )
    removed = tuple(
        {
            "identity": identity,
            "interface": dict(legacy_by_identity[identity]),
        }
        for identity in sorted(legacy_by_identity.keys() - shadow_by_identity.keys())
    )
    changed = tuple(
        {
            "identity": identity,
            "fields": _changed_fields(
                legacy_by_identity[identity],
                shadow_by_identity[identity],
            ),
        }
        for identity in sorted(legacy_by_identity.keys() & shadow_by_identity.keys())
        if _changed_fields(
            legacy_by_identity[identity],
            shadow_by_identity[identity],
        )
    )
    return added, removed, changed


def _validate_shadow_result(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping):
        raise TypeError("shadow normalized result must be a mapping")
    if "interfaces" not in value:
        raise ValueError("shadow normalized result missing interfaces")
    if not isinstance(value["interfaces"], list):
        raise TypeError("shadow normalized interfaces must be a list")


def _normalized_interfaces(
    snapshot: Mapping[str, Any],
    label: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(snapshot, Mapping):
        raise TypeError(f"{label} normalized result must be a mapping")
    interfaces = snapshot.get("interfaces")
    if not isinstance(interfaces, list):
        raise TypeError(f"{label} normalized interfaces must be a list")
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(interfaces):
        if not isinstance(value, Mapping):
            raise TypeError(f"{label} interface row {index} must be a mapping")
        rows.append(_without_ignored_fields(value))
    return tuple(rows)


def _index_interfaces(
    rows: tuple[dict[str, Any], ...],
    label: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        identity = _interface_identity(row, index)
        if identity in indexed:
            raise ValueError(f"{label} duplicate interface identity: {identity}")
        indexed[identity] = row
    return indexed


def _interface_identity(row: Mapping[str, Any], index: int) -> str:
    for field_name in ("normalized_name", "interface_name"):
        value = row.get(field_name, _MISSING)
        if value is not _MISSING and value not in (None, ""):
            return f"{field_name}={value}"
    return f"index={index}"


def _changed_fields(
    legacy: Mapping[str, Any],
    shadow: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for field_name in sorted(set(legacy) | set(shadow)):
        legacy_value = legacy.get(field_name, _MISSING)
        shadow_value = shadow.get(field_name, _MISSING)
        if legacy_value == shadow_value:
            continue
        fields[field_name] = {
            "legacy": _value_descriptor(legacy_value),
            "shadow": _value_descriptor(shadow_value),
        }
    return fields


def _value_descriptor(value: Any) -> dict[str, Any]:
    if value is _MISSING:
        return {"missing": True}
    return {"missing": False, "value": value}


def _without_ignored_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _without_ignored_value(child)
        for key, child in value.items()
        if key not in _IGNORED_FIELDS
    }


def _without_ignored_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _without_ignored_fields(value)
    if isinstance(value, list):
        return [_without_ignored_value(child) for child in value]
    return value


def _safe_device_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("device_identity must be a mapping")
    return {
        str(key): item
        for key, item in value.items()
        if str(key) in _SAFE_DEVICE_IDENTITY_FIELDS
    }


def _safe_error(exc: BaseException) -> str:
    message = f"{type(exc).__name__}: {exc}"
    redacted = _SENSITIVE_ERROR_VALUE.sub("[REDACTED]", message)
    return redacted[:500]


def _safe_status(value: str) -> str:
    return str(value).strip().upper() or "UNKNOWN"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_execution_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
