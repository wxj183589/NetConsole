from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

import pytest

import netconsole.services.production_database_maintenance as production_maintenance_module
from netconsole.core.backend_instance_lock import BackendInstanceInUseError
from netconsole.core.build_metadata import current_build_metadata
from netconsole.core.paths import PathResolver
from netconsole.services.production_database_maintenance import (
    PRODUCTION_AUTHORIZATION_TOKEN,
    PRODUCTION_GATE_KEYS,
    ProductionEvidenceBinding,
    ProductionMaintenanceCapability,
    ProductionMaintenanceError,
    ProductionRollbackOwner,
    build_exact_manifest,
    write_exact_manifest,
)
from netconsole.services.database_footprint_maintenance import sqlite_quick_profile
from netconsole.services.database_upgrade.sqlite_consistency import sqlite_backup
from scripts.maintenance.production_database_maintenance import (
    _evidence_pass,
    _gate_evidence,
    main as production_main,
)


ROOT = Path(__file__).resolve().parents[1]
HEAD = str(current_build_metadata(ROOT)["git_commit_full"])
REHEARSAL_HEAD = "ce2f0d98f9e8305b36a004ef0b7bdbc6fd2ad237"
_REAL_BUILD_METADATA = current_build_metadata


@pytest.fixture(autouse=True)
def _clean_build_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def read_clean_metadata(root: Path) -> dict[str, Any]:
        metadata = dict(_REAL_BUILD_METADATA(root))
        metadata["build_dirty"] = False
        return metadata

    monkeypatch.setattr(
        production_maintenance_module,
        "current_build_metadata",
        read_clean_metadata,
    )


def _binding(paths: PathResolver, *, claimed_head: str = HEAD) -> ProductionEvidenceBinding:
    return ProductionEvidenceBinding.from_runtime(
        paths,
        claimed_current_head=claimed_head,
        rehearsal_evidence_head=REHEARSAL_HEAD,
        storage_registry=ROOT / "config" / "storage_registry.yaml",
        production_maintenance_script=(
            ROOT / "scripts" / "maintenance" / "production_database_maintenance.py"
        ),
    )


