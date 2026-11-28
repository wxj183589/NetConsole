from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.models.device_detail import identify_device_platform
from netconsole.models.task_snapshot import utc_now_iso
from netconsole.models.task_state import TERMINAL_TASK_STATES
from netconsole.parsers.h3c.version_parser import parse_version
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.config_snapshot_repository import ConfigSnapshotRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.rail_infrastructure_repository import RailInfrastructureRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.command_template_library import CommandTemplateLibrary, SavedTemplateExecution
from netconsole.services.device_collection_support import resolve_device_collection_support
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    device_cli_output_is_unsupported,
)
from netconsole.services.device_scope import is_current_debug_device
from netconsole.services.config_collection_web_service import ConfigCollectionApplicationService
from netconsole.services.device_health_check_application_service import DeviceHealthCheckApplicationService
from netconsole.services.h3c_command_template import (
    CommandTemplatePreviewRequest,
    is_read_only_h3c_command,
    preview_command_template,
)
from netconsole.services.job_center.handlers.config_jobs import config_web_snapshot_fetch
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService, TaskResourceConflictError
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.netmiko_connection import (
    run_netmiko_with_retry,
    safe_send_command_with_paging,
    sanitize_sensitive_text,
)
from netconsole.services.site_manager import SiteManager


DEVICE_TASK_TYPE = "device_maintenance_collection"
DEVICE_TASK_OWNER = "web_device_task_center"
DeviceTaskKind = Literal["configuration", "backup", "diagnostic", "optical", "lldp", "version", "custom", "wireless", "mesh", "config_diff", "config_preview", "health"]
DEVICE_TASK_LABELS = {
    "configuration": "配置收集",
    "backup": "配置备份",
    "diagnostic": "诊断收集",
    "optical": "光衰收集",
    "lldp": "LLDP 收集",
    "version": "版本检查",
    "custom": "自定义命令采集",
    "wireless": "无线信息收集",
    "mesh": "MESH 收集",
    "config_diff": "配置快照差异",
    "config_preview": "已保存配置快照",
    "health": "设备健康检查",
}
_COMMANDS = {
    "diagnostic": ("display version", "display cpu-usage", "display memory", "display interface brief"),
    "lldp": ("display lldp neighbor-information list", "display lldp neighbor-information verbose"),
    "version": ("display version",),
}
_MAX_TARGETS = 64


class DeviceTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DeviceTaskKind
    device_uuids: list[str] = Field(default_factory=list, max_length=_MAX_TARGETS)
    group_id: int | Literal["all", "ungrouped"] | None = None
    organization_uid: str | None = Field(default=None, min_length=1, max_length=160)
    concurrency: int = Field(default=4, ge=1, le=8)
    command_timeout: int = Field(default=40, ge=5, le=120)
    template: CommandTemplatePreviewRequest | None = None
    saved_template: SavedTemplateExecution | None = None
    scheduled_at: AwareDatetime | None = None


class DeviceTaskReference(BaseModel):
    task_id: str
    run_id: str
    target_count: int
    scheduled_at: AwareDatetime | None = None


class DeviceTaskSchedule(BaseModel):
    task_id: str = Field(pattern=r"^device-scheduled-[0-9a-f]{32}$")
    scheduled_at: AwareDatetime
    request: DeviceTaskRequest
    commands: list[str] = Field(max_length=8)
    template_info: dict[str, object]
    status: Literal["WAITING", "SUBMITTED", "FAILED", "CANCELLED"] = "WAITING"
    error: str = ""


