from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Callable, Protocol

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TERMINAL_TASK_STATES, TaskState
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter, LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.online_mr_collector import NetmikoShellConnection
from netconsole.services.vehicle_mr_online import (
    H3CComwareV9VehicleMrMeshLinkParser,
    MatchedAp,
    UNKNOWN_STATION,
    VehicleMrOnlineStore,
    build_mapping_lookup,
    build_mapping_trains,
    build_registered_trains,
    build_train_states,
    is_ac_device,
    load_group_names,
    load_vehicle_mr_mapping_trains,
    normalize_mac,
)


MESH_LINK_REFRESH_TASK_TYPE = "ac_mesh_link_refresh"
MESH_LINK_REFRESH_COMMANDS = (
    "screen-length disable",
    "display clock",
    "display wlan mesh-link ap",
)
MESH_LINK_SWITCH_HISTORY_COMMANDS = ("display wlan mesh-link switch-history",)
MESH_LINK_PARSER_VERSION = "H3CComwareV9VehicleMrMeshLinkParser/v1"

_COMMAND_FAILURE_MARKERS = (
    "% unrecognized command",
    "% incomplete command",
    "% wrong parameter",
    "permission denied",
    "error:",
)
_VALID_EMPTY_RE = re.compile(r"\b(?:total(?:\s+records?)?\s*[:=]?\s*0|0\s+records?)\b", re.IGNORECASE)


class AcMeshLinkRefreshErrorCode:
    CONTROLLER_NOT_FOUND = "AC_MESH_LINK_CONTROLLER_NOT_FOUND"
    PROFILE_INVALID = "AC_MESH_LINK_PROFILE_INVALID"
    CREDENTIAL_UNAVAILABLE = "AC_MESH_LINK_CREDENTIAL_UNAVAILABLE"
    CONNECT_FAILED = "AC_MESH_LINK_CONNECT_FAILED"
    COMMAND_FAILED = "AC_MESH_LINK_COMMAND_FAILED"
    EMPTY_RESPONSE = "AC_MESH_LINK_EMPTY_RESPONSE"
    PARSE_FAILED = "AC_MESH_LINK_PARSE_FAILED"
    SNAPSHOT_WRITE_FAILED = "AC_MESH_LINK_SNAPSHOT_WRITE_FAILED"
    CANCELLED = "AC_MESH_LINK_CANCELLED"
    INTERNAL_ERROR = "AC_MESH_LINK_INTERNAL_ERROR"


class AcMeshLinkRefreshError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class MeshLinkConnection(Protocol):
    def send_command(self, command: str, timeout: int) -> str: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[OnlineMrConnectionConfig], MeshLinkConnection]


@dataclass(frozen=True)
class AcMeshLinkRefreshStart:
    task: TaskSnapshot
    already_running: bool = False


