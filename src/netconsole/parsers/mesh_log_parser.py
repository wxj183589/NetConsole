from __future__ import annotations

import gzip
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

from netconsole.models.mesh_log_models import (
    LINK_STATE_ACTIVE,
    LINK_STATE_STANDBY,
    PAIRED_METRICS,
    ImportedLogFile,
    MeshLogRecord,
    ParseIssue,
)
from netconsole.utils.text_encoding import decode_bytes_with_fallback


TIMESTAMP_RE = re.compile(
    r"^\[(?P<radio>\d+)\]\s+"
    r"(?P<date>\d{4}[/-]\d{2}[/-]\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)"
    r"(?:\s+\((?P<tag>\d+)\))?(?:\s+.*)?$"
)
LOG_TIMESTAMP_RE = re.compile(
    r"(?:^|[^\d])(?:\[(?:\d+)\]\s*)?"
    r"(?P<date>\d{4}[/-]\d{2}[/-]\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)"
)
SOURCE_RE = re.compile(r"^(?P<source>.+?)-\d{4}_\d{2}_\d{2}(?:_\d+)?-?meshlog\.log(?:\.gz)?$", re.IGNORECASE)
VALID_STATES = {"Active": LINK_STATE_ACTIVE, "Standy": LINK_STATE_STANDBY, "Standby": LINK_STATE_STANDBY}
MIN_RECORD_FIELDS = 23
TIMESTAMP_SCAN_MAX_BYTES = 4 * 1024 * 1024
TIMESTAMP_SCAN_MAX_LINES = 50_000


@dataclass(frozen=True)
class MeshLogContentMetadata:
    raw_sha256: str
    content_sha256: str
    size_bytes: int
    expanded_size_bytes: int
    first_log_timestamp: datetime | None
    last_log_timestamp: datetime | None

    @property
    def log_date(self):
        return self.first_log_timestamp.date() if self.first_log_timestamp else None


class MeshLogSizeLimitError(ValueError):
    pass


