from __future__ import annotations

import json

import pytest

from netconsole.core.feature_flags import verify_admin_unlock_password
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


def test_prepare_customer_edition_rejects_missing_or_weak_password(tmp_path) -> None:
    root = _backend_root(tmp_path)

    with pytest.raises(EditionPreparationError, match="至少 8 位"):
        prepare_electron_edition(
            root,
            edition="customer",
            customer_password="short",
        )
