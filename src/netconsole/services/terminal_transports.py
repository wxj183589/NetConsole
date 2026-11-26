from __future__ import annotations

import codecs
import os
import re
import socket
import struct
from contextlib import ExitStack
from typing import Any, Protocol

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.host_key_manager import HostKeyManager, HostKeyManagerError
from netconsole.services.host_key_trust_service import (
    HostKeyTrustService,
    finalize_managed_host_key,
    install_managed_host_key_policy,
)
from netconsole.services.netmiko_connection import (
    ConnectionTarget,
    prepared_connection_target,
)
from netconsole.services.site_ssh_relay import SiteSSHRelayService
from netconsole.services.terminal_serial import SerialConnectionOptions


class TerminalTransport(Protocol):
    def connect(self, cols: int, rows: int) -> None: ...
    def read(self, maximum: int = 65536) -> str: ...
    def write(self, data: str) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...
    def close(self) -> None: ...


class SshInteractiveTransport:
    def __init__(
        self,
        paths: PathResolver,
        device: Device,
        target: ConnectionTarget,
        *,
        site_name: str,
        site_id: str,
        managed_device: bool = True,
    ) -> None:
        self.paths = paths
        self.device = device
        self.target = target
        self.site_name = site_name
        self.site_id = site_id
        self.managed_device = managed_device
        self.encoding = target.encoding or "utf-8"
        self._decoder = codecs.getincrementaldecoder(self.encoding)(errors="replace")
        self._stack = ExitStack()
        self._client = None
        self._channel = None
        self._relay_channel = None

    def connect(self, cols: int, rows: int) -> None:
        import paramiko

        trust = HostKeyTrustService(self.paths)
        relay = SiteSSHRelayService(self.paths)
        relay_enabled = bool(relay.load(self.site_id).enabled)
        prepared = self.target
        if not relay_enabled:
            prepared = self._stack.enter_context(prepared_connection_target(self.target, host_key_trust=trust))
        client = paramiko.SSHClient()
        manager = HostKeyManager(self.paths)
        device_id = str(self.device.device_uuid or "").strip()
        managed = self.managed_device and manager.has_device_resource_authority(self.site_name)
        if managed and not manager.is_registered_device(self.site_name, device_id):
            raise HostKeyManagerError(
                "未登记或未授权设备不得自动建立 SSH Host Key 信任。",
                {"device_id": device_id, "host": self.target.host, "port": self.target.port},
                code="HOST_KEY_TARGET_UNAUTHORIZED",
            )
        install_managed_host_key_policy(
            client,
            trust,
            self.target.host,
            int(self.target.port),
            role="target",
            host_key_policy="AUTO_UPDATE" if managed else "AUTO_REPLACE",
            device_id=device_id if managed else "",
            authorized=managed,
            host_key_manager=manager if managed else None,
        )
        sock = None
        try:
            if relay_enabled:
                sock = relay.open_target_channel(self.site_id, self.target.host, int(self.target.port))
                self._relay_channel = sock
            client.connect(
                hostname=prepared.host,
                port=int(prepared.port),
                username=prepared.username,
                password=prepared.password,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10,
                look_for_keys=False,
                allow_agent=False,
                sock=sock,
            )
            if managed:
                finalize_managed_host_key(client, success=True)
            channel = client.invoke_shell(term="xterm-256color", width=int(cols), height=int(rows))
            channel.settimeout(0.0)
            self._client = client
            self._channel = channel
        except BaseException:
            if managed:
                finalize_managed_host_key(client, success=False, failure_reason="terminal_connect_failed")
            client.close()
            if sock is not None:
                sock.close()
            self._stack.close()
            raise

    def read(self, maximum: int = 65536) -> str:
        if self._channel is None:
            raise RuntimeError("SSH shell is not connected")
        if not self._channel.recv_ready():
            if self._channel.closed or not self._channel.active:
                raise ConnectionError("SSH shell closed")
            return ""
        data = self._channel.recv(maximum)
        if not data:
            raise ConnectionError("SSH shell closed")
        return self._decoder.decode(data, final=False)

    def write(self, data: str) -> None:
        if self._channel is None:
            raise RuntimeError("SSH shell is not connected")
        self._channel.sendall(str(data).encode(self.encoding, errors="replace"))

    def resize(self, cols: int, rows: int) -> None:
        if self._channel is not None:
            self._channel.resize_pty(width=int(cols), height=int(rows))

    def close(self) -> None:
        try:
            if self._channel is not None:
                self._channel.close()
            if self._client is not None:
                self._client.close()
            if self._relay_channel is not None:
                self._relay_channel.close()
        finally:
            self._stack.close()
            self._channel = None
            self._client = None
            self._relay_channel = None


