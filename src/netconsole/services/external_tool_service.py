from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.services.tool_path_resolver import get_tool_dir


IPOP_SETTINGS_KEY = "external_tools/ipop_path"


@dataclass(frozen=True)
class ExternalToolValidationResult:
    success: bool
    message: str
    executable_path: Path | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ExternalToolLaunchResult:
    success: bool
    message: str
    executable_path: Path | None = None
    error_code: str | None = None

    @property
    def path(self) -> Path | None:
        return self.executable_path


def get_configured_ipop_path(
    settings: SettingsStore | None = None,
    *,
    paths: PathResolver | None = None,
) -> Path | None:
    resolver = paths or PathResolver()
    store = settings or SettingsStore(resolver)
    return normalize_ipop_path(store.get_value(IPOP_SETTINGS_KEY, ""))


def save_ipop_path(
    path: str | Path,
    settings: SettingsStore | None = None,
    *,
    paths: PathResolver | None = None,
) -> Path:
    resolver = paths or PathResolver()
    store = settings or SettingsStore(resolver)
    normalized = normalize_ipop_path(path)
    if normalized is None:
        raise ValueError("IPOP 路径不能为空")
    store.set_value(IPOP_SETTINGS_KEY, str(normalized))
    return normalized


def clear_ipop_path(
    settings: SettingsStore | None = None,
    *,
    paths: PathResolver | None = None,
) -> None:
    resolver = paths or PathResolver()
    store = settings or SettingsStore(resolver)
    store.set_value(IPOP_SETTINGS_KEY, "")


def get_local_ipop_path(paths: PathResolver | None = None) -> Path:
    resolver = paths or PathResolver()
    return get_tool_dir("ipop", resolver) / "IPOP.EXE"


def resolve_ipop_executable(
    paths: PathResolver | None = None,
    *,
    settings: SettingsStore | None = None,
) -> Path | None:
    resolver = paths or PathResolver()
    configured = get_configured_ipop_path(settings, paths=resolver)
    if validate_ipop_executable(configured).success:
        return configured
    local_path = get_local_ipop_path(resolver)
    if validate_ipop_executable(local_path).success:
        return local_path.resolve()
    return None


def validate_ipop_executable(
    path: str | Path | None,
    *,
    platform_name: str | None = None,
) -> ExternalToolValidationResult:
    normalized = normalize_ipop_path(path)
    if normalized is None:
        return ExternalToolValidationResult(False, "IPOP 路径未配置", error_code="not_configured")
    try:
        if not normalized.exists():
            return ExternalToolValidationResult(False, f"IPOP 文件不存在：{normalized}", normalized, "not_found")
        if normalized.is_dir():
            return ExternalToolValidationResult(False, f"IPOP 路径指向目录：{normalized}", normalized, "is_directory")
        if not normalized.is_file():
            return ExternalToolValidationResult(False, f"IPOP 路径不是普通文件：{normalized}", normalized, "not_file")
    except OSError as exc:
        return ExternalToolValidationResult(False, f"IPOP 路径无法访问：{exc}", normalized, "access_denied")
    if (platform_name or sys.platform) == "win32" and normalized.suffix.casefold() != ".exe":
        return ExternalToolValidationResult(False, f"IPOP 文件不是 EXE：{normalized}", normalized, "not_exe")
    return ExternalToolValidationResult(True, "IPOP 路径有效", normalized.resolve())


def launch_ipop(
    paths: PathResolver | None = None,
    *,
    settings: SettingsStore | None = None,
    executable_path: str | Path | None = None,
) -> ExternalToolLaunchResult:
    if sys.platform != "win32":
        return ExternalToolLaunchResult(False, "不支持当前平台", error_code="unsupported_platform")
    resolver = paths or PathResolver()
    configured = get_configured_ipop_path(settings, paths=resolver)
    candidate = normalize_ipop_path(executable_path) if executable_path is not None else resolve_ipop_executable(resolver, settings=settings)
    validation = validate_ipop_executable(candidate)
    if not validation.success:
        if executable_path is None and configured is not None:
            validation = validate_ipop_executable(configured)
        elif executable_path is None:
            local_path = get_local_ipop_path(resolver)
            validation = ExternalToolValidationResult(
                False,
                f"IPOP 路径未配置，默认本地路径未找到：{local_path}",
                local_path,
                "not_configured",
            )
        return ExternalToolLaunchResult(False, validation.message, validation.executable_path, validation.error_code)
    executable = validation.executable_path
    assert executable is not None
    try:
        result = QProcess.startDetached(str(executable), [], str(executable.parent))
    except PermissionError as exc:
        return ExternalToolLaunchResult(False, f"IPOP v4.1 启动失败：权限不足，{exc}", executable, "permission_denied")
    except OSError as exc:
        code = "access_denied" if getattr(exc, "winerror", None) == 5 else "start_failed"
        return ExternalToolLaunchResult(False, f"IPOP v4.1 启动失败：{exc}", executable, code)
    except Exception as exc:
        return ExternalToolLaunchResult(False, f"IPOP v4.1 启动失败：{exc}", executable, "start_failed")
    started = bool(result[0]) if isinstance(result, tuple) else bool(result)
    if not started:
        return ExternalToolLaunchResult(False, "IPOP v4.1 启动失败：QProcess 未能启动程序", executable, "qprocess_failed")
    return ExternalToolLaunchResult(True, "IPOP v4.1 已启动。", executable)


def normalize_ipop_path(path: object) -> Path | None:
    text = str(path or "").strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    if not text:
        return None
    expanded = os.path.expandvars(os.path.expanduser(text))
    candidate = Path(expanded)
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate.absolute()
