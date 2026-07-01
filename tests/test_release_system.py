from pathlib import Path
import os
import subprocess
import sys

import clean_build_spec
import pytest
from project import release
from scripts.check_runtime_deps import check_runtime_deps
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


def test_version_file_exposes_release_metadata():
    assert APP_VERSION == "v1.3.4"
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
    text = (root / "project" / "release.py").read_text(encoding="utf-8")

    assert not (root / "release.py").exists()
    assert "self-hosted Gitea repository" in text
    assert "SSH key" in text
    assert "SSH key authentication is required" in text
    assert "Release system should not block on auth failure" in text


def test_release_script_pushes_two_remotes_and_tags():
    root = Path(__file__).resolve().parents[1]
    text = (root / "project" / "release.py").read_text(encoding="utf-8")

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
        lambda args, check=True: "abc1234" if args[:2] == ["rev-parse", "--short"] else "",
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
    assert any(cmd[:4] == ["git", "tag", "-a", "v1.0.9"] and cmd[4] == "-m" and cmd[5].endswith("v1.0.9") for cmd in commands)
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
        lambda args, check=True: "abc1234" if args[:2] == ["rev-parse", "--short"] else "",
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
    text = (root / "build_release.bat").read_text(encoding="utf-8")

    assert "project\\build_release.py" in text
    assert "--backend pyinstaller --build-editions both %*" in text
    assert "project\\release.py" not in text
    assert "PROJECT_ROOT=%ROOT%\\project" not in text
    assert "--add-data" not in text
    assert "project\\build_release.py\" --backend pyinstaller --build-editions both %*" in text


def test_changelog_source_is_chinese_for_zh_ui():
    root = Path(__file__).resolve().parents[1]
    text = (root / "netconsole" / "docs" / "changelog.md").read_text(encoding="utf-8")
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
    text = (root / "project" / "release.py").read_text(encoding="utf-8")

    assert "auto release build" not in text
    assert 'git", "commit", "--allow-empty", "-m"' in text
    assert 'git", "tag", "-a", selected_version' in text

def test_clean_build_spec_uses_strict_whitelist_and_excludes():
    assert clean_build_spec.CLEAN_BUILD is True
    assert (".", ".") in clean_build_spec.FORBIDDEN_DATA
    assert ("project", "project") in clean_build_spec.FORBIDDEN_DATA
    assert ("tests", "tests") in clean_build_spec.FORBIDDEN_DATA
    assert ("docs", "docs") in clean_build_spec.FORBIDDEN_DATA
    assert ("netconsole", "netconsole") in clean_build_spec.ALLOWED_DATA
    assert ("data", "data") not in clean_build_spec.ALLOWED_DATA
    assert ("tools", "tools") in clean_build_spec.ALLOWED_DATA
    assert ("netconsole/ui/icons", "netconsole/ui/icons") in clean_build_spec.ALLOWED_DATA
    assert ("netconsole/docs", "netconsole/docs") not in clean_build_spec.ALLOWED_DATA
    assert ("netconsole/docs/changelog.md", "netconsole/docs/changelog.md") not in clean_build_spec.ALLOWED_DATA
    assert "tests" in clean_build_spec.EXCLUDE_DIRS
    assert "docs" in clean_build_spec.EXCLUDE_DIRS
    assert "project" in clean_build_spec.EXCLUDE_DIRS
    assert "__pycache__" in clean_build_spec.EXCLUDE_DIRS


def test_clean_build_spec_scans_runtime_import_graph():
    imports = clean_build_spec.scan_import_graph()

    assert "netconsole.app" in imports
    assert all(not item.startswith("tests") for item in imports)
    assert all(not item.startswith("project") for item in imports)


def test_clean_build_import_graph_is_entry_file_driven():
    root = Path(__file__).resolve().parents[1]
    text = (root / "clean_build_spec.py").read_text(encoding="utf-8")

    assert "pending_sources = [ENTRY_FILE]" in text
    assert ".rglob(" not in text
    assert '(ROOT / "netconsole").rglob' not in text
    assert "(ROOT / 'netconsole').rglob" not in text


def test_clean_build_runtime_subset_copies_only_imported_modules_and_assets(tmp_path, monkeypatch):
    runtime_files = clean_build_spec.build_runtime_subset_from_import_graph()
    staged_relative = {path.relative_to(clean_build_spec.ROOT) for path in runtime_files}
    expected_relative = {
        path.relative_to(clean_build_spec.ROOT)
        for path in clean_build_spec.build_runtime_module_map().values()
    }

    assert staged_relative == expected_relative
    assert all("docs" not in path.parts for path in staged_relative)
    assert all("tests" not in path.parts for path in staged_relative)
    assert all("project" not in path.parts for path in staged_relative)
    datas = clean_build_spec.build_runtime_datas_from_import_graph()
    assert any(destination == "netconsole/ui/icons" and source.endswith("love.ico") for source, destination in datas)
    assert any(destination == "tools" and Path(source).name == "tools" for source, destination in datas)
    assert all(destination != "data" for _source, destination in datas)


