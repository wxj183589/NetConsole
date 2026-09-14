from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.sqlite_utils import connect_sqlite
from netconsole.core.sites import SiteManager
from netconsole.services import site_ssh_relay
from netconsole.services.netmiko_connection import classify_connection_exception
from netconsole.services.site_ssh_relay import (
    DeviceSSHConnectionFactory,
    ResolvedSiteSSHRelayConfig,
    SiteJumpSessionManager,
    SiteSSHRelayError,
    SiteSSHRelayService,
)
from netconsole.services.host_key_trust_service import HostKeyTrustService


def _paths(tmp_path: Path) -> PathResolver:
    paths = PathResolver(data_root=tmp_path)
    SiteManager(paths).create_site("alpha", display_name="Alpha")
    return paths


def test_new_site_relay_is_disabled_and_has_no_plaintext_credential_file(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    config = SiteSSHRelayService(paths).load("alpha")

    assert config.enabled is False
    assert config.password_configured is False
    assert not (paths.site_dir("alpha") / "db" / "site_ssh_credentials.sqlite3").exists()


def test_relay_password_is_dpapi_protected_and_not_plaintext_in_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(
        site_ssh_relay,
        "protect_windows_data",
        lambda data, entropy: bytes(value ^ 0x5A for value in data),
    )
    monkeypatch.setattr(
        site_ssh_relay,
        "unprotect_windows_data",
        lambda data, entropy: bytes(value ^ 0x5A for value in data),
    )

    service = SiteSSHRelayService(paths)
    saved = service.save(
        "alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        password="jump-secret",
    )

    db_path = paths.site_dir("alpha") / "db" / "site_ssh_credentials.sqlite3"
    with connect_sqlite(db_path) as connection:
        ciphertext = connection.execute("SELECT ciphertext FROM site_credentials").fetchone()[0]
    assert saved.password_configured is True
    assert b"jump-secret" not in bytes(ciphertext)
    assert service.resolve_for_connection("alpha").password == "jump-secret"


def test_enabled_relay_requires_complete_configuration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    service = SiteSSHRelayService(paths)

    with pytest.raises(SiteSSHRelayError) as error:
        service.save(
            "alpha",
            enabled=True,
            host="10.81.40.10",
            port=22,
            username="jump",
        )

    assert error.value.code == "SSH_RELAY_CONFIG_INCOMPLETE"


def test_delete_jump_host_key_is_exact_and_marks_relay_unrecorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(site_ssh_relay, "protect_windows_data", lambda data, _entropy: data)
    monkeypatch.setattr(site_ssh_relay, "unprotect_windows_data", lambda data, _entropy: data)
    service = SiteSSHRelayService(paths)
    service.save(
        "alpha",
        enabled=True,
        host="192.0.2.50",
        port=2222,
        username="jump",
        password="secret",
    )
    trust = HostKeyTrustService(paths)
    import paramiko

    deleted = paramiko.RSAKey.generate(1024)
    other = paramiko.RSAKey.generate(1024)
    trust.trust("192.0.2.50", 2222, deleted, role="jump")
    trust.trust("192.0.2.51", 22, other, role="target")

    result = service.delete_jump_host_key("alpha")

    assert result["host_key_status"] == "HOST_KEY_UNRECORDED"
    assert trust.is_trusted("192.0.2.50", 2222, deleted, role="jump") is False
    assert trust.trust_or_replace("192.0.2.50", 2222, deleted, role="jump").action == "ADD"
    trust.verify("192.0.2.51", 22, other, role="target")


def test_refresh_jump_host_key_replaces_and_publishes_current_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(site_ssh_relay, "protect_windows_data", lambda data, _entropy: data)
    monkeypatch.setattr(site_ssh_relay, "unprotect_windows_data", lambda data, _entropy: data)
    service = SiteSSHRelayService(paths)
    service.save(
        "alpha",
        enabled=True,
        host="192.0.2.52",
        port=2222,
        username="jump",
        password="secret",
    )

    class FakeClient:
        _netconsole_host_key_event = {
            "status": "HOST_KEY_AUTO_UPDATED",
            "fingerprint_sha256": "SHA256:new",
        }

        class _Transport:
            @staticmethod
            def is_active() -> bool:
                return True

            @staticmethod
            def set_keepalive(_seconds: int) -> None:
                return None

        def connect(self, **_kwargs: object) -> None:
            return None

        def get_transport(self):
            return self._Transport()

        def close(self) -> None:
            return None

    monkeypatch.setattr(site_ssh_relay, "_new_paramiko_client", lambda *_args, **_kwargs: FakeClient())

    result = service.refresh_jump_host_key("alpha")

    assert result["message"] == "指纹已更新"
    assert result["host_key_status"] == "HOST_KEY_AUTO_UPDATED"
    assert result["host_key_fingerprint_sha256"] == "SHA256:new"
    assert result["runtime_status"] == "RUNNING"
    public = service.public_config("alpha")
    assert public["host_key_status"] == "HOST_KEY_AUTO_UPDATED"
    assert public["host_key_fingerprint_sha256"] == "SHA256:new"
    assert public["runtime_status"] == "RUNNING"


def test_unified_factory_keeps_direct_path_when_site_relay_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    config = site_ssh_relay.SiteSSHRelayConfig(
        site_id="alpha",
        enabled=False,
        host="",
        port=22,
        username="",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=False,
    )
    service = type("RelayService", (), {"load": lambda _self, _site: config})()
    monkeypatch.setattr(
        site_ssh_relay,
        "_manager_for",
        lambda *_args: pytest.fail("disabled relay opened a Jump manager"),
    )
    direct_calls: list[dict[str, object]] = []

    def raw_connect(**params: object) -> str:
        direct_calls.append(params)
        return "direct-session"

    result = DeviceSSHConnectionFactory(paths, "alpha", relay_service=service).connect(
        {
            "device_type": "hp_comware",
            "host": "10.82.21.11",
            "username": "admin",
            "password": "secret",
            "port": 22,
        },
        raw_connect_handler=raw_connect,
        compatibility_connect=lambda handler, params: handler(**params),
    )

    assert result == "direct-session"
    assert direct_calls[0]["host"] == "10.82.21.11"


def test_factory_uses_one_direct_tcpip_channel_and_keeps_credentials_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeChannel:
        pass

    channel = FakeChannel()
    import paramiko

    target_key = paramiko.RSAKey.generate(1024)
    opened: list[tuple[str, int]] = []

    class FakeManager:
        def open_channel(self, host: str, port: int) -> FakeChannel:
            opened.append((host, port))
            return channel

    monkeypatch.setattr(site_ssh_relay, "_manager_for", lambda _paths, _config: FakeManager())
    service = type("RelayService", (), {"load": lambda _self, _site: config, "resolve_for_connection": lambda _self, _site: config})()
    captured: dict[str, object] = {}

    def raw_connect(**params: object) -> object:
        captured.update(params)
        return SimpleNamespace(
            remote_conn_pre=SimpleNamespace(
                get_transport=lambda: SimpleNamespace(get_remote_server_key=lambda: target_key),
            )
        )

    def compatibility(connect_handler, params):
        return connect_handler(**params)

    result = DeviceSSHConnectionFactory(paths, "alpha", relay_service=service).connect(
        {
            "device_type": "hp_comware",
            "host": "10.82.21.11",
            "username": "device-user",
            "password": "device-secret",
            "port": 22,
        },
        raw_connect_handler=raw_connect,
        compatibility_connect=compatibility,
    )

    assert result is not None
    assert opened == [("10.82.21.11", 22)]
    assert captured["sock"] is channel
    assert captured["ssh_strict"] is False
    assert captured["username"] == "device-user"
    assert captured["password"] == "device-secret"
    assert "jump-secret" not in str(captured)
    assert site_ssh_relay.HostKeyTrustService(paths).is_trusted("10.82.21.11", 22, target_key)


def test_factory_replaces_target_host_key_and_returns_original_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paramiko

    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )
    key_one = paramiko.RSAKey.generate(1024)
    key_two = paramiko.RSAKey.generate(1024)

    class FakeChannel:
        def close(self) -> None:
            pass

    class FakeManager:
        def open_channel(self, _host: str, _port: int) -> FakeChannel:
            return FakeChannel()

    class FakeConnection:
        def __init__(self, key) -> None:
            self.remote_conn_pre = SimpleNamespace(
                get_transport=lambda: SimpleNamespace(get_remote_server_key=lambda: key),
            )
            self.disconnected = False

        def disconnect(self) -> None:
            self.disconnected = True

    current_key = key_one
    connections: list[FakeConnection] = []
    monkeypatch.setattr(site_ssh_relay, "_manager_for", lambda _paths, _config: FakeManager())
    service = type("RelayService", (), {"load": lambda _self, _site: config, "resolve_for_connection": lambda _self, _site: config})()

    def raw_connect(**_params: object) -> FakeConnection:
        connection = FakeConnection(current_key)
        connections.append(connection)
        return connection

    def compatibility(connect_handler, params):
        return connect_handler(**params)

    factory = DeviceSSHConnectionFactory(paths, "alpha", relay_service=service)
    factory.connect(
        {"device_type": "hp_comware", "host": "10.82.21.11", "username": "admin", "password": "secret", "port": 22},
        raw_connect_handler=raw_connect,
        compatibility_connect=compatibility,
    )
    current_key = key_two
    result = factory.connect(
        {"device_type": "hp_comware", "host": "10.82.21.11", "username": "admin", "password": "secret", "port": 22},
        raw_connect_handler=raw_connect,
        compatibility_connect=compatibility,
    )

    assert result is connections[-1]
    assert connections[-1].disconnected is False
    assert site_ssh_relay.HostKeyTrustService(paths).is_trusted("10.82.21.11", 22, key_two)
    assert "secret" not in str(result)


