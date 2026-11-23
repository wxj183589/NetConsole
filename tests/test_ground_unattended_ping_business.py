from __future__ import annotations

from netconsole.services.ground_unattended.ping_business import (
    classify_heartbeat_status,
    classify_status,
    natural_second_loss_buckets,
    normalize_status,
    point_values,
    selected_statistics,
)


def _row(stamp: str, sample_id: str, sample: dict[str, object]) -> dict[str, object]:
    return {"received_at": stamp, "sample_id": sample_id, "sample": sample}


def test_status_classification_preserves_explicit_precedence_and_aliases() -> None:
    assert normalize_status("timed-out") == "TIMEOUT"
    assert normalize_status("timed -   out") == "TIMEOUT"
    assert classify_status({"status": "ok", "ok": False, "error": "timeout"}) == "SUCCESS"
    assert classify_status({"status": "UNKNOWN", "state": "OK", "ok": True, "rtt_ms": 1}) == "UNKNOWN"
    assert classify_status({"ok": False, "error": "timed_out"}) == "TIMEOUT"
    assert classify_status({"ok": False, "error": "unreachable"}) == "PACKET_LOSS"
    assert classify_status({"ok": True, "rtt_ms": None}) == "UNKNOWN"
    assert classify_heartbeat_status({"ok": True, "rtt_ms": None}) == "SUCCESS"


def test_point_values_are_backend_display_contract() -> None:
    assert point_values({"ok": True, "rtt_ms": 2.5}) == {
        "normalized_status": None,
        "status": "SUCCESS",
        "heartbeat_status": "SUCCESS",
        "loss_percent": 0.0,
        "rtt_display_ms": 2.5,
    }
    assert point_values({"ok": False, "timeout": True, "rtt_ms": None})["rtt_display_ms"] is None
    assert point_values({"ok": False, "timeout": True, "rtt_ms": None})["loss_percent"] == 100.0


def test_natural_second_buckets_are_half_open_and_deduplicated() -> None:
    rows = [
        _row("2026-11-22T00:00:00.000Z", "a", {"ok": True, "rtt_ms": 2.5}),
        _row("2026-11-22T00:00:00.999Z", "b", {"ok": False, "timeout": True}),
        _row("2026-11-22T00:00:00.999Z", "b", {"ok": False, "timeout": True}),
        _row("2026-11-22T00:00:01.000Z", "c", {"ok": True, "rtt_ms": 3.5}),
    ]
    buckets = natural_second_loss_buckets(rows)
    assert len(buckets) == 2
    assert buckets[0]["start"] == "2026-11-22T00:00:00.000Z"
    assert buckets[0]["ping_total"] == 2
    assert buckets[0]["ping_success"] == 1
    assert buckets[0]["ping_lost"] == 1
    assert buckets[0]["packet_loss_rate"] == 50.0
    assert buckets[1]["ping_total"] == 1


def test_selected_statistics_ignore_duplicate_rows_and_unknown_rtt() -> None:
    rows = [
        _row("2026-11-22T00:00:00.100Z", "a", {"status": "UNKNOWN", "rtt_ms": None}),
        _row("2026-11-22T00:00:00.100Z", "a", {"status": "UNKNOWN", "rtt_ms": None}),
        _row("2026-11-22T00:00:00.200Z", "b", {"status": "TIMEOUT", "rtt_ms": None}),
        _row("2026-11-22T00:00:00.300Z", "c", {"status": "SUCCESS", "rtt_ms": 4}),
    ]
    assert selected_statistics(rows) == {
        "ping_total": 3,
        "ping_success": 1,
        "ping_lost": 1,
        "ping_unknown": 1,
        "packet_loss_rate": 33.33333333333333,
        "min_rtt_ms": 4.0,
        "average_rtt_ms": 4.0,
        "max_rtt_ms": 4.0,
    }
