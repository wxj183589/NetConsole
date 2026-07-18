from __future__ import annotations

import os
import sys
from pathlib import Path


FORBIDDEN_RUNTIME_DIR_NAMES = frozenset({"docs", "tests", "project"})


def is_packaged_runtime() -> bool:
    if getattr(sys, "frozen", False):
        return True
    main_module = sys.modules.get("__main__")
    if getattr(main_module, "__compiled__", None):
        return True
    return _executable_app_root() is not None


def app_root() -> Path:
    executable_root = _executable_app_root()
    if executable_root is not None:
        return executable_root
    if is_packaged_runtime():
        return Path(sys.executable).resolve().parent
    return _source_project_root()


def _executable_app_root() -> Path | None:
    for executable in _runtime_executable_candidates():
        root = executable.parent
        if (root / "runtime" / "build_info.json").is_file():
            return root
    return None


def _runtime_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    for raw_path in (sys.argv[0] if sys.argv else "", sys.executable):
        path = Path(raw_path)
        if not raw_path or path.name.lower().startswith("python") or path.suffix.lower() != ".exe":
            continue
        resolved = path.resolve()
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


def data_root() -> Path:
    configured = os.environ.get("NETCONSOLE_DATA_ROOT")
    if configured:
        resolved = Path(configured).expanduser().resolve()
    else:
        base = _platform_data_home()
        resolved = (base / "NetConsole").resolve()
        if not is_packaged_runtime():
            resolved = resolved / "Development"
    _reject_source_tree_data_root(resolved)
    return resolved


def _platform_data_home() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser().resolve()
        return (Path.home() / "AppData" / "Local").resolve()
    configured = os.environ.get("XDG_DATA_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".local" / "share").resolve()


def _reject_source_tree_data_root(candidate: Path) -> None:
    if is_packaged_runtime():
        return
    source_root = _source_project_root().resolve()
    if candidate == source_root or candidate.is_relative_to(source_root):
        raise RuntimeError(f"NETCONSOLE_DATA_ROOT must not be inside the source repository: {candidate}")


def _source_project_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    return current.parents[3]


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
