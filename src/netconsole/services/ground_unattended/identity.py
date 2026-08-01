from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.rail_transit.train_identity import (
    canonical_train_id_for,
    train_identity_matches,
)


_QUERY_IDENTITY_PREFIX = "gpq1."
_MR_ROLE_PATTERN = re.compile(r"(?:^|[-_\s])(CT|CW)(?:$|[-_\s])", re.IGNORECASE)


class GroundIdentityResolutionError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GroundResolvedPingIdentity:
    run_id: str
    target_ip: str
    requested_train_id: str
    requested_mr_id: str
    query_identity: str
    train_aliases: tuple[str, ...]
    mr_aliases: tuple[str, ...]
    registered_train_ids: tuple[str, ...]
    registered_mr_ids: tuple[str, ...]
    mr_roles: tuple[str, ...]
    expected_target_signatures: tuple[tuple[str, str], ...]

    @property
    def registry_train_id(self) -> str:
        return (
            self.registered_train_ids[0]
            if len(self.registered_train_ids) == 1
            else ""
        )

    @property
    def registry_device_uuid(self) -> str:
        if self.target_ip or not self.requested_mr_id:
            return ""
        return (
            self.registered_mr_ids[0]
            if len(self.registered_mr_ids) == 1
            else self.requested_mr_id
        )

    @property
    def registry_mr_role(self) -> str:
        return self.mr_roles[0] if len(self.mr_roles) == 1 else ""

    def matches_record(self, item: Mapping[str, Any]) -> bool:
        record_target_ip = str(item.get("target_ip") or "").strip()
        if self.target_ip:
            return record_target_ip == self.target_ip
        if self.requested_train_id and not train_identity_matches(
            self.train_aliases,
            _record_train_values(item),
        ):
            return False
        if not self.requested_mr_id:
            return True
        record_mr_values = {
            _identity_key(item.get("mr_id")),
            _identity_key(item.get("device_uuid")),
            _identity_key(item.get("mr_name")),
            _identity_key(item.get("mr_position_code")),
            _identity_key(item.get("mr_role")),
        }
        return bool(
            {value for value in record_mr_values if value}
            & set(self.mr_aliases)
        )

    def target_signature(self, item: Mapping[str, Any]) -> tuple[str, str]:
        train_key = canonical_train_id_for(*_record_train_values(item))
        role = _normalize_role(
            item.get("mr_position_code"),
            item.get("mr_role"),
            item.get("mr_name"),
        )
        return train_key, role

    def assert_target_signature(
        self,
        signature: tuple[str, str],
        observed: set[tuple[str, str]],
    ) -> None:
        if not self.target_ip:
            return
        normalized = tuple(str(value or "") for value in signature)
        expected = set(self.expected_target_signatures)
        if expected and all(
            _signatures_conflict(normalized, value)
            for value in expected
        ):
            raise GroundIdentityResolutionError(
                "同一运行内目标 IP 对应了冲突的列车或 MR 端位",
                code="PING_TARGET_IDENTITY_CONFLICT",
            )
        if any(
            _signatures_conflict(normalized, value)
            for value in observed
        ):
            raise GroundIdentityResolutionError(
                "同一运行内目标 IP 对应了多个列车或 MR 端位",
                code="PING_TARGET_IDENTITY_CONFLICT",
            )
        observed.add(normalized)


