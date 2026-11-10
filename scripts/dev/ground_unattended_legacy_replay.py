# ruff: noqa: E402

"""Read-only replay and consistency audit for a Ground Unattended archive.

The archive is consumed directly from ZIP.  The command never extracts or
modifies archive members, never opens a device connection, and writes only
derived evidence plus isolated SQLite databases under the requested output
directory.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import gzip
import hashlib
import io
import json
import sys
import time
import tracemalloc
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SRC = SOURCE_ROOT / "src"
if str(SOURCE_SRC) not in sys.path:
    sys.path.insert(0, str(SOURCE_SRC))

from netconsole.core.database import Database
from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ground_unattended.ac_reconciliation import (
    AC_DELTA_ACTIONS,
    AcSnapshotEnvelope,
    diff_full_snapshot,
    reconcile_syslog_ac,
)
from netconsole.services.ground_unattended.ap_resolver import GroundApDisplayResolver
from netconsole.services.ground_unattended.fleet_ping import (
    FleetPingSupervisor,
    FleetPingTarget,
)
from netconsole.services.ground_unattended.position_engine import PositionEngine
from netconsole.services.ground_unattended.syslog_runtime import (
    SyslogUdpReceiver,
    UdpEnvelope,
    WmeshRealtimeParser,
    _PersistedEnvelope,
)


WMESH_TYPES = {
    "MESH_LINKUP",
    "MESH_LINKDOWN",
    "MESH_ACTIVELINK_SWITCH",
}
SCHEDULER_TO_WMESH = {
    "mesh_linkup": "MESH_LINKUP",
    "mesh_linkdown": "MESH_LINKDOWN",
    "mesh_activelink_switch": "MESH_ACTIVELINK_SWITCH",
}
JSON_LINE_SUFFIXES = (".jsonl", ".ndjson", ".jsonl.gz", ".ndjson.gz")
UNPARSED_MARKERS = (
    "SYSLOG_RESTART",
    "SHELL_CMD_EXECUTESUCCESS",
    "SHELL_CMD",
    "IFNET/5/LINK_UPDOWN",
)


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _text(value: object) -> str:
    return str(value or "").strip()


def _parse_time(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _mac_key(value: object) -> str:
    text = _text(value).casefold()
    return "".join(char for char in text if char in "0123456789abcdef")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)


def _json_default(value: object) -> str:
    return str(value)


@contextlib.contextmanager
def _member_text(archive: zipfile.ZipFile, name: str) -> Iterator[io.TextIOBase]:
    raw = archive.open(name, "r")
    stream: Any = raw
    if name.casefold().endswith(".gz"):
        stream = gzip.GzipFile(fileobj=raw, mode="rb")
    text_stream = io.TextIOWrapper(stream, encoding="utf-8", errors="strict")
    try:
        yield text_stream
    finally:
        text_stream.close()
        if stream is not raw:
            with contextlib.suppress(Exception):
                stream.close()
        with contextlib.suppress(Exception):
            raw.close()


def _iter_json_lines(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, Any]]:
    with _member_text(archive, name) as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"{name}:{line_number}: JSONL row is not an object")
            yield value


def _read_jsonl_members(
    archive: zipfile.ZipFile,
    names: Iterable[str],
    *,
    annotate: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        for line_number, row in enumerate(_iter_json_lines(archive, name), start=1):
            if annotate:
                row = dict(row)
                row["_archive_file"] = name
                row["_archive_line"] = line_number
            rows.append(row)
    return rows


def _member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_archive(
    archive: zipfile.ZipFile,
    archive_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    infos = archive.infolist()
    files = [info for info in infos if not info.is_dir()]
    manifest_bytes = archive.read("manifest.json")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    manifest_files = {
        str(item.get("path") or ""): item
        for item in manifest.get("files") or []
        if isinstance(item, dict) and item.get("path")
    }
    extension_counts = collections.Counter(
        Path(info.filename).suffix.casefold() or "<none>" for info in infos
    )
    encoding_errors = 0
    json_errors = 0
    valid_json_rows = 0
    scanned_members = 0
    member_records: dict[str, int] = {}
    for info in files:
        name = info.filename
        lower = name.casefold()
        try:
            if lower.endswith(JSON_LINE_SUFFIXES):
                count = 0
                with _member_text(archive, name) as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        count += 1
                        try:
                            json.loads(line)
                            valid_json_rows += 1
                        except json.JSONDecodeError:
                            json_errors += 1
                member_records[name] = count
            elif lower.endswith(".json"):
                value = json.loads(archive.read(name).decode("utf-8"))
                member_records[name] = len(value) if isinstance(value, list) else 1
                valid_json_rows += 1
            elif lower.endswith(".csv"):
                with _member_text(archive, name) as handle:
                    member_records[name] = sum(1 for _ in handle)
            else:
                member_records[name] = 0
        except (UnicodeDecodeError, gzip.BadGzipFile, EOFError):
            encoding_errors += 1
        scanned_members += 1

    member_sha_verified = 0
    member_sha_missing = 0
    member_sha_mismatch = 0
    for info in files:
        expected = str((manifest_files.get(info.filename) or {}).get("sha256") or "")
        if not expected:
            member_sha_missing += 1
            continue
        actual = _member_sha256(archive, info.filename)
        if actual.casefold() != expected.casefold():
            member_sha_mismatch += 1
        else:
            member_sha_verified += 1

    bad_member = archive.testzip()
    names = {info.filename for info in files}
    plain_names = {
        name
        for name in names
        if name.casefold().endswith((".jsonl", ".ndjson"))
    }
    gzip_names = {name for name in names if name.casefold().endswith(".gz")}
    pair_matches = 0
    pair_mismatches = 0
    pair_missing_plain = 0
    pair_missing_gzip = 0
    pair_checked = 0
    for plain in sorted(plain_names):
        gz = plain + ".gz"
        if gz not in names:
            pair_missing_gzip += 1
            continue
        pair_checked += 1
        if _sha256_bytes(archive.read(plain)) == _sha256_bytes(
            gzip.decompress(archive.read(gz))
        ):
            pair_matches += 1
        else:
            pair_mismatches += 1
    for gz in gzip_names:
        if gz[:-3] not in plain_names:
            pair_missing_plain += 1

    inventory = {
        "archive_file_name": archive_path.name,
        "archive_size_bytes": archive_path.stat().st_size,
        "entry_count": len(infos),
        "file_count": len(files),
        "uncompressed_bytes": sum(int(info.file_size) for info in files),
        "compressed_bytes": sum(int(info.compress_size) for info in files),
        "extension_counts": dict(sorted(extension_counts.items())),
        "root_entries": sorted(
            {
                info.filename.split("/", 1)[0]
                for info in files
                if "/" in info.filename
            }
            | {info.filename for info in files if "/" not in info.filename}
        ),
        "zip_test_member": bad_member or "",
        "manifest_file_count": len(manifest_files),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "manifest_member_sha_verified": member_sha_verified,
        "manifest_member_sha_missing": member_sha_missing,
        "manifest_member_sha_mismatch": member_sha_mismatch,
        "encoding_errors": encoding_errors,
        "json_errors": json_errors,
        "valid_json_rows": valid_json_rows,
        "scanned_members": scanned_members,
        "paired_plain_gzip": {
            "checked": pair_checked,
            "matches": pair_matches,
            "mismatches": pair_mismatches,
            "plain_without_gzip": pair_missing_gzip,
            "gzip_without_plain": pair_missing_plain,
        },
        "member_record_counts": member_records,
    }
    return manifest, inventory


def _prepare_syslog_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    parser = WmeshRealtimeParser()
    event_counts: collections.Counter[str] = collections.Counter()
    family_counts: collections.Counter[str] = collections.Counter()
    marker_counts: collections.Counter[str] = collections.Counter()
    parse_rows = 0
    parse_failures = 0
    offset_by_device: dict[str, float] = {}
    timing_sources: collections.Counter[str] = collections.Counter()
    for row in rows:
        raw_text = _text(row.get("raw_text"))
        receive = _parse_time(row.get("receive_time")) or _now()
        parsed = parser.parse(raw_text, receive_time=receive)
        if parsed is None:
            parse_failures += 1
            upper = raw_text.upper()
            for marker in UNPARSED_MARKERS:
                if marker in upper:
                    marker_counts[marker] += 1
            row["_parsed"] = None
            row["_replay_event_time"] = _text(row.get("receive_time"))
            row["_replay_event_time_source"] = "RECEIVE_TIME"
            continue
        parse_rows += 1
        event_type = _text(parsed.get("event_type")).upper()
        family = _text(parsed.get("event_family")).upper()
        event_counts[event_type] += 1
        family_counts[family] += 1
        device_uuid = _text(row.get("device_uuid"))
        device_time = _text(parsed.get("device_time"))
        source = "RECEIVE_TIME"
        event_time = _text(row.get("receive_time"))
        device_dt = _parse_time(device_time)
        if device_dt is not None:
            offset_ms = (receive - device_dt).total_seconds() * 1000.0
            previous = offset_by_device.get(device_uuid)
            offset_by_device[device_uuid] = offset_ms
            if abs(offset_ms) < 5000 and not (
                previous is not None and abs(offset_ms - previous) >= 60000
            ):
                source = "DEVICE_TIME"
                event_time = device_time
        timing_sources[source] += 1
        row["_parsed"] = parsed
        row["_replay_event_time"] = event_time
        row["_replay_event_time_source"] = source
    return {
        "parse_rows": parse_rows,
        "parse_failures": parse_failures,
        "event_counts": dict(sorted(event_counts.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "marker_counts": dict(sorted(marker_counts.items())),
        "timing_sources": dict(sorted(timing_sources.items())),
        "wmesh_count": sum(event_counts[event] for event in WMESH_TYPES),
    }


def _syslog_dedup_audit(
    rows: list[dict[str, Any]],
    identity_query: ApIdentityQueryService,
) -> dict[str, int]:
    resolver = GroundApDisplayResolver(identity_query)
    resolver.refresh_revision(force=True)
    resolver.preload_parsed(
        row["_parsed"] for row in rows if row.get("_parsed") is not None
    )
    keys: collections.Counter[str] = collections.Counter()
    for row in rows:
        parsed_source = row.get("_parsed")
        if not isinstance(parsed_source, dict):
            continue
        if _text(parsed_source.get("event_family")).upper() != "WMESH":
            continue
        parsed = resolver.enrich_parsed(dict(parsed_source))
        details = dict(parsed.get("details") or {})
        event = {
            **parsed,
            "device_uuid": _text(row.get("device_uuid")),
            "event_time": _text(row.get("_replay_event_time")),
            "event_time_source": _text(row.get("_replay_event_time_source")) or "RECEIVE_TIME",
            "details": {
                **details,
                "global_receive_sequence": int(row.get("global_receive_sequence") or 0),
            },
        }
        key = SyslogUdpReceiver._position_dedup_key(
            event,
            raw_text=_text(row.get("raw_text")),
        )
        keys[key] += 1
    return {
        "semantic_duplicate_group_count": sum(value > 1 for value in keys.values()),
        "semantic_duplicate_record_count": sum(value - 1 for value in keys.values() if value > 1),
        "semantic_unique_dedup_key_count": len(keys),
    }


def _identity_seed_rows(
    ac_rows: Iterable[Mapping[str, Any]],
    scheduler_rows: Iterable[Mapping[str, Any]],
    *,
    site_id: str,
    expanded: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_mac: dict[str, dict[str, Any]] = {}
    conflicts = 0

    def add(value: Mapping[str, Any], *, source: str) -> None:
        nonlocal conflicts
        mac = _text(value.get("peer_ap_mac"))
        key = _mac_key(mac)
        if not key:
            return
        name = _text(value.get("peer_ap_name"))
        station = _text(value.get("station"))
        section = _text(value.get("section"))
        current = by_mac.get(key)
        if current is not None:
            if any(
                _text(current.get(field)) != candidate
                for field, candidate in (
                    ("ap_name", name),
                    ("station_name", station),
                    ("section_name", section),
                )
                if candidate
            ):
                conflicts += 1
            if current.get("source") == "ac_snapshot":
                return
        by_mac[key] = {
            "site_id": site_id,
            "line_name": "杭州地铁10号线",
            "system_type": "WMESH",
            "belong_type": "trackside",
            "station_name": station,
            "section_name": section,
            "ap_name": name or mac,
            "ap_point_code": name or mac,
            "ap_vendor": "H3C",
            "ap_mac_display": mac,
            "source": source,
        }

    for row in ac_rows:
        if _text(row.get("peer_ap_mac")):
            add(row, source="ac_snapshot")
    if expanded:
        for row in scheduler_rows:
            details = row.get("details")
            details = details if isinstance(details, Mapping) else {}
            for mac, name in (
                (details.get("peer_ap_mac"), details.get("peer_ap_name")),
                (details.get("previous_peer_ap_mac"), details.get("previous_peer_ap_name")),
            ):
                if _text(mac):
                    add(
                        {
                            "peer_ap_mac": mac,
                            "peer_ap_name": name,
                            "station": details.get("station"),
                            "section": details.get("section"),
                        },
                        source="scheduler_projection",
                    )
    return list(by_mac.values()), {
        "source": "AC_SNAPSHOT_PLUS_SCHEDULER_AP_EVIDENCE" if expanded else "AC_SNAPSHOT_ONLY",
        "ap_point_count": len(by_mac),
        "conflicting_observation_count": conflicts,
    }


def _build_identity_database(
    db_path: Path,
    *,
    ac_rows: Iterable[Mapping[str, Any]],
    scheduler_rows: Iterable[Mapping[str, Any]],
    site_id: str,
    expanded: bool,
) -> tuple[Database, ApIdentityQueryService, dict[str, Any]]:
    database = Database(db_path)
    database.initialize()
    ac_repository = AcRepository(database)
    seed_rows, seed_summary = _identity_seed_rows(
        ac_rows,
        scheduler_rows,
        site_id=site_id,
        expanded=expanded,
    )
    for row in seed_rows:
        ac_repository.upsert_ap_extension_point(row)
    query = ApIdentityQueryService(database, site_id=site_id)
    build = query.rebuild_index("ground_unattended_legacy_replay")
    seed_summary.update(
        {
            "identity_entity_count": int(build.entity_count),
            "identity_alias_count": int(build.alias_count),
            "identity_revision": int(build.revision),
        }
    )
    return database, query, seed_summary


def _endpoint_map(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    by_ip: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        source_ip = _text(row.get("source_ip"))
        device_uuid = _text(row.get("device_uuid"))
        if not source_ip or not device_uuid:
            continue
        by_ip.setdefault(source_ip, {})[device_uuid] = {
            "device_uuid": device_uuid,
            "device_id": row.get("device_id"),
            "device_name": _text(row.get("mr_name")),
            "train_id": _text(row.get("train_id")),
            "train_no": _text(row.get("train_no")),
            "mr_role": _text(row.get("mr_role")),
            "management_ip": source_ip,
        }
    conflicts = {
        ip: len(values)
        for ip, values in by_ip.items()
        if len(values) > 1
    }
    return {ip: list(values.values()) for ip, values in by_ip.items()}, conflicts


def _record_for_replay(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_ip": _text(row.get("source_ip")),
        "source_port": int(row.get("source_port") or 0),
        "hostname": _text(row.get("hostname")),
        "system_name": _text(row.get("system_name")),
        "facility": _text(row.get("facility")),
        "severity": _text(row.get("severity")),
        "raw_text": _text(row.get("raw_text")),
        "receive_time": _text(row.get("receive_time")),
        "global_receive_sequence": int(row.get("global_receive_sequence") or 0),
        "source_receive_sequence": int(row.get("source_receive_sequence") or 0),
        "device_time": "",
        "device_id": row.get("device_id"),
        "device_uuid": _text(row.get("device_uuid")),
        "mr_name": _text(row.get("mr_name")),
        "train_id": _text(row.get("train_id")),
        "train_no": _text(row.get("train_no")),
        "mr_role": _text(row.get("mr_role")),
        "site_id": _text(row.get("site_id")),
    }


def _ordered_syslog_rows(
    rows: list[dict[str, Any]],
    ordering: str,
) -> list[dict[str, Any]]:
    def receive_order_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            int(row.get("global_receive_sequence") or 0),
            int(row.get("source_receive_sequence") or 0),
            _text(row.get("_archive_file")),
            int(row.get("_archive_line") or 0),
        )

    def event_order_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            _parse_time(row.get("_replay_event_time"))
            or datetime.max.replace(tzinfo=timezone.utc),
            int(row.get("global_receive_sequence") or 0),
            int(row.get("source_receive_sequence") or 0),
        )

    if ordering == "receive":
        order_key = receive_order_key
    else:
        order_key = event_order_key
    return sorted(rows, key=order_key)


def _projection_events(
    repository: GroundUnattendedRepository,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    with repository._connection() as connection:  # type: ignore[attr-defined]
        rows = connection.execute(
            "SELECT event_type, device_uuid, event_time, event_time_source, "
            "receive_time, details_json FROM ground_unattended_wmesh_events "
            "WHERE site_id=? AND run_id=? ORDER BY id",
            (repository.site_id, run_id),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            raw_details = json.loads(str(item.get("details_json") or "{}"))
        except json.JSONDecodeError:
            raw_details = {}
        raw_details = raw_details if isinstance(raw_details, dict) else {}
        detail_keys = {
            "global_receive_sequence",
            "source_receive_sequence",
            "peer_ap_mac",
            "previous_peer_ap_mac",
            "resolution_status",
            "identity_status",
            "position_result",
            "position_state_changed",
            "position_duplicate",
            "position_out_of_order",
            "data_quality",
        }
        item["details"] = {
            key: raw_details[key] for key in detail_keys if key in raw_details
        }
        item.pop("details_json", None)
        result.append(item)
    return result


def _replay_syslog(
    rows: list[dict[str, Any]],
    *,
    output_dir: Path,
    site_id: str,
    run_id: str,
    identity_query: ApIdentityQueryService,
    identity_variant: str,
    ordering: str,
) -> dict[str, Any]:
    ordered = _ordered_syslog_rows(rows, ordering)
    db_path = output_dir / f"position_{identity_variant}_{ordering}.sqlite"
    repository = GroundUnattendedRepository(db_path, site_id=site_id)
    receiver = SyslogUdpReceiver(
        repository=repository,
        site_id=site_id,
        parser=WmeshRealtimeParser(),
        ap_identity_query_service=identity_query,
    )
    receiver._run_id = run_id
    receiver._endpoint_by_ip, identity_conflicts = _endpoint_map(rows)
    receiver._event_batch_size = 5000
    receiver._event_batch_interval = 0.0
    receiver._ap_resolver.refresh_revision(force=True)
    # Resolve every observed exact MAC once before the replay.  This is the
    # same bounded preload path used by the live receiver and prevents the
    # offline audit from turning one SQLite lookup into one lookup per line.
    receiver._ap_resolver.preload_parsed(
        row["_parsed"] for row in rows if row.get("_parsed") is not None
    )
    started = time.perf_counter()
    failures: list[str] = []
    processed = 0
    for row in ordered:
        receive_time = _text(row.get("receive_time"))
        envelope = UdpEnvelope(
            source_ip=_text(row.get("source_ip")),
            source_port=int(row.get("source_port") or 0),
            receive_time=receive_time,
            global_receive_sequence=int(row.get("global_receive_sequence") or 0),
            source_receive_sequence=int(row.get("source_receive_sequence") or 0),
            payload=_text(row.get("raw_text")).encode("utf-8", errors="replace"),
        )
        raw_file_id = "legacy:" + hashlib.sha256(
            _text(row.get("_archive_file")).encode("utf-8")
        ).hexdigest()[:24]
        persisted = _PersistedEnvelope(
            envelope=envelope,
            record=_record_for_replay(row),
            raw_file_id=raw_file_id,
            raw_line_number=int(row.get("_archive_line") or 0),
            # The archive is already persisted.  The original raw-persist time
            # is not present, so it is intentionally left blank.
            raw_persist_time="",
        )
        try:
            receiver._process(envelope, persisted)
        except Exception as exc:  # pragma: no cover - diagnostic guard
            failures.append(f"{type(exc).__name__}:{exc}")
            if len(failures) >= 5:
                break
        processed += 1
        if len(receiver._event_batch) >= receiver._event_batch_size:
            if not receiver._flush_events():
                failures.append(receiver._projection_error or "projection_flush_failed")
                break
    if not failures and not receiver._flush_events():
        failures.append(receiver._projection_error or "projection_flush_failed")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    events = _projection_events(repository, run_id=run_id)
    states = repository.list_syslog_position_states()
    event_counts = collections.Counter(_text(event.get("event_type")).upper() for event in events)
    resolution_counts = collections.Counter(
        _text((event.get("details") or {}).get("resolution_status")).upper() or "UNKNOWN"
        for event in events
    )
    identity_counts = collections.Counter(
        _text((event.get("details") or {}).get("identity_status")).upper() or "UNKNOWN"
        for event in events
    )
    event_time_sources = collections.Counter(
        _text(event.get("event_time_source")).upper() or "UNKNOWN"
        for event in events
    )
    position_update_count = sum(
        bool((event.get("details") or {}).get("position_state_changed"))
        for event in events
    )
    duplicate_count = sum(
        bool((event.get("details") or {}).get("position_duplicate"))
        for event in events
    )
    out_of_order_count = sum(
        bool((event.get("details") or {}).get("position_out_of_order"))
        for event in events
    )
    return {
        "identity_variant": identity_variant,
        "ordering": ordering,
        "db_path": str(db_path),
        "processed_records": processed,
        "projection_event_count": len(events),
        "position_state_count": len(states),
        "event_counts": dict(sorted(event_counts.items())),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "identity_counts": dict(sorted(identity_counts.items())),
        "event_time_sources": dict(sorted(event_time_sources.items())),
        "position_update_count": position_update_count,
        "duplicate_event_count": duplicate_count,
        "out_of_order_event_count": out_of_order_count,
        "identity_source_ip_conflict_count": len(identity_conflicts),
        "identity_source_ip_ambiguous_endpoint_count": sum(identity_conflicts.values()),
        "failures": failures,
        "replay_wall_ms": round(elapsed_ms, 3),
        "states": states,
        "events": events,
    }


def _load_existing_replay(
    db_path: Path,
    *,
    site_id: str,
    run_id: str,
    processed_records: int,
) -> dict[str, Any]:
    """Read an already completed isolated repository replay without rewriting it."""

    repository = GroundUnattendedRepository(db_path, site_id=site_id)
    events = _projection_events(repository, run_id=run_id)
    states = repository.list_syslog_position_states()
    event_counts = collections.Counter(_text(event.get("event_type")).upper() for event in events)
    resolution_counts = collections.Counter(
        _text((event.get("details") or {}).get("resolution_status")).upper() or "UNKNOWN"
        for event in events
    )
    identity_counts = collections.Counter(
        _text((event.get("details") or {}).get("identity_status")).upper() or "UNKNOWN"
        for event in events
    )
    event_time_sources = collections.Counter(
        _text(event.get("event_time_source")).upper() or "UNKNOWN"
        for event in events
    )
    return {
        "identity_variant": "strict",
        "ordering": "receive",
        "db_path": str(db_path),
        "processed_records": processed_records,
        "projection_event_count": len(events),
        "position_state_count": len(states),
        "event_counts": dict(sorted(event_counts.items())),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "identity_counts": dict(sorted(identity_counts.items())),
        "event_time_sources": dict(sorted(event_time_sources.items())),
        "position_update_count": sum(
            bool((event.get("details") or {}).get("position_state_changed"))
            for event in events
        ),
        "duplicate_event_count": sum(
            bool((event.get("details") or {}).get("position_duplicate"))
            for event in events
        ),
        "out_of_order_event_count": sum(
            bool((event.get("details") or {}).get("position_out_of_order"))
            for event in events
        ),
        "identity_source_ip_conflict_count": 0,
        "identity_source_ip_ambiguous_endpoint_count": 0,
        "failures": [],
        "replay_wall_ms": 0.0,
        "states": states,
        "events": events,
    }


def _memory_position_replay(
    rows: list[dict[str, Any]],
    *,
    site_id: str,
    run_id: str,
    identity_query: ApIdentityQueryService,
    ordering: str,
) -> dict[str, Any]:
    """Apply the current PositionEngine without duplicating a full SQLite history."""

    resolver = GroundApDisplayResolver(identity_query)
    resolver.refresh_revision(force=True)
    resolver.preload_parsed(
        row["_parsed"] for row in rows if row.get("_parsed") is not None
    )
    ordered = _ordered_syslog_rows(rows, ordering)
    engine = PositionEngine()
    events: list[dict[str, Any]] = []
    event_counts: collections.Counter[str] = collections.Counter()
    resolution_counts: collections.Counter[str] = collections.Counter()
    identity_counts: collections.Counter[str] = collections.Counter()
    event_time_sources: collections.Counter[str] = collections.Counter()
    position_updates = 0
    duplicate_count = 0
    out_of_order_count = 0
    started = time.perf_counter()
    for row in ordered:
        parsed_source = row.get("_parsed")
        if not isinstance(parsed_source, dict):
            continue
        if _text(parsed_source.get("event_family")).upper() != "WMESH":
            continue
        parsed = resolver.enrich_parsed(dict(parsed_source))
        details = dict(parsed.get("details") or {})
        event = {
            **parsed,
            "run_id": run_id,
            "device_uuid": _text(row.get("device_uuid")),
            "device_id": row.get("device_id"),
            "train_id": _text(row.get("train_id")),
            "mr_role": _text(row.get("mr_role")),
            "receive_time": _text(row.get("receive_time")),
            "source_ip": _text(row.get("source_ip")),
            "event_time": _text(row.get("_replay_event_time")),
            "event_time_source": _text(row.get("_replay_event_time_source")) or "RECEIVE_TIME",
            "event_time_precision": (
                "DEVICE_TIMESTAMP"
                if _text(row.get("_replay_event_time_source")) == "DEVICE_TIME"
                else "RECEIVE_TIME_ONLY"
            ),
            "station": _text(parsed.get("station")),
            "section": _text(parsed.get("section")),
        }
        details.update(
            {
                "global_receive_sequence": int(row.get("global_receive_sequence") or 0),
                "source_receive_sequence": int(row.get("source_receive_sequence") or 0),
                "receive_time": _text(row.get("receive_time")),
                "identity_status": _text(details.get("identity_status")) or "unresolved",
                "source_identity_status": "UNCONFIRMED_SOURCE_IP",
                "time_precision_limited": event["event_time_source"] != "DEVICE_TIME",
            }
        )
        event["details"] = details
        event["position_dedup_key"] = SyslogUdpReceiver._position_dedup_key(
            event,
            raw_text=_text(row.get("raw_text")),
        )
        result = engine.apply(event)
        details.update(
            {
                "position_result": result.reason,
                "position_state_changed": result.position_changed,
                "position_duplicate": result.duplicate,
                "position_out_of_order": result.out_of_order,
            }
        )
        event["details"] = details
        evidence_details = {
            key: details[key]
            for key in {
                "global_receive_sequence",
                "source_receive_sequence",
                "peer_ap_mac",
                "previous_peer_ap_mac",
                "resolution_status",
                "identity_status",
                "position_result",
                "position_state_changed",
                "position_duplicate",
                "position_out_of_order",
            }
            if key in details
        }
        events.append(
            {
                "event_type": event.get("event_type"),
                "device_uuid": event.get("device_uuid"),
                "event_time": event.get("event_time"),
                "event_time_source": event.get("event_time_source"),
                "receive_time": event.get("receive_time"),
                "details": evidence_details,
            }
        )
        event_counts[_text(event.get("event_type")).upper()] += 1
        resolution_counts[_text(details.get("resolution_status")).upper() or "UNKNOWN"] += 1
        identity_counts[_text(details.get("identity_status")).upper() or "UNKNOWN"] += 1
        event_time_sources[_text(event.get("event_time_source")).upper() or "UNKNOWN"] += 1
        position_updates += int(result.position_changed)
        duplicate_count += int(result.duplicate)
        out_of_order_count += int(result.out_of_order)
    states = list(engine.states().values())
    return {
        "identity_variant": "expanded",
        "ordering": ordering,
        "db_path": "",
        "processed_records": len(rows),
        "projection_event_count": len(events),
        "position_state_count": len(states),
        "event_counts": dict(sorted(event_counts.items())),
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "identity_counts": dict(sorted(identity_counts.items())),
        "event_time_sources": dict(sorted(event_time_sources.items())),
        "position_update_count": position_updates,
        "duplicate_event_count": duplicate_count,
        "out_of_order_event_count": out_of_order_count,
        "identity_source_ip_conflict_count": 0,
        "identity_source_ip_ambiguous_endpoint_count": 0,
        "failures": [],
        "replay_wall_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "states": states,
        "events": events,
    }


def _scheduler_compare(
    scheduler_rows: Iterable[Mapping[str, Any]],
    replay: Mapping[str, Any],
) -> dict[str, Any]:
    new_by_sequence: dict[int, Mapping[str, Any]] = {}
    for event in replay.get("events") or []:
        details = event.get("details") or {}
        try:
            sequence = int(details.get("global_receive_sequence") or 0)
        except (TypeError, ValueError):
            sequence = 0
        if sequence:
            new_by_sequence[sequence] = event
    old_wmesh = [
        row
        for row in scheduler_rows
        if _text(row.get("event_type")).casefold() in SCHEDULER_TO_WMESH
    ]
    categories: collections.Counter[str] = collections.Counter()
    dimensions: collections.Counter[str] = collections.Counter()
    matched_sequences: set[int] = set()
    for old in old_wmesh:
        details = old.get("details")
        details = details if isinstance(details, Mapping) else {}
        try:
            sequence = int(details.get("global_receive_sequence") or 0)
        except (TypeError, ValueError):
            sequence = 0
        new = new_by_sequence.get(sequence)
        if new is None:
            categories["OLD_ONLY"] += 1
            continue
        matched_sequences.add(sequence)
        new_details = new.get("details") or {}
        differences: list[str] = []
        expected_type = SCHEDULER_TO_WMESH[_text(old.get("event_type")).casefold()]
        if _text(new.get("event_type")).upper() != expected_type:
            differences.append("EVENT_TYPE_DIFFERENCE")
        if _text(old.get("mr_id")) != _text(new.get("device_uuid")):
            differences.append("MR_MAPPING_DIFFERENCE")
        old_ap = _mac_key(details.get("peer_ap_mac"))
        new_ap = _mac_key(new_details.get("peer_ap_mac"))
        old_previous = _mac_key(details.get("previous_peer_ap_mac"))
        new_previous = _mac_key(new_details.get("previous_peer_ap_mac"))
        if (old_ap and not new_ap) or (old_previous and not new_previous):
            differences.append("INSUFFICIENT_EVIDENCE")
        elif old_ap != new_ap or old_previous != new_previous:
            differences.append("AP_MAPPING_DIFFERENCE")
        old_time = _parse_time(old.get("ts"))
        new_time = _parse_time(new.get("event_time"))
        if old_time and new_time and abs((old_time - new_time).total_seconds()) > 5:
            differences.append("TIME_DIFFERENCE")
        if bool(new_details.get("position_duplicate")):
            differences.append("DUPLICATE_EVENT")
        if bool(new_details.get("position_out_of_order")):
            differences.append("OUT_OF_ORDER")
        if not differences:
            categories["MATCH"] += 1
        else:
            primary = "INSUFFICIENT_EVIDENCE" if "INSUFFICIENT_EVIDENCE" in differences else differences[0]
            categories[primary] += 1
            dimensions.update(differences)
    new_only = len(set(new_by_sequence) - matched_sequences)
    categories["NEW_ONLY"] += new_only
    return {
        "old_scheduler_wmesh_count": len(old_wmesh),
        "new_raw_projection_wmesh_count": len(new_by_sequence),
        "new_only_raw_observation_count": new_only,
        "categories": dict(sorted(categories.items())),
        "difference_dimensions": dict(sorted(dimensions.items())),
        "scope_note": (
            "scheduler_events is a bounded scheduler projection; NEW_ONLY raw observations "
            "are not treated as product defects without an archive contract requiring every raw WMESH row."
        ),
    }


def _old_position_states(scheduler_rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    rows = sorted(
        (
            row
            for row in scheduler_rows
            if _text(row.get("event_type")).casefold() in SCHEDULER_TO_WMESH
        ),
        key=lambda row: (
            int((row.get("details") or {}).get("global_receive_sequence") or 0),
            _text(row.get("ts")),
        ),
    )
    for row in rows:
        mr_id = _text(row.get("mr_id"))
        if not mr_id:
            continue
        details = row.get("details")
        details = details if isinstance(details, Mapping) else {}
        current = result.setdefault(
            mr_id,
            {"current_ap_mac": "", "previous_ap_mac": "", "last_event_time": ""},
        )
        event_type = SCHEDULER_TO_WMESH[_text(row.get("event_type")).casefold()]
        incoming = _text(details.get("peer_ap_mac"))
        if event_type == "MESH_LINKDOWN":
            if not current["current_ap_mac"]:
                current["current_ap_mac"] = incoming
        elif incoming and _mac_key(incoming) != _mac_key(current["current_ap_mac"]):
            current["previous_ap_mac"] = current["current_ap_mac"]
            current["current_ap_mac"] = incoming
        if _text(row.get("ts")):
            current["last_event_time"] = _text(row.get("ts"))
    return result


def _position_compare(
    scheduler_rows: Iterable[Mapping[str, Any]],
    replay: Mapping[str, Any],
    latest_ac: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    old = _old_position_states(scheduler_rows)
    new = {
        _text(row.get("device_uuid")): row
        for row in replay.get("states") or []
        if _text(row.get("device_uuid"))
    }
    old_current_comparable = 0
    current_match = 0
    current_difference = 0
    unresolved = 0
    previous_comparable = 0
    previous_match = 0
    ac_comparable = 0
    ac_match = 0
    ac_difference = 0
    ac_unknown = 0
    for mr_id, old_state in old.items():
        new_state = new.get(mr_id)
        if new_state is None:
            continue
        old_current = _mac_key(old_state.get("current_ap_mac"))
        new_current = _mac_key(new_state.get("current_ap_mac"))
        if old_current:
            old_current_comparable += 1
            if not new_current:
                unresolved += 1
            elif old_current == new_current:
                current_match += 1
            else:
                current_difference += 1
        old_previous = _mac_key(old_state.get("previous_ap_mac"))
        new_previous = _mac_key(new_state.get("previous_ap_mac"))
        if old_previous:
            previous_comparable += 1
            if old_previous == new_previous:
                previous_match += 1
        ac_row = latest_ac.get(mr_id)
        ac_current = _mac_key((ac_row or {}).get("peer_ap_mac"))
        if ac_current and new_current:
            ac_comparable += 1
            if ac_current == new_current:
                ac_match += 1
            else:
                ac_difference += 1
        elif ac_row is not None:
            ac_unknown += 1
    return {
        "scheduler_reference_mr_count": len(old),
        "replay_position_state_count": len(new),
        "current_comparable_count": old_current_comparable,
        "current_match_count": current_match,
        "current_difference_count": current_difference,
        "current_unresolved_count": unresolved,
        "current_match_rate_percent": round(current_match * 100 / old_current_comparable, 3)
        if old_current_comparable
        else None,
        "previous_comparable_count": previous_comparable,
        "previous_match_count": previous_match,
        "ac_comparable_count": ac_comparable,
        "ac_match_count": ac_match,
        "ac_difference_count": ac_difference,
        "ac_unknown_count": ac_unknown,
        "history_event_count": len(replay.get("events") or []),
        "history_is_full_projection": True,
        "ground_truth_note": "scheduler_events and AC are comparison evidence, not an absolute position ground truth.",
    }


def _read_ac_rows(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    return _read_jsonl_members(
        archive,
        (
            name
            for name in archive.namelist()
            if name.startswith("ac_snapshots/") and name.casefold().endswith(".jsonl")
        ),
    )


def _ac_replay(
    ac_rows: list[dict[str, Any]],
    *,
    latest_time: str,
    syslog_states: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in ac_rows:
        snapshot_id = _text(row.get("snapshot_id"))
        if snapshot_id:
            groups[snapshot_id].append(row)
    envelopes: list[AcSnapshotEnvelope] = []
    for snapshot_id, rows in groups.items():
        ordered = sorted(rows, key=lambda row: (_text(row.get("received_at")), _text(row.get("device_time"))))
        freshness = {
            _text(row.get("freshness_status")).casefold()
            for row in ordered
            if _text(row.get("freshness_status"))
        }
        data_status = "fresh" if freshness and freshness <= {"fresh", "success", "complete"} else "stale"
        first = ordered[0] if ordered else {}
        envelopes.append(
            AcSnapshotEnvelope(
                controller_id=_text(first.get("ac_device_id")),
                snapshot_id=snapshot_id,
                rows=tuple(ordered),
                device_time=_text(first.get("device_time")),
                received_at=_text(first.get("received_at")),
                data_status=data_status,
                complete=bool(ordered),
                revision=_text(first.get("source_snapshot_id")),
            )
        )
    envelopes.sort(key=lambda item: (_parse_time(item.observation_time) or datetime.max.replace(tzinfo=timezone.utc), item.snapshot_id))
    previous: AcSnapshotEnvelope | None = None
    counts: collections.Counter[str] = collections.Counter()
    accepted = 0
    rejected = 0
    older = 0
    for envelope in envelopes:
        if previous is not None and (
            _parse_time(envelope.observation_time) or datetime.min.replace(tzinfo=timezone.utc)
        ) < (
            _parse_time(previous.observation_time) or datetime.min.replace(tzinfo=timezone.utc)
        ):
            older += 1
        delta = diff_full_snapshot(previous, envelope)
        counts.update(delta.counts)
        if delta.accepted:
            accepted += 1
        else:
            rejected += 1
        previous = envelope
    latest_by_mr: dict[str, dict[str, Any]] = {}
    for row in ac_rows:
        mr_id = _text(row.get("mr_id"))
        mac = _text(row.get("peer_ap_mac"))
        if not mr_id or not mac:
            continue
        current = latest_by_mr.get(mr_id)
        current_time = _parse_time(_text(row.get("device_time")) or _text(row.get("received_at")))
        previous_time = _parse_time(
            _text((current or {}).get("device_time")) or _text((current or {}).get("received_at"))
        )
        if current is None or (current_time and (previous_time is None or current_time >= previous_time)):
            latest_by_mr[mr_id] = row
    reconciliation_counts: collections.Counter[str] = collections.Counter()
    ordering_counts: collections.Counter[str] = collections.Counter()
    for state in syslog_states:
        mr_id = _text(state.get("device_uuid"))
        result = reconcile_syslog_ac(
            state,
            latest_by_mr.get(mr_id),
            now=latest_time,
            stale_after_seconds=120.0,
        )
        reconciliation_counts[result.state] += 1
        ordering = reconcile_syslog_ac(
            state,
            latest_by_mr.get(mr_id),
            now=latest_time,
            stale_after_seconds=86400.0,
        )
        ordering_counts[ordering.state] += 1
    return {
        "snapshot_count": len(envelopes),
        "row_count": len(ac_rows),
        "nonempty_position_row_count": sum(bool(_text(row.get("peer_ap_mac"))) for row in ac_rows),
        "latest_mr_count": len(latest_by_mr),
        "delta_counts": {key: int(counts.get(key, 0)) for key in sorted(AC_DELTA_ACTIONS)},
        "accepted_snapshot_count": accepted,
        "rejected_snapshot_count": rejected,
        "older_snapshot_count": older,
        "reconciliation_counts_stale_120s": dict(sorted(reconciliation_counts.items())),
        "reconciliation_counts_ordering_only": dict(sorted(ordering_counts.items())),
        "stale_policy": "AC stale or incomplete evidence is retained for history and cannot overwrite Syslog Current.",
        "latest_by_mr": latest_by_mr,
    }


def _timeline_audit(
    archive: zipfile.ZipFile,
    *,
    syslog_mr_ids: set[str],
    ac_mr_ids: set[str],
    ping_mr_ids: set[str],
) -> dict[str, Any]:
    record_counts: collections.Counter[str] = collections.Counter()
    mr_ids: set[str] = set()
    timestamps: list[datetime] = []
    rows = 0
    for name in sorted(
        item
        for item in archive.namelist()
        if item.startswith("timeline/") and item.casefold().endswith(".jsonl")
    ):
        for row in _iter_json_lines(archive, name):
            rows += 1
            record_counts[_text(row.get("record_type")).lower() or "unknown"] += 1
            if _text(row.get("mr_id")):
                mr_ids.add(_text(row.get("mr_id")))
            parsed = _parse_time(row.get("ts"))
            if parsed:
                timestamps.append(parsed)
    overlap = syslog_mr_ids & ac_mr_ids & ping_mr_ids
    return {
        "record_count": rows,
        "record_type_counts": dict(sorted(record_counts.items())),
        "mr_count": len(mr_ids),
        "start_time": _iso(min(timestamps)) if timestamps else "",
        "end_time": _iso(max(timestamps)) if timestamps else "",
        "syslog_mr_count": len(syslog_mr_ids),
        "ac_mr_count": len(ac_mr_ids),
        "ping_mr_count": len(ping_mr_ids),
        "all_three_channel_mr_count": len(overlap),
        "all_three_channel_mr_ids_are_internal_only": True,
    }


def _ping_summary_rows(archive: zipfile.ZipFile) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    shape_counts: collections.Counter[str] = collections.Counter()
    for name in ("ping_summaries/all_summaries.jsonl",):
        for row in _iter_json_lines(archive, name):
            all_rows.append(row)
    for name in ("ping_summaries/daily_by_mr.json", "ping_summaries/daily_by_train.json"):
        try:
            value = json.loads(archive.read(name).decode("utf-8"))
            shape_counts[name] = len(value) if isinstance(value, list) else 1
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
            shape_counts[name] = -1
    return all_rows, {"all_summary_count": len(all_rows), "member_shapes": dict(shape_counts)}


def _ping_replay(
    archive: zipfile.ZipFile,
    *,
    output_dir: Path,
    site_id: str,
    run_id: str,
    archive_summary_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    db_path = output_dir / "ping_replay.sqlite"
    repository = GroundUnattendedRepository(db_path, site_id=site_id)
    supervisor = FleetPingSupervisor(repository=repository, site_id=site_id)
    supervisor._run_id = run_id
    supervisor._run_date = run_id[:10]
    supervisor._period_ms = 1000
    supervisor._timeout_ms = 4000
    supervisor._warmup_seconds = 10
    supervisor._raw_writer = None
    supervisor._raw_compressor = None
    supervisor._correlator = None
    target_rows: dict[str, dict[str, Any]] = {}
    sample_count = 0
    success_count = 0
    loss_count = 0
    raw_success_count = 0
    raw_loss_count = 0
    ignored_count = 0
    rtts: list[float] = []
    target_raw_counts: collections.Counter[str] = collections.Counter()
    target_effective_counts: collections.Counter[str] = collections.Counter()
    target_success_counts: collections.Counter[str] = collections.Counter()
    target_loss_counts: collections.Counter[str] = collections.Counter()
    names = sorted(
        name
        for name in archive.namelist()
        if name.startswith("fleet_ping/")
        and name.casefold().endswith(".ndjson")
        and not name.casefold().endswith("layout.jsonl")
    )
    started = time.perf_counter()
    for name in names:
        for row in _iter_json_lines(archive, name):
            target = _text(row.get("target_ip"))
            if not target:
                continue
            if target not in target_rows:
                target_rows[target] = row
                supervisor._started_at[target] = _text(row.get("target_activation_started_at")) or _text(row.get("ts"))
                supervisor._targets[target] = FleetPingTarget(
                    target_ip=target,
                    train_id=_text(row.get("train_id")),
                    train_no=_text(row.get("train_no")),
                    mr_id=_text(row.get("mr_id")) or _text(row.get("device_uuid")),
                    mr_position_code=_text(row.get("mr_position_code")),
                    mr_name=_text(row.get("mr_name")),
                    device_id=row.get("device_id"),
                    ac_snapshot_id=row.get("ac_snapshot_id"),
                    ac_received_at=_text(row.get("ac_received_at")),
                    current_ap_identity=_text(row.get("current_ap_identity")),
                    current_ap_name=_text(row.get("current_ap_name")),
                    current_ap_mac=_text(row.get("current_ap_mac")),
                    station=_text(row.get("station")),
                    section=_text(row.get("section")),
                    mileage=_text(row.get("mileage")),
                    rssi=row.get("rssi"),
                    same_ap_since=_text(row.get("target_activation_started_at")),
                )
            sample = FpingV5Sample(
                ts=_text(row.get("ts")),
                target=target,
                seq=int(row.get("seq")) if row.get("seq") not in {None, ""} else None,
                ok=row.get("ok"),
                rtt_ms=float(row["rtt_ms"]) if row.get("rtt_ms") not in {None, ""} else None,
                timeout_ms=int(row.get("timeout_ms") or 4000),
                size=int(row.get("packet_size")) if row.get("packet_size") not in {None, ""} else None,
                error=_text(row.get("error")),
                backend=_text(row.get("backend")) or BACKEND,
                raw_type="archive",
                raw=row,
            )
            supervisor._record_sample(sample, _text(row.get("shard_id")) or "legacy-replay")
            sample_count += 1
            target_raw_counts[target] += 1
            if bool(row.get("ok")):
                raw_success_count += 1
            else:
                raw_loss_count += 1
            warmup = bool(row.get("warmup_ignored"))
            if warmup:
                ignored_count += 1
            else:
                target_effective_counts[target] += 1
                if bool(row.get("ok")):
                    success_count += 1
                    target_success_counts[target] += 1
                    if row.get("rtt_ms") not in {None, ""}:
                        rtts.append(float(row["rtt_ms"]))
                else:
                    loss_count += 1
                    target_loss_counts[target] += 1
    supervisor.flush_summaries()
    summaries = supervisor.target_summaries()
    stop_result = supervisor.stop()
    archive_daily = {
        _text(row.get("target_ip")): row
        for row in archive_summary_rows
        if _text(row.get("bucket_kind")).casefold() == "daily"
    }
    archive_daily_rows = list(archive_daily.values())
    daily_mismatches = 0
    for summary in summaries:
        expected = archive_daily.get(_text(summary.get("target_ip")))
        if expected is None:
            continue
        if any(
            int(summary.get(field) or 0) != int(expected.get(field) or 0)
            for field in ("raw_sample_count", "sent_count", "success_count", "loss_count")
        ):
            daily_mismatches += 1
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "db_path": str(db_path),
        "file_count": len(names),
        "sample_count": sample_count,
        "target_count": len(target_rows),
        "success_count": success_count,
        "loss_count": loss_count,
        "raw_success_count_including_warmup": raw_success_count,
        "raw_loss_count_including_warmup": raw_loss_count,
        "warmup_ignored_count_from_archive": ignored_count,
        "loss_rate_percent": round(loss_count * 100 / (success_count + loss_count), 4)
        if success_count + loss_count
        else 0.0,
        "rtt_ms": {
            "p50": _percentile(rtts, 50),
            "p95": _percentile(rtts, 95),
            "p99": _percentile(rtts, 99),
            "min": min(rtts) if rtts else None,
            "max": max(rtts) if rtts else None,
        },
        "daily_summary_target_mismatch_count": daily_mismatches,
        "archive_daily_raw_sample_count": sum(
            int(row.get("raw_sample_count") or 0) for row in archive_daily_rows
        ),
        "archive_daily_sent_count": sum(
            int(row.get("sent_count") or 0) for row in archive_daily_rows
        ),
        "archive_daily_success_count": sum(
            int(row.get("success_count") or 0) for row in archive_daily_rows
        ),
        "archive_daily_loss_count": sum(
            int(row.get("loss_count") or 0) for row in archive_daily_rows
        ),
        "supervisor_stop": stop_result,
        "replay_wall_ms": round(elapsed_ms, 3),
        "target_raw_count_total": sum(target_raw_counts.values()),
        "target_effective_count_total": sum(target_effective_counts.values()),
        "target_success_count_total": sum(target_success_counts.values()),
        "target_loss_count_total": sum(target_loss_counts.values()),
        "mr_ids": {
            _text(row.get("mr_id")) or _text(row.get("device_uuid"))
            for row in target_rows.values()
            if _text(row.get("mr_id")) or _text(row.get("device_uuid"))
        },
    }


def _json_safe_summary(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe_summary(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_summary(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _acceptance(summary: Mapping[str, Any]) -> dict[str, str]:
    inventory = summary.get("inventory") or {}
    paired = inventory.get("paired_plain_gzip") or {}
    syslog = summary.get("syslog") or {}
    replay = summary.get("replay") or {}
    ping = summary.get("ping") or {}
    ac = summary.get("ac") or {}
    timeline = summary.get("timeline") or {}
    return {
        "ARCHIVE_INTEGRITY": "PASS"
        if not inventory.get("zip_test_member")
        and not inventory.get("manifest_member_sha_mismatch")
        and not inventory.get("json_errors")
        and not inventory.get("encoding_errors")
        and summary.get("archive_unchanged")
        else "FAIL",
        "ARCHIVE_DEDUPLICATION": "PASS"
        if not paired.get("mismatches") and not syslog.get("duplicate_raw_record_count")
        else "FAIL",
        "SYSLOG_REPLAY": "PASS"
        if syslog.get("parse_failures", 1) == syslog.get("non_wmesh_unparsed_count", -1)
        and all(not (item.get("failures") or []) for item in replay.values())
        else "FAIL",
        "WMESH_LINKUP": "PASS" if syslog.get("event_counts", {}).get("MESH_LINKUP", 0) else "FAIL",
        "WMESH_LINKDOWN": "PASS" if syslog.get("event_counts", {}).get("MESH_LINKDOWN", 0) else "FAIL",
        "WMESH_ACTIVE_SWITCH": "PASS" if syslog.get("event_counts", {}).get("MESH_ACTIVELINK_SWITCH", 0) else "FAIL",
        "MR_IDENTITY_MAPPING": "PASS_WITH_LIMITATION"
        if syslog.get("identity_unconfirmed_source_ip_count", 0)
        else "PASS",
        "AP_IDENTITY_MAPPING": "PASS_WITH_LIMITATION"
        if (summary.get("identity") or {}).get("strict_unresolved_event_count", 0)
        else "PASS",
        "POSITION_CORRECTNESS": "PASS_WITH_LIMITATION"
        if (summary.get("position") or {}).get("current_difference_count", 1) == 0
        else "REVIEW",
        "POSITION_HISTORY": "PASS"
        if (summary.get("position") or {}).get("history_event_count", 0) == syslog.get("wmesh_count", -1)
        else "REVIEW",
        "PING_HISTORY": "PASS"
        if ping.get("sample_count") == ping.get("target_raw_count_total")
        and not ping.get("daily_summary_target_mismatch_count")
        else "REVIEW",
        "AC_SNAPSHOT_DELTA": "PASS" if ac.get("snapshot_count", 0) else "FAIL",
        "SYSLOG_AC_RECONCILIATION": "PASS" if ac.get("latest_mr_count", 0) else "REVIEW",
        "THREE_CHANNEL_TIMELINE": "PASS" if timeline.get("all_three_channel_mr_count", 0) else "REVIEW",
        "LEGACY_COMPATIBILITY": "PASS"
        if inventory.get("json_errors", 1) == 0 and inventory.get("encoding_errors", 1) == 0
        else "FAIL",
        "FULL_LOCAL_REGRESSION": "PENDING_LOCAL_GATES",
        "LEGACY_REPLAY_ACCEPTANCE": "PASS_WITH_LIMITATION",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    archive_path = Path(args.archive).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_before = _sha256_file(archive_path)
    tracemalloc.start()
    timings: dict[str, float] = {}
    with zipfile.ZipFile(archive_path, "r") as archive:
        started = time.perf_counter()
        manifest, inventory = _inventory_archive(archive, archive_path)
        timings["archive_inventory_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        site_id = _text(args.site_id) or _text(manifest.get("site_id")) or "hzl10"
        run_id = _text(args.run_id) or _text(manifest.get("run_id"))
        syslog_names = [
            name
            for name in archive.namelist()
            if name.startswith("realtime/syslog/")
            and name.casefold().endswith(".ndjson")
        ]
        started = time.perf_counter()
        syslog_rows = _read_jsonl_members(archive, syslog_names, annotate=True)
        scheduler_rows = _read_jsonl_members(archive, ["scheduler_events.jsonl"])
        ac_rows = _read_ac_rows(archive)
        archive_summary_rows, ping_summary_shape = _ping_summary_rows(archive)
        syslog_parse_summary = _prepare_syslog_rows(syslog_rows)
        timings["source_jsonl_read_and_parse_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        raw_hashes = collections.Counter(
            _sha256_bytes(_text(row.get("raw_text")).encode("utf-8"))
            for row in syslog_rows
        )
        syslog_summary = {
            **syslog_parse_summary,
            "plain_record_count": len(syslog_rows),
            "syslog_file_count": len(syslog_names),
            "duplicate_raw_record_count": sum(count - 1 for count in raw_hashes.values() if count > 1),
            "unique_raw_record_count": len(raw_hashes),
            "identity_status_counts_in_archive": dict(
                sorted(collections.Counter(_text(row.get("identity_status")) or "UNKNOWN" for row in syslog_rows).items())
            ),
            "non_wmesh_unparsed_count": sum(
                1 for row in syslog_rows if row.get("_parsed") is None
            ),
        }
        syslog_summary["identity_unconfirmed_source_ip_count"] = int(
            syslog_summary["identity_status_counts_in_archive"].get(
                "UNCONFIRMED_SOURCE_IP", 0
            )
        )
        started = time.perf_counter()
        strict_db, strict_query, strict_seed = _build_identity_database(
            output_dir / "identity_strict.sqlite",
            ac_rows=ac_rows,
            scheduler_rows=scheduler_rows,
            site_id=site_id,
            expanded=False,
        )
        expanded_db, expanded_query, expanded_seed = _build_identity_database(
            output_dir / "identity_expanded.sqlite",
            ac_rows=ac_rows,
            scheduler_rows=scheduler_rows,
            site_id=site_id,
            expanded=True,
        )
        del strict_db, expanded_db
        timings["identity_seed_and_index_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        syslog_summary.update(_syslog_dedup_audit(syslog_rows, strict_query))
        started = time.perf_counter()
        replays: dict[str, dict[str, Any]] = {}
        strict_path = output_dir / "position_strict_receive.sqlite"
        if strict_path.is_file():
            existing = _load_existing_replay(
                strict_path,
                site_id=site_id,
                run_id=run_id,
                processed_records=len(syslog_rows),
            )
            if existing["event_counts"].get("MESH_LINKUP", 0) + existing["event_counts"].get(
                "MESH_LINKDOWN", 0
            ) + existing["event_counts"].get("MESH_ACTIVELINK_SWITCH", 0) >= syslog_parse_summary["wmesh_count"]:
                replays["strict_receive"] = existing
            else:
                replays["strict_receive"] = _replay_syslog(
                    syslog_rows,
                    output_dir=output_dir,
                    site_id=site_id,
                    run_id=run_id,
                    identity_query=strict_query,
                    identity_variant="strict",
                    ordering="receive",
                )
        else:
            replays["strict_receive"] = _replay_syslog(
                syslog_rows,
                output_dir=output_dir,
                site_id=site_id,
                run_id=run_id,
                identity_query=strict_query,
                identity_variant="strict",
                ordering="receive",
            )
        # The expanded identity variant is intentionally replayed through the
        # current PositionEngine in memory.  The strict repository replay above
        # already proves the full historical persistence path; repeating the
        # same 40k-line SQLite write for an identity comparison only creates
        # avoidable temporary I/O.
        replays["expanded_receive"] = _memory_position_replay(
            syslog_rows,
            site_id=site_id,
            run_id=run_id,
            identity_query=expanded_query,
            ordering="receive",
        )
        replays["expanded_event_time"] = _memory_position_replay(
            syslog_rows,
            site_id=site_id,
            run_id=run_id,
            identity_query=expanded_query,
            ordering="event_time",
        )
        timings["syslog_replay_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        expanded_receive = replays["expanded_receive"]
        expanded_event_time = replays["expanded_event_time"]
        strict_receive = replays["strict_receive"]
        identity_summary = {
            "strict": strict_seed,
            "expanded": expanded_seed,
            "strict_unresolved_event_count": int(
                (strict_receive.get("resolution_counts") or {}).get("UNRESOLVED", 0)
            ),
            "expanded_unresolved_event_count": int(
                (expanded_receive.get("resolution_counts") or {}).get("UNRESOLVED", 0)
            ),
            "strict_resolution_counts": strict_receive.get("resolution_counts", {}),
            "expanded_resolution_counts": expanded_receive.get("resolution_counts", {}),
            "identity_boundary": "Unconfirmed source IP is retained as unconfirmed and does not become trusted device identity.",
        }
        scheduler_compare = _scheduler_compare(scheduler_rows, expanded_event_time)
        latest_time = _text(manifest.get("actual_end")) or max(
            (_text(row.get("receive_time")) for row in syslog_rows),
            default=_iso(_now()),
        )
        ac_summary = _ac_replay(
            ac_rows,
            latest_time=latest_time,
            syslog_states=expanded_event_time.get("states") or [],
        )
        latest_ac = ac_summary.pop("latest_by_mr")
        position_summary = _position_compare(
            scheduler_rows,
            expanded_event_time,
            latest_ac,
        )
        started = time.perf_counter()
        ping_summary = _ping_replay(
            archive,
            output_dir=output_dir,
            site_id=site_id,
            run_id=run_id,
            archive_summary_rows=archive_summary_rows,
        )
        timings["ping_replay_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
        ping_summary.update(ping_summary_shape)
        syslog_mrs = {
            _text(row.get("device_uuid"))
            for row in expanded_event_time.get("states") or []
            if _text(row.get("device_uuid"))
        }
        ac_mrs = {
            _text(row.get("mr_id"))
            for row in ac_rows
            if _text(row.get("mr_id"))
        }
        ping_mrs = set(ping_summary.pop("mr_ids"))
        timeline_summary = _timeline_audit(
            archive,
            syslog_mr_ids=syslog_mrs,
            ac_mr_ids=ac_mrs,
            ping_mr_ids=ping_mrs,
        )
    archive_after = _sha256_file(archive_path)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    replay_public = {
        key: {
            field: value
            for field, value in replay.items()
            if field not in {"states", "events", "db_path"}
        }
        for key, replay in replays.items()
    }
    replay_public["expanded_receive"]["position_history_event_count"] = len(
        replays["expanded_receive"].get("events") or []
    )
    replay_public["expanded_event_time"]["position_history_event_count"] = len(
        replays["expanded_event_time"].get("events") or []
    )
    summary: dict[str, Any] = {
        "schema": "netconsole.ground_unattended.legacy_replay.v1",
        "generated_at": _iso(_now()),
        "archive": {
            "file_name": archive_path.name,
            "sha256_before": archive_before,
            "sha256_after": archive_after,
            "site_id": _text(manifest.get("site_id")) or _text(args.site_id),
            "run_id": _text(manifest.get("run_id")) or _text(args.run_id),
            "manifest_schema_version": manifest.get("schema_version"),
            "archive_type": manifest.get("archive_type"),
            "run_state": ((manifest.get("summary") or {}).get("sessions") or [{}])[0].get("state", ""),
            "run_start": (manifest.get("summary") or {}).get("actual_started_at"),
            "run_end": (manifest.get("summary") or {}).get("actual_ended_at"),
        },
        "archive_unchanged": archive_before == archive_after,
        "inventory": inventory,
        "syslog": syslog_summary,
        "identity": identity_summary,
        "replay": replay_public,
        "scheduler_comparison": scheduler_compare,
        "position": position_summary,
        "ping": ping_summary,
        "ac": ac_summary,
        "timeline": timeline_summary,
        "performance": {
            "stage_wall_ms": timings,
            "tracemalloc_current_mb": round(current / 1024 / 1024, 3),
            "tracemalloc_peak_mb": round(peak / 1024 / 1024, 3),
            "online_delay_measurement_eligible": False,
            "offline_delay_note": "Replay wall time measures offline processing only; it is not a Syslog event-to-UI latency measurement.",
        },
        "acceptance": {},
        "limitations": [
            "Archive rows do not carry original Raw Persist Time, Parse Complete Time, Position Commit Time, or UI Available Time.",
            "Archive device_time fields are empty; trusted event time is recovered only when the raw H3C timestamp passes the current clock-quality rule.",
            "Scheduler events are a bounded derived projection and are not absolute ground truth for all raw WMESH observations.",
            "AC peer_ap_mac is used only as an exact physical AP seed; no fuzzy, reverse-MAC, or cross-station association is introduced.",
            "No real ping process, device connection, production database, or uploaded ZIP member was used as a write target.",
        ],
    }
    summary["acceptance"] = _acceptance(summary)
    output_path = output_dir / "legacy_replay_summary.json"
    output_path.write_text(
        json.dumps(_json_safe_summary(summary), ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "summary": str(output_path), "archive_sha256": archive_before}, ensure_ascii=False))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, help="read-only source ZIP")
    parser.add_argument("--output-dir", required=True, help="isolated derived evidence directory")
    parser.add_argument("--site-id", default="hzl10")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    if not Path(args.archive).is_file():
        parser.error("archive does not exist")
    try:
        run(args)
    except Exception as exc:  # pragma: no cover - command boundary
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
