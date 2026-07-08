from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Callable, Iterator

from netconsole.ui.pagination import DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, PaginationState


PAGE_SIZE = DEFAULT_PAGE_SIZE
LOG_PAGE_SIZE_OPTIONS = PAGE_SIZE_OPTIONS


@dataclass(frozen=True)
class LogPage:
    rows: list[dict[str, str]]
    state: PaginationState


def get_logs(
    log_path: Path,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    keyword: str | None = None,
    level: str | None = None,
    parser: Callable[[str], dict[str, str] | None] | None = None,
) -> LogPage:
    size = page_size if page_size in LOG_PAGE_SIZE_OPTIONS else PAGE_SIZE
    requested_page = max(int(page or 1), 1)
    offset = (requested_page - 1) * size
    keyword_text = keyword.strip().casefold() if keyword else None
    level_text = level.strip().upper() if level else None
    parse = parser or _default_parse_line
    rows: list[dict[str, str]] = []
    total = 0

    if log_path.exists():
        for line in _read_lines_reversed(log_path):
            parsed = parse(line)
            if parsed is None:
                continue
            if level_text and parsed.get("level") != level_text:
                continue
            if keyword_text and keyword_text not in " ".join(parsed.values()).casefold():
                continue
            if offset <= total < offset + size:
                rows.append(parsed)
            total += 1

    total_pages = max(ceil(total / size), 1)
    current_page = min(requested_page, total_pages)
    if current_page != requested_page:
        return get_logs(log_path, current_page, size, keyword, level, parser)
    return LogPage(rows=rows, state=PaginationState(page_size=size, current_page=current_page, total_items=total, total_pages=total_pages))


def iter_logs(
    log_path: Path,
    keyword: str | None = None,
    level: str | None = None,
    parser: Callable[[str], dict[str, str] | None] | None = None,
) -> Iterator[dict[str, str]]:
    keyword_text = keyword.strip().casefold() if keyword else None
    level_text = level.strip().upper() if level else None
    parse = parser or _default_parse_line
    if not log_path.exists():
        return
    for line in _read_lines_reversed(log_path):
        parsed = parse(line)
        if parsed is None:
            continue
        if level_text and parsed.get("level") != level_text:
            continue
        if keyword_text and keyword_text not in " ".join(parsed.values()).casefold():
            continue
        yield parsed


def _read_lines_reversed(path: Path, chunk_size: int = 64 * 1024) -> Iterator[str]:
    with path.open("rb") as file:
        file.seek(0, 2)
        position = file.tell()
        buffer = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            file.seek(position)
            chunk = file.read(read_size)
            parts = (chunk + buffer).split(b"\n")
            buffer = parts[0]
            for raw_line in reversed(parts[1:]):
                if raw_line:
                    yield raw_line.decode("utf-8", errors="replace").rstrip("\r")
        if buffer:
            yield buffer.decode("utf-8", errors="replace").rstrip("\r")


def _default_parse_line(line: str) -> dict[str, str] | None:
    parts = line.split(" | ", 3)
    if len(parts) != 4:
        return None
    time, level, event, detail = parts
    return {"time": time, "level": level, "event": event, "detail": detail}
