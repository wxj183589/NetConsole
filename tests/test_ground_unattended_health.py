from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from netconsole.models.api.ground_unattended import GroundAcPollerHealthDTO
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)


def _service(tmp_path):
    service = object.__new__(GroundUnattendedApplicationService)
    service.site_id = "demo"
    service.paths = SimpleNamespace(ground_unattended_root=lambda _site: tmp_path)
    service.repository = SimpleNamespace(
        latest_health_event=lambda: {"severity": "info", "message": "正常运行"},
        list_archives=lambda: [],
        get_active_run=lambda: None,
        get_profile=lambda: SimpleNamespace(fleet_ping_timeout_ms=4000),
        count_raw_files=lambda: 7,
    )
    service.supervisor = SimpleNamespace(
        running=True,
        fleet_ping=SimpleNamespace(
            target_count=2, process_count=1, sample_rate_per_second=2.0,
            last_sample_at="2026-11-07T10:00:00+08:00",
            last_sample_write_duration_ms=1.2, worker_warnings=[],
        ),
    )
    service._syslog_health = lambda: {}
    service._ac_poller_health = lambda *_: []
    service.deep_collections = lambda _: SimpleNamespace(items=[])
    return service


def test_health_exposes_existing_metrics_and_does_not_treat_info_as_error(tmp_path):
    health = _service(tmp_path).health("demo")
    assert health.status == "HEALTHY"
    assert health.last_error == ""
    assert health.supervisor_running is True
    assert health.ping_sample_rate_per_second == 2.0
    assert health.ping_sample_write_duration_ms == 1.2
    assert health.ping_last_sample_at == "2026-11-07T10:00:00+08:00"
    assert health.disk_total_bytes > 0
    assert health.raw_file_count == 7
    assert health.run_elapsed_seconds is None


@pytest.mark.parametrize("metrics, expected", [
    ({"raw_write_failed_count": 1}, "CRITICAL"),
    ({"udp_dropped_count": 1}, "CRITICAL"),
    ({"spool_guard_state": "EMERGENCY"}, "CRITICAL"),
    ({"spool_guard_state": "CRITICAL"}, "CRITICAL"),
    ({"udp_running": True, "writer_alive": False}, "CRITICAL"),
    ({"last_error": "磁盘不可写"}, "DEGRADED"),
    ({"compression_failed_count": 1}, "DEGRADED"),
    ({"compression_skipped_count": 1}, "DEGRADED"),
    ({"spool_guard_state": "WARNING"}, "DEGRADED"),
    ({"udp_queue_pressure": 0.9}, "DEGRADED"),
])
def test_health_reports_current_pipeline_faults(tmp_path, metrics, expected):
    service = _service(tmp_path)
    service._syslog_health = lambda: dict(metrics)
    assert service.health("demo").status == expected


def test_auxiliary_ac_failure_only_degrades_observed_healthy_engine(tmp_path):
    service = _service(tmp_path)
    service._ac_poller_health = lambda *_: [
        GroundAcPollerHealthDTO(controller_id="ac", status="CRITICAL")
    ]
    assert service.health("demo").status == "DEGRADED"


def test_health_unknown_without_observable_runtime(tmp_path):
    service = _service(tmp_path)
    service.supervisor = SimpleNamespace(fleet_ping=SimpleNamespace())
    service.repository.latest_health_event = lambda: {
        "severity": "error", "message": "上一次运行的错误"
    }
    health = service.health("demo")
    assert health.status == "UNKNOWN"
    assert health.last_error == "上一次运行的错误"
    assert health.supervisor_running is None
    assert health.ping_sample_rate_per_second is None


@pytest.mark.parametrize("age, supervisor_running, udp_running, expected", [
    (1, True, False, "HEALTHY"),
    (30, True, False, "CRITICAL"),
    (1, False, True, "CRITICAL"),
    (30, True, True, "HEALTHY"),
])
def test_running_lifecycle_checks_allow_startup_grace(
    tmp_path, age, supervisor_running, udp_running, expected
):
    service = _service(tmp_path)
    service.supervisor.running = supervisor_running
    started = datetime.now().astimezone() - timedelta(seconds=age)
    service.repository.get_active_run = lambda: {
        "state": "RUNNING", "actual_started_at": started.isoformat()
    }
    service._syslog_health = lambda: {"udp_running": udp_running}
    health = service.health("demo")
    assert health.status == expected
    assert health.run_elapsed_seconds >= age


def test_archive_failures_are_separate_from_pending(tmp_path):
    service = _service(tmp_path)
    service.repository.list_archives = lambda: [
        {"archive_status": status} for status in ("PENDING", "BUILDING", "FAILED", "READY")
    ]
    health = service.health("demo")
    assert health.archive_pending_count == 2
    assert health.archive_failed_count == 1
    assert health.status == "DEGRADED"
