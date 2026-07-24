from __future__ import annotations

from enum import StrEnum


class RuntimeMode(StrEnum):
    DESKTOP = "desktop"
    SERVER = "server"
    TEST = "test"
