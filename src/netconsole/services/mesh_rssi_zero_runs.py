from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Callable, Literal, Sequence, TypeVar


SUSTAINED_ZERO_DISPLAY_MS = 3_000
MINIMUM_SAMPLE_INTERVAL_MS = 100
MAXIMUM_SAMPLE_INTERVAL_MS = 5_000
DEFAULT_SAMPLE_INTERVAL_MS = 1_000
MAXIMUM_CONTINUOUS_GAP_MS = 60_000

RssiZeroState = Literal["suppressed", "sustained"]
RssiZeroBoundary = Literal["start", "middle", "end", "single"]

T = TypeVar("T")


@dataclass(frozen=True)
class RssiZeroRunMetadata:
    state: RssiZeroState
    start_time: str
    end_time: str
    duration_ms: int
    sample_count: int
    boundary: RssiZeroBoundary
    estimated_end: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "state": self.state,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "sample_count": self.sample_count,
            "boundary": self.boundary,
            "estimated_end": self.estimated_end,
        }


@dataclass(frozen=True)
class RssiZeroRunSummary:
    suppressed_sample_count: int = 0
    suppressed_run_count: int = 0
    sustained_run_count: int = 0
    sustained_total_duration_ms: int = 0
    sustained_longest_duration_ms: int = 0


@dataclass(frozen=True)
class RssiZeroRunAnalysis:
    metadata_by_index: dict[int, RssiZeroRunMetadata]
    sustained_boundary_indices: frozenset[int]
    sample_interval_ms: int
    maximum_continuous_gap_ms: int
    summary: RssiZeroRunSummary


def analyze_rssi_zero_runs(
    rows: Sequence[T],
    *,
    timestamp_selector: Callable[[T], object],
    value_selector: Callable[[T], object],
    boundary_before_selector: Callable[[T], bool] | None = None,
    fallback_sample_interval_ms: object = None,
    maximum_continuous_gap_ms: object = None,
    sustained_zero_display_ms: int = SUSTAINED_ZERO_DISPLAY_MS,
) -> RssiZeroRunAnalysis:
    """Classify explicit zero runs without changing the source rows."""

    boundary_before_selector = boundary_before_selector or (lambda _row: False)
    timestamps = [_parse_time(timestamp_selector(row)) for row in rows]
    sample_interval_ms = _estimate_sample_interval_ms(
        rows,
        timestamps,
        boundary_before_selector,
        fallback_sample_interval_ms,
    )
    continuous_gap_ms = _continuous_gap_ms(
        maximum_continuous_gap_ms,
        sample_interval_ms,
    )
    metadata_by_index: dict[int, RssiZeroRunMetadata] = {}
    sustained_boundaries: set[int] = set()
    suppressed_sample_count = 0
    suppressed_run_count = 0
    sustained_run_count = 0
    sustained_total_duration_ms = 0
    sustained_longest_duration_ms = 0
    zero_indices: list[int] = []
    previous_time: datetime | None = None

    def flush(next_valid_time: datetime | None = None) -> None:
        nonlocal zero_indices
        nonlocal suppressed_sample_count, suppressed_run_count
        nonlocal sustained_run_count, sustained_total_duration_ms
        nonlocal sustained_longest_duration_ms
        if not zero_indices:
            return
        first_index = zero_indices[0]
        last_index = zero_indices[-1]
        start = timestamps[first_index]
        last = timestamps[last_index]
        if start is None or last is None:
            zero_indices = []
            return
        estimated_end = next_valid_time is None
        end = next_valid_time or (last + timedelta(milliseconds=sample_interval_ms))
        duration_ms = max(int(round((end - start).total_seconds() * 1_000)), 0)
        state: RssiZeroState = (
            "sustained"
            if duration_ms >= max(int(sustained_zero_display_ms), 0)
            else "suppressed"
        )
        sample_count = len(zero_indices)
        if state == "suppressed":
            suppressed_sample_count += sample_count
            suppressed_run_count += 1
        else:
            sustained_run_count += 1
            sustained_total_duration_ms += duration_ms
            sustained_longest_duration_ms = max(
                sustained_longest_duration_ms,
                duration_ms,
            )
        for offset, index in enumerate(zero_indices):
            boundary: RssiZeroBoundary
            if sample_count == 1:
                boundary = "single"
            elif offset == 0:
                boundary = "start"
            elif offset == sample_count - 1:
                boundary = "end"
            else:
                boundary = "middle"
            metadata_by_index[index] = RssiZeroRunMetadata(
                state=state,
                start_time=_format_time(start),
                end_time=_format_time(end),
                duration_ms=duration_ms,
                sample_count=sample_count,
                boundary=boundary,
                estimated_end=estimated_end,
            )
            if state == "sustained" and boundary in {"start", "end", "single"}:
                sustained_boundaries.add(index)
        zero_indices = []

    for index, row in enumerate(rows):
        timestamp = timestamps[index]
        boundary_before = bool(boundary_before_selector(row))
        gap_before = (
            previous_time is not None
            and timestamp is not None
            and (
                timestamp < previous_time
                or (timestamp - previous_time).total_seconds() * 1_000
                > continuous_gap_ms
            )
        )
        if timestamp is None or boundary_before or gap_before:
            flush()
            previous_time = None
        if timestamp is None:
            continue
        value = _finite_number(value_selector(row))
        if value == 0:
            zero_indices.append(index)
            previous_time = timestamp
            continue
        if value is not None:
            flush(timestamp)
            previous_time = timestamp
            continue
        flush()
        previous_time = None
    flush()

    return RssiZeroRunAnalysis(
        metadata_by_index=metadata_by_index,
        sustained_boundary_indices=frozenset(sustained_boundaries),
        sample_interval_ms=sample_interval_ms,
        maximum_continuous_gap_ms=continuous_gap_ms,
        summary=RssiZeroRunSummary(
            suppressed_sample_count=suppressed_sample_count,
            suppressed_run_count=suppressed_run_count,
            sustained_run_count=sustained_run_count,
            sustained_total_duration_ms=sustained_total_duration_ms,
            sustained_longest_duration_ms=sustained_longest_duration_ms,
        ),
    )


