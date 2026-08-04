from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from netconsole.parsers.mesh_log_parser import normalize_mac as normalize_mesh_mac
from netconsole.repositories.mesh_mr_repository import (
    MeshIdentityRemapValidationError,
    MeshMrRepository,
)
from scripts.maintenance.remap_mesh_identity import _expected_projection


def _create_detail(
    tmp_path: Path,
    peers: list[str],
    *,
    rows_per_peer: int = 1,
) -> MeshMrRepository:
    repo = MeshMrRepository(tmp_path / "parsed" / "source.mesh.sqlite")
    with sqlite3.connect(repo.path) as connection:
        source_id = connection.execute(
            """
            INSERT INTO source_files (
                mr_id, original_path, archived_path, original_filename,
                archived_filename, sha256, file_size, imported_at,
                parser_version, parse_status
            ) VALUES ('synthetic', '', '', 'meshlog.log', 'meshlog.log',
                      'synthetic-sha', 0, '2026-08-04 00:00:00',
                      'synthetic', 'imported')
            """
        ).lastrowid
        sample_id = connection.execute(
            """
            INSERT INTO samples (
                source_file_id, radio, sample_time, sample_time_epoch_ms,
                timestamp_tag
            ) VALUES (?, 1, '2026-08-04 00:00:00.000', 0, '')
            """,
            (source_id,),
        ).lastrowid
        values: list[tuple[object, ...]] = []
        for peer_index, peer in enumerate(peers):
            for row_index in range(rows_per_peer):
                record_id = peer_index * rows_per_peer + row_index + 1
                link_state = "ACTIVE" if record_id % 2 else "STANDBY"
                values.append(
                    (
                        sample_id,
                        source_id,
                        record_id,
                        record_id,
                        record_id,
                        f"2026-08-04 00:00:{record_id % 60:02d}.000",
                        link_state,
                        peer,
                        peer,
                        40 + (record_id % 5),
                        35 + (record_id % 5),
                        record_id * 10,
                        record_id * 10 + 9,
                        f"fact-{record_id}",
                    )
                )
        connection.executemany(
            """
            INSERT INTO mesh_links (
                sample_id, source_file_id, source_file_order, record_seq,
                source_line_number, radio, sample_time, link_state_raw,
                link_state, peer_mac_raw, peer_mac_normalized,
                duration_text, local_rssi_db, peer_rssi_db,
                raw_line_start, raw_line_end, raw_offset_start, raw_offset_end,
                record_fingerprint
            ) VALUES (?, ?, 1, ?, ?, 1, ?, ?, ?, ?, ?, '0d 00h 00m 01s',
                      ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    value[0],
                    value[1],
                    value[2],
                    value[3],
                    value[5],
                    value[6],
                    value[6],
                    value[7],
                    value[8],
                    value[9],
                    value[10],
                    value[3],
                    value[3],
                    value[11],
                    value[12],
                    value[13],
                )
                for value in values
            ],
        )
        active_links = connection.execute(
            "SELECT id, sample_id, source_file_id, sample_time, peer_mac_raw, peer_mac_normalized "
            "FROM mesh_links WHERE link_state = 'ACTIVE' ORDER BY id"
        ).fetchall()
        connection.executemany(
            """
            INSERT INTO active_points (
                link_id, sample_id, source_file_id, sample_time, radio,
                peer_mac_raw, peer_mac_normalized
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            active_links,
        )
        connection.execute(
            """
            INSERT INTO switch_events (
                event_type, event_time, radio, details_json, source_file_id,
                source_line_number, raw_line_start, raw_line_end
            ) VALUES ('ACTIVE_SWITCH', '2026-08-04 00:00:01.000', 1, '{}', ?, 9, 9, 9)
            """,
            (source_id,),
        )
    return repo


def _mapping(
    peer: str,
    *,
    name: str = "AP-X_1906",
    ap_mac: str = "083b-e9ec-a2e0",
    radio_id: int = 2,
    status: str = "matched",
) -> dict[str, object]:
    return {
        "peer_mac_normalized": peer,
        "peer_ap_name": name if status == "matched" else "",
        "peer_ap_mac": ap_mac if status == "matched" else "",
        "peer_radio_id": radio_id if status == "matched" else None,
        "peer_radio_label": f"radio{radio_id}" if status == "matched" else "",
        "peer_radio_mac": peer,
        "peer_site": "20翠柏里站" if status == "matched" else "",
        "peer_section": "望春桥站-翠柏里站" if status == "matched" else "",
        "peer_location": "K12+300" if status == "matched" else "",
        "peer_direction": "下行" if status == "matched" else "",
        "match_rule": (
            f"h3c_physical_mac_to_r{radio_id}_exact_v1"
            if status == "matched"
            else "unresolved"
        ),
        "match_confidence": 95 if status == "matched" else 0,
        "identity_status": status,
        "identity_source": "ac_runtime" if status == "matched" else "",
        "identity_reason": (
            "exact_alias_not_found" if status == "unresolved" else ""
        ),
    }


@pytest.mark.parametrize(
    "mapping_peer",
    ["08:3b:e9:ec:a2:ff", "083b-e9ec-a2ff", "083be9eca2ff"],
)
def test_remap_normalizes_mapping_and_cache_keys(
    tmp_path: Path,
    mapping_peer: str,
) -> None:
    repo = _create_detail(tmp_path, ["083be9eca2ff"])

    result = repo.replace_peer_identity_mappings(
        [_mapping(mapping_peer)],
        identity_index_revision=7,
    )

    with sqlite3.connect(repo.path) as connection:
        mapping_key = connection.execute(
            "SELECT peer_mac_normalized FROM mesh_peer_mapping"
        ).fetchone()[0]
        cache_key = connection.execute(
            "SELECT peer_mac FROM mesh_peer_resolve_cache"
        ).fetchone()[0]
        link = connection.execute(
            "SELECT peer_ap_name, peer_identity_status FROM mesh_links"
        ).fetchone()
        active = connection.execute(
            "SELECT peer_ap_name, peer_site, peer_radio FROM active_points"
        ).fetchone()

    assert mapping_key == cache_key == "083be9eca2ff"
    assert link == ("AP-X_1906", "matched")
    assert active == ("AP-X_1906", "20翠柏里站", "radio2")
    assert result["validation_status"] == "passed"
    assert result["covered_peer_count"] == 1
    assert result["updated_link_row_count"] == 1
    assert result["updated_active_point_row_count"] == 1
    assert result["facts_unchanged"] is True


def test_remap_deduplicates_display_formats_and_skips_invalid_mac(tmp_path: Path) -> None:
    repo = _create_detail(tmp_path, ["083be9eca2ff"])
    result = repo.replace_peer_identity_mappings(
        [
            _mapping("08:3b:e9:ec:a2:ff"),
            _mapping("083b-e9ec-a2ff"),
            _mapping("083be9eca2ff"),
            _mapping("not-a-mac"),
            _mapping(""),
        ],
        identity_index_revision=7,
    )

    assert result["mapping_count"] == 1
    assert result["persisted_mapping_count"] == 1
    assert result["invalid_mapping_key_count"] == 0


def test_r1_r2_samples_and_all_identity_statuses_are_persisted(tmp_path: Path) -> None:
    peers = [
        "10b65e92beef",
        "083be9eca2ff",
        "001122334455",
        "001122334466",
    ]
    repo = _create_detail(tmp_path, peers)
    rows = [
        _mapping(
            "10b6-5e92-beef",
            name="AP-CLD_40",
            ap_mac="10b6-5e92-bee0",
            radio_id=1,
        ),
        _mapping("083b-e9ec-a2ff"),
        _mapping("00:11:22:33:44:55", status="unresolved"),
        _mapping("0011-2233-4466", status="ambiguous"),
    ]

    result = repo.replace_peer_identity_mappings(
        rows,
        identity_index_revision=11,
    )

    with sqlite3.connect(repo.path) as connection:
        links = connection.execute(
            """
            SELECT peer_mac_normalized, peer_ap_name, peer_ap_mac,
                   peer_radio_id, peer_match_rule, peer_identity_status
            FROM mesh_links ORDER BY id
            """
        ).fetchall()

    assert links[0] == (
        "10b65e92beef",
        "AP-CLD_40",
        "10:b6:5e:92:be:e0",
        1,
        "h3c_physical_mac_to_r1_exact_v1",
        "matched",
    )
    assert links[1] == (
        "083be9eca2ff",
        "AP-X_1906",
        "08:3b:e9:ec:a2:e0",
        2,
        "h3c_physical_mac_to_r2_exact_v1",
        "matched",
    )
    assert [row[-1] for row in links] == [
        "matched",
        "matched",
        "unresolved",
        "ambiguous",
    ]
    assert result["matched_mapping_count"] == 2
    assert result["unresolved_mapping_count"] == 1
    assert result["ambiguous_mapping_count"] == 1
    assert result["matched_link_row_count"] == 2
    assert result["unresolved_link_row_count"] == 1
    assert result["ambiguous_link_row_count"] == 1


def test_zero_persisted_match_rolls_back_every_identity_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _create_detail(tmp_path, ["083be9eca2ff"])
    repo.replace_peer_identity_mappings(
        [_mapping("083be9eca2ff", status="unresolved")],
        identity_index_revision=6,
    )
    monkeypatch.setattr(
        MeshMrRepository,
        "_update_mesh_link_identity_projection",
        staticmethod(lambda _conn: None),
    )

    with pytest.raises(
        MeshIdentityRemapValidationError,
        match="MESH_IDENTITY_REMAP_ZERO_PERSISTED_MATCH",
    ):
        repo.replace_peer_identity_mappings(
            [_mapping("08:3b:e9:ec:a2:ff")],
            identity_index_revision=7,
        )

    with sqlite3.connect(repo.path) as connection:
        mapping = connection.execute(
            "SELECT identity_status FROM mesh_peer_mapping"
        ).fetchone()[0]
        link = connection.execute(
            "SELECT peer_identity_status FROM mesh_links"
        ).fetchone()[0]
    assert mapping == link == "unresolved"


def test_remap_is_idempotent_and_preserves_all_mesh_facts(tmp_path: Path) -> None:
    repo = _create_detail(
        tmp_path,
        ["10b65e92beef", "083be9eca2ff"],
        rows_per_peer=3,
    )
    rows = [
        _mapping(
            "10b6-5e92-beef",
            name="AP-CLD_40",
            ap_mac="10b6-5e92-bee0",
            radio_id=1,
        ),
        _mapping("083b-e9ec-a2ff"),
    ]

    first = repo.replace_peer_identity_mappings(rows, identity_index_revision=9)
    second = repo.replace_peer_identity_mappings(rows, identity_index_revision=9)

    assert first["fact_fingerprint_before"] == first["fact_fingerprint_after"]
    assert second["fact_fingerprint_before"] == second["fact_fingerprint_after"]
    assert first["fact_fingerprint_after"] == second["fact_fingerprint_after"]
    assert first["link_row_count"] == second["link_row_count"] == 6
    assert first["active_point_row_count"] == second["active_point_row_count"] == 3
    assert first["switch_event_row_count"] == second["switch_event_row_count"] == 1
    assert first["after"] == second["after"] == {
        "matched": 6,
        "unresolved": 0,
        "ambiguous": 0,
    }


def test_parser_keeps_display_format_while_repository_keys_are_compact() -> None:
    assert normalize_mesh_mac("08:3b:e9:ec:a2:ff") == "08:3b:e9:ec:a2:ff"
    assert normalize_mesh_mac("083b-e9ec-a2ff") == "08:3b:e9:ec:a2:ff"
    assert normalize_mesh_mac("083b.e9ec.a2ff") == "08:3b:e9:ec:a2:ff"


def test_dry_run_accepts_historical_detail_without_peer_section(
    tmp_path: Path,
) -> None:
    repo = _create_detail(tmp_path, ["083be9eca2ff"])
    legacy_path = repo.path.with_name("legacy.mesh.sqlite")
    with sqlite3.connect(repo.path) as source, sqlite3.connect(legacy_path) as target:
        source.backup(target)
    with sqlite3.connect(legacy_path) as connection:
        connection.execute("ALTER TABLE mesh_links DROP COLUMN peer_section")

    expected, changed = _expected_projection(
        legacy_path,
        [_mapping("08:3b:e9:ec:a2:ff")],
    )

    assert expected == {"matched": 1, "unresolved": 0, "ambiguous": 0}
    assert changed == 1
    with sqlite3.connect(legacy_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(mesh_links)")
        }
    assert "peer_section" not in columns


def test_remap_uses_bounded_set_operations_for_fifty_thousand_links(
    tmp_path: Path,
) -> None:
    peers = [f"02000000{index:04x}" for index in range(200)]
    repo = _create_detail(tmp_path, peers, rows_per_peer=250)
    mappings = [
        _mapping(peer, name=f"AP-{index:03d}")
        for index, peer in enumerate(peers)
    ]

    result = repo.replace_peer_identity_mappings(
        mappings,
        identity_index_revision=12,
    )

    assert result["mapping_count"] == 200
    assert result["distinct_link_peer_count"] == 200
    assert result["updated_link_row_count"] == 50_000
    assert result["matched_link_row_count"] == 50_000
    assert result["facts_unchanged"] is True
