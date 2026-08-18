from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from netconsole.core.feature_flags import PACKAGED_PRODUCTION_FEATURE_IDS
from netconsole.core.version import APP_VERSION
from scripts.build import clean_build_spec
from scripts.build.build_config import BuildConfig, load_config
from scripts.build.build_release import (
    BACKEND_ALLOWED_RELEASE_ITEMS,
    BuildError,
    copy_release_tools,
    find_forbidden_release_dirs,
    pyinstaller_command,
    validate_no_ipop_artifacts,
    validate_release_app_dir,
    validate_release_version_tree,
    validate_zip_file,
    zip_directory,
)


ROOT = Path(__file__).resolve().parents[1]


def test_backend_release_reads_unified_version() -> None:
    config = load_config()

    assert config.app_name == "NetConsole"
    assert config.app_version == APP_VERSION
    assert config.zip_path("pyinstaller").name == f"NetConsole_{APP_VERSION}_pyinstaller.zip"
    assert config.release_version_dir == ROOT / "dist" / "_build" / "backend-release" / APP_VERSION
    assert config.backend_build_dir("pyinstaller") == ROOT / "dist" / "_build" / "pyinstaller"
    assert config.ipop_notice == ROOT / "docs" / "release" / "IPOP_v4.1_NOTICE.md"
    assert config.ipop_notice.is_file()


def test_backend_pyinstaller_command_uses_generated_qt_free_spec() -> None:
    config = load_config()
    command_text = " ".join(pyinstaller_command(config))

    assert "PyInstaller" in command_text
    assert "NetConsoleBackend.spec" in command_text
    assert "NetConsole.spec" not in command_text
    assert "nuitka" not in command_text.casefold()


def test_backend_build_script_does_not_call_publish_flow() -> None:
    script_text = (ROOT / "scripts" / "build" / "build_release.bat").read_text(encoding="utf-8")
    helper_text = (ROOT / "scripts" / "build" / "build_release.py").read_text(encoding="utf-8")
    combined = f"{script_text}\n{helper_text}".casefold()

    for token in ("git commit", "git tag", "git push", "git remote", "build_nuitka_release"):
        assert token not in combined


def test_clean_build_generates_fixed_packaged_runtime_feature_policy() -> None:
    paths = clean_build_spec.write_packaged_runtime_feature_policy()

    build_info = json.loads(
        paths[clean_build_spec.PACKAGED_BUILD_INFO_SOURCE].read_text(encoding="utf-8")
    )
    feature_flags = json.loads(
        paths[clean_build_spec.PACKAGED_FEATURE_FLAGS_SOURCE].read_text(
            encoding="utf-8"
        )
    )
    assert build_info == {
        "edition": "customer",
        "feature_profile": "production",
        "admin_unlock_enabled": False,
    }
    assert feature_flags["profile"] == "production"
    assert all(
        feature_flags["features"][feature_id]["visible"]
        and feature_flags["features"][feature_id]["enabled"]
        for feature_id in PACKAGED_PRODUCTION_FEATURE_IDS
    )


def test_backend_release_allowlist_rejects_project_root_pollution(tmp_path: Path) -> None:
    release_dir = tmp_path / "NetConsoleBackend"
    release_dir.mkdir()
    (release_dir / "NetConsoleBackend.exe").write_text("", encoding="utf-8")
    (release_dir / "_internal").mkdir()
    (release_dir / "docs").mkdir()
    (release_dir / "tests").mkdir()
    (release_dir / "project").mkdir()

    with pytest.raises(BuildError, match="Unexpected release items|Forbidden release directories"):
        validate_release_app_dir(release_dir, BACKEND_ALLOWED_RELEASE_ITEMS)

    forbidden = {path.name for path in find_forbidden_release_dirs(release_dir)}
    assert {"docs", "tests", "project"}.issubset(forbidden)


