"""Read-only integrity audit for task current state and related authorities."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.repositories.history_store import verify_task_result_row
from netconsole.repositories.task_result_blob_repository import (
    TaskResultBlobError,
    verify_task_result_authority,
)


DEFAULT_DEV_ROOT = Path(r"D:\NetConsoleData-dev")
PRODUCTION_ROOT = Path(r"D:\NetConsoleData")


def _quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _open(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    }


def _ground_references(paths: PathResolver, site: str, task_ids: set[str]) -> list[dict[str, object]]:
    path = paths.ground_unattended_db_path(site)
    if not path.is_file():
        return []
    refs: list[dict[str, object]] = []
    try:
        with _open(path) as conn:
            for table in sorted(_tables(conn)):
                columns = _columns(conn, table)
                for column in sorted(columns & {"task_id", "controller_task_id"}):
                    for start in range(0, len(task_ids), 500):
                        chunk = sorted(task_ids)[start : start + 500]
                        if not chunk:
                            continue
                        placeholders = ",".join("?" for _ in chunk)
                        rows = conn.execute(
                            f"SELECT {_quote(column)} AS task_id FROM {_quote(table)} "
                            f"WHERE {_quote(column)} IN ({placeholders})",
                            chunk,
                        ).fetchall()
                        for row in rows:
                            refs.append({"table": table, "column": column, "task_id": str(row["task_id"])})
    except (OSError, sqlite3.DatabaseError) as exc:
        return [{"error": "GROUND_DB_UNREADABLE", "message": str(exc)}]
    return refs


def audit_database(site: str, db_path: Path, *, data_root: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "site": site,
        "db_path": str(db_path),
        "status": "PASS",
        "task_count": 0,
        "event_count": 0,
        "snapshot_count": 0,
        "result_count": 0,
        "blob_count": 0,
        "rollout_state": "LEGACY_UNTRACKED",
        "authority_schema_ready": False,
        "task_result_parent_orphans": 0,
        "task_blob_orphans": 0,
        "missing_blob": 0,
        "hash_mismatch": 0,
        "issues": [],
        "orphan_result_ids": [],
        "orphan_blob_hashes": [],
        "online_mr_orphan_task_ids": [],
        "ground_references": [],
        "artifact_manifest_orphans": [],
        "counts": {},
    }
    if not db_path.is_file():
        result["status"] = "MISSING"
        return result

    issues: list[dict[str, object]] = []
    with _open(db_path) as conn:
        tables = _tables(conn)
        result_columns = _columns(conn, "task_results") if "task_results" in tables else set()
        blob_columns = _columns(conn, "task_result_blobs") if "task_result_blobs" in tables else set()
        if "task_result_storage_rollout" in tables:
            rollout = conn.execute(
                "SELECT state FROM task_result_storage_rollout WHERE singleton_id=1"
            ).fetchone()
            result["rollout_state"] = (
                str(rollout[0] or "LEGACY_UNTRACKED")
                if rollout is not None
                else "LEGACY_UNTRACKED"
            )
        result["authority_schema_ready"] = bool(
            {"content_sha256", "blob_codec", "blob_ready"} <= result_columns
            and {
                "content_sha256", "codec", "compressed_blob", "uncompressed_bytes",
                "compressed_bytes", "created_time", "verified_at",
            } <= blob_columns
        )
        if result["rollout_state"] == "RESULT_REF_AUTHORITY" and not result["authority_schema_ready"]:
            issues.append({"code": "ROLLOUT_PHYSICAL_SCHEMA_MISMATCH"})
        task_ids: set[str] = set()
        if "task_snapshots" in tables:
            task_ids = {
                str(row["task_id"])
                for row in conn.execute("SELECT task_id FROM task_snapshots")
            }
            result["snapshot_count"] = len(task_ids)
            result["task_count"] = len(task_ids)
        if "task_events" in tables:
            result["event_count"] = int(
                conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
            )
            for row in conn.execute(
                "SELECT task_id, event_id, payload_json FROM task_events"
            ):
                try:
                    payload = json.loads(str(row["payload_json"] or "{}"))
                except json.JSONDecodeError:
                    issues.append({"code": "EVENT_JSON_INVALID", "event_id": row["event_id"]})
                    continue
                if not isinstance(payload, dict):
                    continue
                result_id = str(payload.get("result_id") or "")
                if result_id and str(row["task_id"]) not in task_ids:
                    issues.append({"code": "EVENT_TASK_MISSING", "event_id": row["event_id"]})

        result_rows: dict[str, dict[str, object]] = {}
        if "task_results" in tables:
            rows = conn.execute("SELECT * FROM task_results").fetchall()
            result["result_count"] = len(rows)
            for raw in rows:
                row = dict(raw)
                result_id = str(row.get("result_id") or "")
                if not result_id:
                    issues.append({"code": "RESULT_ID_EMPTY"})
                    continue
                if str(row.get("task_id") or "") not in task_ids:
                    result["task_result_parent_orphans"] += 1
                    result["orphan_result_ids"].append(result_id)
                try:
                    ready = int(row.get("blob_ready") or 0)
                    if ready:
                        verified = verify_task_result_authority(conn, row)
                    else:
                        if result["rollout_state"] == "RESULT_REF_AUTHORITY":
                            result["missing_blob"] += 1
                            issues.append({"code": "RESULT_BLOB_NOT_READY", "result_id": result_id})
                        verified = verify_task_result_row(row)
                    result_rows[result_id] = {
                        "result_id": result_id,
                        "task_id": verified.get("task_id"),
                        "terminal_event_type": verified.get("terminal_event_type"),
                        "sha256": verified.get("sha256"),
                        "byte_size": verified.get("byte_size"),
                    }
                    if str(verified.get("task_id") or "") not in task_ids:
                        issues.append({"code": "RESULT_TASK_MISSING", "result_id": result_id})
                except (sqlite3.DatabaseError, TaskResultBlobError) as exc:
                    if int(row.get("blob_ready") or 0):
                        result["hash_mismatch"] += 1
                    issues.append({"code": "RESULT_AUTHORITY_INVALID", "result_id": result_id, "message": str(exc)})
        result["blob_count"] = (
            int(conn.execute("SELECT COUNT(*) FROM task_result_blobs").fetchone()[0])
            if "task_result_blobs" in tables
            else 0
        )

        if "task_snapshots" in tables and "result_id" in _columns(conn, "task_snapshots"):
            for row in conn.execute(
                "SELECT task_id, result_id, result_hash FROM task_snapshots "
                "WHERE result_id IS NOT NULL AND result_id <> ''"
            ):
                result_id = str(row["result_id"])
                authority = result_rows.get(result_id)
                if authority is None:
                    issues.append({"code": "SNAPSHOT_RESULT_MISSING", "task_id": row["task_id"], "result_id": result_id})
                    continue
                if str(authority.get("task_id") or "") != str(row["task_id"]):
                    issues.append({"code": "SNAPSHOT_RESULT_TASK_MISMATCH", "task_id": row["task_id"], "result_id": result_id})
                if str(row["result_hash"] or "") not in {"", str(authority.get("sha256") or "")}:
                    issues.append({"code": "SNAPSHOT_RESULT_HASH_MISMATCH", "task_id": row["task_id"], "result_id": result_id})
        if "task_events" in tables:
            for row in conn.execute(
                "SELECT task_id, event_id, payload_json FROM task_events"
            ):
                try:
                    payload = json.loads(str(row["payload_json"] or "{}"))
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and payload.get("result_id"):
                    result_id = str(payload["result_id"])
                    if result_id not in result_rows:
                        issues.append({"code": "EVENT_RESULT_MISSING", "event_id": row["event_id"], "result_id": result_id})

        if "task_result_blobs" in tables:
            for row in conn.execute(
                "SELECT content_sha256 FROM task_result_blobs"
            ):
                digest = str(row["content_sha256"] or "")
                if not conn.execute(
                    "SELECT 1 FROM task_results WHERE blob_ready=1 AND content_sha256=? LIMIT 1",
                    (digest,),
                ).fetchone():
                    result["orphan_blob_hashes"].append(digest)
            result["task_blob_orphans"] = len(result["orphan_blob_hashes"])

        if "online_mr_task_sessions" in tables:
            columns = _columns(conn, "online_mr_task_sessions")
            task_column = "controller_task_id" if "controller_task_id" in columns else "task_id" if "task_id" in columns else ""
            if task_column:
                for row in conn.execute(
                    f"SELECT {_quote(task_column)} AS task_id FROM online_mr_task_sessions"
                ):
                    task_id = str(row["task_id"] or "")
                    if task_id and task_id not in task_ids:
                        result["online_mr_orphan_task_ids"].append(task_id)

    resolver = PathResolver(app_root=data_root, data_root=data_root)
    result["ground_references"] = _ground_references(resolver, site, task_ids)
    manifest_root = resolver.rail_transit_root(site) / "web_artifacts" / "manifests"
    if manifest_root.is_dir():
        for path in sorted(manifest_root.glob("*.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(manifest, dict):
                task_id = str(manifest.get("task_id") or "")
                if task_id and task_id not in task_ids:
                    result["artifact_manifest_orphans"].append({"path": str(path), "task_id": task_id})

    counts = Counter(str(item.get("code") or "UNKNOWN") for item in issues)
    result["issues"] = issues
    result["counts"] = dict(sorted(counts.items()))
    if (
        issues
        or result["orphan_blob_hashes"]
        or result["online_mr_orphan_task_ids"]
        or result["task_result_parent_orphans"]
        or result["task_blob_orphans"]
        or result["missing_blob"]
        or result["hash_mismatch"]
    ):
        result["status"] = "FAIL"
    return result


def _markdown(reports: list[dict[str, object]]) -> str:
    lines = [
        "# TASKS_DB 存储完整性审计",
        "",
        "> 只读审计；未执行迁移、清理、VACUUM、checkpoint 或文件删除。",
        "",
        "| Site | tasks.db | Tasks | Events | Results | Blobs | Issues | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in reports:
        lines.append(
            "| {site} | `{db_path}` | {task_count} | {event_count} | {result_count} | {blob_count} | {issue_count} | {status} |".format(
                issue_count=len(item.get("issues") or []), **item
            )
        )
    lines.extend(["", "## 发现", ""])
    for item in reports:
        for issue in item.get("issues") or []:
            lines.append(f"- `{item['site']}` `{issue.get('code', 'UNKNOWN')}`: {issue}")
        for digest in item.get("orphan_blob_hashes") or []:
            lines.append(f"- `{item['site']}` 孤立 result blob: `{digest}`")
        for task_id in item.get("online_mr_orphan_task_ids") or []:
            lines.append(f"- `{item['site']}` Online MR mapping 缺少 Task Snapshot: `{task_id}`")
    if not any(item.get("issues") or item.get("orphan_blob_hashes") or item.get("online_mr_orphan_task_ids") for item in reports):
        lines.append("- 未发现当前任务数据、结果 authority、Blob、Online MR 映射之间的不一致。")
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读审计 tasks.db 关联完整性")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DEV_ROOT)
    parser.add_argument("--site")
    parser.add_argument("--all-sites", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(r"D:\study\diagnostic\NetConsole\tasks-db-space-audit"))
    return parser


def _registered_task_databases(root: Path) -> dict[str, Path]:
    registry_path = root / "config" / "site_registry.json"
    try:
        value = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"局点 Registry 不可读，拒绝扫描未登记目录: {registry_path}"
        ) from exc
    raw_sites = value.get("sites") if isinstance(value, dict) else None
    if not isinstance(raw_sites, list):
        raise SystemExit("局点 Registry 缺少 sites，拒绝扫描未登记目录")
    sites_root = (root / "sites").resolve()
    result: dict[str, Path] = {}
    for item in raw_sites:
        if not isinstance(item, dict):
            continue
        site_id = str(item.get("site_id") or "").strip().casefold()
        relative = Path(str(item.get("relative_path") or f"sites/{site_id}"))
        raw_root = root / relative
        site_root = raw_root.resolve()
        if (
            not site_id
            or relative.is_absolute()
            or ".." in relative.parts
            or raw_root.is_symlink()
            or site_root.parent != sites_root
            or not site_root.is_dir()
        ):
            raise SystemExit(f"局点 Registry 路径无效，拒绝扫描: {site_id or '<empty>'}")
        if site_id in result:
            raise SystemExit(f"局点 Registry 存在重复 site_id: {site_id}")
        task_db = site_root / "db" / "tasks.db"
        if task_db.is_file() and not task_db.is_symlink():
            result[site_id] = task_db
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.data_root.resolve()
    if root == PRODUCTION_ROOT.resolve():
        raise SystemExit("禁止审计生产数据根 D:\\NetConsoleData")
    if bool(args.site) == bool(args.all_sites):
        raise SystemExit("必须指定 --site 或 --all-sites（二选一）")
    registered = _registered_task_databases(root)
    if args.site:
        wanted = str(args.site).strip().casefold()
        if wanted not in registered:
            raise SystemExit(f"site 未登记或缺少 tasks.db，拒绝扫描: {args.site}")
        sites = [wanted]
    else:
        sites = sorted(registered)
    reports = [
        audit_database(site, registered[site], data_root=root)
        for site in sites
    ]
    payload = {
        "schema": "task-storage-integrity-audit/v1",
        "data_root": str(root),
        "reports": reports,
        "status": "PASS" if all(item["status"] in {"PASS", "MISSING"} for item in reports) else "FAIL",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "TASK_STORAGE_INTEGRITY_AUDIT.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "TASK_STORAGE_INTEGRITY_AUDIT.md").write_text(
        _markdown(reports), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
