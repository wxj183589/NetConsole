from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Literal

from netconsole.core.log_policy import LOG_POLICY
from netconsole.core.paths import PathResolver


LogCategory = Literal["electron", "app", "wps", "diagnostic", "archive"]

_ELECTRON_ROTATED = re.compile(r"^electron-\d{8}-\d{6}-\d{4}\.log$", re.IGNORECASE)
_APP_ROTATED = re.compile(
    r"^(?:app-\d{8}-\d{6}-\d{4}\.log|app_[^/]+\.log|app\.log\.[^/]+)$",
    re.IGNORECASE,
)
_WPS_LOG = re.compile(r"^wps-.+\.(?:stdout|stderr)\.log$", re.IGNORECASE)
_STARTUP_ROTATED = re.compile(r"^startup_error-.+\.log$", re.IGNORECASE)
_FAULT_ROTATED = re.compile(r"^(?:faulthandler|crash)-.+\.log$", re.IGNORECASE)
_DIAGNOSTIC_LOG = re.compile(
    r"^(?:electron-log-fallback|netconsole_.+|runtime_.+|ui_.+|backend_.+|renderer_.+)\.log$",
    re.IGNORECASE,
)
_PROTECTED_NAMES = frozenset(
    {
        "electron.log",
        "app.log",
        "startup_error.log",
        "faulthandler.log",
        "database_upgrade_audit.jsonl",
    }
)
_CATEGORY_PRIORITY: dict[LogCategory, int] = {
    "electron": 1,
    "app": 2,
    "wps": 3,
    "diagnostic": 4,
    "archive": 5,
}


@dataclass(frozen=True)
class LogHousekeepingCandidate:
    path: Path
    size: int
    modified_at: datetime
    category: LogCategory
    reason: Literal["retention", "capacity"]


@dataclass(frozen=True)
class LogHousekeepingScan:
    total_bytes: int
    candidates: tuple[LogHousekeepingCandidate, ...]
    protected_files: tuple[Path, ...]


@dataclass
class LogHousekeepingResult:
    total_bytes_before: int
    total_bytes_after: int
    deleted_files: int = 0
    freed_bytes: int = 0
    failures: list[tuple[Path, str]] | None = None

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []


class LogHousekeeper:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.root = paths.logs_dir.resolve()

    def scan(
        self,
        *,
        now: datetime | None = None,
        application_retention_days: int | None = None,
    ) -> LogHousekeepingScan:
        current = now or datetime.now()
        application_days = max(
            1,
            int(application_retention_days or LOG_POLICY.backend.retention_days),
        )
        files: list[tuple[Path, int, datetime, LogCategory | None, bool]] = []
        protected: list[Path] = []
        total_bytes = 0
        if not self.root.is_dir():
            return LogHousekeepingScan(0, (), ())
        for item in self.root.rglob("*"):
            if item.is_symlink():
                protected.append(item)
                continue
            resolved = _safe_resolve(item)
            if resolved is None or not resolved.is_file() or not resolved.is_relative_to(self.root):
                continue
            try:
                metadata = resolved.stat()
            except OSError:
                continue
            total_bytes += metadata.st_size
            category, is_protected = self._classify(resolved, current)
            if is_protected:
                protected.append(resolved)
            files.append(
                (
                    resolved,
                    metadata.st_size,
                    datetime.fromtimestamp(metadata.st_mtime),
                    category,
                    is_protected,
                )
            )

        candidates: dict[Path, LogHousekeepingCandidate] = {}
        for path, size, modified_at, category, is_protected in files:
            if category is None or is_protected:
                continue
            retention_days = self._retention_days(category, path, application_days)
            if modified_at < current - timedelta(days=retention_days):
                candidates[path] = LogHousekeepingCandidate(
                    path, size, modified_at, category, "retention"
                )

        projected_total = total_bytes - sum(candidate.size for candidate in candidates.values())
        if projected_total > LOG_POLICY.housekeeper.max_total_bytes:
            available = sorted(
                (
                    (path, size, modified_at, category)
                    for path, size, modified_at, category, is_protected in files
                    if category is not None and not is_protected and path not in candidates
                ),
                key=lambda item: (_CATEGORY_PRIORITY[item[3]], item[2], item[0].name.casefold()),
            )
            for path, size, modified_at, category in available:
                candidates[path] = LogHousekeepingCandidate(
                    path, size, modified_at, category, "capacity"
                )
                projected_total -= size
                if projected_total <= LOG_POLICY.housekeeper.target_total_bytes:
                    break

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                0 if item.reason == "retention" else 1,
                _CATEGORY_PRIORITY[item.category],
                item.modified_at,
                item.path.name.casefold(),
            ),
        )
        return LogHousekeepingScan(total_bytes, tuple(ordered), tuple(sorted(protected)))

    def clean(
        self,
        *,
        now: datetime | None = None,
        application_retention_days: int | None = None,
        selected_paths: Iterable[Path] | None = None,
        should_cancel: Callable[[], None] | None = None,
        progress_callback: Callable[[int, int, LogHousekeepingResult], None] | None = None,
    ) -> LogHousekeepingResult:
        scan = self.scan(
            now=now,
            application_retention_days=application_retention_days,
        )
        selected = (
            {_safe_resolve(path) for path in selected_paths}
            if selected_paths is not None
            else None
        )
        candidates = [
            candidate
            for candidate in scan.candidates
            if selected is None or candidate.path in selected
        ]
        result = LogHousekeepingResult(scan.total_bytes, scan.total_bytes)
        for index, candidate in enumerate(candidates, start=1):
            if should_cancel is not None:
                should_cancel()
            try:
                size = candidate.path.stat().st_size
                candidate.path.unlink()
                result.deleted_files += 1
                result.freed_bytes += size
                result.total_bytes_after = max(0, result.total_bytes_after - size)
            except OSError as exc:
                assert result.failures is not None
                result.failures.append((candidate.path, str(exc)))
            if progress_callback is not None:
                progress_callback(index, len(candidates), result)
        return result

    def _classify(self, path: Path, now: datetime) -> tuple[LogCategory | None, bool]:
        name = path.name.casefold()
        if name in _PROTECTED_NAMES:
            return None, True
        if _ELECTRON_ROTATED.fullmatch(name):
            return "electron", False
        if _APP_ROTATED.fullmatch(name):
            return "app", False
        if _WPS_LOG.fullmatch(name):
            # A recently modified external stdout/stderr file may still be owned by WPS.
            try:
                active = datetime.fromtimestamp(path.stat().st_mtime) > now - timedelta(minutes=5)
            except OSError:
                active = True
            return "wps", active
        if _STARTUP_ROTATED.fullmatch(name) or _FAULT_ROTATED.fullmatch(name):
            return "diagnostic", False
        if _DIAGNOSTIC_LOG.fullmatch(name):
            return "diagnostic", False
        if "archive" in {part.casefold() for part in path.relative_to(self.root).parts[:-1]} and path.suffix.casefold() == ".log":
            return "archive", False
        return None, False

    @staticmethod
    def _retention_days(category: LogCategory, path: Path, application_days: int) -> int:
        name = path.name.casefold()
        if category == "wps":
            return LOG_POLICY.wps.retention_days
        if name.startswith("startup_error-"):
            return LOG_POLICY.startup_error.retention_days
        if name.startswith(("faulthandler-", "crash-")):
            return LOG_POLICY.faulthandler.retention_days
        if category in {"electron", "app", "diagnostic"}:
            return application_days
        return LOG_POLICY.backend.retention_days


def _safe_resolve(path: Path) -> Path | None:
    try:
        return Path(path).resolve()
    except OSError:
        return None
