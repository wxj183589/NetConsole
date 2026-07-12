from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.ui.logs.log_pagination_engine import LogPage, get_logs as paginate_log_file, iter_logs as iter_paginated_log_file


_paths = PathResolver()
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


def log_info(event: str, detail: str = "") -> None:
    _write_log("INFO", event, detail)


def log_warning(event: str, detail: str = "") -> None:
    _write_log("WARNING", event, detail)


def log_error(event: str, detail: str = "") -> None:
    _write_log("ERROR", event, detail)


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
    return paginate_log_file(log_path or _log_path(), page=page, page_size=page_size, keyword=keyword, level=level, parser=_parse_line)


def iter_logs(keyword: str | None = None, level: str | None = None):
    return iter_paginated_log_file(_log_path(), keyword=keyword, level=level, parser=_parse_line)


def clear_logs() -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def export_logs(target_path: str | Path) -> None:
    source = _log_path()
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source.write_text("", encoding="utf-8")
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def sanitize_detail(detail: object) -> str:
    return _sanitize_detail(detail)


def _write_log(level: str, event: str, detail: str = "") -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_event = _clean_cell(event).upper()
    safe_detail = _sanitize_detail(detail)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{timestamp} | {level} | {safe_event} | {safe_detail}\n")


def _log_path() -> Path:
    return _paths.app_log_path


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
            rf"\1***",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _clean_cell(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace(" | ", " / ").strip()
