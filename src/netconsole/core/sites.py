"""Backward-compatible import facade for the moved site service.

Site composition belongs to :mod:`netconsole.services.site_manager`.  This
module keeps the historical import path usable for extensions while avoiding
any core-owned repository or startup composition.
"""

from __future__ import annotations

import importlib
from typing import Any


_PUBLIC_NAMES = {
    "DEFAULT_SITE",
    "INVALID_SITE_NAME_CHARS",
    "Site",
    "SiteManager",
}


def __getattr__(name: str) -> Any:
    if name not in _PUBLIC_NAMES:
        raise AttributeError(name)
    module = importlib.import_module("netconsole.services.site_manager")
    return getattr(module, name)


__all__ = sorted(_PUBLIC_NAMES)
