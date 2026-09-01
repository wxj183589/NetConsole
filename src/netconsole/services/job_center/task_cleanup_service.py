from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from netconsole.core.paths import PathResolver
from netconsole.models.task_history_policy import ACTIVE_TASK_STATE_VALUES, TERMINAL_TASK_STATE_VALUES
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.repositories.task_repository import TaskRepository


_REFERENCE_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_ref",
        "artifact_path",
        "download_ref",
        "output_path",
        "package_path",
        "report_path",
        "result_path",
        "path",
        "online_mr_session_id",
        "online_mr_session_ids",
        "ground_session_id",
        "ground_session_ids",
        "ground_unattended_session_id",
        "ground_unattended_session_ids",
        "ground_run_id",
        "ground_operation_id",
        "mesh_session_id",
        "mesh_session_ids",
        "mesh_source_id",
        "mesh_source_ids",
    }
)


@dataclass(frozen=True)
class CleanupDecision:
    task_id: str
    can_cleanup: bool
    status: str = ""
    reasons: tuple[str, ...] = ()
    protected_resources: tuple[str, ...] = ()
    event_rows: int = 0
    snapshot_rows: int = 0
    result_rows: int = 0
    result_bytes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "can_cleanup": self.can_cleanup,
            "status": self.status,
            "reasons": list(self.reasons),
            "protected_resources": list(self.protected_resources),
            "event_rows": self.event_rows,
            "snapshot_rows": self.snapshot_rows,
            "result_rows": self.result_rows,
            "result_bytes": self.result_bytes,
        }


@dataclass(frozen=True)
class _ArtifactManifestIndex:
    references_by_site_task: dict[tuple[str, str], tuple[str, ...]]
    unreadable_sites: frozenset[str]

    def references_for(self, site: str, task_id: str) -> list[str]:
        if site in self.unreadable_sites:
            return ["artifact_manifest_unreadable"]
        return list(self.references_by_site_task.get((site, task_id), ()))


