from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from netconsole.core.paths import PathResolver
from netconsole.core.version import APP_VERSION


_LOCK_OFFSET = 1024 * 1024


class BackendInstanceInUseError(RuntimeError):
    def __init__(self, data_root: Path, owner: dict[str, object] | None = None) -> None:
        self.data_root = Path(data_root)
        self.owner = dict(owner or {})
        super().__init__(f"{self.data_root} 当前已由另一个 NetConsole Backend 使用。")


class BackendInstanceLock:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.path = paths.locks_dir / "netconsole-backend.lock"
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self.handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            _lock_nonblocking(handle)
        except OSError as exc:
            handle.close()
            raise BackendInstanceInUseError(self.paths.data_root, _read_owner(self.path)) from exc
        try:
            _write_owner(handle, self.paths)
        except Exception:
            _unlock(handle)
            handle.close()
            raise
        self.handle = handle

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        self.handle = None
        try:
            _unlock(handle)
        finally:
            handle.close()

    def __enter__(self) -> BackendInstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def _lock_nonblocking(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(_LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(_LOCK_OFFSET)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_owner(handle: BinaryIO, paths: PathResolver) -> None:
    executable = Path(sys.executable).resolve()
    payload = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": APP_VERSION,
        "executable": str(executable),
        "data_root": str(paths.data_root),
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    handle.seek(0)
    handle.truncate()
    handle.write(encoded)
    handle.flush()
    os.fsync(handle.fileno())
    handle.seek(0)


def _read_owner(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


__all__ = ["BackendInstanceInUseError", "BackendInstanceLock"]
