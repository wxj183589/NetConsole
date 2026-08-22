from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
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
    def __init__(
        self,
        paths: PathResolver,
        *,
        active_site_id: str = "",
        warm_handoff_owner_id: str = "",
    ) -> None:
        self.paths = paths
        self.path = paths.locks_dir / "netconsole-backend.lock"
        self.transition_path = paths.locks_dir / "netconsole-backend-transition.lock"
        self.active_site_id = str(active_site_id or "").strip()
        self.warm_handoff_owner_id = str(warm_handoff_owner_id or "").strip()
        self.handle: BinaryIO | None = None
        self.transition_handle: BinaryIO | None = None
        self.warm_handoff = False
        self._promotion_stop = threading.Event()
        self._promotion_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

    def acquire(self) -> None:
        if self.handle is not None or self.transition_handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        transition = _open_lock_handle(self.transition_path)
        try:
            _lock_nonblocking(transition)
        except OSError as exc:
            transition.close()
            raise BackendInstanceInUseError(self.paths.data_root, _read_owner(self.path)) from exc

        if self.warm_handoff_owner_id:
            owner = _read_owner(self.path)
            if not self._valid_warm_handoff_owner(owner):
                _unlock(transition)
                transition.close()
                raise BackendInstanceInUseError(self.paths.data_root, owner)
            self.transition_handle = transition
            self.warm_handoff = True
            self._start_promotion_monitor()
            return

        handle = _open_lock_handle(self.path)
        try:
            _lock_nonblocking(handle)
            _write_owner(handle, self.paths, self.active_site_id)
        except OSError as exc:
            handle.close()
            _unlock(transition)
            transition.close()
            raise BackendInstanceInUseError(self.paths.data_root, _read_owner(self.path)) from exc
        except Exception:
            _unlock(handle)
            handle.close()
            _unlock(transition)
            transition.close()
            raise
        self.handle = handle
        _unlock(transition)
        transition.close()

    def release(self) -> None:
        self._promotion_stop.set()
        thread = self._promotion_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._state_lock:
            handle = self.handle
            transition = self.transition_handle
            self.handle = None
            self.transition_handle = None
        if handle is not None:
            try:
                _unlock(handle)
            finally:
                handle.close()
        if transition is not None:
            try:
                _unlock(transition)
            finally:
                transition.close()

    def _valid_warm_handoff_owner(self, owner: dict[str, object]) -> bool:
        return bool(
            self.active_site_id
            and self.warm_handoff_owner_id
            and owner.get("instance_id") == self.warm_handoff_owner_id
            and owner.get("active_site_id")
            and owner.get("active_site_id") != self.active_site_id
            and owner.get("data_root") == str(self.paths.data_root)
        )

    def _start_promotion_monitor(self) -> None:
        def promote() -> None:
            while not self._promotion_stop.wait(0.05):
                handle = _open_lock_handle(self.path)
                try:
                    _lock_nonblocking(handle)
                except OSError:
                    handle.close()
                    continue
                try:
                    _write_owner(handle, self.paths, self.active_site_id)
                    with self._state_lock:
                        if self._promotion_stop.is_set():
                            _unlock(handle)
                            handle.close()
                            return
                        self.handle = handle
                        transition = self.transition_handle
                        self.transition_handle = None
                    if transition is not None:
                        _unlock(transition)
                        transition.close()
                    return
                except Exception:
                    _unlock(handle)
                    handle.close()
                    time.sleep(0.05)

        self._promotion_thread = threading.Thread(
            target=promote,
            name="netconsole-backend-lock-promotion",
            daemon=True,
        )
        self._promotion_thread.start()

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


def _open_lock_handle(path: Path) -> BinaryIO:
    handle = path.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    return handle


def _write_owner(handle: BinaryIO, paths: PathResolver, active_site_id: str = "") -> None:
    executable = Path(sys.executable).resolve()
    payload = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": APP_VERSION,
        "executable": str(executable),
        "data_root": str(paths.data_root),
        "instance_id": uuid.uuid4().hex,
        "active_site_id": str(active_site_id or ""),
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
