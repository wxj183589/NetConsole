from __future__ import annotations

import base64
import hashlib
import json
import queue
import re
import socket
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ground_unattended.ap_resolver import (
    GroundApDisplayResolver,
)
from netconsole.services.ground_unattended.radio_control import (
    GroundRadioControlCorrelationService,
    control_event_dedup_key,
)

_WMESH_EVENT_RE = re.compile(
    r"WMESH/\d+/(?P<event>MESH_LINKUP|MESH_LINKDOWN|MESH_ACTIVELINK_SWITCH)\s*:",
    re.IGNORECASE,
)
_IFNET_EVENT_RE = re.compile(r"IFNET/\d+/PHY_UPDOWN\s*:", re.IGNORECASE)
_CFGMAN_EVENT_RE = re.compile(
    r"CFGMAN/\d+/CFGMAN_CFGCHANGED\s*:", re.IGNORECASE
)
_CFGMAN_FIELD_RE = re.compile(
    r"-(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>.*?)(?=-[A-Za-z][A-Za-z0-9_]*=|;|$)",
    re.DOTALL,
)
_PRI_RE = re.compile(r"^<(?P<priority>\d{1,3})>")
_FACILITY_SEVERITY_RE = re.compile(
    r"\b(?P<facility>(?:local\d|kern|user|mail|daemon|auth|syslog|lpr|news|uucp|cron))\.(?P<severity>"
    r"emerg|alert|crit|err|warning|notice|info|debug)\b",
    re.IGNORECASE,
)
_LINKUP_RE = re.compile(
    r"mesh\s+link\s+on\s+(?:the\s+)?interface\s+(?P<interface>\S+)\s+is\s+up\s*:\s*"
    r".*?peer\s+MAC\s*=\s*(?P<peer_mac>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})"
    r".*?peer\s+radio\s+mode\s*=\s*(?P<radio_mode>\d+)"
    r".*?RSSI\s*=\s*(?P<rssi>-?\d+)",
    re.IGNORECASE | re.DOTALL,
)
_LINKDOWN_RE = re.compile(
    r"mesh\s+link\s+on\s+(?:the\s+)?interface\s+(?P<interface>\S+)\s+is\s+down\s*:\s*"
    r".*?peer\s+MAC\s*=\s*(?P<peer_mac>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})"
    r".*?RSSI\s*=\s*(?P<rssi>-?\d+)\s*,?\s*reason\s*:\s*(?P<reason>.+?)\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVE_LINK_SWITCH_RE = re.compile(
    r"switch\s+an\s+active\s+link\s+from\s+(?P<old>\S+)\s+to\s+(?P<new>\S+)\s*:\s*"
    r"peer\s+quantity\s*=\s*(?P<peer_quantity>\d+)\s*,\s*"
    r"link\s+quantity\s*=\s*(?P<link_quantity>\d+)\s*,\s*"
    r"switch\s+reason\s*=\s*(?P<reason>\d+)\s*\.",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVE_LINK_ENDPOINT_RE = re.compile(
    r"^(?P<radio>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})_"
    r"(?P<peer>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})"
    r"\((?P<rssi>-?\d+)\)$"
)
_ACTIVE_LINK_SINGLE_MAC_ENDPOINT_RE = re.compile(
    r"^(?:.*?)_?(?P<peer>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})"
    r"\((?P<rssi>-?\d+)\)$"
)
_IFNET_PHY_RE = re.compile(
    r"physical\s+state\s+on\s+the\s+interface\s+(?P<interface>\S+)\s+changed\s+to\s+(?P<state>up|down)\b",
    re.IGNORECASE,
)
_LEGACY_PEER_RE = re.compile(
    r"(?P<name>[A-Za-z0-9_.-]+)_?(?P<mac>[0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4}[-:.][0-9A-Fa-f]{4})",
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
    global_receive_sequence: int
    source_receive_sequence: int
    payload: bytes


@dataclass
class _OpenRawFile:
    file_id: str
    path: Path
    relative_path: str
    handle: Any
    start_time: str
    last_record_time: str
    record_count: int = 0
    flushed_record_count: int = 0
    last_flush_at: float = field(default_factory=time.monotonic)


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
        self.records_written = 0
        self.bytes_written = 0
        self.last_write_duration_ms = 0.0

    @property
    def open_file_count(self) -> int:
        return len(self._files)

    @property
    def file_checkpoints(self) -> dict[str, int]:
        return {
            current.file_id: current.record_count for current in self._files.values()
        }

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
        received_at_text = received_at.isoformat(timespec="milliseconds")
        if received_at_text > current.last_record_time:
            current.last_record_time = received_at_text
        self.records_written += 1
        self.bytes_written += len(encoded)
        if (
            current.record_count % self.flush_records == 0
            or time.monotonic() - current.last_flush_at
            >= self.flush_interval_seconds
        ):
            current.handle.flush()
            current.flushed_record_count = current.record_count
            current.last_flush_at = time.monotonic()
        self.last_write_duration_ms = (time.perf_counter() - started) * 1000
        return current.file_id, current.record_count

    def flush_through(self, checkpoints: Mapping[str, int]) -> None:
        """Make checkpointed raw lines visible before derived SQLite commits."""

        required = {
            str(file_id): max(0, int(line_number))
            for file_id, line_number in checkpoints.items()
            if str(file_id)
        }
        if not required:
            return
        for current in self._files.values():
            line_number = required.get(current.file_id)
            if line_number is None:
                continue
            if line_number > current.record_count:
                raise ValueError("raw checkpoint exceeds written record count")
            if line_number <= current.flushed_record_count:
                continue
            current.handle.flush()
            current.flushed_record_count = current.record_count
            current.last_flush_at = time.monotonic()

    def close(self) -> int:
        closed = len(self._files)
        ended_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        for key in tuple(self._files):
            self._close_one(key, ended_at)
        return closed

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
            last_record_time=started_at,
            last_flush_at=time.monotonic(),
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
                "end_time": current.last_record_time or ended_at,
                "record_count": current.record_count,
                "size_bytes": size,
                "sha256": _sha256(current.path),
                "status": "CLOSED",
                "archive_status": "PENDING",
                "parse_status": (
                    "PENDING_RECOVERY"
                    if self.data_type == "syslog"
                    else "SUMMARIZED"
                ),
            }
        )


