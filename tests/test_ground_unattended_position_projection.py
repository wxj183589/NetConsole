from __future__ import annotations

from datetime import datetime

from netconsole.services.ground_unattended.application_service import (
    _syslog_position_projection,
)


def test_stale_syslog_position_never_falls_back_to_ac_as_active_peer() -> None:
    now = datetime.fromisoformat("2026-11-10T10:05:00+08:00")

    projection = _syslog_position_projection(
        {
            "current_ap_name": "SYSLOG-AP-A",
            "position_status": "VALID",
            "position_quality": "EXACT_IDENTITY",
            "last_receive_time": "2026-11-10T10:00:00+08:00",
            "last_switch_time": "",
        },
        now=now,
        stale_after_seconds=120,
    )

    assert projection == {
        "position_freshness": "STALE",
        "current_active_peer": "",
        "last_link_switch_at": "",
    }


def test_fresh_disconnected_syslog_position_is_not_an_active_peer() -> None:
    now = datetime.fromisoformat("2026-11-10T10:05:00+08:00")

    projection = _syslog_position_projection(
        {
            "current_ap_name": "SYSLOG-AP-A",
            "position_status": "DISCONNECTED",
            "position_quality": "EXACT_IDENTITY",
            "last_receive_time": "2026-11-10T10:04:30+08:00",
            "last_switch_time": "2026-11-10T10:04:00+08:00",
        },
        now=now,
        stale_after_seconds=120,
    )

    assert projection["position_freshness"] == "DISCONNECTED"
    assert projection["current_active_peer"] == ""
    assert projection["last_link_switch_at"] == "2026-11-10T10:04:00+08:00"
