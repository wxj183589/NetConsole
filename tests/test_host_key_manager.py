from __future__ import annotations

import sqlite3

import paramiko
import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.host_key_manager import (
    STRICT,
    HostKeyManager,
    HostKeyManagerError,
)
from netconsole.services.host_key_trust_service import (
    HostKeyPolicy,
    HostKeyTrustError,
    HostKeyTrustService,
    finalize_managed_host_key,
    install_managed_host_key_policy,
)


def _key() -> paramiko.RSAKey:
    return paramiko.RSAKey.generate(1024)


def _manager(tmp_path):
    return HostKeyManager(PathResolver(tmp_path))


def _trust_first(manager: HostKeyManager, key: paramiko.RSAKey, *, device_id: str = "dev-1"):
    return manager.observe_successful_connection(
        device_id,
        "192.0.2.10",
        22,
        key,
        authorized=True,
    )


def test_schema_migration_is_idempotent_and_uses_sqlite_version(tmp_path):
    manager = _manager(tmp_path)
    manager.repository.ensure_schema()
    manager.repository.ensure_schema()

    with sqlite3.connect(manager.repository.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"host_key_records", "host_key_history", "host_key_events"} <= names


def test_first_connection_is_pending_until_success_then_saved(tmp_path):
    manager = _manager(tmp_path)
    key = _key()

    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, key, authorized=True
    )
    assert staged.status == "HOST_KEY_AUTO_ADDED"
    pending = manager.get_record("dev-1", "192.0.2.10")
    assert pending["current_fingerprint_sha256"] is None
    assert pending["pending_status"] == "PENDING_TRUST"

    committed = manager.commit_success(staged.pending_token)
    current = manager.get_record("dev-1", "192.0.2.10")
    assert committed.status == "HOST_KEY_AUTO_ADDED"
    assert current["current_fingerprint_sha256"] == committed.details.fingerprint_sha256
    assert current["first_seen_at"]
    assert current["last_verified_at"]
    assert current["pending_token"] is None


def test_matching_key_verifies_without_creating_a_new_current_fingerprint(tmp_path):
    manager = _manager(tmp_path)
    key = _key()
    _trust_first(manager, key)

    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, key, authorized=True
    )
    assert staged.status == "HOST_KEY_VERIFIED"
    assert manager.get_record("dev-1", "192.0.2.10")["current_fingerprint_sha256"] == staged.details.fingerprint_sha256
    manager.commit_success(staged.pending_token)
    assert manager.get_record("dev-1", "192.0.2.10")["revision"] == 2


def test_auto_update_keeps_old_current_until_success_and_preserves_history(tmp_path):
    manager = _manager(tmp_path)
    old_key = _key()
    new_key = _key()
    _trust_first(manager, old_key)

    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, new_key, authorized=True
    )
    current_before = manager.get_record("dev-1", "192.0.2.10")
    assert staged.status == "HOST_KEY_CHANGED"
    assert current_before["current_fingerprint_sha256"] == staged.old_fingerprint_sha256
    assert current_before["pending_fingerprint_sha256"] == staged.details.fingerprint_sha256

    committed = manager.commit_success(staged.pending_token)
    current_after = manager.get_record("dev-1", "192.0.2.10")
    assert committed.status == "HOST_KEY_AUTO_UPDATED"
    assert current_after["current_fingerprint_sha256"] == committed.details.fingerprint_sha256
    assert current_after["last_changed_at"]
    history = manager.list_history("dev-1")
    assert any(item["event_type"] == "REPLACED" for item in history)
    assert any(item["old_fingerprint_sha256"] == staged.old_fingerprint_sha256 for item in history)


def test_strict_mode_rejects_changed_key_and_keeps_old_current(tmp_path):
    manager = _manager(tmp_path)
    old_key = _key()
    new_key = _key()
    _trust_first(manager, old_key)
    manager.set_policy("dev-1", "192.0.2.10", 22, STRICT, authorized=True)

    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, new_key, authorized=True
    )
    assert staged.allowed is False
    assert staged.status == "HOST_KEY_STRICT_REJECTED"
    with pytest.raises(HostKeyManagerError, match="STRICT"):
        manager.observe_successful_connection(
            "dev-1", "192.0.2.10", 22, new_key, authorized=True
        )
    current = manager.get_record("dev-1", "192.0.2.10")
    assert current["current_fingerprint_sha256"] == manager.repository.get("dev-1", "192.0.2.10", 22).current_fingerprint_sha256
    assert current["update_policy"] == STRICT
    assert any(item["event_type"] == "STRICT_REJECTED" for item in manager.list_history("dev-1"))


def test_failed_update_clears_pending_and_keeps_old_current(tmp_path):
    manager = _manager(tmp_path)
    old_key = _key()
    new_key = _key()
    _trust_first(manager, old_key)
    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, new_key, authorized=True
    )

    manager.reject_pending(staged.pending_token, reason="authentication cancelled")
    current = manager.get_record("dev-1", "192.0.2.10")
    assert current["current_fingerprint_sha256"] == staged.old_fingerprint_sha256
    assert current["pending_token"] is None
    events = manager.list_events("dev-1")
    assert any(item["event_type"] == "HOST_KEY_UPDATE_FAILED" for item in events)


