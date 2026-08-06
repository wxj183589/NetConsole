from __future__ import annotations

from types import SimpleNamespace

import pytest

from netconsole.backend.api.edition_access import (
    EditionUnlockPasswordError,
    ensure_edition_gate,
    lock_customer_edition,
    unlock_customer_edition,
)
from netconsole.core.feature_flags import (
    FeatureGate,
    default_profile,
    hash_admin_unlock_password,
    install_embedded_feature_files,
)


def _app_with_gate(tmp_path, *, edition: str, password: str = ""):
    full_flags = default_profile("full")
    profile = "customer" if edition == "customer" else "full"
    build_info = {
        "edition": edition,
        "feature_profile": profile,
        "admin_unlock_enabled": False,
    }
    if password:
        build_info.update(hash_admin_unlock_password(password, salt="test-salt"))
    install_embedded_feature_files(
        tmp_path,
        build_info=build_info,
        feature_flags=default_profile(profile),
        session_full_flags=full_flags,
    )
    gate = FeatureGate(
        root=tmp_path,
        allow_local_override=False,
        packaged_runtime=True,
        runtime_path=tmp_path / "runtime",
    )
    settings_service = SimpleNamespace(feature_gate=gate)
    app = SimpleNamespace(
        state=SimpleNamespace(
            feature_gate=gate,
            settings_application_service=settings_service,
        )
    )
    return app


def test_full_edition_activates_embedded_full_profile_and_syncs_services(tmp_path) -> None:
    app = _app_with_gate(tmp_path, edition="full")

    gate = ensure_edition_gate(app)

    assert gate.edition == "full"
    assert gate.profile == "full"
    assert gate.packaged_policy.active is False
    assert app.state.feature_gate is gate
    assert app.state.settings_application_service.feature_gate is gate


def test_customer_unlock_is_session_only_and_relock_restores_packaged_gate(tmp_path) -> None:
    password = "customer-maintenance-password"
    app = _app_with_gate(tmp_path, edition="customer", password=password)

    unlocked = unlock_customer_edition(app, password)

    assert unlocked.edition == "customer"
    assert unlocked.base_profile == "customer"
    assert unlocked.profile == "full"
    assert unlocked.is_session_override_active() is True
    assert unlocked.packaged_policy.active is False
    assert app.state.settings_application_service.feature_gate is unlocked

    locked = lock_customer_edition(app)

    assert locked.edition == "customer"
    assert locked.profile == "customer"
    assert locked.is_session_override_active() is False
    assert locked.packaged_policy.active is True
    assert app.state.feature_gate is locked
    assert app.state.settings_application_service.feature_gate is locked


def test_customer_unlock_rejects_wrong_password_without_replacing_gate(tmp_path) -> None:
    app = _app_with_gate(
        tmp_path,
        edition="customer",
        password="customer-maintenance-password",
    )
    original = app.state.feature_gate

    with pytest.raises(EditionUnlockPasswordError, match="维护密码不正确"):
        unlock_customer_edition(app, "wrong-password")

    assert app.state.feature_gate is original
    assert app.state.settings_application_service.feature_gate is original