class AcMeshLinkRefreshApplicationService:
    """只负责创建受控 Task；设备连接和凭据读取始终发生在 Worker。"""

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: LocalProcessAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self._lock = RLock()
        self._active_by_controller: dict[tuple[str, str], str] = {}

    def start_refresh(
        self,
        *,
        site_name: str,
        controller_id: str,
        include_switch_history: bool = False,
    ) -> AcMeshLinkRefreshStart:
        site = SiteManager(self.paths).validate_site_name(site_name)
        controller = load_mesh_link_controller(self.paths, site, controller_id, require_credentials=False)
        key = (site, str(controller.device_uuid or controller_id))
        with self._lock:
            existing = self._active_snapshot(key)
            if existing is not None:
                return AcMeshLinkRefreshStart(existing, already_running=True)

            task_id = f"ac-mesh-link-{uuid.uuid4().hex}"
            task_name = f"AC Mesh-Link 刷新 · {controller.name or controller.system_name or controller_id}"
            job = BackgroundJob(
                job_id=task_id,
                task_type=MESH_LINK_REFRESH_TASK_TYPE,
                params={
                    "site_name": site,
                    "controller_id": str(controller.device_uuid or controller_id),
                    "controller_name": str(controller.name or controller.system_name or controller_id),
                    "include_switch_history": bool(include_switch_history),
                    "task_name": task_name,
                    "owner": "web_ac_mesh_link",
                    "device": str(controller.device_uuid or controller_id),
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "_emit_log_events": True,
                    "_cancel_grace_ms": 3000,
                },
            )
            self._active_by_controller[key] = task_id
            try:
                self.process_adapter.start_job(job, on_complete=lambda value: self._complete(key, value))
            except Exception:
                self._active_by_controller.pop(key, None)
                raise
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is None:
                self._active_by_controller.pop(key, None)
                raise RuntimeError("Mesh-Link 刷新任务创建后未写入任务中心")
            return AcMeshLinkRefreshStart(snapshot)

    async def stop(self) -> None:
        import asyncio

        await asyncio.to_thread(self.process_adapter.shutdown)

    def _active_snapshot(self, key: tuple[str, str]) -> TaskSnapshot | None:
        site, controller_id = key
        task_id = self._active_by_controller.get(key)
        if task_id:
            snapshot = self.task_service.repository(site).get(task_id)
            if snapshot is not None and snapshot.status not in TERMINAL_TASK_STATES:
                return snapshot
            self._active_by_controller.pop(key, None)
        active_states = {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
        for snapshot in self.task_service.repository(site).list(statuses=active_states, limit=1000):
            if snapshot.task_type == MESH_LINK_REFRESH_TASK_TYPE and snapshot.device == controller_id:
                self._active_by_controller[key] = snapshot.task_id
                return snapshot
        return None

    def _complete(self, key: tuple[str, str], completion: LocalProcessCompletion) -> None:
        with self._lock:
            if self._active_by_controller.get(key) == completion.job_id:
                self._active_by_controller.pop(key, None)


class AcMeshLinkRefreshWorkerService:
    def __init__(
        self,
        paths: PathResolver,
        *,
        connection_factory: ConnectionFactory = NetmikoShellConnection,
        now_provider: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.paths = paths
        self.connection_factory = connection_factory
        self.now_provider = now_provider

    def execute(self, context: JobContext) -> dict[str, object]:
        params = dict(context.params)
        site = SiteManager(self.paths).validate_site_name(str(params.get("site_name") or ""))
        controller_id = str(params.get("controller_id") or "")
        include_history = bool(params.get("include_switch_history"))
        controller = load_mesh_link_controller(self.paths, site, controller_id, require_credentials=True)
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        store = VehicleMrOnlineStore(self.paths, site)
        session_id = store.create_session(controller, 0)
        staging = self.paths.ac_mesh_link_staging_root(site) / context.job_id
        target = self.paths.ac_mesh_link_snapshot_dir(site, session_id)
        failure = self.paths.ac_mesh_link_failures_root(site) / context.job_id
        started = time.monotonic()
        connection: MeshLinkConnection | None = None
        moved_to_target = False
        try:
            context.progress("profile", 1, 7, "已加载 AC 连接配置")
            context.check_cancelled()
            config = self._connection_config(site, controller)
            try:
                connection = self.connection_factory(config)
            except Exception:
                raise AcMeshLinkRefreshError(
                    AcMeshLinkRefreshErrorCode.CONNECT_FAILED,
                    "连接 AC 失败，请检查设备地址、服务状态和受控凭据。",
                ) from None
            context.progress("connected", 2, 7, "AC 连接成功")
            outputs: dict[str, str] = {}
            for command in MESH_LINK_REFRESH_COMMANDS:
                context.check_cancelled()
                try:
                    outputs[command] = str(connection.send_command(command, config.command_timeout) or "")
                except Exception:
                    raise AcMeshLinkRefreshError(
                        AcMeshLinkRefreshErrorCode.COMMAND_FAILED,
                        "Mesh-Link 白名单命令执行失败。",
                    ) from None
            history_output = ""
            if include_history:
                command = MESH_LINK_SWITCH_HISTORY_COMMANDS[0]
                context.check_cancelled()
                try:
                    history_output = str(connection.send_command(command, config.command_timeout) or "")
                except Exception:
                    raise AcMeshLinkRefreshError(
                        AcMeshLinkRefreshErrorCode.COMMAND_FAILED,
                        "Mesh-Link 切换历史白名单命令执行失败。",
                    ) from None
            context.progress("collected", 3, 7, "白名单命令采集完成")
        except BackgroundTaskCancelled:
            store.update_session(session_id, "已取消", error="用户取消", stopped=True)
            self._preserve_failure(staging, failure)
            raise
        except AcMeshLinkRefreshError as exc:
            store.update_session(session_id, "失败", error=exc.message, stopped=True)
            self._preserve_failure(staging, failure)
            raise RuntimeError(str(exc)) from None
        except Exception:
            store.update_session(session_id, "失败", error="内部错误", stopped=True)
            self._preserve_failure(staging, failure)
            raise RuntimeError(
                f"{AcMeshLinkRefreshErrorCode.INTERNAL_ERROR}: Mesh-Link 刷新发生内部错误，旧快照已保留。"
            ) from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

        try:
            mesh_output = outputs[MESH_LINK_REFRESH_COMMANDS[-1]]
            clock_output = outputs[MESH_LINK_REFRESH_COMMANDS[1]]
            warnings: list[str] = []
            if not self._has_device_clock(clock_output):
                warnings.append("display clock 未返回可解析日期，快照使用本地采集时间。")
            self._write_staging(
                staging,
                context=context,
                site=site,
                controller=controller,
                session_id=session_id,
                outputs=outputs,
                history_output=history_output,
                warnings=warnings,
            )
            self._validate_mesh_output(mesh_output)
            raw_for_parse = f"{clock_output}\n{mesh_output}"
            parse_result = H3CComwareV9VehicleMrMeshLinkParser().parse(raw_for_parse)
            if parse_result.parse_status.casefold() not in {"ok", "success"}:
                raise AcMeshLinkRefreshError(
                    AcMeshLinkRefreshErrorCode.PARSE_FAILED,
                    "Mesh-Link 回显无法按现有 H3C 格式解析。",
                )
            if not parse_result.links and not self._is_valid_empty(mesh_output):
                raise AcMeshLinkRefreshError(
                    AcMeshLinkRefreshErrorCode.PARSE_FAILED,
                    "Mesh-Link 回显没有可识别记录，也未明确返回零条链路。",
                )
            context.progress("parsed", 4, 7, f"解析完成，共 {len(parse_result.links)} 条链路")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
            moved_to_target = True
            context.progress("raw_saved", 5, 7, "原始回显已原子落盘")

            mappings = store.list_mappings()
            registered = build_registered_trains(repository.list(), load_group_names(repository, site))
            registered.update(load_vehicle_mr_mapping_trains(repository))
            registered.update(build_mapping_trains(mappings))
            ap_lookup = self._read_only_ap_lookup(site)
            trains = build_train_states(
                registered,
                parse_result,
                ap_lookup,
                store.load_current_states(),
                build_mapping_lookup(mappings),
            )
            try:
                snapshot_id = store.persist_snapshot(
                    session_id,
                    1,
                    parse_result,
                    trains,
                    ap_lookup,
                    round((time.monotonic() - started) * 1000),
                )
            except Exception:
                self._move_target_to_failure(target, failure)
                moved_to_target = False
                raise AcMeshLinkRefreshError(
                    AcMeshLinkRefreshErrorCode.SNAPSHOT_WRITE_FAILED,
                    "Mesh-Link 快照写入失败，旧快照已保留。",
                ) from None
            self._finish_meta(target, snapshot_id)
            store.update_session(session_id, "已完成", ac_time=parse_result.ac_time, stopped=True)
            context.progress("completed", 7, 7, "Mesh-Link 快照已更新")
            raw_reference = (target / "raw" / "mesh_link_raw.log").relative_to(self.paths.site_dir(site)).as_posix()
            return {
                "site_id": site,
                "controller_id": str(controller.device_uuid or controller_id),
                "controller_name": str(controller.name or controller.system_name or controller_id),
                "session_id": session_id,
                "snapshot_id": snapshot_id,
                "raw_output_reference": raw_reference,
                "parser_version": MESH_LINK_PARSER_VERSION,
                "records_count": len(parse_result.links),
                "warning_count": len(warnings),
                "warnings": warnings,
            }
        except BackgroundTaskCancelled:
            store.update_session(session_id, "已取消", error="用户取消", stopped=True)
            if moved_to_target:
                self._move_target_to_failure(target, failure)
            else:
                self._preserve_failure(staging, failure)
            raise
        except AcMeshLinkRefreshError as exc:
            store.update_session(session_id, "失败", error=exc.message, stopped=True)
            if moved_to_target:
                self._move_target_to_failure(target, failure)
            else:
                self._preserve_failure(staging, failure)
            raise RuntimeError(str(exc)) from None
        except Exception:
            store.update_session(session_id, "失败", error="内部错误", stopped=True)
            if moved_to_target:
                self._move_target_to_failure(target, failure)
            else:
                self._preserve_failure(staging, failure)
            raise RuntimeError(
                f"{AcMeshLinkRefreshErrorCode.INTERNAL_ERROR}: Mesh-Link 刷新发生内部错误，旧快照已保留。"
            ) from None

    @staticmethod
    def _connection_config(site: str, controller: Device) -> OnlineMrConnectionConfig:
        targets = tuple(connection_targets(controller))
        if not targets:
            raise AcMeshLinkRefreshError(
                AcMeshLinkRefreshErrorCode.PROFILE_INVALID,
                "AC 没有可用的 SSH/Telnet 连接配置。",
            )
        first = targets[0]
        return OnlineMrConnectionConfig(
            site=site,
            mr_id=str(controller.device_uuid or ""),
            mr_name=str(controller.name or "AC"),
            safe_mr_name="ac-mesh-link",
            device_id=controller.id,
            device_name=str(controller.name or "AC"),
            host=first.host,
            protocol=first.protocol,
            port=first.port,
            username=first.username,
            password=first.password,
            command_timeout=20,
            connection_targets=targets,
        )

    @staticmethod
    def _validate_mesh_output(output: str) -> None:
        text = str(output or "")
        if not text.strip():
            raise AcMeshLinkRefreshError(
                AcMeshLinkRefreshErrorCode.EMPTY_RESPONSE,
                "AC 未返回 Mesh-Link 回显。",
            )
        lowered = text.casefold()
        if any(marker in lowered for marker in _COMMAND_FAILURE_MARKERS):
            raise AcMeshLinkRefreshError(
                AcMeshLinkRefreshErrorCode.COMMAND_FAILED,
                "AC 拒绝或不支持 Mesh-Link 白名单命令。",
            )

    @staticmethod
    def _is_valid_empty(output: str) -> bool:
        text = str(output or "")
        lowered = text.casefold()
        return bool(_VALID_EMPTY_RE.search(text) or "no mesh link" in lowered or "no matching record" in lowered)

    @staticmethod
    def _has_device_clock(output: str) -> bool:
        text = str(output or "")
        return bool(re.search(r"\d{1,2}:\d{2}:\d{2}", text) and re.search(r"\d{1,2}/\d{1,2}/\d{4}", text))

    def _write_staging(
        self,
        staging: Path,
        *,
        context: JobContext,
        site: str,
        controller: Device,
        session_id: str,
        outputs: dict[str, str],
        history_output: str,
        warnings: list[str],
    ) -> None:
        raw_dir = staging / "raw"
        raw_dir.mkdir(parents=True, exist_ok=False)
        mesh_text = "\n\n".join(f"$ {command}\n{outputs.get(command, '')}" for command in MESH_LINK_REFRESH_COMMANDS)
        self._write_text_atomic(raw_dir / "mesh_link_raw.log", mesh_text.rstrip() + "\n")
        if history_output:
            command = MESH_LINK_SWITCH_HISTORY_COMMANDS[0]
            self._write_text_atomic(raw_dir / "switch_history_raw.log", f"$ {command}\n{history_output}".rstrip() + "\n")
        self._write_json_atomic(staging / "parse_warnings.json", {"warnings": warnings})
        self._write_json_atomic(
            staging / "snapshot_meta.json",
            {
                "snapshot_id": None,
                "session_id": session_id,
                "task_id": context.job_id,
                "site_id": site,
                "controller_id": str(controller.device_uuid or ""),
                "controller_name": str(controller.name or controller.system_name or ""),
                "collected_at": self.now_provider().isoformat(sep=" ", timespec="seconds"),
                "source_type": "ac_live_refresh",
                "parser_version": MESH_LINK_PARSER_VERSION,
                "raw_reference": "raw/mesh_link_raw.log",
            },
        )

    @staticmethod
    def _finish_meta(target: Path, snapshot_id: int) -> None:
        meta_path = target / "snapshot_meta.json"
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            payload["snapshot_id"] = int(snapshot_id)
            AcMeshLinkRefreshWorkerService._write_json_atomic(meta_path, payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # 快照和 raw 已经完整落盘；meta 补写失败不能反向破坏已提交快照。
            return

    def _read_only_ap_lookup(self, site: str) -> dict[str, object]:
        lookup: dict[str, object] = {"__resources__": []}
        for detail in AcManagementQueryService(self.paths).list_all_ap_details(site):
            ap = detail.ap
            station = ap.station or UNKNOWN_STATION
            resource = MatchedAp(ap.name, station, "resource", 0, normalize_mac(ap.mac), "ac_web_query")
            resources = lookup["__resources__"]
            if isinstance(resources, list):
                resources.append(resource)
            if ap.name:
                lookup[f"name:{ap.name.casefold()}"] = MatchedAp(
                    ap.name, station, "ap_name_exact", 100, normalize_mac(ap.mac), "ac_web_query"
                )
            for value in (ap.mac, *(radio.bssid for radio in detail.radios)):
                mac = normalize_mac(value)
                if mac:
                    lookup[f"mac:{mac}"] = MatchedAp(
                        ap.name or mac, station, "mac_exact", 95, normalize_mac(ap.mac), "ac_web_query"
                    )
        return lookup

    @staticmethod
    def _write_text_atomic(path: Path, text: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
        AcMeshLinkRefreshWorkerService._write_text_atomic(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    @staticmethod
    def _preserve_failure(source: Path, failure: Path) -> None:
        if not source.exists() or failure.exists():
            return
        failure.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, failure)

    @staticmethod
    def _move_target_to_failure(target: Path, failure: Path) -> None:
        if not target.exists() or failure.exists():
            return
        failure.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, failure)


def load_mesh_link_controller(
    paths: PathResolver,
    site_name: str,
    controller_id: str,
    *,
    require_credentials: bool,
) -> Device:
    site = SiteManager(paths).validate_site_name(site_name)
    db_path = paths.site_db_path(site)
    if not db_path.is_file():
        raise AcMeshLinkRefreshError(
            AcMeshLinkRefreshErrorCode.CONTROLLER_NOT_FOUND,
            "当前局点设备库不存在。",
        )
    if not require_credentials:
        with Database(db_path).connect() as conn:
            row = conn.execute(
                """
                SELECT id, device_uuid, name, system_name, device_vendor, device_type,
                       primary_address, backup_address, protocol, port,
                       ssh_enabled, ssh_port, telnet_enabled, telnet_port
                FROM devices WHERE device_uuid = ? LIMIT 1
                """,
                (str(controller_id or ""),),
            ).fetchone()
        controller = Device.from_mapping(dict(row)) if row is not None else None
        if controller is None or not is_ac_device(controller):
            raise AcMeshLinkRefreshError(
                AcMeshLinkRefreshErrorCode.CONTROLLER_NOT_FOUND,
                "指定 AC 不存在于当前局点。",
            )
        if not controller.primary_address or not (controller.ssh_enabled or controller.telnet_enabled or controller.protocol):
            raise AcMeshLinkRefreshError(
                AcMeshLinkRefreshErrorCode.PROFILE_INVALID,
                "AC 没有可用的 SSH/Telnet 连接配置。",
            )
        return controller
    repository = DeviceRepository(Database(db_path))
    controller = next(
        (item for item in repository.list() if str(item.device_uuid or "") == str(controller_id or "")),
        None,
    )
    if controller is None or not is_ac_device(controller):
        raise AcMeshLinkRefreshError(
            AcMeshLinkRefreshErrorCode.CONTROLLER_NOT_FOUND,
            "指定 AC 不存在于当前局点。",
        )
    targets = connection_targets(controller)
    if not targets:
        raise AcMeshLinkRefreshError(
            AcMeshLinkRefreshErrorCode.PROFILE_INVALID,
            "AC 没有可用的 SSH/Telnet 连接配置。",
        )
    if require_credentials and not any(target.username and target.password for target in targets):
        raise AcMeshLinkRefreshError(
            AcMeshLinkRefreshErrorCode.CREDENTIAL_UNAVAILABLE,
            "AC 受控凭据不完整。",
        )
    return controller


def run_ac_mesh_link_refresh(context: JobContext) -> dict[str, object]:
    return AcMeshLinkRefreshWorkerService(context.paths).execute(context)


__all__ = [
    "AcMeshLinkRefreshApplicationService",
    "AcMeshLinkRefreshError",
    "AcMeshLinkRefreshErrorCode",
    "AcMeshLinkRefreshStart",
    "AcMeshLinkRefreshWorkerService",
    "MESH_LINK_PARSER_VERSION",
    "MESH_LINK_REFRESH_COMMANDS",
    "MESH_LINK_REFRESH_TASK_TYPE",
    "MESH_LINK_SWITCH_HISTORY_COMMANDS",
    "load_mesh_link_controller",
    "run_ac_mesh_link_refresh",
]
