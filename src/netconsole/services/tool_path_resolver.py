from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.services.settings_tool_validation import (
    SettingsToolPathError,
    validate_settings_tool_path,
)


@dataclass(frozen=True)
class ToolDefinition:
    relative_path: Path
    setting_keys: tuple[str, ...]
    path_names: tuple[str, ...]
    mode_key: str | None = None
    builtin_companions: tuple[str, ...] = ()


NetworkToolSource = Literal["builtin", "custom"]
NetworkToolMode = Literal["builtin", "custom"]


@dataclass(frozen=True)
class NetworkToolResolution:
    component_name: str
    mode: NetworkToolMode
    source: NetworkToolSource
    configured_path: str
    effective_path: Path | None
    available: bool
    fallback_used: bool = False
    fallback_reason: str = ""
    validation_message: str = ""


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "fping": ToolDefinition(
        relative_path=Path("fping") / "fping.exe",
        setting_keys=("online_mr.fping_path",),
        path_names=("fping.exe", "fping"),
        mode_key="network_components/fping_mode",
        builtin_companions=("cygwin1.dll",),
    ),
    "iperf3": ToolDefinition(
        relative_path=Path("iperf3") / "iperf3.exe",
        setting_keys=("network_tools/iperf_path",),
        path_names=("iperf3.exe", "iperf3"),
        mode_key="network_components/iperf3_mode",
        builtin_companions=("cygwin1.dll", "cygcrypto-3.dll", "cygz.dll"),
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
    normalized = _normalized_tool_name(tool_name)
    if normalized in {"fping", "iperf3"}:
        return resolve_network_tool(
            normalized,
            paths,
            settings=settings,
            custom_path=custom_path,
            project_root=project_root,
        ).effective_path

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


def resolve_network_tool(
    tool_name: str,
    paths: PathResolver | None = None,
    *,
    settings: SettingsStore | None = None,
    custom_path: str | Path | None = None,
    project_root: Path | None = None,
) -> NetworkToolResolution:
    normalized = _normalized_tool_name(tool_name)
    if normalized not in {"fping", "iperf3"}:
        raise ValueError(f"Unsupported network component: {tool_name}")
    definition = TOOL_DEFINITIONS[normalized]
    resolver = paths or PathResolver()
    store = settings or _load_settings(resolver)
    configured_path = str(custom_path or _configured_path(definition, store) or "").strip()
    mode = _configured_mode(definition, store, configured_path, explicit_custom=custom_path is not None)

    custom, custom_error = _validate_custom_component(normalized, configured_path)
    builtin, builtin_error = _resolve_builtin_component(
        normalized,
        definition,
        resolver,
        project_root=project_root,
    )

    if mode == "custom" and custom is not None:
        return NetworkToolResolution(
            component_name=normalized,
            mode=mode,
            source="custom",
            configured_path=configured_path,
            effective_path=custom,
            available=True,
            validation_message="自定义组件可用",
        )
    if mode == "builtin" and builtin is not None:
        return NetworkToolResolution(
            component_name=normalized,
            mode=mode,
            source="builtin",
            configured_path=configured_path,
            effective_path=builtin,
            available=True,
            validation_message="内置组件可用",
        )
    if mode == "custom" and builtin is not None:
        reason = f"自定义组件不可用，已回退到内置组件：{custom_error}"
        return NetworkToolResolution(
            component_name=normalized,
            mode=mode,
            source="builtin",
            configured_path=configured_path,
            effective_path=builtin,
            available=True,
            fallback_used=True,
            fallback_reason=reason,
            validation_message=reason,
        )
    if mode == "builtin" and custom is not None:
        reason = f"内置组件不可用，已回退到自定义组件：{builtin_error}"
        return NetworkToolResolution(
            component_name=normalized,
            mode=mode,
            source="custom",
            configured_path=configured_path,
            effective_path=custom,
            available=True,
            fallback_used=True,
            fallback_reason=reason,
            validation_message=reason,
        )

    message = f"内置和自定义组件均不可用。内置组件：{builtin_error}；自定义组件：{custom_error}"
    return NetworkToolResolution(
        component_name=normalized,
        mode=mode,
        source=mode,
        configured_path=configured_path,
        effective_path=None,
        available=False,
        validation_message=message,
    )


def candidate_tool_paths(
    tool_name: str,
    paths: PathResolver,
    *,
    settings: SettingsStore | None = None,
    custom_path: str | Path | None = None,
    project_root: Path | None = None,
) -> list[Path]:
    definition = _tool_definition(tool_name)
    normalized = _normalized_tool_name(tool_name)

    if normalized in {"fping", "iperf3"}:
        store = settings or _load_settings(paths)
        configured_path = str(custom_path or _configured_path(definition, store) or "").strip()
        mode = _configured_mode(definition, store, configured_path, explicit_custom=custom_path is not None)
        custom_candidates = [Path(configured_path)] if configured_path else []
        builtin_candidates = _builtin_tool_paths(definition, paths, project_root=project_root)
        ordered = (
            [*custom_candidates, *builtin_candidates]
            if mode == "custom"
            else [*builtin_candidates, *custom_candidates]
        )
        return _deduplicate_paths(ordered)

    candidates: list[Path] = []
    if custom_path:
        candidates.append(Path(custom_path))

    store = settings or _load_settings(paths)
    if store is not None:
        for key in definition.setting_keys:
            try:
                value = str(store.get_value(key, "") or "").strip()
            except Exception:
                value = ""
            if value:
                try:
                    candidates.append(validate_settings_tool_path(_settings_tool_id(tool_name), value))
                except SettingsToolPathError:
                    continue

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


def _builtin_tool_paths(
    definition: ToolDefinition,
    paths: PathResolver,
    *,
    project_root: Path | None,
) -> list[Path]:
    candidates = [
        root / definition.relative_path
        for root in _platform_tool_roots(paths.app_root, definition)
    ]
    if not _is_compiled_runtime():
        development_root = project_root or _development_project_root(paths.app_root)
        candidates.append(
            development_root / "resources" / "tools" / platform_tools_dir_name() / definition.relative_path
        )
    return _deduplicate_paths(candidates)


def _resolve_builtin_component(
    tool_name: str,
    definition: ToolDefinition,
    paths: PathResolver,
    *,
    project_root: Path | None,
) -> tuple[Path | None, str]:
    errors: list[str] = []
    for candidate in _builtin_tool_paths(definition, paths, project_root=project_root):
        resolved, error = _validate_builtin_candidate(tool_name, definition, candidate)
        if resolved is not None:
            return resolved, ""
        if candidate.exists():
            errors.append(error)
    return None, errors[0] if errors else f"{tool_name} 文件不存在"


def _validate_builtin_candidate(
    tool_name: str,
    definition: ToolDefinition,
    candidate: Path,
) -> tuple[Path | None, str]:
    try:
        resolved = validate_settings_tool_path(_settings_tool_id(tool_name), candidate)
    except SettingsToolPathError as exc:
        return None, str(exc)
    missing = [name for name in definition.builtin_companions if not (resolved.parent / name).is_file()]
    if missing:
        return None, f"缺少运行依赖：{', '.join(missing)}"
    return resolved, ""


def _validate_custom_component(tool_name: str, configured_path: str) -> tuple[Path | None, str]:
    if not configured_path:
        return None, "未配置自定义组件"
    try:
        return validate_settings_tool_path(_settings_tool_id(tool_name), configured_path), ""
    except SettingsToolPathError as exc:
        return None, str(exc)


def _configured_path(definition: ToolDefinition, store: SettingsStore | None) -> str:
    if store is None:
        return ""
    for key in definition.setting_keys:
        try:
            value = str(store.get_value(key, "") or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return ""


def _configured_mode(
    definition: ToolDefinition,
    store: SettingsStore | None,
    configured_path: str,
    *,
    explicit_custom: bool,
) -> NetworkToolMode:
    if explicit_custom:
        return "custom"
    value = ""
    if store is not None and definition.mode_key:
        try:
            value = str(store.get_value(definition.mode_key, "") or "").strip().casefold()
        except Exception:
            value = ""
    if value == "builtin":
        return "builtin"
    if value == "custom":
        return "custom"
    return "custom" if configured_path else "builtin"


def _load_settings(paths: PathResolver) -> SettingsStore | None:
    try:
        return SettingsStore(paths)
    except Exception:
        return None


def _tool_definition(tool_name: str) -> ToolDefinition:
    normalized = _normalized_tool_name(tool_name)
    definition = TOOL_DEFINITIONS.get(normalized)
    if definition is None:
        raise ValueError(f"Unsupported external tool: {tool_name}")
    return definition


def _normalized_tool_name(tool_name: str) -> str:
    value = str(tool_name).strip().casefold()
    return TOOL_NAME_ALIASES.get(value, value)


def _settings_tool_id(tool_name: str) -> str:
    normalized = TOOL_NAME_ALIASES.get(str(tool_name).strip().casefold(), str(tool_name).strip().casefold())
    if normalized not in {"fping", "iperf3", "ipop"}:
        raise SettingsToolPathError("不支持的工具标识")
    return normalized


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


__all__ = [
    "NetworkToolMode",
    "NetworkToolResolution",
    "NetworkToolSource",
    "candidate_tool_paths",
    "get_platform_tools_dir",
    "get_tool_dir",
    "get_tool_executable",
    "get_tools_root",
    "platform_tools_dir_name",
    "resolve_network_tool",
    "resolve_tool_path",
]
