from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build import pyinstaller_artifact_inventory as inventory


_VALID_EXECUTABLE = {
    "name": "NetConsoleBackend.exe",
    "sha256": "0" * 64,
}


class FakeDistribution:
    def __init__(self, root: Path, name: str, version: str, files: list[str]):
        self.root = root
        self.metadata = {"Name": name}
        self.version = version
        self.files = [Path(item) for item in files]

    def locate_file(self, relative: object) -> Path:
        return self.root / Path(str(relative))


def _write_toc(path: Path, groups: dict[str, list[tuple[str, str, str]]]) -> Path:
    values: list[object] = [[] for _ in range(20)]
    for group, index in inventory._ANALYSIS_GROUP_INDEX.items():
        values[index] = groups.get(group, [])
    path.write_text(repr(tuple(values)), encoding="utf-8")
    return path


def test_collects_actual_toc_file_owners_including_packaging_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    site_packages = tmp_path / "site-packages"
    runtime_file = site_packages / "demo_pkg" / "runtime.py"
    hook_file = site_packages / "_pyinstaller_hooks_contrib" / "rthooks" / "hook.py"
    runtime_file.parent.mkdir(parents=True)
    hook_file.parent.mkdir(parents=True)
    runtime_file.write_text("", encoding="utf-8")
    hook_file.write_text("", encoding="utf-8")
    installed = [
        FakeDistribution(site_packages, "Demo_Pkg", "1.2.3", ["demo_pkg/runtime.py"]),
        FakeDistribution(
            site_packages,
            "pyinstaller-hooks-contrib",
            "2026.5",
            ["_pyinstaller_hooks_contrib/rthooks/hook.py"],
        ),
    ]
    monkeypatch.setattr(inventory.metadata, "distributions", lambda: installed)
    toc = _write_toc(
        tmp_path / "Analysis-00.toc",
        {
            "pure": [("demo_pkg.runtime", str(runtime_file), "PYMODULE")],
            "scripts": [("pyi_rth_demo", str(hook_file), "PYSOURCE")],
        },
    )

    result = inventory.collect_pyinstaller_distributions(toc)

    assert result == {
        "demo-pkg": "1.2.3",
        "pyinstaller-hooks-contrib": "2026.5",
    }


def test_exact_approval_rejects_extra_ambient_distribution_and_version_drift(
    tmp_path: Path,
):
    executable = tmp_path / "NetConsoleBackend.exe"
    executable.write_bytes(b"exe")
    actual = {"approved": "1.0", "ambient": "2.0"}

    with pytest.raises(inventory.ArtifactInventoryError, match=r"extra=\['ambient'\]"):
        inventory.create_inventory(
            actual, executable=executable, expected={"approved": "1.0"}
        )

    with pytest.raises(
        inventory.ArtifactInventoryError, match=r"version_drift=\['approved'\]"
    ):
        inventory.create_inventory(
            {"approved": "1.1"},
            executable=executable,
            expected={"approved": "1.0"},
        )


@pytest.mark.parametrize(
    "raw",
    [
        "not a toc",
        repr(([],)),
        repr(tuple([[] for _ in range(13)] + ["bad"] + [[] for _ in range(6)])),
    ],
)
def test_rejects_corrupt_or_unsupported_analysis_toc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
):
    toc = tmp_path / "Analysis-00.toc"
    toc.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(inventory.metadata, "distributions", lambda: [])

    with pytest.raises(inventory.ArtifactInventoryError):
        inventory.collect_pyinstaller_distributions(toc)


def test_rejects_ambiguous_distribution_file_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "site-packages"
    source = root / "shared.py"
    source.parent.mkdir()
    source.write_text("", encoding="utf-8")
    installed = [
        FakeDistribution(root, "owner-one", "1.0", ["shared.py"]),
        FakeDistribution(root, "owner-two", "2.0", ["shared.py"]),
    ]
    monkeypatch.setattr(inventory.metadata, "distributions", lambda: installed)
    toc = _write_toc(
        tmp_path / "Analysis-00.toc",
        {"pure": [("shared", str(source), "PYMODULE")]},
    )

    with pytest.raises(inventory.ArtifactInventoryError, match="ambiguous"):
        inventory.collect_pyinstaller_distributions(toc)


