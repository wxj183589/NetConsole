"""Bounded UTF-8 editing over an authenticated SFTP session."""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from uuid import uuid4

from netconsole.services.file_transfer_service import FileTransferService, TransferVerificationFailed


MAX_TEXT_BYTES = 256 * 1024
UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class TextRevision:
    text: str
    digest: str
    mode: int
    uid: int
    gid: int
    newline: str
    bom: bool


def read_text_revision(sftp, path: str) -> TextRevision:
    attrs = sftp.lstat(path)
    if not stat.S_ISREG(attrs.st_mode):
        raise ValueError("文本编辑仅支持普通文件")
    if int(attrs.st_size) > MAX_TEXT_BYTES:
        raise ValueError("文本编辑最多支持 256 KiB")
    with sftp.open(path, "rb") as stream:
        data = stream.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError("文本编辑最多支持 256 KiB")
    text = _decode(data)
    newline = "\r\n" if "\r\n" in text else "\n"
    normalized = text.replace("\r\n", "\n")
    if "\r" in normalized or (newline == "\r\n" and text.count("\n") != text.count("\r\n")):
        raise ValueError("文本编辑需要一致的 LF 或 CRLF 换行格式")
    return TextRevision(normalized, hashlib.sha256(data).hexdigest(), stat.S_IMODE(attrs.st_mode),
                        int(attrs.st_uid), int(attrs.st_gid), newline, data.startswith(UTF8_BOM))


def save_text_revision(
    sftp, path: str, expected: str, text: str, original: TextRevision | None = None,
) -> TextRevision:
    current = read_text_revision(sftp, path)
    if current.digest != expected or (original is not None and current != original):
        raise RuntimeError("远程文件在打开后已变化，请重新读取")
    if current.text == text:
        return current
    source = original or current
    if "\r" in text:
        raise ValueError("文本内容包含无效换行")
    try:
        body = (UTF8_BOM if source.bom else b"") + text.replace("\n", source.newline).encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("文本内容必须使用 UTF-8") from exc
    if len(body) > MAX_TEXT_BYTES:
        raise ValueError("文本编辑最多支持 256 KiB")
    _decode(body)
    digest = hashlib.sha256(body).hexdigest()
    temporary = f"{path}.netconsole-edit-{uuid4().hex}.part"
    created = False
    try:
        with sftp.open(temporary, "xb") as stream:
            created = True
            stream.write(body)
        sftp.chmod(temporary, source.mode)
        attrs = sftp.lstat(temporary)
        if (stat.S_IMODE(attrs.st_mode), int(attrs.st_uid), int(attrs.st_gid)) != (source.mode, source.uid, source.gid):
            raise ValueError("目标设备无法保留原文件权限或属主")
        FileTransferService._verify_remote_hash(sftp, temporary, digest)
        if read_text_revision(sftp, path) != source:
            raise RuntimeError("远程文件在打开后已变化，请重新读取")
        try:
            sftp.posix_rename(temporary, path)
        except OSError as exc:
            raise RuntimeError("设备未能执行原子替换，远程文本保存失败") from exc
        created = False
    finally:
        if created:
            try:
                sftp.remove(temporary)
            except OSError:
                pass
    published = read_text_revision(sftp, path)
    if published.digest != digest:
        raise TransferVerificationFailed("远程编辑后的 SHA-256 校验失败")
    return published


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("文本编辑仅支持 UTF-8") from exc
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise ValueError("文本包含二进制控制字符")
    return text
