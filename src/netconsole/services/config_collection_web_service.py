from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.config_collection import (
    ConfigConfirmationDTO,
    ConfigDirectoryDTO,
    ConfigDeviceDTO,
    ConfigDeviceGroupDTO,
    ConfigDevicePageDTO,
    ConfigSnapshotDTO,
    ConfigTaskReferenceDTO,
    ConfigTaskStatusDTO,
)
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot, utc_now_iso
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.config_snapshot_repository import ConfigSnapshot, ConfigSnapshotRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.config_collection_job_handlers import (
    CONFIG_WEB_EXPORT_DIFF_TASK,
    CONFIG_WEB_EXPORT_SNAPSHOTS_TASK,
    CONFIG_WEB_EXPORT_TASKS,
    CONFIG_WEB_SAVE_TASK,
    interrupted_irreversible_result,
    read_irreversible_checkpoint,
    remove_irreversible_checkpoint,
)
from netconsole.services.config_lifecycle_service import safe_artifact_display_name, safe_device_name
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService


CONFIG_COLLECTION_ACTIONS = {"fetch": "config_web_snapshot_fetch"}
CONFIG_WEB_OWNER = "web_config_collection"
ACTIVE_TASK_STATES = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
CONFIG_WEB_TASK_TYPES = frozenset(
    {
        "config_web_snapshot_fetch",
        "config_snapshot_load_content",
        "config_compare_latest_snapshots",
        "config_compare_latest_running_between_devices",
        "config_compare_snapshot_pair",
        "config_snapshot_delete_many",
        CONFIG_WEB_SAVE_TASK,
        *CONFIG_WEB_EXPORT_TASKS,
    }
)
CONFIG_WEB_COMPARE_TASK_TYPES = frozenset(
    {
        "config_compare_latest_snapshots",
        "config_compare_latest_running_between_devices",
        "config_compare_snapshot_pair",
    }
)
IRREVERSIBLE_CONFIG_TASK_TYPES = frozenset({"config_snapshot_delete_many", CONFIG_WEB_SAVE_TASK})
_SNAPSHOT_ARTIFACT_RE = re.compile(r"snapshot-(\d+)")
_DIFF_ARTIFACT_RE = re.compile(r"diff-([0-9A-Za-z_.-]+)")
_EXPORT_ARTIFACT_RE = re.compile(r"export-[0-9a-f]{32}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:file://[^\s\"']+|[a-z]:[\\/][^\s\"']+|\\\\[^\\/\s]+[\\/][^\s\"']+)")
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b((?:x-agent-token|authorization|token|password|credential|secret|community)\s*[:=]\s*(?:bearer\s+)?)\S+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


@dataclass(frozen=True)
class _ConfirmationRecord:
    action: str
    site_name: str
    object_ids: tuple[int, ...]
    digest: str
    summary: str
    action_plan: tuple[str, ...]
    expires_at: float


