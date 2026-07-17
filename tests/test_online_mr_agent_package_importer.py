from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_agent import ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES
from netconsole.models.online_mr_application import (
    OnlineMrExecutorKind,
    OnlineMrMappingState,
    OnlineMrPhase,
    OnlineMrTaskSessionMapping,
)
from netconsole.models.task_snapshot import TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.online_mr.agent_package_importer import (
    OnlineMrAgentPackageImporter,
)
from scripts.maintenance.check_online_mr_session_state import (
    FAILED,
    WARNING,
    audit_online_mr_session,
)


SITE = "site-a"
DEVICE_ID = 7
DEVICE_NAME = "MR-07"
MR_ID = "7"
MR_NAME = "MR-07"


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs(SITE)
    return paths


def _write_package(
    path: Path,
    *,
    session_id: str = "agent-session-1",
    agent_task_id: str = "agent-task-1",
    status: str = "stopped",
    root: bool = True,
    omit: set[str] | None = None,
    extra: dict[str, str] | None = None,
    secret_file: str = "",
    secret_key: str = "password",
    private_session_path: str = "",
    data_integrity: str = "",
    raw_marker: str = "raw evidence\n",
    manifest_status: str = "",
    session_meta_overrides: dict[str, object] | None = None,
    task_overrides: dict[str, object] | None = None,
) -> Path:
    omit = omit or set()
    prefix = f"{session_id}_{MR_NAME}_agent/" if root else ""
    session_status = status.upper()
    stop_reason = {
        "force_stopped": "force_stop",
        "failed": "runner_error",
        "running": "",
    }.get(status, "user_stop")
    documents: dict[str, dict[str, object]] = {
        "session_meta.json": {
            "session_id": session_id,
            "site": SITE,
            "device_id": str(DEVICE_ID),
            "device_name": DEVICE_NAME,
            "mr_id": MR_ID,
            "mr_name": MR_NAME,
            "status": session_status,
            "started_at": "2026-07-13 10:00:00",
            "ended_at": None if status == "running" else "2026-07-13 10:02:00",
            "duration_minutes": 2.0,
            "stop_reason": stop_reason,
            "force_stopped": status == "force_stopped",
            "data_integrity": data_integrity,
            "raw_log_path": private_session_path or "raw/collector_output_raw.log",
            "fping": {"enabled": False},
            "iperf": {"enabled": False},
        },
        "task.json": {
            "task_id": agent_task_id,
            "task_type": "mr_realtime_collect",
            "status": manifest_status or status,
            "created_at": "2026-07-13T10:00:00Z",
            "start_time": "2026-07-13T10:00:00Z",
            "end_time": "" if status == "running" else "2026-07-13T10:02:00Z",
            "error_message": "Agent runner failed" if status == "failed" else "",
            "params": {"target": {"password": ""}},
        },
        "manifest.json": {
            "package_type": "netconsole_agent_collect_package",
            "package_version": 1,
            "task_type": "mr_realtime_collect",
            "task_id": agent_task_id,
            "agent_id": "agent-a",
            "agent_name": "Agent A",
            "created_at": "2026-07-13T10:02:01Z",
            "start_time": "2026-07-13T10:00:00Z",
            "end_time": "2026-07-13T10:02:00Z",
            "status": status,
        },
        "agent_info.json": {
            "agent_id": "agent-a",
            "agent_name": "Agent A",
            "version": "test",
        },
        "system_info.json": {
            "os": "windows",
            "arch": "amd64",
            "hostname": "agent-host",
        },
        "stop_reason.json": {"reason": stop_reason or "running"},
    }
    documents["session_meta.json"].update(session_meta_overrides or {})
    documents["task.json"].update(task_overrides or {})
    if secret_file:
        documents[secret_file][secret_key] = "plain-secret"

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(ONLINE_MR_AGENT_PACKAGE_REQUIRED_FILES):
            if name in omit:
                continue
            if name in documents:
                content = json.dumps(documents[name], ensure_ascii=False)
            elif name == "raw/collector_output_raw.log":
                content = raw_marker
            elif name.endswith(".json"):
                content = "{}\n"
            else:
                content = ""
            archive.writestr(prefix + name, content)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return path


def _import(importer: OnlineMrAgentPackageImporter, package: Path, **kwargs):
    return importer.import_package(
        package,
        site_id=SITE,
        site_name=SITE,
        device_id=DEVICE_ID,
        device_name=DEVICE_NAME,
        mr_id=MR_ID,
        mr_name=MR_NAME,
        owner="test",
        **kwargs,
    )


