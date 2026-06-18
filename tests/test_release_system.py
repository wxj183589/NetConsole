from pathlib import Path
import os
import subprocess
import sys

import clean_build_spec
import pytest
from project import release
from netconsole.build.clean_build_lock import (
    CleanBuildLockError,
    validate_datas,
    validate_dist_output,
    validate_project_safety,
    validate_pyinstaller_command,
)
from netconsole.core.version import APP_VERSION, BUILD_TIME, GIT_COMMIT


def test_version_file_exposes_release_metadata():
    assert APP_VERSION.startswith("v1.0.")
    assert BUILD_TIME
    assert GIT_COMMIT


def test_next_patch_version_uses_existing_v1_tags():
    assert release.next_patch_version([]) == "v1.0.0"
    assert release.next_patch_version(["v1.0.0", "v1.0.2", "v0.9.9", "bad"]) == "v1.0.3"


def test_render_version_py_contains_single_version_source_fields():
    text = release.render_version_py("v1.0.7", "2026-06-17 12:00:00", "abc1234")

    assert 'APP_VERSION = "v1.0.7"' in text
    assert 'BUILD_TIME = "2026-06-17 12:00:00"' in text
    assert 'GIT_COMMIT = "abc1234"' in text
    assert "https://nas.love-ok.com:3021/mengyou/NetConsole.git" in text
    assert "https://github.com/wxj183589/NetConsole.git" in text


def test_release_script_documents_gitea_https_authentication():
    root = Path(__file__).resolve().parents[1]
    text = (root / "project" / "release.py").read_text(encoding="utf-8")

    assert not (root / "release.py").exists()
    assert "self-hosted Gitea repository" in text
    assert "Personal Access Token" in text
    assert "SSH key" in text
    assert "Release system should not block on auth failure" in text


def test_release_script_pushes_two_remotes_and_tags():
    root = Path(__file__).resolve().parents[1]
    text = (root / "project" / "release.py").read_text(encoding="utf-8")

    assert "def safe_run(cmd: list[str])" in text
    assert "def check_git_remote()" in text
    assert 'git", "push", "origin", "main"' in text
    assert 'git", "push", "github", "main"' in text
    assert 'git", "push", "origin", selected_version' in text
    assert 'git", "push", "github", selected_version' in text
    assert 'git", "tag", "-a", selected_version' in text


