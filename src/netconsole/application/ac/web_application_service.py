from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from netconsole.application.web_artifacts import WebArtifactError, WebArtifactStore
from netconsole.application.web_export_process_adapter import WebExportProcessAdapter
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.ac_management import (
    AcActionPlanDTO,
    AcExtensionApplyResultDTO,
    AcExtensionDTO,
    AcExtensionPageDTO,
    AcExtensionPreviewDTO,
    AcExtensionRollbackResultDTO,
    AcTracksidePlanDTO,
    AcTracksidePlanPageDTO,
    AcWebTaskDTO,
)
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_task_builders import fit_ap_extension_xlsx_spec
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text, sanitize_web_export_snapshot
from netconsole.services.rail_transit.base_data_import_service import BaseDataImportError, RailTransitBaseDataImportService
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService


ACTION_DEFINITIONS = {
    "persist_auto_ap": ("固化新 AP", ("system-view", "wlan auto-ap persistent all", "save force", "return", "quit")),
    "save_config": ("save force", ("save force",)),
    "enable_ap_remote_login": ("开启 AP 远程登录", ("screen-length disable", "system-view", "probe", "wlan ap-execute all exec-console enable", "return", "quit")),
}
_PLAN_ID = re.compile(r"^ac-plan-[0-9a-f]{32}$")


class AcWebActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AcWebApplicationService:
    """AC Web 用例边界；设备 IO 只通过持久化后台任务执行。"""

    _OWNER = "web_ac"
    _ARTIFACT_TASK_TYPES = {"ac_extension_export": "web_export_fit_ap_extension_xlsx"}
    _LOCAL_REBUILD_TASKS = {
        "ac_overview_refresh": "AC 在线概览本地重算",
        "ac_fit_ap_resources_refresh": "FIT-AP 信息本地重算",
        "ac_fit_ap_optical_refresh": "FIT-AP 光衰本地重算",
        "trackside_ap_plan_refresh": "轨旁 AP 规划本地加载",
        "ac_trackside_business_refresh": "轨旁 AP 业务本地重算",
    }
    _REFRESH_TASKS = {
        "ac": ("ac_info_refresh", "更新 AC 信息"),
        "fit-ap": ("ac_fit_ap_resources_refresh", "更新 FIT-AP 资源"),
        "ap-detail": ("ac_fit_ap_detail_refresh", "深度更新 FIT-AP"),
    }
    _TASK_ACTIONS = {
        **{task_type: task_type for task_type in _LOCAL_REBUILD_TASKS},
        **{task_type: task_type for task_type, _task_name in _REFRESH_TASKS.values()},
        "web_export_fit_ap_extension_xlsx": "ac_extension_export",
    }
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter,
        import_preview_service: RailTransitImportPreviewService | None = None,
        base_import_service: RailTransitBaseDataImportService | None = None,
        export_adapter: WebExportProcessAdapter | None = None,
        artifact_store: WebArtifactStore | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter
        self.base_import_service = base_import_service or RailTransitBaseDataImportService(paths)
        self.import_preview_service = import_preview_service or RailTransitImportPreviewService(
            RailTransitBaseDataQueryService(paths), import_service=self.base_import_service
        )
        self.export_adapter = export_adapter
        self.artifact_store = artifact_store or WebArtifactStore(paths, task_service)

    def current_site_id(self) -> str:
        try:
            data = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            value = data.get("current_site") if isinstance(data, dict) else None
            return self._site(str(value or ""))
        except (OSError, TypeError, ValueError, json.JSONDecodeError, AcWebActionError) as exc:
            raise AcWebActionError("SITE_CONTEXT_INVALID", "当前局点上下文无效") from exc

    def list_extensions(self, site_id: str, *, search: str = "", page: int = 1, page_size: int = 50) -> AcExtensionPageDTO:
        site_id = self._site(site_id)
        rows = self._repository(site_id).list_ap_extension_points(search=search)
        items = [self._extension_dto(row) for row in rows]
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        start = (page - 1) * page_size
        return AcExtensionPageDTO(items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)

    def list_trackside_plan(self, site_id: str, mode: str = TRACKSIDE_AP_PLAN_MODE) -> AcTracksidePlanPageDTO:
        site_id = self._site(site_id)
        mode = str(mode or TRACKSIDE_AP_PLAN_MODE)
        rows = self._repository(site_id).list_trackside_ap_plan(mode)
        items = [
            AcTracksidePlanDTO(
                mode=str(row.get("mode") or TRACKSIDE_AP_PLAN_MODE),
                station_name=str(row.get("station_name") or ""),
                ap_count=int(row.get("ap_count") or 0),
                ap_start_address=str(row.get("ap_start_address") or ""),
                mask_length=int(row.get("mask_length") or 0),
                ap_gateway=str(row.get("ap_gateway") or ""),
                ap_management_vlans=str(row.get("ap_management_vlans") or ""),
                remark=str(row.get("remark") or ""),
                sort_order=int(row.get("sort_order") or 0),
                created_at=str(row.get("created_at") or ""),
                updated_at=str(row.get("updated_at") or ""),
            )
            for row in rows
        ]
        return AcTracksidePlanPageDTO(items=items, total=len(items), mode=mode)

    def start_local_rebuild(
        self,
        site_id: str,
        task_type: str,
        *,
        ac_id: str,
    ) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if task_type not in self._LOCAL_REBUILD_TASKS:
            raise AcWebActionError("TASK_NOT_ALLOWED", "不支持的 AC Web 本地重算任务")
        ac_id = str(ac_id or "").strip()
        if ac_id:
            ac_id = str(self._target(site_id, ac_id).device_uuid)
        task_id = f"ac-web-{uuid4().hex}"
        params: dict[str, object] = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": self._LOCAL_REBUILD_TASKS[task_type],
            "owner": self._OWNER,
            "task_source": "local",
            "device_uuid": ac_id,
            "ac_uuid": ac_id,
        }
        if task_type == "trackside_ap_plan_refresh":
            params["mode"] = TRACKSIDE_AP_PLAN_MODE
        self.process_adapter.start_job(BackgroundJob(job_id=task_id, task_type=task_type, params=params))
        return self._task_dto(site_id, task_id)

    def start_refresh(self, site_id: str, refresh_kind: str, *, ac_id: str, ap_id: str = "") -> AcWebTaskDTO:
        site_id = self._site(site_id)
        try:
            task_type, task_name = self._REFRESH_TASKS[refresh_kind]
        except KeyError as exc:
            raise AcWebActionError("TASK_NOT_ALLOWED", "不支持的 AC/FIT-AP 更新类型") from exc
        device_uuid = str(self._target(site_id, ac_id).device_uuid)
        ap_uuid = str(ap_id or "").strip()
        if refresh_kind == "ap-detail":
            if not ap_uuid:
                raise AcWebActionError("AP_TARGET_REQUIRED", "FIT-AP 深度更新缺少 AP 目标")
            if self._repository(site_id).get_fit_ap_resource_by_uuid(device_uuid, ap_uuid) is None:
                raise AcWebActionError("AP_TARGET_NOT_AUTHORIZED", "目标 FIT-AP 不属于当前 AC")
        task_id = f"ac-web-{uuid4().hex}"
        params = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": task_name,
            "owner": self._OWNER,
            "task_source": "local",
            "device_uuid": device_uuid,
            "ac_uuid": device_uuid,
            "mode": "collect",
            "source": "cli",
        }
        if ap_uuid:
            params["ap_uuid"] = ap_uuid
        self.process_adapter.start_job(BackgroundJob(job_id=task_id, task_type=task_type, params=params))
        return self._task_dto(site_id, task_id)

    def get_task(self, site_id: str, task_id: str) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        return self._task_dto(site_id, task_id)

    def cancel_task(self, site_id: str, task_id: str) -> AcWebTaskDTO:
        site_id = self._site(site_id)
        snapshot = self._task_snapshot(site_id, task_id)
        if snapshot.status not in TERMINAL_TASK_STATES:
            cancelled = self.process_adapter.cancel_job(task_id)
            if not cancelled and self.export_adapter is not None:
                cancelled = self.export_adapter.cancel_job(task_id)
            if not cancelled:
                self._reconcile_owned_orphans(site_id)
        return self._task_dto(site_id, task_id)

    def recover_tasks(self, site_id: str) -> list[AcWebTaskDTO]:
        site_id = self._site(site_id)
        repository = self.task_service.repository(site_id)
        self._reconcile_owned_orphans(site_id)
        for item in repository.list(statuses=TERMINAL_TASK_STATES, limit=1000):
            if item.site_name != site_id or not self._authorized_task(item):
                continue
            self._cleanup_task_runtime(item.task_id)
            if item.task_type in self._ARTIFACT_TASK_TYPES.values():
                self.artifact_store.recover_task(
                    site_id,
                    item.task_id,
                    owner=self._OWNER,
                    source_task_types=self._ARTIFACT_TASK_TYPES,
                    succeeded=item.status == TaskState.COMPLETED,
                )
        return [
            self._task_dto(site_id, item.task_id)
            for item in repository.list(limit=200)
            if item.site_name == site_id and self._authorized_task(item)
        ]

    def create_action_plan(self, site_id: str, target_id: str, action_id: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        label, commands = self._action(action_id)
        target = self._target(site_id, target_id)
        plan_id = f"ac-plan-{uuid4().hex}"
        fingerprint = self._fingerprint(target)
        digest = self._digest(plan_id, site_id, str(target.device_uuid), action_id, commands, fingerprint)
        plan: dict[str, object] = {
            "plan_id": plan_id,
            "site_id": site_id,
            "target_id": str(target.device_uuid),
            "target_fingerprint": fingerprint,
            "action_id": action_id,
            "action_label": label,
            "commands": list(commands),
            "digest": digest,
            "token": secrets.token_urlsafe(24),
            "expires_at": time.time() + 300,
            "status": "PREVIEW",
            "task_id": "",
        }
        self._save_plan(plan)
        return self._plan_dto(plan)

    def preview_action_plan(self, site_id: str, plan_id: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            if float(plan["expires_at"]) <= time.time() and plan["status"] == "PREVIEW":
                plan["status"] = "EXPIRED"
                self._save_plan(plan)
            return self._plan_dto(plan)

    def confirm_action_plan(self, site_id: str, plan_id: str, plan_digest: str, confirm_token: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            self._validate_plan(plan, plan_digest, confirm_token)
            if plan["status"] != "PREVIEW":
                raise AcWebActionError("PLAN_ALREADY_CONFIRMED", "计划已确认或已执行")
            self._revalidate_target(plan)
            plan["status"] = "CONFIRMED"
            self._save_plan(plan)
            return self._plan_dto(plan)

    def execute_action_plan(self, site_id: str, plan_id: str) -> AcActionPlanDTO:
        site_id = self._site(site_id)
        with self._lock(plan_id):
            plan = self._plan_data(plan_id, site_id)
            if float(plan["expires_at"]) <= time.time():
                raise AcWebActionError("PLAN_EXPIRED", "动作计划已过期")
            if plan["status"] != "CONFIRMED":
                raise AcWebActionError("CONFIRMATION_REQUIRED", "执行前必须完成二次确认")
            self._validate_plan(plan, str(plan["digest"]), str(plan["token"]))
            self._revalidate_target(plan)
            plan["status"] = "FAKE_EXECUTING"
            self._save_plan(plan)
            label, _commands = self._action(str(plan["action_id"]))
            task_id = f"ac-web-fake-action-{uuid4().hex}"
            try:
                self.task_service.create_external_task(
                    task_id=task_id,
                    task_type="ac_web_fake_action",
                    task_name=f"Fake AC 动作 · {label}",
                    source="fake",
                    site_name=site_id,
                    owner="web_ac_action",
                    device=str(plan["target_id"]),
                )
                self.task_service.record_external_event(
                    task_id,
                    "state",
                    {"state": "RUNNING", "stage": "fake_executor", "message": "Fake Executor 已接收固定 AC 动作"},
                    source="fake",
                    site_name=site_id,
                )
                self.task_service.record_external_event(
                    task_id,
                    "finished",
                    {
                        "message": "Fake AC 动作结束，未连接真实设备",
                        "result": {
                            "fake": True,
                            "executor": "FAKE",
                            "real_device_called": False,
                            "plan_id": str(plan["plan_id"]),
                            "plan_digest": str(plan["digest"]),
                            "action_id": str(plan["action_id"]),
                            "target_id": str(plan["target_id"]),
                        },
                    },
                    source="fake",
                    site_name=site_id,
                )
            except Exception:
                plan["status"] = "FAKE_FAILED"
                self._save_plan(plan)
                raise
            plan["status"] = "FAKE_COMPLETED"
            plan["task_id"] = task_id
            self._save_plan(plan)
            return self._plan_dto(plan)

    def action_audit(self, site_id: str, plan_id: str) -> dict[str, object]:
        plan = self._plan_data(plan_id, self._site(site_id))
        return {
            "plan_id": plan["plan_id"],
            "target_id": plan["target_id"],
            "action_id": plan["action_id"],
            "plan_digest": plan["digest"],
            "status": plan["status"],
            "task_id": plan["task_id"],
            "executor": "FAKE",
            "real_device_called": False,
            "audit": True,
        }

    def preview_extension(self, site_id: str, file_name: str, content: bytes, content_type: str = "") -> AcExtensionPreviewDTO:
        site_id = self._site(site_id)
        try:
            preview = self.import_preview_service.preview(
                site_id=site_id,
                file_name=file_name,
                content=content,
                content_type=content_type,
            )
        except (BaseDataImportError, ValueError) as exc:
            self._import_error(exc)
        summary = preview.merge_plan.summary.model_dump() if preview.merge_plan is not None else {}
        return AcExtensionPreviewDTO(
            preview_id=preview.preview_id,
            file_name=preview.file_name,
            template_type=preview.template_type,
            confidence_score=preview.confidence_score,
            low_confidence=preview.confidence_score < 70,
            summary={key: int(value or 0) for key, value in summary.items()},
            row_count=preview.total_rows,
            preview_digest=preview.database_hash,
        )

    def apply_extension(self, site_id: str, preview_id: str, preview_digest: str, explicit_confirmation: bool) -> AcExtensionApplyResultDTO:
        site_id = self._site(site_id)
        with self._lock(f"import:{site_id}:{preview_id}"):
            try:
                audit = self.base_import_service.apply_preview(
                    preview_id=preview_id,
                    site_id=site_id,
                    expected_database_sha256=preview_digest,
                    explicit_confirmation=explicit_confirmation,
                    owner="web_ac",
                )
            except BaseDataImportError as exc:
                if exc.code != "ALREADY_APPLIED":
                    self._import_error(exc)
                operation = self.base_import_service.get_operation(site_id, preview_id)
                return self._apply_result(operation.model_dump())
        return self._apply_result(audit)

    def rollback_extension(self, site_id: str, audit_id: str, explicit_confirmation: bool) -> AcExtensionRollbackResultDTO:
        site_id = self._site(site_id)
        with self._lock(f"import:{site_id}:{audit_id}"):
            try:
                audit = self.base_import_service.rollback_import(
                    site_id=site_id,
                    operation_id=audit_id,
                    explicit_confirmation=explicit_confirmation,
                )
            except BaseDataImportError as exc:
                self._import_error(exc)
        return AcExtensionRollbackResultDTO(
            audit_id=str(audit.get("operation_id") or audit_id),
            status=str(audit.get("status") or "ROLLED_BACK"),
            restored_rows=len(audit.get("changes") or ()),
        )

    def start_extension_export(self, site_id: str, *, search: str = "", ac_id: str = "") -> AcWebTaskDTO:
        site_id = self._site(site_id)
        if self.export_adapter is None:
            raise AcWebActionError("EXPORT_NOT_WIRED", "AC 扩展导出进程未接线")
        task_id = f"ac-export-{uuid4().hex}"
        reservation = self.artifact_store.reserve(
            site_id=site_id,
            owner="web_ac",
            source="ac_extension_export",
            artifact_type="xlsx",
            task_id=task_id,
            task_type=self._ARTIFACT_TASK_TYPES["ac_extension_export"],
            output_root=self.paths.trackside_ap_outputs_dir(site_id) / "web_extensions",
            preferred_name="AP扩展信息.xlsx",
        )
        job = fit_ap_extension_xlsx_spec(
            reservation.output_path,
            db_path=self.paths.site_db_path(site_id),
            ac_uuid=ac_id,
            search=search,
            title="AP 扩展信息导出",
            open_dir_on_success=False,
        ).to_job(task_id)
        job = replace(job, site_name=site_id)

        def completed(value: LocalProcessCompletion) -> None:
            if value.exit_code == 0 and not value.cancelled:
                try:
                    self.artifact_store.complete(reservation)
                except WebArtifactError:
                    self.artifact_store.fail(reservation)
            else:
                self.artifact_store.fail(reservation)

        try:
            self.export_adapter.start_export(
                job,
                task_name="AP 扩展信息导出",
                owner="web_ac",
                public_result=self._public_artifact_result(reservation),
                on_complete=completed,
            )
        except Exception:
            self.artifact_store.fail(reservation)
            raise
        return self._task_dto(site_id, task_id)

    @staticmethod
    def _public_artifact_result(reservation) -> dict[str, object]:
        return {
            "artifact_id": reservation.artifact_id,
            "artifact_name": reservation.output_path.name,
            "artifact_source": reservation.source,
            "artifact_type": reservation.artifact_type,
        }

    def open_extension_export(self, site_id: str, artifact_id: str) -> tuple[Path, str]:
        try:
            path, name, _manifest = self.artifact_store.open(
                site_id=self._site(site_id),
                artifact_id=artifact_id,
                owner="web_ac",
                source="ac_extension_export",
                artifact_type="xlsx",
                task_type=self._ARTIFACT_TASK_TYPES["ac_extension_export"],
            )
        except WebArtifactError as exc:
            raise AcWebActionError("ARTIFACT_INVALID", str(exc)) from exc
        return path, name

    def _task_dto(self, site_id: str, task_id: str) -> AcWebTaskDTO:
        snapshot = sanitize_web_export_snapshot(self._task_snapshot(site_id, task_id))
        metadata = (
            self.artifact_store.task_metadata(
                site_id,
                task_id,
                owner=self._OWNER,
                source_task_types=self._ARTIFACT_TASK_TYPES,
            )
            if snapshot.task_type in self._ARTIFACT_TASK_TYPES.values()
            else None
        )
        return AcWebTaskDTO(
            task_id=task_id,
            status=snapshot.status.value,
            action=self._TASK_ACTIONS[snapshot.task_type],
            artifact_id=str((metadata or {}).get("artifact_id") or ""),
            available=bool(metadata and metadata.get("completed") is True),
            progress=snapshot.progress,
            stage=snapshot.stage,
            current=snapshot.current,
            total=snapshot.total,
            sha256=str((metadata or {}).get("sha256") or ""),
            size_bytes=int((metadata or {}).get("size_bytes") or 0),
            message=redact_web_task_text(snapshot.message),
            error_message=redact_web_task_text(snapshot.error_message),
            result_summary=self._result_summary(snapshot.result),
        )

    def _task_snapshot(self, site_id: str, task_id: str):
        snapshot = self.task_service.repository(site_id).get(str(task_id or ""))
        if snapshot is None or snapshot.site_name != site_id or not self._authorized_task(snapshot):
            raise AcWebActionError("TASK_NOT_FOUND", "任务不存在或不属于当前局点")
        return snapshot

    def _authorized_task(self, snapshot) -> bool:
        return (
            snapshot.owner == self._OWNER
            and snapshot.source == "local"
            and snapshot.task_type in self._TASK_ACTIONS
        )

    def _reconcile_owned_orphans(self, site_id: str):
        repository = self.task_service.repository(site_id)
        active = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        owned_pids = {
            item.owner_pid
            for item in repository.list(statuses=active, limit=1000)
            if item.site_name == site_id and self._authorized_task(item) and item.owner_pid > 0
        }
        if not owned_pids:
            return []
        return repository.reconcile_orphaned_local_tasks(
            lambda pid: True if pid not in owned_pids else self.task_service._is_process_alive(pid)
        )

    def _cleanup_task_runtime(self, task_id: str) -> None:
        for directory, suffix in (
            (self.paths.runtime_cache_dir / "background_jobs", ".json"),
            (self.paths.runtime_cache_dir / "background_jobs", ".cancel"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json"),
            (self.paths.runtime_cache_dir / "export_jobs", ".json.tmp"),
        ):
            path = (directory / f"{task_id}{suffix}").resolve()
            try:
                if directory.resolve() in path.parents:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _result_summary(result: dict[str, object]) -> dict[str, object]:
        summary: dict[str, object] = {}
        for key in ("count", "row_count", "uses_trackside_plan", "offline_ap_stats"):
            value = result.get(key)
            if isinstance(value, (bool, int, float, str, dict)):
                summary[key] = value
        for key in ("rows", "overview_rows", "resources", "optical_rows", "offline_ap_ledger_rows"):
            value = result.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
        collection = result.get("collection")
        if isinstance(collection, dict):
            summary["collection"] = {
                key: collection[key]
                for key in (
                    "success",
                    "source",
                    "collect_run_uuid",
                    "fit_ap_resources_updated",
                    "unauthenticated_rows_updated",
                    "bbssid_rows_parsed",
                    "lldp_rows_parsed",
                    "failed_commands",
                    "summary_updated",
                    "https_port",
                    "https_port_persisted",
                    "target_ap_uuid",
                    "error_message",
                )
                if key in collection
            }
        return summary

    def _site(self, site_id: str) -> str:
        try:
            value = SiteManager(self.paths).validate_site_name(str(site_id or ""))
        except ValueError as exc:
            raise AcWebActionError("SITE_CONTEXT_INVALID", "局点标识无效") from exc
        root = self.paths.site_dir(value).resolve()
        try:
            root.relative_to(self.paths.sites_dir.resolve())
        except ValueError as exc:
            raise AcWebActionError("SITE_CONTEXT_INVALID", "局点目录不受控") from exc
        if not root.is_dir():
            raise AcWebActionError("SITE_CONTEXT_INVALID", "当前局点不存在")
        return value

    def _repository(self, site_id: str) -> AcRepository:
        site_id = self._site(site_id)
        return AcRepository(Database(self.paths.site_db_path(site_id)))

    def _action(self, action_id: str) -> tuple[str, tuple[str, ...]]:
        try:
            return ACTION_DEFINITIONS[action_id]
        except KeyError as exc:
            raise AcWebActionError("ACTION_NOT_ALLOWED", "AC 动作不在固定白名单") from exc

    def _target(self, site_id: str, target_id: str):
        target_id = str(target_id or "").strip()
        if not target_id:
            raise AcWebActionError("TARGET_REQUIRED", "AC 动作缺少目标")
        device = DeviceRepository(Database(self.paths.site_db_path(self._site(site_id)))).get_by_uuid(target_id)
        if device is None or str(device.device_type or "").upper() != "AC":
            raise AcWebActionError("TARGET_NOT_AUTHORIZED", "目标 AC 在当前局点不存在")
        return device

    def _revalidate_target(self, plan: dict[str, object]) -> None:
        current = self._target(str(plan["site_id"]), str(plan["target_id"]))
        if self._fingerprint(current) != plan.get("target_fingerprint"):
            raise AcWebActionError("TARGET_STALE", "目标 AC 已变化，请重新创建动作计划")

    def _plan_data(self, plan_id: str, site_id: str) -> dict[str, object]:
        path = self._plan_path(plan_id)
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在") from exc
        if not isinstance(plan, dict) or plan.get("plan_id") != plan_id:
            raise AcWebActionError("PLAN_TAMPERED", "动作计划内容无效")
        if plan.get("site_id") != site_id:
            raise AcWebActionError("PLAN_SITE_MISMATCH", "动作计划不属于当前局点")
        return plan

    def _validate_plan(self, plan: dict[str, object], digest: str, token: str) -> None:
        if float(plan["expires_at"]) <= time.time():
            raise AcWebActionError("PLAN_EXPIRED", "动作计划已过期")
        label, commands = self._action(str(plan["action_id"]))
        if str(plan.get("action_label") or "") != label or tuple(plan.get("commands") or ()) != commands:
            raise AcWebActionError("PLAN_TAMPERED", "动作计划命令不一致")
        expected = self._digest(
            str(plan["plan_id"]),
            str(plan["site_id"]),
            str(plan["target_id"]),
            str(plan["action_id"]),
            commands,
            dict(plan.get("target_fingerprint") or {}),
        )
        if not (
            hmac.compare_digest(str(plan.get("digest") or ""), expected)
            and hmac.compare_digest(expected, str(digest or ""))
            and hmac.compare_digest(str(plan.get("token") or ""), str(token or ""))
        ):
            raise AcWebActionError("PLAN_TAMPERED", "动作计划摘要或确认令牌无效")

    def _plan_path(self, plan_id: str) -> Path:
        if not _PLAN_ID.fullmatch(str(plan_id or "")):
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在")
        root = (self.paths.runtime_cache_dir / "ac_web_action_plans").resolve()
        path = (root / f"{plan_id}.json").resolve()
        if root not in path.parents:
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在")
        return path

    def _save_plan(self, plan: dict[str, object]) -> None:
        path = self._plan_path(str(plan["plan_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def _lock(cls, key: str) -> threading.RLock:
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _fingerprint(device) -> dict[str, str]:
        return {
            "device_uuid": str(device.device_uuid or ""),
            "name": str(device.name or ""),
            "system_name": str(device.system_name or ""),
            "primary_address": str(device.primary_address or ""),
            "device_type": str(device.device_type or ""),
            "updated_at": str(device.updated_at or ""),
        }

    @staticmethod
    def _digest(
        plan_id: str,
        site_id: str,
        target_id: str,
        action_id: str,
        commands: tuple[str, ...],
        fingerprint: dict[str, str],
    ) -> str:
        value = json.dumps(
            [plan_id, site_id, target_id, action_id, list(commands), fingerprint],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _plan_dto(plan: dict[str, object]) -> AcActionPlanDTO:
        return AcActionPlanDTO(
            plan_id=str(plan["plan_id"]),
            target_id=str(plan["target_id"]),
            action_id=str(plan["action_id"]),
            action_label=str(plan["action_label"]),
            plan_digest=str(plan["digest"]),
            confirm_token=str(plan["token"]),
            expires_at=float(plan["expires_at"]),
            status=str(plan["status"]),
            command_summary=[str(value) for value in plan["commands"]],
            task_id=str(plan.get("task_id") or ""),
        )

    @staticmethod
    def _extension_dto(row: dict[str, object | None]) -> AcExtensionDTO:
        return AcExtensionDTO(
            id=int(row.get("id") or 0),
            ap_name=str(row.get("ap_name") or ""),
            ap_mac_display=str(row.get("ap_mac_display") or ""),
            ap_mac_norm=str(row.get("ap_mac_norm") or ""),
            station_name=str(row.get("station_name") or ""),
            section_name=str(row.get("section_name") or ""),
            section_start_station=str(row.get("section_start_station") or ""),
            section_end_station=str(row.get("section_end_station") or ""),
            line_side=str(row.get("line_side") or ""),
            direction=str(row.get("direction") or ""),
            mileage_text=str(row.get("mileage_text") or ""),
            location_desc=str(row.get("location_desc") or ""),
            remark=str(row.get("remark") or ""),
            match_status=str(row.get("match_status") or "unmatched"),
            updated_at=str(row.get("updated_at") or ""),
        )

    @staticmethod
    def _apply_result(data: dict[str, object]) -> AcExtensionApplyResultDTO:
        created = int(data.get("created_count") or 0)
        updated = int(data.get("updated_count") or 0)
        skipped = int(data.get("skipped_count") or 0)
        operation_id = str(data.get("operation_id") or data.get("preview_id") or "")
        return AcExtensionApplyResultDTO(
            audit_id=operation_id,
            status=str(data.get("status") or "APPLIED"),
            preview_id=str(data.get("preview_id") or operation_id),
            total_rows=created + updated + skipped,
            success_rows=created + updated,
            updated_rows=updated,
            skipped_rows=skipped,
            error_rows=0,
        )

    @staticmethod
    def _import_error(exc: Exception) -> None:
        code = getattr(exc, "code", "IMPORT_INVALID")
        raise AcWebActionError(str(code), str(exc)) from exc


__all__ = ["ACTION_DEFINITIONS", "AcWebActionError", "AcWebApplicationService"]
