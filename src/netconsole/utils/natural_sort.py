from __future__ import annotations

import re


def natural_text_key(value: object) -> tuple[object, ...]:
    parts = re.split(r"(\d+)", str(value or "").strip().casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


TRAIN_NUMBER_PATTERNS = (
    re.compile(r"LC\s*0*(?P<number>\d{1,3})(?!\d)", re.IGNORECASE),
    re.compile(r"\u5217\u8f66\s*0*(?P<number>\d{1,3})(?!\d)", re.IGNORECASE),
    re.compile(r"(?<!\d)0*(?P<number>\d{1,3})\s*\u8f66"),
)


def extract_train_number(*values: object) -> int | None:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if re.fullmatch(r"0*\d{1,3}", text):
            return int(text)
        for pattern in TRAIN_NUMBER_PATTERNS:
            match = pattern.search(text)
            if match:
                return int(match.group("number"))
    return None


def train_natural_sort_key(*values: object) -> tuple[object, ...]:
    text = " ".join(str(value or "").strip() for value in values if str(value or "").strip())
    number = extract_train_number(*values)
    if number is None:
        return (1, natural_text_key(text), text.casefold())
    return (0, number, natural_text_key(text), text.casefold())