class DeviceTaskApplicationService:
    def __init__(self, task_service: TaskApplicationService, process_adapter: LocalProcessAdapter) -> None:
        self.task_service = task_service
        self.paths = task_service.paths
        self.process_adapter = process_adapter

    def template_library(self, site: str) -> CommandTemplateLibrary:
        return CommandTemplateLibrary(self.paths, site)

    def start(
        self, site: str, request: DeviceTaskRequest, *, retry_of_task_id: str = "",
    ) -> DeviceTaskReference:
        site = SiteManager(self.paths).validate_site_name(site)
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        ids = list(dict.fromkeys(request.device_uuids))
        if sum((bool(ids), request.group_id is not None, request.organization_uid is not None)) != 1:
            raise ValueError("请选择设备、分组或组织其中一项目标范围")
        if request.organization_uid is not None:
            organization = RailInfrastructureRepository(repository.database)
            facts = organization.read()
            if not facts.organization_initialized:
                raise ValueError("请先初始化组织结构")
            nodes = {node["uid"]: node for node in facts.nodes}
            if request.organization_uid not in nodes:
                raise ValueError("组织节点不存在")
            included = {request.organization_uid}
            for _ in range(len(nodes)):
                descendants = {uid for uid, node in nodes.items() if node.get("parent_uid") in included}
                expanded = included | descendants
                if expanded == included:
                    break
                included = expanded
            catalog = organization.organization_catalog(site)
            ids = [asset.device_uuid for asset in catalog.devices if included.intersection(asset.node_uids)]
        if request.group_id is not None:
            group = request.group_id
            if isinstance(group, int) and group < 1:
                raise ValueError("设备分组无效")
            group_filter = "__ungrouped__" if group == "ungrouped" else None if group == "all" else group
            ids = [str(device.device_uuid) for device in repository.list(group_filter=group_filter)]
        if not ids or len(ids) > _MAX_TARGETS:
            raise ValueError(f"每次任务请选择 1 至 {_MAX_TARGETS} 台设备")
        if set(ids) != repository.get_by_uuids(ids).keys():
            raise ValueError("目标设备已不存在或不属于当前局点")
        if request.kind in {"config_diff", "config_preview", "health"}:
            return self._start_existing_read_only_task(site, request, ids, repository.database)
        if request.template is not None and request.saved_template is not None:
            raise ValueError("请选择临时模板或已保存的模板")
        if (request.kind == "custom") != (request.template is not None or request.saved_template is not None):
            raise ValueError("只有自定义命令任务接受模板")
        template_info = {}
        commands = tuple(preview_command_template(request.template).commands) if request.template else ()
        if request.saved_template:
            record, preview = self.template_library(site).preview(request.saved_template)
            if preview.preview_digest != request.saved_template.preview_digest:
                raise ValueError("模板参数已更改，请重新预览")
            if preview.risk != "read_only":
                raise ValueError("当前设备任务仅执行只读模板")
            commands = tuple(preview.commands)
            template_info = {
                "template_id": record.template_id, "version": record.version,
                "device_roles": record.device_roles,
            }
        if request.scheduled_at is not None:
            if request.scheduled_at <= datetime.now(UTC):
                raise ValueError("请选择未来的执行时间")
            if request.kind == "custom" and not request.saved_template:
                raise ValueError("定时自定义任务仅支持已保存的只读模板")
            return self._save_schedule(site, request, ids, commands, template_info)
        return self._submit_resolved(site, request, ids, commands, template_info, retry_of_task_id)

    def _start_existing_read_only_task(
        self, site: str, request: DeviceTaskRequest, ids: list[str], database: Database,
    ) -> DeviceTaskReference:
        if request.scheduled_at or request.template or request.saved_template:
            raise ValueError("该任务仅支持立即执行，且不接受命令模板")
        if request.kind == "health":
            health = DeviceHealthCheckApplicationService(self.paths, self.task_service, process_adapter=self.process_adapter)
            task = health.start(ids, concurrency_limit=request.concurrency, site_name=site)
            return DeviceTaskReference(task_id=task.task_id, run_id=task.task_id, target_count=len(ids))
        if len(ids) != 1:
            raise ValueError("请选择一台设备查看配置快照")
        snapshots = ConfigSnapshotRepository(database, ensure_schema=False)
        config = ConfigCollectionApplicationService(self.paths, self.task_service, self.process_adapter)
        if request.kind == "config_diff":
            left = snapshots.list_for_device_page(ids[0], "saved", limit=1)
            right = snapshots.list_for_device_page(ids[0], "running", limit=1)
            if not left or not right:
                raise ValueError("该设备需要同时具有已保存和运行配置快照")
            task = config.submit_diff_export(site, left[0].id, right[0].id)
        else:
            saved = snapshots.list_for_device_page(ids[0], "saved", limit=1)
            if not saved:
                raise ValueError("该设备没有已保存配置快照")
            task = config.submit_snapshots_export(site, [saved[0].id])
        return DeviceTaskReference(task_id=task.id, run_id=task.id, target_count=1)

    def _submit_resolved(
        self, site: str, request: DeviceTaskRequest, ids: list[str],
        commands: tuple[str, ...], template_info: dict[str, object], retry_of_task_id: str,
        *, scheduled_id: str = "",
    ) -> DeviceTaskReference:
        if request.kind == "custom" and (
            not 1 <= len(commands) <= 8 or any(not is_read_only_h3c_command(command) for command in commands)
        ):
            raise ValueError("自定义采集只允许 1 至 8 条已登记的只读查询命令")
        task_id = scheduled_id or f"device-task-{uuid4().hex}"
        self.process_adapter.start_job(BackgroundJob(
            job_id=task_id,
            task_type=DEVICE_TASK_TYPE,
            params={
                "site_name": site,
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "owner": DEVICE_TASK_OWNER,
                "device": ids[0],
                "task_source": "local",
                "task_name": DEVICE_TASK_LABELS[request.kind],
                "device_uuids": ids,
                "kind": request.kind,
                "commands": list(commands),
                "template": template_info,
                "concurrency": request.concurrency,
                "command_timeout": request.command_timeout,
                "target_scope": {
                    "group_id": request.group_id, "organization_uid": request.organization_uid,
                },
            },
            trigger_source="scheduler" if scheduled_id else "retry" if retry_of_task_id else "ui",
            retry_of_task_id=retry_of_task_id,
        ))
        return DeviceTaskReference(task_id=task_id, run_id=task_id, target_count=len(ids))

    def _schedule_path(self, site: str) -> Path:
        library_path = self.template_library(site).repository.path
        path = library_path.with_name("device-task-schedules.json")
        root = library_path.parent.resolve()
        if not all(candidate.resolve().is_relative_to(root) for candidate in (
            path, path.with_name(f".{path.name}.lock"),
        )):
            raise ValueError("任务计划存储路径越出局点边界")
        return path

    @staticmethod
    def _read_schedules(path: Path) -> list[DeviceTaskSchedule]:
        try:
            with path.open("rb") as stream:
                payload = stream.read(1_000_001)
        except FileNotFoundError:
            return []
        if len(payload) > 1_000_000:
            raise ValueError("任务计划文件过大")
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("schedules"), list):
            raise ValueError("任务计划文件版本无效")
        return [DeviceTaskSchedule.model_validate(item) for item in data["schedules"]]

    @staticmethod
    def _write_schedules(path: Path, schedules: list[DeviceTaskSchedule]) -> None:
        payload = json.dumps({
            "schema": 1, "schedules": [schedule.model_dump(mode="json") for schedule in schedules],
        }, ensure_ascii=False).encode("utf-8")
        if len(payload) > 1_000_000:
            raise ValueError("任务计划文件过大")
        atomic_write_bytes(path, payload)

    def _save_schedule(
        self, site: str, request: DeviceTaskRequest, ids: list[str],
        commands: tuple[str, ...], template_info: dict[str, object],
    ) -> DeviceTaskReference:
        task_id = f"device-scheduled-{uuid4().hex}"
        assert request.scheduled_at is not None
        schedule = DeviceTaskSchedule(
            task_id=task_id, scheduled_at=request.scheduled_at,
            request=DeviceTaskRequest(
                kind=request.kind, device_uuids=ids, concurrency=request.concurrency,
                command_timeout=request.command_timeout,
            ),
            commands=list(commands), template_info=template_info,
        )
        path = self._schedule_path(site)
        with locked_file(path):
            records = self._read_schedules(path)
            if len(records) >= 100:
                raise ValueError("局点最多支持 100 项计划，请先移除已结束的计划")
            self._write_schedules(path, [*records, schedule])
        return DeviceTaskReference(
            task_id=task_id, run_id=task_id, target_count=len(ids), scheduled_at=schedule.scheduled_at,
        )

    def list_schedules(self, site: str) -> list[DeviceTaskSchedule]:
        return list(reversed(self._read_schedules(self._schedule_path(site))))

    def cancel_schedule(self, site: str, task_id: str) -> None:
        path = self._schedule_path(site)
        with locked_file(path):
            records = self._read_schedules(path)
            record = next((item for item in records if item.task_id == task_id), None)
            if record is None:
                raise KeyError(task_id)
            if record.status == "WAITING" and self.task_service.repository(site).get(task_id) is not None:
                raise ValueError("任务已启动，请在任务详情停止执行")
            if record.status == "WAITING":
                record.status = "CANCELLED"
            else:
                records.remove(record)
            self._write_schedules(path, records)

    def dispatch_schedules(self, site: str, *, now: datetime | None = None) -> None:
        path = self._schedule_path(site)
        if not path.is_file():
            return
        now = now or datetime.now(UTC)
        with locked_file(path):
            records = self._read_schedules(path)
            changed = False
            for record in records:
                if record.status != "WAITING" or record.scheduled_at > now:
                    continue
                try:
                    self._launch_schedule(site, record)
                except TaskResourceConflictError:
                    continue
                except (ValueError, KeyError) as exc:
                    record.status = "FAILED"
                    record.error = redact_web_task_text(str(exc))
                else:
                    record.status = "SUBMITTED"
                changed = True
            if changed:
                self._write_schedules(path, records)

    def _launch_schedule(self, site: str, record: DeviceTaskSchedule) -> None:
        if self.task_service.repository(site).get(record.task_id) is not None:
            return
        ids = record.request.device_uuids
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        if not ids or set(ids) != repository.get_by_uuids(ids).keys():
            raise ValueError("目标设备已不存在或不属于当前局点")
        if template_id := record.template_info.get("template_id"):
            versions = self.template_library(site).versions(str(template_id))
            if not versions or not versions[0].enabled:
                raise ValueError("模板已停用，不能启动计划")
        self._submit_resolved(
            site, record.request, ids, tuple(record.commands), record.template_info, "",
            scheduled_id=record.task_id,
        )

    def result(self, site: str, task_id: str) -> dict[str, object]:
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None or snapshot.task_type != DEVICE_TASK_TYPE or snapshot.owner != DEVICE_TASK_OWNER:
            raise KeyError(task_id)
        return dict(snapshot.result or {})

    def organizations(self, site: str) -> list[dict[str, str]]:
        facts = RailInfrastructureRepository(Database(self.paths.site_db_path(site))).read()
        if not facts.organization_initialized:
            return []
        return [
            {"uid": str(node["uid"]), "name": str(node["name"]), "parent_uid": str(node.get("parent_uid") or "")}
            for node in facts.nodes if node["kind"] != "section"
        ]

    def retry(self, site: str, task_id: str) -> DeviceTaskReference:
        site = SiteManager(self.paths).validate_site_name(site)
        snapshot = self.task_service.repository(site).get(task_id)
        if snapshot is None or snapshot.task_type != DEVICE_TASK_TYPE or snapshot.owner != DEVICE_TASK_OWNER:
            raise KeyError(task_id)
        if snapshot.status not in TERMINAL_TASK_STATES:
            raise ValueError("任务结束后才能重试失败设备")
        result = snapshot.result or {}
        kind = result.get("kind")
        ids = list(dict.fromkeys(
            str(item["device_uuid"]) for item in result.get("items", [])
            if item.get("device_uuid") and item.get("status") in {"failed", "partial"}
        ))
        if kind not in DEVICE_TASK_LABELS or not ids:
            raise ValueError("没有可重试的设备结果")
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        if set(ids) != repository.get_by_uuids(ids).keys():
            raise ValueError("目标设备已不存在或不属于当前局点")
        request = DeviceTaskRequest(
            kind=kind, device_uuids=ids,
            concurrency=int(result.get("concurrency") or 4),
            command_timeout=int(result.get("command_timeout") or 40),
        )
        template_info = dict(result.get("template") or {})
        if template_id := template_info.get("template_id"):
            versions = self.template_library(site).versions(str(template_id))
            if not versions or not versions[0].enabled:
                raise ValueError("模板已停用，不能重放历史实例")
        return self._submit_resolved(
            site, request, ids, tuple(result.get("commands", [])) if kind == "custom" else (),
            template_info, task_id,
        )


