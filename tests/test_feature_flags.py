from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core import atomic_file
from netconsole.core.feature_flags import (
    PACKAGED_CORE_FEATURE_IDS,
    PACKAGED_FULL_ONLY_FEATURE_IDS,
    PACKAGED_FULL_REQUIRED_FEATURE_IDS,
    PACKAGED_PRODUCTION_FEATURE_IDS,
    FeatureDisabledError,
    FeatureGate,
    auto_fix_feature_dependencies,
    default_profile,
    engineer_package_enabled,
    feature_dependency_issues,
    install_runtime_feature_files,
    load_profile,
    normalize_feature_state,
    save_profile,
    validate_feature_profile_payload,
    validate_feature_states,
)
from netconsole.core.feature_registry import (
    FEATURE_BY_ID,
    REMOVED_FEATURE_IDS,
    FeatureStatus,
    delivery_dependencies_of,
    dependencies_of,
    list_features,
)
from scripts.build.build_release import EDITION_STAGING_ALLOWED_ITEMS, validate_embedded_feature_gate, validate_zip_file, zip_directory


PROTECTED_INTERNAL_STATE = {"visible": True, "enabled": True, "client_package": False, "internal_only": True}
PROTECTED_INTERNAL_DISABLED_STATE = {"visible": False, "enabled": False, "client_package": False, "internal_only": True}
FORMALIZED_PRODUCTION_FEATURE_IDS = (
    "capability.devices.connection_test",
    "capability.devices.write",
    "capability.devices.collect",
    "capability.devices.import",
    "capability.devices.export",
    "capability.devices.desktop_actions",
    "capability.file_management.remote",
    "capability.file_management.desktop_actions",
    "capability.online_mr.report_export",
    "capability.online_mr.parse",
    "capability.mesh.import",
    "capability.mesh.report_export",
    "capability.rail_transit.task_control",
    "module.train_online",
    "capability.train_online.refresh",
    "capability.train_online.collect",
    "capability.train_online.history_export",
    "capability.train_online.mapping_write",
    "capability.train_online.mapping_import",
    "capability.train_online.mapping_export",
    "capability.trackside_ap.export",
    "capability.trackside_ap.plan",
    "capability.trackside_ap.plan_write",
    "capability.trackside_ap.plan_export",
    "capability.trackside_ap.wps_sync",
    "module.online_mr_analysis",
    "capability.rail_base_data.write",
)


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
    features = list_features()
    feature_ids = {item.feature_id for item in features}

    assert len(features) == len(FEATURE_BY_ID)
    assert len(feature_ids) == len(FEATURE_BY_ID)
    assert all(not feature_id.startswith("web.") for feature_id in feature_ids)
    assert "module.rail_transit" in feature_ids
    assert "module.system_settings" in feature_ids
    assert "internal.feature_switch" in feature_ids
    assert "module.tools" in feature_ids
    assert "rail.online_mr_collection" in feature_ids
    assert FEATURE_BY_ID["network_tools.traffic"].parent_id == "module.network_tools"
    assert "online_mr.collect_config_once" not in feature_ids
    assert FEATURE_BY_ID["online_mr.agent_packages"].parent_id == "rail.online_mr_collection"
    assert FEATURE_BY_ID["module.online_mr"].parent_id == "rail.online_mr_collection"
    assert FEATURE_BY_ID["module.task_center"].item_type == "module"
    assert FEATURE_BY_ID["module.devices"].parent_id is None
    assert "devices.omnipeek_name_table_export" not in feature_ids
    assert FEATURE_BY_ID["ac.omnipeek_name_table_export"].parent_id == "module.ac"
    assert FEATURE_BY_ID["module.config_collection"].parent_id is None
    assert FEATURE_BY_ID["module.file_management"].parent_id is None
    assert FEATURE_BY_ID["module.network_tools"].parent_id is None
    assert FEATURE_BY_ID["capability.trackside_ap.plan"].parent_id == "module.rail_base_data"
    assert FEATURE_BY_ID["capability.trackside_ap.plan"].item_type == "tab"
    trackside_business = FEATURE_BY_ID["module.trackside_ap"]
    assert trackside_business.parent_id == "module.rail_transit"
    assert trackside_business.status is FeatureStatus.ENABLED
    assert trackside_business.default_client_package is True
    trackside_update = FEATURE_BY_ID["capability.trackside_ap.update"]
    assert trackside_update.parent_id == "module.trackside_ap"
    assert trackside_update.status is FeatureStatus.ENABLED
    assert trackside_update.default_visible is True
    assert trackside_update.default_enabled is True
    assert trackside_update.default_client_package is True
    wps_sync = FEATURE_BY_ID["capability.trackside_ap.wps_sync"]
    assert wps_sync.parent_id == "module.trackside_ap"
    assert wps_sync.status is FeatureStatus.ENABLED
    assert wps_sync.default_visible is True
    assert wps_sync.default_enabled is True
    assert wps_sync.default_client_package is True
    assert dependencies_of(wps_sync.feature_id) == ("internal.rail_task_control",)
    assert delivery_dependencies_of(wps_sync.feature_id) == (
        "internal.rail_task_control",
    )
    assert wps_sync.feature_id in PACKAGED_FULL_ONLY_FEATURE_IDS
    assert wps_sync.feature_id in PACKAGED_FULL_REQUIRED_FEATURE_IDS
    assert wps_sync.feature_id not in PACKAGED_PRODUCTION_FEATURE_IDS
    assert FEATURE_BY_ID["ac.mesh_link.refresh"].parent_id == "module.train_online"
    assert FEATURE_BY_ID["capability.devices.connection_test"].parent_id == "module.devices"
    form_test = FEATURE_BY_ID["capability.devices.form_connection_test"]
    assert form_test.parent_id == "module.devices"
    assert form_test.status is FeatureStatus.ENABLED
    assert form_test.default_enabled is True
    assert form_test.default_client_package is True
    for feature_id in (
        "capability.devices.write",
        "capability.devices.collect",
        "capability.devices.import",
        "capability.devices.export",
    ):
        feature = FEATURE_BY_ID[feature_id]
        assert feature.parent_id == "module.devices"
        assert feature.status is FeatureStatus.ENABLED
        assert feature.default_visible is True
        assert feature.default_enabled is True
        assert feature.default_client_package is True
    desktop_feature = FEATURE_BY_ID["capability.devices.desktop_actions"]
    assert desktop_feature.parent_id == "module.devices"
    assert desktop_feature.status is FeatureStatus.ENABLED
    assert desktop_feature.default_visible is True
    assert desktop_feature.default_enabled is True
    assert desktop_feature.default_client_package is True
    assert FEATURE_BY_ID["capability.config_collection.download"].parent_id == "module.config_collection"
    for feature_id in (
        "capability.config_collection.delete",
        "capability.config_collection.save_force",
        "capability.config_collection.export",
        "capability.config_collection.open_directory",
    ):
        feature = FEATURE_BY_ID[feature_id]
        assert feature.parent_id == "module.config_collection"
        assert feature.status is FeatureStatus.ENABLED
        assert feature.default_visible is True
        assert feature.default_enabled is True
        assert feature.default_client_package is True
    assert FEATURE_BY_ID["capability.file_management.download"].parent_id == "module.file_management"
    assert FEATURE_BY_ID["capability.network_tools.tcp_port_test"].parent_id == "capability.network_tools.toolbox"
    wireless_scan = FEATURE_BY_ID["capability.network_tools.wireless_scan"]
    assert wireless_scan.parent_id == "module.network_tools"
    assert wireless_scan.default_visible is True
    assert wireless_scan.default_enabled is True
    assert wireless_scan.default_client_package is True
    assert FEATURE_BY_ID["internal.feature_switch"].internal_only is True
    assert all(
        FEATURE_BY_ID[feature_id].status is FeatureStatus.ENABLED
        for feature_id in FORMALIZED_PRODUCTION_FEATURE_IDS
    )


