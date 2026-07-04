from __future__ import annotations

from pathlib import Path

from netconsole.core.version import APP_VERSION
from project.build_config import load_config
import zipfile

import pytest

from project.build_release import (
    BuildError,
    NUITKA_ALLOWED_RELEASE_ITEMS,
    find_forbidden_release_dirs,
    nuitka_command,
    validate_release_app_dir,
    validate_release_version_tree,
    validate_zip_file,
    zip_directory,
)


ROOT = Path(__file__).resolve().parents[1]


def test_nuitka_release_reads_unified_version() -> None:
    config = load_config()

    assert config.app_name == "NetConsole"
    assert config.app_version == APP_VERSION == "v1.3.6"
    assert config.zip_path("nuitka").name == f"NetConsole_{APP_VERSION}_nuitka.zip"


def test_nuitka_command_uses_onefile_and_required_resources() -> None:
    config = load_config()
    command_text = " ".join(nuitka_command(config, "8", config.backend_build_dir("nuitka") / "pkg.yml"))

    assert "--onefile" in command_text
    assert "--standalone" not in command_text
    assert "main.py" in command_text
    assert "netconsole/ui/icons" in command_text
    assert "netconsole/assets/changelog.md" in command_text
    assert "tools=tools" in command_text
    assert "--report=" in command_text
    assert "data\\sites" not in command_text
    assert "data\\runtime" not in command_text
    assert "data\\shared" not in command_text


def test_nuitka_scripts_do_not_call_publish_flow() -> None:
    script_text = (ROOT / "build_nuitka_release.bat").read_text(encoding="utf-8")
    helper_text = (ROOT / "project" / "build_nuitka_release.py").read_text(encoding="utf-8")
    combined = f"{script_text}\n{helper_text}".lower()

    forbidden_tokens = (
        "project\\release.py",
        "project/release.py",
        "git commit",
        "git tag",
        "git push",
        "git remote",
        "v1.2.",
        "network_toolkit",
        "tasks_v2",
    )
    for token in forbidden_tokens:
        assert token not in combined


def test_nuitka_release_allowlist_rejects_project_root_pollution(tmp_path: Path) -> None:
    release_dir = tmp_path / "nuitka"
    release_dir.mkdir()
    (release_dir / "NetConsole.exe").write_text("", encoding="utf-8")
    (release_dir / "data").mkdir()
    (release_dir / "runtime").mkdir()
    (release_dir / "docs").mkdir()
    (release_dir / "tests").mkdir()
    (release_dir / "project").mkdir()

    with pytest.raises(BuildError, match="Unexpected release items|Forbidden release directories"):
        validate_release_app_dir(release_dir, NUITKA_ALLOWED_RELEASE_ITEMS)

    forbidden = {path.name for path in find_forbidden_release_dirs(release_dir)}
    assert {"docs", "tests", "project"}.issubset(forbidden)


def test_nuitka_zip_uses_release_allowlist_only(tmp_path: Path) -> None:
    release_dir = tmp_path / "nuitka"
    release_dir.mkdir()
    (release_dir / "NetConsole.exe").write_text("exe", encoding="utf-8")
    (release_dir / "data").mkdir()
    (release_dir / "runtime" / "logs").mkdir(parents=True)
    zip_path = release_dir / "NetConsole.zip"

    zip_directory(release_dir, zip_path, release_dir, NUITKA_ALLOWED_RELEASE_ITEMS)
    validate_zip_file(zip_path)

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "NetConsole.exe" in names
    assert "data/" in names
    assert "runtime/logs/" in names
    assert all(not name.startswith(("docs/", "tests/", "project/")) for name in names)


def test_release_zip_validation_rejects_forbidden_entries(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("NetConsole.exe", "")
        archive.writestr("docs/readme.md", "")

    with pytest.raises(BuildError, match="Forbidden release zip entries"):
        validate_zip_file(zip_path)


def test_release_validation_rejects_pyinstaller_internal_docs(tmp_path: Path) -> None:
    app_dir = tmp_path / "NetConsole"
    app_dir.mkdir()
    (app_dir / "NetConsole.exe").write_text("", encoding="utf-8")
    (app_dir / "data").mkdir(parents=True)
    (app_dir / "runtime").mkdir()
    (app_dir / "_internal" / "netconsole" / "docs").mkdir(parents=True)
    (app_dir / "_internal" / "netconsole" / "docs" / "changelog.md").write_text("", encoding="utf-8")

    with pytest.raises(BuildError, match="Forbidden release directories"):
        validate_release_app_dir(app_dir, frozenset({"NetConsole.exe", "_internal", "data", "runtime"}))


def test_release_version_tree_rejects_sibling_backend_pollution(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1.3.1"
    (version_dir / "nuitka").mkdir(parents=True)
    (version_dir / "pyinstaller" / "NetConsole" / "_internal" / "netconsole").mkdir(parents=True)
    validate_release_version_tree(version_dir)

    (version_dir / "nuitka" / "project").mkdir()

    with pytest.raises(BuildError, match="Forbidden release directories"):
        validate_release_version_tree(version_dir)


def test_release_packaging_does_not_use_project_root_sources() -> None:
    script = (ROOT / "project" / "build_release.py").read_text(encoding="utf-8").lower()
    batch_scripts = "\n".join(
        [
            (ROOT / "build_release.bat").read_text(encoding="utf-8").lower(),
            (ROOT / "build_nuitka_release.bat").read_text(encoding="utf-8").lower(),
        ]
    )

    forbidden_script_tokens = (
        "copytree(root",
        "copytree(project_root",
        "zipfile.write(root",
        "path(root).rglob",
        ".rglob(",
        "glob(\"**/*\")",
        "glob('**/*')",
        "robocopy",
        "/mir",
    )
    for token in forbidden_script_tokens:
        assert token not in script

    forbidden_batch_tokens = (
        "compress-archive",
        "-path .\\*",
        "-path release\\*",
        "robocopy",
        "/mir",
        "xcopy",
    )
    for token in forbidden_batch_tokens:
        assert token not in batch_scripts
