from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from netconsole.core.ping.fping_v5_models import FpingV5Sample
from netconsole.core.ping.fping_v5_runner import check_fping_v5_available, run_fping_v5_json
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
        self.source_device_id = source_device_id if source_device_id is not None else self.session.meta.device_id

    def run(self, snapshot_callback: Callable[[dict[str, object]], None] | None = None) -> FpingV5ProbeResult:
        if not self.config.enabled:
            self.session.write_fping_final_summary("Status: high frequency ping disabled")
            return FpingV5ProbeResult("disabled")
        if not self.config.target:
            error = "Ping target is empty"
            self.session.write_fping_final_summary(f"Status: failed\nReason: {error}")
            return FpingV5ProbeResult("FAILED", error)
        check = check_fping_v5_available(fping_path=self.fping_path)
        if not check.available:
            error = check.error or "fping v5 is unavailable"
            self.session.write_fping_final_summary(f"Status: failed\nReason: {error}")
            return FpingV5ProbeResult("FAILED", error)
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
            ):
                snapshot = self.handle_sample(sample)
                if snapshot_callback is not None:
                    snapshot_callback(snapshot)
                if self.stop_requested:
                    break
        except Exception as exc:
            self.session.write_fping_final_summary(f"Status: failed\nReason: {exc}")
            return FpingV5ProbeResult("FAILED", str(exc))
        finally:
            self.write_summary()
        return FpingV5ProbeResult("STOPPED" if self.stop_requested else "DONE")

    def stop(self) -> None:
        self.stop_requested = True
        self.stop_event.set()

    def handle_sample(self, sample: FpingV5Sample) -> dict[str, object]:
        self.stats.add(sample)
        payload = sample.as_dict()
        payload.update(self.stats.as_dict())
        payload["source_device_id"] = self.source_device_id
        payload["target_ip"] = self.config.target
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

    def write_summary(self) -> None:
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
        self.session.write_fping_final_summary(json.dumps({"Status": "normal", **summary}, ensure_ascii=False, indent=2))
