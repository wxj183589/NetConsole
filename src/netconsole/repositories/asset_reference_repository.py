"""Bounded, read-only evidence probes. A negative probe never proves safe deletion."""

from contextlib import closing
from pathlib import Path
import json
import os
import time
from netconsole.core.database import Database


class AssetReferenceRepository:
    def __init__(self, paths):
        self.paths = paths

    def _check_path(self, path):
        root = self.paths.data_root.absolute()
        path = path.absolute()
        if not path.is_relative_to(root):
            raise ValueError("reference path outside data root")
        for part in (path, *path.parents):
            if part == root.parent:
                break
            if part.is_symlink() or (
                part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("reference path is a reparse point")
        return path

    def identity(self, site_id):
        path = self._check_path(self.paths.site_db_path(site_id))
        if not path.is_file():
            raise FileNotFoundError("site database missing")
        with closing(Database(path).connect_readonly()) as conn:
            return conn.execute("SELECT 1").fetchone()[0]

    def device(self, site_id, device_uuid):
        path = self._check_path(self.paths.site_db_path(site_id))
        with closing(Database(path).connect_readonly()) as conn:
            row = conn.execute(
                "SELECT id,device_uuid,name,mac_address,work_scope_status FROM devices WHERE device_uuid=?",
                (device_uuid,),
            ).fetchone()
            return dict(row) if row else None

    def sql_references(self, path, device, deadline):
        path = self._check_path(path)
        if not path.is_file():
            return dict(
                status="NOT_VERIFIED",
                matches=[],
                reason="source absent; absence is not a retention proof",
            )
        result = []
        with closing(Database(path).connect_readonly()) as conn:
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            conn.execute("PRAGMA busy_timeout=100")
            conn.execute("BEGIN")
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in tables:
                if time.monotonic() >= deadline:
                    raise TimeoutError("reference deadline")
                if table == "devices":
                    continue
                quoted = '"' + table.replace('"', '""') + '"'
                columns = {r[1] for r in conn.execute(f"PRAGMA table_info({quoted})")}
                predicates, args = [], []
                for column in sorted(
                    columns
                    & {
                        "device_uuid",
                        "ac_device_uuid",
                        "mr_device_uuid",
                        "mr_device_id",
                        "device_id",
                        "source_uid",
                        "target_uid",
                    }
                ):
                    predicates.append('"' + column + '" IN (?,?)')
                    args.extend(
                        [
                            device["device_uuid"],
                            str(device["id"])
                            if column in {"device_id", "mr_device_id"}
                            else device["device_uuid"],
                        ]
                    )
                if not predicates:
                    continue
                count = conn.execute(
                    f"SELECT count(*) FROM {quoted} WHERE " + " OR ".join(predicates),
                    args,
                ).fetchone()[0]
                if count:
                    result.append(
                        dict(table=table, count=count, match="exact identity column")
                    )
        return dict(
            status="VERIFIED",
            matches=result,
            reason="only enumerated exact ID columns in this SQLite snapshot; JSON/MAC/name joins not proven complete",
        )

    def session_references(self, site_id, device, deadline):
        root = self._check_path(self.paths.online_mr_root(site_id))
        matches, files = [], 0
        if not root.exists():
            return dict(status="NOT_VERIFIED", matches=[], reason="session root absent")
        stack = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            self._check_path(directory)
            with os.scandir(directory) as entries:
                for entry in entries:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("session index deadline")
                    if (
                        entry.is_symlink()
                        or getattr(
                            entry.stat(follow_symlinks=False), "st_file_attributes", 0
                        )
                        & 0x400
                    ):
                        raise ValueError("session index reparse point")
                    if entry.is_dir(follow_symlinks=False) and depth < 3:
                        stack.append((Path(entry.path), depth + 1))
                    elif entry.name == "session_meta.json":
                        files += 1
                        if files > 500 or entry.stat().st_size > 65536:
                            raise ValueError("session index read budget")
                        data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
                        if not isinstance(data, dict):
                            raise ValueError("session metadata must be an object")
                        if any(
                            str(data.get(k, ""))
                            in {device["device_uuid"], str(device["id"])}
                            for k in ("device_uuid", "device_id", "mr_device_id")
                        ):
                            matches.append(
                                dict(
                                    session_id=str(data.get("session_id", "")), count=1
                                )
                            )
        return dict(
            status="NOT_VERIFIED",
            matches=matches,
            reason="bounded metadata only; archived packages, old names, reports and raw evidence require retention audit",
        )
