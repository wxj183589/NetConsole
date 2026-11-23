"""Bounded recursive SFTP operations, independent of any console UI or shell."""
from __future__ import annotations

import stat
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

from netconsole.services.file_transfer_service import TransferCancelled, join_remote_path


def check_cancel(cancel) -> None:
    if cancel.is_set():
        raise TransferCancelled("传输已取消")


def inventory(service, source: str, cancel, *, limit: int = 10000, byte_limit: int = 64 * 1024**3):
    """No symlink traversal; bound both entries and depth before transferring."""
    result = []
    pending = [(source, "", 0)]
    total = 0
    while pending:
        check_cancel(cancel)
        path, relative, depth = pending.pop()
        if depth > 64 or len(result) >= limit:
            raise ValueError("目录超过 64 层或 10000 项限制")
        attrs = service.lstat(path)
        mode = int(attrs.st_mode)
        if stat.S_ISLNK(mode):
            raise ValueError("递归传输不跟随符号链接")
        directory = stat.S_ISDIR(mode)
        size = int(attrs.st_size or 0)
        if not directory:
            total += size
            if total > byte_limit:
                raise ValueError("目录总大小超过 64 GiB 限制")
        result.append((path, relative, directory, size))
        if directory:
            for entry in service.list_directory(path):
                name = entry.name
                if name in {".", ".."} or "/" in name or "\\" in name:
                    raise ValueError("远程目录包含无效文件名")
                if entry.permissions.startswith("l"):
                    raise ValueError("递归传输不跟随符号链接")
                pending.append((entry.remote_path, f"{relative}/{name}".lstrip("/"), depth + 1))
                if len(pending) + len(result) > limit:
                    raise ValueError("目录超过 10000 项限制")
    return result


def download_directory(service, source, destination: Path, cancel, progress, *, work_root: Path | None = None, manifest_progress=None) -> Path:
    from netconsole.services.sftp_resume import download_checkpoint

    entries = inventory(service, source, cancel)
    total = sum(size for _, _, directory, size in entries if not directory)
    transferred = 0
    # Verified files remain for manifest recovery; disk usage is the archive plus
    # the bounded source tree. Memory stays bounded by transfer/compression chunks.
    part = destination.with_suffix(destination.suffix + ".part")
    work = work_root or destination.with_suffix(".entries")
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = work / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    completed_files = 0
    file_count = sum(not directory for _, _, directory, _ in entries)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ZipFile(part, "w", ZIP_DEFLATED, allowZip64=True) as archive:
            for remote, relative, directory, size in entries:
                check_cancel(cancel)
                member = PurePosixPath(source.rstrip("/")).name or "download"
                if relative:
                    member += "/" + relative
                if directory:
                    archive.writestr(member + "/", b"")
                else:
                    key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
                    scratch = work / f"{key}.data"
                    attrs = service.stat(remote)
                    identity = {"size": size, "mtime": getattr(attrs, "st_mtime", None)}
                    previous = manifest.get(relative, {})
                    valid = previous.get("identity") == identity and scratch.is_file()
                    if valid:
                        with scratch.open("rb") as stream:
                            valid = hashlib.file_digest(stream, "sha256").hexdigest() == previous.get("sha256")
                    # Confirm retained files against the server too, not just journal metadata.
                    if valid and hasattr(service, "_require_sftp"):
                        remote_hash = hashlib.sha256()
                        with service._require_sftp().open(remote, "rb") as stream:
                            while chunk := stream.read(1024 * 1024):
                                check_cancel(cancel)
                                remote_hash.update(chunk)
                        valid = remote_hash.hexdigest() == previous.get("sha256")
                    if not valid:
                        if hasattr(service, "_require_sftp"):
                            download_checkpoint(service, remote, scratch, work / f"{key}.part", cancel,
                                                lambda done, _total: progress(transferred + done, total))
                        else:
                            service.download(remote, scratch, cancel_token=cancel,
                                             progress_callback=lambda done, _total: progress(transferred + done, total))
                        with scratch.open("rb") as stream:
                            sha = hashlib.file_digest(stream, "sha256").hexdigest()
                        manifest[relative] = {"identity": identity, "sha256": sha, "status": "COMPLETED"}
                        temporary = manifest_path.with_suffix(".part")
                        temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                        temporary.replace(manifest_path)
                    archive.write(scratch, member)
                    transferred += size
                    completed_files += 1
                    if manifest_progress:
                        manifest_progress(completed_files, file_count)
                    progress(transferred, total)
        check_cancel(cancel)
        part.replace(destination)
        return destination
    finally:
        part.unlink(missing_ok=True)


def copy_directory(service, source, target, cancel, progress) -> None:
    if target == source or target.startswith(source.rstrip("/") + "/"):
        raise ValueError("不能复制目录到自身或其子目录")
    entries = inventory(service, source, cancel)
    total = sum(size for _, _, directory, size in entries if not directory)
    transferred = 0
    for remote, relative, directory, size in entries:
        check_cancel(cancel)
        path = join_remote_path(target, relative) if relative else target
        if directory:
            service.mkdir(path)
        else:
            service.copy(remote, path, cancel_token=cancel,
                         progress_callback=lambda done, _total: progress(transferred + done, total))
            transferred += size
            progress(transferred, total)
