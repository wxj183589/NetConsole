from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class XlsxColumn:
    header: str
    field: str
    width: float = 12.0
    max_width: float = 60.0
    text: bool = False
    wrap: bool = False


def display_width(value: object, *, limit: int = 160) -> int:
    text = str(value or "")
    width = 0
    for char in text[:limit]:
        width += 2 if ord(char) > 127 else 1
    return width


def estimate_excel_width(
    value: object,
    *,
    minimum: float = 10.0,
    maximum: float = 60.0,
    padding: float = 2.0,
) -> float:
    return min(max(display_width(value) + padding, minimum), maximum)


def fixed_or_sampled_width(
    current_width: float,
    value: object,
    *,
    minimum: float = 10.0,
    maximum: float = 60.0,
) -> float:
    return max(current_width, estimate_excel_width(value, minimum=minimum, maximum=maximum))


def excel_column_name(index: int) -> str:
    if index < 1:
        raise ValueError("Excel column index starts at 1")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def sheet_range(column_count: int, row_count: int) -> str:
    return f"A1:{excel_column_name(max(column_count, 1))}{max(row_count, 1)}"


def write_row(
    worksheet,
    row_index: int,
    values: Iterable[Any],
    *,
    default_format=None,
    column_formats: dict[int, object] | None = None,
) -> None:
    formats = column_formats or {}
    for column_index, value in enumerate(values):
        worksheet.write(row_index, column_index, value, formats.get(column_index, default_format))
