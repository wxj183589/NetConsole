from __future__ import annotations

from datetime import datetime, timedelta
from time import perf_counter

from netconsole.services.mesh_rssi_zero_runs import analyze_rssi_zero_runs


def _analyze(rows, **kwargs):
    return analyze_rssi_zero_runs(
        rows,
        timestamp_selector=lambda row: row.get("timestamp"),
        value_selector=lambda row: row.get("rssi"),
        **kwargs,
    )


def test_single_natural_interval_zero_is_suppressed() -> None:
    rows = [
        {"timestamp": "2026-07-24 20:41:20.000", "rssi": 35},
        {"timestamp": "2026-07-24 20:41:20.984", "rssi": 0},
        {"timestamp": "2026-07-24 20:41:21.968", "rssi": 38},
    ]

    result = _analyze(rows)

    zero = result.metadata_by_index[1]
    assert zero.state == "suppressed"
    assert zero.duration_ms == 984
    assert result.summary.suppressed_sample_count == 1
    assert result.summary.suppressed_run_count == 1
    assert result.sustained_boundary_indices == frozenset()


def test_two_consecutive_zero_samples_are_sustained_even_below_previous_time_threshold() -> None:
    rows = [
        {"timestamp": "2026-07-24 20:41:20.000", "rssi": 35},
        {"timestamp": "2026-07-24 20:41:20.984", "rssi": "0.0"},
        {"timestamp": "2026-07-24 20:41:21.968", "rssi": 0},
        {"timestamp": "2026-07-24 20:41:22.952", "rssi": -38},
    ]

    result = _analyze(rows)

    assert {index: value.boundary for index, value in result.metadata_by_index.items()} == {
        1: "start",
        2: "end",
    }
    assert {value.state for value in result.metadata_by_index.values()} == {"sustained"}
    assert result.metadata_by_index[1].duration_ms == 1_968
    assert result.metadata_by_index[1].end_time == "2026-07-24 20:41:22.952"
    assert result.sustained_boundary_indices == frozenset({1, 2})
    assert result.summary.sustained_run_count == 1
    assert result.summary.sustained_total_duration_ms == 1_968


def test_single_zero_is_suppressed_even_when_the_time_gap_is_long() -> None:
    rows = [
        {"timestamp": "2026-07-24 20:41:20.000", "rssi": 35},
        {"timestamp": "2026-07-24 20:41:21.000", "rssi": 0},
        {"timestamp": "2026-07-24 20:41:24.000", "rssi": 38},
    ]

    result = _analyze(rows, maximum_continuous_gap_ms=5_000)

    assert result.metadata_by_index[1].duration_ms == 3_000
    assert result.metadata_by_index[1].state == "suppressed"
    assert result.summary.suppressed_sample_count == 1


def test_tail_zero_run_uses_bounded_estimated_interval() -> None:
    sustained = _analyze(
        [
            {"timestamp": "2026-07-24 20:41:20.000", "rssi": 35},
            {"timestamp": "2026-07-24 20:41:21.000", "rssi": 0},
            {"timestamp": "2026-07-24 20:41:22.000", "rssi": 0},
            {"timestamp": "2026-07-24 20:41:23.000", "rssi": 0},
        ],
        fallback_sample_interval_ms=float("nan"),
    )
    short = _analyze(
        [{"timestamp": "2026-07-24 20:41:20.000", "rssi": 35}, {"timestamp": "2026-07-24 20:41:21.000", "rssi": 0}],
        fallback_sample_interval_ms=99_000,
    )

    assert sustained.sample_interval_ms == 1_000
    assert sustained.metadata_by_index[3].state == "sustained"
    assert sustained.metadata_by_index[3].estimated_end is True
    assert sustained.metadata_by_index[3].end_time == "2026-07-24 20:41:24.000"
    assert short.sample_interval_ms == 1_000
    assert short.metadata_by_index[1].state == "suppressed"


def test_missing_invalid_and_large_gap_end_zero_runs_without_false_bridge() -> None:
    rows = [
        {"timestamp": "2026-07-24 20:41:00.000", "rssi": 35},
        {"timestamp": "2026-07-24 20:41:01.000", "rssi": 0},
        {"timestamp": "2026-07-24 20:41:30.000", "rssi": 38},
        {"timestamp": "2026-07-24 20:41:31.000", "rssi": None},
        {"timestamp": "invalid", "rssi": 0},
        {"timestamp": "2026-07-24 20:41:32.000", "rssi": "not-a-number"},
    ]

    result = _analyze(rows)

    assert result.metadata_by_index[1].state == "suppressed"
    assert result.metadata_by_index[1].duration_ms == 1_000
    assert 4 not in result.metadata_by_index
    assert result.summary.sustained_run_count == 0


def test_explicit_boundary_splits_runs() -> None:
    rows = [
        {"timestamp": "2026-07-24 20:41:00.000", "rssi": 0, "break": False},
        {"timestamp": "2026-07-24 20:41:01.000", "rssi": 0, "break": True},
        {"timestamp": "2026-07-24 20:41:02.000", "rssi": 38, "break": False},
    ]

    result = _analyze(rows, boundary_before_selector=lambda row: bool(row.get("break")))

    assert result.metadata_by_index[0].duration_ms == 1_000
    assert result.metadata_by_index[1].duration_ms == 1_000
    assert result.summary.suppressed_run_count == 2


def test_zero_run_analysis_scales_linearly_to_100_000_points() -> None:
    base = datetime.fromisoformat("2026-07-24T20:00:00+00:00")
    rows = [
        {
            "timestamp": base + timedelta(seconds=index),
            "rssi": 0 if index % 50 in {1, 2, 3, 4} else 35 + index % 20,
        }
        for index in range(100_000)
    ]

    started = perf_counter()
    result = _analyze(rows)
    elapsed = perf_counter() - started

    assert result.summary.sustained_run_count > 0
    assert len(result.metadata_by_index) == 8_000
    assert elapsed < 5.0
