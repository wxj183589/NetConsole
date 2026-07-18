from __future__ import annotations

import sys
from pathlib import Path


def runtime_base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).resolve()
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        internal = exe_dir / "_internal"
        return internal if internal.exists() else exe_dir
    compiled = getattr(sys.modules.get("__main__"), "__compiled__", None) or globals().get("__compiled__")
    if compiled:
        return Path(__file__).resolve().parents[2]
    return Path(__file__).resolve().parents[2]


def get_changelog_path(base_dir: Path) -> Path:
    packaged = base_dir / "netconsole" / "assets" / "changelog.md"
    if packaged.exists():
        return packaged
    root_changelog = base_dir / "docs" / "CHANGELOG.md"
    if root_changelog.exists():
        return root_changelog
    return base_dir / "netconsole" / "docs" / "changelog.md"


def package_resource_path(*parts: str) -> Path:
    resource_relative = Path("netconsole", *parts)
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(runtime_base_dir() / resource_relative)
    candidates.append(runtime_base_dir() / resource_relative)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path(*parts)


def changelog_path() -> Path:
    return get_changelog_path(runtime_base_dir())


def open_source_notices_path(base_dir: Path | None = None) -> Path:
    base = base_dir or runtime_base_dir()
    packaged = base / "netconsole" / "assets" / "open_source_notices.json"
    if packaged.exists():
        return packaged
    root_notices = base / "docs" / "open_source_notices.json"
    if root_notices.exists():
        return root_notices
    return base / "docs" / "open_source_notices.json"
