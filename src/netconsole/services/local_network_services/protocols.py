from __future__ import annotations

import logging
import ntpath
import os
import re
import shutil
import socket
import socketserver
import stat
import struct
import tempfile
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from threading import BoundedSemaphore, Lock, Thread
from urllib.parse import unquote, urlsplit


def shared_path(root: Path, name: str) -> Path:
    parts = name.split("/")
    if any(
        not part
        or part.startswith(".")
        or part.rstrip(" .") != part
        or any(character in part for character in "\\:\x00")
        or ntpath.isreserved(part)
        for part in parts
    ):
        raise ValueError("invalid shared path")
    candidate = root
    for part in parts:
        candidate = candidate / part
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("linked files are outside the share contract")
    return candidate


class _BoundedThreads(socketserver.ThreadingMixIn):
    daemon_threads = False
    block_on_close = True

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except RuntimeError:
            self.slots.release()
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        self.log.warning("Request from %s failed", client_address[0])


class TcpServer(_BoundedThreads, socketserver.TCPServer):
    def __init__(self, *args, **kwargs):
        self._clients = set()
        self._clients_lock = Lock()
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(self.request_timeout)
        with self._clients_lock:
            self._clients.add(client)
        return client, address

    def close_request(self, request):
        with self._clients_lock:
            self._clients.discard(request)
        super().close_request(request)

    def server_close(self):
        with self._clients_lock:
            for client in self._clients:
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                client.close()
        super().server_close()


class UdpServer(_BoundedThreads, socketserver.UDPServer):
    max_packet_size = 4096

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class SyslogUdpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.log_syslog(self.request[0][:self.server.max_packet_size], self.client_address[0])


class SyslogTcpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        peer = self.client_address[0]
        while not self.server.stopping.is_set():
            line = self.rfile.readline(self.server.max_packet_size + 1)
            if not line:
                return
            if len(line) > self.server.max_packet_size:
                self.server.log.warning("Syslog message exceeded size limit from %s", peer)
                return
            self.server.log_syslog(line, peer)


def parse_syslog(payload: bytes) -> tuple[int, int, str, str]:
    data = payload.rstrip(b"\x00\r\n")[:2048]
    priority = 13
    if data.startswith(b"<"):
        separator = data.find(b">", 1, 5)
        if separator > 1 and data[1:separator].isdigit():
            priority = min(int(data[1:separator]), 191)
            data = data[separator + 1:]
    message = data.decode("utf-8", errors="replace")
    rfc5424 = re.match(r"^(\d+)\s+\S+\s+(\S+)\s+\S+\s+\S+\s+\S+\s+(?:-|\[[^\]]*\])(?:\s+(.*))?$", message)
    if rfc5424:
        hostname, body = rfc5424.group(2), rfc5424.group(3) or ""
    else:
        rfc3164 = re.match(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d\d:\d\d:\d\d\s+(\S+)\s+(.*)$", message)
        if rfc3164:
            hostname, body = rfc3164.groups()
        else:
            hostname, _, body = message.partition(" ")
    return priority // 8, priority % 8, (hostname or "-")[:255], body[:1500]


class SyslogService:
    def __init__(self, servers, workers, timeout):
        self.servers = servers
        self.workers = workers
        self.request_timeout = timeout
        self.stopping = servers[0].stopping

    def serve_forever(self, **kwargs):
        for worker in self.workers:
            worker.start()
        for worker in self.workers:
            worker.join()

    def shutdown(self):
        self.stopping.set()
        for server in self.servers:
            server.shutdown()
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=self.request_timeout + 1)

    def server_close(self):
        for server in self.servers:
            server.server_close()


class HttpHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        self.server.log.info("%s HTTP %s", self.client_address[0], format % args)

    def do_HEAD(self):
        self._send_file(send_body=False)

    def do_GET(self):
        self._send_file(send_body=True)

    def _send_file(self, *, send_body: bool):
        try:
            name = unquote(urlsplit(self.path).path).removeprefix("/")
            path = shared_path(self.server.root, name)
            if not path.is_file():
                raise FileNotFoundError
            source = path.open("rb")
        except (OSError, ValueError):
            self.send_error(404)
            return
        with source:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Disposition", "attachment")
            self.send_header("Content-Length", str(os.fstat(source.fileno()).st_size))
            self.end_headers()
            if send_body:
                shutil.copyfileobj(source, self.wfile)


class DnsHandler(socketserver.BaseRequestHandler):
    def handle(self):
        query, transport = self.request
        if response := dns_reply(query, self.server.records):
            transport.sendto(response, self.client_address)


def dns_reply(query: bytes, records: dict[str, bytes]) -> bytes:
    if not 17 <= len(query) <= 512:
        return b""
    ident, flags, questions, answers, authority, additional = struct.unpack_from("!6H", query)
    if flags & 0xF800 or (questions, answers, authority) != (1, 0, 0) or additional > 1:
        return b""
    labels = []
    offset = 12
    while offset < len(query) and query[offset]:
        length = query[offset]
        if length > 63 or offset + 1 + length >= len(query):
            return b""
        labels.append(query[offset + 1:offset + 1 + length])
        offset += 1 + length
    question_end = offset + 5
    if question_end > len(query):
        return b""
    # Accept an optional empty EDNS OPT record, as sent by ordinary DNS diagnostic clients.
    if additional == 1 and (len(query) != question_end + 11 or query[question_end:question_end + 3] != b"\0\0\x29" or query[-2:] != b"\0\0"):
        return b""
    if not additional and question_end != len(query):
        return b""
    name = b".".join(labels).decode("ascii", errors="replace").lower()
    record_type, record_class = struct.unpack_from("!HH", query, offset + 1)
    answer = b""
    if name in records and record_type == 1 and record_class == 1:
        answer = struct.pack("!HHHIH", 0xC00C, 1, 1, 60, 4) + records[name]
    status = 0x8400 | (flags & 0x0100) | (3 if name not in records else 0)
    return struct.pack("!6H", ident, status, 1, bool(answer), 0, 0) + query[12:question_end] + answer


