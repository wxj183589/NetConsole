from __future__ import annotations

from pathlib import Path

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
    opened: list[tuple[str, int]] = []

    class FakeManager:
        def open_channel(self, host: str, port: int) -> FakeChannel:
            opened.append((host, port))
            return channel

    monkeypatch.setattr(site_ssh_relay, "_manager_for", lambda _paths, _config: FakeManager())
    service = type("RelayService", (), {"resolve_for_connection": lambda _self, _site: config})()
    captured: dict[str, object] = {}

    def raw_connect(**params: object) -> object:
        captured.update(params)
        return object()

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
    assert captured["ssh_strict"] is True
    assert captured["username"] == "device-user"
    assert captured["password"] == "device-secret"
    assert "jump-secret" not in str(captured)


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
        ("JUMP_CHANNEL_FAILED", "jump_channel_failed"),
        ("TARGET_CONNECT_FAILED", "target_connect_failed"),
        ("TARGET_AUTH_FAILED", "target_auth_failed"),
        ("TARGET_COMMAND_FAILED", "target_command_failed"),
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
