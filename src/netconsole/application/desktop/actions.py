from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Protocol

from netconsole.core import app_logger
from netconsole.core.runtime_mode import RuntimeMode


class DesktopSelectionPurpose(StrEnum):
    IMPORT_FILE = "import_file"
    IMPORT_FILES = "import_files"
    IMPORT_DIRECTORY = "import_directory"


@dataclass(frozen=True)
class DesktopActionResult:
    success: bool
    code: str
    message: str = ""
    paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RegisteredLaunch:
    executable: Path
    arguments: tuple[str, ...] = ()
    working_directory: Path | None = None


@dataclass(frozen=True)
class RegisteredNotification:
    title: str
    message: str


class DesktopActionAdapter(Protocol):
    def select_file(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult: ...

    def select_files(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult: ...

    def select_directory(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult: ...

    def open_controlled_directory(self, path: Path) -> DesktopActionResult: ...

    def open_controlled_artifact(self, path: Path) -> DesktopActionResult: ...

    def launch_registered_terminal(self, launch: RegisteredLaunch) -> DesktopActionResult: ...

    def launch_registered_tool(self, launch: RegisteredLaunch) -> DesktopActionResult: ...

    def show_native_notification(self, notification: RegisteredNotification) -> DesktopActionResult: ...


class DesktopActionResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DesktopActionResolver:
    """把不可信业务 ID 解析为已登记的本机目标。"""

    def __init__(
        self,
        *,
        controlled_roots: tuple[Path, ...] = (),
        directories: Mapping[str, Path] | None = None,
        artifacts: Mapping[str, Path] | None = None,
        terminals: Mapping[tuple[str, str], RegisteredLaunch] | None = None,
        tools: Mapping[tuple[str, str], RegisteredLaunch] | None = None,
        notifications: Mapping[str, RegisteredNotification] | None = None,
    ) -> None:
        roots: list[Path] = []
        for root in controlled_roots:
            candidate = Path(root)
            if not candidate.is_absolute() or _is_unc(candidate):
                raise ValueError("controlled roots must be local absolute paths")
            roots.append(candidate.resolve())
        self._roots = tuple(roots)
        self._directories = dict(directories or {})
        self._artifacts = dict(artifacts or {})
        self._terminals = dict(terminals or {})
        self._tools = dict(tools or {})
        self._notifications = dict(notifications or {})

    def directory(self, directory_id: str) -> Path:
        return self._path(directory_id, self._directories, "unknown_directory", expect_directory=True)

    def artifact(self, artifact_id: str) -> Path:
        return self._path(artifact_id, self._artifacts, "unknown_artifact", expect_directory=False)

    def terminal(self, action_id: str, object_id: str) -> RegisteredLaunch:
        return self._launch(action_id, object_id, self._terminals, "unknown_terminal_action")

    def validate_launch(self, launch: RegisteredLaunch) -> RegisteredLaunch:
        """校验由 ApplicationService 从受信配置组装的桌面启动项。"""
        return self._validate_launch(launch)

    def tool(self, action_id: str, object_id: str) -> RegisteredLaunch:
        return self._launch(action_id, object_id, self._tools, "unknown_tool_action")

    def notification(self, notification_id: str) -> RegisteredNotification:
        key = _require_identifier(notification_id)
        notification = self._notifications.get(key)
        if notification is None:
            raise DesktopActionResolutionError("unknown_notification", "通知未登记")
        return notification

    def _path(
        self,
        target_id: str,
        registry: Mapping[str, Path],
        unknown_code: str,
        *,
        expect_directory: bool,
    ) -> Path:
        key = _require_identifier(target_id)
        candidate = registry.get(key)
        if candidate is None:
            raise DesktopActionResolutionError(unknown_code, "本机目标未登记")
        raw = Path(candidate)
        if not raw.is_absolute() or _is_unc(raw):
            raise DesktopActionResolutionError("invalid_registered_path", "登记路径必须是本机绝对路径")
        try:
            resolved = raw.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DesktopActionResolutionError("target_not_found", "登记目标不存在") from exc
        if raw.is_symlink() or not any(resolved == root or resolved.is_relative_to(root) for root in self._roots):
            raise DesktopActionResolutionError("path_outside_controlled_roots", "登记目标不属于受控目录")
        if expect_directory and not resolved.is_dir():
            raise DesktopActionResolutionError("target_not_directory", "登记目标不是目录")
        if not expect_directory and not resolved.is_file():
            raise DesktopActionResolutionError("target_not_file", "登记目标不是文件")
        return resolved

    def _launch(
        self,
        action_id: str,
        object_id: str,
        registry: Mapping[tuple[str, str], RegisteredLaunch],
        unknown_code: str,
    ) -> RegisteredLaunch:
        key = (_require_identifier(action_id), _require_identifier(object_id))
        launch = registry.get(key)
        if launch is None:
            raise DesktopActionResolutionError(unknown_code, "启动动作未登记")
        return self._validate_launch(launch)

    def _validate_launch(self, launch: RegisteredLaunch) -> RegisteredLaunch:
        raw_executable = Path(launch.executable)
        if not raw_executable.is_absolute() or _is_unc(raw_executable):
            raise DesktopActionResolutionError("invalid_executable", "登记程序必须是本机绝对路径")
        if (
            raw_executable.name.casefold() in _FORBIDDEN_EXECUTABLES
            or raw_executable.suffix.casefold() in _FORBIDDEN_SCRIPT_SUFFIXES
        ):
            raise DesktopActionResolutionError("forbidden_executable", "登记动作不得启动命令解释器或脚本")
        try:
            executable = raw_executable.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DesktopActionResolutionError("executable_not_found", "登记程序不存在") from exc
        if raw_executable.is_symlink() or not executable.is_file():
            raise DesktopActionResolutionError("invalid_executable", "登记程序不是普通文件")
        arguments = tuple(str(argument) for argument in launch.arguments)
        if any("\0" in argument for argument in arguments):
            raise DesktopActionResolutionError("invalid_registered_arguments", "登记参数包含无效字符")
        raw_working_directory = Path(launch.working_directory or executable.parent)
        if not raw_working_directory.is_absolute() or _is_unc(raw_working_directory):
            raise DesktopActionResolutionError("invalid_working_directory", "工作目录必须是本机绝对路径")
        try:
            working_directory = raw_working_directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DesktopActionResolutionError("invalid_working_directory", "工作目录不存在") from exc
        if raw_working_directory.is_symlink() or not working_directory.is_dir():
            raise DesktopActionResolutionError("invalid_working_directory", "工作目录不是目录")
        return RegisteredLaunch(executable, arguments, working_directory)


class DesktopActionService:
    def __init__(
        self,
        runtime_mode: RuntimeMode,
        adapter: DesktopActionAdapter,
        resolver: DesktopActionResolver,
        audit: Callable[[str, str], None] = app_logger.log_info,
    ) -> None:
        self.runtime_mode = runtime_mode
        self.adapter = adapter
        self.resolver = resolver
        self.audit = audit

    def select_file(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        target = _audit_identifier(purpose)
        self._audit_attempt("select_file", target)
        rejection = self._selection_rejection(purpose, DesktopSelectionPurpose.IMPORT_FILE)
        return self._audit_result("select_file", target, rejection or self.adapter.select_file(purpose))

    def select_files(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        target = _audit_identifier(purpose)
        self._audit_attempt("select_files", target)
        rejection = self._selection_rejection(purpose, DesktopSelectionPurpose.IMPORT_FILES)
        return self._audit_result("select_files", target, rejection or self.adapter.select_files(purpose))

    def select_directory(self, purpose: DesktopSelectionPurpose) -> DesktopActionResult:
        target = _audit_identifier(purpose)
        self._audit_attempt("select_directory", target)
        rejection = self._selection_rejection(purpose, DesktopSelectionPurpose.IMPORT_DIRECTORY)
        return self._audit_result("select_directory", target, rejection or self.adapter.select_directory(purpose))

    def open_controlled_directory(self, directory_id: str) -> DesktopActionResult:
        target = _audit_identifier(directory_id)
        self._audit_attempt("open_controlled_directory", target)
        if rejection := self._server_rejection():
            return self._audit_result("open_controlled_directory", target, rejection)
        try:
            result = self.adapter.open_controlled_directory(self.resolver.directory(directory_id))
        except DesktopActionResolutionError as exc:
            result = _rejected(exc)
        return self._audit_result("open_controlled_directory", target, result)

    def open_controlled_artifact(self, artifact_id: str) -> DesktopActionResult:
        target = _audit_identifier(artifact_id)
        self._audit_attempt("open_controlled_artifact", target)
        if rejection := self._server_rejection():
            return self._audit_result("open_controlled_artifact", target, rejection)
        try:
            result = self.adapter.open_controlled_artifact(self.resolver.artifact(artifact_id))
        except DesktopActionResolutionError as exc:
            result = _rejected(exc)
        return self._audit_result("open_controlled_artifact", target, result)

    def launch_registered_terminal(self, action_id: str, object_id: str) -> DesktopActionResult:
        target = _audit_identifier(action_id, object_id)
        self._audit_attempt("launch_registered_terminal", target)
        if rejection := self._server_rejection():
            return self._audit_result("launch_registered_terminal", target, rejection)
        try:
            result = self.adapter.launch_registered_terminal(self.resolver.terminal(action_id, object_id))
        except DesktopActionResolutionError as exc:
            result = _rejected(exc)
        return self._audit_result("launch_registered_terminal", target, result)

    def launch_terminal(
        self,
        action_id: str,
        object_id: str,
        launch: RegisteredLaunch,
    ) -> DesktopActionResult:
        """启动由业务服务从设备和已保存终端配置解析出的终端。"""
        target = _audit_identifier(action_id, object_id)
        self._audit_attempt("launch_terminal", target)
        if rejection := self._server_rejection():
            return self._audit_result("launch_terminal", target, rejection)
        try:
            result = self.adapter.launch_registered_terminal(
                self.resolver.validate_launch(launch)
            )
        except DesktopActionResolutionError as exc:
            result = _rejected(exc)
        return self._audit_result("launch_terminal", target, result)

    def launch_registered_tool(self, action_id: str, object_id: str) -> DesktopActionResult:
        target = _audit_identifier(action_id, object_id)
        self._audit_attempt("launch_registered_tool", target)
        if rejection := self._server_rejection():
            return self._audit_result("launch_registered_tool", target, rejection)
        try:
            result = self.adapter.launch_registered_tool(self.resolver.tool(action_id, object_id))
        except DesktopActionResolutionError as exc:
            result = _rejected(exc)
        return self._audit_result("launch_registered_tool", target, result)

    def show_native_notification(self, notification_id: str) -> DesktopActionResult:
        target = _audit_identifier(notification_id)
        self._audit_attempt("show_native_notification", target)
        if rejection := self._server_rejection():
            return self._audit_result("show_native_notification", target, rejection)
        try:
            result = self.adapter.show_native_notification(self.resolver.notification(notification_id))
        except DesktopActionResolutionError as exc:
            result = _rejected(exc)
        return self._audit_result("show_native_notification", target, result)

    def _selection_rejection(
        self,
        purpose: DesktopSelectionPurpose,
        expected: DesktopSelectionPurpose,
    ) -> DesktopActionResult | None:
        if rejection := self._server_rejection():
            return rejection
        if purpose is not expected:
            return DesktopActionResult(False, "invalid_selection_purpose", "文件选择用途不受支持")
        return None

    def _server_rejection(self) -> DesktopActionResult | None:
        if self.runtime_mode is RuntimeMode.DESKTOP:
            return None
        return DesktopActionResult(False, "server_mode_forbidden", "Server 模式禁止桌面动作")

    def _audit_attempt(self, action: str, target: str) -> None:
        self.audit("DESKTOP_ACTION_ATTEMPT", f"action={action} target={target}")

    def _audit_result(self, action: str, target: str, result: DesktopActionResult) -> DesktopActionResult:
        self.audit("DESKTOP_ACTION_RESULT", f"action={action} target={target} code={result.code}")
        return result


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_EXECUTABLES = frozenset({"cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe"})
_FORBIDDEN_SCRIPT_SUFFIXES = frozenset({".bat", ".cmd", ".ps1"})


def _require_identifier(value: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise DesktopActionResolutionError("invalid_identifier", "业务标识格式无效")
    return value


def _is_unc(path: Path) -> bool:
    return str(path).startswith("\\\\")


def _audit_identifier(*values: object) -> str:
    identifiers = [str(value) for value in values]
    return ":".join(identifiers) if identifiers and all(_IDENTIFIER.fullmatch(value) for value in identifiers) else "invalid"


def _rejected(exc: DesktopActionResolutionError) -> DesktopActionResult:
    return DesktopActionResult(False, exc.code, str(exc))


__all__ = [
    "DesktopActionAdapter",
    "DesktopActionResolver",
    "DesktopActionResult",
    "DesktopActionService",
    "DesktopSelectionPurpose",
    "RegisteredLaunch",
    "RegisteredNotification",
]
