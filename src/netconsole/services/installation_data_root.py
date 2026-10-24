from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from netconsole.core.data_root_configuration import (
    DataRootConfigurationError,
    validate_installation_data_root,
)
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import write_data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.core.storage_manifest import prepare_storage_manifest
from netconsole.services.site_storage import SiteApplicationService
from netconsole.services.storage_production_authority import (
    resolve_storage_root_authority,
)


_CLEAN_INSTALL_PROTECTED_ENTRIES = frozenset(
    {
        "agents",
        "app.json",
        "application.json",
        "backups",
        "bootstrap.json",
        "config",
        "data",
        "devices.db",
        "migrations",
        "runtime",
        "runtime_mode.json",
        "site_registry.json",
        "sites",
        "staging",
    }
)


def validate_existing_installation_data_root(
    candidate: Path,
    *,
    installation_root: Path | None = None,
    startup_site_resolver: Callable[[PathResolver], object] | None = None,
    stage_callback: Callable[[str], None] | None = None,
) -> Path:
    """Validate an existing root without creating or repairing it."""

    if stage_callback is not None:
        stage_callback("validate-existing-root")
    raw_candidate = Path(candidate).expanduser()
    if not raw_candidate.exists() or not raw_candidate.is_dir():
        raise DataRootConfigurationError(
            "历史数据目录不可访问；请恢复原磁盘，或改选全新安装"
        )
    root = validate_installation_data_root(
        raw_candidate, installation_root=installation_root
    )

    resolve_storage_root_authority(root)
    if not (root / "config" / "site_registry.json").is_file():
        raise DataRootConfigurationError(
            "历史数据目录缺少 site_registry.json；不会自动生成新的空局点"
        )
    if startup_site_resolver is None:
        raise DataRootConfigurationError("缺少 Production 局点校验入口")
    if stage_callback is not None:
        stage_callback("validate-existing-site-registry")
    previous_data_root = os.environ.get("NETCONSOLE_DATA_ROOT")
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    try:
        startup_site_resolver(PathResolver(data_root=root))
    finally:
        if previous_data_root is None:
            os.environ.pop("NETCONSOLE_DATA_ROOT", None)
        else:
            os.environ["NETCONSOLE_DATA_ROOT"] = previous_data_root
    return root


def prepare_installation_data_root(
    candidate: Path,
    *,
    installation_root: Path | None = None,
    clean_install: bool = False,
    stage_callback: Callable[[str], None] | None = None,
) -> Path:
    """Validate and initialize an installer-selected root before publication."""

    if stage_callback is not None:
        stage_callback("validate-installation-root")
    root = validate_installation_data_root(
        candidate, installation_root=installation_root
    )
    if clean_install:
        if stage_callback is not None:
            stage_callback("clean-install-business-data-check")
        _reject_existing_netconsole_business_data(root)

    paths = PathResolver(data_root=root)
    preexisting_entries = {entry.name for entry in root.iterdir()}
    manifest_before = _read_optional_bytes(paths.storage_manifest_path)
    runtime_mode_before = _read_optional_bytes(paths.runtime_mode_path)
    first_run_lock = paths.runtime_dir / "locks" / "first-run-initialization.lock"
    first_run_lock_before = _read_optional_bytes(first_run_lock)
    previous_data_root = os.environ.get("NETCONSOLE_DATA_ROOT")
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)
    try:
        if stage_callback is not None:
            stage_callback("storage-manifest")
        prepare_storage_manifest(paths)
        if not paths.runtime_mode_path.exists():
            if stage_callback is not None:
                stage_callback("runtime-mode")
            write_data_environment(
                root,
                DataEnvironmentInfo(
                    DataEnvironmentMode.PRODUCTION,
                    created_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    readonly_warning=True,
                ),
            )
        if stage_callback is not None:
            stage_callback("first-run-site")
        # The installer has not published HKLM yet.  Configure this candidate
        # only for the short-lived first-run validation process.
        SiteApplicationService(paths).initialize_first_run_site(
            allow_unrelated_root_entries=clean_install
        )
    except BaseException:
        _rollback_failed_installation_attempt(
            root,
            paths,
            preexisting_entries=preexisting_entries,
            manifest_before=manifest_before,
            runtime_mode_before=runtime_mode_before,
            first_run_lock=first_run_lock,
            first_run_lock_before=first_run_lock_before,
        )
        raise
    finally:
        if previous_data_root is None:
            os.environ.pop("NETCONSOLE_DATA_ROOT", None)
        else:
            os.environ["NETCONSOLE_DATA_ROOT"] = previous_data_root
    return root


def _read_optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def _restore_optional_bytes(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.rollback.tmp")
    try:
        temporary.write_bytes(previous)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _rollback_failed_installation_attempt(
    root: Path,
    paths: PathResolver,
    *,
    preexisting_entries: set[str],
    manifest_before: bytes | None,
    runtime_mode_before: bytes | None,
    first_run_lock: Path,
    first_run_lock_before: bytes | None,
) -> None:
    """Remove only metadata and empty directories created by this attempt."""

    try:
        _restore_optional_bytes(paths.storage_manifest_path, manifest_before)
        _restore_optional_bytes(paths.runtime_mode_path, runtime_mode_before)
        _restore_optional_bytes(first_run_lock, first_run_lock_before)
    except OSError:
        # The original exception remains authoritative; a later retry will
        # fail closed if rollback could not restore an existing file.
        pass

    try:
        candidates = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for path in candidates:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if not relative.parts or relative.parts[0] in preexisting_entries:
                continue
            try:
                path.rmdir()
            except OSError:
                pass
    except OSError:
        pass


def _reject_existing_netconsole_business_data(root: Path) -> None:
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise DataRootConfigurationError("清洁安装目标目录无法读取") from exc
    protected = [
        entry.name
        for entry in entries
        if entry.name.casefold() in _CLEAN_INSTALL_PROTECTED_ENTRIES
        or entry.name.casefold().startswith("netconsole")
    ]
    if protected:
        raise DataRootConfigurationError(
            "清洁安装目标包含现有或不明确的 NetConsole 数据，拒绝覆盖："
            + ", ".join(sorted(protected, key=str.casefold))
        )


__all__ = [
    "prepare_installation_data_root",
    "validate_existing_installation_data_root",
]
