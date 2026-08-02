from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

from netconsole.models.ap_identity_index import (
    ApIdentityConflictRecord,
    ApIdentityEntityRecord,
    ApIdentityH3cPrefixRecord,
    ApIdentityIndexBuild,
    ApIdentityMacAliasRecord,
)
from netconsole.services.ap_identity.normalizers import (
    format_mac,
    mac_prefix,
    normalize_ap_name,
    normalize_mac_key,
)
from netconsole.utils.mac_utils import (
    H3cMacDeriveError,
    MacAddressError,
    derive_h3c_r1_mac,
    derive_h3c_r2_mac,
)
from netconsole.utils.station_normalize import normalize_station_value


AC_BASE_CONFLICT_CODE = "AP_IDENTITY_AC_BASE_CONFLICT"

_RADIO_KEYS = {
    "radio_mac",
    "bssid",
    "bbssid",
    "rid1_mac",
    "rid2_mac",
    "rid3_mac",
    "rid1_bssid",
    "rid2_bssid",
    "rid3_bssid",
    "rid1_bbssid",
    "rid2_bbssid",
    "rid3_bbssid",
    "radio1_mac",
    "radio2_mac",
    "radio3_mac",
}


@dataclass(frozen=True)
class _SourceAp:
    source: str
    source_id: str
    ap_uuid: str
    ac_device_uuid: str
    ap_name: str
    ap_mac_key: str
    point_code: str
    serial_number: str
    station: str
    section: str
    location: str
    mileage: str
    direction: str
    belong_type: str
    vendor: str
    model: str
    software_version: str
    updated_at: str
    radio_aliases: tuple[tuple[str, int | None, str], ...]
    raw: Mapping[str, object]


