from __future__ import annotations

import json
import hashlib
import os
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.core.runtime_environment import data_environment
from netconsole.services.database_upgrade.sqlite_consistency import sqlite_backup, validate_sqlite


_TERMINAL_STAGES = {
    "completed",
    "production_preflight",
    "production_rolled_back",
    "failed_before_switch",
    "failed_rolled_back",
    "diagnostic_retention_failed",
    "recovered_no_switch",
    "recovered_rollback",
    "recovered_from_backup",
    "recovered_new_database",
    "recovered_no_existing_database",
}


class DatabaseUpgradeJournal:
    def __init__(self, paths: PathResolver, operation_id: str) -> None:
        self.paths = paths
        root = paths.database_upgrade_journal_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"{operation_id}.json"
        self._data = self._load_existing(operation_id) or {
            "operation_id": operation_id,
            "schema_version": 1,
            "stage": "created",
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def _load_existing(self, operation_id: str) -> dict[str, Any] | None:
        if not self.path.is_file() or self.path.is_symlink():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"database upgrade journal is invalid: {self.path}") from exc
        if not isinstance(value, dict) or str(value.get("operation_id") or "") != operation_id:
            raise RuntimeError(f"database upgrade journal identity mismatch: {self.path}")
        return dict(value)

    @property
    def data(self) -> dict[str, Any]:
        return dict(self._data)

    def update(self, stage: str, **fields: Any) -> dict[str, Any]:
        supplied_authority = fields.pop("database_authority", None)
        supplied_production_evidence = fields.pop("production_maintenance_evidence", None)
        supplied_production_owner = fields.pop("production_rollback_owner", None)
        self._data.update(fields)
        self._data["stage"] = str(stage)
        self._data["updated_at"] = datetime.now(UTC).isoformat()
        if self._data.get("active_path"):
            source_authority = supplied_authority
            if source_authority is None:
                existing = self._data.get("recovery_authority")
                if isinstance(existing, Mapping):
                    existing_source = existing.get("source_authority")
                    source_authority = existing_source if existing_source else None
                    existing_production_evidence = existing.get("production_maintenance_evidence")
                    if supplied_production_evidence is None and isinstance(existing_production_evidence, Mapping):
                        supplied_production_evidence = existing_production_evidence
                    existing_production_owner = existing.get("production_rollback_owner")
                    if supplied_production_owner is None and isinstance(existing_production_owner, Mapping):
                        supplied_production_owner = existing_production_owner
            self._data["recovery_authority"] = _build_journal_recovery_authority(
                self.paths,
                self._data,
                source_authority=source_authority if isinstance(source_authority, Mapping) else None,
                production_maintenance_evidence=(
                    supplied_production_evidence
                    if isinstance(supplied_production_evidence, Mapping)
                    else None
                ),
                production_rollback_owner=(
                    supplied_production_owner
                    if isinstance(supplied_production_owner, Mapping)
                    else None
                ),
            )
        self._write()
        return self.data

    def _write(self) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                json.dump(self._data, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def list_upgrade_journals(paths: PathResolver) -> list[dict[str, Any]]:
    root = paths.database_upgrade_journal_dir
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return sorted(result, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def _build_journal_recovery_authority(
    paths: PathResolver,
    value: Mapping[str, Any],
    *,
    source_authority: Mapping[str, Any] | None = None,
    production_maintenance_evidence: Mapping[str, Any] | None = None,
    production_rollback_owner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from netconsole.services.database_upgrade.authority import build_startup_recovery_authority

    database_kind = str(value.get("database_kind") or "test")
    scope_type = str(value.get("scope_type") or "test")
    scope_id = str(value.get("scope_id") or "__test__")
    adapter_state = value.get("adapter_state")
    return build_startup_recovery_authority(
        paths,
        operation_id=str(value.get("operation_id") or ""),
        database_kind=database_kind,
        scope_type=scope_type,
        scope_id=scope_id,
        active_path=Path(str(value.get("active_path") or "")),
        shadow_path=Path(str(value["shadow_path"])) if value.get("shadow_path") else None,
        rollback_path=Path(str(value["rollback_path"])) if value.get("rollback_path") else None,
        backup_path=Path(str(value["backup_path"])) if value.get("backup_path") else None,
        maintenance_lock=str(value.get("maintenance_lock") or f"database-upgrade:{scope_type}:{scope_id}"),
        source_authority=source_authority,
        allow_legacy_mesh_adapter=(
            str(value.get("startup_recovery_legacy_adapter") or "")
            == "LEGACY_MESH_REBUILD_ADAPTER"
        ),
        production_maintenance_evidence=production_maintenance_evidence,
        production_rollback_owner=production_rollback_owner,
        parsed_artifacts=(
            {
                field: adapter_state[field]
                for field in (
                    "active_parsed_path",
                    "shadow_parsed_path",
                    "rollback_parsed_path",
                )
                if isinstance(adapter_state, Mapping) and str(adapter_state.get(field) or "").strip()
            }
            if isinstance(adapter_state, Mapping)
            else None
        ),
    )


def _validate_journal_identity(journal_path: Path, value: Mapping[str, Any]) -> str:
    operation_id = str(value.get("operation_id") or "").strip()
    if not operation_id or Path(operation_id).name != operation_id or operation_id != journal_path.stem:
        raise ValueError("DATABASE_OPERATION_ID_MISMATCH")
    return operation_id


def _read_existing_journal(path: Path, operation_id: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or str(value.get("operation_id") or "") != operation_id:
        raise ValueError("DATABASE_UPGRADE_JOURNAL_IDENTITY_MISMATCH")
    return dict(value)


def _validate_recovery_authority(
    paths: PathResolver,
    value: Mapping[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    from netconsole.services.database_upgrade.authority import validate_startup_recovery_authority

    authority = value.get("recovery_authority")
    if not isinstance(authority, Mapping):
        raise ValueError("DATABASE_STARTUP_AUTHORITY_REQUIRED")
    return validate_startup_recovery_authority(paths, authority, operation_id=operation_id)


def _validate_recovery_payload(
    paths: PathResolver,
    value: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> None:
    authority_artifacts = authority.get("artifacts")
    if not isinstance(authority_artifacts, Mapping):
        raise ValueError("DATABASE_RECOVERY_ARTIFACTS_REQUIRED")
    journal_fields = {
        field
        for field in ("active_path", "shadow_path", "rollback_path")
        if str(value.get(field) or "").strip()
    }
    authority_fields = {
        str(field)
        for field, raw in authority_artifacts.items()
        if str(raw or "").strip()
    }
    if journal_fields != authority_fields.intersection({"active_path", "shadow_path", "rollback_path"}):
        raise ValueError("DATABASE_RECOVERY_ARTIFACT_MISMATCH")
    for field in ("active_path", "shadow_path", "rollback_path"):
        if field not in authority_fields:
            continue
        raw = value.get(field)
        resolved = _controlled_path(paths, raw, field)
        expected = str(authority_artifacts[field])
        if str(resolved) != str(Path(expected).resolve()):
            raise ValueError("DATABASE_RECOVERY_ARTIFACT_MISMATCH")
    backup_raw = str(value.get("backup_path") or "").strip()
    authority_has_backup = "backup_path" in authority_artifacts and str(authority_artifacts.get("backup_path") or "").strip()
    if bool(backup_raw) != bool(authority_has_backup):
        raise ValueError("DATABASE_RECOVERY_ARTIFACT_MISMATCH")
    if backup_raw:
        backup = Path(backup_raw)
        backup_root = paths.database_upgrade_backups_dir.resolve()
        if not backup.is_absolute() or backup.is_symlink():
            raise ValueError("DATABASE_RECOVERY_BACKUP_INVALID")
        resolved_backup = backup.resolve()
        if resolved_backup != backup_root and not resolved_backup.is_relative_to(backup_root):
            raise ValueError("DATABASE_RECOVERY_BACKUP_INVALID")
        expected_backup = str(authority_artifacts["backup_path"])
        if str(resolved_backup) != str(Path(expected_backup).resolve()):
            raise ValueError("DATABASE_RECOVERY_ARTIFACT_MISMATCH")
    adapter_state = value.get("adapter_state")
    if isinstance(adapter_state, Mapping):
        authority_parsed = authority.get("parsed_artifacts")
        authority_parsed = authority_parsed if isinstance(authority_parsed, Mapping) else {}
        journal_parsed = {
            field: adapter_state.get(field)
            for field in ("active_parsed_path", "shadow_parsed_path", "rollback_parsed_path")
            if str(adapter_state.get(field) or "").strip()
        }
        if set(journal_parsed) != set(authority_parsed):
            raise ValueError("DATABASE_RECOVERY_PARSED_ARTIFACT_MISMATCH")
        for field in ("active_parsed_path", "shadow_parsed_path", "rollback_parsed_path"):
            raw = adapter_state.get(field)
            if str(raw or "").strip():
                resolved = _controlled_path(paths, raw, field)
                if str(resolved) != str(Path(str(authority_parsed[field])).resolve()):
                    raise ValueError("DATABASE_RECOVERY_PARSED_ARTIFACT_MISMATCH")
    elif authority.get("parsed_artifacts"):
        raise ValueError("DATABASE_RECOVERY_PARSED_ARTIFACT_MISMATCH")


def _blocked_recovery_result(
    paths: PathResolver,
    journal_path: Path,
    code: str,
    message: str,
    *,
    value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _record_recovery_block(paths, journal_path, str(code), str(message))
    result = dict(value or {})
    result.update(
        {
            "status": "blocked",
            "recovery_status": "BLOCKED",
            "recovery_block_code": str(code),
            "recovery_error": str(message),
            "recovery_evidence_path": str(evidence),
        }
    )
    return result


def _record_recovery_block(
    paths: PathResolver,
    source: Path,
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> Path:
    root = paths.runtime_dir / "database_upgrade_recovery_blocks"
    root.mkdir(parents=True, exist_ok=True)
    source_text = str(source)
    source_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()[:32]
    target = root / f"{source_digest}.json"
    if target.is_file():
        return target
    raw_digest = ""
    try:
        raw_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        pass
    payload = {
        "schema_version": 1,
        "source": source_text,
        "source_sha256": raw_digest,
        "code": str(code),
        "message": str(message),
        "details": dict(details or {}),
        "created_at": datetime.now(UTC).isoformat(),
    }
    temporary = target.with_name(f".{target.name}.{os.getpid()}-{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def record_startup_recovery_block(
    paths: PathResolver,
    source: Path,
    code: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> Path:
    """Persist a bounded startup admission failure without touching data."""

    return _record_recovery_block(paths, source, code, message, details=details)


def recover_incomplete_upgrades(paths: PathResolver) -> list[dict[str, Any]]:
    """Recover interrupted switches only after authority revalidation.

    A malformed, stale, or unauthorized journal is a startup safety failure,
    not an ignorable background condition.  The original journal remains
    untouched and a small durable block record preserves the evidence needed
    for diagnosis.
    """

    root = paths.database_upgrade_journal_dir.resolve()
    if not root.is_dir():
        return []
    recovered: list[dict[str, Any]] = []
    for journal_path in sorted(root.glob("*.json")):
        if journal_path.is_symlink():
            recovered.append(_blocked_recovery_result(paths, journal_path, "DATABASE_JOURNAL_REPARSE", "journal path is a symlink"))
            continue
        try:
            value = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            recovered.append(_blocked_recovery_result(paths, journal_path, "DATABASE_UPGRADE_JOURNAL_CORRUPT", "journal JSON cannot be parsed"))
            continue
        if not isinstance(value, dict):
            recovered.append(_blocked_recovery_result(paths, journal_path, "DATABASE_UPGRADE_JOURNAL_INVALID", "journal must be a JSON object"))
            continue
        if str(value.get("stage") or "") in _TERMINAL_STAGES:
            continue
        if value.get("recovery_strategy") == "component_resume":
            recovered.append(
                {
                    **value,
                    "status": "skipped",
                    "recovery_status": "COMPONENT_RESUME_DELEGATED",
                }
            )
            continue
        authority_valid = False
        try:
            operation_id = _validate_journal_identity(journal_path, value)
            authority = _validate_recovery_authority(paths, value, operation_id)
            _validate_recovery_payload(paths, value, authority)
            authority_valid = True
            lock_key = str(authority["maintenance_lock"])
            digest = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()[:32]
            with interprocess_file_lock(paths.database_upgrade_locks_dir / f"{digest}.lock", timeout_seconds=60):
                current = _read_existing_journal(journal_path, operation_id)
                if str(current.get("stage") or "") in _TERMINAL_STAGES:
                    recovered.append({**current, "status": "skipped", "recovery_status": "ALREADY_TERMINAL"})
                    continue
                authority = _validate_recovery_authority(paths, current, operation_id)
                _validate_recovery_payload(paths, current, authority)
                if str(authority.get("authority_mode") or "") == "PRODUCTION_MAINTENANCE_ADAPTER":
                    result = _recover_production_journal(paths, current, authority)
                else:
                    result = _recover_journal(paths, current, authority)
                value = current
                value.update(result)
                value["status"] = "recovered"
                _write_existing_journal(journal_path, value)
            recovered.append(dict(value))
        except Exception as exc:
            if authority_valid and isinstance(value, dict):
                value.update(
                    stage="recovery_failed",
                    status="recovery_failed",
                    recovery_error=str(exc),
                    updated_at=datetime.now(UTC).isoformat(),
                )
                try:
                    _write_existing_journal(journal_path, value)
                except Exception as write_exc:
                    _record_recovery_block(
                        paths,
                        journal_path,
                        "DATABASE_RECOVERY_EVIDENCE_WRITE_FAILED",
                        str(write_exc),
                        details={"recovery_error": str(exc)},
                    )
                recovered.append(dict(value))
            else:
                recovered.append(
                    _blocked_recovery_result(
                        paths,
                        journal_path,
                        str(getattr(exc, "code", "") or str(exc) or "DATABASE_STARTUP_AUTHORITY_INVALID"),
                        str(exc),
                        value=value if isinstance(value, dict) else None,
                    )
                )
    return recovered


def _production_rollback_binding(
    paths: PathResolver,
    value: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    from netconsole.services.database_footprint_maintenance import sqlite_quick_profile

    owner = authority.get("production_rollback_owner")
    if not isinstance(owner, Mapping):
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_REQUIRED")
    database_kind = str(authority.get("database_kind") or "")
    site_id = str(authority.get("canonical_site_id") or "")
    binding: Mapping[str, Any] = owner
    resources = owner.get("resources")
    if isinstance(resources, list):
        matches = [
            item
            for item in resources
            if isinstance(item, Mapping)
            and str(item.get("site_id") or "") == site_id
            and str(item.get("database_role") or "") == database_kind
        ]
        if len(matches) != 1:
            raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_SCOPE_MISMATCH")
        binding = matches[0]
    if str(binding.get("database") or binding.get("database_role") or "") != database_kind:
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_SCOPE_MISMATCH")
    rollback = _controlled_path(paths, value.get("rollback_path"), "rollback_path")
    relative = Path(str(binding.get("backup_relative_path") or ""))
    if not relative or relative.is_absolute() or relative.name != "database.sqlite":
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_PATH_INVALID")
    if data_environment(paths.data_root).is_production:
        if (
            len(relative.parts) != 5
            or relative.parts[:3] != ("files", "backups", "production-maintenance")
            or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                for char in relative.parts[3]
            )
        ):
            raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_PATH_INVALID")
        site_relative = Path(str(authority.get("site_root_relative_path") or ""))
        expected = (paths.data_root.resolve() / site_relative / relative).resolve()
        if rollback != expected:
            raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_PATH_MISMATCH")
    try:
        expected_size = int(binding.get("backup_size") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INVALID") from exc
    expected_sha256 = str(binding.get("backup_sha256") or "")
    expected_schema = str(binding.get("schema_fingerprint") or "")
    if expected_size <= 0 or not expected_sha256 or not expected_schema:
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_INCOMPLETE")
    wal = rollback.with_name(rollback.name + "-wal")
    if wal.is_file() and wal.stat().st_size > 0:
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_WAL_ACTIVE")
    profile = sqlite_quick_profile(rollback, immutable=True)
    if (
        not profile["valid"]
        or int(profile["size_bytes"]) != expected_size
        or str(profile["sha256"]) != expected_sha256
        or str(profile["schema_digest"]) != expected_schema
    ):
        raise ValueError("DATABASE_PRODUCTION_ROLLBACK_OWNER_MISMATCH")
    return rollback, profile


def _recover_production_journal(
    paths: PathResolver,
    value: dict[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    from netconsole.services.database_footprint_maintenance import sqlite_quick_profile

    stage = str(value.get("stage") or "")
    if not bool(value.get("switched")):
        return {
            "stage": "recovered_no_switch",
            "rollback_performed": False,
            "recovered_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "production_recovery_status": "NO_SWITCH",
        }
    rollback, rollback_profile = _production_rollback_binding(paths, value, authority)
    active = _controlled_path(paths, value.get("active_path"), "active_path")
    if active == rollback:
        raise ValueError("DATABASE_PRODUCTION_RECOVERY_ARTIFACTS_IDENTICAL")
    backup_dir = _backup_directory(paths, value, str(value.get("operation_id") or "unknown"))
    restoration = active.with_name(f".{active.name}.production-recovery-restore")
    if restoration.exists():
        raise RuntimeError("production recovery restoration candidate already exists")
    sqlite_backup(rollback, restoration)
    restored = sqlite_quick_profile(restoration, immutable=True)
    validation = validate_sqlite(restoration)
    if (
        not restored["valid"]
        or not validation.get("valid")
        or int(restored["size_bytes"]) != int(rollback_profile["size_bytes"])
        or str(restored["sha256"]) != str(rollback_profile["sha256"])
        or str(restored["schema_digest"]) != str(rollback_profile["schema_digest"])
    ):
        raise RuntimeError("production recovery restoration verification failed")
    if active.exists():
        active_wal = active.with_name(active.name + "-wal")
        if active_wal.is_file() and active_wal.stat().st_size > 0:
            raise ValueError("DATABASE_PRODUCTION_RECOVERY_WAL_ACTIVE")
        sqlite_backup(
            active,
            _unique_target(backup_dir / "failed_recovered_production_database.sqlite"),
        )
    os.replace(restoration, active)
    restored = sqlite_quick_profile(active, immutable=True)
    validation = validate_sqlite(active)
    if (
        not restored["valid"]
        or not validation.get("valid")
        or int(restored["size_bytes"]) != int(rollback_profile["size_bytes"])
        or str(restored["sha256"]) != str(rollback_profile["sha256"])
        or str(restored["schema_digest"]) != str(rollback_profile["schema_digest"])
    ):
        raise RuntimeError("production recovery restoration verification failed")
    return {
        "stage": "recovered_production_rollback",
        "rollback_performed": True,
        "recovered_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "production_recovery_status": "OWNER_VERIFIED_ROLLBACK",
        "production_recovery_interrupted_stage": stage,
        "production_recovery_validation": validation,
    }


def _recover_journal(
    paths: PathResolver,
    value: dict[str, Any],
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if authority is not None:
        from netconsole.services.database_upgrade.authority import validate_startup_recovery_authority

        operation_id = str(value.get("operation_id") or "unknown")
        validate_startup_recovery_authority(paths, authority, operation_id=operation_id)
        _validate_recovery_payload(paths, value, authority)
    operation_id = str(value.get("operation_id") or "unknown")
    if str(value.get("stage") or "") == "created" and not str(value.get("active_path") or "").strip():
        return {
            "stage": "recovered_no_switch",
            "rollback_performed": False,
            "recovered_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
    active = _controlled_path(paths, value.get("active_path"), "active_path")
    active.parent.mkdir(parents=True, exist_ok=True)
    shadow = _optional_controlled_path(paths, value.get("shadow_path"), "shadow_path")
    rollback = _optional_controlled_path(paths, value.get("rollback_path"), "rollback_path")
    backup_dir = _backup_directory(paths, value, operation_id)
    adapter_state = value.get("adapter_state") if isinstance(value.get("adapter_state"), dict) else {}
    active_parsed = _optional_controlled_path(paths, adapter_state.get("active_parsed_path"), "active_parsed_path")
    shadow_parsed = _optional_controlled_path(paths, adapter_state.get("shadow_parsed_path"), "shadow_parsed_path")
    rollback_parsed = _optional_controlled_path(paths, adapter_state.get("rollback_parsed_path"), "rollback_parsed_path")
    stage = "recovered_no_switch"

    if str(value.get("stage") or "") == "smoke_validated":
        validation = validate_sqlite(active)
        if validation.get("valid"):
            if rollback is not None and rollback.exists():
                _move_with_sidecars(rollback, _unique_target(backup_dir / "rollback_recovered.sqlite"))
            if rollback_parsed is not None and rollback_parsed.exists():
                _move_path(rollback_parsed, _unique_target(backup_dir / "rollback_recovered_parsed"))
            if shadow is not None and shadow.exists():
                _move_with_sidecars(shadow, _unique_target(backup_dir / "failed_recovered_shadow.sqlite"))
            if shadow_parsed is not None and shadow_parsed.exists():
                _move_path(shadow_parsed, _unique_target(backup_dir / "failed_recovered_shadow_parsed"))
            return {
                "stage": "recovered_new_database",
                "rollback_performed": False,
                "recovered_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "recovery_validation": validation,
            }

    interrupted_after_switch = bool(value.get("switched")) and str(value.get("stage") or "") in {
        "switched",
        "smoke_failed",
        "failed",
    }
    if interrupted_after_switch and (rollback is None or not rollback.exists()):
        backup_database = backup_dir / "database.sqlite"
        if active.exists():
            _move_with_sidecars(active, _unique_target(backup_dir / "failed_recovered_database.sqlite"))
        if active_parsed is not None and active_parsed.exists():
            _move_path(active_parsed, _unique_target(backup_dir / "failed_recovered_parsed"))
        retained_parsed = backup_dir / "rollback_parsed"
        if retained_parsed.exists() and active_parsed is not None:
            retained_parsed.replace(active_parsed)
        if backup_database.is_file():
            sqlite_backup(backup_database, active)
            stage = "recovered_from_backup"
        else:
            return {
                "stage": "recovered_no_existing_database",
                "rollback_performed": True,
                "recovered_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "recovery_validation": {
                    "path": str(active),
                    "exists": False,
                    "valid": True,
                    "status": "NOT_PRESENT",
                },
            }

    if stage != "recovered_from_backup" and rollback is not None and rollback.exists():
        if active.exists():
            _move_with_sidecars(active, _unique_target(backup_dir / "failed_recovered_database.sqlite"))
        rollback.replace(active)
        _move_sidecars(rollback, active)
        stage = "recovered_rollback"
    elif stage != "recovered_from_backup" and not active.exists():
        backup_database = backup_dir / "database.sqlite"
        if not backup_database.is_file():
            raise RuntimeError("正式数据库和 rollback 均不存在，且安全备份不可用")
        sqlite_backup(backup_database, active)
        stage = "recovered_from_backup"

    if rollback_parsed is not None and rollback_parsed.exists() and active_parsed is not None:
        if active_parsed.exists():
            _move_path(active_parsed, _unique_target(backup_dir / "failed_recovered_parsed"))
        rollback_parsed.replace(active_parsed)
    if shadow is not None and shadow.exists():
        _move_with_sidecars(shadow, _unique_target(backup_dir / "failed_recovered_shadow.sqlite"))
    if shadow_parsed is not None and shadow_parsed.exists():
        _move_path(shadow_parsed, _unique_target(backup_dir / "failed_recovered_shadow_parsed"))

    validation = validate_sqlite(active)
    if not validation.get("valid"):
        raise RuntimeError("异常退出恢复后的正式数据库完整性校验失败")
    return {
        "stage": stage,
        "rollback_performed": stage == "recovered_rollback",
        "recovered_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "recovery_validation": validation,
    }


def _controlled_path(paths: PathResolver, value: object, field: str) -> Path:
    raw = Path(str(value or ""))
    if not str(value or "").strip() or not raw.is_absolute():
        raise ValueError(f"数据库升级 journal 的 {field} 必须是绝对路径")
    if raw.is_symlink():
        raise ValueError(f"数据库升级 journal 的 {field} 不得是符号链接")
    path = raw.resolve()
    root = paths.data_root.resolve()
    if path != root and not path.is_relative_to(root):
        raise ValueError(f"数据库升级 journal 的 {field} 越界")
    current = raw
    while current != root:
        if current.is_symlink():
            raise ValueError(f"数据库升级 journal 的 {field} 包含符号链接")
        if current.parent == current:
            raise ValueError(f"数据库升级 journal 的 {field} 越界")
        current = current.parent
    return path


def _optional_controlled_path(paths: PathResolver, value: object, field: str) -> Path | None:
    return _controlled_path(paths, value, field) if str(value or "").strip() else None


def _backup_directory(paths: PathResolver, value: dict[str, Any], operation_id: str) -> Path:
    root = paths.database_upgrade_backups_dir.resolve()
    raw = str(value.get("backup_path") or "").strip()
    path = Path(raw).resolve() if raw else root / "_recovery" / operation_id
    if path != root and not path.is_relative_to(root):
        raise ValueError("数据库升级 journal 的 backup_path 越界")
    if path.is_symlink():
        raise ValueError("数据库升级 journal 的 backup_path 不得是符号链接")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _move_with_sidecars(source: Path, target: Path) -> None:
    source.replace(target)
    _move_sidecars(source, target)


def _move_sidecars(source: Path, target: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            sidecar.replace(target.with_name(target.name + suffix))


def _move_path(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.move(str(source), str(target))
    else:
        source.replace(target)


def _unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return path.with_name(f"{path.name}.{stamp}")


def _write_existing_journal(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "DatabaseUpgradeJournal",
    "list_upgrade_journals",
    "record_startup_recovery_block",
    "recover_incomplete_upgrades",
]
