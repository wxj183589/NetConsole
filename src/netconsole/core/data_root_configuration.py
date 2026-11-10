from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


DATA_ROOT_REGISTRY_KEY = r"SOFTWARE\NetConsole"
DATA_ROOT_REGISTRY_VALUE = "DataRoot"
MINIMUM_DATA_ROOT_FREE_BYTES = 10 * 1024**3
RECOMMENDED_DATA_ROOT_FREE_BYTES = 100 * 1024**3


@dataclass(frozen=True)
class DataRootDiskInfo:
    """Disk facts shown to the user before a data-root decision."""

    drive_root: str
    drive_type: str
    drive_type_code: int | None
    is_system_drive: bool
    total_bytes: int | None
    free_bytes: int | None
    warnings: tuple[str, ...] = ()

    def to_public(self) -> dict[str, object]:
        return {
            "drive_root": self.drive_root,
            "drive_type": self.drive_type,
            "drive_type_code": self.drive_type_code,
            "is_system_drive": self.is_system_drive,
            "total_bytes": self.total_bytes,
            "free_bytes": self.free_bytes,
            "warnings": list(self.warnings),
        }


class DataRootConfigurationError(RuntimeError):
    """Raised when persistent NetConsole storage has not been configured."""


@dataclass(frozen=True)
class DataRootConfiguration:
    path: Path
    source: str


def read_machine_data_root() -> Path | None:
    """Read the installer-owned, machine-wide storage pointer on Windows.

    The registry contains only the root path.  It is deliberately not used by
    tests: test mode must always receive an explicit isolated environment root.
    """

    if sys.platform != "win32":
        return None
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, DATA_ROOT_REGISTRY_KEY, 0, access
        ) as key:
            value, value_type = winreg.QueryValueEx(key, DATA_ROOT_REGISTRY_VALUE)
        if value_type not in {winreg.REG_SZ, winreg.REG_EXPAND_SZ} or not isinstance(
            value, str
        ):
            return None
        candidate = os.path.expandvars(value).strip()
        path = Path(candidate).expanduser()
        return path if candidate and path.is_absolute() else None
    except (FileNotFoundError, OSError, ValueError):
        return None


def resolve_persistent_data_root(*, test_mode: bool) -> DataRootConfiguration:
    configured = str(os.environ.get("NETCONSOLE_DATA_ROOT") or "").strip()
    if configured:
        return DataRootConfiguration(Path(configured).expanduser(), "environment")
    if test_mode:
        raise DataRootConfigurationError("测试模式必须显式设置 NETCONSOLE_DATA_ROOT")
    configured_machine_root = read_machine_data_root()
    if configured_machine_root is not None:
        return DataRootConfiguration(configured_machine_root, "machine_configuration")
    raise DataRootConfigurationError(
        "尚未配置 NetConsole 数据目录。请通过安装程序选择数据存放位置；"
        "优先推荐非系统盘，也可以使用 C 盘的 C:\\ProgramData\\NetConsole\\Data，"
        "或显式设置 NETCONSOLE_DATA_ROOT。"
    )


def recommended_data_root() -> Path:
    """Return a usable first-run suggestion without assuming a D: drive."""

    if sys.platform == "win32":
        preferred = Path(r"D:\NetConsoleData")
        if preferred.drive and Path(preferred.drive + "\\").exists():
            try:
                if (
                    _windows_drive_type(preferred) == 3
                    and shutil.disk_usage(preferred.drive + "\\").free
                    >= MINIMUM_DATA_ROOT_FREE_BYTES
                ):
                    return preferred
            except (DataRootConfigurationError, OSError):
                pass
        return Path(r"C:\ProgramData\NetConsole\Data")
    return Path.home() / "NetConsoleData"


