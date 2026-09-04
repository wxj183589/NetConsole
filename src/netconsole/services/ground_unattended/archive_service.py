from __future__ import annotations

import csv
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.schedule import resolve_timezone


@dataclass(frozen=True)
class ArchiveResult:
    archive_id: str
    success: bool
    message: str
    active_cleanup_pending: bool = False


class GroundUnattendedArchiveService:
    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundUnattendedRepository,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository

    def archive_run(
        self,
        run_id: str,
        profile: GroundUnattendedProfileDTO,
        progress_callback: (
            Callable[[str, int, str, dict[str, Any]], None] | None
        ) = None,
    ) -> ArchiveResult:
        run = self.repository.get_run(run_id)
        if run is None:
            raise ValueError("ground unattended run not found")
        run_date = str(run["run_date"])
        active_dir = self.paths.ground_unattended_active_dir(self.site_id, run_date)
        archive_dir = self.paths.ground_unattended_archives_dir(self.site_id)
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_id = f"archive_{run_id}"
        final_path = archive_dir / f"{run_date}_ground_unattended.zip"
        temp_path = final_path.with_name(f".{final_path.name}.{archive_id}.tmp")
        existing = self.repository.get_archive_by_run(run_id)
        if existing and existing.get("archive_status") == "READY":
            _progress(
                progress_callback,
                "ARCHIVE_VERIFYING",
                80,
                "正在校验已有正式归档",
                {"archive_id": str(existing["archive_id"])},
            )
            existing_path = self._archive_path(existing)
            try:
                self._validate_archive_path(existing_path)
                if not existing_path.is_file() or existing_path.is_symlink():
                    raise OSError("ready archive is not a regular file")
                self._verify_zip(existing_path)
                expected_sha = str(existing.get("sha256") or "")
                if expected_sha and _sha256(existing_path) != expected_sha:
                    raise OSError("ready archive checksum mismatch")
            except (
                OSError,
                ValueError,
                zipfile.BadZipFile,
                json.JSONDecodeError,
            ) as exc:
                if not active_dir.is_dir():
                    message = "正式归档校验失败且原始数据不存在，已保留现有文件"
                    self.repository.upsert_archive(
                        {
                            "archive_id": str(existing["archive_id"]),
                            "site_id": self.site_id,
                            "run_id": run_id,
                            "run_date": run_date,
                            "relative_path": str(existing.get("relative_path") or ""),
                            "archive_status": "FAILED",
                            "archive_size_bytes": int(
                                existing.get("archive_size_bytes") or 0
                            ),
                            "sha256": str(existing.get("sha256") or ""),
                            "manifest_sha256": str(
                                existing.get("manifest_sha256") or ""
                            ),
                            "retention_until": str(
                                existing.get("retention_until") or ""
                            ),
                            "active_cleanup_pending": 0,
                            "summary_json": json.dumps(
                                existing.get("summary") or {}, ensure_ascii=False
                            ),
                            "message": message,
                            "created_at": str(existing.get("created_at") or _now()),
                            "updated_at": _now(),
                        }
                    )
                    self.repository.add_event(
                        run_id=run_id,
                        event_type="archive_validation_failed",
                        severity="error",
                        title=message,
                        message=f"{exc.__class__.__name__}: {exc}",
                    )
                    return ArchiveResult(str(existing["archive_id"]), False, message)
            else:
                archive_reference = str(existing.get("relative_path") or "")
                self.repository.mark_raw_files_archived(run_id, archive_reference)
                raw_registration_complete = (
                    self.repository.count_unarchived_raw_files(run_id) == 0
                )
                cleanup_pending = bool(existing.get("active_cleanup_pending"))
                if not raw_registration_complete:
                    cleanup_pending = True
                elif active_dir.is_dir():
                    try:
                        self._safe_remove_active_dir(active_dir)
                        cleanup_pending = False
                    except OSError:
                        cleanup_pending = True
                if cleanup_pending != bool(existing.get("active_cleanup_pending")):
                    self.repository.upsert_archive(
                        {
                            "archive_id": str(existing["archive_id"]),
                            "site_id": self.site_id,
                            "run_id": run_id,
                            "run_date": run_date,
                            "relative_path": str(existing.get("relative_path") or ""),
                            "archive_status": "READY",
                            "archive_size_bytes": existing_path.stat().st_size,
                            "sha256": str(existing.get("sha256") or ""),
                            "manifest_sha256": str(
                                existing.get("manifest_sha256") or ""
                            ),
                            "retention_until": str(
                                existing.get("retention_until") or ""
                            ),
                            "active_cleanup_pending": int(cleanup_pending),
                            "summary_json": json.dumps(
                                existing.get("summary") or {}, ensure_ascii=False
                            ),
                            "message": "归档已存在并通过校验",
                            "created_at": str(existing.get("created_at") or _now()),
                            "updated_at": _now(),
                        }
                    )
                self.apply_retention(profile, protected_run_id=run_id)
                _progress(
                    progress_callback,
                    "ARCHIVE_READY",
                    98,
                    "已有正式归档校验完成",
                    {"archive_id": str(existing["archive_id"])},
                )
                return ArchiveResult(
                    str(existing["archive_id"]),
                    True,
                    "归档已存在并通过校验",
                    cleanup_pending,
                )
        now = _now()
        retention_until = (
            date.fromisoformat(run_date) + timedelta(days=profile.detail_retention_days)
        ).isoformat()
        summary = self._build_summary(run_id, run, profile)
        _progress(
            progress_callback,
            "ARCHIVE_PREPARING",
            60,
            "正在准备每日汇总和清单",
            {"archive_id": archive_id},
        )
        self.repository.upsert_archive(
            {
                "archive_id": archive_id,
                "site_id": self.site_id,
                "run_id": run_id,
                "run_date": run_date,
                "relative_path": final_path.relative_to(
                    self.paths.ground_unattended_root(self.site_id)
                ).as_posix(),
                "archive_status": "BUILDING",
                "archive_size_bytes": 0,
                "sha256": "",
                "manifest_sha256": "",
                "retention_until": retention_until,
                "active_cleanup_pending": 0,
                "summary_json": json.dumps(summary, ensure_ascii=False),
                "message": "正在生成每日无人值守归档",
                "created_at": now,
                "updated_at": now,
            }
        )
        try:
            active_dir.mkdir(parents=True, exist_ok=True)
            self._write_daily_artifacts(active_dir, run_id, summary)
            manifest = self._build_manifest(active_dir, run, summary)
            self._atomic_json(active_dir / "manifest.json", manifest)
            temp_path.unlink(missing_ok=True)
            _progress(
                progress_callback,
                "ARCHIVE_WRITING",
                70,
                "正在写入临时 ZIP",
                {"archive_id": archive_id, "archive_name": final_path.name},
            )
            self._write_zip(active_dir, temp_path)
            _progress(
                progress_callback,
                "ARCHIVE_VERIFYING",
                82,
                "正在校验 ZIP 完整性",
                {
                    "archive_id": archive_id,
                    "written_bytes": temp_path.stat().st_size,
                },
            )
            self._verify_zip(temp_path)
            os.replace(temp_path, final_path)
            archive_sha = _sha256(final_path)
            manifest_sha = _sha256(active_dir / "manifest.json")
            _progress(
                progress_callback,
                "ARCHIVE_REGISTERING",
                90,
                "正在登记正式归档",
                {
                    "archive_id": archive_id,
                    "archive_name": final_path.name,
                    "written_bytes": final_path.stat().st_size,
                },
            )
            self.repository.upsert_archive(
                {
                    "archive_id": archive_id,
                    "site_id": self.site_id,
                    "run_id": run_id,
                    "run_date": run_date,
                    "relative_path": final_path.relative_to(
                        self.paths.ground_unattended_root(self.site_id)
                    ).as_posix(),
                    "archive_status": "READY",
                    "archive_size_bytes": final_path.stat().st_size,
                    "sha256": archive_sha,
                    "manifest_sha256": manifest_sha,
                    "retention_until": retention_until,
                    "active_cleanup_pending": 1,
                    "summary_json": json.dumps(summary, ensure_ascii=False),
                    "message": "归档校验完成",
                    "created_at": now,
                    "updated_at": _now(),
                }
            )
            self.repository.mark_raw_files_archived(
                run_id,
                final_path.relative_to(
                    self.paths.ground_unattended_root(self.site_id)
                ).as_posix(),
            )
            cleanup_pending = self.repository.count_unarchived_raw_files(run_id) > 0
            _progress(
                progress_callback,
                "CLEANING_ARCHIVED_ACTIVE",
                95,
                "正在按安全策略清理已归档 active 数据",
                {"archive_id": archive_id},
            )
            if not cleanup_pending:
                try:
                    self._safe_remove_active_dir(active_dir)
                except OSError:
                    cleanup_pending = True
            self.repository.upsert_archive(
                {
                    "archive_id": archive_id,
                    "site_id": self.site_id,
                    "run_id": run_id,
                    "run_date": run_date,
                    "relative_path": final_path.relative_to(
                        self.paths.ground_unattended_root(self.site_id)
                    ).as_posix(),
                    "archive_status": "READY",
                    "archive_size_bytes": final_path.stat().st_size,
                    "sha256": archive_sha,
                    "manifest_sha256": manifest_sha,
                    "retention_until": retention_until,
                    "active_cleanup_pending": int(cleanup_pending),
                    "summary_json": json.dumps(summary, ensure_ascii=False),
                    "message": "归档完成，active 原始目录待清理"
                    if cleanup_pending
                    else "归档完成",
                    "created_at": now,
                    "updated_at": _now(),
                }
            )
            self.apply_retention(profile, protected_run_id=run_id)
            _progress(
                progress_callback,
                "ARCHIVE_READY",
                98,
                "正式归档已生成并通过校验",
                {
                    "archive_id": archive_id,
                    "archive_name": final_path.name,
                    "archive_size_bytes": final_path.stat().st_size,
                    "sha256": archive_sha,
                },
            )
            return ArchiveResult(archive_id, True, "归档完成", cleanup_pending)
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            message = "归档失败，原始数据仍保留"
            self.repository.upsert_archive(
                {
                    "archive_id": archive_id,
                    "site_id": self.site_id,
                    "run_id": run_id,
                    "run_date": run_date,
                    "relative_path": final_path.relative_to(
                        self.paths.ground_unattended_root(self.site_id)
                    ).as_posix(),
                    "archive_status": "FAILED",
                    "archive_size_bytes": final_path.stat().st_size
                    if final_path.is_file()
                    else 0,
                    "sha256": _sha256(final_path) if final_path.is_file() else "",
                    "manifest_sha256": "",
                    "retention_until": retention_until,
                    "active_cleanup_pending": 1,
                    "summary_json": json.dumps(summary, ensure_ascii=False),
                    "message": message,
                    "created_at": now,
                    "updated_at": _now(),
                }
            )
            self.repository.add_event(
                run_id=run_id,
                event_type="archive_failed",
                severity="error",
                title=message,
                message=f"{exc.__class__.__name__}: {exc}",
            )
            return ArchiveResult(archive_id, False, message, True)

    def delete_archive(self, archive_id: str) -> None:
        row = self.repository.get_archive(archive_id)
        if row is None:
            return
        active = self.repository.get_active_run()
        if active and active["run_id"] == row["run_id"]:
            raise ValueError("archive is in use")
        path = self._archive_path(row)
        self._validate_archive_path(path)
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise OSError("archive path is not a regular file")
            path.unlink()
        self.repository.purge_run_details(str(row["run_id"]))
        self.repository.delete_archive_record(archive_id)

    def apply_retention(
        self,
        profile: GroundUnattendedProfileDTO,
        *,
        protected_run_id: str | None = None,
    ) -> None:
        today_value = datetime.now(resolve_timezone(profile.timezone)).date()
        today = today_value.isoformat()
        for row in self.repository.list_archives():
            if (
                row.get("archive_status") != "READY"
                or str(row.get("retention_until") or "") >= today
                or (
                    protected_run_id is not None
                    and str(row.get("run_id") or "") == protected_run_id
                )
            ):
                continue
            self.delete_archive(str(row["archive_id"]))
        summary_cutoff = (
            today_value - timedelta(days=profile.summary_retention_days)
        ).isoformat()
        self.repository.delete_summaries_before(summary_cutoff)

    def _build_summary(
        self,
        run_id: str,
        run: dict[str, Any],
        profile: GroundUnattendedProfileDTO,
    ) -> dict[str, Any]:
        trains = self.repository.list_train_runs(run_id)
        deep = self.repository.list_deep_operations(run_id)
        ping = self.repository.list_ping_summaries(run_id)
        return {
            "site_id": self.site_id,
            "run_id": run_id,
            "run_date": run.get("run_date", ""),
            "actual_started_at": run.get("actual_started_at", ""),
            "actual_ended_at": run.get("actual_ended_at", ""),
            "mainline_train_count": sum(
                bool(row.get("mainline_eligible"))
                for row in trains
            ),
            "ping_target_count": len(
                {row.get("target_ip") for row in ping if row.get("target_ip")}
            ),
            "ping_sample_count": int(run.get("ping_sample_count") or 0),
            "covered_train_count": sum(
                row.get("coverage_status") == "COVERED" for row in trains
            ),
            "partial_train_count": sum(
                row.get("coverage_status") == "PARTIAL" for row in trains
            ),
            "complete_session_count": sum(
                row.get("state") == "COMPLETED" for row in deep
            ),
            "partial_session_count": sum(
                row.get("state") in {"PARTIAL", "FAILED"} for row in deep
            ),
            "running_mode": (
                "STANDARD"
                if profile.deep_collection_master_enabled
                else "LIGHTWEIGHT"
            ),
            "deep_collection_master_enabled": (
                profile.deep_collection_master_enabled
            ),
            "deep_collection_skipped_reason": (
                ""
                if profile.deep_collection_master_enabled
                else "局点配置为轻量监测模式"
            ),
            "generated_at": _now(),
        }

    def _write_daily_artifacts(
        self, active_dir: Path, run_id: str, summary: dict[str, Any]
    ) -> None:
        for directory in ("fleet_ping", "ac_snapshots", "timeline", "ping_summaries"):
            (active_dir / directory).mkdir(parents=True, exist_ok=True)
        self._atomic_json(active_dir / "daily_summary.json", summary)
        events = list(reversed(self.repository.list_events(run_id, limit=5000)))
        self._atomic_jsonl(active_dir / "scheduler_events.jsonl", events)
        self._atomic_jsonl(
            active_dir / "errors.jsonl",
            [row for row in events if row.get("severity") in {"warning", "error"}],
        )
        trains = self.repository.list_train_runs(run_id)
        coverage_path = active_dir / "coverage_summary.csv"
        temp_coverage = coverage_path.with_suffix(".csv.tmp")
        with temp_coverage.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "train_id",
                    "train_no",
                    "coverage_status",
                    "attempt_count",
                    "covered_rounds",
                    "eligibility_status",
                    "exclusion_reason",
                    "valid_duration_minutes",
                    "failure_reason",
                ],
            )
            writer.writeheader()
            for row in trains:
                writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_coverage, coverage_path)
        deep = self.repository.list_deep_operations(run_id)
        self._atomic_json(
            active_dir / "deep_collection_manifest.json",
            {
                "run_id": run_id,
                "sessions_embedded": False,
                "items": [
                    {
                        "train_id": row["train_id"],
                        "mr_id": row["mr_id"],
                        "mr_position_code": row["mr_position_code"],
                        "operation_id": row["operation_id"],
                        "session_id": row.get("session_id", ""),
                        "status": row["state"],
                        "package_verified": bool(row.get("package_verified")),
                        "error_summary": row.get("error_summary", ""),
                    }
                    for row in deep
                ],
            },
        )
        ping_rows = self.repository.list_ping_summaries(run_id, bucket_kind=None)
        self._atomic_jsonl(
            active_dir / "ping_summaries" / "all_summaries.jsonl", ping_rows
        )
        daily_by_mr = [
            row for row in ping_rows if str(row.get("bucket_kind") or "") == "daily"
        ]
        self._atomic_json(
            active_dir / "ping_summaries" / "daily_by_mr.json",
            {"run_id": run_id, "items": daily_by_mr},
        )
        self._atomic_json(
            active_dir / "ping_summaries" / "daily_by_train.json",
            {"run_id": run_id, "items": _aggregate_daily_ping_by_train(daily_by_mr)},
        )

    def _build_manifest(
        self, active_dir: Path, run: dict[str, Any], summary: dict[str, Any]
    ) -> dict[str, Any]:
        files = []
        for path in sorted(active_dir.rglob("*")):
            if (
                not path.is_file()
                or path.name.endswith(".tmp")
                or path.name == "manifest.json"
                or self._is_spool_path(path, active_dir)
            ):
                continue
            self._validate_active_member(path, active_dir)
            files.append(
                {
                    "path": path.relative_to(active_dir).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        return {
            "schema_version": 1,
            "archive_type": "ground_unattended_daily",
            "site_id": self.site_id,
            "run_id": run["run_id"],
            "run_date": run["run_date"],
            "generated_at": _now(),
            "deep_session_packages_embedded": False,
            "summary": summary,
            "files": files,
        }

    def _write_zip(self, active_dir: Path, target: Path) -> None:
        with zipfile.ZipFile(
            target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for path in sorted(active_dir.rglob("*")):
                if not path.is_dir() or self._is_spool_path(path, active_dir):
                    continue
                self._validate_active_member(path, active_dir)
                archive.writestr(f"{path.relative_to(active_dir).as_posix()}/", b"")
            for path in sorted(active_dir.rglob("*")):
                if (
                    not path.is_file()
                    or path.name.endswith(".tmp")
                    or self._is_spool_path(path, active_dir)
                ):
                    continue
                self._validate_active_member(path, active_dir)
                archive.write(path, path.relative_to(active_dir).as_posix())

    @staticmethod
    def _verify_zip(path: Path) -> None:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.testzip() is not None:
                raise OSError("archive CRC validation failed")
            names = set(archive.namelist())
            required = {
                "manifest.json",
                "daily_summary.json",
                "scheduler_events.jsonl",
                "coverage_summary.csv",
                "deep_collection_manifest.json",
                "errors.jsonl",
                "fleet_ping/",
                "ac_snapshots/",
                "timeline/",
                "ping_summaries/",
                "ping_summaries/all_summaries.jsonl",
                "ping_summaries/daily_by_mr.json",
                "ping_summaries/daily_by_train.json",
            }
            missing = required - names
            if missing:
                raise OSError(
                    f"archive required member is missing: {sorted(missing)[0]}"
                )
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            for item in manifest.get("files", []):
                name = str(item["path"])
                if name not in names:
                    raise OSError(f"archive member is missing: {name}")
                if _zip_member_sha256(archive, name) != item["sha256"]:
                    raise OSError(f"archive member checksum mismatch: {name}")

    def _safe_remove_active_dir(self, active_dir: Path) -> None:
        root = self.paths.ground_unattended_active_root(self.site_id).resolve()
        resolved = active_dir.resolve(strict=True)
        if resolved.parent != root or resolved == root:
            raise OSError("active cleanup target is outside the managed run directory")
        if self._has_pending_spool(resolved):
            raise OSError("active cleanup blocked while Syslog spool has pending data")
        self._remove_tree(resolved)

    @staticmethod
    def _is_spool_path(path: Path, active_dir: Path) -> bool:
        try:
            relative = path.relative_to(active_dir)
        except ValueError:
            return False
        return "_spool" in relative.parts

    @staticmethod
    def _has_pending_spool(active_dir: Path) -> bool:
        spool_dir = active_dir / "realtime" / "syslog" / "_spool"
        if not spool_dir.is_dir():
            return False
        try:
            for path in spool_dir.rglob("*"):
                if path.is_symlink():
                    return True
                if path.is_file() and path.stat().st_size > 0:
                    return True
        except OSError:
            return True
        return False

    def _remove_tree(self, root: Path) -> None:
        if root.is_symlink() or _is_junction(root):
            raise OSError("managed directory contains a link or junction")
        for entry in os.scandir(root):
            path = Path(entry.path)
            if entry.is_symlink() or _is_junction(path):
                raise OSError("managed directory contains a link or junction")
            if entry.is_dir(follow_symlinks=False):
                self._remove_tree(path)
            else:
                path.unlink()
        root.rmdir()

    def _archive_path(self, row: dict[str, Any]) -> Path:
        return (
            self.paths.ground_unattended_root(self.site_id)
            / str(row.get("relative_path") or "")
        ).resolve()

    def _validate_archive_path(self, path: Path) -> None:
        root = self.paths.ground_unattended_archives_dir(self.site_id).resolve()
        if path.parent != root or path.suffix.casefold() != ".zip":
            raise OSError("archive path is outside the managed archive directory")

    @staticmethod
    def _validate_active_member(path: Path, active_dir: Path) -> None:
        if path.is_symlink() or _is_junction(path):
            raise OSError("active data contains a link or junction")
        path.resolve().relative_to(active_dir.resolve())

    @staticmethod
    def _atomic_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    @staticmethod
    def _atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    try:
        return bool(checker()) if callable(checker) else False
    except OSError:
        return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(
    callback: Callable[[str, int, str, dict[str, Any]], None] | None,
    stage: str,
    percent: int,
    message: str,
    details: dict[str, Any],
) -> None:
    if callback is not None:
        callback(stage, percent, message, details)


def _zip_member_sha256(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate_daily_ping_by_train(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        train_id = str(row.get("train_id") or "")
        if not train_id:
            continue
        current = grouped.setdefault(
            train_id,
            {
                "train_id": train_id,
                "train_no": str(row.get("train_no") or ""),
                "sent_count": 0,
                "raw_sample_count": 0,
                "warmup_ignored_count": 0,
                "success_count": 0,
                "loss_count": 0,
                "rtt_weighted_sum": 0.0,
                "min_rtt_ms": None,
                "max_rtt_ms": None,
                "continuous_loss_max_count": 0,
                "continuous_loss_max_seconds": 0.0,
                "mr_ids": set(),
            },
        )
        sent = int(row.get("sent_count") or 0)
        raw = int(row.get("raw_sample_count") or sent)
        ignored = int(row.get("warmup_ignored_count") or 0)
        success = int(row.get("success_count") or 0)
        loss = int(row.get("loss_count") or 0)
        current["sent_count"] += sent
        current["raw_sample_count"] += raw
        current["warmup_ignored_count"] += ignored
        current["success_count"] += success
        current["loss_count"] += loss
        if row.get("avg_rtt_ms") is not None:
            current["rtt_weighted_sum"] += float(row["avg_rtt_ms"]) * success
        for field, reducer in (("min_rtt_ms", min), ("max_rtt_ms", max)):
            value = row.get(field)
            if value is not None:
                current[field] = (
                    float(value)
                    if current[field] is None
                    else reducer(float(current[field]), float(value))
                )
        current["continuous_loss_max_count"] = max(
            int(current["continuous_loss_max_count"]),
            int(row.get("continuous_loss_max_count") or 0),
        )
        current["continuous_loss_max_seconds"] = max(
            float(current["continuous_loss_max_seconds"]),
            float(row.get("continuous_loss_max_seconds") or 0),
        )
        if row.get("mr_id"):
            current["mr_ids"].add(str(row["mr_id"]))
    result = []
    for current in grouped.values():
        success = int(current.pop("success_count"))
        sent = int(current.pop("sent_count"))
        loss = int(current.pop("loss_count"))
        weighted = float(current.pop("rtt_weighted_sum"))
        mr_ids = sorted(current.pop("mr_ids"))
        result.append(
            {
                **current,
                "mr_ids": mr_ids,
                "sent_count": sent,
                "success_count": success,
                "loss_count": loss,
                "loss_rate_percent": round(loss * 100 / sent, 4) if sent else 0.0,
                "avg_rtt_ms": round(weighted / success, 4) if success else None,
            }
        )
    return sorted(result, key=lambda item: (item["train_no"], item["train_id"]))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


__all__ = ["ArchiveResult", "GroundUnattendedArchiveService"]
