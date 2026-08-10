from __future__ import annotations

import ipaddress
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.core.ping.fping_v5_runner import (
    check_fping_v5_available,
    run_fping_v5_json,
)
from netconsole.core.ping.fping_v5_stats import FpingV5Stats
from netconsole.models.online_mr_models import FpingConfig
from netconsole.services.online_mr.event_bus import EVENT_FPING_V5_SAMPLE, OnlineMrEvent, OnlineMrEventBus
from netconsole.services.online_mr_session_store import OnlineMrSession


@dataclass(frozen=True)
class FpingV5ProbeResult:
    status: str
    error: str = ""


class FpingV5ProbeRunner:
    def __init__(
        self,
        session: OnlineMrSession,
        config: FpingConfig,
        fping_path: Path,
        event_bus: OnlineMrEventBus | None = None,
        source_device_id: int | None = None,
    ) -> None:
        self.session = session
        self.config = config.normalized()
        self.fping_path = fping_path
        self.stop_requested = False
        self.stop_event = threading.Event()
        self.event_bus = event_bus or OnlineMrEventBus()
        self.stats = FpingV5Stats()
        self.source_device_id = (
            source_device_id
            if source_device_id is not None
            else self.session.meta.device_id
        )
        self.process_started = threading.Event()
        self.finished = threading.Event()
        self.last_result: FpingV5ProbeResult | None = None
        self.last_sample: dict[str, object] = {}
        self._prepared = False

    def prepare(self) -> FpingV5ProbeResult:
        if self._prepared:
            return FpingV5ProbeResult("ready")
        if not self.config.enabled:
            return FpingV5ProbeResult("disabled")
        if not self.config.target:
            return FpingV5ProbeResult("FAILED", "Ping target is empty")
        try:
            ipaddress.ip_address(self.config.target)
        except ValueError:
            return FpingV5ProbeResult("FAILED", "Ping target is not a valid IP address")
        check = check_fping_v5_available(fping_path=self.fping_path)
        if not check.available:
            return FpingV5ProbeResult(
                "FAILED", check.error or "fping v5 is unavailable"
            )
        try:
            (self.session.session_dir / "raw").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return FpingV5ProbeResult(
                "FAILED", f"fping output directory is unavailable: {exc}"
            )
        self._prepared = True
        return FpingV5ProbeResult("ready")

    def wait_until_running(self, timeout_seconds: float = 5.0) -> FpingV5ProbeResult:
        if self.process_started.wait(max(0.0, float(timeout_seconds))):
            self.finished.wait(0.05)
            if self.finished.is_set() and self.last_result is not None:
                return self.last_result
            return FpingV5ProbeResult("running")
        if self.last_result is not None:
            return self.last_result
        return FpingV5ProbeResult("FAILED", "fping process startup timed out")

    def run(self, snapshot_callback: Callable[[dict[str, object]], None] | None = None) -> FpingV5ProbeResult:
        prepared = self.prepare()
        if prepared.status != "ready":
            if prepared.status == "disabled":
                self.session.write_fping_final_summary("Status: high frequency ping disabled")
            else:
                self.session.write_fping_final_summary(
                    f"Status: failed\nReason: {prepared.error}"
                )
            self.last_result = prepared
            self.finished.set()
            return prepared
        result = FpingV5ProbeResult("DONE")
        try:
            raw_log = self.session.session_dir / "raw" / "fping_v5_raw.log"
            jsonl = self.session.session_dir / "raw" / "fping_v5_samples.jsonl"
            for sample in run_fping_v5_json(
                target=self.config.target,
                period_ms=self.config.interval_ms,
                timeout_ms=self.config.loss_threshold_ms,
                packet_size=self.config.packet_size,
                count_json=None,
                output_jsonl_path=jsonl,
                output_raw_log_path=raw_log,
                stop_event=self.stop_event,
                fping_path=self.fping_path,
                process_started_event=self.process_started,
            ):
                snapshot = self.handle_sample(sample)
                if snapshot_callback is not None:
                    snapshot_callback(snapshot)
                if self.stop_requested:
                    break
        except Exception as exc:
            result = FpingV5ProbeResult("FAILED", str(exc))
        else:
            result = FpingV5ProbeResult(
                "STOPPED" if self.stop_requested else "DONE"
            )
        finally:
            self.last_result = result
            summary_status = {
                "DONE": "normal",
                "STOPPED": "stopped",
                "FAILED": "failed",
            }.get(result.status, result.status.lower())
            self.write_summary(status=summary_status, error=result.error)
            self.finished.set()
        return result

    def stop(self) -> None:
        self.stop_requested = True
        self.stop_event.set()

    def handle_sample(self, sample: FpingV5Sample) -> dict[str, object]:
        self.stats.add(sample)
        payload = sample.as_dict()
        payload.update(self.stats.as_dict())
        payload["source_device_id"] = self.source_device_id
        payload["target_ip"] = self.config.target
        self.last_sample = payload
        event = OnlineMrEvent(
            timestamp=datetime.fromisoformat(sample.ts),
            device_id=self.source_device_id,
            session_id=self.session.meta.session_id,
            source="fping_v5",
            module="fping",
            event_type=EVENT_FPING_V5_SAMPLE,
            payload=payload,
            raw=json.dumps(sample.raw, ensure_ascii=False),
        )
        self.event_bus.publish(event)
        return self.stats.as_dict()

    def write_summary(self, *, status: str = "normal", error: str = "") -> None:
        stats = self.stats.as_dict()
        summary = {
            "target_ip": self.config.target,
            "sent": stats["sent_count"],
            "received": stats["success_count"],
            "lost": stats["timeout_count"],
            "loss_percent": stats["loss_rate_percent"],
            "min_latency_ms": stats["min_rtt_ms"],
            "max_latency_ms": stats["max_rtt_ms"],
            "avg_latency_ms": stats["avg_rtt_ms"],
        }
        self.session.write_fping_final_summary(
            json.dumps(
                {"Status": status, "error": error, **summary},
                ensure_ascii=False,
                indent=2,
            )
        )
