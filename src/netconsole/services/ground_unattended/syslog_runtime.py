from __future__ import annotations

import hashlib
import json
import queue
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.online_mr_terminal_log_parser import (
    parse_active_link_switch_logs,
)


_HOSTNAME_RE = re.compile(
    r"^(?:<\d+>)?(?:\*|%|#)?(?:[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?::\d{1,3})?(?:\s+\d{4})?\s+)?(?P<hostname>[A-Za-z0-9_.-]+)\s+WMESH/",
    re.IGNORECASE,
)
_EVENT_RE = re.compile(r"WMESH/\d+/(?P<event>MESH_LINKUP|MESH_LINKDOWN|MESH_ACTIVELINK_SWITCH)\s*:", re.IGNORECASE)
_PEER_RE = re.compile(
    r"(?:(?:peer|link)(?:\s+(?:name|ap))?\s*[=:]\s*)?"
    r"(?P<name>[A-Za-z0-9_.-]+)[_\s]+(?P<mac>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})",
    re.IGNORECASE,
)
_DEVICE_TIME_RE = re.compile(
    r"(?:<\d+>)?[*%#]?(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})(?::(?P<millisecond>\d{1,3}))?"
    r"(?:\s+(?P<year>\d{4}))?",
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}


@dataclass(frozen=True)
class UdpEnvelope:
    source_ip: str
    source_port: int
    receive_time: str
    payload: bytes


@dataclass
class _OpenRawFile:
    file_id: str
    path: Path
    relative_path: str
    handle: Any
    start_time: str
    record_count: int = 0


class RawStreamWriter:
    """单线程顺序追加原始 NDJSON，并在轮转边界登记不可变文件。"""

    def __init__(
        self,
        *,
        root: Path,
        repository: GroundUnattendedRepository,
        site_id: str,
        run_id: str,
        run_date: str,
        data_type: str,
        directory_name: str | None = None,
        flush_records: int = 100,
        flush_interval_seconds: float = 1.0,
    ) -> None:
        self.root = Path(root)
        self.repository = repository
        self.site_id = site_id
        self.run_id = run_id
        self.run_date = run_date
        self.data_type = data_type
        self.directory_name = directory_name or data_type
        self.flush_records = max(1, int(flush_records))
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self._generation = uuid.uuid4().hex[:8]
        self._files: dict[tuple[str, str, str], _OpenRawFile] = {}
        self._last_flush = time.monotonic()
        self.records_written = 0
        self.bytes_written = 0
        self.last_write_duration_ms = 0.0

    @property
    def open_file_count(self) -> int:
        return len(self._files)

    def write(self, record: dict[str, Any], received_at: datetime) -> tuple[str, int]:
        started = time.perf_counter()
        train_id = _safe_component(str(record.get("train_id") or "_unidentified"))
        role = _safe_component(str(record.get("mr_role") or record.get("source_ip") or "unknown"))
        hour = received_at.strftime("%Y-%m-%d_%H")
        key = (train_id, role, hour)
        for current_key in tuple(self._files):
            if current_key[:2] == key[:2] and current_key[2] != hour:
                self._close_one(current_key, received_at.isoformat(timespec="milliseconds"))
        current = self._files.get(key)
        if current is None:
            current = self._open(key, received_at, record)
        encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        current.handle.write(encoded.decode("utf-8"))
        current.record_count += 1
        self.records_written += 1
        self.bytes_written += len(encoded)
        if (
            current.record_count % self.flush_records == 0
            or time.monotonic() - self._last_flush >= self.flush_interval_seconds
        ):
            current.handle.flush()
            self._last_flush = time.monotonic()
        self.last_write_duration_ms = (time.perf_counter() - started) * 1000
        return current.file_id, current.record_count

    def close(self) -> None:
        ended_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        for key in tuple(self._files):
            self._close_one(key, ended_at)

    def _open(
        self,
        key: tuple[str, str, str],
        received_at: datetime,
        record: dict[str, Any],
    ) -> _OpenRawFile:
        train_id, role, hour = key
        date_text, hour_text = hour.rsplit("_", 1)
        path = self.root / self.directory_name / train_id / role / date_text / f"{hour_text}_{self._generation}.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        relative = path.relative_to(self.repository.db_path.parent).as_posix()
        file_id = f"raw_{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:32]}"
        started_at = received_at.isoformat(timespec="milliseconds")
        current = _OpenRawFile(
            file_id=file_id,
            path=path,
            relative_path=relative,
            handle=path.open("a", encoding="utf-8", newline="\n"),
            start_time=started_at,
        )
        self._files[key] = current
        self.repository.upsert_raw_file(
            {
                "file_id": file_id,
                "run_id": self.run_id,
                "train_id": "" if train_id == "_unidentified" else train_id,
                "device_id": record.get("device_id"),
                "device_uuid": str(
                    record.get("device_uuid") or record.get("mr_id") or ""
                ),
                "mr_role": "" if train_id == "_unidentified" else role,
                "data_type": self.data_type,
                "relative_path": relative,
                "start_time": started_at,
                "status": "OPEN",
                "archive_status": "PENDING",
                "parse_status": "STREAMING",
            }
        )
        return current

    def _close_one(self, key: tuple[str, str, str], ended_at: str) -> None:
        current = self._files.pop(key, None)
        if current is None:
            return
        current.handle.flush()
        current.handle.close()
        size = current.path.stat().st_size
        self.repository.upsert_raw_file(
            {
                "file_id": current.file_id,
                "run_id": self.run_id,
                "train_id": "" if key[0] == "_unidentified" else key[0],
                "mr_role": "" if key[0] == "_unidentified" else key[1],
                "data_type": self.data_type,
                "relative_path": current.relative_path,
                "start_time": current.start_time,
                "end_time": ended_at,
                "record_count": current.record_count,
                "size_bytes": size,
                "sha256": _sha256(current.path),
                "status": "CLOSED",
                "archive_status": "PENDING",
                "parse_status": "PARSED" if self.data_type == "syslog" else "SUMMARIZED",
            }
        )


