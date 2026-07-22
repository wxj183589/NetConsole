from __future__ import annotations

import json
from pathlib import Path

from netconsole.core import feature_flags
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.feature_registry import FEATURE_BY_ID, FeatureStatus


FORMAL_AC_FEATURES = (
    "web.ac_dangerous_actions",
    "web.ac_fit_ap_external_terminal",
    "ac.omnipeek_name_table_export",
    "desktop.native_bridge",
)


def _write_runtime(root: Path, *, schema_version: int, disabled: tuple[str, ...]) -> None:
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "build_info.json").write_text(
        json.dumps({"edition": "customer", "feature_profile": "customer"}),
        encoding="utf-8",
    )
    (runtime / "feature_flags.json").write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "profile": "customer",
                "features": {
                    feature_id: {
                        "visible": False,
                        "enabled": False,
                        "client_package": False,
                        "internal_only": False,
                    }
                    for feature_id in disabled
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


def test_schema_one_stale_ac_defaults_are_migrated_on_first_start(tmp_path: Path, monkeypatch) -> None:
    migrated = ("web.ac_dangerous_actions", "web.ac_fit_ap_external_terminal")
    _write_runtime(tmp_path, schema_version=1, disabled=migrated)
    monkeypatch.setattr(feature_flags, "is_packaged_runtime", lambda: True)

    gate = FeatureGate(tmp_path)

    for feature_id in migrated:
        assert gate.is_visible(feature_id)
        assert gate.is_enabled(feature_id)
        assert gate.is_in_client_package(feature_id)


def test_schema_two_explicit_user_disable_is_preserved(tmp_path: Path, monkeypatch) -> None:
    feature_id = "web.ac_fit_ap_external_terminal"
    _write_runtime(tmp_path, schema_version=2, disabled=(feature_id,))
    monkeypatch.setattr(feature_flags, "is_packaged_runtime", lambda: True)

    gate = FeatureGate(tmp_path)

    assert gate.is_visible(feature_id) is False
    assert gate.is_enabled(feature_id) is False
    assert gate.is_in_client_package(feature_id) is False
