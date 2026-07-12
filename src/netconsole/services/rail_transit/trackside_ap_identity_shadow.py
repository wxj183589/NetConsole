from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from netconsole.services.ap_identity import (
    ApIdentityCandidate,
    ApIdentityResolver,
    ApMatchEvidence,
    ApMatchResult,
    ApMatchStatus,
    ApObservation,
    candidate_from_fit_ap_resource_row,
    normalize_ap_name,
    normalize_mac,
)


@dataclass(frozen=True)
class TracksideIdentityShadowItem:
    row_ref: str
    old_identity_key: str | None
    old_ap_uuid: str | None
    old_ap_mac: str | None
    old_ap_name: str | None
    new_status: str
    new_candidate_key: str | None
    identity_unchanged: bool
    identity_changed: bool
    name_only_match: bool
    mac_like_name: bool
    missing_ac_scope: bool
    interface_only: bool
    lldp_only: bool
    optical_fallback: bool
    evidence: tuple[ApMatchEvidence, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "row_ref": self.row_ref,
            "old_identity_key": self.old_identity_key,
            "old_ap_uuid": self.old_ap_uuid,
            "old_ap_mac": self.old_ap_mac,
            "old_ap_name": self.old_ap_name,
            "new_status": self.new_status,
            "new_candidate_key": self.new_candidate_key,
            "identity_unchanged": self.identity_unchanged,
            "identity_changed": self.identity_changed,
            "name_only_match": self.name_only_match,
            "mac_like_name": self.mac_like_name,
            "missing_ac_scope": self.missing_ac_scope,
            "interface_only": self.interface_only,
            "lldp_only": self.lldp_only,
            "optical_fallback": self.optical_fallback,
            "evidence": [asdict(item) for item in self.evidence],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class TracksideIdentityShadowReport:
    available: bool = True
    total: int = 0
    matched: int = 0
    unresolved: int = 0
    ambiguous: int = 0
    identity_unchanged: int = 0
    identity_changed: int = 0
    name_only_matches: int = 0
    mac_like_names: int = 0
    missing_ac_scope: int = 0
    interface_only_records: int = 0
    lldp_only_records: int = 0
    optical_fallback_records: int = 0
    warnings: tuple[str, ...] = ()
    items: tuple[TracksideIdentityShadowItem, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "available": self.available,
            "total": self.total,
            "matched": self.matched,
            "unresolved": self.unresolved,
            "ambiguous": self.ambiguous,
            "identity_unchanged": self.identity_unchanged,
            "identity_changed": self.identity_changed,
            "name_only_matches": self.name_only_matches,
            "mac_like_names": self.mac_like_names,
            "missing_ac_scope": self.missing_ac_scope,
            "interface_only_records": self.interface_only_records,
            "lldp_only_records": self.lldp_only_records,
            "optical_fallback_records": self.optical_fallback_records,
            "warnings": list(self.warnings),
            "items": [item.to_payload() for item in self.items],
        }


class TracksideApIdentityShadowService:
    def __init__(self, resolver: ApIdentityResolver | None = None) -> None:
        self.resolver = resolver or ApIdentityResolver()

    def build_candidates_from_fit_ap_resources(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> tuple[ApIdentityCandidate, ...]:
        candidates: list[ApIdentityCandidate] = []
        for row in rows:
            raw = dict(row)
            raw["trackside_ap_mac_raw"] = raw.get("ap_mac")
            raw["ap_mac"] = _normalize_trackside_mac(raw.get("ap_mac")) or raw.get("ap_mac")
            candidates.append(candidate_from_fit_ap_resource_row(raw))
        return tuple(candidates)

    def build_observation_from_trackside_row(self, row: Mapping[str, object]) -> ApObservation:
        return _observation(row, source="trackside_row")

    def build_observation_from_detail_match(self, row: Mapping[str, object]) -> ApObservation:
        return _observation(row, source="trackside_detail")

    def shadow_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        fit_ap_resources: Sequence[Mapping[str, object]],
    ) -> TracksideIdentityShadowReport:
        candidates = self.build_candidates_from_fit_ap_resources(fit_ap_resources)
        items = [self._shadow_row(row, candidates, index) for index, row in enumerate(rows, start=1)]
        return self.summarize_report(items)

    def shadow_detail_matches(
        self,
        old_matches: Sequence[Mapping[str, object]],
        fit_ap_resources: Sequence[Mapping[str, object]],
        request: Mapping[str, object],
    ) -> TracksideIdentityShadowReport:
        candidates = self.build_candidates_from_fit_ap_resources(fit_ap_resources)
        observation = self.build_observation_from_detail_match(request)
        new_result = self.resolver.resolve(observation, candidates)
        matches = tuple(old_matches)
        first = matches[0] if matches else {}
        old_candidate_keys = {
            key
            for match in matches
            if (key := _candidate_key(candidate_from_fit_ap_resource_row(_candidate_row(match))))
        }
        new_candidate_key = _candidate_key(new_result.candidate)
        identity_unchanged = bool(
            len(matches) == 1
            and new_result.status is ApMatchStatus.MATCHED
            and new_candidate_key in old_candidate_keys
        )
        identity_changed = bool(
            (matches and not identity_unchanged)
            or (not matches and new_result.status is ApMatchStatus.MATCHED)
        )
        warnings = [*new_result.warnings]
        if len(matches) > 1:
            warnings.append("旧详情 resolver 返回多个候选；原选择行为保持不变")
        _append_comparison_warnings(warnings, bool(matches), new_result.status, identity_changed)
        item = TracksideIdentityShadowItem(
            row_ref="detail:request",
            old_identity_key=(
                sorted(old_candidate_keys)[0]
                if old_candidate_keys
                else (f"matches:{len(matches)}" if matches else None)
            ),
            old_ap_uuid=_text(first.get("ap_uuid")),
            old_ap_mac=_normalize_trackside_mac(first.get("ap_mac")),
            old_ap_name=normalize_ap_name(first.get("ap_name")),
            new_status=new_result.status.value,
            new_candidate_key=new_candidate_key,
            identity_unchanged=identity_unchanged,
            identity_changed=identity_changed,
            name_only_match=_is_name_only(observation, new_result),
            mac_like_name=bool(_normalize_trackside_mac(request.get("ap_name"))),
            missing_ac_scope=not bool(observation.ac_uuid),
            interface_only=False,
            lldp_only=False,
            optical_fallback=False,
            evidence=(*new_result.evidence, *_context_evidence(request)),
            warnings=tuple(dict.fromkeys(warnings)),
        )
        return self.summarize_report((item,))

    def _shadow_row(
        self,
        row: Mapping[str, object],
        candidates: Sequence[ApIdentityCandidate],
        index: int,
    ) -> TracksideIdentityShadowItem:
        observation = self.build_observation_from_trackside_row(row)
        old_identity_key = _old_identity_key(row)
        has_old_identity = bool(old_identity_key)
        interface = _interface_value(row)
        lldp_mac = _lldp_neighbor_mac(row)
        interface_only = bool(interface and not has_old_identity and not lldp_mac)
        lldp_only = bool(lldp_mac and not has_old_identity)
        optical_fallback = _is_optical_fallback(row)
        new_result = self.resolver.resolve(observation, candidates)
        new_candidate_key = _candidate_key(new_result.candidate)
        identity_unchanged = bool(
            has_old_identity
            and new_result.status is ApMatchStatus.MATCHED
            and new_result.candidate is not None
            and _old_binding_matches_candidate(row, new_result.candidate)
        )
        identity_changed = bool(
            (has_old_identity and not identity_unchanged)
            or (not has_old_identity and new_result.status is ApMatchStatus.MATCHED)
        )
        warnings = [*new_result.warnings]
        if interface_only:
            warnings.append("仅有交换机接口/端口；topology identity 不参与 AP 匹配")
        if lldp_mac:
            warnings.append("LLDP neighbor MAC 仅作为 observation evidence，不替换旧轨旁结果")
        if any(row.get(key) not in (None, "") for key in ("radio_mac", "bssid", "bbssid")):
            warnings.append("Radio MAC/BSSID 不作为轨旁 AP MAC 匹配输入")
        _append_comparison_warnings(warnings, has_old_identity, new_result.status, identity_changed)
        return TracksideIdentityShadowItem(
            row_ref=_row_ref(row, index),
            old_identity_key=old_identity_key,
            old_ap_uuid=_text(row.get("ap_uuid")),
            old_ap_mac=_normalize_trackside_mac(row.get("ap_mac")),
            old_ap_name=normalize_ap_name(row.get("ap_name")),
            new_status=new_result.status.value,
            new_candidate_key=new_candidate_key,
            identity_unchanged=identity_unchanged,
            identity_changed=identity_changed,
            name_only_match=_is_name_only(observation, new_result),
            mac_like_name=bool(_normalize_trackside_mac(row.get("ap_name"))),
            missing_ac_scope=not bool(observation.ac_uuid),
            interface_only=interface_only,
            lldp_only=lldp_only,
            optical_fallback=optical_fallback,
            evidence=(*new_result.evidence, *_context_evidence(row)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def summarize_report(items: Sequence[TracksideIdentityShadowItem]) -> TracksideIdentityShadowReport:
        rows = tuple(items)
        return TracksideIdentityShadowReport(
            total=len(rows),
            matched=sum(item.new_status == ApMatchStatus.MATCHED.value for item in rows),
            unresolved=sum(item.new_status == ApMatchStatus.UNRESOLVED.value for item in rows),
            ambiguous=sum(item.new_status == ApMatchStatus.AMBIGUOUS.value for item in rows),
            identity_unchanged=sum(item.identity_unchanged for item in rows),
            identity_changed=sum(item.identity_changed for item in rows),
            name_only_matches=sum(item.name_only_match for item in rows),
            mac_like_names=sum(item.mac_like_name for item in rows),
            missing_ac_scope=sum(item.missing_ac_scope for item in rows),
            interface_only_records=sum(item.interface_only for item in rows),
            lldp_only_records=sum(item.lldp_only for item in rows),
            optical_fallback_records=sum(item.optical_fallback for item in rows),
            warnings=tuple(dict.fromkeys(warning for item in rows for warning in item.warnings)),
            items=rows,
        )


def unavailable_trackside_identity_shadow(total: int, exc: Exception) -> dict[str, object]:
    return TracksideIdentityShadowReport(
        available=False,
        total=total,
        warnings=(f"trackside identity shadow 不可用：{type(exc).__name__}: {exc}",),
    ).to_payload()


def _observation(row: Mapping[str, object], *, source: str) -> ApObservation:
    return ApObservation(
        ap_uuid=_text(row.get("ap_uuid")),
        ap_id=_text(row.get("apid") or row.get("ap_id")),
        ap_mac=_normalize_trackside_mac(row.get("ap_mac")),
        ap_name=normalize_ap_name(row.get("ap_name")),
        peer_mac=_lldp_neighbor_mac(row),
        ac_uuid=_text(row.get("ac_device_uuid") or row.get("ac_uuid")),
        device_uuid=_text(row.get("device_uuid") or row.get("switch_uuid")),
        interface_name=_interface_value(row),
        site=normalize_ap_name(row.get("site") or row.get("site_name")),
        station=normalize_ap_name(row.get("station") or row.get("station_name")),
        section=normalize_ap_name(row.get("section") or row.get("section_name")),
        mileage=_text(row.get("mileage") or row.get("mileage_text")),
        source=source,
        source_ref=_row_ref(row, 0),
        raw=row,
    )


def _candidate_row(row: Mapping[str, object]) -> dict[str, object]:
    result = dict(row)
    result["ap_mac"] = _normalize_trackside_mac(row.get("ap_mac")) or row.get("ap_mac")
    return result


def _old_identity_key(row: Mapping[str, object]) -> str | None:
    ap_uuid = _text(row.get("ap_uuid"))
    if ap_uuid:
        return f"uuid:{ap_uuid.casefold()}"
    serial = _text(row.get("serial_number") or row.get("serial"))
    if serial and serial.casefold() not in {"-", "n/a"}:
        return f"serial:{serial.casefold()}"
    ap_mac = _normalize_trackside_mac(row.get("ap_mac") or row.get("mac"))
    if ap_mac:
        return f"mac:{ap_mac}"
    ap_name = normalize_ap_name(row.get("ap_name"))
    return f"name:{ap_name.casefold()}" if ap_name else None


def _candidate_key(candidate: ApIdentityCandidate | None) -> str | None:
    if candidate is None:
        return None
    identity = candidate.identity
    if identity.ap_uuid:
        return f"uuid:{identity.ap_uuid.casefold()}"
    if identity.ac_uuid and identity.ap_id:
        return f"apid:{identity.ac_uuid.casefold()}:{identity.ap_id.casefold()}"
    ap_mac = normalize_mac(identity.ap_mac)
    if ap_mac:
        return f"mac:{ap_mac}"
    ap_name = normalize_ap_name(identity.ap_name)
    if ap_name:
        prefix = f"{identity.ac_uuid.casefold()}:" if identity.ac_uuid else ""
        return f"name:{prefix}{ap_name.casefold()}"
    return None


def _old_binding_matches_candidate(row: Mapping[str, object], candidate: ApIdentityCandidate) -> bool:
    identity = candidate.identity
    ap_uuid = _text(row.get("ap_uuid"))
    if ap_uuid:
        return ap_uuid.casefold() == str(identity.ap_uuid or "").casefold()
    serial = _text(row.get("serial_number") or row.get("serial"))
    if serial:
        return serial.casefold() == str(identity.serial_number or "").casefold()
    ap_mac = _normalize_trackside_mac(row.get("ap_mac") or row.get("mac"))
    if ap_mac:
        return ap_mac == normalize_mac(identity.ap_mac)
    ap_name = normalize_ap_name(row.get("ap_name"))
    if ap_name:
        same_name = ap_name.casefold() == str(identity.ap_name or "").casefold()
        ac_uuid = _text(row.get("ac_device_uuid") or row.get("ac_uuid"))
        return same_name and (not ac_uuid or ac_uuid.casefold() == str(identity.ac_uuid or "").casefold())
    return False


def _append_comparison_warnings(
    warnings: list[str],
    old_matched: bool,
    new_status: ApMatchStatus,
    identity_changed: bool,
) -> None:
    if old_matched and new_status is ApMatchStatus.UNRESOLVED:
        warnings.append("旧轨旁逻辑已有 AP 结果，新 resolver 未解析")
    elif old_matched and new_status is ApMatchStatus.AMBIGUOUS:
        warnings.append("旧轨旁逻辑已有 AP 结果，新 resolver 返回歧义")
    elif not old_matched and new_status is ApMatchStatus.MATCHED:
        warnings.append("旧轨旁逻辑未绑定，新 resolver 发现候选；仅记录，不改变结果")
    elif old_matched and identity_changed and new_status is ApMatchStatus.MATCHED:
        warnings.append("旧轨旁 AP 与新 resolver 候选不一致")


def _context_evidence(row: Mapping[str, object]) -> tuple[ApMatchEvidence, ...]:
    evidence: list[ApMatchEvidence] = []
    for field, value, reason in (
        ("device_uuid", row.get("device_uuid") or row.get("switch_uuid"), "交换机只作为 topology evidence"),
        ("interface_name", _interface_value(row), "接口/端口不参与 AP identity 匹配"),
        ("lldp_neighbor_mac", _lldp_neighbor_mac(row), "LLDP MAC 只作为 observation evidence"),
    ):
        text = _text(value)
        if text:
            evidence.append(ApMatchEvidence(field, text, "", 0, reason))
    return tuple(evidence)


def _is_name_only(observation: ApObservation, result: ApMatchResult) -> bool:
    return bool(
        result.status is ApMatchStatus.MATCHED
        and observation.ap_name
        and not any((observation.ap_uuid, observation.ap_id, observation.ap_mac))
    )


def _is_optical_fallback(row: Mapping[str, object]) -> bool:
    source = str(row.get("identity_source") or row.get("ap_match_source") or row.get("data_source") or "").casefold()
    return bool(row.get("optical_fallback")) or "optical_fallback" in source


def _lldp_neighbor_mac(row: Mapping[str, object]) -> str | None:
    return _normalize_trackside_mac(
        row.get("lldp_neighbor_mac")
        or row.get("lldp_neighbor_mac_normalized")
        or row.get("neighbor_mac")
    )


def _interface_value(row: Mapping[str, object]) -> str | None:
    return _text(row.get("interface_name") or row.get("interface") or row.get("port") or row.get("uplink_port"))


def _row_ref(row: Mapping[str, object], index: int) -> str:
    site = _text(row.get("site") or row.get("station"))
    switch = _text(row.get("device_uuid") or row.get("switch_uuid") or row.get("device_name"))
    interface = _interface_value(row)
    if any((site, switch, interface)):
        return f"topology:{site or '-'}:{switch or '-'}:{interface or '-'}"
    identity = _old_identity_key(row)
    return identity or f"index:{index}"


def _normalize_trackside_mac(value: object) -> str | None:
    normalized = normalize_mac(value)
    if normalized:
        return normalized
    text = str(value or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}", text):
        return normalize_mac(text.replace("-", ""))
    return None


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
