from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.models.omnipeek_name_table import (
    DEFAULT_OMNIPEEK_COLORS,
    ENTRY_KIND_GROUP_SUFFIX,
    ENTRY_KIND_LABELS,
    ENTRY_KIND_NAME_SUFFIX,
    OMNIPEEK_ENTRY_KIND_ORDER,
    SOURCE_AC_FIT_AP,
    SOURCE_AP_EXTENSION,
    SOURCE_DEVICE_MANAGEMENT,
    OmniPeekDeviceItem,
    OmniPeekEntryKind,
    OmniPeekExportConfig,
    OmniPeekExportResult,
    OmniPeekNameEntry,
)
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.utils.mac_utils import H3cMacDeriveError, MacAddressError, derive_h3c_r1_mac, derive_h3c_r2_mac, normalize_mac


OMNIPEEK_COLOR_SETTINGS_KEY = "omnipeek/colors"
OMNIPEEK_LAST_EXPORT_DIR_KEY = "omnipeek/last_export_dir"
ONBOARD_MR_RADIO_MODES = ("auto", "r1_only", "r2_only", "r1_r2", "none")


class OmniPeekNameTableService:
    def __init__(self, ac_repository: AcRepository, device_repository: DeviceRepository | None = None) -> None:
        self.ac_repository = ac_repository
        self.device_repository = device_repository

    def source_counts(
        self,
        *,
        ac_device_uuid: str | None = None,
        devices: Iterable[Device] | None = None,
        selected_fit_ap_ids: Iterable[str] | None = None,
        scope_extensions_to_fit_ap: bool = False,
    ) -> dict[str, int]:
        selected = {str(value) for value in selected_fit_ap_ids or [] if str(value)}
        fit_ap_rows = self._fit_ap_rows(ac_device_uuid)
        fit_ap_count = sum(1 for row in fit_ap_rows if not selected or str(row.get("ap_uuid") or "") in selected)
        extension_count = len(self.ac_repository.list_ap_extension_points())
        if scope_extensions_to_fit_ap and ac_device_uuid:
            extension_count = sum(
                1
                for item in self.collect_items(
                    include_ac_fit_ap=True,
                    include_ap_extensions=True,
                    include_device_mr=False,
                    ac_device_uuid=ac_device_uuid,
                    selected_fit_ap_ids=selected_fit_ap_ids,
                    scope_extensions_to_fit_ap=True,
                )
                if SOURCE_AP_EXTENSION in (item.sources or [item.source])
            )
        device_count = 0
        if devices is not None:
            device_count = len(list(devices))
        elif self.device_repository is not None:
            device_count = len(self.device_repository.list())
        return {
            SOURCE_AC_FIT_AP: fit_ap_count,
            SOURCE_AP_EXTENSION: extension_count,
            SOURCE_DEVICE_MANAGEMENT: device_count,
        }

    def collect_items(
        self,
        *,
        include_ac_fit_ap: bool = True,
        include_ap_extensions: bool = True,
        include_device_mr: bool = True,
        ac_device_uuid: str | None = None,
        devices: Iterable[Device] | None = None,
        group_names: dict[int, str] | None = None,
        selected_fit_ap_ids: Iterable[str] | None = None,
        scope_extensions_to_fit_ap: bool = False,
    ) -> list[OmniPeekDeviceItem]:
        items: list[OmniPeekDeviceItem] = []
        if include_ap_extensions:
            items.extend(collect_trackside_ap_items_from_extensions(self.ac_repository.list_ap_extension_points()))
        if include_ac_fit_ap:
            items.extend(collect_trackside_ap_items(self._fit_ap_rows(ac_device_uuid)))
        if include_device_mr:
            if devices is None and self.device_repository is not None:
                devices = self.device_repository.list()
            items.extend(collect_onboard_mr_items(list(devices or []), group_names=group_names or {}))
        prepared = prepare_omnipeek_items(merge_omnipeek_items(items))
        if scope_extensions_to_fit_ap and ac_device_uuid:
            prepared = [item for item in prepared if str(item.raw.get("ap_uuid") or "")]
        selected = {str(value) for value in selected_fit_ap_ids or [] if str(value)}
        if selected:
            prepared = [item for item in prepared if str(item.raw.get("ap_uuid") or "") in selected]
        return prepared

    def _fit_ap_rows(self, ac_device_uuid: str | None) -> list[dict[str, object | None]]:
        if ac_device_uuid:
            return self.ac_repository.list_fit_ap_resources_with_metadata(ac_device_uuid)
        return self.ac_repository.list_all_fit_ap_resources_with_metadata()


