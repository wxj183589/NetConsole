from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core.feature_flags import (
    FeatureDisabledError,
    FeatureGate,
    default_profile,
    engineer_package_enabled,
    install_runtime_feature_files,
    load_profile,
    save_profile,
)
from netconsole.core.feature_registry import FEATURE_BY_ID, FeatureStatus, list_features
from project.build_release import NUITKA_ALLOWED_RELEASE_ITEMS, validate_embedded_feature_gate, validate_zip_file, zip_directory


PROTECTED_INTERNAL_STATE = {"visible": True, "enabled": True, "client_package": False, "internal_only": True}


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
    assert "module.system_settings" in feature_ids
    assert "module.feature_switch" in feature_ids
    assert "rail.online_mr_collection" in feature_ids
    assert "online_mr.collect_config_once" not in feature_ids
    assert FEATURE_BY_ID["module.feature_switch"].internal_only is True
    assert FEATURE_BY_ID["system.feature_flags"].internal_only is True


def test_feature_gate_full_profile_defaults_visible(tmp_path: Path) -> None:
    write_runtime(tmp_path, "internal", "full", {})

    gate = FeatureGate(tmp_path)

    assert all(gate.is_visible(item.feature_id) for item in list_features() if item.status is FeatureStatus.ENABLED)
    assert gate.is_visible("module.feature_switch")
    assert gate.is_visible("system.feature_flags")
    assert not gate.is_visible("module.snmp_center")
    assert not gate.is_visible("module.wifi_survey")


