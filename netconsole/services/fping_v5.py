from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.ping.fping_v5_runner import check_fping_v5_available
from netconsole.services.tool_path_resolver import resolve_tool_path


@dataclass(frozen=True)
class FpingToolStatus:
    path: Path | None
    found: bool
    version: str = ""
    unknown_version: bool = False
    output: str = ""
    json_supported: bool = False


def find_fping_tool(paths: PathResolver, settings: SettingsStore | None = None) -> Path | None:
    return resolve_tool_path("fping_v5", paths, settings=settings)


def detect_fping_version(path: Path) -> FpingToolStatus:
    result = check_fping_v5_available(fping_path=path)
    version = ""
    if "Version" in result.version_output:
        version = result.version_output.rsplit("Version", 1)[-1].strip()
    return FpingToolStatus(
        path=path,
        found=result.available,
        version=version,
        unknown_version=not bool(version),
        output=result.version_output or result.error,
        json_supported=result.json_supported,
    )
