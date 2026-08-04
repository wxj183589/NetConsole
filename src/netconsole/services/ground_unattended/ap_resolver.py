from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any, Callable

from netconsole.models.ap_identity_index import ApIdentityMatch
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import (
    normalize_mac as canonical_normalize_mac,
    normalize_mac_key,
)


class GroundApDisplayResolver:
    """通过统一 AP Identity 查询补全 WMESH 轨旁 AP 展示身份。"""

    def __init__(
        self,
        query_service: ApIdentityQueryService | None = None,
        *,
        revision_check_interval_seconds: float = 30.0,
        monotonic_provider: Callable[[], float] = time.monotonic,
    ) -> None:
        self.query_service = query_service
        self._revision_check_interval_seconds = max(
            0.0,
            float(revision_check_interval_seconds),
        )
        self._monotonic = monotonic_provider
        self._matches: dict[str, ApIdentityMatch] = {}
        self._identity_revision: int | None = None
        self._last_revision_checked_at = float("-inf")
        self._lock = threading.RLock()

    @property
    def identity_revision(self) -> int:
        return int(self._identity_revision or 0)

    def refresh_revision(self, *, force: bool = False) -> int:
        with self._lock:
            self._refresh_revision_if_due(force=force)
            return self.identity_revision

    def preload_parsed(self, parsed_rows: Iterable[Mapping[str, Any]]) -> None:
        keys: list[str] = []
        for parsed in parsed_rows:
            details = parsed.get("details") or {}
            if not isinstance(details, Mapping):
                details = {}
            keys.extend(
                _observed_keys(
                    parsed.get("peer_mac") or details.get("new_peer_mac"),
                    details.get("peer_radio_mac") or details.get("new_peer_radio_mac"),
                )
            )
            keys.extend(
                _observed_keys(
                    parsed.get("previous_peer_mac") or details.get("old_peer_mac"),
                    details.get("previous_peer_radio_mac")
                    or details.get("old_peer_radio_mac"),
                )
            )
        self._resolve_keys(keys)

    def resolve(
        self,
        *,
        name: object = "",
        mac: object = "",
        radio_mac: object = "",
    ) -> dict[str, object]:
        name_text = str(name or "").strip()
        observed_key = normalize_mac_key(radio_mac) or normalize_mac_key(mac)
        if not observed_key:
            return _unresolved_result(
                name_text,
                mac,
                radio_mac,
                reason="invalid_peer_mac",
            )
        match = self._resolve_keys((observed_key,)).get(observed_key)
        if match is None:
            return _unresolved_result(
                name_text,
                mac,
                radio_mac,
                reason="identity_query_unavailable",
                identity_revision=self.identity_revision,
            )
        return _match_result(name_text, mac, radio_mac, match)

    def enrich_parsed(self, parsed: dict[str, Any]) -> dict[str, Any]:
        self.preload_parsed((parsed,))
        result = dict(parsed)
        details = dict(result.get("details") or {})
        current_name = result.get("peer_name")
        current_mac = result.get("peer_mac") or details.get("new_peer_mac")
        current_radio_mac = details.get("peer_radio_mac") or details.get(
            "new_peer_radio_mac"
        )
        current = self.resolve(
            name=current_name,
            mac=current_mac,
            radio_mac=current_radio_mac,
        )
        previous_name = result.get("previous_peer_name")
        previous_mac = result.get("previous_peer_mac") or details.get("old_peer_mac")
        previous_radio_mac = details.get("previous_peer_radio_mac") or details.get(
            "old_peer_radio_mac"
        )
        previous = self.resolve(
            name=previous_name,
            mac=previous_mac,
            radio_mac=previous_radio_mac,
        )
        if str(result.get("event_type") or "").upper() == "MESH_ACTIVELINK_SWITCH":
            if not any(
                str(value or "").strip()
                for value in (current_name, current_mac, current_radio_mac)
            ):
                current = _no_active_link("switch_new_peer_missing")
            if details.get("old_active_link_missing"):
                previous = _no_active_link("switch_old_peer_missing")
        result.update(
            {
                "peer_name": current["peer_ap_name"],
                "peer_mac": normalize_mac(
                    result.get("peer_mac") or details.get("new_peer_mac")
                ),
                "previous_peer_name": previous["peer_ap_name"],
                "previous_peer_mac": normalize_mac(
                    result.get("previous_peer_mac") or details.get("old_peer_mac")
                ),
                "station": current["station"],
                "section": current["section"],
            }
        )
        details.update(
            {
                "peer_ap_id": current["peer_ap_id"],
                "peer_ap_name": current["peer_ap_name"],
                "peer_ap_mac": current["peer_ap_mac"],
                "identity_entity_id": current["identity_entity_id"],
                "identity_revision": current["identity_revision"],
                "identity_status": current["identity_status"],
                "identity_source": current["identity_source"],
                "identity_reason": current["identity_reason"],
                "previous_peer_ap_id": previous["peer_ap_id"],
                "previous_peer_ap_name": previous["peer_ap_name"],
                "previous_peer_ap_mac": previous["peer_ap_mac"],
                "previous_identity_entity_id": previous["identity_entity_id"],
                "previous_identity_revision": previous["identity_revision"],
                "previous_identity_status": previous["identity_status"],
                "previous_identity_source": previous["identity_source"],
                "previous_identity_reason": previous["identity_reason"],
                "peer_radio_mac": normalize_mac(
                    details.get("peer_radio_mac") or details.get("new_peer_radio_mac")
                ),
                "previous_peer_radio_mac": normalize_mac(
                    details.get("previous_peer_radio_mac")
                    or details.get("old_peer_radio_mac")
                ),
                "previous_station": previous["station"],
                "previous_section": previous["section"],
                "resolution_status": current["resolution_status"],
                "resolution_rule": current["resolution_rule"],
                "resolution_confidence": current["resolution_confidence"],
                "display_name_source": current["display_name_source"],
                "resolved_radio_id": current["resolved_radio_id"],
                "previous_resolution_status": previous["resolution_status"],
                "previous_resolution_rule": previous["resolution_rule"],
                "previous_resolution_confidence": previous["resolution_confidence"],
                "previous_display_name_source": previous["display_name_source"],
                "previous_resolved_radio_id": previous["resolved_radio_id"],
            }
        )
        result["details"] = details
        return result

    def _resolve_keys(self, keys: Iterable[str]) -> dict[str, ApIdentityMatch]:
        compact_keys = tuple(
            dict.fromkeys(
                key for value in keys if (key := normalize_mac_key(value)) is not None
            )
        )
        if not compact_keys:
            return {}
        with self._lock:
            self._refresh_revision_if_due()
            missing = [key for key in compact_keys if key not in self._matches]
            if missing:
                matches = self._query_missing(missing)
                revisions = {match.identity_revision for match in matches.values()}
                batch_revision = (
                    next(iter(revisions))
                    if len(revisions) == 1
                    else int(self._identity_revision or 0)
                )
                if (
                    self._identity_revision is not None
                    and batch_revision != self._identity_revision
                ):
                    self._matches.clear()
                self._identity_revision = batch_revision
                self._last_revision_checked_at = self._monotonic()
                self._matches.update(matches)
            return {
                key: self._matches[key] for key in compact_keys if key in self._matches
            }

    def _query_missing(self, keys: list[str]) -> Mapping[str, ApIdentityMatch]:
        if self.query_service is None:
            return _unavailable_matches(
                keys,
                identity_revision=self.identity_revision,
            )
        try:
            return self.query_service.resolve_peer_macs(
                keys,
                ap_role="trackside",
            )
        except (sqlite3.Error, OSError, RuntimeError):
            return _unavailable_matches(
                keys,
                identity_revision=self.identity_revision,
            )

    def _refresh_revision_if_due(self, *, force: bool = False) -> None:
        if self.query_service is None or self._identity_revision is None:
            return
        now = self._monotonic()
        if not force and (
            now - self._last_revision_checked_at < self._revision_check_interval_seconds
        ):
            return
        try:
            state = self.query_service.index_state() or {}
        except (sqlite3.Error, OSError, RuntimeError):
            self._last_revision_checked_at = now
            return
        revision = int(state.get("revision") or 0)
        if revision != self._identity_revision:
            self._matches.clear()
            self._identity_revision = revision
        self._last_revision_checked_at = now


