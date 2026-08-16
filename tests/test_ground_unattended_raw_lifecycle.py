from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import (
    GroundSyslogDeletePreviewRequestDTO,
    GroundSyslogDeleteRequestDTO,
)
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.raw_lifecycle import (
    GroundRawDataLifecycleService,
    GroundRawLifecycleError,
)
from netconsole.services.ground_unattended.raw_deletion import (
    GroundRawDataDeletionApplicationService,
)
from netconsole.services.job_center.handlers.ground_unattended_jobs import (
    ground_syslog_delete,
)
from netconsole.services.job_center.job_context import JobContext


RUN_ID = "run-delete"
RUN_DATE = "2026-07-29"


def test_selected_syslog_delete_rewrites_atomically_and_removes_provenance(
    tmp_path: Path,
) -> None:
    repository, raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="SELECTED",
        record_keys=[
            {
                "raw_file_id": "raw-syslog",
                "global_receive_sequence": 2,
                "source_receive_sequence": 2,
                "raw_line_number": 2,
            }
        ],
        filters={},
        include_derived_events=True,
    )

    assert preview.blocked_reasons == ()
    assert preview.matched_record_count == 1
    assert preview.affected_file_count == 1
    assert preview.affected_event_count == 1
    assert preview.affected_timeline_count == 1
    assert preview.plan is not None

    result = lifecycle.execute_syslog_deletion(
        preview.plan,
        operation_id="operation-selected",
    )

    remaining = [
        json.loads(line)
        for line in raw_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [
        row["global_receive_sequence"] for row in remaining
    ] == [1, 3]
    registered = repository.get_raw_file("raw-syslog")
    assert registered is not None
    assert registered["record_count"] == 2
    assert registered["revision"] == 1
    assert registered["size_bytes"] == raw_path.stat().st_size
    assert registered["sha256"] == _sha256(raw_path)
    assert result["deleted_record_count"] == 1
    assert result["deleted_wmesh_event_count"] == 1
    assert result["deleted_timeline_count"] == 1
    assert repository.list_wmesh_events(run_id=RUN_ID) == []
    timeline = repository.list_events(RUN_ID, limit=20)
    assert {
        row["event_type"] for row in timeline
    } == {"run_started", "ping_loss_pattern"}
    assert not any(path.suffix == ".part" for path in raw_path.parent.iterdir())
    assert not any(path.suffix == ".bak" for path in raw_path.parent.iterdir())


def test_interrupted_raw_rewrite_rolls_back_from_durable_journal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="SELECTED",
        record_keys=[
            {
                "raw_file_id": "raw-syslog",
                "global_receive_sequence": 2,
                "source_receive_sequence": 2,
                "raw_line_number": 2,
            }
        ],
        filters={},
        include_derived_events=True,
    )
    assert preview.plan is not None
    original = raw_path.read_bytes()
    before = repository.get_raw_file("raw-syslog")
    assert before is not None

    monkeypatch.setattr(
        repository,
        "apply_syslog_deletion_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            KeyboardInterrupt("simulated file/registry interruption")
        ),
    )
    with pytest.raises(KeyboardInterrupt, match="file/registry interruption"):
        lifecycle.execute_syslog_deletion(
            preview.plan,
            operation_id="operation-crash-before-metadata",
        )

    assert raw_path.read_bytes() != original
    assert list(lifecycle.journal_root.glob("*.json"))
    assert any(path.suffix == ".bak" for path in raw_path.parent.iterdir())
    monkeypatch.undo()

    recovered = GroundRawDataLifecycleService(repository)

    assert recovered.recover_interrupted_operations() == []
    assert raw_path.read_bytes() == original
    after = repository.get_raw_file("raw-syslog")
    assert after is not None
    assert after["revision"] == before["revision"]
    assert after["sha256"] == before["sha256"]
    assert repository.list_wmesh_events(run_id=RUN_ID)
    assert not list(lifecycle.journal_root.glob("*.json"))
    assert not any(path.suffix == ".bak" for path in raw_path.parent.iterdir())


