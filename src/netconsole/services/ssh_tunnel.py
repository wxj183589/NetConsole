from __future__ import annotations

import select
import socket
import socketserver
import threading
from dataclasses import dataclass

from netconsole.core.paths import PathResolver
from netconsole.services.connection_manager import TunnelProfile
from netconsole.services.host_key_trust_service import (
    HostKeyTrustError,
    HostKeyTrustGrant,
    HostKeyTrustService,
    host_key_mismatch_error,
    install_managed_host_key_policy,
)


class TunnelConnectionError(RuntimeError):
    def __init__(self, code: str, message: str, *, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(message)


class _ForwardState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.channels: set[object] = set()
        self.last_error: BaseException | None = None

    def add(self, channel: object) -> None:
        with self.lock:
            self.channels.add(channel)

    def discard(self, channel: object) -> None:
        with self.lock:
            self.channels.discard(channel)

    def fail(self, error: BaseException) -> None:
        with self.lock:
            self.last_error = error

    def close(self) -> None:
        with self.lock:
            channels = tuple(self.channels)
            self.channels.clear()
        for channel in channels:
            try:
                channel.close()
            except Exception:
                pass


@dataclass
class TunnelSession:
    local_host: str
    local_port: int
    remote_host: str
    remote_port: int
    tunnel: TunnelProfile
    client: object
    server: socketserver.ThreadingTCPServer
    thread: threading.Thread
    forward_state: _ForwardState

    @property
    def forward_error(self) -> BaseException | None:
        return self.forward_state.last_error

    def close(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass
        self.forward_state.close()
        try:
            self.client.close()
        except Exception:
            pass
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)


class TunnelManager:
    def __init__(
        self,
        *,
        strict_host_keys: bool = True,
        host_key_trust: HostKeyTrustService | None = None,
        host_key_grant: HostKeyTrustGrant
        | tuple[HostKeyTrustGrant, ...]
        | None = None,
    ) -> None:
        self.strict_host_keys = bool(strict_host_keys)
        self.host_key_trust = host_key_trust
        self.host_key_grant = host_key_grant

    def open_tunnel(self, tunnel: TunnelProfile, remote_host: str, remote_port: int) -> TunnelSession:
        import paramiko

        local_host = "127.0.0.1"
        local_port = 0
        client = paramiko.SSHClient()
        if self.strict_host_keys:
            trust = self.host_key_trust or HostKeyTrustService(PathResolver())
            install_managed_host_key_policy(
                client,
                trust,
                tunnel.host,
                int(tunnel.port or 22),
                role="jump",
                grant=self.host_key_grant,
            )
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=tunnel.host,
                port=int(tunnel.port or 22),
                username=tunnel.username,
                password=tunnel.password,
                timeout=20,
                banner_timeout=20,
                auth_timeout=20,
                look_for_keys=False,
                allow_agent=False,
            )
            transport = client.get_transport()
            if transport is None:
                raise TunnelConnectionError(
                    "DEVICE_FILE_FORWARD_OPEN_FAILED",
                    "跳板机已认证，但 SSH 转发通道不可用。",
                    stage="forward_open",
                )
            forward_state = _ForwardState()
            handler = _make_forward_handler(
                transport,
                remote_host,
                int(remote_port),
                forward_state,
            )
            server = socketserver.ThreadingTCPServer((local_host, local_port), handler)
            server.daemon_threads = True
            actual_port = int(server.server_address[1])
            thread = threading.Thread(target=server.serve_forever, name=f"netconsole-tunnel-{actual_port}", daemon=True)
            thread.start()
            return TunnelSession(
                local_host,
                actual_port,
                remote_host,
                int(remote_port),
                tunnel,
                client,
                server,
                thread,
                forward_state,
            )
        except paramiko.BadHostKeyException as exc:
            try:
                client.close()
            except Exception:
                pass
            trust = self.host_key_trust or HostKeyTrustService(PathResolver())
            raise host_key_mismatch_error(
                trust,
                tunnel.host,
                int(tunnel.port or 22),
                getattr(exc, "got_key", None),
                role="jump",
            ) from exc
        except HostKeyTrustError:
            try:
                client.close()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            if isinstance(exc, TunnelConnectionError):
                raise
            raise _classify_jump_connection_error(exc) from exc


def _make_forward_handler(
    transport,
    remote_host: str,
    remote_port: int,
    state: _ForwardState,
):
    class ForwardHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                channel = transport.open_channel(
                    "direct-tcpip",
                    (remote_host, remote_port),
                    self.request.getpeername(),
                )
            except Exception as exc:
                state.fail(exc)
                return
            if channel is None:
                state.fail(RuntimeError("direct-tcpip channel unavailable"))
                return
            state.add(channel)
            try:
                while True:
                    readable, _, _ = select.select([self.request, channel], [], [], 1)
                    if self.request in readable:
                        data = self.request.recv(1024)
                        if not data:
                            break
                        channel.sendall(data)
                    if channel in readable:
                        data = channel.recv(1024)
                        if not data:
                            break
                        self.request.sendall(data)
            finally:
                try:
                    channel.close()
                except Exception:
                    pass
                state.discard(channel)
                try:
                    self.request.close()
                except Exception:
                    pass

    return ForwardHandler


def _classify_jump_connection_error(exc: BaseException) -> TunnelConnectionError:
    name = exc.__class__.__name__.casefold()
    text = str(exc or "").casefold()
    if name in {
        "authenticationexception",
        "badauthenticationtype",
        "passwordrequiredexception",
    } or any(
        marker in text
        for marker in (
            "authentication failed",
            "auth failed",
            "invalid password",
            "permission denied",
        )
    ):
        return TunnelConnectionError(
            "DEVICE_FILE_JUMP_HOST_AUTH_FAILED",
            "跳板机 SSH 认证失败，请检查隧道用户名和密码。",
            stage="jump_auth",
        )
    return TunnelConnectionError(
        "DEVICE_FILE_JUMP_HOST_UNREACHABLE",
        "跳板机网络不可达、连接超时或 SSH 端口不可用。",
        stage="jump_connect",
    )


def reserve_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
