from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterator

from netconsole.core.shutdown_manager import shutdown_manager
from netconsole.core.ping.fping_v5_models import FpingV5CheckResult, FpingV5Paths, FpingV5Sample
from netconsole.core.ping.fping_v5_parser import parse_fping_v5_json_line
from netconsole.core.paths import PathResolver
from netconsole.services.tool_path_resolver import resolve_network_tool


def resolve_fping_v5_paths(project_root: Path | None = None, fping_path: Path | None = None) -> FpingV5Paths:
    if fping_path is not None:
        exe = Path(fping_path).resolve()
    elif project_root is not None:
        paths = PathResolver(Path(project_root).resolve())
        resolution = resolve_network_tool("fping", paths, project_root=Path(project_root))
        if resolution.effective_path is None:
            raise FileNotFoundError(resolution.validation_message)
        exe = resolution.effective_path
    else:
        paths = PathResolver()
        resolution = resolve_network_tool("fping", paths)
        if resolution.effective_path is None:
            raise FileNotFoundError(resolution.validation_message)
        exe = resolution.effective_path
    exe = exe.resolve()
    dll = exe.parent / "cygwin1.dll"
    if not exe.exists():
        raise FileNotFoundError(f"fping v5 executable was not found: {exe}")
    if not dll.exists():
        raise FileNotFoundError(f"fping v5 Cygwin runtime was not found: {dll}")
    return FpingV5Paths(exe, dll)


def check_fping_v5_available(project_root: Path | None = None, fping_path: Path | None = None) -> FpingV5CheckResult:
    try:
        paths = resolve_fping_v5_paths(project_root, fping_path)
        version = subprocess.run([str(paths.fping_path), "-v"], cwd=paths.fping_path.parent, capture_output=True, text=True, timeout=5)
        help_result = subprocess.run([str(paths.fping_path), "-h"], cwd=paths.fping_path.parent, capture_output=True, text=True, timeout=5)
    except Exception as exc:
        return FpingV5CheckResult(False, str(fping_path or ""), error=str(exc))
    version_output = _combined_output(version)
    help_output = _combined_output(help_result)
    json_supported = "-J" in help_output or "--json" in help_output
    available = bool(version_output.strip()) and json_supported
    error = "" if available else "fping v5 version/help check failed"
    return FpingV5CheckResult(available, str(paths.fping_path), version_output.strip(), json_supported, error)


def build_fping_v5_args(
    fping_path: Path,
    target: str,
    period_ms: int,
    timeout_ms: int,
    packet_size: int = 64,
    *,
    targets: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    normalized_targets = list(
        dict.fromkeys(
            value.strip()
            for value in (targets or ([target] if target else []))
            if value.strip()
        )
    )
    if not normalized_targets:
        raise ValueError("fping target list cannot be empty")
    return [
        str(fping_path),
        "-J",
        "-b",
        str(max(1, min(65_507, int(packet_size)))),
        "-l",
        "-p",
        str(max(1, int(period_ms))),
        "-t",
        str(max(1, int(timeout_ms))),
        *normalized_targets,
    ]


def run_fping_v5_json(
    target: str = "",
    period_ms: int = 100,
    timeout_ms: int = 100,
    packet_size: int = 64,
    count_json: int | None = 20,
    output_jsonl_path: Path | None = None,
    output_raw_log_path: Path | None = None,
    stop_event: threading.Event | None = None,
    project_root: Path | None = None,
    fping_path: Path | None = None,
    targets: list[str] | tuple[str, ...] | None = None,
) -> Iterator[FpingV5Sample]:
    if stop_event is not None and stop_event.is_set():
        return
    paths = resolve_fping_v5_paths(project_root, fping_path)
    args = build_fping_v5_args(
        paths.fping_path,
        target,
        period_ms,
        timeout_ms,
        packet_size,
        targets=targets,
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    raw_file = _open_text(output_raw_log_path)
    jsonl_file = _open_text(output_jsonl_path)
    process: subprocess.Popen[str] | None = None
    parsed_count = 0
    stop_event = stop_event or threading.Event()
    process_done = threading.Event()
    stop_watcher: threading.Thread | None = None
    try:
        process = subprocess.Popen(
            args,
            cwd=paths.fping_path.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        shutdown_manager.register_process(process, "fping", kind="internal_tool", shutdown_policy="terminate")
        stop_watcher = threading.Thread(
            target=_watch_stop_event,
            args=(process, stop_event, process_done),
            name="fping-stop-watcher",
            daemon=True,
        )
        stop_watcher.start()
        if process.stdout is None:
            return
        for line in process.stdout:
            if stop_event.is_set():
                break
            received_ts = datetime.now().isoformat(timespec="milliseconds")
            if raw_file is not None:
                raw_file.write(f"{received_ts} {line}")
                raw_file.flush()
            sample = parse_fping_v5_json_line(line, received_ts, int(timeout_ms))
            if sample is not None:
                parsed_count += 1
                if jsonl_file is not None:
                    jsonl_file.write(json.dumps(sample.as_dict(), ensure_ascii=False) + "\n")
                    jsonl_file.flush()
                yield sample
                if count_json is not None and parsed_count >= int(count_json):
                    break
    finally:
        process_done.set()
        if process is not None:
            _stop_process(process)
            shutdown_manager.unregister_process(process)
        if stop_watcher is not None:
            stop_watcher.join(timeout=1)
        if raw_file is not None:
            raw_file.close()
        if jsonl_file is not None:
            jsonl_file.close()


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout or ''}\n{result.stderr or ''}"


def _open_text(path: Path | None):
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", errors="replace")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _watch_stop_event(
    process: subprocess.Popen[str],
    stop_event: threading.Event,
    process_done: threading.Event,
) -> None:
    while not process_done.wait(0.05):
        if stop_event.is_set():
            _stop_process(process)
            return
