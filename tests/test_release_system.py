from pathlib import Path
import subprocess

import clean_build_spec
import release
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
    text = (root / "release.py").read_text(encoding="utf-8")

    assert "self-hosted Gitea repository" in text
    assert "Personal Access Token" in text
    assert "SSH key" in text
    assert "Release system should not block on auth failure" in text


def test_release_script_pushes_two_remotes_and_tags():
    root = Path(__file__).resolve().parents[1]
    text = (root / "release.py").read_text(encoding="utf-8")

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

    assert "release.py" in text
    assert "PROJECT_ROOT=%ROOT%\\project" in text
    assert "clean_build_spec.py --prepare --write-spec" in text
    assert "PyInstaller --noconfirm --distpath \"%DIST_ROOT%\" --workpath \"%BUILD_ROOT%\" \"%SPEC_ROOT%\\NetConsole.spec\"" in text
    assert "clean_build_spec.py --finalize" in text
    assert "--add-data" not in text
    assert "%RELEASE_ROOT%\\NetConsole_%APP_VERSION%.zip" in text


def test_clean_build_spec_uses_strict_whitelist_and_excludes():
    assert clean_build_spec.CLEAN_BUILD is True
    assert (".", ".") in clean_build_spec.FORBIDDEN_DATA
    assert ("project", "project") in clean_build_spec.FORBIDDEN_DATA
    assert ("tests", "tests") in clean_build_spec.FORBIDDEN_DATA
    assert ("docs", "docs") in clean_build_spec.FORBIDDEN_DATA
    assert ("netconsole", "netconsole") in clean_build_spec.ALLOWED_DATA
    assert ("netconsole/ui/icons", "netconsole/ui/icons") in clean_build_spec.ALLOWED_DATA
    assert ("netconsole/docs/changelog.md", "netconsole/docs/changelog.md") in clean_build_spec.ALLOWED_DATA
    assert "tests" in clean_build_spec.EXCLUDE_DIRS
    assert "docs" in clean_build_spec.EXCLUDE_DIRS
    assert "project" in clean_build_spec.EXCLUDE_DIRS
    assert "__pycache__" in clean_build_spec.EXCLUDE_DIRS


def test_clean_build_spec_scans_runtime_import_graph():
    imports = clean_build_spec.scan_import_graph()

    assert "netconsole.app" in imports
    assert all(not item.startswith("tests") for item in imports)
    assert all(not item.startswith("project") for item in imports)


def test_clean_build_runtime_subset_copies_only_imported_modules_and_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(clean_build_spec, "RUNTIME_ROOT", tmp_path / "runtime")

    staged_files = clean_build_spec.build_runtime_subset_from_import_graph()
    staged_relative = {path.relative_to(clean_build_spec.RUNTIME_ROOT) for path in staged_files}
    expected_relative = {
        path.relative_to(clean_build_spec.ROOT)
        for path in clean_build_spec.build_runtime_module_map().values()
    }

    assert expected_relative <= staged_relative
    assert (clean_build_spec.RUNTIME_ROOT / "netconsole" / "ui" / "icons" / "love.ico").exists()
    assert (clean_build_spec.RUNTIME_ROOT / "netconsole" / "docs" / "changelog.md").exists()
    assert not (clean_build_spec.RUNTIME_ROOT / "netconsole" / "tests").exists()
    assert not (clean_build_spec.RUNTIME_ROOT / "netconsole" / "project").exists()
    all_py_files = {
        path.relative_to(clean_build_spec.RUNTIME_ROOT)
        for path in (clean_build_spec.RUNTIME_ROOT / "netconsole").rglob("*.py")
    }
    assert all_py_files == expected_relative


def test_clean_build_spec_does_not_use_copytree():
    root = Path(__file__).resolve().parents[1]
    text = (root / "clean_build_spec.py").read_text(encoding="utf-8")

    assert "copytree" not in text
    assert "_copy_runtime_package" not in text


def test_clean_build_spec_generated_spec_is_clean(tmp_path, monkeypatch):
    spec_file = tmp_path / "NetConsole.spec"
    monkeypatch.setattr(clean_build_spec, "SPEC_ROOT", tmp_path)
    monkeypatch.setattr(clean_build_spec, "SPEC_FILE", spec_file)

    clean_build_spec.write_spec()
    text = spec_file.read_text(encoding="utf-8")

    assert "CLEAN_BUILD = True" in text
    assert "RUNTIME_IMPORTS =" in text
    assert "datas=[]" in text
    assert "excludes=['tests', 'docs', 'project', '__pycache__']" in text
    assert "contents_directory='_internal'" in text
    assert "project\\\\main.py" in text or "project/main.py" in text
    assert "('.', '.')" not in text
    assert "('project', 'project')" not in text
    assert "('tests', 'tests')" not in text
    assert "('docs', 'docs')" not in text
