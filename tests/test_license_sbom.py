from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest

from scripts.build.check_runtime_deps import check_runtime_deps
from scripts.build.generate_sbom import (
    audit_runtime_inventory_with_cyclonedx,
    required_python_component_versions,
    validate_notice_file,
    validate_sbom,
    write_runtime_sbom,
)
from scripts.build.pyinstaller_artifact_inventory import (
    load_approved_distributions,
    write_inventory,
)


ROOT = Path(__file__).resolve().parents[1]


def _valid_notice() -> list[dict[str, object]]:
    return [
        {
            "name": "Python",
            "version": "3.13.9",
            "scope": "runtime",
            "license": "PSF License",
            "purl": "pkg:generic/python@3.13.9",
        },
        {
            "name": "Electron",
            "version": "43.1.1",
            "scope": "electron",
            "license": "MIT",
            "purl": "pkg:npm/electron@43.1.1",
        },
        {
            "name": "Chromium",
            "version": "150.0.7871.114",
            "scope": "electron",
            "license": "BSD-3-Clause",
            "purl": "pkg:generic/chromium@150.0.7871.114",
        },
        {
            "name": "Node.js",
            "version": "24.18.0",
            "scope": "electron",
            "license": "MIT",
            "purl": "pkg:generic/node.js@24.18.0",
        },
        {
            "name": "fping",
            "version": "5.5",
            "scope": "runtime-tool",
            "license": "BSD-like",
            "purl": "pkg:generic/fping@5.5",
            "notice_file": "licenses/fping.txt",
        },
        {
            "name": "iPerf3 Windows x64 Cygwin dynamic-auth",
            "version": "3.21",
            "scope": "runtime-tool",
            "license": "BSD-3-Clause and bundled permissive notices",
            "purl": "pkg:generic/iperf3@3.21",
            "notice_file": "licenses/iperf.txt",
        },
        {
            "name": "cJSON (embedded in iPerf3)",
            "version": "1.7.15",
            "scope": "runtime-tool",
            "license": "MIT",
            "purl": "pkg:generic/cjson@1.7.15",
            "notice_file": "licenses/iperf.txt",
        },
        {
            "name": "Cygwin Runtime (fping bundle)",
            "version": "3.6.9",
            "scope": "runtime-tool",
            "license": "LGPL-3.0-or-later WITH Cygwin-exception-3.0",
            "purl": "pkg:generic/cygwin@3.6.9",
            "notice_file": "licenses/cygwin-fping.txt",
        },
        {
            "name": "Cygwin Runtime (iPerf3 bundle)",
            "version": "3.6.7",
            "scope": "runtime-tool",
            "license": "LGPL-3.0-or-later WITH Cygwin-exception-3.0",
            "purl": "pkg:generic/cygwin@3.6.7",
            "notice_file": "licenses/cygwin-iperf.txt",
        },
        {
            "name": "OpenSSL Runtime (iPerf3 bundle)",
            "version": "3.0.19",
            "scope": "runtime-tool",
            "license": "Apache-2.0",
            "purl": "pkg:generic/openssl@3.0.19",
            "notice_file": "licenses/openssl.txt",
        },
        {
            "name": "zlib Runtime (iPerf3 bundle)",
            "version": "1.3.2",
            "scope": "runtime-tool",
            "license": "Zlib",
            "purl": "pkg:generic/zlib@1.3.2",
            "notice_file": "licenses/zlib.txt",
        },
        {
            "name": "PyInstaller",
            "version": "6.21.0",
            "scope": "packaged-build-runtime",
            "license": "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0",
            "purl": "pkg:pypi/pyinstaller@6.21.0",
            "license_files": ["licenses/PYINSTALLER_COPYING.txt"],
        },
        {
            "name": "pyinstaller-hooks-contrib",
            "version": "2026.6",
            "scope": "packaged-build-runtime",
            "license": "Apache-2.0",
            "purl": "pkg:pypi/pyinstaller-hooks-contrib@2026.6",
            "license_files": ["licenses/PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt"],
        },
    ]