def test_rejects_unowned_file_inside_distribution_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "site-packages"
    owned = root / "known.py"
    ambient = root / "ambient.py"
    root.mkdir()
    owned.write_text("", encoding="utf-8")
    ambient.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        inventory.metadata,
        "distributions",
        lambda: [FakeDistribution(root, "known", "1.0", ["known.py"])],
    )
    toc = _write_toc(
        tmp_path / "Analysis-00.toc",
        {"pure": [("ambient", str(ambient), "PYMODULE")]},
    )

    with pytest.raises(inventory.ArtifactInventoryError, match="no RECORD ownership"):
        inventory.collect_pyinstaller_distributions(toc)


def test_editable_project_root_is_not_treated_as_third_party_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source_root = tmp_path / "src"
    source = source_root / "netconsole" / "core.py"
    source.parent.mkdir(parents=True)
    source.write_text("", encoding="utf-8")
    readme = source_root / "README.md"
    readme.write_text("project metadata", encoding="utf-8")
    monkeypatch.setattr(
        inventory.metadata,
        "distributions",
        lambda: [FakeDistribution(source_root, "netconsole", "1.3.9", ["README.md"])],
    )
    toc = _write_toc(
        tmp_path / "Analysis-00.toc",
        {"pure": [("netconsole.core", str(source), "PYMODULE")]},
    )

    assert inventory.collect_pyinstaller_distributions(toc) == {}


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            {
                "schema": inventory.SCHEMA_ID,
                "executable": _VALID_EXECUTABLE,
                "distributions": [
                    {"name": "demo", "version": "1.0"},
                    {"name": "Demo", "version": "1.0"},
                ],
            },
            "Duplicate inventory distribution",
        ),
        (
            {
                "schema": inventory.SCHEMA_ID,
                "executable": _VALID_EXECUTABLE,
                "distributions": [
                    {"name": "demo", "version": "1.0", "path": "C:/secret"}
                ],
            },
            "only name and version",
        ),
        (
            {
                "schema": inventory.SCHEMA_ID,
                "executable": _VALID_EXECUTABLE,
                "distributions": [{"name": "demo", "version": "C:\\secret"}],
            },
            "must not contain a path",
        ),
        (
            {
                "schema": inventory.SCHEMA_ID,
                "executable": _VALID_EXECUTABLE,
                "distributions": [{"name": "../demo", "version": "1.0"}],
            },
            "invalid distribution name",
        ),
        (
            {
                "schema": inventory.SCHEMA_ID,
                "executable": _VALID_EXECUTABLE,
                "distributions": [{"name": "demo", "version": "not a version!"}],
            },
            "invalid distribution version",
        ),
    ],
)
def test_inventory_rejects_duplicates_extra_fields_and_path_leaks(
    payload: object, message: str
):
    with pytest.raises(inventory.ArtifactInventoryError, match=message):
        inventory.validate_inventory(payload)


def test_load_inventory_rejects_duplicate_json_fields(tmp_path: Path):
    path = tmp_path / "inventory.json"
    path.write_text(
        '{"schema":"netconsole.pyinstaller-artifact-inventory.v1",'
        '"schema":"netconsole.pyinstaller-artifact-inventory.v1",'
        '"distributions":[]}',
        encoding="utf-8",
    )

    with pytest.raises(inventory.ArtifactInventoryError, match="Duplicate JSON field"):
        inventory.load_inventory(path)


def test_write_inventory_is_deterministic_and_path_free(tmp_path: Path):
    path = tmp_path / "inventory.json"
    executable = tmp_path / "NetConsoleBackend.exe"
    executable.write_bytes(b"final executable")

    inventory.write_inventory(
        path,
        {"Zed": "2.0", "alpha_pkg": "1.0"},
        executable=executable,
        expected={"alpha-pkg": "1.0", "zed": "2.0"},
    )

    assert inventory.load_inventory(
        path,
        expected={"alpha-pkg": "1.0", "zed": "2.0"},
        executable=executable,
    ) == {"alpha-pkg": "1.0", "zed": "2.0"}
    text = path.read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert '"name": "alpha-pkg"' in text
    assert text.index("alpha-pkg") < text.index("zed")


def test_inventory_recomputes_final_executable_hash(tmp_path: Path):
    executable = tmp_path / "NetConsoleBackend.exe"
    executable.write_bytes(b"original")
    payload = inventory.create_inventory({"demo": "1.0"}, executable=executable)

    executable.write_bytes(b"mutated")

    with pytest.raises(inventory.ArtifactInventoryError, match="does not match"):
        inventory.validate_inventory(payload, executable=executable)


