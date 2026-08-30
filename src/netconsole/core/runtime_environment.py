from __future__ import annotations

import os
import sys
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from netconsole.core.data_root_configuration import resolve_persistent_data_root
from netconsole.core.runtime_mode import (
    DataEnvironmentInfo,
    DataEnvironmentMode,
    RuntimeMode,
)


FORBIDDEN_RUNTIME_DIR_NAMES = frozenset({"docs", "tests", "project"})
STORAGE_MODES = frozenset({"persistent", "isolated_test"})
WINDOWS_TEST_DATA_ROOT = Path(r"D:\study\NetConsole-Workspace\test-data\NetConsole")
RUNTIME_MODE_FILE_NAME = "runtime_mode.json"
ALLOW_PRODUCTION_WRITE_ENV = "NETCONSOLE_ALLOW_PRODUCTION_WRITE"


class ProductionWriteBlockedError(RuntimeError):
    """Raised when a destructive/maintenance operation targets production."""


def is_packaged_runtime() -> bool:
    if getattr(sys, "frozen", False):
        return True
    main_module = sys.modules.get("__main__")
    if getattr(main_module, "__compiled__", None):
        return True
    return _executable_app_root() is not None


def app_root() -> Path:
    executable_root = _executable_app_root()
    if executable_root is not None:
        return executable_root
    if is_packaged_runtime():
        return Path(sys.executable).resolve().parent
    return _source_project_root()


def _executable_app_root() -> Path | None:
    for executable in _runtime_executable_candidates():
        root = executable.parent
        if (root / "runtime" / "build_info.json").is_file():
            return root
    return None


def _runtime_executable_candidates() -> list[Path]:
    candidates: list[Path] = []
    for raw_path in (sys.argv[0] if sys.argv else "", sys.executable):
        path = Path(raw_path)
        if not raw_path or path.name.lower().startswith("python") or path.suffix.lower() != ".exe":
            continue
        resolved = path.resolve()
        if resolved not in candidates:
            candidates.append(resolved)
    return candidates


def data_root() -> Path:
    mode = runtime_mode()
    configured = resolve_persistent_data_root(test_mode=mode is RuntimeMode.TEST)
    return validate_data_root(configured.path, mode=mode)


def runtime_mode() -> RuntimeMode:
    value = str(os.environ.get("NETCONSOLE_RUNTIME_MODE") or "").strip().casefold()
    if value == RuntimeMode.TEST.value:
        return RuntimeMode.TEST
    if value in {"desktop", "desktop-development", "desktop-packaged"}:
        return RuntimeMode.DESKTOP
    if value in {"", "server"}:
        return RuntimeMode.SERVER
    raise RuntimeError("NETCONSOLE_RUNTIME_MODE is invalid")


def validate_data_root(candidate: Path, *, mode: RuntimeMode | None = None) -> Path:
    raw = Path(candidate).expanduser()
    if not raw.is_absolute():
        raise RuntimeError("NETCONSOLE_DATA_ROOT must be an absolute path")
    resolved = raw.resolve()
    selected_mode = mode or runtime_mode()
    _reject_source_tree_data_root(resolved)
    if selected_mode is not RuntimeMode.TEST:
        _reject_temporary_data_root(resolved)
    if sys.platform == "win32":
        _validate_windows_data_root(resolved, selected_mode)
    return resolved


def data_environment(data_root: Path | None = None) -> DataEnvironmentInfo:
    """Read the explicit data-root environment marker.

    Test roots are identified by the explicit process test mode and do not
    write a marker file. Persistent roots must carry a valid marker; no path
    name heuristic is used.
    """

    selected_runtime_mode = runtime_mode()
    if selected_runtime_mode is RuntimeMode.TEST:
        return DataEnvironmentInfo(DataEnvironmentMode.TEST)
    root = Path(data_root) if data_root is not None else data_root_for_environment()
    marker = root / RUNTIME_MODE_FILE_NAME
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"数据根缺少 {RUNTIME_MODE_FILE_NAME}，拒绝启动：{root}。"
            "请先使用受控复制/初始化流程明确标记 production 或 development。"
        ) from exc
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"数据根环境标记无效：{marker}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"数据根环境标记必须是 JSON 对象：{marker}")
    try:
        mode = DataEnvironmentMode(str(value.get("mode") or "").strip().casefold())
    except ValueError as exc:
        raise RuntimeError(f"数据根环境 mode 无效：{marker}") from exc
    if mode is DataEnvironmentMode.TEST:
        raise RuntimeError("runtime_mode.json 不得把持久化数据根标记为 test")
    created_from = str(value.get("created_from") or "")
    created_time = str(value.get("created_time") or "")
    readonly_warning = bool(value.get("readonly_warning", mode is DataEnvironmentMode.PRODUCTION))
    if mode is DataEnvironmentMode.PRODUCTION and not readonly_warning:
        raise RuntimeError("production 数据根必须启用 readonly_warning")
    return DataEnvironmentInfo(mode, created_from, created_time, readonly_warning)


def data_root_for_environment() -> Path:
    configured = resolve_persistent_data_root(test_mode=False)
    return validate_data_root(configured.path, mode=RuntimeMode.DESKTOP)


