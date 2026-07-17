from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from threading import Lock
from typing import Any, BinaryIO


_MAGIC = b"NCJB1"
_MAX_PAYLOAD_BYTES = 64 * 1024


class SensitiveBootstrapError(RuntimeError):
    pass


class SensitiveBootstrap:
    """仅存在于单个 worker 内存中的一次性敏感启动数据。"""

    def __init__(self, values: Mapping[str, str]) -> None:
        normalized = {str(key): str(value) for key, value in values.items()}
        if not normalized or any(not key or not value for key, value in normalized.items()):
            raise SensitiveBootstrapError("敏感启动数据无效")
        self._values: dict[str, str] | None = normalized
        self._lock = Lock()

    def consume(self) -> dict[str, str]:
        with self._lock:
            if self._values is None:
                raise SensitiveBootstrapError("敏感启动数据已消费")
            values = self._values
            self._values = None
        return values

    def clear(self) -> None:
        with self._lock:
            self._values = None


def encode_sensitive_bootstrap(values: Mapping[str, str]) -> bytearray:
    normalized = {str(key): str(value) for key, value in values.items()}
    if not normalized or any(not key or not value for key, value in normalized.items()):
        raise SensitiveBootstrapError("敏感启动数据无效")
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise SensitiveBootstrapError("敏感启动数据过大")
    return bytearray(_MAGIC + struct.pack(">I", len(payload)) + payload)


def read_sensitive_bootstrap(stream: BinaryIO) -> SensitiveBootstrap:
    header = stream.read(len(_MAGIC) + 4)
    if len(header) != len(_MAGIC) + 4 or not header.startswith(_MAGIC):
        raise SensitiveBootstrapError("敏感启动数据不可用，任务不能恢复")
    size = struct.unpack(">I", header[len(_MAGIC) :])[0]
    if size <= 0 or size > _MAX_PAYLOAD_BYTES:
        raise SensitiveBootstrapError("敏感启动数据无效")
    raw = bytearray(stream.read(size))
    try:
        if len(raw) != size or stream.read(1):
            raise SensitiveBootstrapError("敏感启动数据无效")
        parsed: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise SensitiveBootstrapError("敏感启动数据无效")
        return SensitiveBootstrap(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SensitiveBootstrapError("敏感启动数据无效") from exc
    finally:
        raw[:] = b"\x00" * len(raw)


def redact_sensitive_values(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {str(key): redact_sensitive_values(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_sensitive_values(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "<redacted>")
        return redacted
    return value


__all__ = [
    "SensitiveBootstrap",
    "SensitiveBootstrapError",
    "encode_sensitive_bootstrap",
    "read_sensitive_bootstrap",
    "redact_sensitive_values",
]
