from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FRONT_MATTER_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*")
FORBIDDEN_DOCS_ROOT_SUFFIXES = (
    "_ASSESSMENT.MD",
    "_AUDIT.MD",
    "_INVESTIGATION.MD",
    "_PLAN.MD",
)
LEGACY_RENDERER_PATH_RE = re.compile(
    r"(?<!desktop_)apps[\\/]web(?:[\\/]|\b)", re.IGNORECASE
)
CANONICAL_DOC_LINKS = frozenset(
    {
        "CHANGELOG.md",
        "export/PROCESS_POLICY.md",
        "rail-transit/mesh/ANALYSIS_RULES.md",
        "storage/DATA_LAYOUT.md",
    }
)
IGNORED_MARKDOWN_DIRS = frozenset(
    {
        ".git",
        ".local",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "artifacts",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
        "tmp",
        "venv",
    }
)


def _markdown_under(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    markdown: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_MARKDOWN_DIRS]
        markdown.extend(
            Path(current) / name for name in filenames if name.endswith(".md")
        )
    return markdown


def _markdown_files() -> list[Path]:
    paths = [ROOT / "README.md", ROOT / "AGENTS.md"]
    for root in (
        ROOT / "docs",
        ROOT / "apps",
        ROOT / "src",
        ROOT / ".agents" / "skills",
        ROOT / "tools",
        ROOT / "resources",
    ):
        paths.extend(_markdown_under(root))
    return sorted(set(paths))


def _active_docs_markdown(docs_root: Path | None = None) -> list[Path]:
    docs_root = docs_root or ROOT / "docs"
    archive = (docs_root / "archive").resolve()
    return [
        path
        for path in _markdown_under(docs_root)
        if archive not in path.resolve().parents
    ]


def _transient_docs_root_files(docs_root: Path) -> list[Path]:
    return [
        path
        for path in sorted(docs_root.glob("*.md"))
        if path.name.upper().endswith(FORBIDDEN_DOCS_ROOT_SUFFIXES)
    ]


def _retired_renderer_path_references(docs_root: Path) -> list[str]:
    return [
        f"{path.relative_to(docs_root).as_posix()}:{line_number}"
        for path in _active_docs_markdown(docs_root)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if LEGACY_RENDERER_PATH_RE.search(line)
    ]


def test_markdown_discovery_skips_generated_dependency_trees(tmp_path: Path) -> None:
    source = tmp_path / "apps" / "web"
    source.mkdir(parents=True)
    expected = source / "README.md"
    expected.write_text("source", encoding="utf-8")
    dependency = source / "node_modules" / "package" / "README.md"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("dependency", encoding="utf-8")

    discovered = _markdown_under(tmp_path)

    assert expected in discovered
    assert dependency not in discovered


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


def test_docs_root_rejects_transient_governance_filenames() -> None:
    violations = [
        path.relative_to(ROOT).as_posix()
        for path in _transient_docs_root_files(ROOT / "docs")
    ]

    assert not violations, (
        "transient assessment/audit/plan/investigation docs must live in a "
        "topic directory or docs/archive:\n" + "\n".join(violations)
    )


def test_transient_docs_filename_guard_only_applies_to_docs_root(
    tmp_path: Path,
) -> None:
    root_files = [
        tmp_path / name
        for name in (
            "ROOT_ASSESSMENT.md",
            "ROOT_AUDIT.md",
            "ROOT_INVESTIGATION.md",
            "ROOT_PLAN.md",
        )
    ]
    topic_plan = tmp_path / "development" / "TOPIC_PLAN.md"
    archived_audit = tmp_path / "archive" / "HISTORY_AUDIT.md"
    for root_file in root_files:
        root_file.write_text("root", encoding="utf-8")
    topic_plan.parent.mkdir()
    topic_plan.write_text("topic", encoding="utf-8")
    archived_audit.parent.mkdir()
    archived_audit.write_text("archive", encoding="utf-8")

    assert _transient_docs_root_files(tmp_path) == root_files


def test_active_docs_discovery_excludes_archive(tmp_path: Path) -> None:
    active = tmp_path / "topic" / "current.md"
    archived = tmp_path / "archive" / "history.md"
    active.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    active.write_text("apps/desktop_renderer", encoding="utf-8")
    archived.write_text("apps/web", encoding="utf-8")

    discovered = _active_docs_markdown(tmp_path)

    assert active in discovered
    assert archived not in discovered
    assert _retired_renderer_path_references(tmp_path) == []

    active.write_text("APPS\\WEB", encoding="utf-8")

    assert _retired_renderer_path_references(tmp_path) == ["topic/current.md:1"]


def test_active_docs_do_not_reference_retired_apps_web_path() -> None:
    violations = _retired_renderer_path_references(ROOT / "docs")

    assert not violations, "active docs reference retired apps/web paths:\n" + "\n".join(
        violations
    )