class TaskCleanupService:
    """Own explicit Task Center cleanup without deleting business authorities.

    The service is deliberately conservative.  It only removes the three
    task-owned current tables after a terminal task has no active mapping,
    durable artifact/session reference, or unrecognised resource key.  Sealed
    history, Ground data, Online MR data, and files are outside this service's
    deletion boundary.
    """

    def __init__(
        self,
        repository: TaskRepository,
        *,
        paths: PathResolver | None = None,
        site_name: str = "",
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.site_name = str(site_name or "")

    def can_cleanup(self, task_id: str) -> dict[str, object]:
        decision = self._decision(str(task_id or ""))
        return decision.to_dict()

    def preview_cleanup(self, task_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, object]:
        ids = self._normalize_ids(task_ids)
        decisions = self._decisions(ids)
        return self._preview_payload(ids, decisions)

    def cleanup_tasks(
        self,
        task_ids: list[str] | tuple[str, ...] | set[str],
    ) -> dict[str, object]:
        ids = self._normalize_ids(task_ids)
        decisions = self._decisions(ids)
        eligible = [item.task_id for item in decisions if item.can_cleanup]
        deletion = self.repository.delete_task_owned_rows(eligible)
        deleted = dict(deletion["deleted"])

        return {
            "requested_task_ids": ids,
            "deleted_task_ids": deletion["deleted_task_ids"],
            "skipped": [item.to_dict() for item in decisions if not item.can_cleanup],
            "deleted": deleted,
            "orphan_blobs_removed": deletion["orphan_blobs_removed"],
            "orphan_blob_bytes_removed": deletion["orphan_blob_bytes_removed"],
            "external_bytes_created": 0,
            "quick_check": deletion["quick_check"],
            "counts": {
                "task_events": deleted["task_events"],
                "task_snapshots": deleted["task_snapshots"],
                "task_results": deleted["task_results"],
            },
        }

    def dismiss_task(self, task_id: str, *, dismissed_by: str = "local-user") -> dict[str, object]:
        """Keep the existing reversible UI dismissal under this service boundary."""

        return self.repository.dismiss_task(task_id, dismissed_by=dismissed_by)

    def dismiss_history(
        self,
        cleanup_type: str,
        *,
        include_states: list[str] | None = None,
        exclude_states: list[str] | None = None,
        dismissed_by: str = "local-user",
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Run the current Task Center soft-hide contract, without file deletion."""

        return self.repository.cleanup_history(
            cleanup_type,
            include_states=include_states,
            exclude_states=exclude_states,
            dismissed_by=dismissed_by,
            dry_run=dry_run,
        )

    def cleanup_terminal_retention(self) -> dict[str, object]:
        """Compatibility facade for the repository-owned retention entrypoint."""

        return self.repository.enforce_terminal_history_retention()

    def _decisions(self, task_ids: list[str]) -> list[CleanupDecision]:
        contexts: dict[str, dict[str, object]] = {}
        for task_id in task_ids:
            context = self.repository.read_task_cleanup_context(task_id)
            if context is not None:
                contexts[task_id] = context
        manifest_index = self._build_artifact_manifest_index(contexts)
        return [
            self._decision(
                task_id,
                context=contexts.get(task_id),
                manifest_index=manifest_index,
            )
            for task_id in task_ids
        ]

    def _decision(
        self,
        task_id: str,
        *,
        context: dict[str, object] | None = None,
        manifest_index: _ArtifactManifestIndex | None = None,
    ) -> CleanupDecision:
        if not task_id:
            return CleanupDecision(task_id, False, reasons=("TASK_NOT_FOUND",))
        if context is None:
            context = self.repository.read_task_cleanup_context(task_id)
        if context is None:
            return CleanupDecision(task_id, False, reasons=("TASK_NOT_FOUND",))
        values = dict(context["snapshot"])
        status = str(values.get("status") or "").upper()
        reasons: list[str] = []
        protected: list[str] = []
        if status in ACTIVE_TASK_STATE_VALUES:
            reasons.append("ACTIVE_TASK")
        elif status not in TERMINAL_TASK_STATE_VALUES:
            reasons.append("UNKNOWN_OR_NON_TERMINAL_STATUS")

        if bool(context["online_mapping"]):
            reasons.append("ONLINE_MR_MAPPING")
            protected.append("online_mr_task_sessions")
        ground_refs = self._ground_references(values, task_id)
        if ground_refs:
            reasons.append("GROUND_CURRENT_MAPPING")
            protected.extend(ground_refs)
        artifact_refs = self._artifact_references(
            values, task_id, manifest_index=manifest_index
        )
        if artifact_refs:
            reasons.append("ARTIFACT_MANIFEST_REFERENCE")
            protected.extend(artifact_refs)

        resource_keys, valid = self._json_list(values.get("resource_keys_json"))
        if not valid:
            reasons.append("RESOURCE_METADATA_UNREADABLE")
        elif resource_keys:
            reasons.append("RESOURCE_REFERENCE")
            protected.extend(str(value) for value in resource_keys)

        result = context["result"]
        result_valid = bool(context["result_valid"])
        if not result_valid:
            reasons.append("RESULT_METADATA_UNREADABLE")
        elif result is None and str(values.get("result_id") or ""):
            reasons.append("RESULT_AUTHORITY_UNREADABLE")
        if result_valid and result is not None and self._contains_reference(result):
            reasons.append("DURABLE_RESULT_REFERENCE")
            protected.extend(self._reference_names(result))
        summary, summary_valid = self._json_object(values.get("result_summary_json"))
        if not summary_valid:
            reasons.append("RESULT_SUMMARY_UNREADABLE")
        elif self._contains_reference(summary):
            reasons.append("DURABLE_RESULT_SUMMARY_REFERENCE")
            protected.extend(self._reference_names(summary))
        if str(values.get("result_path") or "").strip():
            reasons.append("RESULT_ARTIFACT_REFERENCE")
            protected.append(str(values["result_path"]))
        if "online_mr" in str(values.get("task_type") or "").casefold():
            reasons.append("ONLINE_MR_TASK")
        if "ground_unattended" in str(values.get("task_type") or "").casefold():
            reasons.append("GROUND_TASK")

        reasons = list(dict.fromkeys(reasons))
        protected = list(dict.fromkeys(protected))
        return CleanupDecision(
            task_id=task_id,
            can_cleanup=not reasons,
            status=status,
            reasons=tuple(reasons),
            protected_resources=tuple(protected),
            event_rows=int(context["event_rows"]),
            snapshot_rows=1,
            result_rows=int(context["result_rows"]),
            result_bytes=int(context["result_bytes"]),
        )

    def _ground_references(self, row: dict[str, object], task_id: str) -> list[str]:
        if self.paths is None:
            return ["ground_scope_unavailable"]
        site = str(row.get("site_name") or self.site_name or "demo")
        if not str(row.get("site_name") or self.site_name).strip():
            return ["ground_scope_unknown"]
        db_path = self.paths.ground_unattended_db_path(site)
        try:
            return GroundUnattendedRepository.find_task_references_readonly(
                db_path, task_id
            )
        except (OSError, sqlite3.DatabaseError):
            return ["ground_unreadable"]

    def _artifact_references(
        self,
        row: dict[str, object],
        task_id: str,
        *,
        manifest_index: _ArtifactManifestIndex | None = None,
    ) -> list[str]:
        """Protect task-linked manifests without owning external file deletion."""

        if self.paths is None:
            return ["artifact_scope_unavailable"]
        site = str(row.get("site_name") or self.site_name or "").strip()
        if not site:
            return ["artifact_scope_unknown"]
        if manifest_index is None:
            manifest_index = self._build_artifact_manifest_index(
                {task_id: {"snapshot": row}}
            )
        return manifest_index.references_for(site, task_id)

    def _build_artifact_manifest_index(
        self, contexts: dict[str, dict[str, object]]
    ) -> _ArtifactManifestIndex:
        tasks_by_site: dict[str, set[str]] = {}
        for task_id, context in contexts.items():
            row = dict(context["snapshot"])
            site = str(row.get("site_name") or self.site_name or "").strip()
            if site:
                tasks_by_site.setdefault(site, set()).add(task_id)

        if self.paths is None:
            return _ArtifactManifestIndex({}, frozenset())

        references: dict[tuple[str, str], tuple[str, ...]] = {}
        unreadable_sites: set[str] = set()
        for site, task_ids in tasks_by_site.items():
            site_references, unreadable = self._scan_artifact_manifests(
                site, task_ids
            )
            if unreadable:
                unreadable_sites.add(site)
                continue
            references.update(
                {(site, task_id): paths for task_id, paths in site_references.items()}
            )
        return _ArtifactManifestIndex(references, frozenset(unreadable_sites))

    def _scan_artifact_manifests(
        self, site: str, task_ids: set[str]
    ) -> tuple[dict[str, tuple[str, ...]], bool]:
        roots = (
            self.paths.rail_transit_root(site) / "web_artifacts" / "manifests",
            self.paths.config_center_root(site) / "outputs",
        )
        references: dict[str, list[str]] = {}
        for root in roots:
            try:
                if not root.is_dir():
                    continue
                manifest_paths = sorted(root.glob("*.json"), key=lambda path: path.name)
            except OSError:
                return {}, True
            for manifest_path in manifest_paths:
                try:
                    if manifest_path.is_symlink():
                        continue
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
                    return {}, True
                if isinstance(manifest, dict):
                    task_id = str(manifest.get("task_id") or "")
                    if task_id in task_ids:
                        references.setdefault(task_id, []).append(str(manifest_path))
        return {
            task_id: tuple(paths) for task_id, paths in references.items()
        }, False


    @staticmethod
    def _contains_reference(value: object) -> bool:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key or "").casefold()
                if normalized in _REFERENCE_KEYS and TaskCleanupService._has_value(nested):
                    return True
                if TaskCleanupService._contains_reference(nested):
                    return True
        elif isinstance(value, (list, tuple, set)):
            return any(TaskCleanupService._contains_reference(item) for item in value)
        return False

    @classmethod
    def _reference_names(cls, value: object) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key or "").casefold() in _REFERENCE_KEYS and cls._has_value(nested):
                    found.append(str(key))
                found.extend(cls._reference_names(nested))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                found.extend(cls._reference_names(item))
        return list(dict.fromkeys(found))

    @staticmethod
    def _has_value(value: object) -> bool:
        return bool(value) if isinstance(value, (str, list, tuple, set, dict)) else value is not None

    @staticmethod
    def _json_object(value: object) -> tuple[dict[str, object], bool]:
        raw = str(value or "").strip()
        if raw in {"", "null"}:
            return {}, True
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, False
        return (dict(parsed), True) if isinstance(parsed, dict) else ({}, False)

    @staticmethod
    def _json_list(value: object) -> tuple[list[object], bool]:
        raw = str(value or "").strip()
        if raw in {"", "null"}:
            return [], True
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [], False
        return (list(parsed), True) if isinstance(parsed, list) else ([], False)

    @staticmethod
    def _normalize_ids(task_ids: list[str] | tuple[str, ...] | set[str]) -> list[str]:
        return list(dict.fromkeys(str(task_id).strip() for task_id in task_ids if str(task_id).strip()))

    @staticmethod
    def _now() -> str:
        from netconsole.models.task_snapshot import utc_now_iso

        return utc_now_iso()

    @staticmethod
    def _preview_payload(ids: list[str], decisions: list[CleanupDecision]) -> dict[str, object]:
        eligible = [item for item in decisions if item.can_cleanup]
        return {
            "requested_task_ids": ids,
            "decisions": [item.to_dict() for item in decisions],
            "eligible_count": len(eligible),
            "protected_count": len(decisions) - len(eligible),
            "estimated_reclaimable_bytes": sum(item.result_bytes for item in eligible),
            "estimated_reclaimable_rows": {
                "task_events": sum(item.event_rows for item in eligible),
                "task_snapshots": sum(item.snapshot_rows for item in eligible),
                "task_results": sum(item.result_rows for item in eligible),
            },
        }


__all__ = ["CleanupDecision", "TaskCleanupService"]