class TelnetInteractiveTransport:
    IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
    IS, SEND, ECHO, SGA, TTYPE, NAWS = 0, 1, 1, 3, 24, 31

    MAX_IAC_BUFFER = 65536

    def __init__(self, paths: PathResolver, target: ConnectionTarget, *, site_id: str) -> None:
        self.paths = paths
        self.target = target
        self.site_id = site_id
        self.encoding = target.encoding or "utf-8"
        self._decoder = codecs.getincrementaldecoder(self.encoding)(errors="replace")
        self._stack = ExitStack()
        self._socket: Any | None = None
        self._application_buffer = bytearray()
        self._iac_buffer = bytearray()
        self._cols, self._rows = 120, 32
        self._previous_write_ended_with_cr = False

    def connect(self, cols: int, rows: int) -> None:
        self._cols, self._rows = int(cols), int(rows)
        # Telnet is an independent direct transport. Site SSH jump-host policy
        # applies only to SSH/SFTP and must never wrap the Telnet IAC channel.
        sock = socket.create_connection((self.target.host, int(self.target.port)), timeout=10)
        sock.settimeout(0.2)
        self._socket = sock
        try:
            self._login()
            sock.setblocking(False)
        except BaseException:
            self.close()
            raise

    def _login(self) -> None:
        import time

        deadline = time.monotonic() + 15
        username_sent = not bool(self.target.username)
        password_sent = not bool(self.target.password)
        visible = ""
        while time.monotonic() < deadline and not (username_sent and password_sent):
            try:
                chunk = self._require_socket().recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("Telnet server closed during login")
            visible += self._process_iac(chunk).decode(self.encoding, errors="replace")
            if not username_sent and re.search(r"(?i)(login|username|user\s*name)\s*[:：]\s*$", visible):
                self._send_bytes((self.target.username + "\r\n").encode(self.encoding, errors="replace"))
                username_sent, visible = True, ""
            elif username_sent and not password_sent and re.search(r"(?i)password\s*[:：]\s*$", visible):
                self._send_bytes((self.target.password + "\r\n").encode(self.encoding, errors="replace"))
                password_sent, visible = True, ""
        if not (username_sent and password_sent):
            raise TimeoutError("Telnet login prompt timeout")
        if visible:
            self._application_buffer.extend(visible.encode(self.encoding, errors="replace"))

    def read(self, maximum: int = 65536) -> str:
        if self._application_buffer:
            data = bytes(self._application_buffer[:maximum])
            del self._application_buffer[:maximum]
            return self._decoder.decode(data, final=False)
        try:
            chunk = self._require_socket().recv(maximum)
        except BlockingIOError:
            return ""
        if not chunk:
            raise ConnectionError("Telnet connection closed")
        return self._decoder.decode(self._process_iac(chunk), final=False)

    def write(self, data: str) -> None:
        if not data:
            return
        # xterm emits CR for Enter. Encode each logical newline once for Telnet,
        # including a CRLF pair split across consecutive input messages.
        previous_cr = self._previous_write_ended_with_cr
        self._previous_write_ended_with_cr = data.endswith("\r")
        if previous_cr and data.startswith("\n"):
            data = data[1:]
        data = re.sub(r"\r\n|\r|\n", "\r\n", data)
        self._send_bytes(data.encode(self.encoding, errors="replace").replace(b"\xff", b"\xff\xff"))

    def resize(self, cols: int, rows: int) -> None:
        self._cols, self._rows = int(cols), int(rows)
        payload = struct.pack("!HH", self._cols, self._rows).replace(b"\xff", b"\xff\xff")
        self._send_bytes(bytes((self.IAC, self.SB, self.NAWS)) + payload + bytes((self.IAC, self.SE)))

    def close(self) -> None:
        try:
            if self._socket is not None:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except (OSError, TypeError):
                    pass
                self._socket.close()
        finally:
            self._socket = None
            self._iac_buffer.clear()
            self._stack.close()

    def _process_iac(self, data: bytes) -> bytes:
        pending = bytes(self._iac_buffer) + data
        self._iac_buffer.clear()
        output = bytearray()
        index = 0
        while index < len(pending):
            if pending[index] != self.IAC:
                output.append(pending[index])
                index += 1
                continue
            if index + 1 >= len(pending):
                self._iac_buffer.extend(pending[index:])
                break
            command = pending[index + 1]
            if command == self.IAC:
                output.append(self.IAC)
                index += 2
            elif command in {self.DO, self.DONT, self.WILL, self.WONT}:
                if index + 2 >= len(pending):
                    self._iac_buffer.extend(pending[index:])
                    break
                self._negotiate(command, pending[index + 2])
                index += 3
            elif command == self.SB:
                end = pending.find(bytes((self.IAC, self.SE)), index + 2)
                if end < 0:
                    self._iac_buffer.extend(pending[index:])
                    if len(self._iac_buffer) > self.MAX_IAC_BUFFER:
                        raise ConnectionError("Telnet IAC subnegotiation exceeds limit")
                    break
                self._subnegotiate(pending[index + 2 : end])
                index = end + 2
            else:
                index += 2
        return bytes(output)

    def _negotiate(self, command: int, option: int) -> None:
        if command == self.DO:
            response = self.WILL if option in {self.TTYPE, self.NAWS, self.SGA} else self.WONT
            self._send_bytes(bytes((self.IAC, response, option)))
            if option == self.NAWS and response == self.WILL:
                self.resize(self._cols, self._rows)
        elif command == self.WILL:
            response = self.DO if option in {self.ECHO, self.SGA} else self.DONT
            self._send_bytes(bytes((self.IAC, response, option)))

    def _subnegotiate(self, payload: bytes) -> None:
        if payload[:2] == bytes((self.TTYPE, self.SEND)):
            self._send_bytes(bytes((self.IAC, self.SB, self.TTYPE, self.IS)) + b"xterm-256color" + bytes((self.IAC, self.SE)))

    def _send_bytes(self, data: bytes) -> None:
        self._require_socket().sendall(data)

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("Telnet transport is not connected")
        return self._socket