def test_docs_readme_links_canonical_topic_documents() -> None:
    docs_readme = ROOT / "docs" / "README.md"
    linked_targets = {
        unquote(raw_target.strip().split(maxsplit=1)[0])
        .split("#", 1)[0]
        .removeprefix("./")
        for raw_target in MARKDOWN_LINK_RE.findall(
            docs_readme.read_text(encoding="utf-8")
        )
    }
    missing = sorted(CANONICAL_DOC_LINKS - linked_targets)
    invalid = sorted(
        target
        for target in CANONICAL_DOC_LINKS
        if not (docs_readme.parent / target).is_file()
        or (ROOT / "docs" / "archive").resolve()
        in (docs_readme.parent / target).resolve().parents
    )

    assert not missing, "docs/README.md missing canonical links:\n" + "\n".join(missing)
    assert not invalid, "canonical docs targets must be active files:\n" + "\n".join(
        invalid
    )


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
        keys = [
            match.group(1)
            for line in lines[1:end]
            if (match := FRONT_MATTER_KEY_RE.match(line))
        ]
        assert set(keys) == {"name", "description"}, skill_file
        name = next(
            line.split(":", 1)[1].strip()
            for line in lines[1:end]
            if line.startswith("name:")
        )
        assert name == skill_file.parent.name, skill_file
        names.append(name)
    assert len(names) == len(set(names)), names


def test_user_file_interaction_contract_is_routed_and_indexed() -> None:
    contract_path = ROOT / "docs/export/USER_FILE_INTERACTION.md"
    contract = contract_path.read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    docs_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    skills_index = (ROOT / "docs/development/CODEX_SKILLS.md").read_text(
        encoding="utf-8"
    )
    user_file_skill = (
        ROOT / ".agents/skills/netconsole-user-file-interaction-skill/SKILL.md"
    ).read_text(encoding="utf-8")
    export_skill = (
        ROOT / ".agents/skills/netconsole-export-report-skill/SKILL.md"
    ).read_text(encoding="utf-8")

    assert contract_path.is_file()
    assert contract.count("[ ] ") == 15
    for required_api in (
        "exportActionRegistry.ts",
        "submitExportAfterDestinationSelected",
        "saveReadyArtifact",
        "retryArtifactSave",
        "downloadBackendResource",
    ):
        assert required_api in contract
    assert "docs/export/USER_FILE_INTERACTION.md" in agents
    assert "export/USER_FILE_INTERACTION.md" in docs_index
    assert "netconsole-user-file-interaction-skill" in agents
    assert "netconsole-user-file-interaction-skill" in skills_index
    assert "useUserSelectedExport.ts" in user_file_skill
    assert "useUserSelectedExport.ts" in export_skill
    assert "netconsole-user-file-interaction-skill" in export_skill


def test_project_skills_do_not_reference_deleted_qt_sources() -> None:
    forbidden = (
        "src/netconsole/ui/",
        "netconsole.ui.",
        "background_process_manager.py",
        "qt6-ui-fix-skill",
        "netconsole-qt6-ui-taste-skill",
        "Qt UI Skill",
    )
    violations = [
        f"{skill_file.relative_to(ROOT)} contains {needle!r}"
        for skill_file in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
        for needle in forbidden
        if needle in skill_file.read_text(encoding="utf-8")
    ]
    assert not violations, "stale project Skill references:\n" + "\n".join(violations)


def test_core_docs_do_not_use_known_old_paths() -> None:
    documents = [
        ROOT / "docs/architecture/RUNTIME.md",
        ROOT / "docs/ARCHITECTURE.md",
        ROOT / "docs/README.md",
        ROOT / "docs/DEVELOPMENT_RULES.md",
        ROOT / "apps/agent/README.md",
    ]
    forbidden = (
        r"cd frontend",
        r"(?<!src/)netconsole/app\.py",
        r"(?<!src/)netconsole/ui/main_window\.py",
    )
    violations = [
        f"{document.relative_to(ROOT)} contains {needle!r}"
        for document in documents
        for needle in forbidden
        if re.search(needle, document.read_text(encoding="utf-8"))
    ]
    assert not violations, "stale project paths:\n" + "\n".join(violations)
    assert "](../docs/AGENT_TRAFFIC_API.md)" not in (
        ROOT / "apps/agent/README.md"
    ).read_text(encoding="utf-8")


def test_active_readmes_do_not_describe_qt_as_current_architecture() -> None:
    documents = [
        ROOT / "README.md",
        ROOT / "src/README.md",
        ROOT / "src/netconsole/README.md",
        ROOT / "src/netconsole/services/online_mr/README.md",
        ROOT / "docs/ARCHITECTURE.md",
    ]
    forbidden = (
        "迁移期 Qt",
        "当前仓库正式主线仍为 PySide6",
        "`ui/`：迁移期 Qt",
        "Qt 事实源，最终删除",
    )
    violations = [
        f"{document.relative_to(ROOT)} contains {needle!r}"
        for document in documents
        for needle in forbidden
        if needle in document.read_text(encoding="utf-8")
    ]
    assert not violations, "stale active Qt architecture claims:\n" + "\n".join(
        violations
    )
