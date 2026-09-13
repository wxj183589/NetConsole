from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from netconsole.core.changelog import (
    ChangelogSyncError,
    parse_released_sections,
    parse_runtime_sections,
    normalize_runtime_body,
    render_runtime_changelog,
)
from scripts.build.sync_runtime_changelog import generated_runtime_changelog


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_and_runtime_changelogs_have_one_ordered_content_fingerprint() -> None:
    canonical = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    runtime_path = ROOT / "src" / "netconsole" / "docs" / "changelog.md"
    runtime = runtime_path.read_text(encoding="utf-8")

    canonical_sections = parse_released_sections(canonical, source_name="canonical changelog")
    runtime_sections = parse_runtime_sections(runtime)

    assert [section.version for section in canonical_sections[:3]] == [
        "v1.5.8",
        "v1.5.7",
        "v1.5.6",
    ]
    assert len({section.version for section in canonical_sections}) == len(canonical_sections)
    assert len({section.version for section in runtime_sections}) == len(runtime_sections)
    assert [
        (section.version, section.date, normalize_runtime_body(section.body))
        for section in canonical_sections
    ] == [
        (section.version, section.date, section.body)
        for section in runtime_sections
    ]
    assert runtime == generated_runtime_changelog(ROOT)
    assert hashlib.sha256(runtime.encode("utf-8")).hexdigest() == hashlib.sha256(
        generated_runtime_changelog(ROOT).encode("utf-8")
    ).hexdigest()


def test_changelog_parser_rejects_duplicate_or_non_descending_releases() -> None:
    with pytest.raises(ChangelogSyncError, match="duplicate"):
        parse_released_sections("## v1.5.8 - 2026-09-13\nfirst\n\n## v1.5.8 - 2026-09-13\nsecond")

    with pytest.raises(ChangelogSyncError, match="descending"):
        parse_released_sections("## v1.5.6 - 2026-09-13\nold\n\n## v1.5.8 - 2026-09-13\nnew")


def test_runtime_renderer_preserves_missing_date_and_body() -> None:
    sections = parse_released_sections("## v1.5.1\n### 修复\n\n- 保持兼容\n")

    assert render_runtime_changelog(sections) == "v1.5.1\n### 修复\n\n- 保持兼容\n"


def test_runtime_renderer_drops_links_to_docs_not_shipped_with_the_asset() -> None:
    sections = parse_released_sections(
        "## v1.5.1 - 2026-09-13\n见 [用户文件交互契约](./export/USER_FILE_INTERACTION.md)\n"
    )

    assert normalize_runtime_body(sections[0].body) == "见 用户文件交互契约"
    assert render_runtime_changelog(sections) == "v1.5.1 - 2026-09-13\n见 用户文件交互契约\n"
