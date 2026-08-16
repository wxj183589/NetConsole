from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from netconsole.core.paths import PathResolver
from netconsole.services.database_footprint_maintenance import (
    DEVELOPMENT_ROOT,
    assert_development_path,
)
from netconsole.services.database_upgrade.backup_store import DatabaseBackupStore
from netconsole.services.database_upgrade.sqlite_consistency import (
    sha256_file,
    validate_sqlite,
)


class BackupLifecycleService:
    """Manifest-driven rollback retention with development-only retirement apply."""

    FORMAT = "netconsole-backup-lifecycle-plan"
    VERSION = 1
    REQUIRED_OWNER_FIELDS = ("scope_type", "scope_id", "database_kind")

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.store = DatabaseBackupStore(paths)
        self.root = self.store.root

    def preview_retirement(
        self,
        *,
        keep_revisions: int = 2,
        protected_backup_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        keep = max(1, int(keep_revisions))
        protected_ids = {str(value) for value in protected_backup_ids if str(value)}
        inventory, inventory_digest, unknown = self._inventory()
        decisions: dict[str, dict[str, Any]] = {}
        logical_duplicates: list[dict[str, Any]] = []
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

        for item in inventory:
            backup_id = str(item.get("backup_id") or "")
            missing = [field for field in self.REQUIRED_OWNER_FIELDS if not str(item.get(field) or "")]
            status = str(item.get("result_status") or "")
            authority = str(item.get("authority_status") or "VERIFIED")
            if not backup_id or missing or status != "VALID_BACKUP" or authority != "VERIFIED":
                key = backup_id or str(item.get("manifest_path") or "unknown")
                decisions[key] = self._decision(
                    item,
                    action="PROTECT",
                    reason="UNKNOWN_OR_UNVERIFIED",
                    classification="UNKNOWN",
                )
                continue
            group = tuple(str(item[field]) for field in self.REQUIRED_OWNER_FIELDS)
            groups.setdefault(group, []).append(item)

        for group, members in groups.items():
            ordered = sorted(
                members,
                key=lambda item: (str(item.get("created_at") or ""), str(item.get("backup_id") or "")),
                reverse=True,
            )
            by_revision: dict[str, list[dict[str, Any]]] = {}
            for item in ordered:
                revision = str(item.get("source_revision") or item.get("database_sha256") or "")
                if not revision:
                    decisions[str(item["backup_id"])] = self._decision(
                        item,
                        action="PROTECT",
                        reason="UNKNOWN_SOURCE_REVISION",
                        classification="UNKNOWN",
                    )
                    continue
                by_revision.setdefault(revision, []).append(item)

            canonical: list[dict[str, Any]] = []
            for revision_members in by_revision.values():
                canonical.append(revision_members[0])
                for duplicate in revision_members[1:]:
                    backup_id = str(duplicate["backup_id"])
                    decisions[backup_id] = self._decision(
                        duplicate,
                        action="PROTECT" if backup_id in protected_ids else "RETIRE",
                        reason=(
                            "ACTIVE_REFERENCE"
                            if backup_id in protected_ids
                            else "SUPERSEDED_EXACT_DUPLICATE"
                        ),
                        classification="BACKUP_ROLLBACK",
                    )

            canonical.sort(
                key=lambda item: (str(item.get("created_at") or ""), str(item.get("backup_id") or "")),
                reverse=True,
            )
            signatures: dict[str, list[dict[str, Any]]] = {}
            for item in canonical:
                signature = self._logical_signature(item)
                if signature:
                    signatures.setdefault(signature, []).append(item)
            for same_shape in signatures.values():
                revisions = {
                    str(item.get("source_revision") or item.get("database_sha256") or "")
                    for item in same_shape
                }
                if len(revisions) > 1:
                    logical_duplicates.append(
                        {
                            "group": list(group),
                            "backup_ids": [str(item["backup_id"]) for item in same_shape],
                            "status": "LOGICAL_DUPLICATE_CANDIDATE_PROTECT",
                        }
                    )
            for index, item in enumerate(canonical):
                backup_id = str(item["backup_id"])
                if backup_id in decisions:
                    continue
                if backup_id in protected_ids:
                    action, reason = "PROTECT", "ACTIVE_REFERENCE"
                elif index < keep:
                    action, reason = "KEEP", "ROLLBACK_WINDOW"
                else:
                    action, reason = "RETIRE", "SUPERSEDED_REVISION"
                decisions[backup_id] = self._decision(
                    item,
                    action=action,
                    reason=reason,
                    classification="BACKUP_ROLLBACK",
                )

        retire = sorted(
            (value for value in decisions.values() if value["action"] == "RETIRE"),
            key=lambda item: str(item.get("backup_id") or ""),
        )
        protected = sorted(
            (value for value in decisions.values() if value["action"] == "PROTECT"),
            key=lambda item: str(item.get("backup_id") or item.get("path") or ""),
        )
        semantic = {
            "format": self.FORMAT,
            "version": self.VERSION,
            "root": str(self.root),
            "inventory_digest": inventory_digest,
            "policy": {
                "keep_revisions_per_owner_group": keep,
                "unknown": "PROTECT",
                "production_apply": "REFUSE",
            },
            "retire": retire,
            "protected": protected,
            "unknown": unknown,
            "logical_duplicate_candidates": logical_duplicates,
        }
        return {
            **semantic,
            "plan_digest": self._digest(semantic),
            "empty_scope": not retire,
            "summary": {
                "inventory": len(inventory) + len(unknown),
                "retire": len(retire),
                "protected": len(protected) + len(unknown),
                "bytes_reclaimable": sum(int(item.get("database_size") or 0) for item in retire),
            },
        }

    def apply_retirement(
        self,
        plan: dict[str, Any],
        *,
        expected_plan_digest: str,
        apply: bool = False,
        allow_development_root_only: bool = False,
        development_root: str | Path = DEVELOPMENT_ROOT,
    ) -> dict[str, Any]:
        if not apply or not allow_development_root_only:
            raise ValueError("backup retirement requires explicit development-only apply")
        assert_development_path(self.root, development_root=development_root)
        semantic_keys = (
            "format",
            "version",
            "root",
            "inventory_digest",
            "policy",
            "retire",
            "protected",
            "unknown",
            "logical_duplicate_candidates",
        )
        if str(plan.get("format") or "") != self.FORMAT or int(plan.get("version") or 0) != self.VERSION:
            raise ValueError("invalid backup lifecycle plan")
        semantic = {key: plan[key] for key in semantic_keys}
        digest = self._digest(semantic)
        if digest != str(expected_plan_digest) or digest != str(plan.get("plan_digest") or ""):
            raise ValueError("backup lifecycle plan digest mismatch")
        retire = list(plan.get("retire") or [])
        if not retire:
            raise ValueError("backup retirement scope must not be empty")

        with self.store.lifecycle_lock():
            _inventory, current_digest, _unknown = self._inventory()
            if current_digest != str(plan.get("inventory_digest") or ""):
                raise ValueError("backup lifecycle inventory changed")
            verified: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for expected in retire:
                item = self.store.read(str(expected["backup_id"]))
                for field in (*self.REQUIRED_OWNER_FIELDS, "database_sha256", "database_size"):
                    if str(item.get(field) or "") != str(expected.get(field) or ""):
                        raise ValueError("backup retirement candidate changed")
                if str(item.get("result_status") or "") != "VALID_BACKUP":
                    raise ValueError("backup retirement candidate is no longer verified")
                validation = validate_sqlite(Path(str(item["path"])) / "database.sqlite")
                if (
                    not validation.get("valid")
                    or str(validation.get("sha256") or "") != str(expected["database_sha256"])
                    or int(validation.get("size_bytes") or 0) != int(expected["database_size"])
                ):
                    raise ValueError("backup retirement candidate content changed")
                verified.append((expected, item))

            deleted: list[str] = []
            for expected, _item in verified:
                backup_id = str(expected["backup_id"])
                self.store.delete(backup_id)
                deleted.append(backup_id)
        return {
            "plan_digest": digest,
            "deleted_backup_ids": deleted,
            "deleted_count": len(deleted),
            "reclaimed_bytes": sum(int(item["database_size"]) for item in retire),
            "development_only": True,
        }

    def _inventory(self) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
        inventory: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        if self.root.is_dir():
            for manifest_path in sorted(self.root.rglob("manifest.json")):
                try:
                    value = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    unknown.append(
                        {
                            "path": str(manifest_path.parent),
                            "classification": "UNKNOWN",
                            "action": "PROTECT",
                            "reason": "INVALID_MANIFEST",
                        }
                    )
                    continue
                if not isinstance(value, dict):
                    unknown.append(
                        {
                            "path": str(manifest_path.parent),
                            "classification": "UNKNOWN",
                            "action": "PROTECT",
                            "reason": "INVALID_MANIFEST",
                        }
                    )
                    continue
                database = manifest_path.parent / "database.sqlite"
                inventory.append(
                    {
                        **value,
                        "path": str(manifest_path.parent),
                        "manifest_path": str(manifest_path),
                        "manifest_sha256": sha256_file(manifest_path),
                        "database_exists": database.is_file(),
                        "actual_database_size": database.stat().st_size if database.is_file() else 0,
                    }
                )
            known_dirs = {Path(str(item["path"])).resolve() for item in inventory}
            known_dirs.update(Path(str(item["path"])).resolve() for item in unknown)
            for database in sorted(self.root.rglob("database.sqlite")):
                if database.parent.resolve() not in known_dirs:
                    unknown.append(
                        {
                            "path": str(database.parent),
                            "classification": "UNKNOWN",
                            "action": "PROTECT",
                            "reason": "MISSING_MANIFEST",
                        }
                    )
        digest_rows = [
            {
                "backup_id": str(item.get("backup_id") or ""),
                "manifest_path": str(item.get("manifest_path") or ""),
                "manifest_sha256": str(item.get("manifest_sha256") or ""),
                "database_size": int(item.get("actual_database_size") or 0),
            }
            for item in inventory
        ] + unknown
        return inventory, self._digest(digest_rows), unknown

    @staticmethod
    def _decision(
        item: dict[str, Any], *, action: str, reason: str, classification: str
    ) -> dict[str, Any]:
        return {
            "backup_id": str(item.get("backup_id") or ""),
            "path": str(item.get("path") or ""),
            "scope_type": str(item.get("scope_type") or ""),
            "scope_id": str(item.get("scope_id") or ""),
            "database_kind": str(item.get("database_kind") or ""),
            "database_sha256": str(item.get("database_sha256") or ""),
            "database_size": int(item.get("database_size") or 0),
            "classification": classification,
            "action": action,
            "reason": reason,
        }

    @classmethod
    def _logical_signature(cls, item: dict[str, Any]) -> str:
        validation = item.get("integrity_check_result")
        if not isinstance(validation, dict):
            return ""
        value = {
            "schema_version": validation.get("schema_version"),
            "table_names": validation.get("table_names"),
            "source_file_count": validation.get("source_file_count"),
            "session_count": validation.get("session_count"),
            "link_record_count": validation.get("link_record_count"),
            "switch_event_count": validation.get("switch_event_count"),
            "rssi_record_count": validation.get("rssi_record_count"),
        }
        return cls._digest(value)

    @staticmethod
    def _digest(value: object) -> str:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["BackupLifecycleService"]
