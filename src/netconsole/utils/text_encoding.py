from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
H3C_DEVICE_ENCODINGS = ("gb2312", "gbk", "gb18030", "utf-8", "utf-8-sig")
FILE_ENCODING_ERROR = "文件编码无法识别"
MOJIBAKE_MARKERS = ("锟", "�", "脙", "脗", "悴", "ハ")


@dataclass(frozen=True)
class TextDecodeResult:
    text: str
    encoding: str
    used_replacement: bool = False


def safe_decode(text: bytes | str) -> str:
    if isinstance(text, bytes):
        result = decode_bytes_with_fallback(text)
        return clean_h3c_device_text(result.text)
    return clean_h3c_device_text(str(text or ""))


def decode_text_auto(data: bytes) -> str:
    result = decode_bytes_with_fallback(data, replace_on_failure=False)
    return result.text


def decode_bytes_with_fallback(
    data: bytes,
    *,
    encodings: Iterable[str] = TEXT_ENCODINGS,
    replace_on_failure: bool = True,
) -> TextDecodeResult:
    raw = bytes(data)
    for encoding in tuple(encodings):
        if encoding.lower().replace("_", "-") == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            continue
        try:
            return TextDecodeResult(clean_device_text(raw.decode(encoding)), encoding)
        except UnicodeDecodeError:
            continue
    if not replace_on_failure:
        raise ValueError(FILE_ENCODING_ERROR)
    return TextDecodeResult(clean_device_text(raw.decode("utf-8", errors="replace")), "utf-8-replace", True)


def read_text_auto(path: Path) -> str:
    return decode_text_auto(Path(path).read_bytes())


def read_text_with_fallback(path: Path) -> str:
    return read_text_with_encoding(path).text


def read_text_with_encoding(path: Path) -> TextDecodeResult:
    return decode_bytes_with_fallback(Path(path).read_bytes())


def clean_device_text(text: str) -> str:
    normalized = str(text or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    return fix_mojibake_text(normalized)


def clean_h3c_device_text(text: str) -> str:
    original = str(text or "")
    if not _looks_mojibake(original):
        return clean_device_text(original)
    candidates = [original]
    for encoding in H3C_DEVICE_ENCODINGS:
        try:
            candidates.append(original.encode(encoding, errors="ignore").decode("utf-8", errors="ignore"))
        except UnicodeError:
            continue
        try:
            candidates.append(original.encode("utf-8", errors="ignore").decode(encoding, errors="ignore"))
        except UnicodeError:
            continue
    candidates.append(fix_mojibake_text(original))
    best = min((candidate for candidate in candidates if candidate), key=_mojibake_score)
    return clean_device_text(best)


def fix_mojibake_text(text: str) -> str:
    original = str(text or "")
    if not _looks_mojibake(original):
        return original
    candidates = [original]
    for source_encoding, target_encoding in (
        ("latin1", "gbk"),
        ("gbk", "utf-8"),
        ("utf-8", "gbk"),
    ):
        try:
            candidate = original.encode(source_encoding, errors="ignore").decode(target_encoding, errors="ignore")
        except UnicodeError:
            continue
        if candidate:
            candidates.append(candidate)
    cleaned = "".join(char for char in original if char not in MOJIBAKE_MARKERS and char != "?")
    if cleaned:
        candidates.append(cleaned)
    return min(candidates, key=_mojibake_score)


def _looks_mojibake(text: str) -> bool:
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def _mojibake_score(text: str) -> tuple[int, int]:
    marker_count = sum(text.count(marker) for marker in MOJIBAKE_MARKERS) + text.count("?")
    return marker_count, -len(text.strip())
