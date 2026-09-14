from __future__ import annotations

import paramiko

from netconsole.core.paths import PathResolver
from netconsole.services.host_key_trust_service import (
    HostKeyPolicy,
    HostKeyTrustService,
    install_managed_host_key_policy,
    key_fingerprint_sha256,
)


def test_unknown_key_can_be_trusted_and_persists_in_managed_data_root(tmp_path):
    paths = PathResolver(tmp_path)
    service = HostKeyTrustService(paths)
    key = paramiko.RSAKey.generate(1024)

    result = service.trust_or_replace("192.0.2.1", 22, key)
    assert result.action == "ADD"
    assert result.details.fingerprint_sha256 == key_fingerprint_sha256(key)
    assert paths.global_known_hosts_path.is_file()
    service.verify("192.0.2.1", 22, key)


def test_changed_key_is_replaced_and_connection_can_continue(tmp_path):
    service = HostKeyTrustService(PathResolver(tmp_path))
    old_key = paramiko.RSAKey.generate(1024)
    new_key = paramiko.RSAKey.generate(1024)
    service.trust("192.0.2.2", 2222, old_key)

    result = service.trust_or_replace("192.0.2.2", 2222, new_key)

    assert result.action == "REPLACE"
    assert result.status == "HOST_KEY_AUTO_UPDATED"
    service.verify("192.0.2.2", 2222, new_key)
    replaced_again = service.trust_or_replace("192.0.2.2", 2222, old_key)
    assert replaced_again.action == "REPLACE"


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
    assert service.is_trusted("192.0.2.10", 22, first, role="jump") is False
    assert service.is_trusted("192.0.2.11", 22, other, role="target") is True


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


def test_remove_only_deletes_the_selected_host_port(tmp_path):
    service = HostKeyTrustService(PathResolver(tmp_path))
    jump_key = paramiko.RSAKey.generate(1024)
    target_key = paramiko.RSAKey.generate(1024)
    service.trust("192.0.2.30", 22, jump_key, role="jump")
    service.trust("192.0.2.31", 22, target_key)

    assert service.remove("192.0.2.30", 22) is True
    assert service.trust_or_replace("192.0.2.30", 22, jump_key, role="jump").action == "ADD"
    service.verify("192.0.2.31", 22, target_key)


def test_replacement_is_scoped_to_exact_host_and_port(tmp_path):
    service = HostKeyTrustService(PathResolver(tmp_path))
    port_22 = paramiko.RSAKey.generate(1024)
    port_2222 = paramiko.RSAKey.generate(1024)
    replacement = paramiko.RSAKey.generate(1024)
    service.trust("192.0.2.41", 22, port_22)
    service.trust("192.0.2.41", 2222, port_2222)

    service.trust_or_replace("192.0.2.41", 2222, replacement)

    assert service.is_trusted("192.0.2.41", 22, port_22)
    assert service.is_trusted("192.0.2.41", 2222, replacement)
    assert not service.is_trusted("192.0.2.41", 2222, port_2222)


def test_corrupt_managed_known_hosts_is_rebuilt_on_next_connection(tmp_path):
    paths = PathResolver(tmp_path)
    paths.global_known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    paths.global_known_hosts_path.write_text("not a known_hosts record\n", encoding="utf-8")
    service = HostKeyTrustService(paths)
    key = paramiko.RSAKey.generate(1024)

    result = service.trust_or_replace("192.0.2.40", 22, key)

    assert result.action == "ADD"
    service.verify("192.0.2.40", 22, key)
