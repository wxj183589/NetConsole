from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from netconsole.core.paths import PathResolver


APP_CLEANUP_RETENTION_DAYS = 3
APP_LOG_PATTERNS = ("*.log", "*.log.*", "netconsole_*.log", "runtime_*.log", "app_*.log", "ui_*.log")
CACHE_DIR_NAMES = ("cache", "tmp", "temp", "runtime_cache", "__runtime_cache__", "thumbnails", "chart_cache", "preview_cache")


@dataclass
class CleanupFailure:
    path: str
    error: str


@dataclass
class AppCleanupResult:
    retention_days: int
    cutoff: datetime
    deleted_log_files: int = 0
    deleted_cache_files: int = 0
    deleted_log_records: int = 0
    freed_bytes: int = 0
    failures: list[CleanupFailure] = field(default_factory=list)

    @property
    def deleted_files(self) -> int:
        return self.deleted_log_files + self.deleted_cache_files

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    def summary_detail(self) -> str:
        return (
            f"retention_days={self.retention_days} cutoff={self.cutoff.strftime('%Y-%m-%d %H:%M:%S')} "
            f"deleted_log_files={self.deleted_log_files} deleted_cache_files={self.deleted_cache_files} "
            f"deleted_log_records={self.deleted_log_records} failed={self.failed_count} freed_bytes={self.freed_bytes}"
        )


def run_app_auto_cleanup(paths: PathResolver, retention_days: int = APP_CLEANUP_RETENTION_DAYS, *, emit_log: bool = True) -> AppCleanupResult:
    days = max(1, int(retention_days or APP_CLEANUP_RETENTION_DAYS))
    cutoff = datetime.now() - timedelta(days=days)
    result = AppCleanupResult(retention_days=days, cutoff=cutoff)
    allowed_log_dirs = _existing_dirs([paths.logs_dir])
    allowed_cache_dirs = _existing_dirs(_runtime_cache_dirs(paths))

    _delete_old_logs(allowed_log_dirs, cutoff, result)
    _delete_old_cache_files(allowed_cache_dirs, cutoff, result)
    _remove_empty_dirs(allowed_cache_dirs)

    if emit_log:
        _emit_cleanup_log(result)
    return result


def _runtime_cache_dirs(paths: PathResolver) -> list[Path]:
    runtime = paths.runtime_dir
    return [runtime / name for name in CACHE_DIR_NAMES]


def _existing_dirs(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        try:
            resolved = Path(path).resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in result:
            result.append(resolved)
    return result


def _delete_old_logs(allowed_dirs: list[Path], cutoff: datetime, result: AppCleanupResult) -> None:
    seen: set[Path] = set()
    for directory in allowed_dirs:
        for pattern in APP_LOG_PATTERNS:
            for file_path in directory.glob(pattern):
                resolved = _safe_resolve(file_path)
                if resolved is None or resolved in seen:
                    continue
                seen.add(resolved)
                if not resolved.is_file() or not _is_relative_to_any(resolved, allowed_dirs):
                    continue
                if _is_old_file(resolved, cutoff):
                    _delete_file(resolved, result, is_log=True)


def _delete_old_cache_files(allowed_dirs: list[Path], cutoff: datetime, result: AppCleanupResult) -> None:
    for directory in allowed_dirs:
        for file_path in directory.rglob("*"):
            resolved = _safe_resolve(file_path)
            if resolved is None or not resolved.is_file() or not _is_relative_to_any(resolved, allowed_dirs):
                continue
            if _is_old_file(resolved, cutoff):
                _delete_file(resolved, result, is_log=False)


def _delete_file(path: Path, result: AppCleanupResult, *, is_log: bool) -> None:
    try:
        size = path.stat().st_size
        path.unlink()
        result.freed_bytes += size
        if is_log:
            result.deleted_log_files += 1
        else:
            result.deleted_cache_files += 1
    except OSError as exc:
        result.failures.append(CleanupFailure(str(path), str(exc)))


def _remove_empty_dirs(allowed_dirs: list[Path]) -> None:
    for directory in allowed_dirs:
        for item in sorted(directory.rglob("*"), key=lambda value: len(value.parts), reverse=True):
            resolved = _safe_resolve(item)
            if resolved is None or not resolved.is_dir() or not _is_relative_to_any(resolved, allowed_dirs):
                continue
            try:
                resolved.rmdir()
            except OSError:
                pass


def _is_old_file(path: Path, cutoff: datetime) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    return mtime < cutoff


def _safe_resolve(path: Path) -> Path | None:
    try:
        return Path(path).resolve()
    except OSError:
        return None


def _is_relative_to_any(path: Path, allowed_dirs: list[Path]) -> bool:
    return any(path == directory or path.is_relative_to(directory) for directory in allowed_dirs)


def _emit_cleanup_log(result: AppCleanupResult) -> None:
    from netconsole.core import app_logger

    if result.failures:
        first = result.failures[0]
        app_logger.log_warning(
            "APP_AUTO_CLEANUP_PARTIAL_FAILED",
            f"{result.summary_detail()} first_failed_path={first.path} error={first.error}",
        )
    else:
        app_logger.log_info("APP_AUTO_CLEANUP_COMPLETED", result.summary_detail())