class WmeshRealtimeParser:
    def parse(self, raw_text: str, *, receive_time: datetime) -> dict[str, Any] | None:
        event_match = _EVENT_RE.search(raw_text)
        if not event_match:
            return None
        event_type = event_match.group("event").upper()
        device_time = _parse_device_time(raw_text, receive_time)
        peer_name = ""
        peer_mac = ""
        previous_peer_name = ""
        previous_peer_mac = ""
        details: dict[str, Any] = {}
        if event_type == "MESH_ACTIVELINK_SWITCH":
            switches = parse_active_link_switch_logs(raw_text, fallback_year=receive_time.year)
            if switches:
                switch = switches[-1]
                device_time = switch.log_time.astimezone().isoformat(timespec="milliseconds")
                peer_name, peer_mac = switch.to_peer_name, switch.to_peer_mac
                previous_peer_name, previous_peer_mac = switch.from_peer_name, switch.from_peer_mac
                details = {
                    "from_rssi": switch.from_peer_rssi,
                    "to_rssi": switch.to_peer_rssi,
                    "switch_reason_code": switch.switch_reason_code,
                    "switch_reason_text": switch.switch_reason_text,
                }
        else:
            peers = list(_PEER_RE.finditer(raw_text[event_match.end() :]))
            if peers:
                peer_name = peers[-1].group("name")
                peer_mac = peers[-1].group("mac")
        return {
            "event_type": event_type,
            "device_time": device_time,
            "peer_name": peer_name,
            "peer_mac": peer_mac,
            "previous_peer_name": previous_peer_name,
            "previous_peer_mac": previous_peer_mac,
            "details": details,
        }


