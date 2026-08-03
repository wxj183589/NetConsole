"""Read-only coalescing for duplicate FIT-AP resource projections."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
import re
import unicodedata
from typing import Iterable, Mapping

from netconsole.services.ap_extension_import import normalize_ap_mac


_IDENTITY_PLACEHOLDERS = {"", "-", "n/a", "na", "null", "none"}
_APID_RE = re.compile(r"\s+")


@dataclass
class _ResourceGroup:
    row: dict[str, object | None]
    first_index: int
    tokens: set[tuple[str, str]] = dataclass_field(default_factory=set)
    scope: str = ""
    name: str = ""
    apids: set[str] = dataclass_field(default_factory=set)


def coalesce_fit_ap_resource_rows(
    rows: Iterable[Mapping[str, object | None]],
) -> list[dict[str, object | None]]:
    """Coalesce only records that have defensible same-AP evidence.

    A MAC or serial number is a stable identity token. A row without either
    token may be folded into a single strong row with the same AC-scoped name,
    but only when that name has one strong candidate. This keeps same-name
    hardware replacements and ambiguous name-only rows separate.
    """

    groups: list[_ResourceGroup] = []
    token_to_group: dict[tuple[str, str], int] = {}
    weak_rows: list[tuple[int, dict[str, object | None]]] = []

    for index, source in enumerate(rows):
        row = dict(source)
        tokens = _identity_tokens(row)
        if not tokens:
            weak_rows.append((index, row))
            continue

        group_ids = {token_to_group[token] for token in tokens if token in token_to_group}
        if not group_ids:
            groups.append(
                _ResourceGroup(
                    row=row,
                    first_index=index,
                    tokens=set(tokens),
                    scope=_scope_key(row),
                    name=_name_key(row),
                    apids=_apid_keys(row),
                )
            )
            group_id = len(groups) - 1
        else:
            group_id = min(group_ids)
            for other_id in sorted(group_ids - {group_id}, reverse=True):
                _merge_groups(groups[group_id], groups[other_id])
                groups[other_id].row = {}
                for token, mapped_id in list(token_to_group.items()):
                    if mapped_id == other_id:
                        token_to_group[token] = group_id

        group = groups[group_id]
        _merge_row(group, row, index)
        for token in group.tokens:
            token_to_group[token] = group_id

    group_by_name: dict[tuple[str, str], list[int]] = {}
    for group_id, group in enumerate(groups):
        if group.row and group.name:
            group_by_name.setdefault((group.scope, group.name), []).append(group_id)

    for index, row in weak_rows:
        scope = _scope_key(row)
        name = _name_key(row)
        candidates = [
            group_id
            for group_id in group_by_name.get((scope, name), [])
            if _compatible_name_candidate(row, groups[group_id])
        ]
        if len(candidates) == 1:
            _merge_row(groups[candidates[0]], row, index)
            continue
        groups.append(
            _ResourceGroup(
                row=row,
                first_index=index,
                scope=scope,
                name=name,
                apids=_apid_keys(row),
            )
        )

    merged = [group for group in groups if group.row]
    merged.sort(key=lambda group: group.first_index)
    return [group.row for group in merged]


def _identity_tokens(row: Mapping[str, object | None]) -> set[tuple[str, str]]:
    tokens: set[tuple[str, str]] = set()
    mac = normalize_ap_mac(row.get("ap_mac") or row.get("mac"))
    if mac.valid:
        tokens.add(("mac", mac.normalized.casefold()))
    serial = _identity_value(row.get("serial_number") or row.get("serial"))
    if serial:
        tokens.add(("serial", serial.casefold()))
    return tokens


def _scope_key(row: Mapping[str, object | None]) -> str:
    return _identity_value(row.get("ac_device_uuid") or row.get("device_uuid")).casefold()


def _name_key(row: Mapping[str, object | None]) -> str:
    value = unicodedata.normalize("NFKC", str(row.get("ap_name") or ""))
    return " ".join(value.casefold().split())


def _apid_keys(row: Mapping[str, object | None]) -> set[str]:
    value = _identity_value(row.get("apid") or row.get("ap_id"))
    return {_APID_RE.sub("", value).casefold()} if value else set()


def _identity_value(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in _IDENTITY_PLACEHOLDERS else text


def _compatible_name_candidate(row: Mapping[str, object | None], group: _ResourceGroup) -> bool:
    incoming_apids = _apid_keys(row)
    return not incoming_apids or not group.apids or bool(incoming_apids & group.apids)


def _merge_groups(target: _ResourceGroup, source: _ResourceGroup) -> None:
    _merge_row(target, source.row, source.first_index)
    target.first_index = min(target.first_index, source.first_index)
    target.tokens.update(source.tokens)
    target.apids.update(source.apids)


def _merge_row(group: _ResourceGroup, row: Mapping[str, object | None], index: int) -> None:
    incoming = dict(row)
    if _row_score(incoming) >= _row_score(group.row):
        preferred, fallback = incoming, group.row
    else:
        preferred, fallback = group.row, incoming
    merged = dict(preferred)
    for field, value in fallback.items():
        if _is_missing(merged.get(field)) and not _is_missing(value):
            merged[field] = value
    group.row = merged
    group.first_index = min(group.first_index, index)
    group.tokens.update(_identity_tokens(incoming))
    group.scope = group.scope or _scope_key(incoming)
    group.name = group.name or _name_key(incoming)
    group.apids.update(_apid_keys(incoming))


def _row_score(row: Mapping[str, object | None]) -> tuple[int, int, int, int, str, int]:
    mac = normalize_ap_mac(row.get("ap_mac") or row.get("mac"))
    serial = _identity_value(row.get("serial_number") or row.get("serial"))
    populated_fields = sum(
        not _is_missing(row.get(field))
        for field in (
            "ap_ip",
            "model",
            "state",
            "state_raw",
            "state_display",
            "connection_ip",
            "connection_state",
            "lldp_neighbor_name",
            "lldp_neighbor_interface",
            "optical_rx_power",
            "optical_tx_power",
        )
    )
    radio_fields = sum(
        not _is_missing(row.get(f"rid{rid}_{field}"))
        for rid in (1, 2, 3)
        for field in ("status", "channel", "bandwidth", "tx_power", "bbssid", "clients")
    )
    return (
        int(mac.valid),
        int(bool(serial)),
        populated_fields,
        radio_fields,
        str(row.get("updated_at") or row.get("collected_at") or ""),
        _integer(row.get("id")),
    )


def _is_missing(value: object) -> bool:
    return value is None or value == ""


def _integer(value: object) -> int:
    try:
        return int(str(value or "0"))
    except (TypeError, ValueError):
        return 0


__all__ = ["coalesce_fit_ap_resource_rows"]
