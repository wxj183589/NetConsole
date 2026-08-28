from __future__ import annotations

import json
import hashlib
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.services.database_upgrade.sqlite_consistency import sqlite_backup, validate_sqlite


_TERMINAL_STAGES = {
    "completed",
    "production_preflight",
    "production_switched",
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
        self._data.update(fields)
        self._data["stage"] = str(stage)
        self._data["updated_at"] = datetime.now(UTC).isoformat()
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


def recover_incomplete_upgrades(paths: PathResolver) -> list[dict[str, Any]]:
    """Recover interrupted switches without deleting any database artifact."""

    root = paths.database_upgrade_journal_dir.resolve()
    if not root.is_dir():
        return []
    recovered: list[dict[str, Any]] = []
    for journal_path in sorted(root.glob("*.json")):
        try:
            value = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or str(value.get("stage") or "") in _TERMINAL_STAGES:
            continue
        if value.get("recovery_strategy") == "component_resume":
            continue
        try:
            lock_key = str(
                value.get("maintenance_lock")
                or f"database-upgrade:{value.get('scope_type')}:{value.get('scope_id')}"
            )
            digest = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()[:32]
            with interprocess_file_lock(paths.database_upgrade_locks_dir / f"{digest}.lock", timeout_seconds=60):
                result = _recover_journal(paths, value)
            value.update(result)
            _write_existing_journal(journal_path, value)
            recovered.append(dict(value))
        except Exception as exc:
            value.update(
                stage="recovery_failed",
                recovery_error=str(exc),
                updated_at=datetime.now(UTC).isoformat(),
            )
            _write_existing_journal(journal_path, value)
            recovered.append(dict(value))
    return recovered


def _recover_journal(paths: PathResolver, value: dict[str, Any]) -> dict[str, Any]:
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
    path = Path(str(value or "")).resolve()
    root = paths.data_root.resolve()
    if not str(value or "").strip() or (path != root and not path.is_relative_to(root)):
        raise ValueError(f"数据库升级 journal 的 {field} 越界")
    return path


def _optional_controlled_path(paths: PathResolver, value: object, field: str) -> Path | None:
    return _controlled_path(paths, value, field) if str(value or "").strip() else None


def _backup_directory(paths: PathResolver, value: dict[str, Any], operation_id: str) -> Path:
    root = paths.database_upgrade_backups_dir.resolve()
    raw = str(value.get("backup_path") or "").strip()
    path = Path(raw).resolve() if raw else root / "_recovery" / operation_id
    if path != root and not path.is_relative_to(root):
        raise ValueError("数据库升级 journal 的 backup_path 越界")
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


__all__ = ["DatabaseUpgradeJournal", "list_upgrade_journals", "recover_incomplete_upgrades"]