def _valid_sbom(
    python_components: dict[str, str] | None = None,
) -> dict[str, object]:
    components = [
        {
            "type": "library",
            "name": item[0],
            "version": item[1],
            "bom-ref": item[2],
            "purl": item[2],
            "licenses": [{"license": {"id": item[3]}}],
        }
        for item in (
            ("Python", "3.13.9", "pkg:generic/python@3.13.9", "PSF License"),
            ("Electron", "43.1.1", "pkg:npm/electron@43.1.1", "MIT"),
            (
                "Chromium",
                "150.0.7871.114",
                "pkg:generic/chromium@150.0.7871.114",
                "BSD-3-Clause",
            ),
            ("Node.js", "24.18.0", "pkg:generic/node.js@24.18.0", "MIT"),
            ("fping", "5.5", "pkg:generic/fping@5.5", "BSD-like"),
            (
                "iPerf3 Windows x64 Cygwin dynamic-auth",
                "3.21",
                "pkg:generic/iperf3@3.21",
                "BSD-3-Clause and bundled permissive notices",
            ),
            ("cJSON (embedded in iPerf3)", "1.7.15", "pkg:generic/cjson@1.7.15", "MIT"),
            (
                "Cygwin Runtime (fping bundle)",
                "3.6.9",
                "pkg:generic/cygwin@3.6.9",
                "LGPL-3.0-or-later WITH Cygwin-exception-3.0",
            ),
            (
                "Cygwin Runtime (iPerf3 bundle)",
                "3.6.7",
                "pkg:generic/cygwin@3.6.7",
                "LGPL-3.0-or-later WITH Cygwin-exception-3.0",
            ),
            (
                "OpenSSL Runtime (iPerf3 bundle)",
                "3.0.19",
                "pkg:generic/openssl@3.0.19",
                "Apache-2.0",
            ),
            ("zlib Runtime (iPerf3 bundle)", "1.3.2", "pkg:generic/zlib@1.3.2", "Zlib"),
        )
    ]
    components.extend(
        {
            "type": "library",
            "name": name,
            "version": version,
            "bom-ref": f"pkg:pypi/{name}@{version}",
            "purl": f"pkg:pypi/{name}@{version}",
            "licenses": [{"license": {"id": "MIT"}}],
        }
        for name, version in (
            python_components or required_python_component_versions()
        ).items()
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "NetConsole Backend",
                "version": "1.3.9",
                "bom-ref": "pkg:generic/netconsole-backend@1.3.9",
            }
        },
        "components": components,
    }


