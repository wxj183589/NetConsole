from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv4Address
from random import randint
from typing import Any

from netconsole.models.snmp_models import SnmpProfile, SnmpQueryRequest, SnmpQueryResult, SnmpSetRequest, SnmpSetResult, SnmpVarBind


SYS_OIDS = {
    "sysDescr.0": "1.3.6.1.2.1.1.1.0",
    "sysObjectID.0": "1.3.6.1.2.1.1.2.0",
    "sysUpTime.0": "1.3.6.1.2.1.1.3.0",
    "sysName.0": "1.3.6.1.2.1.1.5.0",
    "ifDescr": "1.3.6.1.2.1.2.2.1.2",
}


class SnmpClient:
    def get(self, profile: SnmpProfile, oid: str) -> SnmpQueryResult:
        request = SnmpQueryRequest(profile=profile, method="Get", oid=normalize_oid(oid), save_history=False)
        return self._single(request, pdu_type=0xA0)

    def get_next(self, profile: SnmpProfile, oid: str) -> SnmpQueryResult:
        request = SnmpQueryRequest(profile=profile, method="GetNext", oid=normalize_oid(oid), save_history=False)
        return self._single(request, pdu_type=0xA1)

    def walk(self, profile: SnmpProfile, oid: str, *, max_rows: int = 200, cancel_checker=None) -> SnmpQueryResult:
        root = normalize_oid(oid)
        request = SnmpQueryRequest(profile=profile, method="Walk", oid=root, max_rows=max_rows, save_history=False)
        started = time.perf_counter()
        rows: list[SnmpVarBind] = []
        current = root
        status = "success"
        error = ""
        for _ in range(max(1, int(max_rows))):
            if cancel_checker is not None and cancel_checker():
                status = "cancelled"
                error = "查询已取消。"
                break
            result = self._single(SnmpQueryRequest(profile=profile, method="GetNext", oid=current, save_history=False), pdu_type=0xA1)
            if result.status != "success":
                status = result.status
                error = result.error_message
                break
            if not result.rows:
                status = "empty_table" if not rows else "success"
                break
            row = result.rows[0]
            if not oid_starts_with(row.oid, root):
                break
            rows.append(row)
            current = row.oid
        elapsed = int((time.perf_counter() - started) * 1000)
        return SnmpQueryResult(request=request, rows=rows, status=status, error_message=error, elapsed_ms=elapsed)

    def bulk_walk(self, profile: SnmpProfile, oid: str, *, max_repetitions: int = 10, max_rows: int = 200, cancel_checker=None) -> SnmpQueryResult:
        if profile.version.lower() == "v1":
            return self.walk(profile, oid, max_rows=max_rows, cancel_checker=cancel_checker)
        root = normalize_oid(oid)
        request = SnmpQueryRequest(profile=profile, method="BulkWalk", oid=root, max_repetitions=max_repetitions, max_rows=max_rows, save_history=False)
        started = time.perf_counter()
        rows: list[SnmpVarBind] = []
        current = root
        status = "success"
        error = ""
        while len(rows) < max_rows:
            if cancel_checker is not None and cancel_checker():
                status = "cancelled"
                error = "查询已取消。"
                break
            result = self._bulk(request, current, max_repetitions=max_repetitions)
            if result.status != "success":
                status = result.status
                error = result.error_message
                break
            if not result.rows:
                status = "empty_table" if not rows else "success"
                break
            advanced = False
            for row in result.rows:
                if not oid_starts_with(row.oid, root):
                    advanced = False
                    break
                rows.append(row)
                current = row.oid
                advanced = True
                if len(rows) >= max_rows:
                    break
            if not advanced:
                break
        elapsed = int((time.perf_counter() - started) * 1000)
        return SnmpQueryResult(request=request, rows=rows, status=status, error_message=error, elapsed_ms=elapsed)

    def table_walk(self, profile: SnmpProfile, oid: str, *, max_repetitions: int = 10, max_rows: int = 500, cancel_checker=None) -> SnmpQueryResult:
        result = self.bulk_walk(profile, oid, max_repetitions=max_repetitions, max_rows=max_rows, cancel_checker=cancel_checker)
        return SnmpQueryResult(request=SnmpQueryRequest(profile=profile, method="Table Walk", oid=normalize_oid(oid), max_repetitions=max_repetitions, max_rows=max_rows, save_history=False), rows=result.rows, status=result.status, error_message=result.error_message, elapsed_ms=result.elapsed_ms)

    def set_value(self, request: SnmpSetRequest) -> SnmpSetResult:
        started = time.perf_counter()
        if request.profile.version.lower() == "v3":
            return SnmpSetResult(request=request, status="auth_failed", error_message="当前内置 SNMPv3 适配层暂不支持 Set，请检查设备 SNMPv3 写权限并接入兼容库。")
        if not request.profile.community_rw:
            return SnmpSetResult(request=request, status="auth_failed", error_message="当前设备未配置 SNMP 写团体字 community_rw，不能执行 Set。")
        try:
            oid = normalize_oid(request.oid)
            response = _SnmpWireClient(request.profile).set_value(oid, request.data_type, request.value)
        except TimeoutError:
            return SnmpSetResult(request=request, status="timeout", error_message="SNMP Set 请求超时。", elapsed_ms=int((time.perf_counter() - started) * 1000))
        except ValueError as exc:
            return SnmpSetResult(request=request, status="invalid_value", error_message=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
        except PermissionError as exc:
            return SnmpSetResult(request=request, status="auth_failed", error_message=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
        except Exception as exc:
            return SnmpSetResult(request=request, status="failed", error_message=f"SNMP Set 请求失败：{exc}", elapsed_ms=int((time.perf_counter() - started) * 1000))
        elapsed = int((time.perf_counter() - started) * 1000)
        result_value = str(response.varbinds[0].value) if response.varbinds else ""
        return SnmpSetResult(request=request, new_value=str(request.value), result_value=result_value, status=response.status, error_message=response.error_message, elapsed_ms=elapsed)

    def test_device(self, profile: SnmpProfile, *, cancel_checker=None) -> dict[str, Any]:
        started = time.perf_counter()
        result: dict[str, Any] = {"status": "success", "latency_ms": 0, "error_message": ""}
        for label, oid in (("sysName", SYS_OIDS["sysName.0"]), ("sysObjectID", SYS_OIDS["sysObjectID.0"]), ("sysDescr", SYS_OIDS["sysDescr.0"]), ("sysUpTime", SYS_OIDS["sysUpTime.0"])):
            if cancel_checker is not None and cancel_checker():
                result.update({"status": "cancelled", "error_message": "测试已取消。"})
                break
            query = self.get(profile, oid)
            if query.status == "success" and query.rows:
                result[label] = str(query.rows[0].value)
            elif label == "sysName":
                result.update({"status": query.status, "error_message": query.error_message})
                break
        if result["status"] == "success":
            if_result = self.walk(profile, SYS_OIDS["ifDescr"], max_rows=50, cancel_checker=cancel_checker)
            result["interface_count"] = len(if_result.rows)
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    def decode_value(self, oid: str, value: Any, enum_map: dict[str, str] | None = None) -> str:
        text = str(value)
        if enum_map and text in enum_map:
            return enum_map[text]
        return text

    def _single(self, request: SnmpQueryRequest, *, pdu_type: int) -> SnmpQueryResult:
        started = time.perf_counter()
        if request.profile.version.lower() == "v3":
            return SnmpQueryResult(request=request, status="unsupported", error_message="当前内置适配层暂不支持 SNMPv3，请后续接入兼容 Python 3.13 的 SNMP 库。")
        try:
            response = _SnmpWireClient(request.profile).request([request.oid], pdu_type=pdu_type)
        except TimeoutError:
            return SnmpQueryResult(request=request, status="timeout", error_message="SNMP 请求超时。", elapsed_ms=int((time.perf_counter() - started) * 1000))
        except PermissionError as exc:
            return SnmpQueryResult(request=request, status="auth_failed", error_message=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
        except Exception as exc:
            return SnmpQueryResult(request=request, status="failed", error_message=f"SNMP 请求失败：{exc}", elapsed_ms=int((time.perf_counter() - started) * 1000))
        elapsed = int((time.perf_counter() - started) * 1000)
        status = response.status
        error = response.error_message
        rows = [SnmpVarBind(oid=row.oid, value=row.value, value_type=row.value_type, decoded_value=str(row.value), latency_ms=elapsed, status=status, error_message=error) for row in response.varbinds]
        return SnmpQueryResult(request=request, rows=rows, status=status, error_message=error, elapsed_ms=elapsed)

    def _bulk(self, request: SnmpQueryRequest, oid: str, *, max_repetitions: int) -> SnmpQueryResult:
        started = time.perf_counter()
        try:
            response = _SnmpWireClient(request.profile).request([oid], pdu_type=0xA5, max_repetitions=max_repetitions)
        except TimeoutError:
            return SnmpQueryResult(request=request, status="timeout", error_message="SNMP BulkWalk 请求超时。", elapsed_ms=int((time.perf_counter() - started) * 1000))
        except Exception as exc:
            return SnmpQueryResult(request=request, status="failed", error_message=f"SNMP BulkWalk 请求失败：{exc}", elapsed_ms=int((time.perf_counter() - started) * 1000))
        elapsed = int((time.perf_counter() - started) * 1000)
        rows = [SnmpVarBind(oid=row.oid, value=row.value, value_type=row.value_type, decoded_value=str(row.value), latency_ms=elapsed, status=response.status, error_message=response.error_message) for row in response.varbinds]
        return SnmpQueryResult(request=request, rows=rows, status=response.status, error_message=response.error_message, elapsed_ms=elapsed)


@dataclass(frozen=True)
class _WireVarBind:
    oid: str
    value: Any
    value_type: str


@dataclass(frozen=True)
class _WireResponse:
    status: str
    error_message: str
    varbinds: list[_WireVarBind]


class _SnmpWireClient:
    def __init__(self, profile: SnmpProfile) -> None:
        self.profile = profile
        self.version_number = 0 if profile.version.lower() == "v1" else 1

    def request(self, oids: list[str], *, pdu_type: int, max_repetitions: int = 10) -> _WireResponse:
        request_id = randint(1, 2**31 - 1)
        packet = self._build_packet(oids, request_id, pdu_type=pdu_type, max_repetitions=max_repetitions)
        timeout = max(0.1, self.profile.timeout_ms / 1000)
        attempts = max(1, int(self.profile.retries) + 1)
        last_timeout = False
        for _ in range(attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                try:
                    sock.sendto(packet, (self.profile.host, int(self.profile.port)))
                    data, _addr = sock.recvfrom(65535)
                    return self._parse_response(data)
                except socket.timeout:
                    last_timeout = True
                    continue
        if last_timeout:
            raise TimeoutError("SNMP timeout")
        raise RuntimeError("SNMP request failed")

    def set_value(self, oid: str, data_type: str, value: str) -> _WireResponse:
        request_id = randint(1, 2**31 - 1)
        encoded_value = _encode_snmp_value(data_type, value)
        packet = self._build_packet([oid], request_id, pdu_type=0xA3, max_repetitions=10, encoded_values=[encoded_value], community=self.profile.community_rw)
        timeout = max(0.1, self.profile.timeout_ms / 1000)
        attempts = max(1, int(self.profile.retries) + 1)
        last_timeout = False
        for _ in range(attempts):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                try:
                    sock.sendto(packet, (self.profile.host, int(self.profile.port)))
                    data, _addr = sock.recvfrom(65535)
                    return self._parse_response(data)
                except socket.timeout:
                    last_timeout = True
                    continue
        if last_timeout:
            raise TimeoutError("SNMP timeout")
        raise RuntimeError("SNMP Set request failed")

    def _build_packet(self, oids: list[str], request_id: int, *, pdu_type: int, max_repetitions: int, encoded_values: list[bytes] | None = None, community: str | None = None) -> bytes:
        values = encoded_values or [_null() for _ in oids]
        varbinds = b"".join(_seq(_oid(oid) + value) for oid, value in zip(oids, values))
        varbind_list = _seq(varbinds)
        if pdu_type == 0xA5:
            pdu_body = _int(request_id) + _int(0) + _int(max(1, int(max_repetitions))) + varbind_list
        else:
            pdu_body = _int(request_id) + _int(0) + _int(0) + varbind_list
        pdu = bytes([pdu_type]) + _len(len(pdu_body)) + pdu_body
        return _seq(_int(self.version_number) + _octet(community if community is not None else self.profile.community_ro) + pdu)

    def _parse_response(self, data: bytes) -> _WireResponse:
        decoder = _BerReader(data)
        _tag, content = decoder.read_tlv(expected=0x30)
        msg = _BerReader(content)
        _version = msg.read_int()
        _community = msg.read_octet()
        pdu_tag, pdu_content = msg.read_tlv()
        if pdu_tag != 0xA2:
            raise RuntimeError(f"unexpected SNMP PDU: {pdu_tag:#x}")
        pdu = _BerReader(pdu_content)
        _request_id = pdu.read_int()
        error_status = pdu.read_int()
        error_index = pdu.read_int()
        status, error_message = _error_status(error_status, error_index)
        _vb_tag, vb_content = pdu.read_tlv(expected=0x30)
        vb_reader = _BerReader(vb_content)
        rows: list[_WireVarBind] = []
        while not vb_reader.eof:
            _seq_tag, row_content = vb_reader.read_tlv(expected=0x30)
            row_reader = _BerReader(row_content)
            oid = row_reader.read_oid()
            value_type, value = row_reader.read_value()
            row_status = _value_status(value_type)
            if row_status != "success":
                status = row_status
                error_message = _status_message(row_status)
            rows.append(_WireVarBind(oid=oid, value=value, value_type=value_type))
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
    if text.startswith("."):
        text = text[1:]
    if not text:
        raise ValueError("OID 不能为空。")
    if not all(part.isdigit() for part in text.split(".")):
        raise ValueError("最终 SNMP 查询必须使用数字 OID。")
    return text


def oid_starts_with(oid: str, root: str) -> bool:
    oid = normalize_oid(oid)
    root = normalize_oid(root)
    return oid == root or oid.startswith(root + ".")


def _seq(value: bytes) -> bytes:
    return bytes([0x30]) + _len(len(value)) + value


def _int(value: int) -> bytes:
    raw = int(value).to_bytes(max(1, (int(value).bit_length() + 8) // 8), "big", signed=True)
    return bytes([0x02]) + _len(len(raw)) + raw


def _octet(value: str) -> bytes:
    raw = str(value or "").encode("utf-8")
    return bytes([0x04]) + _len(len(raw)) + raw


def _raw_octet(value: bytes) -> bytes:
    return bytes([0x04]) + _len(len(value)) + value


def _null() -> bytes:
    return b"\x05\x00"


def _oid(value: str) -> bytes:
    parts = [int(part) for part in normalize_oid(value).split(".")]
    if len(parts) < 2:
        raise ValueError("OID 至少需要两段。")
    encoded = bytes([parts[0] * 40 + parts[1]]) + b"".join(_base128(part) for part in parts[2:])
    return bytes([0x06]) + _len(len(encoded)) + encoded


def _application_value(tag: int, value: int) -> bytes:
    raw = int(value).to_bytes(max(1, (int(value).bit_length() + 7) // 8), "big", signed=False)
    return bytes([tag]) + _len(len(raw)) + raw


def _encode_snmp_value(data_type: str, value: str) -> bytes:
    kind = str(data_type or "").strip().lower().replace(" ", "")
    text = str(value or "").strip()
    if kind in {"integer", "integer32"}:
        return _int(int(text))
    if kind in {"unsigned32", "unsignedinteger", "gauge32", "gauge"}:
        number = int(text)
        if number < 0:
            raise ValueError("Unsigned32/Gauge32 不能为负数。")
        return _application_value(0x42, number)
    if kind == "counter32":
        number = int(text)
        if number < 0:
            raise ValueError("Counter32 不能为负数。")
        return _application_value(0x41, number)
    if kind == "counter64":
        number = int(text)
        if number < 0:
            raise ValueError("Counter64 不能为负数。")
        return _application_value(0x46, number)
    if kind in {"octetstring", "displaystring", "bits", "float"}:
        return _octet(text)
    if kind == "dateandtime":
        return _raw_octet(_encode_date_and_time(text))
    if kind == "hexstring":
        compact = text.replace("0x", "").replace("0X", "").replace(" ", "")
        if len(compact) % 2:
            raise ValueError("HexString 长度必须为偶数。")
        try:
            return _raw_octet(bytes.fromhex(compact))
        except ValueError as exc:
            raise ValueError("HexString 只能包含十六进制字符。") from exc
    if kind == "ipaddress":
        raw = IPv4Address(text).packed
        return bytes([0x40]) + _len(len(raw)) + raw
    if kind in {"objectidentifier", "objectid", "oid"}:
        return _oid(text)
    if kind == "timeticks":
        number = int(text)
        if number < 0:
            raise ValueError("TimeTicks 不能为负数。")
        return _application_value(0x43, number)
    if kind in {"boolean", "truthvalue"}:
        lowered = text.lower()
        if lowered in {"true", "1", "enabled", "enable", "yes"}:
            return _int(1)
        if lowered in {"false", "2", "disabled", "disable", "no"}:
            return _int(2)
        raise ValueError("Boolean/TruthValue 请输入 true/false、1/2 或 enabled/disabled。")
    raise ValueError(f"不支持的 SNMP Set 数据类型：{data_type}")


def _encode_date_and_time(value: str) -> bytes:
    text = str(value or "").strip()
    for fmt in ("%y-%m-%d,%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return bytes(
                [
                    (parsed.year >> 8) & 0xFF,
                    parsed.year & 0xFF,
                    parsed.month,
                    parsed.day,
                    parsed.hour,
                    parsed.minute,
                    parsed.second,
                    0,
                ]
            )
        except ValueError:
            continue
    return text.encode("utf-8")


def _base128(value: int) -> bytes:
    if value == 0:
        return b"\x00"
    chunks: list[int] = []
    while value:
        chunks.append(value & 0x7F)
        value >>= 7
    chunks = list(reversed(chunks))
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
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.hex()


def _error_status(error_status: int, error_index: int) -> tuple[str, str]:
    if error_status == 0:
        return "success", ""
    mapping = {
        1: "too_big",
        2: "no_such_object",
        3: "invalid_value",
        4: "not_writable",
        5: "commit_failed",
        16: "auth_failed",
    }
    status = mapping.get(error_status, "failed")
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
        "end_of_mib_view": "已到达 MIB 视图末尾。",
    }.get(status, "")
