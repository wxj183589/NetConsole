from __future__ import annotations

import hashlib
import inspect
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api import main as api_main
from netconsole.backend.api import ground_unattended_router
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


def test_ground_profile_reader_ignores_future_additive_columns(tmp_path) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground-unattended.sqlite", site_id="demo"
    )
    repository.get_profile()
    with repository._connection() as connection:
        connection.execute(
            "ALTER TABLE ground_unattended_profiles ADD COLUMN future_runtime_field TEXT"
        )
        connection.execute(
            "UPDATE ground_unattended_profiles SET future_runtime_field='newer-runtime'"
        )

    profile = repository.get_profile()

    assert profile.site_id == "demo"


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


def test_ground_unattended_run_history_delete_removes_run_records_and_keeps_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    # This test drives repository state directly; the live supervisor would
    # race the explicit COMPLETED transition during the API assertion.
    monkeypatch.setattr(app.state.ground_unattended_supervisor, "start", lambda: None)
    repository = app.state.ground_unattended_repository
    run_id = "run-history-delete"
    run_date = "2026-07-29"
    repository.create_or_get_run(
        run_id=run_id,
        run_date=run_date,
        scheduled_start_at="2026-07-29T09:00:00+08:00",
        scheduled_end_at="2026-07-29T10:00:00+08:00",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-history-delete",
            "run_id": run_id,
            "data_type": "ping",
            "relative_path": "rail_transit/ground_unattended/active/2026-07-29/fleet_ping/01/01/2026-07-29/09_1.ndjson",
            "start_time": "2026-07-29T09:00:00+08:00",
            "end_time": "2026-07-29T09:00:10+08:00",
            "record_count": 1,
            "size_bytes": 10,
            "sha256": "a" * 64,
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )
    repository.upsert_ping_summary(
        {
            "site_id": repository.site_id,
            "run_id": run_id,
            "bucket_kind": "daily",
            "bucket_start": "2026-07-29T00:00:00+08:00",
            "bucket_end": "2026-07-30T00:00:00+08:00",
            "target_ip": "192.0.2.10",
            "train_id": "train-01",
            "train_no": "01",
            "mr_id": "mr-ct",
            "mr_position_code": "CT",
            "ac_snapshot_id": None,
            "ap_identity": "",
            "raw_sample_count": 1,
            "warmup_ignored_count": 0,
            "sent_count": 1,
            "success_count": 1,
            "loss_count": 0,
            "loss_rate_percent": 0.0,
            "min_rtt_ms": 1.0,
            "avg_rtt_ms": 1.0,
            "max_rtt_ms": 1.0,
            "continuous_loss_max_count": 0,
            "continuous_loss_max_seconds": 0.0,
            "created_at": "2026-07-29T09:00:00+08:00",
        }
    )
    repository.add_event(
        run_id=run_id,
        event_type="run_started",
        title="运行开始",
        message="history delete test",
    )

    with TestClient(app) as client:
        rejected = client.request(
            "DELETE",
            f"/api/rail-transit/ground-unattended/runs/{run_id}",
            json={"explicit_confirmation": False},
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"

        blocked = client.request(
            "DELETE",
            f"/api/rail-transit/ground-unattended/runs/{run_id}",
            json={"explicit_confirmation": True},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "RUN_IN_USE"

        repository.update_run(
            run_id,
            state="COMPLETED",
            actual_started_at="2026-07-29T09:00:00+08:00",
            actual_ended_at="2026-07-29T09:10:00+08:00",
        )
        response = client.request(
            "DELETE",
            f"/api/rail-transit/ground-unattended/runs/{run_id}",
            json={"explicit_confirmation": True},
        )
        runs = client.get("/api/rail-transit/ground-unattended/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["state"] == "WAITING_WINDOW"
    assert repository.get_run(run_id) is None
    assert repository.list_raw_files_for_run(run_id) == []
    assert repository.list_ping_summaries(run_id) == []
    assert repository.list_events(run_id) == []
    deleted_events = repository.list_events("", event_type="run_history_deleted")
    assert len(deleted_events) == 1
    assert deleted_events[0]["details"]["run_id"] == run_id
    assert deleted_events[0]["details"]["archive_preserved"] is False
    assert all(item["run_id"] != run_id for item in runs.json()["items"])


def test_syslog_delete_api_previews_blocks_and_queues_one_scoped_job(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run_id = "run-syslog-delete-api"
    run_date = "2026-07-29"
    repository.create_or_get_run(
        run_id=run_id,
        run_date=run_date,
        scheduled_start_at="2026-07-29T09:00:00+08:00",
        scheduled_end_at="2026-07-29T10:00:00+08:00",
    )
    repository.update_run(
        run_id,
        state="COMPLETED",
        actual_started_at="2026-07-29T09:00:00+08:00",
        actual_ended_at="2026-07-29T09:10:00+08:00",
    )
    raw_path = (
        paths.ground_unattended_active_dir("demo", run_date)
        / "realtime"
        / "syslog"
        / "events.ndjson"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "receive_time": "2026-07-29T09:00:01+08:00",
        "global_receive_sequence": 1,
        "source_receive_sequence": 1,
        "source_ip": "192.0.2.3",
        "train_id": "_03",
        "device_uuid": "mr-ct",
        "mr_role": "CT",
        "raw_text": "WMESH LINKUP peer=AP01",
    }
    raw_path.write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-syslog-api",
            "run_id": run_id,
            "train_id": "_03",
            "device_uuid": "mr-ct",
            "mr_role": "CT",
            "data_type": "syslog",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": record["receive_time"],
            "end_time": record["receive_time"],
            "record_count": 1,
            "size_bytes": raw_path.stat().st_size,
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )

    class CapturingProcessAdapter:
        def __init__(self) -> None:
            self.jobs = []

        def start_job(self, job, **_kwargs):
            self.jobs.append(job)
            return job.job_id

    process = CapturingProcessAdapter()
    app.state.ground_unattended_application_service.raw_deletion.process_adapter = (
        process
    )
    selected = {
        "run_id": run_id,
        "mode": "SELECTED",
        "record_keys": [
            {
                "raw_file_id": "raw-syslog-api",
                "global_receive_sequence": 1,
                "source_receive_sequence": 1,
                "raw_line_number": 1,
            }
        ],
        "filters": {},
        "include_derived_events": True,
    }

    with TestClient(app) as client:
        preview = client.post(
            "/api/rail-transit/ground-unattended/syslog-delete-preview",
            json=selected,
        )
        assert preview.status_code == 200
        preview_payload = preview.json()
        assert preview_payload["matched_record_count"] == 1
        assert preview_payload["affected_file_count"] == 1
        assert preview_payload["blocked_reasons"] == []
        assert preview_payload["preview_token"]

        submitted = client.post(
            "/api/rail-transit/ground-unattended/syslog-delete",
            json={
                "preview_token": preview_payload["preview_token"],
                "explicit_confirmation": True,
                "confirmation_text": f"DELETE {run_date}",
                "include_derived_events": True,
            },
        )
        assert submitted.status_code == 202
        assert submitted.json()["status"] == "PENDING"
        assert len(process.jobs) == 1
        assert process.jobs[0].task_type == "ground_syslog_delete"

        invalid_key = client.post(
            "/api/rail-transit/ground-unattended/syslog-delete-preview",
            json={
                **selected,
                "record_keys": [{"raw_file_id": "raw-syslog-api"}],
            },
        )
        assert invalid_key.status_code == 422

        repository.update_run(run_id, state="RUNNING")
        registered = repository.get_raw_file("raw-syslog-api")
        assert registered is not None
        repository.upsert_raw_file({**registered, "status": "OPEN"})
        active = client.post(
            "/api/rail-transit/ground-unattended/syslog-delete-preview",
            json={
                "run_id": run_id,
                "mode": "RUN_ALL",
                "record_keys": [],
                "filters": {},
                "include_derived_events": True,
            },
        )
        assert active.status_code == 200
        assert any(
            "RUN_ACTIVE" in reason
            for reason in active.json()["blocked_reasons"]
        )
        assert any(
            "RAW_FILE_OPEN" in reason
            for reason in active.json()["blocked_reasons"]
        )

        repository.update_run(
            run_id,
            state="COMPLETED",
            actual_ended_at="2026-07-29T09:10:00+08:00",
        )
        repository.upsert_raw_file({**registered, "status": "CLOSED"})
        repository.upsert_archive(
            {
                "archive_id": "archive-ready-api",
                "site_id": repository.site_id,
                "run_id": run_id,
                "run_date": run_date,
                "relative_path": "archives/ready.zip",
                "archive_status": "READY",
                "archive_size_bytes": 10,
                "sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "retention_until": "2099-01-01",
                "active_cleanup_pending": 0,
                "summary_json": "{}",
                "message": "ready",
                "created_at": "2026-07-29T09:10:00+08:00",
                "updated_at": "2026-07-29T09:10:00+08:00",
            }
        )
        ready = client.post(
            "/api/rail-transit/ground-unattended/syslog-delete-preview",
            json={
                "run_id": run_id,
                "mode": "RUN_ALL",
                "record_keys": [],
                "filters": {},
                "include_derived_events": True,
            },
        )
        assert ready.status_code == 200
        assert any(
            "READY_ARCHIVE_IMMUTABLE" in reason
            for reason in ready.json()["blocked_reasons"]
        )


def test_syslog_delete_router_keeps_file_and_sql_work_in_services() -> None:
    source = "\n".join(
        (
            inspect.getsource(
                ground_unattended_router.preview_syslog_delete
            ),
            inspect.getsource(
                ground_unattended_router.submit_syslog_delete
            ),
        )
    )

    for forbidden in ("Path(", "open(", "sqlite3", ".execute(", "os.replace"):
        assert forbidden not in source


def test_timeline_api_returns_exact_server_page_and_search_total(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run_id = "run-timeline-page"
    repository.create_or_get_run(
        run_id=run_id,
        run_date="2026-07-29",
        scheduled_start_at="2026-07-29T09:00:00+08:00",
        scheduled_end_at="2026-07-29T10:00:00+08:00",
    )
    for sequence in range(1, 4):
        repository.add_event(
            run_id=run_id,
            event_type="mesh_linkup",
            title=f"AP01 第 {sequence} 次建链",
            details={"peer_name": "AP01", "sequence": sequence},
            ts=f"2026-07-29T09:00:0{sequence}+08:00",
        )
    repository.add_event(
        run_id=run_id,
        event_type="run_started",
        title="运行开始",
        ts="2026-07-29T09:00:00+08:00",
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/ground-unattended/timeline",
            params={
                "run_id": run_id,
                "query": "AP01",
                "page": 2,
                "page_size": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["page"] == 2
    assert payload["page_size"] == 1
    assert payload["total_exact"] is True
    assert len(payload["items"]) == 1
    assert "AP01" in payload["items"][0]["title"]


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


def test_syslog_transport_status_keeps_return_and_listen_state_separate(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    repository.save_profile(
        repository.get_profile().model_copy(
            update={
                "syslog_server_ip": "10.8.0.3",
                "syslog_server_port": 514,
                "udp_listen_host": "0.0.0.0",
                "udp_listen_port": 514,
                "allow_external_syslog_address": False,
            }
        )
    )
    inspected: list[tuple[str, int]] = []
    candidate = SimpleNamespace(ipv4="10.0.0.24", adapter_name="板载")
    network = SimpleNamespace(
        is_local_ipv4=lambda value: value == "10.0.0.24",
        inspect_udp_port=lambda host, port: (
            inspected.append((host, port))
            or SimpleNamespace(available=True, message="UDP 端口空闲")
        ),
        recommend_source_ip=lambda _request: SimpleNamespace(
            recommended_ip="10.0.0.24",
            candidates=[candidate],
        ),
    )
    service = app.state.ground_unattended_application_service
    service.network_service = network

    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/ground-unattended/syslog-transport-status"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured_return_ip"] == "10.8.0.3"
    assert payload["return_address_status"] == "NOT_LOCAL"
    assert payload["listen_host"] == "0.0.0.0"
    assert payload["port_state"] == "AVAILABLE"
    assert payload["ports_match"] is None
    assert payload["recommended_local_ip"] == "10.0.0.24"
    assert payload["recommended_adapter_name"] == "板载"
    assert inspected == [("0.0.0.0", 514)]


def test_syslog_transport_status_distinguishes_receiver_from_other_process(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repository.save_profile(
        repository.get_profile().model_copy(
            update={
                "syslog_server_ip": "10.0.0.24",
                "udp_listen_host": "0.0.0.0",
                "udp_listen_port": 514,
            }
        )
    )
    health = {
        "udp_running": True,
        "udp_listen_address": "0.0.0.0:514",
        "udp_received_count": 8,
        "udp_unidentified_count": 2,
        "udp_identity_conflict_count": 1,
        "udp_last_received_at": "2026-07-30T12:00:00+08:00",
        "udp_queue_length": 3,
        "udp_queue_capacity": 20_000,
        "udp_dropped_count": 0,
        "last_error": "",
    }
    supervisor = _Supervisor()
    supervisor.syslog_receiver = SimpleNamespace(
        health_snapshot=lambda: dict(health)
    )
    inspected = []
    candidate = SimpleNamespace(ipv4="10.0.0.24", adapter_name="板载")
    network = SimpleNamespace(
        is_local_ipv4=lambda value: value == "10.0.0.24",
        inspect_udp_port=lambda host, port: (
            inspected.append((host, port))
            or SimpleNamespace(available=False, message="UDP 端口已被占用")
        ),
        recommend_source_ip=lambda _request: SimpleNamespace(
            recommended_ip="10.0.0.24",
            candidates=[candidate],
        ),
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,  # type: ignore[arg-type]
        network_service=network,  # type: ignore[arg-type]
    )

    own = service.syslog_transport_status("site-a")
    assert own.receiver_state == "LISTENING"
    assert own.port_state == "NETCONSOLE_LISTENING"
    assert own.received_count == 8
    assert own.identity_conflict_count == 1
    assert inspected == []

    health["udp_running"] = False
    health["udp_listen_address"] = ""
    other = service.syslog_transport_status("site-a")
    assert other.receiver_state == "STOPPED"
    assert other.port_state == "OCCUPIED_BY_OTHER"
    assert inspected == [("0.0.0.0", 514)]


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


def test_syslog_unexpected_failure_returns_request_id_and_keeps_backend_alive(
    tmp_path, monkeypatch
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    events: list[tuple[str, str]] = []

    def fail_query(*_args, **_kwargs):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(
        app.state.ground_unattended_application_service,
        "syslog_records",
        fail_query,
    )
    monkeypatch.setattr(
        ground_unattended_router.app_logger,
        "log_info",
        lambda event, detail="": events.append((event, detail)),
    )
    monkeypatch.setattr(
        ground_unattended_router.app_logger,
        "log_error",
        lambda event, detail="": events.append((event, detail)),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/ground-unattended/syslog-records",
            params={"run_id": "run-failure", "page": 1, "page_size": 100},
        )
        health = client.get("/api/health")

    assert response.status_code == 500
    body = response.json()["detail"]
    request_id = body["details"]["request_id"]
    assert body["code"] == "GROUND_SYSLOG_QUERY_FAILED"
    assert len(request_id) == 32
    assert response.headers["x-request-id"] == request_id
    assert health.status_code == 200
    failed = next(detail for event, detail in events if event == "GROUND_SYSLOG_QUERY_FAILED")
    assert f"request_id={request_id}" in failed
    assert "exception_type=RuntimeError" in failed
    assert "Traceback" in failed


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


def test_runtime_train_list_and_detail_share_persisted_decision_contract(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    run = repository.create_or_get_run(
        run_id="run-decision-contract",
        run_date="2026-08-07",
        scheduled_start_at="2026-08-07T07:00:00+08:00",
        scheduled_end_at="2026-08-07T23:00:00+08:00",
    )
    repository.upsert_train_state(
        run["run_id"],
        run["run_date"],
        {
            "train_id": "train-01",
            "train_no": "01",
            "train_name": "列车01",
            "location_class": "MAINLINE",
            "location_class_source": "DEFAULT_MAINLINE",
            "participates_in_mainline": True,
            "mainline_eligible": True,
            "mainline_reason_code": "MAINLINE_DEFAULT_CLASSIFICATION",
            "mainline_reason_text": "AP 已匹配且没有特殊区域标记，按默认正线纳入",
            "ping_eligible": True,
            "ping_reason_code": "MAINLINE_DEFAULT_CLASSIFICATION",
            "ping_reason_text": "AP 已匹配，无特殊区域标记，按默认正线纳入",
            "deep_collection_eligible": True,
            "deep_collection_reason_code": "ELIGIBLE",
            "deep_collection_reason_text": "正线在线，符合深度采集资格",
            "decision_revision": 2,
            "decision_source": "RUNTIME_AP_IDENTITY",
            "eligibility_status": "MAINLINE",
            "endpoints": [],
        },
        ap_identity="ap-1",
        same_ap_since="2026-08-07T08:00:00+08:00",
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=_Supervisor(),  # type: ignore[arg-type]
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    listed = service.list_trains("site-a").items[0]
    detailed = service.get_train("site-a", "train-01")

    assert listed.model_dump() == detailed.model_dump()
    assert listed.location_class == "MAINLINE"
    assert listed.participates_in_mainline is True
    assert listed.mainline_eligible is True
    assert listed.ping_reason_text != "未评估"
    assert listed.deep_collection_reason_code == "ELIGIBLE"
    assert listed.decision_revision == 2


def test_legacy_evaluated_train_snapshot_gets_auditable_effective_decision(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    run = repository.create_or_get_run(
        run_id="run-legacy-decision",
        run_date="2026-08-06",
        scheduled_start_at="2026-08-06T07:00:00+08:00",
        scheduled_end_at="2026-08-06T23:00:00+08:00",
    )
    repository.upsert_train_state(
        run["run_id"],
        run["run_date"],
        {
            "train_id": "train-legacy",
            "location_class": "UNKNOWN",
            "mainline_eligible": True,
            "ping_eligible": True,
            "deep_collection_eligible": True,
            "eligibility_status": "MAINLINE",
            "exclusion_reason": "正线在线",
            "ping_inclusion_reason": "正线在线",
            "endpoints": [],
        },
        ap_identity="legacy-ap",
        same_ap_since="2026-08-06T08:00:00+08:00",
    )

    repository.initialize()
    row = repository.get_train_run(run["run_id"], "train-legacy")

    assert row is not None
    assert row["location_class"] == "MAINLINE"
    assert row["participates_in_mainline"] == 1
    assert row["ping_reason_text"] == "正线在线"
    assert row["decision_revision"] == 1
    assert row["decision_source"] == "LEGACY_ELIGIBILITY_SNAPSHOT"


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

    assert supervisor.config_checks == [("mr-ct", True, True)]
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
    profile = repository.get_profile().model_copy(
        update={
            "enabled": True,
            "syslog_server_ip": "192.0.2.100",
            "allow_external_syslog_address": True,
        }
    )
    repository.save_profile(profile)
    supervisor = _Supervisor()
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,  # type: ignore[arg-type]
    )
    window = schedule_window(
        datetime.now().astimezone(),
        profile.schedule_start_time,
        profile.schedule_end_time,
        profile.timezone,
    )
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


def test_deep_collection_running_requires_raw_evidence_and_reads_incrementally(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    query = _DeepCollectionQuery()
    supervisor = _Supervisor()
    supervisor.deep_scheduler = SimpleNamespace(query_service=query)
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,  # type: ignore[arg-type]
    )
    run = repository.create_or_get_run(
        run_id="run-deep-evidence",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repository.upsert_train_state(
        run["run_id"],
        run["run_date"],
        {
            "train_id": "train-1",
            "train_no": "01",
            "deep_collection_eligible": True,
            "coverage_status": "COLLECTING",
            "endpoints": [
                {
                    "endpoint": "CT",
                    "mr_id": "mr-ct",
                    "management_ip": "192.0.2.10",
                }
            ],
        },
        ap_identity="ap-1",
        same_ap_since="2026-07-25T08:00:00+08:00",
    )
    repository.save_deep_operation(
        {
            "operation_id": "operation-ct",
            "site_id": "site-a",
            "run_id": run["run_id"],
            "train_id": "train-1",
            "mr_id": "mr-ct",
            "mr_position_code": "CT",
            "session_id": "session-ct",
            "state": "RUNNING",
            "started_at": "2026-07-25T08:00:00+08:00",
            "ended_at": "",
            "stop_reason": "",
            "error_summary": "",
            "finalization_complete": 0,
            "package_verified": 0,
            "updated_at": "2026-07-25T08:00:00+08:00",
        }
    )

    starting = service.deep_collections("site-a", run_id=run["run_id"]).items[0]
    assert starting.deep_state == "STARTING"
    assert starting.collectors[0].state == "STARTING"
    assert starting.collectors[0].bytes_written == 0

    query.size_bytes = 256
    running = service.deep_collections("site-a", run_id=run["run_id"]).items[0]
    assert running.deep_state == "RUNNING"
    assert running.collectors[0].state == "RUNNING"
    assert running.collectors[0].record_count is None

    first = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RAW_OUTPUT",
        limit=1,
    )
    assert [item.text for item in first.records] == ["first record"]
    assert first.has_more is True
    assert first.next_cursor

    second = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RAW_OUTPUT",
        cursor=first.next_cursor,
        limit=1,
    )
    assert [item.text for item in second.records] == ["second record"]
    assert second.has_more is False

    query.source_lines["mesh_link"] = [
        "2026-07-25 08:00:03 [collector=repeat] RX display clock",
        "2026-07-25 08:00:04 [collector=repeat] RX Time Zone : BeiJing add 08:00:00",
        "2026-07-25 08:00:05 bc5a-3457-cbef RSSI: 33 ACTIVE",
    ]
    wmesh = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="WMESH",
        limit=20,
    )
    assert [item.text for item in wmesh.records] == [
        "2026-07-25 08:00:05 bc5a-3457-cbef RSSI: 33 ACTIVE"
    ]
    assert all(item.category == "WMESH" for item in wmesh.records)

    rssi = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RSSI",
        limit=20,
    )
    assert len(rssi.records) == 1
    assert "RSSI: 33" in rssi.records[0].text

    query.source_lines["terminal_monitor"] = [
        "2026-07-25 08:00:06 RSSI threshold: 30",
        "2026-07-25 08:00:07 bc5a-3457-cbef RSSI: 31 ACTIVE",
        "2026-07-25 08:00:08 channel busy 47",
    ]
    rssi = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RSSI",
        limit=20,
    )
    assert any("RSSI: 31 ACTIVE" in item.text for item in rssi.records)
    assert all("RSSI threshold" not in item.text for item in rssi.records)
    radio = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RADIO",
        limit=20,
    )
    assert [item.text for item in radio.records] == [
        "2026-07-25 08:00:08 channel busy 47"
    ]

    query.source_lines["collector"] = [
        "2026-07-25 08:00:09 arbitrary collector payload",
        "2026-07-25 08:00:10 collector started",
    ]
    status_records = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="STATUS",
        limit=20,
    )
    assert [item.text for item in status_records.records] == [
        "2026-07-25 08:00:10 collector started"
    ]

    raw = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RAW_OUTPUT",
        limit=20,
    )
    assert any("display clock" in item.text for item in raw.records)
    assert any("Time Zone" in item.text for item in raw.records)
    with pytest.raises(GroundUnattendedError) as mismatch:
        service.deep_collection_records(
            "site-a",
            run_id=run["run_id"],
            train_id="train-1",
            mr_role="CT",
            category="RSSI",
            cursor=wmesh.next_cursor,
            limit=20,
        )
    assert mismatch.value.code == "DEEP_RECORD_CURSOR_FILTER_MISMATCH"

    query.source_lines = {
        "collector_output": [
            "2026-07-25T08:01:01+08:00 collector first",
            "2026-07-25T08:01:03+08:00 collector second",
        ],
        "mesh_link": [
            "2026-07-25T08:01:02+08:00 mesh first",
            "2026-07-25T08:01:04+08:00 mesh second",
        ],
    }
    first_page = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RAW_OUTPUT",
        limit=2,
    )
    second_page = service.deep_collection_records(
        "site-a",
        run_id=run["run_id"],
        train_id="train-1",
        mr_role="CT",
        category="RAW_OUTPUT",
        cursor=first_page.next_cursor,
        limit=2,
    )
    paged_records = [*first_page.records, *second_page.records]
    assert [item.text for item in paged_records] == [
        "2026-07-25T08:01:01+08:00 collector first",
        "2026-07-25T08:01:02+08:00 mesh first",
        "2026-07-25T08:01:03+08:00 collector second",
        "2026-07-25T08:01:04+08:00 mesh second",
    ]
    assert len({(item.source, item.sequence) for item in paged_records}) == 4
    assert first_page.has_more is True
    assert second_page.has_more is False


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
        self,
        device_uuid="",
        *,
        repair_enabled=True,
        allow_target_port_change=False,
    ):
        self.config_checks.append(
            (device_uuid, repair_enabled, allow_target_port_change)
        )


class _DeepCollectionQuery:
    def __init__(self) -> None:
        self.size_bytes = 0
        self.source_lines = {
            "collector_output": ["first record", "second record"]
        }

    @staticmethod
    def get_session(*_args, **_kwargs):
        return SimpleNamespace(status="RUNNING", error_message="")

    def list_collectors(self, *_args, **_kwargs):
        return [
            SimpleNamespace(
                name="mesh_link",
                exists=True,
                size_bytes=self.size_bytes,
                updated_at="2026-07-25T08:00:10+08:00" if self.size_bytes else "",
            )
        ]

    def read_log_chunk(self, _site_id, _session_id, source, *, cursor, limit):
        source_lines = self.source_lines.get(source, [])
        lines = source_lines[cursor : cursor + limit]
        next_cursor = cursor + len(lines)
        return SimpleNamespace(
            next_cursor=next_cursor,
            has_more=next_cursor < len(source_lines),
            lines=[
                SimpleNamespace(
                    sequence=index,
                    timestamp=f"2026-07-25T08:00:0{index + 1}+08:00",
                    text=text,
                )
                for index, text in enumerate(lines, start=cursor)
            ],
        )


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