def build_ap_identity_index(
    base_rows: Sequence[Mapping[str, object]],
    ac_rows: Sequence[Mapping[str, object]],
    *,
    site_id: str = "current",
) -> ApIdentityIndexBuild:
    base_sources = tuple(
        item
        for item in (_source_ap(row, source="base_data") for row in base_rows)
        if item.ap_mac_key or item.ap_name or item.point_code
    )
    identity_sources = tuple(
        item
        for item in (_source_ap(row, source="ac_runtime") for row in ac_rows)
        if item.ap_mac_key or item.ap_name or item.ap_uuid
    )
    ac_sources = tuple(
        item for item in identity_sources if item.source == "ac_runtime"
    )
    legacy_sources = tuple(
        item for item in identity_sources if item.source == "legacy_cache"
    )
    base_groups = _group_sources(base_sources)
    ac_groups = _group_sources(ac_sources)
    legacy_groups = _group_sources(legacy_sources)

    base_to_ac = _match_groups(base_groups, ac_groups)
    matched_base_indexes = set(base_to_ac)
    legacy_to_ac = _match_groups(legacy_groups, ac_groups)
    legacy_to_base = _match_groups(legacy_groups, base_groups)
    entities: list[ApIdentityEntityRecord] = []
    aliases: list[ApIdentityMacAliasRecord] = []
    prefixes: list[ApIdentityH3cPrefixRecord] = []
    conflicts: list[ApIdentityConflictRecord] = []

    bases_by_ac: dict[int, list[int]] = defaultdict(list)
    for base_index, ac_index in base_to_ac.items():
        bases_by_ac[ac_index].append(base_index)
    legacy_by_ac: dict[int, list[int]] = defaultdict(list)
    legacy_by_base: dict[int, list[int]] = defaultdict(list)
    standalone_legacy_indexes: list[int] = []
    for legacy_index in range(len(legacy_groups)):
        ac_index = legacy_to_ac.get(legacy_index)
        if ac_index is not None:
            legacy_by_ac[ac_index].append(legacy_index)
            continue
        base_index = legacy_to_base.get(legacy_index)
        if base_index is None:
            standalone_legacy_indexes.append(legacy_index)
            continue
        mapped_ac_index = base_to_ac.get(base_index)
        if mapped_ac_index is not None:
            legacy_by_ac[mapped_ac_index].append(legacy_index)
        else:
            legacy_by_base[base_index].append(legacy_index)

    for ac_index, ac_group in enumerate(ac_groups):
        base_group = tuple(
            item
            for index in bases_by_ac.get(ac_index, [])
            for item in base_groups[index]
        )
        combined_ac_group = (
            *ac_group,
            *(
                item
                for index in legacy_by_ac.get(ac_index, [])
                for item in legacy_groups[index]
            ),
        )
        entity, entity_aliases, entity_prefixes, entity_conflicts = _entity_projection(
            site_id=site_id,
            ac_group=combined_ac_group,
            base_group=base_group,
        )
        entities.append(entity)
        aliases.extend(entity_aliases)
        prefixes.extend(entity_prefixes)
        conflicts.extend(entity_conflicts)

    for base_index, base_group in enumerate(base_groups):
        if base_index in matched_base_indexes:
            continue
        combined_ac_group = tuple(
            item
            for index in legacy_by_base.get(base_index, [])
            for item in legacy_groups[index]
        )
        entity, entity_aliases, entity_prefixes, entity_conflicts = _entity_projection(
            site_id=site_id,
            ac_group=combined_ac_group,
            base_group=base_group,
        )
        entities.append(entity)
        aliases.extend(entity_aliases)
        prefixes.extend(entity_prefixes)
        conflicts.extend(entity_conflicts)

    for legacy_index in standalone_legacy_indexes:
        entity, entity_aliases, entity_prefixes, entity_conflicts = _entity_projection(
            site_id=site_id,
            ac_group=legacy_groups[legacy_index],
            base_group=(),
        )
        entities.append(entity)
        aliases.extend(entity_aliases)
        prefixes.extend(entity_prefixes)
        conflicts.extend(entity_conflicts)

    return ApIdentityIndexBuild(
        entities=tuple(_dedupe(entities, lambda item: item.entity_id)),
        aliases=tuple(
            _dedupe(
                aliases,
                lambda item: (
                    item.site_id,
                    item.entity_id,
                    item.mac_key,
                    item.alias_type,
                    item.source,
                ),
            )
        ),
        prefixes=tuple(
            _dedupe(
                prefixes,
                lambda item: (
                    item.site_id,
                    item.entity_id,
                    item.base_mac_key,
                    item.prefix_bits,
                    item.source,
                ),
            )
        ),
        conflicts=tuple(
            _dedupe(
                conflicts,
                lambda item: (item.site_id, item.entity_id, item.conflict_type),
            )
        ),
        base_record_count=len(base_sources),
        ac_record_count=len(ac_sources),
    )


def _source_ap(row: Mapping[str, object], *, source: str) -> _SourceAp:
    source_name = str(row.get("_identity_source") or source).strip()
    if source_name not in {"ac_runtime", "base_data", "legacy_cache"}:
        source_name = source
    ap_mac_key = normalize_mac_key(
        row.get("ap_mac")
        or row.get("ap_mac_norm")
        or row.get("ap_mac_display")
    ) or ""
    ap_name = str(row.get("ap_name") or "").strip()
    point_code = str(row.get("ap_point_code") or row.get("point_code") or "").strip()
    station = normalize_station_value(dict(row)) or str(
        row.get("station_name") or ""
    ).strip()
    section = str(
        row.get("section_name")
        or row.get("belong_section")
        or row.get("metadata_belong_section")
        or ""
    ).strip()
    source_id = str(
        row.get("_identity_source_id")
        or row.get("ap_uuid")
        or row.get("id")
        or row.get("extension_id")
        or ap_mac_key
        or ap_name
        or point_code
    ).strip()
    return _SourceAp(
        source=source_name,
        source_id=source_id,
        ap_uuid=str(row.get("ap_uuid") or "").strip(),
        ac_device_uuid=str(row.get("ac_device_uuid") or "").strip(),
        ap_name=ap_name,
        ap_mac_key=ap_mac_key,
        point_code=point_code,
        serial_number=_first_text(row, "serial_number", "serial", "sn", "device_sn"),
        station=station,
        section=section,
        location=_first_text(row, "metadata_location_note", "location_note", "location_desc"),
        mileage=_first_text(row, "metadata_mileage", "mileage", "mileage_text"),
        direction=_first_text(row, "metadata_direction", "direction"),
        belong_type=_belong_type(row, station, section),
        vendor=_first_text(row, "ap_vendor", "vendor", "device_vendor").upper(),
        model=_first_text(row, "model", "ac_model"),
        software_version=_first_text(row, "software_version", "ac_software_version"),
        updated_at=_first_text(row, "updated_at", "collected_at"),
        radio_aliases=_radio_aliases(row, ap_mac_key),
        raw=dict(row),
    )