class MeshLogParser:
    def is_supported_file(self, path: Path) -> bool:
        current_radio: int | None = None
        current_sample_time: datetime | None = None
        current_tag: str | None = None
        try:
            for line_number, raw_offset_start, raw_offset_end, line in _iter_decoded_lines(path):
                raw_line = line.rstrip("\r\n")
                stripped = raw_line.strip()
                ts_match = TIMESTAMP_RE.match(stripped)
                if ts_match:
                    try:
                        current_radio = int(ts_match.group("radio"))
                        current_sample_time = _parse_sample_time(ts_match.group("date"), ts_match.group("time"))
                        current_tag = ts_match.group("tag")
                    except ValueError:
                        current_sample_time = None
                    continue
                if not stripped.startswith("["):
                    continue
                parsed, _issues = self._parse_record_line(
                    stripped,
                    raw_line,
                    path,
                    line_number,
                    raw_offset_start,
                    raw_offset_end,
                    path.stem,
                    current_radio,
                    current_sample_time,
                    current_tag,
                )
                if parsed is not None:
                    return True
        except (OSError, UnicodeDecodeError, gzip.BadGzipFile):
            return False
        return False

    def parse_file(
        self,
        path: Path,
        source_label: str | None = None,
        precomputed_hash: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[int, int, int], None] | None = None,
    ) -> tuple[ImportedLogFile, list[MeshLogRecord], list[ParseIssue]]:
        info = make_imported_file(path, source_label, precomputed_hash=precomputed_hash)
        records: list[MeshLogRecord] = []
        issues: list[ParseIssue] = []
        current_radio: int | None = None
        current_sample_time: datetime | None = None
        current_tag: str | None = None
        skipped = 0
        read_lines = 0
        record_seq = 0
        try:
            for line_number, raw_offset_start, raw_offset_end, line in _iter_decoded_lines(path):
                if should_cancel and should_cancel():
                    info.status = "cancelled"
                    break
                read_lines += 1
                raw_line = line.rstrip("\r\n")
                stripped = raw_line.strip()
                if not stripped:
                    continue
                ts_match = TIMESTAMP_RE.match(stripped)
                if ts_match:
                    try:
                        current_radio = int(ts_match.group("radio"))
                        current_sample_time = _parse_sample_time(ts_match.group("date"), ts_match.group("time"))
                        current_tag = ts_match.group("tag")
                    except ValueError:
                        issues.append(ParseIssue(str(path), line_number, "时间格式异常", "采样时间格式异常", raw_line))
                        current_sample_time = None
                    continue
                if not stripped.startswith("["):
                    continue
                parsed, row_issues = self._parse_record_line(
                    stripped,
                    raw_line,
                    path,
                    line_number,
                    raw_offset_start,
                    raw_offset_end,
                    info.source_label,
                    current_radio,
                    current_sample_time,
                    current_tag,
                )
                issues.extend(row_issues)
                if parsed is None:
                    skipped += 1
                    continue
                record_seq += 1
                parsed.record_seq = record_seq
                records.append(parsed)
                if progress and read_lines % 200 == 0:
                    progress(read_lines, len(records), skipped)
            if info.status not in {"cancelled"}:
                info.status = "done"
        except gzip.BadGzipFile as exc:
            info.status = "failed"
            info.error_message = str(exc)
            issues.append(ParseIssue(str(path), 0, "GZIP读取失败", str(exc), ""))
        except UnicodeDecodeError as exc:
            info.status = "failed"
            info.error_message = str(exc)
            issues.append(ParseIssue(str(path), 0, "文件编码异常", str(exc), ""))
        except OSError as exc:
            info.status = "failed"
            info.error_message = str(exc)
            issues.append(ParseIssue(str(path), 0, "文件读取失败", str(exc), ""))
        info.record_count = len(records)
        info.skipped_count = skipped
        info.error_count = len(issues)
        info.lines_read = read_lines
        times = [record.sample_time for record in records]
        if times:
            info.start_time = min(times)
            info.end_time = max(times)
        return info, records, issues

    def _parse_record_line(
        self,
        stripped: str,
        raw_line: str,
        path: Path,
        line_number: int,
        raw_offset_start: int,
        raw_offset_end: int,
        source_label: str,
        current_radio: int | None,
        current_sample_time: datetime | None,
        current_tag: str | None,
    ) -> tuple[MeshLogRecord | None, list[ParseIssue]]:
        issues: list[ParseIssue] = []
        if current_sample_time is None or current_radio is None:
            issues.append(ParseIssue(str(path), line_number, "缺少采样时间", "记录行前没有有效采样时间", raw_line))
            return None, issues
        parts = re.split(r"\s+", stripped)
        if len(parts) < MIN_RECORD_FIELDS:
            issues.append(ParseIssue(str(path), line_number, "字段数量不足", f"字段数量不足：{len(parts)}", raw_line))
            return None, issues
        line_radio = _strip_radio(parts[0])
        if line_radio is None:
            issues.append(ParseIssue(str(path), line_number, "字段数量不足", "记录行缺少Radio字段", raw_line))
            return None, issues
        state_raw = parts[1]
        state = parse_link_state(state_raw)
        if state is None:
            issues.append(ParseIssue(str(path), line_number, "无法识别链路状态", state_raw, raw_line))
            return None, issues
        peer_mac_raw = parts[2]
        peer_mac = normalize_mac(peer_mac_raw)
        if peer_mac is None:
            issues.append(ParseIssue(str(path), line_number, "MAC格式异常", peer_mac_raw, raw_line))
        establish_time = _parse_datetime(parts[3], parts[4])
        if establish_time is None:
            issues.append(ParseIssue(str(path), line_number, "时间格式异常", f"{parts[3]} {parts[4]}", raw_line))
        duration_text = " ".join(parts[5:9])
        duration_seconds = parse_duration_seconds(parts[5:9])
        link_count = _parse_int(parts[9])
        metric_tokens = parts[10:24]
        metrics: dict[str, int | None] = {}
        for index, (metric_name, local_key, peer_key) in enumerate(PAIRED_METRICS):
            token = metric_tokens[index] if index < len(metric_tokens) else ""
            local_value, peer_value, ok = parse_pair_token(token, percent=metric_name in {"cpu", "mem"})
            metrics[local_key] = local_value
            metrics[peer_key] = peer_value
            if not ok:
                issues.append(ParseIssue(str(path), line_number, "指标格式异常", f"{metric_name}: {token}", raw_line))
        local_noise_dbm, peer_noise_dbm, local_signal_dbm, peer_signal_dbm = calculate_signal(metrics)
        record = MeshLogRecord(
            source_label=source_label,
            source_file=str(path),
            source_line_number=line_number,
            raw_line=raw_line,
            radio=line_radio,
            sample_time=current_sample_time,
            timestamp_tag=current_tag,
            link_state_raw=state_raw,
            link_state=state,
            peer_mac_raw=peer_mac_raw,
            peer_mac_normalized=peer_mac,
            establish_time=establish_time,
            duration_text=duration_text,
            duration_seconds=duration_seconds,
            link_count=link_count,
            metrics=metrics,
            local_noise_dbm=local_noise_dbm,
            peer_noise_dbm=peer_noise_dbm,
            local_signal_dbm=local_signal_dbm,
            peer_signal_dbm=peer_signal_dbm,
        )
        record.raw_line_start = line_number
        record.raw_line_end = line_number
        record.raw_offset_start = raw_offset_start
        record.raw_offset_end = raw_offset_end
        record.sample_time_epoch_ms = int(current_sample_time.timestamp() * 1000)
        if establish_time is not None:
            expected = int((current_sample_time - establish_time).total_seconds())
            record.expected_duration_seconds = expected if expected >= 0 else None
        if record.duration_seconds is not None and record.expected_duration_seconds is not None:
            record.duration_deviation_seconds = record.duration_seconds - record.expected_duration_seconds
        record.duplicate_hash = make_duplicate_hash(record)
        return record, issues