def _site(tmp_path: Path) -> tuple[PathResolver, Path, Path]:
    root = tmp_path / "data"
    site = root / "sites" / "宁波地铁12号线"
    site.mkdir(parents=True)
    (site / "db").mkdir()
    for name in ("devices.db", "tasks.db"):
        with closing(sqlite3.connect(site / "db" / name)) as connection:
            connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT INTO records(value) VALUES (?)", [("a",), ("b",)])
            connection.commit()
    config = root / "config"
    config.mkdir()
    (config / "application.json").write_text(
        json.dumps({"current_site": "legacy-dfd356e96ea0"}), encoding="utf-8"
    )
    (config / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "legacy-dfd356e96ea0",
                        "display_name": "宁波地铁12号线",
                        "relative_path": "sites/宁波地铁12号线",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return PathResolver(data_root=root), site, root


def _owner(
    database: str,
    *,
    operation_id: str,
    source_identity: str,
    source_sha256: str,
    schema_fingerprint: str,
    backup_sha256: str,
    backup_size: int,
    backup_relative_path: str,
) -> ProductionRollbackOwner:
    return ProductionRollbackOwner(
        backup_set_id=f"verified-{database}",
        site_id="legacy-dfd356e96ea0",
        operation_id=operation_id,
        database=database,
        source_identity=source_identity,
        source_sha256=source_sha256,
        source_revision=source_sha256,
        created_at="2026-08-17T00:00:00Z",
        verified_at="2026-08-17T00:00:01Z",
        quick_check="ok",
        schema_fingerprint=schema_fingerprint,
        rollback_required=True,
        observation_state="VERIFIED",
        superseded_by="",
        retire_state="PROTECT",
        backup_sha256=backup_sha256,
        backup_size=backup_size,
        backup_relative_path=backup_relative_path,
    )


def _backup(paths: PathResolver, database: str) -> tuple[Path, dict[str, object]]:
    site = paths.data_root / "sites" / "宁波地铁12号线"
    backup_set_id = f"verified-{database}"
    relative = (
        Path("files")
        / "backups"
        / "production-maintenance"
        / backup_set_id
        / "database.sqlite"
    )
    target = site / relative
    if not target.exists():
        sqlite_backup(site / "db" / database, target)
    return target, {"relative": relative.as_posix(), **sqlite_quick_profile(target)}


def _capability(
    paths: PathResolver,
    *,
    operation_id: str = "test-operation",
    source_identity: str = "snapshot-identity",
    runtime_lock_factory: Callable[[PathResolver], Any] | None = None,
) -> ProductionMaintenanceCapability:
    site = paths.data_root / "sites" / "宁波地铁12号线" / "db"
    profiles = {
        name: sqlite_quick_profile(site / name)
        for name in ("devices.db", "tasks.db")
    }
    backups = {
        name: _backup(paths, name)[1]
        for name in ("devices.db", "tasks.db")
    }
    kwargs = {}
    if runtime_lock_factory is not None:
        kwargs["runtime_lock_factory"] = runtime_lock_factory
    return ProductionMaintenanceCapability(
        paths,
        site_id="legacy-dfd356e96ea0",
        evidence_binding=_binding(paths),
        rollback_owners={
            ("legacy-dfd356e96ea0", "devices.db"): _owner(
                "devices.db",
                operation_id=operation_id,
                source_identity=source_identity,
                source_sha256=profiles["devices.db"]["sha256"],
                schema_fingerprint=profiles["devices.db"]["schema_digest"],
                backup_sha256=backups["devices.db"]["sha256"],
                backup_size=backups["devices.db"]["size_bytes"],
                backup_relative_path=backups["devices.db"]["relative"],
            ),
            ("legacy-dfd356e96ea0", "tasks.db"): _owner(
                "tasks.db",
                operation_id=operation_id,
                source_identity=source_identity,
                source_sha256=profiles["tasks.db"]["sha256"],
                schema_fingerprint=profiles["tasks.db"]["schema_digest"],
                backup_sha256=backups["tasks.db"]["sha256"],
                backup_size=backups["tasks.db"]["size_bytes"],
                backup_relative_path=backups["tasks.db"]["relative"],
            ),
        },
        **kwargs,
    )


def _manifest(tmp_path: Path, database: Path, *, candidate: Path | None = None) -> Path:
    binding = _binding(PathResolver(data_root=tmp_path / "binding-data-root"))
    value = build_exact_manifest(
        database,
        candidate=candidate or database,
        site_id="legacy-dfd356e96ea0",
        row_identity={"table": "records", "key": "id"},
        expected_count=2,
        evidence_binding=binding,
        plan_kind="test",
        execution_status="EXECUTABLE",
        blocking_prerequisites=(),
    )
    return write_exact_manifest(
        tmp_path / "manifest.json",
        value,
        evidence_binding=binding,
    )


def _candidate(paths: PathResolver, operation_id: str, database: str) -> Path:
    path = (
        paths.staging_dir
        / "production-maintenance"
        / operation_id
        / f"{database}.candidate"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _gates() -> dict[str, dict[str, str]]:
    return {
        key: {
            "status": "PASS",
            "current_implementation_head": HEAD,
            "evidence_sha256": "a" * 64,
        }
        for key in PRODUCTION_GATE_KEYS
    }


class _RejectedRuntimeLock:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def acquire(self) -> None:
        raise BackendInstanceInUseError(self.paths.data_root, {"pid": 1234})

    def release(self) -> None:
        raise AssertionError("rejected runtime lock must not be released")


class _DriftingRuntimeLock:
    def __init__(self, active: Path) -> None:
        self.active = active

    def acquire(self) -> None:
        with closing(sqlite3.connect(self.active)) as connection:
            connection.execute("INSERT INTO records(value) VALUES ('late-writer')")
            connection.commit()

    def release(self) -> None:
        return None


class _CountingRuntimeLock:
    def __init__(self, state: dict[str, int], *, reject_on: int = 0) -> None:
        self.state = state
        self.reject_on = reject_on
        self.acquired = False

    def acquire(self) -> None:
        self.state["acquires"] += 1
        if self.state["acquires"] == self.reject_on:
            raise BackendInstanceInUseError(Path("D:/test-data"), {"pid": 1234})
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            self.state["releases"] += 1
            self.acquired = False


def test_production_capability_requires_exact_allowlist(tmp_path: Path) -> None:
    paths, _, _ = _site(tmp_path)
    with pytest.raises(ProductionMaintenanceError, match="allowlist"):
        ProductionMaintenanceCapability(
            paths,
            site_id="other-site",
            evidence_binding=_binding(paths),
        )


def test_evidence_binding_rejects_registry_or_script_content_drift(
    tmp_path: Path,
) -> None:
    paths, _site_path, _root = _site(tmp_path)
    registry = tmp_path / "storage_registry.yaml"
    script = tmp_path / "production_database_maintenance.py"
    registry.write_text('{"version": 1}\n', encoding="utf-8")
    script.write_text("# production boundary\n", encoding="utf-8")
    binding = ProductionEvidenceBinding.from_runtime(
        paths,
        claimed_current_head=HEAD,
        rehearsal_evidence_head=REHEARSAL_HEAD,
        storage_registry=registry,
        production_maintenance_script=script,
    )

    registry.write_text('{"version": 2}\n', encoding="utf-8")
    with pytest.raises(ProductionMaintenanceError, match="EVIDENCE_BINDING_CHANGED"):
        binding.assert_current(paths)

    registry.write_text('{"version": 1}\n', encoding="utf-8")
    script.write_text("# changed production boundary\n", encoding="utf-8")
    with pytest.raises(ProductionMaintenanceError, match="EVIDENCE_BINDING_CHANGED"):
        binding.assert_current(paths)


def test_evidence_binding_rejects_dirty_implementation_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _site_path, _root = _site(tmp_path)
    metadata = dict(_REAL_BUILD_METADATA(ROOT))
    metadata["build_dirty"] = True
    monkeypatch.setattr(
        production_maintenance_module,
        "current_build_metadata",
        lambda _root: metadata,
    )

    with pytest.raises(ProductionMaintenanceError, match="CURRENT_HEAD_DIRTY"):
        _binding(paths)


def test_quiescence_evidence_requires_all_execution_safety_fields(
    tmp_path: Path,
) -> None:
    paths, _site_path, _root = _site(tmp_path)
    evidence = tmp_path / "quiescence.json"
    value = {
        "evidence_type": "production-writer-quiescence-v1",
        "status": "PASS",
        "site_id": "legacy-dfd356e96ea0",
        "operation_id": "op-quiescence",
        "current_implementation_head": HEAD,
        "rehearsal_evidence_head": REHEARSAL_HEAD,
        "verified_at": "2026-08-17T00:00:00Z",
        "runtime_writer_stopped": True,
        "database_owner_inactive": True,
        "wal_zero": True,
        "sqlite_sidecars_quiescent": True,
    }
    evidence.write_text(json.dumps(value), encoding="utf-8")
    binding = _binding(paths)
    assert _evidence_pass(
        evidence,
        label="production-writer-quiescence-v1",
        site_id="legacy-dfd356e96ea0",
        operation_id="op-quiescence",
        binding=binding,
    )

    for key in (
        "runtime_writer_stopped",
        "database_owner_inactive",
        "wal_zero",
        "sqlite_sidecars_quiescent",
    ):
        invalid = dict(value)
        invalid[key] = False
        evidence.write_text(json.dumps(invalid), encoding="utf-8")
        assert not _evidence_pass(
            evidence,
            label="production-writer-quiescence-v1",
            site_id="legacy-dfd356e96ea0",
            operation_id="op-quiescence",
            binding=binding,
        )


def test_gate_evidence_is_bound_to_actual_current_head_pass_report(
    tmp_path: Path,
) -> None:
    paths, _site_path, _root = _site(tmp_path)
    source_report = tmp_path / "targeted-report.json"
    source_report.write_text(
        json.dumps(
            {
                "mode": "targeted",
                "result": "PASS",
                "head_sha": HEAD,
                "failed": [],
                "not_run": [],
                "required_suites": ["storage-targeted"],
                "passed": ["storage-targeted"],
            }
        ),
        encoding="utf-8",
    )
    source_sha256 = hashlib.sha256(source_report.read_bytes()).hexdigest()
    wrapper = tmp_path / "targeted-wrapper.json"
    wrapper.write_text(
        json.dumps(
            {
                "evidence_type": "production-current-head-gate-v2",
                "gate": "targeted",
                "status": "PASS",
                "current_implementation_head": HEAD,
                "rehearsal_evidence_head": REHEARSAL_HEAD,
                "verified_at": "2026-08-17T00:00:00Z",
                "source_reports": [
                    {
                        "path": str(source_report.resolve()),
                        "sha256": source_sha256,
                        "status": "PASS",
                        "current_implementation_head": HEAD,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    parsed = _gate_evidence([wrapper], binding=_binding(paths))

    assert parsed["targeted"]["evidence_sha256"] == hashlib.sha256(
        json.dumps([source_sha256], separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_gate_evidence_rejects_missing_changed_or_stale_source_report(
    tmp_path: Path,
) -> None:
    paths, _site_path, _root = _site(tmp_path)
    source_report = tmp_path / "full-report.json"
    source_report.write_text(
        json.dumps(
            {
                "mode": "full",
                "result": "PASS",
                "head_sha": HEAD,
                "failed": [],
                "not_run": [],
                "required_suites": [
                    "change-impact",
                    "ruff-changed",
                    "python-direct",
                    "renderer-direct",
                    "electron-direct",
                    "architecture-targeted",
                    "git-diff-check",
                ],
                "passed": [
                    "change-impact",
                    "ruff-changed",
                    "python-direct",
                    "renderer-direct",
                    "electron-direct",
                    "architecture-targeted",
                    "git-diff-check",
                ],
            }
        ),
        encoding="utf-8",
    )
    wrapper = tmp_path / "full-wrapper.json"
    base = {
        "evidence_type": "production-current-head-gate-v2",
        "gate": "full",
        "status": "PASS",
        "current_implementation_head": HEAD,
        "rehearsal_evidence_head": REHEARSAL_HEAD,
        "verified_at": "2026-08-17T00:00:00Z",
    }
    wrapper.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(SystemExit, match="not source-bound"):
        _gate_evidence([wrapper], binding=_binding(paths))

    source_sha256 = hashlib.sha256(source_report.read_bytes()).hexdigest()
    bound = {
        **base,
        "source_reports": [
            {
                "path": str(source_report.resolve()),
                "sha256": source_sha256,
                "status": "PASS",
                "current_implementation_head": HEAD,
            }
        ],
    }
    wrapper.write_text(json.dumps(bound), encoding="utf-8")
    source_report.write_text(
        json.dumps({"mode": "full", "result": "FAIL", "head_sha": HEAD}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="missing or changed"):
        _gate_evidence([wrapper], binding=_binding(paths))

    bound["source_reports"][0]["sha256"] = hashlib.sha256(
        source_report.read_bytes()
    ).hexdigest()
    bound["source_reports"][0]["status"] = "FAIL"
    wrapper.write_text(json.dumps(bound), encoding="utf-8")
    with pytest.raises(SystemExit, match="not current-HEAD PASS"):
        _gate_evidence([wrapper], binding=_binding(paths))


def test_gate_evidence_rejects_source_report_for_wrong_gate_semantics(
    tmp_path: Path,
) -> None:
    paths, _site_path, _root = _site(tmp_path)
    source_report = tmp_path / "wrong-mode.json"
    source_report.write_text(
        json.dumps(
            {
                "mode": "fast",
                "result": "PASS",
                "head_sha": HEAD,
                "failed": [],
                "not_run": [],
                "required_suites": ["python-full"],
                "passed": ["python-full"],
            }
        ),
        encoding="utf-8",
    )
    wrapper = tmp_path / "targeted-wrapper.json"
    wrapper.write_text(
        json.dumps(
            {
                "evidence_type": "production-current-head-gate-v2",
                "gate": "targeted",
                "status": "PASS",
                "current_implementation_head": HEAD,
                "rehearsal_evidence_head": REHEARSAL_HEAD,
                "verified_at": "2026-08-17T00:00:00Z",
                "source_reports": [
                    {
                        "path": str(source_report.resolve()),
                        "sha256": hashlib.sha256(
                            source_report.read_bytes()
                        ).hexdigest(),
                        "status": "PASS",
                        "current_implementation_head": HEAD,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="mode does not match"):
        _gate_evidence([wrapper], binding=_binding(paths))


def test_bind_gate_cli_writes_create_only_source_bound_evidence(
    tmp_path: Path,
) -> None:
    _paths, _site_path, root = _site(tmp_path)
    report = tmp_path / "fast.json"
    report.write_text(
        json.dumps(
            {
                "mode": "fast",
                "result": "PASS",
                "head_sha": HEAD,
                "failed": [],
                "not_run": [],
                "required_suites": [
                    "change-impact",
                    "ruff-changed",
                    "python-direct",
                    "renderer-direct",
                    "electron-direct",
                    "architecture-targeted",
                    "git-diff-check",
                ],
                "passed": [
                    "change-impact",
                    "ruff-changed",
                    "python-direct",
                    "renderer-direct",
                    "electron-direct",
                    "architecture-targeted",
                    "git-diff-check",
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "fast-gate.json"
    command = [
        "bind-gate",
        "--data-root",
        str(root),
        "--site-id",
        "legacy-dfd356e96ea0",
        "--git-head",
        HEAD,
        "--rehearsal-evidence-head",
        REHEARSAL_HEAD,
        "--gate",
        "fast",
        "--source-report",
        str(report),
        "--output",
        str(output),
    ]

    assert production_main(command) == 0
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["evidence_type"] == "production-current-head-gate-v2"
    assert value["source_reports"][0]["sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
    with pytest.raises(FileExistsError, match="output already exists"):
        production_main(command)


def test_storage_registry_has_protected_pending_production_rollback_owners() -> None:
    owners = ProductionMaintenanceCapability.load_rollback_owners(
        ROOT / "config" / "storage_registry.yaml"
    )
    assert set(owners) == {
        ("legacy-dfd356e96ea0", "devices.db"),
        ("legacy-dfd356e96ea0", "tasks.db"),
    }
    assert all(owner.retire_state == "PROTECT" for owner in owners.values())
    assert all(owner.observation_state == "PENDING_PRODUCTION_BACKUP" for owner in owners.values())
    assert not any(owner.verified() for owner in owners.values())


def test_preflight_rejects_stale_source_and_requires_production_mode(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    manifest = _manifest(tmp_path, site / "db" / "devices.db")
    with closing(sqlite3.connect(site / "db" / "devices.db")) as connection:
        connection.execute("INSERT INTO records(value) VALUES ('changed')")
        connection.commit()
    capability = _capability(paths)
    with pytest.raises(ProductionMaintenanceError, match="mode=production"):
        capability.preflight(
            manifest,
            mode="development",
            writer_quiescent=True,
            gates=_gates(),
        )
    with pytest.raises(ProductionMaintenanceError, match="STALE_SOURCE"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )


def test_preflight_rejects_tampered_manifest_missing_owner_and_active_writer(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    manifest = _manifest(tmp_path, site / "db" / "devices.db")
    without_owner = ProductionMaintenanceCapability(
        paths,
        site_id="legacy-dfd356e96ea0",
        evidence_binding=_binding(paths),
    )
    with pytest.raises(ProductionMaintenanceError, match="owner is not registered"):
        without_owner.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )
    capability = _capability(paths)
    with pytest.raises(ProductionMaintenanceError, match="quiescence"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=False,
            gates=_gates(),
        )
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["expected_count"] = 3
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ProductionMaintenanceError, match="STALE_PLAN"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )


def test_preflight_rejects_gate_evidence_from_rehearsal_head(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    manifest = _manifest(tmp_path, site / "db" / "devices.db")
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))[
        "database_identity"
    ]
    capability = _capability(paths, source_identity=source_identity)
    gates = _gates()
    gates["full"]["current_implementation_head"] = REHEARSAL_HEAD

    with pytest.raises(ProductionMaintenanceError, match="not current-HEAD PASS"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=gates,
        )


def test_preflight_rejects_executable_manifest_from_rehearsal_head(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    binding = _binding(paths)
    value = build_exact_manifest(
        active,
        candidate=active,
        site_id="legacy-dfd356e96ea0",
        row_identity={"table": "records", "key": "id"},
        expected_count=2,
        evidence_binding=binding,
        plan_kind="stale-executable",
        execution_status="EXECUTABLE",
        blocking_prerequisites=(),
    )
    value["generated_git_head"] = REHEARSAL_HEAD
    with pytest.raises(ProductionMaintenanceError, match="CURRENT_HEAD_MISMATCH"):
        write_exact_manifest(
            tmp_path / "rejected-stale-manifest.json",
            value,
            evidence_binding=binding,
        )
    manifest = tmp_path / "stale-manifest.json"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    capability = _capability(
        paths,
        source_identity=value["database_identity"],
    )

    with pytest.raises(ProductionMaintenanceError, match="generated Git HEAD mismatch"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )


def test_execute_replace_requires_explicit_authorization_and_supports_rollback(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-replace", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    source_identity = manifest_value["database_identity"]
    capability = _capability(
        paths,
        operation_id="op-replace",
        source_identity=source_identity,
    )
    rollback_path = _backup(paths, "devices.db")[0]
    rollback_sha = sqlite_quick_profile(rollback_path)["sha256"]
    with pytest.raises(ProductionMaintenanceError, match="authorization"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization="",
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-no-auth",
            restart_verifier=lambda: True,
            functional_gate=lambda: True,
        )
    result = capability.execute_replace(
        manifest,
        candidate=candidate,
        rollback=rollback_path,
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        gates=_gates(),
        operation_id="op-replace",
        restart_verifier=lambda: True,
        functional_gate=lambda: True,
    )
    assert result["replaced"] is True
    assert result["execution_time_recheck"] == {
        "runtime_writer_stopped": True,
        "database_owner_inactive": True,
        "wal_zero": True,
        "sqlite_sidecars_quiescent": True,
        "source_sha256": manifest_value["source_sha256"],
        "source_size": manifest_value["source_size"],
        "schema_fingerprint": manifest_value["schema_fingerprint"],
        "status": "PASS",
    }
    assert result["evidence_binding"] == {
        "current_implementation_head": HEAD,
        "rehearsal_evidence_head": REHEARSAL_HEAD,
        "source_snapshot_identity": source_identity,
        "manifest_generated_head": HEAD,
        "storage_registry_sha256": _binding(paths).storage_registry_sha256,
        "production_maintenance_script_sha256": _binding(
            paths
        ).production_maintenance_script_sha256,
    }
    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "candidate"
    restored = capability.rollback(
        "devices.db",
        rollback_path,
        mode="production",
        authorization=PRODUCTION_AUTHORIZATION_TOKEN,
        writer_quiescent=True,
        operation_id="op-rollback",
    )
    assert restored["rolled_back"] is True
    assert rollback_path.is_file()
    assert sqlite_quick_profile(rollback_path)["sha256"] == rollback_sha
    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 2


def test_post_switch_restart_failure_rolls_back_and_finalizes_journal(tmp_path: Path) -> None:
    paths, site, root = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-restart-failure", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    lock_state = {"acquires": 0, "releases": 0}
    capability = _capability(
        paths,
        operation_id="op-restart-failure",
        source_identity=source_identity,
        runtime_lock_factory=lambda _paths: _CountingRuntimeLock(lock_state),
    )
    rollback_path = _backup(paths, "devices.db")[0]
    rollback_sha = sqlite_quick_profile(rollback_path)["sha256"]

    with pytest.raises(ProductionMaintenanceError, match="rollback completed"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-restart-failure",
            restart_verifier=lambda: False,
            functional_gate=lambda: True,
        )

    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM records ORDER BY id").fetchall() == [
            ("a",),
            ("b",),
        ]
    journal = json.loads(
        (root / "runtime" / "database_upgrade" / "op-restart-failure.json").read_text(
            encoding="utf-8"
        )
    )
    assert journal["stage"] == "failed_rolled_back"
    assert journal["rollback_performed"] is True
    assert lock_state == {"acquires": 2, "releases": 2}
    assert rollback_path.is_file()
    assert sqlite_quick_profile(rollback_path)["sha256"] == rollback_sha


def test_post_switch_rollback_rejects_active_runtime_owner(tmp_path: Path) -> None:
    paths, site, root = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-rollback-runtime-active", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))[
        "database_identity"
    ]
    lock_state = {"acquires": 0, "releases": 0}
    capability = _capability(
        paths,
        operation_id="op-rollback-runtime-active",
        source_identity=source_identity,
        runtime_lock_factory=lambda _paths: _CountingRuntimeLock(
            lock_state,
            reject_on=2,
        ),
    )
    rollback_path = _backup(paths, "devices.db")[0]

    with pytest.raises(
        ProductionMaintenanceError,
        match="post-switch verification and rollback both failed",
    ):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-rollback-runtime-active",
            restart_verifier=lambda: False,
            functional_gate=lambda: True,
        )

    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT value FROM records ORDER BY id").fetchall() == [
            ("candidate",),
            ("candidate-2",),
        ]
    journal = json.loads(
        (
            root
            / "runtime"
            / "database_upgrade"
            / "op-rollback-runtime-active.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["stage"] == "failed"
    assert journal["rollback_error_type"] == "ProductionMaintenanceError"
    assert lock_state == {"acquires": 2, "releases": 1}


def test_execute_rejects_candidate_content_drift_with_same_total_rows(
    tmp_path: Path,
) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-candidate-drift", "devices.db")
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO records(value) VALUES (?)", [("candidate",), ("candidate-2",)]
        )
        connection.commit()
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    capability = _capability(
        paths,
        operation_id="op-candidate-drift",
        source_identity=source_identity,
    )
    rollback_path = _backup(paths, "devices.db")[0]
    active_sha = sqlite_quick_profile(active)["sha256"]
    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute("UPDATE records SET value = 'drifted' WHERE id = 1")
        connection.commit()

    with pytest.raises(ProductionMaintenanceError, match="candidate identity mismatch"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-candidate-drift",
            restart_verifier=lambda: True,
            functional_gate=lambda: True,
        )

    assert sqlite_quick_profile(active)["sha256"] == active_sha


def test_execute_rechecks_runtime_owner_before_atomic_replace(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-runtime-active", "devices.db")
    sqlite_backup(active, candidate)
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))[
        "database_identity"
    ]
    capability = _capability(
        paths,
        operation_id="op-runtime-active",
        source_identity=source_identity,
        runtime_lock_factory=_RejectedRuntimeLock,
    )
    rollback_path = _backup(paths, "devices.db")[0]
    active_sha = sqlite_quick_profile(active)["sha256"]

    with pytest.raises(ProductionMaintenanceError, match="EXECUTION_QUIESCENCE_FAILED"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-runtime-active",
            restart_verifier=lambda: True,
            functional_gate=lambda: True,
        )

    assert sqlite_quick_profile(active)["sha256"] == active_sha
    assert candidate.is_file()


def test_execute_rechecks_source_identity_inside_runtime_lock(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    candidate = _candidate(paths, "op-late-writer", "devices.db")
    sqlite_backup(active, candidate)
    manifest = _manifest(tmp_path, active, candidate=candidate)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))[
        "database_identity"
    ]
    capability = _capability(
        paths,
        operation_id="op-late-writer",
        source_identity=source_identity,
        runtime_lock_factory=lambda _paths: _DriftingRuntimeLock(active),
    )
    rollback_path = _backup(paths, "devices.db")[0]

    with pytest.raises(ProductionMaintenanceError, match="STALE_SOURCE"):
        capability.execute_replace(
            manifest,
            candidate=candidate,
            rollback=rollback_path,
            mode="production",
            authorization=PRODUCTION_AUTHORIZATION_TOKEN,
            writer_quiescent=True,
            gates=_gates(),
            operation_id="op-late-writer",
            restart_verifier=lambda: True,
            functional_gate=lambda: True,
        )

    with closing(sqlite3.connect(active)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3
    assert candidate.is_file()


def test_preflight_uses_immutable_reads_and_rejects_nonempty_wal(tmp_path: Path) -> None:
    paths, site, _ = _site(tmp_path)
    active = site / "db" / "devices.db"
    manifest = _manifest(tmp_path, active)
    source_identity = json.loads(manifest.read_text(encoding="utf-8"))["database_identity"]
    capability = _capability(paths, source_identity=source_identity)
    wal = active.with_name(f"{active.name}-wal")
    shm = active.with_name(f"{active.name}-shm")
    assert not wal.exists()
    assert not shm.exists()

    capability.preflight(
        manifest,
        mode="production",
        writer_quiescent=True,
        gates=_gates(),
    )
    assert not wal.exists()
    assert not shm.exists()

    wal.write_bytes(b"active-wal")
    with pytest.raises(ProductionMaintenanceError, match="sidecars are active"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )
    assert wal.read_bytes() == b"active-wal"
    assert not shm.exists()


def test_manifest_cli_refuses_conflicting_or_existing_output(tmp_path: Path) -> None:
    _paths, site, root = _site(tmp_path)
    source = site / "db" / "devices.db"
    manifest = root / "manifest.json"
    common = [
        "manifest",
        "--data-root",
        str(root),
        "--site-id",
        "legacy-dfd356e96ea0",
        "--source",
        str(source),
        "--candidate",
        str(source),
        "--manifest",
        str(manifest),
        "--git-head",
        HEAD,
        "--rehearsal-evidence-head",
        REHEARSAL_HEAD,
        "--expected-count",
        "2",
        "--row-identity",
        "table=records",
        "--row-identity",
        "key=id",
    ]

    with pytest.raises(SystemExit, match="must differ"):
        production_main([*common, "--output", str(manifest)])
    assert not manifest.exists()

    output = root / "existing-output.json"
    output.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError, match="output already exists"):
        production_main([*common, "--output", str(output)])
    assert output.read_text(encoding="utf-8") == "preserve"
    assert not manifest.exists()


def test_manifest_cli_rejects_caller_head_mismatch(tmp_path: Path) -> None:
    _paths, site, root = _site(tmp_path)
    manifest = root / "manifest.json"

    with pytest.raises(ProductionMaintenanceError, match="CURRENT_HEAD_MISMATCH"):
        production_main(
            [
                "manifest",
                "--data-root",
                str(root),
                "--site-id",
                "legacy-dfd356e96ea0",
                "--source",
                str(site / "db" / "devices.db"),
                "--candidate",
                str(site / "db" / "devices.db"),
                "--manifest",
                str(manifest),
                "--git-head",
                REHEARSAL_HEAD,
                "--rehearsal-evidence-head",
                REHEARSAL_HEAD,
                "--expected-count",
                "2",
                "--row-identity-json",
                json.dumps({"table_counts": {"records": 2}}),
            ]
        )

    assert not manifest.exists()


def test_manifest_cli_accepts_structured_identity_and_stays_not_executable(
    tmp_path: Path,
) -> None:
    paths, site, root = _site(tmp_path)
    source = site / "db" / "devices.db"
    manifest = root / "manifest.json"
    assert production_main(
        [
            "manifest",
            "--data-root",
            str(root),
            "--site-id",
            "legacy-dfd356e96ea0",
            "--source",
            str(source),
            "--candidate",
            str(source),
            "--manifest",
            str(manifest),
            "--git-head",
            HEAD,
            "--rehearsal-evidence-head",
            REHEARSAL_HEAD,
            "--expected-count",
            "2",
            "--row-identity-json",
            json.dumps({"table_counts": {"records": 2}}),
        ]
    ) == 0
    value = json.loads(manifest.read_text(encoding="utf-8"))
    assert value["generated_git_head"] == HEAD
    assert value["execution_status"] == "NOT_EXECUTABLE"
    assert value["blocking_prerequisites"]

    capability = _capability(
        paths,
        source_identity=value["database_identity"],
    )
    with pytest.raises(ProductionMaintenanceError, match="NOT_EXECUTABLE"):
        capability.preflight(
            manifest,
            mode="production",
            writer_quiescent=True,
            gates=_gates(),
        )
