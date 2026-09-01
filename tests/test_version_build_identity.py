from __future__ import annotations

import pytest

from netconsole.core.update_policy import should_offer_update
from scripts.build.build_metadata import BuildMetadataError, collect_build_metadata
from netconsole.core.version import APP_VERSION


def test_update_policy_ignores_build_and_hash_changes() -> None:
    assert not should_offer_update(APP_VERSION, {"version": "v1.5.1", "published": True, "build_number": 2})
    assert not should_offer_update(APP_VERSION, {"version": "v1.5.2", "published": False, "build_number": 1})
    assert should_offer_update(APP_VERSION, {"version": "v1.5.5", "published": True, "git_sha": "e91d47b"})


def test_build_number_is_explicit_and_does_not_change_product_version(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "scripts.build.build_metadata._git",
        lambda _root, *args: "1" * 40 if args == ("rev-parse", "HEAD") else "",
    )
    monkeypatch.setenv("NETCONSOLE_BUILD_NUMBER", "7")
    result = collect_build_metadata(
        tmp_path,
        app_version=APP_VERSION,
        release=False,
        build_time_utc="2026-08-19T00:00:00Z",
    )

    assert result["product_version"] == APP_VERSION.removeprefix("v")
    assert result["build_number"] == 7
    assert result["file_version"] == f"{APP_VERSION.removeprefix('v')}.7"
    assert result["published"] is False


def test_invalid_build_number_is_rejected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.build.build_metadata._git",
        lambda _root, *args: "1" * 40 if args == ("rev-parse", "HEAD") else "",
    )
    monkeypatch.setenv("NETCONSOLE_BUILD_NUMBER", "not-a-number")
    with pytest.raises(BuildMetadataError, match="NETCONSOLE_BUILD_NUMBER"):
        collect_build_metadata(
            tmp_path,
            app_version=APP_VERSION,
            release=False,
            build_time_utc="2026-08-19T00:00:00Z",
        )
