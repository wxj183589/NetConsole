from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

from netconsole.core.paths import PathResolver


APP_CLEANUP_RETENTION_DAYS = 3
APP_LOG_PATTERNS = ("*.log", "*.log.*", "netconsole_*.log", "runtime_*.log", "app_*.log", "ui_*.log")
CLEANUP_ITEM_IDS = ("runtime_logs", "runtime_cache", "temporary_files")
_RUNTIME_CACHE_SUBDIRS = ("thumbnails", "chart_cache", "preview_cache")
_TEMPORARY_SUBDIRS = ("tmp", "temp", "export_tmp", "download_tmp")
_PROTECTED_RUNTIME_SUBDIRS = frozenset(
    {
        "background_jobs",
        "export_jobs",
        "ac_web_action_plans",
        "config_irreversible",
        "rail_web_table_previews",
        "rail_web_uploads",
    }
)


@dataclass
class CleanupFailure:
    path: str
    error: str


@dataclass(frozen=True)
class CleanupCandidate:
    path: Path
    size: int
    is_log: bool


@dataclass
class CleanupItem:
    item_id: str
    title: str
    description: str
    retention_policy: str
    status: str
    candidates: list[CleanupCandidate] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.candidates)

    @property
    def total_bytes(self) -> int:
        return sum(candidate.size for candidate in self.candidates)


@dataclass
class AppCleanupResult:
    retention_days: int
    cutoff: datetime
    deleted_log_files: int = 0
    deleted_cache_files: int = 0
    deleted_log_records: int = 0
    freed_bytes: int = 0
    processed_files: int = 0
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