def test_interrupted_after_metadata_commit_finalizes_durable_journal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="SELECTED",
        record_keys=[
            {
                "raw_file_id": "raw-syslog",
                "global_receive_sequence": 2,
                "source_receive_sequence": 2,
                "raw_line_number": 2,
            }
        ],
        filters={},
        include_derived_events=True,
    )
    assert preview.plan is not None
    original = raw_path.read_bytes()
    original_apply = repository.apply_syslog_deletion_metadata

    def commit_then_interrupt(*args, **kwargs):
        original_apply(*args, **kwargs)
        raise KeyboardInterrupt("simulated post-commit interruption")

    monkeypatch.setattr(
        repository,
        "apply_syslog_deletion_metadata",
        commit_then_interrupt,
    )
    with pytest.raises(KeyboardInterrupt, match="post-commit interruption"):
        lifecycle.execute_syslog_deletion(
            preview.plan,
            operation_id="operation-crash-after-metadata",
        )

    committed = raw_path.read_bytes()
    assert committed != original
    assert list(lifecycle.journal_root.glob("*.json"))
    monkeypatch.undo()

    GroundRawDataLifecycleService(repository)

    assert raw_path.read_bytes() == committed
    registered = repository.get_raw_file("raw-syslog")
    assert registered is not None
    assert registered["revision"] == 1
    assert registered["sha256"] == _sha256(raw_path)
    assert repository.list_wmesh_events(run_id=RUN_ID) == []
    assert not list(lifecycle.journal_root.glob("*.json"))
    assert not any(path.suffix == ".bak" for path in raw_path.parent.iterdir())


def test_filtered_and_run_all_preview_are_blocked_for_active_open_or_ready(
    tmp_path: Path,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    repository.update_run(RUN_ID, state="RUNNING", actual_ended_at="")
    registered = repository.get_raw_file("raw-syslog")
    assert registered is not None
    repository.upsert_raw_file({**registered, "status": "OPEN"})

    active = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="FILTERED",
        record_keys=[],
        filters={"keyword": "WMESH"},
        include_derived_events=True,
    )

    assert any("RUN_ACTIVE" in reason for reason in active.blocked_reasons)
    assert any("RAW_FILE_OPEN" in reason for reason in active.blocked_reasons)
    assert active.plan is None

    repository.update_run(
        RUN_ID,
        state="COMPLETED",
        actual_ended_at="2026-07-29T09:10:00+08:00",
    )
    repository.upsert_raw_file({**registered, "status": "CLOSED"})
    repository.upsert_archive(
        {
            "archive_id": "archive-ready",
            "site_id": repository.site_id,
            "run_id": RUN_ID,
            "run_date": RUN_DATE,
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
    ready = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="RUN_ALL",
        record_keys=[],
        filters={},
        include_derived_events=True,
    )
    assert any(
        "READY_ARCHIVE_IMMUTABLE" in reason
        for reason in ready.blocked_reasons
    )
    assert ready.plan is None


def test_revision_conflict_and_registry_failure_preserve_original_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="RUN_ALL",
        record_keys=[],
        filters={},
        include_derived_events=True,
    )
    assert preview.plan is not None
    original = raw_path.read_bytes()
    registered = repository.get_raw_file("raw-syslog")
    assert registered is not None
    repository.update_raw_file_after_rewrite(
        "raw-syslog",
        base_revision=0,
        record_count=registered["record_count"],
        size_bytes=registered["size_bytes"],
        sha256=registered["sha256"],
        start_time=registered["start_time"],
        end_time=registered["end_time"],
    )

    with pytest.raises(
        GroundRawLifecycleError,
        match="revision 已变化",
    ):
        lifecycle.execute_syslog_deletion(
            preview.plan,
            operation_id="operation-conflict",
        )
    assert raw_path.read_bytes() == original

    fresh = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="RUN_ALL",
        record_keys=[],
        filters={},
        include_derived_events=True,
    )
    assert fresh.plan is not None

    def fail_metadata(*_args, **_kwargs):
        raise RuntimeError("simulated registry failure")

    monkeypatch.setattr(
        repository,
        "apply_syslog_deletion_metadata",
        fail_metadata,
    )
    with pytest.raises(RuntimeError, match="simulated registry failure"):
        lifecycle.execute_syslog_deletion(
            fresh.plan,
            operation_id="operation-rollback",
        )
    assert raw_path.read_bytes() == original
    assert not any(path.suffix == ".part" for path in raw_path.parent.iterdir())
    assert not any(path.suffix == ".bak" for path in raw_path.parent.iterdir())