def _make_packaged_runtime(tmp_path: Path) -> Path:
    app_dir = tmp_path / "NetConsoleBackend"
    internal = app_dir / "_internal" / "netconsole" / "assets"
    internal.mkdir(parents=True)
    tools = app_dir / "tools" / "windows-x64"
    (tools / "fping").mkdir(parents=True)
    (tools / "iperf3").mkdir(parents=True)
    (app_dir / "NetConsoleBackend.exe").write_bytes(b"MZ")
    (app_dir / "_internal" / "python313.dll").write_bytes(b"")
    for name in (
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
        "MSVCP140.dll",
        "CONCRT140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
    ):
        (app_dir / "_internal" / name).write_bytes(b"")
    for relative in (
        "fping/fping.exe",
        "fping/cygwin1.dll",
        "fping/COPYING",
        "fping/COPYING.LIB",
        "fping/GPL-3.0.txt",
        "fping/CYGWIN_LICENSE",
        "fping/BUILD_RECIPE.md",
        "fping/CORRESPONDING_SOURCE.md",
        "fping/CYGWIN_ICMP_COMPAT.patch",
        "fping/SOURCE_PROVENANCE.json",
        "iperf3/iperf3.exe",
        "iperf3/cygwin1.dll",
        "iperf3/cygcrypto-3.dll",
        "iperf3/cygz.dll",
        "iperf3/SOURCE_PROVENANCE.json",
        "iperf3/CORRESPONDING_SOURCE.md",
    ):
        (tools / relative).write_bytes(b"")
    licenses = tools / "iperf3" / "licenses"
    licenses.mkdir()
    for name in (
        "AR51AN_APACHE-2.0.txt",
        "CYGWIN_LGPL-3.0.txt",
        "CYGWIN_LINKING_EXCEPTION.txt",
        "GPL-3.0.txt",
        "IPERF3_LICENSE.txt",
        "OPENSSL_APACHE-2.0.txt",
        "ZLIB_LICENSE.txt",
    ):
        (licenses / name).write_text("license", encoding="utf-8")
    (internal / "open_source_notices.json").write_text(
        json.dumps(_valid_notice()), encoding="utf-8"
    )
    (internal / "THIRD_PARTY_COMPONENTS.md").write_text(
        "第三方组件说明", encoding="utf-8"
    )
    approved = load_approved_distributions(
        ROOT / "config" / "pyinstaller-approved-distributions.json",
        platform="windows-x64",
        python_version="3.13",
    )
    (internal / "sbom.cdx.json").write_text(
        json.dumps(_valid_sbom(approved)),
        encoding="utf-8",
    )
    write_inventory(
        internal / "pyinstaller-artifact-inventory.json",
        approved,
        executable=app_dir / "NetConsoleBackend.exe",
        expected=approved,
    )
    packaged_licenses = internal / "licenses"
    packaged_licenses.mkdir()
    for name in (
        "PYINSTALLER_COPYING.txt",
        "PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt",
    ):
        (packaged_licenses / name).write_bytes(
            (ROOT / "src" / "netconsole" / "assets" / "licenses" / name).read_bytes()
        )
    return app_dir


def test_product_notice_does_not_list_test_or_build_tools() -> None:
    path = ROOT / "src/netconsole/assets/open_source_notices.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    names = {str(item["name"]).casefold() for item in entries}
    assert "pytest" not in names
    assert not names & {"pytest", "mypy", "pip-licenses", "cyclonedx-bom"}
    assert {
        "paramiko",
        "electron",
        "chromium",
        "node.js",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
    } <= names
    scopes = {str(item["name"]).casefold(): item["scope"] for item in entries}
    assert scopes["pyinstaller"] == "packaged-build-runtime"
    assert scopes["pyinstaller-hooks-contrib"] == "packaged-build-runtime"
    assert {
        "iperf3 windows x64 cygwin dynamic-auth",
        "cjson (embedded in iperf3)",
        "cygwin runtime (fping bundle)",
        "cygwin runtime (iperf3 bundle)",
        "openssl runtime (iperf3 bundle)",
        "zlib runtime (iperf3 bundle)",
    } <= names
    assert path.read_bytes() == (ROOT / "docs/open_source_notices.json").read_bytes()


def test_project_notice_has_no_unknown_license() -> None:
    path = ROOT / "src/netconsole/assets/open_source_notices.json"
    assert validate_notice_file(path) == ()
    entries = json.loads(path.read_text(encoding="utf-8"))
    assert all(
        str(item.get("status") or "").casefold() != "blocked" for item in entries
    )
    for item in entries:
        for relative in item.get("license_files", ()):  # source-package evidence
            path = Path(relative)
            if path.parts and path.parts[0] == "tools":
                path = Path("resources") / path
            elif path.parts and path.parts[0] == "licenses":
                path = Path("src/netconsole/assets") / path
            assert (ROOT / path).is_file(), relative


def test_sbom_validation_rejects_unknown_license(tmp_path: Path) -> None:
    payload = _valid_sbom()
    payload["components"].append(
        {
            "type": "library",
            "name": "unknown-lib",
            "version": "1",
            "bom-ref": "pkg:pypi/unknown-lib@1",
            "purl": "pkg:pypi/unknown-lib@1",
            "licenses": [{"license": {"name": "UNKNOWN"}}],
        }
    )
    path = tmp_path / "bad.cdx.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert any("unknown-lib" in error for error in validate_sbom(path))


