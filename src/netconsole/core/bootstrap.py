"""Backward-compatible import facade for the moved demo context service."""

from __future__ import annotations

import importlib
from typing import Any


_PUBLIC_NAMES = {"AppContext", "create_demo_context"}


def __getattr__(name: str) -> Any:
    if name not in _PUBLIC_NAMES:
        raise AttributeError(name)
    module = importlib.import_module("netconsole.services.demo_context")
    return getattr(module, name)


__all__ = sorted(_PUBLIC_NAMES)