class AppCleanupService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def scan_cleanup_items(self, retention_days: int = APP_CLEANUP_RETENTION_DAYS) -> list[CleanupItem]:
        days = max(1, int(retention_days or APP_CLEANUP_RETENTION_DAYS))
        cutoff = datetime.now() - timedelta(days=days)
        policy = f"保留最近 {days} 天"
        items = [
            CleanupItem(
                "runtime_logs",
                "软件运行日志",
                "NetConsole 软件自身运行日志文件",
                policy,
                "待清理",
                self._log_candidates(cutoff),
            ),
            CleanupItem(
                "runtime_cache",
                "页面/图表缓存",
                "页面渲染、图表预览、运行时缓存文件",
                policy,
                "待清理",
                self._cache_candidates(cutoff, self._runtime_cache_dirs()),
            ),
            CleanupItem(
                "temporary_files",
                "临时文件",
                "临时目录、导出缓存、下载缓存中的过期文件",
                policy,
                "待清理",
                self._cache_candidates(cutoff, self._temporary_dirs()),
            ),
        ]
        for item in items:
            item.status = "可清理" if item.file_count else "无需清理"
        return items

    def cleanup_items(
        self,
        items: list[CleanupItem],
        retention_days: int = APP_CLEANUP_RETENTION_DAYS,
        *,
        should_cancel: Callable[[], None] | None = None,
        progress_callback: Callable[[int, int, AppCleanupResult], None] | None = None,
    ) -> AppCleanupResult:
        days = max(1, int(retention_days or APP_CLEANUP_RETENTION_DAYS))
        cutoff = datetime.now() - timedelta(days=days)
        result = AppCleanupResult(retention_days=days, cutoff=cutoff)
        self.validate_item_ids(item.item_id for item in items)
        allowed_dirs_by_item = {
            "runtime_logs": _existing_dirs([self.paths.logs_dir]),
            "runtime_cache": _existing_dirs(self._runtime_cache_dirs()),
            "temporary_files": _existing_dirs(self._temporary_dirs()),
        }
        total = sum(item.file_count for item in items)
        seen: set[Path] = set()
        for item in items:
            allowed_dirs = allowed_dirs_by_item[item.item_id]
            for candidate in item.candidates:
                if should_cancel is not None:
                    should_cancel()
                resolved = _safe_resolve(candidate.path)
                if resolved is None or resolved in seen:
                    continue
                seen.add(resolved)
                refreshed = _candidate_for_file(
                    resolved,
                    cutoff,
                    allowed_dirs,
                    is_log=candidate.is_log,
                )
                if refreshed is None:
                    continue
                _delete_file(refreshed.path, result, is_log=refreshed.is_log)
                result.processed_files += 1
                if progress_callback is not None:
                    progress_callback(result.processed_files, total, result)
        _remove_empty_dirs(_existing_dirs([*self._runtime_cache_dirs(), *self._temporary_dirs()]))
        return result

    def cleanup_selected(
        self,
        item_ids: Iterable[str],
        retention_days: int = APP_CLEANUP_RETENTION_DAYS,
        *,
        should_cancel: Callable[[], None] | None = None,
        progress_callback: Callable[[int, int, AppCleanupResult], None] | None = None,
    ) -> tuple[list[CleanupItem], AppCleanupResult]:
        selected = self.validate_item_ids(item_ids)
        rescanned = self.scan_cleanup_items(retention_days)
        items = [item for item in rescanned if item.item_id in selected]
        return items, self.cleanup_items(
            items,
            retention_days,
            should_cancel=should_cancel,
            progress_callback=progress_callback,
        )

    @staticmethod
    def validate_item_ids(item_ids: Iterable[str]) -> tuple[str, ...]:
        values = tuple(str(value or "").strip() for value in item_ids)
        if not values or any(not value for value in values):
            raise ValueError("清理项目不能为空")
        if len(values) != len(set(values)):
            raise ValueError("清理项目不能重复")
        unknown = set(values) - set(CLEANUP_ITEM_IDS)
        if unknown:
            raise ValueError("清理项目不在白名单")
        return values

    def auto_cleanup(self, retention_days: int = APP_CLEANUP_RETENTION_DAYS) -> AppCleanupResult:
        items = self.scan_cleanup_items(retention_days)
        result = self.cleanup_items(items, retention_days)
        _emit_cleanup_log(result)
        return result

    def _log_candidates(self, cutoff: datetime) -> list[CleanupCandidate]:
        candidates: list[CleanupCandidate] = []
        seen: set[Path] = set()
        allowed_dirs = _existing_dirs([self.paths.logs_dir])
        active_log = _safe_resolve(self.paths.app_log_path)
        for directory in allowed_dirs:
            for pattern in APP_LOG_PATTERNS:
                for file_path in directory.glob(pattern):
                    candidate = _candidate_for_file(file_path, cutoff, allowed_dirs, is_log=True)
                    if candidate is None or candidate.path == active_log or candidate.path in seen:
                        continue
                    seen.add(candidate.path)
                    candidates.append(candidate)
        return candidates

    def _cache_candidates(
        self,
        cutoff: datetime,
        directories: Iterable[Path],
    ) -> list[CleanupCandidate]:
        candidates: list[CleanupCandidate] = []
        allowed_dirs = _existing_dirs(list(directories))
        for directory in allowed_dirs:
            for file_path in directory.rglob("*"):
                candidate = _candidate_for_file(file_path, cutoff, allowed_dirs, is_log=False)
                if candidate is not None:
                    candidates.append(candidate)
        return candidates

    def _runtime_cache_dirs(self) -> list[Path]:
        root = self.paths.runtime_cache_dir
        return [root / name for name in _RUNTIME_CACHE_SUBDIRS]

    def _temporary_dirs(self) -> list[Path]:
        return [
            *(self.paths.runtime_cache_dir / name for name in _TEMPORARY_SUBDIRS),
            *(
                self.paths.runtime_dir / name
                for name in ("tmp", "temp", "export_tmp", "download_tmp")
            ),
        ]


def run_app_auto_cleanup(paths: PathResolver, retention_days: int = APP_CLEANUP_RETENTION_DAYS, *, emit_log: bool = True) -> AppCleanupResult:
    service = AppCleanupService(paths)
    result = service.cleanup_items(service.scan_cleanup_items(retention_days), retention_days)
    if emit_log:
        _emit_cleanup_log(result)
    return result


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


def _candidate_for_file(path: Path, cutoff: datetime, allowed_dirs: list[Path], *, is_log: bool) -> CleanupCandidate | None:
    resolved = _safe_resolve(path)
    if resolved is None or not resolved.is_file() or not _is_relative_to_any(resolved, allowed_dirs):
        return None
    if not _is_old_file(resolved, cutoff):
        return None
    if not is_log and any(part.casefold() in _PROTECTED_RUNTIME_SUBDIRS for part in resolved.parts):
        return None
    if resolved.name.casefold().endswith((".cancel", ".json.tmp", ".part")):
        return None
    try:
        size = resolved.stat().st_size
    except OSError:
        size = 0
    return CleanupCandidate(path=resolved, size=size, is_log=is_log)


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
        app_logger.log_warning(
            "APP_AUTO_CLEANUP_PARTIAL_FAILED",
            result.summary_detail(),
        )
    else:
        app_logger.log_info("APP_AUTO_CLEANUP_COMPLETED", result.summary_detail())