def _ntp_timestamp() -> bytes:
    seconds, nanoseconds = divmod(time.time_ns(), 1_000_000_000)
    return struct.pack("!II", (seconds + 2_208_988_800) & 0xFFFFFFFF, (nanoseconds << 32) // 1_000_000_000)


class NtpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        query, transport = self.request
        if len(query) != 48 or query[0] & 7 != 3 or (query[0] >> 3) & 7 not in (3, 4):
            return
        received = _ntp_timestamp()
        # Report the host clock as a local reference, without claiming upstream synchronization.
        header = struct.pack("!BBBBII4s", (query[0] & 0x38) | 4, 10, 6, 236, 0, 6553, b"LOCL")
        response = header + received + query[40:48] + received + _ntp_timestamp()
        transport.sendto(response, self.client_address)


class TftpHandler(socketserver.BaseRequestHandler):
    block_size = 512

    def handle(self):
        request, _ = self.request
        if not 6 <= len(request) <= 516:
            return
        opcode = int.from_bytes(request[:2], "big")
        fields = request[2:].split(b"\0")
        if opcode not in (1, 2) or len(fields) < 3 or fields[-1] or fields[1].lower() != b"octet":
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as transfer:
            transfer.bind((self.server.server_address[0], 0))
            transfer.connect(self.client_address)
            transfer.settimeout(self.server.request_timeout)
            try:
                path = shared_path(self.server.root, fields[0].decode("utf-8"))
                if opcode == 1:
                    self._download(transfer, path)
                elif self.server.allow_upload:
                    self._upload(transfer, path)
                else:
                    raise PermissionError
            except FileExistsError:
                transfer.send(b"\0\5\0\6File already exists\0")
            except FileNotFoundError:
                transfer.send(b"\0\5\0\1File not found\0")
            except (PermissionError, ValueError):
                transfer.send(b"\0\5\0\2Access denied\0")
            except OSError:
                self.server.log.warning("TFTP transfer from %s interrupted", self.client_address[0])

    def _exchange(self, transfer: socket.socket, packet: bytes, opcode: int, block: int) -> bytes:
        expected = struct.pack("!HH", opcode, block)
        for _ in range(3):
            if self.server.stopping.is_set():
                break
            transfer.send(packet)
            try:
                response = transfer.recv(517)
                if response[:4] == expected and (len(response) == 4 if opcode == 4 else len(response) <= 516):
                    return response
                if response[:2] == b"\0\5":
                    break
            except TimeoutError:
                continue
        raise TimeoutError

    def _download(self, transfer: socket.socket, path: Path):
        if not path.is_file():
            raise FileNotFoundError
        with path.open("rb") as source:
            if os.fstat(source.fileno()).st_size >= self.block_size * 65535:
                raise PermissionError
            for block in range(1, 65536):
                data = source.read(self.block_size)
                self._exchange(transfer, struct.pack("!HH", 3, block) + data, 4, block)
                if len(data) < self.block_size:
                    self.server.log.info("TFTP download completed for %s", self.client_address[0])
                    return

    def _upload(self, transfer: socket.socket, path: Path):
        if path.exists():
            raise FileExistsError
        if not path.parent.is_dir():
            raise FileNotFoundError
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tftp-", delete=False) as target:
            temporary = Path(target.name)
            try:
                for block in range(1, 16385):
                    data = self._exchange(transfer, struct.pack("!HH", 4, block - 1), 3, block)[4:]
                    target.write(data)
                    if len(data) < self.block_size:
                        target.close()
                        os.link(temporary, path)
                        transfer.send(struct.pack("!HH", 4, block))
                        self.server.log.info("TFTP upload completed from %s", self.client_address[0])
                        return
                raise PermissionError
            finally:
                target.close()
                temporary.unlink(missing_ok=True)


def create_server(kind, config, root, log: logging.Logger, stopping):
    if kind == "syslog":
        return create_syslog_server(config, log, stopping)
    handlers = {"http": HttpHandler, "dns": DnsHandler, "ntp": NtpHandler, "tftp": TftpHandler}
    server_class = TcpServer if kind == "http" else UdpServer
    server = server_class((config.address, config.port), handlers[kind], bind_and_activate=False)
    server.root = root
    server.slots = BoundedSemaphore(config.max_connections)
    server.request_timeout = config.timeout
    server.allow_upload = config.allow_upload
    server.records = {name: socket.inet_aton(address) for name, address in config.dns_records.items()}
    server.log = log
    server.stopping = stopping
    try:
        server.server_bind()
        server.server_activate()
    except OSError:
        server.server_close()
        raise
    return server


def create_syslog_server(config, log, stopping):
    if config.port == 65535:
        raise ValueError("syslog_udp_port_has_no_tcp_pair")

    def initialize(server):
        server.slots = BoundedSemaphore(config.max_connections)
        server.request_timeout = config.timeout
        server.max_packet_size = 4096
        server.log = log
        server.stopping = stopping
        server.log_syslog = lambda payload, peer: _write_syslog(log, payload, peer)
        server.server_bind()
        server.server_activate()

    udp = UdpServer((config.address, config.port), SyslogUdpHandler, bind_and_activate=False)
    servers = [udp]
    try:
        initialize(udp)
        tcp = TcpServer((config.address, config.port + 1), SyslogTcpHandler, bind_and_activate=False)
        servers.append(tcp)
        initialize(tcp)
    except OSError:
        for server in servers:
            server.server_close()
        raise
    servers = tuple(servers)
    workers = tuple(
        Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        for server in servers
    )
    return SyslogService(servers, workers, config.timeout)


def _write_syslog(log, payload, peer):
    facility, severity, hostname, message = parse_syslog(payload)
    log.info(
        "Syslog source=%s facility=%d severity=%d hostname=%s message=%s",
        peer,
        facility,
        severity,
        hostname,
        message,
    )
