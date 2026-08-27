"""Enforce the repository-root file allowlist."""

from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
ROOT_FILE_ALLOWLIST = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        "AGENTS.md",
        "LICENSE",
        "README.md",
        "README_EN.md",
        "constraints.txt",
        "main.py",
        "pyproject.toml",
        "pytest.ini",
        "requirements.txt",
        "一键打包安装包.cmd",
    }
)
ROOT_FILE_ALLOWLIST_PATTERNS = ("requirements-*.txt",)


def is_allowed_root_file(name: str) -> bool:
    return name in ROOT_FILE_ALLOWLIST or any(
        fnmatchcase(name, pattern) for pattern in ROOT_FILE_ALLOWLIST_PATTERNS
    )


def unexpected_root_files(root: Path = ROOT) -> tuple[Path, ...]:
    """Return unexpected files directly below ``root`` in stable order."""

    return tuple(
        path
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file()
        # A linked Git worktree represents .git as a metadata pointer file;
        # a regular clone represents it as a directory and never reaches this
        # file-only check.
        and path.name != ".git"
        and not is_allowed_root_file(path.name)
    )


def _format_violation(paths: Sequence[Path]) -> str:
    lines = [
        "ROOT_ARTIFACT_VIOLATION",
        "Unexpected repository-root file:",
        *(f"  {path.name}" for path in paths),
        "",
        "Generated reports/audits/tests/migration evidence must be placed under docs/... according to repository-layout.md.",
        "Review the root allowlist before adding any new project-level file.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root to inspect")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"ROOT_LAYOUT_GATE=ERROR\nRepository root does not exist: {root}")
        return 2
    violations = unexpected_root_files(root)
    if violations:
        print(_format_violation(violations))
        return 1
    print("ROOT_LAYOUT_GATE=PASS")
    print("ROOT_FILE_ALLOWLIST=ENFORCED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
