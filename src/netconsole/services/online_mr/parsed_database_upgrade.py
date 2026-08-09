from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from netconsole.services.online_mr.parsed_database_contract import (
    PARSER_CAPABILITIES,
    PARSER_SCHEMA_VERSION,
    PARSER_VERSION,
    inspect_parsed_database,
)
from netconsole.services.rail_transit.online_mr_diagnosis_parser import (
    OnlineMrDiagnosisParser,
    OnlineMrParseSummary,
)


LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]

UPGRADE_CURRENT = "CURRENT"
UPGRADE_REQUIRED = "REQUIRED"
UPGRADE_UPGRADING = "UPGRADING"
UPGRADE_FAILED = "FAILED"
UPGRADE_RAW_DATA_MISSING = "RAW_DATA_MISSING"

RAW_SOURCE_NAMES = frozenset(
    {
        "mesh_link_raw.log",
        "terminal_monitor_raw.log",
        "channel_busy_raw.log",
        "ap_radio_statistics_raw.log",
        "interface_rate_raw.log",
        "switch_history_latest.log",
        "fping_v5_raw.log",
        "fping_v5_samples.jsonl",
        "fping_raw.log",
        "Fping.txt",
        "fping.txt",
        "iperf_client_raw.log",
        "iperf_client.json",
        "iperf3.json",
        "iperf_client_raw.json",
    }
)


class OnlineMrParsedDatabaseUpgradeError(RuntimeError):
    pass


class OnlineMrRawDataMissingError(OnlineMrParsedDatabaseUpgradeError):
    pass