def _estimate_sample_interval_ms(
    rows: Sequence[T],
    timestamps: Sequence[datetime | None],
    boundary_before_selector: Callable[[T], bool],
    fallback_sample_interval_ms: object,
) -> int:
    intervals: list[float] = []
    previous: datetime | None = None
    for row, timestamp in zip(rows, timestamps, strict=True):
        if timestamp is None or boundary_before_selector(row):
            previous = timestamp
            continue
        if previous is not None:
            interval = (timestamp - previous).total_seconds() * 1_000
            if MINIMUM_SAMPLE_INTERVAL_MS <= interval <= MAXIMUM_SAMPLE_INTERVAL_MS:
                intervals.append(interval)
        previous = timestamp
    if intervals:
        candidate = median(intervals)
    else:
        fallback = _finite_number(fallback_sample_interval_ms)
        candidate = fallback if fallback is not None and fallback > 0 else DEFAULT_SAMPLE_INTERVAL_MS
    return int(round(max(MINIMUM_SAMPLE_INTERVAL_MS, min(MAXIMUM_SAMPLE_INTERVAL_MS, candidate))))


def _continuous_gap_ms(configured: object, sample_interval_ms: int) -> int:
    value = _finite_number(configured)
    if value is not None and value > 0:
        return int(round(max(sample_interval_ms, min(MAXIMUM_CONTINUOUS_GAP_MS, value))))
    return int(
        round(
            min(
                MAXIMUM_CONTINUOUS_GAP_MS,
                max(MAXIMUM_SAMPLE_INTERVAL_MS, sample_interval_ms * 5),
            )
        )
    )


def _finite_number(value: object) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _format_time(value: datetime) -> str:
    if value.tzinfo is not None:
        return value.isoformat(timespec="milliseconds")
    return value.isoformat(sep=" ", timespec="milliseconds")
