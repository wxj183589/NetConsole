from __future__ import annotations

import os
import sys
import json
import sqlite3
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


def test_data_root_base(repository_root: Path | None = None) -> Path:
    """Resolve the canonical isolated test-data base for a source checkout.

    Test data belongs beside the repository checkout so the same rule works on
    a developer machine and on a portable CI runner. Packaged production
    startup never calls this resolver because it uses a non-test runtime mode.
    Frozen test smoke may explicitly pass the source checkout through
    ``NETCONSOLE_PROJECT_ROOT``; the override is ignored outside test mode so
    a packaged production process cannot derive a test root from its cwd.
    """

    if repository_root is None:
        configured_project_root = str(
            os.environ.get("NETCONSOLE_PROJECT_ROOT") or ""
        ).strip()
        configured_runtime_mode = str(
            os.environ.get("NETCONSOLE_RUNTIME_MODE") or ""
        ).strip().casefold()
        if configured_project_root and configured_runtime_mode == RuntimeMode.TEST.value:
            repository_root = Path(configured_project_root)
    return (repository_workspace_root(repository_root) / "test-data" / "NetConsole").resolve()


def repository_workspace_root(repository_root: Path | None = None) -> Path:
    """Resolve the checkout's portable workspace parent.

    CI and local checkouts may live at different absolute paths.  Shared
    maintenance/test helpers use this parent for bounded evidence and test
    roots instead of assuming a machine-specific development directory.
    """

    source_root = Path(repository_root or _source_project_root()).expanduser().resolve()
    return source_root.parent


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
    require a marker file. If an explicit target root does carry a persistent
    marker, it still wins over the process mode so TEST cannot downgrade a
    Production root. Persistent roots normally carry a valid marker. For
    compatibility with existing business roots created before the marker
    contract, a root with a verified storage manifest and standard directory
    layout may start without writing a new marker; it is treated as a
    production persistent root so production write and authority gates remain
    fail-closed.
    """

    selected_runtime_mode = runtime_mode()
    if selected_runtime_mode is RuntimeMode.TEST and data_root is None:
        return DataEnvironmentInfo(DataEnvironmentMode.TEST)
    root = Path(data_root) if data_root is not None else data_root_for_environment()
    marker = root / RUNTIME_MODE_FILE_NAME
    if selected_runtime_mode is RuntimeMode.TEST and not marker.is_file():
        return DataEnvironmentInfo(DataEnvironmentMode.TEST)
    if not marker.exists():
        if _has_verified_unmarked_persistent_layout(root):
            return DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True)
        raise RuntimeError(
            f"数据根缺少 {RUNTIME_MODE_FILE_NAME}，且未发现可验证的持久化存储清单：{root}。"
            "请确认数据目录包含原有业务目录和 config/storage-manifest.json。"
        )
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"数据根缺少 {RUNTIME_MODE_FILE_NAME}，拒绝启动：{root}。"
            "请先使用受控初始化/环境标记流程明确标记 production 或 development。"
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


def prepare_startup_environment(data_root: Path) -> DataEnvironmentInfo:
    """Validate or recover startup metadata for an explicitly configured root.

    Source Electron/PyCharm runs may point at a root created before the
    runtime marker contract.  When the process explicitly selected
    ``desktop-development`` and supplied ``NETCONSOLE_DATA_ROOT``, missing
    metadata can be reconstructed after checking the root contents and every
    existing site database.  Production and packaged roots remain fail closed;
    this helper never selects a different root and never creates a site.
    """

    root = validate_data_root(Path(data_root), mode=runtime_mode())
    if runtime_mode() is RuntimeMode.TEST:
        return DataEnvironmentInfo(DataEnvironmentMode.TEST)
    marker = root / RUNTIME_MODE_FILE_NAME
    manifest = root / "config" / "storage-manifest.json"
    if marker.is_file() or manifest.is_file():
        return data_environment(root)
    if not _source_development_root_is_explicitly_selected():
        return data_environment(root)
    _recover_source_development_metadata(root)
    return data_environment(root)


def _source_development_root_is_explicitly_selected() -> bool:
    return (
        str(os.environ.get("NETCONSOLE_RUNTIME_MODE") or "").strip().casefold()
        == "desktop-development"
        and bool(str(os.environ.get("NETCONSOLE_DATA_ROOT") or "").strip())
    )


def _recover_source_development_metadata(root: Path) -> None:
    """Atomically restore only metadata for a verified source development root."""

    allowed_entries = {
        "agents",
        "backups",
        "config",
        "migrations",
        "runtime",
        "sites",
        "staging",
        ".trash",
    }
    try:
        entries = tuple(root.iterdir()) if root.exists() else ()
    except OSError as exc:
        raise RuntimeError(f"开发数据根无法读取，拒绝恢复启动元数据：{root}") from exc
    unknown = [entry.name for entry in entries if entry.name.casefold() not in allowed_entries]
    if unknown:
        raise RuntimeError(
            "开发数据根包含未识别内容，拒绝猜测数据环境：" + ", ".join(sorted(unknown))
        )
    _validate_existing_development_metadata(root)
    _validate_existing_development_sites(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / RUNTIME_MODE_FILE_NAME
    temporary = root / f".{RUNTIME_MODE_FILE_NAME}.{uuid.uuid4().hex}.tmp"
    payload = asdict(
        DataEnvironmentInfo(
            DataEnvironmentMode.DEVELOPMENT,
            created_from="source-development-startup-recovery",
            created_time="",
            readonly_warning=False,
        )
    )
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)

    # A source-development recovery must leave the same metadata contract as
    # a normal startup.  The manifest is created only after the existing
    # registry/sites have been validated above; it never discovers a site or
    # copies business data.  If this fails, startup remains fail-closed.
    from netconsole.core.paths import PathResolver
    from netconsole.core.storage_manifest import prepare_storage_manifest

    prepare_storage_manifest(PathResolver(data_root=root))


def _validate_existing_development_sites(root: Path) -> None:
    sites = root / "sites"
    if not sites.exists():
        return
    if not sites.is_dir() or sites.is_symlink():
        raise RuntimeError("开发数据根 sites 目录不可安全读取")
    for site in sites.iterdir():
        if site.is_symlink() or not site.is_dir():
            raise RuntimeError(f"开发数据根存在不可验证的局点项：{site.name}")
        database = site / "db" / "devices.db"
        if not database.exists():
            raise RuntimeError(f"既有局点缺少 devices.db，拒绝恢复元数据：{site.name}")
        if database.is_symlink() or not database.is_file() or database.stat().st_size == 0:
            raise RuntimeError(f"既有局点 devices.db 不可安全读取：{site.name}")
        try:
            from netconsole.core.database import CURRENT_SCHEMA_VERSION

            with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
                schema = connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'schema_metadata'"
                ).fetchone()
                schema_version = connection.execute(
                    "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
                ).fetchone() if schema is not None else None
        except sqlite3.Error as exc:
            raise RuntimeError(f"既有局点 schema/完整性无法验证：{site.name}") from exc
        if not result or str(result[0]).casefold() != "ok":
            raise RuntimeError(f"既有局点 schema/完整性检查失败：{site.name}")
        if schema is None or not schema_version or str(schema_version[0]) != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(f"既有局点 schema 不兼容，拒绝恢复元数据：{site.name}")


def _validate_existing_development_metadata(root: Path) -> None:
    """Check existing JSON authorities without discovering or writing sites."""

    config = root / "config"
    if config.exists() and (config.is_symlink() or not config.is_dir()):
        raise RuntimeError("开发数据根 config 目录不可安全读取")
    if not config.is_dir():
        return

    registry = config / "site_registry.json"
    if registry.exists():
        if registry.is_symlink() or not registry.is_file():
            raise RuntimeError("既有 SiteRegistry 路径不可安全读取")
        try:
            value = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError("既有 SiteRegistry 无法读取或不是有效 JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("sites"), list):
            raise RuntimeError("既有 SiteRegistry 结构无效，拒绝恢复元数据")
        seen_ids: set[str] = set()
        seen_paths: set[Path] = set()
        sites_root = (root / "sites").resolve()
        for item in value["sites"]:
            if not isinstance(item, dict):
                raise RuntimeError("既有 SiteRegistry 包含无效记录")
            site_id = str(item.get("site_id") or "").strip()
            relative = Path(str(item.get("relative_path") or ""))
            if (
                not site_id
                or site_id.casefold() in seen_ids
                or relative.is_absolute()
                or len(relative.parts) != 2
                or relative.parts[0].casefold() != "sites"
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise RuntimeError("既有 SiteRegistry 包含越界或重复局点记录")
            candidate = (root / relative).resolve()
            if candidate.parent != sites_root or candidate in seen_paths:
                raise RuntimeError("既有 SiteRegistry 包含越界或重复局点记录")
            if candidate.is_symlink() or not candidate.is_dir():
                raise RuntimeError(f"既有 SiteRegistry 局点目录不可验证：{site_id}")
            seen_ids.add(site_id.casefold())
            seen_paths.add(candidate)

    for application in (config / "application.json", config / "app.json"):
        if not application.exists():
            continue
        if application.is_symlink() or not application.is_file():
            raise RuntimeError(f"既有应用配置路径不可安全读取：{application.name}")
        try:
            value = json.loads(application.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"既有应用配置无效：{application.name}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"既有应用配置结构无效：{application.name}")


def _has_verified_unmarked_persistent_layout(root: Path) -> bool:
    required_directories = ("config", "sites", "runtime")
    if not all((root / name).is_dir() for name in required_directories):
        return False
    manifest = root / "config" / "storage-manifest.json"
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    configured_root = str(value.get("data_root") or "").strip()
    if not configured_root:
        return False
    try:
        return Path(configured_root).expanduser().resolve() == root.resolve()
    except (OSError, RuntimeError, ValueError):
        return False


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


def require_non_production_data_root(
    data_root: Path,
    operation: str,
) -> DataEnvironmentInfo:
    """Allow an explicitly marked development/test root and fail closed otherwise."""

    resolved = Path(data_root).expanduser().resolve()
    if runtime_mode() is RuntimeMode.TEST:
        try:
            resolved = validate_data_root(resolved, mode=RuntimeMode.TEST)
        except RuntimeError as exc:
            raise ProductionWriteBlockedError(
                f"已阻止仅开发/隔离操作触及非隔离测试数据根：{operation}。"
            ) from exc
    info = data_environment(resolved)
    if info.is_production:
        raise ProductionWriteBlockedError(
            f"已阻止仅开发/隔离操作触及 Production 数据根：{operation}。"
        )
    return info


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
        test_root = test_data_root_base()
        if candidate == test_root or not candidate.is_relative_to(test_root):
            raise RuntimeError(
                f"测试数据根必须位于 {test_root}{os.sep}<run-id>，且不能直接使用测试根目录"
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
