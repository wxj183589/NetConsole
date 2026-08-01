from __future__ import annotations

import errno
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_LOCAL_LOCKS_GUARD = threading.Lock()
_THREAD_STATE = threading.local()


@dataclass
class _LocalLockState:
    lock: threading.RLock
    handle: object | None = None
    active_count: int = 0


_LOCAL_STATES: dict[str, _LocalLockState] = {}


def _canonical_lock_key(path: Path) -> str:
    raw_path = os.path.abspath(os.fspath(path))
    if os.name == "nt":
        raw_path = raw_path.replace("/", "\\")
        lower_path = raw_path.lower()
        if lower_path.startswith("\\\\?\\unc\\"):
            raw_path = "\\\\" + raw_path[8:]
        elif lower_path.startswith("\\\\?\\"):
            raw_path = raw_path[4:]
    return os.path.normcase(raw_path)


def _register_local_state(key: str) -> _LocalLockState:
    with _LOCAL_LOCKS_GUARD:
        state = _LOCAL_STATES.get(key)
        if state is None:
            state = _LocalLockState(lock=threading.RLock())
            _LOCAL_STATES[key] = state
        state.active_count += 1
        return state


def _os_lock_handle_for(state: _LocalLockState, path: Path):
    with _LOCAL_LOCKS_GUARD:
        handle = state.handle
        if handle is None or getattr(handle, "closed", False):
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a+b")
            _seed_lock_file(handle)
            state.handle = handle
        else:
            handle.seek(0)
        return handle


def _unregister_local_state(key: str, state: _LocalLockState) -> None:
    handle = None
    with _LOCAL_LOCKS_GUARD:
        remaining = state.active_count - 1
        if remaining > 0:
            state.active_count = remaining
            return
        state.active_count = 0
        handle = state.handle
        state.handle = None
        if _LOCAL_STATES.get(key) is state:
            _LOCAL_STATES.pop(key, None)
    if handle is not None:
        try:
            handle.close()
        except Exception:
            pass


def _thread_depths() -> dict[str, int]:
    depths = getattr(_THREAD_STATE, "depths", None)
    if depths is None:
        depths = {}
        _THREAD_STATE.depths = depths
    return depths


def _seed_lock_file(handle) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)


def _acquire_os_lock(
    handle,
    timeout_seconds: float | None = None,
) -> None:
    deadline = (
        time.monotonic() + max(0.0, float(timeout_seconds))
        if timeout_seconds is not None
        else None
    )
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        mode = msvcrt.LK_NBLCK if deadline is not None else msvcrt.LK_LOCK
        attempts = 50 if deadline is None else None
        attempt = 0
        while True:
            try:
                msvcrt.locking(handle.fileno(), mode, 1)
            except OSError as exc:
                attempt += 1
                retry_deadlock = (
                    deadline is None
                    and getattr(exc, "errno", None) == errno.EDEADLK
                    and attempt < int(attempts or 0)
                )
                retry_busy = (
                    deadline is not None
                    and getattr(exc, "errno", None)
                    in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
                    and time.monotonic() < deadline
                )
                if retry_deadlock:
                    time.sleep(0.002)
                    continue
                if retry_busy:
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
                    continue
                if deadline is not None and getattr(exc, "errno", None) in {
                    errno.EACCES,
                    errno.EAGAIN,
                    errno.EDEADLK,
                }:
                    raise TimeoutError("interprocess lock timeout") from exc
                raise
            return
    import fcntl

    if deadline is None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if (
                getattr(exc, "errno", None) in {errno.EACCES, errno.EAGAIN}
                and time.monotonic() < deadline
            ):
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
                continue
            if getattr(exc, "errno", None) in {errno.EACCES, errno.EAGAIN}:
                raise TimeoutError("interprocess lock timeout") from exc
            raise


def _release_os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def interprocess_file_lock(
    path: Path,
    *,
    timeout_seconds: float | None = None,
) -> Iterator[None]:
    lock_path = Path(path).resolve()
    lock_key = _canonical_lock_key(lock_path)
    state = _register_local_state(lock_key)
    local_lock = state.lock
    started = time.monotonic()
    if timeout_seconds is None:
        local_lock.acquire()
        local_acquired = True
    else:
        local_acquired = local_lock.acquire(
            timeout=max(0.0, float(timeout_seconds))
        )
    if not local_acquired:
        _unregister_local_state(lock_key, state)
        raise TimeoutError("interprocess lock timeout")
    depths = _thread_depths()
    depth = int(depths.get(lock_key, 0))
    depths[lock_key] = depth + 1
    os_locked = False
    try:
        handle = _os_lock_handle_for(state, lock_path)
        if depth == 0:
            if timeout_seconds is None:
                _acquire_os_lock(handle)
            else:
                remaining = max(
                    0.0,
                    float(timeout_seconds) - (time.monotonic() - started),
                )
                _acquire_os_lock(handle, remaining)
            os_locked = True
        try:
            yield
        finally:
            if os_locked:
                _release_os_lock(handle)
    finally:
        next_depth = int(depths.get(lock_key, 0)) - 1
        if next_depth > 0:
            depths[lock_key] = next_depth
        else:
            depths.pop(lock_key, None)
        local_lock.release()
        _unregister_local_state(lock_key, state)


__all__ = ["interprocess_file_lock"]
