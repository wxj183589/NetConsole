from __future__ import annotations

import csv
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)


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
        now = _now()
        retention_until = (
            date.fromisoformat(run_date) + timedelta(days=profile.detail_retention_days)
        ).isoformat()
        summary = self._build_summary(run_id, run)
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
            self._write_zip(active_dir, temp_path)
            self._verify_zip(temp_path)
            os.replace(temp_path, final_path)
            archive_sha = _sha256(final_path)
            manifest_sha = _sha256(active_dir / "manifest.json")
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
            cleanup_pending = False
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
            self.apply_retention(profile)
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

    def apply_retention(self, profile: GroundUnattendedProfileDTO) -> None:
        today = date.today().isoformat()
        for row in self.repository.list_archives():
            if (
                row.get("archive_status") != "READY"
                or str(row.get("retention_until") or "") >= today
            ):
                continue
            self.delete_archive(str(row["archive_id"]))
        summary_cutoff = (
            date.today() - timedelta(days=profile.summary_retention_days)
        ).isoformat()
        self.repository.delete_summaries_before(summary_cutoff)

    def _build_summary(self, run_id: str, run: dict[str, Any]) -> dict[str, Any]:
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
                row.get("eligibility_status") in {"MAINLINE", "MAINLINE_STATIONARY"}
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
            "generated_at": _now(),
        }

    def _write_daily_artifacts(
        self, active_dir: Path, run_id: str, summary: dict[str, Any]
    ) -> None:
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

    def _build_manifest(
        self, active_dir: Path, run: dict[str, Any], summary: dict[str, Any]
    ) -> dict[str, Any]:
        files = []
        for path in sorted(active_dir.rglob("*")):
            if (
                not path.is_file()
                or path.name.endswith(".tmp")
                or path.name == "manifest.json"
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
                if not path.is_file() or path.name.endswith(".tmp"):
                    continue
                self._validate_active_member(path, active_dir)
                archive.write(path, path.relative_to(active_dir).as_posix())

    @staticmethod
    def _verify_zip(path: Path) -> None:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.testzip() is not None:
                raise OSError("archive CRC validation failed")
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise OSError("archive manifest is missing")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            for item in manifest.get("files", []):
                name = str(item["path"])
                if name not in names:
                    raise OSError(f"archive member is missing: {name}")
                if hashlib.sha256(archive.read(name)).hexdigest() != item["sha256"]:
                    raise OSError(f"archive member checksum mismatch: {name}")

    def _safe_remove_active_dir(self, active_dir: Path) -> None:
        root = self.paths.ground_unattended_active_root(self.site_id).resolve()
        resolved = active_dir.resolve(strict=True)
        if resolved.parent != root or resolved == root:
            raise OSError("active cleanup target is outside the managed run directory")
        self._remove_tree(resolved)

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


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


__all__ = ["ArchiveResult", "GroundUnattendedArchiveService"]
