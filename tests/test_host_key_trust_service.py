from __future__ import annotations

import paramiko
import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.host_key_trust_service import (
    HostKeyChallengeError,
    HostKeyPolicy,
    HostKeyMismatchError,
    HostKeyTrustService,
    install_managed_host_key_policy,
    key_fingerprint_sha256,
)


def test_unknown_key_can_be_trusted_and_persists_in_managed_data_root(tmp_path):
    paths = PathResolver(tmp_path)
    service = HostKeyTrustService(paths)
    key = paramiko.RSAKey.generate(1024)

    with pytest.raises(HostKeyChallengeError) as excinfo:
        service.verify("192.0.2.1", 22, key)

    assert excinfo.value.code == "DEVICE_FILE_TARGET_HOST_KEY_UNKNOWN"
    assert excinfo.value.details["host_key_role"] == "target"
    assert excinfo.value.details["fingerprint_sha256"] == key_fingerprint_sha256(key)
    assert str(tmp_path) not in str(excinfo.value.details)

    service.trust("192.0.2.1", 22, key)
    assert paths.global_known_hosts_path.is_file()
    service.verify("192.0.2.1", 22, key)


def test_changed_key_is_blocked(tmp_path):
    service = HostKeyTrustService(PathResolver(tmp_path))
    service.trust("192.0.2.2", 2222, paramiko.RSAKey.generate(1024))

    with pytest.raises(HostKeyMismatchError) as excinfo:
        service.verify("192.0.2.2", 2222, paramiko.RSAKey.generate(1024))

    assert excinfo.value.code == "DEVICE_FILE_TARGET_HOST_KEY_MISMATCH"


def test_auto_replace_changes_only_the_selected_host_and_keeps_other_entries(tmp_path):
    paths = PathResolver(tmp_path)
    service = HostKeyTrustService(paths)
    first = paramiko.RSAKey.generate(1024)
    replacement = paramiko.RSAKey.generate(1024)
    other = paramiko.RSAKey.generate(1024)
    service.trust("192.0.2.10", 22, first, role="jump")
    service.trust("192.0.2.11", 22, other, role="target")

    result = service.trust_or_replace("192.0.2.10", 22, replacement, role="jump")

    assert result.action == "REPLACE"
    assert result.status == "HOST_KEY_AUTO_UPDATED"
    assert result.old_fingerprint_sha256 == key_fingerprint_sha256(first)
    service.verify("192.0.2.10", 22, replacement, role="jump")
    service.verify("192.0.2.11", 22, other, role="target")
    with pytest.raises(HostKeyMismatchError):
        service.verify("192.0.2.10", 22, first, role="jump")


def test_auto_replace_policy_records_add_and_update_events(tmp_path):
    paths = PathResolver(tmp_path)
    service = HostKeyTrustService(paths)
    client = paramiko.SSHClient()
    install_managed_host_key_policy(
        client,
        service,
        "192.0.2.20",
        22,
        role="jump",
        host_key_policy=HostKeyPolicy.AUTO_REPLACE,
    )
    first = paramiko.RSAKey.generate(1024)
    replacement = paramiko.RSAKey.generate(1024)

    client._policy.missing_host_key(client, "192.0.2.20", first)
    assert client._netconsole_host_key_event["status"] == "HOST_KEY_AUTO_ADDED"
    client._policy.missing_host_key(client, "192.0.2.20", replacement)
    assert client._netconsole_host_key_event["status"] == "HOST_KEY_AUTO_UPDATED"
    assert client._netconsole_host_key_event["old_fingerprint_sha256"] == key_fingerprint_sha256(first)