class SyslogUdpReceiver:
    """一个局点一个 UDP socket；recv 与解析/落盘严格分线程。"""

    def __init__(
        self,
        *,
        repository: GroundUnattendedRepository,
        site_id: str,
        parser: WmeshRealtimeParser | None = None,
    ) -> None:
        self.repository = repository
        self.site_id = site_id
        self.parser = parser or WmeshRealtimeParser()
        self._queue: queue.Queue[UdpEnvelope] = queue.Queue(maxsize=20_000)
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._recv_thread: threading.Thread | None = None
        self._process_thread: threading.Thread | None = None
        self._writer: RawStreamWriter | None = None
        self._run_id = ""
        self._listen_address = ""
        self._endpoint_by_ip: dict[str, dict[str, Any]] = {}
        self._endpoint_by_hostname: dict[str, dict[str, Any]] = {}
        self._received_count = 0
        self._unidentified_count = 0
        self._dropped_count = 0
        self._started_monotonic = 0.0
        self._last_error = ""
        self._event_batch: list[dict[str, Any]] = []
        self._timeline_batch: list[dict[str, Any]] = []
        self._last_batch_at = time.monotonic()
        self._last_device_time: dict[str, datetime] = {}
        self._last_line_hash: dict[str, str] = {}
        self._batch_duration_ms = 0.0
        self._reported_dropped_count = 0
        self._ap_by_name: dict[str, dict[str, str]] = {}
        self._ap_by_mac: dict[str, dict[str, str]] = {}

    def start(
        self,
        *,
        run_id: str,
        run_date: str,
        active_dir: Path,
        listen_host: str,
        listen_port: int,
        queue_capacity: int,
        flush_records: int,
        flush_interval_seconds: float,
        event_batch_size: int,
        event_batch_interval_seconds: float,
    ) -> None:
        if self.running and self._run_id == run_id:
            return
        self.stop()
        self._queue = queue.Queue(maxsize=max(100, int(queue_capacity)))
        self._run_id = run_id
        self._stop.clear()
        self._received_count = self._unidentified_count = self._dropped_count = 0
        self._last_error = ""
        self._reported_dropped_count = 0
        self._event_batch_size = max(1, int(event_batch_size))
        self._event_batch_interval = max(0.1, float(event_batch_interval_seconds))
        self._writer = RawStreamWriter(
            root=Path(active_dir) / "realtime",
            repository=self.repository,
            site_id=self.site_id,
            run_id=run_id,
            run_date=run_date,
            data_type="syslog",
            flush_records=flush_records,
            flush_interval_seconds=flush_interval_seconds,
        )
        recover_raw_files(
            active_dir=Path(active_dir),
            repository=self.repository,
            run_id=run_id,
        )
        self.refresh_inventory()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        try:
            sock.bind((listen_host, int(listen_port)))
        except Exception:
            sock.close()
            raise
        self._socket = sock
        actual = sock.getsockname()
        self._listen_address = f"{actual[0]}:{actual[1]}"
        self._started_monotonic = time.monotonic()
        self._recv_thread = threading.Thread(
            target=self._recv_loop,
            name=f"ground-syslog-recv-{self.site_id}",
            daemon=True,
        )
        self._process_thread = threading.Thread(
            target=self._process_loop,
            name=f"ground-syslog-process-{self.site_id}",
            daemon=True,
        )
        self._recv_thread.start()
        self._process_thread.start()

    @property
    def running(self) -> bool:
        return bool(self._recv_thread and self._recv_thread.is_alive())

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()
        for thread in (self._recv_thread, self._process_thread):
            if thread is not None:
                thread.join(timeout=5)
        self._recv_thread = self._process_thread = None
        self._drain_remaining()
        self._flush_events()
        if self._writer is not None:
            self._writer.close()
        self._writer = None
        self._run_id = ""

    def refresh_inventory(self) -> None:
        active = self.repository.list_inventory(include_removed=False)
        by_ip: dict[str, dict[str, Any]] = {}
        by_host: dict[str, dict[str, Any]] = {}
        for train in active:
            if not bool(train.get("enabled", True)):
                continue
            for endpoint in train.get("endpoints", []):
                if endpoint.get("binding_status") != "ACTIVE":
                    continue
                value = {**endpoint, "train_id": train["train_id"], "train_no": train.get("train_no", "")}
                address = str(endpoint.get("management_ip") or "").strip()
                hostname = str(endpoint.get("source_hostname") or endpoint.get("device_name") or "").strip().casefold()
                if address:
                    by_ip[address] = value
                if hostname:
                    by_host[hostname] = value
        self._endpoint_by_ip = by_ip
        self._endpoint_by_hostname = by_host

    def update_ap_locations(self, rows: list[Any]) -> None:
        by_name: dict[str, dict[str, str]] = {}
        by_mac: dict[str, dict[str, str]] = {}
        for row in rows:
            value = {
                "station": str(getattr(row, "station", "") or ""),
                "section": str(getattr(row, "section", "") or ""),
            }
            name = str(getattr(row, "name", "") or "").strip().casefold()
            mac = _normalize_mac(getattr(row, "mac", ""))
            if name:
                by_name[name] = value
            if mac:
                by_mac[mac] = value
        self._ap_by_name = by_name
        self._ap_by_mac = by_mac

    def health_snapshot(self) -> dict[str, Any]:
        elapsed = max(0.001, time.monotonic() - self._started_monotonic) if self._started_monotonic else 1.0
        writer = self._writer
        return {
            "udp_running": self.running,
            "udp_listen_address": self._listen_address,
            "udp_receive_rate_per_second": round(self._received_count / elapsed, 3),
            "udp_received_count": self._received_count,
            "udp_unidentified_count": self._unidentified_count,
            "udp_queue_length": self._queue.qsize(),
            "udp_queue_capacity": self._queue.maxsize,
            "udp_dropped_count": self._dropped_count,
            "raw_records_written": writer.records_written if writer else 0,
            "raw_bytes_written": writer.bytes_written if writer else 0,
            "raw_last_write_duration_ms": writer.last_write_duration_ms if writer else 0.0,
            "database_pending_count": len(self._event_batch),
            "database_last_batch_duration_ms": self._batch_duration_ms,
            "open_file_count": writer.open_file_count if writer else 0,
            "last_error": self._last_error,
        }

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._socket
            if sock is None:
                return
            try:
                payload, address = sock.recvfrom(65_535)
            except socket.timeout:
                continue
            except OSError:
                return
            envelope = UdpEnvelope(
                source_ip=str(address[0]),
                source_port=int(address[1]),
                receive_time=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                payload=payload,
            )
            self._received_count += 1
            try:
                self._queue.put_nowait(envelope)
            except queue.Full:
                self._dropped_count += 1

    def _process_loop(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                envelope = self._queue.get(timeout=0.2)
            except queue.Empty:
                self._flush_if_due()
                continue
            try:
                self._process(envelope)
            except Exception as exc:
                self._last_error = f"{exc.__class__.__name__}: {exc}"
                self.repository.add_health_event(
                    run_id=self._run_id,
                    component="syslog_writer",
                    severity="error",
                    code="SYSLOG_PROCESS_FAILED",
                    message=self._last_error,
                )
            self._flush_if_due()

    def _drain_remaining(self) -> None:
        while True:
            try:
                self._process(self._queue.get_nowait())
            except queue.Empty:
                break

    def _process(self, envelope: UdpEnvelope) -> None:
        receive_time = datetime.fromisoformat(envelope.receive_time)
        raw_text = envelope.payload.decode("utf-8", errors="replace").strip("\x00\r\n")
        hostname_match = _HOSTNAME_RE.search(raw_text)
        hostname = hostname_match.group("hostname") if hostname_match else ""
        by_ip = self._endpoint_by_ip.get(envelope.source_ip)
        by_host = self._endpoint_by_hostname.get(hostname.casefold()) if hostname else None
        endpoint = by_ip or by_host
        if by_ip and by_host and by_ip.get("device_uuid") != by_host.get("device_uuid"):
            endpoint = None
        if endpoint is None:
            self._unidentified_count += 1
        parsed = self.parser.parse(raw_text, receive_time=receive_time)
        quality = self._quality(endpoint, raw_text, parsed, receive_time)
        record = {
            "source_ip": envelope.source_ip,
            "source_port": envelope.source_port,
            "hostname": hostname,
            "raw_text": raw_text,
            "receive_time": envelope.receive_time,
            "device_time": str((parsed or {}).get("device_time") or ""),
            "device_id": (endpoint or {}).get("device_id"),
            "device_uuid": str((endpoint or {}).get("device_uuid") or ""),
            "train_id": str((endpoint or {}).get("train_id") or ""),
            "mr_role": str((endpoint or {}).get("mr_role") or ""),
            "site_id": self.site_id,
            "parse_status": "PARSED" if parsed else "IGNORED",
            "data_quality": quality,
        }
        if self._writer is None:
            return
        file_id, line_number = self._writer.write(record, receive_time)
        if parsed is None:
            return
        device_time = _datetime_or_none(str(parsed.get("device_time") or ""))
        delay_ms = (receive_time - device_time).total_seconds() * 1000 if device_time else None
        event = {
            **parsed,
            "run_id": self._run_id,
            "device_uuid": record["device_uuid"],
            "device_id": record["device_id"],
            "train_id": record["train_id"],
            "mr_role": record["mr_role"],
            "receive_time": envelope.receive_time,
            "source_ip": envelope.source_ip,
            "hostname": hostname,
            "data_quality": quality,
            "receive_delay_ms": delay_ms,
            "raw_file_id": file_id,
            "raw_line_number": line_number,
        }
        location = self._ap_by_name.get(str(parsed.get("peer_name") or "").casefold()) or self._ap_by_mac.get(
            _normalize_mac(parsed.get("peer_mac"))
        )
        if location:
            event.update(location)
        self._event_batch.append(event)
        self._timeline_batch.append(
            {
                "run_id": self._run_id,
                "ts": envelope.receive_time,
                "event_type": str(parsed["event_type"]).casefold(),
                "severity": "warning" if quality != "COMPLETE" else "info",
                "train_id": record["train_id"],
                "mr_id": record["device_uuid"],
                "title": _event_title(str(parsed["event_type"])),
                "message": str(parsed.get("peer_name") or ""),
                "details": {"data_quality": quality, "raw_file_id": file_id, **dict(parsed.get("details") or {})},
            }
        )
        if record["device_uuid"]:
            self.repository.touch_boot_syslog(record["device_uuid"], envelope.receive_time)

    def _quality(
        self,
        endpoint: dict[str, Any] | None,
        raw_text: str,
        parsed: dict[str, Any] | None,
        receive_time: datetime,
    ) -> str:
        if endpoint is None:
            return "UNIDENTIFIED_SOURCE"
        device_uuid = str(endpoint.get("device_uuid") or "")
        line_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        if self._last_line_hash.get(device_uuid) == line_hash:
            return "DUPLICATE"
        self._last_line_hash[device_uuid] = line_hash
        current = _datetime_or_none(str((parsed or {}).get("device_time") or ""))
        previous = self._last_device_time.get(device_uuid)
        if current is not None:
            self._last_device_time[device_uuid] = current
            if previous is not None and current < previous:
                return "OUT_OF_ORDER" if (previous - current).total_seconds() < 300 else "CLOCK_JUMP"
            if abs((receive_time - current).total_seconds()) > 300:
                return "CLOCK_JUMP"
        return "COMPLETE"

    def _flush_if_due(self) -> None:
        if self._dropped_count > self._reported_dropped_count:
            added = self._dropped_count - self._reported_dropped_count
            self._reported_dropped_count = self._dropped_count
            self.repository.add_health_event(
                run_id=self._run_id,
                component="udp_receiver",
                severity="warning",
                code="UDP_QUEUE_OVERFLOW",
                message=f"UDP 有界队列已丢弃 {added} 条报文",
                details={
                    "dropped_total": self._dropped_count,
                    "queue_capacity": self._queue.maxsize,
                },
            )
            self._timeline_batch.append(
                {
                    "run_id": self._run_id,
                    "event_type": "udp_queue_overflow",
                    "severity": "warning",
                    "title": "UDP 接收队列溢出",
                    "message": f"新增丢弃 {added} 条，累计 {self._dropped_count} 条",
                }
            )
        if len(self._event_batch) >= self._event_batch_size or (
            self._event_batch and time.monotonic() - self._last_batch_at >= self._event_batch_interval
        ):
            self._flush_events()

    def _flush_events(self) -> None:
        if not self._event_batch and not self._timeline_batch:
            return
        started = time.perf_counter()
        events, timeline = self._event_batch, self._timeline_batch
        self._event_batch, self._timeline_batch = [], []
        self.repository.insert_wmesh_events(events)
        self.repository.add_events_batch(timeline)
        self._batch_duration_ms = (time.perf_counter() - started) * 1000
        self._last_batch_at = time.monotonic()


def _parse_device_time(raw_text: str, receive_time: datetime) -> str:
    match = _DEVICE_TIME_RE.search(raw_text)
    if not match:
        return ""
    month = _MONTHS.get(match.group("month").casefold())
    if month is None:
        return ""
    value = datetime(
        int(match.group("year") or receive_time.year),
        month,
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second")),
        int((match.group("millisecond") or "0").ljust(3, "0")[:3]) * 1000,
        tzinfo=receive_time.tzinfo,
    )
    return value.isoformat(timespec="milliseconds")


def _datetime_or_none(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.astimezone()
    except (TypeError, ValueError):
        return None


def _safe_component(value: str) -> str:
    # Leading underscores are valid internal stream buckets (for example,
    # ``_unidentified``); stripping dots is sufficient to reject traversal.
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip(".")
    return result[:100] or "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_mac(value: object) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", str(value or "")).casefold()


def _event_title(event_type: str) -> str:
    return {
        "MESH_LINKUP": "WMESH 链路建立",
        "MESH_LINKDOWN": "WMESH 链路断开",
        "MESH_ACTIVELINK_SWITCH": "WMESH 主链路切换",
    }.get(event_type, event_type)


def recover_raw_files(
    *,
    active_dir: Path,
    repository: GroundUnattendedRepository,
    run_id: str,
) -> int:
    """重启时封闭旧 OPEN 文件，并为同一运行日未登记的 NDJSON 补索引。"""

    root = repository.db_path.parent.resolve()
    active = Path(active_dir).resolve()
    active.relative_to(root)
    known = {
        str(row.get("relative_path") or ""): row
        for row in repository.list_raw_files(limit=1000)
    }
    recovered = 0
    now = datetime.now().astimezone().isoformat(timespec="milliseconds")
    for relative, row in known.items():
        if row.get("run_id") != run_id or row.get("status") != "OPEN":
            continue
        path = (root / relative).resolve()
        valid = path.is_file() and not path.is_symlink()
        repository.upsert_raw_file(
            {
                **row,
                "end_time": now,
                "record_count": _line_count(path) if valid else int(row.get("record_count") or 0),
                "size_bytes": path.stat().st_size if valid else 0,
                "sha256": _sha256(path) if valid else "",
                "status": "RECOVERED" if valid else "MISSING",
                "parse_status": "PENDING_RECOVERY" if valid else "MISSING",
            }
        )
        recovered += 1
    for path in active.rglob("*.ndjson") if active.is_dir() else ():
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in known:
            continue
        first = _first_json_line(path)
        data_type = "ping" if "fleet_ping" in path.parts else "syslog"
        repository.upsert_raw_file(
            {
                "file_id": f"raw_{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:32]}",
                "run_id": run_id,
                "train_id": str(first.get("train_id") or ""),
                "device_id": first.get("device_id"),
                "device_uuid": str(first.get("device_uuid") or first.get("mr_id") or ""),
                "mr_role": str(first.get("mr_role") or first.get("mr_position_code") or ""),
                "data_type": data_type,
                "relative_path": relative,
                "start_time": str(first.get("receive_time") or first.get("ts") or ""),
                "end_time": now,
                "record_count": _line_count(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "status": "RECOVERED",
                "archive_status": "PENDING",
                "parse_status": "PENDING_RECOVERY",
            }
        )
        recovered += 1
    return recovered


def _line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def _first_json_line(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.loads(handle.readline())
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


__all__ = [
    "RawStreamWriter",
    "SyslogUdpReceiver",
    "UdpEnvelope",
    "WmeshRealtimeParser",
    "recover_raw_files",
]