def run_device_maintenance_collection(context: JobContext) -> dict[str, object]:
    site = SiteManager(context.paths).validate_site_name(str(context.params["site_name"]))
    kind = str(context.params["kind"])
    if kind not in DEVICE_TASK_LABELS:
        raise ValueError("设备任务类型无效")
    commands = tuple(str(command) for command in context.params.get("commands", []))
    if kind == "custom":
        if not 1 <= len(commands) <= 8 or any(not is_read_only_h3c_command(command) for command in commands):
            raise ValueError("自定义采集命令未通过只读校验")
    else:
        commands = _COMMANDS.get(kind, ())
    database = Database(context.paths.site_db_path(site))
    devices = DeviceRepository(database)
    facts = DeviceFactRepository(database)
    ids = list(dict.fromkeys(context.params["device_uuids"]))
    concurrency = max(1, min(8, int(context.params.get("concurrency") or 4)))

    def collect(device_uuid: str) -> dict[str, object]:
        context.check_cancelled()
        device = devices.get_by_uuid(device_uuid)
        item = {"device_uuid": device_uuid, "started_at": utc_now_iso()}
        if device is None:
            return {**item, "status": "failed", "message": "设备不存在"}
        item["device_name"] = device.name
        if not is_current_debug_device(device):
            return {**item, "status": "skipped", "message": "当前设备不参与收集"}
        stored = facts.get_device_fact(device_uuid) or {}
        platform = identify_device_platform(
            vendor=device.vendor_key, device_type=device.device_type, software_version=stored.get("software_version"),
        )
        support = resolve_device_collection_support(
            device, DEVICE_INVENTORY_OPERATION_ID, platform_facts=platform, paths=context.paths,
        )
        if not support.supported or device.vendor_key != "h3c":
            return {**item, "status": "skipped", "message": support.reason_message or "当前任务仅支持 H3C 设备"}
        if kind in {"optical", "lldp"} and platform.role != "switch":
            return {**item, "status": "skipped", "message": "该采集面向交换机"}
        if kind in {"wireless", "mesh"} and platform.role != "wireless_controller":
            return {**item, "status": "skipped", "message": "无线与 MESH 采集需要 H3C 无线控制器，FIT-AP 独立采集尚未适配"}
        allowed_roles = context.params.get("template", {}).get("device_roles", [])
        if allowed_roles and platform.role not in allowed_roles:
            return {**item, "status": "skipped", "message": "设备类型不在模板适用范围内"}
        started = monotonic()
        try:
            result = _collect_device(context, site, kind, device, facts, commands)
            return {**item, **result, "elapsed_ms": round((monotonic() - started) * 1000)}
        except BackgroundTaskCancelled:
            raise
        except Exception as exc:
            context.check_cancelled()
            return {**item, "status": "failed", "message": redact_web_task_text(sanitize_sensitive_text(str(exc), device)),
                    "elapsed_ms": round((monotonic() - started) * 1000)}

    results: dict[str, dict[str, object]] = {}
    context.progress(kind, 0, len(ids), DEVICE_TASK_LABELS[kind])
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        pending = {executor.submit(collect, device_uuid): device_uuid for device_uuid in ids}
        while pending:
            context.check_cancelled()
            done, _remaining = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                device_uuid = pending.pop(future)
                result = {**future.result(), "finished_at": utc_now_iso()}
                results[device_uuid] = result
                context.structured_progress(
                    kind, len(results), len(ids), f"{DEVICE_TASK_LABELS[kind]} {len(results)}/{len(ids)}",
                    device_uuid=device_uuid, status=result["status"],
                )
    counts = {status: sum(item["status"] == status for item in results.values()) for status in ("success", "failed", "partial", "skipped")}
    if counts["success"] == len(ids):
        business_status = "SUCCESS"
    elif counts["success"] or counts["partial"]:
        business_status = "PARTIAL_SUCCESS"
    elif counts["failed"]:
        business_status = "FAILED"
    else:
        business_status = "NO_EFFECTIVE_TARGET"
    return {
        "task_id": context.job_id, "run_id": context.job_id, "kind": kind,
        "commands": list(commands) if kind == "custom" else [],
        "template": context.params.get("template", {}),
        "concurrency": concurrency,
        "command_timeout": int(context.params.get("command_timeout") or 40),
        "target_scope": context.params.get("target_scope", {}),
        "items": [results[device_uuid] for device_uuid in ids],
        "total": len(ids),
        "success": counts["success"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "partial": counts["partial"],
        "business_status": business_status,
        "warning_count": counts["partial"],
        "primary_failure_reason": next(
            (str(item["message"]) for item in results.values() if item["status"] == "failed" and item.get("message")),
            "",
        ),
    }


def _collect_device(
    context: JobContext, site: str, kind: str, device: Device,
    facts: DeviceFactRepository, commands: tuple[str, ...],
) -> dict[str, object]:
    if kind in {"wireless", "mesh"}:
        from netconsole.services.device_task_ac_collection import collect_ac_task

        return collect_ac_task(context, site, kind, device)
    if kind in {"configuration", "backup"}:
        child_context = replace(
            context,
            params={**context.params, "device_uuid": device.device_uuid},
            progress_callback=None,
        )
        output = config_web_snapshot_fetch(child_context)
        return {"status": "partial" if output.get("warning_message") else "success", **output}
    if kind == "optical":
        from netconsole.services.h3c_optical_refresh_service import refresh_h3c_device_optical

        output = refresh_h3c_device_optical(device, site, repository=facts, paths=context.paths)
        context.check_cancelled()
        records = [
            {key: row[key] for key in ("interface_name", "module_type", "rx_power_dbm", "tx_power_dbm", "collected_at") if key in row}
            for row in facts.list_optical_modules(str(device.device_uuid))
            if row.get("collect_run_uuid") == output.collect_run_uuid
        ] if output.success else []
        return {
            "status": "success" if output.success else "failed",
            "collect_run_uuid": output.collect_run_uuid,
            "records": records[:128],
            "record_count": len(records),
            "message": redact_web_task_text(sanitize_sensitive_text(output.error_message or "", device)),
        }

    def execute(connection, target):
        responses: dict[str, str] = {}
        for command in commands:
            context.check_cancelled()
            response = safe_send_command_with_paging(
                connection, command, encoding=target.encoding,
                command_timeout=max(5, min(120, int(context.params.get("command_timeout") or 40))),
                max_pages=32, max_output_bytes=128_000, cancel_check=context.should_cancel,
            ).output
            responses[command] = "" if device_cli_output_is_unsupported(device, response) else response.strip()
        return responses

    responses = run_netmiko_with_retry(device, execute, paths=context.paths, site_id=site)
    context.check_cancelled()
    if kind == "lldp":
        from netconsole.parsers.h3c.lldp_parser import parse_lldp_neighbors

        records = parse_lldp_neighbors(responses[commands[0]], responses[commands[1]])
        details = {"records": records[:128], "record_count": len(records)}
    else:
        details = {"command_results": [
            {"command": command, "status": "success" if response else "unavailable",
             "output": redact_web_task_text(sanitize_sensitive_text(response, device))[:4096]}
            for command, response in responses.items()
        ]}
        if kind in {"version", "diagnostic"}:
            version = parse_version(responses["display version"])
            details["software_version"] = version.get("software_version")
            details["device_model"] = version.get("model")
    completed = sum(bool(output) for output in responses.values())
    status = "success" if completed == len(responses) else "partial" if completed else "failed"
    return {"status": status, "collected_at": utc_now_iso(), **details}