def test_unified_factory_uses_direct_channel_for_telnet_and_preserves_target_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeChannel:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeManager:
        def __init__(self) -> None:
            self.channel = FakeChannel()

        def open_channel(self, host: str, port: int) -> FakeChannel:
            assert (host, port) == ("10.82.43.24", 23)
            return self.channel

    manager = FakeManager()
    monkeypatch.setattr(site_ssh_relay, "_manager_for", lambda _paths, _config: manager)
    service = type("RelayService", (), {"load": lambda _self, _site: config, "resolve_for_connection": lambda _self, _site: config})()
    captured: dict[str, object] = {}

    class FakeConnection:
        def disconnect(self) -> None:
            pass

    def raw_connect(**_params: object) -> FakeConnection:
        raise AssertionError("Telnet relay must not open a direct Windows socket")

    def telnet_connect(params: dict[str, object], channel: object) -> FakeConnection:
        captured.update(params)
        assert channel is manager.channel
        return FakeConnection()

    monkeypatch.setattr(site_ssh_relay, "_connect_telnet_over_channel", telnet_connect)

    def compatibility(connect_handler, params):
        return connect_handler(**params)

    result = site_ssh_relay.DeviceSSHConnectionFactory(paths, "alpha", relay_service=service).connect(
        {
            "device_type": "hp_comware_telnet",
            "host": "10.82.43.24",
            "username": "ap-user",
            "password": "ap-secret",
            "port": 23,
        },
        raw_connect_handler=raw_connect,
        compatibility_connect=compatibility,
    )

    assert result is not None
    assert captured["host"] == "10.82.43.24"
    assert captured["port"] == 23
    assert captured["username"] == "ap-user"
    assert captured["password"] == "ap-secret"
    assert "jump-secret" not in str(captured)
    result.disconnect()
    assert manager.channel.closed is False


