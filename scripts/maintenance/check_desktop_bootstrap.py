from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BootstrapInspection:
    bootstrap_path: Path
    value: dict[str, object]
    data_root: Path | None
    data_root_kind: str
    data_root_valid: bool
    active_site_valid: bool

    @property
    def valid(self) -> bool:
        return self.data_root_valid and self.active_site_valid


def inspect_bootstrap(bootstrap_path: Path, *, temp_root: Path | None = None) -> BootstrapInspection:
    value = _read_json(bootstrap_path)
    raw_root = value.get("data_root")
    data_root = Path(raw_root).expanduser().resolve() if isinstance(raw_root, str) and raw_root else None
    root_kind = _root_kind(data_root, temp_root or Path(tempfile.gettempdir()))
    root_valid = root_kind == "persistent" and bool(_site_directories(data_root))
    active = str(value.get("active_site_id") or "").strip()
    active_valid = bool(root_valid and _resolve_site_id(data_root, active))
    return BootstrapInspection(
        bootstrap_path=bootstrap_path,
        value=value,
        data_root=data_root,
        data_root_kind=root_kind,
        data_root_valid=bool(root_valid),
        active_site_valid=active_valid,
    )


def repair_bootstrap(
    inspection: BootstrapInspection,
    *,
    candidate_roots: Iterable[Path],
    site_id: str | None = None,
    dry_run: bool = False,
) -> tuple[Path, str, Path | None]:
    if inspection.valid:
        assert inspection.data_root is not None
        return inspection.data_root, str(inspection.value["active_site_id"]), None

    target = next((root.resolve() for root in candidate_roots if _site_directories(root.resolve())), None)
    if target is None:
        raise RuntimeError("未找到包含有效局点的持久化数据根，未修改 bootstrap")
    selected = _select_site(target, inspection.value.get("active_site_id"), site_id)
    backup = inspection.bootstrap_path.with_name(
        f"{inspection.bootstrap_path.name}.invalid-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    if dry_run:
        return target, selected, backup
    if inspection.bootstrap_path.is_file():
        backup = _unique_path(backup)
        shutil.copy2(inspection.bootstrap_path, backup)
    else:
        backup = None
    _atomic_json(
        inspection.bootstrap_path,
        {"schema_version": 1, "data_root": str(target), "active_site_id": selected},
    )
    return target, selected, backup


def _select_site(data_root: Path, original: object, requested: str | None) -> str:
    site_map = _site_map(data_root)
    if requested:
        selected = _mapped_site_id(site_map, requested)
        if selected:
            return selected
        raise RuntimeError("--site-id 指定的局点不存在，未修改 bootstrap")
    for candidate in (str(original or "").strip(), _configured_site(data_root)):
        if candidate and candidate in site_map:
            return candidate
        if candidate:
            match = _mapped_site_id(site_map, candidate)
            if match:
                return match
    directories = set(site_map.values())
    if len(directories) == 1:
        directory = next(iter(directories))
        return next((site_id for site_id, value in site_map.items() if value == directory and site_id != directory), directory)
    raise RuntimeError("持久化数据根包含多个局点且无法确定当前局点；请使用 --site-id 明确指定")


def _mapped_site_id(site_map: dict[str, str], value: str) -> str | None:
    if value in site_map:
        return value
    return next((site_id for site_id, directory in site_map.items() if directory == value), None)


def _site_map(data_root: Path) -> dict[str, str]:
    directories = _site_directories(data_root)
    mapping = {name: name for name in directories}
    registry = _read_json(data_root / "data" / "config" / "site_registry.json")
    entries = registry.get("sites")
    if not isinstance(entries, list):
        return mapping
    for item in entries:
        if not isinstance(item, dict):
            continue
        site_id = str(item.get("site_id") or "").strip()
        relative = str(item.get("relative_path") or "").replace("\\", "/").strip("/")
        directory = Path(relative).name if relative else site_id
        if site_id and directory in directories:
            mapping[site_id] = directory
    return mapping


def _configured_site(data_root: Path) -> str:
    value = _read_json(data_root / "data" / "config" / "app.json")
    current = value.get("current_site")
    return str(current).strip() if isinstance(current, str) else ""


def _resolve_site_id(data_root: Path, value: str) -> str | None:
    if not value:
        return None
    mapping = _site_map(data_root)
    if value in mapping:
        return value
    return next((site_id for site_id, directory in mapping.items() if directory == value), None)


def _site_directories(data_root: Path | None) -> set[str]:
    if data_root is None:
        return set()
    sites_root = data_root / "data" / "sites"
    if not sites_root.is_dir():
        return set()
    return {
        item.name
        for item in sites_root.iterdir()
        if item.is_dir() and (item / "db" / "devices.db").is_file()
    }


def _root_kind(data_root: Path | None, temp_root: Path) -> str:
    if data_root is None:
        return "missing"
    resolved = data_root.resolve()
    temporary = temp_root.resolve()
    if resolved == temporary or temporary in resolved.parents:
        return "temporary"
    if any(part.casefold().startswith("netconsole-codex-") for part in resolved.parts):
        return "temporary"
    return "persistent" if resolved.exists() else "missing"


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    return path.with_name(f"{path.name}-{uuid.uuid4().hex[:8]}")


def _default_paths() -> tuple[Path, list[Path]]:
    roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    development_bootstrap = roaming / "netconsole-desktop-electron" / "bootstrap.json"
    packaged_bootstrap = roaming / "NetConsole" / "bootstrap.json"
    bootstrap = development_bootstrap if development_bootstrap.exists() else packaged_bootstrap
    return bootstrap, [
        local / "NetConsole" / "Development",
        local / "NetConsole",
    ]


def main(argv: list[str] | None = None) -> int:
    default_bootstrap, default_roots = _default_paths()
    parser = argparse.ArgumentParser(description="只读检查并安全修复 Electron desktop bootstrap 引用")
    parser.add_argument("--repair", action="store_true", help="备份后原子修复无效引用")
    parser.add_argument("--dry-run", action="store_true", help="显示修复决策但不写文件")
    parser.add_argument("--site-id", help="多局点时明确指定已有局点 ID")
    parser.add_argument("--bootstrap", type=Path, default=default_bootstrap, help=argparse.SUPPRESS)
    parser.add_argument("--candidate-root", action="append", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--temp-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    inspection = inspect_bootstrap(args.bootstrap, temp_root=args.temp_root)
    print(f"bootstrap_status={'valid' if inspection.valid else 'invalid'}")
    print(f"data_root_kind={inspection.data_root_kind}")
    print(f"data_root_exists={str(bool(inspection.data_root and inspection.data_root.exists())).lower()}")
    print(f"active_site_exists={str(inspection.active_site_valid).lower()}")
    if not args.repair:
        print("action=read_only")
        return 0 if inspection.valid else 1
    try:
        target, selected, backup = repair_bootstrap(
            inspection,
            candidate_roots=args.candidate_root or default_roots,
            site_id=args.site_id,
            dry_run=args.dry_run,
        )
    except RuntimeError as exc:
        print(f"repair_status=refused reason={exc}")
        return 2
    print(f"repair_status={'dry_run' if args.dry_run else 'repaired'}")
    print(f"target_kind={_root_kind(target, args.temp_root or Path(tempfile.gettempdir()))}")
    print(f"active_site_exists={str(bool(_resolve_site_id(target, selected))).lower()}")
    print(f"backup_created={str(bool(backup and backup.exists())).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
