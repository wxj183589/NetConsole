from __future__ import annotations

from types import SimpleNamespace

import pytest

from netconsole.backend.api.edition_access import (
    EditionUnlockNotAvailableError,
    ensure_edition_gate,
    lock_customer_edition,
    unlock_customer_edition,
)
from netconsole.core.feature_flags import FeatureGate, default_profile, install_embedded_feature_files


def _app_with_gate(tmp_path, *, edition: str):
    profile = edition if edition == "customer" else "full"
    install_embedded_feature_files(
        tmp_path,
        build_info={
            "edition": edition,
            "feature_profile": profile,
            "admin_unlock_enabled": False,
        },
        feature_flags=default_profile(profile),
        session_full_flags=default_profile("full"),
    )
    gate = FeatureGate(
        root=tmp_path,
        allow_local_override=False,
        packaged_runtime=True,
        runtime_path=tmp_path / "runtime",
    )
    settings_service = SimpleNamespace(feature_gate=gate)
    return SimpleNamespace(
        state=SimpleNamespace(
            feature_gate=gate,
            settings_application_service=settings_service,
        )
    )


def test_full_edition_activates_embedded_full_profile_and_syncs_services(tmp_path) -> None:
    app = _app_with_gate(tmp_path, edition="full")

    gate = ensure_edition_gate(app)

    assert gate.edition == "full"
    assert gate.profile == "full"
    assert gate.packaged_policy.active is False
    assert app.state.feature_gate is gate
    assert app.state.settings_application_service.feature_gate is gate


@pytest.mark.parametrize("operation", ["unlock", "lock"])
def test_customer_runtime_switch_is_retired_and_does_not_replace_gate(tmp_path, operation) -> None:
    app = _app_with_gate(tmp_path, edition="customer")
    original = app.state.feature_gate

    with pytest.raises(EditionUnlockNotAvailableError, match="Customer 版本交付机制已退役"):
        if operation == "unlock":
            unlock_customer_edition(app, "legacy-password")
        else:
            lock_customer_edition(app)

    assert app.state.feature_gate is original
    assert app.state.settings_application_service.feature_gate is original
