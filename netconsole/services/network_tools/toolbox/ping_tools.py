from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from netconsole.utils.text_encoding import decode_bytes_with_fallback


Runner = Callable[[list[str], int], subprocess.CompletedProcess]
IP_RE = r"[0-9a-fA-F:.]+"


@dataclass(frozen=True)
class PingResult:
    target: str
    resolved_ip: str = ""
    status: str = "unknown"
    latency_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    avg_ms: float | None = None
    packet_loss_percent: float | None = None
    sent: int = 0
    received: int = 0
    timestamp: str = ""
    error: str = ""
    raw_output: str = ""


@dataclass(frozen=True)
class TcpPingResult:
    target: str
    port: int
    resolved_ip: str = ""
    status: str = "unknown"
    latency_ms: float | None = None
    timestamp: str = ""
    error: str = ""


def run_single_ping(
    target: str,
    *,
    count: int = 4,
    size: int = 32,
    timeout_ms: int = 1500,
    source_ip: str = "",
    runner: Runner | None = None,
) -> PingResult:
    target = target.strip()
    if not target:
        raise ValueError("请输入目标主机。")
    runner = runner or _default_ping_runner
    args = _ping_args(target, count=count, size=size, timeout_ms=timeout_ms, source_ip=source_ip)
    try:
        completed = runner(args, max(int(timeout_ms / 1000 * max(count, 1)) + 5, 5))
    except Exception as exc:
        return PingResult(target=target, status="failed", timestamp=_now(), error=str(exc))
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    parsed = parse_ping_output(output, target=target)
    online = completed.returncode == 0 and parsed.received > 0 and parsed.latency_ms is not None
    return PingResult(
        target=target,
        resolved_ip=parsed.resolved_ip,
        status="online" if online else _fallback_status(output),
        latency_ms=parsed.latency_ms,
        min_ms=parsed.min_ms,
        max_ms=parsed.max_ms,
        avg_ms=parsed.avg_ms,
        packet_loss_percent=parsed.packet_loss_percent,
        sent=parsed.sent or count,
        received=parsed.received,
        timestamp=_now(),
        error="" if online else _trim_output(output),
        raw_output=output,
    )


def run_batch_ping(
    targets: list[str],
    *,
    count: int = 1,
    size: int = 32,
    timeout_ms: int = 1500,
    concurrency: int = 100,
    source_ip: str = "",
    runner: Runner | None = None,
) -> list[PingResult]:
    cleaned = [target.strip() for target in targets if target.strip()]
    concurrency = max(1, min(int(concurrency), 500))
    results: list[PingResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                run_single_ping,
                target,
                count=count,
                size=size,
                timeout_ms=timeout_ms,
                source_ip=source_ip,
                runner=runner,
            )
            for target in cleaned
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: cleaned.index(item.target) if item.target in cleaned else 0)


def run_tcp_ping(
    target: str,
    port: int,
    *,
    timeout_seconds: float = 3.0,
    socket_factory=socket.create_connection,
) -> TcpPingResult:
    target = target.strip()
    if not target:
        raise ValueError("请输入目标主机。")
    if int(port) <= 0 or int(port) > 65535:
        raise ValueError("端口必须在 1-65535 之间。")
    started = time.perf_counter()
    try:
        resolved_ip = socket.gethostbyname(target)
        connection = socket_factory((target, int(port)), timeout=float(timeout_seconds))
        close = getattr(connection, "close", None)
        if callable(close):
            close()
        latency = (time.perf_counter() - started) * 1000
        return TcpPingResult(target=target, port=int(port), resolved_ip=resolved_ip, status="open", latency_ms=round(latency, 2), timestamp=_now())
    except socket.gaierror as exc:
        return TcpPingResult(target=target, port=int(port), status="failed", timestamp=_now(), error=f"dns failed: {exc}")
    except TimeoutError as exc:
        return TcpPingResult(target=target, port=int(port), status="timeout", timestamp=_now(), error=f"timeout: {exc}")
    except OSError as exc:
        return TcpPingResult(target=target, port=int(port), status="closed", timestamp=_now(), error=str(exc))


