from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core import settings as settings_module
from netconsole.core.paths import PathResolver
from netconsole.core.settings import (
    SettingsConflictError,
    SettingsFileInvalidError,
    SettingsStore,
)


def _paths(tmp_path: Path) -> PathResolver:
    return PathResolver(app_root=tmp_path, data_root=tmp_path / "data")


@pytest.mark.parametrize("payload", [b"{broken", b"[1, 2, 3]", b"\xff\xfe"])
def test_invalid_existing_settings_are_preserved_and_refuse_writes(
    tmp_path: Path, payload: bytes
) -> None:
    paths = _paths(tmp_path)
    paths.settings_path.parent.mkdir(parents=True)
    paths.settings_path.write_bytes(payload)

    with pytest.raises(SettingsFileInvalidError):
        SettingsStore(paths)

    assert paths.settings_path.read_bytes() == payload


def test_atomic_replace_failure_rolls_back_memory_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    store = SettingsStore(paths)
    store.set_theme("dark")
    original = paths.settings_path.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(settings_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.set_language("en_US")

    assert store.language == "zh_CN"
    assert store.dirty_keys == frozenset()
    assert paths.settings_path.read_bytes() == original
    assert list(paths.settings_path.parent.glob(".settings.json.*.tmp")) == []


def test_stale_same_key_conflicts_but_unrelated_keys_merge(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = SettingsStore(paths)
    stale = SettingsStore(paths)
    first.set_theme("dark")
    stale.set_value("unrelated/value", 7)
    assert SettingsStore(paths).get_value("unrelated/value") == 7

    stale_again = SettingsStore(paths)
    SettingsStore(paths).set_theme("light")
    with pytest.raises(SettingsConflictError):
        stale_again.set_theme("dark")
    assert stale_again.theme == "dark"
    assert stale_again.dirty_keys == frozenset()


def test_explicit_restore_old_value_uses_version_cas(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    initial = SettingsStore(paths)
    initial.set_theme("light")
    stale = SettingsStore(paths)
    version = stale.version
    SettingsStore(paths).set_theme("dark")

    with pytest.raises(SettingsConflictError):
        stale.update_explicit({"theme": "light"}, expected_version=version)

    assert json.loads(paths.settings_path.read_text(encoding="utf-8"))["theme"] == "dark"


def test_invalid_persisted_values_are_normalized_without_losing_unknown_keys(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    paths.settings_path.parent.mkdir(parents=True)
    paths.settings_path.write_text(
        json.dumps(
            {
                "theme": "neon",
                "language": "fr_FR",
                "external_terminal/type": "Windows Terminal",
                "extension/owned": {"keep": True},
            }
        ),
        encoding="utf-8",
    )

    store = SettingsStore(paths)

    assert store.theme == "light"
    assert store.language == "zh_CN"
    assert store.values["external_terminal/type"] == "securecrt"
    assert store.dirty_keys == frozenset()
    persisted = json.loads(paths.settings_path.read_text(encoding="utf-8"))
    assert persisted["theme"] == "light"
    assert persisted["language"] == "zh_CN"
    assert persisted["external_terminal/type"] == "securecrt"
    assert persisted["extension/owned"] == {"keep": True}
