from __future__ import annotations

import sys
from pathlib import Path


def package_resource_path(*parts: str) -> Path:
    asset_relative = Path("assets", *parts)
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / asset_relative)
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "_internal" / asset_relative)
        candidates.append(exe_dir / asset_relative)
    candidates.append(Path(__file__).resolve().parents[1] / Path(*parts))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path(*parts)


def icon_path(name: str = "love.png") -> Path:
    return package_resource_path("ui", "icons", name)


def changelog_path() -> Path:
    return package_resource_path("docs", "changelog.md")
