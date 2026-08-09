from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from netconsole.services.online_mr.session_time_alignment import (
    SessionTimeAlignment,
    TimeAlignmentAnchor,
)


def _anchor(collector: datetime, collector_minus_device_ms: float) -> TimeAlignmentAnchor:
    return TimeAlignmentAnchor(
        collector_time=collector,
        device_time=collector - timedelta(milliseconds=collector_minus_device_ms),
    )


def test_fixed_offset_maps_collector_time_to_mr_device_time() -> None:
    start = datetime(2026, 7, 21, 12, 0, 4, 250_000)
    alignment = SessionTimeAlignment.from_anchors(
        [_anchor(start + timedelta(seconds=index), 4_250.0) for index in range(20)]
    )

    result = alignment.collector_to_device(datetime(2026, 7, 21, 12, 0, 10, 250_000))

    assert result.normalized_time == datetime(2026, 7, 21, 12, 0, 6)
    assert result.correction_ms == pytest.approx(-4_250.0)
    assert alignment.offset_median_ms == pytest.approx(4_250.0)
    assert alignment.method == "fixed-offset"
    assert alignment.confidence == "high"


def test_linear_drift_maps_twenty_minute_session() -> None:
    start = datetime(2026, 7, 21, 12, 0, 4, 200_000)
    anchors = []
    for minute in range(21):
        offset = 4_200.0 + 15.0 * minute
        anchors.append(_anchor(start + timedelta(minutes=minute), offset))
    alignment = SessionTimeAlignment.from_anchors(anchors)

    result = alignment.collector_to_device(start + timedelta(minutes=20, seconds=6, milliseconds=300))

    assert alignment.method == "linear-drift"
    assert alignment.drift_ms_per_minute == pytest.approx(15.0)
    assert result.normalized_time == pytest.approx(
        datetime(2026, 7, 21, 12, 20, 6),
        abs=timedelta(milliseconds=2),
    )


def test_outliers_do_not_pollute_fixed_offset() -> None:
    start = datetime(2026, 7, 21, 12, 0, 4, 250_000)
    anchors = [
        _anchor(start + timedelta(seconds=index), 4_250.0 + (index % 5 - 2) * 20.0)
        for index in range(40)
    ]
    anchors.extend(
        [
            _anchor(start + timedelta(seconds=7), 65_000.0),
            _anchor(start + timedelta(seconds=19), -40_000.0),
        ]
    )

    alignment = SessionTimeAlignment.from_anchors(anchors)

    assert alignment.inlier_count == 40
    assert alignment.offset_median_ms == pytest.approx(4_250.0)
    assert alignment.confidence == "high"
    assert "剔除 2 个异常时间锚点" in alignment.warning


def test_missing_and_single_anchor_report_explicit_low_confidence() -> None:
    missing = SessionTimeAlignment.from_anchors([])
    single = SessionTimeAlignment.from_anchors(
        [_anchor(datetime(2026, 7, 21, 12, 0, 4, 250_000), 4_250.0)]
    )

    assert missing.collector_to_device(datetime(2026, 7, 21, 12, 0, 10)).normalized_time is None
    assert missing.method == "none"
    assert missing.confidence == "low"
    assert single.method == "fixed-offset"
    assert single.confidence == "low"
    assert single.collector_to_device(datetime(2026, 7, 21, 12, 0, 10, 250_000)).normalized_time == datetime(
        2026, 7, 21, 12, 0, 6
    )


def test_device_to_collector_inverts_linear_alignment() -> None:
    start = datetime(2026, 7, 21, 12, 0, 4, 200_000)
    alignment = SessionTimeAlignment.from_anchors(
        [
            _anchor(start + timedelta(minutes=minute), 4_200.0 + 15.0 * minute)
            for minute in range(21)
        ]
    )
    collector = start + timedelta(minutes=13, seconds=2)
    normalized = alignment.collector_to_device(collector).normalized_time

    assert normalized is not None
    assert alignment.device_to_collector(normalized) == pytest.approx(collector, abs=timedelta(microseconds=1))
