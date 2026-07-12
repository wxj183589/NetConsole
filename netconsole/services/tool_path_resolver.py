from __future__ import annotations

import shutil
import sys
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
    "fping_v5": ToolDefinition(
        relative_path=Path("fping_v5") / "fping.exe",
        setting_keys=("online_mr.fping_path",),
        path_names=("fping.exe", "fping"),
    ),
    "iperf3": ToolDefinition(
        relative_path=Path("iperf") / "iperf3.exe",
        setting_keys=("network_tools/iperf_path",),
        path_names=("iperf3.exe", "iperf3"),
    ),
    "ipop": ToolDefinition(
        relative_path=Path("IPOP_v4.1") / "IPOP.EXE",
        setting_keys=(),
        path_names=(),
    ),
}


def resolve_tool_path(
    tool_name: str,
    paths: PathResolver | None = None,
    *,
    settings: SettingsStore | None = None,
    custom_path: str | Path | None = None,
    project_root: Path | None = None,
) -> Path | None:
    definition = TOOL_DEFINITIONS.get(tool_name)
    if definition is None:
        raise ValueError(f"Unsupported external tool: {tool_name}")

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
    definition = TOOL_DEFINITIONS.get(tool_name)
    if definition is None:
        raise ValueError(f"Unsupported external tool: {tool_name}")

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
    for tools_root in _internal_tool_roots(app_root):
        candidates.append(tools_root / definition.relative_path)

    if not _is_compiled_runtime():
        candidates.append((project_root or _development_project_root(app_root)) / "tools" / definition.relative_path)
        candidates.append(app_root / "tools" / definition.relative_path)
    return _deduplicate_paths(candidates)


def _internal_tool_roots(app_root: Path) -> Iterable[Path]:
    yield app_root / "_internal" / "tools"
    yield app_root / "tools"
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield Path(meipass) / "tools"
    try:
        package_root = Path(__file__).resolve().parents[2]
        yield package_root / "tools"
        yield package_root / "_internal" / "tools"
    except OSError:
        return


def _is_compiled_runtime() -> bool:
    return bool(getattr(sys, "frozen", False) or globals().get("__compiled__"))


def _source_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _development_project_root(app_root: Path) -> Path:
    if (app_root / "tools").exists() or (app_root / "netconsole").exists():
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
