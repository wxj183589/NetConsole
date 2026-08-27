"""Content-addressed compressed storage for immutable task-result bodies."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from typing import Any


TASK_RESULT_BLOB_CODEC_ZLIB = "zlib"


class TaskResultBlobError(sqlite3.DatabaseError):
    """A result blob is missing, corrupt, or does not match its authority hash."""


@dataclass(frozen=True)
class TaskResultBlob:
    content_sha256: str
    codec: str
    compressed_blob: bytes
    uncompressed_bytes: int
    compressed_bytes: int
    created_time: str
    verified_at: str


def ensure_blob(
    conn: sqlite3.Connection,
    *,
    canonical_json: str,
    content_sha256: str,
    created_time: str,
    verified_at: str,
) -> TaskResultBlob:
    """Insert-or-reuse a blob and verify its decoded bytes before returning it."""

    encoded = str(canonical_json).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != str(content_sha256):
        raise TaskResultBlobError("task result blob content hash mismatch before write")
    compressed = zlib.compress(encoded, level=6)
    conn.execute(
        """
        INSERT OR IGNORE INTO task_result_blobs(
            content_sha256, codec, compressed_blob, uncompressed_bytes,
            compressed_bytes, created_time, verified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            digest,
            TASK_RESULT_BLOB_CODEC_ZLIB,
            compressed,
            len(encoded),
            len(compressed),
            str(created_time),
            str(verified_at),
        ),
    )
    row = conn.execute(
        "SELECT content_sha256, codec, compressed_blob, uncompressed_bytes, "
        "compressed_bytes, created_time, verified_at "
        "FROM task_result_blobs WHERE content_sha256=?",
        (digest,),
    ).fetchone()
    if row is None:
        raise TaskResultBlobError("task result blob disappeared after write")
    blob = _blob_from_row(row)
    decoded = decode_blob(blob, expected_sha256=digest, expected_bytes=len(encoded))
    if decoded != canonical_json:
        raise TaskResultBlobError("task result blob decoded content mismatch")
    return blob


def read_blob(
    conn: sqlite3.Connection,
    *,
    content_sha256: str,
    expected_bytes: int | None = None,
) -> str:
    row = conn.execute(
        "SELECT content_sha256, codec, compressed_blob, uncompressed_bytes, "
        "compressed_bytes, created_time, verified_at "
        "FROM task_result_blobs WHERE content_sha256=?",
        (str(content_sha256),),
    ).fetchone()
    if row is None:
        raise TaskResultBlobError("task result blob is missing")
    blob = _blob_from_row(row)
    return decode_blob(
        blob,
        expected_sha256=str(content_sha256),
        expected_bytes=expected_bytes,
    )


def verify_task_result_authority(
    conn: sqlite3.Connection,
    row: dict[str, Any],
) -> dict[str, Any]:
    """Verify a task-result row, resolving a ready Blob before legacy JSON.

    This helper is for compatibility readers outside ``TaskRepository``.  A
    ready Blob is authoritative; a missing or corrupt Blob is never replaced
    by ``canonical_json``.
    """

    from netconsole.repositories.history_store import verify_task_result_row

    materialized = dict(row)
    try:
        ready = int(materialized.get("blob_ready") or 0)
    except (TypeError, ValueError) as exc:
        raise TaskResultBlobError("task result blob readiness is invalid") from exc
    if ready:
        materialized["canonical_json"] = read_blob(
            conn,
            content_sha256=str(
                materialized.get("content_sha256")
                or materialized.get("sha256")
                or ""
            ),
            expected_bytes=int(materialized.get("byte_size") or -1),
        )
    elif str(materialized.get("content_sha256") or ""):
        raise TaskResultBlobError("task result blob is not ready")
    return verify_task_result_row(materialized)


def decode_blob(
    blob: TaskResultBlob,
    *,
    expected_sha256: str,
    expected_bytes: int | None = None,
) -> str:
    if blob.codec != TASK_RESULT_BLOB_CODEC_ZLIB:
        raise TaskResultBlobError("task result blob codec is invalid")
    if blob.compressed_bytes != len(blob.compressed_blob):
        raise TaskResultBlobError("task result blob compressed size mismatch")
    if expected_bytes is not None and blob.uncompressed_bytes != int(expected_bytes):
        raise TaskResultBlobError("task result blob uncompressed size mismatch")
    try:
        decoded = zlib.decompress(blob.compressed_blob)
    except zlib.error as exc:
        raise TaskResultBlobError("task result blob compressed bytes are corrupt") from exc
    if len(decoded) != blob.uncompressed_bytes:
        raise TaskResultBlobError("task result blob decoded size mismatch")
    digest = hashlib.sha256(decoded).hexdigest()
    if digest != str(expected_sha256):
        raise TaskResultBlobError("task result blob hash mismatch")
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TaskResultBlobError("task result blob is not valid UTF-8") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskResultBlobError("task result blob JSON is invalid") from exc
    if not isinstance(value, dict):
        raise TaskResultBlobError("task result blob JSON must be an object")
    return text


def _blob_from_row(row: Any) -> TaskResultBlob:
    try:
        compressed = bytes(row["compressed_blob"])
        return TaskResultBlob(
            content_sha256=str(row["content_sha256"] or ""),
            codec=str(row["codec"] or ""),
            compressed_blob=compressed,
            uncompressed_bytes=int(row["uncompressed_bytes"]),
            compressed_bytes=int(row["compressed_bytes"]),
            created_time=str(row["created_time"] or ""),
            verified_at=str(row["verified_at"] or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TaskResultBlobError("task result blob row is incomplete") from exc


__all__ = [
    "TASK_RESULT_BLOB_CODEC_ZLIB",
    "TaskResultBlob",
    "TaskResultBlobError",
    "decode_blob",
    "ensure_blob",
    "read_blob",
    "verify_task_result_authority",
]
