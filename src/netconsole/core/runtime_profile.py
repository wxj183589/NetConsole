"""Bounded host environment collection and low-performance capability policy.

The profile is deliberately advisory.  It never changes SQLite durability or
infers disk media/RAID level from a drive letter, size, or disk count.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


HOST_PROFILE_SCHEMA_VERSION = 1
HOST_PROFILE_COLLECTOR_VERSION = "1"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 4.0
MAX_COMMAND_TIMEOUT_SECONDS = 15.0
_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProfileValue:
    value: Any = _UNKNOWN
    source: str = "unavailable"
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source, "confidence": self.confidence}

    @classmethod
    def from_dict(cls, payload: Any) -> "ProfileValue":
        if not isinstance(payload, Mapping):
            return cls()
        confidence = str(payload.get("confidence", "low"))
        if confidence not in {"high", "medium", "low", "unknown"}:
            confidence = "unknown"
        return cls(payload.get("value", _UNKNOWN), str(payload.get("source", "unavailable")), confidence)


@dataclass(frozen=True)
class HostEnvironmentProfile:
    schema_version: int = HOST_PROFILE_SCHEMA_VERSION
    collected_at: float = field(default_factory=time.time)
    os: Mapping[str, ProfileValue] = field(default_factory=dict)
    cpu: Mapping[str, ProfileValue] = field(default_factory=dict)
    memory: Mapping[str, ProfileValue] = field(default_factory=dict)
    storage: Mapping[str, ProfileValue] = field(default_factory=dict)
    virtualization: Mapping[str, ProfileValue] = field(default_factory=dict)
    collector_version: str = HOST_PROFILE_COLLECTOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        def encode(items: Mapping[str, ProfileValue]) -> dict[str, Any]:
            return {key: (value.to_dict() if isinstance(value, ProfileValue) else ProfileValue.from_dict(value).to_dict()) for key, value in items.items()}

        return {
            "schema_version": self.schema_version,
            "collected_at": self.collected_at,
            "collector_version": self.collector_version,
            "os": encode(self.os),
            "cpu": encode(self.cpu),
            "memory": encode(self.memory),
            "storage": encode(self.storage),
            "virtualization": encode(self.virtualization),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "HostEnvironmentProfile":
        if not isinstance(payload, Mapping) or payload.get("schema_version") != HOST_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported host environment profile schema")

        def decode(name: str) -> dict[str, ProfileValue]:
            raw = payload.get(name, {})
            return {str(key): ProfileValue.from_dict(value) for key, value in raw.items()} if isinstance(raw, Mapping) else {}

        return cls(
            schema_version=HOST_PROFILE_SCHEMA_VERSION,
            collected_at=float(payload.get("collected_at", 0) or 0),
            os=decode("os"), cpu=decode("cpu"), memory=decode("memory"),
            storage=decode("storage"), virtualization=decode("virtualization"),
            collector_version=str(payload.get("collector_version") or "unknown"),
        )


def write_host_environment_profile(path: Path, profile: HostEnvironmentProfile) -> None:
    """Atomically publish a profile; a partial file is never considered valid."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(profile.to_dict(), handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw_tmp, target)
    finally:
        try:
            os.unlink(raw_tmp)
        except FileNotFoundError:
            pass


def read_host_environment_profile(path: Path) -> HostEnvironmentProfile | None:
    """Read an advisory profile. Missing, corrupt, or old profiles fail open."""
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return HostEnvironmentProfile.from_dict(json.load(handle))
    except (OSError, ValueError, TypeError, OverflowError, json.JSONDecodeError):
        return None


CommandRunner = Callable[[Sequence[str], float], str]


def _run_command(command: Sequence[str], timeout: float) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, timeout=timeout, check=False)
    return completed.stdout or ""


def _value(value: Any, source: str, confidence: str = "medium") -> ProfileValue:
    return ProfileValue(value=value if value not in (None, "") else _UNKNOWN, source=source, confidence=confidence)


