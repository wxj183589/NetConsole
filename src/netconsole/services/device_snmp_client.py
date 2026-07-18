from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from random import randint
from typing import Any

from netconsole.models.device_snmp import (
    DeviceSnmpProfile,
    DeviceSnmpQueryResult,
    DeviceSnmpVarBind,
)
from netconsole.utils.text_encoding import decode_bytes_with_fallback


SYS_OIDS = {
    "sysDescr.0": "1.3.6.1.2.1.1.1.0",
    "sysObjectID.0": "1.3.6.1.2.1.1.2.0",
    "sysUpTime.0": "1.3.6.1.2.1.1.3.0",
    "sysName.0": "1.3.6.1.2.1.1.5.0",
    "ifDescr": "1.3.6.1.2.1.2.2.1.2",
}


class DeviceSnmpClient:
    """设备管理专用的 SNMP v1/v2c 只读探测客户端。"""

    def _get(self, profile: DeviceSnmpProfile, oid: str) -> DeviceSnmpQueryResult:
        return self._single(profile, normalize_oid(oid), pdu_type=0xA0)

    def _get_next(self, profile: DeviceSnmpProfile, oid: str) -> DeviceSnmpQueryResult:
        return self._single(profile, normalize_oid(oid), pdu_type=0xA1)

    def _walk(
        self,
        profile: DeviceSnmpProfile,
        oid: str,
        *,
        max_rows: int = 200,
        cancel_checker=None,
    ) -> DeviceSnmpQueryResult:
        root = normalize_oid(oid)
        started = time.perf_counter()
        rows: list[DeviceSnmpVarBind] = []
        current = root
        status = "success"
        error = ""
        limit = max(1, int(max_rows))
        for _ in range(limit):
            if cancel_checker is not None and cancel_checker():
                status = "cancelled"
                error = "查询已取消。"
                break
            result = self._get_next(profile, current)
            if result.status != "success":
                status = "empty_table" if result.status == "end_of_mib_view" and not rows else result.status
                error = result.error_message
                break
            if not result.rows:
                status = "empty_table" if not rows else "success"
                break
            row = result.rows[0]
            if not oid_starts_with(row.oid, root):
                if not rows:
                    status = "empty_table"
                break
            if _oid_key(row.oid) <= _oid_key(current):
                status = "failed"
                error = "SNMP 设备返回了非递增 OID。"
                break
            rows.append(row)
            current = row.oid
        elapsed = int((time.perf_counter() - started) * 1000)
        return DeviceSnmpQueryResult(
            rows=rows,
            status=status,
            error_message=error,
            elapsed_ms=elapsed,
        )

    def test_device(self, profile: DeviceSnmpProfile, *, cancel_checker=None) -> dict[str, Any]:
        started = time.perf_counter()
        result: dict[str, Any] = {"status": "success", "latency_ms": 0, "error_message": ""}
        for label, oid in (
            ("sysName", SYS_OIDS["sysName.0"]),
            ("sysObjectID", SYS_OIDS["sysObjectID.0"]),
            ("sysDescr", SYS_OIDS["sysDescr.0"]),
            ("sysUpTime", SYS_OIDS["sysUpTime.0"]),
        ):
            if cancel_checker is not None and cancel_checker():
                result.update({"status": "cancelled", "error_message": "测试已取消。"})
                break
            query = self._get(profile, oid)
            if query.status == "success" and query.rows:
                result[label] = str(query.rows[0].value)
            elif label == "sysName":
                result.update({"status": query.status, "error_message": query.error_message})
                break
        if result["status"] == "success":
            interfaces = self._walk(
                profile,
                SYS_OIDS["ifDescr"],
                max_rows=50,
                cancel_checker=cancel_checker,
            )
            result["interface_count"] = len(interfaces.rows)
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    @staticmethod
    def decode_value(value: Any) -> str:
        return str(value)

    @staticmethod
    def _single(
        profile: DeviceSnmpProfile,
        oid: str,
        *,
        pdu_type: int,
    ) -> DeviceSnmpQueryResult:
        started = time.perf_counter()
        try:
            response = _DeviceSnmpWireClient(profile).request([oid], pdu_type=pdu_type)
        except TimeoutError:
            return DeviceSnmpQueryResult(
                status="timeout",
                error_message="SNMP 请求超时。",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception:
            return DeviceSnmpQueryResult(
                status="failed",
                error_message="SNMP 请求失败。",
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        rows = [
            DeviceSnmpVarBind(
                oid=row.oid,
                value=row.value,
                value_type=row.value_type,
                status=row.status,
                error_message=row.error_message,
            )
            for row in response.varbinds
        ]
        return DeviceSnmpQueryResult(
            rows=rows,
            status=response.status,
            error_message=response.error_message,
            elapsed_ms=elapsed,
        )


@dataclass(frozen=True)
class _WireVarBind:
    oid: str
    value: Any
    value_type: str
    status: str = "success"
    error_message: str = ""


@dataclass(frozen=True)
class _WireResponse:
    status: str
    error_message: str
    varbinds: list[_WireVarBind]


class _DeviceSnmpWireClient:
    def __init__(self, profile: DeviceSnmpProfile) -> None:
        self.profile = profile
        self.version_number = 0 if profile.version == "v1" else 1

    def request(self, oids: list[str], *, pdu_type: int) -> _WireResponse:
        request_id = randint(1, 2**31 - 1)
        packet = self._build_packet(oids, request_id, pdu_type=pdu_type)
        timeout = max(0.1, self.profile.timeout_ms / 1000)
        attempts = max(1, int(self.profile.retries) + 1)
        for _ in range(attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                try:
                    sock.sendto(packet, (self.profile.host, int(self.profile.port)))
                    data, _address = sock.recvfrom(65535)
                    return self._parse_response(data)
                except socket.timeout:
                    continue
        raise TimeoutError("SNMP timeout")

    def _build_packet(self, oids: list[str], request_id: int, *, pdu_type: int) -> bytes:
        varbinds = b"".join(_seq(_oid(oid) + _null()) for oid in oids)
        pdu_body = _int(request_id) + _int(0) + _int(0) + _seq(varbinds)
        pdu = bytes([pdu_type]) + _len(len(pdu_body)) + pdu_body
        return _seq(
            _int(self.version_number)
            + _octet(self.profile.community_ro)
            + pdu
        )

    @staticmethod
    def _parse_response(data: bytes) -> _WireResponse:
        decoder = _BerReader(data)
        _tag, content = decoder.read_tlv(expected=0x30)
        message = _BerReader(content)
        message.read_int()
        message.read_octet()
        pdu_tag, pdu_content = message.read_tlv()
        if pdu_tag != 0xA2:
            raise RuntimeError(f"unexpected SNMP PDU: {pdu_tag:#x}")
        pdu = _BerReader(pdu_content)
        pdu.read_int()
        error_status = pdu.read_int()
        error_index = pdu.read_int()
        status, error_message = _error_status(error_status, error_index)
        _tag, varbind_content = pdu.read_tlv(expected=0x30)
        varbind_reader = _BerReader(varbind_content)
        rows: list[_WireVarBind] = []
        while not varbind_reader.eof:
            _tag, row_content = varbind_reader.read_tlv(expected=0x30)
            row_reader = _BerReader(row_content)
            oid = row_reader.read_oid()
            value_type, value = row_reader.read_value()
            row_status = _value_status(value_type)
            row_error = _status_message(row_status) if row_status != "success" else ""
            if row_status != "success":
                status = row_status
                error_message = row_error
            rows.append(
                _WireVarBind(
                    oid=oid,
                    value=value,
                    value_type=value_type,
                    status=row_status,
                    error_message=row_error,
                )
            )
        return _WireResponse(status=status, error_message=error_message, varbinds=rows)


class _BerReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    @property
    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def read_tlv(self, expected: int | None = None) -> tuple[int, bytes]:
        if self.pos >= len(self.data):
            raise ValueError("truncated BER")
        tag = self.data[self.pos]
        self.pos += 1
        length = self._read_length()
        value = self.data[self.pos : self.pos + length]
        self.pos += length
        if expected is not None and tag != expected:
            raise ValueError(f"BER tag mismatch: expected {expected:#x}, got {tag:#x}")
        return tag, value

    def _read_length(self) -> int:
        first = self.data[self.pos]
        self.pos += 1
        if first < 0x80:
            return first
        count = first & 0x7F
        value = int.from_bytes(self.data[self.pos : self.pos + count], "big")
        self.pos += count
        return value

    def read_int(self) -> int:
        _tag, value = self.read_tlv(expected=0x02)
        return int.from_bytes(value, "big", signed=True) if value else 0

    def read_octet(self) -> bytes:
        _tag, value = self.read_tlv(expected=0x04)
        return value

    def read_oid(self) -> str:
        _tag, value = self.read_tlv(expected=0x06)
        return _decode_oid(value)

    def read_value(self) -> tuple[str, Any]:
        tag, value = self.read_tlv()
        if tag == 0x02:
            return "INTEGER", int.from_bytes(value, "big", signed=True) if value else 0
        if tag == 0x04:
            return "OCTET STRING", _decode_octets(value)
        if tag == 0x05:
            return "NULL", ""
        if tag == 0x06:
            return "OBJECT IDENTIFIER", _decode_oid(value)
        if tag == 0x40:
            return "IpAddress", ".".join(str(part) for part in value)
        if tag == 0x41:
            return "Counter32", int.from_bytes(value, "big", signed=False)
        if tag == 0x42:
            return "Gauge32", int.from_bytes(value, "big", signed=False)
        if tag == 0x43:
            return "TimeTicks", int.from_bytes(value, "big", signed=False)
        if tag == 0x46:
            return "Counter64", int.from_bytes(value, "big", signed=False)
        if tag == 0x80:
            return "noSuchObject", "noSuchObject"
        if tag == 0x81:
            return "noSuchInstance", "noSuchInstance"
        if tag == 0x82:
            return "endOfMibView", "endOfMibView"
        return f"TAG:{tag:#x}", value.hex()


def normalize_oid(oid: str) -> str:
    text = str(oid or "").strip()
    if text in SYS_OIDS:
        text = SYS_OIDS[text]
    text = text.removeprefix(".")
    if not text:
        raise ValueError("OID 不能为空。")
    if not all(part.isdigit() for part in text.split(".")):
        raise ValueError("设备 SNMP 探测必须使用数字 OID。")
    return text


def oid_starts_with(oid: str, root: str) -> bool:
    value = normalize_oid(oid)
    prefix = normalize_oid(root)
    return value == prefix or value.startswith(prefix + ".")


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in normalize_oid(oid).split("."))


def _seq(value: bytes) -> bytes:
    return bytes([0x30]) + _len(len(value)) + value


def _int(value: int) -> bytes:
    raw = int(value).to_bytes(max(1, (int(value).bit_length() + 8) // 8), "big", signed=True)
    return bytes([0x02]) + _len(len(raw)) + raw


def _octet(value: str) -> bytes:
    raw = str(value or "").encode("utf-8")
    return bytes([0x04]) + _len(len(raw)) + raw


def _null() -> bytes:
    return b"\x05\x00"


def _oid(value: str) -> bytes:
    parts = [int(part) for part in normalize_oid(value).split(".")]
    if len(parts) < 2:
        raise ValueError("OID 至少需要两段。")
    encoded = bytes([parts[0] * 40 + parts[1]]) + b"".join(_base128(part) for part in parts[2:])
    return bytes([0x06]) + _len(len(encoded)) + encoded


def _base128(value: int) -> bytes:
    if value == 0:
        return b"\x00"
    chunks: list[int] = []
    while value:
        chunks.append(value & 0x7F)
        value >>= 7
    chunks.reverse()
    for index in range(len(chunks) - 1):
        chunks[index] |= 0x80
    return bytes(chunks)


def _len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = int(length).to_bytes((int(length).bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _decode_oid(value: bytes) -> str:
    if not value:
        return ""
    first = value[0]
    parts = [first // 40, first % 40]
    current = 0
    for byte in value[1:]:
        current = (current << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(current)
            current = 0
    return ".".join(str(part) for part in parts)


def _decode_octets(value: bytes) -> str:
    try:
        return decode_bytes_with_fallback(value, replace_on_failure=False).text
    except ValueError:
        return value.hex()


def _error_status(error_status: int, error_index: int) -> tuple[str, str]:
    if error_status == 0:
        return "success", ""
    status = {
        1: "too_big",
        2: "no_such_object",
        3: "invalid_value",
        5: "failed",
        16: "auth_failed",
    }.get(error_status, "failed")
    return status, f"SNMP 错误：{status}，索引 {error_index}"


def _value_status(value_type: str) -> str:
    return {
        "noSuchObject": "no_such_object",
        "noSuchInstance": "no_such_instance",
        "endOfMibView": "end_of_mib_view",
    }.get(value_type, "success")


def _status_message(status: str) -> str:
    return {
        "no_such_object": "OID 不存在。",
        "no_such_instance": "OID 实例不存在。",
        "end_of_mib_view": "已到达视图末尾。",
    }.get(status, "")