def collect_trackside_ap_items(rows: Iterable[dict[str, object | None]]) -> list[OmniPeekDeviceItem]:
    items: list[OmniPeekDeviceItem] = []
    for row in rows:
        name = _first_text(row, "ap_name", "name")
        physical_mac = _first_text(row, "ap_mac", "mac", "ap_mac_display", "ap_mac_norm")
        if not name and physical_mac:
            name = physical_mac
        if not name:
            continue
        item = OmniPeekDeviceItem(
            role="trackside_ap",
            name=name,
            physical_mac=physical_mac,
            location=_trackside_location(row),
            source=SOURCE_AC_FIT_AP,
            sources=[SOURCE_AC_FIT_AP],
            raw=dict(row),
        )
        item.key = _item_key(item)
        items.append(item)
    return items


def collect_trackside_ap_items_from_extensions(rows: Iterable[dict[str, object | None]]) -> list[OmniPeekDeviceItem]:
    items: list[OmniPeekDeviceItem] = []
    for row in rows:
        name = _first_text(row, "ap_name", "ap_point_code")
        physical_mac = _first_text(row, "ap_mac_display", "ap_mac_norm", "ap_mac")
        if not name and physical_mac:
            name = physical_mac
        if not name:
            continue
        item = OmniPeekDeviceItem(
            role="trackside_ap",
            name=name,
            physical_mac=physical_mac,
            location=_trackside_location(row),
            source=SOURCE_AP_EXTENSION,
            sources=[SOURCE_AP_EXTENSION],
            raw=dict(row),
        )
        item.key = _item_key(item)
        items.append(item)
    return items


def collect_onboard_mr_items(devices: Iterable[Device], *, group_names: dict[int, str] | None = None) -> list[OmniPeekDeviceItem]:
    group_names = group_names or {}
    items: list[OmniPeekDeviceItem] = []
    for device in devices:
        group_name = group_names.get(int(device.group_id or 0), "")
        if not _looks_like_onboard_mr(device, group_name):
            continue
        item = OmniPeekDeviceItem(
            role="onboard_mr",
            name=str(device.name or device.system_name or "").strip(),
            system_name=str(device.system_name or "").strip(),
            physical_mac=str(device.mac_address or "").strip(),
            location=str(device.station or device.location or "").strip(),
            source=SOURCE_DEVICE_MANAGEMENT,
            sources=[SOURCE_DEVICE_MANAGEMENT],
            raw={
                "device_id": device.id,
                "device_uuid": device.device_uuid,
                "group_name": group_name,
                "device_type": device.device_type,
            },
        )
        item.key = _item_key(item)
        items.append(item)
    return items


def merge_omnipeek_items(items: Iterable[OmniPeekDeviceItem]) -> list[OmniPeekDeviceItem]:
    merged: dict[str, OmniPeekDeviceItem] = {}
    passthrough: list[OmniPeekDeviceItem] = []
    for item in items:
        key = _merge_key(item)
        if not key:
            passthrough.append(item)
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            continue
        _merge_item(existing, item)

    result = [*merged.values(), *passthrough]
    by_name: dict[tuple[str, str], set[str]] = {}
    for item in result:
        name_key = (item.role, item.name.casefold())
        mac = _safe_normalize_mac(item.physical_mac)
        if mac:
            by_name.setdefault(name_key, set()).add(mac)
    conflict_names = {key for key, macs in by_name.items() if len(macs) > 1}
    for item in result:
        if (item.role, item.name.casefold()) in conflict_names:
            _mark_item(item, "MAC冲突", "同名设备存在不同物理MAC，默认跳过")
            item.selected = False
    return result


