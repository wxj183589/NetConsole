from __future__ import annotations

import socket

import pytest

from netconsole.core.device_credential_store import resolve_device_credentials
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services import command_guard, netmiko_connection
from netconsole.services.netmiko_connection import (
    build_netmiko_params,
    choose_connection_target,
    prepared_connection_target,
    run_netmiko_with_retry,
    ssh_connection_context,
)


def _fixture_device() -> Device:
    return Device(
        device_uuid="b2-e3-offline-device",
        name="DEVICE-NB10-C7-01",
        device_vendor="H3C",
        device_type="SW",
        primary_address="192.0.2.10",
        ssh_enabled=1,
        ssh_port=22,
        ssh_username="offline-user",
        ssh_password="fixture-credential-value",
    )


def test_b2_and_e3_use_the_same_connection_factory_and_target_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    calls: list[dict[str, object]] = []
    socket_calls: list[object] = []

    class FakeConnection:
        def disconnect(self) -> None:
            return None

    def fake_socket(*args, **kwargs):
        socket_calls.append((args, kwargs))
        raise AssertionError("offline E3 validation must not open a socket")

    def fake_connect_handler(**kwargs: object) -> FakeConnection:
        calls.append(
            {
                "params": dict(kwargs),
                "context": netmiko_connection._SSH_CONNECTION_CONTEXT.get(),
            }
        )
        return FakeConnection()

    monkeypatch.setattr(socket, "create_connection", fake_socket)
    monkeypatch.setattr(netmiko_connection, "ConnectHandler", fake_connect_handler)

    device = _fixture_device()
    paths = PathResolver(data_root=tmp_path)
    site_id = "宁波10号线"

    # B2/formal collector seam: the production retry helper owns target
    # preparation, context, and the shared ConnectHandler entrypoint.
    formal_result = run_netmiko_with_retry(
        device,
        lambda _connection, target: target.method,
        paths=paths,
        site_id=site_id,
    )

    # E3 capture seam: capture-only validation uses the same target preparation,
    # context, parameter builder, and shared ConnectHandler.  It has no writer.
    target = choose_connection_target(device)
    assert target is not None
    with prepared_connection_target(target) as prepared:
        with ssh_connection_context(
            "interface_discovery_e3",
            "readonly_capture",
            device_uuid=str(device.device_uuid or ""),
            paths=paths,
            site_id=site_id,
        ):
            connection = netmiko_connection.ConnectHandler(
                **build_netmiko_params(prepared)
            )
        connection.disconnect()

    assert formal_result == target.method
    assert len(calls) == 2
    assert calls[0]["params"] == calls[1]["params"]
    assert calls[0]["params"]["device_type"] == "hp_comware"
    assert calls[0]["params"]["host"] == "192.0.2.10"
    assert calls[0]["params"]["port"] == 22
    assert calls[0]["params"]["username"] == "offline-user"
    assert calls[0]["params"]["password"] == device.ssh_password
    assert calls[0]["context"].paths == paths
    assert calls[1]["context"].paths == paths
    assert calls[0]["context"].site_id == site_id
    assert calls[1]["context"].site_id == site_id
    assert socket_calls == []


def test_e3_credential_resolution_matches_device_repository_contract() -> None:
    values, resolution = resolve_device_credentials(
        {
            "device_uuid": "b2-e3-credential-device",
            "device_vendor": "H3C",
            "device_type": "SW",
            "primary_address": "192.0.2.11",
            "ssh_enabled": 1,
            "ssh_port": 22,
            "username": "offline-user",
            "password": "fixture-credential-value",
        }
    )
    device = Device.from_mapping(values)

    assert resolution.status == "available"
    assert resolution.source == "local_database"
    assert device.ssh_username == "offline-user"
    assert device.ssh_password == "fixture-credential-value"
    target = choose_connection_target(device)
    assert target is not None
    assert target.username == device.ssh_username
    assert target.password == device.ssh_password


def test_e3_readonly_commands_are_guarded_and_configuration_is_rejected() -> None:
    command_guard.validate_command_list(
        ("screen-length disable", "display version", "display interface"),
        "device_collect",
    )

    with pytest.raises(command_guard.CommandRejected):
        command_guard.validate_command_list(("system-view",), "device_collect")
