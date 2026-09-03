from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from netconsole.adapters.h3c.h3c_command_profile import H3cAcCommandProfile
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.ac_models import (
    AcCommandExecutionResult,
    AcCommandRequest,
    is_ac_device_type,
)
from netconsole.services.h3c_ac_collect_service import AcCommandActionResult, run_h3c_ac_action
from netconsole.services.device_scope import require_current_debug_device


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class AcCommandCancelled(RuntimeError):
    pass


class AcCommandService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        ac_repository: AcRepository,
        paths: PathResolver,
        *,
        action_runner=run_h3c_ac_action,
    ) -> None:
        self.device_repository = device_repository
        self.ac_repository = ac_repository
        self.paths = paths
        self.action_runner = action_runner

    def execute_action(
        self,
        request: AcCommandRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcCommandExecutionResult:
        source = str(request.source or "auto").strip().lower()
        if source not in {"auto", "cli", "ssh", "telnet"}:
            raise ValueError(f"不支持的 AC 命令来源：{request.source}")
        self._check_cancelled(should_cancel)
        device = self._load_device(request.device_uuid)
        commands, context = self._resolve_action(device, request)
        return self.execute_command_sequence(
            device,
            request,
            commands,
            context,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    def persist_auto_ap(
        self,
        request: AcCommandRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcCommandExecutionResult:
        return self.execute_action(request, progress_callback=progress_callback, should_cancel=should_cancel)

    def enable_ap_remote_login(
        self,
        request: AcCommandRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcCommandExecutionResult:
        return self.execute_action(request, progress_callback=progress_callback, should_cancel=should_cancel)

    def save_config(
        self,
        request: AcCommandRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcCommandExecutionResult:
        return self.execute_action(request, progress_callback=progress_callback, should_cancel=should_cancel)

    def execute_command_sequence(
        self,
        device: Device,
        request: AcCommandRequest,
        commands: tuple[str, ...],
        context: str,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcCommandExecutionResult:
        self._progress(progress_callback, "ac_command_action", 0, len(commands), f"正在执行 AC 动作：{request.action}")
        completed = 0

        def progress(message: str) -> None:
            nonlocal completed
            if message.startswith("正在执行 "):
                completed = min(len(commands), completed + 1)
            self._progress(progress_callback, "ac_command_action", completed, len(commands), message)

        result: AcCommandActionResult = self.action_runner(
            device,
            request.site_name,
            request.action,
            commands=commands,
            context=context,
            repository=self.ac_repository,
            paths=self.paths,
            progress=progress,
            should_cancel=should_cancel,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcCommandCancelled("用户已取消更新")
        self._progress(
            progress_callback,
            "ac_command_action",
            len(commands),
            len(commands),
            "AC 动作执行完成" if result.success else "AC 动作执行失败",
        )
        error_message = str(result.error_message or "")
        return AcCommandExecutionResult(
            success=result.success,
            device_uuid=str(result.ac_device_uuid or request.device_uuid),
            action=result.action,
            commands=list(result.commands),
            command_results=[asdict(item) for item in result.command_results],
            collect_run_uuid=result.collect_run_uuid,
            raw_log_path=result.raw_log_path,
            error_code=self._error_code(error_message),
            error_message=error_message,
            confirm_required=request.confirm_required,
        )

    def _resolve_action(self, device: Device, request: AcCommandRequest) -> tuple[tuple[str, ...], str]:
        profile = H3cAcCommandProfile(device)
        verified = {
            "persist_auto_ap": (profile.persist_auto_ap_commands, "ac_persist_auto_ap"),
            "enable_ap_remote_login": (profile.enable_ap_remote_login_commands, "ac_enable_ap_remote_login"),
            "save_config": (("save force",), "config_lifecycle"),
        }
        if request.action in verified:
            commands, context = verified[request.action]
            if request.command_sequence and tuple(request.command_sequence) != commands:
                raise ValueError("AC 命令序列与已验证动作不一致")
            return commands, context
        if request.action != "custom_sequence" or not request.command_sequence:
            raise ValueError(f"不支持的 AC 命令动作：{request.action}")
        sequence = tuple(request.command_sequence)
        for commands, context in verified.values():
            if sequence == commands:
                return sequence, context
        raise ValueError("自定义命令序列未通过 AC 安全白名单")

    def _load_device(self, device_uuid: str) -> Device:
        device = next(
            (
                item
                for item in self.device_repository.list()
                if is_ac_device_type(item.device_type)
                and str(item.device_uuid or "") == device_uuid
            ),
            None,
        )
        if device is None:
            raise KeyError(f"AC device not found: {device_uuid}")
        return require_current_debug_device(device)

    @staticmethod
    def _error_code(message: str) -> str:
        text = message.casefold()
        if not text:
            return ""
        if "cancel" in text or "取消" in text:
            return "cancelled"
        if "auth" in text or "password" in text or "认证" in text or "密码" in text:
            return "authentication_failed"
        if "timeout" in text or "timed out" in text or "超时" in text:
            return "timeout"
        if "unrecognized command" in text or "incomplete command" in text or "设备返回" in text:
            return "device_command_error"
        if "save" in text or "保存" in text:
            return "save_failed"
        if "connect" in text or "连接" in text or "未启用连接方式" in text:
            return "connection_failed"
        return "command_failed"

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: str, current: int, total: int, message: str) -> None:
        if callback is not None:
            callback(stage, current, total, message)

    @classmethod
    def _check_cancelled(cls, callback: CancelCallback | None) -> None:
        if cls._cancelled(callback):
            raise AcCommandCancelled("用户已取消更新")

    @staticmethod
    def _cancelled(callback: CancelCallback | None) -> bool:
        return bool(callback is not None and callback())
