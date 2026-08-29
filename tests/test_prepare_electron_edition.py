from __future__ import annotations

import json

import pytest

from netconsole.core.feature_flags import (
    CUSTOMER_UNLOCK_PASSWORD_DEFAULT,
    CUSTOMER_UNLOCK_PASSWORD_ENV,
    default_profile,
    resolve_customer_unlock_password,
    verify_admin_unlock_password,
)
from scripts.build import prepare_electron_edition as prepare_module
from scripts.build.prepare_electron_edition import (
    EditionPreparationError,
    prepare_electron_edition,
)


def _backend_root(tmp_path):
    root = tmp_path / "backend"
    root.mkdir()
    (root / "NetConsoleBackend.exe").write_bytes(b"test")
    return root


def _embedded_build_info(root):
    path = (
        root
        / "_internal"
        / "netconsole"
        / "assets"
        / "runtime"
        / "build_info.json"
    )
    return path, json.loads(path.read_text(encoding="utf-8"))


def _embedded_feature_flags(root):
    path = (
        root
        / "_internal"
        / "netconsole"
        / "assets"
        / "runtime"
        / "feature_flags.json"
    )
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_prepare_full_edition_has_no_customer_password_hash(tmp_path) -> None:
    root = _backend_root(tmp_path)

    result = prepare_electron_edition(root, edition="full")

    _, build_info = _embedded_build_info(root)
    assert result["edition"] == "full"
    assert result["feature_profile"] == "full"
    assert result["admin_unlock_configured"] is False
    assert build_info == {
        "edition": "full",
        "feature_profile": "full",
        "admin_unlock_enabled": False,
    }


@pytest.mark.parametrize("environment_value", (None, ""))
def test_customer_unlock_resolver_falls_back_to_builtin_default(
    monkeypatch, environment_value: str | None
) -> None:
    if environment_value is None:
        monkeypatch.delenv(CUSTOMER_UNLOCK_PASSWORD_ENV, raising=False)
    else:
        monkeypatch.setenv(CUSTOMER_UNLOCK_PASSWORD_ENV, environment_value)

    resolved = resolve_customer_unlock_password()

    assert resolved.value == CUSTOMER_UNLOCK_PASSWORD_DEFAULT
    assert resolved.source == "BUILTIN_DEFAULT"


def test_customer_unlock_resolver_prefers_non_empty_environment_override(monkeypatch) -> None:
    monkeypatch.setenv(CUSTOMER_UNLOCK_PASSWORD_ENV, "TestOverride123!")

    resolved = resolve_customer_unlock_password()

    assert resolved.value == "TestOverride123!"
    assert resolved.source == "ENVIRONMENT"


def test_prepare_customer_edition_uses_builtin_default_when_environment_is_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv(CUSTOMER_UNLOCK_PASSWORD_ENV, raising=False)
    root = _backend_root(tmp_path)

    prepare_electron_edition(root, edition="customer")

    path, build_info = _embedded_build_info(root)
    assert verify_admin_unlock_password(build_info, CUSTOMER_UNLOCK_PASSWORD_DEFAULT)
    assert CUSTOMER_UNLOCK_PASSWORD_DEFAULT not in path.read_text(encoding="utf-8")


def test_prepare_customer_edition_uses_environment_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(CUSTOMER_UNLOCK_PASSWORD_ENV, "TestOverride123!")
    root = _backend_root(tmp_path)

    prepare_electron_edition(root, edition="customer")

    _, build_info = _embedded_build_info(root)
    assert verify_admin_unlock_password(build_info, "TestOverride123!")
    assert verify_admin_unlock_password(build_info, CUSTOMER_UNLOCK_PASSWORD_DEFAULT) is False


def test_prepare_customer_edition_stores_only_verifiable_hash(tmp_path) -> None:
    root = _backend_root(tmp_path)
    password = "customer-maintenance-password"

    result = prepare_electron_edition(
        root,
        edition="customer",
        customer_password=password,
    )

    path, build_info = _embedded_build_info(root)
    serialized = path.read_text(encoding="utf-8")
    assert result["edition"] == "customer"
    assert result["feature_profile"] == "customer"
    assert result["admin_unlock_configured"] is True
    assert password not in serialized
    assert verify_admin_unlock_password(build_info, password) is True
    assert verify_admin_unlock_password(build_info, "wrong-password") is False


@pytest.mark.parametrize(
    ("edition", "password", "expected_enabled"),
    (
        ("full", None, True),
        ("customer", "customer-maintenance-password", False),
    ),
)
def test_prepared_edition_embeds_the_wps_full_only_delivery_contract(
    tmp_path,
    edition: str,
    password: str | None,
    expected_enabled: bool,
) -> None:
    root = _backend_root(tmp_path)

    prepare_electron_edition(
        root,
        edition=edition,
        customer_password=password,
    )

    _, feature_flags = _embedded_feature_flags(root)
    assert feature_flags["profile"] == edition
    assert feature_flags["features"]["capability.trackside_ap.wps_sync"] == {
        "visible": expected_enabled,
        "enabled": expected_enabled,
        "client_package": expected_enabled,
        "internal_only": False,
    }


def test_prepare_customer_edition_rejects_weak_password(tmp_path) -> None:
    root = _backend_root(tmp_path)

    with pytest.raises(EditionPreparationError, match="至少 8 位"):
        prepare_electron_edition(
            root,
            edition="customer",
            customer_password="short",
        )


def test_prepare_customer_edition_rejects_invalid_profile_before_packaging(
    tmp_path, monkeypatch
) -> None:
    root = _backend_root(tmp_path)
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    full = default_profile("full")
    customer = default_profile("customer")
    customer["features"]["internal.train_online_data"].update(
        visible=False,
        enabled=False,
        client_package=False,
    )
    (profile_dir / "full.json").write_text(
        json.dumps(full, ensure_ascii=False),
        encoding="utf-8",
    )
    (profile_dir / "customer.json").write_text(
        json.dumps(customer, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_module, "profiles_dir", lambda: profile_dir)

    with pytest.raises(
        EditionPreparationError,
        match="CUSTOMER PROFILE INVALID",
    ):
        prepare_electron_edition(
            root,
            edition="customer",
            customer_password="customer-maintenance-password",
        )
