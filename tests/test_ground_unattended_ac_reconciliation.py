from __future__ import annotations

from pathlib import Path

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.ac_reconciliation import (
    AC_DELTA_ADDED,
    AC_DELTA_REMOVED,
    AC_DELTA_UNCHANGED,
    AC_DELTA_UNKNOWN,
    AC_DELTA_UPDATED,
    AcSnapshotEnvelope,
    RECONCILIATION_AC_NEWER,
    RECONCILIATION_CONSISTENT,
    RECONCILIATION_STALE,
    RECONCILIATION_SYSLOG_NEWER,
    diff_full_snapshot,
    reconcile_syslog_ac,
)


def _snapshot(snapshot_id: str, rows: tuple[dict, ...], *, at: str, status: str = "fresh", complete: bool = True) -> AcSnapshotEnvelope:
    return AcSnapshotEnvelope(
        controller_id="ac-sim-1",
        snapshot_id=snapshot_id,
        rows=rows,
        device_time=at,
        received_at=at,
        data_status=status,
        complete=complete,
    )


def _row(mr_id: str, ap: str, *, rssi: int = -50) -> dict:
    return {
        "mr_id": mr_id,
        "train_id": f"train-{mr_id}",
        "peer_ap_name": ap,
        "peer_ap_mac": f"00:00:00:00:00:{mr_id[-1]}",
        "rssi": rssi,
    }


def test_full_snapshot_diff_retains_history_and_classifies_all_changes() -> None:
    previous = _snapshot(
        "1",
        (_row("mr-1", "AP-A"), _row("mr-2", "AP-B"), _row("mr-3", "AP-C")),
        at="2026-11-10T10:00:00+08:00",
    )
    current = _snapshot(
        "2",
        (
            _row("mr-1", "AP-A"),
            _row("mr-2", "AP-D"),
            _row("mr-4", "AP-E"),
            {"train_id": "train-unknown", "peer_ap_name": "AP-X"},
        ),
        at="2026-11-10T10:00:05+08:00",
    )

    result = diff_full_snapshot(previous, current)

    assert result.accepted is True
    assert result.counts == {
        AC_DELTA_ADDED: 1,
        AC_DELTA_REMOVED: 1,
        AC_DELTA_UNCHANGED: 1,
        AC_DELTA_UNKNOWN: 1,
        AC_DELTA_UPDATED: 1,
    }
    assert {item.entity_key for item in result.records if item.change_type == AC_DELTA_REMOVED} == {"mr:mr-3"}
    assert all(item.safe_to_apply for item in result.records if item.change_type != AC_DELTA_UNKNOWN)
    assert all(not item.safe_to_apply for item in result.records if item.change_type == AC_DELTA_UNKNOWN)


def test_stale_or_incomplete_snapshot_cannot_generate_removals() -> None:
    previous = _snapshot(
        "1", (_row("mr-1", "AP-A"), _row("mr-2", "AP-B")), at="2026-11-10T10:00:10+08:00"
    )
    stale = _snapshot(
        "0", (_row("mr-1", "AP-A"),), at="2026-11-10T10:00:00+08:00", status="stale"
    )
    result = diff_full_snapshot(previous, stale)

    assert result.accepted is False
    assert result.reason == "OLDER_THAN_PREVIOUS_SNAPSHOT"
    assert not any(item.change_type == AC_DELTA_REMOVED for item in result.records)
    assert all(item.change_type == AC_DELTA_UNKNOWN for item in result.records)
    assert all(not item.safe_to_apply for item in result.records)


def test_delayed_ac_does_not_replace_newer_syslog_position() -> None:
    syslog = {
        "device_uuid": "mr-1",
        "current_ap_name": "AP-B",
        "current_ap_mac": "00:00:00:00:00:0b",
        "last_event_time": "2026-11-10T10:00:01+08:00",
        "last_event_time_source": "DEVICE_TIME",
        "last_receive_time": "2026-11-10T10:00:02+08:00",
    }
    delayed_ac = {
        "mr_id": "mr-1",
        "peer_ap_name": "AP-A",
        "peer_ap_mac": "00:00:00:00:00:0a",
        "device_time": "2026-11-10T09:59:59+08:00",
        "received_at": "2026-11-10T10:00:05+08:00",
    }
    result = reconcile_syslog_ac(
        syslog,
        delayed_ac,
        now="2026-11-10T10:00:06+08:00",
        stale_after_seconds=60,
    )

    assert result.state == RECONCILIATION_SYSLOG_NEWER
    assert result.syslog_identity == "00000000000b"
    assert result.ac_identity == "00000000000a"


def test_reconciliation_distinguishes_consistent_ac_newer_and_stale() -> None:
    base_syslog = {
        "device_uuid": "mr-1",
        "current_ap_name": "AP-A",
        "last_event_time": "2026-11-10T10:00:01+08:00",
        "last_event_time_source": "DEVICE_TIME",
        "last_receive_time": "2026-11-10T10:00:02+08:00",
    }
    matching_ac = {
        "mr_id": "mr-1",
        "peer_ap_name": "AP-A",
        "device_time": "2026-11-10T10:00:00+08:00",
        "received_at": "2026-11-10T10:00:03+08:00",
    }
    assert reconcile_syslog_ac(
        base_syslog, matching_ac, now="2026-11-10T10:00:04+08:00", stale_after_seconds=60
    ).state == RECONCILIATION_CONSISTENT

    ac_newer = {**matching_ac, "peer_ap_name": "AP-B", "device_time": "2026-11-10T10:00:05+08:00"}
    assert reconcile_syslog_ac(
        base_syslog, ac_newer, now="2026-11-10T10:00:06+08:00", stale_after_seconds=60
    ).state == RECONCILIATION_AC_NEWER

    assert reconcile_syslog_ac(
        base_syslog, matching_ac, now="2026-11-10T12:00:00+08:00", stale_after_seconds=60
    ).state == RECONCILIATION_STALE


def test_delta_and_reconciliation_evidence_is_persisted_additively(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    current = _snapshot(
        "snapshot-1",
        (_row("mr-1", "AP-A"),),
        at="2026-11-10T10:00:00+08:00",
    )
    delta = diff_full_snapshot(None, current)
    assert repository.insert_ac_delta_rows(
        item.to_record(
            site_id="site-a",
            run_id="run-1",
            created_at="2026-11-10T10:00:01+08:00",
        )
        for item in delta.records
    ) == 1

    evidence = reconcile_syslog_ac(
        {
            "device_uuid": "mr-1",
            "current_ap_name": "AP-B",
            "last_event_time": "2026-11-10T10:00:02+08:00",
            "last_event_time_source": "DEVICE_TIME",
        },
        {
            "mr_id": "mr-1",
            "peer_ap_name": "AP-A",
            "device_time": "2026-11-10T10:00:00+08:00",
        },
        now="2026-11-10T10:00:03+08:00",
    )
    assert repository.upsert_position_reconciliations(
        [evidence.to_record(site_id="site-a", run_id="run-1", observed_at="2026-11-10T10:00:03+08:00")]
    ) == 1

    deltas = repository.list_ac_deltas("run-1")
    reconciliation = repository.get_position_reconciliation("run-1", "mr-1")
    assert deltas[0]["change_type"] == AC_DELTA_ADDED
    assert deltas[0]["safe_to_apply"] is True
    assert reconciliation is not None
    assert reconciliation["state"] == RECONCILIATION_SYSLOG_NEWER
