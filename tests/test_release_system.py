from pathlib import Path
import inspect
import json
import os
import shutil
import subprocess
import sys

from scripts.build import clean_build_spec
import pytest
from scripts.build import release
from scripts.build import build_release
from scripts.build.check_runtime_deps import REQUIRED_TOOLS, check_runtime_deps
from netconsole.build.clean_build_lock import (
    CleanBuildLockError,
    validate_allowed_runtime,
    validate_datas,
    validate_dist_output,
    validate_project_safety,
    validate_pyinstaller_command,
)
from netconsole.core.resources import get_changelog_path
from netconsole.core.version import APP_VERSION, BUILD_TIME, GIT_COMMIT


def _write_clean_build_tool_files(app_dist: Path) -> None:
    for relative in clean_build_spec.REQUIRED_TOOL_FILES:
        path = app_dist / relative.relative_to("resources")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")


def test_version_file_exposes_release_metadata():
    assert APP_VERSION == "v1.4.2"
    assert BUILD_TIME
    assert GIT_COMMIT


def test_release_version_defaults_to_app_version_without_tag_scan():
    assert release.get_release_version() == APP_VERSION
    assert release.get_release_version("v9.9.9") == "v9.9.9"
    assert not hasattr(release, "next_patch_version")
    assert not hasattr(release, "get_next_version")


def test_render_version_py_contains_single_version_source_fields():
    text = release.render_version_py("v1.0.7", "2026-06-17 12:00:00", "abc1234")

    assert 'APP_NAME = "NetConsole"' in text
    assert 'APP_VERSION = "v1.0.7"' in text
    assert "APP_VERSION_DISPLAY = APP_VERSION" in text
    assert 'BUILD_TIME = "2026-06-17 12:00:00"' in text
    assert 'GIT_COMMIT = "abc1234"' in text
    assert 'APP_AUTHOR = "' in text
    assert "ssh://git@nas.love-ok.com:3022/mengyou/NetConsole.git" in text
    assert "git@github.com:wxj183589/NetConsole.git" in text


def test_release_script_documents_gitea_https_authentication():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build" / "release.py").read_text(encoding="utf-8")

    assert not (root / "release.py").exists()
    assert "self-hosted Gitea repository" in text
    assert "SSH key" in text
    assert "SSH key authentication is required" in text
    assert "Release system should not block on auth failure" in text


def test_release_script_pushes_two_remotes_and_tags():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build" / "release.py").read_text(encoding="utf-8")

    assert "def safe_run(cmd: list[str])" in text
    assert 'def check_git_remote(remote: str = "nas")' in text
    assert 'git", "push", "github", "HEAD"' in text
    assert 'git", "push", "nas", "HEAD"' in text
    assert 'git", "push", "github", selected_version' in text
    assert 'git", "push", "nas", selected_version' in text
    assert 'git", "tag", "-a", selected_version' in text


