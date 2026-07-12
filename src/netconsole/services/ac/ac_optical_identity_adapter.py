from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from netconsole.services.ap_identity import (
    ApIdentityCandidate,
    ApIdentityResolver,
    ApMatchResult,
    ApMatchStatus,
    ApObservation,
    normalize_ap_name,
    normalize_mac,
)

from .ac_identity_adapter import AcApIdentityAdapter
from .ac_identity_models import AcOpticalIdentityShadowItem, AcOpticalIdentityShadowReport


RECORD_TYPES = {"ap_side", "switch_side", "merged", "offline"}


class AcOpticalIdentityAdapter:
    def __init__(self, resolver: ApIdentityResolver | None = None) -> None:
        self.resolver = resolver or ApIdentityResolver()
        self.ac_identity = AcApIdentityAdapter(self.resolver)

    def build_optical_observation(
        self,
        row: Mapping[str, object],
        *,
        ac_uuid: str | None = None,
    ) -> ApObservation:
        return ApObservation(
            ap_uuid=_text(row.get("ap_uuid")),
            ap_id=_text(row.get("apid") or row.get("ap_id")),
            ap_mac=_normalize_optical_mac(row.get("ap_mac")),
            ap_name=normalize_ap_name(row.get("ap_name")),
            ac_uuid=_text(row.get("ac_device_uuid") or row.get("ac_uuid") or ac_uuid),
            site=normalize_ap_name(row.get("site") or row.get("site_name")),
            source="ac_optical",
            source_ref=_optical_ref(row, 0),
            raw=row,
        )

    def shadow_compare_optical_binding(
        self,
        optical_rows: Sequence[Mapping[str, object]],
        fit_ap_rows: Sequence[Mapping[str, object]],
        *,
        ac_uuid: str | None = None,
    ) -> AcOpticalIdentityShadowReport:
        candidate_rows = [
            {**dict(row), "ap_mac": _normalize_optical_mac(row.get("ap_mac")) or row.get("ap_mac")}
            for row in fit_ap_rows
        ]
        candidates = self.ac_identity.build_fit_ap_candidates(candidate_rows)
        items: list[AcOpticalIdentityShadowItem] = []
        for index, row in enumerate(optical_rows, start=1):
            record_type = _record_type(row)
            observation = self.build_optical_observation(row, ac_uuid=ac_uuid)
            old_ap_key = _old_ap_key(row, observation)
            interface_only = record_type == "switch_side" and old_ap_key is None
            warnings = _boundary_warnings(row, observation, interface_only)
            if interface_only:
                new_result = ApMatchResult(status=ApMatchStatus.UNRESOLVED)
            else:
                new_result = self.resolver.resolve(observation, candidates)
            warnings.extend(new_result.warnings)
            new_candidate_key = _candidate_key(new_result.candidate)
            identity_unchanged = bool(
                old_ap_key
                and new_result.status is ApMatchStatus.MATCHED
                and new_result.candidate is not None
                and _old_binding_matches_candidate(row, observation, new_result.candidate)
            )
            identity_changed = bool(
                (old_ap_key and not identity_unchanged)
                or (not old_ap_key and new_result.status is ApMatchStatus.MATCHED)
            )
            if old_ap_key and new_result.status is ApMatchStatus.UNRESOLVED:
                warnings.append("旧光衰绑定存在，新 resolver 未解析")
            elif old_ap_key and new_result.status is ApMatchStatus.AMBIGUOUS:
                warnings.append("旧光衰绑定存在，新 resolver 返回歧义")
            elif old_ap_key and identity_changed and new_result.status is ApMatchStatus.MATCHED:
                warnings.append("旧光衰绑定与新 resolver 候选不一致")
            items.append(
                AcOpticalIdentityShadowItem(
                    optical_ref=_optical_ref(row, index),
                    record_type=record_type,
                    old_ap_key=old_ap_key,
                    new_status=new_result.status.value,
                    new_candidate_key=new_candidate_key,
                    identity_changed=identity_changed,
                    identity_unchanged=identity_unchanged,
                    name_only_match=_is_name_only_match(observation, new_result),
                    mac_like_name=bool(_normalize_optical_mac(row.get("ap_name"))),
                    missing_ac_scope=not bool(observation.ac_uuid),
                    interface_only=interface_only,
                    evidence=new_result.evidence,
                    warnings=tuple(dict.fromkeys(warnings)),
                )
            )
        return self.summarize_optical_shadow_report(items)

    @staticmethod
    def summarize_optical_shadow_report(
        items: Sequence[AcOpticalIdentityShadowItem],
    ) -> AcOpticalIdentityShadowReport:
        rows = tuple(items)
        return AcOpticalIdentityShadowReport(
            total=len(rows),
            matched=sum(item.new_status == ApMatchStatus.MATCHED.value for item in rows),
            unresolved=sum(item.new_status == ApMatchStatus.UNRESOLVED.value for item in rows),
            ambiguous=sum(item.new_status == ApMatchStatus.AMBIGUOUS.value for item in rows),
            identity_unchanged=sum(item.identity_unchanged for item in rows),
            identity_changed=sum(item.identity_changed for item in rows),
            ap_side_records=sum(item.record_type == "ap_side" for item in rows),
            switch_side_records=sum(item.record_type == "switch_side" for item in rows),
            interface_only_records=sum(item.interface_only for item in rows),
            offline_records=sum(item.record_type == "offline" for item in rows),
            name_only_matches=sum(item.name_only_match for item in rows),
            mac_like_names=sum(item.mac_like_name for item in rows),
            missing_ac_scope=sum(item.missing_ac_scope for item in rows),
            warnings=tuple(dict.fromkeys(warning for item in rows for warning in item.warnings)),
            items=rows,
        )


