from netconsole.utils.mileage import format_track_mileage, mileage_search_tokens, mileage_storage_text, parse_mileage_to_meters, parse_track_mileage


def test_format_track_mileage_uses_line_prefixes_and_k_fallback():
    assert format_track_mileage(0, line_side="左线") == "ZDK0+000"
    assert format_track_mileage(35, line_side="右线") == "YDK0+035"
    assert format_track_mileage(168, line_side="出段线") == "CDK0+168"
    assert format_track_mileage(12345, line_side="入段线") == "RDK12+345"
    assert format_track_mileage(1020) == "K1+020"


def test_parse_track_mileage_accepts_prefixed_and_plain_values():
    assert parse_track_mileage("ZDK1+020").meters == 1020
    assert parse_track_mileage("zdk1+20").display == "ZDK1+020"
    assert parse_track_mileage("YDK01+020").display == "YDK1+020"
    assert parse_track_mileage("CDK1+170").meters == 1170
    assert parse_track_mileage("RDK12+345").prefix == "RDK"
    assert parse_mileage_to_meters("K0+035") == 35
    assert mileage_storage_text("YDK0+035") == "35"


def test_mileage_search_tokens_include_equivalent_prefix_forms():
    tokens = mileage_search_tokens(35, line_side="左线")

    assert "35" in tokens
    assert "K0+035" in tokens
    assert "ZDK0+035" in tokens
    assert "YDK0+035" in tokens
