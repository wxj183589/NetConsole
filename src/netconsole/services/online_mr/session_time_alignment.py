from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable


MIN_LINEAR_SPAN_MINUTES = 10.0
MIN_LINEAR_DRIFT_MS = 250.0
MIN_INLIER_WINDOW_MS = 1_000.0
MAX_INLIER_WINDOW_MS = 5_000.0


@dataclass(frozen=True)
class TimeAlignmentAnchor:
    collector_time: datetime
    device_time: datetime
    source: str = "mesh_link_display_clock"

    @property
    def device_minus_collector_ms(self) -> float:
        return (self.device_time - self.collector_time).total_seconds() * 1_000.0


@dataclass(frozen=True)
class TimeAlignmentResult:
    normalized_time: datetime | None
    correction_ms: float | None
    method: str
    confidence: str


@dataclass(frozen=True)
class SessionTimeAlignment:
    anchor_count: int
    inlier_count: int
    offset_median_ms: float | None
    offset_p05_ms: float | None
    offset_p95_ms: float | None
    drift_ms_per_minute: float | None
    method: str
    confidence: str
    reference_collector_time: datetime | None
    device_delta_intercept_ms: float | None
    device_delta_slope_ms_per_minute: float
    warning: str = ""

    @classmethod
    def from_anchors(cls, anchors: Iterable[TimeAlignmentAnchor]) -> SessionTimeAlignment:
        rows = sorted(anchors, key=lambda item: item.collector_time)
        if not rows:
            return cls(
                anchor_count=0,
                inlier_count=0,
                offset_median_ms=None,
                offset_p05_ms=None,
                offset_p95_ms=None,
                drift_ms_per_minute=None,
                method="none",
                confidence="low",
                reference_collector_time=None,
                device_delta_intercept_ms=None,
                device_delta_slope_ms_per_minute=0.0,
                warning="没有可用的 MR 设备时钟锚点，外部指标保留采集端时间。",
            )

        deltas = [row.device_minus_collector_ms for row in rows]
        center = float(median(deltas))
        absolute_deviations = [abs(value - center) for value in deltas]
        mad = float(median(absolute_deviations))
        inlier_window = min(MAX_INLIER_WINDOW_MS, max(MIN_INLIER_WINDOW_MS, mad * 6.0))
        inliers = [row for row in rows if abs(row.device_minus_collector_ms - center) <= inlier_window]
        if not inliers:
            inliers = rows

        reference = inliers[0].collector_time
        x_minutes = [(row.collector_time - reference).total_seconds() / 60.0 for row in inliers]
        y_delta = [row.device_minus_collector_ms for row in inliers]
        fixed_delta = float(median(y_delta))
        span_minutes = max(x_minutes) - min(x_minutes) if len(x_minutes) > 1 else 0.0

        slope = 0.0
        intercept = fixed_delta
        linear_candidate = False
        if len(inliers) >= 3 and span_minutes > 0:
            x_mean = sum(x_minutes) / len(x_minutes)
            y_mean = sum(y_delta) / len(y_delta)
            denominator = sum((value - x_mean) ** 2 for value in x_minutes)
            if denominator > 0:
                fitted_slope = sum(
                    (x_value - x_mean) * (y_value - y_mean)
                    for x_value, y_value in zip(x_minutes, y_delta, strict=True)
                ) / denominator
                fitted_intercept = y_mean - fitted_slope * x_mean
                residuals = [
                    y_value - (fitted_intercept + fitted_slope * x_value)
                    for x_value, y_value in zip(x_minutes, y_delta, strict=True)
                ]
                residual_spread = _percentile(residuals, 0.95) - _percentile(residuals, 0.05)
                projected_drift = abs(fitted_slope * span_minutes)
                linear_candidate = (
                    span_minutes >= MIN_LINEAR_SPAN_MINUTES
                    and projected_drift >= MIN_LINEAR_DRIFT_MS
                    and projected_drift >= residual_spread * 0.5
                )
                if linear_candidate:
                    slope = fitted_slope
                    intercept = fitted_intercept

        collector_offsets = sorted(-row.device_minus_collector_ms for row in inliers)
        offset_p05 = _percentile(collector_offsets, 0.05)
        offset_p95 = _percentile(collector_offsets, 0.95)
        spread = offset_p95 - offset_p05
        inlier_ratio = len(inliers) / len(rows)
        if len(inliers) >= 10 and inlier_ratio >= 0.75 and spread <= 2_000.0:
            confidence = "high"
        elif len(inliers) >= 3 and inlier_ratio >= 0.5 and spread <= 5_000.0:
            confidence = "medium"
        else:
            confidence = "low"

        warning = ""
        if confidence == "low":
            warning = "时间锚点不足或波动过大，校正结果仅供参考。"
        elif len(inliers) < len(rows):
            warning = f"已剔除 {len(rows) - len(inliers)} 个异常时间锚点。"

        return cls(
            anchor_count=len(rows),
            inlier_count=len(inliers),
            offset_median_ms=float(median(collector_offsets)),
            offset_p05_ms=offset_p05,
            offset_p95_ms=offset_p95,
            drift_ms_per_minute=(-slope if linear_candidate else 0.0),
            method="linear-drift" if linear_candidate else "fixed-offset",
            confidence=confidence,
            reference_collector_time=reference,
            device_delta_intercept_ms=intercept,
            device_delta_slope_ms_per_minute=slope,
            warning=warning,
        )

    def collector_to_device(self, collector_time: datetime) -> TimeAlignmentResult:
        if self.reference_collector_time is None or self.device_delta_intercept_ms is None:
            return TimeAlignmentResult(None, None, "none", "low")
        elapsed_minutes = (collector_time - self.reference_collector_time).total_seconds() / 60.0
        correction_ms = self.device_delta_intercept_ms + self.device_delta_slope_ms_per_minute * elapsed_minutes
        return TimeAlignmentResult(
            normalized_time=collector_time + timedelta(milliseconds=correction_ms),
            correction_ms=correction_ms,
            method=self.method,
            confidence=self.confidence,
        )

    def device_to_collector(self, device_time: datetime) -> datetime | None:
        if self.reference_collector_time is None or self.device_delta_intercept_ms is None:
            return None
        reference_ms = self.reference_collector_time.timestamp() * 1_000.0
        device_ms = device_time.timestamp() * 1_000.0
        slope_per_ms = self.device_delta_slope_ms_per_minute / 60_000.0
        denominator = 1.0 + slope_per_ms
        if abs(denominator) < 1e-9:
            return None
        collector_ms = (
            device_ms - self.device_delta_intercept_ms + slope_per_ms * reference_ms
        ) / denominator
        return datetime.fromtimestamp(collector_ms / 1_000.0, tz=device_time.tzinfo)


def _percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, quantile))
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


__all__ = ["SessionTimeAlignment", "TimeAlignmentAnchor", "TimeAlignmentResult"]