class SerialInteractiveTransport:
    def __init__(self, options: SerialConnectionOptions, *, serial_factory=None) -> None:
        self.options = options
        self._serial_factory = serial_factory
        self._serial = None
        self.last_written_text = ""
        self._decoder = codecs.getincrementaldecoder(
            "mbcs" if options.encoding == "ansi" else options.encoding
        )(errors="replace")
        self.last_read_bytes = b""

    def connect(self, cols: int, rows: int) -> None:
        try:
            if self._serial_factory is None:
                import ctypes

                import serial
                from serial import win32
                from serial.serialwin32 import Serial as WindowsSerial

                serial_factory = serial.Serial
                if os.name == "nt":
                    options_snapshot = self.options

                    class PreserveUnspecifiedLinesSerial(WindowsSerial):
                        def _reconfigure_port(self):
                            handle = getattr(self, "_port_handle", None)
                            if handle is not None:
                                state = win32.DCB()
                                win32.GetCommState(handle, ctypes.byref(state))
                                if options_snapshot.dtr == "KEEP" and options_snapshot.flow_control != "dsrdtr":
                                    self._dtr_state = state.fDtrControl == win32.DTR_CONTROL_ENABLE
                                if options_snapshot.rts == "KEEP" and options_snapshot.flow_control != "rtscts":
                                    self._rts_state = state.fRtsControl == win32.RTS_CONTROL_ENABLE
                            super()._reconfigure_port()

                    serial_factory = PreserveUnspecifiedLinesSerial
            else:
                serial_factory = self._serial_factory
            options = self.options
            port = serial_factory(
                port=None,
                baudrate=options.baud_rate,
                bytesize=options.data_bits,
                parity=options.parity,
                stopbits=options.stop_bits,
                timeout=options.timeout_seconds,
                write_timeout=2,
                xonxoff=options.flow_control == "xonxoff",
                rtscts=options.flow_control == "rtscts",
                dsrdtr=options.flow_control == "dsrdtr",
            )
            if options.dtr != "KEEP":
                port.dtr = options.dtr == "ON"
            if options.rts != "KEEP":
                port.rts = options.rts == "ON"
            port.port = options.port
            port.open()
            self._serial = port
        except Exception:
            self.close()
            raise

    def read(self, maximum: int = 65536) -> str:
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("串口已断开")
        waiting = int(self._serial.in_waiting or 0)
        data = self._serial.read(min(maximum, max(1, waiting)))
        self.last_read_bytes = bytes(data)
        return self._decoder.decode(data, final=False)

    def write(self, data: str) -> None:
        options = self.options
        value = re.sub(
            r"\r\n|\r|\n",
            {"CR": "\r", "LF": "\n", "CRLF": "\r\n"}[options.line_ending],
            str(data),
        )
        self.last_written_text = value
        self.write_bytes(value.encode("mbcs" if options.encoding == "ansi" else options.encoding, errors="replace"))

    def write_bytes(self, data: bytes) -> None:
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("串口已断开")
        self._serial.write(bytes(data))

    def resize(self, cols: int, rows: int) -> None:
        return None

    def flush(self, direction: str = "both") -> None:
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError("串口已断开")
        if direction in {"input", "both"}:
            self._serial.reset_input_buffer()
        if direction in {"output", "both"}:
            self._serial.reset_output_buffer()

    def close(self) -> None:
        port, self._serial = self._serial, None
        if port is not None and port.is_open:
            port.close()


def create_terminal_transport(
    paths: PathResolver,
    device: Device,
    target: ConnectionTarget,
    *,
    site_name: str,
    site_id: str,
    managed_device: bool = True,
) -> TerminalTransport:
    if target.protocol.casefold() == "ssh":
        return SshInteractiveTransport(
            paths,
            device,
            target,
            site_name=site_name,
            site_id=site_id,
            managed_device=managed_device,
        )
    return TelnetInteractiveTransport(paths, target, site_id=site_id)


__all__ = [
    "SerialInteractiveTransport",
    "SshInteractiveTransport",
    "TelnetInteractiveTransport",
    "TerminalTransport",
    "create_terminal_transport",
]
