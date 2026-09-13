"""Generate the packaged changelog from the canonical project changelog."""

from __future__ import annotations

import argparse
from pathlib import Path

from netconsole.core.changelog import (
    ChangelogSyncError,
    parse_released_sections,
    render_runtime_changelog,
)


def canonical_changelog_path(repo_root: Path) -> Path:
    return Path(repo_root) / "docs" / "CHANGELOG.md"


def runtime_changelog_path(repo_root: Path) -> Path:
    return Path(repo_root) / "src" / "netconsole" / "docs" / "changelog.md"


def generated_runtime_changelog(repo_root: Path) -> str:
    canonical = canonical_changelog_path(repo_root).read_text(encoding="utf-8")
    return render_runtime_changelog(parse_released_sections(canonical, source_name="canonical changelog"))


def sync_runtime_changelog(repo_root: Path, *, check: bool = False) -> bool:
    target = runtime_changelog_path(repo_root)
    rendered = generated_runtime_changelog(repo_root)
    current = target.read_text(encoding="utf-8") if target.exists() else None
    matches = current == rendered
    if check:
        if not matches:
            raise ChangelogSyncError(f"runtime changelog is out of sync: {target}")
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 canonical changelog 到 runtime 资源")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        sync_runtime_changelog(args.repo_root.resolve(), check=args.check)
    except (OSError, ChangelogSyncError) as exc:
        parser.error(str(exc))
    print(f"CHANGELOG_SYNC={'CHECK' if args.check else 'WRITE'} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
