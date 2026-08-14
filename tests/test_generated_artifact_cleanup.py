from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.maintenance.clean_generated_artifacts import CleanupError, clean_generated_artifacts


def _repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='netconsole'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    return tmp_path


def test_cleanup_defaults_to_dry_run(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    target = root / "dist" / "v1.3.8"
    target.mkdir(parents=True)
    (target / "Qt6Core.dll").write_bytes(b"qt")

    report = clean_generated_artifacts(root, "legacy-qt-release")

    assert report["mode"] == "dry-run"
    assert report["items"] == [
        {
            "relative_path": "dist/v1.3.8",
            "status": "planned",
            "file_count": 1,
            "total_bytes": 2,
        }
    ]
    assert target.exists()


def test_cleanup_removes_only_allowlisted_legacy_release(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    target = root / "dist" / "v1.3.8"
    current = root / "dist" / "v1.4.6"
    data = root / "data"
    for directory in (target, current, data):
        directory.mkdir(parents=True)
        (directory / "keep-or-remove.txt").write_text(directory.name, encoding="utf-8")

    report = clean_generated_artifacts(root, "legacy-qt-release", apply=True)

    assert report["mode"] == "apply"
    assert report["items"][0]["status"] == "removed"
    assert not target.exists()
    assert current.exists()
    assert data.exists()


def test_cleanup_removes_only_build_temporary_directory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    temporary = root / "dist" / "_build"
    retained = [
        root / "dist" / "v1.4.6",
        root / "dist" / "electron",
        root / "dist" / "agent",
        root / "data",
    ]
    temporary.mkdir(parents=True)
    (temporary / "setuptools-residue").mkdir()
    (temporary / "setuptools-residue" / "module.py").write_text("generated", encoding="utf-8")
    for directory in retained:
        directory.mkdir(parents=True)
        (directory / "keep.txt").write_text("keep", encoding="utf-8")

    planned = clean_generated_artifacts(root, "build-temporary")
    applied = clean_generated_artifacts(root, "build-temporary", apply=True)

    assert planned["items"] == [
        {
            "relative_path": "dist/_build",
            "status": "planned",
            "file_count": 1,
            "total_bytes": 9,
        }
    ]
    assert applied["items"][0]["status"] == "removed"
    assert not temporary.exists()
    assert all(directory.exists() for directory in retained)


def test_all_build_output_cleanup_never_touches_durable_release(tmp_path: Path) -> None:
    root = _repo(tmp_path / "NetConsole")
    generated = root / "dist" / "electron" / "setup.exe"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"build")
    durable = tmp_path / "release" / "NetConsole" / "v1.4.9" / "setup.exe"
    durable.parent.mkdir(parents=True)
    durable.write_bytes(b"release")

    report = clean_generated_artifacts(root, "all-build-output", apply=True)

    assert report["items"][0]["status"] == "removed"
    assert not (root / "dist").exists()
    assert durable.read_bytes() == b"release"


def test_cleanup_rejects_linked_target(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / "dist" / "v1.3.8"
    target.parent.mkdir(parents=True)
    try:
        os.symlink(outside, target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"当前 Windows 环境不能创建符号链接：{exc}")

    with pytest.raises(CleanupError, match="符号链接"):
        clean_generated_artifacts(root, "legacy-qt-release", apply=True)

    assert outside.exists()
