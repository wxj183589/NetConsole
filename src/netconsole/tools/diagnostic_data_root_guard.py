"""Fail-closed data-root guard for disposable diagnostic tools.

This module is intentionally limited to diagnostic/test entry points.  It is
not used by Electron, ApplicationService, database maintenance, or shared
business repositories.  It lives in the installed ``netconsole`` package so
workspace-external one-off diagnostics can import it without relying on the
checkout being their Python module root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from netconsole.core.runtime_mode import RuntimeMode


DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED = (
    "DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED"
)
_PRODUCTION_WRITE_ENV = "NETCONSOLE_ALLOW_PRODUCTION_WRITE"


class DiagnosticDataRootBlockedError(RuntimeError):
    """Raised before a diagnostic tool may create directories or databases."""

    code = DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED

    def __init__(self, reason: str) -> None:
        super().__init__(f"{self.code}: {reason}")
        self.reason = reason


def require_diagnostic_test_root(
    data_root: str | os.PathLike[str] | None,
    *,
    repository_root: str | os.PathLike[str] | None,
    runtime_mode: RuntimeMode | str | None,
    production_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Validate an explicit disposable TEST root before any write side effect.

    ``repository_root`` and ``runtime_mode`` are deliberately required as
    keyword arguments.  A diagnostic caller must not infer either value from
    the current working directory or from the normal production environment.
    The accepted root is exactly one run directory below the canonical
    ``<repository-parent>/test-data/NetConsole`` base.
    """

    if _normalise_runtime_mode(runtime_mode) is not RuntimeMode.TEST:
        _blocked("runtime mode must be explicitly TEST")

    if str(os.environ.get(_PRODUCTION_WRITE_ENV) or "").strip() == "1":
        _blocked("production write authorization is not accepted by diagnostics")

    raw_root = str(data_root or "").strip()
    if not raw_root:
        _blocked("data_root is required and must be explicit")

    candidate_input = Path(raw_root).expanduser()
    if not candidate_input.is_absolute():
        _blocked("data_root must be an absolute path")

    source_root = _resolve_path(repository_root, "repository_root")
    configured_production_root = _resolve_production_root(production_root)
    _reject_reparse_ancestors(candidate_input)

    candidate = _resolve_path(candidate_input, "data_root")
    test_base = (source_root.parent / "test-data" / "NetConsole").resolve()
    if not _is_same_or_child(candidate, test_base) or candidate == test_base:
        _blocked(
            "data_root must be one explicit run directory below "
            f"{test_base}"
        )

    relative = candidate.relative_to(test_base)
    if len(relative.parts) != 1 or relative.parts[0] in {".", "..", ""}:
        _blocked("data_root must identify exactly one TEST run directory")

    if _is_same_or_child(candidate, configured_production_root) or _is_same_or_child(
        configured_production_root, candidate
    ):
        _blocked("data_root overlaps the configured production data root")

    if candidate.exists() and not candidate.is_dir():
        _blocked("data_root exists but is not a directory")

    return candidate


def _normalise_runtime_mode(value: RuntimeMode | str | None) -> RuntimeMode | None:
    if isinstance(value, RuntimeMode):
        return value
    if value is None:
        return None
    try:
        return RuntimeMode(str(value).strip().casefold())
    except ValueError:
        return None


def _resolve_production_root(
    production_root: str | os.PathLike[str] | None,
) -> Path:
    if production_root is not None and str(production_root).strip():
        return _resolve_path(production_root, "production_root")

    try:
        from netconsole.core.data_root_configuration import read_machine_data_root

        configured = read_machine_data_root() if sys.platform == "win32" else None
    except (ImportError, OSError, RuntimeError, ValueError):
        configured = None
    if configured is None:
        _blocked("cannot determine the configured production data root")
    return _resolve_path(configured, "production_root")


def _resolve_path(value: str | os.PathLike[str] | None, label: str) -> Path:
    if value is None or not str(value).strip():
        _blocked(f"{label} is required")
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        _blocked(f"invalid {label}: {exc}")


def _is_same_or_child(candidate: Path, parent: Path) -> bool:
    try:
        return candidate == parent or candidate.is_relative_to(parent)
    except (AttributeError, ValueError):
        candidate_text = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        parent_text = os.path.normcase(os.path.abspath(os.fspath(parent)))
        try:
            return os.path.commonpath((candidate_text, parent_text)) == parent_text
        except ValueError:
            return False


def _reject_reparse_ancestors(path: Path) -> None:
    """Reject existing links/junctions before path resolution can hide them."""

    current = path
    while True:
        try:
            stat_result = current.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _blocked(f"cannot inspect data_root path: {exc}")
        else:
            attributes = int(getattr(stat_result, "st_file_attributes", 0) or 0)
            if current.is_symlink() or attributes & 0x400:
                _blocked("data_root or an ancestor is a symlink/junction")
        if current.parent == current:
            return
        current = current.parent


def _blocked(reason: str) -> None:
    raise DiagnosticDataRootBlockedError(reason)


__all__ = [
    "DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED",
    "DiagnosticDataRootBlockedError",
    "require_diagnostic_test_root",
]
