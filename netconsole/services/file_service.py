from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Callable, Protocol


class RemoteFileClient(Protocol):
    def stat(self, remote_path: str): ...

    def download(self, remote_path: str, local_path: Path, *args, **kwargs) -> Path: ...


@dataclass(frozen=True)
class SafeDownloadResult:
    local_path: Path
    remote_size: int
    local_size: int
    sha256: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_download(
    client: RemoteFileClient,
    remote_path: str,
    local_path: Path,
    *,
    stable_wait_seconds: float = 2.0,
    retries: int = 3,
    sleeper: Callable[[float], None] = sleep,
) -> SafeDownloadResult:
    last_error: Exception | None = None
    for _attempt in range(max(1, int(retries))):
        try:
            size1 = int(client.stat(remote_path).st_size)
            sleeper(stable_wait_seconds)
            size2 = int(client.stat(remote_path).st_size)
            if size1 != size2:
                raise RuntimeError(f"remote file is still changing: {size1} != {size2}")
            downloaded = Path(client.download(remote_path, Path(local_path)))
            local_size = downloaded.stat().st_size
            if local_size != size2:
                raise RuntimeError(f"download size mismatch: local={local_size}, remote={size2}")
            return SafeDownloadResult(downloaded, size2, local_size, file_sha256(downloaded))
        except Exception as exc:
            last_error = exc
            sleeper(min(1.0, stable_wait_seconds))
    raise RuntimeError(f"safe download failed for {remote_path}: {last_error}") from last_error
