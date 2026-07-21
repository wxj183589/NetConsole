from __future__ import annotations

import os


DEFAULT_FIT_AP_OPTICAL_CONCURRENCY = 64
FIT_AP_OPTICAL_CONCURRENCY_WINDOWS = 64
FIT_AP_OPTICAL_CONCURRENCY_OTHER = 128


def fit_ap_optical_platform_concurrency_limit() -> int:
    return FIT_AP_OPTICAL_CONCURRENCY_WINDOWS if os.name == "nt" else FIT_AP_OPTICAL_CONCURRENCY_OTHER


def clamp_fit_ap_optical_concurrency(
    requested_concurrency: object,
    target_count: int,
    *,
    platform_limit: int | None = None,
) -> int:
    targets = max(0, int(target_count or 0))
    if targets <= 0:
        return 0
    limit = max(1, int(platform_limit or fit_ap_optical_platform_concurrency_limit()))
    requested = _positive_int(requested_concurrency, DEFAULT_FIT_AP_OPTICAL_CONCURRENCY)
    return max(1, min(targets, requested, limit))


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(1, int(default))
    return max(1, parsed)


__all__ = [
    "DEFAULT_FIT_AP_OPTICAL_CONCURRENCY",
    "FIT_AP_OPTICAL_CONCURRENCY_OTHER",
    "FIT_AP_OPTICAL_CONCURRENCY_WINDOWS",
    "clamp_fit_ap_optical_concurrency",
    "fit_ap_optical_platform_concurrency_limit",
]
