from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Callable, Iterator


_PATH_LOCKS: dict[Path, RLock] = {}
_PATH_LOCKS_GUARD = RLock()


def _path_lock(path: Path) -> RLock:
    resolved = path.resolve(strict=False)
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, RLock())


@contextmanager
def locked_file(path: Path) -> Iterator[None]:
    with _path_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock_file.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    replace: Callable[[Path, Path], None] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        (replace or os.replace)(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


__all__ = ["atomic_write_bytes", "locked_file"]
