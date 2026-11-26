from __future__ import annotations

import socket
import threading
import time

import paramiko

from netconsole.core.paths import PathResolver
from netconsole.core.database import Database
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.netmiko_connection import ConnectionTarget
from netconsole.services.site_manager import SiteManager
from netconsole.services.terminal_transports import (
    SshInteractiveTransport,
    TelnetInteractiveTransport,
)


class _CaptureSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


def _wait_for_output(transport, needle: str, *, timeout: float = 3.0) -> str:
    deadline = time.monotonic() + timeout
    output = ""
    while time.monotonic() < deadline:
        output += transport.read()
        if needle in output:
            return output
        time.sleep(0.01)
    raise AssertionError(f"terminal output did not contain {needle!r}: {output!r}")


def _transport(tmp_path) -> tuple[TelnetInteractiveTransport, _CaptureSocket]:
    target = ConnectionTarget(
        protocol="Telnet",
        device_type="hp_comware_telnet",
        host="127.0.0.1",
        port=23,
        username="operator",
        password="secret",
    )
    transport = TelnetInteractiveTransport(
        PathResolver(data_root=tmp_path / "data"),
        target,
        site_id="test-site",
    )
    capture = _CaptureSocket()
    transport._socket = capture
    return transport, capture


def test_telnet_iac_negotiation_survives_recv_fragmentation(tmp_path) -> None:
    transport, capture = _transport(tmp_path)

    assert transport._process_iac(b"hello\xff") == b"hello"
    assert transport._process_iac(bytes((transport.DO,))) == b""
    assert transport._process_iac(bytes((transport.NAWS,)) + b"world") == b"world"

    assert capture.sent[0] == bytes((transport.IAC, transport.WILL, transport.NAWS))
    assert capture.sent[1].startswith(bytes((transport.IAC, transport.SB, transport.NAWS)))


def test_telnet_ttype_subnegotiation_survives_recv_fragmentation(tmp_path) -> None:
    transport, capture = _transport(tmp_path)

    first = bytes((transport.IAC, transport.SB, transport.TTYPE))
    second = bytes((transport.SEND, transport.IAC))
    third = bytes((transport.SE,)) + b"prompt>"

    assert transport._process_iac(first) == b""
    assert transport._process_iac(second) == b""
    assert transport._process_iac(third) == b"prompt>"
    assert capture.sent == [
        bytes((transport.IAC, transport.SB, transport.TTYPE, transport.IS))
        + b"xterm-256color"
        + bytes((transport.IAC, transport.SE))
    ]


class _SshServer(paramiko.ServerInterface):
    def __init__(self) -> None:
        self.shell_requested = threading.Event()
        self.resize_requests: list[tuple[int, int]] = []

    def check_auth_password(self, username: str, password: str) -> int:
        return (
            paramiko.AUTH_SUCCESSFUL
            if (username, password) == ("operator", "secret")
            else paramiko.AUTH_FAILED
        )

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(
        self,
        channel,
        term: bytes,
        width: int,
        height: int,
        pixelwidth: int,
        pixelheight: int,
        modes: bytes,
    ) -> bool:
        self.resize_requests.append((width, height))
        return True

    def check_channel_window_change_request(
        self,
        channel,
        width: int,
        height: int,
        pixelwidth: int,
        pixelheight: int,
    ) -> bool:
        self.resize_requests.append((width, height))
        return True

    def check_channel_shell_request(self, channel) -> bool:
        self.shell_requested.set()
        return True


def _start_ssh_server() -> tuple[int, _SshServer, list[bytes], threading.Thread]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    server = _SshServer()
    received: list[bytes] = []

    def run() -> None:
        client, _address = listener.accept()
        transport = paramiko.Transport(client)
        transport.add_server_key(paramiko.RSAKey.generate(1024))
        try:
            transport.start_server(server=server)
            channel = transport.accept(3)
            assert channel is not None
            assert server.shell_requested.wait(3)
            channel.send(b"\x1b[32mLAB-SW\x1b[0m\r\n<LAB-SW>")
            while transport.is_active():
                data = channel.recv(4096)
                if not data:
                    break
                received.append(data)
                channel.send(data + b"<LAB-SW>")
        finally:
            transport.close()
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, server, received, thread