def prepare_omnipeek_items(items: Iterable[OmniPeekDeviceItem], config: OmniPeekExportConfig | None = None) -> list[OmniPeekDeviceItem]:
    prepared = [copy.deepcopy(item) for item in items]
    for item in prepared:
        _prepare_item_macs(item, config)
        item.key = item.key or _item_key(item)
    _mark_export_mac_conflicts(prepared, config)
    return prepared


def build_omnipeek_entries(items: Iterable[OmniPeekDeviceItem], config: OmniPeekExportConfig) -> list[OmniPeekNameEntry]:
    entries: list[OmniPeekNameEntry] = []
    prepared = prepare_omnipeek_items(items, config)
    for item in prepared:
        if not item.selected:
            continue
        if item.status in {"缺少物理MAC", "MAC格式错误", "MAC冲突"} and not item.force_export:
            continue
        for kind, mac in _item_export_macs(item, config):
            if not mac:
                continue
            entries.append(
                OmniPeekNameEntry(
                    name=_entry_name(item, kind),
                    mac=mac,
                    group=f"{config.line_name}{ENTRY_KIND_GROUP_SUFFIX[kind]}",
                    color=_color_for_kind(config, kind),
                    kind=kind,
                    item_key=item.key,
                )
            )
    return _dedupe_entries(entries)


def export_omnipeek_nam(
    entries: Iterable[OmniPeekNameEntry],
    output_path: Path,
    config: OmniPeekExportConfig,
    *,
    source_counts: dict[str, int] | None = None,
    warnings: Iterable[str] | None = None,
) -> OmniPeekExportResult:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entry_list = list(entries)
    root = ET.Element("NameTable", {"Version": "3.0"})
    mod_time = (config.mod_time or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for item in entry_list:
        node = ET.SubElement(root, "Entry", {"Class": "Address"})
        ET.SubElement(node, "Name").text = item.name
        address = ET.SubElement(node, "Address", {"Type": "Wireless", "Node": "Access Point", "Resolve": "User"})
        address.text = item.mac
        ET.SubElement(node, "Color").text = item.color
        ET.SubElement(node, "Group").text = item.group
        ET.SubElement(node, "Trust").text = "Trusted"
        ET.SubElement(node, "Mod").text = mod_time
    ET.indent(root, space="    ")
    xml_body = ET.tostring(root, encoding="utf-8")
    output_path.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + b"\n")

    counts = {kind: 0 for kind in OMNIPEEK_ENTRY_KIND_ORDER}
    for entry in entry_list:
        counts[entry.kind] += 1
    warning_list = [str(item) for item in warnings or [] if str(item).strip()]
    log_path = _write_export_log(output_path, counts, source_counts or {}, warning_list)
    return OmniPeekExportResult(
        output_path=output_path,
        log_path=log_path,
        counts=counts,
        skipped_count=0,
        error_count=len(warning_list),
        source_counts=source_counts or {},
        warnings=warning_list,
    )


def export_items_to_omnipeek_nam(
    items: Iterable[OmniPeekDeviceItem],
    config: OmniPeekExportConfig,
    *,
    source_counts: dict[str, int] | None = None,
) -> OmniPeekExportResult:
    prepared = prepare_omnipeek_items(items, config)
    entries = build_omnipeek_entries(prepared, config)
    warnings = _warnings_from_items(prepared)
    skipped = sum(1 for item in prepared if not item.selected or (item.status not in {"正常", "R2推导失败"} and not item.force_export))
    result = export_omnipeek_nam(entries, config.output_path, config, source_counts=source_counts, warnings=warnings)
    return OmniPeekExportResult(
        output_path=result.output_path,
        log_path=result.log_path,
        counts=result.counts,
        skipped_count=skipped,
        error_count=len(warnings),
        source_counts=result.source_counts,
        warnings=result.warnings,
    )