def collect_host_environment_profile(*, data_root: Path | None = None, command_runner: CommandRunner | None = None, timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> HostEnvironmentProfile:
    """Collect inexpensive, bounded facts. WMI/PowerShell failures become unknown."""
    timeout = min(max(float(timeout_seconds), 0.1), MAX_COMMAND_TIMEOUT_SECONDS)
    runner = command_runner or (lambda command, limit: _run_command(command, limit))
    os_values = {
        "platform": _value(platform.system() or _UNKNOWN, "python", "high"),
        "release": _value(platform.release() or _UNKNOWN, "python", "medium"),
        "architecture": _value(platform.machine() or _UNKNOWN, "python", "medium"),
    }
    cpu_values = {"logical_processors": _value(os.cpu_count() or _UNKNOWN, "python", "medium")}
    memory_values: dict[str, ProfileValue] = {}
    storage_values: dict[str, ProfileValue] = {}
    virtualization: dict[str, ProfileValue] = {"status": _value(_UNKNOWN, "unavailable", "low")}

    if os.name == "nt":
        # Windows Server 2012-compatible WMI path; no modern Storage cmdlets required.
        try:
            raw = runner(["wmic", "computersystem", "get", "TotalPhysicalMemory", "/value"], timeout)
            for line in raw.splitlines():
                if line.lower().startswith("totalphysicalmemory="):
                    memory_values["bytes"] = _value(int(line.split("=", 1)[1].strip()), "wmic", "medium")
                    break
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError):
            pass
        try:
            raw = runner(["wmic", "os", "get", "Caption,Version,BuildNumber,ProductType", "/value"], timeout)
            fields = {
                line.split("=", 1)[0].strip().casefold(): line.split("=", 1)[1].strip()
                for line in raw.splitlines() if "=" in line
            }
            os_values["product_name"] = _value(fields.get("caption"), "wmic", "medium")
            os_values["version"] = _value(fields.get("version"), "wmic", "medium")
            os_values["build"] = _value(fields.get("buildnumber"), "wmic", "medium")
            product_type = fields.get("producttype")
            os_values["kind"] = _value(
                "server" if product_type in {"2", "3"} else "client" if product_type == "1" else _UNKNOWN,
                "wmic",
                "medium" if product_type else "unknown",
            )
        except (OSError, TimeoutError, subprocess.SubprocessError):
            pass
        try:
            raw = runner(["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors", "/value"], timeout)
            fields = {
                line.split("=", 1)[0].strip().casefold(): line.split("=", 1)[1].strip()
                for line in raw.splitlines() if "=" in line
            }
            cpu_values["model"] = _value(fields.get("name"), "wmic", "medium")
            if fields.get("numberofcores"):
                cpu_values["physical_cores"] = _value(int(fields["numberofcores"]), "wmic", "medium")
            if fields.get("numberoflogicalprocessors"):
                cpu_values["logical_processors"] = _value(int(fields["numberoflogicalprocessors"]), "wmic", "medium")
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError):
            pass
        try:
            raw = runner(["wmic", "diskdrive", "get", "Model,MediaType", "/value"], timeout)
            models = [line.split("=", 1)[1].strip() for line in raw.splitlines() if line.lower().startswith("model=")]
            if models:
                raid_hint = any(token in model.casefold() for model in models for token in ("perc", "smart array", "megaraid", "raid"))
                storage_values["hardware_raid"] = _value("likely" if raid_hint else _UNKNOWN, "wmic", "medium" if raid_hint else "low")
                storage_values["raid_level"] = _value(_UNKNOWN, "wmic", "low")
        except (OSError, TimeoutError, subprocess.SubprocessError):
            pass
    if data_root is not None:
        try:
            usage = shutil.disk_usage(Path(data_root))
            total = int(usage.total)
            free = int(usage.free)
            storage_values["volume"] = _value(str(Path(data_root).drive or _UNKNOWN), "path", "high")
            storage_values["data_root"] = _value(str(Path(data_root)), "installer", "high")
            storage_values["total_bytes"] = _value(total, "disk_usage", "high")
            storage_values["free_bytes"] = _value(free, "disk_usage", "high")
            storage_values["free_percent"] = _value(round((free / total) * 100, 2) if total else _UNKNOWN, "disk_usage", "high")
        except OSError:
            pass
    storage_values.setdefault("media_type", _value(_UNKNOWN, "windows", "unknown"))
    storage_values.setdefault("hardware_raid", _value(_UNKNOWN, "windows", "unknown"))
    storage_values.setdefault("raid_level", _value(_UNKNOWN, "windows", "unknown"))
    return HostEnvironmentProfile(os=os_values, cpu=cpu_values, memory=memory_values, storage=storage_values, virtualization=virtualization)


