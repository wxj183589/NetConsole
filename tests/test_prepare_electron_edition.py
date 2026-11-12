from __future__ import annotations

import json

import pytest

from scripts.build.prepare_electron_edition import EditionPreparationError, prepare_electron_edition


def _backend_root(tmp_path):
    root = tmp_path / "backend"
    root.mkdir()
    (root / "NetConsoleBackend.exe").write_bytes(b"test")
    return root


def _embedded_build_info(root):
    path = root / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _embedded_feature_flags(root):
    path = root / "_internal" / "netconsole" / "assets" / "runtime" / "feature_flags.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_prepare_full_edition_is_the_only_formal_electron_policy(tmp_path) -> None:
    root = _backend_root(tmp_path)

    result = prepare_electron_edition(root, edition="full")

    _, build_info = _embedded_build_info(root)
    _, feature_flags = _embedded_feature_flags(root)
    assert result["edition"] == "full"
    assert result["feature_profile"] == "full"
    assert result["admin_unlock_configured"] is False
    assert build_info == {
        "edition": "full",
        "feature_profile": "full",
        "admin_unlock_enabled": False,
    }
    assert feature_flags["profile"] == "full"
    assert feature_flags["features"]["capability.trackside_ap.wps_sync"]["enabled"] is True


@pytest.mark.parametrize("edition", ["customer", "both", "engineer"])
def test_prepare_rejects_retired_or_unknown_formal_editions(tmp_path, edition: str) -> None:
    with pytest.raises(EditionPreparationError, match="仅允许 full"):
        prepare_electron_edition(_backend_root(tmp_path), edition=edition)
