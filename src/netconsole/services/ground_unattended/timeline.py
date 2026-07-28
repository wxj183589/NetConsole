from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class GroundUnattendedTimelineCorrelator:
    def __init__(
        self,
        output_dir: Path,
        *,
        tolerance_seconds: int,
        switch_before_seconds: int,
        switch_after_seconds: int,
        event_callback: Callable[..., Any] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.tolerance_seconds = max(1, int(tolerance_seconds))
        self.switch_before_seconds = max(0, int(switch_before_seconds))
        self.switch_after_seconds = max(0, int(switch_after_seconds))
        self.event_callback = event_callback or (lambda **_kwargs: None)
        self._lock = threading.RLock()
        self._hour = ""
        self._file = None
        self._recent: dict[str, deque[dict[str, Any]]] = {}
        self._latest_by_train: dict[str, dict[str, tuple[datetime, bool]]] = {}
        self._last_pattern: dict[str, str] = {}
        self._pending_flush_count = 0
        self._last_flush_monotonic = time.monotonic()

    def correlate(
        self, sample: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            ts = _parse_ts(str(sample["ts"]))
            received = _parse_ts(str(context.get("ac_received_at") or ""))
            ac_valid = bool(
                received
                and abs((ts - received).total_seconds()) <= self.tolerance_seconds
            )
            transition_context = self._transition_context(ts, context)
            sample_id = str(sample.get("sample_id") or "")
            result = {
                "record_type": "correlation",
                "ping_sample_id": sample_id,
                "ac_snapshot_id": context.get("ac_snapshot_id") if ac_valid else None,
                "train_id": context.get("train_id", ""),
                "mr_id": context.get("mr_id", ""),
                "peer_ap_name": context.get("current_ap_name", "") if ac_valid else "",
                "peer_ap_mac": context.get("current_ap_mac", "") if ac_valid else "",
                "station": context.get("station", "") if ac_valid else "",
                "section": context.get("section", "") if ac_valid else "",
                "mileage": context.get("mileage", "") if ac_valid else "",
                "rssi": context.get("rssi") if ac_valid else None,
                "ap_transition_context": transition_context,
                "ac_position_status": "matched" if ac_valid else "unknown",
                "loss_pattern": self._loss_pattern(
                    ts, sample, context, ac_valid=ac_valid
                ),
                "ts": sample["ts"],
            }
            self._write(result, ts)
            recent = self._recent.setdefault(
                str(sample.get("target_ip") or ""), deque()
            )
            recent.append({"ts": ts, "sample_id": sample_id})
            cutoff = max(1, self.switch_before_seconds)
            while recent and (ts - recent[0]["ts"]).total_seconds() > cutoff:
                recent.popleft()
            return result

    def ap_transition(
        self,
        *,
        target_ip: str,
        train_id: str,
        mr_id: str,
        transition_at: str,
        before_ap: str,
        after_ap: str,
    ) -> None:
        if self.switch_before_seconds <= 0:
            return
        moment = _parse_ts(transition_at)
        with self._lock:
            for item in tuple(self._recent.get(target_ip, ())):
                delta = (moment - item["ts"]).total_seconds()
                if 0 <= delta <= self.switch_before_seconds:
                    self._write(
                        {
                            "record_type": "correlation_update",
                            "ping_sample_id": item["sample_id"],
                            "train_id": train_id,
                            "mr_id": mr_id,
                            "ap_transition_context": "before_transition",
                            "transition_at": transition_at,
                            "before_ap": before_ap,
                            "after_ap": after_ap,
                        },
                        moment,
                    )

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
                self._file = None

    def _transition_context(self, ts: datetime, context: dict[str, Any]) -> str:
        transition_at = _parse_ts(
            str(context.get("ap_transition_at") or ""), required=False
        )
        if transition_at is None:
            return "same_ap"
        delta = (ts - transition_at).total_seconds()
        # fping 进程可能在控制面切换目标元数据前已经吐出一条样本；
        # 该样本在切换后被顺序处理时归入切换后窗口，避免产生虚假的时间轴空洞。
        if -1.0 <= delta <= self.switch_after_seconds:
            return "after_transition"
        return "same_ap"

    def _loss_pattern(
        self,
        ts: datetime,
        sample: dict[str, Any],
        context: dict[str, Any],
        *,
        ac_valid: bool,
    ) -> str:
        train_id = str(context.get("train_id") or "")
        endpoint = str(context.get("mr_position_code") or "")
        if not train_id or endpoint not in {"CT", "CW"}:
            return ""
        state = self._latest_by_train.setdefault(train_id, {})
        state[endpoint] = (ts, not bool(sample.get("ok")))
        other = "CW" if endpoint == "CT" else "CT"
        if not sample.get("ok") and not ac_valid:
            pattern = "AC_POSITION_UNKNOWN_LOSS"
        elif other not in state or abs((ts - state[other][0]).total_seconds()) > 2:
            pattern = ""
        else:
            ct_loss = state.get("CT", (ts, False))[1]
            cw_loss = state.get("CW", (ts, False))[1]
            pattern = (
                "BOTH_LOSS"
                if ct_loss and cw_loss
                else "CT_ONLY_LOSS"
                if ct_loss
                else "CW_ONLY_LOSS"
                if cw_loss
                else ""
            )
        if pattern and self._last_pattern.get(train_id) != pattern:
            self.event_callback(
                event_type="ping_loss_pattern",
                severity="warning",
                train_id=train_id,
                mr_id=str(context.get("mr_id") or ""),
                title="检测到列车双端 Ping 异常模式",
                message=pattern,
                details={"pattern": pattern, "ts": sample.get("ts")},
            )
        self._last_pattern[train_id] = pattern
        return pattern

    def _write(self, payload: dict[str, Any], ts: datetime) -> None:
        hour = ts.strftime("%Y%m%d_%H")
        if hour != self._hour:
            if self._file is not None:
                self._file.flush()
                self._file.close()
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._file = (self.output_dir / f"timeline_{hour}.jsonl").open(
                "a", encoding="utf-8", newline="\n"
            )
            self._hour = hour
            self._pending_flush_count = 0
            self._last_flush_monotonic = time.monotonic()
        self._file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._pending_flush_count += 1
        if (
            self._pending_flush_count >= 64
            or time.monotonic() - self._last_flush_monotonic >= 1.0
        ):
            self._file.flush()
            self._pending_flush_count = 0
            self._last_flush_monotonic = time.monotonic()


def _parse_ts(value: str, *, required: bool = True) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        return parsed if parsed.tzinfo else parsed.astimezone()
    except ValueError:
        if required:
            return datetime.now().astimezone()
        return None


__all__ = ["GroundUnattendedTimelineCorrelator"]