def test_backend_zip_uses_release_allowlist_only(tmp_path: Path) -> None:
    release_dir = tmp_path / "NetConsoleBackend"
    release_dir.mkdir()
    (release_dir / "NetConsoleBackend.exe").write_text("exe", encoding="utf-8")
    (release_dir / "_internal" / "netconsole").mkdir(parents=True)
    (release_dir / "tools" / "windows-x64").mkdir(parents=True)
    zip_path = tmp_path / "NetConsoleBackend.zip"

    zip_directory(release_dir, zip_path, tmp_path, BACKEND_ALLOWED_RELEASE_ITEMS)
    validate_zip_file(zip_path)

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "NetConsoleBackend/NetConsoleBackend.exe" in names
    assert "NetConsoleBackend/_internal/netconsole/" in names
    assert all("/data/" not in name and "/runtime/" not in name for name in names)


def test_release_zip_validation_rejects_forbidden_entries(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("NetConsoleBackend/NetConsoleBackend.exe", "")
        archive.writestr("NetConsoleBackend/docs/readme.md", "")

    with pytest.raises(BuildError, match="Forbidden release zip entries"):
        validate_zip_file(zip_path)


def test_release_validation_rejects_ipop_but_keeps_other_tools(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    (release_dir / "tools" / "windows-x64" / "fping").mkdir(parents=True)
    (release_dir / "tools" / "windows-x64" / "iperf3").mkdir(parents=True)
    (release_dir / "tools" / "windows-x64" / "fping" / "fping.exe").write_bytes(b"MZ")
    (release_dir / "tools" / "windows-x64" / "iperf3" / "iperf3.exe").write_bytes(b"MZ")
    validate_no_ipop_artifacts(release_dir)

    forbidden = release_dir / "tools" / "windows-x64" / "ipop" / "IPOP.EXE"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_bytes(b"MZ")
    with pytest.raises(BuildError, match="检测到未经确认可再分发"):
        validate_no_ipop_artifacts(release_dir)


def test_release_tool_copy_uses_allowlist_and_never_copies_ipop(tmp_path: Path) -> None:
    tools = tmp_path / "resources" / "tools"
    for relative in (
        "windows-x64/fping/fping.exe",
        "windows-x64/iperf3/iperf3.exe",
        "windows-x64/ipop/IPOP.EXE",
    ):
        path = tools / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ")
    config = BuildConfig(
        "NetConsole",
        "v1.3.9",
        "WXJ",
        root=tmp_path,
        tools_dir=tools,
        release_dir=tmp_path / "release",
    )
    destination = tmp_path / "output"

    copy_release_tools(config, destination)

    assert (destination / "tools" / "windows-x64" / "fping" / "fping.exe").exists()
    assert (destination / "tools" / "windows-x64" / "iperf3" / "iperf3.exe").exists()
    assert not (destination / "tools" / "windows-x64" / "ipop").exists()


def test_release_validation_rejects_backend_internal_docs(tmp_path: Path) -> None:
    app_dir = tmp_path / "NetConsoleBackend"
    app_dir.mkdir()
    (app_dir / "NetConsoleBackend.exe").write_text("", encoding="utf-8")
    (app_dir / "_internal" / "netconsole" / "docs").mkdir(parents=True)

    with pytest.raises(BuildError, match="Forbidden release directories"):
        validate_release_app_dir(app_dir, BACKEND_ALLOWED_RELEASE_ITEMS)


def test_release_version_tree_rejects_sibling_backend_pollution(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1.3.9"
    (version_dir / "pyinstaller" / "NetConsoleBackend" / "_internal" / "netconsole").mkdir(parents=True)
    validate_release_version_tree(version_dir)

    (version_dir / "pyinstaller" / "project").mkdir()
    with pytest.raises(BuildError, match="Forbidden release directories"):
        validate_release_version_tree(version_dir)


def test_release_packaging_does_not_use_project_root_sources() -> None:
    script = (ROOT / "scripts" / "build" / "build_release.py").read_text(encoding="utf-8").casefold()
    batch = (ROOT / "scripts" / "build" / "build_release.bat").read_text(encoding="utf-8").casefold()

    for token in ("copytree(root", "copytree(project_root", "zipfile.write(root", ".rglob(", "glob(\"**/*\")"):
        assert token not in script
    for token in ("compress-archive", "robocopy", "/mir", "xcopy"):
        assert token not in batch