def test_preserved_derived_events_are_marked_source_deleted(
    tmp_path: Path,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="SELECTED",
        record_keys=[
            {
                "raw_file_id": "raw-syslog",
                "global_receive_sequence": 2,
                "raw_line_number": 2,
            }
        ],
        filters={},
        include_derived_events=False,
    )
    assert preview.plan is not None

    lifecycle.execute_syslog_deletion(
        preview.plan,
        operation_id="operation-preserve-derived",
    )

    wmesh = repository.list_wmesh_events(run_id=RUN_ID)
    assert wmesh[0]["details"]["source_deleted"] is True
    timeline = repository.list_events(RUN_ID, limit=20)
    syslog_event = next(
        row for row in timeline if row["event_type"] == "mesh_linkup"
    )
    assert syslog_event["details"]["source_deleted"] is True
    assert any(row["event_type"] == "run_started" for row in timeline)
    ping_event = next(
        row for row in timeline if row["event_type"] == "ping_loss_pattern"
    )
    assert ping_event["details"].get("source_deleted") is not True


def test_delete_application_requires_preview_confirmation_and_queues_job(
    tmp_path: Path,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)

    class ProcessAdapter:
        def __init__(self) -> None:
            self.job = None

        def start_job(self, job, **_kwargs):
            self.job = job
            return job.job_id

    process = ProcessAdapter()
    service = GroundRawDataDeletionApplicationService(
        repository,
        process_adapter=process,
        app_root=str(tmp_path / "app"),
        data_root=str(tmp_path / "data"),
    )
    preview = service.preview(
        GroundSyslogDeletePreviewRequestDTO(
            run_id=RUN_ID,
            mode="FILTERED",
            filters={"keyword": "WMESH"},
            include_derived_events=True,
        )
    )
    assert preview.preview_token
    assert preview.matched_record_count == 1

    with pytest.raises(
        GroundRawLifecycleError,
        match="确认文本不匹配",
    ):
        service.submit(
            GroundSyslogDeleteRequestDTO(
                preview_token=preview.preview_token,
                explicit_confirmation=True,
                confirmation_text="DELETE wrong-date",
                include_derived_events=True,
            )
        )

    accepted = service.submit(
        GroundSyslogDeleteRequestDTO(
            preview_token=preview.preview_token,
            explicit_confirmation=True,
            confirmation_text=f"DELETE {RUN_DATE}",
            include_derived_events=True,
        )
    )

    assert accepted.accepted is True
    assert accepted.task_id
    assert process.job.task_type == "ground_syslog_delete"
    assert process.job.params["plan"]["run_id"] == RUN_ID
    audit = repository.get_delete_operation(accepted.operation_id)
    assert audit is not None
    assert audit["status"] == "PENDING"
    assert audit["confirmation_source"] == "RUN_DATE"
    assert audit["matched_count"] == 1


def test_malformed_syslog_line_is_preserved_during_filtered_rewrite(
    tmp_path: Path,
) -> None:
    repository, raw_path = _setup_completed_run(tmp_path)
    malformed = b"{not-valid-json}\n"
    original = raw_path.read_bytes()
    raw_path.write_bytes(original.splitlines(keepends=True)[0] + malformed + b"".join(
        original.splitlines(keepends=True)[1:]
    ))
    registered = repository.get_raw_file("raw-syslog")
    assert registered is not None
    repository.upsert_raw_file(
        {
            **registered,
            "record_count": 4,
            "size_bytes": raw_path.stat().st_size,
            "sha256": _sha256(raw_path),
        }
    )
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="FILTERED",
        record_keys=[],
        filters={"keyword": "WMESH"},
        include_derived_events=True,
    )
    assert preview.plan is not None
    assert any("损坏或非对象 NDJSON" in warning for warning in preview.warnings)

    result = lifecycle.execute_syslog_deletion(
        preview.plan,
        operation_id="operation-malformed",
    )

    assert result["deleted_record_count"] == 1
    assert malformed in raw_path.read_bytes()
    refreshed = repository.get_raw_file("raw-syslog")
    assert refreshed is not None
    assert refreshed["record_count"] == 3


