from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status


@contextmanager
def map_api_errors(
    database_detail: str,
    *,
    io_detail: str | None = None,
    io_errors: tuple[type[BaseException], ...] = (OSError,),
    io_status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
) -> Iterator[None]:
    try:
        yield
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=database_detail,
        ) from exc
    except io_errors as exc:
        if io_detail is None:
            raise
        raise HTTPException(status_code=io_status_code, detail=io_detail) from exc


__all__ = ["map_api_errors"]