def _group_sources(rows: Sequence[_SourceAp]) -> tuple[tuple[_SourceAp, ...], ...]:
    groups: dict[str, list[_SourceAp]] = {}
    for row in rows:
        if row.source in {"ac_runtime", "legacy_cache"} and row.ap_uuid:
            key = f"uuid:{row.ap_uuid.casefold()}"
        elif row.ap_mac_key:
            key = f"mac:{row.ap_mac_key}"
        else:
            key = f"source:{row.source}:{row.source_id.casefold()}"
        groups.setdefault(key, []).append(row)
    return tuple(
        tuple(sorted(values, key=_source_sort_key, reverse=True))
        for _key, values in sorted(groups.items())
    )


def _match_groups(
    source_groups: Sequence[tuple[_SourceAp, ...]],
    target_groups: Sequence[tuple[_SourceAp, ...]],
) -> dict[int, int]:
    target_by_uuid: dict[str, list[int]] = defaultdict(list)
    target_by_mac: dict[str, list[int]] = defaultdict(list)
    target_by_serial: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(target_groups):
        for item in group:
            if item.ap_uuid:
                target_by_uuid[item.ap_uuid.casefold()].append(index)
            if item.ap_mac_key:
                target_by_mac[item.ap_mac_key].append(index)
            if item.serial_number:
                target_by_serial[item.serial_number.casefold()].append(index)

    result: dict[int, int] = {}
    for source_index, group in enumerate(source_groups):
        candidates: list[int] = []
        for item in group:
            if item.ap_uuid:
                candidates.extend(target_by_uuid.get(item.ap_uuid.casefold(), ()))
        match = _single_index(candidates)
        if match is None:
            candidates = []
            for item in group:
                if item.ap_mac_key:
                    candidates.extend(target_by_mac.get(item.ap_mac_key, ()))
            match = _single_index(candidates)
        if match is None:
            candidates = []
            for item in group:
                if item.serial_number:
                    candidates.extend(
                        target_by_serial.get(item.serial_number.casefold(), ())
                    )
            match = _single_index(candidates)
        if match is not None:
            result[source_index] = match
    return result


