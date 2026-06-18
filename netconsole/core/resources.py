from __future__ import annotations

import sys
from pathlib import Path


def runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "_internal"
    return Path(__file__).resolve().parents[2]


def get_changelog_path(base_dir: Path) -> Path:
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


def icon_path(name: str = "love.png") -> Path:
    return package_resource_path("ui", "icons", name)


def changelog_path() -> Path:
    return get_changelog_path(runtime_base_dir())
