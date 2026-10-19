"""Compatibility imports for maintenance modules.

The canonical guard lives in the installed ``netconsole`` package so
workspace-external diagnostics can import it by package name.  Keep this
module as a stable compatibility path for existing in-repository tests and
maintenance callers.
"""

from netconsole.tools.diagnostic_data_root_guard import (
    DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED,
    DiagnosticDataRootBlockedError,
    create_diagnostic_path_resolver,
    require_diagnostic_test_root,
    require_diagnostic_path_resolver,
)

__all__ = [
    "DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED",
    "DiagnosticDataRootBlockedError",
    "create_diagnostic_path_resolver",
    "require_diagnostic_test_root",
    "require_diagnostic_path_resolver",
]
