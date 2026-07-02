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


Runner = Callable[[list[str], int], subprocess.CompletedProcess]


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
    runner: Runner | None = None,
) -> PingResult:
    target = target.strip()
    if not target:
        raise ValueError("请输入目标主机。")
    runner = runner or _default_ping_runner
    args = _ping_args(target, count=count, size=size, timeout_ms=timeout_ms)
    try:
        completed = runner(args, max(int(timeout_ms / 1000 * max(count, 1)) + 5, 5))
    except Exception as exc:
        return PingResult(target=target, status="failed", timestamp=_now(), error=str(exc))
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    parsed = parse_ping_output(output, target=target)
    status = "online" if completed.returncode == 0 and (parsed.received > 0 or parsed.latency_ms is not None) else "offline"
    return PingResult(
        target=target,
        resolved_ip=parsed.resolved_ip,
        status=status,
        latency_ms=parsed.latency_ms,
        min_ms=parsed.min_ms,
        max_ms=parsed.max_ms,
        avg_ms=parsed.avg_ms,
        packet_loss_percent=parsed.packet_loss_percent,
        sent=parsed.sent or count,
        received=parsed.received,
        timestamp=_now(),
        error="" if status == "online" else _trim_output(output),
        raw_output=output,
    )


def run_batch_ping(
    targets: list[str],
    *,
    count: int = 1,
    size: int = 32,
    timeout_ms: int = 1500,
    concurrency: int = 100,
    runner: Runner | None = None,
) -> list[PingResult]:
    cleaned = [target.strip() for target in targets if target.strip()]
    concurrency = max(1, min(int(concurrency), 500))
    results: list[PingResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(run_single_ping, target, count=count, size=size, timeout_ms=timeout_ms, runner=runner) for target in cleaned]
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
    resolved_ip = ""
    first_line = output.splitlines()[0] if output.splitlines() else ""
    match = re.search(r"\[([0-9a-fA-F:.]+)\]|(?:Pinging|正在 Ping)\s+[^[]*\[?([0-9a-fA-F:.]+)\]?", first_line)
    if match:
        resolved_ip = next((group for group in match.groups() if group), "")
    latencies = [float(value) for value in re.findall(r"(?:time|时间)[=<]\s*(\d+(?:\.\d+)?)\s*ms", output, flags=re.IGNORECASE)]
    sent = received = 0
    loss: float | None = None
    stats = re.search(r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)\s*\((\d+)%", output, re.IGNORECASE)
    if not stats:
        stats = re.search(r"数据包:\s*已发送\s*=\s*(\d+)，\s*已接收\s*=\s*(\d+)，\s*丢失\s*=\s*(\d+)\s*\((\d+)%", output)
    if stats:
        sent = int(stats.group(1))
        received = int(stats.group(2))
        loss = float(stats.group(4))
    avg_match = re.search(r"(?:Average|平均)\s*=\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
    min_match = re.search(r"(?:Minimum|最短)\s*=\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
    max_match = re.search(r"(?:Maximum|最长)\s*=\s*(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
    return PingResult(
        target=target,
        resolved_ip=resolved_ip,
        latency_ms=latencies[-1] if latencies else None,
        min_ms=float(min_match.group(1)) if min_match else (min(latencies) if latencies else None),
        max_ms=float(max_match.group(1)) if max_match else (max(latencies) if latencies else None),
        avg_ms=float(avg_match.group(1)) if avg_match else (round(sum(latencies) / len(latencies), 2) if latencies else None),
        packet_loss_percent=loss,
        sent=sent,
        received=received or len(latencies),
        raw_output=output,
    )


def _ping_args(target: str, *, count: int, size: int, timeout_ms: int) -> list[str]:
    if sys.platform.startswith("win"):
        return ["ping", "-n", str(count), "-l", str(size), "-w", str(timeout_ms), target]
    return ["ping", "-c", str(count), "-s", str(size), "-W", str(max(1, int(timeout_ms / 1000))), target]


def _default_ping_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _trim_output(output: str) -> str:
    text = " ".join(output.split())
    return text[:300]
