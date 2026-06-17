from __future__ import annotations

from netconsole.core.optical_severity_engine import (
    OpticalSeverityResult as SeverityResult,
    SEVERITY_RANK,
    compute_optical_severity,
    worse_optical_severity,
)


def compute_severity(context: dict) -> SeverityResult:
    return compute_optical_severity(context)


def worse_severity(left: str, right: str) -> str:
    return worse_optical_severity(left, right)
