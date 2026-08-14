from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, deque
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PLAN_PATH = "/api/rail-transit/trackside-ap-business/plan"
HEALTH_PATH = "/api/health"
COMPANION_PATHS = (
    "/api/rail-transit/base-data/stations?page=1&page_size=200",
    "/api/rail-transit/base-data/sections?page=1&page_size=200",
    "/api/rail-transit/base-data/issues/groups?page=1&page_size=200",
)
SESSION_HEADER = "x-netconsole-session"
TEST_DATA_ROOT = Path(r"D:\study\test-data\NetConsole")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在显式设备数据库副本和 TEST 数据根中稳定性验证轨旁 AP 规划 GET 接口",
    )
    parser.add_argument(
        "--database-copy",
        type=Path,
        required=True,
        help="现有 devices.db 副本；不得指向 sites/<site>/db/devices.db 正式布局",
    )
    parser.add_argument(
        "--test-root",
        type=Path,
        required=True,
        help=r"新的隔离 TEST 数据根（Windows 必须位于 D:\study\test-data\NetConsole\<run-id>）",
    )
    parser.add_argument("--site", default="demo")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--with-companions",
        action="store_true",
        help="每轮额外并发请求站点、区间和数据质量接口",
    )
    parser.add_argument("--json-output", type=Path)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_formal_site_database(path: Path) -> bool:
    parts = [item.casefold() for item in path.parts]
    return (
        len(parts) >= 5
        and parts[-1] == "devices.db"
        and parts[-2] == "db"
        and parts[-4] == "sites"
        and parts[-3] != ""
    )


def _validate_paths(source: Path, test_root: Path) -> tuple[Path, Path]:
    source = source.resolve(strict=True)
    test_root = test_root.resolve()
    if not source.is_file() or source.name.casefold() != "devices.db":
        raise ValueError("--database-copy 必须指向现有 devices.db 副本")
    if _is_formal_site_database(source):
        raise ValueError(
            "--database-copy 不能直接指向正式 sites/<site>/db/devices.db；"
            "请先制作隔离数据库副本"
        )
    if test_root.exists():
        raise ValueError("--test-root 必须是尚不存在的新 TEST 数据根，脚本不会覆盖已有目录")
    if not test_root.is_absolute():
        raise ValueError("--test-root 必须是绝对路径")
    if os.name == "nt":
        allowed = TEST_DATA_ROOT.resolve()
        if test_root == allowed or not test_root.is_relative_to(allowed):
            raise ValueError(r"--test-root 必须位于 D:\study\test-data\NetConsole\<run-id>，且不能直接使用测试根")
    if source == test_root or test_root in source.parents:
        raise ValueError("--test-root 与 --database-copy 不能重叠")
    return source, test_root


