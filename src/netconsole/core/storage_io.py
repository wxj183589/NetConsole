"""实际数据根所在卷的存储介质识别与统一 I/O profile。

识别失败必须降级到保守策略。该模块只读取 Windows 存储信息，不修改磁盘、
SQLite durability 或业务数据。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class StorageMediaType(StrEnum):
    NVME = "NVME"
    SSD = "SSD"
    HDD = "HDD"
    RAID = "RAID"
    UNKNOWN = "UNKNOWN"


class StorageProfileMode(StrEnum):
    AUTO = "AUTO"
    FAST = "FAST"
    CONSERVATIVE = "CONSERVATIVE"


@dataclass(frozen=True)
class StorageDetection:
    data_root: str
    volume: str
    media_type: str = StorageMediaType.UNKNOWN.value
    confidence: str = "LOW"
    profile: str = "CONSERVATIVE_STORAGE"
    reason: str = "无法可靠识别底层介质，已采用保守策略"
    detection_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["detection_sources"] = list(self.detection_sources)
        return payload


@dataclass(frozen=True)
class StorageIOProfile:
    """所有实时写入消费者共享的参数契约。"""

    name: str
    raw_batch_bytes: int
    raw_flush_interval_ms: int
    durable_sync_interval_ms: int
    raw_segment_size: int
    max_active_raw_writers: int
    parser_batch_size: int
    db_batch_size: int
    db_batch_interval_ms: int
    sqlite_checkpoint_policy: str
    archive_during_active_collection: bool
    profile_source: str = "AUTO"

    @classmethod
    def fast(cls, *, source: str = "AUTO") -> "StorageIOProfile":
        return cls(
            name="FAST_STORAGE", raw_batch_bytes=64 * 1024,
            raw_flush_interval_ms=250, durable_sync_interval_ms=1000,
            raw_segment_size=128 * 1024 * 1024, max_active_raw_writers=32,
            parser_batch_size=200, db_batch_size=200, db_batch_interval_ms=500,
            sqlite_checkpoint_policy="NORMAL", archive_during_active_collection=True,
            profile_source=source,
        )

    @classmethod
    def conservative(cls, *, source: str = "AUTO") -> "StorageIOProfile":
        return cls(
            name="CONSERVATIVE_STORAGE", raw_batch_bytes=512 * 1024,
            raw_flush_interval_ms=400, durable_sync_interval_ms=1000,
            raw_segment_size=128 * 1024 * 1024, max_active_raw_writers=4,
            parser_batch_size=500, db_batch_size=1000, db_batch_interval_ms=750,
            sqlite_checkpoint_policy="DEFERRED", archive_during_active_collection=False,
            profile_source=source,
        )

    @classmethod
    def from_mode(cls, mode: str, *, detected: StorageDetection | None = None) -> "StorageIOProfile":
        value = str(mode or StorageProfileMode.AUTO.value).upper()
        if value == StorageProfileMode.FAST.value:
            return cls.fast(source="MANUAL")
        if value == StorageProfileMode.CONSERVATIVE.value:
            return cls.conservative(source="MANUAL")
        if detected is not None and detected.profile == "FAST_STORAGE":
            return cls.fast(source="AUTO")
        return cls.conservative(source="AUTO")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CommandRunner = Callable[[Sequence[str], float], str]


def _run_powershell(command: Sequence[str], timeout: float) -> str:
    return subprocess.run(
        list(command), capture_output=True, text=True, encoding="utf-8",
        errors="replace", shell=False, timeout=timeout, check=False,
    ).stdout or ""


def _records(raw: str) -> list[Mapping[str, Any]]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(value, Mapping):
        return [value]
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        for actual, value in record.items():
            if str(actual).casefold() == key.casefold() and value not in (None, ""):
                return str(value).strip()
    return ""


def nvme_signal_from_records(records: list[Mapping[str, Any]]) -> bool:
    return any(
        _text(record, "BusType", "BusTypeName").casefold() in {"17", "nvme"}
        or "nvme" in _text(record, "FriendlyName", "Model").casefold()
        for record in records
    )


class StorageProfileDetector:
    """通过 data_root -> volume -> Windows CIM 信息识别存储介质。"""

    def __init__(self, *, command_runner: CommandRunner | None = None, timeout_seconds: float = 4.0) -> None:
        self.command_runner = command_runner or _run_powershell
        self.timeout_seconds = max(0.1, min(float(timeout_seconds), 15.0))

    def detect(self, data_root: Path | str) -> StorageDetection:
        root = Path(data_root).resolve()
        volume = str(root.drive or "").upper()
        sources: list[str] = ["path"]
        if not volume:
            return StorageDetection(str(root), volume, detection_sources=tuple(sources))
        try:
            drive_letter = volume.rstrip(":")
            raw = self.command_runner(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"$disk=Get-Partition -DriveLetter '{drive_letter}' | Get-Disk; "
                 "$physical=Get-CimInstance -Namespace root/Microsoft/Windows/Storage "
                 "-ClassName MSFT_PhysicalDisk -ErrorAction SilentlyContinue; "
                 "@($disk,$physical) | Select-Object * | ConvertTo-Json -Depth 4"],
                self.timeout_seconds,
            )
            records = _records(raw)
            if not records:
                return StorageDetection(str(root), volume, reason="Windows 存储 API 未返回可用信息", detection_sources=tuple(sources + ["cim:unavailable"]))
            sources.append("cim:partition-disk")
            return self._classify(str(root), volume, records, sources)
        except (OSError, TimeoutError, ValueError, subprocess.SubprocessError) as exc:
            return StorageDetection(str(root), volume, reason=f"存储检测异常，已采用保守策略: {exc.__class__.__name__}", detection_sources=tuple(sources + ["cim:error"]))

    def _classify(self, root: str, volume: str, records: list[Mapping[str, Any]], sources: list[str]) -> StorageDetection:
        values = " ".join(" ".join(str(v) for v in record.values()) for record in records).casefold()
        media_numbers = {_text(record, "MediaType") for record in records}
        raid = any(token in values for token in ("raid", "perc", "megaraid", "smart array", "virtual disk", "logical disk"))
        nvme_signal = any(token in values for token in ("nvme", "non-volatile memory express")) or nvme_signal_from_records(records)
        ssd_signal = any(token in values for token in ("solid state", " ssd", "ssd ")) or "4" in media_numbers
        hdd_signal = any(token in values for token in ("hard disk", " hdd", "hdd ")) or "3" in media_numbers
        if raid:
            media, confidence, reason = StorageMediaType.RAID.value, "MEDIUM", "检测到 RAID/虚拟磁盘呈现，底层介质不可可靠确认"
        elif nvme_signal:
            media, confidence, reason = StorageMediaType.NVME.value, "HIGH", "CIM 信息明确包含 NVMe 总线/介质信号"
        elif ssd_signal and not hdd_signal:
            media, confidence, reason = StorageMediaType.SSD.value, "MEDIUM", "CIM 信息提供 SSD 介质信号"
        elif hdd_signal:
            media, confidence, reason = StorageMediaType.HDD.value, "HIGH", "CIM 信息明确包含 HDD 介质信号"
        else:
            media, confidence, reason = StorageMediaType.UNKNOWN.value, "LOW", "介质类型未明确，已采用保守策略"
        profile = "FAST_STORAGE" if media in {StorageMediaType.NVME.value, StorageMediaType.SSD.value} else "CONSERVATIVE_STORAGE"
        return StorageDetection(root, volume, media, confidence, profile, reason, tuple(sources))


def detect_storage_profile(data_root: Path | str, *, mode: str = "AUTO", detector: StorageProfileDetector | None = None) -> tuple[StorageDetection, StorageIOProfile]:
    detection = (detector or StorageProfileDetector()).detect(data_root)
    return detection, StorageIOProfile.from_mode(mode, detected=detection)


__all__ = ["StorageMediaType", "StorageProfileMode", "StorageDetection", "StorageIOProfile", "StorageProfileDetector", "detect_storage_profile"]
