import secrets
import socket
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.ioloop import IOLoop
from pyftpdlib.servers import FTPServer

from netconsole.services.local_network_services.protocols import shared_path

FTP_USERNAME = "netconsole"


class FtpShare(AbstractedFS):
    def validpath(self, path):
        try:
            relative = Path(path).relative_to(self.root)
            if relative.parts:
                shared_path(Path(self.root), relative.as_posix())
        except (OSError, ValueError):
            return False
        return super().validpath(path)


class PassiveFtpHandler(FTPHandler):
    abstracted_fs = FtpShare
    auth_failed_timeout = 1

    def ftp_PORT(self, line):
        self.respond("502 Active FTP is disabled.")

    def ftp_EPRT(self, line):
        self.respond("502 Active FTP is disabled.")


class LocalFtpServer:
    def __init__(self, config, root, logger, stopping):
        self.password = secrets.token_urlsafe(18)
        self.stopping = stopping
        authorizer = DummyAuthorizer()
        authorizer.add_user(FTP_USERNAME, self.password, str(root), perm="elr")

        class Handler(PassiveFtpHandler):
            def on_file_sent(self, file):
                logger.info("FTP download completed for %s", self.remote_ip)

        Handler.authorizer = authorizer
        Handler.timeout = config.timeout
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