class GroundDeviceIdentityResolver:
    """Resolve stable run/target identity without fuzzy device-name matching."""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository

    def resolve_ping(
        self,
        *,
        run_id: str,
        train_id: str = "",
        mr_id: str = "",
        target_ip: str = "",
        query_identity: str = "",
    ) -> GroundResolvedPingIdentity:
        resolved_run_id = str(run_id or "").strip()
        resolved_target_ip = str(target_ip or "").strip()
        if query_identity:
            token_run_id, token_target_ip = decode_ping_query_identity(
                query_identity
            )
            if resolved_run_id and resolved_run_id != token_run_id:
                raise GroundIdentityResolutionError(
                    "稳定查询身份与请求运行不一致",
                    code="PING_IDENTITY_MISMATCH",
                )
            if resolved_target_ip and resolved_target_ip != token_target_ip:
                raise GroundIdentityResolutionError(
                    "稳定查询身份与目标 IP 不一致",
                    code="PING_IDENTITY_MISMATCH",
                )
            resolved_run_id = token_run_id
            resolved_target_ip = token_target_ip
        inventory = self.repository.list_inventory(include_removed=True)
        endpoints = [
            {
                **dict(endpoint),
                "train_no": str(train.get("train_no") or ""),
                "train_name": str(train.get("train_name") or ""),
            }
            for train in inventory
            for endpoint in list(train.get("endpoints") or [])
        ]
        target_endpoints = [
            endpoint
            for endpoint in endpoints
            if resolved_target_ip
            and str(endpoint.get("management_ip") or "").strip()
            == resolved_target_ip
        ]
        mr_endpoints = [
            endpoint
            for endpoint in endpoints
            if mr_id
            and _identity_key(mr_id)
            in {
                _identity_key(endpoint.get("device_uuid")),
                _identity_key(endpoint.get("device_id")),
                _identity_key(endpoint.get("device_name")),
                _identity_key(endpoint.get("source_hostname")),
            }
        ]
        relevant_endpoints = _deduplicate_endpoints(
            [*target_endpoints, *mr_endpoints]
        )

        train_values: list[object] = [train_id]
        mr_values: list[object] = [mr_id]
        roles: set[str] = set()
        expected_signatures: set[tuple[str, str]] = set()
        for endpoint in relevant_endpoints:
            endpoint_train_values = (
                endpoint.get("train_id"),
                endpoint.get("train_no"),
                endpoint.get("train_name"),
                endpoint.get("device_name"),
                endpoint.get("source_hostname"),
            )
            train_values.extend(endpoint_train_values)
            mr_values.extend(
                (
                    endpoint.get("device_uuid"),
                    endpoint.get("device_id"),
                    endpoint.get("device_name"),
                    endpoint.get("source_hostname"),
                    endpoint.get("mr_role"),
                    endpoint.get("management_ip"),
                )
            )
            role = _normalize_role(
                endpoint.get("mr_role"),
                endpoint.get("device_name"),
                endpoint.get("source_hostname"),
            )
            if role:
                roles.add(role)
            if resolved_target_ip:
                expected_signatures.add(
                    (
                        canonical_train_id_for(*endpoint_train_values),
                        role,
                    )
                )
        if len(
            {
                value
                for value in expected_signatures
                if any(part for part in value)
            }
        ) > 1:
            raise GroundIdentityResolutionError(
                "当前清单中同一目标 IP 对应了多个列车或 MR 端位",
                code="PING_TARGET_IDENTITY_CONFLICT",
            )

        raw_files = (
            [
                row
                for row in self.repository.list_raw_files_for_run(
                    resolved_run_id
                )
                if str(row.get("data_type") or "") == "ping"
            ]
            if resolved_run_id
            else []
        )
        train_alias_values = tuple(
            dict.fromkeys(
                str(value or "").strip()
                for value in train_values
                if str(value or "").strip()
            )
        )
        registered_train_ids = tuple(
            sorted(
                {
                    str(row.get("train_id") or "")
                    for row in raw_files
                    if str(row.get("train_id") or "")
                    and train_alias_values
                    and train_identity_matches(
                            train_alias_values,
                            (str(row.get("train_id") or ""),),
                    )
                }
            )
        )
        candidate_files = [
            row
            for row in raw_files
            if (
                not registered_train_ids
                or str(row.get("train_id") or "") in registered_train_ids
            )
            and (
                not roles
                or str(row.get("mr_role") or "").upper() in roles
            )
        ]
        if not resolved_target_ip and mr_id:
            exact_mr_files = [
                row
                for row in candidate_files
                if _identity_key(row.get("device_uuid"))
                in {
                    _identity_key(value)
                    for value in mr_values
                    if _identity_key(value)
                }
            ]
            if exact_mr_files:
                candidate_files = exact_mr_files
        registered_mr_ids = tuple(
            sorted(
                {
                    str(row.get("device_uuid") or "")
                    for row in candidate_files
                    if str(row.get("device_uuid") or "")
                }
            )
        )
        mr_values.extend(registered_mr_ids)
        mr_aliases = tuple(
            sorted(
                {
                    _identity_key(value)
                    for value in mr_values
                    if _identity_key(value)
                }
            )
        )
        query_token = (
            encode_ping_query_identity(
                resolved_run_id,
                resolved_target_ip,
            )
            if resolved_target_ip
            else ""
        )
        return GroundResolvedPingIdentity(
            run_id=resolved_run_id,
            target_ip=resolved_target_ip,
            requested_train_id=str(train_id or "").strip(),
            requested_mr_id=str(mr_id or "").strip(),
            query_identity=query_token,
            train_aliases=train_alias_values,
            mr_aliases=mr_aliases,
            registered_train_ids=registered_train_ids,
            registered_mr_ids=registered_mr_ids,
            mr_roles=tuple(sorted(roles)),
            expected_target_signatures=tuple(sorted(expected_signatures)),
        )


