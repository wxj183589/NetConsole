from __future__ import annotations

import time
from threading import RLock
from typing import Any

from netconsole.core import app_logger
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.runtime_environment import is_packaged_runtime

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
_LOCK_ATTRIBUTE = "_edition_access_lock"
_FAILED_ATTRIBUTE = "_edition_unlock_failed_attempts"
_LOCKED_UNTIL_ATTRIBUTE = "_edition_unlock_locked_until"


class EditionAccessError(RuntimeError):
    pass


class EditionUnlockNotAvailableError(EditionAccessError):
    pass


class EditionUnlockPasswordError(EditionAccessError):
    pass


class EditionUnlockThrottledError(EditionAccessError):
    pass


def ensure_edition_gate(app: Any) -> FeatureGate:
    """Activate the embedded full profile for a packaged Full edition.

    Packaged customer policy remains sealed until a password-authenticated session
    explicitly replaces it. The replacement still reads only embedded profiles and
    never enables local feature override files.
    """

    with _lock_for(app):
        gate = _require_gate(app)
        if gate.edition != "full" or not gate.packaged_policy.active:
            return gate
        replacement = _new_session_gate(gate)
        _replace_gate(app, replacement)
        app_logger.log_info(
            "FULL_EDITION_FEATURE_GATE_ACTIVATED",
            (
                f"edition={replacement.edition} profile={replacement.profile} "
                f"source={replacement.current_profile_source()}"
            ),
        )
        return replacement


def unlock_customer_edition(
    app: Any,
    password: str,
    *,
    operator: str = "desktop",
) -> FeatureGate:
    with _lock_for(app):
        gate = _require_gate(app)
        if gate.edition != "customer" or not gate.is_admin_unlock_configured():
            raise EditionUnlockNotAvailableError("当前版本未配置完整功能解锁")
        if gate.is_session_override_active():
            return gate

        locked_until = float(getattr(app.state, _LOCKED_UNTIL_ATTRIBUTE, 0.0) or 0.0)
        now = time.monotonic()
        if locked_until > now:
            raise EditionUnlockThrottledError("密码错误次数过多，请稍后重试")
        if not password or not gate.verify_admin_unlock_password(password):
            _record_failed_attempt(app, now)
            raise EditionUnlockPasswordError("维护密码不正确")

        replacement = _new_session_gate(gate)
        replacement.enable_session_full_mode(
            reason="customer_edition_admin_unlock",
            operator=operator,
        )
        _replace_gate(app, replacement)
        _clear_failed_attempts(app)
        app_logger.log_info(
            "CUSTOMER_EDITION_FULL_MODE_ENABLED",
            (
                f"edition={replacement.edition} base_profile={replacement.base_profile} "
                f"active_profile={replacement.profile} operator={operator}"
            ),
        )
        return replacement


def lock_customer_edition(app: Any) -> FeatureGate:
    with _lock_for(app):
        gate = _require_gate(app)
        if gate.edition != "customer":
            raise EditionUnlockNotAvailableError("当前版本不是客户版")
        replacement = FeatureGate(
            root=gate.root,
            allow_local_override=False,
            packaged_runtime=True,
            runtime_path=gate.runtime_path,
        )
        _replace_gate(app, replacement)
        _clear_failed_attempts(app)
        app_logger.log_info(
            "CUSTOMER_EDITION_FULL_MODE_DISABLED",
            (
                f"edition={replacement.edition} profile={replacement.profile} "
                f"source={replacement.current_profile_source()}"
            ),
        )
        return replacement


def edition_runtime_status(app: Any) -> dict[str, Any]:
    gate = ensure_edition_gate(app)
    full_features_active = gate.edition == "full" or gate.is_session_override_active()
    return {
        "edition": gate.edition,
        "base_profile": gate.base_profile,
        "active_profile": gate.profile,
        "full_features_active": full_features_active,
        "admin_unlock_available": (
            gate.edition == "customer" and gate.is_admin_unlock_configured()
        ),
        "relock_available": (
            gate.edition == "customer" and gate.is_session_override_active()
        ),
        "packaged_runtime": is_packaged_runtime(),
        "profile_source": gate.current_profile_source(),
    }


def _new_session_gate(gate: FeatureGate) -> FeatureGate:
    return FeatureGate(
        root=gate.root,
        allow_local_override=False,
        packaged_runtime=False,
        runtime_path=gate.runtime_path,
    )


def _replace_gate(app: Any, replacement: FeatureGate) -> None:
    app.state.feature_gate = replacement
    settings_service = getattr(app.state, "settings_application_service", None)
    if settings_service is not None and hasattr(settings_service, "feature_gate"):
        settings_service.feature_gate = replacement


def _require_gate(app: Any) -> FeatureGate:
    gate = getattr(app.state, "feature_gate", None)
    if not isinstance(gate, FeatureGate):
        raise EditionAccessError("Feature Gate 尚未初始化")
    return gate


def _lock_for(app: Any) -> Any:
    lock = getattr(app.state, _LOCK_ATTRIBUTE, None)
    if lock is not None and hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        return lock
    lock = RLock()
    setattr(app.state, _LOCK_ATTRIBUTE, lock)
    return lock


def _record_failed_attempt(app: Any, now: float) -> None:
    attempts = int(getattr(app.state, _FAILED_ATTRIBUTE, 0) or 0) + 1
    setattr(app.state, _FAILED_ATTRIBUTE, attempts)
    if attempts >= MAX_FAILED_ATTEMPTS:
        setattr(app.state, _LOCKED_UNTIL_ATTRIBUTE, now + LOCKOUT_SECONDS)
        setattr(app.state, _FAILED_ATTRIBUTE, 0)
        app_logger.log_warning(
            "CUSTOMER_EDITION_UNLOCK_THROTTLED",
            f"lockout_seconds={LOCKOUT_SECONDS}",
        )


def _clear_failed_attempts(app: Any) -> None:
    setattr(app.state, _FAILED_ATTRIBUTE, 0)
    setattr(app.state, _LOCKED_UNTIL_ATTRIBUTE, 0.0)


__all__ = [
    "EditionAccessError",
    "EditionUnlockNotAvailableError",
    "EditionUnlockPasswordError",
    "EditionUnlockThrottledError",
    "edition_runtime_status",
    "ensure_edition_gate",
    "lock_customer_edition",
    "unlock_customer_edition",
]
