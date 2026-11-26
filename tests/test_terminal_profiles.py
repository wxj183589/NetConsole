from __future__ import annotations

from pathlib import Path
import json

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.terminal_profiles import TerminalProfileStore


def _store(tmp_path: Path) -> TerminalProfileStore:
    return TerminalProfileStore(
        PathResolver(
            app_root=tmp_path / "app",
            data_root=tmp_path / "data",
            runtime_root=tmp_path / "runtime",
        )
    )


def test_saved_terminal_profiles_keep_folders_favorites_and_no_plaintext_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "netconsole.services.terminal_profiles.protect_windows_data",
        lambda value, entropy: b"encrypted:" + entropy + b":" + value,
    )
    monkeypatch.setattr(
        "netconsole.services.terminal_profiles.unprotect_windows_data",
        lambda value, entropy: value.removeprefix(b"encrypted:" + entropy + b":"),
    )
    store = _store(tmp_path)
    folder = store.create_folder("核心交换机")
    profile = store.save_profile(
        {
            "name": "LAB-SW",
            "host": "192.0.2.10",
            "port": 22,
            "protocol": "SSH",
            "username": "operator",
            "encoding": "gb18030",
            "vendor": "H3C",
            "device_type": "SW",
            "folder_id": folder["folder_id"],
            "favorite": True,
        },
        password="test-secret",
        remember_password=True,
    )

    document = store.document()
    resolved, password = store.resolve(profile["profile_id"])

    assert document["folders"] == [folder]
    assert document["profiles"][0]["favorite"] is True
    assert document["profiles"][0]["password_configured"] is True
    assert password == "test-secret"
    assert resolved["encoding"] == "gb18030"
    assert "test-secret" not in store.path.read_text(encoding="utf-8")
    assert "test-secret" not in store.secret_path.read_text(encoding="utf-8")


def test_deleting_profile_folder_keeps_sessions_at_root(tmp_path: Path) -> None:
    store = _store(tmp_path)
    folder = store.create_folder("无线")
    profile = store.save_profile(
        {
            "name": "LAB-AC",
            "host": "example.internal",
            "port": 23,
            "protocol": "TELNET",
            "username": "operator",
            "encoding": "utf-8",
            "vendor": "H3C",
            "device_type": "AC",
            "folder_id": folder["folder_id"],
            "favorite": False,
        }
    )

    store.delete_folder(folder["folder_id"])

    document = store.document()
    assert document["folders"] == []
    assert document["profiles"][0]["profile_id"] == profile["profile_id"]
    assert document["profiles"][0]["folder_id"] == ""


def test_import_accepts_schema_one_and_preserves_backup_metadata_without_secrets(tmp_path: Path) -> None:
    store = _store(tmp_path)
    document = store.import_document({
        "schema_version": 1,
        "folders": [{"folder_id": "a" * 32, "name": "核心设备"}],
        "profiles": [{
            "profile_id": "b" * 32,
            "name": "LAB-AC",
            "host": "192.0.2.10",
            "backup_host": "192.0.2.11",
            "backup_port": 2222,
            "port": 22,
            "protocol": "SSH",
            "username": "operator",
            "encoding": "utf-8",
            "vendor": "H3C",
            "device_type": "AC",
            "folder_id": "a" * 32,
            "favorite": True,
            "notes": "实验室控制器",
            "tags": ["无线", "核心"],
            "password": "must-not-be-imported",
        }],
    })

    profile = document["profiles"][0]
    stored = json.loads(store.path.read_text(encoding="utf-8"))

    assert document["schema_version"] == 2
    assert profile["backup_host"] == "192.0.2.11"
    assert profile["backup_port"] == 2222
    assert profile["notes"] == "实验室控制器"
    assert profile["tags"] == ["无线", "核心"]
    assert profile["folder_id"] == document["folders"][0]["folder_id"]
    assert profile["password_configured"] is False
    assert "must-not-be-imported" not in json.dumps(stored, ensure_ascii=False)


def test_import_rejects_invalid_documents_without_mutating_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = store.document()

    with pytest.raises(ValueError, match="会话配置版本无效"):
        store.import_document({"schema_version": 99, "folders": [], "profiles": []})

    assert store.document() == before
