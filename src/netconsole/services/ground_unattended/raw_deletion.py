from __future__ import annotations

import json
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from netconsole.models.api.ground_unattended import (
    GroundSyslogDeleteAcceptedDTO,
    GroundSyslogDeletePreviewDTO,
    GroundSyslogDeletePreviewRequestDTO,
    GroundSyslogDeleteRequestDTO,
)
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.ground_unattended.raw_lifecycle import (
    GroundRawDataLifecycleService,
    GroundRawLifecycleError,
    GroundSyslogDeletionPlan,
)


class GroundDeletionProcessPort(Protocol):
    def start_job(self, job: BackgroundJob, **kwargs: object) -> str: ...


@dataclass(frozen=True)
class _StoredPreview:
    operation_id: str
    plan: GroundSyslogDeletionPlan
    expires_at: datetime


class GroundRawDataDeletionApplicationService:
    """Coordinates preview tokens, confirmation, audit, and Job Center."""

    def __init__(
        self,
        repository: GroundUnattendedRepository,
        *,
        process_adapter: GroundDeletionProcessPort | None = None,
        app_root: str = "",
        data_root: str = "",
        preview_ttl_seconds: int = 600,
    ) -> None:
        self.repository = repository
        self.lifecycle = GroundRawDataLifecycleService(repository)
        self.process_adapter = process_adapter
        self.app_root = str(app_root or "")
        self.data_root = str(data_root or "")
        self.preview_ttl_seconds = max(60, min(int(preview_ttl_seconds), 1800))
        self._previews: dict[str, _StoredPreview] = {}
        self._lock = threading.Lock()

    def preview(
        self,
        request: GroundSyslogDeletePreviewRequestDTO,
    ) -> GroundSyslogDeletePreviewDTO:
        preview = self.lifecycle.preview_syslog_deletion(
            run_id=request.run_id,
            mode=request.mode,
            record_keys=[
                item.model_dump(mode="json") for item in request.record_keys
            ],
            filters=request.filters.model_dump(mode="json"),
            include_derived_events=request.include_derived_events,
        )
        run = self.repository.get_run(request.run_id) or {}
        token = ""
        expires_at = ""
        if preview.plan is not None and not preview.blocked_reasons:
            now = datetime.now().astimezone()
            expiry = now + timedelta(seconds=self.preview_ttl_seconds)
            token = secrets.token_urlsafe(32)
            operation_id = f"grounddelete_{uuid.uuid4().hex}"
            stored = _StoredPreview(
                operation_id=operation_id,
                plan=preview.plan,
                expires_at=expiry,
            )
            with self._lock:
                self._drop_expired_locked(now)
                self._previews[token] = stored
            self.repository.save_delete_operation(
                {
                    "operation_id": operation_id,
                    "run_id": request.run_id,
                    "mode": request.mode,
                    "filters_json": request.model_dump_json(),
                    "selected_count": len(request.record_keys),
                    "matched_count": preview.matched_record_count,
                    "affected_file_count": preview.affected_file_count,
                    "revision_before_json": _revision_json(preview.plan),
                    "status": "PREVIEWED",
                    "confirmation_source": "",
                }
            )
            expires_at = expiry.isoformat(timespec="milliseconds")
        return GroundSyslogDeletePreviewDTO(
            run_id=request.run_id,
            run_date=str(run.get("run_date") or ""),
            mode=request.mode,
            matched_record_count=preview.matched_record_count,
            affected_file_count=preview.affected_file_count,
            affected_event_count=preview.affected_event_count,
            affected_timeline_count=preview.affected_timeline_count,
            total_bytes=preview.total_bytes,
            file_statuses=list(preview.file_statuses),
            archive_status=preview.archive_status,
            blocked_reasons=list(preview.blocked_reasons),
            warnings=list(preview.warnings),
            preview_token=token,
            expires_at=expires_at,
            confirmation_hint=(
                f"DELETE {str(run.get('run_date') or '')}"
                if run.get("run_date")
                else self.repository.site_id
            ),
        )

    def submit(
        self,
        request: GroundSyslogDeleteRequestDTO,
    ) -> GroundSyslogDeleteAcceptedDTO:
        now = datetime.now().astimezone()
        with self._lock:
            self._drop_expired_locked(now)
            stored = self._previews.get(request.preview_token)
            if stored is None:
                raise GroundRawLifecycleError(
                    "DELETE_PREVIEW_EXPIRED",
                    "删除预览已过期或已使用，请重新预览",
                )
            plan = stored.plan
            if not request.explicit_confirmation:
                raise GroundRawLifecycleError(
                    "DELETE_CONFIRMATION_REQUIRED",
                    "必须明确确认 Syslog 删除操作",
                )
            accepted_confirmations = {
                f"DELETE {plan.run_date}".strip(),
                self.repository.site_id,
            }
            if request.confirmation_text.strip() not in accepted_confirmations:
                raise GroundRawLifecycleError(
                    "DELETE_CONFIRMATION_INVALID",
                    "确认文本不匹配运行日期或当前局点",
                )
            if request.include_derived_events != plan.include_derived_events:
                raise GroundRawLifecycleError(
                    "DELETE_PREVIEW_CHANGED",
                    "派生事件处理选项已变化，请重新预览",
                )
            if self.process_adapter is None:
                raise GroundRawLifecycleError(
                    "JOB_CENTER_UNAVAILABLE",
                    "当前环境无法启动 Syslog 删除后台任务",
                )
            self._previews.pop(request.preview_token, None)
        task_id = uuid.uuid4().hex
        self.repository.update_delete_operation(
            stored.operation_id,
            status="PENDING",
            task_id=task_id,
            confirmation_source=(
                "RUN_DATE"
                if request.confirmation_text.strip().startswith("DELETE ")
                else "SITE_NAME"
            ),
        )
        job = BackgroundJob(
            job_id=task_id,
            task_type="ground_syslog_delete",
            params={
                "app_root": self.app_root,
                "data_root": self.data_root,
                "site_name": self.repository.site_id,
                "site_id": self.repository.site_id,
                "operation_id": stored.operation_id,
                "plan": plan.to_dict(),
                "task_name": (
                    f"删除无人值守 Syslog · {plan.run_date or plan.run_id}"
                ),
                "resource_keys": [
                    f"ground-unattended:{self.repository.site_id}:"
                    f"{plan.run_id}:syslog-lifecycle"
                ],
                "resource_conflict_message": (
                    "当前运行已有 Syslog 文件生命周期任务正在执行"
                ),
            },
        )
        try:
            started_task_id = self.process_adapter.start_job(job)
        except Exception as exc:
            self.repository.update_delete_operation(
                stored.operation_id,
                status="FAILED",
                completed_at=datetime.now()
                .astimezone()
                .isoformat(timespec="milliseconds"),
                failure_code="JOB_START_FAILED",
                failure_message=str(exc)[:500],
            )
            raise
        return GroundSyslogDeleteAcceptedDTO(
            operation_id=stored.operation_id,
            task_id=started_task_id,
            run_id=plan.run_id,
            message="Syslog 删除任务已进入任务中心",
        )

    def _drop_expired_locked(self, now: datetime) -> None:
        expired = [
            token
            for token, value in self._previews.items()
            if value.expires_at <= now
        ]
        for token in expired:
            self._previews.pop(token, None)


def _revision_json(plan: GroundSyslogDeletionPlan) -> str:
    return json.dumps(
        {
            str(row.get("file_id") or ""): int(row.get("revision") or 0)
            for row in plan.files
        },
        ensure_ascii=False,
    )


__all__ = [
    "GroundDeletionProcessPort",
    "GroundRawDataDeletionApplicationService",
]
