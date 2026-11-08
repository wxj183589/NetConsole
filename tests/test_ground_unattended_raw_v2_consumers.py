from __future__ import annotations

import gzip
import json
from datetime import datetime

from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.services.ground_unattended.archive_service import GroundUnattendedArchiveService
from netconsole.services.ground_unattended.history_query import GroundHistoryQueryService
from netconsole.services.ground_unattended.raw_lifecycle import GroundRawDataLifecycleService
from netconsole.services.ground_unattended.syslog_runtime import RawCompressionWorker, RawStreamWriter


def test_per_mr_gzip_keeps_api_history_and_ready_archive_consumers_queryable(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run_id, run_date = "raw-v2-consumers", "2026-07-25"
    stamp = "2026-07-25T08:00:00+08:00"
    repository.create_or_get_run(
        run_id=run_id, run_date=run_date,
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repository.update_run(run_id, state="COMPLETED", actual_started_at=stamp, actual_ended_at=stamp)
    active = paths.ground_unattended_active_dir(repository.site_id, run_date)
    for data_type in ("ping", "syslog"):
        compressor = RawCompressionWorker(repository=repository, run_id=run_id, data_type=data_type)
        writer = RawStreamWriter(
            root=active if data_type == "ping" else active / "realtime",
            repository=repository, site_id=repository.site_id,
            run_id=run_id, run_date=run_date, data_type=data_type,
            directory_name="fleet_ping" if data_type == "ping" else "syslog",
            compression_worker=compressor, max_file_size_bytes=10 * 1024 * 1024,
        )
        try:
            for index, mr_id in enumerate(("mr-before", "mr-after")):
                writer.write({
                    "train_id": "train-1", "device_uuid": mr_id, "mr_id": mr_id,
                    "mr_role": "CT", "mr_position_code": "CT", "ts": stamp,
                    "receive_time": stamp, "target_ip": f"192.0.2.{index + 10}",
                    "source_ip": f"192.0.2.{index + 10}", "sample_id": f"sample-{index}",
                    "seq": 1, "ok": True, "rtt_ms": 2.0,
                    "global_receive_sequence": index + 1,
                    "event_type": "MESH_LINKUP", "event_family": "WMESH",
                    "raw_text": f"mock raw record {index}",
                }, datetime.fromisoformat(stamp))
            writer.close()
            assert writer.flush_metadata(timeout=10)
        finally:
            writer.close()
            assert compressor.stop(timeout=10)
        assert compressor.snapshot()["compression_completed_count"] == 2
    rows = repository.list_raw_files_for_run(run_id)
    assert len(rows) == 4
    for row in rows:
        assert row["gzip_path"] and not row["compressed_path"]
        raw = repository.db_path.parent / row["relative_path"]
        with gzip.open(repository.db_path.parent / row["gzip_path"], "rb") as handle:
            assert handle.read() == raw.read_bytes()
        assert json.loads(raw.read_text(encoding="utf-8"))["device_uuid"] == row["device_uuid"]

    history = GroundHistoryQueryService(repository.db_path, site_id=repository.site_id)
    assert history.query(data_type="syslog_raw", run_id=run_id)["total"] == 2
    assert history.query(data_type="syslog_raw", run_id=run_id, mr_id="mr-before")["total"] == 1
    # Gzip is an additional immutable copy. Record deletion must fail closed
    # while it exists rather than leave an obsolete compressed raw record.
    preview = GroundRawDataLifecycleService(repository).preview_syslog_deletion(
        run_id=run_id, mode="ALL", record_keys=[], filters={}, include_derived_events=True,
    )
    assert preview.plan is None
    assert any("READY_ARCHIVE_IMMUTABLE" in reason for reason in preview.blocked_reasons)

    with TestClient(app) as client:
        for expected_source in ("ACTIVE", "ARCHIVE"):
            if expected_source == "ARCHIVE":
                archive_result = GroundUnattendedArchiveService(
                    paths, site_id=repository.site_id, repository=repository,
                ).archive_run(run_id, repository.get_profile())
                assert archive_result.success, archive_result
                assert not active.exists()
                for row in repository.list_raw_files_for_run(run_id):
                    assert row["archive_status"] == "ARCHIVED"
                    assert row["compressed_path"].endswith(".zip")
                    assert row["gzip_path"] == ""
            for mr_id in ("mr-before", "mr-after"):
                response = client.get(
                    "/api/rail-transit/ground-unattended/ping-series",
                    params={"run_id": run_id, "mr_id": mr_id},
                )
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["raw_sample_count"] == 1
                assert result["diagnostics"]["source_kind"] == expected_source
                assert result["points"][0]["mr_id"] == mr_id
                response = client.get(
                    "/api/rail-transit/ground-unattended/syslog-records",
                    params={"run_id": run_id, "mr_id": mr_id},
                )
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["total"] == 1
                assert result["diagnostics"]["source_kind"] == expected_source
                assert result["items"][0]["device_uuid"] == mr_id
            assert history.query(data_type="syslog_raw", run_id=run_id)["total"] == 2
