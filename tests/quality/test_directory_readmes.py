from __future__ import annotations

from pathlib import Path

import scripts.quality.check_directory_readmes as checker
from scripts.quality.check_directory_readmes import format_report
from scripts.quality.check_directory_readmes import ReadmeReport
from scripts.quality.check_directory_readmes import REQUIRED_MAJOR_SECTIONS
from scripts.quality.check_directory_readmes import scan_tracked_files


def test_current_tracked_directories_have_readmes() -> None:
    from scripts.quality.check_directory_readmes import scan_project

    report = scan_project()
    assert not report.missing_directories, format_report(report)


def test_excludes_dependency_generated_binary_and_tool_internal_paths(tmp_path: Path) -> None:
    tracked = [
        "apps/desktop_renderer/src/README.md",
        "apps/desktop_renderer/node_modules/package/index.js",
        "apps/desktop_renderer/dist/index.js",
        "apps/desktop_renderer/build/generated.js",
        "resources/branding/README.md",
        "resources/tools/windows-x64/fping/fping.exe",
        "resources/branding/logo.png",
    ]
    report = scan_tracked_files(tracked, tmp_path)

    assert report.maintained_directories == (
        "apps",
        "apps/desktop_renderer",
        "apps/desktop_renderer/src",
        "resources",
        "resources/branding",
    )
    assert report.missing_directories == (
        "apps",
        "apps/desktop_renderer",
        "apps/desktop_renderer/src",
        "resources",
        "resources/branding",
    )
    assert any(path.endswith("fping.exe") for path, _ in report.excluded_files)


def test_excludes_skill_packages_but_keeps_regular_project_paths(tmp_path: Path) -> None:
    tracked = [
        ".agents/skills/example-skill/SKILL.md",
        "scripts/quality/check.py",
    ]
    (tmp_path / "scripts" / "quality").mkdir(parents=True)
    (tmp_path / "scripts" / "quality" / "README.md").write_text("quality\n", encoding="utf-8")

    report = scan_tracked_files(tracked, tmp_path)

    assert report.maintained_directories == ("scripts", "scripts/quality")
    assert report.missing_directories == ("scripts",)
    assert any("SKILL.md" in path for path, _ in report.excluded_files)


def test_excludes_protected_investigation_material(tmp_path: Path) -> None:
    tracked = ["docs/investigations/archive.md", "docs/README.md"]
    report = scan_tracked_files(tracked, tmp_path)

    assert "docs/investigations" not in report.maintained_directories
    assert "docs/investigations" not in report.missing_directories
    assert any(path.endswith("docs/investigations/archive.md") for path, _ in report.excluded_files)


def test_excludes_pure_fixture_data_but_not_fixture_source(tmp_path: Path) -> None:
    tracked = [
        "tests/fixtures/h3c/display.txt",
        "tests/fixtures/h3c/parser.py",
        "tests/support/helper.py",
    ]

    report = scan_tracked_files(tracked, tmp_path)

    assert "tests/fixtures/h3c" in report.maintained_directories
    assert "tests/fixtures" in report.maintained_directories
    assert "tests" in report.missing_directories
    assert "tests/fixtures" in report.missing_directories
    assert "tests/fixtures/h3c" in report.missing_directories
    assert any(path.endswith("display.txt") for path, _ in report.excluded_files)


def test_source_build_directories_are_not_treated_as_generated(tmp_path: Path) -> None:
    tracked = ["scripts/build/release.py", "src/netconsole/build/clean.py"]

    report = scan_tracked_files(tracked, tmp_path)

    assert report.maintained_directories == (
        "scripts",
        "scripts/build",
        "src",
        "src/netconsole",
        "src/netconsole/build",
    )


def test_missing_directories_are_sorted_and_report_is_stable(tmp_path: Path) -> None:
    tracked = ["z/file.py", "a/file.py", "z/other.py"]

    first = scan_tracked_files(tracked, tmp_path)
    second = scan_tracked_files(reversed(tracked), tmp_path)

    assert first.missing_directories == ("a", "z")
    assert first == second
    assert "- a -> a/README.md" in format_report(first)


def test_main_returns_nonzero_when_readme_is_missing(monkeypatch) -> None:
    report = ReadmeReport(1, ("src",), ("src",), (), ())
    monkeypatch.setattr(checker, "scan_project", lambda: report)

    assert checker.main() == 1


def test_major_directory_requires_structured_sections(tmp_path: Path) -> None:
    tracked = ["src/netconsole/repositories/device_repository.py"]
    readme = tmp_path / "src" / "netconsole" / "repositories" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# Repository\n", encoding="utf-8")

    incomplete = scan_tracked_files(tracked, tmp_path)
    assert incomplete.missing_sections == tuple(
        ("src/netconsole/repositories", heading) for heading in REQUIRED_MAJOR_SECTIONS
    )

    readme.write_text("\n".join(REQUIRED_MAJOR_SECTIONS) + "\n", encoding="utf-8")
    complete = scan_tracked_files(tracked, tmp_path)
    assert not complete.missing_sections
