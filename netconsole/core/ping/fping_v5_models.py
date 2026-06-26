from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


BACKEND = "fping_v5_json"


@dataclass(frozen=True)
class FpingV5CheckResult:
    available: bool
    fping_path: str = ""
    version_output: str = ""
    json_supported: bool = False
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FpingV5Sample:
    ts: str
    target: str
    seq: int | None
    ok: bool | None
    rtt_ms: float | None
    timeout_ms: int
    size: int | None
    error: str
    backend: str
    raw_type: str
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FpingV5Paths:
    fping_path: Path
    cygwin_dll_path: Path

