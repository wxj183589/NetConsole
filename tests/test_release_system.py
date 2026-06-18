from pathlib import Path
import subprocess

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
    assert "--distpath \"%DIST_ROOT%\"" in text
    assert "--workpath \"%BUILD_ROOT%\"" in text
    assert "--specpath \"%SPEC_ROOT%\"" in text
    assert "--version-file \"%ROOT%\\project\\version_info.txt\"" in text
    assert "--paths \"%ROOT%\"" in text
    assert "--contents-directory \"_internal\"" in text
    assert "--exclude-module tests" in text
    assert "--exclude-module docs" in text
    assert "--exclude-module project" in text
    assert "--exclude-module __pycache__" in text
    assert "/XD docs tests project __pycache__" in text
    assert "robocopy \"%RUNTIME_ROOT%\\netconsole\" \"%DIST_ROOT%\\NetConsole\\netconsole\"" in text
    assert "--add-data" not in text
    assert "%PROJECT_ROOT%\\main.py" in text
    assert "%ROOT%\\main.py" not in text
    assert "netconsole\\docs;netconsole\\docs" not in text
    assert "docs\\changelog.md;assets\\docs" not in text
    assert "Unexpected dist item:" in text
    assert 'allowed = @(\'NetConsole.exe\', \'_internal\', \'netconsole\')' in text
    assert "if not exist \"%DIST_ROOT%\\NetConsole\\netconsole\" goto failed" in text
    assert "%DIST_ROOT%\\NetConsole\\_internal\\netconsole" in text
    assert "%DIST_ROOT%\\NetConsole\\netconsole\\docs" in text
    assert "%RELEASE_ROOT%\\NetConsole_%APP_VERSION%.zip" in text
