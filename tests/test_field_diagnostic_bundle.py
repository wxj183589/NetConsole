from __future__ import annotations

import json
import zipfile
from pathlib import Path

from netconsole.core.storage_io import StorageDetection, StorageIOProfile
from netconsole.services import field_diagnostic_bundle as bundle


def _storage(_root: Path):
    detection = StorageDetection(str(_root), "D:", "RAID", "LOW", "CONSERVATIVE_STORAGE", "底层磁盘不可见")
    return detection, StorageIOProfile.conservative()


def test_bundle_is_bounded_redacted_and_integrity_checked(tmp_path, monkeypatch) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "ground.log").write_text("token=TOP_SECRET password=bad\nnormal\n", encoding="utf-8")
    (tmp_path / "raw.ndjson").write_text("\n".join('{"message":"row"}' for _ in range(1500)), encoding="utf-8")
    monkeypatch.setattr(bundle, "detect_storage_profile", _storage)
    monkeypatch.setattr(bundle, "_windows_storage", lambda _root: {"status": "unavailable", "reason": "test"})
    monkeypatch.setattr(bundle, "_raid_tools", lambda: {"status": "not_available", "detected_tools": []})
    output = tmp_path / "diagnostic.zip"

    result = bundle.collect_field_diagnostic_bundle(
        {
            "data_root": str(tmp_path),
            "sample_duration_minutes": 0,
            "log_window_minutes": 30,
            "runtime_config": {"password": "TOP_SECRET", "udp_port": 514, "token": "bad"},
        },
        output,
    )

    assert result["size_bytes"] == output.stat().st_size
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "summary.json", "bundle_integrity.json"} <= names
        assert len(archive.read("samples/raw_sample.ndjson")) <= bundle.MAX_RAW_BYTES
        text = "\n".join(archive.read(name).decode("utf-8", "replace") for name in names)
        assert "TOP_SECRET" not in text
        assert "password=bad" not in text
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["failed_sections"] == []


def test_bundle_can_omit_raw_and_reports_unavailable_sections(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bundle, "detect_storage_profile", _storage)
    monkeypatch.setattr(bundle, "_windows_storage", lambda _root: {"status": "unavailable"})
    monkeypatch.setattr(bundle, "_raid_tools", lambda: {"status": "not_available"})
    output = tmp_path / "diagnostic.zip"
    bundle.collect_field_diagnostic_bundle(
        {"data_root": str(tmp_path), "sample_duration_minutes": 0, "raw_sample": False},
        output,
    )
    with zipfile.ZipFile(output) as archive:
        assert "samples/raw_sample.ndjson" not in archive.namelist()
        assert json.loads(archive.read("samples/raw_sample_meta.json"))["status"] == "excluded"


def test_bundle_honors_cancellation_before_package_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bundle, "detect_storage_profile", _storage)
    monkeypatch.setattr(bundle, "_windows_storage", lambda _root: {"status": "unavailable"})
    monkeypatch.setattr(bundle, "_raid_tools", lambda: {"status": "not_available"})
    output = tmp_path / "diagnostic.zip"
    try:
        bundle.collect_field_diagnostic_bundle(
            {"data_root": str(tmp_path), "sample_duration_minutes": 0},
            output,
            should_cancel=lambda: True,
        )
    except bundle.DiagnosticCancelled:
        pass
    else:
        raise AssertionError("expected cancellation")
