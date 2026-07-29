from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api import main as api_main
from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.models.api.rail_transit_base_data import VehicleMrDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
    GroundUnattendedError,
)
from netconsole.services.ground_unattended.schedule import schedule_window


def test_ground_unattended_default_profile_does_not_overwrite_concurrent_save(
    tmp_path, monkeypatch
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground-unattended.sqlite", site_id="demo"
    )
    concurrent_repository = GroundUnattendedRepository(
        repository.db_path, site_id="demo"
    )
    original_transaction = repository._transaction

    @contextmanager
    def concurrent_transaction():
        concurrent_repository.save_profile(
            GroundUnattendedProfileDTO(site_id="demo", enabled=True)
        )
        with original_transaction() as connection:
            yield connection

    monkeypatch.setattr(repository, "_transaction", concurrent_transaction)

    assert repository.get_profile().enabled is True


def test_ground_unattended_profile_status_and_actions_are_site_scoped(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    with TestClient(create_app(paths=paths)) as client:
        profile = client.get("/api/rail-transit/ground-unattended/profile")
        assert profile.status_code == 200
        assert profile.json()["schedule_start_time"] == "07:00"
        payload = profile.json()
        payload.update(
            {
                "enabled": True,
                "schedule_start_time": "08:00",
                "schedule_end_time": "22:30",
                "syslog_server_ip": "192.0.2.100",
                "allow_external_syslog_address": True,
                "external_syslog_address_confirmation": True,
            }
        )
        saved = client.put("/api/rail-transit/ground-unattended/profile", json=payload)
        assert saved.status_code == 200
        assert saved.json()["schedule_end_time"] == "22:30"
        started = client.post("/api/rail-transit/ground-unattended/start")
        assert started.status_code == 202
        status = client.get("/api/rail-transit/ground-unattended/status")
        assert status.status_code == 200
        assert status.json()["site_id"] == "demo"


def test_ground_unattended_rejects_invalid_bound_site(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    app.state.ground_unattended_application_service.site_id = "../invalid"

    with TestClient(app) as client:
        response = client.get("/api/rail-transit/ground-unattended/profile")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SITE_INVALID"


def test_ground_unattended_rejects_invalid_profile_and_archive_delete_without_confirmation(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    with TestClient(create_app(paths=paths)) as client:
        payload = client.get("/api/rail-transit/ground-unattended/profile").json()
        payload["schedule_end_time"] = payload["schedule_start_time"]
        response = client.put(
            "/api/rail-transit/ground-unattended/profile", json=payload
        )
        assert response.status_code == 422
        missing = client.request(
            "DELETE",
            "/api/rail-transit/ground-unattended/archives/missing",
            json={"explicit_confirmation": False},
        )
        assert missing.status_code in {404, 409}


def test_ground_profile_requires_local_address_or_confirmed_external_nat(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    with TestClient(app) as client:
        disabled = client.get(
            "/api/rail-transit/ground-unattended/profile"
        ).json()
        disabled["syslog_server_ip"] = ""
        assert client.put(
            "/api/rail-transit/ground-unattended/profile",
            json=disabled,
        ).status_code == 200

        unspecified = {
            **disabled,
            "enabled": True,
            "syslog_server_ip": "0.0.0.0",
        }
        assert client.put(
            "/api/rail-transit/ground-unattended/profile",
            json=unspecified,
        ).status_code == 422

        external = {
            **disabled,
            "enabled": True,
            "syslog_server_ip": "192.0.2.100",
        }
        blocked = client.put(
            "/api/rail-transit/ground-unattended/profile",
            json=external,
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "SYSLOG_TARGET_NOT_LOCAL"

        needs_confirmation = client.put(
            "/api/rail-transit/ground-unattended/profile",
            json={**external, "allow_external_syslog_address": True},
        )
        assert needs_confirmation.status_code == 409
        assert (
            needs_confirmation.json()["detail"]["code"]
            == "EXTERNAL_SYSLOG_CONFIRMATION_REQUIRED"
        )

        saved = client.put(
            "/api/rail-transit/ground-unattended/profile",
            json={
                **external,
                "allow_external_syslog_address": True,
                "external_syslog_address_confirmation": True,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["syslog_server_ip"] == "192.0.2.100"


def test_ground_unattended_empty_pages_are_stable(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    with TestClient(create_app(paths=paths)) as client:
        trains = client.get("/api/rail-transit/ground-unattended/trains")
        assert trains.status_code == 200
        assert trains.json()["items"]
        assert trains.json()["items"][0]["eligibility_status"] == "AC_UNKNOWN"
        for path in (
            "ping-targets",
            "ping-samples",
            "syslog-records",
            "deep-collections",
            "coverage",
            "timeline",
            "archives",
        ):
            response = client.get(f"/api/rail-transit/ground-unattended/{path}")
            assert response.status_code == 200, path
            assert response.json()["items"] == []
        series = client.get("/api/rail-transit/ground-unattended/ping-series")
        assert series.status_code == 200
        assert series.json()["points"] == []
        operation = client.get(
            "/api/rail-transit/ground-unattended/operations/latest"
        )
        assert operation.status_code == 200
        assert operation.json() is None


def test_ground_unattended_legacy_run_and_persisted_ping_summary_are_api_compatible(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run = repository.create_or_get_run(
        run_id="legacy-run",
        run_date="2026-07-27",
        scheduled_start_at="2026-07-27T07:00:00+08:00",
        scheduled_end_at="2026-07-27T23:00:00+08:00",
    )
    repository.update_run(
        str(run["run_id"]),
        state="running",
        summary_json=json.dumps("legacy-summary"),
    )
    repository.upsert_ping_summary(
        {
            "site_id": "demo",
            "run_id": str(run["run_id"]),
            "bucket_kind": "daily",
            "bucket_start": "2026-07-27T00:00:00+08:00",
            "bucket_end": "2026-07-28T00:00:00+08:00",
            "target_ip": "10.8.0.6",
            "train_id": "train-06",
            "train_no": "06",
            "mr_id": "mr-06-ct",
            "mr_position_code": "CT",
            "ac_snapshot_id": None,
            "ap_identity": "",
            "raw_sample_count": 10,
            "warmup_ignored_count": 0,
            "sent_count": 10,
            "success_count": 9,
            "loss_count": 1,
            "loss_rate_percent": 10.0,
            "min_rtt_ms": 1.0,
            "avg_rtt_ms": 2.0,
            "max_rtt_ms": 3.0,
            "continuous_loss_max_count": 1,
            "continuous_loss_max_seconds": 1.0,
            "created_at": "2026-07-27T23:00:00+08:00",
        }
    )

    client = TestClient(app, raise_server_exceptions=False)
    status = client.get("/api/rail-transit/ground-unattended/status")
    ping_targets = client.get(
        "/api/rail-transit/ground-unattended/ping-targets"
    )
    client.close()

    assert status.status_code == 200
    assert status.json()["state"] == "RUNNING"
    assert status.json()["disk_used_bytes"] == 0
    assert ping_targets.status_code == 200
    item = ping_targets.json()["items"][0]
    assert item["run_id"] == "legacy-run"
    assert item["run_date"] == "2026-07-27"
    assert item["target_ip"] == "10.8.0.6"
    assert item["mr_id"] == "mr-06-ct"
    assert item["raw_sample_count"] == 10
    assert item["effective_sample_count"] == 10
    assert item["loss_count"] == 1
    assert item["loss_rate_percent"] == 10.0
    assert item["data_availability"] == "SUMMARY_ONLY"


def test_ground_unattended_repository_failure_is_feature_scoped(
    tmp_path, monkeypatch
) -> None:
    class _BrokenRepository:
        def __init__(self, *_args, **_kwargs) -> None:
            raise OSError("index unavailable")

    monkeypatch.setattr(api_main, "GroundUnattendedRepository", _BrokenRepository)
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)

    assert app.state.ground_unattended_application_service is None
    assert app.state.ground_unattended_startup_error == "OSError"
    with TestClient(app) as client:
        health = client.get("/api/health")
        profile = client.get("/api/rail-transit/ground-unattended/profile")
    assert health.status_code == 200
    assert profile.status_code == 503
    assert profile.json()["detail"] == {
        "code": "GROUND_UNATTENDED_STARTUP_FAILED",
        "message": "地面无人值守后台初始化失败（OSError），请查看运行日志",
        "details": {"startup_error": "OSError"},
    }


def test_ground_unattended_archive_summary_download_and_desktop_action(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run = repository.create_or_get_run(
        run_id="run-download",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    summary = {"ping_sample_count": 123, "covered_train_count": 2}
    repository.upsert_archive(
        {
            "archive_id": "archive-download",
            "site_id": "demo",
            "run_id": run["run_id"],
            "run_date": run["run_date"],
            "relative_path": "archives/2026-07-25_ground_unattended.zip",
            "archive_status": "READY",
            "archive_size_bytes": 456,
            "sha256": "abc",
            "manifest_sha256": "def",
            "retention_until": "2026-08-24",
            "active_cleanup_pending": 0,
            "summary_json": json.dumps(summary),
            "message": "归档完成",
            "created_at": "2026-07-25T23:01:00+08:00",
            "updated_at": "2026-07-25T23:01:00+08:00",
        }
    )

    with TestClient(app) as client:
        download = client.get(
            "/api/rail-transit/ground-unattended/archives/"
            "archive-download/summary-download"
        )
        opened = client.post(
            "/api/rail-transit/ground-unattended/archives/open-directory"
        )

    assert download.status_code == 200
    assert download.json()["ping_sample_count"] == 123
    assert (
        "2026-07-25_ground_unattended_summary.json"
        in download.headers["content-disposition"]
    )
    assert opened.status_code == 200
    assert opened.json()["success"] is False


def test_priority_candidates_are_available_before_first_run(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=_Supervisor(),  # type: ignore[arg-type]
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    page = service.list_trains("site-a")
    assert page.total == 1
    assert [item.endpoint for item in page.items[0].endpoints] == ["CT", "CW"]
    updated = service.set_priority("site-a", "train-01", True)
    assert updated.priority is True
    assert repository.list_priority_train_ids() == {"train-01"}

    run = repository.create_or_get_run(
        run_id="run-endpoints",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repository.upsert_train_state(
        run["run_id"],
        run["run_date"],
        page.items[0].model_dump(mode="json"),
        ap_identity="ap:1",
        same_ap_since="2026-07-25T08:00:00+08:00",
    )
    repository.save_profile(
        repository.get_profile().model_copy(
            update={
                "syslog_server_ip": "192.0.2.50",
                "syslog_server_port": 514,
            }
        )
    )
    repository.upsert_boot_session(
        {
            "boot_session_id": "boot-current-profile",
            "device_uuid": "mr-ct",
            "device_id": 1,
            "train_id": "train-01",
            "mr_role": "CT",
            "last_checked_at": "2026-07-25T08:10:00+08:00",
            "estimated_boot_time": "2026-07-25T07:00:00+08:00",
            "info_center_metrics": {
                "log_hosts": [
                    {"ip": "192.0.2.50", "port": 5514, "facility": "local7"},
                    {"ip": "192.0.2.99", "port": 514, "facility": "local7"},
                ],
                "managed_target": {
                    "ip": "192.0.2.50",
                    "port": 5514,
                    "statuses": ["TARGET_PRESENT"],
                },
            },
        }
    )
    service.supervisor.fleet_ping.target_summaries = lambda: [
        {
            "target_ip": "192.0.2.10",
            "train_id": "train-01",
            "train_no": "01",
            "mr_id": "mr-ct",
            "mr_position_code": "CT",
            "sent_count": 12,
            "success_count": 11,
            "loss_count": 1,
            "loss_rate_percent": 8.3333,
            "avg_rtt_ms": 2.5,
        }
    ]
    enriched = service.get_train("site-a", "train-01")
    ct = next(item for item in enriched.endpoints if item.endpoint == "CT")
    assert ct.ping_active is True
    assert ct.ping_sent_count == 12
    assert ct.managed_target_ip == "192.0.2.50"
    assert ct.managed_target_port == 514
    assert ct.managed_target_statuses == [
        "TARGET_PORT_CONFLICT",
        "OTHER_TARGETS_PRESENT",
    ]
    assert ct.configured_log_hosts[0].same_ip_different_port is True


def test_target_port_change_requires_single_mr_confirmation_and_is_audited(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repository.save_profile(
        repository.get_profile().model_copy(
            update={
                "syslog_server_ip": "192.0.2.50",
                "allow_external_syslog_address": True,
            }
        )
    )
    repository.sync_inventory(
        trains=[{"train_id": "train-01", "train_no": "01"}],
        endpoints=[
            {
                "device_uuid": "mr-ct",
                "device_id": 1,
                "train_id": "train-01",
                "mr_role": "CT",
                "management_ip": "192.0.2.10",
            }
        ],
    )
    repository.create_or_get_run(
        run_id="run-port-change",
        run_date="2026-07-27",
        scheduled_start_at="2026-07-27T07:00:00+08:00",
        scheduled_end_at="2026-07-27T23:00:00+08:00",
    )
    supervisor = _Supervisor()
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,  # type: ignore[arg-type]
    )

    with pytest.raises(GroundUnattendedError) as fleet_error:
        service.request_config_check(
            "site-a",
            allow_target_port_change=True,
            explicit_confirmation=True,
        )
    assert fleet_error.value.code == "TARGET_PORT_CHANGE_CONFIRMATION_REQUIRED"
    with pytest.raises(GroundUnattendedError) as confirmation_error:
        service.request_config_check(
            "site-a",
            device_uuid="mr-ct",
            allow_target_port_change=True,
        )
    assert (
        confirmation_error.value.code
        == "TARGET_PORT_CHANGE_CONFIRMATION_REQUIRED"
    )

    service.request_config_check(
        "site-a",
        device_uuid="mr-ct",
        allow_target_port_change=True,
        explicit_confirmation=True,
    )

    assert supervisor.config_checks == [("mr-ct", True)]
    events = repository.list_events(
        "run-port-change",
        event_type="mr_loghost_port_change_authorized",
    )
    assert len(events) == 1
    assert events[0]["details"]["risk_level"] == "high"


def test_start_is_idempotent_for_active_run_and_rejects_archived_day(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repository.save_profile(
        repository.get_profile().model_copy(
            update={
                "enabled": True,
                "syslog_server_ip": "192.0.2.100",
                "allow_external_syslog_address": True,
            }
        )
    )
    supervisor = _Supervisor()
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,  # type: ignore[arg-type]
    )
    window = schedule_window(datetime.now().astimezone(), "07:00", "23:00", "system")
    run = repository.create_or_get_run(
        run_id="run-today",
        run_date=window.run_date,
        scheduled_start_at=window.next_start.isoformat(),
        scheduled_end_at=window.next_end.isoformat(),
    )
    active_response = service.start_now("site-a")
    assert active_response.run_id == run["run_id"]
    assert active_response.message == "当前无人值守运行已存在，无需重复启动"
    assert supervisor.requests == []

    repository.update_run(run["run_id"], state="COMPLETED")
    repository.upsert_archive(
        {
            "archive_id": "archive-today",
            "site_id": "site-a",
            "run_id": run["run_id"],
            "run_date": run["run_date"],
            "relative_path": f"archives/{run['run_date']}_ground_unattended.zip",
            "archive_status": "READY",
            "archive_size_bytes": 1,
            "sha256": "sha",
            "manifest_sha256": "manifest",
            "retention_until": run["run_date"],
            "active_cleanup_pending": 0,
            "summary_json": "{}",
            "message": "归档完成",
            "created_at": datetime.now().astimezone().isoformat(),
            "updated_at": datetime.now().astimezone().isoformat(),
        }
    )
    with pytest.raises(GroundUnattendedError) as archived_error:
        service.start_now("site-a")
    assert archived_error.value.code == "DAILY_RUN_ARCHIVED"
    assert supervisor.requests == []


def test_deep_collection_page_reuses_persisted_daily_queue_order(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=_Supervisor(),  # type: ignore[arg-type]
    )
    run = repository.create_or_get_run(
        run_id="run-queue",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    for train_id, train_no, priority in (
        ("train-a", "A", False),
        ("train-b", "B", True),
    ):
        repository.upsert_train_state(
            run["run_id"],
            run["run_date"],
            {
                "train_id": train_id,
                "train_no": train_no,
                "deep_collection_eligible": True,
                "ping_eligible": True,
                "eligibility_status": "MAINLINE_MOVING",
                "coverage_status": "WAITING",
                "priority": priority,
                "endpoints": [],
            },
            ap_identity=f"ap:{train_id}",
            same_ap_since="2026-07-25T08:00:00+08:00",
        )
    repository.save_daily_queue(
        run_id=run["run_id"],
        run_date=run["run_date"],
        random_seed=123,
        candidate_train_ids=["train-a", "train-b"],
        queue_order=["train-a", "train-b"],
    )

    page = service.deep_collections("site-a")
    by_id = {item.train_id: item for item in page.items}

    assert by_id["train-a"].queue_position == 1
    assert by_id["train-b"].queue_position == 2
    assert by_id["train-b"].scheduling_priority == 1
    assert by_id["train-b"].selection_reason == "置顶列车今日尚未完成第一轮"
    assert by_id["train-a"].scheduling_priority == 2


class _Supervisor:
    def __init__(self) -> None:
        self.requests = []
        self.config_checks = []
        self.fleet_ping = SimpleNamespace(target_count=0, target_summaries=lambda: [])

    def request(self, action, *, archive=False):
        self.requests.append((action, archive))

    def profile_updated(self):
        return None

    def request_config_check(
        self, device_uuid="", *, allow_target_port_change=False
    ):
        self.config_checks.append((device_uuid, allow_target_port_change))


class _BaseQuery:
    def list_mrs(self, _site_id, *, page, page_size):
        del page_size
        rows = [
            VehicleMrDTO(
                id="mr-ct",
                device_id=1,
                name="01-CT",
                train_id="train-01",
                train_no="01",
                mr_position_code="CT",
                management_ip="192.0.2.10",
            ),
            VehicleMrDTO(
                id="mr-cw",
                device_id=2,
                name="01-CW",
                train_id="train-01",
                train_no="01",
                mr_position_code="CW",
                management_ip="192.0.2.11",
            ),
        ]
        return SimpleNamespace(items=rows if page == 1 else [], total=len(rows))