def test_sbom_validation_rejects_purl_version_drift(tmp_path: Path) -> None:
    payload = _valid_sbom()
    payload["components"][0]["version"] = "9.9"
    path = tmp_path / "purl-drift.cdx.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert any("PURL 版本不一致" in error for error in validate_sbom(path))


def test_sbom_validation_rejects_missing_locked_runtime_component(
    tmp_path: Path,
) -> None:
    payload = _valid_sbom()
    payload["components"] = [
        item
        for item in payload["components"]
        if str(item.get("name") or "").casefold() != "fastapi"
    ]
    path = tmp_path / "missing-fastapi.cdx.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert any(
        "缺少锁定 Python 组件：fastapi==" in error for error in validate_sbom(path)
    )


def test_sbom_validation_rejects_unapproved_python_component(tmp_path: Path) -> None:
    payload = _valid_sbom()
    payload["components"].append(
        {
            "type": "library",
            "name": "pytest",
            "version": "9.1.1",
            "bom-ref": "pkg:pypi/pytest@9.1.1",
            "purl": "pkg:pypi/pytest@9.1.1",
            "licenses": [{"license": {"id": "MIT"}}],
        }
    )
    path = tmp_path / "extra-pytest.cdx.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert any(
        "包含未批准 Python 组件：pytest==9.1.1" in error
        for error in validate_sbom(path)
    )


def test_sbom_validation_rejects_duplicate_canonical_python_name(
    tmp_path: Path,
) -> None:
    payload = _valid_sbom()
    payload["components"].append(
        {
            "type": "library",
            "name": "PyInstaller",
            "version": "6.21.0",
            "bom-ref": "pkg:pypi/pyinstaller@6.21.0",
            "purl": "pkg:pypi/pyinstaller@6.21.0",
            "licenses": [{"license": {"id": "Apache-2.0"}}],
        }
    )
    path = tmp_path / "duplicate-pyinstaller.cdx.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert any("Python 组件重复：pyinstaller" in error for error in validate_sbom(path))


def test_cyclonedx_audit_rejects_inventory_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_payload = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {"name": "fastapi", "version": "0.139.2"},
        ],
    }
    monkeypatch.setattr(
        "scripts.build.generate_sbom.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=json.dumps(audit_payload),
            stderr="",
        ),
    )

    with pytest.raises(ValueError, match="运行闭包交叉审计不一致"):
        audit_runtime_inventory_with_cyclonedx(
            {"fastapi": "0.139.2", "starlette": "1.3.1"}
        )


def test_runtime_guard_accepts_complete_compliance_artifacts(tmp_path: Path) -> None:
    result = check_runtime_deps(
        _make_packaged_runtime(tmp_path), require_compliance_artifacts=True
    )
    assert result.ok, result.messages
    assert "[OK] NOTICE, SBOM and artifact inventory validated" in result.messages


def test_runtime_guard_rejects_inventory_exe_and_license_tampering(
    tmp_path: Path,
) -> None:
    app_dir = _make_packaged_runtime(tmp_path / "inventory")
    inventory_path = (
        app_dir
        / "_internal"
        / "netconsole"
        / "assets"
        / "pyinstaller-artifact-inventory.json"
    )
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    payload["distributions"][0]["version"] = "999"
    inventory_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not check_runtime_deps(
        app_dir,
        require_compliance_artifacts=True,
    ).ok

    app_dir = _make_packaged_runtime(tmp_path / "executable")
    (app_dir / "NetConsoleBackend.exe").write_bytes(b"MZ-tampered")
    assert not check_runtime_deps(
        app_dir,
        require_compliance_artifacts=True,
    ).ok

    app_dir = _make_packaged_runtime(tmp_path / "license")
    (
        app_dir
        / "_internal"
        / "netconsole"
        / "assets"
        / "licenses"
        / "PYINSTALLER_COPYING.txt"
    ).write_text("tampered", encoding="utf-8")
    assert not check_runtime_deps(
        app_dir,
        require_compliance_artifacts=True,
    ).ok


