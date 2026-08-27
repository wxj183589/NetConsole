from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quality.check_repository_root_layout import (
    ROOT_FILE_ALLOWLIST,
    is_allowed_root_file,
    main,
    unexpected_root_files,
)


def _populate_allowlisted_root(root: Path) -> None:
    for name in ROOT_FILE_ALLOWLIST:
        (root / name).write_text("", encoding="utf-8")
    (root / "requirements-extra.txt").write_text("", encoding="utf-8")


def test_current_project_allowlist_passes(tmp_path: Path) -> None:
    _populate_allowlisted_root(tmp_path)

    assert unexpected_root_files(tmp_path) == ()


def test_git_worktree_pointer_is_metadata(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: metadata", encoding="utf-8")

    assert unexpected_root_files(tmp_path) == ()


@pytest.mark.parametrize("name", ("FOO_REPORT.md", "random.json"))
def test_unknown_root_files_fail_closed(tmp_path: Path, name: str) -> None:
    _populate_allowlisted_root(tmp_path)
    unexpected = tmp_path / name
    unexpected.write_text("evidence", encoding="utf-8")

    assert tuple(path.name for path in unexpected_root_files(tmp_path)) == (name,)
    assert not is_allowed_root_file(name)


def test_archive_artifact_does_not_pollute_root(tmp_path: Path) -> None:
    _populate_allowlisted_root(tmp_path)
    archived = tmp_path / "docs" / "archive" / "FOO_REPORT.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("historical evidence", encoding="utf-8")

    assert unexpected_root_files(tmp_path) == ()


@pytest.mark.parametrize("name", ("README.md", "requirements-runtime.txt"))
def test_project_level_allowlist_files_pass(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("", encoding="utf-8")

    assert unexpected_root_files(tmp_path) == ()


def test_cli_reports_a_clear_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "FOO_REPORT.md").write_text("evidence", encoding="utf-8")

    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "ROOT_ARTIFACT_VIOLATION" in output
    assert "FOO_REPORT.md" in output
    assert "repository-layout.md" in output


def test_cli_reports_pass_for_a_clean_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _populate_allowlisted_root(tmp_path)

    assert main(["--root", str(tmp_path)]) == 0
    assert "ROOT_LAYOUT_GATE=PASS" in capsys.readouterr().out
