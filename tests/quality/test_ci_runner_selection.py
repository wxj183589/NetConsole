from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def test_readme_architecture_keeps_infrastructure_under_application() -> None:
    for filename in ("README.md", "README_EN.md"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "A --> I[\"Infrastructure / Device Adapters\"]" in text
        assert "D --> I[\"Infrastructure / Device Adapters\"]" not in text
