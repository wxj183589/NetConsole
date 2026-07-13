from __future__ import annotations

import json
from pathlib import Path

from netconsole.services.open_source_notice_service import OpenSourceNoticeService


def test_open_source_notice_service_merges_requirements_and_overrides(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pytest>=8.0\nmissing-demo-package\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "open_source_notices.json").write_text(
        json.dumps(
            [
                {
                    "name": "pytest",
                    "purpose": "自动化测试",
                    "license": "MIT",
                    "homepage": "https://docs.pytest.org/",
                },
                {
                    "name": "missing-demo-package",
                    "purpose": "测试缺失包兜底",
                    "license": "Custom",
                    "homepage": "https://example.invalid/",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    components = OpenSourceNoticeService(tmp_path).list_components()
    by_name = {component.name.casefold(): component for component in components}

    assert "pytest" in by_name
    assert by_name["pytest"].purpose == "自动化测试"
    assert by_name["missing-demo-package"].version == ""
    assert by_name["missing-demo-package"].license == "Custom"


def test_ipop_is_not_listed_as_open_source_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("docs/open_source_notices.json", "src/netconsole/assets/open_source_notices.json"):
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
        assert all(str(item.get("name") or "").casefold() != "ipop v4.1" for item in payload)
