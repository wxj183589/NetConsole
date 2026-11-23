from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from zipfile import ZipFile

import paramiko

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.site_manager import SiteManager
from netconsole.services.terminal_workspace import TerminalSessionManager
from test_terminal_workspace import _wait_until


@contextmanager
def ssh_lab():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    key = paramiko.RSAKey.generate(2048)
    stop = threading.Event()
    transports, peers, auth, ptys, shells = [], [], [], [], []
    received = {}
    refuse = threading.Event()

    class Server(paramiko.ServerInterface):
        def __init__(self, index):
            self.index = index

        def check_auth_password(self, username, password):
            auth.append(self.index)
            return paramiko.AUTH_FAILED if refuse.is_set() else paramiko.AUTH_SUCCESSFUL

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED

        def check_channel_pty_request(self, *args):
            ptys.append(self.index)
            return True

        def check_channel_shell_request(self, channel):
            shells.append(self.index)

            def run():
                try:
                    channel.send(b"<LAB>")
                    buffer = b""
                    while data := channel.recv(65536):
                        received[self.index].append(data)
                        channel.send(data)
                        buffer += data
                        while b"\r" in buffer:
                            command, buffer = buffer.split(b"\r", 1)
                            channel.send(
                                b"\r\nresult:"
                                + command
                                + b"\r\npassword hash $test\r\n<LAB>"
                            )
                except OSError:
                    pass

            threading.Thread(target=run, daemon=True).start()
            return True

    def accept():
        while not stop.is_set():
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            index = len(peers)
            peers.append(peer)
            received[index] = []
            transport = paramiko.Transport(connection)
            transports.append(transport)
            transport.add_server_key(key)
            try:
                transport.start_server(server=Server(index))
            except (EOFError, paramiko.SSHException):
                pass

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], peers, auth, ptys, shells, received, refuse
    finally:
        stop.set()
        thread.join(timeout=2)
        listener.close()
        for transport in transports:
            transport.close()


def manager_device(tmp_path, port, protocol="SSH"):
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
    )
    SiteManager(paths).create_site("lab")
    device = DeviceRepository(Database(paths.site_db_path("lab"))).create(
        Device(
            name="LAB",
            primary_address="127.0.0.1",
            ssh_enabled=int(protocol == "SSH"),
            ssh_port=port,
            ssh_username="operator",
            ssh_password="test",
            telnet_enabled=int(protocol == "TELNET"),
            telnet_port=port,
            telnet_username="operator",
            telnet_password="test",
        )
    )
    return TerminalSessionManager(paths), device


def test_real_ssh_twelve_tcp_connections_unique_ptys_batch_and_recordings(tmp_path):
    with ssh_lab() as (port, peers, auth, ptys, shells, received, refuse):
        manager, device = manager_device(tmp_path, port)
        try:
            ids = []
            for _ in range(12):
                item, _ = manager.create_session(device.device_uuid)
                ids.append(item["session_id"])
                _wait_until(
                    lambda: manager.get_runtime(ids[-1]).snapshot.state == "RUNNING",
                    timeout=6,
                )
            assert (
                len(set(ids))
                == len(set(peers))
                == len(auth)
                == len(ptys)
                == len(shells)
                == 12
            )
            for index, session_id in enumerate(ids):
                manager.input(session_id, f"display unique-{index}\r")
            _wait_until(
                lambda: all(
                    any(f"unique-{index}".encode() in data for data in received[index])
                    for index in range(12)
                )
            )
            job = manager.dispatcher.submit(
                ids[:2], "display selected\r", scope="selected"
            )
            _wait_until(
                lambda: all(
                    row["state"] == "SENT"
                    for row in manager.dispatcher.get(job["id"])["rows"]
                )
            )
            assert b"selected" not in b"".join(received[2])
            manager.close_session(ids[0])
            _wait_until(lambda: manager.get_runtime(ids[0]).snapshot.state == "CLOSED")
            manager.input(ids[1], "display still-alive\r")
            _wait_until(lambda: b"still-alive" in b"".join(received[1]))
            partial = manager.dispatcher.submit(
                ids[:2], "display after-peer-close\r", scope="selected"
            )
            _wait_until(
                lambda: all(
                    row["state"] in {"SENT", "FAILED"}
                    for row in manager.dispatcher.get(partial["id"])["rows"]
                )
            )
            assert [
                row["state"] for row in manager.dispatcher.get(partial["id"])["rows"]
            ] == ["FAILED", "SENT"]
            _wait_until(lambda: b"after-peer-close" in b"".join(received[1]))
            assert b"after-peer-close" not in b"".join(received[2])
            refuse.set()
            failed, _ = manager.create_session(device.device_uuid)
            _wait_until(
                lambda: (
                    manager.get_runtime(failed["session_id"]).snapshot.state == "FAILED"
                )
            )
            assert (
                "Authentication failed"
                in manager.get_runtime(failed["session_id"]).snapshot.error_message
            )
            assert manager.get_runtime(ids[1]).snapshot.state == "RUNNING"
        finally:
            manager.close()
        for index, session_id in enumerate(ids):
            log, _ = manager.export_path(session_id, "log")
            archive, _ = manager.export_path(session_id, "zip")
            text = log.read_text(encoding="utf-8")
            assert f"display unique-{index}" in text and "password hash $test" in text
            assert all(
                f"result:display unique-{other}\n" not in text
                for other in range(12)
                if other != index
            )
            with ZipFile(archive) as zipped:
                assert zipped.namelist() == [log.name] and zipped.testzip() is None


def test_real_telnet_iac_command_pager_and_recording(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    received = []

    def server():
        client, _ = listener.accept()
        with client:
            client.sendall(b"Username:")
            client.recv(100)
            client.sendall(b"Password:")
            client.recv(100)
            client.sendall(b"<TELNET>")
            command = client.recv(100)
            received.append(command)
            client.sendall(command + "\r\n中文配置\r\n---- More ----".encode())
            received.append(client.recv(100))
            client.sendall(b"\r               \rinterface Vlan-interface1\r\n<TELNET>")
            while client.recv(100):
                pass
        listener.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    manager, device = manager_device(tmp_path, port, "TELNET")
    try:
        item, _ = manager.create_session(device.device_uuid, protocol="TELNET")
        session_id = item["session_id"]
        _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING")
        manager.input(session_id, "display current-configuration\r")
        _wait_until(
            lambda: any(
                "More" in str(event.get("data"))
                for event in manager.recording_events(session_id)
            )
        )
        manager.input(session_id, " ")
        _wait_until(lambda: len(received) == 2)
        _wait_until(
            lambda: any(
                "Vlan-interface1" in str(event.get("data"))
                for event in manager.recording_events(session_id)
            )
        )
    finally:
        manager.close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    log, _ = manager.export_path(session_id, "log")
    text = log.read_text(encoding="utf-8")
    assert text.count("display current-configuration") == 1
    assert (
        "More" not in text
        and "中文配置" in text
        and "interface Vlan-interface1" in text
    )