def parse_ping_output(output: str, *, target: str = "") -> PingResult:
    resolved_ip = _resolved_ip_from_output(output, target)
    valid_latencies: list[float] = []
    for line in output.splitlines():
        reply_ip = _reply_ip(line)
        if not reply_ip or not _is_target_reply(reply_ip, target, resolved_ip) or _is_unreachable_line(line):
            continue
        latency = _latency_from_line(line)
        if latency is not None:
            valid_latencies.append(latency)
    sent = 0
    loss: float | None = None
    stats = re.search(r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)\s*\((\d+)%", output, re.IGNORECASE)
    if not stats:
        stats = re.search(r"已发送\s*=\s*(\d+)[，,]\s*已接收\s*=\s*(\d+)[，,]\s*丢失\s*=\s*(\d+)\s*\((\d+)%", output)
    if stats:
        sent = int(stats.group(1))
        loss = float(stats.group(4))
    received = len(valid_latencies)
    min_ms = min(valid_latencies) if valid_latencies else None
    max_ms = max(valid_latencies) if valid_latencies else None
    avg_ms = round(sum(valid_latencies) / len(valid_latencies), 2) if valid_latencies else None
    return PingResult(
        target=target,
        resolved_ip=resolved_ip,
        latency_ms=valid_latencies[-1] if valid_latencies else None,
        min_ms=min_ms,
        max_ms=max_ms,
        avg_ms=avg_ms,
        packet_loss_percent=loss,
        sent=sent,
        received=received,
        raw_output=output,
    )


def _ping_args(target: str, *, count: int, size: int, timeout_ms: int, source_ip: str = "") -> list[str]:
    source_ip = source_ip.strip()
    if sys.platform.startswith("win"):
        args = ["ping"]
        if source_ip:
            args.extend(["-S", source_ip])
        args.extend(["-n", str(count), "-l", str(size), "-w", str(timeout_ms), target])
        return args
    args = ["ping"]
    if source_ip:
        args.extend(["-I", source_ip])
    args.extend(["-c", str(count), "-s", str(size), "-W", str(max(1, int(timeout_ms / 1000))), target])
    return args


def _default_ping_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    completed = subprocess.run(args, capture_output=True, timeout=timeout)
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        _decode_output(completed.stdout),
        _decode_output(completed.stderr),
    )


def _resolved_ip_from_output(output: str, target: str) -> str:
    first_line = output.splitlines()[0] if output.splitlines() else ""
    match = re.search(r"\[(" + IP_RE + r")\]|(?:Pinging|正在 Ping)\s+[^[]*\[?(" + IP_RE + r")\]?", first_line, re.IGNORECASE)
    if match:
        return next((group for group in match.groups() if group), "")
    return target if _looks_like_ip(target) else ""


def _reply_ip(line: str) -> str:
    match = re.search(r"(?:Reply from|来自)\s+(" + IP_RE + r")", line, re.IGNORECASE)
    return match.group(1).rstrip(":") if match else ""


def _is_target_reply(reply_ip: str, target: str, resolved_ip: str) -> bool:
    expected = {value for value in (target.strip(), resolved_ip.strip()) if value and _looks_like_ip(value)}
    return reply_ip in expected


def _latency_from_line(line: str) -> float | None:
    match = re.search(r"(?:time|时间)[=<]\s*(\d+(?:\.\d+)?)\s*ms", line, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _is_unreachable_line(line: str) -> bool:
    lowered = line.lower()
    return "unreachable" in lowered or "无法访问目标主机" in line or "无法访问" in line


def _fallback_status(output: str) -> str:
    lowered = output.lower()
    if "unreachable" in lowered or "无法访问" in output:
        return "unreachable"
    if "timed out" in lowered or "请求超时" in output or "timeout" in lowered:
        return "timeout"
    return "offline"


def _looks_like_ip(value: str) -> bool:
    return bool(re.fullmatch(IP_RE, value.strip()))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _trim_output(output: str) -> str:
    text = " ".join(output.split()).replace("\ufffd", "")
    return text[:300] or "命令执行失败：Ping 输出解析失败"


def _decode_output(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data.replace("\ufffd", "")
    # 外部 ping 回显统一按 utf-8-sig/utf-8/gb18030/gbk 解码；仅无法识别时才 replacement。
    return decode_bytes_with_fallback(data).text
