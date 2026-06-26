from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from netconsole.services.network_tools.iperf_runner import IperfClientConfig
from netconsole.services.online_mr.event_bus import EVENT_IPERF3_SAMPLE, OnlineMrEvent, OnlineMrEventBus


def build_iperf3_json_args(iperf_path: Path, config: IperfClientConfig) -> list[str]:
    cfg = config.normalized()
    args = [
        str(iperf_path),
        "-c",
        cfg.server_ip,
        "-p",
        str(cfg.port),
        "-i",
        str(cfg.interval_seconds),
        "-t",
        str(cfg.duration_seconds),
        "-J",
        "--forceflush",
    ]
    if cfg.protocol == "UDP":
        args.append("-u")
    if cfg.parallel > 1:
        args.extend(["-P", str(cfg.parallel)])
    if cfg.direction == "download":
        args.append("-R")
    elif cfg.direction == "bidirectional":
        args.append("--bidir")
    if cfg.target_bandwidth:
        args.extend(["-b", cfg.target_bandwidth])
    return args


class Iperf3JsonWorker:
    def __init__(
        self,
        iperf_path: Path,
        config: IperfClientConfig,
        event_bus: OnlineMrEventBus,
        *,
        session_id: str,
        device_id: int | None,
        raw_json_path: Path | None = None,
    ) -> None:
        self.iperf_path = iperf_path
        self.config = config.normalized()
        self.event_bus = event_bus
        self.session_id = session_id
        self.device_id = device_id
        self.raw_json_path = raw_json_path
        self.process: subprocess.Popen[str] | None = None

    def run(self) -> dict[str, object]:
        args = build_iperf3_json_args(self.iperf_path, self.config)
        self.process = subprocess.Popen(
            args,
            cwd=self.iperf_path.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output, _ = self.process.communicate()
        if self.raw_json_path is not None:
            self.raw_json_path.parent.mkdir(parents=True, exist_ok=True)
            self.raw_json_path.write_text(output or "", encoding="utf-8", errors="replace")
        payload = json.loads(output or "{}")
        self.event_bus.publish(
            OnlineMrEvent(
                timestamp=datetime.now(),
                device_id=self.device_id,
                session_id=self.session_id,
                source="iperf3",
                module="iperf",
                event_type=EVENT_IPERF3_SAMPLE,
                payload=payload if isinstance(payload, dict) else {"value": payload},
                raw=output,
            )
        )
        return payload if isinstance(payload, dict) else {"value": payload}

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
