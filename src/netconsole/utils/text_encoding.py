from __future__ import annotations

import codecs
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
    had_bom: bool = False
    decode_warning: str = ""
    source: str = ""

    @property
    def selected_encoding(self) -> str:
        return self.encoding

    @property
    def replacement_used(self) -> bool:
        return self.used_replacement


class Utf8IncrementalTextDecoder:
    """Decode one internal UTF-8 byte stream without corrupting split code points."""

    def __init__(self, *, source: str, errors: str = "replace") -> None:
        self.source = str(source or "internal_stream")
        if errors not in {"strict", "replace"}:
            raise ValueError("内部 UTF-8 解码器只支持 strict 或 replace")
        self.errors = errors
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors=errors)

    def decode(self, data: bytes, *, final: bool = False) -> TextDecodeResult:
        text = self._decoder.decode(bytes(data), final=final)
        replaced = "\ufffd" in text
        return TextDecodeResult(
            text=text,
            encoding="utf-8",
            used_replacement=replaced,
            decode_warning=(
                "内部 UTF-8 字节流包含非法序列，已执行受控替代。"
                if replaced
                else ""
            ),
            source=self.source,
        )


def safe_decode(text: bytes | str) -> str:
    if isinstance(text, bytes):
        return decode_external_text(text, source="device_output").text
    return clean_h3c_device_text(str(text or ""))


def decode_external_text(
    value: bytes | str,
    *,
    source: str,
    encoding_hint: str | None = None,
) -> TextDecodeResult:
    if isinstance(value, str):
        return TextDecodeResult(
            clean_device_text(value),
            "unicode",
            source=str(source or ""),
        )
    candidates: list[str] = []
    if encoding_hint:
        candidates.append(str(encoding_hint))
    candidates.extend(("utf-8-sig", "utf-8", "gb18030", "cp936"))
    return decode_bytes_with_fallback(
        value,
        encodings=tuple(dict.fromkeys(candidates)),
        source=source,
    )


def decode_text_auto(data: bytes) -> str:
    result = decode_bytes_with_fallback(data, replace_on_failure=False)
    return result.text


def decode_bytes_with_fallback(
    data: bytes,
    *,
    encodings: Iterable[str] = TEXT_ENCODINGS,
    replace_on_failure: bool = True,
    source: str = "external_bytes",
) -> TextDecodeResult:
    raw = bytes(data)
    for encoding in tuple(encodings):
        if encoding.lower().replace("_", "-") == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            continue
        try:
            had_bom = encoding.lower().replace("_", "-") == "utf-8-sig"
            return TextDecodeResult(
                clean_device_text(raw.decode(encoding)),
                encoding,
                had_bom=had_bom,
                source=source,
            )
        except UnicodeDecodeError:
            continue
    if not replace_on_failure:
        raise ValueError(FILE_ENCODING_ERROR)
    return TextDecodeResult(
        clean_device_text(raw.decode("utf-8", errors="replace")),
        "utf-8-replace",
        True,
        decode_warning="所有候选编码均严格解码失败，已执行受控替代。",
        source=source,
    )


def read_text_auto(path: Path) -> str:
    return decode_text_auto(Path(path).read_bytes())


def read_text_with_fallback(path: Path) -> str:
    return read_text_with_encoding(path).text


def read_text_with_encoding(path: Path) -> TextDecodeResult:
    return decode_bytes_with_fallback(Path(path).read_bytes())


def clean_device_text(text: str) -> str:
    return str(text or "").replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")


def clean_h3c_device_text(text: str) -> str:
    # 输入已是 Unicode 时不再猜测式 encode/decode，避免二次转码造成不可逆损坏。
    return clean_device_text(text)


def fix_mojibake_text(text: str) -> str:
    # 历史损坏的 str 缺少原始字节，不能安全猜测恢复。
    return str(text or "")


def _looks_mojibake(text: str) -> bool:
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def _mojibake_score(text: str) -> tuple[int, int]:
    marker_count = sum(text.count(marker) for marker in MOJIBAKE_MARKERS) + text.count("?")
    return marker_count, -len(text.strip())
