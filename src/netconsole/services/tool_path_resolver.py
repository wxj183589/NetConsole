from __future__ import annotations

import shutil
import sys
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore


@dataclass(frozen=True)
class ToolDefinition:
    relative_path: Path
    setting_keys: tuple[str, ...]
    path_names: tuple[str, ...]


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "fping": ToolDefinition(
        relative_path=Path("fping") / "fping.exe",
        setting_keys=("online_mr.fping_path",),
        path_names=("fping.exe", "fping"),
    ),
    "iperf3": ToolDefinition(
        relative_path=Path("iperf3") / "iperf3.exe",
        setting_keys=("network_tools/iperf_path",),
        path_names=("iperf3.exe", "iperf3"),
    ),
    "ipop": ToolDefinition(
        relative_path=Path("ipop") / "IPOP.EXE",
        setting_keys=("external_tools/ipop_path",),
        path_names=(),
    ),
}

TOOL_NAME_ALIASES = {"fping": "fping", "fping_v5": "fping", "iperf": "iperf3", "iperf3": "iperf3", "ipop": "ipop"}


def get_tools_root(paths: PathResolver | None = None) -> Path:
    return (paths or PathResolver()).app_root / "tools"


def platform_tools_dir_name(*, system_name: str | None = None, machine: str | None = None) -> str:
    system = (system_name or platform.system()).strip().casefold()
    architecture = (machine or platform.machine()).strip().casefold()
    if system == "windows" and architecture in {"amd64", "x86_64", "x64"}:
        return "windows-x64"
    raise RuntimeError(f"不支持当前工具平台：{system or 'unknown'} / {architecture or 'unknown'}")


def get_platform_tools_dir(
    paths: PathResolver | None = None,
    *,
    system_name: str | None = None,
    machine: str | None = None,
) -> Path:
    return get_tools_root(paths) / platform_tools_dir_name(system_name=system_name, machine=machine)


def get_tool_dir(tool_name: str, paths: PathResolver | None = None) -> Path:
    definition = _tool_definition(tool_name)
    return get_platform_tools_dir(paths) / definition.relative_path.parent


def get_tool_executable(
    tool_name: str,
    paths: PathResolver | None = None,
    *,
    settings: SettingsStore | None = None,
    custom_path: str | Path | None = None,
    project_root: Path | None = None,
) -> Path | None:
    return resolve_tool_path(
        tool_name,
        paths,
        settings=settings,
        custom_path=custom_path,
        project_root=project_root,
    )


def resolve_tool_path(
    tool_name: str,
    paths: PathResolver | None = None,
    *,
    settings: SettingsStore | None = None,
    custom_path: str | Path | None = None,
    project_root: Path | None = None,
) -> Path | None:
    definition = _tool_definition(tool_name)

    paths = paths or PathResolver()
    for candidate in candidate_tool_paths(
        tool_name,
        paths,
        settings=settings,
        custom_path=custom_path,
        project_root=project_root,
    ):
        resolved = _resolve_existing_file(candidate)
        if resolved is not None:
            return resolved

    if not _is_compiled_runtime():
        for name in definition.path_names:
            resolved = shutil.which(name)
            if resolved:
                return Path(resolved).resolve()
    return None


def candidate_tool_paths(
    tool_name: str,
    paths: PathResolver,
    *,
    settings: SettingsStore | None = None,
    custom_path: str | Path | None = None,
    project_root: Path | None = None,
) -> list[Path]:
    definition = _tool_definition(tool_name)

    candidates: list[Path] = []
    if custom_path:
        candidates.append(Path(custom_path))

    store = settings
    if store is None:
        try:
            store = SettingsStore(paths)
        except Exception:
            store = None
    if store is not None:
        for key in definition.setting_keys:
            try:
                value = str(store.get_value(key, "") or "").strip()
            except Exception:
                value = ""
            if value:
                candidates.append(Path(value))

    app_root = paths.app_root
    for tools_root in _platform_tool_roots(app_root, definition):
        candidates.append(tools_root / definition.relative_path)

    if not _is_compiled_runtime():
        development_root = project_root or _development_project_root(app_root)
        source_root = development_root / "tools" if definition is TOOL_DEFINITIONS["ipop"] else development_root / "resources" / "tools"
        candidates.append(source_root / platform_tools_dir_name() / definition.relative_path)
    return _deduplicate_paths(candidates)


def _platform_tool_roots(app_root: Path, definition: ToolDefinition) -> Iterable[Path]:
    platform_dir = platform_tools_dir_name()
    yield app_root / "tools" / platform_dir
    yield app_root / "_internal" / "tools" / platform_dir
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield Path(meipass) / "tools" / platform_dir
    try:
        package_root = Path(__file__).resolve().parents[3]
        yield package_root / "tools" / platform_dir
        yield package_root / "_internal" / "tools" / platform_dir
    except OSError:
        return


def _tool_definition(tool_name: str) -> ToolDefinition:
    normalized = TOOL_NAME_ALIASES.get(str(tool_name).strip().casefold(), str(tool_name).strip().casefold())
    definition = TOOL_DEFINITIONS.get(normalized)
    if definition is None:
        raise ValueError(f"Unsupported external tool: {tool_name}")
    return definition


def _is_compiled_runtime() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def _source_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _development_project_root(app_root: Path) -> Path:
    if (app_root / "resources" / "tools").exists() or (app_root / "src" / "netconsole").exists():
        return app_root
    return _source_project_root()


def _resolve_existing_file(candidate: Path) -> Path | None:
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    if resolved.exists() and resolved.is_file():
        return resolved
    return None


def _deduplicate_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result
