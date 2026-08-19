"""Shared, deliberately small data-lifecycle vocabulary.

The application only distinguishes long-lived evidence, authoritative current
state, and bounded change history.  Domain repositories own the details of
their entity keys and deletion workflows.
"""

from __future__ import annotations

from enum import StrEnum


KEEP_LAST_EFFECTIVE_COUNT = 10


class DataLifecycle(StrEnum):
    LONG_TERM_MANUAL_DELETE = "LONG_TERM_MANUAL_DELETE"
    CURRENT_STATE = "CURRENT_STATE"
    KEEP_LAST_10_EFFECTIVE = "KEEP_LAST_10_EFFECTIVE"


__all__ = ["DataLifecycle", "KEEP_LAST_EFFECTIVE_COUNT"]
