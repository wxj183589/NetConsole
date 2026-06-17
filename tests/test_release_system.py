from pathlib import Path

from project import release
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


def test_release_script_pushes_two_remotes_and_tags():
    root = Path(__file__).resolve().parents[1]
    text = (root / "release.py").read_text(encoding="utf-8")

    assert 'git", "push", "origin", "main"' in text
    assert 'git", "push", "github", "main"' in text
    assert 'git", "push", "origin", selected_version' in text
    assert 'git", "push", "github", selected_version' in text
    assert 'git", "tag", "-a", selected_version' in text


def test_build_release_script_uses_build_output_and_release_zip():
    root = Path(__file__).resolve().parents[1]
    text = (root / "build_release.bat").read_text(encoding="utf-8")

    assert "release.py" in text
    assert "build_output" in text
    assert "--distpath \"%BUILD_ROOT%\\dist\"" in text
    assert "--workpath \"%BUILD_ROOT%\\build\"" in text
    assert "--specpath \"%BUILD_ROOT%\\spec\"" in text
    assert "--version-file \"%ROOT%project\\version_info.txt\"" in text
    assert '--add-data "%ROOT%netconsole;netconsole"' in text
    assert "%RELEASE_ROOT%\\NetConsole_%APP_VERSION%.zip" in text
