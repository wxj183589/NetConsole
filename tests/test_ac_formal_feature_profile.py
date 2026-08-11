from __future__ import annotations

import json
from pathlib import Path

from netconsole.core.feature_flags import FeatureGate, install_runtime_feature_files
from netconsole.core.feature_registry import FEATURE_BY_ID, FeatureStatus


FORMAL_AC_FEATURES = (
    "capability.ac.dangerous_actions",
    "capability.ac.external_terminal",
    "ac.omnipeek_name_table_export",
    "capability.desktop_native_integration",
)


def _write_runtime(
    root: Path,
    *,
    schema_version: int,
    states: dict[str, bool],
    edition: str = "dev",
    profile: str = "full",
) -> None:
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "build_info.json").write_text(
        json.dumps({"edition": edition, "feature_profile": profile}),
        encoding="utf-8",
    )
    (runtime / "feature_flags.json").write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "profile": profile,
                "features": {
                    feature_id: {
                        "visible": state,
                        "enabled": state,
                        "client_package": state,
                        "internal_only": False,
                    }
                    for feature_id, state in states.items()
                },
            }
        ),
        encoding="utf-8",
    )


def test_ac_features_are_formal_customer_features() -> None:
    for feature_id in FORMAL_AC_FEATURES:
        feature = FEATURE_BY_ID[feature_id]
        assert feature.status is FeatureStatus.ENABLED
        assert feature.default_visible is True
        assert feature.default_enabled is True
        assert feature.default_client_package is True


def test_schema_one_ac_states_are_not_automatically_migrated(
    tmp_path: Path,
) -> None:
    feature_ids = ("capability.ac.dangerous_actions", "capability.ac.external_terminal")
    _write_runtime(
        tmp_path,
        schema_version=1,
        states={feature_id: False for feature_id in feature_ids},
    )

    gate = FeatureGate(tmp_path, packaged_runtime=False)

    for feature_id in feature_ids:
        assert not gate.is_visible(feature_id)
        assert not gate.is_enabled(feature_id)
        assert not gate.is_in_client_package(feature_id)


def test_packaged_runtime_ignores_external_schema_two_disable(tmp_path: Path) -> None:
    feature_id = "capability.ac.external_terminal"
    install_runtime_feature_files(tmp_path, edition="customer", profile="production")
    _write_runtime(
        tmp_path,
        schema_version=2,
        states={feature_id: False},
        edition="internal",
        profile="full",
    )

    gate = FeatureGate(tmp_path, packaged_runtime=True)

    assert gate.resolution.source == "embedded"
    assert gate.is_visible(feature_id)
    assert gate.is_enabled(feature_id)
    assert gate.is_in_client_package(feature_id)


def test_development_runtime_honors_external_schema_two_disable(
    tmp_path: Path,
) -> None:
    feature_id = "capability.ac.external_terminal"
    _write_runtime(tmp_path, schema_version=2, states={feature_id: False})

    gate = FeatureGate(tmp_path, packaged_runtime=False)

    assert gate.resolution.source == "external_runtime"
    assert gate.is_visible(feature_id) is False
    assert gate.is_enabled(feature_id) is False
    assert gate.is_in_client_package(feature_id) is False


def test_external_schema_cannot_enable_development_feature_in_packaged_runtime(
    tmp_path: Path,
) -> None:
    feature_id = "capability.ac.extensions"
    install_runtime_feature_files(tmp_path, edition="customer", profile="production")
    _write_runtime(
        tmp_path,
        schema_version=2,
        states={feature_id: True},
        edition="internal",
        profile="full",
    )

    gate = FeatureGate(tmp_path, packaged_runtime=True)

    assert FEATURE_BY_ID[feature_id].status is FeatureStatus.DEVELOPMENT
    assert gate.is_visible(feature_id) is False
    assert gate.is_enabled(feature_id) is False
    assert gate.is_in_client_package(feature_id) is False
