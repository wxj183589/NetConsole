from pathlib import Path

import pytest

from netconsole.utils.text_encoding import (
    FILE_ENCODING_ERROR,
    Utf8IncrementalTextDecoder,
    decode_bytes_with_fallback,
    decode_external_text,
    decode_text_auto,
    read_text_with_encoding,
)


@pytest.mark.parametrize(
    ("encoding", "expected_encoding"),
    [
        ("utf-8-sig", "utf-8-sig"),
        ("utf-8", "utf-8"),
        ("gb18030", "gb18030"),
        ("gbk", "gb18030"),
    ],
)
def test_decode_bytes_with_fallback_preserves_chinese(encoding: str, expected_encoding: str) -> None:
    result = decode_bytes_with_fallback("H3C端口描述".encode(encoding))

    assert result.text == "H3C端口描述"
    assert result.encoding == expected_encoding
    assert result.used_replacement is False


def test_read_text_with_encoding_reports_selected_encoding(tmp_path: Path) -> None:
    path = tmp_path / "h3c.txt"
    path.write_bytes("轨旁AP日志".encode("gb18030"))

    result = read_text_with_encoding(path)

    assert result.text == "轨旁AP日志"
    assert result.encoding == "gb18030"


def test_decode_fallback_marks_utf8_replacement() -> None:
    result = decode_bytes_with_fallback(b"\x81")

    assert result.encoding == "utf-8-replace"
    assert result.used_replacement is True
    assert "�" in result.text
    with pytest.raises(ValueError, match=FILE_ENCODING_ERROR):
        decode_text_auto(b"\x81")


def test_incremental_utf8_decoder_preserves_split_chinese_code_point() -> None:
    decoder = Utf8IncrementalTextDecoder(source="worker_stdout")
    raw = "SSH 认证失败".encode("utf-8")
    split_at = raw.index("认".encode("utf-8")) + 1

    first = decoder.decode(raw[:split_at])
    second = decoder.decode(raw[split_at:], final=True)

    assert first.text + second.text == "SSH 认证失败"
    assert first.used_replacement is False
    assert second.used_replacement is False
    assert "�" not in first.text + second.text


def test_incremental_utf8_decoder_reports_truly_invalid_bytes() -> None:
    decoder = Utf8IncrementalTextDecoder(source="worker_stderr")

    result = decoder.decode(b"bad:\x81", final=True)

    assert result.used_replacement is True
    assert result.decode_warning
    assert result.source == "worker_stderr"


def test_decode_external_text_does_not_reencode_unicode_string() -> None:
    text = "宁波地铁1号线 �"

    result = decode_external_text(text, source="already_unicode")

    assert result.text == text
    assert result.encoding == "unicode"
