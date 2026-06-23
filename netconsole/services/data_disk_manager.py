from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROTECTED_CATEGORIES = {"database", "reports", "backups", "exports", "config"}
CLEANABLE_CATEGORIES = {"raw_logs", "runtime_cache", "debug_logs"}


@dataclass(frozen=True)
class DiskCategory:
    name: str
    path: Path
    bytes: int
    cleanable: bool


def scan_data_disk(data_dir: Path, runtime_dir: Path | None = None) -> list[DiskCategory]:
    data_root = Path(data_dir)
    runtime_root = Path(runtime_dir) if runtime_dir is not None else data_root.parent / "runtime"
    categories = [
        DiskCategory("database", data_root / "sites", _size_matching(data_root / "sites", {".db", ".sqlite", ".sqlite3"}), False),
        DiskCategory("reports", data_root, _size_named_dirs(data_root, {"reports"}), False),
        DiskCategory("backups", data_root, _size_named_dirs(data_root, {"backups", "db_backup"}), False),
        DiskCategory("exports", data_root, _size_named_dirs(data_root, {"exports", "export"}), False),
        DiskCategory("config", data_root / "config", _dir_size(data_root / "config"), False),
        DiskCategory("raw_logs", data_root, _size_named_dirs(data_root, {"raw"}), True),
        DiskCategory("debug_logs", data_root, _size_named_dirs(data_root, {"debug", "logs"}), True),
        DiskCategory("runtime_cache", runtime_root / "cache", _dir_size(runtime_root / "cache"), True),
    ]
    return categories


def clean_data_disk(data_dir: Path, runtime_dir: Path | None = None, categories: set[str] | None = None) -> dict[str, int]:
    requested = set(categories or CLEANABLE_CATEGORIES)
    unsafe = requested - CLEANABLE_CATEGORIES
    if unsafe:
        raise ValueError(f"Refusing to clean protected categories: {', '.join(sorted(unsafe))}")
    data_root = Path(data_dir)
    runtime_root = Path(runtime_dir) if runtime_dir is not None else data_root.parent / "runtime"
    result: dict[str, int] = {}
    if "raw_logs" in requested:
        result["raw_logs"] = _remove_named_dirs(data_root, {"raw"})
    if "debug_logs" in requested:
        result["debug_logs"] = _remove_named_dirs(data_root, {"debug", "logs"})
    if "runtime_cache" in requested:
        result["runtime_cache"] = _clear_dir(runtime_root / "cache")
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


def _size_named_dirs(root: Path, names: set[str]) -> int:
    if not root.exists():
        return 0
    return sum(_dir_size(item) for item in root.rglob("*") if item.is_dir() and item.name.casefold() in names)


def _remove_named_dirs(root: Path, names: set[str]) -> int:
    if not root.exists():
        return 0
    removed = 0
    targets = sorted(
        [item for item in root.rglob("*") if item.is_dir() and item.name.casefold() in names],
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for target in targets:
        removed += _clear_dir(target)
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
