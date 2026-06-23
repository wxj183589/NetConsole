from __future__ import annotations

import select
import socket
import socketserver
import threading
from dataclasses import dataclass

from netconsole.services.connection_manager import TunnelProfile


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

    def close(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass
        try:
            self.client.close()
        except Exception:
            pass


class TunnelManager:
    def open_tunnel(self, tunnel: TunnelProfile, remote_host: str, remote_port: int) -> TunnelSession:
        import paramiko

        local_host = "127.0.0.1"
        local_port = int(tunnel.local_port or 0)
        client = paramiko.SSHClient()
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
                raise RuntimeError("SSH tunnel transport unavailable")
            handler = _make_forward_handler(transport, remote_host, int(remote_port))
            server = socketserver.ThreadingTCPServer((local_host, local_port), handler)
            server.daemon_threads = True
            actual_port = int(server.server_address[1])
            thread = threading.Thread(target=server.serve_forever, name=f"netconsole-tunnel-{actual_port}", daemon=True)
            thread.start()
            return TunnelSession(local_host, actual_port, remote_host, int(remote_port), tunnel, client, server, thread)
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            raise


def _make_forward_handler(transport, remote_host: str, remote_port: int):
    class ForwardHandler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            try:
                channel = transport.open_channel(
                    "direct-tcpip",
                    (remote_host, remote_port),
                    self.request.getpeername(),
                )
            except Exception:
                return
            if channel is None:
                return
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
                try:
                    self.request.close()
                except Exception:
                    pass

    return ForwardHandler


def reserve_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