def normalize_mac(value: object) -> str:
    return canonical_normalize_mac(value) or ""


def _observed_keys(mac: object, radio_mac: object) -> tuple[str, ...]:
    key = normalize_mac_key(radio_mac) or normalize_mac_key(mac)
    return (key,) if key else ()


def _match_result(
    name_text: str,
    mac: object,
    radio_mac: object,
    match: ApIdentityMatch,
) -> dict[str, object]:
    if not match.matched:
        return _unresolved_result(
            name_text,
            mac,
            radio_mac,
            ambiguous=match.status == "ambiguous",
            reason=match.unresolved_reason or "exact_alias_not_found",
            identity_revision=match.identity_revision,
        )
    return {
        "peer_ap_id": match.matched_entity_id,
        "peer_ap_name": match.effective_ap_name
        or name_text
        or normalize_mac(radio_mac)
        or normalize_mac(mac),
        "peer_ap_mac": normalize_mac(match.effective_ap_mac),
        "canonical_ap_mac": normalize_mac(match.effective_ap_mac),
        "station": match.station,
        "section": match.section,
        "resolution_status": "RADIO_BSSID",
        "resolution_rule": match.match_rule or match.matched_alias_type,
        "resolution_confidence": str(int(match.match_confidence or 0)),
        "identity_entity_id": match.matched_entity_id,
        "identity_revision": match.identity_revision,
        "identity_status": match.status,
        "identity_source": match.matched_source,
        "identity_reason": match.data_quality_warning or match.unresolved_reason,
        "display_name_source": _display_name_source(match),
        "resolved_radio_id": str(match.radio_id or ""),
    }


