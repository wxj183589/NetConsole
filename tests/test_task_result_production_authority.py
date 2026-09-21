from __future__ import annotations

import json
import hashlib
import sqlite3
import zlib
from pathlib import Path

import pytest

import netconsole.services.production_database_maintenance as production_maintenance
import scripts.maintenance.close_task_result_ref_only as ref_only
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.core.runtime_environment import write_data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.repositories.task_repository import TaskRepository
from netconsole.repositories.task_result_blob_repository import read_blob
from scripts.maintenance.close_task_result_ref_only import (
    TASK_RESULT_REF_ONLY_AUTHORIZATION,
    TaskResultClosureError,
    apply_ref_only_plan,
    build_ref_only_plan,
)
from scripts.maintenance.manage_task_result_rollout import (
    TASK_RESULT_ROLLOUT_AUTHORIZATION,
    main as rollout_cli_main,
)
from netconsole.services.production_database_maintenance import PRODUCTION_SITE_ALLOWLIST


def _write_registry(root: Path, *, include_unlisted: bool = False) -> None:
    sites = [
        {
            "site_id": site_id,
            "display_name": display_name,
            "relative_path": f"sites/{site_id}",
        }
        for site_id, display_name in PRODUCTION_SITE_ALLOWLIST.items()
        if site_id in {"sxl1", "hzl10"}
    ]
    if include_unlisted:
        sites.append(
            {
                "site_id": "unlisted-site",
                "display_name": "未登记局点",
                "relative_path": "sites/unlisted-site",
            }
        )
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "site_registry.json").write_text(
        json.dumps({"schema_version": 2, "sites": sites}, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_authority_db(
    path: Path,
    *,
    task_id: str = "candidate",
    authority_result: dict[str, object] | None = None,
) -> None:
    repository = TaskRepository(path)
    timestamp = "2026-09-22T01:00:00Z"
    result = {"task": task_id, "value": 1}
    repository.record(
        TaskSnapshot(
            task_id=task_id,
            task_type="production-authority-test",
            task_name="production-authority-test",
            status=TaskState.COMPLETED,
            created_time=timestamp,
            finished_time=timestamp,
            updated_time=timestamp,
            progress=100,
            result=result,
        ),
        TaskEvent(
            event_id=f"event-{task_id}",
            task_id=task_id,
            type="finished",
            time=timestamp,
            source="test",
            payload={"result": result},
        ),
    )
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='trigger' AND name='trg_task_results_immutable'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER trg_task_results_immutable")
        for row in connection.execute(
            "SELECT result_id, content_sha256, byte_size FROM task_results"
        ).fetchall():
            canonical = read_blob(
                connection,
                content_sha256=row[1],
                expected_bytes=row[2],
            )
            connection.execute(
                "UPDATE task_results SET canonical_json=? WHERE result_id=?",
                (canonical, row[0]),
            )
        if authority_result is not None:
            row = connection.execute(
                "SELECT result_id, content_sha256, task_id, terminal_event_type, schema_version, "
                "created_time FROM task_results"
            ).fetchone()
            canonical = json.dumps(
                authority_result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            encoded = canonical.encode("utf-8")
            content_sha256 = hashlib.sha256(encoded).hexdigest()
            compressed = zlib.compress(encoded)
            result_id = "tr-" + hashlib.sha256(
                f"{row['task_id']}\0{row['terminal_event_type']}\0{content_sha256}".encode(
                    "utf-8"
                )
            ).hexdigest()
            connection.execute(
                "DELETE FROM task_result_blobs WHERE content_sha256=?",
                (row["content_sha256"],),
            )
            connection.execute(
                "INSERT INTO task_result_blobs("
                "content_sha256, codec, compressed_blob, uncompressed_bytes, "
                "compressed_bytes, created_time, verified_at"
                ") VALUES (?, 'zlib', ?, ?, ?, ?, ?)",
                (
                    content_sha256,
                    compressed,
                    len(encoded),
                    len(compressed),
                    row["created_time"],
                    row["created_time"],
                ),
            )
            connection.execute(
                "DELETE FROM task_results WHERE result_id=?", (row["result_id"],)
            )
            connection.execute(
                "INSERT INTO task_results("
                "result_id, task_id, terminal_event_type, canonical_json, sha256, "
                "byte_size, schema_version, created_time, content_sha256, "
                "blob_codec, blob_ready"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'zlib', 1)",
                (
                    result_id,
                    row["task_id"],
                    row["terminal_event_type"],
                    canonical,
                    content_sha256,
                    len(encoded),
                    row["schema_version"],
                    row["created_time"],
                    content_sha256,
                ),
            )
        connection.execute(trigger)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _production_fixture(
    tmp_path: Path,
    *,
    include_unlisted: bool = False,
    authority_result: dict[str, object] | None = None,
) -> tuple[Path, dict[str, Path]]:
    root = tmp_path / "relocated-production-root"
    write_data_environment(
        root,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    _write_registry(root, include_unlisted=include_unlisted)
    databases: dict[str, Path] = {}
    for site_id in ("sxl1", "hzl10"):
        database = root / "sites" / site_id / "db" / "tasks.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        _make_authority_db(
            database,
            task_id=f"candidate-{site_id}",
            authority_result=authority_result if site_id == "sxl1" else None,
        )
        databases[site_id] = database
    if include_unlisted:
        database = root / "sites" / "unlisted-site" / "db" / "tasks.db"
        database.parent.mkdir(parents=True, exist_ok=True)
        _make_authority_db(database, task_id="candidate-unlisted")
        databases["unlisted-site"] = database
    return root, databases


def test_relocated_production_plan_binds_canonical_site_and_operation(
    tmp_path: Path,
) -> None:
    root, databases = _production_fixture(tmp_path)

    plan = build_ref_only_plan(
        databases["sxl1"],
        site_id="sxl1",
        data_root=root,
        generated_at="2026-09-22T02:00:00Z",
    )

    assert plan["authority_mode"] == "PRODUCTION_CANONICAL"
    assert plan["operation"] == "TASK_RESULT_REF_ONLY_CLOSURE"
    assert plan["database"] == {
        "name": "tasks.db",
        "path": str(databases["sxl1"].resolve()),
        "site_id": "sxl1",
    }
    assert plan["rollout"]["revision"] == 1
    assert plan["target_state"]["storage_action"] == (
        "CLEAR_TASK_RESULTS_CANONICAL_JSON_ONLY"
    )


def test_production_ref_only_requires_operation_authorization_before_backup(
    tmp_path: Path,
) -> None:
    root, databases = _production_fixture(tmp_path)
    plan = build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)
    plan_path = tmp_path / "ref-only-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    backup = tmp_path / "backup.db"

    with pytest.raises(TaskResultClosureError, match="AUTHORIZATION_REQUIRED"):
        apply_ref_only_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=backup,
            authorization=ref_only.AUTHORIZATION,
        )
    assert not backup.exists()


