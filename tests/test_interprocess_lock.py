from __future__ import annotations

import errno
import os
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import netconsole.core.interprocess_lock as lock_module
from netconsole.core.interprocess_lock import interprocess_file_lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_interprocess_file_lock_serializes_many_threads_and_supports_reentry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "locks" / "app-log.lock"
    guard = threading.Lock()
    os_active = 0
    critical_active = 0
    os_lock_calls = 0
    violations: list[int] = []

    def fake_acquire(_handle) -> None:
        nonlocal os_active, os_lock_calls
        with guard:
            os_active += 1
            os_lock_calls += 1
            if os_active != 1:
                violations.append(-1)

    def fake_release(_handle) -> None:
        nonlocal os_active
        with guard:
            os_active -= 1

    monkeypatch.setattr(lock_module, "_acquire_os_lock", fake_acquire)
    monkeypatch.setattr(lock_module, "_release_os_lock", fake_release)

    def worker(index: int) -> None:
        nonlocal critical_active
        for _ in range(50):
            with interprocess_file_lock(lock_path):
                with interprocess_file_lock(lock_path):
                    with guard:
                        critical_active += 1
                        if critical_active != 1:
                            violations.append(index)
                    time.sleep(0.0001)
                    with guard:
                        critical_active -= 1

    with ThreadPoolExecutor(max_workers=50) as executor:
        list(executor.map(worker, range(50)))

    assert violations == []
    assert os_lock_calls == 50 * 50


def test_interprocess_file_lock_allows_different_paths_to_run_in_parallel(tmp_path: Path) -> None:
    entered = 0
    max_entered = 0
    guard = threading.Lock()
    barrier = threading.Barrier(2)

    def worker(lock_name: str) -> None:
        nonlocal entered, max_entered
        barrier.wait()
        with interprocess_file_lock(tmp_path / f"{lock_name}.lock"):
            with guard:
                entered += 1
                max_entered = max(max_entered, entered)
            time.sleep(0.05)
            with guard:
                entered -= 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, ["left", "right"]))

    assert max_entered == 2


def test_interprocess_file_lock_releases_after_exception(tmp_path: Path) -> None:
    lock_path = tmp_path / "exception.lock"

    try:
        with interprocess_file_lock(lock_path):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with interprocess_file_lock(lock_path):
        assert lock_path.exists()


def test_interprocess_file_lock_can_fail_fast_when_the_local_lock_is_busy(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "timeout.lock"
    entered = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with interprocess_file_lock(lock_path):
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(timeout=1)
    try:
        with pytest.raises(TimeoutError, match="lock timeout"):
            with interprocess_file_lock(lock_path, timeout_seconds=0.02):
                pass
    finally:
        release.set()
        thread.join(timeout=1)
    assert not thread.is_alive()


def test_interprocess_file_lock_nested_windows_lock_calls_os_lock_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    locked = False
    calls: list[str] = []

    def fake_locking(_fileno: int, mode: int, _size: int) -> None:
        nonlocal locked
        if mode == 1:
            calls.append("lock")
            if locked:
                raise OSError(errno.EDEADLK, "Resource deadlock avoided")
            locked = True
            return
        calls.append("unlock")
        locked = False

    fake_msvcrt = types.SimpleNamespace(LK_LOCK=1, LK_UNLCK=2, locking=fake_locking)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(lock_module.os, "name", "nt")

    with interprocess_file_lock(tmp_path / "windows.lock"):
        with interprocess_file_lock(tmp_path / "windows.lock"):
            pass

    assert calls == ["lock", "unlock"]


def test_interprocess_file_lock_blocks_across_processes(tmp_path: Path) -> None:
    lock_path = tmp_path / "process.lock"
    release_path = tmp_path / "release"
    script = """
import sys
import time
from pathlib import Path
from netconsole.core.interprocess_lock import interprocess_file_lock

lock_path = Path(sys.argv[1])
release_path = Path(sys.argv[2])
with interprocess_file_lock(lock_path):
    print("ready", flush=True)
    while not release_path.exists():
        time.sleep(0.02)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not env.get("PYTHONPATH")
        else f"{PROJECT_ROOT}{os.pathsep}{env['PYTHONPATH']}"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path), str(release_path)],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    acquired = threading.Event()
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"

        thread = threading.Thread(
            target=lambda: _acquire_and_signal(lock_path, acquired),
            daemon=True,
        )
        thread.start()
        assert not acquired.wait(0.2)

        release_path.write_text("go", encoding="utf-8")
        assert acquired.wait(3)
        thread.join(timeout=3)
        assert process.wait(timeout=3) == 0
    finally:
        release_path.write_text("go", encoding="utf-8")
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


def _acquire_and_signal(lock_path: Path, acquired: threading.Event) -> None:
    with interprocess_file_lock(lock_path):
        acquired.set()