def _unresolved_result(
    name_text: str,
    mac: object,
    radio_mac: object,
    *,
    ambiguous: bool = False,
    reason: str,
    identity_revision: int = 0,
) -> dict[str, object]:
    return {
        "peer_ap_id": "",
        "peer_ap_name": name_text or normalize_mac(mac) or normalize_mac(radio_mac),
        "peer_ap_mac": "",
        "canonical_ap_mac": "",
        "station": "",
        "section": "",
        "resolution_status": "AMBIGUOUS" if ambiguous else "UNRESOLVED",
        "resolution_rule": "",
        "resolution_confidence": "",
        "identity_entity_id": "",
        "identity_revision": identity_revision,
        "identity_status": "ambiguous" if ambiguous else "unresolved",
        "identity_source": "",
        "identity_reason": reason,
        "display_name_source": "RAW_OBSERVATION",
        "resolved_radio_id": "",
    }


def _unavailable_matches(
    keys: Iterable[str],
    *,
    identity_revision: int,
) -> dict[str, ApIdentityMatch]:
    return {
        key: ApIdentityMatch(
            status="unresolved",
            identity_revision=identity_revision,
            query_mac=key,
            unresolved_reason="identity_query_unavailable",
        )
        for key in keys
    }


def _display_name_source(match: ApIdentityMatch) -> str:
    if match.matched_source == "ac_runtime":
        return "AC_AP_NAME"
    if match.matched_source in {"base_data", "legacy_cache"}:
        return "BASE_NAME"
    return "AP_IDENTITY_INDEX"


def _no_active_link(rule: str) -> dict[str, object]:
    return {
        "peer_ap_id": "",
        "peer_ap_name": "无主链路",
        "peer_ap_mac": "",
        "station": "",
        "section": "",
        "resolution_status": "NO_ACTIVE_LINK",
        "resolution_rule": rule,
        "resolution_confidence": "100",
        "identity_entity_id": "",
        "identity_revision": 0,
        "identity_status": "not_applicable",
        "identity_source": "",
        "identity_reason": rule,
        "display_name_source": "EVENT_STATE",
        "resolved_radio_id": "",
    }


__all__ = ["GroundApDisplayResolver", "normalize_mac"]