def _entity_projection(
    *,
    site_id: str,
    ac_group: Sequence[_SourceAp],
    base_group: Sequence[_SourceAp],
) -> tuple[
    ApIdentityEntityRecord,
    list[ApIdentityMacAliasRecord],
    list[ApIdentityH3cPrefixRecord],
    list[ApIdentityConflictRecord],
]:
    ac = _best_source(
        tuple(item for item in ac_group if item.source == "ac_runtime")
    )
    legacy = _best_source(
        tuple(item for item in ac_group if item.source == "legacy_cache")
    )
    base = _best_source(base_group)
    effective = ac or base or legacy
    if effective is None:
        raise ValueError("AP identity entity requires at least one source")
    entity_id = _entity_id(site_id, ac or legacy, base)
    effective_mac = ac.ap_mac_key if ac and ac.ap_mac_key else (
        base.ap_mac_key if base and base.ap_mac_key else legacy.ap_mac_key if legacy else ""
    )
    effective_name = ac.ap_name if ac and ac.ap_name else (
        base.ap_name if base and base.ap_name else legacy.ap_name if legacy else ""
    )
    effective_station = ac.station if ac and ac.station else (
        base.station if base and base.station else legacy.station if legacy else ""
    )
    effective_section = ac.section if ac and ac.section else (
        base.section if base and base.section else legacy.section if legacy else ""
    )
    warning_types: list[str] = []
    conflict_rows: list[ApIdentityConflictRecord] = []
    if ac and base:
        if (
            ac.ap_mac_key
            and base.ap_mac_key
            and ac.ap_mac_key != base.ap_mac_key
        ):
            warning_types.append("ap_mac_mismatch")
            conflict_rows.append(
                _conflict(
                    site_id,
                    entity_id,
                    "ap_mac_mismatch",
                    format_mac(ac.ap_mac_key),
                    format_mac(base.ap_mac_key),
                    ac,
                    base,
                )
            )
        if (
            ac.ap_name
            and base.ap_name
            and _name_key(ac.ap_name) != _name_key(base.ap_name)
        ):
            warning_types.append("ap_name_mismatch")
            conflict_rows.append(
                _conflict(
                    site_id,
                    entity_id,
                    "ap_name_mismatch",
                    ac.ap_name,
                    base.ap_name,
                    ac,
                    base,
                )
            )

    warning = AC_BASE_CONFLICT_CODE if warning_types else ""
    entity = ApIdentityEntityRecord(
        entity_id=entity_id,
        site_id=site_id,
        effective_ap_name=effective_name or effective.point_code,
        effective_ap_mac_key=effective_mac,
        effective_ap_mac_display=format_mac(effective_mac),
        effective_station=effective_station,
        effective_section=effective_section,
        effective_point_code=(
            ac.point_code
            if ac and ac.point_code
            else base.point_code
            if base and base.point_code
            else legacy.point_code
            if legacy
            else ""
        ),
        effective_serial_number=(
            ac.serial_number
            if ac and ac.serial_number
            else base.serial_number
            if base
            else legacy.serial_number
            if legacy
            else ""
        ),
        effective_location=(
            ac.location
            if ac and ac.location
            else base.location
            if base and base.location
            else legacy.location
            if legacy
            else ""
        ),
        effective_mileage=(
            ac.mileage
            if ac and ac.mileage
            else base.mileage
            if base and base.mileage
            else legacy.mileage
            if legacy
            else ""
        ),
        effective_direction=(
            ac.direction
            if ac and ac.direction
            else base.direction
            if base and base.direction
            else legacy.direction
            if legacy
            else ""
        ),
        effective_belong_type=(
            ac.belong_type
            if ac and ac.belong_type != "unknown"
            else base.belong_type
            if base
            else legacy.belong_type
            if legacy
            else "unknown"
        ),
        ac_ap_uuid=ac.ap_uuid if ac else "",
        ac_device_uuid=ac.ac_device_uuid if ac else "",
        ac_ap_name=ac.ap_name if ac else "",
        ac_ap_mac_key=ac.ap_mac_key if ac else "",
        ac_station=ac.station if ac else "",
        ac_section=ac.section if ac else "",
        ac_updated_at=ac.updated_at if ac else "",
        base_record_id=base.source_id if base else "",
        base_ap_name=base.ap_name if base else "",
        base_ap_mac_key=base.ap_mac_key if base else "",
        base_station=base.station if base else "",
        base_section=base.section if base else "",
        base_updated_at=base.updated_at if base else "",
        effective_source=(
            "ac_runtime" if ac else "base_data" if base else "legacy_cache"
        ),
        identity_status="conflict" if warning else "matched",
        data_quality_warning=warning,
    )

    aliases: list[ApIdentityMacAliasRecord] = []
    prefixes: list[ApIdentityH3cPrefixRecord] = []
    for source in ac_group:
        if source.ap_mac_key:
            alias_type = (
                "ac_ap_mac" if source.source == "ac_runtime" else "legacy_mac"
            )
            alias_priority = 900 if source.source == "ac_runtime" else 500
            alias_confidence = 98 if source.source == "ac_runtime" else 60
            alias_rule = (
                "ac_ap_mac_exact"
                if source.source == "ac_runtime"
                else "legacy_mac_exact"
            )
            aliases.append(
                _alias(
                    site_id,
                    entity_id,
                    source.ap_mac_key,
                    alias_type,
                    source.source,
                    alias_priority,
                    alias_confidence,
                    alias_rule,
                )
            )
            if source.source == "ac_runtime":
                aliases.extend(
                    _h3c_exact_aliases(
                        site_id,
                        entity_id,
                        source.ap_mac_key,
                        source="ac_runtime",
                        priority=930,
                        confidence=95,
                        vendor=source.vendor,
                    )
                )
        if source.source != "ac_runtime":
            continue
        for mac_key, radio_id, field_name in source.radio_aliases:
            alias_type, match_rule, priority = _actual_alias_metadata(field_name)
            aliases.append(
                _alias(
                    site_id,
                    entity_id,
                    mac_key,
                    alias_type,
                    "ac_runtime",
                    priority,
                    100,
                    match_rule,
                    radio_id=radio_id,
                )
            )
    for source in base_group:
        if not source.ap_mac_key:
            continue
        aliases.append(
            _alias(
                site_id,
                entity_id,
                source.ap_mac_key,
                "base_ap_mac",
                "base_data",
                700,
                90,
                "base_ap_mac_exact",
            )
        )
        entity_vendor = (
            (ac.vendor if ac else "")
            or source.vendor
            or (base.vendor if base else "")
        )
        aliases.extend(
            _h3c_exact_aliases(
                site_id,
                entity_id,
                source.ap_mac_key,
                source="base_data",
                priority=830,
                confidence=90,
                vendor=entity_vendor,
                allow_unknown_vendor=True,
            )
        )
    return entity, aliases, prefixes, conflict_rows


