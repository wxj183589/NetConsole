from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROTECTED_CATEGORIES = {"database", "config_center", "file_manager", "rail_transit", "network_tools", "backups", "config"}
CLEANABLE_CATEGORIES = {"cache"}


@dataclass(frozen=True)
class DiskCategory:
    name: str
    path: Path
    bytes: int
    cleanable: bool


def scan_data_disk(data_dir: Path, runtime_dir: Path | None = None) -> list[DiskCategory]:
    data_root = Path(data_dir)
    runtime_root = Path(runtime_dir) if runtime_dir is not None else data_root / "runtime"
    sites_root = data_root / "sites"
    categories = [
        DiskCategory("database", sites_root, _size_site_children(sites_root, "db"), False),
        DiskCategory("config_center", sites_root, _size_site_children(sites_root, "files/config_center"), False),
        DiskCategory("file_manager", sites_root, _size_site_children(sites_root, "files/file_manager"), False),
        DiskCategory("rail_transit", sites_root, _size_site_children(sites_root, "files/rail_transit"), False),
        DiskCategory("network_tools", sites_root, _size_site_children(sites_root, "files/network_tools"), False),
        DiskCategory("backups", sites_root, _size_site_children(sites_root, "files/backups"), False),
        DiskCategory("config", data_root / "config", _dir_size(data_root / "config"), False),
        DiskCategory("cache", data_root, _size_site_children(sites_root, "cache") + _dir_size(runtime_root / "cache"), True),
        DiskCategory("debug_logs", runtime_root / "logs", _dir_size(runtime_root / "logs"), False),
    ]
    return categories


def clean_data_disk(data_dir: Path, runtime_dir: Path | None = None, categories: set[str] | None = None) -> dict[str, int]:
    requested = set(categories or CLEANABLE_CATEGORIES)
    unsafe = requested - CLEANABLE_CATEGORIES
    if unsafe:
        raise ValueError(f"Refusing to clean protected categories: {', '.join(sorted(unsafe))}")
    data_root = Path(data_dir)
    runtime_root = Path(runtime_dir) if runtime_dir is not None else data_root / "runtime"
    result: dict[str, int] = {}
    if "cache" in requested:
        removed = _clear_site_children(data_root / "sites", "cache")
        removed += _clear_dir(runtime_root / "cache")
        result["cache"] = removed
    return result


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def _size_matching(path: Path, suffixes: set[str]) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and item.suffix.casefold() in suffixes)


def _size_site_children(sites_root: Path, relative: str) -> int:
    if not sites_root.exists():
        return 0
    total = 0
    parts = Path(relative).parts
    for site in sites_root.iterdir():
        if site.is_dir():
            total += _dir_size(site.joinpath(*parts))
    return total


def _clear_site_children(sites_root: Path, relative: str) -> int:
    if not sites_root.exists():
        return 0
    removed = 0
    parts = Path(relative).parts
    for site in sites_root.iterdir():
        if site.is_dir():
            removed += _clear_dir(site.joinpath(*parts))
    return removed


def _clear_dir(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    removed = 0
    for item in sorted(path.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if item.is_file():
            size = item.stat().st_size
            item.unlink()
            removed += size
        elif item.is_dir():
            try:
                item.rmdir()
            except OSError:
                pass
    return removed