def make_omnipeek_filename(line_name: str) -> str:
    safe_name = _safe_filename(str(line_name or "").strip() or "线路")
    return f"{safe_name}名称表.nam"


def default_omnipeek_line_name(site_name: str, paths: PathResolver | None = None) -> str:
    paths = paths or PathResolver()
    metadata = SiteManager(paths).load_site_metadata(site_name)
    base = str(metadata.get("line_name") or metadata.get("display_name") or site_name or "").strip()
    if not base:
        base = site_name or "线路"
    for field in ("system_type", "network_domain"):
        value = str(metadata.get(field) or "").strip()
        if value and value.casefold() != "default" and value not in base:
            base += value
    return base


def infer_line_name_from_items(items: Iterable[OmniPeekDeviceItem], fallback: str) -> str:
    fallback = str(fallback or "").strip() or "线路"
    if fallback and fallback != "demo":
        return fallback
    for item in items:
        raw = item.raw or {}
        line_name = str(raw.get("line_name") or "").strip()
        if not line_name:
            continue
        for field in ("system_type", "network_domain"):
            value = str(raw.get(field) or "").strip()
            if value and value.casefold() != "default" and value not in line_name:
                line_name += value
        return line_name
    return fallback


def load_omnipeek_color_settings(settings: SettingsStore) -> dict[OmniPeekEntryKind, str]:
    raw = settings.get_value(OMNIPEEK_COLOR_SETTINGS_KEY, {})
    colors = dict(DEFAULT_OMNIPEEK_COLORS)
    if isinstance(raw, dict):
        for key in OMNIPEEK_ENTRY_KIND_ORDER:
            value = str(raw.get(key) or "").strip()
            if _valid_color(value):
                colors[key] = value.upper()
    return colors


def save_omnipeek_color_settings(settings: SettingsStore, colors: dict[OmniPeekEntryKind, str]) -> None:
    payload = {key: _color_for_key(colors, key) for key in OMNIPEEK_ENTRY_KIND_ORDER}
    settings.set_value(OMNIPEEK_COLOR_SETTINGS_KEY, payload)


def save_omnipeek_last_export_dir(settings: SettingsStore, path: Path) -> None:
    settings.set_value(OMNIPEEK_LAST_EXPORT_DIR_KEY, str(Path(path)))


