from __future__ import annotations

import re
import shutil
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Iterator

from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.core.paths import PathResolver
from netconsole.core.log_pagination import (
    LogPage,
    get_logs_from_paths,
    iter_logs_from_paths,
)


_paths = PathResolver()
APP_LOG_MAX_BYTES = 25 * 1024 * 1024
_ROTATED_LOG_PATTERN = "app-*.log"
_LOG_FAILURE_GUARD = threading.Lock()
_LOG_FAILURE_COUNT = 0
_SENSITIVE_KEYS = (
    "password",
    "ssh_password",
    "telnet_password",
    "snmpv3_auth_password",
    "snmpv3_priv_password",
    "密码",
    "认证密码",
    "加密密码",
    "密码",
    "认证密码",
    "加密密码",
)


def configure_path_resolver(paths: PathResolver) -> None:
    global _paths
    _paths = paths


def log_info(event: str, detail: str = "", *, log_path: Path | None = None) -> None:
    _write_log("INFO", event, detail, log_path=log_path)


def log_warning(event: str, detail: str = "", *, log_path: Path | None = None) -> None:
    _write_log("WARNING", event, detail, log_path=log_path)


def log_error(event: str, detail: str = "", *, log_path: Path | None = None) -> None:
    _write_log("ERROR", event, detail, log_path=log_path)


def log_debug(event: str, detail: str = "", *, log_path: Path | None = None) -> None:
    _write_log("DEBUG", event, detail, log_path=log_path)


def read_logs(keyword: str | None = None, level: str | None = None) -> list[dict[str, str]]:
    return get_logs(1, 1000, keyword, level).rows


def get_logs(
    page: int = 1,
    page_size: int = 200,
    keyword: str | None = None,
    level: str | None = None,
    *,
    log_path: Path | None = None,
) -> LogPage:
    path = log_path or _log_path()
    return get_logs_from_paths(
        log_files(path),
        page=page,
        page_size=page_size,
        keyword=keyword,
        level=level,
        parser=_parse_line,
    )


def iter_logs(keyword: str | None = None, level: str | None = None) -> Iterator[dict[str, str]]:
    path = _log_path()
    return iter_logs_from_paths(log_files(path), keyword=keyword, level=level, parser=_parse_line)


def clear_logs(log_path: Path | None = None) -> None:
    path = (log_path or _log_path()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with interprocess_file_lock(log_lock_path(path)):
        for rotated in log_files(path):
            if rotated == path:
                continue
            rotated.unlink(missing_ok=True)
        path.write_text("", encoding="utf-8")


def export_logs(target_path: str | Path) -> None:
    source = _log_path()
    source.parent.mkdir(parents=True, exist_ok=True)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with interprocess_file_lock(log_lock_path(source)):
        if not source.exists():
            source.write_text("", encoding="utf-8")
        with target.open("wb") as output:
            for item in reversed(log_files(source)):
                with item.open("rb") as current:
                    shutil.copyfileobj(current, output)


def sanitize_detail(detail: object) -> str:
    return _sanitize_detail(detail)


def _write_log(level: str, event: str, detail: str = "", *, log_path: Path | None = None) -> None:
    path = log_path or _log_path()
    safe_event = ""
    safe_detail = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        safe_event = _clean_cell(event).upper()
        safe_detail = _sanitize_detail(detail)
        line = f"{timestamp} | {level} | {safe_event} | {safe_detail}\n"
        with interprocess_file_lock(log_lock_path(path)):
            _rotate_if_needed(path, now, len(line.encode("utf-8")))
            with path.open("a", encoding="utf-8") as file:
                file.write(line)
    except Exception as exc:
        _report_log_write_failure(level, safe_event or event, safe_detail or detail, path, exc)


def _log_path() -> Path:
    return _paths.app_log_path


def log_lock_path(path: Path) -> Path:
    return path.resolve().parent.parent / "locks" / "app-log.lock"


def log_files(path: Path | None = None) -> list[Path]:
    active = (path or _log_path()).resolve()
    rotated = [item.resolve() for item in active.parent.glob(_ROTATED_LOG_PATTERN) if item.is_file()]
    rotated.sort(key=lambda item: item.name, reverse=True)
    return ([active] if active.is_file() else []) + [item for item in rotated if item != active]


def _rotate_if_needed(path: Path, now: datetime, incoming_bytes: int) -> None:
    if not path.is_file():
        return
    try:
        stat = path.stat()
        changed_date = datetime.fromtimestamp(stat.st_mtime).date()
    except OSError:
        return
    if stat.st_size + incoming_bytes <= APP_LOG_MAX_BYTES and changed_date == now.date():
        return
    stamp = now.strftime("%Y%m%d-%H%M%S")
    for sequence in range(1, 10_000):
        rotated = path.with_name(f"app-{stamp}-{sequence:04d}.log")
        if rotated.exists():
            continue
        try:
            path.replace(rotated)
        except OSError:
            return
        return


def _report_log_write_failure(
    level: str,
    event: object,
    detail: object,
    path: Path,
    exc: Exception,
) -> None:
    global _LOG_FAILURE_COUNT
    with _LOG_FAILURE_GUARD:
        _LOG_FAILURE_COUNT += 1
        count = _LOG_FAILURE_COUNT
    try:
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        trace = f"{type(exc).__name__}: {exc}"
    message = _sanitize_detail(
        "log_write_failed "
        f"count={count} level={level} event={event} path={path} detail={detail} "
        f"error_type={type(exc).__name__} error={exc} traceback={trace}"
    )
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _parse_line(line: str) -> dict[str, str] | None:
    parts = line.split(" | ", 3)
    if len(parts) != 4:
        return None
    time, level, event, detail = parts
    return {"time": time, "level": level, "event": event, "detail": detail}


def _sanitize_detail(detail: object) -> str:
    text = _clean_cell(str(detail or ""))
    for key in sorted(_SENSITIVE_KEYS, key=len, reverse=True):
        text = re.sub(
            rf"({re.escape(key)}\s*[:=]\s*)[^,;|\s]+",
            r"\1***",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _clean_cell(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace(" | ", " / ").strip()
