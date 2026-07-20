from __future__ import annotations

import pytest

from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryError, MeshAnalysisQueryService
from tests.mesh_analysis_test_support import EmptyBaseQuery, create_mesh_analysis_fixture


def test_artifact_id_resolves_only_enumerated_session_files(tmp_path) -> None:
    paths, session_id, _detail, raw, report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    artifacts = service.list_report_artifacts("demo", session_id)

    resolved = {service.open_artifact("demo", session_id, item.artifact_id)[0] for item in artifacts}
    assert resolved == {raw.resolve(), report.resolve()}
    with pytest.raises(MeshAnalysisQueryError):
        service.open_artifact("demo", session_id, "..%2F..%2Fsecret")
    with pytest.raises(MeshAnalysisQueryError):
        service.open_artifact("demo", session_id, "f" * 24)


def test_raw_tail_is_controlled_by_source_id(tmp_path) -> None:
    paths, session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    service = MeshAnalysisQueryService(paths, base_query=EmptyBaseQuery())  # type: ignore[arg-type]
    source = service.get_raw_source_summary("demo", session_id)[0]

    tail = service.read_raw_tail("demo", session_id, source.source_id)

    assert tail.available is True
    assert tail.lines[-1] == "mesh sample"
    with pytest.raises(MeshAnalysisQueryError):
        service.read_raw_tail("demo", session_id, "invalid")
