from __future__ import annotations

import contextvars
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator


@dataclass
class RequestPerformanceProfile:
    request_id: str
    method: str
    path: str
    started_at: float = field(default_factory=perf_counter)
    sql_count: int = 0
    sql_ms: float = 0.0
    repository_ms: float = 0.0
    repository_calls: dict[str, float] = field(default_factory=dict)

    def record_sql(self, elapsed_ms: float) -> None:
        self.sql_count += 1
        self.sql_ms += max(0.0, elapsed_ms)

    def record_repository(self, name: str, elapsed_ms: float) -> None:
        duration = max(0.0, elapsed_ms)
        self.repository_ms += duration
        self.repository_calls[name] = self.repository_calls.get(name, 0.0) + duration


_CURRENT_PROFILE: contextvars.ContextVar[RequestPerformanceProfile | None] = (
    contextvars.ContextVar("netconsole_request_performance_profile", default=None)
)


def begin_request_profile(
    request_id: str,
    method: str,
    path: str,
) -> tuple[RequestPerformanceProfile, contextvars.Token[RequestPerformanceProfile | None]]:
    profile = RequestPerformanceProfile(
        request_id=request_id,
        method=str(method or ""),
        path=str(path or ""),
    )
    return profile, _CURRENT_PROFILE.set(profile)


def end_request_profile(
    token: contextvars.Token[RequestPerformanceProfile | None],
) -> None:
    _CURRENT_PROFILE.reset(token)


def current_request_profile() -> RequestPerformanceProfile | None:
    return _CURRENT_PROFILE.get()


@contextmanager
def profile_repository(name: str) -> Iterator[None]:
    profile = current_request_profile()
    if profile is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        profile.record_repository(name, (perf_counter() - started) * 1000)


class ProfilingCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=(), /):  # type: ignore[no-untyped-def]
        return _profile_sql(super().execute, sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):  # type: ignore[no-untyped-def]
        return _profile_sql(super().executemany, sql, seq_of_parameters)

    def executescript(self, sql_script, /):  # type: ignore[no-untyped-def]
        return _profile_sql(super().executescript, sql_script)


class ProfilingConnection(sqlite3.Connection):
    def cursor(self, factory=ProfilingCursor):  # type: ignore[no-untyped-def]
        return super().cursor(factory)

    def execute(self, sql, parameters=(), /):  # type: ignore[no-untyped-def]
        return _profile_sql(super().execute, sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):  # type: ignore[no-untyped-def]
        return _profile_sql(super().executemany, sql, seq_of_parameters)

    def executescript(self, sql_script, /):  # type: ignore[no-untyped-def]
        return _profile_sql(super().executescript, sql_script)


def _profile_sql(operation, *args):  # type: ignore[no-untyped-def]
    profile = current_request_profile()
    if profile is None:
        return operation(*args)
    started = perf_counter()
    try:
        return operation(*args)
    finally:
        profile.record_sql((perf_counter() - started) * 1000)


__all__ = [
    "ProfilingConnection",
    "RequestPerformanceProfile",
    "begin_request_profile",
    "current_request_profile",
    "end_request_profile",
    "profile_repository",
]
