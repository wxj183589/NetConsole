from __future__ import annotations

import sqlite3
import traceback
import uuid
from collections.abc import Iterator
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import TypeAlias

from fastapi import HTTPException, status


DatabaseErrorContext: TypeAlias = (
    Mapping[str, object] | Callable[[], Mapping[str, object]]
)

_DATABASE_ERROR_MESSAGES = {
    "DEVICE_DATABASE_SCHEMA_NOT_READY": (
        "设备数据库升级未完成，请重启后端或查看数据库迁移日志。"
    ),
    "DEVICE_DATABASE_BUSY": "设备数据库正在被占用，请稍后重试。",
    "DEVICE_DATABASE_ACCESS_DENIED": (
        "设备数据库无法访问，请检查数据目录权限和磁盘状态。"
    ),
    "DEVICE_DATABASE_INTEGRITY_ERROR": (
        "设备数据库完整性检查失败，原数据库未被自动修改，请使用迁移备份恢复。"
    ),
    "DEVICE_DATABASE_IO_ERROR": (
        "设备数据库读写失败，请检查磁盘空间和数据目录。"
    ),
    "DEVICE_DATABASE_UNAVAILABLE": (
        "设备数据库暂时不可读，请查看后端日志。"
    ),
}


@contextmanager
def map_api_errors(
    database_detail: str,
    *,
    io_detail: str | None = None,
    io_errors: tuple[type[BaseException], ...] = (OSError,),
    io_status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
    structured_database_errors: bool = False,
    database_context: DatabaseErrorContext | None = None,
) -> Iterator[None]:
    try:
        yield
    except sqlite3.Error as exc:
        if structured_database_errors:
            context = _resolve_database_context(database_context)
            request_id = str(context.get("request_id") or uuid.uuid4().hex)
            context["request_id"] = request_id
            code = classify_sqlite_error(exc)
            _log_sqlite_error(exc, code, context)
            public_details = {
                key: context[key]
                for key in ("operation", "site", "request_id")
                if context.get(key) not in {None, ""}
            }
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": code,
                    "message": _DATABASE_ERROR_MESSAGES[code],
                    "details": public_details,
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=database_detail,
        ) from exc
    except io_errors as exc:
        if io_detail is None:
            raise
        raise HTTPException(status_code=io_status_code, detail=io_detail) from exc


def classify_sqlite_error(exc: sqlite3.Error) -> str:
    message = str(exc).casefold()
    error_code = getattr(exc, "sqlite_errorcode", None)
    primary_code = int(error_code) & 0xFF if isinstance(error_code, int) else None
    error_name = str(getattr(exc, "sqlite_errorname", "") or "").upper()

    if any(
        marker in message
        for marker in (
            "no such column",
            "no such table",
            "has no column named",
            "schema mismatch",
        )
    ):
        return "DEVICE_DATABASE_SCHEMA_NOT_READY"
    if primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or any(
        marker in message for marker in ("database is locked", "database is busy")
    ):
        return "DEVICE_DATABASE_BUSY"
    if primary_code in {
        sqlite3.SQLITE_AUTH,
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_PERM,
        sqlite3.SQLITE_READONLY,
    } or any(
        marker in message
        for marker in (
            "attempt to write a readonly database",
            "permission denied",
            "unable to open database file",
        )
    ):
        return "DEVICE_DATABASE_ACCESS_DENIED"
    if primary_code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB} or any(
        marker in message
        for marker in (
            "database disk image is malformed",
            "file is not a database",
            "not a database",
            "integrity check",
            "完整性校验失败",
        )
    ):
        return "DEVICE_DATABASE_INTEGRITY_ERROR"
    if (
        primary_code in {sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR}
        or error_name.startswith("SQLITE_IOERR")
        or any(
            marker in message
            for marker in ("disk i/o error", "database or disk is full", "disk full")
        )
    ):
        return "DEVICE_DATABASE_IO_ERROR"
    return "DEVICE_DATABASE_UNAVAILABLE"


def _resolve_database_context(
    provider: DatabaseErrorContext | None,
) -> dict[str, object]:
    if provider is None:
        return {}
    try:
        value = provider() if callable(provider) else provider
        return dict(value)
    except Exception as exc:
        return {"diagnostic_error": exc.__class__.__name__}


def _log_sqlite_error(
    exc: sqlite3.Error,
    classification: str,
    context: Mapping[str, object],
) -> None:
    try:
        from netconsole.core import app_logger

        values = {
            "request_id": context.get("request_id", ""),
            "operation": context.get("operation", ""),
            "route": context.get("route", ""),
            "site": context.get("site", ""),
            "database_path": context.get("database_path", ""),
            "exception_class": exc.__class__.__name__,
            "sqlite_errorcode": getattr(exc, "sqlite_errorcode", ""),
            "sqlite_errorname": getattr(exc, "sqlite_errorname", ""),
            "error": str(exc),
            "schema_version": context.get("schema_version", ""),
            "missing_columns": _list_text(context.get("missing_columns")),
            "missing_indexes": _list_text(context.get("missing_indexes")),
            "migration_stage": context.get("migration_stage", "repository_query"),
            "classification": classification,
            "diagnostic_error": context.get("diagnostic_error", ""),
            "traceback": traceback.format_exc(),
        }
        app_logger.log_error(
            "DEVICE_DATABASE_QUERY_FAILED",
            " ".join(f"{key}={value}" for key, value in values.items()),
        )
    except Exception:
        pass


def _list_text(value: object) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(str(item) for item in value) or "<none>"
    return str(value or "<none>")


__all__ = ["classify_sqlite_error", "map_api_errors"]