def test_disabled_modules_cannot_be_reenabled_by_profile(tmp_path: Path) -> None:
    forced_on = {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    write_runtime(
        tmp_path,
        "internal",
        "full",
        {"module.snmp_center": forced_on, "module.wifi_survey": forced_on},
    )

    gate = FeatureGate(tmp_path)

    for feature_id in ("module.snmp_center", "module.wifi_survey"):
        assert gate.status_for(feature_id) is FeatureStatus.DISABLED
        assert gate.state_for(feature_id) == {
            "visible": False,
            "enabled": False,
            "client_package": False,
            "internal_only": False,
        }


def test_packaged_runtime_never_exposes_feature_switch_page(tmp_path: Path, monkeypatch) -> None:
    from netconsole.core import feature_flags

    write_runtime(tmp_path, "engineer", "full", {})
    monkeypatch.setattr(feature_flags, "is_packaged_runtime", lambda: True)

    gate = FeatureGate(tmp_path)

    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_enabled("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")
    assert not gate.is_enabled("system.feature_flags")


def test_engineer_package_option_persists_in_customer_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "customer.json"

    save_profile(profile_path, "customer", {}, build_options={"engineer_package": True})

    assert engineer_package_enabled(profile_path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert payload["build_options"] == {"engineer_package": True}


def test_feature_gate_customer_profile_hides_config_and_disabled_feature(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "customer",
        "customer",
        {
            "rail.online_mr_collection": {"visible": False, "enabled": False},
            "module.feature_switch": {"visible": True, "enabled": True},
            "system.feature_flags": {"visible": True, "enabled": True},
        },
    )

    gate = FeatureGate(tmp_path)

    assert not gate.is_visible("rail.online_mr_collection")
    assert not gate.is_enabled("rail.online_mr_collection")
    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")
    with pytest.raises(FeatureDisabledError):
        gate.assert_enabled("rail.online_mr_collection")


def test_internal_profile_cannot_hide_feature_switch_entry(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "internal",
        "full",
        {
            "module.feature_switch": {"visible": False, "enabled": False},
            "system.feature_flags": {"visible": False, "enabled": False},
        },
    )

    gate = FeatureGate(tmp_path)

    assert gate.is_visible("module.feature_switch")
    assert gate.is_enabled("module.feature_switch")
    assert gate.is_visible("system.feature_flags")
    assert gate.is_enabled("system.feature_flags")


def test_install_runtime_feature_files_writes_distinct_editions(tmp_path: Path) -> None:
    internal = tmp_path / "internal"
    customer = tmp_path / "customer"
    install_runtime_feature_files(internal, edition="internal", profile="full")
    install_runtime_feature_files(customer, edition="customer", profile="customer", admin_unlock_password="temporary-secret")

    internal_info = json.loads((internal / "runtime" / "build_info.json").read_text(encoding="utf-8"))
    customer_info = json.loads((customer / "runtime" / "build_info.json").read_text(encoding="utf-8"))
    customer_flags = json.loads((customer / "runtime" / "feature_flags.json").read_text(encoding="utf-8"))
    embedded_info_text = (customer / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json").read_text(encoding="utf-8")

    assert internal_info != customer_info
    assert internal_info["admin_unlock_enabled"] is False
    assert customer_info["admin_unlock_enabled"] is True
    assert "temporary-secret" not in embedded_info_text
    assert customer_flags["features"]["module.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert customer_flags["features"]["system.feature_flags"] == PROTECTED_INTERNAL_STATE
    assert (customer / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json").is_file()
    assert (customer / "_internal" / "netconsole" / "assets" / "runtime" / "feature_flags.json").is_file()
    assert (customer / "_internal" / "netconsole" / "assets" / "runtime" / "feature_flags.full.json").is_file()


def test_customer_embedded_feature_flags_survive_missing_runtime(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")
    runtime = tmp_path / "runtime"
    for path in sorted(runtime.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    runtime.rmdir()

    gate = FeatureGate(tmp_path)

    assert gate.build_info["edition"] == "customer"
    assert gate.build_info["feature_profile"] == "customer"
    assert gate.resolution.source == "embedded"
    assert gate.allow_local_override is False
    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")


def test_customer_admin_unlock_requires_configured_hash(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")

    gate = FeatureGate(tmp_path)

    assert gate.is_admin_unlock_configured() is False
    assert gate.verify_admin_unlock_password("temporary-secret") is False
    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")


def test_customer_session_full_mode_is_process_only(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer", admin_unlock_password="temporary-secret")
    runtime_info_before = (tmp_path / "runtime" / "build_info.json").read_text(encoding="utf-8")
    embedded_info_before = (tmp_path / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json").read_text(encoding="utf-8")

    gate = FeatureGate(tmp_path)

    assert gate.edition == "customer"
    assert gate.profile == "customer"
    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")
    assert gate.verify_admin_unlock_password("wrong") is False
    assert gate.verify_admin_unlock_password("temporary-secret") is True

    gate.enable_session_full_mode(reason="test", operator="tester")

    assert gate.edition == "customer"
    assert gate.profile == "full"
    assert gate.base_profile == "customer"
    assert gate.is_session_override_active()
    assert gate.current_profile_source() == "embedded+session_override"
    assert gate.is_visible("module.feature_switch")
    assert gate.is_enabled("module.feature_switch")
    assert gate.is_visible("system.feature_flags")
    assert gate.is_enabled("system.feature_flags")
    assert not (tmp_path / "runtime" / "feature_flags.local.json").exists()
    assert (tmp_path / "runtime" / "build_info.json").read_text(encoding="utf-8") == runtime_info_before
    assert (tmp_path / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json").read_text(encoding="utf-8") == embedded_info_before

    gate.disable_session_override(reason="test")

    assert not gate.is_session_override_active()
    assert gate.profile == "customer"
    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")

    restarted = FeatureGate(tmp_path)
    assert restarted.profile == "customer"
    assert not restarted.is_session_override_active()
    assert not restarted.is_visible("module.feature_switch")
    assert not restarted.is_visible("system.feature_flags")


def test_customer_local_override_cannot_enable_internal_only(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")
    local = tmp_path / "runtime" / "feature_flags.local.json"
    local.write_text(
        json.dumps(
            {
                "profile": "full",
                "features": {
                    "module.feature_switch": {"visible": True, "enabled": True},
                    "system.feature_flags": {"visible": True, "enabled": True},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    gate = FeatureGate(tmp_path, allow_local_override=True)

    assert gate.allow_local_override is False
    assert not gate.is_visible("module.feature_switch")
    assert not gate.is_enabled("module.feature_switch")
    assert not gate.is_visible("system.feature_flags")
    assert not gate.is_enabled("system.feature_flags")


def test_build_validation_checks_customer_without_runtime(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")

    validate_embedded_feature_gate(tmp_path, edition="customer", profile="customer")

    assert (tmp_path / "runtime" / "build_info.json").is_file()


def test_load_profile_keeps_saved_customer_flags(tmp_path: Path) -> None:
    profile_path = tmp_path / "customer.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "customer",
                    "features": {
                        "module.network_tools": {"visible": False, "enabled": False},
                        "module.system_settings": {"visible": None, "enabled": ""},
                        "module.feature_switch": {"visible": True, "enabled": True},
                        "system.feature_flags": {"visible": True, "enabled": True},
                    },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    features = load_profile(profile_path, "customer")

    assert features["module.network_tools"] == {"visible": False, "enabled": False, "client_package": False, "internal_only": False}
    assert features["module.system_settings"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert features["module.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert features["system.feature_flags"] == PROTECTED_INTERNAL_STATE


def test_default_profiles_have_complete_boolean_state() -> None:
    payload = default_profile("customer")

    assert "online_mr.collect_config_once" not in payload["features"]
    for feature_id, state in payload["features"].items():
        assert set(state) == {"visible", "enabled", "client_package", "internal_only"}, feature_id
        assert all(isinstance(value, bool) for value in state.values()), feature_id
    assert payload["features"]["module.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert payload["features"]["rail.online_mr_collection"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["online_mr.advanced_ping"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["online_mr.iperf_test"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["mesh.generate_report"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}


def test_customer_effective_state_cascades_parent_flags(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "customer",
        "customer",
        {
            "module.rail_transit": {"visible": False, "enabled": False, "client_package": False, "internal_only": False},
            "rail.online_mr_collection": {"visible": True, "enabled": True, "client_package": True, "internal_only": False},
            "online_mr.advanced_ping": {"visible": True, "enabled": True, "client_package": True, "internal_only": False},
        },
    )

    gate = FeatureGate(tmp_path)

    assert not gate.is_visible("rail.online_mr_collection")
    assert not gate.is_enabled("rail.online_mr_collection")
    assert not gate.is_in_client_package("rail.online_mr_collection")
    assert not gate.is_visible("online_mr.advanced_ping")
    assert not gate.is_enabled("online_mr.advanced_ping")
    assert not gate.is_in_client_package("online_mr.advanced_ping")


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
        embedded_flags = json.loads(archive.read("_internal/netconsole/assets/runtime/feature_flags.json").decode("utf-8"))
        embedded_full_flags = json.loads(archive.read("_internal/netconsole/assets/runtime/feature_flags.full.json").decode("utf-8"))

    assert "NetConsole.exe" in names
    assert "runtime/feature_flags.json" in names
    assert "_internal/netconsole/assets/runtime/build_info.json" in names
    assert "_internal/netconsole/assets/runtime/feature_flags.json" in names
    assert "_internal/netconsole/assets/runtime/feature_flags.full.json" in names
    assert all(not name.startswith(("docs/", "tests/", "project/")) for name in names)
    assert flags["features"]["module.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert flags["features"]["system.feature_flags"] == PROTECTED_INTERNAL_STATE
    assert embedded_flags["features"]["module.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert embedded_flags["features"]["system.feature_flags"] == PROTECTED_INTERNAL_STATE
    assert embedded_full_flags["features"]["module.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert embedded_full_flags["features"]["system.feature_flags"] == PROTECTED_INTERNAL_STATE