def test_release_push_failures_do_not_interrupt_release(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(release, "write_release_files", lambda *args: None)
    monkeypatch.setattr(release, "ensure_remotes", lambda dry_run: None)
    monkeypatch.setattr(release, "check_git_remote", lambda: False)
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
    assert not result.push_origin_success
    assert not result.push_github_success
    assert result.final_status == release.OFFLINE_RELEASE
    assert ["git", "tag", "-a", "v1.0.9", "-m", "Release v1.0.9"] in commands
    assert ["git", "push", "origin", "main"] in commands
    assert ["git", "push", "github", "main"] in commands
    assert ["git", "push", "origin", "v1.0.9"] in commands
    assert ["git", "push", "github", "v1.0.9"] in commands


def test_release_tag_failure_does_not_interrupt_push_attempts(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(release, "write_release_files", lambda *args: None)
    monkeypatch.setattr(release, "ensure_remotes", lambda dry_run: None)
    monkeypatch.setattr(release, "check_git_remote", lambda: True)
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
    assert result.push_origin_success
    assert result.push_github_success
    assert result.final_status == release.LOCAL_BUILD_ONLY
    assert ["git", "push", "origin", "main"] in commands
    assert ["git", "push", "github", "main"] in commands


def test_build_release_script_uses_project_output_and_release_zip():
    root = Path(__file__).resolve().parents[1]
    text = (root / "build_release.bat").read_text(encoding="utf-8")

    assert "project\\release.py" in text
    assert "PROJECT_ROOT=%ROOT%\\project" in text
    assert "clean_build_spec.py --prepare --write-spec" in text
    assert "PyInstaller --noconfirm --clean --distpath \"%DIST_ROOT%\" --workpath \"%BUILD_ROOT%\" \"%SPEC_ROOT%\\NetConsole.spec\"" in text
    assert "clean_build_spec.py --validate" in text
    assert "--finalize" not in text
    assert "--add-data" not in text
    assert "%RELEASE_ROOT%\\NetConsole_%APP_VERSION%.zip" in text


def test_clean_build_spec_uses_strict_whitelist_and_excludes():
    assert clean_build_spec.CLEAN_BUILD is True
    assert (".", ".") in clean_build_spec.FORBIDDEN_DATA
    assert ("project", "project") in clean_build_spec.FORBIDDEN_DATA
    assert ("tests", "tests") in clean_build_spec.FORBIDDEN_DATA
    assert ("docs", "docs") in clean_build_spec.FORBIDDEN_DATA
    assert ("netconsole", "netconsole") in clean_build_spec.ALLOWED_DATA
    assert ("data", "data") in clean_build_spec.ALLOWED_DATA
    assert ("netconsole/ui/icons", "netconsole/ui/icons") in clean_build_spec.ALLOWED_DATA
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
    assert "datas=RUNTIME_DATAS" in text
    assert "excludes=['tests', 'docs', 'project', '__pycache__']" in text
    assert "contents_directory='_internal'" in text
    assert "project\\\\main.py" in text or "project/main.py" in text
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
        str(root / "project" / "dist"),
        "--workpath",
        str(root / "project" / "build"),
    ]

    validate_pyinstaller_command(args)

    with pytest.raises(CleanBuildLockError, match="Missing required PyInstaller option: --windowed"):
        validate_pyinstaller_command([arg for arg in args if arg != "--windowed"])


@pytest.mark.parametrize("forbidden", ["docs", "tests", "project", "build", "spec"])
def test_clean_build_lock_rejects_forbidden_dist_dirs(tmp_path, forbidden):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "netconsole").mkdir(parents=True)
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")
    (app_dist / forbidden).mkdir()

    with pytest.raises(CleanBuildLockError, match="CleanBuildLock violation"):
        validate_dist_output(app_dist)


def test_clean_build_success_shape_allows_independent_exe_layout(tmp_path):
    app_dist = tmp_path / "NetConsole"
    (app_dist / "_internal" / "netconsole" / "ui" / "icons").mkdir(parents=True)
    (app_dist / "NetConsole.exe").write_text("", encoding="utf-8")
    (app_dist / "_internal" / "netconsole" / "ui" / "icons" / "love.ico").write_text("", encoding="utf-8")

    validate_dist_output(app_dist)

    assert sorted(path.name for path in app_dist.iterdir()) == [
        "NetConsole.exe",
        "_internal",
    ]
    assert not (app_dist / "docs").exists()
    assert not (app_dist / "tests").exists()
    assert not (app_dist / "project").exists()
    assert not (app_dist / "netconsole").exists()
    assert (app_dist / "_internal" / "netconsole").exists()


def test_clean_build_pyinstaller_output_is_clean_and_exe_smoke_runs():
    root = Path(__file__).resolve().parents[1]
    dist_root = root / "project" / "dist"
    build_root = root / "project" / "build"
    spec_root = root / "project" / "spec"
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
    subprocess.run([sys.executable, "clean_build_spec.py", "--validate"], cwd=root, check=True)

    validate_dist_output(app_dist)
    forbidden_names = {"docs", "tests", "project"}
    assert not [path for path in app_dist.rglob("*") if path.name in forbidden_names]
    assert not (app_dist / "netconsole").exists()
    assert (app_dist / "_internal" / "netconsole").exists()

    env = os.environ.copy()
    env["NETCONSOLE_SMOKE_TEST"] = "1"
    subprocess.run([str(app_dist / "NetConsole.exe")], cwd=app_dist, env=env, check=True, timeout=20)