def describe_data_root_location(candidate: Path) -> DataRootDiskInfo:
    """Inspect disk type and capacity without changing the selected root."""

    root = Path(candidate).expanduser()
    drive_root = root.anchor or str(root)
    system_drive = str(os.environ.get("SystemDrive") or "C:").rstrip("\\/").casefold()
    is_system_drive = bool(root.drive) and root.drive.casefold() == system_drive
    drive_type_code: int | None = None
    drive_type = "unknown"
    warnings: list[str] = []
    if sys.platform == "win32":
        drive_type_code = _windows_drive_type(root)
        drive_type = {
            2: "removable",
            3: "fixed",
            4: "network",
            5: "cdrom",
        }.get(drive_type_code, "unavailable")
        if drive_type_code == 2:
            warnings.append("可移动磁盘可能被拔出，建议改用固定本地磁盘。")
        elif drive_type_code == 4:
            warnings.append("网络盘受连接和锁定稳定性影响，建议改用固定本地磁盘。")
        elif drive_type_code == 5:
            warnings.append("光盘或临时介质不适合持续保存业务数据。")
    try:
        usage = shutil.disk_usage(root if root.exists() else root.parent)
        total_bytes, free_bytes = usage.total, usage.free
    except OSError:
        total_bytes = free_bytes = None
    if free_bytes is not None and free_bytes < MINIMUM_DATA_ROOT_FREE_BYTES:
        warnings.append("可用空间低于 10 GB，请选择其他位置或先释放空间。")
    if is_system_drive:
        warnings.append(
            "建议将 NetConsole 业务数据存放在非系统盘，以降低系统重装或系统盘空间不足造成的数据风险。"
            "继续使用 C 盘不会影响软件正常运行。"
        )
    return DataRootDiskInfo(
        drive_root=drive_root,
        drive_type=drive_type,
        drive_type_code=drive_type_code,
        is_system_drive=is_system_drive,
        total_bytes=total_bytes,
        free_bytes=free_bytes,
        warnings=tuple(warnings),
    )


