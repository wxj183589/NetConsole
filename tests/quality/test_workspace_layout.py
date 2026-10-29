from __future__ import annotations

from pathlib import Path
import subprocess

from scripts.check_workspace_layout import (
    WORKSPACE_TOP_LEVEL,
    check_repository_root,
    check_worktree_locations,
    check_workspace_root,
    run_checks,
)
import scripts.check_workspace_layout as workspace_layout


def _make_dirs(root: Path, names: set[str]) -> None:
    for name in names:
        (root / name).mkdir(parents=True)


def test_workspace_top_level_allows_standard_directories_and_registered_exceptions(tmp_path: Path) -> None:
    _make_dirs(tmp_path, set(WORKSPACE_TOP_LEVEL))

    assert check_workspace_root(tmp_path) == []


def test_workspace_top_level_reports_unknown_directory_without_deleting_it(tmp_path: Path) -> None:
    _make_dirs(tmp_path, {"NetConsole", "worktrees", "reports"})
    unknown = tmp_path / "NetConsole-copy"
    unknown.mkdir()

    violations = check_workspace_root(tmp_path)

    assert any(item.kind == "PROHIBITED_WORKSPACE_TOP_LEVEL" for item in violations)
    assert unknown.is_dir()


def test_workspace_top_level_reports_duplicate_repository(tmp_path: Path) -> None:
    _make_dirs(tmp_path, {"NetConsole", "NetConsole-DevStatus", "worktrees"})
    duplicate = tmp_path / "NetConsole-copy"
    duplicate.mkdir()
    (duplicate / ".git").mkdir()

    violations = check_workspace_root(tmp_path)

    assert any(item.kind == "DUPLICATE_WORKSPACE_REPOSITORY" for item in violations)


def test_registered_independent_repository_is_accepted_only_with_expected_identity(tmp_path: Path) -> None:
    independent = tmp_path / "NetConsole-Next"
    independent.mkdir()
    subprocess.run(("git", "init", "-q", str(independent)), check=True)
    subprocess.run(
        ("git", "-C", str(independent), "remote", "add", "origin", "https://github.com/wxj183589/NetConsole-Next.git"),
        check=True,
    )

    assert check_workspace_root(tmp_path) == []

    subprocess.run(
        ("git", "-C", str(independent), "remote", "set-url", "origin", "https://github.com/example/other.git"),
        check=True,
    )
    kinds = {item.kind for item in check_workspace_root(tmp_path)}
    assert kinds == {"UNAPPROVED_WORKSPACE_TOP_LEVEL", "DUPLICATE_WORKSPACE_REPOSITORY"}


def test_registered_independent_repository_worktrees_are_managed(tmp_path: Path) -> None:
    main = tmp_path / "NetConsole"
    main.mkdir()
    subprocess.run(("git", "init", "-q", str(main)), check=True)
    independent = tmp_path / "NetConsole-Next"
    independent.mkdir()
    subprocess.run(("git", "init", "-q", str(independent)), check=True)
    subprocess.run(
        ("git", "-C", str(independent), "remote", "add", "origin", "https://github.com/wxj183589/NetConsole-Next.git"),
        check=True,
    )
    (independent / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(independent), "add", "README.md"), check=True)
    subprocess.run(("git", "-C", str(independent), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"), check=True)
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    subprocess.run(("git", "-C", str(independent), "worktree", "add", "--detach", "-q", str(worktrees / "next")), check=True)

    violations = run_checks(main, tmp_path)

    assert not any(item.kind == "UNMANAGED_WORKTREE_DIRECTORY" for item in violations)


def test_invalid_workspace_boundary_skips_independent_repository_probe(
    tmp_path: Path, monkeypatch
) -> None:
    main = tmp_path / "NetConsole"
    main.mkdir()
    workspace = tmp_path / "workspace-link"
    workspace.mkdir()

    monkeypatch.setattr(workspace_layout, "_git_worktrees", lambda _repo: ((), []))
    monkeypatch.setattr(workspace_layout, "_is_reparse_point", lambda path: path == workspace)
    monkeypatch.setattr(
        workspace_layout,
        "_registered_independent_worktrees",
        lambda _root: (_ for _ in ()).throw(AssertionError("must not probe an invalid Workspace root")),
    )

    violations = run_checks(main, workspace)

    assert any(item.kind == "WORKSPACE_ROOT_REPARSE" for item in violations)


def test_backup_container_is_allowed_but_unknown_repository_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "backups").mkdir()
    assert check_workspace_root(tmp_path) == []

    unknown = tmp_path / "another-project"
    unknown.mkdir()
    (unknown / ".git").mkdir()
    kinds = {item.kind for item in check_workspace_root(tmp_path)}
    assert kinds == {"UNAPPROVED_WORKSPACE_TOP_LEVEL", "DUPLICATE_WORKSPACE_REPOSITORY"}


def test_workspace_reports_nonstandard_output_container(tmp_path: Path) -> None:
    _make_dirs(tmp_path, {"NetConsole", "worktrees", "reports", "temp"})
    (tmp_path / "temp" / "temp-build-new").mkdir()

    violations = check_workspace_root(tmp_path)

    assert any(item.kind == "NONSTANDARD_OUTPUT_CONTAINER" for item in violations)


def test_worktree_must_be_direct_child_of_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "NetConsole"
    workspace = tmp_path / "NetConsole-Workspace"
    repo.mkdir()
    workspace.mkdir()

    violations = check_worktree_locations(repo, workspace, (repo, workspace / "package-worktrees" / "task"))

    assert [item.kind for item in violations] == ["WORKTREE_OUTSIDE_CONTAINER"]


def test_repository_top_level_reports_new_directory(tmp_path: Path) -> None:
    for name in ("apps", "src", "tests", "docs"):
        (tmp_path / name).mkdir()
    (tmp_path / "new_app").mkdir()

    violations = check_repository_root(tmp_path)

    assert any(item.kind == "UNAPPROVED_REPOSITORY_TOP_LEVEL" for item in violations)
