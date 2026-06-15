from __future__ import annotations

from pathlib import Path


TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "gb2312")
H3C_DEVICE_ENCODINGS = ("gb2312", "gbk", "gb18030", "utf-8", "utf-8-sig")
FILE_ENCODING_ERROR = "文件编码无法识别"
MOJIBAKE_MARKERS = ("锟", "�", "脙", "脗", "悴", "ハ")


def decode_text_auto(data: bytes) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return clean_device_text(bytes(data).decode(encoding))
        except UnicodeDecodeError:
            continue
    raise ValueError(FILE_ENCODING_ERROR)


def read_text_auto(path: Path) -> str:
    return decode_text_auto(Path(path).read_bytes())


def read_text_with_fallback(path: Path) -> str:
    return read_text_auto(path)


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
