from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from netconsole.services.network_tools.toolbox.ping_tools import PingResult, _decode_output
from netconsole.core.shutdown_manager import shutdown_manager
from netconsole.core.paths import PathResolver
from netconsole.services.tool_path_resolver import resolve_network_tool


ProgressCallback = Callable[[PingResult], None]
StopCallback = Callable[[], bool]


@dataclass(frozen=True)
class FpingAvailability:
    available: bool
    path: Path | None = None
    version: str = ""
    error: str = ""
    supports_json: bool = False
    supports_source_ip: bool = False
    source: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def discover_fping(root: Path | None = None) -> FpingAvailability:
    project_root = Path(root).resolve() if root else None
    paths = PathResolver(project_root) if project_root else PathResolver()
    resolution = resolve_network_tool("fping", paths, project_root=project_root)
    if not resolution.available or resolution.effective_path is None:
        return FpingAvailability(False, error=resolution.validation_message, source=resolution.source)
    return _check_fping(
        resolution.effective_path,
        source=resolution.source,
        fallback_used=resolution.fallback_used,
        fallback_reason=resolution.fallback_reason,
    )


def scan_targets(
    targets: Iterable[str],
    *,
    root: Path | None = None,
    count: int = 1,
    size: int = 32,
    timeout_ms: int = 1500,
    source_ip: str = "",
    progress: ProgressCallback | None = None,
    should_stop: StopCallback | None = None,
) -> tuple[list[PingResult], FpingAvailability]:
    cleaned = [target.strip() for target in targets if target and target.strip()]
    availability = discover_fping(root)
    if not availability.available or not availability.path:
        return [], availability
    args = _build_args(availability, count=count, size=size, timeout_ms=timeout_ms, source_ip=source_ip)
    results: dict[str, PingResult] = {}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        target_file = Path(handle.name)
        handle.write("\n".join(cleaned))
        handle.write("\n")
    try:
        command = [*args, "-f", str(target_file)]
        process = subprocess.Popen(
            command,
            cwd=str(availability.path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        shutdown_manager.register_process(process, "fping", kind="internal_tool", shutdown_policy="terminate")
        assert process.stdout is not None
        non_json_lines: list[str] = []
        for raw_line in process.stdout:
            if should_stop and should_stop():
                _terminate_process(process)
                break
            line = _decode_output(raw_line).strip()
            result = parse_fping_json_line(line)
            if result is None:
                if line:
                    non_json_lines.append(line)
                continue
            results[result.target] = result
            if progress:
                progress(result)
        return_code = process.wait(timeout=2)
        if return_code not in (0, 1) and not (should_stop and should_stop()):
            detail = " ".join(non_json_lines)[:300] or str(return_code)
            return [], FpingAvailability(False, availability.path, availability.version, f"fping 执行失败：{detail}", True, availability.supports_source_ip)
    finally:
        if "process" in locals():
            shutdown_manager.unregister_process(process)
        try:
            target_file.unlink()
        except OSError:
            pass
    ordered = [results[target] for target in cleaned if target in results]
    return ordered, availability


def parse_fping_json_line(line: str) -> PingResult | None:
    if not line.strip():
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("resp"), dict):
        resp = payload["resp"]
        target = _target(resp)
        rtt = _float(resp.get("rtt"))
        if not target or rtt is None:
            return None
        return PingResult(
            target=target,
            resolved_ip=str(resp.get("ip") or target),
            status="online",
            latency_ms=rtt,
            min_ms=rtt,
            max_ms=rtt,
            avg_ms=rtt,
            sent=1,
            received=1,
            packet_loss_percent=0,
            timestamp=_now(),
            raw_output=line,
        )
    if isinstance(payload.get("timeout"), dict):
        timeout = payload["timeout"]
        target = _target(timeout)
        if not target:
            return None
        return PingResult(target=target, resolved_ip=target, status="timeout", sent=1, received=0, packet_loss_percent=100, timestamp=_now(), error="timeout", raw_output=line)
    if isinstance(payload.get("unreachable"), dict):
        unreachable = payload["unreachable"]
        target = _target(unreachable)
        if not target:
            return None
        return PingResult(target=target, resolved_ip=target, status="unreachable", sent=1, received=0, packet_loss_percent=100, timestamp=_now(), error="unreachable", raw_output=line)
    if isinstance(payload.get("summary"), dict):
        summary = payload["summary"]
        target = _target(summary)
        if not target:
            return None
        sent = _int(summary.get("xmt"), summary.get("sent"), default=0)
        received = _int(summary.get("rcv"), summary.get("received"), default=0)
        loss = _float(summary.get("loss"), summary.get("lossPercent"))
        avg = _float(summary.get("rttAvg"), summary.get("avg"), summary.get("avg_ms"))
        min_ms = _float(summary.get("rttMin"), summary.get("min"), summary.get("min_ms"))
        max_ms = _float(summary.get("rttMax"), summary.get("max"), summary.get("max_ms"))
        online = received > 0 and avg is not None
        return PingResult(
            target=target,
            resolved_ip=str(summary.get("ip") or target),
            status="online" if online else "offline",
            latency_ms=avg,
            min_ms=min_ms,
            max_ms=max_ms,
            avg_ms=avg,
            packet_loss_percent=loss,
            sent=sent,
            received=received,
            timestamp=_now(),
            error="" if online else "no response",
            raw_output=line,
        )
    return None


def _check_fping(
    path: Path,
    *,
    source: str,
    fallback_used: bool,
    fallback_reason: str,
) -> FpingAvailability:
    try:
        version = subprocess.run([str(path), "-v"], cwd=path.parent, capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)
        help_result = subprocess.run([str(path), "--help"], cwd=path.parent, capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return FpingAvailability(False, path, error=f"fping 执行失败：{exc}", source=source)
    except subprocess.TimeoutExpired:
        return FpingAvailability(False, path, error="fping 检查超时", source=source)
    version_text = _decode_output(version.stdout + version.stderr).strip()
    help_text = _decode_output(help_result.stdout + help_result.stderr)
    json_supported = "-J" in help_text or "--json" in help_text
    source_supported = "-S" in help_text or "--src" in help_text
    if version.returncode != 0 or help_result.returncode != 0:
        return FpingAvailability(False, path, version_text, "fping version/help 检查失败", json_supported, source_supported, source)
    if not json_supported:
        return FpingAvailability(False, path, version_text, "fping 不支持 JSON 输出", False, source_supported, source)
    return FpingAvailability(
        True,
        path,
        version_text,
        "",
        True,
        source_supported,
        source,
        fallback_used,
        fallback_reason,
    )


def _build_args(availability: FpingAvailability, *, count: int, size: int, timeout_ms: int, source_ip: str) -> list[str]:
    assert availability.path is not None
    args = [str(availability.path), "-J", "-c", str(max(1, int(count))), "-t", str(max(1, int(timeout_ms))), "-b", str(max(1, int(size)))]
    if source_ip.strip() and availability.supports_source_ip:
        args.extend(["-S", source_ip.strip()])
    return args


def _terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def _target(row: dict) -> str:
    return str(row.get("target") or row.get("host") or row.get("ip") or "").strip()


def _float(*values: object) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _int(*values: object, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