class WmeshRealtimeParser:
    def parse(self, raw_text: str, *, receive_time: datetime) -> dict[str, Any] | None:
        event_match = _WMESH_EVENT_RE.search(raw_text)
        if event_match:
            event_family = "WMESH"
            event_type = event_match.group("event").upper()
            payload = self._parse_wmesh_event(event_type, raw_text)
        elif _IFNET_EVENT_RE.search(raw_text):
            event_family = "IFNET"
            event_type = "IFNET_PHY_UPDOWN"
            payload = self._parse_ifnet_event(raw_text)
        elif _CFGMAN_EVENT_RE.search(raw_text):
            event_family = "CFGMAN"
            event_type = "CFGMAN_CFGCHANGED"
            payload = self._parse_cfgman_event(raw_text)
        else:
            return None
        if payload is None:
            return None
        return {
            "event_type": event_type,
            "event_family": event_family,
            "device_time": _parse_device_time(raw_text, receive_time),
            **payload,
        }

    @staticmethod
    def _parse_wmesh_event(event_type: str, raw_text: str) -> dict[str, Any] | None:
        if event_type == "MESH_LINKUP":
            match = _LINKUP_RE.search(raw_text)
            if not match:
                return _legacy_link_event(raw_text)
            peer_mac = match.group("peer_mac")
            return {
                "peer_name": "",
                "peer_mac": peer_mac,
                "previous_peer_name": "",
                "previous_peer_mac": "",
                "details": {
                    "mesh_interface": match.group("interface"),
                    "peer_mac": peer_mac,
                    "peer_radio_mode": int(match.group("radio_mode")),
                    "rssi": int(match.group("rssi")),
                },
            }
        if event_type == "MESH_LINKDOWN":
            match = _LINKDOWN_RE.search(raw_text)
            if not match:
                return _legacy_link_event(raw_text)
            peer_mac = match.group("peer_mac")
            reason = match.group("reason").strip().rstrip(".")
            reason_code = _linkdown_reason_code(reason)
            return {
                "peer_name": "",
                "peer_mac": peer_mac,
                "previous_peer_name": "",
                "previous_peer_mac": "",
                "details": {
                    "mesh_interface": match.group("interface"),
                    "peer_mac": peer_mac,
                    "rssi": int(match.group("rssi")),
                    "reason_raw": reason,
                    "reason_code": reason_code,
                    "reason_label": _linkdown_reason_label(reason_code),
                },
            }
        match = _ACTIVE_LINK_SWITCH_RE.search(raw_text)
        if not match:
            return None
        old = _parse_active_endpoint(match.group("old"))
        new = _parse_active_endpoint(match.group("new"))
        return {
            "peer_name": "",
            "peer_mac": str(new["peer_mac"] or ""),
            "previous_peer_name": "",
            "previous_peer_mac": str(old["peer_mac"] or ""),
            "details": {
                "old_peer_radio_mac": old["radio_mac"],
                "old_peer_mac": old["peer_mac"],
                "old_rssi": old["rssi"],
                "old_active_link_missing": old["missing"],
                "new_peer_radio_mac": new["radio_mac"],
                "new_peer_mac": new["peer_mac"],
                "new_rssi": new["rssi"],
                "peer_quantity": int(match.group("peer_quantity")),
                "link_quantity": int(match.group("link_quantity")),
                "switch_reason_code": int(match.group("reason")),
            },
        }

    @staticmethod
    def _parse_ifnet_event(raw_text: str) -> dict[str, Any] | None:
        match = _IFNET_PHY_RE.search(raw_text)
        if not match:
            return None
        return {
            "peer_name": "",
            "peer_mac": "",
            "previous_peer_name": "",
            "previous_peer_mac": "",
            "interface_name": match.group("interface"),
            "interface_type": (
                "RADIO"
                if match.group("interface").casefold().startswith("wlan-radio")
                else "OTHER"
            ),
            "physical_state": match.group("state").upper(),
            "details": {
                "interface": match.group("interface"),
                "interface_name": match.group("interface"),
                "interface_type": (
                    "RADIO"
                    if match.group("interface")
                    .casefold()
                    .startswith("wlan-radio")
                    else "OTHER"
                ),
                "physical_state": match.group("state").upper(),
            },
        }

    @staticmethod
    def _parse_cfgman_event(raw_text: str) -> dict[str, Any] | None:
        marker = _CFGMAN_EVENT_RE.search(raw_text)
        if marker is None:
            return None
        tail = raw_text[marker.end() :]
        fields = {
            match.group("key").casefold(): match.group("value").strip()
            for match in _CFGMAN_FIELD_RE.finditer(tail)
        }
        message = tail.split(";", 1)[1].strip() if ";" in tail else ""
        return {
            "peer_name": "",
            "peer_mac": "",
            "previous_peer_name": "",
            "previous_peer_mac": "",
            "cfg_event_index": fields.get("eventindex", ""),
            "cfg_command_source": fields.get("commandsource", "").casefold(),
            "cfg_source": fields.get("configsource", "").casefold(),
            "cfg_destination": fields.get(
                "configdestination", ""
            ).casefold(),
            "details": {
                "cfg_fields": fields,
                "cfg_event_index": fields.get("eventindex", ""),
                "cfg_command_source": fields.get(
                    "commandsource", ""
                ).casefold(),
                "cfg_source": fields.get("configsource", "").casefold(),
                "cfg_destination": fields.get(
                    "configdestination", ""
                ).casefold(),
                "message": message.rstrip("."),
            },
        }


