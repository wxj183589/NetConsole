from __future__ import annotations

import logging
import json
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
from queue import Empty, Full, Queue
from threading import BoundedSemaphore, Event, Lock, Thread
from urllib.parse import unquote, urlsplit

from netconsole.services.system_maintenance_redaction import redact_system_maintenance_text


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
        self.ssl_context = None
        self.request_timeout = 3
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()
        if self.ssl_context is not None:
            self.socket = self.ssl_context.wrap_socket(
                self.socket,
                server_side=True,
                do_handshake_on_connect=False,
            )

    def get_request(self):
        client, address = super().get_request()
        client.settimeout(self.request_timeout)
        with self._clients_lock:
            self._clients.add(client)
        return client, address

    def finish_request(self, request, client_address):
        # Perform TLS negotiation inside a bounded request worker.
        if self.ssl_context is not None:
            request.do_handshake()
        super().finish_request(request, client_address)

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


class SyslogUdpServer(UdpServer):
    def process_request(self, request, client_address):
        # Queue UDP datagrams without a new thread or disk IO per message.
        self.finish_request(request, client_address)


class SyslogTcpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        peer = self.client_address[0]
        while not self.server.stopping.is_set():
            frame = self._read_frame(peer)
            if frame is None:
                return
            if frame:
                self.server.log_syslog(frame, peer)

    def _read_frame(self, peer: str) -> bytes | None:
        first = self.rfile.read(1)
        if not first:
            return None
        if not first.isdigit():
            return self._read_line_frame(first, peer)

        prefix = bytearray(first)
        while len(prefix) <= 10:
            character = self.rfile.read(1)
            if not character:
                return None
            if character == b" ":
                length = int(prefix)
                if not 0 < length <= self.server.max_packet_size:
                    self.server.log.warning("Syslog octet-counted frame size is invalid from %s", peer)
                    return None
                payload = self.rfile.read(length)
                if len(payload) != length:
                    self.server.log.warning("Syslog octet-counted frame is truncated from %s", peer)
                    return None
                return payload
            if character.isdigit():
                prefix.extend(character)
                continue
            return self._read_line_frame(bytes(prefix) + character, peer)

        self.server.log.warning("Syslog octet-counted frame length is invalid from %s", peer)
        return None

    def _read_line_frame(self, prefix: bytes, peer: str) -> bytes | None:
        remaining = self.server.max_packet_size + 1 - len(prefix)
        frame = prefix + self.rfile.readline(max(0, remaining))
        if len(frame) > self.server.max_packet_size:
            self.server.log.warning("Syslog message exceeded size limit from %s", peer)
            return None
        return frame.rstrip(b"\r\n")



def parse_syslog_record(payload: bytes) -> dict[str, object]:
    data = payload.rstrip(b"\x00\r\n")[:2048]
    raw = data.decode("utf-8", errors="replace")
    priority = 13
    if data.startswith(b"<"):
        separator = data.find(b">", 1, 5)
        if separator > 1 and data[1:separator].isdigit():
            priority = min(int(data[1:separator]), 191)
            data = data[separator + 1:]
    message = data.decode("utf-8", errors="replace")
    format_name, timestamp, app_name = "unstructured", "", ""
    rfc5424 = re.match(r"^(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+\S+\s+\S+\s+(?:-|\[[^\]]*\])(?:\s+(.*))?$", message)
    if rfc5424:
        format_name = "rfc5424"
        timestamp, hostname, app_name, body = rfc5424.group(2), rfc5424.group(3), rfc5424.group(4), rfc5424.group(5) or ""
    else:
        rfc3164 = re.match(r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d\d:\d\d:\d\d)\s+(\S+)\s+(.*)$", message)
        if rfc3164:
            format_name = "rfc3164"
            timestamp, hostname, body = rfc3164.groups()
            if ":" in body:
                app_name, body = (part.strip() for part in body.split(":", 1))
        else:
            hostname, _, body = message.partition(" ")
    return {
        "format": format_name,
        "timestamp": timestamp[:64],
        "facility": priority // 8,
        "severity": priority % 8,
        "hostname": (hostname or "-")[:255],
        "app_name": app_name[:128],
        "message": body[:1500],
        "raw": raw,
    }


def parse_syslog(payload: bytes) -> tuple[int, int, str, str]:
    record = parse_syslog_record(payload)
    return int(record["facility"]), int(record["severity"]), str(record["hostname"]), str(record["message"])


class SyslogService:
    def __init__(self, servers, workers, timeout, receivers_stopped):
        self.servers = servers
        self.workers = workers
        self.request_timeout = timeout
        self.stopping = servers[0].stopping
        self.receivers_stopped = receivers_stopped

    def serve_forever(self, **kwargs):
        for worker in self.workers:
            worker.start()
        for worker in self.workers:
            worker.join()

    def shutdown(self):
        self.stopping.set()
        for server in self.servers:
            server.shutdown()
        for server in self.servers:
            server.server_close()
        self.receivers_stopped.set()
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


def create_server(kind, config, root, log: logging.Logger, stopping, *, ssl_context=None):
    if kind == "syslog":
        return create_syslog_server(config, log, stopping)
    handlers = {"http": HttpHandler, "https": HttpHandler, "dns": DnsHandler, "ntp": NtpHandler, "tftp": TftpHandler}
    server_class = TcpServer if kind in {"http", "https"} else UdpServer
    server = server_class((config.address, config.port), handlers[kind], bind_and_activate=False)
    server.ssl_context = ssl_context
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

    pending = Queue(maxsize=4096)
    receivers_stopped = Event()
    counts = {"received": 0, "dropped": 0}
    count_lock = Lock()

    def enqueue(payload, peer):
        with count_lock:
            counts["received"] += 1
            try:
                pending.put_nowait((payload, peer))
            except Full:
                counts["dropped"] += 1

    def write_messages():
        while not receivers_stopped.is_set() or not pending.empty():
            try:
                payload, peer = pending.get(timeout=0.1)
            except Empty:
                continue
            _write_syslog(log, payload, peer)
        log.info("Syslog receiver stopped received=%d dropped=%d", counts["received"], counts["dropped"])

    def initialize(server):
        server.slots = BoundedSemaphore(config.max_connections)
        server.request_timeout = config.timeout
        server.max_packet_size = 4096
        server.log = log
        server.stopping = stopping
        server.log_syslog = enqueue
        server.server_bind()
        server.server_activate()

    udp = SyslogUdpServer((config.address, config.port), SyslogUdpHandler, bind_and_activate=False)
    udp.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1_048_576)
    servers = [udp]
    try:
        initialize(udp)
        tcp = TcpServer((config.address, config.port), SyslogTcpHandler, bind_and_activate=False)
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
    ) + (Thread(target=write_messages, daemon=True),)
    return SyslogService(servers, workers, config.timeout, receivers_stopped)


def _write_syslog(log, payload, peer):
    record = parse_syslog_record(payload)
    record["message"] = redact_system_maintenance_text(record["message"])
    record["raw"] = redact_system_maintenance_text(record["raw"])
    record["source"] = peer
    log.info("Syslog %s", json.dumps(record, ensure_ascii=False, separators=(",", ":")))