def test_production_ref_only_preserves_blob_references_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root, databases = _production_fixture(tmp_path)
    database = databases["sxl1"]
    plan = build_ref_only_plan(database, site_id="sxl1", data_root=root)
    plan_path = tmp_path / "ref-only-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    first = apply_ref_only_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path / "ref-only-backup.db",
        authorization=TASK_RESULT_REF_ONLY_AUTHORIZATION,
    )
    assert first["released_rows"] == 1
    assert first["backup"]["site_id"] == "sxl1"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM task_results").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM task_results WHERE canonical_json<>''"
        ).fetchone()[0] == 0
    snapshot = TaskRepository(database).get("candidate-sxl1")
    assert snapshot is not None and snapshot.result_id
    assert TaskRepository(database).get_result(snapshot.result_id)["result"] == {
        "task": "candidate-sxl1",
        "value": 1,
    }

    replay = apply_ref_only_plan(
        plan_path,
        expected_plan_digest=plan["plan_digest"],
        backup_path=tmp_path / "ref-only-replay-backup.db",
        authorization=TASK_RESULT_REF_ONLY_AUTHORIZATION,
    )
    assert replay["no_op"] is True
    assert replay["backup"] is None


def test_cross_site_database_path_is_not_a_production_identity(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)

    with pytest.raises(TaskResultClosureError, match="PATH_NOT_CANONICAL"):
        build_ref_only_plan(
            databases["sxl1"], site_id="hzl10", data_root=root
        )


def test_arbitrary_production_tasks_db_path_is_rejected(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    arbitrary = root / "other" / "db" / "tasks.db"
    arbitrary.parent.mkdir(parents=True)
    _make_authority_db(arbitrary, task_id="arbitrary")

    with pytest.raises(TaskResultClosureError, match="PATH_NOT_CANONICAL"):
        build_ref_only_plan(arbitrary, site_id="sxl1", data_root=root)


@pytest.mark.parametrize(
    "requested",
    [
        "../tasks.db",
        r"..\tasks.db",
        r"C:\other\tasks.db",
        r"\\server\share\tasks.db",
        "file://server/share/tasks.db",
    ],
)
def test_production_direct_path_traversal_and_unc_forms_are_rejected(
    tmp_path: Path, requested: str
) -> None:
    root, _databases = _production_fixture(tmp_path)

    with pytest.raises(TaskResultClosureError, match="PATH_NOT_CANONICAL"):
        build_ref_only_plan(requested, site_id="sxl1", data_root=root)


def test_cross_site_plan_cannot_redirect_backup_or_restore_target(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    plan = build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)
    plan["database"]["path"] = str(databases["hzl10"].resolve())
    plan["source"]["path"] = str(databases["hzl10"].resolve())
    plan["plan_digest"] = ref_only._digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )
    plan_path = tmp_path / "cross-site-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    backup = tmp_path / "cross-site-backup.db"

    with pytest.raises(TaskResultClosureError, match="PATH_NOT_CANONICAL"):
        apply_ref_only_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=backup,
            authorization=TASK_RESULT_REF_ONLY_AUTHORIZATION,
        )
    assert not backup.exists()