def _record_type(row: Mapping[str, object]) -> str:
    explicit = str(row.get("record_type") or "").strip().lower()
    if explicit in RECORD_TYPES:
        return explicit
    if bool(row.get("is_ap_offline")) or str(row.get("ap_optical_status") or "").strip().lower() == "offline":
        return "offline"
    has_ap = any(row.get(key) not in (None, "") for key in ("ap_uuid", "apid", "ap_id", "ap_mac", "ap_name"))
    has_switch = any(
        row.get(key) not in (None, "")
        for key in ("neighbor_device_name", "neighbor_interface", "switch_uuid", "switch_interface")
    )
    if has_ap and has_switch:
        return "merged"
    if has_switch:
        return "switch_side"
    return "ap_side"


def _boundary_warnings(
    row: Mapping[str, object],
    observation: ApObservation,
    interface_only: bool,
) -> list[str]:
    warnings: list[str] = []
    if interface_only:
        warnings.append("仅有交换机接口上下文，交换机接口不是 AP identity")
    radio_values = [row.get(key) for key in ("radio_mac", "bssid", "bbssid") if row.get(key) not in (None, "")]
    if radio_values:
        warnings.append("Radio MAC/BSSID 不作为光衰 AP 写入匹配依据")
    if any(row.get(key) not in (None, "") for key in ("peer_mac", "peer_radio_mac")):
        warnings.append("Peer MAC 不参与光衰 AP 写入匹配")
    ap_mac = _normalize_optical_mac(observation.ap_mac)
    if ap_mac and any(_normalize_optical_mac(value) == ap_mac for value in radio_values):
        warnings.append("AP MAC 与 Radio MAC/BSSID 字段相同，存在语义混用风险")
    if not observation.ac_uuid:
        warnings.append("缺少 AC 作用域，跨 AC 候选可能产生歧义")
    return warnings


def _old_ap_key(row: Mapping[str, object], observation: ApObservation) -> str | None:
    explicit = _text(row.get("old_ap_key"))
    if explicit:
        return explicit
    if observation.ap_uuid:
        return f"uuid:{observation.ap_uuid.casefold()}"
    if observation.ac_uuid and observation.ap_id:
        return f"apid:{observation.ac_uuid.casefold()}:{observation.ap_id.casefold()}"
    ap_mac = _normalize_optical_mac(observation.ap_mac)
    if ap_mac:
        return f"mac:{ap_mac}"
    if observation.ap_name:
        prefix = f"{observation.ac_uuid.casefold()}:" if observation.ac_uuid else ""
        return f"name:{prefix}{observation.ap_name.casefold()}"
    return None


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


def _old_binding_matches_candidate(
    row: Mapping[str, object],
    observation: ApObservation,
    candidate: ApIdentityCandidate,
) -> bool:
    explicit = _text(row.get("old_ap_key"))
    if explicit:
        return explicit.casefold() == str(_candidate_key(candidate) or "").casefold()
    identity = candidate.identity
    if observation.ap_uuid:
        return observation.ap_uuid.casefold() == str(identity.ap_uuid or "").casefold()
    if observation.ac_uuid and observation.ap_id:
        return (
            observation.ac_uuid.casefold() == str(identity.ac_uuid or "").casefold()
            and observation.ap_id.casefold() == str(identity.ap_id or "").casefold()
        )
    if observation.ap_mac:
        return _normalize_optical_mac(observation.ap_mac) == normalize_mac(identity.ap_mac)
    if observation.ap_name:
        same_name = observation.ap_name.casefold() == str(identity.ap_name or "").casefold()
        return same_name and (not observation.ac_uuid or observation.ac_uuid.casefold() == str(identity.ac_uuid or "").casefold())
    return False


def _is_name_only_match(observation: ApObservation, result: ApMatchResult) -> bool:
    return bool(
        result.status is ApMatchStatus.MATCHED
        and observation.ap_name
        and not any((observation.ap_uuid, observation.ap_id, observation.ap_mac))
    )


def _optical_ref(row: Mapping[str, object], index: int) -> str:
    if row.get("id") not in (None, ""):
        return f"row:{row.get('id')}"
    for key, prefix in (("ap_uuid", "uuid"), ("ap_mac", "mac"), ("ap_name", "name")):
        value = _text(row.get(key))
        if value:
            return f"{prefix}:{value}"
    switch_name = _text(row.get("neighbor_device_name") or row.get("switch_uuid"))
    interface = _text(row.get("neighbor_interface") or row.get("switch_interface"))
    if switch_name or interface:
        return f"switch:{switch_name or '-'}:{interface or '-'}"
    return f"index:{index}"


def _text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_optical_mac(value: object) -> str | None:
    normalized = normalize_mac(value)
    if normalized:
        return normalized
    text = str(value or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}", text):
        return normalize_mac(text.replace("-", ""))
    return None