def _alias(
    site_id: str,
    entity_id: str,
    mac_key: str,
    alias_type: str,
    source: str,
    priority: int,
    confidence: int,
    rule: str,
    *,
    radio_id: int | None = None,
) -> ApIdentityMacAliasRecord:
    return ApIdentityMacAliasRecord(
        entity_id=entity_id,
        site_id=site_id,
        mac_key=mac_key,
        mac_display=format_mac(mac_key),
        alias_type=alias_type,
        source=source,
        match_priority=priority,
        confidence=confidence,
        radio_id=radio_id,
        derivation_rule=rule,
    )


def _prefix(
    site_id: str,
    entity_id: str,
    base_mac_key: str,
    source: str,
    priority: int,
    confidence: int,
) -> ApIdentityH3cPrefixRecord:
    prefix = mac_prefix(base_mac_key, 36)
    if prefix is None:
        raise ValueError("invalid AP MAC for H3C prefix")
    return ApIdentityH3cPrefixRecord(
        entity_id=entity_id,
        site_id=site_id,
        base_mac_key=base_mac_key,
        prefix_key=prefix,
        prefix_bits=36,
        derivation_rule="h3c_radio_block_36",
        source=source,
        match_priority=priority,
        confidence=confidence,
    )


def _h3c_exact_aliases(
    site_id: str,
    entity_id: str,
    base_mac_key: str,
    *,
    source: str,
    priority: int,
    confidence: int,
    vendor: str,
    allow_unknown_vendor: bool = False,
) -> list[ApIdentityMacAliasRecord]:
    normalized_vendor = str(vendor or "").strip().upper()
    if normalized_vendor != "H3C" and not (
        allow_unknown_vendor and not normalized_vendor
    ):
        return []
    if not base_mac_key or base_mac_key[-1].upper() != "0":
        return []
    aliases: list[ApIdentityMacAliasRecord] = []
    derivations = (
        (derive_h3c_r1_mac, 1, "h3c_r1_derived", "h3c_physical_mac_to_r1_exact_v1"),
        (derive_h3c_r2_mac, 2, "h3c_r2_derived", "h3c_physical_mac_to_r2_exact_v1"),
    )
    for derive, radio_id, alias_type, rule in derivations:
        try:
            mac_key = normalize_mac_key(derive(base_mac_key)) or ""
        except (H3cMacDeriveError, MacAddressError):
            continue
        if not mac_key:
            continue
        aliases.append(
            _alias(
                site_id,
                entity_id,
                mac_key,
                alias_type,
                source,
                priority,
                confidence,
                rule,
                radio_id=radio_id,
            )
        )
    return aliases


