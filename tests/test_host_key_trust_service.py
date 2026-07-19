from __future__ import annotations

import paramiko
import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.host_key_trust_service import (
    HostKeyChallengeError,
    HostKeyMismatchError,
    HostKeyTrustService,
    key_fingerprint_sha256,
)


def test_unknown_key_can_be_trusted_and_persists_in_managed_data_root(tmp_path):
    paths = PathResolver(tmp_path)
    service = HostKeyTrustService(paths)
    key = paramiko.RSAKey.generate(1024)

    with pytest.raises(HostKeyChallengeError) as excinfo:
        service.verify("192.0.2.1", 22, key)

    assert excinfo.value.code == "DEVICE_FILE_HOST_KEY_UNKNOWN"
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

    assert excinfo.value.code == "DEVICE_FILE_HOST_KEY_MISMATCH"