def encode_ping_query_identity(run_id: str, target_ip: str) -> str:
    payload = json.dumps(
        {
            "run_id": str(run_id or "").strip(),
            "target_ip": str(target_ip or "").strip(),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{_QUERY_IDENTITY_PREFIX}{encoded}"


def decode_ping_query_identity(value: str) -> tuple[str, str]:
    token = str(value or "").strip()
    if not token.startswith(_QUERY_IDENTITY_PREFIX) or len(token) > 1000:
        raise GroundIdentityResolutionError(
            "稳定查询身份格式无效",
            code="PING_IDENTITY_MISMATCH",
        )
    encoded = token.removeprefix(_QUERY_IDENTITY_PREFIX)
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GroundIdentityResolutionError(
            "稳定查询身份格式无效",
            code="PING_IDENTITY_MISMATCH",
        ) from exc
    if not isinstance(payload, dict):
        raise GroundIdentityResolutionError(
            "稳定查询身份格式无效",
            code="PING_IDENTITY_MISMATCH",
        )
    run_id = str(payload.get("run_id") or "").strip()
    target_ip = str(payload.get("target_ip") or "").strip()
    if not run_id or not target_ip:
        raise GroundIdentityResolutionError(
            "稳定查询身份缺少运行或目标 IP",
            code="PING_IDENTITY_MISMATCH",
        )
    return run_id, target_ip


def _record_train_values(item: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        item.get("train_id"),
        item.get("train_no"),
        item.get("mr_name"),
    )


def _normalize_role(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text.upper() in {"CT", "CW"}:
            return text.upper()
        match = _MR_ROLE_PATTERN.search(text)
        if match:
            return match.group(1).upper()
    return ""


def _identity_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _deduplicate_endpoints(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("device_uuid") or ""),
            str(row.get("train_id") or ""),
            str(row.get("mr_role") or ""),
            str(row.get("management_ip") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _signatures_conflict(
    left: tuple[str, str],
    right: tuple[str, str],
) -> bool:
    left_train, left_role = left
    right_train, right_role = right
    return bool(
        left_train
        and right_train
        and left_train != right_train
    ) or bool(
        left_role
        and right_role
        and left_role != right_role
    )


__all__ = [
    "GroundDeviceIdentityResolver",
    "GroundIdentityResolutionError",
    "GroundResolvedPingIdentity",
    "decode_ping_query_identity",
    "encode_ping_query_identity",
]