def test_imports_standard_agent_package_and_registers_terminal_operation(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    expected = paths.online_mr_session_dir(SITE, "MR-07__7", "agent-session-1")
    assert result.success and result.imported
    assert result.session_dir == expected.resolve()
    assert (expected / "raw" / "collector_output_raw.log").read_text(
        encoding="utf-8"
    ) == "raw evidence\n"
    assert (expected / "session_meta.json").is_file()
    assert (expected / "import_manifest.json").is_file()
    assert (expected / "outputs" / "agent-session-1.zip").is_file()
    assert package.is_file()

    mapping = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    ).get_by_session("agent-session-1")
    task = TaskRepository(paths.site_tasks_db_path(SITE)).get(result.task_id)
    assert mapping is not None
    assert mapping.executor_kind is OnlineMrExecutorKind.AGENT
    assert mapping.mapping_state is OnlineMrMappingState.TERMINAL
    assert (
        task is not None
        and task.status is TaskState.COMPLETED
        and task.source == "agent"
    )
    assert not paths.site_tasks_db_path("demo").exists()

    report = audit_online_mr_session(paths, task_id=result.task_id)
    assert all(check.status != FAILED for check in report.checks)


def test_same_zip_is_idempotent_without_duplicate_task_or_mapping(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")
    importer = OnlineMrAgentPackageImporter(paths)

    first = _import(importer, package)
    second = _import(importer, package)

    assert first.imported
    assert second.success and second.already_imported and not second.imported
    assert second.task_id == first.task_id
    assert len(TaskRepository(paths.site_tasks_db_path(SITE)).list()) == 1
    assert (
        len(
            OnlineMrTaskSessionRepository(
                paths.site_tasks_db_path(SITE), site_id=SITE
            ).list()
        )
        == 1
    )


def test_import_manifest_records_remote_package_id(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        source_package_id="remote-package-1",
    )

    manifest = json.loads(
        (result.session_dir / "import_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_package_id"] == "remote-package-1"


def test_agent_local_identity_requires_explicit_mapping(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "agent-local-identity.zip",
        session_meta_overrides={
            "device_id": "agent-device-12",
            "device_name": "12-MR-CT",
            "mr_id": "agent-mr-12",
            "mr_name": "12-MR-CT",
        },
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("device_id" in error for error in result.errors)
    assert any("mr_id" in error for error in result.errors)
    assert not paths.site_tasks_db_path(SITE).exists()
    assert not paths.online_mr_root(SITE).exists()


def test_manual_identity_override_preserves_source_and_resolved_identity(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "agent-local-identity.zip",
        session_meta_overrides={
            "device_id": "agent-device-12",
            "device_name": "12-MR-CT",
            "mr_id": "agent-mr-12",
            "mr_name": "12-MR-CT",
        },
    )

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        identity_match_policy="manual_override",
        allow_identity_override=True,
    )

    assert result.success and result.imported
    assert any("手工指定" in warning for warning in result.warnings)
    meta = json.loads(
        (result.session_dir / "session_meta.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (result.session_dir / "import_manifest.json").read_text(encoding="utf-8")
    )
    mapping = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    ).get_by_task(result.task_id)
    assert meta["device_id"] == DEVICE_ID
    assert meta["mr_id"] == MR_ID
    assert manifest["identity"]["match_method"] == "manual_override"
    assert manifest["identity"]["source"] == {
        "site_id": SITE,
        "device_id": "agent-device-12",
        "device_name": "12-MR-CT",
        "mr_id": "agent-mr-12",
        "mr_name": "12-MR-CT",
        "host": "",
        "agent_task_id": "agent-task-1",
        "session_id": "agent-session-1",
    }
    assert manifest["identity"]["resolved"]["device_id"] == str(DEVICE_ID)
    assert manifest["identity"]["resolved"]["device_name"] == DEVICE_NAME
    assert meta["import_context"]["match_method"] == "manual_override"
    assert mapping is not None
    assert mapping.device_id == str(DEVICE_ID)
    assert mapping.mr_id == MR_ID
    assert not paths.site_tasks_db_path("demo").exists()


def test_ip_match_allows_temporary_agent_identity(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "agent-ip-match.zip",
        session_meta_overrides={
            "device_id": "agent-device-12",
            "device_name": "12-MR-CT",
            "mr_id": "agent-mr-12",
            "mr_name": "12-MR-CT",
            "target_host": "192.0.2.12",
        },
    )

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        identity_match_policy="ip_match",
        expected_host="192.0.2.12",
    )

    assert result.success and result.imported
    assert any("按 IP 匹配" in warning for warning in result.warnings)
    manifest = json.loads(
        (result.session_dir / "import_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["identity"]["match_method"] == "ip_match"
    assert manifest["identity"]["source"]["host"] == "192.0.2.12"
    assert manifest["identity"]["resolved"]["host"] == "192.0.2.12"


@pytest.mark.parametrize("source_host", ["", "192.0.2.13"])
def test_ip_match_rejects_missing_or_different_host(
    tmp_path: Path, source_host: str
) -> None:
    paths = _paths(tmp_path)
    overrides: dict[str, object] = {
        "device_id": "agent-device-12",
        "device_name": "12-MR-CT",
        "mr_id": "agent-mr-12",
        "mr_name": "12-MR-CT",
    }
    if source_host:
        overrides["target_host"] = source_host
    package = _write_package(
        tmp_path / "agent-ip-mismatch.zip",
        session_meta_overrides=overrides,
    )

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        identity_match_policy="ip_match",
        expected_host="192.0.2.12",
    )

    assert not result.success
    assert any("IP" in error for error in result.errors)
    assert not paths.site_tasks_db_path(SITE).exists()


def test_manual_override_requires_explicit_permission(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "agent-manual-denied.zip",
        session_meta_overrides={
            "device_id": "agent-device-12",
            "device_name": "12-MR-CT",
            "mr_id": "agent-mr-12",
            "mr_name": "12-MR-CT",
        },
    )

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        identity_match_policy="manual_override",
    )

    assert not result.success
    assert any("allow_identity_override" in error for error in result.errors)
    assert not paths.site_tasks_db_path(SITE).exists()


def test_idempotent_import_rejects_incomplete_task_registration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")
    importer = OnlineMrAgentPackageImporter(paths)
    first = _import(importer, package)
    repository = TaskRepository(paths.site_tasks_db_path(SITE))
    task = repository.get(first.task_id)
    assert task is not None
    repository.save(replace(task, status=TaskState.RUNNING))

    second = _import(importer, package)

    assert not second.success and second.conflict
    assert any("Task/Mapping 登记不完整" in error for error in second.errors)


def test_import_updates_existing_agent_task_and_mapping_to_terminal(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")
    controller_task_id = "controller-agent-task-1"
    now = utc_now_iso()
    TaskRepository(paths.site_tasks_db_path(SITE)).save(
        TaskSnapshot(
            task_id=controller_task_id,
            task_type="online_mr_collection_start",
            task_name="Online MR - MR-07",
            status=TaskState.RUNNING,
            created_time=now,
            updated_time=now,
            owner="controller",
            device=DEVICE_NAME,
            agent="agent-a",
            source="agent",
            site_name=SITE,
        )
    )
    repository = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    )
    repository.create(
        OnlineMrTaskSessionMapping(
            controller_task_id=controller_task_id,
            session_id="agent-session-1",
            site_id=SITE,
            device_id=str(DEVICE_ID),
            device_name=DEVICE_NAME,
            mr_id=MR_ID,
            mr_name=MR_NAME,
            executor_kind=OnlineMrExecutorKind.AGENT,
            agent_id="agent-a",
            phase=OnlineMrPhase.FINALIZING,
            mapping_state=OnlineMrMappingState.LINKED,
            created_at=now,
            updated_at=now,
        )
    )

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        controller_task_id=controller_task_id,
        agent_id="agent-a",
    )

    task = TaskRepository(paths.site_tasks_db_path(SITE)).get(controller_task_id)
    mapping = repository.get_by_task(controller_task_id)
    assert result.success and result.task_id == controller_task_id
    assert task is not None and task.status is TaskState.COMPLETED
    assert task.owner == "controller"
    assert (
        mapping is not None and mapping.mapping_state is OnlineMrMappingState.TERMINAL
    )
    assert len(TaskRepository(paths.site_tasks_db_path(SITE)).list()) == 1
    assert len(repository.list()) == 1


