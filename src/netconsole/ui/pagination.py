from __future__ import annotations

from dataclasses import dataclass
from math import ceil


DEFAULT_PAGE_SIZE = 200
PAGE_SIZE_OPTIONS = (200, 500, 1000)


@dataclass(frozen=True)
class PaginationState:
    page_size: int = DEFAULT_PAGE_SIZE
    current_page: int = 1
    total_items: int = 0
    total_pages: int = 1


def paginate_rows(rows: list[dict[str, object | None]], page_size: int = DEFAULT_PAGE_SIZE, current_page: int = 1) -> tuple[list[dict[str, object | None]], PaginationState]:
    size = page_size if page_size in PAGE_SIZE_OPTIONS else DEFAULT_PAGE_SIZE
    total_items = len(rows)
    total_pages = max(ceil(total_items / size), 1)
    page = min(max(int(current_page or 1), 1), total_pages)
    start = (page - 1) * size
    end = start + size
    return rows[start:end], PaginationState(page_size=size, current_page=page, total_items=total_items, total_pages=total_pages)