def make_imported_file(path: Path, source_label: str | None = None, precomputed_hash: str | None = None) -> ImportedLogFile:
    stat = path.stat()
    return ImportedLogFile(
        path=path,
        source_label=source_label or infer_source_label(path),
        size=stat.st_size,
        modified_time=datetime.fromtimestamp(stat.st_mtime),
        file_hash=precomputed_hash or sha256_file(path),
    )


def infer_source_label(path: Path) -> str:
    match = SOURCE_RE.match(path.name)
    return match.group("source") if match else path.stem


def normalize_mac(value: str) -> str | None:
    compact = re.sub(r"[-:\s.]", "", value).lower()
    if re.fullmatch(r"[0-9a-f]{12}", compact):
        return compact
    return None


def normalize_peer_mac(value: str) -> str | None:
    return normalize_mac(value)


def parse_link_state(raw: str) -> str | None:
    text = str(raw or "").strip().casefold()
    if "active" in text:
        return LINK_STATE_ACTIVE
    if "standby" in text or "standy" in text:
        return LINK_STATE_STANDBY
    return VALID_STATES.get(str(raw or "").strip())


def parse_pair_token(token: str, percent: bool = False) -> tuple[int | None, int | None, bool]:
    if "/" not in token:
        return None, None, False
    left, right = token.split("/", 1)
    local_value = _parse_int(left.rstrip("%") if percent else left)
    peer_value = _parse_int(right.rstrip("%") if percent else right)
    return local_value, peer_value, local_value is not None and peer_value is not None


def parse_pair_metric(token: str, percent: bool = False) -> tuple[int | None, int | None, bool]:
    return parse_pair_token(token, percent=percent)


def calculate_signal(metrics: dict[str, int | None]) -> tuple[int | None, int | None, int | None, int | None]:
    local_rssi = metrics.get("local_rssi_db")
    peer_rssi = metrics.get("peer_rssi_db")
    local_noise = metrics.get("local_noise_raw")
    peer_noise = metrics.get("peer_noise_raw")
    local_noise_dbm = -abs(local_noise) if isinstance(local_noise, int) and local_noise > 0 else None
    peer_noise_dbm = -abs(peer_noise) if isinstance(peer_noise, int) and peer_noise > 0 else None
    local_signal = local_rssi + local_noise_dbm if isinstance(local_rssi, int) and local_rssi > 0 and local_noise_dbm is not None else None
    peer_signal = peer_rssi + peer_noise_dbm if isinstance(peer_rssi, int) and peer_rssi > 0 and peer_noise_dbm is not None else None
    return local_noise_dbm, peer_noise_dbm, local_signal, peer_signal