def test_unlisted_site_with_valid_database_is_rejected_before_collection(
    tmp_path: Path,
) -> None:
    root, databases = _production_fixture(tmp_path, include_unlisted=True)

    with pytest.raises(TaskResultClosureError, match="NOT_ALLOWLISTED"):
        build_ref_only_plan(
            databases["unlisted-site"], site_id="unlisted-site", data_root=root
        )


def test_fake_tenth_site_is_not_production_authority(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path, include_unlisted=True)

    with pytest.raises(TaskResultClosureError, match="NOT_ALLOWLISTED"):
        build_ref_only_plan(
            databases["unlisted-site"], site_id="unlisted-site", data_root=root
        )


def test_rollout_production_marker_routes_unlisted_site_to_canonical_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _databases = _production_fixture(tmp_path, include_unlisted=True)
    monkeypatch.setenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", "1")

    with pytest.raises(SystemExit, match="NOT_ALLOWLISTED"):
        rollout_cli_main(
            [
                "status",
                "--data-root",
                str(root),
                "--site-id",
                "unlisted-site",
            ]
        )


def test_production_registry_provider_failure_is_fail_closed(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    (root / "config" / "site_registry.json").unlink()

    with pytest.raises(TaskResultClosureError, match="REGISTRY_UNAVAILABLE"):
        build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)


def test_production_environment_marker_missing_is_fail_closed(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    (root / "runtime_mode.json").unlink()

    with pytest.raises(TaskResultClosureError, match="DATA_ENVIRONMENT_UNAVAILABLE"):
        build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)


def test_canonical_result_reference_protects_ref_only_plan(tmp_path: Path) -> None:
    root, databases = _production_fixture(
        tmp_path,
        authority_result={
            "task": "candidate-sxl1",
            "value": 1,
            "online_mr_session_id": "session-from-canonical-result",
        },
    )

    with pytest.raises(TaskResultClosureError, match="LONG_TERM_REFERENCE_PROTECTED"):
        build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)


def test_malformed_production_registry_is_fail_closed(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    (root / "config" / "site_registry.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(TaskResultClosureError, match="REGISTRY_UNAVAILABLE"):
        build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)


def test_empty_production_allowlist_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    monkeypatch.setattr(production_maintenance, "PRODUCTION_SITE_ALLOWLIST", {})

    with pytest.raises(TaskResultClosureError, match="NOT_ALLOWLISTED"):
        build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)


def test_production_site_reparse_point_is_rejected_before_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, databases = _production_fixture(tmp_path)
    site_root = (root / "sites" / "sxl1").resolve()
    original = production_maintenance._is_link_or_reparse_point
    monkeypatch.setattr(
        production_maintenance,
        "_is_link_or_reparse_point",
        lambda path: original(path) or Path(path).resolve() == site_root,
    )

    with pytest.raises(TaskResultClosureError, match="REGISTRY_IDENTITY_MISMATCH"):
        build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)


def test_active_task_reference_blocks_ref_only_plan(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    database = databases["sxl1"]
    with sqlite3.connect(database) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='trigger' AND name='trg_task_results_immutable'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER trg_task_results_immutable")
        connection.execute(
            "UPDATE task_snapshots SET status='RUNNING', finished_time='' "
            "WHERE task_id='candidate-sxl1'"
        )
        connection.execute(trigger)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    with pytest.raises(TaskResultClosureError, match="ACTIVE_TASK_PROTECTED"):
        build_ref_only_plan(database, site_id="sxl1", data_root=root)


def test_stale_rollout_revision_blocks_ref_only_apply(tmp_path: Path) -> None:
    root, databases = _production_fixture(tmp_path)
    plan = build_ref_only_plan(databases["sxl1"], site_id="sxl1", data_root=root)
    plan_path = tmp_path / "stale-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    with sqlite3.connect(databases["sxl1"]) as connection:
        connection.execute(
            "UPDATE task_result_storage_rollout SET revision=2, reason='stale test' "
            "WHERE singleton_id=1"
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    with pytest.raises(TaskResultClosureError, match="STALE_SOURCE"):
        apply_ref_only_plan(
            plan_path,
            expected_plan_digest=plan["plan_digest"],
            backup_path=tmp_path / "stale-backup.db",
            authorization=TASK_RESULT_REF_ONLY_AUTHORIZATION,
        )


def test_rollout_cli_uses_canonical_scope_lock_and_revision_cas(
    tmp_path: Path,
) -> None:
    root, databases = _production_fixture(tmp_path)
    with sqlite3.connect(databases["sxl1"]) as connection:
        connection.execute(
            "UPDATE task_result_storage_rollout SET state='TASK_RESULTS_DUAL_WRITE', "
            "revision=4, reason='cas fixture' WHERE singleton_id=1"
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    with pytest.raises(SystemExit, match="REVISION_CONFLICT"):
        rollout_cli_main(
            [
                "disable-dual-write",
                "--data-root",
                str(root),
                "--site-id",
                "sxl1",
                "--expected-revision",
                "3",
                "--reason",
                "CAS regression",
                "--apply",
                "--allow-production-write",
                "--authorization",
                TASK_RESULT_ROLLOUT_AUTHORIZATION,
            ]
        )