def test_syslog_delete_rejects_registered_path_traversal(
    tmp_path: Path,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)
    registered = repository.get_raw_file("raw-syslog")
    assert registered is not None
    repository.upsert_raw_file(
        {
            **registered,
            "relative_path": "../outside.ndjson",
        }
    )

    preview = GroundRawDataLifecycleService(
        repository
    ).preview_syslog_deletion(
        run_id=RUN_ID,
        mode="RUN_ALL",
        record_keys=[],
        filters={},
        include_derived_events=True,
    )

    assert preview.plan is None
    assert any(
        "RAW_FILE_PATH_INVALID" in reason
        for reason in preview.blocked_reasons
    )


def test_ground_syslog_delete_job_completes_audit_and_reports_progress(
    tmp_path: Path,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)

    class ProcessAdapter:
        def __init__(self) -> None:
            self.job = None

        def start_job(self, job, **_kwargs):
            self.job = job
            return job.job_id

    process = ProcessAdapter()
    service = GroundRawDataDeletionApplicationService(
        repository,
        process_adapter=process,
        app_root=str(tmp_path / "app"),
        data_root=str(tmp_path / "data"),
    )
    preview = service.preview(
        GroundSyslogDeletePreviewRequestDTO(
            run_id=RUN_ID,
            mode="RUN_ALL",
            include_derived_events=True,
        )
    )
    accepted = service.submit(
        GroundSyslogDeleteRequestDTO(
            preview_token=preview.preview_token,
            explicit_confirmation=True,
            confirmation_text=f"DELETE {RUN_DATE}",
            include_derived_events=True,
        )
    )
    assert process.job is not None
    progress: list[tuple[str, int, int, object]] = []
    context = JobContext(
        process.job.job_id,
        process.job.task_type,
        process.job.params,
        lambda *values: progress.append(values),
        lambda: False,
        PathResolver(tmp_path / "app", tmp_path / "data"),
    )

    result = ground_syslog_delete(context)

    assert result["deleted_record_count"] == 3
    audit = repository.get_delete_operation(accepted.operation_id)
    assert audit is not None
    assert audit["status"] == "COMPLETED"
    assert audit["deleted_record_count"] == 3
    assert audit["deleted_event_count"] == 2
    assert audit["revision_before"] == {"raw-syslog": 0}
    assert audit["revision_after"] == {"raw-syslog": 1}
    assert audit["completed_at"]
    assert progress[-1][0] == "COMPLETED"


def test_ground_syslog_delete_job_records_lifecycle_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)
    operation_id = "operation-job-failure"
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="RUN_ALL",
        record_keys=[],
        filters={},
        include_derived_events=True,
    )
    assert preview.plan is not None
    repository.save_delete_operation(
        {
            "operation_id": operation_id,
            "run_id": RUN_ID,
            "mode": "RUN_ALL",
            "filters_json": "{}",
            "matched_count": preview.matched_record_count,
            "affected_file_count": preview.affected_file_count,
            "revision_before_json": json.dumps({"raw-syslog": 0}),
            "status": "PENDING",
        }
    )

    def fail_execute(*_args, **_kwargs):
        raise GroundRawLifecycleError(
            "RAW_FILE_LOCK_UNAVAILABLE",
            "无法取得文件生命周期锁",
        )

    monkeypatch.setattr(
        GroundRawDataLifecycleService,
        "execute_syslog_deletion",
        fail_execute,
    )
    context = JobContext(
        "task-failure",
        "ground_syslog_delete",
        {
            "site_id": repository.site_id,
            "operation_id": operation_id,
            "plan": preview.plan.to_dict(),
        },
        None,
        lambda: False,
        PathResolver(tmp_path / "app", tmp_path / "data"),
    )

    with pytest.raises(
        GroundRawLifecycleError,
        match="无法取得文件生命周期锁",
    ):
        ground_syslog_delete(context)

    audit = repository.get_delete_operation(operation_id)
    assert audit is not None
    assert audit["status"] == "FAILED"
    assert audit["failure_code"] == "RAW_FILE_LOCK_UNAVAILABLE"
    assert audit["completed_at"]


