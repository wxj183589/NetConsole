from __future__ import annotations

from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.services.tool_path_resolver import (
    candidate_tool_paths,
    get_platform_tools_dir,
    get_tool_dir,
    get_tool_executable,
    get_tools_root,
    platform_tools_dir_name,
    resolve_tool_path,
)


def _write_tool(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake", encoding="utf-8")
    return path


def test_resolver_finds_development_tools_from_project_root(tmp_path: Path) -> None:
    fping = _write_tool(tmp_path / "tools" / "windows-x64" / "fping" / "fping.exe")
    iperf = _write_tool(tmp_path / "tools" / "windows-x64" / "iperf3" / "iperf3.exe")
    paths = PathResolver(tmp_path)

    assert resolve_tool_path("fping", paths, project_root=tmp_path) == fping.resolve()
    assert resolve_tool_path("iperf3", paths, project_root=tmp_path) == iperf.resolve()


def test_resolver_finds_packaged_internal_tools(tmp_path: Path) -> None:
    app_root = tmp_path / "dist" / "NetConsole"
    fping = _write_tool(app_root / "_internal" / "tools" / "windows-x64" / "fping" / "fping.exe")
    iperf = _write_tool(app_root / "_internal" / "tools" / "windows-x64" / "iperf3" / "iperf3.exe")
    paths = PathResolver(app_root)

    assert resolve_tool_path("fping", paths, project_root=tmp_path / "missing") == fping.resolve()
    assert resolve_tool_path("iperf3", paths, project_root=tmp_path / "missing") == iperf.resolve()


def test_resolver_is_independent_from_current_working_directory(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "dist" / "NetConsole"
    iperf = _write_tool(app_root / "_internal" / "tools" / "windows-x64" / "iperf3" / "iperf3.exe")
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    assert resolve_tool_path("iperf3", PathResolver(app_root), project_root=tmp_path / "missing") == iperf.resolve()


def test_resolver_prefers_custom_settings_path(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    packaged = _write_tool(app_root / "_internal" / "tools" / "windows-x64" / "fping" / "fping.exe")
    custom = _write_tool(tmp_path / "custom" / "fping.exe")
    paths = PathResolver(app_root)
    settings = SettingsStore(paths)
    settings.set_value("online_mr.fping_path", str(custom))

    assert resolve_tool_path("fping", paths, settings=settings, project_root=tmp_path / "missing") == custom.resolve()
    assert packaged.exists()


def test_resolver_prefers_explicit_custom_path_before_settings(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "app")
    configured = _write_tool(tmp_path / "configured" / "iperf3.exe")
    explicit = _write_tool(tmp_path / "explicit" / "iperf3.exe")
    settings = SettingsStore(paths)
    settings.set_value("network_tools/iperf_path", str(configured))

    assert (
        resolve_tool_path("iperf3", paths, settings=settings, custom_path=explicit, project_root=tmp_path / "missing")
        == explicit.resolve()
    )


def test_resolver_finds_packaged_app_tools(tmp_path: Path) -> None:
    app_root = tmp_path / "NetConsole"
    packaged = _write_tool(app_root / "tools" / "windows-x64" / "iperf3" / "iperf3.exe")

    assert resolve_tool_path("iperf3", PathResolver(app_root), project_root=tmp_path / "missing") == packaged.resolve()


def test_resolver_app_tools_precede_internal_tools(tmp_path: Path) -> None:
    app_root = tmp_path / "NetConsole"
    internal = _write_tool(app_root / "_internal" / "tools" / "windows-x64" / "iperf3" / "iperf3.exe")
    packaged = _write_tool(app_root / "tools" / "windows-x64" / "iperf3" / "iperf3.exe")

    assert resolve_tool_path("iperf3", PathResolver(app_root), project_root=tmp_path / "missing") == packaged.resolve()
    assert internal.exists()


def test_resolver_candidate_order_contains_packaged_and_development_paths(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "NetConsole")
    candidates = candidate_tool_paths("fping", paths, project_root=tmp_path / "project_root")
    normalized = [path.as_posix() for path in candidates]

    assert normalized[0].endswith("NetConsole/tools/windows-x64/fping/fping.exe")
    assert normalized[1].endswith("NetConsole/_internal/tools/windows-x64/fping/fping.exe")
    assert any(path.endswith("project_root/tools/windows-x64/fping/fping.exe") for path in normalized)


def test_resolver_finds_nuitka_onefile_extracted_tools(tmp_path: Path, monkeypatch) -> None:
    package_root = tmp_path / "onefile"
    fping = _write_tool(package_root / "tools" / "windows-x64" / "fping" / "fping.exe")
    fake_file = package_root / "netconsole" / "services" / "tool_path_resolver.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("netconsole.services.tool_path_resolver.__file__", str(fake_file))

    assert resolve_tool_path("fping", PathResolver(tmp_path / "app"), project_root=tmp_path / "missing") == fping.resolve()


def test_windows_x64_platform_and_tool_helpers(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)

    assert platform_tools_dir_name(system_name="Windows", machine="AMD64") == "windows-x64"
    assert platform_tools_dir_name(system_name="Windows", machine="x86_64") == "windows-x64"
    assert get_tools_root(paths) == tmp_path.resolve() / "tools"
    assert get_platform_tools_dir(paths, system_name="Windows", machine="AMD64") == tmp_path.resolve() / "tools" / "windows-x64"
    assert get_tool_dir("fping", paths) == tmp_path.resolve() / "tools" / "windows-x64" / "fping"
    assert get_tool_dir("iperf3", paths) == tmp_path.resolve() / "tools" / "windows-x64" / "iperf3"


def test_ipop_executable_helper_uses_new_path(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    expected = _write_tool(tmp_path / "tools" / "windows-x64" / "ipop" / "IPOP.EXE")

    assert get_tool_dir("ipop", paths) == expected.parent.resolve()
    assert get_tool_executable("ipop", paths) == expected.resolve()