def test_import_does_not_overwrite_cancelled_controller_task(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")
    controller_task_id = "controller-agent-task-cancelled"
    now = utc_now_iso()
    task_repository = TaskRepository(paths.site_tasks_db_path(SITE))
    task_repository.save(
        TaskSnapshot(
            task_id=controller_task_id,
            task_type="online_mr_collection_start",
            task_name="Online MR - MR-07",
            status=TaskState.CANCELLED,
            created_time=now,
            updated_time=now,
            owner="controller",
            device=DEVICE_NAME,
            agent="agent-a",
            source="agent",
            site_name=SITE,
        )
    )
    mapping_repository = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    )
    mapping_repository.create(
        OnlineMrTaskSessionMapping(
            controller_task_id=controller_task_id,
            session_id="agent-session-1",
            site_id=SITE,
            device_id=str(DEVICE_ID),
            device_name=DEVICE_NAME,
            mr_id=MR_ID,
            mr_name=MR_NAME,
            executor_kind=OnlineMrExecutorKind.AGENT,
            agent_id="agent-a",
            phase=OnlineMrPhase.FINALIZING,
            mapping_state=OnlineMrMappingState.LINKED,
            created_at=now,
            updated_at=now,
        )
    )

    result = _import(
        OnlineMrAgentPackageImporter(paths),
        package,
        controller_task_id=controller_task_id,
        agent_id="agent-a",
    )

    task = task_repository.get(controller_task_id)
    mapping = mapping_repository.get_by_task(controller_task_id)
    assert not result.success
    assert any("任务状态已变化" in error for error in result.errors)
    assert task is not None and task.status is TaskState.CANCELLED
    assert mapping is not None and mapping.mapping_state is OnlineMrMappingState.LINKED


