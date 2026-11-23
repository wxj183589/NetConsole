"""Verified sequential download checkpoints; no shell or SFTP extensions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from netconsole.services.sftp_tree import check_cancel


def _identity(attrs) -> dict:
    if getattr(attrs, "st_size", None) is None:
        raise ValueError("服务器未提供文件大小，不能验证续传")
    return {"size": int(attrs.st_size), "mtime": getattr(attrs, "st_mtime", None)}


def download_checkpoint(service, source: str, destination: Path, checkpoint: Path, cancel, progress) -> Path:
    sftp = service._require_sftp()
    identity = _identity(sftp.stat(source))
    journal = checkpoint.with_suffix(".identity.json")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint.exists():
        if not journal.is_file() or json.loads(journal.read_text(encoding="utf-8")) != identity:
            raise ValueError("源文件身份变化，断点已保留；请取消旧任务并新建下载")
    else:
        temporary = journal.with_suffix(".part")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(identity, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(journal)
    offset = checkpoint.stat().st_size if checkpoint.exists() else 0
    if offset > identity["size"]:
        raise ValueError("断点长度超过源文件，拒绝续传")
    with sftp.open(source, "rb") as remote:
        if offset:
            with checkpoint.open("rb") as local:
                remaining = offset
                while remaining:
                    check_cancel(cancel)
                    chunk = local.read(min(1024 * 1024, remaining))
                    if not chunk or remote.read(len(chunk)) != chunk:
                        raise ValueError("源文件前缀与断点不一致，拒绝续传")
                    remaining -= len(chunk)
        remote.seek(offset)
        with checkpoint.open("ab") as local:
            transferred = offset
            while transferred < identity["size"]:
                check_cancel(cancel)
                chunk = remote.read(min(1024 * 1024, identity["size"] - transferred))
                if not chunk:
                    raise IOError("远程文件提前结束")
                local.write(chunk)
                local.flush()
                transferred += len(chunk)
                progress(transferred, identity["size"])
            os.fsync(local.fileno())
    check_cancel(cancel)
    if _identity(sftp.stat(source)) != identity:
        raise ValueError("传输期间源文件发生变化")
    remote_hash = hashlib.sha256()
    local_hash = hashlib.sha256()
    with sftp.open(source, "rb") as remote, checkpoint.open("rb") as local:
        while True:
            check_cancel(cancel)
            a, b = remote.read(1024 * 1024), local.read(1024 * 1024)
            if len(a) != len(b):
                raise IOError("完整性校验长度不一致")
            remote_hash.update(a)
            local_hash.update(b)
            if not a:
                break
    if remote_hash.digest() != local_hash.digest():
        raise IOError("完整文件 SHA-256 不一致")
    if _identity(sftp.stat(source)) != identity:
        raise ValueError("校验期间源文件发生变化")
    destination.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.replace(destination)
    journal.unlink(missing_ok=True)
    return destination
