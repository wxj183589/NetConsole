from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterator

from netconsole.core.ping.fping_v5_models import FpingV5CheckResult, FpingV5Paths, FpingV5Sample
from netconsole.core.ping.fping_v5_parser import parse_fping_v5_json_line


def resolve_fping_v5_paths(project_root: Path | None = None, fping_path: Path | None = None) -> FpingV5Paths:
    root = (project_root or Path.cwd()).resolve()
    exe = (fping_path or root / "tools" / "fping_v5" / "fping.exe").resolve()
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


def build_fping_v5_args(fping_path: Path, target: str, period_ms: int, timeout_ms: int) -> list[str]:
    return [str(fping_path), "-J", "-l", "-p", str(max(1, int(period_ms))), "-t", str(max(1, int(timeout_ms))), target]


def run_fping_v5_json(
    target: str,
    period_ms: int = 100,
    timeout_ms: int = 100,
    count_json: int | None = 20,
    output_jsonl_path: Path | None = None,
    output_raw_log_path: Path | None = None,
    stop_event: threading.Event | None = None,
    project_root: Path | None = None,
    fping_path: Path | None = None,
) -> Iterator[FpingV5Sample]:
    paths = resolve_fping_v5_paths(project_root, fping_path)
    args = build_fping_v5_args(paths.fping_path, target, period_ms, timeout_ms)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    raw_file = _open_text(output_raw_log_path)
    jsonl_file = _open_text(output_jsonl_path)
    process: subprocess.Popen[str] | None = None
    parsed_count = 0
    stop_event = stop_event or threading.Event()
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
        if process.stdout is None:
            return
        for line in process.stdout:
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
            if stop_event.is_set():
                break
    finally:
        if process is not None:
            _stop_process(process)
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