class SyslogUdpReceiver:
    """一个局点一个 UDP socket；recv 与解析/落盘严格分线程。"""

    def __init__(
        self,
        *,
        repository: GroundUnattendedRepository,
        site_id: str,
        parser: WmeshRealtimeParser | None = None,
        ap_identity_query_service: ApIdentityQueryService | None = None,
    ) -> None:
        self.repository = repository
        self.site_id = site_id
        self.parser = parser or WmeshRealtimeParser()
        self.radio_control = GroundRadioControlCorrelationService(repository)
        self._queue: queue.Queue[UdpEnvelope] = queue.Queue(maxsize=20_000)
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._recv_thread: threading.Thread | None = None
        self._process_thread: threading.Thread | None = None
        self._writer: RawStreamWriter | None = None
        self._run_id = ""
        self._listen_address = ""
        self._listen_host = ""
        self._listen_port = 0
        self._endpoint_by_ip: dict[str, list[dict[str, Any]]] = {}
        self._endpoint_by_hostname: dict[str, list[dict[str, Any]]] = {}
        self._received_count = 0
        self._unidentified_count = 0
        self._identity_conflict_count = 0
        self._dropped_count = 0
        self._last_received_at = ""
        self._started_monotonic = 0.0
        self._last_error = ""
        self._event_batch: list[dict[str, Any]] = []
        self._timeline_batch: list[dict[str, Any]] = []
        self._raw_checkpoints: dict[str, int] = {}
        self._event_batch_size = 100
        self._event_batch_interval = 1.0
        self._last_batch_at = time.monotonic()
        self._last_clock_offset_ms: dict[str, float] = {}
        self._last_line_hash: dict[str, str] = {}
        self._global_receive_sequence = 0
        self._source_receive_sequences: dict[tuple[str, int], int] = {}
        self._batch_duration_ms = 0.0
        self._reported_dropped_count = 0
        self._reported_pressure = False
        self._ap_resolver = GroundApDisplayResolver(
            ap_identity_query_service
        )

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
        stop_result = self.stop()
        if not stop_result["success"]:
            raise RuntimeError(
                "previous Syslog receiver did not stop: "
                + ", ".join(stop_result["alive_thread_names"])
            )
        self._queue = queue.Queue(maxsize=max(100, int(queue_capacity)))
        self._run_id = run_id
        self._stop.clear()
        self._received_count = self._unidentified_count = self._dropped_count = 0
        self._identity_conflict_count = 0
        self._last_received_at = ""
        self._global_receive_sequence = 0
        self._source_receive_sequences = {}
        self._last_clock_offset_ms = {}
        self._last_line_hash = {}
        self._last_error = ""
        self._reported_dropped_count = 0
        self._reported_pressure = False
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
        self._listen_host = str(actual[0])
        self._listen_port = int(actual[1])
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

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()
        for thread in (self._recv_thread, self._process_thread):
            if thread is not None:
                thread.join(timeout=5)
        udp_port_released = _udp_port_is_available(
            self._listen_host, self._listen_port
        )
        threads = [
            thread
            for thread in (self._recv_thread, self._process_thread)
            if thread is not None
        ]
        alive = [thread.name for thread in threads if thread.is_alive()]
        if alive:
            return {
                "success": False,
                "udp_port_released": udp_port_released,
                "alive_thread_names": alive,
                "queue_empty": self._queue.empty(),
                "queue_length": self._queue.qsize(),
                "closed_file_count": 0,
                "received_count": self._received_count,
                "dropped_count": self._dropped_count,
            }
        self._recv_thread = self._process_thread = None
        self._drain_remaining()
        closed_file_count = 0
        if self._writer is not None:
            self._raw_checkpoints.update(self._writer.file_checkpoints)
            closed_file_count = self._writer.close()
        projection_flushed = self._flush_events()
        self._writer = None
        self._run_id = ""
        self._listen_address = ""
        self._listen_host = ""
        self._listen_port = 0
        return {
            "success": self._queue.empty() and udp_port_released and projection_flushed,
            "udp_port_released": udp_port_released,
            "alive_thread_names": [],
            "queue_empty": self._queue.empty(),
            "queue_length": self._queue.qsize(),
            "closed_file_count": closed_file_count,
            "projection_flushed": projection_flushed,
            "received_count": self._received_count,
            "dropped_count": self._dropped_count,
        }

    def refresh_inventory(self) -> None:
        active = self.repository.list_inventory(include_removed=False)
        by_ip: dict[str, list[dict[str, Any]]] = {}
        by_host: dict[str, list[dict[str, Any]]] = {}
        for train in active:
            if not bool(train.get("enabled", True)):
                continue
            for endpoint in train.get("endpoints", []):
                if endpoint.get("binding_status") != "ACTIVE":
                    continue
                value = {**endpoint, "train_id": train["train_id"], "train_no": train.get("train_no", "")}
                addresses = {
                    str(endpoint.get("management_ip") or "").strip(),
                    str(endpoint.get("last_syslog_source_ip") or "").strip(),
                }
                hostnames = {
                    str(endpoint.get("source_hostname") or "").strip().casefold(),
                    str(endpoint.get("syslog_hostname") or "").strip().casefold(),
                    str(endpoint.get("device_name") or "").strip().casefold(),
                }
                for address in addresses - {""}:
                    by_ip.setdefault(address, []).append(value)
                for hostname in hostnames - {""}:
                    by_host.setdefault(hostname, []).append(value)
        self._endpoint_by_ip = by_ip
        self._endpoint_by_hostname = by_host

    def refresh_ap_identity(self) -> int:
        return self._ap_resolver.refresh_revision()

    def health_snapshot(self) -> dict[str, Any]:
        elapsed = max(0.001, time.monotonic() - self._started_monotonic) if self._started_monotonic else 1.0
        writer = self._writer
        return {
            "udp_running": self.running,
            "udp_listen_address": self._listen_address,
            "udp_receive_rate_per_second": round(self._received_count / elapsed, 3),
            "udp_received_count": self._received_count,
            "udp_unidentified_count": self._unidentified_count,
            "udp_identity_conflict_count": self._identity_conflict_count,
            "udp_last_received_at": self._last_received_at,
            "udp_queue_length": self._queue.qsize(),
            "udp_queue_capacity": self._queue.maxsize,
            "udp_queue_pressure": round(self._queue.qsize() / self._queue.maxsize, 4),
            "udp_dropped_count": self._dropped_count,
            "raw_records_written": writer.records_written if writer else 0,
            "raw_bytes_written": writer.bytes_written if writer else 0,
            "raw_last_write_duration_ms": writer.last_write_duration_ms if writer else 0.0,
            "database_pending_count": len(self._event_batch),
            "database_last_batch_duration_ms": self._batch_duration_ms,
            "open_file_count": writer.open_file_count if writer else 0,
            "last_error": self._last_error,
        }

    def _next_global_receive_sequence(self) -> int:
        self._global_receive_sequence += 1
        return self._global_receive_sequence

    def _next_source_receive_sequence(self, source_ip: str, source_port: int) -> int:
        key = (source_ip, source_port)
        value = self._source_receive_sequences.get(key, 0) + 1
        self._source_receive_sequences[key] = value
        return value

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
                global_receive_sequence=self._next_global_receive_sequence(),
                source_receive_sequence=self._next_source_receive_sequence(
                    str(address[0]), int(address[1])
                ),
                payload=payload,
            )
            self._received_count += 1
            self._last_received_at = envelope.receive_time
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
        hostname = _extract_hostname(raw_text)
        facility, severity = _extract_facility_severity(raw_text)
        endpoint, identity_status = self._resolve_identity(envelope.source_ip, hostname)
        if identity_status == "UNIDENTIFIED":
            self._unidentified_count += 1
        if identity_status == "IDENTITY_CONFLICT":
            self._identity_conflict_count += 1
        parsed = self.parser.parse(raw_text, receive_time=receive_time)
        if parsed is not None:
            parsed = self._ap_resolver.enrich_parsed(parsed)
            if (
                str(parsed.get("event_family") or "") == "CFGMAN"
                and endpoint
                and str(parsed.get("cfg_command_source") or "").casefold()
                != "snmp"
            ):
                expected = self.repository.expected_config_change_at(
                    device_uuid=str(endpoint.get("device_uuid") or ""),
                    event_time=envelope.receive_time,
                )
                parsed["expected_internal_change"] = expected
                details = dict(parsed.get("details") or {})
                details["expected_internal_change"] = expected
                parsed["details"] = details
        quality, clock_offset_ms = self._quality(
            endpoint,
            identity_status,
            raw_text,
            parsed,
            receive_time,
        )
        parsed_details = dict((parsed or {}).get("details") or {})
        reason_code = str(
            parsed_details.get("reason_code")
            or parsed_details.get("switch_reason_code")
            or ""
        )
        record = {
            "source_ip": envelope.source_ip,
            "source_port": envelope.source_port,
            "hostname": hostname,
            "system_name": hostname,
            "facility": facility,
            "severity": severity,
            "raw_bytes_base64": base64.b64encode(envelope.payload).decode("ascii"),
            "raw_text": raw_text,
            "receive_time": envelope.receive_time,
            "global_receive_sequence": envelope.global_receive_sequence,
            "source_receive_sequence": envelope.source_receive_sequence,
            "device_time": str((parsed or {}).get("device_time") or ""),
            "device_id": (endpoint or {}).get("device_id"),
            "device_uuid": str((endpoint or {}).get("device_uuid") or ""),
            "mr_name": str((endpoint or {}).get("device_name") or ""),
            "train_id": str((endpoint or {}).get("train_id") or ""),
            "train_no": str((endpoint or {}).get("train_no") or ""),
            "mr_role": str((endpoint or {}).get("mr_role") or ""),
            "site_id": self.site_id,
            "parse_status": "PARSED" if parsed else "IGNORED",
            "data_quality": quality,
            "identity_status": identity_status,
            "clock_offset_ms": clock_offset_ms,
            "event_type": str((parsed or {}).get("event_type") or ""),
            "event_family": str((parsed or {}).get("event_family") or ""),
            "interface_name": str(
                (parsed or {}).get("interface_name") or ""
            ),
            "interface_type": str(
                (parsed or {}).get("interface_type") or ""
            ),
            "physical_state": str(
                (parsed or {}).get("physical_state") or ""
            ),
            "cfg_event_index": str(
                (parsed or {}).get("cfg_event_index") or ""
            ),
            "cfg_command_source": str(
                (parsed or {}).get("cfg_command_source") or ""
            ),
            "cfg_source": str((parsed or {}).get("cfg_source") or ""),
            "cfg_destination": str(
                (parsed or {}).get("cfg_destination") or ""
            ),
            "expected_internal_change": bool(
                (parsed or {}).get("expected_internal_change")
            ),
            "peer_name": str((parsed or {}).get("peer_name") or ""),
            "peer_mac": str((parsed or {}).get("peer_mac") or ""),
            "previous_peer_name": str(
                (parsed or {}).get("previous_peer_name") or ""
            ),
            "previous_peer_mac": str(
                (parsed or {}).get("previous_peer_mac") or ""
            ),
            "peer_radio_mac": str(
                parsed_details.get("peer_radio_mac")
                or parsed_details.get("new_peer_radio_mac")
                or ""
            ),
            "previous_peer_radio_mac": str(
                parsed_details.get("previous_peer_radio_mac")
                or parsed_details.get("old_peer_radio_mac")
                or ""
            ),
            "resolved_ap_id": str(parsed_details.get("peer_ap_id") or ""),
            "resolved_ap_name": str(parsed_details.get("peer_ap_name") or ""),
            "previous_resolved_ap_id": str(
                parsed_details.get("previous_peer_ap_id") or ""
            ),
            "previous_resolved_ap_name": str(
                parsed_details.get("previous_peer_ap_name") or ""
            ),
            "station": str((parsed or {}).get("station") or ""),
            "section": str((parsed or {}).get("section") or ""),
            "previous_station": str(
                parsed_details.get("previous_station") or ""
            ),
            "previous_section": str(
                parsed_details.get("previous_section") or ""
            ),
            "rssi": parsed_details.get("rssi")
            if parsed_details.get("rssi") is not None
            else parsed_details.get("new_rssi"),
            "previous_rssi": parsed_details.get("old_rssi"),
            "reason_code": reason_code,
            "reason_text": str(parsed_details.get("reason_raw") or ""),
            "resolution_status": str(
                parsed_details.get("resolution_status") or ""
            ),
            "parsed_details": parsed_details,
        }
        if self._writer is None:
            return
        file_id, line_number = self._writer.write(record, receive_time)
        self._raw_checkpoints[file_id] = line_number
        if parsed is None:
            return
        use_device_time = quality not in {"CLOCK_OFFSET", "CLOCK_JUMP"} and bool(
            parsed.get("device_time")
        )
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
            "receive_delay_ms": clock_offset_ms,
            "clock_offset_ms": clock_offset_ms,
            "raw_file_id": file_id,
            "raw_line_number": line_number,
            "event_time": str(
                parsed.get("device_time") if use_device_time else envelope.receive_time
            ),
            "event_time_source": (
                "DEVICE_TIME" if use_device_time else "RECEIVE_TIME"
            ),
            "details": {
                **dict(parsed.get("details") or {}),
                "facility": facility,
                "severity": severity,
                "identity_status": identity_status,
                "global_receive_sequence": envelope.global_receive_sequence,
                "source_receive_sequence": envelope.source_receive_sequence,
            },
        }
        event.update(
            {
                "station": str(parsed.get("station") or ""),
                "section": str(parsed.get("section") or ""),
            }
        )
        event_family = str(parsed.get("event_family") or "")
        if (
            event_family in {"IFNET", "CFGMAN"}
            and record["device_uuid"]
        ):
            event["dedup_key"] = control_event_dedup_key(
                device_uuid=record["device_uuid"],
                event_type=str(parsed.get("event_type") or ""),
                device_time=str(parsed.get("device_time") or ""),
                raw_text=raw_text,
                interface_name=str(parsed.get("interface_name") or ""),
                physical_state=str(parsed.get("physical_state") or ""),
                cfg_event_index=str(parsed.get("cfg_event_index") or ""),
                cfg_command_source=str(
                    parsed.get("cfg_command_source") or ""
                ),
            )
            self.radio_control.process(event)
        else:
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
                    "message": _event_message(parsed),
                    "dedup_key": f"raw-syslog:{file_id}:{line_number}",
                    "details": {
                        "data_quality": quality,
                        "identity_status": identity_status,
                        "train_no": record["train_no"],
                        "mr_name": record["mr_name"],
                        "mr_position_code": record["mr_role"],
                        "raw_file_id": file_id,
                        "global_receive_sequence": envelope.global_receive_sequence,
                        "source_receive_sequence": envelope.source_receive_sequence,
                        "clock_offset_ms": clock_offset_ms,
                        **dict(parsed.get("details") or {}),
                    },
                }
            )
        if record["device_uuid"] and identity_status == "VERIFIED":
            self.repository.touch_boot_syslog(
                record["device_uuid"],
                envelope.receive_time,
                source_ip=envelope.source_ip,
                hostname=hostname,
                identity_verified=True,
            )

    def _resolve_identity(
        self, source_ip: str, hostname: str
    ) -> tuple[dict[str, Any] | None, str]:
        by_ip = self._endpoint_by_ip.get(source_ip, [])
        by_host = self._endpoint_by_hostname.get(hostname.casefold(), []) if hostname else []
        ip_by_uuid = {str(item.get("device_uuid") or ""): item for item in by_ip}
        host_by_uuid = {str(item.get("device_uuid") or ""): item for item in by_host}
        if ip_by_uuid and host_by_uuid:
            overlap = set(ip_by_uuid) & set(host_by_uuid)
            if len(overlap) == 1:
                return ip_by_uuid[overlap.pop()], "VERIFIED"
            return None, "IDENTITY_CONFLICT"
        if len(host_by_uuid) == 1:
            return next(iter(host_by_uuid.values())), "UNCONFIRMED_HOSTNAME"
        if len(ip_by_uuid) == 1:
            return next(iter(ip_by_uuid.values())), "UNCONFIRMED_SOURCE_IP"
        return None, "UNIDENTIFIED"

    def _quality(
        self,
        endpoint: dict[str, Any] | None,
        identity_status: str,
        raw_text: str,
        parsed: dict[str, Any] | None,
        receive_time: datetime,
    ) -> tuple[str, float | None]:
        if identity_status == "IDENTITY_CONFLICT":
            return "IDENTITY_CONFLICT", None
        if endpoint is None:
            return "UNIDENTIFIED_SOURCE", None
        device_uuid = str(endpoint.get("device_uuid") or f"{identity_status}:{endpoint.get('management_ip') or ''}")
        line_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        if self._last_line_hash.get(device_uuid) == line_hash:
            return "DUPLICATE", None
        self._last_line_hash[device_uuid] = line_hash
        current = _datetime_or_none(str((parsed or {}).get("device_time") or ""))
        if current is not None:
            offset_ms = (receive_time - current).total_seconds() * 1000
            previous_offset = self._last_clock_offset_ms.get(device_uuid)
            self._last_clock_offset_ms[device_uuid] = offset_ms
            if previous_offset is not None and abs(offset_ms - previous_offset) >= 60_000:
                return "CLOCK_JUMP", offset_ms
            if abs(offset_ms) >= 5_000:
                return "CLOCK_OFFSET", offset_ms
            return "COMPLETE", offset_ms
        return "COMPLETE", None

    def _flush_if_due(self) -> None:
        queue_length = self._queue.qsize()
        queue_capacity = self._queue.maxsize
        pressure = queue_length / queue_capacity if queue_capacity else 0.0
        if pressure >= 0.8 and not self._reported_pressure:
            self._reported_pressure = True
            self.repository.add_health_event(
                run_id=self._run_id,
                component="udp_receiver",
                severity="warning",
                code="SYSLOG_QUEUE_PRESSURE",
                message="Syslog 接收队列接近容量上限",
                details={"queue_length": queue_length, "queue_capacity": queue_capacity},
            )
        elif pressure < 0.5:
            self._reported_pressure = False
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
            self.repository.add_health_event(
                run_id=self._run_id,
                component="udp_receiver",
                severity="warning",
                code="SYSLOG_DROPPED",
                message=f"Syslog 队列已丢弃 {added} 条报文",
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
        projection_pending = bool(
            self._event_batch or self._timeline_batch or self._raw_checkpoints
        )
        if len(self._event_batch) >= self._event_batch_size or (
            projection_pending
            and time.monotonic() - self._last_batch_at >= self._event_batch_interval
        ):
            self._flush_events()

    def _flush_events(self) -> bool:
        if (
            not self._event_batch
            and not self._timeline_batch
            and not self._raw_checkpoints
        ):
            return True
        started = time.perf_counter()
        events = list(self._event_batch)
        timeline = list(self._timeline_batch)
        checkpoints = dict(self._raw_checkpoints)
        try:
            if self._writer is not None:
                self._writer.flush_through(checkpoints)
            self.repository.commit_wmesh_projection_batch(
                events,
                timeline,
                raw_checkpoints=checkpoints,
                complete_closed_files=True,
            )
        except Exception as exc:
            self._last_error = f"{exc.__class__.__name__}: {exc}"
            return False
        del self._event_batch[: len(events)]
        del self._timeline_batch[: len(timeline)]
        for file_id, line_number in checkpoints.items():
            if self._raw_checkpoints.get(file_id, 0) <= line_number:
                self._raw_checkpoints.pop(file_id, None)
        self._batch_duration_ms = (time.perf_counter() - started) * 1000
        self._last_batch_at = time.monotonic()
        return True

    def replay_pending_events(self, *, max_records: int = 5_000) -> dict[str, int]:
        """Boundedly rebuild structured WMESH projections from crash-safe raw files."""

        root = self.repository.db_path.parent.resolve()
        remaining = max(1, int(max_records))
        files_completed = 0
        records_processed = 0
        events_projected = 0
        candidates = [
            row
            for row in self.repository.list_raw_files_for_run(self._run_id)
            if str(row.get("data_type") or "") == "syslog"
            and str(row.get("parse_status") or "").startswith("PENDING_RECOVERY")
        ]
        for row in candidates:
            if remaining <= 0:
                break
            relative_path = str(row.get("relative_path") or "")
            path = _managed_regular_file(root, relative_path)
            if path is None:
                self.repository.upsert_raw_file(
                    {**row, "status": "MISSING", "parse_status": "MISSING"}
                )
                continue
            parse_status = str(row.get("parse_status") or "")
            persisted_cursor, persisted_offset = _parse_recovery_cursor(parse_status)
            file_id = str(row.get("file_id") or "")
            event_batch: list[dict[str, Any]] = []
            timeline_batch: list[dict[str, Any]] = []
            file_size = path.stat().st_size
            with path.open("rb") as handle:
                cursor, last_processed_offset = _seek_recovery_cursor(
                    handle,
                    line_cursor=persisted_cursor,
                    byte_offset=persisted_offset,
                    file_size=file_size,
                )
                last_processed_line = cursor
                while remaining > 0:
                    raw_line = handle.readline()
                    if not raw_line:
                        break
                    line_number = last_processed_line + 1
                    remaining -= 1
                    records_processed += 1
                    last_processed_line = line_number
                    last_processed_offset = handle.tell()
                    line = raw_line.decode("utf-8", errors="replace")
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    projection = self._recovered_projection(
                        record,
                        raw_file_id=str(row.get("file_id") or ""),
                        raw_line_number=line_number,
                    )
                    if projection is None:
                        continue
                    event, timeline = projection
                    event_batch.append(event)
                    timeline_batch.append(timeline)
                    if len(event_batch) >= 100:
                        events_projected += (
                            self.repository.commit_wmesh_projection_batch(
                                event_batch,
                                timeline_batch,
                                raw_checkpoints={file_id: last_processed_line},
                            )
                        )
                        self._persist_recovery_offset(
                            file_id=file_id,
                            line_number=last_processed_line,
                            byte_offset=last_processed_offset,
                        )
                        event_batch, timeline_batch = [], []
            completed = last_processed_offset >= file_size
            events_projected += self.repository.commit_wmesh_projection_batch(
                event_batch,
                timeline_batch,
                raw_checkpoints={file_id: last_processed_line},
                completed_raw_file_ids=(file_id,) if completed else (),
            )
            if completed:
                files_completed += 1
            else:
                self._persist_recovery_offset(
                    file_id=file_id,
                    line_number=last_processed_line,
                    byte_offset=last_processed_offset,
                )
        return {
            "files_completed": files_completed,
            "records_processed": records_processed,
            "events_projected": events_projected,
            "files_pending": max(0, len(candidates) - files_completed),
        }

    def _persist_recovery_offset(
        self,
        *,
        file_id: str,
        line_number: int,
        byte_offset: int,
    ) -> None:
        row = self.repository.get_raw_file(file_id)
        if row is None:
            raise ValueError("ground unattended raw file not found")
        if not str(row.get("parse_status") or "").startswith("PENDING_RECOVERY"):
            return
        self.repository.upsert_raw_file(
            {
                **row,
                "parse_status": _format_recovery_cursor(
                    line_number=line_number,
                    byte_offset=byte_offset,
                ),
            }
        )

    def _recovered_projection(
        self,
        record: dict[str, Any],
        *,
        raw_file_id: str,
        raw_line_number: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        raw_text = str(record.get("raw_text") or "")
        try:
            receive_time = datetime.fromisoformat(str(record.get("receive_time") or ""))
        except (TypeError, ValueError):
            return None
        parsed = self.parser.parse(raw_text, receive_time=receive_time)
        if parsed is None or str(parsed.get("event_family") or "") != "WMESH":
            return None
        parsed = self._ap_resolver.enrich_parsed(parsed)
        details = {
            **dict(parsed.get("details") or {}),
            "facility": str(record.get("facility") or ""),
            "severity": str(record.get("severity") or ""),
            "identity_status": str(record.get("identity_status") or ""),
            "global_receive_sequence": int(
                record.get("global_receive_sequence") or 0
            ),
            "source_receive_sequence": int(
                record.get("source_receive_sequence") or 0
            ),
            "recovered_from_raw": True,
        }
        quality = str(record.get("data_quality") or "COMPLETE")
        use_device_time = quality not in {"CLOCK_OFFSET", "CLOCK_JUMP"} and bool(
            parsed.get("device_time")
        )
        event_time = (
            str(parsed.get("device_time"))
            if use_device_time
            else receive_time.isoformat(timespec="milliseconds")
        )
        event = {
            **parsed,
            "run_id": self._run_id,
            "device_uuid": str(record.get("device_uuid") or ""),
            "device_id": record.get("device_id"),
            "train_id": str(record.get("train_id") or ""),
            "mr_role": str(record.get("mr_role") or ""),
            "receive_time": receive_time.isoformat(timespec="milliseconds"),
            "source_ip": str(record.get("source_ip") or ""),
            "hostname": str(record.get("hostname") or ""),
            "data_quality": quality,
            "receive_delay_ms": record.get("clock_offset_ms"),
            "clock_offset_ms": record.get("clock_offset_ms"),
            "raw_file_id": raw_file_id,
            "raw_line_number": raw_line_number,
            "event_time": event_time,
            "event_time_source": (
                "DEVICE_TIME" if use_device_time else "RECEIVE_TIME"
            ),
            "dedup_key": f"raw-syslog:{raw_file_id}:{raw_line_number}",
            "station": str(parsed.get("station") or ""),
            "section": str(parsed.get("section") or ""),
            "details": details,
        }
        timeline = {
            "run_id": self._run_id,
            "ts": receive_time.isoformat(timespec="milliseconds"),
            "event_type": str(parsed["event_type"]).casefold(),
            "severity": "warning" if quality != "COMPLETE" else "info",
            "train_id": str(record.get("train_id") or ""),
            "mr_id": str(record.get("device_uuid") or ""),
            "title": _event_title(str(parsed["event_type"])),
            "message": _event_message(parsed),
            "dedup_key": f"raw-syslog:{raw_file_id}:{raw_line_number}",
            "details": {
                "data_quality": quality,
                "identity_status": str(record.get("identity_status") or ""),
                "train_no": str(record.get("train_no") or ""),
                "mr_name": str(record.get("mr_name") or ""),
                "mr_position_code": str(record.get("mr_role") or ""),
                "raw_file_id": raw_file_id,
                "raw_line_number": raw_line_number,
                "recovered_from_raw": True,
                **details,
            },
        }
        return event, timeline


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


def _extract_hostname(raw_text: str) -> str:
    event_match = (
        _WMESH_EVENT_RE.search(raw_text)
        or _IFNET_EVENT_RE.search(raw_text)
        or _CFGMAN_EVENT_RE.search(raw_text)
    )
    if not event_match:
        return ""
    prefix = raw_text[: event_match.start()]
    time_match = _DEVICE_TIME_RE.search(prefix)
    if time_match:
        prefix = prefix[time_match.end() :]
    prefix = _PRI_RE.sub("", prefix).strip()
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", prefix)
    return tokens[0] if tokens else ""


def _extract_facility_severity(raw_text: str) -> tuple[str, str]:
    explicit = _FACILITY_SEVERITY_RE.search(raw_text)
    if explicit:
        return explicit.group("facility").casefold(), explicit.group("severity").casefold()
    priority = _PRI_RE.search(raw_text)
    if not priority:
        return "", ""
    value = int(priority.group("priority"))
    facilities = (
        "kern", "user", "mail", "daemon", "auth", "syslog", "lpr", "news",
        "uucp", "cron", "authpriv", "ftp", "ntp", "audit", "alert", "clock",
        "local0", "local1", "local2", "local3", "local4", "local5", "local6", "local7",
    )
    severities = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")
    facility_code, severity_code = divmod(value, 8)
    return (
        facilities[facility_code] if 0 <= facility_code < len(facilities) else "",
        severities[severity_code] if 0 <= severity_code < len(severities) else "",
    )


def _parse_active_endpoint(value: str) -> dict[str, Any]:
    candidate = str(value or "").strip()
    if candidate.casefold() == "na_0000-0000-0000(0)":
        return {"radio_mac": "", "peer_mac": "", "rssi": None, "missing": True}
    match = _ACTIVE_LINK_ENDPOINT_RE.fullmatch(candidate)
    if match:
        return {
            "radio_mac": match.group("radio"),
            "peer_mac": match.group("peer"),
            "rssi": int(match.group("rssi")),
            "missing": False,
        }
    single = _ACTIVE_LINK_SINGLE_MAC_ENDPOINT_RE.fullmatch(candidate)
    if single:
        return {
            "radio_mac": "",
            "peer_mac": single.group("peer"),
            "rssi": int(single.group("rssi")),
            "missing": False,
        }
    return {"radio_mac": "", "peer_mac": "", "rssi": None, "missing": False}


def _linkdown_reason_code(reason: str) -> str:
    normalized = " ".join(str(reason or "").casefold().split())
    if "weak rssi" in normalized:
        return "WEAK_RSSI_LOCAL" if "local" in normalized else "WEAK_RSSI"
    if "radio status change" in normalized:
        return "RADIO_STATUS_CHANGE_LOCAL" if "local" in normalized else "RADIO_STATUS_CHANGE"
    return "UNKNOWN"


def _linkdown_reason_label(reason_code: str) -> str:
    return {
        "WEAK_RSSI_LOCAL": "弱信号（本端）",
        "WEAK_RSSI": "弱信号",
        "RADIO_STATUS_CHANGE_LOCAL": "射频状态变化（本端）",
        "RADIO_STATUS_CHANGE": "射频状态变化",
    }.get(reason_code, "未知原因")


def _legacy_link_event(raw_text: str) -> dict[str, Any] | None:
    """Keep historical compact WMESH records parseable when detail fields are absent."""

    match = _LEGACY_PEER_RE.search(raw_text)
    if not match:
        return None
    return {
        "peer_name": match.group("name"),
        "peer_mac": match.group("mac"),
        "previous_peer_name": "",
        "previous_peer_mac": "",
        "details": {"legacy_compact_format": True},
    }


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


def _event_title(event_type: str) -> str:
    return {
        "MESH_LINKUP": "WMESH 链路建立",
        "MESH_LINKDOWN": "WMESH 链路断开",
        "MESH_ACTIVELINK_SWITCH": "WMESH 主链路切换",
        "IFNET_PHY_UPDOWN": "接口物理状态变化",
        "CFGMAN_CFGCHANGED": "设备配置发生变化",
    }.get(event_type, event_type)


def _event_message(parsed: dict[str, Any]) -> str:
    event_type = str(parsed.get("event_type") or "")
    details = dict(parsed.get("details") or {})
    current = str(parsed.get("peer_name") or parsed.get("peer_mac") or "")
    previous = str(
        parsed.get("previous_peer_name")
        or parsed.get("previous_peer_mac")
        or ""
    )
    if event_type == "MESH_ACTIVELINK_SWITCH":
        if details.get("old_active_link_missing"):
            previous = "无主链路"
        return f"{previous or '未知 AP'} → {current or '未知 AP'}"
    if event_type == "MESH_LINKDOWN" and details.get("reason_raw"):
        reason = details.get("reason_label") or details["reason_raw"]
        return f"{current or '未知 AP'}；原因：{reason}"
    if event_type == "IFNET_PHY_UPDOWN":
        return (
            f"{details.get('interface_name') or details.get('interface') or '未知接口'} "
            f"changed to {str(details.get('physical_state') or '').casefold()}"
        ).strip()
    if event_type == "CFGMAN_CFGCHANGED":
        return _cfgman_message(details)
    return current


def _cfgman_message(details: dict[str, Any]) -> str:
    index = str(details.get("cfg_event_index") or "")
    source = str(details.get("cfg_source") or "")
    destination = str(details.get("cfg_destination") or "")
    parts = [f"EventIndex {index}" if index else "配置发生变化"]
    if source or destination:
        parts.append(f"{source or '未知'} → {destination or '未知'}")
    return " · ".join(parts)


def _udp_port_is_available(host: str, port: int) -> bool:
    if not host or port <= 0:
        return True
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind((host, port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


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
        for row in repository.list_raw_files_for_run(run_id)
    }
    recovered = 0
    now = datetime.now().astimezone().isoformat(timespec="milliseconds")
    for relative, row in known.items():
        if row.get("run_id") != run_id or row.get("status") != "OPEN":
            continue
        path = _managed_regular_file(root, relative)
        valid = path is not None
        record_count = (
            _line_count(path) if path else int(row.get("record_count") or 0)
        )
        parse_status = (
            _pending_recovery_parse_status(
                row.get("parse_status"),
                record_count=record_count,
            )
            if valid
            else "MISSING"
        )
        repository.upsert_raw_file(
            {
                **row,
                "end_time": now,
                "record_count": record_count,
                "size_bytes": path.stat().st_size if path else 0,
                "sha256": _sha256(path) if path else "",
                "status": "RECOVERED" if valid else "MISSING",
                "parse_status": parse_status,
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


def _pending_recovery_parse_status(value: object, *, record_count: int) -> str:
    parse_status = str(value or "")
    if not parse_status.startswith("STREAMING@"):
        return "PENDING_RECOVERY"
    cursor, _byte_offset = _parse_recovery_cursor(parse_status)
    if not parse_status.partition("@")[2].partition(":")[0].isdigit():
        return "PENDING_RECOVERY"
    return f"PENDING_RECOVERY@{min(cursor, max(0, int(record_count)))}"


def _parse_recovery_cursor(value: object) -> tuple[int, int | None]:
    payload = str(value or "").partition("@")[2]
    line_text, separator, offset_text = payload.partition(":")
    try:
        line_number = max(0, int(line_text or 0))
    except ValueError:
        return 0, None
    if not separator:
        return line_number, None
    try:
        return line_number, max(0, int(offset_text))
    except ValueError:
        return line_number, None


def _format_recovery_cursor(*, line_number: int, byte_offset: int) -> str:
    return (
        f"PENDING_RECOVERY@{max(0, int(line_number))}:"
        f"{max(0, int(byte_offset))}"
    )


def _seek_recovery_cursor(
    handle: Any,
    *,
    line_cursor: int,
    byte_offset: int | None,
    file_size: int,
) -> tuple[int, int]:
    if byte_offset is not None and 0 <= byte_offset <= file_size:
        boundary_valid = byte_offset == 0
        if byte_offset > 0:
            handle.seek(byte_offset - 1)
            boundary_valid = handle.read(1) == b"\n"
        if boundary_valid:
            handle.seek(byte_offset)
            return max(0, int(line_cursor)), byte_offset
    handle.seek(0)
    actual_line = 0
    while actual_line < max(0, int(line_cursor)):
        if not handle.readline():
            break
        actual_line += 1
    return actual_line, handle.tell()


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


def _managed_regular_file(root: Path, relative_path: str) -> Path | None:
    relative = Path(relative_path)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        return None
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or _is_junction(current):
            return None
    resolved = current.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


__all__ = [
    "RawStreamWriter",
    "SyslogUdpReceiver",
    "UdpEnvelope",
    "WmeshRealtimeParser",
    "recover_raw_files",
]