def compute_signal_dbm(metrics: dict[str, int | None]) -> tuple[int | None, int | None, int | None, int | None]:
    return calculate_signal(metrics)


def parse_mesh_link_table(
    text: str,
    *,
    source_label: str = "online",
    source_file: str = "",
    sample_time: datetime | None = None,
    radio: int | None = None,
) -> tuple[list[MeshLogRecord], list[ParseIssue]]:
    parser = MeshLogParser()
    records: list[MeshLogRecord] = []
    issues: list[ParseIssue] = []
    current_radio = radio
    current_sample_time = sample_time
    current_tag: str | None = None
    path = Path(source_file or "<online>")
    record_seq = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        raw_line = line.rstrip("\r\n")
        stripped = raw_line.strip()
        if not stripped:
            continue
        ts_match = TIMESTAMP_RE.match(stripped)
        if ts_match:
            try:
                current_radio = int(ts_match.group("radio"))
                current_sample_time = _parse_sample_time(ts_match.group("date"), ts_match.group("time"))
                current_tag = ts_match.group("tag")
            except ValueError:
                issues.append(ParseIssue(str(path), line_number, "鏃堕棿鏍煎紡寮傚父", "閲囨牱鏃堕棿鏍煎紡寮傚父", raw_line))
            continue
        if not stripped.startswith("["):
            continue
        parsed, row_issues = parser._parse_record_line(
            stripped,
            raw_line,
            path,
            line_number,
            0,
            0,
            source_label,
            current_radio,
            current_sample_time,
            current_tag,
        )
        issues.extend(row_issues)
        if parsed is not None:
            record_seq += 1
            parsed.record_seq = record_seq
            records.append(parsed)
    return records, issues


def parse_mesh_log_file(
    path: Path,
    source_label: str | None = None,
    precomputed_hash: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[int, int, int], None] | None = None,
) -> tuple[ImportedLogFile, list[MeshLogRecord], list[ParseIssue]]:
    return MeshLogParser().parse_file(path, source_label, precomputed_hash, should_cancel, progress)


def parse_duration_seconds(parts: list[str]) -> int | None:
    if len(parts) != 4:
        return None
    match = re.fullmatch(r"(?P<d>\d+)d", parts[0]), re.fullmatch(r"(?P<h>\d+)h", parts[1]), re.fullmatch(r"(?P<m>\d+)m", parts[2]), re.fullmatch(r"(?P<s>\d+)s", parts[3])
    if not all(match):
        return None
    return int(match[0].group("d")) * 86400 + int(match[1].group("h")) * 3600 + int(match[2].group("m")) * 60 + int(match[3].group("s"))


