from __future__ import annotations


OPTICAL_NOT_APPLICABLE_STATUS = "not_applicable"
OPTICAL_NOT_APPLICABLE_REASON = "该型号使用网口接入，不适用 AP 光模块光衰检测。"
_OPTICAL_NOT_APPLICABLE_MODELS = frozenset({"wa6522"})


def normalize_ap_model(value: object) -> str:
    return str(value or "").strip().casefold()


def is_ap_optical_applicable(value: object) -> bool:
    return normalize_ap_model(value) not in _OPTICAL_NOT_APPLICABLE_MODELS


__all__ = [
    "OPTICAL_NOT_APPLICABLE_REASON",
    "OPTICAL_NOT_APPLICABLE_STATUS",
    "is_ap_optical_applicable",
    "normalize_ap_model",
]
