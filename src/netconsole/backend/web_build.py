from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from netconsole.core.build_metadata import current_build_metadata
from netconsole.core.version import APP_VERSION


FRONTEND_BUILD_META_FILE = "desktop-renderer-build-meta.json"
FRONTEND_MISMATCH_MESSAGE = "当前 Desktop Renderer 资源与后端版本不一致，请重新构建 Renderer 资源。"
_BUILD_ID_RE = re.compile(r"[A-Za-z0-9._+-]{1,128}")
_FULL_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")


def backend_build_id(project_root: Path) -> str:
    metadata = current_build_metadata(project_root)
    commit = str(metadata.get("backend_commit") or "unknown")
    if bool(metadata.get("build_dirty")) and commit != "unknown":
        commit = f"{commit}-dirty"
    return f"{APP_VERSION}+{commit}"


def read_frontend_build_meta(frontend_root: Path) -> dict[str, Any]:
    path = frontend_root / FRONTEND_BUILD_META_FILE
    try:
        if path.stat().st_size > 65_536:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def frontend_build_id(metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("build_id") or "").strip()
    if _BUILD_ID_RE.fullmatch(explicit):
        return explicit
    version = str(metadata.get("app_version") or "").strip()
    commit = str(metadata.get("git_commit") or "").strip()
    derived = f"{version}+{commit}" if version and commit else ""
    return derived if _BUILD_ID_RE.fullmatch(derived) else ""


def verified_frontend_commit(metadata: dict[str, Any]) -> str:
    """Return the Renderer commit only when its embedded identity is self-consistent."""

    full = str(metadata.get("git_commit_full") or "").strip()
    if _FULL_GIT_SHA_RE.fullmatch(full) is None:
        return "unknown"
    if any(
        str(metadata.get(key) or "").strip() != full
        for key in ("frontend_commit", "backend_commit")
    ):
        return "unknown"
    if str(metadata.get("git_commit_short") or "").strip() != full[:8]:
        return "unknown"
    dirty = metadata.get("build_dirty")
    if not isinstance(dirty, bool):
        return "unknown"
    identity = f"{full}-dirty" if dirty else full
    if str(metadata.get("git_commit") or "").strip() != identity:
        return "unknown"
    version = str(metadata.get("app_version") or "").strip()
    if not version or str(metadata.get("build_id") or "").strip() != f"{version}+{identity}":
        return "unknown"
    return full