def _prepare_copy(source: Path, test_root: Path, site: str) -> Path:
    target = test_root / "sites" / site / "db" / "devices.db"
    target.parent.mkdir(parents=True, exist_ok=False)
    test_root.joinpath("config").mkdir(parents=True, exist_ok=True)
    test_root.joinpath("config", "application.json").write_text(
        json.dumps({"current_site": site}, ensure_ascii=False),
        encoding="utf-8",
    )
    test_root.joinpath("sites", site, "site_meta.json").write_text(
        json.dumps(
            {
                "name": site,
                "base_data_write_scope": "copy_validation",
                "base_data_source_sha256": _sha256(source),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    shutil.copy2(source, target)
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, target.with_name(target.name + suffix))
    return target


def _reader(stream, output: queue.Queue[str], tail: deque[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            line = line.rstrip("\r\n")
            tail.append(line)
            output.put(line)
    finally:
        output.put("")


def _start_backend(test_root: Path, site: str, timeout: float):
    token = uuid.uuid4().hex + uuid.uuid4().hex
    environment = os.environ.copy()
    environment.update(
        {
            "NETCONSOLE_DATA_ROOT": str(test_root),
            "NETCONSOLE_RUNTIME_MODE": "test",
            "NETCONSOLE_STORAGE_MODE": "isolated_test",
            "NETCONSOLE_ACTIVE_SITE_ID": site,
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    source_root = str(Path(__file__).resolve().parents[2] / "src")
    existing_python_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        source_root
        if not existing_python_path
        else source_root + os.pathsep + existing_python_path
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "netconsole.entrypoint",
            "--electron-backend",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--dev-mode",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdin is not None
    process.stdin.write(json.dumps({"session_token": token}) + "\n")
    process.stdin.flush()
    output: queue.Queue[str] = queue.Queue()
    stderr_output: queue.Queue[str] = queue.Queue()
    stderr_tail: deque[str] = deque(maxlen=200)
    assert process.stdout is not None and process.stderr is not None
    threading.Thread(target=_reader, args=(process.stdout, output, deque(maxlen=200)), daemon=True).start()
    threading.Thread(target=_reader, args=(process.stderr, stderr_output, stderr_tail), daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = output.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Backend 在握手前退出 code={process.returncode} stderr={list(stderr_tail)[-20:]}"
                )
            continue
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "netconsole.electron_backend.listening":
            return process, token, f"http://127.0.0.1:{int(payload['port'])}", stderr_tail
        if payload.get("event") == "netconsole.electron_backend.startup_failed":
            raise RuntimeError(f"Backend 启动失败：{payload.get('message', '')}")
    raise TimeoutError("等待 Backend 握手超时")


def _request(base_url: str, token: str, path: str, timeout: float) -> dict[str, object]:
    request = Request(
        f"{base_url}{path}",
        headers={SESSION_HEADER: token, "Cache-Control": "no-store"},
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            return {
                "path": path,
                "status": int(response.status),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "backend_pid": response.headers.get("X-NetConsole-Backend-PID", ""),
                "request_id": response.headers.get("X-Request-ID", ""),
                "rows": (json.loads(body.decode("utf-8")).get("total") if body else None),
            }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "path": path,
            "status": int(exc.code),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_type": "HTTPError",
            "error": body[:1000],
        }
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError, URLError) as exc:
        reason = getattr(exc, "reason", exc)
        return {
            "path": path,
            "status": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_type": exc.__class__.__name__,
            "error": str(reason)[:1000],
        }


def _stop_backend(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if process.stdin is not None:
        try:
            process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
            process.stdin.flush()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"command": "exit"}) + "\n")
                process.stdin.flush()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=3)


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.count < 1 or args.count > 10_000:
        raise ValueError("--count 必须在 1～10000 之间")
    if args.concurrency < 1 or args.concurrency > 32:
        raise ValueError("--concurrency 必须在 1～32 之间")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds 必须大于 0")
    source, test_root = _validate_paths(args.database_copy, args.test_root)
    source_hash = _sha256(source)
    source_mtime_ns = source.stat().st_mtime_ns
    copied = _prepare_copy(source, test_root, args.site)
    process = None
    records: list[dict[str, object]] = []
    stderr_tail: deque[str] = deque(maxlen=200)
    try:
        process, token, base_url, stderr_tail = _start_backend(
            test_root,
            args.site,
            max(args.timeout_seconds, 10.0),
        )
        health = _request(base_url, token, HEALTH_PATH, args.timeout_seconds)
        if health.get("status") != 200:
            raise RuntimeError(f"Backend 健康检查失败：{health}")
        paths = [PLAN_PATH] + (list(COMPANION_PATHS) if args.with_companions else [])
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            for index in range(args.count):
                futures = [
                    executor.submit(_request, base_url, token, path, args.timeout_seconds)
                    for path in paths
                ]
                for future in futures:
                    item = future.result()
                    item["iteration"] = index + 1
                    records.append(item)
    finally:
        if process is not None:
            _stop_backend(process)
    source_unchanged = _sha256(source) == source_hash and source.stat().st_mtime_ns == source_mtime_ns
    status_counts = Counter(str(item.get("status")) for item in records)
    connection_errors = [
        item for item in records if item.get("status") is None
    ]
    http_errors = [
        item for item in records if isinstance(item.get("status"), int) and int(item["status"]) >= 400
    ]
    observed_pids = sorted(
        {
            str(item["backend_pid"])
            for item in records
            if str(item.get("backend_pid") or "").strip()
        }
    )
    stable_backend_pid = observed_pids[0] if len(observed_pids) == 1 else None
    pid_changed = len(observed_pids) > 1
    result = {
        "database_copy": str(source),
        "copied_database": str(copied),
        "test_root": str(test_root),
        "requested_count": args.count,
        "concurrency": args.concurrency,
        "with_companions": bool(args.with_companions),
        "status_counts": dict(status_counts),
        "connection_error_count": len(connection_errors),
        "http_error_count": len(http_errors),
        "launcher_pid": process.pid if process is not None else None,
        "backend_pid": stable_backend_pid,
        "observed_response_pids": observed_pids,
        "pid_changed": pid_changed,
        "source_sha256": source_hash,
        "source_unchanged": source_unchanged,
        "stderr_tail": list(stderr_tail)[-200:],
        "records": records,
        "passed": (
            source_unchanged
            and not connection_errors
            and not http_errors
            and stable_backend_pid is not None
            and not pid_changed
        ),
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"轨旁 AP 规划接口稳定性验证失败：{exc}")
        return 2
    print(
        "轨旁 AP 规划接口稳定性验证："
        f"请求 {len(result['records'])} 次，"
        f"HTTP 错误 {result['http_error_count']}，"
        f"连接错误 {result['connection_error_count']}，"
        f"PID 变化={'是' if result['pid_changed'] else '否'}，"
        f"源库未变化={'是' if result['source_unchanged'] else '否'}"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