def test_different_zip_with_same_session_is_conflict_without_overwrite(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    importer = OnlineMrAgentPackageImporter(paths)
    first = _write_package(tmp_path / "first.zip", raw_marker="first\n")
    second = _write_package(
        tmp_path / "second.zip", agent_task_id="agent-task-2", raw_marker="second\n"
    )

    imported = _import(importer, first)
    conflict = _import(importer, second)

    assert imported.imported
    assert not conflict.success and conflict.conflict and conflict.status == "conflict"
    assert (imported.session_dir / "raw" / "collector_output_raw.log").read_text(
        encoding="utf-8"
    ) == "first\n"


@pytest.mark.parametrize(
    "name",
    ["../../evil.txt", "C:\\evil.txt", "/etc/passwd", "\\\\server\\share\\evil.txt"],
)
def test_rejects_unsafe_zip_member_paths(tmp_path: Path, name: str) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "unsafe.zip", extra={name: "bad"})

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success and result.status == "invalid"
    assert any("不安全的包路径" in error for error in result.errors)
    assert not paths.online_mr_root(SITE).exists()


def test_rejects_stop_request(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "stop.zip",
        extra={"agent-session-1_MR-07_agent/stop.request": "stop"},
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("stop.request" in error for error in result.errors)


@pytest.mark.parametrize(
    "filename,key",
    [
        ("session_meta.json", "password"),
        ("task.json", "access_token"),
        ("agent_info.json", "credential"),
        ("stop_reason.json", "private_key"),
    ],
)
def test_rejects_non_empty_secret_in_public_metadata(
    tmp_path: Path, filename: str, key: str
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "secret.zip", secret_file=filename, secret_key=key
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("敏感字段" in error for error in result.errors)


def test_accepts_agent_masked_password_placeholder(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "masked-password.zip",
        task_overrides={"params": {"target": {"password": "******"}}},
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert result.success and result.imported


def test_rejects_private_absolute_path_in_session_meta(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "private-path.zip", private_session_path="C:\\Agent\\data\\raw.log"
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("私有绝对路径" in error for error in result.errors)


def test_rejects_secret_in_other_public_json(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "target-secret.zip",
        extra={
            "agent-session-1_MR-07_agent/target_snapshot.json": '{"api_token":"plain-secret"}'
        },
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any(
        "target_snapshot.json" in error and "敏感字段" in error
        for error in result.errors
    )


def test_rejects_missing_session_meta_without_writing_database(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "missing-meta.zip", omit={"session_meta.json"})

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("session_meta.json" in error for error in result.errors)
    assert not paths.site_tasks_db_path(SITE).exists()


def test_rejects_package_declared_invalid(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "invalid-integrity.zip", data_integrity="invalid"
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("data_integrity" in error for error in result.errors)


def test_force_stopped_package_imports_as_partial_terminal_warning(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "forced.zip", status="force_stopped")

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert result.success and result.data_integrity == "partial"
    task = TaskRepository(paths.site_tasks_db_path(SITE)).get(result.task_id)
    mapping = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    ).get_by_task(result.task_id)
    meta = json.loads(
        (result.session_dir / "session_meta.json").read_text(encoding="utf-8")
    )
    assert task is not None and task.status is TaskState.CANCELLED
    assert (
        mapping is not None
        and mapping.mapping_state is OnlineMrMappingState.TERMINAL
        and mapping.force_stopped
    )
    assert meta["status"] == "FORCED_STOPPED" and meta["data_integrity"] == "partial"
    report = audit_online_mr_session(paths, task_id=result.task_id)
    assert report.status == WARNING
    assert all(check.status != FAILED for check in report.checks)


def test_failed_package_registers_failed_task_and_terminal_mapping(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "failed.zip", status="failed")

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    task = TaskRepository(paths.site_tasks_db_path(SITE)).get(result.task_id)
    mapping = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    ).get_by_task(result.task_id)
    meta = json.loads(
        (result.session_dir / "session_meta.json").read_text(encoding="utf-8")
    )
    assert result.success and result.data_integrity == "partial"
    assert task is not None and task.status is TaskState.FAILED
    assert (
        mapping is not None and mapping.mapping_state is OnlineMrMappingState.TERMINAL
    )
    assert mapping.error_summary == "Agent runner failed"
    assert meta["status"] == "FAILED"


def test_running_package_is_rejected_in_strict_mode(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "running.zip", status="running")

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("strict 模式拒绝非终态" in error for error in result.errors)
    assert not paths.site_tasks_db_path(SITE).exists()


def test_rejects_inconsistent_package_status_metadata(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(
        tmp_path / "inconsistent-status.zip", manifest_status="running"
    )

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert any("status 不一致" in error for error in result.errors)
    assert not paths.site_tasks_db_path(SITE).exists()


def test_running_package_can_be_imported_as_explicit_partial_evidence(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "running-partial.zip", status="running")

    result = _import(
        OnlineMrAgentPackageImporter(paths), package, import_mode="partial"
    )

    task = TaskRepository(paths.site_tasks_db_path(SITE)).get(result.task_id)
    mapping = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    ).get_by_task(result.task_id)
    meta = json.loads(
        (result.session_dir / "session_meta.json").read_text(encoding="utf-8")
    )
    assert result.success and result.data_integrity == "partial"
    assert task is not None and task.status is TaskState.CANCELLED
    assert (
        mapping is not None and mapping.mapping_state is OnlineMrMappingState.TERMINAL
    )
    assert meta["status"] == "ABORTED"


def test_corrupt_zip_is_invalid_and_source_is_preserved(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = tmp_path / "corrupt.zip"
    package.write_bytes(b"not a zip")

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success and result.status == "invalid"
    assert package.read_bytes() == b"not a zip"
    assert not paths.site_tasks_db_path(SITE).exists()


def test_accepts_package_without_outer_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "flat.zip", root=False)

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert result.success and result.imported
    assert (
        result.session_dir
        == paths.online_mr_session_dir(SITE, "MR-07__7", "agent-session-1").resolve()
    )


def test_imported_database_rows_are_in_selected_site_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")

    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert result.success
    with sqlite3.connect(paths.site_tasks_db_path(SITE)) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM task_snapshots").fetchone()[0] == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM online_mr_task_sessions"
            ).fetchone()[0]
            == 1
        )
    assert not paths.site_tasks_db_path("demo").exists()


def test_database_registration_failure_rolls_back_mapping_and_final_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    package = _write_package(tmp_path / "source.zip")

    def fail_record(*_args, **_kwargs) -> None:
        raise sqlite3.OperationalError("simulated registration failure")

    monkeypatch.setattr(TaskRepository, "record", fail_record)
    result = _import(OnlineMrAgentPackageImporter(paths), package)

    assert not result.success
    assert package.is_file()
    assert not paths.online_mr_session_dir(SITE, "MR-07__7", "agent-session-1").exists()
    repository = OnlineMrTaskSessionRepository(
        paths.site_tasks_db_path(SITE), site_id=SITE
    )
    assert repository.get_by_session("agent-session-1") is None
    imports_root = paths.site_imports_dir(SITE) / "online_mr"
    assert not imports_root.exists() or not any(imports_root.iterdir())
