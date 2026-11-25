import secrets
import errno
import socket
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.ioloop import IOLoop
from pyftpdlib.servers import FTPServer

try:
    from pyftpdlib.handlers import TLS_FTPHandler
except ImportError:
    TLS_FTPHandler = None

from netconsole.services.local_network_services.protocols import shared_path

FTP_USERNAME = "netconsole"


class FtpShare(AbstractedFS):
    def open(self, filename, mode):
        # Exclusive creation preserves existing files under concurrent uploads.
        if "a" in mode or "+" in mode:
            raise PermissionError("FTP overwrite is disabled")
        return super().open(filename, mode.replace("w", "x"))

    def validpath(self, path):
        try:
            relative = Path(path).relative_to(self.root)
            if relative.parts:
                shared_path(Path(self.root), relative.as_posix())
        except (OSError, ValueError):
            return False
        return super().validpath(path)


class RestrictedPassiveDtp(FTPHandler.passive_dtp):
    def __init__(self, cmd_channel, extmode=False):
        try:
            super().__init__(cmd_channel, extmode)
        except OSError:
            self.close()
            cmd_channel.respond("425 Configured passive port range is unavailable.")

    def bind(self, address):
        if address[1] == 0 and self.cmd_channel.passive_ports is not None:
            raise OSError(errno.EACCES, "Configured passive port range is unavailable")
        return super().bind(address)

    def listen(self, backlog):
        ports = self.cmd_channel.passive_ports
        if ports is not None and self.socket.getsockname()[1] not in ports:
            raise OSError(errno.EACCES, "Configured passive port range is unavailable")
        return super().listen(backlog)


class PassiveFtpMixin:
    auth_failed_timeout = 1
    passive_dtp = RestrictedPassiveDtp

    def ftp_PORT(self, line):
        self.respond("502 Active FTP is disabled.")

    def ftp_EPRT(self, line):
        self.respond("502 Active FTP is disabled.")


class PassiveFtpHandler(PassiveFtpMixin, FTPHandler):
    abstracted_fs = FtpShare


class PassiveTlsFtpHandler(PassiveFtpMixin, TLS_FTPHandler if TLS_FTPHandler is not None else FTPHandler):
    abstracted_fs = FtpShare


class LocalFtpServer:
    def __init__(self, config, root, logger, stopping, tls_certificate=None, *, password=None):
        self.password = password or secrets.token_urlsafe(18)
        self.stopping = stopping
        if tls_certificate is not None and TLS_FTPHandler is None:
            raise RuntimeError("FTPS requires the pyOpenSSL runtime dependency")
        authorizer = DummyAuthorizer()
        authorizer.add_user(config.ftp_username, self.password, str(root), perm="elrw" if config.allow_upload else "elr")

        handler_base = PassiveTlsFtpHandler if tls_certificate is not None else PassiveFtpHandler

        class Handler(handler_base):
            def on_file_sent(self, file):
                logger.info("FTP download completed for %s", self.remote_ip)

            def on_file_received(self, file):
                logger.info("FTP upload completed for %s", self.remote_ip)

            def on_login(self, username):
                logger.info("FTP login accepted from %s", self.remote_ip)

            def on_login_failed(self, username, password):
                logger.warning("FTP login rejected from %s", self.remote_ip)

        Handler.authorizer = authorizer
        Handler.timeout = config.timeout
        if config.passive_ports is not None:
            start, end = config.passive_ports
            Handler.passive_ports = range(start, end + 1)
        if tls_certificate is not None:
            Handler.certfile = str(tls_certificate[0])
            Handler.keyfile = str(tls_certificate[1])
            Handler.tls_control_required = True
            Handler.tls_data_required = True
        listener = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((config.address, config.port))
            self.server = FTPServer(listener, Handler, ioloop=IOLoop.factory())
        except Exception:
            listener.close()
            raise
        self.server.max_cons = config.max_connections * 2 + 1
        self.server.max_cons_per_ip = config.max_connections * 2

    def serve_forever(self, poll_interval=0.1):
        while not self.stopping.is_set():
            self.server.ioloop.loop(timeout=poll_interval, blocking=False)

    def shutdown(self):
        self.stopping.set()

    def server_close(self):
        self.server.close_all()