def test_syslog_delete_maps_file_lock_timeout_to_stable_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository, _raw_path = _setup_completed_run(tmp_path)
    lifecycle = GroundRawDataLifecycleService(repository)
    preview = lifecycle.preview_syslog_deletion(
        run_id=RUN_ID,
        mode="RUN_ALL",
        record_keys=[],
        filters={},
        include_derived_events=True,
    )
    assert preview.plan is not None

    @contextmanager
    def unavailable_lock(*_args, **_kwargs):
        raise TimeoutError("simulated lifecycle lock timeout")
        yield

    monkeypatch.setattr(
        "netconsole.services.ground_unattended.raw_lifecycle."
        "interprocess_file_lock",
        unavailable_lock,
    )

    with pytest.raises(
        GroundRawLifecycleError,
        match="无法取得 Syslog 文件生命周期锁",
    ) as raised:
        lifecycle.execute_syslog_deletion(
            preview.plan,
            operation_id="operation-lock-timeout",
        )
    assert raised.value.code == "RAW_FILE_LOCK_UNAVAILABLE"


def _setup_completed_run(
    tmp_path: Path,
) -> tuple[GroundUnattendedRepository, Path]:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"),
        site_id="site-a",
    )
    run = repository.create_or_get_run(
        run_id=RUN_ID,
        run_date=RUN_DATE,
        scheduled_start_at="2026-07-29T09:00:00+08:00",
        scheduled_end_at="2026-07-29T10:00:00+08:00",
    )
    repository.update_run(
        str(run["run_id"]),
        state="COMPLETED",
        actual_started_at="2026-07-29T09:00:00+08:00",
        actual_ended_at="2026-07-29T09:10:00+08:00",
    )
    raw_path = (
        paths.ground_unattended_active_dir("site-a", RUN_DATE)
        / "realtime"
        / "syslog"
        / "events.ndjson"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        _syslog_record(1, "ordinary"),
        _syslog_record(2, "WMESH LINKUP peer=AP01"),
        _syslog_record(3, "ordinary tail"),
    ]
    raw_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-syslog",
            "run_id": RUN_ID,
            "train_id": "_03",
            "device_uuid": "mr-ct",
            "mr_role": "CT",
            "data_type": "syslog",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": rows[0]["receive_time"],
            "end_time": rows[-1]["receive_time"],
            "record_count": len(rows),
            "size_bytes": raw_path.stat().st_size,
            "sha256": _sha256(raw_path),
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )
    repository.insert_wmesh_events(
        [
            {
                "run_id": RUN_ID,
                "device_uuid": "mr-ct",
                "train_id": "_03",
                "mr_role": "CT",
                "event_type": "MESH_LINKUP",
                "device_time": rows[1]["receive_time"],
                "receive_time": rows[1]["receive_time"],
                "source_ip": "192.0.2.3",
                "raw_file_id": "raw-syslog",
                "raw_line_number": 2,
                "details": {
                    "global_receive_sequence": 2,
                    "source_receive_sequence": 2,
                },
            }
        ]
    )
    repository.add_event(
        run_id=RUN_ID,
        event_type="mesh_linkup",
        title="WMESH 建链",
        details={
            "raw_file_id": "raw-syslog",
            "global_receive_sequence": 2,
            "source_receive_sequence": 2,
        },
        ts=rows[1]["receive_time"],
    )
    repository.add_event(
        run_id=RUN_ID,
        event_type="run_started",
        title="运行开始",
        ts=rows[0]["receive_time"],
    )
    repository.add_event(
        run_id=RUN_ID,
        event_type="ping_loss_pattern",
        title="Ping 丢包模式",
        details={
            "raw_file_id": "raw-syslog",
            "global_receive_sequence": 2,
            "source_receive_sequence": 2,
        },
        ts=rows[1]["receive_time"],
    )
    return repository, raw_path


def _syslog_record(sequence: int, raw_text: str) -> dict[str, object]:
    return {
        "receive_time": f"2026-07-29T09:00:0{sequence}+08:00",
        "global_receive_sequence": sequence,
        "source_receive_sequence": sequence,
        "source_ip": "192.0.2.3",
        "train_id": "_03",
        "train_no": "03",
        "device_uuid": "mr-ct",
        "mr_name": "列车03-MR-CT",
        "mr_role": "CT",
        "system_name": "MR03-CT",
        "facility": "local7",
        "severity": "info",
        "identity_status": "VERIFIED",
        "raw_text": raw_text,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