def load_omnipeek_last_export_dir(settings: SettingsStore) -> Path | None:
    value = str(settings.get_value(OMNIPEEK_LAST_EXPORT_DIR_KEY, "") or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.exists() and path.is_dir() else None


def _prepare_item_macs(item: OmniPeekDeviceItem, config: OmniPeekExportConfig | None = None) -> None:
    conflict_status = item.status == "MAC冲突"
    conflict_warnings = [warning for warning in item.warnings if "冲突" in warning]
    item.normalized_physical_mac = ""
    item.r1_mac = ""
    item.r2_mac = ""
    item.r1_source = ""
    item.r2_source = ""
    if not conflict_status:
        item.status = "正常"
        item.warnings = []
    else:
        item.warnings = conflict_warnings
    if not str(item.physical_mac or "").strip():
        _mark_item(item, "缺少物理MAC", "缺少物理MAC，已跳过")
        item.selected = False
        return
    try:
        item.normalized_physical_mac = normalize_mac(item.physical_mac)
    except MacAddressError as exc:
        _mark_item(item, "MAC格式错误", str(exc))
        item.selected = False
        return
    if config is not None and not config.enable_h3c_derivation:
        item.r1_source = ""
        item.r2_source = ""
        return
    try:
        item.r1_mac = derive_h3c_r1_mac(item.normalized_physical_mac)
        item.r1_source = "H3C规则推导"
    except MacAddressError as exc:
        _mark_item(item, "MAC格式错误", str(exc))
        item.selected = False
    try:
        item.r2_mac = derive_h3c_r2_mac(item.normalized_physical_mac)
        item.r2_source = "H3C规则推导"
    except H3cMacDeriveError as exc:
        item.r2_mac = ""
        item.r2_source = "推导失败"
        _mark_item(item, "R2推导失败", str(exc), keep_selected=True)
    except MacAddressError as exc:
        _mark_item(item, "MAC格式错误", str(exc))
        item.selected = False


def _item_export_macs(item: OmniPeekDeviceItem, config: OmniPeekExportConfig) -> list[tuple[OmniPeekEntryKind, str]]:
    if item.role == "trackside_ap":
        return [
            ("trackside_physical", item.normalized_physical_mac if config.export_trackside_physical and item.export_physical else ""),
            ("trackside_r1", item.r1_mac if config.export_trackside_r1 and item.export_r1 else ""),
            ("trackside_r2", item.r2_mac if config.export_trackside_r2 and item.export_r2 else ""),
        ]
    r1_enabled, r2_enabled = _onboard_radio_export_enabled(config)
    return [
        ("onboard_physical", item.normalized_physical_mac if config.export_onboard_physical and item.export_physical else ""),
        ("onboard_r1", item.r1_mac if config.export_onboard_r1 and r1_enabled and item.export_r1 else ""),
        ("onboard_r2", item.r2_mac if config.export_onboard_r2 and r2_enabled and item.export_r2 else ""),
    ]


def _onboard_radio_export_enabled(config: OmniPeekExportConfig) -> tuple[bool, bool]:
    mode = config.onboard_radio_mode if config.onboard_radio_mode in ONBOARD_MR_RADIO_MODES else "auto"
    if mode == "r1_only":
        return True, False
    if mode == "r2_only":
        return False, True
    if mode == "r1_r2":
        return True, True
    if mode == "none":
        return False, False
    return True, True


def _mark_export_mac_conflicts(items: list[OmniPeekDeviceItem], config: OmniPeekExportConfig | None) -> None:
    if config is None:
        return
    seen: dict[str, str] = {}
    conflict_macs: set[str] = set()
    for item in items:
        for _kind, mac in _item_export_macs(item, config):
            if not mac:
                continue
            owner = seen.get(mac)
            label = f"{item.role}:{item.name}"
            if owner is not None and owner != label:
                conflict_macs.add(mac)
            else:
                seen[mac] = label
    if not conflict_macs:
        return
    for item in items:
        if item.force_export:
            continue
        if any(mac in conflict_macs for _kind, mac in _item_export_macs(item, config) if mac):
            _mark_item(item, "MAC冲突", "同一个导出MAC出现在多个名称下，默认跳过")
            item.selected = False


def _dedupe_entries(entries: Iterable[OmniPeekNameEntry]) -> list[OmniPeekNameEntry]:
    seen: set[tuple[str, str, str]] = set()
    result: list[OmniPeekNameEntry] = []
    for entry in entries:
        key = (entry.kind, entry.mac, entry.name)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def _write_export_log(
    output_path: Path,
    counts: dict[OmniPeekEntryKind, int],
    source_counts: dict[str, int],
    warnings: list[str],
) -> Path:
    log_path = output_path.with_name(f"{output_path.stem}_导出日志.txt")
    lines = [
        f"输出文件：{output_path}",
        "输入数据源统计：",
        *[f"- {name}：{count} 条" for name, count in source_counts.items()],
        "导出统计：",
        *[f"- {ENTRY_KIND_LABELS[kind]}：{counts.get(kind, 0)} 条" for kind in OMNIPEEK_ENTRY_KIND_ORDER],
        f"异常：{len(warnings)} 条",
    ]
    if warnings:
        lines.append("异常明细：")
        lines.extend(f"- {warning}" for warning in warnings)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


def _warnings_from_items(items: Iterable[OmniPeekDeviceItem]) -> list[str]:
    warnings: list[str] = []
    for item in items:
        for warning in item.warnings:
            warnings.append(f"{item.name}：{warning}")
    return warnings


def _entry_name(item: OmniPeekDeviceItem, kind: OmniPeekEntryKind) -> str:
    prefix = str(item.location or "").strip()
    base = str(item.name or item.system_name or item.physical_mac or "").strip()
    if prefix and base and not base.startswith(f"{prefix}-"):
        base = f"{prefix}-{base}"
    suffix = ENTRY_KIND_NAME_SUFFIX[kind]
    return f"{base}-{suffix}" if base else suffix


def _trackside_location(row: dict[str, object | None]) -> str:
    return _first_text(
        row,
        "extension_station_name",
        "station_name",
        "site_name",
        "site",
        "extension_section_name",
        "section_name",
        "extension_belong_section",
        "metadata_belong_section",
        "extension_yard_name",
        "yard_name",
        "extension_area_name",
        "area_name",
    )


def _merge_item(existing: OmniPeekDeviceItem, incoming: OmniPeekDeviceItem) -> None:
    for source in incoming.sources or [incoming.source]:
        if source and source not in existing.sources:
            existing.sources.append(source)
    existing.source = " / ".join(existing.sources)
    existing.raw = {**incoming.raw, **existing.raw} if incoming.source == SOURCE_AC_FIT_AP else {**existing.raw, **incoming.raw}
    if incoming.source == SOURCE_AP_EXTENSION:
        for field in ("name", "physical_mac", "location"):
            value = getattr(incoming, field)
            if str(value or "").strip():
                setattr(existing, field, value)
    else:
        for field in ("name", "physical_mac", "location", "system_name"):
            if not str(getattr(existing, field) or "").strip():
                setattr(existing, field, getattr(incoming, field))
    existing.key = _item_key(existing)


def _merge_key(item: OmniPeekDeviceItem) -> str:
    mac = _safe_normalize_mac(item.physical_mac)
    if mac:
        return f"{item.role}:mac:{mac}"
    name = str(item.name or item.system_name or "").strip().casefold()
    return f"{item.role}:name:{name}" if name else ""


def _item_key(item: OmniPeekDeviceItem) -> str:
    return _merge_key(item) or f"{item.role}:raw:{id(item)}"


def _safe_normalize_mac(value: object) -> str:
    try:
        return normalize_mac(str(value or ""))
    except MacAddressError:
        return ""


def _mark_item(item: OmniPeekDeviceItem, status: str, warning: str, *, keep_selected: bool = False) -> None:
    item.status = status
    if warning and warning not in item.warnings:
        item.warnings.append(warning)
    if not keep_selected:
        item.selected = False


def _looks_like_onboard_mr(device: Device, group_name: str) -> bool:
    group = str(group_name or "").replace(" ", "").replace("_", "-").casefold()
    if group in {"车载-mr", "车载mr", "mr", "onboard-mr"}:
        return True
    text = " ".join(
        str(value or "")
        for value in (device.name, device.system_name, device.remark, device.device_type)
    ).casefold()
    return "mr" in text and ("车载" in text or str(device.device_type or "").casefold() in {"cloud-ap", "fat-ap"})


def _first_text(row: dict[str, object | None], *fields: str) -> str:
    for field in fields:
        value = row.get(field)
        text = str(value or "").strip()
        if text and text not in {"-", "N/A", "n/a", "None"}:
            return text
    return ""


def _color_for_kind(config: OmniPeekExportConfig, kind: OmniPeekEntryKind) -> str:
    return _color_for_key(config.colors, kind)


def _color_for_key(colors: dict[str, str], kind: OmniPeekEntryKind) -> str:
    value = str(colors.get(kind) or "").strip()
    return value.upper() if _valid_color(value) else DEFAULT_OMNIPEEK_COLORS[kind]


def _valid_color(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", str(value or "").strip()))


def _safe_filename(value: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in value)
    return cleaned.strip().strip(".") or "线路"