def test_release_push_failures_do_not_interrupt_release(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(release, "write_release_files", lambda *args: None)
    monkeypatch.setattr(release, "ensure_remotes", lambda dry_run: None)
    monkeypatch.setattr(release, "check_git_remote", lambda remote="nas": False)
    monkeypatch.setattr(
        release,
        "run_git",
        lambda args, check=True: (
            "abc1234" if args[:2] == ["rev-parse", "--short"] else ""
        ),
    )

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[:2] == ["git", "push"]:
            raise subprocess.CalledProcessError(128, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(release.subprocess, "run", fake_run)

    result = release.release(version="v1.0.9", dry_run=False)

    assert result.build_success
    assert result.commit_success
    assert result.tag_success
    assert not result.push_nas_success
    assert not result.push_github_success
    assert result.final_status == release.OFFLINE_RELEASE
    assert any(
        cmd[:4] == ["git", "tag", "-a", "v1.0.9"]
        and cmd[4] == "-m"
        and cmd[5].endswith("v1.0.9")
        for cmd in commands
    )
    assert ["git", "push", "github", "HEAD"] in commands
    assert ["git", "push", "nas", "HEAD"] in commands
    assert ["git", "push", "github", "v1.0.9"] in commands
    assert ["git", "push", "nas", "v1.0.9"] in commands


def test_release_tag_failure_does_not_interrupt_push_attempts(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(release, "write_release_files", lambda *args: None)
    monkeypatch.setattr(release, "ensure_remotes", lambda dry_run: None)
    monkeypatch.setattr(release, "check_git_remote", lambda remote="nas": True)
    monkeypatch.setattr(
        release,
        "run_git",
        lambda args, check=True: (
            "abc1234" if args[:2] == ["rev-parse", "--short"] else ""
        ),
    )

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[:3] == ["git", "tag", "-a"]:
            raise subprocess.CalledProcessError(128, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(release.subprocess, "run", fake_run)

    result = release.release(version="v1.0.10", dry_run=False)

    assert result.build_success
    assert not result.tag_success
    assert result.push_nas_success
    assert result.push_github_success
    assert result.final_status == release.LOCAL_BUILD_ONLY
    assert ["git", "push", "github", "HEAD"] in commands
    assert ["git", "push", "nas", "HEAD"] in commands


def test_build_release_script_uses_project_output_and_release_zip():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build" / "build_release.bat").read_text(
        encoding="utf-8"
    )

    assert "scripts.build.build_release" in text
    assert "--backend pyinstaller %*" in text
    assert "project\\release.py" not in text
    assert "PROJECT_ROOT=%ROOT%\\project" not in text
    assert "--add-data" not in text
    assert "scripts.build.build_release --backend pyinstaller %*" in text
    assert "--build-editions" not in text
    assert "admin-unlock-password" not in text


def test_changelog_source_is_chinese_for_zh_ui():
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "netconsole" / "docs" / "changelog.md").read_text(
        encoding="utf-8"
    )
    forbidden_fragments = [
        "Onboard MR Online Collection",
        "Packaging",
        "Rail Transit",
        "Tests",
        "high-frequency ping",
    ]

    assert all(fragment not in text for fragment in forbidden_fragments)


def test_release_script_uses_chinese_auto_commit_message():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build" / "release.py").read_text(encoding="utf-8")

    assert "auto release build" not in text
    assert 'git", "commit", "--allow-empty", "-m"' in text
    assert 'git", "tag", "-a", selected_version' in text


def test_clean_build_spec_uses_strict_whitelist_and_excludes():
    assert clean_build_spec.CLEAN_BUILD is True
    assert (".", ".") in clean_build_spec.FORBIDDEN_DATA
    assert ("project", "project") in clean_build_spec.FORBIDDEN_DATA
    assert ("tests", "tests") in clean_build_spec.FORBIDDEN_DATA
    assert ("docs", "docs") in clean_build_spec.FORBIDDEN_DATA
    assert ("src/netconsole", "netconsole") in clean_build_spec.ALLOWED_DATA
    assert ("data", "data") not in clean_build_spec.ALLOWED_DATA
    assert (
        "resources/tools/windows-x64/fping",
        "tools/windows-x64/fping",
    ) not in clean_build_spec.ALLOWED_DATA
    assert (
        "resources/tools/windows-x64/iperf3",
        "tools/windows-x64/iperf3",
    ) not in clean_build_spec.ALLOWED_DATA
    assert not any(
        source.casefold().startswith("tools/windows-x64/ipop")
        for source, _destination in clean_build_spec.ALLOWED_DATA
    )
    assert ("tools", "tools") not in clean_build_spec.ALLOWED_DATA
    assert all(
        "/ui/" not in source.replace("\\", "/")
        for source, _destination in clean_build_spec.ALLOWED_DATA
    )
    assert ("apps/web/dist", "netconsole/assets/web") in clean_build_spec.ALLOWED_DATA
    assert (
        "resources/device_command_profiles.json",
        "netconsole/assets",
    ) in clean_build_spec.ALLOWED_DATA
    assert (
        "src/netconsole/docs",
        "netconsole/docs",
    ) not in clean_build_spec.ALLOWED_DATA
    assert (
        "src/netconsole/docs/changelog.md",
        "netconsole/docs/changelog.md",
    ) not in clean_build_spec.ALLOWED_DATA
    assert "tests" in clean_build_spec.EXCLUDE_DIRS
    assert "docs" in clean_build_spec.EXCLUDE_DIRS
    assert "project" in clean_build_spec.EXCLUDE_DIRS
    assert "__pycache__" in clean_build_spec.EXCLUDE_DIRS


def test_release_tools_are_copied_only_from_versioned_local_resources():
    source = inspect.getsource(build_release.copy_release_tools)

    assert "config.tools_dir" in source
    assert 'for tool_name in ("fping", "iperf3")' in source
    assert "http://" not in source
    assert "https://" not in source
    assert "urlopen" not in source
    assert "download" not in source.casefold()


def test_clean_build_always_rebuilds_and_validates_web_frontend(tmp_path, monkeypatch):
    web_dir = tmp_path / "apps" / "web"
    (web_dir / "node_modules").mkdir(parents=True)
    (web_dir / "dist").mkdir()
    (web_dir / "dist" / "index.html").write_text("stale", encoding="utf-8")
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command, *, cwd, check, env):
        assert check is True
        assert env["NETCONSOLE_FRONTEND_GIT_COMMIT"] == GIT_COMMIT
        calls.append((command, cwd))
        (web_dir / "dist" / "index.html").write_text("web", encoding="utf-8")
        (web_dir / "dist" / "web-build-meta.json").write_text(
            json.dumps(
                {
                    "app_version": APP_VERSION,
                    "git_commit": GIT_COMMIT,
                    "build_time": "2026-07-15T00:00:00Z",
                    "navigation_schema_version": 1,
                    "build_id": f"{APP_VERSION}+{GIT_COMMIT}",
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(clean_build_spec, "ROOT", tmp_path)
    monkeypatch.setattr(clean_build_spec.shutil, "which", lambda _name: "pnpm.cmd")
    monkeypatch.setattr(clean_build_spec.subprocess, "run", fake_run)

    clean_build_spec.ensure_web_frontend()

    assert calls == [(["pnpm.cmd", "build"], web_dir)]


def test_web_frontend_metadata_rejects_inconsistent_version_fields(tmp_path):
    from scripts.build.web_frontend_meta import validate_web_frontend_meta

    (tmp_path / "index.html").write_text("web", encoding="utf-8")
    (tmp_path / "web-build-meta.json").write_text(
        json.dumps(
            {
                "app_version": "v0.0.0",
                "git_commit": GIT_COMMIT,
                "build_time": "2026-07-15T00:00:00Z",
                "navigation_schema_version": 1,
                "build_id": f"{APP_VERSION}+{GIT_COMMIT}",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="构建身份与后端不一致"):
        validate_web_frontend_meta(
            tmp_path,
            expected_version=APP_VERSION,
            expected_commit=GIT_COMMIT,
        )


def test_clean_build_spec_scans_runtime_import_graph():
    imports = clean_build_spec.scan_import_graph()

    assert {
        "netconsole.backend.api.main",
        "netconsole.backend.electron_runtime",
        "netconsole.launcher.launcher",
        "netconsole.launcher.runtime_supervisor",
        "netconsole.launcher.web_server",
    } <= set(imports)
    assert not any(
        item == "netconsole.ui" or item.startswith("netconsole.ui.") for item in imports
    )
    assert all(not item.startswith("tests") for item in imports)
    assert all(not item.startswith("project") for item in imports)


def test_clean_build_spec_keeps_direct_runtime_distributions_reachable():
    imports = set(clean_build_spec.build_direct_runtime_hidden_imports())

    assert {
        "fastapi",
        "httpx",
        "matplotlib",
        "netmiko",
        "numpy",
        "openpyxl",
        "paramiko",
        "pydantic",
        "python_multipart",
        "uvicorn",
        "websockets",
        "xlsxwriter",
    } <= imports
    assert "__pycache__" not in imports


def test_clean_build_import_graph_is_entry_file_driven():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build" / "clean_build_spec.py").read_text(
        encoding="utf-8"
    )

    assert "pending_sources = [ENTRY_FILE]" in text
    assert ".rglob(" not in text
    assert '(ROOT / "netconsole").rglob' not in text
    assert "(ROOT / 'netconsole').rglob" not in text


def test_clean_build_runtime_subset_copies_only_imported_modules_and_assets(
    tmp_path, monkeypatch
):
    runtime_files = clean_build_spec.build_runtime_subset_from_import_graph()
    staged_relative = {
        path.relative_to(clean_build_spec.ROOT) for path in runtime_files
    }
    expected_relative = {
        path.relative_to(clean_build_spec.ROOT)
        for path in clean_build_spec.build_runtime_module_map().values()
    }

    assert staged_relative == expected_relative
    assert all("docs" not in path.parts for path in staged_relative)
    assert all("tests" not in path.parts for path in staged_relative)
    assert all("project" not in path.parts for path in staged_relative)
    datas = clean_build_spec.build_runtime_datas_from_import_graph()
    assert all(not destination.startswith("tools/") for _source, destination in datas)
    assert any(
        destination == "netconsole/assets/web" and Path(source).name == "dist"
        for source, destination in datas
    )
    assert any(
        destination == "netconsole/assets"
        and Path(source).name == "device_command_profiles.json"
        for source, destination in datas
    )
    profile_source = next(
        Path(source)
        for source, destination in datas
        if destination == "netconsole/assets"
        and Path(source).name == "device_command_profiles.json"
    )
    profile_payload = json.loads(profile_source.read_text(encoding="utf-8"))
    assert {profile["operation_id"] for profile in profile_payload["profiles"]} == {
        "device.inventory.collect"
    }
    assert {profile["profile_id"] for profile in profile_payload["profiles"]} == {
        "h3c.comware.switch.generic.device-inventory.v1",
        "h3c.comware.mobile_router.generic.device-inventory.v1",
    }
    assert {
        "PYINSTALLER_COPYING.txt",
        "PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt",
    } <= {
        Path(source).name
        for source, destination in datas
        if destination == "netconsole/assets/licenses"
    }
    assert not any(
        destination == "tools" and Path(source).name == "tools"
        for source, destination in datas
    )
    assert all(destination != "data" for _source, destination in datas)


def test_clean_build_excludes_only_ambient_non_runtime_modules(monkeypatch):
    monkeypatch.setattr(
        clean_build_spec,
        "runtime_dependency_versions",
        lambda _root: {"fastapi": "1", "shared-runtime": "1"},
    )
    monkeypatch.setattr(
        clean_build_spec.metadata,
        "packages_distributions",
        lambda: {
            "fastapi": ["fastapi"],
            "pytest": ["pytest"],
            "shared": ["shared-runtime", "build-helper"],
            "netconsole": ["netconsole-backend"],
        },
    )
    monkeypatch.setattr(clean_build_spec.metadata, "distributions", lambda: ())

    assert clean_build_spec.build_non_runtime_module_excludes() == ["pytest"]


def test_clean_build_spec_does_not_use_directory_copy_or_full_scan():
    root = Path(__file__).resolve().parents[1]
    text = (root / "scripts" / "build" / "clean_build_spec.py").read_text(
        encoding="utf-8"
    )

    assert "copytree" not in text
    assert "_copy_runtime_package" not in text
    assert ".rglob(" not in text


def test_clean_build_spec_generated_spec_is_clean(tmp_path, monkeypatch):
    spec_file = tmp_path / "NetConsoleBackend.spec"
    monkeypatch.setattr(clean_build_spec, "SPEC_ROOT", tmp_path)
    monkeypatch.setattr(clean_build_spec, "SPEC_FILE", spec_file)

    clean_build_spec.write_spec()
    text = spec_file.read_text(encoding="utf-8")

    assert "CLEAN_BUILD = True" in text
    assert "RUNTIME_IMPORTS =" in text
    assert "RUNTIME_DATAS =" in text
    assert "RUNTIME_EXCLUDES =" in text
    assert "VC_RUNTIME_BINARIES =" in text
    assert "datas=RUNTIME_DATAS" in text
    assert "binaries=VC_RUNTIME_BINARIES" in text
    assert (
        str(clean_build_spec.DIST_ROOT / "NetConsoleBackend" / "_internal") not in text
    )
    assert "hiddenimports=RUNTIME_IMPORTS" in text
    assert "hooksconfig={'matplotlib': {'backends': 'Agg'}}" in text
    assert "PySide" not in text
    assert "qfluent" not in text.casefold()
    assert "*RUNTIME_EXCLUDES" in text
    assert "contents_directory='_internal'" in text
    assert "console=True" in text
    assert "name='NetConsoleBackend'" in text
    assert "tools/windows-x64/fping" not in text
    assert "tools/windows-x64/iperf3" not in text
    assert "tools/windows-x64/ipop" not in text
    assert "tools/windows-x64/ipop/IPOP.EXE" not in text
    assert "main.py" in text
    assert "('.', '.')" not in text
    assert "('project', 'project')" not in text
    assert "('tests', 'tests')" not in text
    assert "('docs', 'docs')" not in text


@pytest.mark.parametrize(
    "datas",
    [
        [("", ".")],
        [(".", ".")],
        [("project", "project")],
        [("docs", "docs")],
        [("tests", "tests")],
        [(Path("docs"), "docs")],
    ],
)
def test_clean_build_lock_rejects_illegal_datas(datas):
    with pytest.raises(CleanBuildLockError, match="Illegal datasource detected"):
        validate_datas(datas)


def test_clean_build_lock_rejects_netconsole_docs_runtime_path():
    with pytest.raises(CleanBuildLockError, match="Runtime data is not whitelisted"):
        validate_allowed_runtime([("netconsole/docs", "netconsole/docs")])


def test_clean_build_lock_rejects_illegal_spec_datas():
    with pytest.raises(
        CleanBuildLockError, match="Illegal PyInstaller spec datasource"
    ):
        validate_project_safety(
            spec_text="a = Analysis(['main.py'], datas=[('.', '.')])"
        )


def test_clean_build_lock_validates_required_pyinstaller_options():
    root = Path(__file__).resolve().parents[1]
    args = [
        "--onedir",
        "--console",
        "--name",
        "NetConsoleBackend",
        "--icon",
        str(root / "resources" / "branding" / "netconsole.ico"),
        "--distpath",
        str(root / "dist" / "_build" / "pyinstaller" / "dist"),
        "--workpath",
        str(root / "dist" / "_build" / "pyinstaller" / "build"),
    ]

    validate_pyinstaller_command(args)

    with pytest.raises(
        CleanBuildLockError, match="Missing required PyInstaller option: --console"
    ):
        validate_pyinstaller_command([arg for arg in args if arg != "--console"])


@pytest.mark.parametrize("forbidden", ["docs", "tests", "project", "build", "spec"])
def test_clean_build_lock_rejects_forbidden_dist_dirs(tmp_path, forbidden):
    app_dist = tmp_path / "NetConsoleBackend"
    (app_dist / "_internal" / "netconsole").mkdir(parents=True)
    (app_dist / "NetConsoleBackend.exe").write_text("", encoding="utf-8")
    (app_dist / forbidden).mkdir()

    with pytest.raises(CleanBuildLockError, match="CleanBuildLock violation"):
        validate_dist_output(app_dist)


def test_clean_build_success_shape_allows_independent_exe_layout(tmp_path):
    app_dist = tmp_path / "NetConsoleBackend"
    (app_dist / "_internal" / "netconsole").mkdir(parents=True)
    (app_dist / "NetConsoleBackend.exe").write_text("", encoding="utf-8")

    validate_dist_output(app_dist)

    assert sorted(path.name for path in app_dist.iterdir()) == [
        "NetConsoleBackend.exe",
        "_internal",
    ]
    assert not (app_dist / "docs").exists()
    assert not (app_dist / "tests").exists()
    assert not (app_dist / "project").exists()
    assert not (app_dist / "netconsole").exists()
    assert (app_dist / "_internal" / "netconsole").exists()


def test_clean_build_packaged_tools_validation(tmp_path):
    app_dist = tmp_path / "NetConsoleBackend"
    _write_clean_build_tool_files(app_dist)

    clean_build_spec.check_packaged_tools(app_dist, run_version_check=False)


def test_engineer_edition_is_selected_by_explicit_request_or_customer_option(
    monkeypatch,
):
    monkeypatch.setattr(build_release, "engineer_package_enabled", lambda: False)
    assert build_release.selected_editions("engineer") == ("engineer",)
    assert build_release.selected_editions("both") == ("internal", "customer")

    monkeypatch.setattr(build_release, "engineer_package_enabled", lambda: True)
    assert build_release.selected_editions("both") == (
        "internal",
        "customer",
        "engineer",
    )


def test_clean_build_packaged_tools_validation_rejects_missing_tool(tmp_path):
    app_dist = tmp_path / "NetConsoleBackend"
    (app_dist / "tools" / "windows-x64" / "fping").mkdir(parents=True)
    (app_dist / "tools" / "windows-x64" / "fping" / "fping.exe").write_text(
        "", encoding="utf-8"
    )
    (app_dist / "tools" / "windows-x64" / "fping" / "cygwin1.dll").write_text(
        "", encoding="utf-8"
    )

    with pytest.raises(CleanBuildLockError, match="packaged runtime tool is missing"):
        clean_build_spec.check_packaged_tools(app_dist, run_version_check=False)


def test_clean_build_lock_rejects_ipop_in_final_dist(tmp_path):
    app_dist = tmp_path / "NetConsoleBackend"
    (app_dist / "_internal" / "netconsole").mkdir(parents=True)
    (app_dist / "tools" / "windows-x64" / "ipop").mkdir(parents=True)
    (app_dist / "NetConsoleBackend.exe").write_bytes(b"MZ")
    (app_dist / "tools" / "windows-x64" / "ipop" / "IPOP.EXE").write_bytes(b"MZ")

    with pytest.raises(CleanBuildLockError, match="检测到未经确认可再分发"):
        validate_dist_output(app_dist)


def _write_test_pe(
    path: Path, machine: int = clean_build_spec.IMAGE_FILE_MACHINE_AMD64
) -> None:
    payload = bytearray(0x88)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\x00\x00"
    payload[0x84:0x86] = machine.to_bytes(2, "little")
    path.write_bytes(payload)


def test_collect_vc_runtime_dlls_finds_required_files(tmp_path):
    dll_dir = tmp_path / "runtime"
    dll_dir.mkdir()
    for dll_name in clean_build_spec.REQUIRED_VC_RUNTIME_DLLS:
        _write_test_pe(dll_dir / dll_name)

    result = clean_build_spec.collect_vc_runtime_dlls([dll_dir])

    assert {Path(source).name for source, _target in result} == set(
        clean_build_spec.REQUIRED_VC_RUNTIME_DLLS
    )
    assert all(target == "." for _source, target in result)


def test_collect_vc_runtime_dlls_rejects_missing_required_file(tmp_path):
    dll_dir = tmp_path / "runtime"
    dll_dir.mkdir()
    for dll_name in clean_build_spec.REQUIRED_VC_RUNTIME_DLLS:
        if dll_name != "VCRUNTIME140_1.dll":
            _write_test_pe(dll_dir / dll_name)

    with pytest.raises(CleanBuildLockError, match="VCRUNTIME140_1.dll"):
        clean_build_spec.collect_vc_runtime_dlls([dll_dir])


def test_collect_vc_runtime_dlls_rejects_x86_runtime(tmp_path):
    dll_dir = tmp_path / "runtime"
    dll_dir.mkdir()
    for dll_name in clean_build_spec.REQUIRED_VC_RUNTIME_DLLS:
        machine = (
            0x014C
            if dll_name == "MSVCP140.dll"
            else clean_build_spec.IMAGE_FILE_MACHINE_AMD64
        )
        _write_test_pe(dll_dir / dll_name, machine)

    with pytest.raises(CleanBuildLockError, match="MSVCP140.dll"):
        clean_build_spec.collect_vc_runtime_dlls([dll_dir])


def test_default_vc_runtime_roots_never_include_syswow64(monkeypatch, tmp_path):
    system32 = tmp_path / "System32"
    syswow64 = tmp_path / "SysWOW64"
    system32.mkdir()
    syswow64.mkdir()
    monkeypatch.setenv("WINDIR", str(tmp_path))
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    roots = clean_build_spec._default_vc_runtime_search_roots()

    assert system32.resolve() in roots
    assert syswow64.resolve() not in roots


def _make_packaged_runtime(tmp_path: Path) -> Path:
    app_dist = tmp_path / "NetConsoleBackend"
    internal = app_dist / "_internal"
    (internal / "netconsole").mkdir(parents=True)
    (app_dist / "NetConsoleBackend.exe").write_text("", encoding="utf-8")
    (internal / "python310.dll").write_text("", encoding="utf-8")
    for name in (
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
        "MSVCP140.dll",
        "CONCRT140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
    ):
        (internal / name).write_text("", encoding="utf-8")
    for relative in REQUIRED_TOOLS:
        path = app_dist / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    return app_dist


def test_runtime_deps_rejects_missing_internal_dir(tmp_path):
    app_dist = tmp_path / "NetConsoleBackend"
    app_dist.mkdir()
    (app_dist / "NetConsoleBackend.exe").write_text("", encoding="utf-8")

    result = check_runtime_deps(app_dist)

    assert not result.ok
    assert any("_internal" in message for message in result.messages)


def test_runtime_deps_rejects_qt_residue(tmp_path):
    app_dist = _make_packaged_runtime(tmp_path)
    residue = app_dist / "_internal" / "legacy" / "Qt6Gui.dll"
    residue.parent.mkdir(parents=True)
    residue.write_text("", encoding="utf-8")

    result = check_runtime_deps(app_dist)

    assert not result.ok
    assert any(
        "Qt runtime residue found" in message and "Qt6Gui.dll" in message
        for message in result.messages
    )


def test_runtime_deps_rejects_writable_data_inside_bundle(tmp_path):
    app_dist = _make_packaged_runtime(tmp_path)
    (app_dist / "data").mkdir()

    result = check_runtime_deps(app_dist)

    assert not result.ok
    assert any(
        "must not contain writable data" in message for message in result.messages
    )


def test_runtime_deps_accepts_complete_packaged_runtime(tmp_path):
    app_dist = _make_packaged_runtime(tmp_path)

    result = check_runtime_deps(app_dist)

    assert result.ok
    assert "[OK] Qt runtime residue not found" in result.messages
    assert "[OK] VCRUNTIME140.dll found" in result.messages
    assert "[OK] MSVCP140.dll found" in result.messages
    assert "[OK] CONCRT140.dll found" in result.messages
    assert "[OK] tools/windows-x64/fping/fping.exe found" in result.messages
    assert "[OK] tools/windows-x64/iperf3/iperf3.exe found" in result.messages
    assert (
        "[OK] no writable data/runtime directory in backend bundle" in result.messages
    )


def test_check_packaged_runtime_script_runs_from_repo_root(tmp_path):
    root = Path(__file__).resolve().parents[1]
    app_dist = _make_packaged_runtime(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-m", "scripts.build.check_packaged_runtime", str(app_dist)],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "[OK] Qt runtime residue not found" in completed.stdout
    assert "[OK] VCRUNTIME140.dll found" in completed.stdout


def test_readme_documents_electron_runtime():
    root = Path(__file__).resolve().parents[1]
    text = (root / "README.md").read_text(encoding="utf-8")

    assert "NetConsole" in text
    assert "Windows" in text
    assert "Electron" in text
    assert "runtime" in text.lower()


def test_clean_build_packaged_tools_version_checks_accept_expected_markers(
    tmp_path, monkeypatch
):
    app_dist = tmp_path / "NetConsoleBackend"
    _write_clean_build_tool_files(app_dist)

    def fake_run(args, **kwargs):
        if str(args[0]).endswith("fping.exe"):
            return subprocess.CompletedProcess(
                args, 2, stdout="Version 5.5\nHost not found: -v error", stderr=""
            )
        return subprocess.CompletedProcess(
            args, 0, stdout="iperf 3.21 (cJSON 1.7.15)", stderr=""
        )

    monkeypatch.setattr(clean_build_spec.subprocess, "run", fake_run)

    clean_build_spec.check_packaged_tools(app_dist)


def test_clean_build_pins_approved_iperf_3_21_dynamic_auth_asset():
    clean_build_spec.validate_tool_sources()

    assert clean_build_spec.IPERF_RELEASE_ASSET == {
        "name": "iperf-3.21-win64-dynamic-auth.zip",
        "sha256": "0d3ac723df5cc7b2ab1851fe9441c14291c6583b6acf8ef81dabee73c145c2eb",
    }
    assert set(path.name for path in clean_build_spec.IPERF_RELEASE_SHA256) == {
        "iperf3.exe",
        "cygwin1.dll",
        "cygcrypto-3.dll",
        "cygz.dll",
    }


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_file",
        "wrong_file_version",
        "extra_root_property",
        "incomplete_upstream_source",
        "boolean_as_number",
        "missing_allowed_file",
    ],
)
def test_clean_build_rejects_inexact_runtime_tool_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
):
    source = Path(__file__).resolve().parents[1] / "resources" / "tools" / "windows-x64"
    target = tmp_path / "resources" / "tools" / "windows-x64"
    shutil.copytree(source, target)
    provenance = target / "iperf3" / "SOURCE_PROVENANCE.json"
    payload = json.loads(provenance.read_text(encoding="utf-8"))

    if change == "duplicate_file":
        payload["files"].insert(0, dict(payload["files"][0]))
    elif change == "wrong_file_version":
        payload["files"][0]["version"] = "999"
    elif change == "extra_root_property":
        payload["unapproved"] = True
    elif change == "incomplete_upstream_source":
        payload["upstream_sources"][2] = {"name": "OpenSSL Cygwin Runtime"}
    elif change == "boolean_as_number":
        fping = target / "fping" / "SOURCE_PROVENANCE.json"
        fping_payload = json.loads(fping.read_text(encoding="utf-8"))
        fping_payload["build"]["network_required_during_product_packaging"] = 0
        fping.write_text(
            json.dumps(fping_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        (target / "fping" / "README.txt").unlink()

    provenance.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(clean_build_spec, "ROOT", tmp_path)

    with pytest.raises(CleanBuildLockError):
        clean_build_spec.validate_tool_sources()


def test_changelog_path_prefers_packaged_assets_and_keeps_source_fallback(tmp_path):
    base_dir = Path("dist") / "NetConsole" / "_internal"
    fallback = get_changelog_path(base_dir)

    assert fallback == base_dir / "netconsole" / "docs" / "changelog.md"

    source_base = tmp_path / "source"
    source_changelog = source_base / "docs" / "CHANGELOG.md"
    source_changelog.parent.mkdir(parents=True)
    source_changelog.write_text("source changes", encoding="utf-8")

    assert get_changelog_path(source_base) == source_changelog

    packaged_base = tmp_path / "_internal"
    packaged = packaged_base / "netconsole" / "assets" / "changelog.md"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("changes", encoding="utf-8")

    assert get_changelog_path(packaged_base) == packaged


def test_clean_build_pyinstaller_output_is_clean_and_exe_smoke_runs():
    root = Path(__file__).resolve().parents[1]
    dist_root = root / "dist" / "_build" / "pyinstaller" / "dist"
    build_root = root / "dist" / "_build" / "pyinstaller" / "build"
    spec_root = root / "dist" / "_build" / "pyinstaller" / "spec"
    app_dist = dist_root / "NetConsoleBackend"
    build_env = os.environ.copy()
    existing_pythonpath = build_env.get("PYTHONPATH", "")
    build_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(root / "src"), existing_pythonpath))
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.build.clean_build_spec",
            "--prepare",
            "--write-spec",
        ],
        cwd=root,
        env=build_env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_root),
            "--workpath",
            str(build_root),
            str(spec_root / "NetConsoleBackend.spec"),
        ],
        cwd=root,
        env=build_env,
        check=True,
    )
    build_release.copy_release_tools(build_release.load_config(), app_dist)
    subprocess.run(
        [sys.executable, "-m", "scripts.build.clean_build_spec", "--validate"],
        cwd=root,
        env=build_env,
        check=True,
    )

    validate_dist_output(app_dist)
    assert not (app_dist / "docs").exists()
    assert not (app_dist / "tests").exists()
    assert not (app_dist / "project").exists()
    assert not (app_dist / "netconsole").exists()
    assert not (app_dist / "data").exists()
    assert not (app_dist / "runtime").exists()
    assert (app_dist / "_internal" / "netconsole").exists()
    assert (app_dist / "tools" / "windows-x64" / "fping" / "fping.exe").exists()
    assert (app_dist / "tools" / "windows-x64" / "iperf3" / "iperf3.exe").exists()
    assert (app_dist / "_internal" / "netconsole" / "assets" / "changelog.md").exists()
    assert not (app_dist / "_internal" / "netconsole" / "docs").exists()

    env = os.environ.copy()
    env["NETCONSOLE_SMOKE_TEST"] = "1"
    subprocess.run(
        [str(app_dist / "NetConsoleBackend.exe")],
        cwd=app_dist,
        env=env,
        check=True,
        timeout=20,
    )