def test_feature_gate_full_profile_defaults_visible(tmp_path: Path) -> None:
    write_runtime(tmp_path, "internal", "full", {})

    gate = FeatureGate(tmp_path)

    assert all(
        gate.is_visible(item.feature_id)
        for item in list_features()
        if item.status is FeatureStatus.ENABLED and item.item_type != "capability"
    )
    assert all(
        gate.is_enabled(item.feature_id) and not gate.is_visible(item.feature_id)
        for item in list_features()
        if item.item_type == "capability"
    )
    assert gate.is_visible("internal.feature_switch")
    assert not gate.is_visible("module.snmp_center")
    assert not gate.is_visible("module.wifi_survey")


def test_removed_modules_are_ignored_by_profile(tmp_path: Path) -> None:
    forced_on = {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    write_runtime(
        tmp_path,
        "internal",
        "full",
        {"module.snmp_center": forced_on, "module.wifi_survey": forced_on},
    )

    gate = FeatureGate(tmp_path)

    for feature_id in REMOVED_FEATURE_IDS:
        assert not gate.is_visible(feature_id)
        assert not gate.is_enabled(feature_id)
        assert feature_id not in gate.features
        with pytest.raises(KeyError):
            gate.status_for(feature_id)


def test_packaged_runtime_never_exposes_feature_switch_page(tmp_path: Path, monkeypatch) -> None:
    from netconsole.core import feature_flags

    write_runtime(tmp_path, "engineer", "full", {})
    monkeypatch.setattr(feature_flags, "is_packaged_runtime", lambda: True)

    gate = FeatureGate(tmp_path)

    assert not gate.is_visible("internal.feature_switch")
    assert not gate.is_enabled("internal.feature_switch")
    assert not gate.is_in_client_package("internal.feature_switch")


def test_engineer_package_option_persists_in_customer_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "customer.json"

    save_profile(profile_path, "customer", {}, build_options={"engineer_package": True})

    assert engineer_package_enabled(profile_path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    assert payload["build_options"] == {"engineer_package": True}


def test_customer_profile_atomic_replace_failure_preserves_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path = tmp_path / "customer.json"
    save_profile(profile_path, "customer", {}, build_options={"engineer_package": True})
    original = profile_path.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(atomic_file.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_profile(profile_path, "customer", {}, build_options={"engineer_package": False})

    assert profile_path.read_bytes() == original
    assert engineer_package_enabled(profile_path)
    assert list(tmp_path.glob(".customer.json.*.tmp")) == []


def test_feature_gate_customer_profile_hides_config_and_disabled_feature(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "customer",
        "customer",
        {
            "rail.online_mr_collection": {"visible": False, "enabled": False},
            "internal.feature_switch": {"visible": True, "enabled": True},
        },
    )

    gate = FeatureGate(tmp_path)

    assert not gate.is_visible("rail.online_mr_collection")
    assert not gate.is_enabled("rail.online_mr_collection")
    assert not gate.is_visible("internal.feature_switch")
    with pytest.raises(FeatureDisabledError):
        gate.assert_enabled("rail.online_mr_collection")


def test_trackside_ap_business_legacy_runtime_state_is_upgraded(tmp_path: Path, monkeypatch) -> None:
    from netconsole.core import feature_flags

    write_runtime(
        tmp_path,
        "customer",
        "customer",
        {
            "module.rail_transit": {"visible": True, "enabled": True, "client_package": True, "internal_only": False},
            "module.trackside_ap": {"visible": False, "enabled": False, "client_package": False, "internal_only": False},
            "capability.trackside_ap.update": {"visible": False, "enabled": False, "client_package": False, "internal_only": False},
        },
    )
    monkeypatch.setattr(feature_flags, "is_packaged_runtime", lambda: True)

    gate = FeatureGate(tmp_path)

    assert gate.is_visible("module.trackside_ap")
    assert gate.is_enabled("module.trackside_ap")
    assert gate.is_in_client_package("module.trackside_ap")
    assert gate.is_visible("capability.trackside_ap.update")
    assert gate.is_enabled("capability.trackside_ap.update")
    assert gate.is_in_client_package("capability.trackside_ap.update")


def test_internal_profile_cannot_hide_feature_switch_entry(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "internal",
        "full",
        {
            "internal.feature_switch": {"visible": False, "enabled": False},
        },
    )

    gate = FeatureGate(tmp_path)

    assert gate.is_visible("internal.feature_switch")
    assert gate.is_enabled("internal.feature_switch")


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
    assert customer_flags["features"]["internal.feature_switch"] == PROTECTED_INTERNAL_DISABLED_STATE
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
    assert not gate.is_visible("internal.feature_switch")


def test_customer_admin_unlock_requires_configured_hash(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")

    gate = FeatureGate(tmp_path)

    assert gate.is_admin_unlock_configured() is False
    assert gate.verify_admin_unlock_password("temporary-secret") is False
    assert not gate.is_visible("internal.feature_switch")


def test_customer_session_full_mode_is_process_only(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer", admin_unlock_password="temporary-secret")
    runtime_info_before = (tmp_path / "runtime" / "build_info.json").read_text(encoding="utf-8")
    embedded_info_before = (tmp_path / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json").read_text(encoding="utf-8")

    gate = FeatureGate(tmp_path)

    assert gate.edition == "customer"
    assert gate.profile == "customer"
    assert not gate.is_visible("internal.feature_switch")
    assert gate.verify_admin_unlock_password("wrong") is False
    assert gate.verify_admin_unlock_password("temporary-secret") is True

    gate.enable_session_full_mode(reason="test", operator="tester")

    assert gate.edition == "customer"
    assert gate.profile == "full"
    assert gate.base_profile == "customer"
    assert gate.is_session_override_active()
    assert gate.current_profile_source() == "embedded+session_override"
    assert gate.is_visible("internal.feature_switch")
    assert gate.is_enabled("internal.feature_switch")
    assert not (tmp_path / "runtime" / "feature_flags.local.json").exists()
    assert (tmp_path / "runtime" / "build_info.json").read_text(encoding="utf-8") == runtime_info_before
    assert (tmp_path / "_internal" / "netconsole" / "assets" / "runtime" / "build_info.json").read_text(encoding="utf-8") == embedded_info_before

    gate.disable_session_override(reason="test")

    assert not gate.is_session_override_active()
    assert gate.profile == "customer"
    assert not gate.is_visible("internal.feature_switch")

    restarted = FeatureGate(tmp_path)
    assert restarted.profile == "customer"
    assert not restarted.is_session_override_active()
    assert not restarted.is_visible("internal.feature_switch")


def test_customer_local_override_cannot_enable_internal_only(tmp_path: Path) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")
    local = tmp_path / "runtime" / "feature_flags.local.json"
    local.write_text(
        json.dumps(
            {
                "profile": "full",
                "features": {
                    "internal.feature_switch": {"visible": True, "enabled": True},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    gate = FeatureGate(tmp_path, allow_local_override=True)

    assert gate.allow_local_override is False
    assert not gate.is_visible("internal.feature_switch")
    assert not gate.is_enabled("internal.feature_switch")


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
                        "internal.feature_switch": {"visible": True, "enabled": True},
                    },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    features = load_profile(profile_path, "customer")

    assert features["module.network_tools"] == {"visible": False, "enabled": False, "client_package": True, "internal_only": False}
    assert features["module.system_settings"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert features["internal.feature_switch"] == PROTECTED_INTERNAL_STATE


def test_default_profiles_have_complete_boolean_state() -> None:
    payload = default_profile("customer")

    assert "online_mr.collect_config_once" not in payload["features"]
    for feature_id, state in payload["features"].items():
        assert set(state) == {"visible", "enabled", "client_package", "internal_only"}, feature_id
        assert all(isinstance(value, bool) for value in state.values()), feature_id
    assert payload["features"]["internal.feature_switch"] == PROTECTED_INTERNAL_STATE
    assert payload["features"]["rail.online_mr_collection"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["module.trackside_ap"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["capability.trackside_ap.update"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["online_mr.advanced_ping"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["online_mr.iperf_test"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert payload["features"]["mesh.generate_report"] == {"visible": True, "enabled": True, "client_package": True, "internal_only": False}
    assert all(
        payload["features"][feature_id]["visible"]
        and payload["features"][feature_id]["enabled"]
        for feature_id in PACKAGED_PRODUCTION_FEATURE_IDS
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@pytest.mark.parametrize("profile_name", ("customer", "full"))
def test_v2_profiles_are_complete_and_have_unique_feature_ids(profile_name: str) -> None:
    profile_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "profiles"
        / "features"
        / f"{profile_name}.json"
    )
    payload = json.loads(
        profile_path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )

    assert payload["schema_version"] == 2
    assert payload["profile"] == profile_name
    assert set(payload["features"]) == set(FEATURE_BY_ID)
    assert not any(feature_id.startswith("web.") for feature_id in payload["features"])


def test_v2_device_connection_capabilities_preserve_customer_scope() -> None:
    customer = json.loads(
        (Path(__file__).resolve().parents[1] / "config/profiles/features/customer.json").read_text(
            encoding="utf-8"
        )
    )["features"]
    full = json.loads(
        (Path(__file__).resolve().parents[1] / "config/profiles/features/full.json").read_text(
            encoding="utf-8"
        )
    )["features"]

    assert customer["capability.devices.connection_test"]["enabled"] is True
    assert customer["capability.devices.form_connection_test"]["enabled"] is True
    assert full["capability.devices.connection_test"]["enabled"] is True
    assert full["capability.devices.form_connection_test"]["enabled"] is True


def test_customer_parent_is_presentation_hierarchy_not_runtime_dependency(tmp_path: Path) -> None:
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

    assert gate.is_visible("rail.online_mr_collection")
    assert gate.is_enabled("rail.online_mr_collection")
    assert gate.is_in_client_package("rail.online_mr_collection")
    assert gate.is_visible("online_mr.advanced_ping")
    assert gate.is_enabled("online_mr.advanced_ping")
    assert gate.is_in_client_package("online_mr.advanced_ping")


def test_hidden_runtime_entry_stays_enabled_and_keeps_release_metadata(tmp_path: Path) -> None:
    state = normalize_feature_state(
        FEATURE_BY_ID["module.devices"],
        {
            "visible": False,
            "enabled": True,
            "client_package": True,
            "internal_only": False,
        },
    )

    assert state == {
        "visible": False,
        "enabled": True,
        "client_package": True,
        "internal_only": False,
    }
    features = default_profile("full")["features"]
    features["module.devices"] = state
    assert validate_feature_states(features) == ""


def test_disabled_dependency_makes_dependent_feature_unavailable(tmp_path: Path) -> None:
    write_runtime(
        tmp_path,
        "internal",
        "full",
        {
            "internal.task_center": {
                "visible": False,
                "enabled": False,
                "client_package": True,
                "internal_only": False,
            },
            "module.agent": {
                "visible": True,
                "enabled": True,
                "client_package": True,
                "internal_only": False,
            },
        },
    )

    gate = FeatureGate(tmp_path)

    assert not gate.is_enabled("module.agent")
    assert not gate.is_visible("module.agent")


def test_customer_zip_keeps_allowlist_and_hidden_feature_config(tmp_path: Path) -> None:
    app_dir = tmp_path / "customer"
    (app_dir / "_internal").mkdir(parents=True)
    (app_dir / "runtime" / "logs").mkdir(parents=True)
    (app_dir / "NetConsoleBackend.exe").write_text("", encoding="utf-8")
    install_runtime_feature_files(app_dir, edition="customer", profile="customer")
    zip_path = tmp_path / "NetConsole_customer.zip"

    zip_directory(app_dir, zip_path, app_dir, EDITION_STAGING_ALLOWED_ITEMS)
    validate_zip_file(zip_path)

    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        flags = json.loads(archive.read("runtime/feature_flags.json").decode("utf-8"))
        embedded_flags = json.loads(archive.read("_internal/netconsole/assets/runtime/feature_flags.json").decode("utf-8"))
        embedded_full_flags = json.loads(archive.read("_internal/netconsole/assets/runtime/feature_flags.full.json").decode("utf-8"))

    assert "NetConsoleBackend.exe" in names
    assert "runtime/feature_flags.json" in names
    assert "_internal/netconsole/assets/runtime/build_info.json" in names
    assert "_internal/netconsole/assets/runtime/feature_flags.json" in names
    assert "_internal/netconsole/assets/runtime/feature_flags.full.json" in names
    assert all(not name.startswith(("docs/", "tests/", "project/")) for name in names)
    assert flags["features"]["internal.feature_switch"] == PROTECTED_INTERNAL_DISABLED_STATE
    assert embedded_flags["features"]["internal.feature_switch"] == PROTECTED_INTERNAL_DISABLED_STATE
    assert embedded_full_flags["features"]["internal.feature_switch"] == PROTECTED_INTERNAL_STATE


def test_packaged_runtime_ignores_external_overrides_and_protects_core_features(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")
    (tmp_path / "runtime" / "feature_flags.local.json").write_text(
        json.dumps(
            {
                "features": {
                    "module.system_settings": {"visible": False, "enabled": False}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NETCONSOLE_EDITION", "internal")
    monkeypatch.setenv("NETCONSOLE_FEATURE_PROFILE", "full")

    gate = FeatureGate(tmp_path, packaged_runtime=True, allow_local_override=True)

    assert gate.resolution.source == "embedded"
    assert gate.allow_local_override is False
    for feature_id in PACKAGED_CORE_FEATURE_IDS:
        assert gate.is_visible(feature_id), feature_id
        assert gate.is_enabled(feature_id), feature_id
    assert not gate.is_visible("online_mr.iperf_test")
    assert not gate.is_enabled("online_mr.iperf_test")
    assert not gate.is_visible("internal.feature_switch")


def test_packaged_runtime_does_not_use_client_package_as_runtime_denial(
    tmp_path: Path,
) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="production")
    baseline = (
        tmp_path
        / "_internal"
        / "netconsole"
        / "assets"
        / "runtime"
        / "feature_flags.json"
    )
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["features"]["capability.devices.collect"]["client_package"] = False
    payload["features"]["capability.online_mr.local_control"].update(
        visible=True,
        enabled=True,
        client_package=True,
    )
    baseline.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    gate = FeatureGate(tmp_path, packaged_runtime=True)

    assert gate.is_visible("capability.devices.collect")
    assert gate.is_enabled("capability.devices.collect")
    assert not gate.is_in_client_package("capability.devices.collect")
    assert not gate.is_visible("capability.online_mr.local_control")
    assert not gate.is_enabled("capability.online_mr.local_control")


@pytest.mark.parametrize("baseline_state", ["missing", "invalid"])
def test_packaged_runtime_falls_back_to_registry_when_baseline_unavailable(
    tmp_path: Path, baseline_state: str
) -> None:
    install_runtime_feature_files(tmp_path, edition="customer", profile="customer")
    baseline = (
        tmp_path
        / "_internal"
        / "netconsole"
        / "assets"
        / "runtime"
        / "feature_flags.json"
    )
    if baseline_state == "missing":
        baseline.unlink()
    else:
        baseline.write_text("{broken", encoding="utf-8")

    gate = FeatureGate(tmp_path, packaged_runtime=True)

    assert gate.resolution.embedded_flags_status == baseline_state
    for feature_id in PACKAGED_PRODUCTION_FEATURE_IDS:
        assert gate.is_visible(feature_id)
        assert gate.is_enabled(feature_id)
    assert not gate.is_visible("capability.trackside_ap.wps_sync")
    assert not gate.is_enabled("capability.trackside_ap.wps_sync")
    assert not gate.is_in_client_package("capability.trackside_ap.wps_sync")
    assert not gate.is_visible("internal.feature_switch")


def test_packaged_runtime_missing_build_info_uses_production_identity(
    tmp_path: Path,
) -> None:
    gate = FeatureGate(tmp_path, packaged_runtime=True)

    assert gate.build_info == {"edition": "customer", "feature_profile": "production"}
    assert gate.resolution.source == "packaged_registry_fallback"
    assert gate.is_visible("module.system_settings")
    assert gate.is_visible("module.task_center")


def test_registry_separates_parent_runtime_and_delivery_dependencies() -> None:
    assert FEATURE_BY_ID["ac.mesh_link.refresh"].parent_id == "module.train_online"
    assert dependencies_of("ac.mesh_link.refresh") == ("internal.train_online_data",)
    assert delivery_dependencies_of("ac.mesh_link.refresh") == (
        "internal.train_online_data",
    )


def test_customer_dependency_check_and_auto_fix_use_hidden_delivery_capabilities() -> None:
    features = default_profile("customer")["features"]
    features["module.train_online"].update(
        visible=False,
        enabled=False,
        client_package=False,
    )
    features["ac.mesh_link.refresh"].update(
        visible=True,
        enabled=True,
        client_package=True,
    )

    issues = feature_dependency_issues(features, target="customer")

    assert any(
        issue.feature_id == "ac.mesh_link.refresh"
        and issue.dependency_id == "module.train_online"
        and issue.issue_type == "delivery_parent_missing"
        for issue in issues
    )
    fixed = auto_fix_feature_dependencies(features, target="customer")
    assert fixed["module.train_online"] == {
        "visible": False,
        "enabled": True,
        "client_package": True,
        "internal_only": False,
    }
    assert feature_dependency_issues(fixed, target="customer") == []


def test_profile_preflight_rejects_missing_delivery_dependency_chain() -> None:
    payload = default_profile("customer")
    payload["features"]["internal.train_online_data"].update(
        visible=False,
        enabled=False,
        client_package=False,
    )

    errors = validate_feature_profile_payload(payload, profile="customer")

    assert any(
        "module.train_online" in error and "internal.train_online_data" in error
        for error in errors
    )