def write_data_environment(
    data_root: Path,
    info: DataEnvironmentInfo,
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically write the explicit marker used by startup and diagnostics."""

    root = Path(data_root).resolve()
    if info.mode is DataEnvironmentMode.TEST:
        raise ValueError("test environment markers are process-only")
    marker = root / RUNTIME_MODE_FILE_NAME
    if marker.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite data environment marker: {marker}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{RUNTIME_MODE_FILE_NAME}.{uuid.uuid4().hex}.tmp"
    payload = asdict(info)
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)
    return marker


def production_write_allowed() -> bool:
    return str(os.environ.get(ALLOW_PRODUCTION_WRITE_ENV) or "").strip() == "1"


def enable_production_write_flag(enabled: bool) -> None:
    """Propagate an explicit CLI authorization to the shared process gate."""

    if enabled:
        os.environ[ALLOW_PRODUCTION_WRITE_ENV] = "1"


def data_root_for_path(path: Path) -> Path:
    """Find the nearest explicit data-root marker for a file or directory."""

    candidate = Path(path).expanduser().resolve()
    start = candidate if candidate.is_dir() else candidate.parent
    for parent in (start, *start.parents):
        if (parent / RUNTIME_MODE_FILE_NAME).is_file():
            return parent
    raise RuntimeError(
        f"无法从路径识别 NetConsole 数据根：{candidate}。"
        f"请确认祖先目录包含 {RUNTIME_MODE_FILE_NAME}。"
    )


def require_data_root_write_allowed(
    data_root: Path,
    operation: str,
    *,
    allow_production_write: bool = False,
) -> DataEnvironmentInfo:
    """Validate the explicit marker and block production writes by default."""

    enable_production_write_flag(allow_production_write)
    resolved = Path(data_root).expanduser().resolve()
    environment = data_environment(resolved)
    require_production_write_allowed(resolved, operation, environment=environment)
    return environment


def require_production_write_allowed(
    data_root: Path,
    operation: str,
    *,
    environment: DataEnvironmentInfo | None = None,
) -> None:
    info = environment or data_environment(data_root)
    if info.is_production and not production_write_allowed():
        raise ProductionWriteBlockedError(
            f"已阻止生产数据写操作：{operation}。"
            "如确需执行，请显式指定 --allow-production-write。"
        )


def desktop_storage_mode() -> str:
    value = str(os.environ.get("NETCONSOLE_STORAGE_MODE") or "persistent").strip()
    if value not in STORAGE_MODES:
        raise RuntimeError("NETCONSOLE_STORAGE_MODE is invalid")
    return value


def persistent_storage() -> bool:
    return desktop_storage_mode() == "persistent"


def _reject_source_tree_data_root(candidate: Path) -> None:
    source_root = _source_project_root().resolve()
    if candidate == source_root or candidate.is_relative_to(source_root):
        raise RuntimeError(f"NETCONSOLE_DATA_ROOT must not be inside the source repository: {candidate}")


def _reject_temporary_data_root(candidate: Path) -> None:
    import tempfile

    temporary = Path(tempfile.gettempdir()).resolve()
    if candidate == temporary or candidate.is_relative_to(temporary):
        raise RuntimeError(f"NETCONSOLE_DATA_ROOT must not use the system temporary directory: {candidate}")


def _validate_windows_data_root(candidate: Path, mode: RuntimeMode) -> None:
    if mode is RuntimeMode.TEST:
        test_root = WINDOWS_TEST_DATA_ROOT.resolve()
        if candidate == test_root or not candidate.is_relative_to(test_root):
            raise RuntimeError(
                "测试数据根必须位于 D:\\study\\NetConsole-Workspace\\test-data\\NetConsole\\<run-id>，且不能直接使用测试根目录"
            )
        return
    system_drive = str(os.environ.get("SystemDrive") or "C:").rstrip("\\/").casefold()
    if candidate.drive.rstrip("\\/").casefold() == system_drive:
        raise RuntimeError(f"NetConsole 数据根不得位于系统盘：{candidate}")
    forbidden_roots = {
        "AppData": (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")),
        "系统临时目录": (os.environ.get("TEMP"), os.environ.get("TMP")),
        "用户 Profile": (os.environ.get("USERPROFILE"),),
        "程序安装目录": (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramW6432"),
        ),
        "Windows 目录": (os.environ.get("SystemRoot"), os.environ.get("WINDIR")),
    }
    for label, values in forbidden_roots.items():
        for raw_root in values:
            if not raw_root:
                continue
            root = Path(raw_root).expanduser()
            if not root.is_absolute():
                continue
            root = root.resolve()
            if candidate == root or candidate.is_relative_to(root):
                raise RuntimeError(f"NetConsole 数据根不得位于 {label}：{candidate}")


def _source_project_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    return current.parents[3]


def validate_runtime_write_path(path: Path) -> Path:
    resolved = Path(path).resolve()
    forbidden = [part for part in resolved.parts if part.lower() in FORBIDDEN_RUNTIME_DIR_NAMES]
    if forbidden:
        raise RuntimeError(f"invalid runtime write path: {resolved}")
    return resolved


def ensure_runtime_dir(path: Path) -> Path:
    resolved = validate_runtime_write_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