def test_clean_build_spec_does_not_use_directory_copy_or_full_scan():
    root = Path(__file__).resolve().parents[1]
    text = (root / "clean_build_spec.py").read_text(encoding="utf-8")

    assert "copytree" not in text
    assert "_copy_runtime_package" not in text
    assert ".rglob(" not in text


def test_clean_build_spec_generated_spec_is_clean(tmp_path, monkeypatch):
    spec_file = tmp_path / "NetConsole.spec"
    monkeypatch.setattr(clean_build_spec, "SPEC_ROOT", tmp_path)
    monkeypatch.setattr(clean_build_spec, "SPEC_FILE", spec_file)

    clean_build_spec.write_spec()
    text = spec_file.read_text(encoding="utf-8")

    assert "CLEAN_BUILD = True" in text
    assert "RUNTIME_IMPORTS =" in text
    assert "RUNTIME_DATAS =" in text
    assert 'collect_all("PySide6")' in text
    assert "VC_RUNTIME_BINARIES =" in text
    assert "pyside_binaries" in text
    assert "pyside_hiddenimports" in text
    assert "datas=RUNTIME_DATAS" in text
    assert "datas=RUNTIME_DATAS + pyside_datas" in text
    assert "binaries=pyside_binaries + VC_RUNTIME_BINARIES" in text
    assert "excludes=['tests', 'docs', 'project', '__pycache__']" in text
    assert "contents_directory='_internal'" in text
    assert "('tools', 'tools')" in text or '("tools", "tools")' in text
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
    with pytest.raises(CleanBuildLockError, match="Illegal PyInstaller spec datasource"):
        validate_project_safety(spec_text="a = Analysis(['main.py'], datas=[('.', '.')])")


def test_clean_build_lock_validates_required_pyinstaller_options():
    root = Path(__file__).resolve().parents[1]
    args = [
        "--onedir",
        "--windowed",
        "--name",
        "NetConsole",
        "--icon",
        str(root / "netconsole" / "ui" / "icons" / "love.ico"),
        "--distpath",
        str(root / "release" / "_build" / "pyinstaller" / "dist"),
        "--workpath",
        str(root / "release" / "_build" / "pyinstaller" / "build"),
    ]

    validate_pyinstaller_command(args)

    with pytest.raises(CleanBuildLockError, match="Missing required PyInstaller option: --windowed"):
        validate_pyinstaller_command([arg for arg in args if arg != "--windowed"])


@pytest.mark.parametrize("forbidden", ["docs", "tests", "project", "build", "spec"])
def test_clean_build_lock_rejects_forbidden_dist_dirs(tmp_path, forbidden):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "netconsole").mkdir(parents=True)
    (app_dist / "data").mkdir()
    (app_dist / "runtime" / "logs").mkdir(parents=True)
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")
    (app_dist / forbidden).mkdir()

    with pytest.raises(CleanBuildLockError, match="CleanBuildLock violation"):
        validate_dist_output(app_dist)


def test_clean_build_success_shape_allows_independent_exe_layout(tmp_path):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "netconsole" / "ui" / "icons").mkdir(parents=True)
    (app_dist / "data").mkdir()
    (app_dist / "runtime" / "logs").mkdir(parents=True)
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "netconsole" / "ui" / "icons" / "love.ico").write_text("", encoding="utf-8")

    validate_dist_output(app_dist)

    assert sorted(path.name for path in app_dist.iterdir()) == [
        "NetConsole.exe",
        "_internal",
        "data",
        "runtime",
    ]
    assert not (app_dist / "docs").exists()
    assert not (app_dist / "tests").exists()
    assert not (app_dist / "project").exists()
    assert not (app_dist / "netconsole").exists()
    assert (app_dist / "_internal" / "netconsole").exists()


def test_clean_build_packaged_tools_validation(tmp_path):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "netconsole" / "ui" / "icons").mkdir(parents=True)
    (app_dist / "_internal" / "tools" / "fping_v5").mkdir(parents=True)
    (app_dist / "_internal" / "tools" / "iperf").mkdir(parents=True)
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "netconsole" / "ui" / "icons" / "love.ico").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "fping_v5" / "fping.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "fping_v5" / "cygwin1.dll").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "iperf" / "iperf3.exe").write_text("", encoding="utf-8")
    for dll_name in ("cygcrypto-3.dll", "cygwin1.dll", "cygz.dll"):
        (app_dist / "_internal" / "tools" / "iperf" / dll_name).write_text("", encoding="utf-8")

    clean_build_spec.check_packaged_tools(app_dist, run_version_check=False)


