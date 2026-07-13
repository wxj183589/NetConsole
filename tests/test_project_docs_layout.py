from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FRONT_MATTER_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*")


def _markdown_files() -> list[Path]:
    paths = [ROOT / "README.md", ROOT / "AGENTS.md"]
    paths.extend((ROOT / "docs").rglob("*.md"))
    paths.extend((ROOT / "apps").rglob("*.md"))
    paths.extend((ROOT / ".agents" / "skills").rglob("*.md"))
    paths.extend((ROOT / "tools").rglob("*.md"))
    paths.extend((ROOT / "resources").rglob("*.md"))
    return sorted(set(paths))


def test_markdown_relative_links_exist() -> None:
    broken: list[str] = []
    for markdown in _markdown_files():
        text = markdown.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0]
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = unquote(target.split("#", 1)[0])
            if not target_path:
                continue
            resolved = (markdown.parent / target_path).resolve()
            if not resolved.exists():
                broken.append(f"{markdown.relative_to(ROOT)} -> {target}")
    assert not broken, "broken Markdown links:\n" + "\n".join(broken)


def test_project_skill_front_matter_is_unique_and_minimal() -> None:
    skill_files = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    assert skill_files
    names: list[str] = []
    for skill_file in skill_files:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
        assert lines and lines[0] == "---", skill_file
        try:
            end = lines.index("---", 1)
        except ValueError as exc:
            raise AssertionError(f"missing front matter end: {skill_file}") from exc
        keys = [match.group(1) for line in lines[1:end] if (match := FRONT_MATTER_KEY_RE.match(line))]
        assert set(keys) == {"name", "description"}, skill_file
        name = next(line.split(":", 1)[1].strip() for line in lines[1:end] if line.startswith("name:"))
        assert name == skill_file.parent.name, skill_file
        names.append(name)
    assert len(names) == len(set(names)), names


def test_core_docs_do_not_use_known_old_paths() -> None:
    documents = [
        ROOT / "docs/WEB_ARCHITECTURE.md",
        ROOT / "docs/PROJECT_OVERVIEW.md",
        ROOT / "docs/02-architecture.md",
        ROOT / "docs/README.md",
        ROOT / "docs/DEVELOPMENT_CONVENTIONS.md",
        ROOT / "apps/agent/README.md",
    ]
    forbidden = (r"cd frontend", r"(?<!src/)netconsole/app\.py", r"(?<!src/)netconsole/ui/main_window\.py")
    violations = [
        f"{document.relative_to(ROOT)} contains {needle!r}"
        for document in documents
        for needle in forbidden
        if re.search(needle, document.read_text(encoding="utf-8"))
    ]
    assert not violations, "stale project paths:\n" + "\n".join(violations)
    assert "](../docs/AGENT_TRAFFIC_API.md)" not in (ROOT / "apps/agent/README.md").read_text(encoding="utf-8")
