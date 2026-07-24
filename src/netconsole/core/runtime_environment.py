from __future__ import annotations

import os
import sys
from pathlib import Path

from netconsole.core.runtime_mode import RuntimeMode


FORBIDDEN_RUNTIME_DIR_NAMES = frozenset({"docs", "tests", "project"})
STORAGE_MODES = frozenset({"persistent", "isolated_test"})
DEFAULT_WINDOWS_DATA_ROOT = Path(r"D:\NetConsoleData")
WINDOWS_TEST_DATA_ROOT = Path(r"D:\NetConsoleTestData")


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
    configured = str(os.environ.get("NETCONSOLE_DATA_ROOT") or "").strip()
    mode = runtime_mode()
    if configured:
        resolved = Path(configured).expanduser().resolve()
    elif mode is RuntimeMode.TEST:
        raise RuntimeError("测试模式必须显式设置 NETCONSOLE_DATA_ROOT")
    elif sys.platform == "win32":
        resolved = DEFAULT_WINDOWS_DATA_ROOT.resolve()
    else:
        raise RuntimeError("NETCONSOLE_DATA_ROOT must be configured outside Windows")
    return validate_data_root(resolved, mode=mode)


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
    resolved = Path(candidate).expanduser().resolve()
    if not resolved.is_absolute():
        raise RuntimeError("NETCONSOLE_DATA_ROOT must be an absolute path")
    selected_mode = mode or runtime_mode()
    _reject_source_tree_data_root(resolved)
    _reject_temporary_data_root(resolved)
    if sys.platform == "win32":
        _validate_windows_data_root(resolved, selected_mode)
    return resolved


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
                "测试数据根必须位于 D:\\NetConsoleTestData\\<run-id>，且不能直接使用测试根目录"
            )
        return
    system_drive = str(os.environ.get("SystemDrive") or "C:").rstrip("\\/").casefold()
    if candidate.drive.rstrip("\\/").casefold() == system_drive:
        raise RuntimeError(f"NetConsole 数据根不得位于系统盘：{candidate}")
    forbidden_roots = [
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("APPDATA"),
        os.environ.get("TEMP"),
        os.environ.get("TMP"),
    ]
    for raw_root in forbidden_roots:
        if not raw_root:
            continue
        root = Path(raw_root).expanduser().resolve()
        if candidate == root or candidate.is_relative_to(root):
            raise RuntimeError(f"NetConsole 数据根不得位于 AppData 或系统临时目录：{candidate}")


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