def make_duplicate_hash(record: MeshLogRecord) -> str:
    metric_values = [f"{key}={record.metrics.get(key)}" for _, local_key, peer_key in PAIRED_METRICS for key in (local_key, peer_key)]
    base = "|".join(
        [
            record.source_label,
            record.sample_time.isoformat(timespec="milliseconds"),
            record.timestamp_tag or "",
            str(record.radio),
            record.link_state,
            record.peer_mac_normalized or "",
            record.establish_time.isoformat(timespec="seconds") if record.establish_time else "",
            *metric_values,
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_mesh_log_path(path: Path, *, max_expanded_size: int | None = None) -> MeshLogContentMetadata:
    """流式计算来源指纹和首尾日志时间，不把整个日志读入内存。"""

    raw_sha = sha256_file(path)
    try:
        with path.open("rb") as raw:
            stream: BinaryIO = gzip.GzipFile(fileobj=raw, mode="rb") if path.suffix.casefold() == ".gz" else raw
            try:
                return _inspect_mesh_log_stream(
                    stream,
                    raw_sha256=raw_sha,
                    size_bytes=path.stat().st_size,
                    max_expanded_size=max_expanded_size,
                )
            finally:
                if stream is not raw:
                    stream.close()
    except gzip.BadGzipFile:
        raise


def inspect_mesh_log_bytes(content: bytes, name: str, *, max_expanded_size: int | None = None) -> MeshLogContentMetadata:
    raw_sha = hashlib.sha256(content).hexdigest()
    raw = io.BytesIO(content)
    stream: BinaryIO = gzip.GzipFile(fileobj=raw, mode="rb") if name.casefold().endswith(".gz") else raw
    try:
        return _inspect_mesh_log_stream(
            stream,
            raw_sha256=raw_sha,
            size_bytes=len(content),
            max_expanded_size=max_expanded_size,
        )
    finally:
        if stream is not raw:
            stream.close()


def inspect_mesh_log_stream(
    stream: BinaryIO,
    *,
    raw_sha256: str,
    size_bytes: int,
    max_expanded_size: int | None = None,
) -> MeshLogContentMetadata:
    return _inspect_mesh_log_stream(
        stream,
        raw_sha256=raw_sha256,
        size_bytes=size_bytes,
        max_expanded_size=max_expanded_size,
    )


def _inspect_mesh_log_stream(
    stream: BinaryIO,
    *,
    raw_sha256: str,
    size_bytes: int,
    max_expanded_size: int | None,
) -> MeshLogContentMetadata:
    content_digest = hashlib.sha256()
    expanded_size = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    scan_bytes = 0
    scan_lines = 0
    first_line = True
    for raw_line in stream:
        payload = bytes(raw_line)
        expanded_size += len(payload)
        if max_expanded_size is not None and expanded_size > max_expanded_size:
            raise MeshLogSizeLimitError("日志解压后超过允许大小")
        if first_line:
            first_line = False
            if payload.startswith(b"\xef\xbb\xbf"):
                payload = payload[3:]
        content_digest.update(payload)
        if scan_lines < TIMESTAMP_SCAN_MAX_LINES and scan_bytes < TIMESTAMP_SCAN_MAX_BYTES:
            scan_lines += 1
            scan_bytes += len(payload)
            timestamp = parse_log_timestamp_line(decode_bytes_with_fallback(payload).text)
            if timestamp is not None:
                if first_timestamp is None:
                    first_timestamp = timestamp
                last_timestamp = timestamp
        elif first_timestamp is not None:
            timestamp = parse_log_timestamp_line(decode_bytes_with_fallback(payload).text)
            if timestamp is not None:
                last_timestamp = timestamp
    return MeshLogContentMetadata(
        raw_sha256=raw_sha256,
        content_sha256=content_digest.hexdigest(),
        size_bytes=size_bytes,
        expanded_size_bytes=expanded_size,
        first_log_timestamp=first_timestamp,
        last_log_timestamp=last_timestamp,
    )


def _iter_decoded_lines(path: Path) -> Iterable[tuple[int, int, int, str]]:
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    offset = 0
    with opener(path, "rb") as raw:
        for line_number, line in enumerate(raw, start=1):
            line_start = offset
            offset += len(line)
            yield line_number, line_start, offset, _decode_line(line)


def _decode_line(line: bytes) -> str:
    return decode_bytes_with_fallback(line).text


def _parse_sample_time(date_text: str, time_text: str) -> datetime:
    return _parse_datetime(date_text, time_text) or datetime.strptime(f"{date_text} {time_text}", "%Y/%m/%d %H:%M:%S")


def _parse_datetime(date_text: str, time_text: str) -> datetime | None:
    text = f"{date_text.replace('-', '/')} {time_text}"
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_log_timestamp_line(line: str) -> datetime | None:
    text = str(line or "").lstrip("\ufeff").strip()
    if re.match(r"^\[\d+\]\s+\S+\s+\S+\s+", text) and not TIMESTAMP_RE.match(text):
        return None
    match = LOG_TIMESTAMP_RE.search(text)
    if not match:
        return None
    return _parse_datetime(match.group("date"), match.group("time"))


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strip_radio(value: str) -> int | None:
    match = re.fullmatch(r"\[(\d+)\]", value)
    return int(match.group(1)) if match else None
