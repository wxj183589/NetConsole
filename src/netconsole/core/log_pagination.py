from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Callable, Iterable, Iterator

from netconsole.core.pagination import DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, PaginationState
from netconsole.utils.text_encoding import decode_bytes_with_fallback


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
    return get_logs_from_paths(
        [log_path],
        page=page,
        page_size=page_size,
        keyword=keyword,
        level=level,
        parser=parser,
    )


def get_logs_from_paths(
    log_paths: Iterable[Path],
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

    paths = tuple(Path(path) for path in log_paths)
    for log_path in paths:
        if not log_path.exists():
            continue
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
        return get_logs_from_paths(paths, current_page, size, keyword, level, parser)
    return LogPage(
        rows=rows,
        state=PaginationState(
            page_size=size,
            current_page=current_page,
            total_items=total,
            total_pages=total_pages,
        ),
    )


def iter_logs(
    log_path: Path,
    keyword: str | None = None,
    level: str | None = None,
    parser: Callable[[str], dict[str, str] | None] | None = None,
    max_bytes: int | None = None,
) -> Iterator[dict[str, str]]:
    yield from iter_logs_from_paths(
        [log_path],
        keyword=keyword,
        level=level,
        parser=parser,
        max_bytes_by_path={Path(log_path): max_bytes} if max_bytes is not None else None,
    )


def iter_logs_from_paths(
    log_paths: Iterable[Path],
    keyword: str | None = None,
    level: str | None = None,
    parser: Callable[[str], dict[str, str] | None] | None = None,
    max_bytes_by_path: dict[Path, int | None] | None = None,
) -> Iterator[dict[str, str]]:
    keyword_text = keyword.strip().casefold() if keyword else None
    level_text = level.strip().upper() if level else None
    parse = parser or _default_parse_line
    limits = max_bytes_by_path or {}
    for raw_path in log_paths:
        log_path = Path(raw_path)
        if not log_path.exists():
            continue
        for line in _read_lines_reversed(log_path, max_bytes=limits.get(log_path)):
            parsed = parse(line)
            if parsed is None:
                continue
            if level_text and parsed.get("level") != level_text:
                continue
            if keyword_text and keyword_text not in " ".join(parsed.values()).casefold():
                continue
            yield parsed


def _read_lines_reversed(
    path: Path,
    chunk_size: int = 64 * 1024,
    max_bytes: int | None = None,
) -> Iterator[str]:
    with path.open("rb") as file:
        file.seek(0, 2)
        position = file.tell()
        if max_bytes is not None:
            position = min(position, max(0, int(max_bytes)))
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
                    yield decode_bytes_with_fallback(raw_line).text.rstrip("\r\n")
        if buffer:
            yield decode_bytes_with_fallback(buffer).text.rstrip("\r\n")


def _default_parse_line(line: str) -> dict[str, str] | None:
    parts = line.split(" | ", 3)
    if len(parts) != 4:
        return None
    time, level, event, detail = parts
    return {"time": time, "level": level, "event": event, "detail": detail}
