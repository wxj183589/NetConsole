from __future__ import annotations

from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.services.tool_path_resolver import candidate_tool_paths, resolve_tool_path


def _write_tool(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake", encoding="utf-8")
    return path


def test_resolver_finds_development_tools_from_project_root(tmp_path: Path) -> None:
    fping = _write_tool(tmp_path / "tools" / "fping_v3" / "Fping_v3.exe")
    iperf = _write_tool(tmp_path / "tools" / "iperf" / "iperf3.exe")
    paths = PathResolver(tmp_path)

    assert resolve_tool_path("fping_v3", paths, project_root=tmp_path) == fping.resolve()
    assert resolve_tool_path("iperf3", paths, project_root=tmp_path) == iperf.resolve()


def test_resolver_finds_packaged_internal_tools(tmp_path: Path) -> None:
    app_root = tmp_path / "dist" / "NetConsole"
    fping = _write_tool(app_root / "_internal" / "tools" / "fping_v3" / "Fping_v3.exe")
    iperf = _write_tool(app_root / "_internal" / "tools" / "iperf" / "iperf3.exe")
    paths = PathResolver(app_root)

    assert resolve_tool_path("fping_v3", paths, project_root=tmp_path / "missing") == fping.resolve()
    assert resolve_tool_path("iperf3", paths, project_root=tmp_path / "missing") == iperf.resolve()


def test_resolver_is_independent_from_current_working_directory(tmp_path: Path, monkeypatch) -> None:
    app_root = tmp_path / "dist" / "NetConsole"
    iperf = _write_tool(app_root / "_internal" / "tools" / "iperf" / "iperf3.exe")
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    assert resolve_tool_path("iperf3", PathResolver(app_root), project_root=tmp_path / "missing") == iperf.resolve()


def test_resolver_prefers_custom_settings_path(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    packaged = _write_tool(app_root / "_internal" / "tools" / "fping_v3" / "Fping_v3.exe")
    custom = _write_tool(tmp_path / "custom" / "Fping_v3.exe")
    paths = PathResolver(app_root)
    settings = SettingsStore(paths)
    settings.set_value("online_mr.fping_path", str(custom))

    assert resolve_tool_path("fping_v3", paths, settings=settings, project_root=tmp_path / "missing") == custom.resolve()
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


def test_resolver_legacy_app_root_tools_fallback(tmp_path: Path) -> None:
    app_root = tmp_path / "NetConsole"
    legacy = _write_tool(app_root / "tools" / "iperf" / "iperf3.exe")

    assert resolve_tool_path("iperf3", PathResolver(app_root), project_root=tmp_path / "missing") == legacy.resolve()


def test_resolver_internal_tools_precede_legacy_app_root_tools(tmp_path: Path) -> None:
    app_root = tmp_path / "NetConsole"
    internal = _write_tool(app_root / "_internal" / "tools" / "iperf" / "iperf3.exe")
    legacy = _write_tool(app_root / "tools" / "iperf" / "iperf3.exe")

    assert resolve_tool_path("iperf3", PathResolver(app_root), project_root=tmp_path / "missing") == internal.resolve()
    assert legacy.exists()


def test_resolver_candidate_order_contains_packaged_dev_and_legacy_paths(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "NetConsole")
    candidates = candidate_tool_paths("fping_v3", paths, project_root=tmp_path / "project_root")
    normalized = [path.as_posix() for path in candidates]

    assert normalized[0].endswith("NetConsole/_internal/tools/fping_v3/Fping_v3.exe")
    assert normalized[1].endswith("NetConsole/tools/fping_v3/Fping_v3.exe")
    assert normalized[2].endswith("NetConsole/tools/fping_v3/Fping_v3.exe") or normalized[2].endswith("NetConsole/_internal/tools/fping_v3/Fping_v3.exe") or normalized[2].endswith("tools/fping_v3/Fping_v3.exe")
    assert any(path.endswith("project_root/tools/fping_v3/Fping_v3.exe") for path in normalized)


def test_resolver_finds_nuitka_onefile_extracted_tools(tmp_path: Path, monkeypatch) -> None:
    package_root = tmp_path / "onefile"
    fping = _write_tool(package_root / "tools" / "fping_v3" / "Fping_v3.exe")
    fake_file = package_root / "netconsole" / "services" / "tool_path_resolver.py"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr("netconsole.services.tool_path_resolver.__file__", str(fake_file))

    assert resolve_tool_path("fping_v3", PathResolver(tmp_path / "app"), project_root=tmp_path / "missing") == fping.resolve()
