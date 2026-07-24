from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from netconsole.core.runtime_environment import is_packaged_runtime
from netconsole.core.version import APP_VERSION


BUILD_METADATA_FILE = "build-metadata.json"
UNKNOWN_BUILD_VALUE = "unknown"


def current_build_metadata(project_root: Path) -> dict[str, Any]:
    if is_packaged_runtime():
        return read_embedded_build_metadata(project_root)
    return source_build_metadata(project_root)


def read_embedded_build_metadata(app_root: Path) -> dict[str, Any]:
    root = Path(app_root)
    candidates = (
        root / "_internal" / "netconsole" / "assets" / "runtime" / BUILD_METADATA_FILE,
        root / "netconsole" / "assets" / "runtime" / BUILD_METADATA_FILE,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def source_build_metadata(project_root: Path) -> dict[str, Any]:
    root = Path(project_root)
    try:
        full = _git(root, "rev-parse", "HEAD")
        dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=normal"))
    except (OSError, subprocess.SubprocessError):
        full = UNKNOWN_BUILD_VALUE
        dirty = True
    short = full[:8] if full != UNKNOWN_BUILD_VALUE else UNKNOWN_BUILD_VALUE
    return {
        "app_version": APP_VERSION,
        "git_commit_full": full,
        "git_commit_short": short,
        "build_time_utc": "",
        "build_dirty": dirty,
        "build_source": "source-worktree",
        "frontend_commit": full,
        "backend_commit": full,
    }


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=5,
    ).stdout.strip()


__all__ = [
    "BUILD_METADATA_FILE",
    "UNKNOWN_BUILD_VALUE",
    "current_build_metadata",
    "read_embedded_build_metadata",
    "source_build_metadata",
]
