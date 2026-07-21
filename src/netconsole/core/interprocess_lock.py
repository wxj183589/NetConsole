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


def _acquire_os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        attempts = 50
        for attempt in range(attempts):
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except OSError as exc:
                if getattr(exc, "errno", None) == errno.EDEADLK and attempt < attempts - 1:
                    time.sleep(0.002)
                    continue
                raise
            return
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def interprocess_file_lock(path: Path) -> Iterator[None]:
    lock_path = Path(path).resolve()
    lock_key = _canonical_lock_key(lock_path)
    state = _register_local_state(lock_key)
    local_lock = state.lock
    local_lock.acquire()
    depths = _thread_depths()
    depth = int(depths.get(lock_key, 0))
    depths[lock_key] = depth + 1
    os_locked = False
    try:
        handle = _os_lock_handle_for(state, lock_path)
        if depth == 0:
            _acquire_os_lock(handle)
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