def test_jump_manager_reuses_transport_but_target_channels_are_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeChannel:
        def __init__(self, target: tuple[str, int]) -> None:
            self.target = target
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeTransport:
        def __init__(self) -> None:
            self.channels: list[FakeChannel] = []

        def is_active(self) -> bool:
            return True

        def open_channel(self, _kind: str, destination: tuple[str, int], _source: tuple[str, int]) -> FakeChannel:
            channel = FakeChannel(destination)
            self.channels.append(channel)
            return channel

    class FakeClient:
        def __init__(self) -> None:
            self.transport = FakeTransport()
            self.connect_count = 0
            self.closed = False

        def connect(self, **_kwargs: object) -> None:
            self.connect_count += 1

        def get_transport(self) -> FakeTransport:
            return self.transport

        def close(self) -> None:
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(site_ssh_relay, "_new_paramiko_client", lambda *_args, **_kwargs: client)
    manager = SiteJumpSessionManager(paths, config)

    first = manager.open_channel("10.82.21.11", 22)
    second = manager.open_channel("10.82.21.12", 22)
    first.close()

    assert first is not second
    assert client.connect_count == 1
    assert client.closed is False
    assert client.transport.channels[1].closed is False

    manager.close()
    assert client.closed is True


def test_jump_manager_publishes_current_auto_host_key_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeTransport:
        def is_active(self) -> bool:
            return True

    class FakeClient:
        def __init__(self) -> None:
            self.transport = FakeTransport()
            self.closed = False
            self._netconsole_host_key_event = {
                "status": "HOST_KEY_AUTO_UPDATED",
                "fingerprint_sha256": "SHA256:new",
                "old_fingerprint_sha256": "SHA256:old",
            }

        def connect(self, **_kwargs: object) -> None:
            return None

        def get_transport(self) -> FakeTransport:
            return self.transport

        def close(self) -> None:
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(site_ssh_relay, "_new_paramiko_client", lambda *_args, **_kwargs: client)
    manager = SiteJumpSessionManager(paths, config)

    manager.ensure_running()

    status = manager.public_status()
    assert status["runtime_status"] == "RUNNING"
    assert status["runtime_message"] == "SSH 中转已连接"
    assert status["host_key_status"] == "HOST_KEY_AUTO_UPDATED"
    assert status["host_key_fingerprint_sha256"] == "SHA256:new"
    assert status["host_key_updated_at"]
    manager.close()
    assert manager.public_status()["host_key_status"] == ""


