from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.core.paths import PathResolver


_JOURNAL_DIR_NAME = "site-package-staging-journal"
_REPLACEMENT_JOURNAL_DIR_NAME = "site-import-replacement-journal"
_SYNC_IMPORT_JOURNAL_DIR_NAME = "site-sync-import-journal"
_IMPORT_STAGING_DIR_NAME = "site-import-staging"
_OPERATION_LOCK_NAME = "site-package-staging-operation.lock"
_INTERNAL_STAGING_PREFIXES = (
    "netconsole-site-export-",
    "netconsole-field-package-",
    "netconsole-return-package-",
    "netconsole-return-inspect-",
    "netconsole-return-import-",
)
_OPERATION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class SitePackageStagingRecovery:
    removed_internal_entries: int = 0
    removed_publish_files: int = 0
    removed_journals: int = 0
    restored_site_imports: int = 0
    completed_site_imports: int = 0
    restored_sync_imports: int = 0
    completed_sync_imports: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if not self.failures else "PARTIAL"

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, **asdict(self)}


class SitePackageStagingLifecycle:
    """Own Site Package staging cleanup, including post-termination recovery."""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    @property
    def journal_dir(self) -> Path:
        return self.paths.temp_dir / _JOURNAL_DIR_NAME

    @property
    def replacement_journal_dir(self) -> Path:
        return self.paths.temp_dir / _REPLACEMENT_JOURNAL_DIR_NAME

    @property
    def sync_import_journal_dir(self) -> Path:
        return self.paths.temp_dir / _SYNC_IMPORT_JOURNAL_DIR_NAME

    @contextmanager
    def publish_path(self, destination: Path) -> Iterator[Path]:
        with self.operation_lease():
            staging, journal = self.begin_publish_path(destination)
            try:
                yield staging
            finally:
                self.finish_publish_path(staging, journal)

    @contextmanager
    def operation_lease(self) -> Iterator[None]:
        lock = self.paths.runtime_dir / "locks" / _OPERATION_LOCK_NAME
        with interprocess_file_lock(lock):
            yield

    def begin_publish_path(self, destination: Path) -> tuple[Path, Path]:
        target = Path(destination).expanduser().resolve()
        operation_id = uuid.uuid4().hex
        staging = target.with_name(f".{target.name}.{operation_id}.tmp")
        journal = self._write_publish_journal(
            operation_id=operation_id,
            staging=staging,
            destination=target,
        )
        return staging, journal

    @staticmethod
    def finish_publish_path(staging: Path, journal: Path) -> None:
        staging.unlink(missing_ok=True)
        journal.unlink(missing_ok=True)

    def recover_orphans(self) -> SitePackageStagingRecovery:
        result = SitePackageStagingRecovery()
        lock = self.paths.runtime_dir / "locks" / "site-package-staging-recovery.lock"
        with self.operation_lease():
            with interprocess_file_lock(lock):
                self._recover_replacement_journals(result)
                self._recover_sync_import_journals(result)
                self._recover_internal_staging(result)
                self._recover_publish_journals(result)
        return result

    def begin_site_replacement(self, target: Path, backup: Path | None) -> Path:
        operation_id = uuid.uuid4().hex
        journal = self.replacement_journal_dir / f"{operation_id}.json"
        self._write_journal(
            journal,
            {
                "schema_version": 1,
                "operation_id": operation_id,
                "state": "PREPARED",
                "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "target_path": str(Path(target).resolve()),
                "backup_path": str(Path(backup).resolve()) if backup is not None else "",
                "operation_kind": "REPLACE" if backup is not None else "CREATE",
            },
        )
        return journal

    def mark_site_replacement(self, journal: Path, state: str) -> None:
        if state not in {
            "BACKUP_PUBLISHED",
            "TARGET_PUBLISHED",
            "APPLICATION_COMMITTED",
        }:
            raise ValueError("invalid Site Package replacement state")
        payload = json.loads(Path(journal).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid Site Package replacement journal")
        payload["state"] = state
        payload["updated_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
        self._write_journal(Path(journal), payload)

    def bind_site_replacement_registry(
        self,
        journal: Path,
        *,
        site_id: str,
        preimage: dict[str, object] | None,
        expected: dict[str, object],
    ) -> None:
        payload = json.loads(Path(journal).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("invalid Site Package replacement journal")
        if not _valid_registry_record(expected, site_id):
            raise ValueError("invalid expected Site Registry record")
        if preimage is not None and not _valid_registry_record(preimage, site_id):
            raise ValueError("invalid Site Registry preimage")
        target = Path(str(payload.get("target_path") or ""))
        target_identity = _directory_identity(target)
        payload.update(
            {
                "schema_version": 3,
                "site_id": site_id,
                "registry_preimage": preimage,
                "registry_expected": expected,
                "target_identity": target_identity,
                "updated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        self._write_journal(Path(journal), payload)

    def reconcile_site_replacement(self, journal: Path) -> str:
        result = SitePackageStagingRecovery()
        outcome = self._recover_one_replacement(Path(journal), result)
        if result.failures:
            raise ValueError("Site Package replacement recovery failed")
        return outcome

    def promote_persisted_registry_commit(self, journal: Path) -> bool:
        """Bind a post-write registry exception to an explicit commit state.

        ``SiteRegistry.register`` can persist the record and then raise while
        flushing/returning.  The caller may safely promote the journal only
        when the expected registry record and target identity both match.
        Recovery itself still requires the resulting APPLICATION_COMMITTED
        state, so an actual process interruption remains fail-closed.
        """

        path = Path(journal)
        target, _backup, state, payload = self._validated_replacement_paths(path)
        if int(payload.get("schema_version") or 1) != 3:
            return False
        if state != "TARGET_PUBLISHED":
            return state == "APPLICATION_COMMITTED"
        site_id = str(payload.get("site_id") or "")
        if not _registry_record_matches(
            self._registry_record(site_id), payload.get("registry_expected")
        ):
            return False
        if not target.is_dir() or target.is_symlink():
            return False
        expected_identity = payload.get("target_identity")
        if not isinstance(expected_identity, str) or _directory_identity(target) != expected_identity:
            return False
        self.mark_site_replacement(path, "APPLICATION_COMMITTED")
        return True

    @staticmethod
    def finish_site_replacement(journal: Path | None) -> None:
        if journal is not None:
            Path(journal).unlink(missing_ok=True)

    def begin_sync_import(
        self,
        *,
        operation_id: str,
        target: Path,
        recovery: Path,
        package_id: str,
        package_sha256: str,
        base_revision: int,
        raw_only: bool,
        devices_existed: bool,
        tasks_existed: bool,
        metadata_existed: bool,
        audit_path: Path,
    ) -> Path:
        normalized_operation = operation_id.replace("-", "")
        if not _OPERATION_ID_RE.fullmatch(normalized_operation):
            raise ValueError("invalid Site Sync import operation id")
        journal = self.sync_import_journal_dir / f"{normalized_operation}.json"
        target = Path(target).resolve()
        recovery = Path(recovery).resolve()
        audit_path = Path(audit_path).resolve()
        self._validate_sync_import_paths(target, recovery, audit_path)
        self._write_journal(
            journal,
            {
                "schema_version": 1,
                "operation_id": normalized_operation,
                "state": "PREPARING",
                "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
                "target_path": str(target),
                "recovery_path": str(recovery),
                "audit_path": str(audit_path),
                "package_id": str(package_id),
                "package_sha256": str(package_sha256),
                "base_revision": int(base_revision),
                "raw_only": bool(raw_only),
                "devices_existed": bool(devices_existed),
                "tasks_existed": bool(tasks_existed),
                "metadata_existed": bool(metadata_existed),
                "created_paths": [],
            },
        )
        return journal

    def mark_sync_import(
        self,
        journal: Path,
        state: str,
        *,
        applied_revision: int | None = None,
    ) -> None:
        if state not in {"PREPARED", "APPLYING", "APPLIED"}:
            raise ValueError("invalid Site Sync import state")
        path, payload = self._validated_sync_import_journal(Path(journal))
        del path
        payload["state"] = state
        if applied_revision is not None:
            payload["applied_revision"] = int(applied_revision)
        payload["updated_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
        self._write_journal(Path(journal), payload)

    def record_sync_import_created_path(self, journal: Path, created: Path) -> None:
        target, payload = self._validated_sync_import_journal(Path(journal))
        path = Path(created).resolve()
        try:
            relative = path.relative_to(target).as_posix()
        except ValueError as exc:
            raise ValueError("Site Sync created path escaped target") from exc
        if not relative or relative.startswith("../"):
            raise ValueError("invalid Site Sync created path")
        created_paths = payload.get("created_paths")
        if not isinstance(created_paths, list):
            raise ValueError("invalid Site Sync created path journal")
        if relative not in created_paths:
            created_paths.append(relative)
            payload["updated_at_utc"] = datetime.now(UTC).isoformat(
                timespec="seconds"
            )
            self._write_journal(Path(journal), payload)

    def reconcile_sync_import(self, journal: Path) -> str:
        result = SitePackageStagingRecovery()
        outcome = self._recover_one_sync_import(Path(journal), result)
        if result.failures:
            raise ValueError("Site Sync import recovery failed")
        return outcome

    @staticmethod
    def finish_sync_import(journal: Path | None) -> None:
        if journal is not None:
            Path(journal).unlink(missing_ok=True)

    def _write_publish_journal(
        self,
        *,
        operation_id: str,
        staging: Path,
        destination: Path,
    ) -> Path:
        journal = self.journal_dir / f"{operation_id}.json"
        payload = {
            "schema_version": 1,
            "operation_id": operation_id,
            "pid": os.getpid(),
            "created_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "staging_path": str(staging),
            "destination_path": str(destination),
        }
        self._write_journal(journal, payload)
        return journal

    @staticmethod
    def _write_journal(journal: Path, payload: dict[str, object]) -> None:
        journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = journal.with_name(f".{journal.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, journal)
        finally:
            temporary.unlink(missing_ok=True)

    def _recover_internal_staging(
        self, result: SitePackageStagingRecovery
    ) -> None:
        root = self.paths.temp_dir
        if not root.is_dir():
            return
        for child in root.iterdir():
            if child.name.startswith(_INTERNAL_STAGING_PREFIXES):
                if self._remove_internal_entry(child, root, result):
                    result.removed_internal_entries += 1
        import_root = root / _IMPORT_STAGING_DIR_NAME
        if import_root.is_dir() and not import_root.is_symlink():
            for child in import_root.iterdir():
                if self._remove_internal_entry(child, import_root, result):
                    result.removed_internal_entries += 1
            try:
                import_root.rmdir()
            except OSError:
                pass

    @staticmethod
    def _remove_internal_entry(
        path: Path,
        root: Path,
        result: SitePackageStagingRecovery,
    ) -> bool:
        try:
            if path.parent.resolve() != root.resolve():
                raise ValueError("staging entry escaped its owner directory")
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                return False
            return True
        except (OSError, ValueError) as exc:
            result.failures.append(
                {"path": str(path), "error": exc.__class__.__name__}
            )
            return False

    def _recover_publish_journals(
        self, result: SitePackageStagingRecovery
    ) -> None:
        if not self.journal_dir.is_dir():
            return
        for journal in sorted(self.journal_dir.glob("*.json")):
            try:
                staging = _validated_publish_staging(journal)
                if staging.is_dir() and not staging.is_symlink():
                    raise ValueError("publish staging must not be a directory")
                if staging.exists() or staging.is_symlink():
                    staging.unlink()
                    result.removed_publish_files += 1
                journal.unlink()
                result.removed_journals += 1
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                result.failures.append(
                    {"path": str(journal), "error": exc.__class__.__name__}
                )
        try:
            self.journal_dir.rmdir()
        except OSError:
            pass

    def _recover_replacement_journals(
        self, result: SitePackageStagingRecovery
    ) -> None:
        if not self.replacement_journal_dir.is_dir():
            return
        for journal in sorted(self.replacement_journal_dir.glob("*.json")):
            try:
                self._recover_one_replacement(journal, result)
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                result.failures.append(
                    {"path": str(journal), "error": exc.__class__.__name__}
                )
        try:
            self.replacement_journal_dir.rmdir()
        except OSError:
            pass

    def _recover_sync_import_journals(
        self, result: SitePackageStagingRecovery
    ) -> None:
        if not self.sync_import_journal_dir.is_dir():
            return
        for journal in sorted(self.sync_import_journal_dir.glob("*.json")):
            try:
                self._recover_one_sync_import(journal, result)
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                result.failures.append(
                    {"path": str(journal), "error": exc.__class__.__name__}
                )
        try:
            self.sync_import_journal_dir.rmdir()
        except OSError:
            pass

    def _recover_one_sync_import(
        self,
        journal: Path,
        result: SitePackageStagingRecovery,
    ) -> str:
        target, payload = self._validated_sync_import_journal(journal)
        recovery = Path(str(payload["recovery_path"])).resolve()
        audit_path = Path(str(payload["audit_path"])).resolve()
        state = str(payload.get("state") or "")
        if state == "APPLIED":
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            metadata_path = target / "site_meta.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            applied_revision = int(payload.get("applied_revision") or 0)
            if (
                not isinstance(audit, dict)
                or not isinstance(metadata, dict)
                or str(audit.get("package_id") or "")
                != str(payload.get("package_id") or "")
                or str(audit.get("package_sha256") or "")
                != str(payload.get("package_sha256") or "")
                or int(audit.get("applied_revision") or 0)
                != applied_revision
                or int(metadata.get("revision") or 0) != applied_revision
            ):
                raise ValueError(
                    "Site Sync committed audit or target revision does not match journal"
                )
            result.completed_sync_imports += 1
            outcome = "COMMITTED"
        else:
            if state == "APPLYING":
                devices_backup = recovery / "db" / "devices.db"
                if not devices_backup.is_file():
                    raise ValueError("Site Sync devices rollback snapshot is missing")
                _restore_sqlite_snapshot(
                    devices_backup, target / "db" / "devices.db"
                )
                tasks_backup = recovery / "db" / "tasks.db"
                tasks_target = target / "db" / "tasks.db"
                if bool(payload.get("tasks_existed")):
                    if not tasks_backup.is_file():
                        raise ValueError("Site Sync tasks rollback snapshot is missing")
                    _restore_sqlite_snapshot(tasks_backup, tasks_target)
                else:
                    tasks_target.unlink(missing_ok=True)
                metadata_backup = recovery / "site_meta.json"
                metadata_target = target / "site_meta.json"
                if bool(payload.get("metadata_existed")):
                    if not metadata_backup.is_file():
                        raise ValueError("Site Sync metadata rollback snapshot is missing")
                    shutil.copy2(metadata_backup, metadata_target)
                else:
                    metadata_target.unlink(missing_ok=True)
                created_paths = payload.get("created_paths")
                if not isinstance(created_paths, list):
                    raise ValueError("invalid Site Sync created paths")
                for relative_text in reversed(created_paths):
                    relative = Path(str(relative_text))
                    if (
                        not relative.parts
                        or relative.is_absolute()
                        or ".." in relative.parts
                    ):
                        raise ValueError("invalid Site Sync created path")
                    created = (target / relative).resolve()
                    try:
                        created.relative_to(target)
                    except ValueError as exc:
                        raise ValueError("Site Sync created path escaped target") from exc
                    _remove_sync_created_path(created, target)
                audit_path.unlink(missing_ok=True)
                result.restored_sync_imports += 1
            if recovery.exists():
                if recovery.is_symlink() or not recovery.is_dir():
                    raise ValueError("Site Sync recovery snapshot is not a directory")
                _remove_directory_with_retry(recovery)
            outcome = "ROLLED_BACK"
        journal.unlink()
        result.removed_journals += 1
        return outcome

    def _validated_sync_import_journal(
        self, journal: Path
    ) -> tuple[Path, dict[str, object]]:
        payload = json.loads(Path(journal).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("invalid Site Sync import journal")
        operation_id = str(payload.get("operation_id") or "")
        if not _OPERATION_ID_RE.fullmatch(operation_id):
            raise ValueError("invalid Site Sync import operation id")
        if Path(journal).name != f"{operation_id}.json":
            raise ValueError("Site Sync journal name does not match operation id")
        if str(payload.get("state") or "") not in {
            "PREPARING",
            "PREPARED",
            "APPLYING",
            "APPLIED",
        }:
            raise ValueError("invalid Site Sync import state")
        package_sha256 = str(payload.get("package_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", package_sha256):
            raise ValueError("invalid Site Sync package identity")
        target = Path(str(payload.get("target_path") or "")).resolve()
        recovery = Path(str(payload.get("recovery_path") or "")).resolve()
        audit_path = Path(str(payload.get("audit_path") or "")).resolve()
        self._validate_sync_import_paths(target, recovery, audit_path)
        return target, payload

    def _validate_sync_import_paths(
        self,
        target: Path,
        recovery: Path,
        audit_path: Path,
    ) -> None:
        sites_root = self.paths.sites_dir.resolve()
        if target.parent != sites_root or target == sites_root:
            raise ValueError("Site Sync target is outside sites root")
        backup_root = (target / "files" / "backups").resolve()
        if recovery.parent != backup_root or not re.fullmatch(
            r"sync-import-[0-9a-f-]{36}", recovery.name
        ):
            raise ValueError("Site Sync recovery path is outside its owner")
        imports_root = (target / "sync" / "imports").resolve()
        if audit_path.parent != imports_root or audit_path.suffix.casefold() != ".json":
            raise ValueError("Site Sync audit path is outside its owner")

    def _recover_one_replacement(
        self,
        journal: Path,
        result: SitePackageStagingRecovery,
    ) -> str:
        target, backup, state, payload = self._validated_replacement_paths(journal)
        schema_version = int(payload.get("schema_version") or 1)
        registry_committed = False
        registry_preimage = False
        if schema_version in {2, 3}:
            site_id = str(payload["site_id"])
            current = self._registry_record(site_id)
            registry_committed = _registry_record_matches(
                current, payload.get("registry_expected")
            )
            registry_preimage = _registry_record_matches(
                current, payload.get("registry_preimage")
            )
            if not registry_committed and not registry_preimage:
                raise ValueError("Site Registry no longer matches replacement journal")

        if schema_version in {1, 2}:
            # Legacy journals have no cryptographic target binding.  They may
            # still be rolled back, but a journal state alone cannot retain a
            # published target after restart.
            committed = False
        else:
            target_identity = payload.get("target_identity")
            actual_identity = (
                _directory_identity(target)
                if target.is_dir() and not target.is_symlink()
                else ""
            )
            committed = bool(
                state == "APPLICATION_COMMITTED"
                and registry_committed
                and isinstance(target_identity, str)
                and target_identity == actual_identity
            )
        if committed and target.exists():
            result.completed_site_imports += 1
            outcome = "COMMITTED"
        else:
            if schema_version in {2, 3} and registry_committed:
                self._restore_registry_preimage(payload)
            if backup is not None and backup.exists():
                if target.exists():
                    shutil.rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
                result.restored_site_imports += 1
            elif backup is None and target.exists():
                shutil.rmtree(target)
                result.restored_site_imports += 1
            elif state == "PREPARED":
                pass
            else:
                raise ValueError("site replacement has neither target nor backup")
            outcome = "ROLLED_BACK"
        journal.unlink()
        result.removed_journals += 1
        return outcome

    def _validated_replacement_paths(
        self, journal: Path
    ) -> tuple[Path, Path | None, str, dict[str, object]]:
        payload = json.loads(journal.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in {1, 2, 3}
        ):
            raise ValueError("invalid Site Package replacement journal")
        operation_id = str(payload.get("operation_id") or "")
        if not _OPERATION_ID_RE.fullmatch(operation_id):
            raise ValueError("invalid Site Package replacement operation id")
        if journal.name != f"{operation_id}.json":
            raise ValueError("replacement journal name does not match operation id")
        state = str(payload.get("state") or "")
        if state not in {
            "PREPARED",
            "BACKUP_PUBLISHED",
            "TARGET_PUBLISHED",
            "APPLICATION_COMMITTED",
        }:
            raise ValueError("invalid Site Package replacement state")
        target = Path(str(payload.get("target_path") or ""))
        backup_text = str(payload.get("backup_path") or "")
        backup = Path(backup_text) if backup_text else None
        operation_kind = str(payload.get("operation_kind") or "REPLACE")
        if operation_kind not in {"CREATE", "REPLACE"}:
            raise ValueError("invalid Site Package replacement operation kind")
        if not target.is_absolute() or (
            backup is not None and not backup.is_absolute()
        ):
            raise ValueError("Site Package replacement paths must be absolute")
        if (operation_kind == "CREATE") != (backup is None):
            raise ValueError("Site Package replacement operation does not match backup")
        sites_root = self.paths.sites_dir.resolve()
        archive_root = self.paths.archive_dir.resolve()
        if target.resolve().parent != sites_root:
            raise ValueError("Site Package replacement target is outside sites root")
        if backup is not None:
            if backup.resolve().parent != archive_root:
                raise ValueError("Site Package replacement backup is outside archive root")
            expected_prefix = f"site-import-{target.name}-"
            if not backup.name.startswith(expected_prefix):
                raise ValueError("Site Package replacement backup name is invalid")
        if payload.get("schema_version") in {2, 3}:
            site_id = str(payload.get("site_id") or "")
            expected = payload.get("registry_expected")
            preimage = payload.get("registry_preimage")
            if not _valid_registry_record(expected, site_id):
                raise ValueError("invalid expected Site Registry record")
            if preimage is not None and not _valid_registry_record(preimage, site_id):
                raise ValueError("invalid Site Registry preimage")
            if payload.get("schema_version") == 3:
                identity = payload.get("target_identity")
                if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
                    raise ValueError("invalid Site Package target identity")
        return target, backup, state, payload

    def _registry_record(self, site_id: str) -> dict[str, object] | None:
        registry = self.paths.config_dir / "site_registry.json"
        if not registry.is_file():
            return None
        payload = json.loads(registry.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid Site Registry")
        matches = [
            item
            for item in payload.get("sites", [])
            if isinstance(item, dict) and str(item.get("site_id") or "") == site_id
        ]
        if len(matches) > 1:
            raise ValueError("duplicate Site Registry record")
        return dict(matches[0]) if matches else None

    def _restore_registry_preimage(self, journal: dict[str, object]) -> None:
        site_id = str(journal["site_id"])
        registry = self.paths.config_dir / "site_registry.json"
        payload: dict[str, object]
        if registry.is_file():
            loaded = json.loads(registry.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("invalid Site Registry")
            payload = loaded
        else:
            payload = {"schema_version": 2, "sites": []}
        current = self._registry_record(site_id)
        if not _registry_record_matches(current, journal.get("registry_expected")):
            raise ValueError("Site Registry changed before rollback")
        retained = [
            item
            for item in payload.get("sites", [])
            if not isinstance(item, dict)
            or str(item.get("site_id") or "") != site_id
        ]
        preimage = journal.get("registry_preimage")
        if isinstance(preimage, dict):
            retained.append(preimage)
        payload["schema_version"] = max(2, int(payload.get("schema_version") or 1))
        payload["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        payload["sites"] = retained
        self._write_journal(registry, payload)


def _valid_registry_record(value: object, site_id: str) -> bool:
    if not isinstance(value, dict) or not site_id:
        return False
    if str(value.get("site_id") or "") != site_id:
        return False
    relative = Path(str(value.get("relative_path") or ""))
    return (
        bool(relative.parts)
        and not relative.is_absolute()
        and ".." not in relative.parts
    )


def _registry_record_matches(actual: object, expected: object) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    return all(actual.get(key) == value for key, value in expected.items())


def _directory_identity(path: Path) -> str:
    """Return a deterministic identity for the published site tree."""

    root = Path(path).resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Site Package target identity requires a real directory")
    digest = hashlib.sha256()
    for child in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        if child.is_symlink() or not child.is_file():
            continue
        relative = child.relative_to(root).as_posix()
        file_digest = hashlib.sha256()
        with child.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                file_digest.update(chunk)
        marker = f"{relative}\0{child.stat().st_size}\0{file_digest.hexdigest()}\n".encode("utf-8")
        digest.update(marker)
    return digest.hexdigest()


def _restore_sqlite_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.restore")
    try:
        shutil.copy2(source, temporary)
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        connection = sqlite3.connect(
            f"{temporary.resolve().as_uri()}?mode=ro", uri=True, timeout=30.0
        )
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).casefold() != "ok":
                raise ValueError("Site Sync rollback snapshot quick_check failed")
        finally:
            connection.close()
        for suffix in ("-wal", "-shm", "-journal"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        _replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_sync_created_path(path: Path, target_root: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        raise ValueError("Site Sync created path is not a regular file")
    parent = path.parent
    while parent != target_root and parent.is_relative_to(target_root):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _replace_with_retry(source: Path, destination: Path) -> None:
    last_error: OSError | None = None
    for _attempt in range(20):
        try:
            os.replace(source, destination)
            return
        except (OSError, PermissionError) as exc:
            last_error = exc
            time.sleep(0.05)
    raise PermissionError(f"unable to replace {destination.name}") from last_error


def _remove_directory_with_retry(path: Path) -> None:
    last_error: OSError | None = None
    for _attempt in range(20):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
        except (OSError, PermissionError) as exc:
            last_error = exc
        if not path.exists():
            return
        time.sleep(0.05)
    raise PermissionError(f"unable to remove {path.name}") from last_error


def _validated_publish_staging(journal: Path) -> Path:
    payload = json.loads(journal.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("invalid Site Package staging journal")
    operation_id = str(payload.get("operation_id") or "")
    if not _OPERATION_ID_RE.fullmatch(operation_id):
        raise ValueError("invalid Site Package staging operation id")
    if journal.name != f"{operation_id}.json":
        raise ValueError("journal name does not match operation id")
    staging = Path(str(payload.get("staging_path") or ""))
    destination = Path(str(payload.get("destination_path") or ""))
    if not staging.is_absolute() or not destination.is_absolute():
        raise ValueError("Site Package staging paths must be absolute")
    if staging.parent.resolve() != destination.parent.resolve():
        raise ValueError("Site Package staging parent does not match destination")
    expected_name = f".{destination.name}.{operation_id}.tmp"
    if staging.name != expected_name:
        raise ValueError("Site Package staging name does not match destination")
    return staging
