from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.ac_management import (
    AcActionPlanDTO,
    AcExtensionApplyResultDTO,
    AcExtensionPreviewDTO,
    AcExtensionRollbackResultDTO,
    AcTracksidePlanPageDTO,
    AcWebTaskDTO,
)
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.services.background_job import BackgroundJob
from netconsole.services.fit_ap_import_export import FitApImportExportService
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService


ACTION_DEFINITIONS = {
    "persist_auto_ap": ("固化新 AP", ("system-view", "wlan auto-ap persistent all", "save force", "return", "quit")),
    "save_config": ("save force", ("save force",)),
    "enable_ap_remote_login": ("开启 AP 远程登录", ("screen-length disable", "system-view", "probe", "wlan ap-execute all exec-console enable", "return", "quit")),
}


class AcWebActionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AcWebApplicationService:
    """AC Web 用例边界；设备动作在此阶段只提交 Fake Executor。"""

    def __init__(self, paths: PathResolver, task_service: TaskApplicationService) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = LocalProcessAdapter(task_service)
        self._plans: dict[str, dict[str, object]] = {}
        self._previews: dict[str, dict[str, object]] = {}
        self._extension_audits: dict[str, dict[str, object]] = {}

    def current_site_id(self, default: str = "demo") -> str:
        try:
            data = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            value = data.get("current_site") if isinstance(data, dict) else default
            return SiteManager(self.paths).validate_site_name(str(value or default))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return default

    def list_extensions(self, site_id: str, *, search: str = "", page: int = 1, page_size: int = 50):
        rows = AcRepository(Database(self.paths.site_db_path(site_id))).list_ap_extension_points(search=search)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 200))
        start = (page - 1) * page_size
        return {"items": rows[start : start + page_size], "total": len(rows), "page": page, "page_size": page_size}

    def list_trackside_plan(self, site_id: str, mode: str = TRACKSIDE_AP_PLAN_MODE) -> AcTracksidePlanPageDTO:
        rows = AcRepository(Database(self.paths.site_db_path(site_id))).list_trackside_ap_plan(mode)
        return AcTracksidePlanPageDTO(items=rows, total=len(rows), mode=mode)

    def start_refresh(self, site_id: str, task_type: str, *, ac_id: str, source: str = "auto", refresh_scope: str = "all") -> AcWebTaskDTO:
        allowed = {
            "ac_overview_refresh": "AC 在线概览刷新",
            "ac_fit_ap_resources_refresh": "FIT-AP 信息刷新",
            "ac_fit_ap_optical_refresh": "FIT-AP 光衰刷新",
            "trackside_ap_plan_refresh": "轨旁 AP 规划刷新",
            "ac_trackside_business_refresh": "轨旁 AP 业务刷新",
        }
        if task_type not in allowed:
            raise AcWebActionError("TASK_NOT_ALLOWED", "不支持的 AC Web 刷新任务")
        task_id = f"ac-web-{uuid4().hex}"
        params: dict[str, object] = {
            "site_name": site_id,
            "db_path": str(self.paths.site_db_path(site_id)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": allowed[task_type],
            "owner": "web_ac",
            "task_source": "local",
            "device_uuid": ac_id,
            "ac_uuid": ac_id,
            "source": source,
            "refresh_scope": refresh_scope,
            "mode": "collect" if task_type != "trackside_ap_plan_refresh" else TRACKSIDE_AP_PLAN_MODE,
        }
        job = BackgroundJob(job_id=task_id, task_type=task_type, params=params)
        self.process_adapter.start_job(job)
        snapshot = self.task_service.repository(site_id).get(task_id)
        return AcWebTaskDTO(task_id=task_id, task_type=task_type, status=snapshot.status.value if snapshot else "PENDING", message=allowed[task_type])

    def create_action_plan(self, site_id: str, target_id: str, action_id: str) -> AcActionPlanDTO:
        label, commands = self._action(action_id)
        target_id = str(target_id or "").strip()
        if not target_id:
            raise AcWebActionError("TARGET_REQUIRED", "AC 动作缺少目标")
        plan_id = f"ac-plan-{uuid4().hex}"
        digest = self._digest(plan_id, site_id, target_id, action_id, commands)
        plan = {
            "plan_id": plan_id,
            "site_id": site_id,
            "target_id": target_id,
            "action_id": action_id,
            "action_label": label,
            "commands": commands,
            "digest": digest,
            "token": secrets.token_urlsafe(24),
            "expires_at": time.time() + 300,
            "status": "PREVIEW",
            "task_id": "",
        }
        self._plans[plan_id] = plan
        return self._plan_dto(plan)

    def preview_action_plan(self, plan_id: str) -> AcActionPlanDTO:
        return self._plan(plan_id)

    def confirm_action_plan(self, plan_id: str, plan_digest: str, confirm_token: str) -> AcActionPlanDTO:
        plan = self._plan_data(plan_id)
        self._validate_plan(plan, plan_digest, confirm_token)
        if plan["status"] != "PREVIEW":
            raise AcWebActionError("PLAN_ALREADY_CONFIRMED", "计划已确认或已执行")
        plan["status"] = "CONFIRMED"
        return self._plan_dto(plan)

    def execute_action_plan(self, plan_id: str) -> AcActionPlanDTO:
        plan = self._plan_data(plan_id)
        if float(plan["expires_at"]) <= time.time():
            raise AcWebActionError("PLAN_EXPIRED", "动作计划已过期")
        if plan["status"] != "CONFIRMED":
            raise AcWebActionError("CONFIRMATION_REQUIRED", "执行前必须完成二次确认")
        label, _commands = self._action(str(plan["action_id"]))
        if str(plan["action_label"]) != label:
            raise AcWebActionError("PLAN_TAMPERED", "动作计划摘要不一致")
        self._revalidate_target(plan)
        expected_digest = self._digest(
            str(plan["plan_id"]),
            str(plan["site_id"]),
            str(plan["target_id"]),
            str(plan["action_id"]),
            tuple(str(value) for value in plan["commands"]),
        )
        if not hmac.compare_digest(str(plan["digest"]), expected_digest):
            raise AcWebActionError("PLAN_TAMPERED", "动作计划摘要不一致")
        task_id = f"ac-web-fake-action-{uuid4().hex}"
        self.task_service.create_external_task(
            task_id=task_id,
            task_type="ac_web_fake_action",
            task_name=f"Fake AC 动作 · {label}",
            source="local",
            site_name=str(plan["site_id"]),
            owner="web_ac_action",
            device=str(plan["target_id"]),
        )
        self.task_service.record_external_event(
            task_id,
            "state",
            {"state": "RUNNING", "stage": "fake_executor", "message": "Fake Executor 已接收固定 AC 动作"},
            site_name=str(plan["site_id"]),
        )
        self.task_service.record_external_event(
            task_id,
            "finished",
            {
                "message": "Fake AC 动作完成，未连接真实设备",
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
            site_name=str(plan["site_id"]),
        )
        plan["status"] = "COMPLETED"
        plan["task_id"] = task_id
        return self._plan_dto(plan)

    def action_audit(self, plan_id: str) -> dict[str, object]:
        plan = self._plan_data(plan_id)
        return {
            "plan_id": plan["plan_id"],
            "site_id": plan["site_id"],
            "target_id": plan["target_id"],
            "action_id": plan["action_id"],
            "plan_digest": plan["digest"],
            "status": plan["status"],
            "task_id": plan["task_id"],
            "executor": "FAKE",
            "audit": True,
        }

    def preview_extension(self, site_id: str, file_name: str, content: bytes, import_mode: str) -> AcExtensionPreviewDTO:
        suffix = Path(file_name or "").suffix.casefold()
        if suffix not in {".csv", ".xlsx"}:
            raise AcWebActionError("FILE_TYPE_INVALID", "仅支持 CSV/XLSX AP 扩展文件")
        upload_dir = self.paths.runtime_cache_dir / "ac_web_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / f"{uuid4().hex}{suffix}"
        path.write_bytes(content)
        try:
            preview = FitApImportExportService(AcRepository(Database(self.paths.site_db_path(site_id)))).preview_ap_extension_import(path, import_mode or "standard_template")
        finally:
            path.unlink(missing_ok=True)
        preview_id = f"ac-extension-preview-{uuid4().hex}"
        digest = hashlib.sha256(json.dumps(preview.standard_rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        self._previews[preview_id] = {"site_id": site_id, "preview": preview, "digest": digest, "expires_at": time.time() + 600, "before_rows": AcRepository(Database(self.paths.site_db_path(site_id))).list_ap_extension_points()}
        return AcExtensionPreviewDTO(preview_id=preview_id, file_name=preview.file_name, template_type=preview.template_type, confidence_score=preview.confidence_score, low_confidence=preview.low_confidence, summary=preview.summary, row_count=len(preview.standard_rows), preview_digest=digest)

    def apply_extension(self, site_id: str, preview_id: str, preview_digest: str, explicit_confirmation: bool) -> AcExtensionApplyResultDTO:
        if not explicit_confirmation:
            raise AcWebActionError("CONFIRMATION_REQUIRED", "AP 扩展写入需要显式确认")
        item = self._preview_data(preview_id, site_id, preview_digest)
        preview = item["preview"]
        stats = FitApImportExportService(AcRepository(Database(self.paths.site_db_path(site_id)))).commit_ap_extension_import(preview)
        audit_id = f"ac-extension-audit-{uuid4().hex}"
        item["status"] = "APPLIED"
        self._extension_audits[audit_id] = {"site_id": site_id, "before_rows": item["before_rows"], "status": "APPLIED", "preview_id": preview_id}
        return AcExtensionApplyResultDTO(audit_id=audit_id, status="APPLIED", preview_id=preview_id, **{key: int(stats.get(key) or 0) for key in ("total_rows", "success_rows", "updated_rows", "skipped_rows", "error_rows")})

    def rollback_extension(self, site_id: str, audit_id: str, explicit_confirmation: bool) -> AcExtensionRollbackResultDTO:
        if not explicit_confirmation:
            raise AcWebActionError("CONFIRMATION_REQUIRED", "回滚需要显式确认")
        audit = self._extension_audits.get(audit_id)
        if audit is None or audit["site_id"] != site_id:
            raise AcWebActionError("AUDIT_NOT_FOUND", "导入审计不存在")
        if audit["status"] != "APPLIED":
            raise AcWebActionError("ALREADY_ROLLED_BACK", "导入已回滚")
        repository = AcRepository(Database(self.paths.site_db_path(site_id)))
        before = [dict(row) for row in audit["before_rows"]]
        current = repository.list_ap_extension_points()
        before_ids = {int(row["id"]) for row in before if row.get("id") is not None}
        current_ids = [int(row["id"]) for row in current if row.get("id") is not None and int(row["id"]) not in before_ids]
        repository.delete_ap_extension_points(current_ids)
        for row in before:
            repository.upsert_ap_extension_point(row)
        audit["status"] = "ROLLED_BACK"
        return AcExtensionRollbackResultDTO(audit_id=audit_id, status="ROLLED_BACK", restored_rows=len(before))

    def _action(self, action_id: str) -> tuple[str, tuple[str, ...]]:
        try:
            return ACTION_DEFINITIONS[action_id]
        except KeyError as exc:
            raise AcWebActionError("ACTION_NOT_ALLOWED", "AC 动作不在固定白名单") from exc

    def _plan_data(self, plan_id: str) -> dict[str, object]:
        plan = self._plans.get(str(plan_id or ""))
        if plan is None:
            raise AcWebActionError("PLAN_NOT_FOUND", "动作计划不存在")
        return plan

    def _plan(self, plan_id: str) -> AcActionPlanDTO:
        plan = self._plan_data(plan_id)
        if float(plan["expires_at"]) <= time.time() and plan["status"] == "PREVIEW":
            plan["status"] = "EXPIRED"
        return self._plan_dto(plan)

    def _validate_plan(self, plan: dict[str, object], digest: str, token: str) -> None:
        if float(plan["expires_at"]) <= time.time():
            plan["status"] = "EXPIRED"
            raise AcWebActionError("PLAN_EXPIRED", "动作计划已过期")
        expected_digest = self._digest(
            str(plan["plan_id"]),
            str(plan["site_id"]),
            str(plan["target_id"]),
            str(plan["action_id"]),
            tuple(str(value) for value in plan["commands"]),
        )
        if (
            not hmac.compare_digest(str(plan["digest"]), expected_digest)
            or not hmac.compare_digest(str(plan["digest"]), str(digest or ""))
            or not hmac.compare_digest(str(plan["token"]), str(token or ""))
        ):
            raise AcWebActionError("PLAN_TAMPERED", "动作计划摘要或确认令牌无效")

    @staticmethod
    def _revalidate_target(plan: dict[str, object]) -> None:
        if not str(plan.get("site_id") or "").strip() or not str(plan.get("target_id") or "").strip():
            raise AcWebActionError("TARGET_NOT_AUTHORIZED", "执行前目标或站点校验失败")

    def _preview_data(self, preview_id: str, site_id: str, digest: str) -> dict[str, object]:
        item = self._previews.get(str(preview_id or ""))
        if item is None or item["site_id"] != site_id:
            raise AcWebActionError("PREVIEW_NOT_FOUND", "AP 扩展预览不存在")
        if float(item["expires_at"]) <= time.time():
            raise AcWebActionError("PREVIEW_EXPIRED", "AP 扩展预览已过期")
        if not hmac.compare_digest(str(item["digest"]), str(digest or "")):
            raise AcWebActionError("PREVIEW_TAMPERED", "AP 扩展预览摘要不一致")
        if item.get("status") == "APPLIED":
            raise AcWebActionError("PREVIEW_ALREADY_APPLIED", "AP 扩展预览已写入")
        return item

    @staticmethod
    def _digest(plan_id: str, site_id: str, target_id: str, action_id: str, commands: tuple[str, ...]) -> str:
        value = json.dumps([plan_id, site_id, target_id, action_id, list(commands)], ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _plan_dto(plan: dict[str, object]) -> AcActionPlanDTO:
        return AcActionPlanDTO(plan_id=str(plan["plan_id"]), site_id=str(plan["site_id"]), target_id=str(plan["target_id"]), action_id=str(plan["action_id"]), action_label=str(plan["action_label"]), plan_digest=str(plan["digest"]), confirm_token=str(plan["token"]), expires_at=float(plan["expires_at"]), status=str(plan["status"]), command_summary=[str(value) for value in plan["commands"]], task_id=str(plan.get("task_id") or ""))


__all__ = ["AcWebActionError", "AcWebApplicationService", "ACTION_DEFINITIONS"]
