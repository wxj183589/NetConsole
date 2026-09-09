from __future__ import annotations

import json
import os
import tempfile
from threading import RLock
from typing import Any

from netconsole.core.paths import PathResolver


class TaskAuthorityIndex:
    """Persist the site authority of operational tasks across site switches.

    ``tasks.db`` remains the task data authority.  This file is only a small
    routing index, so a query can find the owning per-site database after a
    restart without scanning every site database.  A task id can be present in
    more than one site database in compatibility fixtures; implicit resolution
    then returns ``None`` and callers must provide the explicit site.
    """

    _lock = RLock()
    _SCHEMA_VERSION = 2

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def resolve(self, task_id: str) -> str | None:
        authorities = self._authorities(str(task_id or ""))
        sites = {str(item.get("site_name") or "").strip() for item in authorities}
        sites.discard("")
        return next(iter(sites)) if len(sites) == 1 else None

    def bind(self, *, task_id: str, site_name: str, task_type: str) -> None:
        task_id = str(task_id or "").strip()
        site_name = str(site_name or "").strip()
        task_type = str(task_type or "").strip()
        if not task_id or not site_name or not task_type:
            return
        with self._lock:
            values = self._load()
            authorities = self._authorities_from_values(values, task_id)
            replacement = {"site_name": site_name, "task_type": task_type}
            for index, item in enumerate(authorities):
                if str(item.get("site_name") or "").strip() == site_name:
                    authorities[index] = replacement
                    break
            else:
                authorities.append(replacement)
            values[task_id] = authorities
            self._save(values)

    def remove(self, task_ids: list[str], *, site_name: str | None = None) -> None:
        ids = {str(value or "").strip() for value in task_ids if str(value or "").strip()}
        selected_site = str(site_name or "").strip()
        if not ids:
            return
        with self._lock:
            values = self._load()
            changed = False
            for task_id in ids:
                authorities = self._authorities_from_values(values, task_id)
                if not authorities:
                    continue
                if selected_site:
                    remaining = [
                        item
                        for item in authorities
                        if str(item.get("site_name") or "").strip() != selected_site
                    ]
                else:
                    remaining = []
                if remaining:
                    values[task_id] = remaining
                else:
                    values.pop(task_id, None)
                changed = True
            if changed:
                self._save(values)

    def sites(self) -> set[str]:
        sites: set[str] = set()
        for authorities in self._load().values():
            if not isinstance(authorities, list):
                continue
            for item in authorities:
                if isinstance(item, dict):
                    site_name = str(item.get("site_name") or "").strip()
                    if site_name:
                        sites.add(site_name)
        return sites

    def _authorities(self, task_id: str) -> list[dict[str, Any]]:
        return self._authorities_from_values(self._load(), str(task_id or "").strip())

    @staticmethod
    def _authorities_from_values(
        values: dict[str, Any], task_id: str
    ) -> list[dict[str, Any]]:
        raw = values.get(task_id)
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)]
        # Read the v1 index written by the previous multisite fix.  The next
        # bind upgrades just that task entry to the v2 representation.
        if isinstance(raw, dict):
            return [dict(raw)]
        return []

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(
                self.paths.task_authority_index_path.read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        version = payload.get("schema_version")
        if version not in {1, self._SCHEMA_VERSION}:
            return {}
        values = payload.get("tasks")
        return dict(values) if isinstance(values, dict) else {}

    def _save(self, values: dict[str, Any]) -> None:
        target = self.paths.task_authority_index_path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_tmp = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {
                        "schema_version": self._SCHEMA_VERSION,
                        "tasks": values,
                    },
                    handle,
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(raw_tmp, target)
        finally:
            try:
                os.unlink(raw_tmp)
            except FileNotFoundError:
                pass


__all__ = ["TaskAuthorityIndex"]
