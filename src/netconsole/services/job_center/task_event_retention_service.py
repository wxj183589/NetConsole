"""Short-lived task runtime event retention.

This service is deliberately separate from explicit task-owned operational GC
and from SiteRetention/Production maintenance. It only removes old
``task_events`` rows after the task repository and external current-state
owners have been checked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.task_history_policy import TERMINAL_TASK_STATE_VALUES
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.repositories.task_repository import TaskRepository


TASK_EVENT_RETENTION_INTERVAL = timedelta(hours=24)
TASK_EVENT_RETENTION_BATCH_TASKS = 500


class TaskEventRetentionService:
    """Run the once-per-day, event-only retention policy for one site."""

    def __init__(self, paths: PathResolver, repository: TaskRepository, *, site_name: str) -> None:
        self.paths = paths
        self.repository = repository
        self.site_name = str(site_name or "demo")

    def run_due(
        self,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict[str, object]:
        settings = SettingsStore(self.paths)
        current_time = _as_utc(now or datetime.now(UTC))
        retention_days = settings.task_event_retention_days
        previous_run = _parse_timestamp(settings.get_value("last_task_event_cleanup_at", ""))
        if (
            not force
            and previous_run is not None
            and timedelta(0) <= current_time - previous_run < TASK_EVENT_RETENTION_INTERVAL
        ):
            return {
                "status": "SKIPPED_NOT_DUE",
                "site_name": self.site_name,
                "retention_days": retention_days,
                "last_cleanup_at": _timestamp(previous_run),
                "deleted_event_rows": 0,
                "deleted_task_ids": [],
            }

        cutoff = current_time - timedelta(days=retention_days)
        preview = self.repository.preview_task_event_retention(cutoff=cutoff)
        candidates = [
            item for item in preview.get("candidates", [])
            if isinstance(item, dict)
            and str(item.get("task_id") or "").strip()
            and str(item.get("status") or "").upper() in TERMINAL_TASK_STATE_VALUES
        ]
        online_protected = {
            str(task_id)
            for task_id in preview.get("protected_online_task_ids", [])
            if str(task_id).strip()
        }
        ground_protected: set[str] = set()
        ground_protection_errors: dict[str, str] = {}
        for item in candidates:
            task_id = str(item["task_id"])
            try:
                references = GroundUnattendedRepository.find_task_references_readonly(
                    self.paths.ground_unattended_db_path(self.site_name),
                    task_id,
                )
            except Exception as exc:  # fail closed when the external owner cannot be read
                ground_protected.add(task_id)
                ground_protection_errors[task_id] = exc.__class__.__name__
                continue
            if references:
                ground_protected.add(task_id)

        externally_protected = online_protected | ground_protected
        candidate_ids = [str(item["task_id"]) for item in candidates]
        deleted_task_ids: list[str] = []
        deleted_event_rows = 0
        deleted_event_payload_bytes = 0
        event_batches = 0
        protected_ids = sorted(externally_protected)
        for start in range(0, len(candidate_ids), TASK_EVENT_RETENTION_BATCH_TASKS):
            batch_ids = candidate_ids[start : start + TASK_EVENT_RETENTION_BATCH_TASKS]
            batch = self.repository.delete_task_events_for_retention(
                batch_ids,
                cutoff=cutoff,
                protected_task_ids=externally_protected,
            )
            deleted_task_ids.extend(str(task_id) for task_id in batch.get("deleted_task_ids", []))
            deleted_event_rows += int(batch.get("deleted_event_rows") or 0)
            deleted_event_payload_bytes += int(batch.get("deleted_event_payload_bytes") or 0)
            event_batches += int(batch.get("event_batches") or 0)

        cleanup_timestamp = _timestamp(current_time)
        settings.update_explicit({"last_task_event_cleanup_at": cleanup_timestamp})
        return {
            "status": "COMPLETED",
            "site_name": self.site_name,
            "retention_days": retention_days,
            "cutoff": _timestamp(cutoff),
            "last_cleanup_at": cleanup_timestamp,
            "candidate_task_ids": candidate_ids,
            "candidate_count": len(candidate_ids),
            "deleted_task_ids": deleted_task_ids,
            "deleted_event_rows": deleted_event_rows,
            "deleted_event_payload_bytes": deleted_event_payload_bytes,
            "event_batches": event_batches,
            "protected_online_task_ids": sorted(online_protected),
            "protected_ground_task_ids": sorted(ground_protected),
            "protected_task_ids": protected_ids,
            "ground_protection_errors": ground_protection_errors,
            "skipped_invalid_finished_time": int(preview.get("skipped_invalid_finished_time") or 0),
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = ["TASK_EVENT_RETENTION_BATCH_TASKS", "TASK_EVENT_RETENTION_INTERVAL", "TaskEventRetentionService"]