def test_clean_build_packaged_tools_validation_rejects_missing_tool(tmp_path):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "tools" / "fping_v5").mkdir(parents=True)
    (app_dist / "_internal" / "tools" / "fping_v5" / "fping.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "fping_v5" / "cygwin1.dll").write_text("", encoding="utf-8")

    with pytest.raises(CleanBuildLockError, match="packaged runtime tool is missing"):
        clean_build_spec.check_packaged_tools(app_dist, run_version_check=False)


def test_collect_vc_runtime_dlls_finds_required_files(tmp_path):
    dll_dir = tmp_path / "runtime"
    dll_dir.mkdir()
    for dll_name in clean_build_spec.REQUIRED_VC_RUNTIME_DLLS:
        (dll_dir / dll_name).write_text("", encoding="utf-8")

    result = clean_build_spec.collect_vc_runtime_dlls([dll_dir])

    assert {Path(source).name for source, _target in result} == set(clean_build_spec.REQUIRED_VC_RUNTIME_DLLS)
    assert all(target == "." for _source, target in result)


def test_collect_vc_runtime_dlls_rejects_missing_required_file(tmp_path):
    dll_dir = tmp_path / "runtime"
    dll_dir.mkdir()
    for dll_name in clean_build_spec.REQUIRED_VC_RUNTIME_DLLS:
        if dll_name != "VCRUNTIME140_1.dll":
            (dll_dir / dll_name).write_text("", encoding="utf-8")

    with pytest.raises(CleanBuildLockError, match="VCRUNTIME140_1.dll"):
        clean_build_spec.collect_vc_runtime_dlls([dll_dir])


def _make_packaged_runtime(tmp_path: Path) -> Path:
    app_dist = tmp_path / "NetConsole"
    internal = app_dist / "_internal"
    (internal / "PySide6" / "plugins" / "platforms").mkdir(parents=True)
    (internal / "tools" / "fping_v5").mkdir(parents=True)
    (internal / "tools" / "iperf").mkdir(parents=True)
    (app_dist / "data").mkdir(parents=True)
    (app_dist / "runtime" / "logs").mkdir(parents=True)
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")
    for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "python310.dll"):
        (internal / "PySide6" / name).write_text("", encoding="utf-8")
    for name in ("VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "MSVCP140.dll", "CONCRT140.dll", "msvcp140_1.dll", "msvcp140_2.dll"):
        (internal / name).write_text("", encoding="utf-8")
    (internal / "PySide6" / "plugins" / "platforms" / "qwindows.dll").write_text("", encoding="utf-8")
    (internal / "tools" / "fping_v5" / "fping.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "fping_v5" / "cygwin1.dll").write_text("", encoding="utf-8")
    (internal / "tools" / "fping_v5" / "cygwin1.dll").write_text("", encoding="utf-8")
    (internal / "tools" / "iperf" / "iperf3.exe").write_text("", encoding="utf-8")
    return app_dist


def test_runtime_deps_rejects_missing_internal_dir(tmp_path):
    app_dist = tmp_path / "NetConsole"
    app_dist.mkdir()
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")

    result = check_runtime_deps(app_dist)

    assert not result.ok
    assert any("_internal" in message for message in result.messages)


def test_runtime_deps_rejects_missing_qtgui_dll(tmp_path):
    app_dist = _make_packaged_runtime(tmp_path)
    (app_dist / "_internal" / "PySide6" / "Qt6Gui.dll").unlink()

    result = check_runtime_deps(app_dist)

    assert not result.ok
    assert any("Qt6Gui.dll missing" in message and "QtGui" in message for message in result.messages)


def test_runtime_deps_rejects_missing_qwindows_plugin(tmp_path):
    app_dist = _make_packaged_runtime(tmp_path)
    (app_dist / "_internal" / "PySide6" / "plugins" / "platforms" / "qwindows.dll").unlink()

    result = check_runtime_deps(app_dist)

    assert not result.ok
    assert any("qwindows.dll missing" in message and "Qt platform plugin" in message for message in result.messages)


def test_runtime_deps_accepts_complete_packaged_runtime(tmp_path):
    app_dist = _make_packaged_runtime(tmp_path)

    result = check_runtime_deps(app_dist)

    assert result.ok
    assert "[OK] Qt6Core.dll found" in result.messages
    assert "[OK] Qt6Gui.dll found" in result.messages
    assert "[OK] Qt6Widgets.dll found" in result.messages
    assert "[OK] qwindows.dll found" in result.messages
    assert "[OK] VCRUNTIME140.dll found" in result.messages
    assert "[OK] MSVCP140.dll found" in result.messages
    assert "[OK] CONCRT140.dll found" in result.messages
    assert "[OK] tools/fping_v5/fping.exe found" in result.messages
    assert "[OK] tools/iperf/iperf3.exe found" in result.messages
    assert "[OK] runtime/logs directory found" in result.messages


def test_check_packaged_runtime_script_runs_from_repo_root(tmp_path):
    root = Path(__file__).resolve().parents[1]
    app_dist = _make_packaged_runtime(tmp_path)

    completed = subprocess.run(
        [sys.executable, "scripts/check_packaged_runtime.py", str(app_dist)],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "[OK] Qt6Gui.dll found" in completed.stdout
    assert "[OK] VCRUNTIME140.dll found" in completed.stdout


def test_readme_documents_complete_folder_and_vc_runtime():
    root = Path(__file__).resolve().parents[1]
    text = (root / "README.md").read_text(encoding="utf-8")

    assert "NetConsole" in text
    assert "VC++" in text
    assert "Windows" in text
    assert "runtime" in text.lower()

def test_clean_build_packaged_tools_version_checks_accept_expected_markers(tmp_path, monkeypatch):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "tools" / "fping_v5").mkdir(parents=True)
    (app_dist / "_internal" / "tools" / "iperf").mkdir(parents=True)
    (app_dist / "_internal" / "tools" / "fping_v5" / "fping.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "fping_v5" / "cygwin1.dll").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "tools" / "iperf" / "iperf3.exe").write_text("", encoding="utf-8")
    for dll_name in ("cygcrypto-3.dll", "cygwin1.dll", "cygz.dll"):
        (app_dist / "_internal" / "tools" / "iperf" / dll_name).write_text("", encoding="utf-8")

    def fake_run(args, **kwargs):
        if str(args[0]).endswith("fping.exe"):
            return subprocess.CompletedProcess(args, 2, stdout="Version 5.5\nHost not found: -v error", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="iperf 3.20 (cJSON 1.7.15)", stderr="")

    monkeypatch.setattr(clean_build_spec.subprocess, "run", fake_run)

    clean_build_spec.check_packaged_tools(app_dist)


def test_changelog_path_prefers_packaged_assets_and_keeps_source_fallback(tmp_path):
    base_dir = Path("dist") / "NetConsole" / "_internal"
    fallback = get_changelog_path(base_dir)

    assert fallback == base_dir / "netconsole" / "docs" / "changelog.md"

    packaged_base = tmp_path / "_internal"
    packaged = packaged_base / "netconsole" / "assets" / "changelog.md"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("changes", encoding="utf-8")

    assert get_changelog_path(packaged_base) == packaged


def test_clean_build_pyinstaller_output_is_clean_and_exe_smoke_runs():
    root = Path(__file__).resolve().parents[1]
    dist_root = root / "release" / "_build" / "pyinstaller" / "dist"
    build_root = root / "release" / "_build" / "pyinstaller" / "build"
    spec_root = root / "release" / "_build" / "pyinstaller" / "spec"
    app_dist = dist_root / "NetConsole"

    subprocess.run([sys.executable, "clean_build_spec.py", "--prepare", "--write-spec"], cwd=root, check=True)
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
            str(spec_root / "NetConsole.spec"),
        ],
        cwd=root,
        check=True,
    )
    (app_dist / "data").mkdir(exist_ok=True)
    (app_dist / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "clean_build_spec.py", "--validate"], cwd=root, check=True)

    validate_dist_output(app_dist)
    assert not (app_dist / "docs").exists()
    assert not (app_dist / "tests").exists()
    assert not (app_dist / "project").exists()
    assert not (app_dist / "netconsole").exists()
    assert (app_dist / "data").exists()
    assert (app_dist / "runtime" / "logs").exists()
    assert (app_dist / "_internal" / "netconsole").exists()
    assert (app_dist / "_internal" / "tools" / "fping_v5" / "fping.exe").exists()
    assert (app_dist / "_internal" / "tools" / "iperf" / "iperf3.exe").exists()
    assert (app_dist / "_internal" / "netconsole" / "assets" / "changelog.md").exists()
    assert not (app_dist / "_internal" / "netconsole" / "docs").exists()

    env = os.environ.copy()
    env["NETCONSOLE_SMOKE_TEST"] = "1"
    subprocess.run([str(app_dist / "NetConsole.exe")], cwd=app_dist, env=env, check=True, timeout=20)