def raw_fingerprint(raw_root: Path) -> str:
    items: list[dict[str, object]] = []
    if raw_root.is_dir():
        for path in sorted(raw_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append(
                {
                    "path": path.relative_to(raw_root).as_posix(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class OnlineMrParsedDatabaseUpgradeService:
    def __init__(self, session_dir: str | Path) -> None:
        self.session_dir = Path(session_dir)
        self.raw_dir = self.session_dir / "raw"
        self.parsed_dir = self.session_dir / "parsed"
        self.database_path = self.parsed_dir / "online_diagnosis.sqlite"
        self.candidate_path = self.parsed_dir / "online_diagnosis.sqlite.upgrading"
        self.state_path = self.parsed_dir / "online_diagnosis.upgrade.json"
        self.retired_dir = self.parsed_dir / "retired"
        self.rollback_path = self.retired_dir / "online_diagnosis.previous.sqlite"

    def read_state(self) -> dict[str, object]:
        if not self.state_path.is_file() or self.state_path.is_symlink():
            return {}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return dict(value) if isinstance(value, dict) else {}

    def write_state(self, status: str, **values: object) -> dict[str, object]:
        self.parsed_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status,
            "target_schema_version": PARSER_SCHEMA_VERSION,
            "target_capabilities": list(PARSER_CAPABILITIES),
            "updated_at": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
            **values,
        }
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)
        return payload

    def raw_sources_available(self) -> tuple[bool, str]:
        if not (self.session_dir / "session_meta.json").is_file():
            return False, "缺少 session_meta.json"
        if not self.raw_dir.is_dir() or self.raw_dir.is_symlink():
            return False, "缺少原始采集目录"
        for path in self.raw_dir.iterdir():
            if path.name in RAW_SOURCE_NAMES and path.is_file() and not path.is_symlink():
                try:
                    if path.stat().st_size > 0:
                        return True, ""
                except OSError:
                    continue
        return False, "缺少可用于重建的原始采集文件"

    def current_raw_fingerprint(self) -> str:
        return raw_fingerprint(self.raw_dir)

    def retry_suppressed(self, fingerprint: str | None = None) -> bool:
        state = self.read_state()
        return (
            str(state.get("status") or "") in {UPGRADE_FAILED, UPGRADE_RAW_DATA_MISSING}
            and str(state.get("raw_fingerprint") or "") == str(fingerprint or self.current_raw_fingerprint())
        )

    def rebuild(
        self,
        *,
        force: bool,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> dict[str, object]:
        started = time.monotonic()
        fingerprint = self.current_raw_fingerprint()
        previous = inspect_parsed_database(self.database_path)
        missing = sorted(previous.missing_capabilities)
        if previous.current and not force:
            self._cleanup_candidate()
            self.write_state(
                UPGRADE_CURRENT,
                from_schema=previous.schema_version,
                raw_fingerprint=fingerprint,
                missing_capabilities=[],
                message="解析数据库已是当前版本。",
            )
            return {
                "upgrade_status": UPGRADE_CURRENT,
                "cache_used": True,
                "schema_version": PARSER_SCHEMA_VERSION,
                "capabilities": list(PARSER_CAPABILITIES),
            }
        available, reason = self.raw_sources_available()
        if not available:
            self.write_state(
                UPGRADE_RAW_DATA_MISSING,
                from_schema=previous.schema_version,
                raw_fingerprint=fingerprint,
                missing_capabilities=missing,
                message=reason,
            )
            raise OnlineMrRawDataMissingError(reason)
        self.write_state(
            UPGRADE_UPGRADING,
            from_schema=previous.schema_version,
            raw_fingerprint=fingerprint,
            missing_capabilities=missing,
            message="正在从原始采集数据重建解析数据库。",
        )
        LOGGER.info(
            "online_mr_parser_upgrade session=%s from_schema=%s to_schema=%s missing_capabilities=%s status=started",
            self.session_dir.name,
            previous.schema_version,
            PARSER_SCHEMA_VERSION,
            len(missing),
        )
        try:
            recovered = self._recover_completed_candidate(fingerprint)
            if recovered is None:
                self._cleanup_candidate()
                parser = OnlineMrDiagnosisParser(self.session_dir, db_path=self.candidate_path)
                summary = parser.parse(force=True, progress=progress, should_cancel=should_cancel)
                self._validate_candidate(fingerprint, summary)
            else:
                summary = recovered
                if progress is not None:
                    progress("恢复升级结果", 12, 12, "使用上次中断前已完成校验的解析库")
            self._publish_candidate()
            current = inspect_parsed_database(self.database_path)
            if not current.current:
                raise OnlineMrParsedDatabaseUpgradeError("原子替换后的解析数据库未通过 capability 校验")
            duration_ms = int((time.monotonic() - started) * 1000)
            state = self.write_state(
                UPGRADE_CURRENT,
                from_schema=previous.schema_version,
                raw_fingerprint=fingerprint,
                missing_capabilities=[],
                message="解析数据库升级完成。",
                duration_ms=duration_ms,
                revision=self.database_revision(),
            )
            LOGGER.info(
                "online_mr_parser_upgrade session=%s from_schema=%s to_schema=%s status=completed duration_ms=%s capabilities=%s",
                self.session_dir.name,
                previous.schema_version,
                PARSER_SCHEMA_VERSION,
                duration_ms,
                ",".join(PARSER_CAPABILITIES),
            )
            return {
                **asdict(summary),
                "upgrade_status": UPGRADE_CURRENT,
                "schema_version": PARSER_SCHEMA_VERSION,
                "capabilities": list(PARSER_CAPABILITIES),
                "revision": state["revision"],
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            self._cleanup_candidate()
            duration_ms = int((time.monotonic() - started) * 1000)
            status = UPGRADE_RAW_DATA_MISSING if isinstance(exc, OnlineMrRawDataMissingError) else UPGRADE_FAILED
            self.write_state(
                status,
                from_schema=previous.schema_version,
                raw_fingerprint=fingerprint,
                missing_capabilities=missing,
                message=str(exc),
                duration_ms=duration_ms,
            )
            LOGGER.error(
                "online_mr_parser_upgrade session=%s from_schema=%s to_schema=%s status=failed duration_ms=%s reason=%s",
                self.session_dir.name,
                previous.schema_version,
                PARSER_SCHEMA_VERSION,
                duration_ms,
                str(exc),
            )
            raise

    def _recover_completed_candidate(self, fingerprint: str) -> OnlineMrParseSummary | None:
        if not self.candidate_path.is_file():
            return None
        parser = OnlineMrDiagnosisParser(self.session_dir, db_path=self.candidate_path)
        summary = parser.cached_summary_if_valid()
        if summary is None:
            return None
        self._validate_candidate(fingerprint, summary)
        return summary

    def _validate_candidate(self, fingerprint: str, summary: OnlineMrParseSummary) -> None:
        with closing(sqlite3.connect(self.candidate_path, timeout=10)) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.casefold() != "ok":
                raise OnlineMrParsedDatabaseUpgradeError(f"临时解析数据库完整性校验失败：{integrity}")
            row = connection.execute(
                """
                SELECT parser_version, raw_fingerprint, row_counts, status
                FROM online_parse_metadata
                ORDER BY parsed_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None or str(row[0]) != PARSER_VERSION or str(row[1]) != fingerprint or str(row[3]).upper() != "OK":
                raise OnlineMrParsedDatabaseUpgradeError("临时解析数据库 metadata 校验失败")
            try:
                counts = json.loads(str(row[2] or "{}"))
            except json.JSONDecodeError as exc:
                raise OnlineMrParsedDatabaseUpgradeError("临时解析数据库 row_counts 无法读取") from exc
            count_checks = {
                "mesh_samples": "main_link_samples",
                "channel_samples": "channel_busy_records",
                "interface_samples": "interface_rate_samples",
                "ping_samples": "fping_samples",
                "active_segments": "active_segments",
            }
            for key, table in count_checks.items():
                expected = int(counts.get(key) or 0)
                actual = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                if expected > 0 and actual <= 0:
                    raise OnlineMrParsedDatabaseUpgradeError(f"临时解析数据库业务投影校验失败：{table}")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
        inspected = inspect_parsed_database(self.candidate_path)
        if not inspected.current or inspected.missing_capabilities:
            missing = ", ".join(sorted(inspected.missing_capabilities))
            raise OnlineMrParsedDatabaseUpgradeError(f"临时解析数据库 capability 校验失败：{missing}")
        summary_values = asdict(summary)
        projection_keys = {
            "mesh_samples",
            "channel_samples",
            "radio_stats_samples",
            "interface_samples",
            "ping_samples",
            "iperf_samples",
            "switch_history_samples",
            "active_link_switch_logs",
            "active_segments",
        }
        if not any(int(summary_values.get(key) or 0) > 0 for key in projection_keys):
            raise OnlineMrParsedDatabaseUpgradeError("临时解析数据库没有生成任何有效业务投影")

    def _publish_candidate(self) -> None:
        if not self.candidate_path.is_file():
            raise OnlineMrParsedDatabaseUpgradeError("临时解析数据库不存在")
        self.parsed_dir.mkdir(parents=True, exist_ok=True)
        if self.database_path.is_file():
            self.retired_dir.mkdir(parents=True, exist_ok=True)
            pending = self.rollback_path.with_suffix(self.rollback_path.suffix + ".pending")
            self._unlink_file(pending)
            self._cleanup_sqlite_sidecars(pending)
            shutil.copy2(self.database_path, pending)
            try:
                uri = f"{pending.resolve().as_uri()}?mode=ro&immutable=1"
                with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
                    if str(connection.execute("PRAGMA quick_check").fetchone()[0]).casefold() != "ok":
                        self._unlink_file(pending)
                        raise OnlineMrParsedDatabaseUpgradeError("旧解析数据库回滚副本校验失败")
                self._replace_with_retry(pending, self.rollback_path)
            finally:
                self._cleanup_sqlite_sidecars(pending)
            self._cleanup_sqlite_sidecars(self.database_path)
        self._replace_with_retry(self.candidate_path, self.database_path)
        self._cleanup_sqlite_sidecars(self.candidate_path)

    def _cleanup_candidate(self) -> None:
        self._unlink_file(self.candidate_path)
        self._cleanup_sqlite_sidecars(self.candidate_path)

    @staticmethod
    def _cleanup_sqlite_sidecars(path: Path) -> None:
        for suffix in ("-wal", "-shm"):
            OnlineMrParsedDatabaseUpgradeService._unlink_file(Path(str(path) + suffix))

    @staticmethod
    def _unlink_file(path: Path) -> None:
        for attempt in range(10):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if attempt == 9:
                    LOGGER.warning("online_mr_parser_upgrade cleanup_pending path=%s", path.name)
                    return
                time.sleep(0.1)

    @staticmethod
    def _replace_with_retry(source: Path, destination: Path) -> None:
        for attempt in range(10):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.1)

    def database_revision(self) -> str:
        stat = self.database_path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