def test_inventory_rejects_executable_path_leak():
    payload = {
        "schema": inventory.SCHEMA_ID,
        "executable": {
            "name": "C:\\release\\NetConsoleBackend.exe",
            "sha256": "0" * 64,
        },
        "distributions": [],
    }

    with pytest.raises(inventory.ArtifactInventoryError, match="executable name"):
        inventory.validate_inventory(payload)


def test_app_dir_requires_final_artifact_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    site_packages = tmp_path / "site-packages"
    source = site_packages / "demo" / "payload.dat"
    source.parent.mkdir(parents=True)
    source.write_text("payload", encoding="utf-8")
    monkeypatch.setattr(
        inventory.metadata,
        "distributions",
        lambda: [FakeDistribution(site_packages, "demo", "1.0", ["demo/payload.dat"])],
    )
    toc = _write_toc(
        tmp_path / "Analysis-00.toc",
        {"datas": [("demo/payload.dat", str(source), "DATA")]},
    )
    app_dir = tmp_path / "dist" / "Demo"
    app_dir.mkdir(parents=True)
    monkeypatch.setattr(
        inventory, "_read_final_archive_names", lambda _path: (set(), set())
    )

    with pytest.raises(
        inventory.ArtifactInventoryError, match="No final-artifact evidence"
    ):
        inventory.collect_pyinstaller_distributions(toc, app_dir)

    packaged = app_dir / "_internal" / "demo" / "payload.dat"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("payload", encoding="utf-8")
    assert inventory.collect_pyinstaller_distributions(toc, app_dir) == {"demo": "1.0"}


def test_app_dir_accepts_pyz_module_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    site_packages = tmp_path / "site-packages"
    source = site_packages / "demo" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        inventory.metadata,
        "distributions",
        lambda: [FakeDistribution(site_packages, "demo", "1.0", ["demo/module.py"])],
    )
    toc = _write_toc(
        tmp_path / "Analysis-00.toc",
        {"pure": [("demo.module", str(source), "PYMODULE")]},
    )
    app_dir = tmp_path / "dist" / "Demo"
    app_dir.mkdir(parents=True)
    monkeypatch.setattr(
        inventory,
        "_read_final_archive_names",
        lambda _path: ({"PYZ.pyz"}, {"demo.module"}),
    )

    assert inventory.collect_pyinstaller_distributions(toc, app_dir) == {"demo": "1.0"}


def test_json_payload_has_only_versioned_schema_and_distribution_records(
    tmp_path: Path,
):
    executable = tmp_path / "NetConsoleBackend.exe"
    executable.write_bytes(b"exe")
    payload = inventory.create_inventory({"demo": "1.0"}, executable=executable)

    assert payload == {
        "schema": "netconsole.pyinstaller-artifact-inventory.v1",
        "executable": {
            "name": "NetConsoleBackend.exe",
            "sha256": "9095bdb859308b62acf04036ffd4adfe366d7f737d276eb6c46ae434f3816c9b",
        },
        "distributions": [{"name": "demo", "version": "1.0"}],
    }
    assert json.loads(json.dumps(payload)) == payload


def test_loads_exact_human_approved_distribution_baseline(tmp_path: Path):
    path = tmp_path / "approved.json"
    path.write_text(
        json.dumps(
            {
                "schema": inventory.APPROVAL_SCHEMA_ID,
                "platform": "windows-x64",
                "python_version": "3.13",
                "distributions": [
                    {"name": "demo", "version": "1.0"},
                    {"name": "second-package", "version": "2.0"},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert inventory.load_approved_distributions(
        path,
        platform="windows-x64",
        python_version="3.13",
    ) == {"demo": "1.0", "second-package": "2.0"}


def test_approval_rejects_platform_drift_and_unsorted_self_approval(tmp_path: Path):
    payload = {
        "schema": inventory.APPROVAL_SCHEMA_ID,
        "platform": "windows-x64",
        "python_version": "3.13",
        "distributions": [
            {"name": "z-last", "version": "1.0"},
            {"name": "a-first", "version": "1.0"},
        ],
    }
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        inventory.ArtifactInventoryError,
        match="deterministically sorted",
    ):
        inventory.load_approved_distributions(
            path,
            platform="windows-x64",
            python_version="3.13",
        )
    payload["distributions"].reverse()
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(inventory.ArtifactInventoryError, match="platform"):
        inventory.load_approved_distributions(
            path,
            platform="linux-x64",
            python_version="3.13",
        )