def test_runtime_guard_rejects_full_qt_marker_set(tmp_path: Path) -> None:
    app_dir = _make_packaged_runtime(tmp_path)
    marker = app_dir / "_internal" / "legacy"
    marker.mkdir()
    for name in (
        "PySide2",
        "PySide6",
        "PyQt5",
        "PyQt6",
        "shiboken2",
        "shiboken6",
        "qfluentwidgets",
        "Qt5Core.dll",
        "Qt6Core.dll",
        "Qt6Svg.dll",
        "Qt6Qml.dll",
        "QtWebEngineProcess.exe",
        "qt.conf",
        "sip.pyd",
        "qwindowsd.dll",
    ):
        (marker / name).write_bytes(b"")
    result = check_runtime_deps(app_dir)
    assert not result.ok
    assert any("Qt runtime residue found" in message for message in result.messages)


def test_runtime_guard_uses_relative_precise_qt_paths(tmp_path: Path) -> None:
    app_dir = _make_packaged_runtime(tmp_path / "PySide6-parent")
    generic_plugin = app_dir / "_internal" / "plugins" / "imageformats"
    generic_plugin.mkdir(parents=True)
    (generic_plugin / "business-image.dll").write_bytes(b"")

    result = check_runtime_deps(app_dir)

    assert result.ok, result.messages


def test_sbom_validation_rejects_invalid_spec_and_purl(tmp_path: Path) -> None:
    payload = _valid_sbom()
    payload["specVersion"] = "0.1"
    payload["components"][0]["purl"] = "pkg:pypi/electron runtime@43.1.1"
    path = tmp_path / "bad-format.cdx.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    errors = validate_sbom(path)

    assert any("specVersion" in error for error in errors)
    assert any("PURL" in error for error in errors)


def test_generated_sbom_is_deterministic(tmp_path: Path) -> None:
    left = write_runtime_sbom(tmp_path / "left.cdx.json")
    right = write_runtime_sbom(tmp_path / "right.cdx.json")
    assert json.loads(left.read_text(encoding="utf-8")) == json.loads(
        right.read_text(encoding="utf-8")
    )


def test_generated_sbom_uses_the_correct_component_ecosystems(tmp_path: Path) -> None:
    path = write_runtime_sbom(tmp_path / "runtime.cdx.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    components = {item["name"].casefold(): item for item in payload["components"]}

    assert components["fastapi"]["purl"].startswith("pkg:pypi/fastapi@")
    assert components["websockets"]["version"] == "16.0"
    assert components["pyinstaller"]["version"] == "6.21.0"
    assert components["pyinstaller-hooks-contrib"]["version"] == "2026.6"
    assert components["pyinstaller"]["licenses"] == [
        {"expression": "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0"}
    ]
    assert components["electron"]["purl"].startswith("pkg:npm/electron@")
    assert components["chromium"]["purl"].startswith("pkg:generic/chromium@")
    assert components["node.js"]["purl"].startswith("pkg:generic/node.js@")
    assert " " not in components["iperf3 windows x64 cygwin dynamic-auth"]["purl"]
    assert (
        components["openssl runtime (iperf3 bundle)"]["purl"]
        == "pkg:generic/openssl@3.0.19"
    )
    assert components["numpy"]["licenses"] == [
        {"expression": "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"}
    ]
    assert validate_sbom(path) == ()


def test_packaged_sbom_matches_the_approved_actual_artifact_exactly(
    tmp_path: Path,
) -> None:
    approved = load_approved_distributions(
        ROOT / "config" / "pyinstaller-approved-distributions.json",
        platform="windows-x64",
        python_version="3.13",
    )
    path = write_runtime_sbom(
        tmp_path / "packaged.cdx.json",
        packaged_python_components=approved,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    actual = {
        item["name"].casefold().replace("_", "-").replace(".", "-"): item["version"]
        for item in payload["components"]
        if str(item.get("purl") or "").startswith("pkg:pypi/")
    }

    assert actual == approved
    assert validate_sbom(path, required_python_components=approved) == ()
