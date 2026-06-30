from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core.feature_flags import FeatureDisabledError, FeatureGate, install_runtime_feature_files, load_profile
from netconsole.core.feature_registry import FEATURE_BY_ID, list_features
from project.build_release import NUITKA_ALLOWED_RELEASE_ITEMS, validate_zip_file, zip_directory


def write_runtime(root: Path, edition: str, profile: str, features: dict[str, dict[str, bool]]) -> None:
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "build_info.json").write_text(
        json.dumps({"edition": edition, "feature_profile": profile}, ensure_ascii=False),
        encoding="utf-8",
    )
    (runtime / "feature_flags.json").write_text(
        json.dumps({"schema_version": 1, "profile": profile, "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_feature_registry_lists_expected_features() -> None:
    feature_ids = {item.feature_id for item in list_features()}

    assert "module.rail_transit" in feature_ids
    assert "rail.online_mr_collection" in feature_ids
    assert FEATURE_BY_ID["system.feature_flags"].internal_only is True


def test_feature_gate_full_profile_defaults_visible(tmp_path: Path) -> None:
    write_runtime(tmp_path, "internal", "full", {})

    gate = FeatureGate(tmp_path)

    assert all(gate.is_visible(item.feature_id) for item in list_features())
    assert gate.is_visible("system.feature_flags")


def test_feature_gate_customer_profile_hides_config_and_disabled_feature(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "customer",
        "customer",
        {
            "rail.online_mr_collection": {"visible": False, "enabled": False},
            "system.feature_flags": {"visible": True, "enabled": True},
        },
    )

    gate = FeatureGate(tmp_path)

    assert not gate.is_visible("rail.online_mr_collection")
    assert not gate.is_enabled("rail.online_mr_collection")
    assert not gate.is_visible("system.feature_flags")
    with pytest.raises(FeatureDisabledError):
        gate.assert_enabled("rail.online_mr_collection")


def test_install_runtime_feature_files_writes_distinct_editions(tmp_path: Path) -> None:
    internal = tmp_path / "internal"
    customer = tmp_path / "customer"
    install_runtime_feature_files(internal, edition="internal", profile="full")
    install_runtime_feature_files(customer, edition="customer", profile="customer")

    internal_info = json.loads((internal / "runtime" / "build_info.json").read_text(encoding="utf-8"))
    customer_info = json.loads((customer / "runtime" / "build_info.json").read_text(encoding="utf-8"))
    customer_flags = json.loads((customer / "runtime" / "feature_flags.json").read_text(encoding="utf-8"))

    assert internal_info != customer_info
    assert customer_flags["features"]["system.feature_flags"] == {"visible": False, "enabled": False}


def test_load_profile_keeps_saved_customer_flags(tmp_path: Path) -> None:
    profile_path = tmp_path / "customer.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "customer",
                "features": {
                    "module.network_tools": {"visible": False, "enabled": False},
                    "online_mr.collect_config_once": {"visible": False, "enabled": False},
                    "system.feature_flags": {"visible": True, "enabled": True},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    features = load_profile(profile_path, "customer")

    assert features["module.network_tools"] == {"visible": False, "enabled": False}
    assert features["online_mr.collect_config_once"] == {"visible": False, "enabled": False}
    assert features["system.feature_flags"] == {"visible": False, "enabled": False}


def test_customer_zip_keeps_allowlist_and_hidden_feature_config(tmp_path: Path) -> None:
    app_dir = tmp_path / "customer"
    (app_dir / "_internal").mkdir(parents=True)
    (app_dir / "data").mkdir()
    (app_dir / "runtime" / "logs").mkdir(parents=True)
    (app_dir / "NetConsole.exe").write_text("", encoding="utf-8")
    install_runtime_feature_files(app_dir, edition="customer", profile="customer")
    zip_path = tmp_path / "NetConsole_customer.zip"

    zip_directory(app_dir, zip_path, app_dir, NUITKA_ALLOWED_RELEASE_ITEMS)
    validate_zip_file(zip_path)

    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        flags = json.loads(archive.read("runtime/feature_flags.json").decode("utf-8"))

    assert "NetConsole.exe" in names
    assert "runtime/feature_flags.json" in names
    assert all(not name.startswith(("docs/", "tests/", "project/")) for name in names)
    assert flags["features"]["system.feature_flags"] == {"visible": False, "enabled": False}