def validate_installation_data_root(
    candidate: Path, *, installation_root: Path | None = None
) -> Path:
    """Validate the root selected by the NSIS installer before committing it.

    The installer only writes HKLM after this check succeeds.  Temporary files
    are confined to the candidate itself and removed whether validation passes
    or fails; no business data or manifest is initialized here.
    """

    from netconsole.core.runtime_environment import app_root, validate_data_root

    raw_candidate = Path(candidate).expanduser()
    _reject_reparse_path_or_ancestor(raw_candidate)
    from netconsole.core.runtime_mode import RuntimeMode

    root = validate_data_root(Path(candidate), mode=RuntimeMode.DESKTOP)
    if installation_root is not None:
        installed = Path(installation_root).expanduser().resolve()
        if root == installed or root.is_relative_to(installed):
            raise DataRootConfigurationError("数据根不得位于程序安装目录")
    application_root = app_root().resolve()
    if root == application_root or root.is_relative_to(application_root):
        raise DataRootConfigurationError("数据根不得位于程序安装目录")
    if sys.platform == "win32":
        _require_windows_fixed_drive(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DataRootConfigurationError(
            _probe_failure("数据目录无法创建", exc)
        ) from exc
    _require_no_data_root_path_conflicts(root)
    free_bytes = shutil.disk_usage(root).free
    if free_bytes < MINIMUM_DATA_ROOT_FREE_BYTES:
        raise DataRootConfigurationError("数据目录可用空间不足 10 GB")
    _verify_writable_and_renamable(root)
    _verify_sqlite_locking(root)
    return root


def _reject_reparse_path_or_ancestor(candidate: Path) -> None:
    """Reject junctions/reparse points before Path.resolve() can hide them."""

    if not candidate.is_absolute():
        return
    current = candidate
    while True:
        if _is_reparse_point(current):
            raise DataRootConfigurationError(
                "数据目录或其父路径不得是符号链接或 Reparse Point"
            )
        if current.parent == current:
            return
        current = current.parent


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    except (FileNotFoundError, OSError):
        return False
    return bool(attributes & 0x400)


def _windows_drive_type(root: Path) -> int:
    try:
        import ctypes

        drive_root = f"{root.drive}\\"
        if not root.drive:
            raise DataRootConfigurationError("数据目录必须位于 Windows 磁盘路径")
        return int(ctypes.windll.kernel32.GetDriveTypeW(drive_root))
    except AttributeError as exc:
        raise DataRootConfigurationError("无法验证数据目录所在磁盘类型") from exc


def _require_windows_fixed_drive(root: Path) -> None:
    """Require an accessible fixed local drive for installer validation.

    Keep this small compatibility seam separate from the richer disk
    description API.  Installer/backend tests and callers can replace the
    policy check without having to fake all disk metadata collection.
    """

    if _windows_drive_type(root) != 3:
        raise DataRootConfigurationError("数据目录必须位于本地固定磁盘")


def _require_no_data_root_path_conflicts(root: Path) -> None:
    for name in ("config", "sites", "runtime", "agents", "migrations", "staging"):
        required = root / name
        if required.is_symlink() or (required.exists() and not required.is_dir()):
            raise DataRootConfigurationError(
                f"数据目录中的必需路径发生冲突：{name} 必须是目录"
            )
    manifest = root / "config" / "storage-manifest.json"
    if manifest.is_symlink() or (manifest.exists() and not manifest.is_file()):
        raise DataRootConfigurationError(
            "数据目录中的必需路径发生冲突：config/storage-manifest.json 必须是文件"
        )


def _verify_writable_and_renamable(root: Path) -> None:
    temporary: Path | None = None
    renamed: Path | None = None
    handle = None
    try:
        for _attempt in range(32):
            probe_id = uuid.uuid4().hex
            candidate = root / f".netconsole-install-probe-{probe_id}.tmp"
            candidate_renamed = Path(f"{candidate}.renamed")
            if candidate_renamed.exists():
                continue
            try:
                handle = candidate.open("x", encoding="ascii")
            except FileExistsError:
                continue
            except OSError as exc:
                raise DataRootConfigurationError(
                    _probe_failure("临时探测文件创建失败", exc)
                ) from exc
            temporary = candidate
            renamed = candidate_renamed
            break
        if temporary is None or renamed is None or handle is None:
            raise DataRootConfigurationError("无法生成唯一的临时探测文件名")
        try:
            handle.write("NetConsole-install-probe-v1")
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            handle = None
        except OSError as exc:
            raise DataRootConfigurationError(
                _probe_failure("临时探测文件写入或刷新失败", exc)
            ) from exc
        try:
            os.rename(temporary, renamed)
        except OSError as exc:
            raise DataRootConfigurationError(
                _probe_failure("同目录临时文件重命名失败", exc)
            ) from exc
        try:
            if renamed.read_text(encoding="ascii") != "NetConsole-install-probe-v1":
                raise DataRootConfigurationError("重命名后的临时文件内容校验失败")
        except OSError as exc:
            raise DataRootConfigurationError(
                _probe_failure("重命名后的临时文件读取失败", exc)
            ) from exc
    finally:
        if handle is not None:
            handle.close()
        cleanup_errors: list[OSError] = []
        for path in (temporary, renamed):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append(exc)
        if cleanup_errors and sys.exc_info()[0] is None:
            raise DataRootConfigurationError(
                _probe_failure("临时探测文件清理失败", cleanup_errors[0])
            )


def _probe_failure(step: str, error: OSError) -> str:
    code = getattr(error, "winerror", None)
    if code is None:
        code = getattr(error, "errno", None)
    return f"{step}（Windows 错误码：{code if code is not None else 'unknown'}）"


def _verify_sqlite_locking(root: Path) -> None:
    database = root / f".netconsole-install-lock-{uuid.uuid4().hex}.sqlite"
    first: sqlite3.Connection | None = None
    second: sqlite3.Connection | None = None
    try:
        first = sqlite3.connect(database, timeout=1)
        first.execute("CREATE TABLE validation (value INTEGER)")
        first.execute("BEGIN IMMEDIATE")
        second = sqlite3.connect(database, timeout=0.05)
        try:
            second.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            return
        raise DataRootConfigurationError("数据目录不支持 SQLite 写锁")
    except sqlite3.Error as exc:
        raise DataRootConfigurationError("数据目录无法创建 SQLite 数据库") from exc
    finally:
        if second is not None:
            second.close()
        if first is not None:
            first.close()
        for suffix in ("", "-wal", "-shm", "-journal"):
            (root / f"{database.name}{suffix}").unlink(missing_ok=True)


__all__ = [
    "DATA_ROOT_REGISTRY_KEY",
    "DATA_ROOT_REGISTRY_VALUE",
    "DataRootConfiguration",
    "DataRootDiskInfo",
    "DataRootConfigurationError",
    "MINIMUM_DATA_ROOT_FREE_BYTES",
    "RECOMMENDED_DATA_ROOT_FREE_BYTES",
    "describe_data_root_location",
    "recommended_data_root",
    "read_machine_data_root",
    "resolve_persistent_data_root",
    "validate_installation_data_root",
]
