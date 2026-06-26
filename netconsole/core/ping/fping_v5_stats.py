from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample


@dataclass
class FpingV5Stats:
    sent_count: int = 0
    success_count: int = 0
    timeout_count: int = 0
    last_rtt_ms: float | None = None
    min_rtt_ms: float | None = None
    max_rtt_ms: float | None = None
    rtt_sum_ms: float = 0.0
    last_error: str = ""
    first_ts: str = ""
    last_ts: str = ""
    backend: str = BACKEND

    def add(self, sample: FpingV5Sample) -> None:
        if sample.raw_type not in {"resp", "timeout"}:
            return
        if not self.first_ts:
            self.first_ts = sample.ts
        self.last_ts = sample.ts
        self.sent_count += 1
        if sample.ok:
            self.success_count += 1
            if sample.rtt_ms is not None:
                rtt = float(sample.rtt_ms)
                self.last_rtt_ms = rtt
                self.rtt_sum_ms += rtt
                self.min_rtt_ms = rtt if self.min_rtt_ms is None else min(self.min_rtt_ms, rtt)
                self.max_rtt_ms = rtt if self.max_rtt_ms is None else max(self.max_rtt_ms, rtt)
            self.last_error = ""
        else:
            self.timeout_count += 1
            self.last_error = sample.error

    @property
    def loss_rate_percent(self) -> float:
        return (self.timeout_count / self.sent_count * 100.0) if self.sent_count else 0.0

    @property
    def avg_rtt_ms(self) -> float | None:
        return (self.rtt_sum_ms / self.success_count) if self.success_count else None

    def as_dict(self) -> dict[str, object]:
        return {
            "sent_count": self.sent_count,
            "success_count": self.success_count,
            "timeout_count": self.timeout_count,
            "loss_rate_percent": self.loss_rate_percent,
            "last_rtt_ms": self.last_rtt_ms,
            "avg_rtt_ms": self.avg_rtt_ms,
            "min_rtt_ms": self.min_rtt_ms,
            "max_rtt_ms": self.max_rtt_ms,
            "last_error": self.last_error,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "backend": self.backend,
        }