def test_jump_manager_recovers_one_stale_transport_and_applies_keepalive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paramiko

    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeTransport:
        def __init__(self, *, stale: bool) -> None:
            self.active = True
            self.stale = stale
            self.open_count = 0
            self.keepalive: int | None = None

        def is_active(self) -> bool:
            return self.active

        def set_keepalive(self, seconds: int) -> None:
            self.keepalive = seconds

        def open_channel(self, *_args):
            self.open_count += 1
            if self.stale:
                self.active = False
                raise paramiko.SSHException("No existing session")
            return object()

    class FakeClient:
        def __init__(self, transport: FakeTransport) -> None:
            self.transport = transport
            self.closed = False

        def connect(self, **_kwargs: object) -> None:
            return None

        def get_transport(self) -> FakeTransport:
            return self.transport

        def close(self) -> None:
            self.closed = True

    transports = [FakeTransport(stale=True), FakeTransport(stale=False)]
    clients = [FakeClient(item) for item in transports]
    monkeypatch.setattr(
        site_ssh_relay,
        "_new_paramiko_client",
        lambda *_args, **_kwargs: clients.pop(0),
    )
    manager = SiteJumpSessionManager(paths, config)

    channel = manager.open_channel("10.82.21.11", 22)

    assert channel is not None
    assert transports[0].open_count == 1
    assert transports[1].open_count == 1
    assert transports[0].keepalive == site_ssh_relay.SITE_RELAY_KEEPALIVE_SECONDS
    assert transports[1].keepalive == site_ssh_relay.SITE_RELAY_KEEPALIVE_SECONDS
    assert clients == []
    manager.close()


def test_jump_manager_does_not_retry_target_acl_failure_after_active_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paramiko

    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeTransport:
        def __init__(self) -> None:
            self.open_count = 0

        def is_active(self) -> bool:
            return True

        def set_keepalive(self, _seconds: int) -> None:
            return None

        def open_channel(self, *_args):
            self.open_count += 1
            raise paramiko.ChannelException(1, "Administratively prohibited")

    class FakeClient:
        def __init__(self) -> None:
            self.transport = FakeTransport()

        def connect(self, **_kwargs: object) -> None:
            return None

        def get_transport(self) -> FakeTransport:
            return self.transport

        def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(site_ssh_relay, "_new_paramiko_client", lambda *_args, **_kwargs: client)
    manager = SiteJumpSessionManager(paths, config)

    with pytest.raises(SiteSSHRelayError) as error:
        manager.open_channel("10.82.21.11", 22)

    assert error.value.code == "JUMP_CHANNEL_FAILED"
    assert client.transport.open_count == 1
    assert error.value.details["recovery_retry_count"] == 0
    manager.close()


