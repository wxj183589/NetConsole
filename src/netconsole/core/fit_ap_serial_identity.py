from __future__ import annotations

import unicodedata


FIT_AP_INVALID_IDENTITY_VALUES = frozenset(
    {"", "-", "--", "n/a", "na", "none", "null", "unknown"}
)


def clean_fit_ap_serial(value: object) -> str:
    """Normalize FIT-AP serial text for persistence and identity matching."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text or text.casefold() in FIT_AP_INVALID_IDENTITY_VALUES:
        return ""
    return text


def fit_ap_serial_identity_key(value: object) -> str:
    """Return the case-insensitive key used by application and SQLite identity."""

    return clean_fit_ap_serial(value).casefold()