class ConfigCollectionApplicationService:
    """配置中心 Web 适配层；设备 IO 统一交给现有 Job Center Worker。"""

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        process_adapter: LocalProcessAdapter | None = None,
        desktop_action_service: object | None = None,
        confirmation_ttl_seconds: int = 300,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self.desktop_action_service = desktop_action_service
        self._confirmation_ttl_seconds = max(1, min(int(confirmation_ttl_seconds), 900))
        self._confirmations: dict[str, _ConfirmationRecord] = {}
        self._start_lock = RLock()
        self._irreversible_finalize_lock = RLock()

    def close(self) -> None:
        self.process_adapter.shutdown()

    def current_site_id(self) -> str:
        try:
            payload = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            value = payload.get("current_site") if isinstance(payload, dict) else "demo"
            return SiteManager(self.paths).validate_site_name(str(value or "demo"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return "demo"

    def list_devices(
        self,
        site_name: str,
        *,
        search: str = "",
        group_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> ConfigDevicePageDTO:
        database = self._database(site_name)
        if not database.path.is_file():
            return ConfigDevicePageDTO(page=page, page_size=page_size)
        devices = DeviceRepository(database).list(
            search=str(search or "").strip() or None,
            vendor="H3C",
            group_filter=self._group_filter(group_filter),
        )
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        total = len(devices)
        total_pages = max(1, (total + size - 1) // size)
        current_page = min(current_page, total_pages)
        start = (current_page - 1) * size
        groups = self._groups(database, site_name)
        return ConfigDevicePageDTO(
            items=[self._device_dto(device) for device in devices[start : start + size]],
            total=total,
            page=current_page,
            page_size=size,
            total_pages=total_pages,
            groups=groups,
        )

    def list_snapshots(self, site_name: str, device_id: int, snapshot_type: str = "") -> list[ConfigSnapshotDTO]:
        device, _repository, service = self._device_context(site_name, device_id)
        snapshots = service.list_device_snapshots(device, str(snapshot_type or "").strip() or None)
        return [
            self._snapshot_dto(site_name, device, snapshot, self._snapshot_path(site_name, snapshot))
            for snapshot in snapshots
            if self._safe_snapshot_path(site_name, snapshot) is not None
        ]

    def submit_collection(self, site_name: str, action: str, device_ids: list[int]) -> list[ConfigTaskReferenceDTO]:
        task_type = CONFIG_COLLECTION_ACTIONS.get(str(action or "").strip().lower())
        if task_type is None:
            raise ValueError("不支持的配置操作")
        if not device_ids or len(device_ids) > 50:
            raise ValueError("一次最多选择 50 台设备")
        database = self._database(site_name)
        repository = DeviceRepository(database)
        devices = [self._h3c_device(repository, int(device_id)) for device_id in dict.fromkeys(device_ids)]
        return [self._start_device_job(site_name, task_type, device) for device in devices]

    def submit_snapshot_content(self, site_name: str, snapshot_id: int) -> ConfigTaskReferenceDTO:
        self._snapshot_context(site_name, snapshot_id)
        return self._start_job(
            site_name,
            "config_snapshot_load_content",
            {"snapshot_id": int(snapshot_id), "max_chars": 2_000_000},
            "读取配置快照",
        )

    def submit_latest_diff(self, site_name: str, device_id: int) -> ConfigTaskReferenceDTO:
        database = self._database(site_name)
        device = self._h3c_device(DeviceRepository(database), device_id)
        return self._start_job(
            site_name,
            "config_compare_latest_snapshots",
            {"device_uuid": str(device.device_uuid or "")},
            f"比较配置 · {device.name or device.device_uuid}",
        )

    def submit_snapshot_diff(self, site_name: str, left_snapshot_id: int, right_snapshot_id: int) -> ConfigTaskReferenceDTO:
        self._snapshot_context(site_name, left_snapshot_id)
        self._snapshot_context(site_name, right_snapshot_id)
        return self._start_job(
            site_name,
            "config_compare_snapshot_pair",
            {"left_snapshot_id": int(left_snapshot_id), "right_snapshot_id": int(right_snapshot_id)},
            "比较配置快照",
        )

    def submit_device_diff(self, site_name: str, left_device_id: int, right_device_id: int) -> ConfigTaskReferenceDTO:
        database = self._database(site_name)
        repository = DeviceRepository(database)
        left = self._h3c_device(repository, left_device_id)
        right = self._h3c_device(repository, right_device_id)
        return self._start_job(
            site_name,
            "config_compare_latest_running_between_devices",
            {"device_uuid_a": str(left.device_uuid or ""), "device_uuid_b": str(right.device_uuid or "")},
            f"比较设备 · {left.name} / {right.name}",
        )

    def issue_snapshot_delete(self, site_name: str, snapshot_ids: list[int]) -> ConfigConfirmationDTO:
        ids = list(dict.fromkeys(int(value) for value in snapshot_ids))
        if not ids or len(ids) > 50:
            raise ValueError("一次最多删除 50 个配置快照")
        snapshots = [self._snapshot_context(site_name, snapshot_id)[0] for snapshot_id in ids]
        summary = f"删除 {len(ids)} 个配置快照（{', '.join(snapshot.type for snapshot in snapshots)}）"
        return self._issue_confirmation("delete_snapshots", site_name, ids, summary)

    def confirm_snapshot_delete(
        self,
        site_name: str,
        confirmation_token: str,
        digest: str,
    ) -> ConfigTaskReferenceDTO:
        record = self._consume_confirmation("delete_snapshots", site_name, confirmation_token, digest)
        return self._start_job(
            site_name,
            "config_snapshot_delete_many",
            {"snapshot_ids": list(record.object_ids)},
            "删除配置快照",
        )

    def preview_save_force(self, site_name: str, device_ids: list[int]) -> ConfigConfirmationDTO:
        ids = list(dict.fromkeys(int(value) for value in device_ids))
        if not ids or len(ids) > 50:
            raise ValueError("一次最多保存 50 台设备配置")
        repository = DeviceRepository(self._database(site_name))
        devices = [self._h3c_device(repository, device_id) for device_id in ids]
        summary = f"保存 {len(devices)} 台设备配置：{', '.join(str(device.name or device.device_uuid) for device in devices)}"
        return self._issue_confirmation(
            "save_force",
            site_name,
            ids,
            summary,
            ("固定执行 save force", "仅写入命令审计，不采集或伪造 saved-configuration 快照"),
        )

    def confirm_save_force(
        self,
        site_name: str,
        confirmation_token: str,
        digest: str,
    ) -> ConfigTaskReferenceDTO:
        record = self._consume_confirmation("save_force", site_name, confirmation_token, digest)
        repository = DeviceRepository(self._database(site_name))
        devices = [self._h3c_device(repository, device_id) for device_id in record.object_ids]
        return self._start_job(
            site_name,
            CONFIG_WEB_SAVE_TASK,
            {"device_uuids": [str(device.device_uuid or "") for device in devices]},
            "保存设备配置",
        )

    def submit_diff_export(
        self,
        site_name: str,
        left_snapshot_id: int,
        right_snapshot_id: int,
    ) -> ConfigTaskReferenceDTO:
        self._snapshot_context(site_name, left_snapshot_id)
        self._snapshot_context(site_name, right_snapshot_id)
        return self._start_job(
            site_name,
            CONFIG_WEB_EXPORT_DIFF_TASK,
            {"left_snapshot_id": int(left_snapshot_id), "right_snapshot_id": int(right_snapshot_id)},
            "导出配置差异",
        )

    def submit_snapshots_export(self, site_name: str, snapshot_ids: list[int]) -> ConfigTaskReferenceDTO:
        ids = list(dict.fromkeys(int(value) for value in snapshot_ids))
        if not ids or len(ids) > 200:
            raise ValueError("一次最多导出 200 个配置快照")
        for snapshot_id in ids:
            self._snapshot_context(site_name, snapshot_id)
        return self._start_job(
            site_name,
            CONFIG_WEB_EXPORT_SNAPSHOTS_TASK,
            {"snapshot_ids": ids},
            "批量导出配置快照",
        )

    def cancel_task(self, site_name: str, task_id: str) -> ConfigTaskStatusDTO | None:
        task = self.task_service.repository(site_name).get(str(task_id or ""))
        if not self._is_web_task(task, site_name):
            return None
        if task.status not in ACTIVE_TASK_STATES:
            return self._task_dto(task, site_name=site_name)
        if task.status is TaskState.STOPPING:
            return self._task_dto(task, site_name=site_name)
        cancellable, reason = self.cancel_capability(site_name, task.task_id)
        if not cancellable:
            raise ValueError(reason)
        cancel = getattr(self.process_adapter, "cancel_job", None)
        assert callable(cancel)
        try:
            accepted = cancel(task.task_id)
        except Exception as exc:
            raise ValueError("配置任务取消接收端调用失败") from exc
        if accepted is not True:
            raise ValueError("配置任务取消接收端未接受请求")
        updated = self.task_service.repository(site_name).get(task.task_id)
        if updated is None or updated.status not in {TaskState.STOPPING, TaskState.CANCELLED}:
            raise ValueError("配置任务 owner 未确认停止请求")
        return self._task_dto(updated, site_name=site_name)

    def cancel_capability(self, site_name: str, task_id: str) -> tuple[bool, str]:
        task = self.task_service.repository(site_name).get(str(task_id or ""))
        if not self._is_web_task(task, site_name):
            return False, "配置任务不存在或归属不匹配"
        if task.status in TERMINAL_TASK_STATES:
            return False, "任务已结束"
        if task.status is TaskState.STOPPING:
            return False, "已请求停止，等待配置任务 owner 收口"
        is_running = getattr(self.process_adapter, "is_running", None)
        if not callable(is_running):
            return False, "配置任务没有受管取消接收端"
        try:
            receiver_active = is_running(task.task_id) is True
        except Exception:
            return False, "配置任务取消接收端状态检查失败"
        if not receiver_active:
            return False, "配置任务已失去受管取消接收端"
        if task.task_type in IRREVERSIBLE_CONFIG_TASK_TYPES and task.status is TaskState.RUNNING:
            checkpoint = read_irreversible_checkpoint(self.paths, task.task_id)
            if checkpoint is not None:
                if task.task_type == CONFIG_WEB_SAVE_TASK:
                    return False, "强制保存已进入不可安全中断阶段"
                return False, "快照删除已进入不可安全中断阶段"
        return True, ""

    def directory_info(self, site_name: str, directory_kind: str) -> ConfigDirectoryDTO:
        kind = str(directory_kind or "").strip()
        if kind not in {"config_snapshots", "config_exports"}:
            raise ValueError("结果目录类型无效")
        target_id = f"{kind}:{site_name}"
        action = self.desktop_action_service
        if action is None:
            return ConfigDirectoryDTO(
                directory_kind=kind,
                target_id=target_id,
                code="desktop_action_unavailable",
                message="当前运行模式未注入 DesktopActionService，已拒绝打开目录。",
            )
        result = action.open_controlled_directory(target_id)  # type: ignore[attr-defined]
        return ConfigDirectoryDTO(
            directory_kind=kind,
            target_id=target_id,
            success=bool(getattr(result, "success", False)),
            code=str(getattr(result, "code", "desktop_action_failed")),
            message=str(getattr(result, "message", "DesktopAction 执行失败")),
        )

    def list_tasks(self, site_name: str, limit: int = 100) -> list[ConfigTaskStatusDTO]:
        selected_limit = max(1, min(int(limit), 200))
        return [
            self._task_dto(self._recover_irreversible_snapshot(site_name, snapshot), site_name=site_name)
            for snapshot in self._scan_tasks(site_name, selected_limit)
        ]

    def get_task(self, site_name: str, task_id: str, diff_filter: str = "all") -> ConfigTaskStatusDTO | None:
        snapshot = self.task_service.repository(site_name).get(str(task_id))
        if not self._is_web_task(snapshot, site_name):
            return None
        snapshot = self._recover_irreversible_snapshot(site_name, snapshot)
        return self._task_dto(snapshot, diff_filter=diff_filter, site_name=site_name)

    def open_artifact(self, site_name: str, artifact_id: str) -> tuple[Path, str]:
        value = str(artifact_id or "")
        snapshot_match = _SNAPSHOT_ARTIFACT_RE.fullmatch(value)
        if snapshot_match:
            snapshot_id = int(snapshot_match.group(1))
            snapshot = self._snapshot_context(site_name, snapshot_id)[0]
            path = self._safe_snapshot_path(site_name, snapshot)
            if path is None:
                raise FileNotFoundError("配置快照不存在")
            name = f"{safe_device_name(str(snapshot.device_uuid or 'device'))}_{snapshot.type}_{snapshot.timestamp}"
            return path, f"{name}{'.diff' if snapshot.type == 'diff' else '.txt'}"
        diff_match = _DIFF_ARTIFACT_RE.fullmatch(value)
        if diff_match:
            task_id = diff_match.group(1)
            task = self.task_service.repository(site_name).get(task_id)
            if task is None:
                raise FileNotFoundError("配置差异 Artifact 不存在")
            if not self._is_web_task(task, site_name) or task.task_type not in CONFIG_WEB_COMPARE_TASK_TYPES:
                raise FileNotFoundError("配置差异 Artifact 不存在")
            if task.status is not TaskState.COMPLETED:
                raise FileNotFoundError("配置差异 Artifact 不存在")
            path = self._safe_diff_path(task)
            if path is None:
                raise FileNotFoundError("配置差异 Artifact 不存在")
            return path, f"config_diff_{task.task_id}.diff"
        if _EXPORT_ARTIFACT_RE.fullmatch(value):
            return self._open_export_artifact(site_name, value)
        raise FileNotFoundError("Artifact 不存在或不属于当前局点")

    def _start_device_job(self, site_name: str, task_type: str, device: Device) -> ConfigTaskReferenceDTO:
        device_uuid = str(device.device_uuid or "")
        with self._start_lock:
            active = next(
                (
                    task
                    for task in self.task_service.repository(site_name).list_filtered(
                        statuses=ACTIVE_TASK_STATES,
                        owner=CONFIG_WEB_OWNER,
                        source="local",
                        site_name=site_name,
                        task_types={task_type},
                        device=device_uuid,
                        limit=1,
                    )
                    if self._is_web_task(task, site_name)
                ),
                None,
            )
            if active is not None:
                return self._task_dto(active, site_name=site_name)
            return self._start_job(
                site_name,
                task_type,
                {"device_uuid": device_uuid},
                f"配置采集 · {device.name or device.device_uuid}",
                device=device,
            )

    def _start_job(
        self,
        site_name: str,
        task_type: str,
        extra_params: dict[str, object],
        task_name: str,
        *,
        device: Device | None = None,
    ) -> ConfigTaskReferenceDTO:
        task_id = f"config-web-{uuid4().hex}"
        params: dict[str, object] = {
            "site_name": site_name,
            "db_path": str(self.paths.site_db_path(site_name)),
            "app_root": str(self.paths.app_root),
            "data_root": str(self.paths.data_root),
            "task_name": task_name,
            "owner": CONFIG_WEB_OWNER,
            "task_source": "local",
            "_emit_log_events": True,
            "_cancel_grace_ms": 3_000,
            **extra_params,
        }
        if device is not None:
            params.update(
                {
                    "device": str(device.device_uuid or ""),
                    "device_name": str(device.name or ""),
                    "device_id": str(device.id or ""),
                }
            )
        job = BackgroundJob(job_id=task_id, task_type=task_type, params=params)
        on_complete = None
        if task_type in IRREVERSIBLE_CONFIG_TASK_TYPES:
            def on_complete(_completion) -> None:
                self._finalize_irreversible_task(site_name, task_id)

        self.process_adapter.start_job(job, on_complete=on_complete)
        snapshot = self.task_service.repository(site_name).get(task_id)
        if snapshot is None:
            raise RuntimeError("配置任务创建后未写入任务中心")
        return self._task_dto(snapshot, site_name=site_name)

    def _finalize_irreversible_task(self, site_name: str, task_id: str) -> None:
        with self._irreversible_finalize_lock:
            checkpoint = read_irreversible_checkpoint(self.paths, task_id)
            if checkpoint is None:
                return
            repository = self.task_service.repository(site_name)
            snapshot = repository.get(task_id)
            if not self._is_web_task(snapshot, site_name) or snapshot.task_type not in IRREVERSIBLE_CONFIG_TASK_TYPES:
                return
            if checkpoint.get("site_name") != site_name or checkpoint.get("task_type") != snapshot.task_type:
                return
            checkpoint_status = str(checkpoint.get("status") or "running")
            if snapshot.status is TaskState.COMPLETED and snapshot.result:
                remove_irreversible_checkpoint(self.paths, task_id)
                return
            if snapshot.status not in TERMINAL_TASK_STATES:
                return

            result = (
                dict(checkpoint.get("result") or {})
                if checkpoint_status == "completed"
                else interrupted_irreversible_result(checkpoint)
            )
            all_failed = bool(result.get("total")) and int(result.get("failed") or 0) >= int(result["total"])
            recovered_complete = checkpoint_status == "completed" and not all_failed
            final_status = (
                TaskState.CANCELLED
                if snapshot.status is TaskState.CANCELLED
                else TaskState.COMPLETED if recovered_complete else snapshot.status
            )
            if all_failed and snapshot.status is not TaskState.CANCELLED:
                final_status = TaskState.FAILED
            if recovered_complete:
                message = "不可逆批次已执行完成，终态由检查点恢复"
            elif checkpoint_status == "completed":
                message = "不可逆批次已执行完成，但全部项目失败"
            else:
                message = "不可逆批次被宿主中断，已保留结构化执行结果"
            now = utc_now_iso()
            updated = TaskSnapshot(
                **{
                    **asdict(snapshot),
                    "status": final_status,
                    "finished_time": snapshot.finished_time or now,
                    "updated_time": now,
                    "progress": 100 if recovered_complete else snapshot.progress,
                    "message": message,
                    "error_message": "" if recovered_complete else snapshot.error_message,
                    "result": result,
                }
            )
            event = TaskEvent(
                event_id=f"config-irreversible-recovery-{task_id}",
                task_id=task_id,
                type="recovery",
                time=now,
                source="recovery",
                payload={
                    "message": message,
                    "state": final_status.value,
                    "result": result,
                },
            )
            if repository.record_once(updated, event, allowed_from={snapshot.status}):
                self.task_service.events.publish_persisted(event.to_dict())
            remove_irreversible_checkpoint(self.paths, task_id)

    def _recover_irreversible_snapshot(self, site_name: str, snapshot: TaskSnapshot) -> TaskSnapshot:
        if (
            snapshot.task_type in IRREVERSIBLE_CONFIG_TASK_TYPES
            and snapshot.status in TERMINAL_TASK_STATES
        ):
            self._finalize_irreversible_task(site_name, snapshot.task_id)
            return self.task_service.repository(site_name).get(snapshot.task_id) or snapshot
        return snapshot

    def _issue_confirmation(
        self,
        action: str,
        site_name: str,
        object_ids: list[int],
        summary: str,
        action_plan: tuple[str, ...] = (),
    ) -> ConfigConfirmationDTO:
        now = time.time()
        expires_at = now + self._confirmation_ttl_seconds
        payload = {
            "action": action,
            "site_name": site_name,
            "object_ids": object_ids,
            "summary": summary,
            "action_plan": list(action_plan),
            "expires_at": int(expires_at),
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        token = secrets.token_urlsafe(32)
        record = _ConfirmationRecord(
            action=action,
            site_name=site_name,
            object_ids=tuple(object_ids),
            digest=digest,
            summary=summary,
            action_plan=action_plan,
            expires_at=expires_at,
        )
        with self._start_lock:
            self._purge_expired_confirmations(now)
            self._confirmations[token] = record
        app_logger.log_info(
            "CONFIG_WEB_CONFIRMATION_ISSUED",
            f"action={action} site={site_name} count={len(object_ids)} digest={digest}",
        )
        return ConfigConfirmationDTO(
            action=action,
            confirmation_token=token,
            digest=digest,
            summary=summary,
            expires_at=datetime.fromtimestamp(expires_at, timezone.utc).isoformat(timespec="seconds"),
            snapshot_ids=object_ids if action == "delete_snapshots" else [],
            device_ids=object_ids if action == "save_force" else [],
            action_plan=list(action_plan),
        )

    def _consume_confirmation(
        self,
        action: str,
        site_name: str,
        confirmation_token: str,
        digest: str,
    ) -> _ConfirmationRecord:
        now = time.time()
        with self._start_lock:
            self._purge_expired_confirmations(now)
            record = self._confirmations.get(str(confirmation_token or ""))
            if record is None:
                raise ValueError("确认令牌无效、已过期或已使用")
            if (
                record.action != action
                or record.site_name != site_name
                or not hmac.compare_digest(record.digest, str(digest or ""))
            ):
                raise ValueError("确认内容已变化，请重新预览")
            self._confirmations.pop(confirmation_token, None)
        app_logger.log_info(
            "CONFIG_WEB_CONFIRMATION_CONSUMED",
            f"action={action} site={site_name} count={len(record.object_ids)} digest={record.digest}",
        )
        return record

    def _purge_expired_confirmations(self, now: float) -> None:
        for token in [key for key, value in self._confirmations.items() if value.expires_at <= now]:
            self._confirmations.pop(token, None)

    def _scan_tasks(self, site_name: str, limit: int) -> list[TaskSnapshot]:
        repository = self.task_service.repository(site_name)
        filters = {
            "owner": CONFIG_WEB_OWNER,
            "source": "local",
            "site_name": site_name,
            "task_types": CONFIG_WEB_TASK_TYPES,
        }
        page_size = 1000
        active: list[TaskSnapshot] = []
        offset = 0
        while True:
            page = repository.list_filtered(
                statuses=ACTIVE_TASK_STATES,
                limit=page_size,
                offset=offset,
                **filters,
            )
            active.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        history_limit = max(0, limit - len(active))
        if history_limit == 0:
            return active
        history = repository.list_filtered(
            statuses=TERMINAL_TASK_STATES,
            limit=history_limit,
            **filters,
        )
        return active + history

    def _safe_diff_path(self, task: TaskSnapshot) -> Path | None:
        raw_path = str(task.result.get("diff_file") or "")
        path = Path(raw_path)
        root = (self.paths.runtime_cache_dir / "config_diff").resolve()
        if path.is_symlink():
            return None
        resolved = path.resolve()
        if root not in resolved.parents or not resolved.is_file() or resolved.is_symlink():
            return None
        return resolved

    def _open_export_artifact(self, site_name: str, artifact_id: str) -> tuple[Path, str]:
        root = (self.paths.config_center_root(site_name) / "outputs").resolve()
        manifest_path = root / f"{artifact_id}.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise FileNotFoundError("配置导出 Artifact 不存在")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise FileNotFoundError("配置导出 Artifact 不存在") from exc
        if not isinstance(manifest, dict) or any(
            (
                manifest.get("artifact_id") != artifact_id,
                manifest.get("site_name") != site_name,
                manifest.get("owner") != CONFIG_WEB_OWNER,
                manifest.get("source") != "local",
                manifest.get("task_type") not in CONFIG_WEB_EXPORT_TASKS,
                manifest.get("status") != TaskState.COMPLETED.value,
            )
        ):
            raise FileNotFoundError("配置导出 Artifact 不存在")
        task = self.task_service.repository(site_name).get(str(manifest.get("task_id") or ""))
        if (
            not self._is_web_task(task, site_name)
            or task is None
            or task.task_type not in CONFIG_WEB_EXPORT_TASKS
            or task.status is not TaskState.COMPLETED
            or task.result.get("artifact_id") != artifact_id
        ):
            raise FileNotFoundError("配置导出 Artifact 不存在")
        try:
            manifest_size = int(manifest.get("size_bytes"))
            task_size = int(task.result.get("size"))
        except (TypeError, ValueError) as exc:
            raise FileNotFoundError("配置导出 Artifact 校验失败") from exc
        task_hash = str(task.result.get("hash") or "")
        task_display_name = str(task.result.get("display_name") or "")
        if any(
            (
                manifest.get("task_type") != task.task_type,
                manifest.get("sha256") != task_hash,
                manifest_size != task_size,
                manifest.get("display_name") != task_display_name,
                _SHA256_RE.fullmatch(task_hash) is None,
                task_size < 0,
                not task_display_name,
            )
        ):
            raise FileNotFoundError("配置导出 Artifact 校验失败")
        physical_name = str(manifest.get("physical_name") or "")
        path = root / physical_name
        resolved = path.resolve()
        expected_suffix = ".diff" if task.task_type == CONFIG_WEB_EXPORT_DIFF_TASK else ".zip"
        if (
            path.name != physical_name
            or path.is_symlink()
            or root not in resolved.parents
            or not resolved.is_file()
            or resolved.stem != artifact_id
            or resolved.suffix != expected_suffix
            or resolved.stat().st_size != manifest_size
            or _sha256_file(resolved) != task_hash
        ):
            raise FileNotFoundError("配置导出 Artifact 校验失败")
        display_name = safe_artifact_display_name(task_display_name, expected_suffix)
        if not display_name:
            raise FileNotFoundError("配置导出 Artifact 显示名无效")
        return resolved, display_name

    def _device_context(self, site_name: str, device_id: int):
        database = self._database(site_name)
        device = self._h3c_device(DeviceRepository(database), device_id)
        repository = ConfigSnapshotRepository(database, ensure_schema=False)
        from netconsole.services.config_lifecycle_service import ConfigLifecycleService

        return device, repository, ConfigLifecycleService(site_name, database, self.paths, repository)

    def _snapshot_context(self, site_name: str, snapshot_id: int) -> tuple[ConfigSnapshot, ConfigSnapshotRepository, Path]:
        database = self._database(site_name)
        repository = ConfigSnapshotRepository(database, ensure_schema=False)
        snapshot = repository.get(int(snapshot_id))
        path = self._safe_snapshot_path(site_name, snapshot)
        if path is None:
            raise FileNotFoundError("配置快照不存在")
        return snapshot, repository, path

    def _database(self, site_name: str) -> Database:
        site = SiteManager(self.paths).validate_site_name(site_name)
        return Database(self.paths.site_db_path(site))

    @staticmethod
    def _h3c_device(repository: DeviceRepository, device_id: int) -> Device:
        try:
            device = repository.get(int(device_id))
        except KeyError as exc:
            raise FileNotFoundError("设备不存在") from exc
        if str(device.device_vendor or "").upper() != "H3C":
            raise ValueError("配置中心仅支持 H3C 设备")
        return device

    @staticmethod
    def _group_filter(value: str) -> int | str | None:
        text = str(value or "").strip()
        if not text or text == "__all_groups__":
            return None
        if text == "__ungrouped__":
            return text
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError("设备分组筛选无效") from exc

    @staticmethod
    def _device_dto(device: Device) -> ConfigDeviceDTO:
        return ConfigDeviceDTO(
            id=int(device.id or 0),
            device_uuid=str(device.device_uuid or ""),
            name=str(device.name or ""),
            system_name=str(device.system_name or ""),
            device_type=str(device.device_type or ""),
            station=str(device.station or ""),
            group_id=int(device.group_id) if device.group_id is not None else None,
        )

    def _groups(self, database: Database, site_name: str) -> list[ConfigDeviceGroupDTO]:
        repository = DeviceGroupRepository(database, site_name)
        counts = repository.counts()
        return [
            ConfigDeviceGroupDTO(id=int(group.id or 0), name=str(group.name), device_count=counts.get(int(group.id or 0), 0))
            for group in repository.list()
            if group.id is not None
        ]

    def _snapshot_dto(self, site_name: str, device: Device, snapshot: ConfigSnapshot, path: Path) -> ConfigSnapshotDTO:
        suffix = ".diff" if snapshot.type == "diff" else ".txt"
        filename = f"{safe_device_name(device.name or device.device_uuid or 'device')}_{snapshot.type}_{snapshot.timestamp}{suffix}"
        return ConfigSnapshotDTO(
            id=int(snapshot.id or 0),
            device_id=snapshot.device_id,
            device_uuid=snapshot.device_uuid,
            timestamp=snapshot.timestamp,
            type=snapshot.type,
            size_bytes=path.stat().st_size if path.is_file() else 0,
            artifact_id=f"snapshot-{int(snapshot.id or 0)}",
            filename=filename,
            hash=snapshot.hash,
            created_at=str(snapshot.created_at or ""),
            error_message=_sanitize_text(str(snapshot.error_message or "")),
        )

    def _snapshot_path(self, site_name: str, snapshot: ConfigSnapshot) -> Path:
        return self._safe_snapshot_path(site_name, snapshot) or Path()

    def _safe_snapshot_path(self, site_name: str, snapshot: ConfigSnapshot) -> Path | None:
        root = self.paths.config_center_root(site_name).resolve()
        candidate = self.paths.site_dir(site_name) / snapshot.file_path
        if candidate.is_symlink():
            return None
        path = candidate.resolve()
        if root not in path.parents or not path.is_file():
            return None
        return path

    @staticmethod
    def _is_web_task(snapshot: TaskSnapshot | None, site_name: str) -> bool:
        return bool(
            snapshot is not None
            and snapshot.site_name == site_name
            and snapshot.source == "local"
            and snapshot.owner == CONFIG_WEB_OWNER
            and snapshot.task_type in CONFIG_WEB_TASK_TYPES
        )

    def _task_dto(
        self,
        snapshot: TaskSnapshot,
        *,
        diff_filter: str = "all",
        site_name: str = "",
    ) -> ConfigTaskStatusDTO:
        if site_name and not self._is_web_task(snapshot, site_name):
            raise ValueError("配置任务不属于当前局点")
        result = _safe_result(snapshot.result)
        if snapshot.task_type in CONFIG_WEB_COMPARE_TASK_TYPES and snapshot.status is TaskState.COMPLETED:
            path = self._safe_diff_path(snapshot)
            if path is not None:
                result.update(
                    {
                        "artifact_id": f"diff-{snapshot.task_id}",
                        "hash": _sha256_file(path),
                        "size": path.stat().st_size,
                    }
                )
            if str(diff_filter or "all") != "all":
                result["raw_diff"] = _filter_diff(str(result.get("raw_diff") or ""), diff_filter)
        return ConfigTaskStatusDTO(
            id=snapshot.task_id,
            type=snapshot.task_type,
            status=snapshot.status.value,
            progress=int(snapshot.progress),
            device_name=snapshot.device,
            message=_sanitize_text(snapshot.message),
            stage=snapshot.stage,
            created_time=snapshot.created_time,
            started_time=snapshot.started_time,
            finished_time=snapshot.finished_time,
            error_message=_sanitize_text(snapshot.error_message),
            result=result,
        )


def _safe_result(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    blocked = ("path", "file", "password", "token", "secret", "credential", "username", "community")
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key).casefold()
        if any(word in name for word in blocked):
            continue
        if isinstance(item, dict):
            result[str(key)] = _safe_result(item)
        elif isinstance(item, list):
            result[str(key)] = [_safe_value(entry) for entry in item]
        elif isinstance(item, str):
            result[str(key)] = _sanitize_text(item)
        else:
            result[str(key)] = item
    return result


def _safe_value(value: object) -> object:
    if isinstance(value, dict):
        return _safe_result(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    redacted = _ABSOLUTE_PATH_RE.sub("<redacted-path>", str(value or ""))
    redacted = _SECRET_VALUE_RE.sub(r"\1<redacted>", redacted)
    return _BEARER_RE.sub("Bearer <redacted>", redacted)


def _filter_diff(text: str, diff_filter: str) -> str:
    kind = str(diff_filter or "all").strip().casefold()
    if kind not in {"all", "added", "removed"}:
        raise ValueError("差异过滤类型无效")
    if kind == "all":
        return text
    return "\n".join(
        line
        for line in str(text or "").splitlines()
        if line.startswith("---")
        or line.startswith("+++")
        or line.startswith("@@")
        or (kind == "added" and line.startswith("+") and not line.startswith("+++"))
        or (kind == "removed" and line.startswith("-") and not line.startswith("---"))
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["CONFIG_WEB_TASK_TYPES", "ConfigCollectionApplicationService"]