def test_jump_manager_stale_recovery_retries_channel_once_then_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(data_root=tmp_path)
    config = ResolvedSiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
        password="jump-secret",
    )

    class FakeTransport:
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail
            self.open_count = 0

        def is_active(self) -> bool:
            return True

        def set_keepalive(self, _seconds: int) -> None:
            return None

        def open_channel(self, *_args):
            self.open_count += 1
            if self.fail:
                raise RuntimeError("No existing session")
            return object()

    class FakeClient:
        def __init__(self, transport: FakeTransport) -> None:
            self.transport = transport

        def connect(self, **_kwargs: object) -> None:
            return None

        def get_transport(self) -> FakeTransport:
            return self.transport

        def close(self) -> None:
            return None

    transports = [FakeTransport(fail=True), FakeTransport(fail=True)]
    clients = [FakeClient(item) for item in transports]
    monkeypatch.setattr(
        site_ssh_relay,
        "_new_paramiko_client",
        lambda *_args, **_kwargs: clients.pop(0),
    )
    manager = SiteJumpSessionManager(paths, config)

    with pytest.raises(SiteSSHRelayError) as error:
        manager.open_channel("10.82.21.11", 22)

    assert error.value.code == "JUMP_CHANNEL_FAILED"
    assert transports[0].open_count == 1
    assert transports[1].open_count == 1
    assert error.value.details["stale_transport_recovery"] is True
    assert error.value.details["recovery_retry_count"] == 1
    assert clients == []
    manager.close()


def test_common_netmiko_facade_selects_jump_for_active_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import netmiko

    from netconsole.services import netmiko_connection

    selected: dict[str, object] = {}
    relay_config = site_ssh_relay.SiteSSHRelayConfig(
        site_id="alpha",
        enabled=True,
        host="10.81.40.10",
        port=22,
        username="jump",
        credential_ref="site-ssh-relay-alpha",
        revision="r1",
        password_configured=True,
    )

    def fake_connect(_self, params, **_kwargs):
        selected.update(params)
        return "jump-session"

    monkeypatch.setattr(site_ssh_relay, "active_site_id", lambda _paths: "alpha")
    monkeypatch.setattr(site_ssh_relay.SiteSSHRelayService, "load", lambda _self, _site: relay_config)
    monkeypatch.setattr(site_ssh_relay.DeviceSSHConnectionFactory, "connect", fake_connect)
    monkeypatch.setattr(netmiko, "ConnectHandler", lambda **_params: "direct-session")

    result = netmiko_connection.ConnectHandler(
        device_type="hp_comware",
        host="10.82.21.11",
        username="device-user",
        password="device-secret",
        port=22,
    )

    assert result == "jump-session"
    assert selected["host"] == "10.82.21.11"
    assert selected["password"] == "device-secret"


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("JUMP_CONNECT_FAILED", "jump_connect_failed"),
        ("JUMP_AUTH_FAILED", "jump_auth_failed"),
        ("JUMP_HOSTKEY_FAILED", "jump_hostkey_failed"),
        ("JUMP_CHANNEL_FAILED", "jump_channel_failed"),
        ("TARGET_CONNECT_FAILED", "target_connect_failed"),
        ("TARGET_TCP_FAILED", "target_tcp_failed"),
        ("TARGET_SSH_BANNER_FAILED", "target_ssh_banner_failed"),
        ("TARGET_SSH_HANDSHAKE_FAILED", "target_ssh_handshake_failed"),
        ("TARGET_HOSTKEY_FAILED", "target_hostkey_failed"),
        ("TARGET_HOSTKEY_CHANGED", "target_hostkey_changed"),
        ("TARGET_AUTH_FAILED", "target_auth_failed"),
        ("TARGET_SESSION_FAILED", "target_session_failed"),
        ("TARGET_COMMAND_FAILED", "target_command_failed"),
        ("CONNECT_TIMEOUT", "connect_timeout"),
    ],
)
def test_relay_error_codes_are_preserved_in_common_connection_classification(
    code: str,
    status: str,
) -> None:
    error = SiteSSHRelayError(code, "safe message")

    classification = classify_connection_exception(error)

    assert classification.status == status
    assert classification.error_type == code