def test_unauthorized_target_cannot_stage_or_auto_trust(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(HostKeyManagerError) as error:
        manager.stage_connection(
            "unknown", "192.0.2.99", 22, _key(), authorized=False
        )
    assert error.value.code == "HOST_KEY_TARGET_UNAUTHORIZED"
    assert manager.get_record("unknown", "192.0.2.99") is None


def test_automatic_trust_requires_the_registered_device_resource_table(tmp_path):
    paths = PathResolver(tmp_path)
    manager = _manager(tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = Device(
        name="registered-switch",
        device_uuid=Device.new_uuid(),
        primary_address="192.0.2.30",
    )
    DeviceRepository(database).create(device)

    assert manager.has_device_resource_authority("demo") is True
    assert manager.is_registered_device("demo", device.device_uuid) is True
    assert manager.is_registered_device("other-site", device.device_uuid) is False
    assert manager.is_registered_device("demo", Device.new_uuid()) is False


def test_concurrent_different_updates_fail_closed_and_first_update_wins(tmp_path):
    manager = _manager(tmp_path)
    _trust_first(manager, _key())
    first = _key()
    second = _key()
    staged_first = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, first, authorized=True
    )
    staged_second = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, second, authorized=True
    )
    assert staged_first.allowed is True
    assert staged_second.allowed is False
    manager.commit_success(staged_first.pending_token)
    current = manager.get_record("dev-1", "192.0.2.10")
    assert current["current_fingerprint_sha256"] == staged_first.details.fingerprint_sha256
    assert any(item["event_type"] == "HOST_KEY_UPDATE_CONFLICT" for item in manager.list_events("dev-1"))


def test_cancelled_first_connection_is_not_registered_as_current(tmp_path):
    manager = _manager(tmp_path)
    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, _key(), authorized=True
    )
    manager.reject_pending(staged.pending_token, reason="cancelled")
    record = manager.get_record("dev-1", "192.0.2.10")
    assert record["current_fingerprint_sha256"] is None
    assert record["pending_token"] is None


def test_unsupported_host_key_algorithm_is_rejected(tmp_path):
    manager = _manager(tmp_path)

    class UnsupportedKey:
        def get_name(self):
            return "ssh-unknown-test"

        def asbytes(self):
            return b"not-a-real-key"

    with pytest.raises(HostKeyManagerError) as error:
        manager.stage_connection(
            "dev-1", "192.0.2.10", 22, UnsupportedKey(), authorized=True
        )
    assert error.value.code == "HOST_KEY_UNSUPPORTED_ALGORITHM"


def test_repeated_commit_is_idempotent_and_history_query_is_available(tmp_path):
    manager = _manager(tmp_path)
    old_key = _key()
    new_key = _key()
    _trust_first(manager, old_key)
    staged = manager.stage_connection(
        "dev-1", "192.0.2.10", 22, new_key, authorized=True
    )
    first = manager.commit_success(staged.pending_token)
    second = manager.commit_success(staged.pending_token)
    assert first.details.fingerprint_sha256 == second.details.fingerprint_sha256
    assert len([item for item in manager.list_history("dev-1") if item["event_type"] == "REPLACED"]) == 1
    assert len([item for item in manager.list_events("dev-1") if item["event_type"] == "HOST_KEY_AUTO_UPDATED"]) == 1


def test_paramiko_policy_does_not_promote_unknown_key_until_connection_success(tmp_path):
    paths = PathResolver(tmp_path)
    manager = HostKeyManager(paths)
    client = paramiko.SSHClient()
    install_managed_host_key_policy(
        client,
        HostKeyTrustService(paths),
        "192.0.2.10",
        22,
        device_id="dev-1",
        authorized=True,
        host_key_policy=HostKeyPolicy.AUTO_UPDATE,
    )
    key = _key()
    client._policy.missing_host_key(client, "192.0.2.10", key)
    assert manager.get_record("dev-1", "192.0.2.10")["current_fingerprint_sha256"] is None

    failed = finalize_managed_host_key(
        client, success=False, failure_reason="authentication cancelled"
    )
    assert failed["result"] == "FAILED"
    assert manager.get_record("dev-1", "192.0.2.10")["current_fingerprint_sha256"] is None

    client._policy.missing_host_key(client, "192.0.2.10", key)
    finalized = finalize_managed_host_key(client, success=True)
    assert finalized["status"] == "HOST_KEY_AUTO_ADDED"
    assert manager.get_record("dev-1", "192.0.2.10")["current_fingerprint_sha256"]


def test_paramiko_policy_uses_persisted_strict_policy_for_registered_target(tmp_path):
    paths = PathResolver(tmp_path)
    manager = HostKeyManager(paths)
    manager.register_target(
        "dev-1",
        "192.0.2.10",
        authorized=True,
        update_policy=STRICT,
    )
    first_key = _key()
    first_client = paramiko.SSHClient()
    install_managed_host_key_policy(
        first_client,
        HostKeyTrustService(paths),
        "192.0.2.10",
        22,
        device_id="dev-1",
        authorized=True,
        host_key_policy=HostKeyPolicy.AUTO_UPDATE,
        host_key_manager=manager,
    )
    first_client._policy.missing_host_key(first_client, "192.0.2.10", first_key)
    finalize_managed_host_key(first_client, success=True)

    second_client = paramiko.SSHClient()
    install_managed_host_key_policy(
        second_client,
        HostKeyTrustService(paths),
        "192.0.2.10",
        22,
        device_id="dev-1",
        authorized=True,
        host_key_policy=HostKeyPolicy.AUTO_UPDATE,
        host_key_manager=manager,
    )
    with pytest.raises(HostKeyTrustError) as error:
        second_client._policy.missing_host_key(second_client, "192.0.2.10", _key())
    assert getattr(error.value, "code", "") == "HOST_KEY_STRICT_REJECTED"
    assert manager.get_record("dev-1", "192.0.2.10")["update_policy"] == STRICT
