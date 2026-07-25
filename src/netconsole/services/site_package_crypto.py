from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


ALGORITHM = "AES-256-GCM"
KDF_NAME = "scrypt"
KDF_N = 2**15
KDF_R = 8
KDF_P = 1
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16
_CHUNK_BYTES = 1024 * 1024


class SitePackageCryptoError(RuntimeError):
    pass


def new_encryption_metadata() -> dict[str, object]:
    return {
        "algorithm": ALGORITHM,
        "kdf": KDF_NAME,
        "n": KDF_N,
        "r": KDF_R,
        "p": KDF_P,
        "salt_b64": _encode(os.urandom(SALT_BYTES)),
        "nonce_b64": _encode(os.urandom(NONCE_BYTES)),
        "aad_version": 1,
        "payload": "payload.enc",
    }


def encrypt_file(
    source: Path,
    destination: Path,
    *,
    password: str,
    metadata: dict[str, object],
    aad: bytes,
) -> None:
    _validate_password(password)
    salt, nonce, n, r, p = _parameters(metadata)
    key = bytearray(_derive_key(password, salt, n=n, r=r, p=p))
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        encryptor = Cipher(algorithms.AES(bytes(key)), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(aad)
        with Path(source).open("rb") as input_stream, destination.open("wb") as output:
            for chunk in iter(lambda: input_stream.read(_CHUNK_BYTES), b""):
                output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            output.flush()
            os.fsync(output.fileno())
        metadata["tag_b64"] = _encode(encryptor.tag)
    finally:
        key[:] = b"\x00" * len(key)


def decrypt_stream(
    source: BinaryIO,
    destination: Path,
    *,
    password: str,
    metadata: Mapping[str, object],
    aad: bytes,
) -> None:
    _validate_password(password)
    salt, nonce, n, r, p = _parameters(metadata)
    tag = _decode(metadata.get("tag_b64"), expected=TAG_BYTES)
    key = bytearray(_derive_key(password, salt, n=n, r=r, p=p))
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        decryptor = Cipher(
            algorithms.AES(bytes(key)),
            modes.GCM(nonce, tag),
        ).decryptor()
        decryptor.authenticate_additional_data(aad)
        with destination.open("wb") as output:
            for chunk in iter(lambda: source.read(_CHUNK_BYTES), b""):
                output.write(decryptor.update(chunk))
            output.write(decryptor.finalize())
            output.flush()
            os.fsync(output.fileno())
    except InvalidTag as exc:
        destination.unlink(missing_ok=True)
        raise SitePackageCryptoError("迁移密码错误或数据包认证失败") from exc
    finally:
        key[:] = b"\x00" * len(key)


def _derive_key(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    try:
        return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(
            password.encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise SitePackageCryptoError("数据包加密参数无效") from exc


def _parameters(
    metadata: Mapping[str, object],
) -> tuple[bytes, bytes, int, int, int]:
    try:
        aad_version = int(metadata.get("aad_version") or 0)
        n = int(metadata.get("n") or 0)
        r = int(metadata.get("r") or 0)
        p = int(metadata.get("p") or 0)
    except (TypeError, ValueError) as exc:
        raise SitePackageCryptoError("数据包加密参数无效") from exc
    if (
        metadata.get("algorithm") != ALGORITHM
        or metadata.get("kdf") != KDF_NAME
        or aad_version != 1
        or metadata.get("payload") != "payload.enc"
    ):
        raise SitePackageCryptoError("数据包加密格式不受支持")
    if (n, r, p) != (KDF_N, KDF_R, KDF_P):
        raise SitePackageCryptoError("数据包密钥派生参数不受支持")
    return (
        _decode(metadata.get("salt_b64"), expected=SALT_BYTES),
        _decode(metadata.get("nonce_b64"), expected=NONCE_BYTES),
        n,
        r,
        p,
    )


def _validate_password(password: str) -> None:
    if len(str(password or "")) < 8:
        raise SitePackageCryptoError("迁移密码至少需要 8 个字符")


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: object, *, expected: int) -> bytes:
    try:
        decoded = base64.b64decode(str(value or ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise SitePackageCryptoError("数据包加密参数无效") from exc
    if len(decoded) != expected:
        raise SitePackageCryptoError("数据包加密参数无效")
    return decoded


__all__ = [
    "SitePackageCryptoError",
    "decrypt_stream",
    "encrypt_file",
    "new_encryption_metadata",
]