def test_ssh_transport_uses_real_interactive_shell_and_pty(tmp_path) -> None:
    port, server, received, thread = _start_ssh_server()
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("terminal-ssh", display_name="Terminal SSH")
    device = DeviceRepository(Database(paths.site_db_path("terminal-ssh"))).create(
        Device(
            device_uuid="11111111-1111-4111-8111-111111111111",
            name="LAB-SW",
            primary_address="127.0.0.1",
            ssh_enabled=1,
            ssh_username="operator",
            ssh_password="secret",
        )
    )
    target = ConnectionTarget(
        protocol="SSH",
        device_type="hp_comware",
        host="127.0.0.1",
        port=port,
        username="operator",
        password="secret",
    )
    transport = SshInteractiveTransport(
        paths,
        device,
        target,
        site_name="terminal-ssh",
        site_id="terminal-ssh",
    )

    transport.connect(132, 40)
    assert "\x1b[32mLAB-SW\x1b[0m\r\n" in _wait_for_output(transport, "<LAB-SW>")
    transport.write("system-view\r")
    transport.write("\x03")
    assert "system-view\r" in _wait_for_output(transport, "system-view")
    transport.resize(160, 48)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and (160, 48) not in server.resize_requests:
        time.sleep(0.01)
    transport.close()
    thread.join(timeout=3)

    assert received == [b"system-view\r", b"\x03"]
    assert server.resize_requests[0] == (132, 40)
    assert (160, 48) in server.resize_requests


def _start_telnet_server(*, password_only: bool = False) -> tuple[int, list[bytes], threading.Thread]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    received: list[bytes] = []

    def recv_until(client: socket.socket, needle: bytes) -> bytes:
        data = b""
        while needle not in data:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        return data

    def run() -> None:
        client, _address = listener.accept()
        client.settimeout(3)
        try:
            client.sendall(bytes((255,)))
            client.sendall(bytes((253, 24)))
            if not password_only:
                client.sendall(b"login: ")
                received.append(recv_until(client, b"operator\r\n"))
            client.sendall(b"Password: ")
            received.append(recv_until(client, b"secret\r\n"))
            client.sendall(b"\r\n<LAB-TELNET>")
            received.append(recv_until(client, b"system-view\r\n"))
            client.sendall(b"system-view\r\n[LAB-TELNET]")
            received.append(recv_until(client, b"\x03"))
        finally:
            client.close()
            listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, received, thread


def test_telnet_transport_uses_real_iac_login_and_interactive_stream(tmp_path, monkeypatch) -> None:
    port, received, thread = _start_telnet_server()
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("terminal-telnet", display_name="Terminal Telnet")
    monkeypatch.setattr(
        "netconsole.services.terminal_transports.SiteSSHRelayService.open_target_channel",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Telnet must not use the SSH jump-host channel")
        ),
    )
    target = ConnectionTarget(
        protocol="Telnet",
        device_type="hp_comware_telnet",
        host="127.0.0.1",
        port=port,
        username="operator",
        password="secret",
    )
    transport = TelnetInteractiveTransport(paths, target, site_id="terminal-telnet")

    transport.connect(120, 32)
    assert "<LAB-TELNET>" in _wait_for_output(transport, "<LAB-TELNET>")
    transport.write("system-view\r")
    assert "[LAB-TELNET]" in _wait_for_output(transport, "[LAB-TELNET]")
    transport.write("\n中文\r\nnext\n\r")
    transport.write("\r\x03")
    thread.join(timeout=3)
    transport.close()

    assert b"operator\r\n" in received[0]
    assert b"secret\r\n" in received[1]
    assert received[2] == b"system-view\r\n"
    assert received[3] == "中文\r\nnext\r\n\r\n\r\n\x03".encode(target.encoding)


def test_telnet_transport_logs_in_with_password_only(tmp_path) -> None:
    port, received, thread = _start_telnet_server(password_only=True)
    paths = PathResolver(data_root=tmp_path / "data")
    target = ConnectionTarget(
        protocol="Telnet", device_type="hp_comware_telnet", host="127.0.0.1",
        port=port, username="", password="secret",
    )
    transport = TelnetInteractiveTransport(paths, target, site_id="test")
    try:
        transport.connect(120, 32)
        _wait_for_output(transport, "<LAB-TELNET>")
        transport.write("system-view\r")
        _wait_for_output(transport, "[LAB-TELNET]")
        transport.write("\x03")
        thread.join(timeout=3)
    finally:
        transport.close()
    assert not thread.is_alive()
    assert received == [b"\xff\xfb\x18secret\r\n", b"system-view\r\n", b"\x03"]