def collect_and_write_host_environment_profile(path: Path, *, data_root: Path | None = None, command_runner: CommandRunner | None = None, timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> HostEnvironmentProfile:
    profile = collect_host_environment_profile(data_root=data_root, command_runner=command_runner, timeout_seconds=timeout_seconds)
    write_host_environment_profile(path, profile)
    return profile


@dataclass(frozen=True)
class RuntimeCapabilityPolicy:
    cpu_worker_limit: int = 4
    network_concurrency: int = 4
    disk_maintenance_concurrency: int = 1
    cache_warmup_enabled: bool = True
    mode: str = "standard"
    unattended_priority: bool = False
    low_priority_work_enabled: bool = True

    def clamp_cpu_workers(self, requested: int) -> int:
        """Keep non-realtime CPU work within the persisted runtime budget."""
        return max(1, min(max(1, int(requested)), max(1, self.cpu_worker_limit)))

    @classmethod
    def from_profile(
        cls,
        profile: HostEnvironmentProfile | None,
        *,
        mode: "RuntimePerformanceMode" | None = None,
    ) -> "RuntimeCapabilityPolicy":
        selected_mode = mode or RuntimePerformanceMode.STANDARD
        if profile is None:
            return cls(
                mode=selected_mode.value,
                unattended_priority=selected_mode is RuntimePerformanceMode.SERVER_UNATTENDED,
                low_priority_work_enabled=selected_mode is RuntimePerformanceMode.STANDARD,
            )
        def number(group: Mapping[str, ProfileValue], key: str) -> int | None:
            raw = group.get(key)
            try:
                return int(raw.value) if raw and raw.value != _UNKNOWN else None
            except (TypeError, ValueError):
                return None
        cpu = number(profile.cpu, "logical_processors")
        memory = number(profile.memory, "bytes")
        low = (cpu is not None and cpu <= 2) or (memory is not None and memory < 8 * 1024**3)
        if selected_mode is RuntimePerformanceMode.SERVER_UNATTENDED:
            return cls(
                cpu_worker_limit=1 if low else 2,
                network_concurrency=2 if low else 4,
                disk_maintenance_concurrency=1,
                cache_warmup_enabled=False,
                mode=selected_mode.value,
                unattended_priority=True,
                low_priority_work_enabled=False,
            )
        return cls(
            cpu_worker_limit=1 if low else 4,
            network_concurrency=2 if low else 4,
            disk_maintenance_concurrency=1,
            cache_warmup_enabled=not low,
            mode=selected_mode.value,
        )


class RuntimePerformanceMode(str, Enum):
    STANDARD = "standard"
    SERVER_UNATTENDED = "server_unattended"


def read_runtime_performance_mode(
    path: Path,
    *,
    default: RuntimePerformanceMode = RuntimePerformanceMode.STANDARD,
) -> RuntimePerformanceMode:
    """Read the persisted user choice without hardware detection or writes."""
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        value = payload.get("app/runtime_performance_mode") if isinstance(payload, Mapping) else None
        return RuntimePerformanceMode(str(value))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default


__all__ = ["HOST_PROFILE_SCHEMA_VERSION", "HOST_PROFILE_COLLECTOR_VERSION", "ProfileValue", "HostEnvironmentProfile", "RuntimePerformanceMode", "RuntimeCapabilityPolicy", "collect_host_environment_profile", "collect_and_write_host_environment_profile", "write_host_environment_profile", "read_host_environment_profile", "read_runtime_performance_mode"]
