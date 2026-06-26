from __future__ import annotations

import os
import sys
from pathlib import Path


FORBIDDEN_RUNTIME_DIR_NAMES = frozenset({"docs", "tests", "project"})


def is_packaged_runtime() -> bool:
    if getattr(sys, "frozen", False):
        return True
    main_module = sys.modules.get("__main__")
    return bool(getattr(main_module, "__compiled__", None))


def app_root() -> Path:
    if is_packaged_runtime():
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def data_root() -> Path:
    configured = os.environ.get("NETCONSOLE_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return app_root()


def validate_runtime_write_path(path: Path) -> Path:
    resolved = Path(path).resolve()
    forbidden = [part for part in resolved.parts if part.lower() in FORBIDDEN_RUNTIME_DIR_NAMES]
    if forbidden:
        raise RuntimeError(f"invalid runtime write path: {resolved}")
    return resolved


def ensure_runtime_dir(path: Path) -> Path:
    resolved = validate_runtime_write_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