def _conflict(
    site_id: str,
    entity_id: str,
    conflict_type: str,
    ac_value: str,
    base_value: str,
    ac: _SourceAp,
    base: _SourceAp,
) -> ApIdentityConflictRecord:
    return ApIdentityConflictRecord(
        entity_id=entity_id,
        site_id=site_id,
        conflict_type=conflict_type,
        ac_value=ac_value,
        base_value=base_value,
        details={
            "code": AC_BASE_CONFLICT_CODE,
            "ac_ap_name": ac.ap_name,
            "base_ap_name": base.ap_name,
            "ac_station": ac.station,
            "base_station": base.station,
            "ac_updated_at": ac.updated_at,
            "base_updated_at": base.updated_at,
        },
    )


def _radio_aliases(
    row: Mapping[str, object],
    ap_mac_key: str,
) -> tuple[tuple[str, int | None, str], ...]:
    result: list[tuple[str, int | None, str]] = []
    for key, value in row.items():
        key_text = str(key).casefold()
        if key_text not in _RADIO_KEYS and not (
            any(token in key_text for token in ("radio", "bssid", "bbssid"))
            and any(token in key_text for token in ("mac", "bssid", "bbssid"))
        ):
            continue
        mac_key = normalize_mac_key(value)
        if not mac_key or mac_key == ap_mac_key:
            continue
        result.append((mac_key, _radio_id(key_text), key_text))
    return tuple(_dedupe(result, lambda item: item))


def _actual_alias_metadata(field_name: str) -> tuple[str, str, int]:
    text = field_name.casefold()
    if "bbssid" in text:
        return "ac_bbssid", "actual_bbssid_exact", 980
    if "bssid" in text:
        return "ac_bssid", "actual_bssid_exact", 990
    return "ac_radio_mac", "actual_radio_mac_exact", 1000


def _best_source(rows: Sequence[_SourceAp]) -> _SourceAp | None:
    return max(rows, key=_source_sort_key) if rows else None


def _source_sort_key(value: _SourceAp | None) -> tuple[str, int, str]:
    if value is None:
        return "", 0, ""
    return value.updated_at, sum(
        bool(item)
        for item in (
            value.ap_mac_key,
            value.ap_name,
            value.station,
            value.section,
            value.serial_number,
        )
    ), value.source_id


def _single_index(values: Sequence[int]) -> int | None:
    unique = tuple(dict.fromkeys(values))
    return unique[0] if len(unique) == 1 else None


def _entity_id(
    site_id: str,
    ac: _SourceAp | None,
    base: _SourceAp | None,
) -> str:
    if ac and ac.ap_uuid:
        return f"ac:{ac.ap_uuid}"
    if base and base.source_id:
        return f"base:{base.source_id}"
    seed = "|".join(
        (
            site_id,
            ac.ap_mac_key if ac else "",
            ac.ap_name if ac else "",
            base.ap_mac_key if base else "",
            base.ap_name if base else "",
        )
    )
    return f"ap:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"


def _belong_type(
    row: Mapping[str, object],
    station: str,
    section: str,
) -> str:
    value = str(
        row.get("belong_type") or row.get("metadata_belong_type") or ""
    ).strip().casefold()
    if value:
        return value
    if str(row.get("yard_name") or row.get("area_name") or "").strip():
        return "yard"
    if section:
        return "section"
    if station:
        return "station"
    return "unknown"


def _radio_id(key: str) -> int | None:
    matched = re.search(r"(?:rid|radio)[_-]?([123])", key)
    return int(matched.group(1)) if matched else None


def _name_key(value: object) -> str:
    normalized = normalize_ap_name(value)
    return normalized.casefold() if normalized else ""


def _first_text(row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _dedupe(values, key):
    result = []
    seen = set()
    for value in values:
        marker = key(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


__all__ = ["AC_BASE_CONFLICT_CODE", "build_ap_identity_index"]
