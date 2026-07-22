from __future__ import annotations

import re
from dataclasses import dataclass

from netconsole.services.vehicle_mr_online import normalize_train_no, parse_train_identity


@dataclass(frozen=True)
class CanonicalTrainIdentity:
    canonical_train_id: str
    train_no: str
    display_name: str
    aliases: tuple[str, ...] = ()


def normalize_train_identity(*values: object) -> CanonicalTrainIdentity:
    """Normalize user-facing train labels and formal ids to one stable train key."""

    originals = [str(value or "").strip() for value in values if str(value or "").strip()]
    train_no = next((normalize_train_no(value) for value in originals if normalize_train_no(value)), "")
    if not train_no:
        for value in originals:
            identity = parse_train_identity(value)
            if identity is not None and identity.train_no:
                train_no = identity.train_no
                break
    if train_no:
        canonical = f"train:{train_no}"
        display_name = next(
            (
                value
                for value in originals
                if value.startswith("列车") or value.endswith("车")
            ),
            f"列车{train_no}",
        )
        aliases = _aliases_for_train(train_no, originals)
        return CanonicalTrainIdentity(canonical, train_no, display_name, aliases)

    fallback = _fallback_key(originals[0] if originals else "")
    display_name = originals[0] if originals else ""
    return CanonicalTrainIdentity(fallback, "", display_name, tuple(dict.fromkeys(originals)))


def canonical_train_id_for(*values: object) -> str:
    return normalize_train_identity(*values).canonical_train_id


def train_identity_aliases(*values: object) -> set[str]:
    identity = normalize_train_identity(*values)
    return {_key(value) for value in identity.aliases if _key(value)}


def train_identity_matches(left: tuple[object, ...] | list[object] | set[object], right: tuple[object, ...] | list[object] | set[object]) -> bool:
    left_identity = normalize_train_identity(*left)
    right_identity = normalize_train_identity(*right)
    if left_identity.canonical_train_id and right_identity.canonical_train_id:
        return left_identity.canonical_train_id == right_identity.canonical_train_id
    return bool(train_identity_aliases(*left) & train_identity_aliases(*right))


def _aliases_for_train(train_no: str, originals: list[str]) -> tuple[str, ...]:
    short_no = str(int(train_no)) if train_no.isdigit() else train_no.lstrip("0") or train_no
    aliases = [
        *originals,
        train_no,
        short_no,
        f"{train_no}车",
        f"{short_no}车",
        f"列车{train_no}",
        f"列车{short_no}",
        f"train-{train_no}",
        f"train-{short_no}",
        f"train:{train_no}",
        f"LC{train_no}",
        f"lc{train_no}",
        f"NBL12-LC{train_no}",
    ]
    return tuple(dict.fromkeys(value for value in aliases if str(value or "").strip()))


def _fallback_key(value: str) -> str:
    key = _key(value)
    return f"train:{key}" if key else ""


def _key(value: object) -> str:
    return re.sub(r"[\s_\-/：:]+", "", str(value or "").strip().casefold())


__all__ = [
    "CanonicalTrainIdentity",
    "canonical_train_id_for",
    "normalize_train_identity",
    "train_identity_aliases",
    "train_identity_matches",
]
